import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests
from itsdangerous import BadData, URLSafeSerializer, URLSafeTimedSerializer
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from requests.adapters import HTTPAdapter, Retry

from global_config import Global_Config
from script.serial_tools import STM32Tool, serialized_capture
from script.wiring_recorder import WiringRecorder
from script.exam_exit import ExamExitQueue


app = Flask(__name__)

CONFIG_PATH = Path(os.getenv("LOCAL_GATEWAY_CONFIG", Path(__file__).with_name("local_gateway_config.json")))


def load_local_config() -> Dict[str, Any]:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] 读取本地网关配置失败 {CONFIG_PATH}: {exc}")
    return {}


LOCAL_CONFIG = load_local_config()


def config_value(key: str, default: Any = None, env_key: Optional[str] = None) -> Any:
    env_name = env_key or key.upper()
    env_value = os.getenv(env_name)
    if env_value is not None:
        return env_value
    return LOCAL_CONFIG.get(key, default)


DEFAULT_ALLOWED_ORIGINS = "*"
cors_origins = [
    origin.strip()
    for origin in str(config_value("cors_origins", DEFAULT_ALLOWED_ORIGINS, "LOCAL_GATEWAY_CORS_ORIGINS")).split(",")
    if origin.strip()
]
CORS(
    app,
    resources={r"/*": {"origins": cors_origins or "*"}},
    supports_credentials=False,
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

SERVER_BASE = str(
    config_value(
        "server_base",
        os.getenv("AUTH_SERVICE_BASE", "http://127.0.0.1:7001"),
        "SERVER_BASE",
    )
).rstrip("/")
REQUEST_TIMEOUT = float(config_value("request_timeout", "10", "REQUEST_TIMEOUT"))

STM_PORT = config_value("stm_port", "COM4", "STM_PORT")
STM_BAUD = int(config_value("stm_baud", "38400", "STM_BAUD"))
STM_TIMEOUT = float(config_value("stm_timeout", "3", "STM_TIMEOUT"))
configured_rule_path = Path(
    config_value(
        "local_rule_path",
        str(Path(Global_Config.rule_path) / "current_rule.json"),
        "LOCAL_RULE_PATH",
    )
)
LOCAL_RULE_PATH = (
    configured_rule_path
    if configured_rule_path.is_absolute()
    else Path(__file__).resolve().parent / configured_rule_path
)

http = requests.Session()
http_retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504])
http.mount("http://", HTTPAdapter(max_retries=http_retries))
http.mount("https://", HTTPAdapter(max_retries=http_retries))

detector = None
detection_thread = None
detection_started_at: Optional[str] = None
detection_module = None

runtime_context: Dict[str, Any] = {
    "student_no": config_value("student_no", "", "STUDENT_NO"),
    "student_name": config_value("student_name", "", "STUDENT_NAME"),
    "test_id": config_value("test_id", "", "TEST_ID"),
    "test_name": config_value("test_name", "", "TEST_NAME"),
    "rule_filename": config_value("rule_filename", "", "RULE_FILENAME"),
    "rule_file": config_value("rule_file", "", "RULE_FILE"),
    "session_id": "",
    "server_base": SERVER_BASE,
}
last_report_result: Dict[str, Any] = {}
state_lock = threading.Lock()
active_session_id: Optional[str] = None
session_states: Dict[str, Dict[str, Any]] = {}
EMPTY_WIRING_RESULT: Dict[str, Any] = {"pairs": [], "connected": []}
recording_store = None
recording_store_lock = threading.Lock()
lifecycle_lock = threading.RLock()
active_recording_id: Optional[str] = None
recording_error: Optional[str] = None


def get_recording_store() -> WiringRecorder:
    global recording_store
    with recording_store_lock:
        if recording_store is None:
            path = Path(config_value("recordings_db", "data/recordings/wiring_history.sqlite3",
                                     "WIRING_RECORDINGS_DB"))
            if not path.is_absolute():
                path = Path(__file__).resolve().parent / path
            recording_store = WiringRecorder(path, recover=True)
        return recording_store


exit_queue = None
exit_queue_lock = threading.Lock()


def get_exit_queue():
    global exit_queue
    with exit_queue_lock:
        if exit_queue is None:
            exit_queue = ExamExitQueue(get_recording_store(), submit_after_exit)
            threading.Thread(target=exit_queue.run, daemon=True, name="exam-exit-submit").start()
        return exit_queue


@app.get("/api/exam/page/<token>/watch")
def watch_exam_page(token):
    queue = get_exit_queue()
    with lifecycle_lock:
        if not queue.state(token):
            return jsonify(success=False, message="未找到本次检测"), 404

    def stream():
        with queue.connected(token):
            while True:
                current = queue.state(token)
                if not current or current["state"] != "armed":
                    yield "event: submission\ndata: " + json.dumps(current) + "\n\n"
                    return
                yield ": connected\n\n"
                time.sleep(2)
    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/exam/page/<token>/leave")
def leave_exam_page(token):
    with lifecycle_lock:
        get_exit_queue().leave(token)
    return "", 204


@app.post("/api/exam/page/<token>/release")
def release_exam_page(token):
    if not get_exit_queue().release(token):
        return jsonify(success=False, message="网关已接手交卷"), 409
    return "", 204


def record_capture(recording_id: str, named_result: Dict[str, Any],
                   score_result: Dict[str, Any]) -> None:
    global recording_error
    try:
        get_recording_store().append_snapshot(
            recording_id, named_result.get("pairs", []), score_result.get("total_score", 0))
    except Exception as exc:
        recording_error = str(exc)
        raise


def begin_recording(scoring: Dict[str, Any]) -> str:
    from script.deal_StmResult import load_labels

    metadata = compact_dict(runtime_context.copy())
    metadata["rule_snapshot"] = json.loads(Path(Global_Config.test_rule).read_text(encoding="utf-8"))
    metadata["terminal_labels"] = load_labels(Global_Config.label_csv)
    return get_recording_store().begin(
        metadata, scoring["named_result"].get("pairs", []),
        scoring["score_result"].get("total_score", 0))


def serialized_lifecycle(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with lifecycle_lock:
            return function(*args, **kwargs)
    return wrapped



def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def compact_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, "")}


