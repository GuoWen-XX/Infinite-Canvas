# -*- coding: utf-8 -*-
"""Unit tests verifying adversarial audit security fixes and performance optimizations (Task 3)."""
import ast
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from fastapi import HTTPException

from core.canvas_cache import CanvasCache
from core.providers import BASE_DIR, OUTPUT_DIR, ASSETS_DIR
from routers.canvas import canvas_cache, canvas_path, api_get_canvas_meta, CANVAS_DIR
from routers.integrations import (
    _is_confined_local_media_path,
    codex_prepare_local_media,
    jimeng_prepare_local_media,
)
from routers.assets import api_list_storage_files, storage_kind_dir
from scripts.check_ssrf_guards import SSRFVisitor


class TestMediaConfinement(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(dir=OUTPUT_DIR)
        self.allowed_file = os.path.join(self.test_dir, "test_output.png")
        with open(self.allowed_file, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_is_confined_local_media_path_accepts_output_dir(self):
        self.assertTrue(_is_confined_local_media_path(self.allowed_file))

    def test_is_confined_local_media_path_rejects_external_and_env(self):
        env_path = os.path.join(BASE_DIR, "API", ".env")
        self.assertFalse(_is_confined_local_media_path(env_path))
        self.assertFalse(_is_confined_local_media_path(os.path.abspath(__file__)))
        self.assertFalse(_is_confined_local_media_path(""))
        self.assertFalse(_is_confined_local_media_path(None))

    async def test_codex_and_jimeng_prepare_local_media_reject_unconfined(self):
        env_path = os.path.join(BASE_DIR, "API", ".env")
        # codex_prepare_local_media should reject the env path with HTTPException 400
        with self.assertRaises(HTTPException) as ctx:
            await codex_prepare_local_media(env_path)
        self.assertEqual(ctx.exception.status_code, 400)

        # jimeng_prepare_local_media should reject the env path with HTTPException 400
        with self.assertRaises(HTTPException) as ctx2:
            await jimeng_prepare_local_media(env_path)
        self.assertEqual(ctx2.exception.status_code, 400)

        # Confined path inside OUTPUT_DIR should be accepted
        allowed_res, _ = await codex_prepare_local_media(self.allowed_file)
        self.assertEqual(os.path.realpath(allowed_res), os.path.realpath(self.allowed_file))


class TestSSRFVisitorGate(unittest.TestCase):
    def test_visitor_catches_tainted_url_fetch(self):
        code = """
@router.post("/test")
async def my_route(payload: SomePayload):
    u = payload.url.strip()
    client.get(u)
"""
        tree = ast.parse(code)
        visitor = SSRFVisitor("test_fake.py", code.splitlines(True))
        visitor.visit(tree)
        self.assertGreaterEqual(len(visitor.errors), 1)
        self.assertTrue(any("unvalidated tainted expression" in err[1] for err in visitor.errors))

    def test_visitor_catches_non_standard_client_name(self):
        code = """
@router.post("/test")
async def my_route(payload: SomePayload):
    u = payload.url.strip()
    fetcher = httpx.AsyncClient()
    await fetcher.get(u)
"""
        tree = ast.parse(code)
        visitor = SSRFVisitor("test_fake.py", code.splitlines(True))
        visitor.visit(tree)
        self.assertGreaterEqual(len(visitor.errors), 1)
        self.assertTrue(any("unvalidated tainted expression" in err[1] for err in visitor.errors))

    def test_visitor_catches_allow_private_true(self):
        code = """
@router.post("/test")
async def my_route(payload: SomePayload):
    u = payload.url.strip()
    await safe_download_bytes(u, allow_private=True)
"""
        tree = ast.parse(code)
        visitor = SSRFVisitor("test_fake.py", code.splitlines(True))
        visitor.visit(tree)
        self.assertGreaterEqual(len(visitor.errors), 1)
        self.assertTrue(any("allow_private=True" in err[1] for err in visitor.errors))

    def test_visitor_allows_properly_guarded_url(self):
        code = """
@router.post("/test")
async def my_route(payload: SomePayload):
    u = payload.url.strip()
    validate_safe_url(u, allow_private=False)
    client.get(u)
"""
        tree = ast.parse(code)
        visitor = SSRFVisitor("test_fake.py", code.splitlines(True))
        visitor.visit(tree)
        self.assertEqual(len(visitor.errors), 0)


class TestCanvasMetaCache(unittest.TestCase):
    def setUp(self):
        self.canvas_id = "test_audit_canvas_meta_1"
        self.filename = f"{self.canvas_id}.json"
        self.file_path = os.path.join(CANVAS_DIR, self.filename)
        data = {
            "id": self.canvas_id,
            "title": "Audit Test Canvas",
            "icon": "palette",
            "kind": "classic",
            "updated_at": 1700000000000,
        }
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def tearDown(self):
        if os.path.exists(self.file_path):
            try:
                os.remove(self.file_path)
            except Exception:
                pass
        canvas_cache.invalidate(self.filename)

    def test_canvas_meta_served_from_cache_without_json_load(self):
        # First call populates cache
        rec = canvas_cache.get_record(self.filename)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.get("title"), "Audit Test Canvas")

        # Second call should hit mtime cache without calling json.load
        with patch("json.load", side_effect=RuntimeError("json.load must not be called on cache hit")):
            meta = api_get_canvas_meta(self.canvas_id)
            self.assertEqual(meta["id"], self.canvas_id)
            self.assertEqual(meta["title"], "Audit Test Canvas")
            self.assertEqual(meta["kind"], "classic")
            self.assertEqual(meta["updated_at"], 1700000000000)


class TestStorageFilesPagination(unittest.TestCase):
    def setUp(self):
        self.root = storage_kind_dir("generated")
        self.test_subfolder = os.path.join(self.root, "_audit_test_dir_perf")
        os.makedirs(self.test_subfolder, exist_ok=True)
        # Create 25 dummy png files
        self.created_files = []
        for i in range(25):
            p = os.path.join(self.test_subfolder, f"perf_{i:02d}.png")
            with open(p, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89")
            self.created_files.append(p)

    def tearDown(self):
        shutil.rmtree(self.test_subfolder, ignore_errors=True)

    def test_storage_files_calls_image_open_at_most_limit_times(self):
        from PIL import Image
        original_open = Image.open

        open_call_count = [0]

        def counted_open(*args, **kwargs):
            open_call_count[0] += 1
            return original_open(*args, **kwargs)

        with patch("PIL.Image.open", side_effect=counted_open):
            result = api_list_storage_files(kind="generated", offset=0, limit=20)
            self.assertGreaterEqual(result["total"], 25)
            self.assertEqual(len(result["items"]), 20)
            # Must not open all 25+ files with PIL; at most limit (20)
            self.assertLessEqual(open_call_count[0], 20)
