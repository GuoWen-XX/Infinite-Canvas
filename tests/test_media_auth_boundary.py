"""Audit F04: /output/ and /assets/ must honour IC_ACCESS_TOKEN (opt-out via IC_PUBLIC_MEDIA=1)."""
import os
import sys
import unittest
import uuid
from unittest.mock import patch

from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app  # noqa: E402
from core.providers import ASSETS_DIR, OUTPUT_DIR  # noqa: E402


class TestMediaTokenBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.name = f"audit-boundary-{uuid.uuid4().hex[:8]}.txt"
        cls.paths = [os.path.join(OUTPUT_DIR, cls.name), os.path.join(ASSETS_DIR, cls.name)]
        for p in cls.paths:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write("synthetic")

    @classmethod
    def tearDownClass(cls):
        for p in cls.paths:
            if os.path.isfile(p):
                os.remove(p)

    def test_media_requires_token_when_configured(self):
        with patch("main.get_configured_access_token", return_value="secret123"):
            for prefix in ("/output/", "/assets/"):
                anon = self.client.get(prefix + self.name)
                self.assertEqual(anon.status_code, 401, prefix)
                ok = self.client.get(prefix + self.name, headers={"x-access-token": "secret123"})
                self.assertEqual(ok.status_code, 200, prefix)
                self.assertIn("private", ok.headers.get("cache-control", ""))
                cookie_client = TestClient(app, cookies={"ic_access_token": "secret123"})
                self.assertEqual(cookie_client.get(prefix + self.name).status_code, 200)

    def test_media_open_when_no_token_configured(self):
        with patch("main.get_configured_access_token", return_value=""):
            self.assertEqual(self.client.get("/output/" + self.name).status_code, 200)

    def test_public_media_opt_out(self):
        with patch("main.get_configured_access_token", return_value="secret123"), \
                patch.dict(os.environ, {"IC_PUBLIC_MEDIA": "1"}):
            self.assertEqual(self.client.get("/assets/" + self.name).status_code, 200)

    def test_static_pages_stay_public(self):
        with patch("main.get_configured_access_token", return_value="secret123"):
            self.assertNotEqual(self.client.get("/static/css/canvas.css").status_code, 401)


if __name__ == "__main__":
    unittest.main()
