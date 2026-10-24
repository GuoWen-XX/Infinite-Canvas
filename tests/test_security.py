import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.security import (
    is_safe_remote_url,
    is_valid_comfy_address,
    validate_safe_url,
    safe_download_bytes,
)


class SecurityModuleTests(unittest.TestCase):
    def test_blocks_localhost_and_loopback(self):
        safe, reason = is_safe_remote_url("http://localhost:8000/api/test")
        self.assertFalse(safe)
        self.assertIn("本地或回环", reason)

        safe, _ = is_safe_remote_url("http://127.0.0.1:8000/")
        self.assertFalse(safe)

    def test_blocks_cloud_metadata_service(self):
        safe, reason = is_safe_remote_url("http://169.254.169.254/latest/meta-data/")
        self.assertFalse(safe)
        self.assertIn("受限内网 IP", reason)

    def test_blocks_cloud_metadata_even_with_allow_private(self):
        # 169.254.169.254 (AWS/GCP/Alibaba) must be blocked even if allow_private=True
        safe, reason = is_safe_remote_url("http://169.254.169.254/latest/meta-data/", allow_private=True)
        self.assertFalse(safe)
        self.assertIn("受限内网 IP", reason)

        # 100.100.100.200 (Alibaba Cloud metadata) must also be blocked
        safe, reason = is_safe_remote_url("http://100.100.100.200/latest/meta-data/", allow_private=True)
        self.assertFalse(safe)
        self.assertIn("受限内网 IP", reason)

        # metadata.google.internal must be blocked
        safe, reason = is_safe_remote_url("http://metadata.google.internal/computeMetadata/v1/", allow_private=True)
        self.assertFalse(safe)
        self.assertIn("受限内网 IP", reason)

        # But normal localhost / LAN address must be allowed when allow_private=True
        safe, _ = is_safe_remote_url("http://127.0.0.1:8188/", allow_private=True)
        self.assertTrue(safe)
        safe, _ = is_safe_remote_url("http://localhost:8188/", allow_private=True)
        self.assertTrue(safe)

    def test_blocks_private_networks(self):
        safe, _ = is_safe_remote_url("http://192.168.1.1/admin")
        self.assertFalse(safe)

        safe, _ = is_safe_remote_url("http://10.0.0.1/dashboard")
        self.assertFalse(safe)

        safe, _ = is_safe_remote_url("http://172.16.0.5/api")
        self.assertFalse(safe)

    def test_blocks_non_http_schemes(self):
        safe, reason = is_safe_remote_url("file:///etc/passwd")
        self.assertFalse(safe)
        self.assertIn("不支持的协议方案", reason)

        safe, _ = is_safe_remote_url("gopher://127.0.0.1:6379/")
        self.assertFalse(safe)

    def test_blocks_userinfo_confusion(self):
        safe, reason = is_safe_remote_url("http://admin:pass@example.com/test")
        self.assertFalse(safe)
        self.assertIn("混淆字符 @", reason)

        safe, _ = is_safe_remote_url("http://user@169.254.169.254/test")
        self.assertFalse(safe)

    def test_allows_safe_external_urls(self):
        # We test with a well-known public host like dashscope.aliyuncs.com or example.com
        safe, _ = is_safe_remote_url("https://dashscope.aliyuncs.com/api/test")
        self.assertTrue(safe)

    def test_validates_comfy_addresses(self):
        self.assertTrue(is_valid_comfy_address("127.0.0.1:8188"))
        self.assertTrue(is_valid_comfy_address("localhost:8188"))
        self.assertTrue(is_valid_comfy_address("my-comfy-server:8000"))
        self.assertTrue(is_valid_comfy_address("192.168.1.50"))

        # Injections
        self.assertFalse(is_valid_comfy_address("attacker.com@127.0.0.1:8188"))
        self.assertFalse(is_valid_comfy_address("127.0.0.1:8188/path/injection"))
        self.assertFalse(is_valid_comfy_address("127.0.0.1:8188?arg=1"))
        self.assertFalse(is_valid_comfy_address(""))

    def test_csrf_middleware_blocks_foreign_origin(self):
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        # Foreign Origin attempting a POST request must be blocked with 403
        resp = client.post(
            "/api/storage-files/delete",
            json={"items": []},
            headers={"Origin": "https://evil-attacker.com"}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("CSRF protection", resp.json().get("detail", ""))

    def test_csrf_middleware_allows_local_origin(self):
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        # Local origin passes CSRF guard
        resp = client.post(
            "/api/storage-files/delete",
            json={"items": []},
            headers={"Origin": "http://127.0.0.1:3000"}
        )
        self.assertNotEqual(resp.status_code, 403)

    def test_validate_safe_url_raises_on_restricted_ip(self):
        with self.assertRaises(ValueError) as ctx:
            validate_safe_url("http://127.0.0.1:8000/internal")
        self.assertIn("SSRF 拦截", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            validate_safe_url("http://169.254.169.254/latest/meta-data/")
        self.assertIn("SSRF 拦截", str(ctx.exception))

        # Safe URL returns normalized string
        url = validate_safe_url("https://dashscope.aliyuncs.com/api/test")
        self.assertEqual(url, "https://dashscope.aliyuncs.com/api/test")

    def test_safe_download_bytes_blocks_ssrf(self):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with self.assertRaises(ValueError) as ctx:
                loop.run_until_complete(safe_download_bytes("http://127.0.0.1:9999/secret.png"))
            self.assertIn("SSRF 拦截", str(ctx.exception))
        finally:
            loop.close()

    def test_safe_download_bytes_stream_max_bytes_limit(self):
        import asyncio
        from unittest.mock import AsyncMock, patch, MagicMock
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def fake_aiter():
                yield b"A" * 1000
                yield b"B" * 1000

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {"Content-Type": "image/png"}  # no Content-Length
            mock_resp.raise_for_status = MagicMock()
            mock_resp.aclose = AsyncMock()
            mock_resp.aiter_bytes = MagicMock(return_value=fake_aiter())

            with patch("httpx.AsyncClient.send", new=AsyncMock(return_value=mock_resp)):
                with self.assertRaises(ValueError) as ctx:
                    loop.run_until_complete(safe_download_bytes(
                        "https://example.com/stream.bin",
                        max_bytes=1500,
                        allowed_hosts=["example.com"]
                    ))
                self.assertIn("超出大小限制", str(ctx.exception))
        finally:
            loop.close()

    def test_sanitize_secret_tokens(self):
        from core.security import sanitize_secret_tokens
        # URL query params
        raw_url = "https://api.example.com/v1/generate?key=AIzaSySecretKey123&prompt=hello"
        cleaned_url = sanitize_secret_tokens(raw_url)
        self.assertNotIn("AIzaSySecretKey123", cleaned_url)
        self.assertIn("key=***MASKED***", cleaned_url)

        # Authorization header
        auth_str = "Error from upstream: Bearer sk-live-1234567890abcdef"
        cleaned_auth = sanitize_secret_tokens(auth_str)
        self.assertNotIn("sk-live-1234567890abcdef", cleaned_auth)
        self.assertIn("Bearer ***MASKED***", cleaned_auth)

        # Standalone sk- token
        key_str = "Failed to authenticate with sk-proj-1234567890abcdefghijkl"
        cleaned_key = sanitize_secret_tokens(key_str)
        self.assertNotIn("1234567890abcdef", cleaned_key)
        self.assertIn("sk-pro****jkl", cleaned_key)


if __name__ == "__main__":
    unittest.main()

