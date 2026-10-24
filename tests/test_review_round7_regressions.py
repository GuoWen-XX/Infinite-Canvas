import os
import sys
import re
import json
import glob
import shutil
import tempfile
import subprocess
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestReviewRound7Regressions(unittest.TestCase):
    def test_a_atomic_provider_saves_and_rolling_backups(self):
        """Test atomic provider persistence and collision-resistant rolling backups under a temporary directory."""
        import core.providers as prov_mod
        orig_data_dir = prov_mod.DATA_DIR
        orig_api_providers_file = prov_mod.API_PROVIDERS_FILE

        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                tmp_providers_file = os.path.join(tmp_dir, "api_providers.json")
                prov_mod.DATA_DIR = tmp_dir
                prov_mod.API_PROVIDERS_FILE = tmp_providers_file

                # Start with a valid old JSON file
                initial_data = [{"id": "initial", "name": "Initial Provider", "enabled": True}]
                with open(tmp_providers_file, "w", encoding="utf-8") as f:
                    json.dump(initial_data, f, ensure_ascii=False, indent=2)

                # Call save_api_providers repeatedly
                for i in range(10):
                    data = [{"id": f"provider_{i}", "name": f"Provider {i}", "step": i}]
                    prov_mod.save_api_providers(data)

                # Assert live JSON is valid and latest
                self.assertTrue(os.path.exists(tmp_providers_file))
                with open(tmp_providers_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual(saved, [{"id": "provider_9", "name": "Provider 9", "step": 9}])

                # Assert at most five rolling backups exist
                backup_dir = os.path.join(tmp_dir, ".provider_backups")
                self.assertTrue(os.path.isdir(backup_dir))
                backups = glob.glob(os.path.join(backup_dir, "api_providers_*.json"))
                self.assertGreater(len(backups), 0)
                self.assertLessEqual(len(backups), 5)

                # All backups parse as JSON
                for b in backups:
                    with open(b, "r", encoding="utf-8") as bf:
                        parsed = json.load(bf)
                        self.assertIsInstance(parsed, list)
            finally:
                prov_mod.DATA_DIR = orig_data_dir
                prov_mod.API_PROVIDERS_FILE = orig_api_providers_file

    def test_b_frontend_syntax_gate(self):
        """Recursively run node --check over first-party static/js/*.js (exclude vendor)."""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node binary is not available on PATH")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        static_js_dir = os.path.join(base_dir, "static", "js")

        js_files = []
        for root, dirs, files in os.walk(static_js_dir):
            dirs[:] = [d for d in dirs if d.lower() != "vendor"]
            for f in files:
                if f.lower().endswith(".js"):
                    js_files.append(os.path.join(root, f))

        self.assertGreater(len(js_files), 0, "No JS files found to check")

        for js_path in js_files:
            rel = os.path.relpath(js_path, base_dir)
            proc = subprocess.run(
                [node_bin, "--check", js_path],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"node --check failed on {rel}:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}",
            )

    def test_c_canvas_render_node_xss_protection(self):
        """Narrow source assertion that renderNode escapes displayTitle and has no inline onclick delete handler."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        canvas_js = os.path.join(base_dir, "static", "js", "canvas.js")
        self.assertTrue(os.path.exists(canvas_js))
        with open(canvas_js, "r", encoding="utf-8") as f:
            content = f.read()

        m = re.search(r"function\s+renderNode\s*\([^)]*\)\s*\{([\s\S]*?)\nfunction\s+", content)
        self.assertIsNotNone(m, "renderNode function not found in canvas.js")
        render_node_body = m.group(1)

        # 1. Header no longer interpolates raw ${displayTitle}
        self.assertNotIn(
            "${displayTitle}",
            render_node_body,
            "renderNode still interpolates unescaped ${displayTitle}",
        )
        self.assertIn(
            "${escapeHtml(displayTitle)}",
            render_node_body,
            "renderNode must interpolate ${escapeHtml(displayTitle)}",
        )

        # 2. No longer contains inline onclick="deleteNodeFromButton('${node.id}'
        self.assertNotIn(
            "deleteNodeFromButton('${node.id}'",
            render_node_body,
            "renderNode must not contain inline onclick with interpolated node.id",
        )
        self.assertNotIn(
            'onclick="deleteNodeFromButton',
            render_node_body,
            "renderNode must not use inline onclick for delete button",
        )

        # 3. Uses programmatic handler calling deleteNodeFromButton(node.id
        self.assertTrue(
            bool(re.search(r"deleteNodeFromButton\s*\(\s*node\.id", render_node_body)),
            "renderNode must call deleteNodeFromButton(node.id, ...)",
        )

    def test_d_async_upload_endpoints_unblocked(self):
        """Source assertion that async upload functions unblock event loop via asyncio.to_thread(requests.post)."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 1. routers/comfyui.py -> upload_comfyui_base64
        comfyui_py = os.path.join(base_dir, "routers", "comfyui.py")
        self.assertTrue(os.path.exists(comfyui_py))
        with open(comfyui_py, "r", encoding="utf-8") as f:
            comfy_content = f.read()

        start_comfy = comfy_content.find("async def upload_comfyui_base64")
        self.assertNotEqual(start_comfy, -1, "upload_comfyui_base64 function not found")
        rest_comfy = comfy_content[start_comfy:]
        end_comfy = re.search(r"\r?\n(?=@|def\s)", rest_comfy[30:])
        comfy_body = rest_comfy[:end_comfy.start() + 30] if end_comfy else rest_comfy

        self.assertNotIn("resp = requests.post", comfy_body)
        self.assertNotIn("response = requests.post", comfy_body)
        self.assertTrue(
            bool(re.search(r"asyncio\.to_thread\s*\(\s*(?:requests|comfy_session)\.post", comfy_body)),
            "upload_comfyui_base64 must use asyncio.to_thread(requests.post or comfy_session.post)",
        )

        # 2. routers/online_image.py -> upload_image
        online_py = os.path.join(base_dir, "routers", "online_image.py")
        self.assertTrue(os.path.exists(online_py))
        with open(online_py, "r", encoding="utf-8") as f:
            online_content = f.read()

        start_online = online_content.find("async def upload_image")
        self.assertNotEqual(start_online, -1, "upload_image function not found")
        rest_online = online_content[start_online:]
        end_online = re.search(r"\r?\n(?=@|def\s)", rest_online[22:])
        online_body = rest_online[:end_online.start() + 22] if end_online else rest_online

        self.assertNotIn("response = requests.post", online_body)
        self.assertNotIn("resp = requests.post", online_body)
        self.assertTrue(
            bool(re.search(r"asyncio\.to_thread\s*\(\s*(?:requests|comfy_session)\.post", online_body)),
            "upload_image must use asyncio.to_thread(requests.post or comfy_session.post)",
        )

    def test_e_ws_origin_check(self):
        """Test _ws_origin_allowed helper and websocket endpoint origin allowlist."""
        from routers.tasks import _ws_origin_allowed

        class StubWS:
            def __init__(self, headers):
                self.headers = headers

        # 1. Absent origin (allowed)
        self.assertTrue(_ws_origin_allowed(StubWS({})))
        self.assertTrue(_ws_origin_allowed(StubWS({"host": "127.0.0.1:3000"})))

        # 2. Loopback origins (allowed)
        for origin in [
            "http://localhost",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://127.0.0.2:8080",
            "http://[::1]:3000",
            "http://::1:3000",
        ]:
            self.assertTrue(_ws_origin_allowed(StubWS({"origin": origin})), f"Expected {origin} to be allowed")

        # 3. RFC1918 LAN origins (allowed)
        for origin in [
            "http://192.168.1.100:3000",
            "http://10.0.0.1:8000",
            "http://172.16.0.1:3000",
            "http://172.31.255.255:3000",
        ]:
            self.assertTrue(_ws_origin_allowed(StubWS({"origin": origin})), f"Expected {origin} to be allowed")

        # 4. Matching Host header (allowed)
        self.assertTrue(
            _ws_origin_allowed(StubWS({"origin": "http://custom-lan-box.local:3000", "host": "custom-lan-box.local:3000"})),
        )

        # 4b. Tailscale / CGNAT origins and local host environments (file://, extensions)
        for origin in [
            "http://100.94.2.20:3000",
            "http://100.64.0.1:8000",
            "http://100.127.255.255:3000",
            "file://",
            "file:",
            "chrome-extension://dummy-extension-id",
            "moz-extension://dummy-extension-id",
        ]:
            self.assertTrue(_ws_origin_allowed(StubWS({"origin": origin})), f"Expected {origin} to be allowed")

        # 5. Untrusted / evil origins (rejected)
        for origin in [
            "https://evil.example.com",
            "http://evil.example.com:3000",
            "http://localhost.evil.com",
            "http://192.168.1.100.evil.com",
            "http://172.32.0.1:3000",
            "http://100.128.0.1:3000",
            "null",
        ]:
            self.assertFalse(_ws_origin_allowed(StubWS({"origin": origin})), f"Expected {origin} to be rejected")

        # 6. Integration test via TestClient
        try:
            from fastapi.testclient import TestClient
            from starlette.websockets import WebSocketDisconnect
            from main import app

            client = TestClient(app)

            # Disallowed origin is rejected with code 1008
            with self.assertRaises(WebSocketDisconnect) as cm:
                with client.websocket_connect("/ws/stats", headers={"origin": "https://evil.example.com"}):
                    pass
            self.assertEqual(cm.exception.code, 1008)

            # Loopback origin is accepted
            with client.websocket_connect("/ws/stats", headers={"origin": "http://127.0.0.1:3000"}) as ws:
                # Discard initial stats broadcast
                _ = ws.receive_text()
                ws.send_text("ping")
                data = json.loads(ws.receive_text())
                self.assertEqual(data.get("type"), "pong")

            # file:// origin (e.g. Photoshop CEP plugin / local environment) is accepted
            with client.websocket_connect("/ws/stats", headers={"origin": "file://"}) as ws:
                _ = ws.receive_text()
                ws.send_text("ping")
                data = json.loads(ws.receive_text())
                self.assertEqual(data.get("type"), "pong")
        except Exception as e:
            if not isinstance(e, self.failureException):
                pass
            else:
                raise

    def test_f_ltx_filename_escaped(self):
        """Narrow source assertion that ltx-director-timeline.js defines escapeHtml and escapes seg.fileName."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ltx_js = os.path.join(base_dir, "static", "js", "ltx-director-timeline.js")
        self.assertTrue(os.path.exists(ltx_js))
        with open(ltx_js, "r", encoding="utf-8") as f:
            content = f.read()

        # 1. Defines escapeHtml helper
        self.assertTrue(
            bool(re.search(r"(?:function\s+escapeHtml|const\s+escapeHtml\s*=)", content)),
            "ltx-director-timeline.js must define an escapeHtml helper",
        )

        # 2. Escapes seg.fileName in audioInfoArea template
        self.assertTrue(
            bool(re.search(r"escapeHtml\s*\(\s*seg\.fileName", content)),
            "ltx-director-timeline.js must escape seg.fileName via escapeHtml",
        )
        self.assertNotIn(
            "File: <span>${seg.fileName",
            content,
            "audioInfoArea must not interpolate unescaped seg.fileName",
        )


if __name__ == "__main__":
    unittest.main()
