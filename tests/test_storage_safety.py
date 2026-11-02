"""S03 SEC-03: local storage paths may never follow symlinks outside a configured root.

All fixtures are temporary. No real user files, network, or paid providers.
"""
import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
import main


class StorageRealpathBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="s03_store_")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "allowed"
        self.root.mkdir()
        self.external = self.base / "outside"
        self.external.mkdir()
        self.secret = self.external / "private.png"
        self.secret.write_bytes(b"not-an-image-secret")
        self.patcher = patch.object(main, "OUTPUT_OUTPUT_DIR", str(self.root))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _symlink(self, dest, source):
        try:
            dest.symlink_to(source, target_is_directory=source.is_dir())
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symlinks not supported on this platform: {exc}")

    def test_regular_file_inside_custom_root_remains_accessible(self):
        nested = self.root / "sub"
        nested.mkdir()
        image = nested / "good.png"
        image.write_bytes(b"test")
        path = main.storage_file_path("generated", "sub/good.png")
        self.assertEqual(os.path.realpath(path), os.path.realpath(image))

    def test_storage_file_path_rejects_file_symlink_outside_root(self):
        self._symlink(self.root / "leak.png", self.secret)
        with self.assertRaises(HTTPException) as caught:
            main.storage_file_path("generated", "leak.png")
        self.assertEqual(caught.exception.status_code, 400)

    def test_storage_file_path_rejects_directory_symlink_outside_root(self):
        self._symlink(self.root / "linked_dir", self.external)
        with self.assertRaises(HTTPException) as caught:
            main.storage_file_path("generated", "linked_dir/private.png")
        self.assertEqual(caught.exception.status_code, 400)

    def test_storage_file_path_blocks_dotdot_traversal(self):
        with self.assertRaises(HTTPException) as caught:
            main.storage_file_path("generated", "../outside/private.png")
        self.assertEqual(caught.exception.status_code, 400)

    def test_output_url_does_not_resolve_external_symlink(self):
        self._symlink(self.root / "leak.png", self.secret)
        self.assertIsNone(main.output_file_from_url("/output/leak.png"))

    def test_local_basename_fallback_does_not_resolve_external_symlink(self):
        self._symlink(self.root / "leak.png", self.secret)
        with patch.object(main, "OUTPUT_INPUT_DIR", str(self.root)), \
             patch.object(main, "ASSETS_DIR", str(self.root)):
            self.assertIsNone(main.local_media_file_by_basename("leak.png"))

    def test_storage_listing_does_not_expose_external_symlink(self):
        self._symlink(self.root / "leak.png", self.secret)
        result = asyncio.run(main.list_storage_files(kind="generated", offset=0, limit=80))
        self.assertFalse(any(item["name"] == "leak.png" for item in result["items"]))

    def test_deleting_internal_alias_preserves_original_file(self):
        original = self.root / "original.png"
        original.write_bytes(b"original-should-survive")
        alias = self.root / "alias.png"
        self._symlink(alias, original)
        result = asyncio.run(main.delete_storage_files({"kind": "generated", "items": ["alias.png"]}))
        self.assertEqual(result["removed"], 1)
        self.assertFalse(os.path.lexists(alias))
        self.assertEqual(original.read_bytes(), b"original-should-survive")

    def test_storage_http_byte_range_uses_pinned_file(self):
        from fastapi.testclient import TestClient
        image = self.root / "range.png"
        image.write_bytes(b"0123456789")
        with TestClient(main.app) as client:
            response = client.get(
                "/api/storage-files/generated/range.png",
                headers={"Range": "bytes=2-5"},
            )
        self.assertEqual(response.status_code, 206, response.text[:200])
        self.assertEqual(response.content, b"2345")
        self.assertEqual(response.headers.get("content-range"), "bytes 2-5/10")

    def test_if_range_matching_etag_returns_pinned_partial_content(self):
        from fastapi.testclient import TestClient
        file = self.root / "resume.png"
        file.write_bytes(b"0123456789")
        with TestClient(main.app) as client:
            initial = client.get("/api/storage-files/generated/resume.png")
            etag = initial.headers["etag"]
            response = client.get(
                "/api/storage-files/generated/resume.png",
                headers={"Range": "bytes=4-", "If-Range": etag},
            )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b"456789")
        self.assertEqual(response.headers["etag"], etag)

    def test_if_range_stale_etag_returns_full_new_file(self):
        from fastapi.testclient import TestClient
        file = self.root / "resume.png"
        file.write_bytes(b"OLD-FILE-111")
        os.utime(file, (1600000000, 1600000000))
        with TestClient(main.app) as client:
            old = client.get("/api/storage-files/generated/resume.png")
            file.write_bytes(b"NEW-FILE-222")
            os.utime(file, (1600000060, 1600000060))
            response = client.get(
                "/api/storage-files/generated/resume.png",
                headers={"Range": "bytes=4-", "If-Range": old.headers["etag"]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"NEW-FILE-222")

    def test_if_range_stale_date_returns_full_new_file(self):
        from fastapi.testclient import TestClient
        file = self.root / "resume.png"
        file.write_bytes(b"OLD-FILE-111")
        os.utime(file, (1600000000, 1600000000))
        with TestClient(main.app) as client:
            old = client.get("/api/storage-files/generated/resume.png")
            file.write_bytes(b"NEW-FILE-222")
            os.utime(file, (1600000060, 1600000060))
            response = client.get(
                "/api/storage-files/generated/resume.png",
                headers={"Range": "bytes=4-", "If-Range": old.headers["last-modified"]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"NEW-FILE-222")

    def test_response_stream_remains_pinned_after_path_swap(self):
        if os.name == "nt":
            self.skipTest("Windows share-delete/reparse semantics require a native fixture")
        image = self.root / "fixed.png"
        image.write_bytes(b"SAFE-CONTENT")
        response = main.scoped_local_file_response(
            str(self.root), str(image), media_type="image/png",
        )
        image.unlink()
        self._symlink(image, self.secret)

        async def collect():
            body = b""
            async for part in response.body_iterator:
                body += part
            return body

        self.assertEqual(asyncio.run(collect()), b"SAFE-CONTENT")
        self.assertEqual(self.secret.read_bytes(), b"not-an-image-secret")

    def test_storage_http_external_symlink_cannot_be_downloaded(self):
        from fastapi.testclient import TestClient
        self._symlink(self.root / "leak.png", self.secret)
        with TestClient(main.app) as client:
            response = client.get("/api/storage-files/generated/leak.png")
        self.assertEqual(response.status_code, 400)

    def test_storage_delete_cannot_remove_external_symlink_target(self):
        self._symlink(self.root / "leak.png", self.secret)
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(main.delete_storage_files({"kind": "generated", "items": ["leak.png"]}))
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(self.secret.read_bytes(), b"not-an-image-secret")


if __name__ == "__main__":
    unittest.main()
