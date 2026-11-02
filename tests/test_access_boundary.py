"""S02: run locally with no external services or real account credentials."""
import base64
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

import main


class AccessBoundaryTests(unittest.TestCase):
    def test_default_cors_has_no_wildcard(self):
        self.assertNotIn("*", main.CANVAS_TRUSTED_ORIGINS)

    def test_local_testclient_can_use_api(self):
        with TestClient(main.app) as c:
            result = c.get("/api/models")
            self.assertEqual(result.status_code, 200, result.text[:200])

    def test_remote_is_denied_when_lan_not_explicitly_enabled(self):
        with patch.object(main, "CANVAS_LAN_ENABLED", False):
            status, _, _ = main.canvas_access_result(
                "192.168.1.29", "192.168.1.10:3000", {}, {}, "http")
            self.assertEqual(status, 403)

    def test_dns_rebinding_host_is_rejected_even_for_localhost(self):
        status, _, _ = main.canvas_access_result(
            "127.0.0.1", "attacker.example:3000", {}, {}, "http")
        self.assertEqual(status, 403)

    def test_untrusted_browser_origin_is_rejected_on_loopback(self):
        status, _, _ = main.canvas_access_result(
            "127.0.0.1", "127.0.0.1:3000",
            {"origin": "https://attacker.example"}, {}, "http")
        self.assertEqual(status, 403)

    def test_same_origin_is_accepted_on_loopback(self):
        status, _, _ = main.canvas_access_result(
            "127.0.0.1", "127.0.0.1:3000",
            {"origin": "http://127.0.0.1:3000"}, {}, "http")
        self.assertEqual(status, 0)

    def test_approved_extension_origin_can_access_localhost(self):
        origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
        with patch.object(main, "CANVAS_TRUSTED_ORIGINS", {origin}):
            status, _, _ = main.canvas_access_result(
                "127.0.0.1", "127.0.0.1:3000", {"origin": origin}, {}, "http")
            self.assertEqual(status, 0)

    def test_lan_requires_strong_secret_and_auth(self):
        with patch.object(main, "CANVAS_LAN_ENABLED", True):
            with patch.dict(os.environ, {"INFINITE_CANVAS_LAN_PASSWORD": "bad"}):
                status, _, _ = main.canvas_access_result(
                    "192.168.1.29", "192.168.1.10:3000", {}, {}, "http")
                self.assertEqual(status, 503)
            with patch.dict(os.environ, {"INFINITE_CANVAS_LAN_PASSWORD": "dummy-password-long"}):
                status, _, _ = main.canvas_access_result(
                    "192.168.1.29", "192.168.1.10:3000", {}, {}, "http")
                self.assertEqual(status, 401)
                basic = base64.b64encode(b"canvas:dummy-password-long").decode("ascii")
                status, _, grant = main.canvas_access_result(
                    "192.168.1.29", "192.168.1.10:3000",
                    {"authorization": "Basic " + basic}, {}, "http")
                self.assertEqual(status, 0)
                self.assertTrue(grant)
                cookie = main.canvas_new_session("dummy-password-long")
                status, _, _ = main.canvas_access_result(
                    "192.168.1.29", "192.168.1.10:3000", {},
                    {main.CANVAS_SESSION_NAME: cookie}, "http")
                self.assertEqual(status, 0)

    def test_malformed_basic_authorization_does_not_throw(self):
        self.assertFalse(main.canvas_basic_auth({"authorization": "Basic not-base64??"}, "dummy-password-long"))

    def test_expired_session_rejected(self):
        with patch("main.time.time", return_value=2_000_000):
            old_session = main.canvas_new_session("dummy-password-long")
        with patch("main.time.time", return_value=2_000_000 + main.CANVAS_SESSION_TTL + 10):
            self.assertFalse(main.canvas_valid_session(old_session, "dummy-password-long"))

    def test_http_middleware_blocks_unauthorized_read_and_mutation(self):
        # Stub the access decision; requests must not reach actual endpoints.
        with patch.object(main, "canvas_access_result", return_value=(401, "LAN auth required", False)):
            with TestClient(main.app) as client:
                get_result = client.get("/api/config/token")
                self.assertEqual(get_result.status_code, 401)
                self.assertIn("Basic", get_result.headers.get("www-authenticate", ""))
                post_result = client.post("/api/history/delete", json={"id": "dummy"})
                self.assertEqual(post_result.status_code, 401)

    def test_http_middleware_does_not_serve_api_to_foreign_origin(self):
        with TestClient(main.app) as client:
            result = client.get("/api/config/token", headers={"Origin": "https://attacker.example"})
            self.assertEqual(result.status_code, 403)

    def test_cross_origin_cookie_is_not_enough(self):
        password = "dummy-password-long"
        session = main.canvas_new_session(password)
        with patch.object(main, "CANVAS_LAN_ENABLED", True), \
             patch.dict(os.environ, {"INFINITE_CANVAS_LAN_PASSWORD": password}):
            status, _, _ = main.canvas_access_result(
                "192.168.1.20", "192.168.1.10:3000",
                {"origin": "https://attacker.example"},
                {main.CANVAS_SESSION_NAME: session}, "http")
            self.assertEqual(status, 403)

    def test_token_route_only_reports_presence(self):
        with patch.object(main, "modelscope_api_key", return_value="fake-unit-test-secret"):
            with TestClient(main.app) as client:
                res = client.get("/api/config/token")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json(), {"has_token": True, "token": ""})
                self.assertNotIn("fake-unit-test-secret", res.text)

    def test_modelscope_legacy_json_is_server_side_only(self):
        with tempfile.TemporaryDirectory() as td:
            old_file = os.path.join(td, "global_config.json")
            with open(old_file, "w", encoding="utf-8") as fh:
                fh.write('{"modelscope_token":"test-legacy-secret"}')
            with patch.object(main, "GLOBAL_CONFIG_FILE", old_file), \
                 patch.object(main, "provider_env_key_value", return_value=""), \
                 patch.object(main, "MODELSCOPE_API_KEY", ""):
                self.assertEqual(main.modelscope_api_key(), "test-legacy-secret")
                with TestClient(main.app) as client:
                    response = client.get("/api/config/token")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["token"], "")


if __name__ == "__main__":
    unittest.main()
