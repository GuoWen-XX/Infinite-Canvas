import unittest
import inspect
from pathlib import Path
from fastapi.testclient import TestClient

from main import app
import routers.online_image as oi
import routers.integrations as integrations
import routers.assets as assets
import routers.video as video

ROOT = Path(__file__).resolve().parent.parent

class TestReviewRound13Regressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_r13_1_safe_download_image_uses_safe_download_bytes(self):
        """R13-1: _safe_download_image_to_local must use safe_download_bytes with allow_private=False."""
        src = inspect.getsource(oi._safe_download_image_to_local)
        self.assertIn("safe_download_bytes", src)
        self.assertIn("allow_private=False", src)
        self.assertNotIn("follow_redirects=True", src)

    def test_r13_1_runninghub_store_remote_output_no_private_allow(self):
        """R13-1 secondary: runninghub_store_remote_output must set allow_private=False."""
        src = inspect.getsource(integrations.runninghub_store_remote_output)
        self.assertIn("safe_download_bytes", src)
        self.assertIn("allow_private=False", src)
        self.assertNotIn("allow_private=True", src)

    def test_r13_1_assets_fetch_remote_media_bytes_uses_safe_download(self):
        """R13-1 extension: fetch_remote_media_bytes in assets router must use safe_download_bytes."""
        src = inspect.getsource(assets.fetch_remote_media_bytes)
        self.assertIn("safe_download_bytes", src)
        self.assertIn("allow_private=False", src)
        self.assertNotIn("requests.get", src)

    def test_r13_1_video_yuli_reference_uses_safe_download(self):
        """R13-1 extension: yuli_fetch_reference_bytes in video router must use safe_download_bytes."""
        src = inspect.getsource(video.yuli_fetch_reference_bytes)
        self.assertIn("safe_download_bytes", src)
        self.assertIn("allow_private=False", src)
        self.assertNotIn("client.get", src)

    def test_r13_2_csp_no_unsafe_eval(self):
        """R13-2 note: CSP script-src must not allow unsafe-eval."""
        resp = self.client.get("/api/config")
        csp = resp.headers.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self' 'unsafe-inline';", csp)
        self.assertNotIn("unsafe-eval", csp)

    def test_r13_2_tailwind_config_safelist(self):
        """R13-2: tailwind.config.js must define safelist for dynamic classes."""
        cfg_path = ROOT / "tools" / "tailwind-build" / "tailwind.config.js"
        self.assertTrue(cfg_path.exists())
        content = cfg_path.read_text(encoding="utf-8")
        self.assertIn("safelist:", content)
        self.assertIn("grid-cols", content)

    def test_r13_3_chrome_extension_webrequest_constrained(self):
        """R13-3: background.js webRequest listener must specify resource types."""
        bg_path = ROOT / "tools" / "chrome-local-asset-importer" / "background.js"
        self.assertTrue(bg_path.exists())
        content = bg_path.read_text(encoding="utf-8")
        self.assertIn("types: ['xmlhttprequest', 'media', 'other']", content)

if __name__ == "__main__":
    unittest.main()
