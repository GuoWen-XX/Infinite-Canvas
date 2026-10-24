import os
import sys
import time
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.history_manager import HistoryManager


class HistoryManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_path = os.path.join(self.temp_dir.name, "history.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_empty_init_and_save(self):
        mgr = HistoryManager(self.history_path, flush_debounce_sec=0.05)
        # Save a record
        rec = {"prompt": "A test prompt", "images": ["/output/test.png"], "type": "zimage"}
        mgr.save(rec)

        # Immediate read from memory
        results = mgr.list_records()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["prompt"], "A test prompt")
        self.assertIn("timestamp", results[0])

        # Wait for flush
        time.sleep(0.1)
        mgr.flush()
        self.assertTrue(os.path.exists(self.history_path))

        with open(self.history_path, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        self.assertEqual(len(disk_data), 1)
        self.assertEqual(disk_data[0]["prompt"], "A test prompt")

    def test_corrupted_json_safeguard(self):
        # Write corrupted JSON to history file
        with open(self.history_path, "w", encoding="utf-8") as f:
            f.write("{invalid json content [;;")

        mgr = HistoryManager(self.history_path)
        records = mgr.list_records()
        self.assertEqual(records, [])

        # Check that backup file was created and corrupted file was moved
        backups = [f for f in os.listdir(self.temp_dir.name) if f.startswith("history.json.corrupt")]
        self.assertGreater(len(backups), 0)

    def test_delete_record(self):
        mgr = HistoryManager(self.history_path, flush_debounce_sec=0.05)
        ts = 1700000000.0
        mgr.save({"prompt": "item 1", "images": ["/img1.png"], "timestamp": ts})
        mgr.save({"prompt": "item 2", "images": ["/img2.png"], "timestamp": ts + 10})

        self.assertEqual(len(mgr.list_records()), 2)

        deleted = mgr.delete(ts)
        self.assertIsNotNone(deleted)
        self.assertEqual(deleted["prompt"], "item 1")

        remaining = mgr.list_records()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["prompt"], "item 2")

    def test_filtering_and_max_records(self):
        mgr = HistoryManager(self.history_path, max_records=5, flush_debounce_sec=0.05)
        for i in range(10):
            mgr.save({
                "prompt": f"prompt {i}",
                "images": [f"/img{i}.png"],
                "type": "video" if i % 2 == 0 else "zimage",
                "timestamp": i,
            })

        # Should only keep 5 newest items (i=9,8,7,6,5)
        all_records = mgr.list_records()
        self.assertEqual(len(all_records), 5)

        # Filter by type
        zimage_records = mgr.list_records(record_type="zimage")
        for r in zimage_records:
            self.assertEqual(r["type"], "zimage")

    def test_flush_disk_error_does_not_deadlock(self):
        """Regression test for C1: ensure disk write error during flush doesn't cause self-deadlock."""
        from unittest.mock import patch
        import threading

        mgr = HistoryManager(self.history_path, flush_debounce_sec=999)
        mgr.save({"prompt": "error test", "images": ["/img.png"], "timestamp": 12345})
        if mgr._flush_timer:
            mgr._flush_timer.cancel()

        def do_flush():
            with patch("core.history_manager.os.replace", side_effect=OSError("simulated disk error")):
                mgr.flush()

        t = threading.Thread(target=do_flush, daemon=True)
        t.start()
        t.join(timeout=2.0)
        self.assertFalse(t.is_alive(), "flush() deadlocked on simulated disk error")
        # Ensure it remains marked dirty and reschedule timer was created
        with mgr._lock:
            self.assertTrue(mgr._dirty)

    def test_sliding_window_compaction_on_disk(self):
        mgr = HistoryManager(self.history_path, max_records=3, flush_debounce_sec=0.01)
        for i in range(10):
            mgr.save({"prompt": f"p{i}", "images": [f"/img{i}.png"], "timestamp": i})
        mgr.flush()
        with open(self.history_path, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        self.assertEqual(len(disk_data), 3)
        self.assertEqual([d["prompt"] for d in disk_data], ["p9", "p8", "p7"])


if __name__ == "__main__":
    unittest.main()

