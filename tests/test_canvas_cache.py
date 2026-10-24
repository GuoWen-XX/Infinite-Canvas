import os
import sys
import time
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.canvas_cache import CanvasCache


def dummy_record_builder(data):
    return {
        "id": data.get("id"),
        "title": data.get("title", "untitled"),
        "node_count": len(data.get("nodes", [])),
    }


class CanvasCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.canvas_dir = self.temp_dir.name
        self.cache = CanvasCache(self.canvas_dir, record_builder=dummy_record_builder, cleanup_interval_sec=1.0)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cache_miss_then_hit(self):
        # Create a canvas file
        file1 = os.path.join(self.canvas_dir, "canvas1.json")
        with open(file1, "w", encoding="utf-8") as f:
            json.dump({"id": "c1", "title": "First", "nodes": [1, 2, 3]}, f)

        # Miss: loads from disk
        records = self.cache.iter_records(include_deleted=False)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], "c1")
        self.assertEqual(records[0]["node_count"], 3)

        # Hit: subsequent iter uses cached entry
        records2 = self.cache.iter_records(include_deleted=False)
        self.assertEqual(len(records2), 1)
        self.assertEqual(records2[0]["id"], "c1")

    def test_mtime_change_triggers_reload(self):
        file1 = os.path.join(self.canvas_dir, "canvas1.json")
        with open(file1, "w", encoding="utf-8") as f:
            json.dump({"id": "c1", "title": "First", "nodes": [1]}, f)

        self.assertEqual(self.cache.iter_records()[0]["node_count"], 1)

        # Modify file and bump mtime
        time.sleep(0.02)
        with open(file1, "w", encoding="utf-8") as f:
            json.dump({"id": "c1", "title": "Updated", "nodes": [1, 2, 3, 4]}, f)

        updated_records = self.cache.iter_records()
        self.assertEqual(len(updated_records), 1)
        self.assertEqual(updated_records[0]["title"], "Updated")
        self.assertEqual(updated_records[0]["node_count"], 4)

    def test_deleted_separation_and_trash_cleanup(self):
        now_ms = int(time.time() * 1000)
        expired_deleted_at = now_ms - (31 * 86400 * 1000)

        # Active file
        with open(os.path.join(self.canvas_dir, "active.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "active", "title": "Active"}, f)

        # Unexpired trash file (deleted 1 day ago)
        unexpired_deleted_at = now_ms - (1 * 86400 * 1000)
        unexpired_trash_path = os.path.join(self.canvas_dir, "unexpired_trash.json")
        with open(unexpired_trash_path, "w", encoding="utf-8") as f:
            json.dump({"id": "unexpired_trash", "title": "Recent Trash", "deleted_at": unexpired_deleted_at}, f)

        # Expired trash file (deleted 35 days ago)
        expired_trash_path = os.path.join(self.canvas_dir, "expired_trash.json")
        with open(expired_trash_path, "w", encoding="utf-8") as f:
            json.dump({"id": "expired_trash", "title": "Old Trash", "deleted_at": expired_deleted_at}, f)

        # Active list should NOT include either trash file
        active_records = self.cache.iter_records(include_deleted=False)
        self.assertEqual(len(active_records), 1)
        self.assertEqual(active_records[0]["id"], "active")

        # Expired trash should have been cleaned up automatically
        self.assertFalse(os.path.exists(expired_trash_path))
        # Unexpired trash should still exist on disk
        self.assertTrue(os.path.exists(unexpired_trash_path))

    def test_caller_mutation_does_not_taint_cache(self):
        file1 = os.path.join(self.canvas_dir, "mutate_test.json")
        with open(file1, "w", encoding="utf-8") as f:
            json.dump({"id": "m1", "title": "Original", "nodes": [1, 2]}, f)

        recs = self.cache.iter_records()
        self.assertEqual(recs[0]["title"], "Original")
        recs[0]["title"] = "Hacked Title"

        # Subsequent fetch from cache must still be Original
        recs2 = self.cache.iter_records()
        self.assertEqual(recs2[0]["title"], "Original")


if __name__ == "__main__":
    unittest.main()
