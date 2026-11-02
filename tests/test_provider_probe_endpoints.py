"""S01 endpoint regression tests. All secrets, providers and network calls are mocked."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import main


class ProviderProbeEndpointSecurityTests(unittest.TestCase):
    def setUp(self):
        self.providers = [
            {"id": "demo", "base_url": "https://approved.example/v1", "enabled": True, "protocol": "openai"},
            {"id": "runninghub", "base_url": "https://rh-approved.example", "enabled": True, "protocol": "runninghub"},
            {"id": "volcengine", "base_url": "https://ark-approved.example", "enabled": True, "protocol": "volcengine"},
        ]
        p = patch.object(main, "load_api_providers", return_value=self.providers)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(main, "provider_env_key_value", return_value="test-saved-key")
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(main, "runninghub_wallet_key_value", return_value="test-saved-wallet")
        p.start()
        self.addCleanup(p.stop)

    def test_put_cannot_rebind_saved_key_to_new_url_without_rekey(self):
        payload = main.ApiProviderPayload(id="demo", base_url="https://attacker.example/v1", protocol="openai")
        with patch.object(main, "save_api_providers", side_effect=AssertionError("must not write config")) as save:
            with self.assertRaises(main.HTTPException) as exc:
                asyncio.run(main.save_providers([payload]))
            self.assertEqual(exc.exception.status_code, 400)
            save.assert_not_called()

    def test_put_cannot_rebind_runninghub_wallet_by_rekeying_free_key(self):
        payload = main.ApiProviderPayload(
            id="runninghub", base_url="https://attacker.example",
            protocol="runninghub", api_key="test-replacement-free-key",
        )
        with patch.object(main, "save_api_providers", side_effect=AssertionError("must not write config")) as save:
            with self.assertRaises(main.HTTPException) as exc:
                asyncio.run(main.save_providers([payload]))
            self.assertEqual(exc.exception.status_code, 400)
            save.assert_not_called()

    def test_saved_key_rejected_for_changed_provider_url(self):
        payload = main.TestConnectionPayload(base_url="https://attacker.example/v1", provider_id="demo")
        with self.assertRaises(main.HTTPException) as exc:
            main.api_key_from_payload(payload)
        self.assertEqual(exc.exception.status_code, 400)

    def test_accepted_saved_key_for_configured_url(self):
        payload = main.TestConnectionPayload(base_url="https://approved.example/v1/", provider_id="demo")
        self.assertEqual(main.api_key_from_payload(payload), "test-saved-key")

    def test_temporary_key_can_use_new_url(self):
        payload = main.TestConnectionPayload(base_url="https://other.example/v1", provider_id="demo", api_key="test-temporary-key")
        self.assertEqual(main.api_key_from_payload(payload), "test-temporary-key")

    def test_all_untrusted_probe_routes_reject_before_network_io(self):
        payload = main.TestConnectionPayload(base_url="https://attacker.example", provider_id="demo", protocol="openai")
        routes = [
            main.test_provider_connection,
            main.probe_async_endpoint,
            main.fetch_upstream_models_from_payload,
        ]
        with patch.object(main.httpx, "AsyncClient", side_effect=AssertionError("network must not be called")) as client:
            for route in routes:
                with self.subTest(route=route.__name__), self.assertRaises(main.HTTPException) as exc:
                    asyncio.run(route(payload))
                self.assertEqual(exc.exception.status_code, 400)
            client.assert_not_called()

    def test_volcengine_cannot_borrow_global_key_by_protocol_alone(self):
        payload = main.TestConnectionPayload(base_url="https://attacker.example", protocol="volcengine", provider_id="")
        self.assertEqual(main.api_key_from_payload(payload, "volcengine"), "")
        with patch.object(main.httpx, "AsyncClient", side_effect=AssertionError("network must not be called")) as client:
            with self.assertRaises(main.HTTPException) as exc:
                asyncio.run(main.fetch_upstream_models_from_payload(payload))
            self.assertEqual(exc.exception.status_code, 400)
            client.assert_not_called()

    def test_runninghub_saved_wallet_never_leaves_saved_destination(self):
        payload = main.TestConnectionPayload(base_url="https://attacker.example", provider_id="runninghub", protocol="runninghub")
        with patch.object(main, "runninghub_models_payload", new=AsyncMock(side_effect=AssertionError("must not fetch"))) as fetch:
            with self.assertRaises(main.HTTPException) as exc:
                asyncio.run(main.test_provider_connection(payload))
            self.assertEqual(exc.exception.status_code, 400)
            fetch.assert_not_awaited()

    def test_runninghub_temporary_key_overrides_saved_wallet(self):
        payload = main.TestConnectionPayload(base_url="https://temporary.example", provider_id="runninghub", protocol="runninghub", api_key="test-temporary-key")
        result = {
            "total": 0, "image_models": [], "chat_models": [], "video_models": [],
            "all": [], "raw": {}, "message": "mocked",
        }
        with patch.object(main, "runninghub_models_payload", new=AsyncMock(return_value=result)) as fetch:
            output = asyncio.run(main.test_provider_connection(payload))
            self.assertTrue(output["ok"])
            provider = fetch.await_args.args[0]
            self.assertEqual(provider["api_key"], "test-temporary-key")
            self.assertEqual(provider["wallet_api_key"], "test-temporary-key")

    def test_saved_runninghub_model_list_uses_saved_wallet_key(self):
        with patch.object(main, "fetch_models_from_upstream", new=AsyncMock(return_value={"total": 0})) as fetch:
            asyncio.run(main.fetch_upstream_models("runninghub"))
            self.assertEqual(fetch.await_args.args[1], "test-saved-wallet")

    def test_runninghub_fetch_models_uses_temporary_key_as_wallet(self):
        result = {"total": 0, "image_models": [], "chat_models": [], "video_models": [], "all": []}
        with patch.object(main, "runninghub_models_payload", new=AsyncMock(return_value=result)) as fetch:
            asyncio.run(main.fetch_models_from_upstream("https://temporary.example", "test-temp-key", "runninghub"))
            provider = fetch.await_args.args[0]
            self.assertEqual(provider["wallet_api_key"], "test-temp-key")


if __name__ == "__main__":
    unittest.main()
