"""S03 SEC-05: canvas asset ZIP exports stay within bounded budgets.

Uses tiny temporary files and mocked remote media; never external networks.
"""
from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
import main


class CanvasAssetZipBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="s03_zip_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patcher = patch.object(main, "OUTPUT_OUTPUT_DIR", str(self.root))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_single_local_asset_still_exports(self):
        (self.root / "good.png").write_bytes(b"image-bytes")
        with TestClient(main.app) as client:
            res = client.post("/api/canvas-assets/download", json={"urls": ["/output/good.png"]})
        self.assertEqual(res.status_code, 200, res.text[:180])
        with zipfile.ZipFile(BytesIO(res.content)) as archive:
            self.assertEqual(archive.namelist(), ["good.png"])
            self.assertEqual(archive.read("good.png"), b"image-bytes")

    def test_too_many_items_rejected_without_remote_download(self):
        with patch.object(main, "CANVAS_ASSET_ZIP_MAX_FILES", 2), \
             patch.object(main, "fetch_remote_media_bytes") as fetch:
            with TestClient(main.app) as client:
                res = client.post("/api/canvas-assets/download",
                                  json={"urls": ["https://cdn.example/1.png", "https://cdn.example/2.png", "https://cdn.example/3.png"]})
        self.assertEqual(res.status_code, 413)
        fetch.assert_not_called()

    def test_local_file_over_limit_rejected_before_read(self):
        (self.root / "large.png").write_bytes(b"012345")
        with patch.object(main, "CANVAS_ASSET_ZIP_MAX_FILE_BYTES", 4):
            with TestClient(main.app) as client:
                res = client.post("/api/canvas-assets/download", json={"urls": ["/output/large.png"]})
        self.assertEqual(res.status_code, 413)

    def test_cumulative_bytes_rejected(self):
        (self.root / "one.png").write_bytes(b"123")
        (self.root / "two.png").write_bytes(b"456")
        with patch.object(main, "CANVAS_ASSET_ZIP_MAX_TOTAL_BYTES", 5):
            with TestClient(main.app) as client:
                res = client.post("/api/canvas-assets/download", json={"urls": ["/output/one.png", "/output/two.png"]})
        self.assertEqual(res.status_code, 413)

    def test_remote_media_receives_remaining_byte_budget(self):
        with patch.object(main, "CANVAS_ASSET_ZIP_MAX_TOTAL_BYTES", 7), \
             patch.object(main, "CANVAS_ASSET_ZIP_MAX_FILE_BYTES", 6), \
             patch.object(main, "fetch_remote_media_bytes", return_value=(b"png", "image/png")) as remote:
            with TestClient(main.app) as client:
                res = client.post("/api/canvas-assets/download", json={"urls": ["https://cdn.example/one.png"]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(remote.call_args.kwargs["max_bytes"], 6)


if __name__ == "__main__":
    unittest.main()
