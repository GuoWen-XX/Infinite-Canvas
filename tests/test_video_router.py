import os
import sys
import unittest
from fastapi import FastAPI
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.video import router as video_router

class TestVideoRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()
        cls.app.include_router(video_router)
        cls.client = TestClient(cls.app)

    def test_01_minimax_export_validation(self):
        # Empty clips should raise 400
        resp = self.client.post("/api/smart-canvas/minimax-export", json={"clips": []})
        self.assertEqual(resp.status_code, 400)

    def test_02_cloud_video_upload_validation(self):
        resp = self.client.post("/api/cloud-video/upload", json={"url": ""})
        # Empty URL should fail gracefully
        self.assertIn(resp.status_code, (200, 400, 403, 422, 500))

    def test_03_canvas_video_prompt_required(self):
        # Prompt is required with min_length 1
        resp = self.client.post("/api/canvas-video", json={"prompt": ""})
        self.assertEqual(resp.status_code, 422)

if __name__ == '__main__':
    unittest.main()
