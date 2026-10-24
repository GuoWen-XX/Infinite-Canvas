import os
import sys
import unittest
from fastapi import FastAPI
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.online_image import router as online_image_router

class TestOnlineImageRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()
        cls.app.include_router(online_image_router)
        cls.client = TestClient(cls.app)

    def test_01_image_params(self):
        resp = self.client.get("/api/image-params")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, dict)

    def test_02_canvas_image_task_not_found(self):
        resp = self.client.get("/api/canvas-image-tasks/non-existent-task-id")
        self.assertEqual(resp.status_code, 404)

    def test_03_online_image_prompt_required(self):
        resp = self.client.post("/api/online-image", json={"prompt": ""})
        self.assertEqual(resp.status_code, 422)

    def test_04_midjourney_tasks_validation(self):
        resp = self.client.get("/api/midjourney/tasks/non-existent-task?provider_id=invalid")
        self.assertIn(resp.status_code, (400, 404, 502))

if __name__ == '__main__':
    unittest.main()
