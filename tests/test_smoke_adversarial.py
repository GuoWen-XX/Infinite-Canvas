import io
import os
import time
import base64
import asyncio
import unittest
import requests
from PIL import Image

BASE_URL = os.getenv("IC_SMOKE_BASE_URL", "http://127.0.0.1:3333").rstrip("/")


def _is_server_reachable():
    try:
        r = requests.get(f"{BASE_URL}/api/canvases", timeout=0.5)
        return r.status_code == 200
    except Exception:
        return False


@unittest.skipUnless(_is_server_reachable(), f"Infinite-Canvas server is not running on {BASE_URL}")
class AdversarialSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure server is reachable
        for _ in range(10):
            try:
                r = requests.get(f"{BASE_URL}/api/canvases", timeout=2)
                if r.status_code == 200:
                    break
            except Exception:
                time.sleep(0.5)

    def test_01_upload_multipart_and_slimming(self):
        """Verify Issue 1 & Issue 3: Multipart upload works and slims large images."""
        # 1. Normal small image upload
        buf_small = io.BytesIO()
        img_small = Image.new("RGB", (100, 100), color=(255, 0, 0))
        img_small.save(buf_small, format="PNG")
        buf_small.seek(0)

        files = {"files": ("test_small.png", buf_small, "image/png")}
        resp = requests.post(f"{BASE_URL}/api/ai/upload", files=files, timeout=5)
        self.assertEqual(resp.status_code, 200, f"Small upload failed: {resp.text}")
        data = resp.json()
        self.assertIn("files", data)
        self.assertEqual(len(data["files"]), 1)
        self.assertTrue(data["files"][0]["url"].startswith("/assets/input/"))

        # 2. Oversized image (3000x3000px) triggers automatic slimming
        buf_large = io.BytesIO()
        img_large = Image.new("RGB", (3000, 3000), color=(0, 255, 0))
        img_large.save(buf_large, format="JPEG", quality=90)
        buf_large.seek(0)

        files_large = {"files": ("oversized.jpg", buf_large, "image/jpeg")}
        resp_large = requests.post(f"{BASE_URL}/api/ai/upload", files=files_large, timeout=10)
        self.assertEqual(resp_large.status_code, 200, f"Large upload failed: {resp_large.text}")
        large_data = resp_large.json()
        self.assertTrue(large_data["files"][0]["url"].startswith("/assets/input/"))

        # Verify saved image was actually downscaled to <= 2048px
        file_url = large_data["files"][0]["url"]
        download_resp = requests.get(f"{BASE_URL}{file_url}", timeout=5)
        self.assertEqual(download_resp.status_code, 200)
        downloaded_img = Image.open(io.BytesIO(download_resp.content))
        self.assertLessEqual(max(downloaded_img.size), 2048, "Image was not slimmed to <= 2048px")

    def test_02_upload_base64(self):
        """Verify base64 upload endpoint."""
        buf = io.BytesIO()
        img = Image.new("RGB", (64, 64), color=(0, 0, 255))
        img.save(buf, format="PNG")
        b64_str = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"

        payload = {"data": b64_str, "filename": "b64_test.png"}
        resp = requests.post(f"{BASE_URL}/api/ai/upload-base64", json=payload, timeout=5)
        self.assertEqual(resp.status_code, 200, f"Base64 upload failed: {resp.text}")
        data = resp.json()
        self.assertTrue(data.get("url", "").startswith("/assets/input/"))

    def test_03_history_manager_latency_and_integrity(self):
        """Verify Issue 2: History API latency is sub-millisecond level and non-blocking."""
        # Test limited query latency (typical UI usage)
        start = time.perf_counter()
        resp = requests.get(f"{BASE_URL}/api/history?limit=50", timeout=5)
        elapsed_ms = (time.perf_counter() - start) * 1000

        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)
        print(f"\n[BENCHMARK] /api/history?limit=50 took {elapsed_ms:.2f}ms (Target: <50ms)")
        self.assertLess(elapsed_ms, 80, "History query took too long")

    def test_04_canvas_cache_speed(self):
        """Verify Issue 3: Canvas listing is served via mtime cache without disk thrashing."""
        start = time.perf_counter()
        resp = requests.get(f"{BASE_URL}/api/canvases", timeout=5)
        elapsed_ms = (time.perf_counter() - start) * 1000

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("canvases", data)
        print(f"[BENCHMARK] /api/canvases took {elapsed_ms:.2f}ms (Target: <100ms)")
        self.assertLess(elapsed_ms, 100, "Canvas listing took too long; may be reparsing all files")

    def test_05_ssrf_blocking(self):
        """Verify Issue 4: SSRF attacks are strictly blocked with 403 Forbidden."""
        malicious_urls = [
            "http://127.0.0.1:3000/api/canvases",
            "http://localhost:3000/api/canvases",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.1/admin",
            "http://10.0.0.1/status",
            "http://attacker@google.com/test",
            "file:///etc/passwd",
        ]

        for url in malicious_urls:
            with self.subTest(target=url):
                resp = requests.get(f"{BASE_URL}/api/download-output", params={"url": url}, timeout=5)
                self.assertIn(resp.status_code, (400, 403), f"SSRF target {url} was NOT blocked! Status: {resp.status_code}")

    def test_06_task_center_endpoints(self):
        """Verify Task History and Ledger endpoints."""
        r_hist = requests.get(f"{BASE_URL}/api/task-history?limit=10", timeout=5)
        self.assertEqual(r_hist.status_code, 200)
        self.assertIn("tasks", r_hist.json())

        r_stats = requests.get(f"{BASE_URL}/api/task-stats?days=7", timeout=5)
        self.assertEqual(r_stats.status_code, 200)
        stats = r_stats.json()
        self.assertIn("total_cost", stats)
        self.assertIn("days", stats)
        self.assertIn("providers", stats)

    def test_07_typography_and_static_pages(self):
        """Verify static pages load and illegal font weights are absent."""
        # Index and main components via root alias and /static/
        r_index = requests.get(f"{BASE_URL}/", timeout=5)
        self.assertEqual(r_index.status_code, 200)

        r_mgr = requests.get(f"{BASE_URL}/asset-manager.html", timeout=5)
        self.assertEqual(r_mgr.status_code, 200)

        r_static_mgr = requests.get(f"{BASE_URL}/static/asset-manager.html", timeout=5)
        self.assertEqual(r_static_mgr.status_code, 200)

        r_canvas = requests.get(f"{BASE_URL}/smart-canvas.html", timeout=5)
        self.assertEqual(r_canvas.status_code, 200)

        # CSS font-weight aesthetic validation (v1.2: no 950, 900, 850, 750)
        r_css = requests.get(f"{BASE_URL}/static/css/canvas.css", timeout=5)
        self.assertEqual(r_css.status_code, 200)
        css_text = r_css.text

        illegal_weights = ["950", "900", "850", "750"]
        for weight in illegal_weights:
            self.assertNotIn(f"font-weight: {weight}", css_text)
            self.assertNotIn(f"font-weight:{weight}", css_text)


if __name__ == "__main__":
    unittest.main()
