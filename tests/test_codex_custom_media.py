"""S07: Codex local references may only use configured media roots.

No Codex executable, outbound requests, API keys or user media involved.
Run with full checkout: python -m unittest tests.test_codex_custom_media -v
"""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from fastapi import HTTPException


class CodexCustomMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="s07_media_")
        self.addCleanup(self.temp.cleanup)
        self.roots = {}
        for key, subdir in (
            ("OUTPUT_OUTPUT_DIR", "generated"), ("OUTPUT_INPUT_DIR", "upload"),
            ("LOCAL_UPLOAD_DIR", "local"), ("ASSETS_DIR", "assets"),
            ("OUTPUT_DIR", "legacy")
        ):
            root = os.path.join(self.temp.name, subdir)
            os.makedirs(root)
            self.roots[key] = root
            p = patch.object(main, key, root)
            p.start()
            self.addCleanup(p.stop)
        self.outside = os.path.join(self.temp.name, "private.png")
        Path(self.outside).write_bytes(b"not a real image")

    def _make(self, root_key, name="image.png"):
        path = os.path.join(self.roots[root_key], name)
        Path(path).write_bytes(b"fixture only")
        return path

    def _prepared(self, value):
        return asyncio.run(main.codex_prepare_local_media(value))

    def test_default_output_root_absolute_path(self):
        path = self._make("OUTPUT_OUTPUT_DIR")
        self.assertEqual(self._prepared(path), (os.path.realpath(path), []))

    def test_custom_generated_root_storage_url(self):
        path = self._make("OUTPUT_OUTPUT_DIR", "custom.png")
        self.assertEqual(self._prepared("/api/storage-files/generated/custom.png"),
                         (os.path.realpath(path), []))

    def test_configured_local_upload_root_path(self):
        path = self._make("LOCAL_UPLOAD_DIR")
        self.assertEqual(self._prepared(path), (os.path.realpath(path), []))

    def test_valid_file_url_under_configured_root(self):
        path = self._make("OUTPUT_INPUT_DIR")
        self.assertEqual(self._prepared(Path(path).as_uri()), (os.path.realpath(path), []))

    def test_unrelated_absolute_path_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            self._prepared(self.outside)
        self.assertEqual(caught.exception.status_code, 400)

    def test_unrelated_file_url_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            self._prepared(Path(self.outside).as_uri())
        self.assertEqual(caught.exception.status_code, 400)

    def test_parent_escape_storage_url_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            self._prepared("/api/storage-files/generated/../../private.png")
        self.assertEqual(caught.exception.status_code, 400)

    def test_symlink_outside_root_cannot_be_used_as_reference(self):
        link = os.path.join(self.roots["OUTPUT_OUTPUT_DIR"], "link.png")
        try:
            os.symlink(self.outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        with self.assertRaises(HTTPException) as caught:
            self._prepared(link)
        self.assertEqual(caught.exception.status_code, 400)

    def test_public_remote_media_uses_existing_safe_bounded_fetch(self):
        from unittest.mock import Mock
        payload = b"fixture bytes only"
        with patch.object(main, "fetch_remote_media_bytes", return_value=(payload, "image/png")) as fetch:
            file_path, temp_paths = self._prepared("https://example.com/fixture.png")
        self.addCleanup(lambda: [os.path.exists(p) and os.unlink(p) for p in temp_paths])
        fetch.assert_called_once_with("https://example.com/fixture.png", 30.0, 20 * 1024 * 1024)
        self.assertEqual(temp_paths, [file_path])
        self.assertEqual(Path(file_path).read_bytes(), payload)

    def test_rejected_remote_media_cannot_create_a_temporary_reference(self):
        with patch.object(main, "fetch_remote_media_bytes",
                          side_effect=HTTPException(status_code=400, detail="private address")):
            with self.assertRaises(HTTPException) as caught:
                self._prepared("http://127.0.0.1/metadata")
        self.assertEqual(caught.exception.status_code, 400)

    def test_file_url_query_rejected(self):
        path = self._make("ASSETS_DIR")
        with self.assertRaises(HTTPException) as caught:
            self._prepared(Path(path).as_uri() + "?unexpected=1")
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
