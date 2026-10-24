import os
import sys
import unittest
from fastapi import FastAPI
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.integrations import router as integrations_router

class TestIntegrationsRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()
        cls.app.include_router(integrations_router)
        cls.client = TestClient(cls.app)

    def test_01_codex_status(self):
        resp = self.client.get("/api/codex/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("installed", resp.json())

    def test_02_gemini_cli_status(self):
        resp = self.client.get("/api/gemini-cli/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("installed", resp.json())

    def test_03_jimeng_status(self):
        resp = self.client.get("/api/jimeng/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("logged_in", resp.json())

    def test_04_runninghub_app_info_requires_webapp_id(self):
        resp = self.client.get("/api/runninghub/app-info")
        self.assertEqual(resp.status_code, 400)

    def test_05_runninghub_workflows(self):
        resp = self.client.get("/api/runninghub/workflows")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("workflows", resp.json())

    def test_06_gemini_cli_image_size_instruction(self):
        from routers.integrations import gemini_cli_image_size_instruction
        inst = gemini_cli_image_size_instruction("1024x1024", "auto")
        self.assertIn("1024x1024", inst)
        self.assertIn("正方形", inst)

if __name__ == '__main__':
    unittest.main()
