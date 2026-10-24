import unittest
import asyncio
import os
import re
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from core.security import (
    is_safe_remote_url,
    validate_safe_url,
    safe_download_bytes,
    pin_host_dns,
    unpin_host_dns,
    clear_safe_dns_cache,
    _SAFE_DNS_CACHE,
    _extract_peer_ip,
    is_ip_restricted,
)
from routers.video import router as video_router
from routers.online_image import yuli_fetch_reference_bytes
from routers.integrations import runninghub_store_remote_output
from routers.common import save_ai_image_to_output, save_remote_video_to_output
from main import app as main_app

ROOT = Path(__file__).resolve().parent.parent

class TestReviewRound10Regressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()
        cls.app.include_router(video_router)
        cls.client = TestClient(cls.app)
        cls.main_client = TestClient(main_app)

    def test_minimax_export_validation_order(self):
        """B-P0-1: Empty clips must return 400 before checking for ffmpeg binary."""
        resp = self.client.post("/api/smart-canvas/minimax-export", json={"clips": []})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("还没有可导出的视频", resp.json().get("detail", ""))

    def test_dns_pinning_cache_scoped_lifecycle(self):
        """B-P2-1-mod: validate_safe_url must NOT pollute _SAFE_DNS_CACHE; pin/unpin must be scoped."""
        clear_safe_dns_cache()
        url = "https://httpbin.org/status/200"
        # 1. Normal validation does not pollute global cache
        validate_safe_url(url, allow_private=False)
        self.assertNotIn("httpbin.org", _SAFE_DNS_CACHE)

        # 2. Explicit scoped pin and unpin with ref counting
        mock_addr = [(2, 1, 6, "", ("93.184.216.34", 443))]
        pin_host_dns("test.example.com", mock_addr)
        self.assertIn("test.example.com", _SAFE_DNS_CACHE)
        pin_host_dns("test.example.com", mock_addr)  # ref count = 2
        unpin_host_dns("test.example.com")           # ref count = 1
        self.assertIn("test.example.com", _SAFE_DNS_CACHE)
        unpin_host_dns("test.example.com")           # ref count = 0 -> removed
        self.assertNotIn("test.example.com", _SAFE_DNS_CACHE)

        # 3. clear_safe_dns_cache
        pin_host_dns("another.example.com", mock_addr)
        clear_safe_dns_cache()
        self.assertEqual(len(_SAFE_DNS_CACHE), 0)

    def test_yuli_reference_fetch_ssrf_blocked(self):
        """B-P1-1: yuli_fetch_reference_bytes must block SSRF URLs."""
        async def run():
            # Cloud metadata
            res = await yuli_fetch_reference_bytes(None, "http://169.254.169.254/latest/meta-data")
            self.assertIsNone(res)
            # Localhost
            res2 = await yuli_fetch_reference_bytes(None, "http://127.0.0.1:8080/secret")
            self.assertIsNone(res2)
        asyncio.run(run())

    def test_runninghub_store_remote_output_ssrf_blocked(self):
        """B-P1-3: runninghub_store_remote_output must safely handle invalid or SSRF metadata URLs."""
        async def run():
            # Cloud metadata
            res = await runninghub_store_remote_output(None, "http://169.254.169.254/secret")
            # Should fail safely without downloading
            self.assertEqual(res, "http://169.254.169.254/secret")
        asyncio.run(run())

    def test_save_ai_image_and_video_ssrf_blocked(self):
        """B-P1-4: save_ai_image_to_output and save_remote_video_to_output must safely handle SSRF."""
        async def run():
            # Image SSRF metadata
            res = await save_ai_image_to_output({"type": "url", "value": "http://169.254.169.254/secret"})
            self.assertEqual(res, "http://169.254.169.254/secret")

            # Video SSRF metadata
            res_vid = await save_remote_video_to_output("http://169.254.169.254/secret.mp4")
            self.assertEqual(res_vid, "http://169.254.169.254/secret.mp4")
        asyncio.run(run())

    def test_no_wildcard_imports_in_main(self):
        """B-P3-1: main.py must not contain wildcard 'from core.providers import *'."""
        main_path = ROOT / "main.py"
        content = main_path.read_text(encoding="utf-8")
        self.assertNotIn("from core.providers import *", content)
        self.assertIn("from core.providers import (", content)

    def test_frontend_escape_util_and_legacy_pages_xss_protection(self):
        """F-P1-1 & F-P3-1: escape.js must exist and 5 legacy pages must use safeMediaUrl & escapeHtml."""
        escape_js_path = ROOT / "static" / "js" / "utils" / "escape.js"
        self.assertTrue(escape_js_path.exists())
        escape_js = escape_js_path.read_text(encoding="utf-8")
        self.assertIn("function escapeHtml", escape_js)
        self.assertIn("function safeMediaUrl", escape_js)

        pages = ["zimage.html", "online.html", "enhance.html", "klein.html", "angle.html"]
        for page in pages:
            page_path = ROOT / "static" / page
            self.assertTrue(page_path.exists(), f"{page} missing")
            content = page_path.read_text(encoding="utf-8")
            self.assertIn("static/js/utils/escape.js", content, f"{page} missing escape.js inclusion")
            self.assertIn("safeMediaUrl", content, f"{page} missing safeMediaUrl in renderImageCard")

    def test_iframe_sandbox_attributes_present(self):
        """F-P2-1: 11 stage iframes in index.html and about iframe in api-settings.html must have sandbox."""
        index_html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        # Check that all 11 frame-* iframes have sandbox
        frame_ids = [
            "frame-zimage", "frame-enhance", "frame-klein", "frame-angle",
            "frame-online", "frame-gpt-chat", "frame-asset-manager",
            "frame-api-settings", "frame-comfyui-settings", "frame-canvas", "frame-about"
        ]
        for fid in frame_ids:
            pattern = rf'<iframe id="{fid}"[^>]*sandbox="[^"]*"[^>]*>'
            self.assertIsNotNone(re.search(pattern, index_html), f"{fid} missing sandbox in index.html")

        # Check api-settings.html about iframe
        api_settings_html = (ROOT / "static" / "api-settings.html").read_text(encoding="utf-8")
        self.assertIn('sandbox="allow-scripts allow-same-origin allow-forms allow-downloads allow-modals allow-popups"', api_settings_html)

    def test_security_headers_middleware_present(self):
        """B-P3-2: Responses from main app must contain security hardening headers."""
        resp = self.main_client.get("/api/config")
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(resp.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertEqual(resp.headers.get("Permissions-Policy"), "camera=(), microphone=(), geolocation=()")
        # B12-4: CSP now defines an explicit policy (default-src + script-src etc.),
        # not just frame-ancestors. Assert the security-critical directives are present
        # rather than an exact string so the policy can evolve without brittle churn.
        csp = resp.headers.get("Content-Security-Policy", "")
        for directive in (
            "default-src 'self'",
            "script-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "frame-ancestors 'self'",
        ):
            self.assertIn(directive, csp)

    def test_gpt_chat_attachment_xss_protection(self):
        """F-P2-1-mod & F-P1-1: gpt-chat.html must sanitize ref.url with safeMediaUrl."""
        gpt_chat_path = ROOT / "static" / "gpt-chat.html"
        self.assertTrue(gpt_chat_path.exists())
        content = gpt_chat_path.read_text(encoding="utf-8")
        self.assertIn("safeMediaUrl(ref.url)", content)
        self.assertNotIn('src="${escapeHtml(ref.url)}"', content)

    def test_pollinations_download_uses_safe_download(self):
        """B-P1-4-mod: online_image.py Pollinations generation must use safe_download_bytes with limits."""
        online_image_path = ROOT / "routers" / "online_image.py"
        content = online_image_path.read_text(encoding="utf-8")
        # Ensure Pollinations section uses safe_download_bytes
        self.assertIn("image_bytes, content_type = await safe_download_bytes(", content)
        self.assertIn("max_bytes=50 * 1024 * 1024", content)
        # Ensure bare httpx client is not used in generate_pollinations_provider_image
        self.assertNotIn("async with httpx.AsyncClient(timeout=240, follow_redirects=True) as client:", content)

if __name__ == "__main__":
    unittest.main()
