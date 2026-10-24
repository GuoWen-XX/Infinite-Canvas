import os
import sys
import ast
import unittest
from starlette.testclient import TestClient
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app
from core.providers import env_quote, env_unquote
from core.history_manager import _sanitize_value
from routers.common import get_global_loop, set_online_ws_manager

class TestRound15Fixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_p0_1_runninghub_test_connection_blocks_mismatched_host(self):
        with patch("routers.providers.load_api_providers", return_value=[{"id": "runninghub", "base_url": "https://www.runninghub.cn", "api_key": "stored_secret_key"}]):
            resp = self.client.post("/api/providers/test-connection", json={
                "provider_id": "runninghub",
                "protocol": "runninghub",
                "base_url": "https://attacker.example.com",
            })
            self.assertEqual(resp.status_code, 400)
            detail = resp.json().get("detail", "")
            self.assertIn("安全拦截：已保存的 API Key 绑定在域名", detail)
            self.assertIn("www.runninghub.cn", detail)
            self.assertIn("attacker.example.com", detail)

    def test_p0_1_runninghub_test_connection_blocks_private_ip(self):
        resp = self.client.post("/api/providers/test-connection", json={
            "provider_id": "runninghub",
            "protocol": "runninghub",
            "api_key": "explicit_key_for_test",
            "base_url": "http://127.0.0.1:8188",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("请求地址非法或受限", resp.json().get("detail", ""))

    def test_p2_1_env_quote_unquote_roundtrip(self):
        cases = [
            'ab"cd\\ef gh',
            'sk-1234567890abcdef',
            'key with spaces and # hashes',
            'complex"string\\with/slashes and \'single\' quotes',
            '',
            'normal_key',
        ]
        for val in cases:
            quoted = env_quote(val)
            unquoted = env_unquote(quoted)
            self.assertEqual(unquoted, val, f"Failed roundtrip for: {val}")

    def test_p2_2_long_prompt_preserved_in_history(self):
        long_english_prompt = ("A breathtaking, highly detailed landscape painting of rolling mountains and mist. " * 80)[:6000]
        sanitized_en, changed_en = _sanitize_value(long_english_prompt)
        self.assertFalse(changed_en)
        self.assertEqual(sanitized_en, long_english_prompt)

        long_chinese_prompt = ("赛博朋克未来城市，霓虹灯光在雨后街道倒映，充满生机与机械细节的构图。" * 150)[:6000]
        sanitized_zh, changed_zh = _sanitize_value(long_chinese_prompt)
        self.assertFalse(changed_zh)
        self.assertEqual(sanitized_zh, long_chinese_prompt)

    def test_p2_2_base64_blob_truncated_in_history(self):
        raw_b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk" * 120)[:6000]
        sanitized_b64, changed_b64 = _sanitize_value(raw_b64)
        self.assertTrue(changed_b64)
        self.assertIn("...[inline blob stripped", sanitized_b64)

        data_uri = "data:image/png;base64," + ("A" * 2000)
        sanitized_uri, changed_uri = _sanitize_value(data_uri)
        self.assertTrue(changed_uri)
        self.assertIn("...[inline blob stripped", sanitized_uri)

    def test_p2_3_core_layering_no_router_imports(self):
        core_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
        for fname in os.listdir(core_dir):
            if fname.endswith(".py"):
                fpath = os.path.join(core_dir, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=fpath)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            self.assertFalse(alias.name.startswith("routers"), f"{fname} imports {alias.name}")
                            self.assertNotEqual(alias.name, "main", f"{fname} imports main")
                    elif isinstance(node, ast.ImportFrom):
                        mod = node.module or ""
                        self.assertFalse(mod.startswith("routers"), f"{fname} imports from {mod}")
                        self.assertNotEqual(mod, "main", f"{fname} imports from main")

    def test_p2_4_rollback_gate_503_when_update_disabled(self):
        with patch("routers.system.EXECUTABLE_UPDATE_ENABLED", False):
            resp = self.client.post("/api/update-rollback", json={"name": "test_backup"})
            self.assertEqual(resp.status_code, 503)
            self.assertIn("在线可执行更新已禁用", resp.json().get("detail", ""))

    def test_p1_1_global_loop_dynamic_resolution(self):
        sentinel_loop = object()
        set_online_ws_manager(None, sentinel_loop)
        self.assertIs(get_global_loop(), sentinel_loop)
        set_online_ws_manager(None, None)
        self.assertIsNone(get_global_loop())

    def test_auth_token_query_sets_cookie_when_configured(self):
        with patch("main.get_configured_access_token", return_value="secret123"):
            resp_no_token = self.client.get("/api/providers")
            self.assertEqual(resp_no_token.status_code, 401)

            resp_token = self.client.get("/?token=secret123")
            self.assertIn("ic_access_token", resp_token.cookies)
            self.assertEqual(resp_token.cookies["ic_access_token"], "secret123")

if __name__ == "__main__":
    unittest.main()
