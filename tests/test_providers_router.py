import os
import sys
import unittest
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
import routers.providers as providers_module

class TestProvidersRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_get_config(self):
        resp = self.client.get("/api/config")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("chat_models", data)
        self.assertIn("image_models", data)
        self.assertIn("api_providers", data)
        self.assertIsInstance(data["api_providers"], list)

    def test_02_get_models(self):
        resp = self.client.get("/api/models")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("chat_models", data)
        self.assertIn("image_models", data)
        self.assertIn("video_models", data)

    def test_03_get_providers(self):
        resp = self.client.get("/api/providers")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("providers", data)
        self.assertIsInstance(data["providers"], list)

    def test_04_get_token(self):
        resp = self.client.get("/api/config/token")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("configured", data)

    def test_05_protocol_and_model_classification(self):
        # Test protocol_from_payload
        p_obj = providers_module.TestConnectionPayload(provider_id="volcengine")
        self.assertEqual(providers_module.protocol_from_payload(p_obj), "volcengine")

        p_obj2 = providers_module.TestConnectionPayload(provider_id="runninghub")
        self.assertEqual(providers_module.protocol_from_payload(p_obj2), "runninghub")

        p_obj3 = providers_module.TestConnectionPayload(base_url="https://api.openai.com/v1")
        self.assertEqual(providers_module.protocol_from_payload(p_obj3), "openai")

        # Test classify_upstream_model
        self.assertEqual(providers_module.classify_upstream_model("sora-2"), "video")
        self.assertEqual(providers_module.classify_upstream_model("dall-e-3"), "image")
        self.assertEqual(providers_module.classify_upstream_model("flux-dev"), "image")
        self.assertEqual(providers_module.classify_upstream_model("gpt-4o"), "chat")

        # Test parse_upstream_models
        raw_models = {
            "data": [
                {"id": "gpt-4o"},
                {"id": "flux-schnell"},
                {"id": "wan2.1-t2v"}
            ]
        }
        grouped, ids = providers_module.parse_upstream_models(raw_models)
        self.assertIn("gpt-4o", grouped["chat"])
        self.assertIn("flux-schnell", grouped["image"])
        self.assertIn("wan2.1-t2v", grouped["video"])
        self.assertEqual(len(ids), 3)

    def test_06_provider_base_url_ssrf_protection(self):
        # PUT /api/providers should reject metadata endpoint
        payload = [{
            "id": "malicious_provider",
            "name": "Malicious",
            "base_url": "http://169.254.169.254/latest/meta-data/",
            "protocol": "openai",
        }]
        resp = self.client.put("/api/providers", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("受限", resp.json().get("detail", ""))

        # POST /api/providers/test-connection should reject metadata endpoint
        test_payload = {
            "base_url": "http://169.254.169.254/latest/meta-data/",
            "api_key": "test",
            "protocol": "openai",
        }
        resp = self.client.post("/api/providers/test-connection", json=test_payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("受限", resp.json().get("detail", ""))

    def test_07_provider_key_host_binding_protection(self):
        # Saved API key must NOT be exfiltrated to a different host
        from unittest.mock import patch
        fake_providers = [{
            "id": "test_provider",
            "name": "Test",
            "base_url": "https://api.example.com/v1",
            "protocol": "openai",
            "enabled": True,
        }]
        with patch("routers.providers.load_api_providers", return_value=fake_providers), \
             patch("routers.providers.provider_env_key_value", return_value="sk-secret-real-key"):
            # Attempt to probe a different host using the stored key of test_provider
            resp = self.client.post("/api/providers/test-connection", json={
                "provider_id": "test_provider",
                "base_url": "https://attacker.com/v1",
                "protocol": "openai",
            })
            self.assertEqual(resp.status_code, 400)
            self.assertIn("已保存的 API Key 绑定在域名", resp.json().get("detail", ""))

if __name__ == "__main__":
    unittest.main()
