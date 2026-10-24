import os
import sys
import unittest
from starlette.testclient import TestClient
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app

class TestReviewRound14Regressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_comfyui_unreachable_returns_503(self):
        import requests
        with patch("routers.comfyui.reserve_best_backend", return_value="127.0.0.1:8188"), \
             patch("routers.comfyui.comfy_session.post", side_effect=requests.exceptions.ConnectionError("Connection refused")), \
             patch("routers.comfyui.requests.post", side_effect=requests.exceptions.ConnectionError("Connection refused")):
            resp = self.client.post("/api/generate", json={
                "type": "txt2img",
                "client_id": "test_client",
                "workflow_json": {"3": {"class_type": "KSampler", "inputs": {}}},
                "params": {}
            })
            self.assertEqual(resp.status_code, 503)
            self.assertIn("ComfyUI 本地服务未启动或不可达", resp.json().get("detail", ""))

    def test_02_comfyui_timeout_returns_503(self):
        import requests
        with patch("routers.comfyui.reserve_best_backend", return_value="127.0.0.1:8188"), \
             patch("routers.comfyui.comfy_session.post", side_effect=requests.exceptions.Timeout("Read timed out")), \
             patch("routers.comfyui.requests.post", side_effect=requests.exceptions.Timeout("Read timed out")):
            resp = self.client.post("/api/generate", json={
                "type": "txt2img",
                "client_id": "test_client",
                "workflow_json": {"3": {"class_type": "KSampler", "inputs": {}}},
                "params": {}
            })
            self.assertEqual(resp.status_code, 503)
            self.assertIn("ComfyUI 本地服务未启动或不可达", resp.json().get("detail", ""))

    def test_03_comfyui_connection_refused_exception_returns_503(self):
        with patch("routers.comfyui.reserve_best_backend", return_value="127.0.0.1:8188"), \
             patch("routers.comfyui.comfy_session.post", side_effect=Exception("Failed to establish a new connection: Connection refused")), \
             patch("routers.comfyui.requests.post", side_effect=Exception("Failed to establish a new connection: Connection refused")):
            resp = self.client.post("/api/generate", json={
                "type": "txt2img",
                "client_id": "test_client",
                "workflow_json": {"3": {"class_type": "KSampler", "inputs": {}}},
                "params": {}
            })
            self.assertEqual(resp.status_code, 503)
            self.assertIn("ComfyUI 本地服务未启动或不可达", resp.json().get("detail", ""))

    def test_04_canvas_meta_optimistic_concurrency_409(self):
        create_resp = self.client.post("/api/canvases", json={"title": "Meta 409 Test"})
        self.assertEqual(create_resp.status_code, 200)
        canvas_id = create_resp.json()["canvas"]["id"]
        created_at = create_resp.json()["canvas"]["updated_at"]

        try:
            # 1. Stale update with base_updated_at < current updated_at must fail with 409
            stale_resp = self.client.post(f"/api/canvases/{canvas_id}/meta", json={
                "title": "Stale Title",
                "base_updated_at": created_at - 1000
            })
            self.assertEqual(stale_resp.status_code, 409)
            detail = stale_resp.json().get("detail", {})
            self.assertIn("画布元数据已被其他页面更新", detail.get("message", ""))
            self.assertEqual(detail.get("updated_at"), created_at)

            # 2. Fresh update with matching or None base_updated_at must succeed
            ok_resp = self.client.post(f"/api/canvases/{canvas_id}/meta", json={
                "title": "Updated Title",
                "base_updated_at": created_at
            })
            self.assertEqual(ok_resp.status_code, 200)
            self.assertEqual(ok_resp.json()["canvas"]["title"], "Updated Title")
        finally:
            self.client.delete(f"/api/canvases/{canvas_id}/purge")

    def test_05_mobile_push_fails_with_500_on_disk_error(self):
        create_resp = self.client.post("/api/canvases", json={"title": "Mobile Push Test"})
        self.assertEqual(create_resp.status_code, 200)
        canvas_id = create_resp.json()["canvas"]["id"]

        try:
            with patch("routers.canvas.save_canvas", side_effect=IOError("Simulated disk write failure")):
                resp = self.client.post("/api/canvas/mobile-push", json={
                    "url": "https://example.com/mobile-image.png",
                    "name": "Mobile Test Image",
                    "canvas_id": canvas_id
                })
                self.assertEqual(resp.status_code, 500)
                self.assertIn("保存推送到画布失败", resp.json().get("detail", ""))
                self.assertIn("Simulated disk write failure", resp.json().get("detail", ""))
        finally:
            self.client.delete(f"/api/canvases/{canvas_id}/purge")

    def test_06_rhino_capture_thread_safety(self):
        import concurrent.futures
        import routers.canvas as canvas_mod

        self.assertTrue(hasattr(canvas_mod, "RHINO_LOCK"), "RHINO_LOCK must exist in routers.canvas")

        # 1x1 transparent PNG
        tiny_png = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )

        created_files = []

        def post_capture(idx):
            r = self.client.post("/api/canvas/rhino-capture", json={
                "image_base64": tiny_png,
                "view_name": f"View_{idx}",
                "timestamp": 1700000000000 + idx
            })
            if r.status_code == 200:
                cap = r.json().get("capture", {})
                if cap.get("id"):
                    created_files.append(f"{cap['id']}.png")
            return r

        def get_latest():
            return self.client.get("/api/canvas/rhino-capture/latest")

        errors = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for i in range(16):
                futures.append(executor.submit(post_capture, i))
                futures.append(executor.submit(get_latest))
            for f in concurrent.futures.as_completed(futures):
                try:
                    res = f.result()
                    self.assertIn(res.status_code, (200, 201))
                except Exception as e:
                    errors.append(e)

        try:
            self.assertEqual(len(errors), 0, f"Concurrent Rhino capture calls produced errors: {errors}")
            latest_res = self.client.get("/api/canvas/rhino-capture/latest")
            self.assertEqual(latest_res.status_code, 200)
            self.assertIsNotNone(latest_res.json().get("capture"))
        finally:
            # Clean up uploaded test files
            for fname in created_files:
                fpath = os.path.join(canvas_mod.RHINO_UPLOAD_DIR, fname)
                if os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass

    def test_07_mobile_push_cold_start_empty_canvas_list(self):
        created_canvas_id = None
        try:
            with patch("routers.canvas.list_canvases", return_value=[]):
                resp = self.client.post("/api/canvas/mobile-push", json={
                    "url": "https://example.com/cold-start-image.png",
                    "name": "Cold Start Image",
                    "canvas_id": ""
                })
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertTrue(data.get("ok"))
                self.assertTrue(data.get("node_id"))
                created_canvas_id = data.get("canvas_id")
                self.assertTrue(created_canvas_id)
                self.assertEqual(data.get("canvas_title"), "移动端创作")

                # Verify canvas was actually created and contains the pushed node
                get_resp = self.client.get(f"/api/canvases/{created_canvas_id}")
                self.assertEqual(get_resp.status_code, 200)
                nodes = get_resp.json().get("canvas", {}).get("nodes", [])
                self.assertEqual(len(nodes), 1)
                self.assertEqual(nodes[0]["url"], "https://example.com/cold-start-image.png")
                self.assertEqual(nodes[0]["title"], "Cold Start Image")
        finally:
            if created_canvas_id:
                self.client.delete(f"/api/canvases/{created_canvas_id}/purge")

    def test_08_deep_recursive_base64_sanitization(self):
        from core.history_manager import _sanitize_record_blobs
        big_b64 = "data:image/png;base64," + "A" * 5000
        rec = {
            "type": "txt2img",
            "params": {
                "image": big_b64,
                "nested": {
                    "mask": big_b64,
                    "list_of_items": [big_b64, {"inner_control": big_b64}]
                }
            }
        }
        cleaned, changed = _sanitize_record_blobs(rec)
        self.assertTrue(changed)
        self.assertIn("[inline blob stripped", cleaned["params"]["image"])
        self.assertIn("[inline blob stripped", cleaned["params"]["nested"]["mask"])
        self.assertIn("[inline blob stripped", cleaned["params"]["nested"]["list_of_items"][0])
        self.assertIn("[inline blob stripped", cleaned["params"]["nested"]["list_of_items"][1]["inner_control"])

    def test_09_zero_literal_emojis_in_frontend(self):
        import re
        emoji_pattern = re.compile(r'[\U00010000-\U0010ffff]')
        for path in ["static/js/canvas.js", "static/js/canvas-list.js"]:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            emojis = emoji_pattern.findall(content)
            self.assertEqual(emojis, [], f"Found literal emojis in {path}: {emojis}")

    def test_10_image_preview_alt_and_event_delegation(self):
        with open("static/js/canvas.js", "r", encoding="utf-8") as f:
            canvas_js = f.read()
        self.assertIn("handleCanvasPreviewImageError", canvas_js)
        self.assertIn("addEventListener('error', handleCanvasPreviewImageError, true)", canvas_js)
        self.assertIn('alt="image"', canvas_js)
        self.assertIn('alt="video preview"', canvas_js)

        with open("static/js/smart-canvas.js", "r", encoding="utf-8") as f:
            smart_js = f.read()
        self.assertIn('alt="image"', smart_js)
        self.assertIn('alt="video preview"', smart_js)

    def test_11_canvas_i18n_keys_convergence(self):
        import re
        with open("static/js/i18n/canvas.js", "r", encoding="utf-8") as f:
            i18n_content = f.read()
        required_keys = [
            "canvas.modelApi",
            "canvas.aiApp",
            "canvas.workflow",
            "canvas.emptyImage",
            "canvas.imageLoadFailed",
            "canvas.imageFetchFailed",
            "canvas.requestFailed",
            "canvas.iconSaveFailed",
            "canvas.renameFailed",
            "canvas.addInput",
            "canvas.addOutput",
            "canvas.preview",
            "canvas.edit",
            "canvas.replace",
            "canvas.alignLeft",
            "canvas.exportToLibrary",
            "canvas.workflowImportFailed",
            "canvas.mobilePush",
        ]
        for key in required_keys:
            self.assertIn(f'"{key}"', i18n_content, f"Missing i18n key {key}")
            # Ensure both zh and en entries exist for key
            match = re.search(rf'"{re.escape(key)}":\s*\{{\s*zh:\s*"([^"]+)",\s*en:\s*"([^"]+)"\s*\}}', i18n_content)
            self.assertIsNotNone(match, f"Key {key} does not have both zh and en translations")
            self.assertTrue(len(match.group(1)) > 0)
            self.assertTrue(len(match.group(2)) > 0)

if __name__ == "__main__":
    unittest.main()


