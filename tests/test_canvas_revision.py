"""S04: revision checks must include metadata-only writes and legacy canvases.

No real canvas files or network services are used. Requires the full project
environment to execute; merely committing these tests is not a PASS result.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import main
from fastapi import HTTPException


class CanvasRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="s04_revision_")
        self.addCleanup(self.temp.cleanup)
        patched = patch.object(main, "CANVAS_DIR", self.temp.name)
        patched.start()
        self.addCleanup(patched.stop)
        self.canvas = main.new_canvas("original")

    def _save(self, **kwargs):
        values = {
            "title": "editor title", "icon": "layers", "nodes": [{"id": "new"}],
            "connections": [], "viewport": {}, "logs": [],
            "base_updated_at": self.canvas["updated_at"],
            "base_revision": self.canvas["revision"],
        }
        values.update(kwargs)
        with patch.object(main.manager, "broadcast_canvas_updated", new_callable=AsyncMock):
            return asyncio.run(main.update_canvas(self.canvas["id"], main.CanvasSaveRequest(**values)))

    def test_every_write_increments_revision_even_when_updated_at_does_not(self):
        first = main.load_canvas(self.canvas["id"])
        main.mutate_canvas(self.canvas["id"], lambda c: c.update({"owner": "other"}), bump_updated_at=False)
        second = main.load_canvas(self.canvas["id"])
        self.assertEqual(second["updated_at"], first["updated_at"])
        self.assertEqual(second["revision"], first["revision"] + 1)

    def test_touch_updates_activity_without_invalidating_content_revision(self):
        before = main.load_canvas(self.canvas["id"])
        touched = asyncio.run(main.touch_canvas(self.canvas["id"]))
        self.assertGreater(touched["updated_at"], before["updated_at"])
        self.assertEqual(touched["canvas"]["revision"], before["revision"])
        # A fresh editor using the content revision may still save.
        saved = self._save()
        self.assertEqual(saved["canvas"]["nodes"], [{"id": "new"}])

    def test_metadata_change_invalidates_stale_full_canvas_save(self):
        before = main.load_canvas(self.canvas["id"])
        asyncio.run(main.update_canvas_meta(
            self.canvas["id"], main.CanvasMetaUpdate(title="remote rename", base_revision=before["revision"])
        ))
        with self.assertRaises(HTTPException) as ctx:
            self._save()
        self.assertEqual(ctx.exception.status_code, 409)
        stored = main.load_canvas(self.canvas["id"])
        self.assertEqual(stored["title"], "remote rename")
        self.assertEqual(stored["nodes"], [])

    def test_legacy_timestamp_fallback_rejects_stale_save(self):
        main.mutate_canvas(self.canvas["id"], lambda c: c.update({"title": "newer"}))
        with self.assertRaises(HTTPException) as ctx:
            self._save(base_revision=None)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_missing_both_version_tokens_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            self._save(base_revision=None, base_updated_at=0)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_parallel_editors_share_one_revision_only_one_write_wins(self):
        original = main.load_canvas(self.canvas["id"])
        barrier = threading.Barrier(2)

        def writer(title):
            payload = main.CanvasSaveRequest(
                title=title, icon="layers", nodes=[{"id": title}],
                connections=[], viewport={}, logs=[],
                base_revision=original["revision"],
                base_updated_at=original["updated_at"],
            )
            barrier.wait(timeout=5)
            try:
                asyncio.run(main.update_canvas(self.canvas["id"], payload))
                return "saved"
            except HTTPException as exc:
                return exc.status_code

        with patch.object(main.manager, "broadcast_canvas_updated", new_callable=AsyncMock):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(writer, "A"), pool.submit(writer, "B")]
                results = [future.result(timeout=10) for future in futures]
        self.assertCountEqual(results, ["saved", 409])
        final = main.load_canvas(self.canvas["id"])
        self.assertIn(final["title"], ("A", "B"))
        self.assertEqual(final["nodes"], [{"id": final["title"]}])
        self.assertEqual(final["revision"], original["revision"] + 1)

    def test_two_editors_same_revision_only_first_can_commit(self):
        first = self._save()
        self.assertEqual(first["canvas"]["nodes"], [{"id": "new"}])
        with self.assertRaises(HTTPException) as ctx:
            self._save(title="stale writer", nodes=[{"id": "lost"}])
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(main.load_canvas(self.canvas["id"])["nodes"], [{"id": "new"}])

    def test_stale_metadata_rename_conflicts_without_overwriting(self):
        before = main.load_canvas(self.canvas["id"])
        asyncio.run(main.update_canvas_meta(
            self.canvas["id"], main.CanvasMetaUpdate(title="first", base_revision=before["revision"])
        ))
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(main.update_canvas_meta(
                self.canvas["id"], main.CanvasMetaUpdate(icon="star", base_revision=before["revision"])
            ))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(main.load_canvas(self.canvas["id"])["title"], "first")

    def test_omitted_settings_does_not_erase_saved_canvas_settings(self):
        main.mutate_canvas(self.canvas["id"], lambda c: c.update({"settings": {"custom": 42}}))
        latest = main.load_canvas(self.canvas["id"])
        self._save(base_revision=latest["revision"], base_updated_at=latest["updated_at"])
        self.assertEqual(main.load_canvas(self.canvas["id"])["settings"], {"custom": 42})

    def test_explicit_empty_settings_can_clear_existing_settings(self):
        main.mutate_canvas(self.canvas["id"], lambda c: c.update({"settings": {"custom": 42}}))
        latest = main.load_canvas(self.canvas["id"])
        self._save(base_revision=latest["revision"], base_updated_at=latest["updated_at"], settings={})
        self.assertEqual(main.load_canvas(self.canvas["id"])["settings"], {})

    def test_stale_delete_rejected_without_trashing_newer_canvas(self):
        before = main.load_canvas(self.canvas["id"])
        self._save(title="newer editor", nodes=[{"id": "keep-new"}])
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(main.delete_canvas(self.canvas["id"], base_revision=before["revision"]))
        self.assertEqual(ctx.exception.status_code, 409)
        still_present = main.load_canvas(self.canvas["id"])
        self.assertEqual(still_present["nodes"], [{"id": "keep-new"}])
        self.assertFalse(still_present.get("deleted_at"))

    def test_delete_without_version_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(main.delete_canvas(self.canvas["id"]))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertFalse(main.load_canvas(self.canvas["id"]).get("deleted_at"))

    def test_matching_revision_soft_delete_succeeds(self):
        latest = main.load_canvas(self.canvas["id"])
        result = asyncio.run(main.delete_canvas(self.canvas["id"], base_revision=latest["revision"]))
        self.assertEqual(result, {"ok": True})
        trashed = main.load_canvas_any(self.canvas["id"])
        self.assertTrue(trashed.get("deleted_at"))
        self.assertEqual(trashed["revision"], latest["revision"] + 1)
        with self.assertRaises(HTTPException) as ctx:
            main.load_canvas(self.canvas["id"])
        self.assertEqual(ctx.exception.status_code, 404)

    def test_legacy_timestamp_soft_delete_checks_version(self):
        initial = main.load_canvas(self.canvas["id"])
        self._save(title="remote new version")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(main.delete_canvas(self.canvas["id"], base_updated_at=initial["updated_at"]))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_purge_live_canvas_rejected_without_removing_file(self):
        latest = main.load_canvas(self.canvas["id"])
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(main.purge_canvas(self.canvas["id"], base_revision=latest["revision"]))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(main.load_canvas(self.canvas["id"])["id"], self.canvas["id"])

    def test_purge_without_revision_rejected(self):
        latest = main.load_canvas(self.canvas["id"])
        asyncio.run(main.delete_canvas(self.canvas["id"], base_revision=latest["revision"]))
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(main.purge_canvas(self.canvas["id"]))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertTrue(main.load_canvas_any(self.canvas["id"]).get("deleted_at"))

    def test_stale_purge_after_concurrent_restore_rejected(self):
        latest = main.load_canvas(self.canvas["id"])
        asyncio.run(main.delete_canvas(self.canvas["id"], base_revision=latest["revision"]))
        trash = main.load_canvas_any(self.canvas["id"])
        asyncio.run(main.restore_canvas(self.canvas["id"]))
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(main.purge_canvas(self.canvas["id"], base_revision=trash["revision"]))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(main.load_canvas(self.canvas["id"])["id"], self.canvas["id"])

    def test_purge_current_trash_revision_removes_file(self):
        latest = main.load_canvas(self.canvas["id"])
        asyncio.run(main.delete_canvas(self.canvas["id"], base_revision=latest["revision"]))
        trash = main.load_canvas_any(self.canvas["id"])
        self.assertEqual(asyncio.run(main.purge_canvas(self.canvas["id"], base_revision=trash["revision"])), {"ok": True})
        with self.assertRaises(HTTPException) as ctx:
            main.load_canvas_any(self.canvas["id"])
        self.assertEqual(ctx.exception.status_code, 404)

    def test_meta_and_list_include_revision(self):
        meta = asyncio.run(main.get_canvas_meta(self.canvas["id"]))
        record = main.canvas_record(main.load_canvas(self.canvas["id"]))
        self.assertEqual(meta["revision"], self.canvas["revision"])
        self.assertEqual(record["revision"], self.canvas["revision"])


if __name__ == "__main__":
    unittest.main()
