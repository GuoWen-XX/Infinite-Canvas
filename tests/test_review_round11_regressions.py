import ast
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from core.security import (
    get_configured_proxy_ips,
    is_ip_restricted,
    sanitize_secret_tokens,
)
from core.providers import (
    mask_secret,
    key_looks_masked,
    strip_auth_scheme,
    FIELD_LABELS,
)
from routers.online_image import (
    CANVAS_TASKS,
    CANVAS_TASK_LOCK,
    MAX_CANVAS_TASKS,
    _prune_canvas_tasks_locked,
)


class TestReviewRound11Regressions(unittest.TestCase):
    def test_b1_proxy_peer_ip_detection(self):
        """B1: get_configured_proxy_ips must accurately detect proxy IPs from environment and system."""
        # Test with simulated environment variables
        orig_http = os.environ.get("HTTP_PROXY")
        try:
            os.environ["HTTP_PROXY"] = "http://127.0.0.1:7897"
            proxies = get_configured_proxy_ips()
            self.assertIn("127.0.0.1", proxies)
            self.assertIn("localhost", proxies)
        finally:
            if orig_http is not None:
                os.environ["HTTP_PROXY"] = orig_http
            else:
                os.environ.pop("HTTP_PROXY", None)

    def test_b1_safe_download_bytes_peer_ip_proxy_vs_direct(self):
        """B1: peer IP check should permit proxy peer IP when proxy is configured, and block when unconfigured."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from core.security import safe_download_bytes

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/png", "Content-Length": "4"}
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aclose = AsyncMock()

        async def aiter_bytes(chunk_size=65536):
            yield b"test"

        mock_resp.aiter_bytes = aiter_bytes

        # Configure mock stream with peer IP 127.0.0.1 (simulating proxy connection)
        mock_stream = MagicMock()
        mock_stream.get_extra_info.return_value = ("127.0.0.1", 7897)
        mock_resp.extensions = {"network_stream": mock_stream}

        async def run_test():
            with patch("httpx.AsyncClient.send", new=AsyncMock(return_value=mock_resp)):
                # 1. When proxy is configured in environment: 127.0.0.1 peer is recognized as proxy and allowed
                with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:7897"}):
                    content, ctype = await safe_download_bytes("https://httpbin.org/image/png")
                    self.assertEqual(content, b"test")

                # 2. When NO proxy is configured: 127.0.0.1 peer is blocked as restricted SSRF
                with patch.dict(os.environ, {}, clear=True), patch("urllib.request.getproxies", return_value={}):
                    with self.assertRaises(ValueError) as cm:
                        await safe_download_bytes("https://httpbin.org/image/png")
                    self.assertIn("远程连接对端 IP 受限 (127.0.0.1)", str(cm.exception))

        asyncio.run(run_test())

    def test_b3_cli_key_sanitization(self):
        """B3: sanitize_secret_tokens must mask --api-key and --key command line arguments."""
        cmd = "gpt-image-2 images generate --provider openai --api-key sk-abc1234567890xyz --model gpt-image-2"
        sanitized = sanitize_secret_tokens(cmd)
        self.assertNotIn("sk-abc1234567890xyz", sanitized)
        self.assertIn("--api-key ***MASKED***", sanitized)

        cmd2 = "tool.exe --key secret_token_12345678"
        sanitized2 = sanitize_secret_tokens(cmd2)
        self.assertNotIn("secret_token_12345678", sanitized2)
        self.assertIn("--key ***MASKED***", sanitized2)

    def test_b5_no_duplicate_top_level_definitions_in_core_and_routers(self):
        """B5: AST verification - no top-level function or class definitions should be duplicated."""
        dirs_to_check = [ROOT / "core", ROOT / "routers"]
        duplicates_found = []

        for folder in dirs_to_check:
            for py_file in folder.glob("*.py"):
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
                seen_names = {}
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        name = node.name
                        if name in seen_names:
                            duplicates_found.append(f"{py_file.name}: '{name}' defined at line {seen_names[name]} and line {node.lineno}")
                        else:
                            seen_names[name] = node.lineno

        self.assertEqual(duplicates_found, [], f"Found duplicate definitions: {duplicates_found}")

    def test_b5_key_looks_masked_comprehensive(self):
        """B5: key_looks_masked should recognize bullet, asterisk, and ellipsis mask formats."""
        self.assertTrue(key_looks_masked("••••••••1234"))
        self.assertTrue(key_looks_masked("****1234"))
        self.assertTrue(key_looks_masked("********1234"))
        self.assertTrue(key_looks_masked("abc…def"))
        self.assertTrue(key_looks_masked("????????1234"))
        self.assertFalse(key_looks_masked("sk-proj-1234567890abcdef"))
        self.assertFalse(key_looks_masked(""))

    def test_b6_canvas_task_pruning(self):
        """B6: _prune_canvas_tasks_locked must bound task cache size."""
        with CANVAS_TASK_LOCK:
            orig_tasks = dict(CANVAS_TASKS)
            try:
                CANVAS_TASKS.clear()
                # Insert completed tasks exceeding MAX_CANVAS_TASKS
                for i in range(MAX_CANVAS_TASKS + 50):
                    CANVAS_TASKS[f"task_{i}"] = {
                        "id": f"task_{i}",
                        "status": "succeeded",
                        "updated_at": i,
                    }
                self.assertEqual(len(CANVAS_TASKS), MAX_CANVAS_TASKS + 50)
                _prune_canvas_tasks_locked()
                self.assertEqual(len(CANVAS_TASKS), MAX_CANVAS_TASKS)
                # Oldest tasks (0..49) should have been pruned
                self.assertNotIn("task_0", CANVAS_TASKS)
                self.assertIn(f"task_{MAX_CANVAS_TASKS + 49}", CANVAS_TASKS)
            finally:
                CANVAS_TASKS.clear()
                CANVAS_TASKS.update(orig_tasks)

    def test_f2_all_html_files_include_escape_js(self):
        """F2: All 15 static HTML files must include escape.js for unified XSS/URL protection."""
        static_dir = ROOT / "static"
        html_files = list(static_dir.glob("*.html"))
        self.assertEqual(len(html_files), 15, "Expected 15 static HTML files")

        missing = []
        for html_file in html_files:
            content = html_file.read_text(encoding="utf-8")
            if "static/js/utils/escape.js" not in content:
                missing.append(html_file.name)

        self.assertEqual(missing, [], f"HTML files missing escape.js: {missing}")


if __name__ == "__main__":
    unittest.main()
