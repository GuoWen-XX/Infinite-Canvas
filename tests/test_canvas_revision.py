"""S04: revision checks must include metadata-only writes and legacy canvases.

No real canvas files or network services are used. Requires the full project
environment to execute; merely committing these tests is not a PASS result.
"""
import asyncio
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

    def test_meta_and_list_include_revision(self):
        meta = asyncio.run(main.get_canvas_meta(self.canvas["id"]))
        record = main.canvas_record(main.load_canvas(self.canvas["id"]))
        self.assertEqual(meta["revision"], self.canvas["revision"])
        self.assertEqual(record["revision"], self.canvas["revision"])


if __name__ == "__main__":
    unittest.main()
