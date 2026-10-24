"""Tests for Phase 3: In-Canvas Sketch & Geometry System (Jaaz Magic Canvas style)
and Rhino 3D Viewport Direct-Push Bridge.
"""

import os
import sys
import re
import json
import base64
import unittest
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from routers.canvas import RHINO_UPLOAD_DIR, _latest_rhino_capture

# Minimal valid 1x1 transparent PNG Base64
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

class TestPhase3SketchAndRhino(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        if os.path.isdir(RHINO_UPLOAD_DIR):
            for name in os.listdir(RHINO_UPLOAD_DIR):
                fpath = os.path.join(RHINO_UPLOAD_DIR, name)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass

    def test_rhino_capture_post_success(self):
        payload = {
            "image_base64": f"data:image/png;base64,{TINY_PNG_B64}",
            "view_name": "Perspective_Test",
            "camera": {
                "location": [10.5, 20.2, 5.0],
                "target": [0.0, 0.0, 0.0],
                "lens_35mm": 50.0,
                "is_perspective": True
            }
        }
        resp = self.client.post("/api/canvas/rhino-capture", json=payload)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertTrue(data["ok"])
        capture = data["capture"]
        self.assertEqual(capture["view_name"], "Perspective_Test")
        self.assertEqual(capture["camera"]["lens_35mm"], 50.0)
        self.assertTrue(capture["url"].startswith("/assets/uploads/rhino/"))
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), capture["url"].lstrip("/"))))

    def test_rhino_capture_post_invalid_b64(self):
        payload = {
            "image_base64": "invalid_not_b64_!@#$%",
            "view_name": "Bad_View"
        }
        resp = self.client.post("/api/canvas/rhino-capture", json=payload)
        self.assertEqual(resp.status_code, 400)

    def test_rhino_capture_latest_polling(self):
        # Post a new capture
        payload = {
            "image_base64": TINY_PNG_B64,
            "view_name": "Top_View",
            "timestamp": 2000000000000
        }
        post_resp = self.client.post("/api/canvas/rhino-capture", json=payload)
        self.assertEqual(post_resp.status_code, 200)

        # Poll with since = 0 -> returns capture
        poll_resp1 = self.client.get("/api/canvas/rhino-capture/latest?since=0")
        self.assertEqual(poll_resp1.status_code, 200)
        self.assertIsNotNone(poll_resp1.json()["capture"])
        self.assertEqual(poll_resp1.json()["capture"]["view_name"], "Top_View")

        # Poll with since = 2000000000000 -> returns None (up to date)
        poll_resp2 = self.client.get("/api/canvas/rhino-capture/latest?since=2000000000000")
        self.assertEqual(poll_resp2.status_code, 200)
        self.assertIsNone(poll_resp2.json()["capture"])

    def test_rhino_script_file_exists_and_compiles(self):
        script_path = os.path.join("tools", "rhino", "infinite_canvas_rhino.py")
        self.assertTrue(os.path.exists(script_path), "Rhino bridge script missing")
        import py_compile
        py_compile.compile(script_path, doraise=True)
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("capture_rhino_viewport", content)
        self.assertIn("send_to_infinite_canvas", content)
        self.assertIn("/api/canvas/rhino-capture", content)

    def test_canvas_html_contains_sketch_and_dock(self):
        html_path = os.path.join("static", "canvas.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('<svg id="sketchLayer" class="sketch-layer">', html)
        self.assertIn('<div id="canvasToolDock" class="canvas-tool-dock"', html)
        self.assertIn('data-tool="select"', html)
        self.assertIn('data-tool="pen"', html)
        self.assertIn('data-tool="rect"', html)
        self.assertIn('data-tool="ellipse"', html)
        self.assertIn('<div id="sketchPropertyInspector"', html)
        self.assertIn('<div id="sketchQuickAction"', html)
        self.assertIn('sketchLineStyleGroup', html)
        self.assertIn('data-style="dashed"', html)
        self.assertIn('data-style="dotted"', html)

    def test_canvas_css_contains_sketch_styles(self):
        css_path = os.path.join("static", "css", "canvas.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn(".sketch-layer", css)
        self.assertIn(".canvas-tool-dock", css)
        self.assertIn(".dock-tool-btn", css)
        self.assertIn(".sketch-property-inspector", css)
        self.assertIn(".sketch-quick-action", css)
        self.assertIn(".sketch-transform-box", css)
        self.assertIn(".sketch-handle", css)
        self.assertIn(".style-button-group", css)
        self.assertIn(".style-btn", css)

    def test_canvas_sketch_js_structure(self):
        js_path = os.path.join("static", "js", "canvas-sketch.js")
        self.assertTrue(os.path.exists(js_path))
        with open(js_path, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("CanvasSketch", code)
        self.assertIn("pointsToSmoothPath", code)
        self.assertIn("addToChat", code)
        self.assertIn("startRhinoReceiver", code)
        self.assertIn("handleRhinoCapture", code)
        self.assertIn("persist", code)
        self.assertIn("lineStyle", code)
        self.assertIn("getDashArray", code)
        self.assertIn("stroke-dasharray", code)

if __name__ == "__main__":
    unittest.main()

