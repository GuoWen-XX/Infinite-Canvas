"""S02: run locally with no external services or real account credentials."""
import base64
import os
import urllib.parse
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

    def test_loopback_reverse_proxy_cannot_bypass_lan_auth(self):
        # Reverse proxy TCP peer is 127.0.0.1, but requested LAN Host is remote.
        with patch.object(main, "CANVAS_LAN_ENABLED", True), \
             patch.dict(os.environ, {"INFINITE_CANVAS_LAN_PASSWORD": "dummy-password-long"}):
            status, _, _ = main.canvas_access_result(
                "127.0.0.1", "192.168.1.10:3000", {}, {}, "http")
            self.assertEqual(status, 401)
        with patch.object(main, "CANVAS_LAN_ENABLED", False):
            status, _, _ = main.canvas_access_result(
                "127.0.0.1", "192.168.1.10:3000", {}, {}, "http")
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

    def test_unicode_basic_password_matches_as_utf8(self):
        password = "中文验证密码abcd123456"
        basic = base64.b64encode(("canvas:" + password).encode("utf-8")).decode("ascii")
        self.assertTrue(main.canvas_basic_auth({"authorization": "Basic " + basic}, password))
        wrong = base64.b64encode("canvas:错误密码abcd123456".encode("utf-8")).decode("ascii")
        self.assertFalse(main.canvas_basic_auth({"authorization": "Basic " + wrong}, password))

    def test_cors_list_is_loaded_after_project_env(self):
        # Regression for early initialization: API/.env is read at import,
        # so middleware must be registered only after load_env_file().
        from pathlib import Path
        source = Path(main.__file__).read_text(encoding="utf-8")
        self.assertLess(source.index("\nload_env_file()\n"), source.index("\napp.add_middleware(\n    CORSMiddleware"))
        middleware = next(m for m in main.app.user_middleware if m.cls.__name__ == "CORSMiddleware")
        self.assertEqual(set(middleware.kwargs["allow_origins"]), main.CANVAS_TRUSTED_ORIGINS)

    def test_signed_media_token_is_bound_to_one_file_and_short_lived(self):
        secret = "test-only-s02-media-signing-key-" + "a" * 32
        path = "/assets/input/test-reference.png"
        with patch.dict(os.environ, {"PUBLIC_MEDIA_TOKEN": secret}):
            with patch("main.time.time", return_value=10_000_000):
                suffix = main.public_media_url_suffix(path)
            self.assertNotIn(secret, suffix)
            query = urllib.parse.parse_qs(suffix.lstrip("?"))
            exp, sig = query["ic_exp"][0], query["ic_sig"][0]
            self.assertTrue(main.canvas_signed_public_media_valid(path, exp, sig, now=10_000_003))
            self.assertFalse(main.canvas_signed_public_media_valid("/assets/input/another.png", exp, sig, now=10_000_003))
            self.assertFalse(main.canvas_signed_public_media_valid(path, exp, sig, now=int(exp) + 1))
            self.assertFalse(main.canvas_signed_public_media_valid(path, exp, sig, now=10_000_000 - 3600))
            self.assertFalse(main.canvas_signed_public_media_valid(path, exp, "0"*64, now=10_000_003))
            self.assertFalse(main.canvas_signed_public_media_valid("/api/config/token", exp, sig, now=10_000_003))
            self.assertFalse(main.canvas_signed_public_media_valid("/assets/../global_config.json", exp, sig, now=10_000_003))
            self.assertFalse(main.canvas_signed_public_media_valid("/assets/%252e%252e/global_config.json", exp, sig, now=10_000_003))
            self.assertFalse(main.canvas_signed_public_media_valid("/assets/foo\\\\secret.png", exp, sig, now=10_000_003))

    def test_signed_path_distinguishes_literal_hash_and_question_mark(self):
        key = "test-path-signing-key-" + "z"*40
        with patch.dict(os.environ, {"PUBLIC_MEDIA_TOKEN": key}), patch("main.time.time", return_value=10_000_000):
            q = urllib.parse.parse_qs(main.public_media_url_suffix("/assets/a.png").lstrip("?"))
            exp, sig = q["ic_exp"][0], q["ic_sig"][0]
            # ASGI has decoded '%23' and '%3F' once. Neither is a URL
            # delimiter at this stage; the signature must not truncate them.
            self.assertFalse(main.canvas_signed_public_media_valid("/assets/a.png#private.png", exp, sig, now=10_000_010))
            self.assertFalse(main.canvas_signed_public_media_valid("/assets/a.png?private.png", exp, sig, now=10_000_010))
            for url_path, asgi_path in [
                ("/assets/a%23private.png", "/assets/a#private.png"),
                ("/assets/a%3Fprivate.png", "/assets/a?private.png"),
            ]:
                signed = urllib.parse.parse_qs(main.public_media_url_suffix(url_path).lstrip("?"))
                self.assertTrue(main.canvas_signed_public_media_valid(
                    asgi_path, signed["ic_exp"][0], signed["ic_sig"][0], now=10_000_010
                ))

    def test_public_media_url_encodes_literal_percent_filename(self):
        key = "test-percent-signing-key-" + "z"*40
        with patch.dict(os.environ, {"PUBLIC_MEDIA_TOKEN": key}), patch("main.time.time", return_value=10_000_000), \
             patch.object(main, "output_file_from_url", return_value="/test-only/mock-file.png"), \
             patch.object(main, "public_base_url", return_value="https://media.example"):
            url = main.local_asset_public_url("/assets/ref%2520final.mp4")
            parsed = urllib.parse.urlsplit(url)
            self.assertEqual(parsed.path, "/assets/ref%2520final.mp4")
            query = urllib.parse.parse_qs(parsed.query)
            # Actual ASGI path is decoded only once, to a literal '%20'.
            self.assertTrue(main.canvas_signed_public_media_valid(
                urllib.parse.unquote(parsed.path), query["ic_exp"][0], query["ic_sig"][0], now=10_000_010
            ))
            self.assertFalse(main.canvas_signed_public_media_valid(
                "/assets/ref final.mp4", query["ic_exp"][0], query["ic_sig"][0], now=10_000_010
            ))

    def test_without_public_media_secret_cannot_generate_signed_url(self):
        with patch.dict(os.environ, {"PUBLIC_MEDIA_TOKEN": ""}):
            self.assertEqual(main.public_media_url_suffix("/output/image.png"), "")
            self.assertFalse(main.canvas_signed_public_media_valid("/output/image.png", "9999999999", "0"*64))

    def test_signed_media_middleware_uses_actual_asgi_path_for_hash_and_question(self):
        # Starlette Request.url.path reconstructs a URL from scope['path'];
        # urlsplit then truncates literal '#'/'?' in decoded filenames.
        # StaticFiles serves scope['path'], so signatures must bind to it.
        secret = "test-only-s02-media-signing-key-" + "a"*32
        with patch.dict(os.environ, {"PUBLIC_MEDIA_TOKEN": secret}), \
             patch("main.time.time", return_value=10_000_000), \
             patch.object(main, "canvas_trusted_host", return_value=True), \
             patch.object(main, "canvas_access_result", return_value=(401, "LAN auth required", False)):
            signed_plain = main.public_media_url_suffix("/assets/a.png")
            with TestClient(main.app) as client:
                for encoded in ("/assets/a.png%23private.png", "/assets/a.png%3Fprivate.png"):
                    # Reusing a.png's valid signature for a different actual
                    # StaticFiles path must fail at the HTTP boundary.
                    denied = client.get(encoded + signed_plain)
                    self.assertEqual(denied.status_code, 401, (encoded, denied.text[:200]))
                    own = main.public_media_url_suffix(encoded)
                    allowed = client.get(encoded + own)
                    # The test-only file does not exist, so reaching StaticFiles
                    # produces 404 instead of the authentication middleware's 401.
                    self.assertEqual(allowed.status_code, 404, (encoded, allowed.text[:200]))

    def test_signed_media_does_not_bypass_other_http_routes(self):
        secret = "test-only-s02-media-signing-key-" + "a"*32
        with patch.dict(os.environ, {"PUBLIC_MEDIA_TOKEN": secret}), patch("main.time.time", return_value=10_000_000):
            suffix = main.public_media_url_suffix("/output/dummy.png")
            with patch.object(main, "canvas_trusted_host", return_value=True), patch.object(main, "canvas_access_result", return_value=(401, "LAN auth required", False)):
                with TestClient(main.app) as client:
                    # Signed media should reach StaticFiles, which 404s on
                    # non-existent dummy media, not authentication middleware.
                    allowed = client.get("/output/dummy.png" + suffix)
                    self.assertEqual(allowed.status_code, 404)
                    denied = client.get("/output/dummy.png")
                    self.assertEqual(denied.status_code, 401)
                    api = client.get("/api/config/token" + suffix)
                    self.assertEqual(api.status_code, 401)

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


    def test_lan_real_http_middleware_requires_basic_then_session(self):
        password = "test-s02-password-long"
        basic = base64.b64encode(("canvas:" + password).encode("utf-8")).decode("ascii")
        with patch.object(main, "CANVAS_LAN_ENABLED", True), \
             patch.dict(os.environ, {"INFINITE_CANVAS_LAN_PASSWORD": password}), \
             patch.object(main, "modelscope_api_key", return_value="test-only-s02-secret"):
            with TestClient(main.app, base_url="http://192.168.1.10:3000") as client:
                denied = client.get("/api/config/token")
                self.assertEqual(denied.status_code, 401)
                approved = client.get("/api/config/token", headers={"Authorization": "Basic " + basic})
                self.assertEqual(approved.status_code, 200)
                self.assertEqual(approved.json(), {"has_token": True, "token": ""})
                self.assertIn("httponly", approved.headers.get("set-cookie", "").lower())
                self.assertIn("samesite=strict", approved.headers.get("set-cookie", "").lower())
                session = client.get("/api/config/token")
                self.assertEqual(session.status_code, 200)
                self.assertNotIn("test-only-s02-secret", session.text)

    def test_websocket_rejects_foreign_origin_at_real_asgi_boundary(self):
        from starlette.websockets import WebSocketDisconnect
        with TestClient(main.app) as client:
            with self.assertRaises(WebSocketDisconnect) as caught:
                with client.websocket_connect("/ws/stats", headers={"Origin": "https://attacker.example"}):
                    pass
            self.assertEqual(caught.exception.code, 1008)

    def test_websocket_rejects_unauthenticated_lan_at_real_asgi_boundary(self):
        from starlette.websockets import WebSocketDisconnect
        with patch.object(main, "CANVAS_LAN_ENABLED", True), \
             patch.dict(os.environ, {"INFINITE_CANVAS_LAN_PASSWORD": "test-s02-password-long"}):
            with TestClient(main.app, base_url="http://192.168.1.10:3000") as client:
                with self.assertRaises(WebSocketDisconnect) as caught:
                    # Starlette's websocket_connect defaults to testserver even
                    # when the HTTP TestClient has a LAN base_url.
                    with client.websocket_connect("/ws/stats", headers={"Host": "192.168.1.10:3000"}):
                        pass
                self.assertEqual(caught.exception.code, 1008)

    def test_websocket_lan_accepts_valid_session_at_real_asgi_boundary(self):
        password = "test-s02-password-long"
        with patch.object(main, "CANVAS_LAN_ENABLED", True), \
             patch.dict(os.environ, {"INFINITE_CANVAS_LAN_PASSWORD": password}):
            session = main.canvas_new_session(password)
            # Starlette TestClient does not automatically forward the HTTP
            # cookie jar to WebSocket; provide the valid session explicitly.
            headers = {
                "Host": "192.168.1.10:3000",
                "Cookie": f"{main.CANVAS_SESSION_NAME}={session}",
            }
            with TestClient(main.app, base_url="http://192.168.1.10:3000") as client:
                with client.websocket_connect("/ws/stats", headers=headers):
                    pass

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
