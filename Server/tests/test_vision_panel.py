"""Graph invariants and the image-to-export protocol, without model weights."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from teacher_webui import vision_panel as vp

EXAMPLES = Path(vp.__file__).parent / "static" / "vision"
DOC = {"title":"逐线校验", "explanation":"三端子跳线和独立回线", "uncertainties":[],
       "components":[{"id":"XT1","label":"端子排","pins":["1","2","3","4","5"]}],
       "nets":[["XT1:1","XT1:2","XT1:3"],["XT1:4","XT1:5"]],
       "wires":[{"from":"XT1:1","to":"XT1:2"},{"from":"XT1:2","to":"XT1:3"},
                {"from":"XT1:4","to":"XT1:5"}]}


class VisionPanelTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(vp.bp)
        self.client = app.test_client()

    def test_migrated_star_delta_example_uses_current_board(self):
        source = json.loads((EXAMPLES / "example.json").read_text(encoding="utf-8"))
        response = self.client.post("/api/vision-panel/diagram", json={"netlist": source})
        self.assertEqual(response.status_code, 200)
        panel = response.get_json()
        self.assertEqual(panel["excluded_count"], 0)
        self.assertEqual(len(panel["wires"]), 33)
        self.assertEqual([{"from": w["from"], "to": w["to"]} for w in panel["wires"]],
                         source["wires"])
        self.assertIn("KM1:1/L1", {w["to"] for w in panel["wires"]})

    def test_confirm_and_compare(self):
        standard = self.client.post("/api/vision-panel/review",json={"netlist":DOC,"confirm":True}).json
        self.assertEqual(standard["status"],"confirmed")
        reversed_wires = [{"from":w["to"],"to":w["from"]} for w in reversed(DOC["wires"])]
        def compare(wires):
            return self.client.post("/api/vision-panel/compare",json={"standard":standard,"wires":wires}).json
        self.assertTrue(compare(reversed_wires)["matches"])
        # Same electrical net, different physical jumper.
        alternative = [dict(w) for w in DOC["wires"]]
        alternative[1]["from"] = "XT1:1"
        result = compare(alternative)
        self.assertFalse(result["matches"])
        self.assertEqual(len(result["missing"]),1)
        self.assertEqual(len(result["extra"]),1)
        self.assertFalse(compare(reversed_wires+reversed_wires[:1])["matches"])

    def test_no_implicit_wires(self):
        partial = dict(DOC,wires=DOC["wires"][:-1])
        panel = vp.strict_panel(partial)
        self.assertEqual(len(panel["wires"]),len(partial["wires"]))
        self.assertTrue(panel["review_items"])
        with self.assertRaises(ValueError):
            vp.strict_panel(partial,confirm=True)
        with self.assertRaises(ValueError):
            vp.strict_panel(dict(DOC,uncertainties=["交点不明"]),confirm=True)

        projected = vp.diagram(partial)
        self.assertEqual(len(projected["wires"]), len(partial["wires"]))

    def test_physical_pair_output(self):
        doc = vp.from_physical_pairs({"title": "逐线校验", "wires": DOC["wires"]})
        self.assertEqual(doc["wires"], DOC["wires"])
        self.assertEqual({frozenset(n) for n in doc["nets"]}, {frozenset(n) for n in DOC["nets"]})
        with self.assertRaisesRegex(ValueError, "M:U1"):
            vp.from_physical_pairs({"title":"盘外触点","wires":[{"from":"XT1:1","to":"M:U1"}]})

    def test_diagnostic_names_pin_and_nets(self):
        bad = dict(DOC, nets=[["XT1:1", "XT1:2"], ["XT1:1", "M:U1"]])
        with self.assertRaises(ValueError) as error:
            vp.validate(bad)
        for detail in ["XT1:1", "M:U1", "N1", "N2"]:
            self.assertIn(detail, str(error.exception))

    @patch.dict("os.environ",{"CIRCUIT_VLM_BASE_URL":"http://model.test/v1","CIRCUIT_VLM_QWEN_DIRECT":"0"})
    @patch("tools.model_client.requests.post")
    def test_upload_and_review(self, call):
        raw = {"title":"测试", "nets":[
            {"line":"1","ends":["FU2:p1.out","FR:NC.in"]},
            {"line":"2","ends":["FR:NC.out","SB1:NC.in","XT:unknown"]},
            {"line":"3","ends":["QF:p1.out","FU1:p1.in"]}]}
        call.return_value.status_code = 200
        call.return_value.json.return_value = {"choices":[{"message":{"content":json.dumps(raw)}}]}
        image = io.BytesIO()
        Image.new("RGB", (40, 40), "white").save(image, "PNG")
        image.seek(0)
        answer = self.client.post("/api/vision-panel/analyze",data={"image":(image,"example.png")})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json["netlist"]["wires"], [{"from":"FU2:2","to":"FR1:95/NC"}])
        self.assertEqual(len(answer.json["observations"]), 3)
        payload = call.call_args.kwargs["json"]
        self.assertTrue(payload["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertNotIn("本次允许的端子",payload["messages"][0]["content"])

    def test_installation_requires_evidence_and_same_net(self):
        obs = {"title":"接线", "nets":[{"line":"3","ends":["SB1:NO.out","KM1:NO.out","KM1:coil.in"]}]}
        boxes = [[10,20,30,40],[120,150,180,200]]
        edge = {"from":"SB1:NO.out","to":"KM1:coil.in","basis":"双方标注对端","boxes":boxes}
        pairs = [edge, dict(edge,to="QF:p1.in"), dict(edge,to="KM2:A1"),
                 dict(edge,to="KM1:NO.out",basis=""), dict(edge,to="KM1:NO.out",boxes=[])]
        result = vp.map_observations(obs, {"edges":pairs})
        self.assertEqual(result["netlist"]["wires"], [{"from":"SB1:4/NO","to":"KM1:A1"}])
        self.assertEqual(result["panel"]["evidence"][0]["boxes"],boxes)
        self.assertNotIn("equivalent", result)
        schematic = vp.map_observations(obs)
        self.assertEqual(schematic["panel"]["wires"], [])
        self.assertEqual(len(schematic["equivalent"]["wires"]), 2)

    def test_local_review_drops_unconfirmed_pair(self):
        image = io.BytesIO()
        Image.new("RGB",(40,40),"white").save(image,"PNG")
        image.seek(0)
        data = vp.image_content(image)
        raw = {"title":"测试","nets":[{"line":"1","ends":["KM1:A1","SB1:NO.out"],
                                    "review_box":[0,0,500,500]}]}
        with patch.object(vp.ModelClient, "complete", side_effect=[
            json.dumps(raw), json.dumps({"line":"1","ends":[]})
        ]) as call:
            result = vp.read_schematic(vp.ModelClient("http://localhost/v1"),"model",data)
        self.assertFalse(result["panel"]["wires"])
        second = call.call_args.args[0]["messages"][1]["content"]
        self.assertEqual(sum(p["type"]=="image_url" for p in second),2)

    def test_installation_only_and_device_override(self):
        obs = {"kind":"installation","title":"施工","nets":[]}
        edge = {"from":"KM1:NO.out","to":"KM2:A1","basis":"直接线",
                "boxes":[[0,0,40,40],[100,100,150,150]]}
        with patch.dict(vp.TERMINAL_MAPPING["devices"], {"KM1":{"NO.OUT":"54/NO"}}):
            result = vp.map_observations(obs, {"edges":[edge]})
        self.assertEqual(result["netlist"]["wires"][0]["from"],"KM1:54/NO")

    def test_conflicting_and_duplicate_networks_do_not_export(self):
        nets = [{"line":"1","ends":["KM1:coil.in","SB1:NO.out"]},
                {"line":"2","ends":["KM1:A1","SB2:NO.out"]},
                {"line":"2","ends":["FU2:p1.out","KM2:coil.in"]}]
        result = vp.map_observations({"title":"重复", "nets":nets})
        self.assertEqual(result["panel"]["wires"], [])



if __name__ == "__main__":
    unittest.main()
