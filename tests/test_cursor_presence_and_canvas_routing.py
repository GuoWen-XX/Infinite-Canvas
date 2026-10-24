"""Tests for multi-workstation cursor presence, frame-group linking, and group auto-routing."""

import json
import os
import sys
import unittest
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app


class TestCursorPresenceAndCanvasEnhancements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_cursor_presence_broadcasts_ip_and_coordinates(self):
        """When station A sends cursor coordinates over /ws/stats, station B receives cursor_presence with IP."""
        with self.client.websocket_connect("/ws/stats?client_id=station_alpha") as ws_alpha:
            with self.client.websocket_connect("/ws/stats?client_id=station_beta") as ws_beta:
                # Alpha sends cursor movement
                ws_alpha.send_text(json.dumps({
                    "type": "cursor",
                    "x": 320,
                    "y": 480,
                    "canvasId": "canvas_xyz"
                }))

                # Beta should receive cursor_presence (skipping any initial stats message)
                msg = {}
                for _ in range(3):
                    msg_raw = ws_beta.receive_text()
                    msg = json.loads(msg_raw)
                    if msg.get("type") == "cursor_presence":
                        break

                self.assertEqual(msg.get("type"), "cursor_presence")
                self.assertEqual(msg.get("clientId"), "station_alpha")
                self.assertEqual(msg.get("x"), 320)
                self.assertEqual(msg.get("y"), 480)
                self.assertEqual(msg.get("canvasId"), "canvas_xyz")
                # IP must be present (e.g. testclient or 127.0.0.1)
                self.assertTrue(bool(msg.get("ip")), "Workstation IP must be populated")

    def test_cursor_leave_broadcast_on_disconnect(self):
        """When a workstation disconnects from /ws/stats, others receive cursor_leave."""
        with self.client.websocket_connect("/ws/stats?client_id=station_receiver") as ws_rec:
            with self.client.websocket_connect("/ws/stats?client_id=station_leaving") as ws_leave:
                # Just open and close
                pass

            # Station receiver should get cursor_leave for station_leaving
            msg = {}
            for _ in range(3):
                msg_raw = ws_rec.receive_text()
                msg = json.loads(msg_raw)
                if msg.get("type") == "cursor_leave":
                    break

            self.assertEqual(msg.get("type"), "cursor_leave")
            self.assertEqual(msg.get("clientId"), "station_leaving")

    def test_canvas_css_contains_remote_cursor_styles(self):
        """Ensure static/css/canvas.css defines remote cursor styles adhering to aesthetics."""
        css_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "css", "canvas.css")
        with open(css_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(".remote-cursor-layer", content)
        self.assertIn(".remote-cursor", content)
        self.assertIn(".remote-cursor-pointer", content)
        self.assertIn(".remote-cursor-label", content)
        self.assertIn("JetBrains Mono", content)

    def test_canvas_js_contains_cursor_presence_and_group_logic(self):
        """Ensure static/js/canvas.js has initRemoteCursorPresence, getGroupContentKind and outPort linking."""
        js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "js", "canvas.js")
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("initRemoteCursorPresence", content)
        self.assertIn("updateRemoteCursorsScreenPosition", content)
        self.assertIn("handleRemoteCursorPresence", content)
        self.assertIn("getGroupContentKind", content)
        self.assertIn("renderFrameGroupNode", content)
        self.assertIn("startLink(e, node.id, 'out')", content)

    def test_index_html_has_sidebar_category_accordion(self):
        """Ensure static/index.html includes ext-cat-group, initExtCategories and category headers."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html_path = os.path.join(root, "static", "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        shell_js = os.path.join(root, "static", "js", "studio-shell.js")
        if os.path.exists(shell_js):
            with open(shell_js, "r", encoding="utf-8") as f:
                content += f.read()
        shell_css = os.path.join(root, "static", "css", "studio-shell.css")
        if os.path.exists(shell_css):
            with open(shell_css, "r", encoding="utf-8") as f:
                content += f.read()

        self.assertIn("initExtCategories", content)
        self.assertIn("ext-cat-group", content)
        self.assertIn("ext-cat-header", content)
        self.assertIn("ext-cat-arrow", content)
        self.assertIn("ext-cat-badge", content)


if __name__ == "__main__":
    unittest.main()
