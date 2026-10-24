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
    now_ms,
    heuristic_agent_decision,
    parse_agent_decision,
)

class TestChatRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()
        cls.app.include_router(chat_router)
        cls.client = TestClient(cls.app)

    def test_01_helpers(self):
        self.assertTrue(now_ms() > 0)
        self.assertEqual(display_title("test topic"), "test topic")
        self.assertEqual(display_title(""), "新对话")

    def test_02_conversations_crud(self):
        # 1. List
        resp = self.client.get("/api/conversations")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("conversations", resp.json())

        # 2. Create
        create_resp = self.client.post("/api/conversations", json={"title": "Chat Sub-router Test"})
        self.assertEqual(create_resp.status_code, 200)
        cid = create_resp.json().get("conversation", {}).get("id")
        self.assertTrue(cid)

        # 3. Get
        get_resp = self.client.get(f"/api/conversations/{cid}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json().get("conversation", {}).get("id"), cid)

        # 4. Delete
        del_resp = self.client.delete(f"/api/conversations/{cid}")
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json().get("ok"))

    def test_03_canvas_llm_validation(self):
        resp = self.client.post("/api/canvas-llm", json={"message": ""})
        self.assertEqual(resp.status_code, 422)

    def test_04_heuristic_agent_decision(self):
        # 1. Text-only query defaults to chat
        d1 = heuristic_agent_decision("什么是现代主义建筑？", [], False)
        self.assertEqual(d1["action"], "chat")

        # 2. Image generation keywords trigger generate_image
        d2 = heuristic_agent_decision("生成一张现代极简住宅外观效果图", [], False)
        self.assertEqual(d2["action"], "generate_image")

        # 3. Having reference image and edit keywords triggers edit_image
        d3 = heuristic_agent_decision("修改这张图片的材质为大理石", [{"url": "/assets/test.png"}], True)
        self.assertEqual(d3["action"], "edit_image")

        # 4. Having reference image and analysis keywords triggers chat
        d4 = heuristic_agent_decision("分析一下这张图片 并用json格式来描述", [{"url": "/assets/test.png"}], False)
        self.assertEqual(d4["action"], "chat")

        d5 = heuristic_agent_decision("反推提示词", [{"url": "/assets/test.png"}], False)
        self.assertEqual(d5["action"], "chat")

    def test_05_parse_agent_decision(self):
        raw_json = '{"action": "generate_image", "prompt": "a minimalist house", "reply": "好的，正在生成"}'
        d = parse_agent_decision(raw_json, "帮我画画", [], False)
        self.assertEqual(d["action"], "generate_image")
        self.assertEqual(d["prompt"], "a minimalist house")
        self.assertEqual(d["reply"], "好的，正在生成")

        # Fallback when raw text is invalid JSON
        d_fallback = parse_agent_decision("not json", "帮我画一张图", [], False)
        self.assertEqual(d_fallback["action"], "generate_image")

    def test_06_chat_agent_validation(self):
        # Empty message should fail with 422
        resp = self.client.post("/api/chat/agent", json={"message": ""})
        self.assertEqual(resp.status_code, 422)

    def test_07_chat_agent_with_image_reference(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": '{"description": "这是一张测试图"}'
                }
            }],
            "usage": {"total_tokens": 42}
        }

        with patch("routers.chat.resolve_chat_provider", return_value=("https://api.openai.com/v1", {"Authorization": "Bearer test"}, "gpt-4o-mini")), \
             patch("routers.chat.post_chat_completions_with_retry", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            resp = self.client.post("/api/chat/agent", json={
                "message": "分析一下这张图片 并用json格式来描述",
                "provider": "comfly",
                "model": "gpt-4o-mini",
                "reference_images": [{
                    "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                    "name": "微信图片_test.png",
                    "role": "reference",
                    "kind": "image"
                }]
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("conversation", data)
            self.assertIn("message", data)
            self.assertEqual(data["message"]["content"], '{"description": "这是一张测试图"}')
            self.assertEqual(data["agent"]["action"], "chat")

            # Verify that post_chat_completions_with_retry was called with real payload
            self.assertEqual(mock_post.call_count, 1)
            call_args = mock_post.call_args
            json_body = call_args[1].get("json_body") or (call_args[0][3] if len(call_args[0]) > 3 else None)
            self.assertIsNotNone(json_body)
            self.assertEqual(json_body["model"], "gpt-4o-mini")

            # Verify multimodal content construction with image_url
            messages = json_body.get("messages", [])
            self.assertGreaterEqual(len(messages), 2)
            user_msg = messages[-1]
            self.assertEqual(user_msg["role"], "user")
            self.assertIsInstance(user_msg["content"], list)
            has_image_url = any(
                isinstance(part, dict) and part.get("type") == "image_url"
                for part in user_msg["content"]
            )
            self.assertTrue(has_image_url)

    def test_08_fast_path_and_rate_limit_retry(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from routers.chat import decide_chat_agent_action, post_chat_completions_with_retry, ChatRequest

        # 1. Test fast-path bypass for explicit analysis queries
        req = ChatRequest(message="分析一下这张图并写一段json提示词", provider="openai", model="gpt-4o")
        conv = {"messages": []}
        decision = asyncio.run(decide_chat_agent_action(req, conv, []))
        self.assertEqual(decision["action"], "chat")
        self.assertEqual(decision["router_model"], "heuristic_fast_path")

        # 2. Test fast-path for modelscope provider
        ms_req = ChatRequest(message="画一只可爱的猫咪", provider="modelscope", model="qwen")
        ms_decision = asyncio.run(decide_chat_agent_action(ms_req, conv, []))
        self.assertEqual(ms_decision["action"], "generate_image")
        self.assertEqual(ms_decision["router_model"], "heuristic_fast_path")

        # 3. Test post_chat_completions_with_retry on 429 rate limit with Retry-After header
        mock_client = MagicMock()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "1.0"}
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.headers = {}
        resp_200.json.return_value = {"ok": True}
        mock_client.post = AsyncMock(side_effect=[resp_429, resp_200])

        final_resp = asyncio.run(post_chat_completions_with_retry(mock_client, "http://test", {}, {}, max_retries=2))
        self.assertEqual(final_resp.status_code, 200)
        self.assertEqual(mock_client.post.call_count, 2)


if __name__ == '__main__':
    unittest.main()