def normalize_wired_status(status: Any) -> str:
    value = str(status or "").strip().lower()
    status_map = {
        "add": "add",
        "sub": "sub",
        "remove": "sub",
        "undo": "sub",
        "error": "error",
        "matched": "add",
        "unmatched": "error",
    }
    return status_map.get(value, value)


def parse_number(value: Any) -> Optional[Any]:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except Exception:
        return value
    return int(parsed) if parsed.is_integer() else parsed


def get_request_session_id(payload: Optional[Dict[str, Any]] = None) -> str:
    if payload and payload.get("session_id"):
        return str(payload["session_id"])
    if request.args.get("session_id"):
        return str(request.args["session_id"])
    if runtime_context.get("session_id"):
        return str(runtime_context["session_id"])
    return "default"


def new_session_id() -> str:
    return str(uuid.uuid4())


def new_session_state(session_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    return {
        "session_id": session_id,
        "student_no": payload.get("student_no", runtime_context.get("student_no", "")),
        "student_name": payload.get("student_name", runtime_context.get("student_name", "")),
        "rule_file": payload.get("rule_file", payload.get("rule_filename", get_rule_filename())),
        "running": False,
        "event_id": 0,
        "timestamp": "",
        "score": 0,
        "contact_A": "",
        "contact_B": "",
        "wired_status": "",
        "airSwitchClosed": True,
        "errorWiringCount": 0,
        "wiringResults": [],
        "wiringEvents": [],
        "last_signature": None,
        "last_error_wiring_count": 0,
    }


def get_or_create_session_state(session_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if session_id not in session_states:
        session_states[session_id] = new_session_state(session_id, payload)
    return session_states[session_id]


def reset_wiring_result_files() -> None:
    payload = json.dumps(EMPTY_WIRING_RESULT, ensure_ascii=False, indent=2)
    for result_path in (Global_Config.new_result_json, Global_Config.old_result_json):
        path = Path(result_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")


def reset_global_detection_state() -> None:
    Global_Config.total_score = 0
    Global_Config.current_session_score = 0
    Global_Config.current_A = ""
    Global_Config.current_B = ""
    Global_Config.wired_status = ""
    Global_Config.error_wiring_count = 0
    Global_Config.wiring_results = []
    Global_Config.current_wiring_events = []
    reset_wiring_result_files()


def next_event_id(session_state: Dict[str, Any]) -> int:
    session_state["event_id"] = int(session_state.get("event_id") or 0) + 1
    session_state["timestamp"] = iso_now()
    return session_state["event_id"]


def record_wiring_event(
    contact_A: Any = "",
    contact_B: Any = "",
    wired_status: Any = "",
    score: Optional[Any] = None,
    score_delta: Optional[Any] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_status = normalize_wired_status(wired_status)
    contact_a = str(contact_A or "")
    contact_b = str(contact_B or "")

    with state_lock:
        target_session_id = session_id or active_session_id or runtime_context.get("session_id") or "default"
        session_state = get_or_create_session_state(str(target_session_id))
        if score is not None:
            Global_Config.total_score = parse_number(score)
        elif score_delta is not None:
            try:
                Global_Config.total_score += float(parse_number(score_delta))
            except Exception:
                pass

        if normalized_status == "error":
            Global_Config.error_wiring_count += 1
        else:
            Global_Config.current_A = contact_a
            Global_Config.current_B = contact_b

        Global_Config.wired_status = normalized_status
        pair = [contact_a, contact_b]
        if normalized_status == "add" and contact_a and contact_b:
            if pair not in Global_Config.wiring_results:
                Global_Config.wiring_results.append(pair)
            if pair not in session_state["wiringResults"]:
                session_state["wiringResults"].append(pair)
        elif normalized_status == "sub" and contact_a and contact_b:
            pair_set = {contact_a, contact_b}
            Global_Config.wiring_results = [
                item
                for item in Global_Config.wiring_results
                if not (isinstance(item, list) and len(item) == 2 and set(map(str, item)) == pair_set)
            ]
            session_state["wiringResults"] = [
                item
                for item in session_state["wiringResults"]
                if not (isinstance(item, list) and len(item) == 2 and set(map(str, item)) == pair_set)
            ]

        session_state.update(
            {
                "score": Global_Config.total_score,
                "contact_A": contact_a,
                "contact_B": contact_b,
                "wired_status": normalized_status,
                "airSwitchClosed": Global_Config.switch_status,
                "errorWiringCount": Global_Config.error_wiring_count,
            }
        )
        signature = (
            session_state["score"],
            session_state["contact_A"],
            session_state["contact_B"],
            session_state["wired_status"],
            session_state["errorWiringCount"],
        )
        session_state["last_signature"] = signature
        session_state["last_error_wiring_count"] = session_state["errorWiringCount"]
        next_event_id(session_state)
        return current_wiring_event_locked(session_state)


def current_wiring_event_locked(session_state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "success": True,
        "session_id": session_state.get("session_id", ""),
        "event_id": session_state.get("event_id", 0),
        "score": session_state.get("score", 0),
        "contact_A": session_state.get("contact_A", ""),
        "contact_B": session_state.get("contact_B", ""),
        "wired_status": session_state.get("wired_status", ""),
        "wiringEvents": session_state.get("wiringEvents", []),
        "wiringResults": session_state.get("wiringResults", []),
        "timestamp": session_state.get("timestamp", ""),
    }


def current_wiring_event(session_id: Optional[str] = None) -> Dict[str, Any]:
    with state_lock:
        target_session_id = session_id or active_session_id or runtime_context.get("session_id") or "default"
        return current_wiring_event_locked(get_or_create_session_state(str(target_session_id)))


def sync_gateway_event_from_global(session_id: Optional[str] = None) -> Dict[str, Any]:
    with state_lock:
        target_session_id = str(session_id or active_session_id or runtime_context.get("session_id") or "default")
        session_state = get_or_create_session_state(target_session_id)
        if target_session_id != active_session_id:
            return current_wiring_event_locked(session_state)

        score = Global_Config.total_score
        contact_a = str(Global_Config.current_A or "")
        contact_b = str(Global_Config.current_B or "")
        wired_status = normalize_wired_status(Global_Config.wired_status)
        error_count = Global_Config.error_wiring_count
        session_state["airSwitchClosed"] = Global_Config.switch_status
        wiring_events = []
        for event in getattr(Global_Config, "current_wiring_events", []) or []:
            if not isinstance(event, dict):
                continue
            event_a = str(event.get("contact_A") or event.get("end1") or "")
            event_b = str(event.get("contact_B") or event.get("end2") or "")
            event_status = normalize_wired_status(event.get("wired_status") or wired_status)
            event_score = event.get("score", 0)
            if event_a and event_b:
                wiring_events.append(
                    {
                        "contact_A": event_a,
                        "contact_B": event_b,
                        "end1": event_a,
                        "end2": event_b,
                        "wired_status": event_status,
                        "score": event_score,
                    }
                )
        if not wiring_events and contact_a and contact_b and wired_status in {"add", "sub", "error"}:
            wiring_events.append(
                {
                    "contact_A": contact_a,
                    "contact_B": contact_b,
                    "end1": contact_a,
                    "end2": contact_b,
                    "wired_status": wired_status,
                    "score": score,
                }
            )

        if error_count > int(session_state.get("last_error_wiring_count") or 0):
            session_state.update(
                {
                    "score": score,
                    "contact_A": "",
                    "contact_B": "",
                    "wired_status": "error",
                    "wiringEvents": [],
                    "errorWiringCount": error_count,
                    "last_error_wiring_count": error_count,
                    "last_signature": ("error", error_count, score),
                }
            )
            next_event_id(session_state)
            return current_wiring_event_locked(session_state)

        events_signature = tuple(
            (event["contact_A"], event["contact_B"], event["wired_status"], event.get("score", 0))
            for event in wiring_events
        )
        signature = (score, contact_a, contact_b, wired_status, events_signature)
        if (
            wired_status in {"add", "sub", "error"}
            and signature != session_state.get("last_signature")
        ):
            session_state.update(
                {
                    "score": score,
                    "contact_A": contact_a,
                    "contact_B": contact_b,
                    "wired_status": wired_status,
                    "errorWiringCount": error_count,
                    "wiringResults": Global_Config.wiring_results.copy(),
                    "wiringEvents": wiring_events,
                    "last_error_wiring_count": error_count,
                    "last_signature": signature,
                }
            )
            next_event_id(session_state)

        return current_wiring_event_locked(session_state)


def report_extra(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not payload:
        return {}

    local_only_fields = {
        "server_base",
        "submit_exam_result",
        "exam_result",
        "port",
        "baudrate",
        "timeout",
    }
    return {
        key: value
        for key, value in payload.items()
        if key not in local_only_fields and value is not None
    }


def update_runtime_context(payload: Optional[Dict[str, Any]]) -> None:
    if not payload:
        return

    for key in (
        "student_no",
        "student_name",
        "test_id",
        "test_name",
        "rule_filename",
        "rule_file",
        "session_id",
        "server_base",
    ):
        if key in payload and payload.get(key) is not None:
            runtime_context[key] = payload.get(key)

    if runtime_context.get("server_base"):
        runtime_context["server_base"] = str(runtime_context["server_base"]).rstrip("/")


def current_server_base() -> str:
    return str(runtime_context.get("server_base") or SERVER_BASE).rstrip("/")


def relative_to_project(path: Path) -> str:
    project_root = Path(__file__).resolve().parent
    try:
        return str(path.resolve().relative_to(project_root))
    except ValueError:
        return str(path)


def update_active_rule_path(rule_path: Path, rule_filename: str = "current_rule.json") -> None:
    Global_Config.test_rule = rule_path
    runtime_context["rule_filename"] = rule_filename


def get_rule_filename() -> str:
    if runtime_context.get("rule_filename"):
        return str(runtime_context["rule_filename"])

    rule_path = Path(Global_Config.test_rule)
    current_rule_path = Path(Global_Config.rule_path) / "current_rule.json"
    if current_rule_path.exists():
        return current_rule_path.name
    return rule_path.name


def build_rule_download_url(payload: Dict[str, Any]) -> Optional[str]:
    absolute_url = payload.get("download_url_absolute")
    if absolute_url:
        return str(absolute_url)

    download_url = payload.get("download_url") or "/student/api/rules/current/download"
    server_base = str(payload.get("server_base") or current_server_base()).rstrip("/")
    if not server_base:
        return None
    return urljoin(f"{server_base}/", str(download_url).lstrip("/"))


def validate_rule_json(content: bytes) -> Any:
    try:
        return json.loads(content.decode("utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"下载内容不是有效 JSON：{exc}") from exc


def read_json_file(path: Path) -> Optional[Any]:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def normalize_wiring_result(result: Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {"pairs": [], "connected": [], "raw": result}

    return {
        "pairs": result.get("pairs") or [],
        "connected": result.get("connected") or [],
        "raw": result,
    }


def get_current_raw_wiring_result() -> Dict[str, Any]:
    result = read_json_file(Path(Global_Config.new_result_json))
    return normalize_wiring_result(result)


def is_thread_alive(thread: Any) -> bool:
    return bool(thread and hasattr(thread, "is_alive") and thread.is_alive())


def is_detector_running() -> bool:
    if detector is None:
        return False

    internal_threads = [
        getattr(detector, "_t_cap", None),
        getattr(detector, "_t_loop", None),
    ]
    if any(is_thread_alive(thread) for thread in internal_threads):
        return True

    stop_event = getattr(detector, "_stop", None)
    if stop_event is not None and hasattr(stop_event, "is_set"):
        return not stop_event.is_set()

    return is_thread_alive(detection_thread)


def load_detection_module():
    global detection_module
    if detection_module is None:
        from script import detect_SwtichHand

        detection_module = detect_SwtichHand
    return detection_module


def stm_tool(port=None, baudrate=None, timeout=None):
    return STM32Tool(
        port=port or STM_PORT,
        baudrate=baudrate or STM_BAUD,
        timeout=timeout or STM_TIMEOUT,
    )


def stm_tool_from_payload(payload: Optional[Dict[str, Any]] = None):
    payload = payload or {}
    return stm_tool(
        port=payload.get("stm_port") or payload.get("port"),
        baudrate=payload.get("stm_baud") or payload.get("baudrate"),
        timeout=payload.get("stm_timeout") or payload.get("timeout"),
    )


def build_wiring_status(extra: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
    raw_wiring = get_current_raw_wiring_result()
    target_session_id = session_id or get_request_session_id()
    latest_event = sync_gateway_event_from_global(target_session_id)
    session_state = get_or_create_session_state(str(target_session_id))
    status = {
        "success": True,
        "session_id": target_session_id,
        "airSwitchClosed": session_state.get("airSwitchClosed", True),
        "errorWiringCount": session_state.get("errorWiringCount", 0),
        "currentContacts": {
            "contact_A": latest_event["contact_A"],
            "contact_B": latest_event["contact_B"],
        },
        "contact_A": latest_event["contact_A"],
        "contact_B": latest_event["contact_B"],
        "wired_status": latest_event["wired_status"],
        "score": latest_event["score"],
        "totalScore": Global_Config.total_score,
        "event_id": latest_event["event_id"],
        "wiringResults": session_state.get("wiringResults", []),
        "raw_wiring": raw_wiring,
        "rule_filename": get_rule_filename(),
        "context": compact_dict(runtime_context.copy()),
        "detection": {
            "running": is_detector_running(),
            "recording_id": active_recording_id,
            "recording_error": recording_error,
            "started_at": detection_started_at,
        },
        "timestamp": latest_event["timestamp"] or iso_now(),
    }
    if extra:
        status.update(extra)
    return status


def build_wiring_report_payload(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    extra = report_extra(extra)
    status = build_wiring_status()
    payload = {
        "student_no": runtime_context.get("student_no"),
        "test_id": runtime_context.get("test_id"),
        "contact_A": status["contact_A"],
        "contact_B": status["contact_B"],
        "wired_status": status["wired_status"],
        "score_delta": (extra or {}).get("score_delta", 0),
        "total_score": status["totalScore"],
        "timestamp": status["timestamp"],
        "rule_filename": status["rule_filename"],
        "wiring_results": status["wiringResults"],
        "raw_yolo": (extra or {}).get("raw_yolo", {}),
        "raw_stm32": status["raw_wiring"],
    }
    if extra:
        payload.update(extra)
    return compact_dict(payload)


def build_exam_report_payload(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    extra = report_extra(extra)
    payload = {
        "student_no": runtime_context.get("student_no"),
        "test_id": runtime_context.get("test_id"),
        "test_name": runtime_context.get("test_name"),
        "test_score": Global_Config.total_score,
        "knowledge": extra.get("knowledge", ""),
        "details": {
            "rule_filename": get_rule_filename(),
            "wiring_results": Global_Config.wiring_results,
            "raw_stm32": get_current_raw_wiring_result(),
            "error_wiring_count": Global_Config.error_wiring_count,
            "airSwitchClosed": Global_Config.switch_status,
        },
        "timestamp": iso_now(),
    }
    if extra:
        details = payload.pop("details")
        extra_details = extra.get("details")
        payload.update({key: value for key, value in extra.items() if key != "details"})
        if isinstance(extra_details, dict):
            details.update(extra_details)
        payload["details"] = details
    return compact_dict(payload)


def post_to_server(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{current_server_base()}{path}"
    started = time.time()
    try:
        resp = http.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        response_json = resp.json() if resp.content else {}
        return {
            "success": resp.status_code < 400,
            "url": url,
            "status_code": resp.status_code,
            "response": response_json,
            "elapsed_ms": round((time.time() - started) * 1000, 1),
        }
    except Exception as exc:
        return {
            "success": False,
            "url": url,
            "message": str(exc),
            "elapsed_ms": round((time.time() - started) * 1000, 1),
        }


@serialized_capture
def maybe_score_stm32_result(connections: Any) -> Dict[str, Any]:
    from script.calculate_score import evaluate_pairs
    from script.deal_StmResult import generate_by_name_json
    from script.update_pairs import diff_json_pairs

    old_result_path = Path(Global_Config.old_result_json)
    if not old_result_path.exists():
        old_result_path.parent.mkdir(parents=True, exist_ok=True)
        old_result_path.write_text(
            json.dumps(EMPTY_WIRING_RESULT, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    named_result = generate_by_name_json(
        connections,
        Global_Config.label_csv,
        Global_Config.new_result_json,
        print_console=False,
    )
    add_pairs, undo_pairs = diff_json_pairs(
        Global_Config.old_result_json,
        Global_Config.new_result_json,
    )
    score_result = evaluate_pairs(
        str(Global_Config.new_result_json),
        str(Global_Config.test_rule),
        print_console=False,
    )
    matched_scores = {
        tuple(sorted((str(item["pair"][0]), str(item["pair"][1])))): item.get("score", 0)
        for item in score_result.get("matched", [])
        if isinstance(item.get("pair"), list) and len(item["pair"]) == 2
    }
    current_events = [
        {
            "contact_A": pair[0],
            "contact_B": pair[1],
            "wired_status": "add",
            "score": matched_scores.get(tuple(sorted((str(pair[0]), str(pair[1])))), 0),
        }
        for pair in add_pairs
    ] + [
        {
            "contact_A": pair[0],
            "contact_B": pair[1],
            "wired_status": "sub",
            "score": 0,
        }
        for pair in undo_pairs
    ]

    if active_recording_id:
        record_capture(active_recording_id, named_result, score_result)

    Global_Config.total_score = score_result.get("total_score", Global_Config.total_score)
    Global_Config.current_session_score = Global_Config.total_score
    Global_Config.wiring_results = named_result.get("pairs", [])
    Global_Config.current_wiring_events = current_events
    if current_events:
        last_event = current_events[-1]
        Global_Config.current_A = last_event["contact_A"]
        Global_Config.current_B = last_event["contact_B"]
        Global_Config.wired_status = last_event["wired_status"]
    else:
        Global_Config.current_A = ""
        Global_Config.current_B = ""
        Global_Config.wired_status = "no_change"
    Path(Global_Config.old_result_json).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Global_Config.new_result_json, Global_Config.old_result_json)

    return {
        "named_result": named_result,
        "score_result": score_result,
        "add_pairs": add_pairs,
        "undo_pairs": undo_pairs,
        "wiring_events": current_events,
    }


@app.route("/health", methods=["GET"])
def health():
    server_ok = False
    health_url = f"{current_server_base()}/api/auth/health"
    try:
        resp = http.get(health_url, timeout=REQUEST_TIMEOUT)
        server_ok = resp.status_code < 400
    except Exception:
        server_ok = False

    return jsonify(
        {
            "success": True,
            "service": "student-local-gateway",
            "message": "本地接线检测网关运行中",
            "listen": "http://127.0.0.1:6001",
            "server_base": current_server_base(),
            "server_ok": server_ok,
            "detection_running": is_detector_running(),
            "context": compact_dict(runtime_context.copy()),
        }
    )


@app.route("/recognize_face", methods=["POST"])
def recognize_face_not_supported():
    return jsonify(
        {
            "success": False,
            "message": "本地网关不处理人脸识别；请由学生浏览器上传照片到服务端 /recognize_face。",
        }
    ), 410


def exam_score_key():
    key = config_value("exam_score_key", "", "EXAM_SCORE_KEY")
    if not key:
        key_file = Path(__file__).with_name("exam-score.key")
        if key_file.is_file():
            key = key_file.read_text(encoding="utf-8").strip()
    return key


def write_rule_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as staging:
            tmp = Path(staging.name)
            staging.write(content)
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def install_local_rule(rules, selection):
    if not isinstance(rules, list) or not rules:
        raise ValueError("规则文件为空或格式错误")
    content = json.dumps(rules, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    metadata = dict(selection, sha256=hashlib.sha256(content).hexdigest())
    write_rule_bytes(LOCAL_RULE_PATH, content)
    write_rule_bytes(LOCAL_RULE_PATH.with_suffix(".selection"), json.dumps(metadata).encode())


def local_rule_selection():
    try:
        selection = json.loads(LOCAL_RULE_PATH.with_suffix(".selection").read_bytes())
        if selection["sha256"] == hashlib.sha256(LOCAL_RULE_PATH.read_bytes()).hexdigest():
            return selection
    except (ValueError, KeyError, TypeError, OSError):
        pass
    return {}


def unpack_exam_rule(payload):
    key = exam_score_key()
    if not key:
        raise ValueError("本机网关尚未配置考试成绩签名密钥")
    try:
        bundle = URLSafeTimedSerializer(key, salt="wiring-exam-rule-v1").loads(
            payload.get("rule_ticket") or "", max_age=180)
    except BadData:
        raise ValueError("考试规则凭据无效或已过期，请重新选择考试") from None
    if bundle["exam"] != str(payload.get("test_id")) or bundle["student"] != str(payload.get("student_no")):
        raise ValueError("考试规则与学生或考试不符")
    return bundle


def exam_selection(bundle):
    return {key: bundle[key] for key in ("exam", "student", "filename")}


def matches_exam(bundle):
    selection = local_rule_selection()
    return (bool(bundle.get("sha256")) and selection.get("sha256") == bundle["sha256"]
            and all(selection.get(k) == v for k, v in exam_selection(bundle).items()))


@app.post("/api/exam/prepare")
@serialized_lifecycle
def prepare_exam_rule():
    try:
        bundle = unpack_exam_rule(request.get_json(silent=True) or {})
        if not bundle.get("challenge"):
            raise ValueError("请从选考页下载规则")
        if not matches_exam(bundle):
            if active_recording_id or is_detector_running():
                return jsonify(success=False, message="请先结束本机正在进行的检测"), 409
            install_local_rule(bundle["rules"], exam_selection(bundle))
            if not matches_exam(bundle):
                raise ValueError("本机规则文件校验失败，请重新下载")
        receipt = URLSafeTimedSerializer(exam_score_key(), salt="wiring-rule-installed-v1").dumps(
            {k: bundle[k] for k in ("exam", "student", "challenge")})
        return jsonify(success=True, receipt=receipt, supports_exit_submission=True)
    except (OSError, ValueError) as error:
        return jsonify(success=False, message=f"考试规则下载失败：{error}"), 400


@app.get("/api/rules/local")
@serialized_lifecycle
def local_practice_rule():
    selection = local_rule_selection()
    return jsonify(success=True, filename=None if "exam" in selection else selection.get("filename"))


@app.post("/api/exam/start")
@app.route("/api/yolo/start", methods=["POST"])
@serialized_lifecycle
def start_yolo():
    global detector, detection_thread, detection_started_at, active_session_id, active_recording_id, recording_error

    payload = request.get_json(silent=True) or {}
    if not payload.get("session_id"):
        payload["session_id"] = new_session_id()
    if payload.get("rule_file") and not payload.get("rule_filename"):
        payload["rule_filename"] = payload["rule_file"]
    session_id = get_request_session_id(payload)

    if active_recording_id or is_detector_running():
        if active_session_id == session_id:
            message = "检测已经在运行"
        else:
            message = f"检测已被其他会话占用: {active_session_id}"
        return jsonify(
            {
                "success": False,
                "message": message,
                "session_id": session_id,
                "active_session_id": active_session_id,
                "running": True,
                "context": compact_dict(runtime_context.copy()),
            }
        )

    if request.path == "/api/exam/start":
        try:
            bundle = unpack_exam_rule(payload)
            exit_token = payload.get("exit_token")
            if not isinstance(exit_token, str) or not re.fullmatch(r"[0-9a-f]{32}", exit_token) or not bundle.get("close_submission"):
                raise ValueError("请刷新考试页面，以启用关闭时自动交卷")
            if not matches_exam(bundle):
                raise ValueError("本机考试规则已变更，请返回选考页重新下载")
            payload["rule_filename"] = payload["rule_file"] = bundle["filename"]
        except (ValueError, OSError) as exc:
            return jsonify(success=False, message=str(exc)), 400
    else:
        if payload.get("test_id") or payload.get("rule_ticket"):
            return jsonify(success=False, message="考试检测必须使用本场考试的规则凭据"), 400
        selection = local_rule_selection()
        if not selection or "exam" in selection:
            return jsonify(success=False, message="请先选择练习规则并设为本机当前规则"), 409
        if payload.get("rule_filename") and payload["rule_filename"] != selection["filename"]:
            return jsonify(success=False, message="本机练习规则已切换，请重新设为当前"), 409
        payload["rule_filename"] = payload["rule_file"] = selection["filename"]
        payload["test_id"] = ""
        payload["test_name"] = ""

    update_active_rule_path(LOCAL_RULE_PATH, payload["rule_filename"])
    update_runtime_context(payload)
    stm_started = False
    started_recording_id = None
    exit_armed = False
    try:
        matrix_tool = stm_tool_from_payload(payload)
        stm_started = matrix_tool.start_detection_mode()
        if not stm_started:
            return jsonify(
                {
                    "success": False,
                    "message": "STM32矩阵检测模式开启失败，未启动接线检测",
                    "session_id": session_id,
                    "running": False,
                }
            ), 500

        reset_global_detection_state()
        with state_lock:
            session_states[session_id] = new_session_state(session_id, payload)
        active_session_id = session_id

        initial_connections = matrix_tool.query_and_parse()
        if matrix_tool.last_query_status != "ok":
            rollback: Dict[str, Any] = {}
            try:
                rollback["stm32_stopped"] = bool(stm_tool_from_payload(payload).stop_detection_mode())
            except Exception as stop_exc:
                rollback["stm32_stop_error"] = str(stop_exc)
            active_session_id = None
            return jsonify(
                {
                    "success": False,
                    "message": f"STM32矩阵初始读取失败：{matrix_tool.last_query_status or 'unknown'}",
                    "session_id": session_id,
                    "running": False,
                    "stm32": {"detection_mode": "started", "query_status": matrix_tool.last_query_status},
                    "rollback": rollback,
                }
            ), 500
        initial_scoring = maybe_score_stm32_result(initial_connections)
        initial_event = sync_gateway_event_from_global(session_id)

        active_recording_id = begin_recording(initial_scoring)
        started_recording_id = active_recording_id
        recording_error = None
        module = load_detection_module()
        if request.path == "/api/exam/start":
            close = bundle["close_submission"]
            get_exit_queue().arm(exit_token, session_id, started_recording_id, SERVER_BASE + close["path"], close["ticket"])
            exit_armed = True
        detector, detection_thread = module.start_hand_detection(
            on_snapshot=lambda named, score: record_capture(started_recording_id, named, score))
        detection_started_at = iso_now()
        with state_lock:
            session_states[session_id]["running"] = True
        return jsonify(
            {
                "success": True,
                "message": "检测已启动",
                "session_id": session_id,
                "running": True,
                "stm32": {
                    "detection_mode": "started",
                    "initial_query_status": matrix_tool.last_query_status,
                    "initial_connections_count": len(initial_connections),
                },
                "recording_id": active_recording_id,
                "initial_scoring": initial_scoring,
                "initial_event": initial_event,
                "context": compact_dict(runtime_context.copy()),
                "rule_filename": get_rule_filename(),
            }
        )
    except Exception as exc:
        if exit_armed:
            get_exit_queue().release(exit_token)
        if started_recording_id:
            get_recording_store().finish(started_recording_id, "failed")
        active_recording_id = None
        recording_error = str(exc)
        detector = None
        detection_thread = None
        detection_started_at = None
        active_session_id = None
        rollback: Dict[str, Any] = {}
        if stm_started:
            try:
                rollback["stm32_stopped"] = bool(stm_tool_from_payload(payload).stop_detection_mode())
            except Exception as stop_exc:
                rollback["stm32_stop_error"] = str(stop_exc)
        return jsonify(
            {
                "success": False,
                "message": f"启动失败: {exc}",
                "running": False,
                **({"rollback": rollback} if rollback else {}),
            }
        ), 500



@app.route("/api/yolo/stop", methods=["POST"])
@serialized_lifecycle
def stop_yolo():
    return stop_detection(request.get_json(silent=True) or {})


def stop_detection(payload):
    global detector, detection_thread, detection_started_at, active_session_id, active_recording_id, recording_error

    session_id = get_request_session_id(payload)
    session_state = get_or_create_session_state(session_id)

    if active_session_id and session_id != active_session_id:
        return jsonify(
            {
                "success": False,
                "message": f"当前会话未启动检测，活动会话为 {active_session_id}",
                "session_id": session_id,
                "active_session_id": active_session_id,
                "score": session_state.get("score", 0),
            }
        ), 409

    if active_recording_id is None and detector is None and not is_thread_alive(detection_thread):
        session_state["running"] = False
        return jsonify(
            {
                "success": True,
                "message": "检测已停止",
                "session_id": session_id,
                "score": session_state.get("score", 0),
                "running": False,
            }
        )

    try:
        module = load_detection_module()
        module.stop_hand_detection()
        if is_thread_alive(detection_thread):
            detection_thread.join(timeout=5)
        if is_thread_alive(detection_thread):
            raise RuntimeError("检测启动线程尚未退出，请重试停止")
        matrix_tool = stm_tool_from_payload(payload)
        final_connections = matrix_tool.query_and_parse()
        final_capture_status = matrix_tool.last_query_status
        if final_capture_status == "ok":
            maybe_score_stm32_result(final_connections)
        stm_stopped = matrix_tool.stop_detection_mode()
        if not stm_stopped:
            return jsonify(
                {
                    "success": False,
                    "message": "STM32矩阵检测模式关闭失败，未停止接线检测",
                    "session_id": session_id,
                    "active_session_id": active_session_id,
                    "running": is_detector_running(),
                }
            ), 500

        latest_event = sync_gateway_event_from_global(session_id)
        finished_recording_id = active_recording_id
        if finished_recording_id:
            get_recording_store().finish(
                finished_recording_id, "completed" if final_capture_status == "ok" and not recording_error else "interrupted")
        active_recording_id = None
        detector = None
        detection_thread = None
        detection_started_at = None
        active_session_id = None
        session_state["running"] = False

        response = {
            "success": True,
            "message": "检测已停止",
            "session_id": session_id,
            "score": latest_event.get("score", session_state.get("score", 0)),
            "running": False,
            "recording_id": finished_recording_id,
            "recording_error": recording_error,
            "stm32": {"detection_mode": "stopped", "final_query_status": final_capture_status},
        }
        if payload.get("submit_exam_result"):
            report_payload = build_exam_report_payload(payload.get("exam_result") or {})
            response["exam_report"] = post_to_server("/student/api/exam_result", report_payload)
        return jsonify(response)
    except Exception as exc:
        return jsonify({"success": False, "message": f"停止失败: {exc}", "running": is_detector_running()}), 500


@app.route("/api/yolo/status", methods=["GET"])
def yolo_status():
    session_id = get_request_session_id()
    session_state = get_or_create_session_state(session_id)
    return jsonify(
        {
            "success": True,
            "session_id": session_id,
            "running": is_detector_running(),
            "session_running": bool(session_state.get("running")),
            "recording_id": active_recording_id,
            "recording_error": recording_error,
            "started_at": detection_started_at,
            "active_session_id": active_session_id,
            "context": compact_dict(runtime_context.copy()),
            "rule_filename": get_rule_filename(),
        }
    )


@app.route("/api/get_air_switch_status", methods=["GET"])
def get_air_switch_status():
    session_id = get_request_session_id()
    sync_gateway_event_from_global(session_id)
    session_state = get_or_create_session_state(session_id)
    return jsonify(
        {
            "success": True,
            "session_id": session_id,
            "airSwitchClosed": session_state.get("airSwitchClosed", True),
            "errorWiringCount": session_state.get("errorWiringCount", 0),
        }
    )


@app.route("/api/get_score_and_contact", methods=["GET"])
def get_score_and_contact():
    session_id = get_request_session_id()
    return jsonify(sync_gateway_event_from_global(session_id))


@app.route("/api/get_current_score", methods=["GET"])
def get_current_score():
    session_id = get_request_session_id()
    sync_gateway_event_from_global(session_id)
    session_state = get_or_create_session_state(session_id)
    return jsonify(
        {
            "success": True,
            "session_id": session_id,
            "score": session_state.get("score", 0),
        }
    )


@app.route("/api/get_wiring_status", methods=["GET"])
def get_wiring_status():
    return jsonify(build_wiring_status(session_id=get_request_session_id()))


@app.route("/api/context", methods=["GET", "POST"])
def context():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        update_runtime_context(payload)
    return jsonify({"success": True, "context": compact_dict(runtime_context.copy())})


@app.route("/api/rules/pull", methods=["POST"])
@serialized_lifecycle
def pull_current_rule():
    if active_recording_id or is_detector_running():
        return jsonify(success=False, message="请先停止当前检测再切换规则"), 409
    payload = request.get_json(silent=True) or {}
    download_url = build_rule_download_url(payload)
    if not download_url:
        return jsonify({"success": False, "message": "缺少规则下载地址"}), 400

    local_path = LOCAL_RULE_PATH
    try:
        response = http.get(download_url, timeout=REQUEST_TIMEOUT)
        if response.status_code >= 400:
            return jsonify(
                {
                    "success": False,
                    "message": f"规则下载失败，HTTP {response.status_code}",
                    "download_url": download_url,
                }
            ), 502

        rule_json = validate_rule_json(response.content)
        name = payload.get("filename") or local_path.name
        install_local_rule(rule_json, {"filename": name})
        update_active_rule_path(local_path, name)
        return jsonify(
            {
                "success": True,
                "message": "规则文件已下载",
                "local_path": str(local_path),
                "relative_path": relative_to_project(local_path),
                "bytes": local_path.stat().st_size,
                "download_url": download_url,
                "rule_filename": name,
            }
        )
    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "message": f"规则文件下载失败: {exc}",
                "download_url": download_url,
                "local_path": str(local_path),
                "relative_path": relative_to_project(local_path),
            }
        ), 500


@app.route("/api/test/wiring_event", methods=["POST"])
def test_wiring_event():
    payload = request.get_json(silent=True) or {}
    session_id = get_request_session_id(payload)
    status = payload.get("wired_status", payload.get("status", "add"))
    event = record_wiring_event(
        contact_A=payload.get("contact_A", payload.get("contact_a", "")),
        contact_B=payload.get("contact_B", payload.get("contact_b", "")),
        wired_status=status,
        score=payload.get("score"),
        score_delta=payload.get("score_delta"),
        session_id=session_id,
    )
    return jsonify({"success": True, **event})


@app.route("/api/test_wired_status", methods=["GET", "POST"])
def test_wired_status():
    payload = request.get_json(silent=True) or {}
    source = payload if request.method == "POST" else request.args
    session_id = get_request_session_id(dict(source))
    event = record_wiring_event(
        contact_A=source.get("contact_A", source.get("contact_a", "")),
        contact_B=source.get("contact_B", source.get("contact_b", "")),
        wired_status=source.get("wired_status", source.get("status", "add")),
        score=source.get("score"),
        score_delta=source.get("score_delta"),
        session_id=session_id,
    )
    return jsonify(event)


@app.route("/api/report/wiring_result", methods=["POST"])
def report_wiring_result():
    global last_report_result

    payload = request.get_json(silent=True) or {}
    update_runtime_context(payload)
    report_payload = build_wiring_report_payload(payload)
    last_report_result = post_to_server("/student/api/wiring_result", report_payload)
    return jsonify(
        {
            "success": last_report_result["success"],
            "message": "接线结果上报完成" if last_report_result["success"] else "接线结果上报失败",
            "payload": report_payload,
            "report": last_report_result,
        }
    ), 200 if last_report_result["success"] else 502


@app.route("/api/report/exam_result", methods=["POST"])
def report_exam_result():
    payload = request.get_json(silent=True) or {}
    update_runtime_context(payload)
    report_payload = build_exam_report_payload(payload)
    report_result = post_to_server("/student/api/exam_result", report_payload)
    return jsonify(
        {
            "success": report_result["success"],
            "message": "考试结果上报完成" if report_result["success"] else "考试结果上报失败",
            "payload": report_payload,
            "report": report_result,
        }
    ), 200 if report_result["success"] else 502


@app.route("/api/stm/start", methods=["POST"])
def stm_start():
    payload = request.get_json(silent=True) or {}
    tool = stm_tool_from_payload(payload)
    try:
        ok = tool.start_detection_mode()
        if ok:
            return jsonify({"success": True, "message": "STM检测模式已开启"})
        return jsonify({"success": False, "message": "STM开启检测模式失败"}), 500
    except Exception as exc:
        return jsonify({"success": False, "message": f"串口异常: {exc}"}), 500


@app.route("/api/stm/stop", methods=["POST"])
def stm_stop():
    payload = request.get_json(silent=True) or {}
    tool = stm_tool_from_payload(payload)
    try:
        ok = tool.stop_detection_mode()
        if ok:
            return jsonify({"success": True, "message": "STM检测模式已关闭"})
        return jsonify({"success": False, "message": "STM关闭检测模式失败"}), 500
    except Exception as exc:
        return jsonify({"success": False, "message": f"串口异常: {exc}"}), 500


@app.route("/api/stm/query", methods=["GET"])
@serialized_lifecycle
@serialized_capture
def stm_query():
    port = request.args.get("port")
    baudrate = request.args.get("baudrate", type=int)
    timeout = request.args.get("timeout", type=float)
    should_score = request.args.get("score", "false").lower() in {"1", "true", "yes", "on"}
    should_report = request.args.get("report", "false").lower() in {"1", "true", "yes", "on"}
    tool = stm_tool(port=port, baudrate=baudrate, timeout=timeout)
    try:
        connections = tool.query_and_parse()
        if tool.last_query_status != "ok":
            return jsonify({"success": False, "message": "STM32采集无效",
                            "query_status": tool.last_query_status}), 502
        response: Dict[str, Any] = {"success": True, "connections": connections, "count": len(connections)}
        if should_score or active_recording_id:
            response["scoring"] = maybe_score_stm32_result(connections)
            response["status"] = build_wiring_status()
        if should_report:
            report_payload = build_wiring_report_payload({"raw_stm32_connections": connections})
            response["wiring_report"] = post_to_server("/student/api/wiring_result", report_payload)
        return jsonify(response)
    except Exception as exc:
        return jsonify({"success": False, "message": f"查询失败: {exc}"}), 500


@app.route("/api/recordings", methods=["GET"])
def list_recordings():
    try:
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("limit 应为 1–200，offset 应大于等于 0")
        return jsonify({"success": True, "recordings": get_recording_store().list_recordings(limit, offset),
                        "active_recording_id": active_recording_id, "recording_error": recording_error})
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.route("/api/recordings/<recording_id>", methods=["GET"])
def read_recording(recording_id: str):
    try:
        after_seq = int(request.args.get("after_seq", 0))
        limit = int(request.args.get("limit", 500))
        if after_seq < 0 or not 1 <= limit <= 2000:
            raise ValueError("after_seq 应大于等于 0，limit 应为 1–2000")
        return jsonify({"success": True, **get_recording_store().read(recording_id, after_seq, limit)})
    except KeyError:
        return jsonify({"success": False, "message": "接线记录不存在"}), 404
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400


@app.post("/api/recordings/<recording_id>/exam-receipt")
def exam_receipt(recording_id):
    return build_exam_receipt(recording_id, include_archive=request.args.get("archive") == "1")


def build_exam_receipt(recording_id, include_archive):
    key = exam_score_key()
    if not key:
        return jsonify(success=False, message="本机网关尚未配置考试成绩签名密钥"), 503
    try:
        record = get_recording_store().read(recording_id, limit=None if include_archive else 0)
    except KeyError:
        return jsonify(success=False, message="未找到本次检测记录"), 404
    if record["status"] != "completed":
        return jsonify(success=False, message="缺少完整的最终接线检查，请重新检测后提交"), 409
    metadata = record["metadata"]
    if not metadata.get("test_id") or not metadata.get("student_no"):
        return jsonify(success=False, message="该记录不属于考试"), 400
    proof = {
        "student_no": metadata["student_no"], "exam_id": metadata["test_id"],
        "recording_id": recording_id, "score": record["latest_state"]["score"],
    }
    response = {"success": True}
    if include_archive:
        archive = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        proof["archive_sha256"] = hashlib.sha256(archive.encode("utf-8")).hexdigest()
        response["archive"] = archive
    receipt = URLSafeSerializer(key, salt="wiring-exam-score-v1").dumps(proof)
    return jsonify(receipt=receipt, **response)


def submit_after_exit(job):
    # Capture a final hardware reading only for the exact attempt that lost its page.
    with app.app_context():
        with lifecycle_lock:
            if active_recording_id == job["recording"]:
                if active_session_id != job["session"]:
                    return "failed", "接线会话与交卷记录不符"
                stopped = app.make_response(stop_detection({"session_id": job["session"]}))
                if not stopped.json["success"]:
                    return "queued", stopped.json["message"]
        result = app.make_response(build_exam_receipt(job["recording"], include_archive=True))
        if result.status_code != 200:
            return ("queued" if result.status_code >= 500 else "failed"), result.json["message"]
        submission = result.get_json()
    submission["ticket"] = job["ticket"]
    response = requests.post(job["destination"], json=submission, timeout=REQUEST_TIMEOUT, allow_redirects=False)
    if response.ok and response.json().get("success"):
        return "submitted", str(response.json()["score"])
    if response.status_code in (400, 401, 403, 404, 409, 410):
        return "failed", response.json().get("message", "考试提交失败")
    return "queued", "暂时无法提交，网关将重试"


@app.route("/api/recordings/<recording_id>/export", methods=["GET"])
def export_recording(recording_id: str):
    try:
        data = get_recording_store().read(recording_id)
    except KeyError:
        return jsonify({"success": False, "message": "接线记录不存在"}), 404
    # The identifier is generated locally. Use that verified value in the filename.
    return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="wiring-{data["recording_id"]}.json"'})


if __name__ == "__main__":
    get_exit_queue()
    host = os.getenv("CLIENT_HOST", "127.0.0.1")
    port = int(os.getenv("CLIENT_PORT", "6001"))
    app.run(host=host, port=port, debug=False)
