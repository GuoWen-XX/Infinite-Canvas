import os
import sys
import unittest
from fastapi import FastAPI
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.comfyui import (
    router as comfyui_router,
    get_best_backend,
    is_valid_comfy_address,
    BUILTIN_WORKFLOWS,
    COMFYUI_INSTANCES,
)

class TestComfyUIRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()
        cls.app.include_router(comfyui_router)
        cls.client = TestClient(cls.app)

    def test_01_comfy_address_validation(self):
        self.assertTrue(is_valid_comfy_address("127.0.0.1:8188"))
        self.assertTrue(is_valid_comfy_address("192.168.1.100:8188"))
        self.assertFalse(is_valid_comfy_address("invalid"))
        self.assertFalse(is_valid_comfy_address("http://127.0.0.1:8188"))
        self.assertFalse(is_valid_comfy_address("127.0.0.1:999999"))

    def test_02_builtin_workflows(self):
        self.assertIn("Z-Image.json", BUILTIN_WORKFLOWS)
        self.assertIn("upscale.json", BUILTIN_WORKFLOWS)

    def test_03_get_instances(self):
        resp = self.client.get("/api/comfyui/instances")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("instances", data)
        self.assertIsInstance(data["instances"], list)

    def test_04_list_workflows(self):
        resp = self.client.get("/api/workflows")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("workflows", data)

    def test_05_nonexistent_canvas_task(self):
        resp = self.client.get("/api/canvas-comfy-tasks/non_existent_task_123")
        self.assertEqual(resp.status_code, 404)

    def test_06_save_instances_validation(self):
        # Comma injection
        resp = self.client.put("/api/comfyui/instances", json={"instances": ["127.0.0.1:8188,10.0.0.1:8188"]})
        self.assertEqual(resp.status_code, 400)

        # Cloud metadata SSRF
        resp = self.client.put("/api/comfyui/instances", json={"instances": ["169.254.169.254:80"]})
        self.assertEqual(resp.status_code, 400)

        # Invalid port
        resp = self.client.put("/api/comfyui/instances", json={"instances": ["127.0.0.1:99999"]})
        self.assertEqual(resp.status_code, 400)

    def test_07_workflow_path_traversal(self):
        # Attempt path traversal via workflow_json
        resp = self.client.post("/api/generate", json={
            "prompt": "test",
            "workflow_json": "../../data/api_providers.json"
        })
        self.assertIn(resp.status_code, (400, 404))

if __name__ == "__main__":
    unittest.main()
