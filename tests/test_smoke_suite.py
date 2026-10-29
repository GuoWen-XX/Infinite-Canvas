import sys
import os
import json
import time
import asyncio
import unittest
import requests
try:
    import websockets
except ImportError:
    websockets = None

BASE_URL = os.getenv("IC_SMOKE_BASE_URL", "http://127.0.0.1:3333").rstrip("/")
WS_URL = os.getenv("IC_SMOKE_WS_URL") or (BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/ws/stats")


def _is_server_reachable():
    try:
        r = requests.get(f"{BASE_URL}/api/canvases", timeout=0.5)
        return r.status_code == 200
    except Exception:
        return False


@unittest.skipUnless(_is_server_reachable(), f"Infinite-Canvas server is not running on {BASE_URL}")
class FullSmokeTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure server is up
        for _ in range(10):
            try:
                r = requests.get(f"{BASE_URL}/api/canvases", timeout=2)
                if r.status_code == 200:
                    break
            except Exception:
                time.sleep(0.5)

    # 1. Server Core Info
    def test_01_core_endpoints(self):
        print("\n[SMOKE] 1. Testing Core Endpoints...")
        r_root = requests.get(f"{BASE_URL}/", timeout=5)
        self.assertEqual(r_root.status_code, 200)
        self.assertIn("<html", r_root.text.lower())

        r_info = requests.get(f"{BASE_URL}/api/app-info", timeout=5)
        self.assertEqual(r_info.status_code, 200)
        self.assertIn("version", r_info.json())

        r_config = requests.get(f"{BASE_URL}/api/config", timeout=5)
        self.assertEqual(r_config.status_code, 200)

        r_models = requests.get(f"{BASE_URL}/api/models", timeout=5)
        self.assertEqual(r_models.status_code, 200)

        r_providers = requests.get(f"{BASE_URL}/api/providers", timeout=5)
        self.assertEqual(r_providers.status_code, 200)
        print("  -> Core endpoints OK")

    # 2. Decoupled Canvas & Project Management (All 15 endpoints)
    def test_02_canvas_and_project_lifecycle(self):
        print("\n[SMOKE] 2. Testing Decoupled Canvas & Project Endpoints...")
        # 1. Projects
        r_proj = requests.get(f"{BASE_URL}/api/projects", timeout=5)
        self.assertEqual(r_proj.status_code, 200)
        self.assertIn("projects", r_proj.json())

        # Create project
        r_cproj = requests.post(f"{BASE_URL}/api/projects", json={"name": "Smoke Project"}, timeout=5)
        self.assertEqual(r_cproj.status_code, 200)
        proj_id = r_cproj.json()["project"]["id"]

        # Update project
        r_uproj = requests.post(f"{BASE_URL}/api/projects/{proj_id}", json={"name": "Smoke Project Renamed", "order": 10}, timeout=5)
        self.assertEqual(r_uproj.status_code, 200)
        self.assertEqual(r_uproj.json()["project"]["name"], "Smoke Project Renamed")

        # Create Canvas in project
        r_canvas = requests.post(f"{BASE_URL}/api/canvases", json={
            "title": "Smoke Canvas",
            "icon": "zap",
            "kind": "classic",
            "project": proj_id
        }, timeout=5)
        self.assertEqual(r_canvas.status_code, 200)
        canvas_id = r_canvas.json()["canvas"]["id"]

        try:
            # List canvases
            r_list = requests.get(f"{BASE_URL}/api/canvases", timeout=5)
            self.assertEqual(r_list.status_code, 200)
            ids = [c["id"] for c in r_list.json()["canvases"]]
            self.assertIn(canvas_id, ids)

            # Get Canvas
            r_get = requests.get(f"{BASE_URL}/api/canvases/{canvas_id}", timeout=5)
            self.assertEqual(r_get.status_code, 200)
            self.assertEqual(r_get.json()["canvas"]["id"], canvas_id)

            # Get Meta
            r_meta = requests.get(f"{BASE_URL}/api/canvases/{canvas_id}/meta", timeout=5)
            self.assertEqual(r_meta.status_code, 200)
            self.assertEqual(r_meta.json()["id"], canvas_id)

            # Update Meta
            r_umeta = requests.post(f"{BASE_URL}/api/canvases/{canvas_id}/meta", json={
                "title": "Smoke Canvas Updated",
                "color": "blue",
                "pinned": True
            }, timeout=5)
            self.assertEqual(r_umeta.status_code, 200)
            self.assertEqual(r_umeta.json()["canvas"]["title"], "Smoke Canvas Updated")

            # Touch
            r_touch = requests.post(f"{BASE_URL}/api/canvases/{canvas_id}/touch", timeout=5)
            self.assertEqual(r_touch.status_code, 200)

            # PUT update
            r_put = requests.put(f"{BASE_URL}/api/canvases/{canvas_id}", json={
                "title": "Smoke Canvas Graph Saved",
                "nodes": [{"id": "n1", "type": "prompt", "x": 50, "y": 50}],
                "connections": [],
                "viewport": {"x": 0, "y": 0, "scale": 1},
                "logs": [],
                "settings": {}
            }, timeout=5)
            self.assertEqual(r_put.status_code, 200)
            self.assertEqual(len(r_put.json()["canvas"]["nodes"]), 1)

            # PUT conflict
            r_conflict = requests.put(f"{BASE_URL}/api/canvases/{canvas_id}", json={
                "title": "Conflict",
                "base_updated_at": 100,
                "nodes": [],
                "connections": []
            }, timeout=5)
            self.assertEqual(r_conflict.status_code, 409)

            # Soft Delete
            r_del = requests.delete(f"{BASE_URL}/api/canvases/{canvas_id}", timeout=5)
            self.assertEqual(r_del.status_code, 200)

            # Check Trash
            r_trash = requests.get(f"{BASE_URL}/api/canvases/trash", timeout=5)
            self.assertEqual(r_trash.status_code, 200)
            trash_ids = [c["id"] for c in r_trash.json()["canvases"]]
            self.assertIn(canvas_id, trash_ids)

            # Restore
            r_restore = requests.post(f"{BASE_URL}/api/canvases/{canvas_id}/restore", timeout=5)
            self.assertEqual(r_restore.status_code, 200)
            self.assertIsNone(r_restore.json()["canvas"].get("deleted_at"))

        finally:
            # Purge
            r_purge = requests.delete(f"{BASE_URL}/api/canvases/{canvas_id}/purge", timeout=5)
            self.assertEqual(r_purge.status_code, 200)
            # Delete Project
            r_dproj = requests.delete(f"{BASE_URL}/api/projects/{proj_id}", timeout=5)
            self.assertEqual(r_dproj.status_code, 200)

        print("  -> Decoupled canvas & project endpoints 100% OK")

    # 3. Canvas Assets
    def test_03_canvas_assets(self):
        print("\n[SMOKE] 3. Testing Canvas Assets Index...")
        r_assets = requests.get(f"{BASE_URL}/api/canvas-assets", timeout=10)
        self.assertEqual(r_assets.status_code, 200)
        data = r_assets.json()
        self.assertIn("items", data)
        self.assertIn("categories", data)
        self.assertIn("canvases", data)

        r_check = requests.post(f"{BASE_URL}/api/canvas-assets/check", json={"urls": []}, timeout=5)
        self.assertEqual(r_check.status_code, 200)
        print("  -> Canvas assets OK")

    # 4. Task Center & History
    def test_04_task_center(self):
        print("\n[SMOKE] 4. Testing Task Center & History...")
        r_hist = requests.get(f"{BASE_URL}/api/task-history?limit=5", timeout=5)
        self.assertEqual(r_hist.status_code, 200)
        self.assertIn("tasks", r_hist.json())

        r_stats = requests.get(f"{BASE_URL}/api/task-stats?days=7", timeout=5)
        self.assertEqual(r_stats.status_code, 200)

        r_history = requests.get(f"{BASE_URL}/api/history?limit=10", timeout=5)
        self.assertEqual(r_history.status_code, 200)

        r_queue = requests.get(f"{BASE_URL}/api/queue_status?client_id=smoke_client", timeout=5)
        self.assertEqual(r_queue.status_code, 200)
        print("  -> Task center & history OK")

    # 5. Static Pages Delivery
    def test_05_static_pages(self):
        print("\n[SMOKE] 5. Testing Static Page Delivery...")
        pages = [
            "index.html",
            "canvas.html",
            "smart-canvas.html",
            "canvas-list.html",
            "api-settings.html",
            "asset-manager.html",
            "comfyui-settings.html",
            "enhance.html",
            "online.html",
            "angle.html",
            "zimage.html",
            "klein.html",
            "gpt-chat.html",
        ]
        for p in pages:
            # Root alias
            r1 = requests.get(f"{BASE_URL}/{p}", timeout=5)
            self.assertEqual(r1.status_code, 200, f"Failed to load root alias {p}")
            # /static/ path
            r2 = requests.get(f"{BASE_URL}/static/{p}", timeout=5)
            self.assertEqual(r2.status_code, 200, f"Failed to load /static/{p}")
        print(f"  -> All {len(pages)} static pages OK via both / and /static/")

    # 6. WebSocket Connectivity
    @unittest.skipIf(websockets is None, "websockets package not installed")
    def test_06_websocket_ping_pong(self):
        print("\n[SMOKE] 6. Testing WebSocket Ping/Pong...")
        async def _test_ws():
            async with websockets.connect(f"{WS_URL}?client_id=smoke_test_client") as ws:
                await ws.send("ping")
                # Server sends initial 'stats' broadcast, then 'pong' for 'ping'
                got_pong = False
                for _ in range(5):
                    raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    msg = json.loads(raw)
                    if msg.get("type") == "pong":
                        got_pong = True
                        break
                self.assertTrue(got_pong, "Did not receive pong from websocket")
        asyncio.run(_test_ws())
        print("  -> WebSocket connected and ping/pong replied OK")

    # 7. Aesthetics & Typography
    def test_07_typography_contract(self):
        print("\n[SMOKE] 7. Testing Typography Aesthetics...")
        r_css = requests.get(f"{BASE_URL}/static/css/canvas.css", timeout=5)
        self.assertEqual(r_css.status_code, 200)
        illegal_weights = ["950", "900", "850", "750"]
        for w in illegal_weights:
            self.assertNotIn(f"font-weight: {w}", r_css.text, f"Illegal font weight {w} in canvas.css")
            self.assertNotIn(f"font-weight:{w}", r_css.text, f"Illegal font weight {w} in canvas.css")
        print("  -> Typography aesthetic contract OK (no illegal font weights)")

    # 8. SSRF Protection
    def test_08_ssrf_protection(self):
        print("\n[SMOKE] 8. Testing SSRF Protection...")
        attacks = [
            "http://127.0.0.1:3000/api/canvases",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.1/admin",
            "file:///etc/passwd"
        ]
        for url in attacks:
            r = requests.get(f"{BASE_URL}/api/download-output", params={"url": url}, timeout=5)
            self.assertIn(r.status_code, (400, 403), f"SSRF url {url} was not blocked: status={r.status_code}")
        print("  -> SSRF attack targets blocked OK")

if __name__ == "__main__":
    unittest.main()
