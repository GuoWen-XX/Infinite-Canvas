import os
import sys
import unittest
from fastapi import FastAPI
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.chat import (
    router as chat_router,
    safe_user_id,
    display_title,
)
from routers.online_image import router as online_image_router
from routers.integrations import router as integrations_router
from routers.common import (
    now_ms,
    set_online_history_saver,
    set_online_ws_manager,
)

class TestOnlineRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()
        cls.app.include_router(chat_router)
        cls.app.include_router(online_image_router)
        cls.app.include_router(integrations_router)
        cls.client = TestClient(cls.app)

    def test_01_helpers(self):
        self.assertTrue(now_ms() > 0)
        self.assertEqual(display_title("hello world"), "hello world")
        self.assertEqual(display_title(""), "新对话")

    def test_02_conversations_flow(self):
        # 1. List conversations
        resp = self.client.get('/api/conversations')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('conversations', data)

        # 2. Create conversation
        create_resp = self.client.post('/api/conversations', json={'title': 'Test Conv'})
        self.assertEqual(create_resp.status_code, 200)
        conv = create_resp.json().get('conversation', {})
        self.assertIn('id', conv)
        cid = conv['id']
        self.assertEqual(conv.get('title'), 'Test Conv')


        # 3. Get conversation
        get_resp = self.client.get(f'/api/conversations/{cid}')
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json().get('conversation', {}).get('id'), cid)

        # 4. Delete conversation
        del_resp = self.client.delete(f'/api/conversations/{cid}')
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json().get('ok'))

    def test_03_image_params(self):
        resp = self.client.get('/api/image-params')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, dict)

    def test_04_status_endpoints(self):
        # webappId is required, expect 400 without it
        resp_rh = self.client.get('/api/runninghub/app-info')
        self.assertEqual(resp_rh.status_code, 400)


        resp_codex = self.client.get('/api/codex/status')
        self.assertEqual(resp_codex.status_code, 200)
        self.assertIn('installed', resp_codex.json())

        resp_gemini = self.client.get('/api/gemini-cli/status')
        self.assertEqual(resp_gemini.status_code, 200)
        self.assertIn('installed', resp_gemini.json())

        resp_jm = self.client.get('/api/jimeng/status')
        self.assertEqual(resp_jm.status_code, 200)
        self.assertIn('logged_in', resp_jm.json())

if __name__ == '__main__':
    unittest.main()
