"""Read a circuit netlist from a vision endpoint; preserve explicit physical conductor endpoints."""
import base64
import io
import json
import os
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from tools.model_client import ModelClient, ProviderError
from flask import Blueprint, jsonify, request
from jsonschema import Draft202012Validator
from PIL import Image, ImageOps, UnidentifiedImageError

bp = Blueprint("vision_panel", __name__)
SKILL = Path(__file__).with_name("skills") / "circuit-netlist"
SCHEMA = json.loads((SKILL / "netlist.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
RULE_CONTACT_REGIONS = json.loads((Path(__file__).resolve().parents[1] / "templates/wiring_panel/contacts.json").read_text(encoding="utf-8"))
BOARD_PINS = {(name.replace("-", ":", 1) if "-" in name else "INV:" + name) for region in RULE_CONTACT_REGIONS for name in region["contacts"]}
TERMINAL_MAPPING = json.loads(Path(__file__).with_name("terminal_mapping.json").read_text(encoding="utf-8"))
MAX_BYTES = 8 * 1024 * 1024


def validate(doc):
    error = next(VALIDATOR.iter_errors(doc), None)
    if error:
        path = ".".join(str(item) for item in error.absolute_path) or "根节点"
        raise ValueError(f"网表字段 {path} 不符合结构规范")
    known, ids = set(), set()
    for part in doc["components"]:
        if part["id"] in ids:
            raise ValueError("元件位号重复")
        ids.add(part["id"])
        known.update(f"{part['id']}:{pin}" for pin in part["pins"])
    if sum(map(len, doc["nets"])) > 512:
        raise ValueError("单图最多解析 512 个已连接端子，请按电路分图")
    owners = {}
    errors = []
    for number, net in enumerate(doc["nets"], 1):
        for pin in net:
            if pin not in known:
                errors.append(f"N{number} 引用了元件表未声明的端子 {pin}")
            if pin in owners:
                errors.append(f"{pin} 同时出现于 N{owners[pin]} 和 N{number}")
            owners[pin] = number
    if errors:
        raise ValueError("；".join(errors))
    if not doc["uncertainties"] and not doc["nets"]:
        raise ValueError("图片中没有可确认的接线网络")
    return doc


def strict_panel(doc, confirm=False):
    validate(doc)
    pins = {pin: i for i, net in enumerate(doc["nets"], 1) for pin in net}
    neighbors = {pin: set() for pin in pins}
    wires = []
    for wire in doc["wires"]:
        a, b = wire["from"], wire["to"]
        if a == b or a not in pins or pins[a] != pins.get(b):
            raise ValueError(f"导线 {a} ↔ {b} 的端子无效或跨越不同网络")
        neighbors[a].add(b)
        neighbors[b].add(a)
        wires.append({"from": a, "to": b, "net": f"N{pins[a]}"})
    issues = list(doc["uncertainties"])
    for net in doc["nets"]:
        reached = set()
        pending = [net[0]]
        while pending:
            pin = pending.pop()
            if pin not in reached:
                reached.add(pin)
                pending.extend(neighbors[pin] - reached)
        if len(reached) != len(net):
            issues.append("请指定网络内逐根导线的两个端子：" + "、".join(net))
    if confirm and (issues or not wires):
        raise ValueError("尚不能确认标准：" + "；".join(issues or ["缺少导线"]))
    return {"version": "circuit-panel/2", "mode": "exact-wire-endpoints",
            "status": "confirmed" if confirm else "needs_review",
            "netlist": doc, "wires": wires, "review_items": issues}


def diagram(doc):
    validate(doc)
    excluded = sorted({pin for net in doc["nets"] for pin in net if pin not in BOARD_PINS})
    strict_panel(doc)
    nets = [[pin for pin in net if pin in BOARD_PINS] for net in doc["nets"]]
    parts = []
    for part in doc["components"]:
        pins = [pin for pin in part["pins"] if f"{part['id']}:{pin}" in BOARD_PINS]
        if pins:
            parts.append(dict(part, pins=pins))
    doc = dict(doc, components=parts, nets=[net for net in nets if len(net)>1],
               wires=[wire for wire in doc["wires"] if wire["from"] in BOARD_PINS and wire["to"] in BOARD_PINS])
    if not doc["wires"]:
        raise ValueError("没有辨认出两端均在模拟配盘上的独立导线")
    panel = strict_panel(doc)
    return {"version": "circuit-diagram/1", "netlist": doc, "wires": panel["wires"],
            "excluded_count": len(excluded)}


def from_physical_pairs(result):
    """Construct connected components from physical edges; never infer an edge from a net."""
    adjacency = {}
    parts = {}
    wires = []
    seen = set()
    for pair in result["wires"]:
        a, b = pair["from"], pair["to"]
        if a not in BOARD_PINS or b not in BOARD_PINS or a == b:
            raise ValueError(f"无效配盘导线：{a} ↔ {b}")
        edge = frozenset((a, b))
        if edge in seen:
            continue
        seen.add(edge)
        wires.append({"from": a, "to": b})
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
        for ref in (a, b):
            component, pin = ref.split(":", 1)
            parts.setdefault(component, {})[pin] = None
    nets = []
    visited = set()
    for pin in adjacency:
        if pin in visited:
            continue
        net, stack = [], [pin]
        while stack:
            current = stack.pop()
            if current not in visited:
                visited.add(current)
                net.append(current)
                stack.extend(adjacency[current])
        nets.append(net)
    title = result.get("title")
    if not isinstance(title, str):
        raise ValueError("方案标题应为文本")
    title = title.strip() or "电路接线方案"
    return {"title": title[:100], "explanation": title[:3000], "uncertainties": [],
            "components": [{"id": name, "label": name, "pins": list(pins)} for name, pins in parts.items()],
            "nets": nets, "wires": wires}


@bp.post("/api/vision-panel/diagram")
def render_diagram():
    try:
        return jsonify(diagram(request.get_json()["netlist"]))
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


def compare_wires(reference, submitted):
    """Compare physical wire multisets; drawing coordinates and direction have no weight."""
    def pairs(wires):
        return Counter(tuple(sorted((wire["from"], wire["to"]))) for wire in wires)
    expected, actual = pairs(reference), pairs(submitted)
    return {"matches": actual == expected, "missing": list((expected-actual).elements()),
            "extra": list((actual-expected).elements())}


def image_content(file):
    raw = file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("图片请小于 8 MiB")
    try:
        with Image.open(io.BytesIO(raw)) as src:
            if src.format not in {"JPEG", "PNG", "WEBP"} or src.width * src.height > 16_000_000:
                raise ValueError("请使用不超过 1600 万像素的 PNG、JPEG 或 WebP 图片")
            img = ImageOps.exif_transpose(src).convert("RGBA")
            flat = Image.new("RGB", img.size, "white")
            flat.paste(img, mask=img.getchannel("A"))
            flat.thumbnail((3072, 3072))
            out = io.BytesIO()
            flat.save(out, format="PNG")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("图片无法解码，请重新导出") from exc
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def analysis_pages(result, *, physical_pairs):
    candidates = result.get("solutions", [result])
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("缺少接线方案")
    panels = []
    seen = set()
    for candidate in candidates:
        doc = from_physical_pairs(candidate) if physical_pairs else candidate
        panel = diagram(doc)
        signature = tuple(sorted(tuple(sorted((w["from"], w["to"]))) for w in panel["wires"]))
        if signature not in seen:
            seen.add(signature)
            panels.append(panel)
    return {"netlist": panels[0]["netlist"], "panel": panels[0], "panels": panels}


def resolve_endpoint(ref, devices):
    """Apply panel conventions only within the original device family."""
    import re
    device, sep, role = ref.upper().strip().partition(":")
    if not sep:
        return None
    if device in {"KM", "SB", "FR", "QS"}:
        if any(re.fullmatch(device + r"\d+", name) for name in devices):
            return None
        device += "1"
    family = device.rstrip("0123456789")
    roles = TERMINAL_MAPPING["families"].get(family, {})
    overrides = TERMINAL_MAPPING["devices"].get(device, {})
    pole = re.fullmatch(r"P([1-4])\.(IN|OUT)", role)
    if pole and family in {"FU", "QS", "KM", "FR"}:
        n = int(pole[1])
        incoming = pole[2] == "IN"
        role = str(2*n - int(incoming))
        if family in {"KM", "FR"}:
            role += "/" + ("L" if incoming else "T") + str(n)
    printed = device + ":" + role
    if printed in BOARD_PINS:
        return printed
    terminal = overrides.get(role, roles.get(role))
    if not isinstance(terminal, str):
        return None
    pin = device + ":" + terminal
    return pin if pin in BOARD_PINS else None


def map_observations(obs, installation=None):
    nets = obs["nets"]
    if not isinstance(nets, list) or (not nets and obs.get("kind") != "installation"):
        raise ValueError("未读到原图网络")
    devices = set()
    for net in nets:
        ends = net["ends"]
        if not isinstance(ends, list) or not all(isinstance(ref, str) for ref in ends):
            raise ValueError("原图端点格式错误")
        devices.update(ref.partition(":")[0].strip().upper() for ref in ends)
    mapped = []
    for net in nets:
        ends = list(dict.fromkeys(net["ends"]))
        pins = [resolve_endpoint(ref, devices) for ref in ends]
        mapped.append(dict(line=net["line"], ends=ends, pins=pins))
    counts = Counter(pin for net in mapped for pin in set(net["pins"]) if pin)
    lines = Counter(net["line"] for net in mapped)
    wires = []
    for net in mapped:
        pins = net["pins"]
        # Never shrink a multi-terminal net by discarding unknown endpoints.
        if (len(pins) == 2 and all(pins) and pins[0] != pins[1]
                and all(counts[p] == 1 for p in pins) and lines[net["line"]] == 1):
            wires.append({"from": pins[0], "to": pins[1]})
    evidence = []
    if installation is not None:
        wires = []
        source_devices = {str(w.get(side, "")).partition(":")[0].upper()
                          for w in installation.get("edges", []) for side in ("from", "to")}
        seen = set()
        for edge in installation.get("edges", []):
            refs = [edge.get(k) for k in ("from", "to")]
            boxes = edge.get("boxes")
            if not all(isinstance(ref, str) for ref in refs) or not valid_boxes(boxes):
                continue
            if not isinstance(edge.get("basis"), str) or not edge["basis"].strip():
                continue
            pins = [resolve_endpoint(ref, source_devices) for ref in refs]
            if not all(pins) or pins[0] == pins[1]:
                continue
            if obs.get("kind") != "installation" and not any(
                all(p in net["pins"] and counts[p] == 1 for p in pins) and lines[net["line"]] == 1
                for net in mapped
            ):
                continue
            signature = frozenset(pins)
            if signature in seen:
                continue
            seen.add(signature)
            wires.append(dict(zip(("from", "to"), pins)))
            evidence.append({"pins":pins, "boxes":boxes, "basis":edge["basis"], "source":"installation"})
    else:
        for wire in wires:
            net = next(n for n in mapped if wire["from"] in n["pins"])
            raw = next(n for n in nets if n["line"] == net["line"])
            if valid_boxes(raw.get("boxes")):
                evidence.append({"pins":[wire["from"],wire["to"]], "boxes":raw["boxes"],
                                 "basis":"双端网络 " + str(net["line"]), "source":"schematic"})
    title = obs["title"]
    doc = from_physical_pairs({"title": title, "wires": wires})
    if wires:
        panel = diagram(doc)
    else:
        panel = {"version":"circuit-diagram/1", "netlist":doc, "wires":[], "excluded_count":0}
    doc = panel["netlist"]
    doc["uncertainties"] = [f"识别 {len(mapped)} 个网络，导出 {len(wires)} 根连线。"]
    panel["evidence"] = evidence
    result = {"netlist":doc, "panel":panel, "panels":[panel], "observations":mapped}
    if installation is None:
        generated = []
        for net in mapped:
            pins = net["pins"]
            if (len(pins) > 2 and all(pins) and len(set(pins)) == len(pins)
                    and lines[net["line"]] == 1 and all(counts[p] == 1 for p in pins)):
                generated.extend({"from":a,"to":b} for a,b in zip(pins,pins[1:]))
        if generated:
            proposal = diagram(from_physical_pairs({"title":doc["title"][:88] + "（等价配盘）",
                                                    "wires":wires + generated}))
            proposal["evidence"] = list(evidence) + [
                {"pins":[w["from"],w["to"]],"basis":"同网等价跨接，由程序分配落点","boxes":[]}
                for w in generated]
            proposal["netlist"]["uncertainties"] = [f"含 {len(generated)} 根程序分配的等价跨接，请核对接线容量。"]
            result["equivalent"] = proposal
    return result


def valid_boxes(boxes):
    return isinstance(boxes, list) and len(boxes) == 2 and all(valid_box(box) for box in boxes)


def valid_box(box):
    return (isinstance(box, list) and len(box) == 4 and
            all(type(v) in (int, float) and 0 <= v <= 1000 for v in box) and
            box[0] < box[2] and box[1] < box[3])


def read_schematic(client, model, image=None, installation=None):
    skill = (SKILL.parent / "circuit-wire-pairs" / "SKILL.md").read_text(encoding="utf-8")

    def read(prompt, images):
        content = [{"type":"text", "text":prompt}]
        content.extend({"type":"image_url","image_url":{"url":url}} for url in images)
        payload = {"model":model, "temperature":0, "max_tokens":8000,
                   "response_format":{"type":"json_object"},
                   "messages":[{"role":"system","content":skill},{"role":"user","content":content}]}
        return json.loads(client.complete(payload, timeout=600))

    obs = None
    if image:
        obs = read("读取原理图，返回 title、nets。每个双端网络附 boxes，按 ends 顺序标记端点位置，"
                   "以画面左上为原点归一到 0..1000 的 [左,上,右,下]。"
                   "若有局部无法分辨，给该网络添加 review_box 包含疑点和邻近标注。", [image])
        # One bounded reread per uncertain region; preserve original line identity.
        uncertain = [n for n in obs["nets"] if valid_box(n.get("review_box"))][:3]
        if uncertain:
            with Image.open(io.BytesIO(base64.b64decode(image.split(",",1)[1]))) as source:
                for net in uncertain:
                    x,y,r,b = net["review_box"]
                    crop = source.crop((int(x*source.width/1000), int(y*source.height/1000),
                                        min(source.width,int(r*source.width/1000)+1),
                                        min(source.height,int(b*source.height/1000)+1)))
                    buf = io.BytesIO()
                    crop.save(buf,format="PNG")
                    inset = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
                    correction = read("第一张为原图，第二张为疑点局部。只复核网络 " +
                                      str(net["line"]) + "，返回 {line,ends}；无法确定返回空 ends。", [image,inset])
                    ends = correction.get("ends")
                    if (str(correction.get("line")) == str(net["line"]) and isinstance(ends,list)
                            and len(ends)>=2 and all(isinstance(e,str) for e in ends)):
                        if ends != net["ends"]:
                            net.pop("boxes",None)
                        net["ends"] = ends
                    else:
                        net["ends"].append("unknown:局部未确认")
        obs["kind"] = "schematic"
    physical = None
    if installation:
        physical = read("当前为实体施工接线图。逐根读取有明确连线或双端对应标记的物理导线。"
                        "返回 {title,edges:[{from,to,basis,boxes}]}，from/to 使用原位号:端点角色；"
                        "basis写出线号及双方的对端标记或明确可追踪的直连证据，不能仅凭同线号或同网枚举。"
                        "boxes 按 from,to 顺序给两端所在位置，各为0..1000的[左,上,右,下]。"
                        "经过XT分段保留，不能跨过中间端子。", [installation])
        if not isinstance(physical.get("edges"),list):
            raise ValueError("施工图缺少逐线证据表")
    if obs is None:
        obs = {"kind":"installation", "title":physical["title"], "nets":[]}
    return map_observations(obs, physical)


BAILIAN_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_VISION_MODEL = "qwen4-max"


def vision_client(base):
    key = os.getenv("CIRCUIT_VLM_API_KEY")
    filename = os.getenv("CIRCUIT_VLM_API_KEY_FILE")
    try:
        if not key and filename:
            key = Path(filename).read_text(encoding="utf-8").strip()
        elif not key and base.rstrip("/") == BAILIAN_BASE:
            key = os.getenv("DASHSCOPE_API_KEY")
            if not key and os.name == "nt":
                encrypted = Path(os.environ["LOCALAPPDATA"]) / "Circuit-Board/bailian-beijing.dpapi"
                if encrypted.is_file():
                    import win32crypt
                    blob = bytes.fromhex(encrypted.read_text(encoding="utf-8-sig").strip())
                    key = win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1].decode("utf-16-le")
            if not key:
                raise ProviderError("请先配置百炼北京地域 API Key。")
    except (OSError, ValueError, ImportError) as exc:
        raise ProviderError("无法读取本机视觉服务凭据。") from exc
    return ModelClient(base, key, os.getenv("CIRCUIT_VLM_PROTOCOL", "auto"))


@bp.post("/api/vision-panel/analyze")
def analyze():
    base = os.getenv("CIRCUIT_VLM_BASE_URL", BAILIAN_BASE).rstrip("/")
    if not base:
        return jsonify(error="尚未配置视觉服务，请设置 CIRCUIT_VLM_BASE_URL 后重启教师端"), 503
    if urlsplit(base).scheme not in ("https", "http"):
        return jsonify(error="视觉服务地址需使用 HTTP 或 HTTPS"), 503
    try:
        request.max_content_length = 2 * MAX_BYTES + 128 * 1024
        if not any(k in request.files for k in ("image","installation")):
            raise ValueError("请选择一张电路图")
        data = image_content(request.files["image"]) if "image" in request.files else None
        installation = image_content(request.files["installation"]) if "installation" in request.files else None
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        client = vision_client(base)
        return jsonify(read_schematic(client, os.getenv("CIRCUIT_VLM_MODEL", DEFAULT_VISION_MODEL), data, installation))
    except ProviderError as exc:
        return jsonify(error=str(exc)), 502
    except (KeyError, IndexError, AttributeError, TypeError, ValueError) as exc:
        message = str(exc) if type(exc) is ValueError else "模型输出不是有效的网表 JSON"
        return jsonify(error=message), 422


@bp.post("/api/vision-panel/review")
def review():
    args = request.get_json()
    if not isinstance(args, dict) or "netlist" not in args:
        return jsonify(error="缺少接线表"), 400
    try:
        return jsonify(strict_panel(args["netlist"], confirm=args.get("confirm") is True))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@bp.post("/api/vision-panel/compare")
def compare():
    """Read-only comparison. The caller supplies a teacher-confirmed export."""
    args = request.get_json()
    if not isinstance(args, dict):
        return jsonify(error="缺少判线数据"), 400
    standard = args.get("standard")
    if (not isinstance(standard, dict) or standard.get("status") != "confirmed"
            or standard.get("version") != "circuit-panel/2"):
        return jsonify(error="需要教师已确认的逐线标准"), 400
    try:
        checked = strict_panel(standard["netlist"], confirm=True)
        if checked["wires"] != standard.get("wires"):
            raise ValueError("标准导线表与网表不一致")
        actual = args["wires"]
        if not isinstance(actual, list) or len(actual) > 4096 or any(
                not isinstance(w, dict) or not all(isinstance(w.get(k), str) for k in ("from", "to"))
                for w in actual):
            raise ValueError("待核对导线缺少端子对")
        return jsonify(compare_wires(checked["wires"], actual))
    except (ValueError, KeyError) as exc:
        return jsonify(error=str(exc)), 400
