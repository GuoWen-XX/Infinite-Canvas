import os
import sys
import json
import time
import unittest
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
import routers.tasks as tasks_module

class TestTasksRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.client = TestClient(app)
        cls._orig_task_file = tasks_module.TASK_HISTORY_FILE
        cls._temp_dir = tempfile.TemporaryDirectory()
        tasks_module.TASK_HISTORY_FILE = os.path.join(cls._temp_dir.name, "task_history.jsonl")

    @classmethod
    def tearDownClass(cls):
        tasks_module.TASK_HISTORY_FILE = getattr(cls, "_orig_task_file", tasks_module.TASK_HISTORY_FILE)
        if hasattr(cls, "_temp_dir"):
            cls._temp_dir.cleanup()

    def test_01_get_task_history(self):
        resp = self.client.get("/api/task-history")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("tasks", data)
        self.assertIn("total", data)
        self.assertIsInstance(data["tasks"], list)

    def test_02_get_task_stats(self):
        resp = self.client.get("/api/task-stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("days", data)
        self.assertIn("providers", data)
        self.assertIn("total_cost", data)
        self.assertIn("currency", data)
        self.assertEqual(data["currency"], "CNY")

    def test_03_get_history_and_delete(self):
        resp = self.client.get("/api/history")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

        # Delete non-existent record
        del_resp = self.client.post("/api/history/delete", json={"timestamp": 12345678.0})
        self.assertEqual(del_resp.status_code, 200)
        self.assertFalse(del_resp.json().get("success"))

    def test_04_queue_status(self):
        resp = self.client.get("/api/queue_status?client_id=non_existent_client")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("total", data)
        self.assertIn("position", data)
        self.assertEqual(data["position"], 0)

    def test_05_estimate_video_cost_and_record_task(self):
        # Test DashScope price estimation
        raw = {"usage": {"duration": 5.0}, "parameters": {"resolution": "720P"}}
        cost, cur, src = tasks_module._estimate_video_cost("dashscope", "wan3.0-video", raw)
        self.assertEqual(cur, "CNY")
        self.assertEqual(src, "dashscope-price-table")
        self.assertAlmostEqual(cost, 3.0)

        # Test record_task_event
        rec = tasks_module.record_task_event(
            provider_id="dashscope",
            model="wan3.0-video",
            status="success",
            task_id="test_task_123",
            duration_ms=5000,
            outputs=["http://example.com/out.mp4"],
            raw=raw
        )
        self.assertEqual(rec["task_id"], "test_task_123")
        self.assertEqual(rec["status"], "success")
        self.assertAlmostEqual(rec["cost"], 3.0)

    def test_06_websocket_stats(self):
        with self.client.websocket_connect("/ws/stats?client_id=test_ws_client") as ws:
            # Upon connection, SafeConnectionManager broadcasts online stats
            init_msg = json.loads(ws.receive_text())
            self.assertEqual(init_msg.get("type"), "stats")

            ws.send_text("ping")
            reply = ws.receive_text()
            data = json.loads(reply)
            self.assertEqual(data.get("type"), "pong")

    def test_07_compact_task_history(self):
        # Write 20 records
        for i in range(20):
            tasks_module._task_history_append({
                "ts": i,
                "task_id": f"task_{i}",
                "status": "success",
                "provider": "test",
                "model": "m",
                "duration_ms": 100,
                "outputs": [],
            })
        # Compact down to 5 records
        compacted = tasks_module.compact_task_history(max_records=5)
        self.assertTrue(compacted)
        with open(tasks_module.TASK_HISTORY_FILE, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(lines), 5)
        self.assertEqual([item["task_id"] for item in lines], [f"task_{i}" for i in range(15, 20)])


if __name__ == "__main__":
    unittest.main()

