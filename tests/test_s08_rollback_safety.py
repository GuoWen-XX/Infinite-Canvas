"""S08: a failed rollback must leave the active application intact.

Extract the actual rollback_update function from main.py without importing the app.
All files and injected failures exist in a disposable temp directory.
"""
import ast
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class HttpError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code

class RollbackSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="s08_rollback_")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / "app"
        self.data = Path(self.tmp.name) / "data"
        self.base.mkdir()
        self.data.mkdir()
        self.selected = self.data / "update_backups" / "selected"
        (self.selected / "static").mkdir(parents=True)
        (self.base / "static").mkdir()
        self.put(self.base / "main.py", "new-main")
        self.put(self.base / "VERSION", "new-version")
        self.put(self.base / "static" / "index.html", "new-static")
        self.put(self.selected / "main.py", "old-main")
        self.put(self.selected / "VERSION", "old-version")
        self.put(self.selected / "static" / "index.html", "old-static")
        self.manifest = {"state": "ready", "from_version": "old", "root_files": {
            "main.py": {"existed": True}, "VERSION": {"existed": True}},
            "static_snapshot": {"exists": True}}
        self.backup_dir = self.data / "update_backups" / "rollback-safe"
        script = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(script)
        funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in {"rollback_update", "restore_failed_rollback"}]
        self.assertEqual(len(funcs), 2)
        funcs[0].decorator_list = []
        code = compile(ast.fix_missing_locations(ast.Module(body=funcs, type_ignores=[])),
                       str(ROOT / "main.py"), "exec")
        # create_update_backup is a controlled stand-in; it snapshots the live files.
        def create_backup(dst, roots, static, **kw):
            dst = Path(dst)
            dst.mkdir()
            shutil.copytree(self.base / "static", dst / "static")
            snap = {"root_files": {}}
            for rel in roots:
                src = self.base / rel
                snap["root_files"][rel] = {"existed": src.exists()}
                if src.exists():
                    shutil.copy2(src, dst / rel)
            snap["static_snapshot"] = {"exists": True}
            return snap
        self.ctx = dict(RollbackRequest=object, HTTPException=HttpError,
                        UPDATE_LOCK=threading.Lock(), os=os, shutil=shutil, DATA_DIR=str(self.data),
                        Dict=dict, Any=object,
                        read_update_backup_manifest=lambda p: self.manifest,
                        next_update_backup_dir=lambda prefix: str(self.backup_dir),
                        create_update_backup=create_backup,
                        current_app_version=lambda: "new",
                        safe_static_dir=lambda: str(self.base / "static"),
                        update_allowed_file=lambda p: p in {"main.py", "VERSION"},
                        safe_update_target=lambda p: str(self.base / p),
                        schedule_self_restart=lambda delay: False,
                        prune_update_backups=lambda names: [])
        exec(code, self.ctx)

    @staticmethod
    def put(path, text):
        Path(path).write_text(text, encoding="utf-8")

    def active_contents(self):
        return {(p.relative_to(self.base).as_posix()): p.read_text(encoding="utf-8")
                for p in self.base.rglob("*") if p.is_file()}

    def rollback(self):
        return self.ctx["rollback_update"](SimpleNamespace(
            name="selected", auto_restart=False, restart_delay=3))

    def test_static_copy_failure_recovers_live_files(self):
        before = self.active_contents()
        original = shutil.copytree
        def fail_selected(src, dst, *args, **kwargs):
            if str(src) == str(self.selected / "static"):
                Path(dst).mkdir(parents=True, exist_ok=True)
                self.put(Path(dst) / "index.html", "partial-damage")
                raise OSError("simulated partial static copy")
            return original(src, dst, *args, **kwargs)
        with patch.object(shutil, "copytree", side_effect=fail_selected):
            with self.assertRaises(HttpError):
                self.rollback()
        self.assertEqual(self.active_contents(), before)

    def test_root_replace_failure_recovers_static_and_root_files(self):
        before = self.active_contents()
        original = os.replace
        failed = [False]
        def fail_once(src, dst):
            if str(dst) == str(self.base / "main.py") and not failed[0]:
                failed[0] = True
                raise OSError("simulated root replace failure")
            return original(src, dst)
        with patch.object(os, "replace", side_effect=fail_once):
            with self.assertRaises(HttpError):
                self.rollback()
        self.assertEqual(self.active_contents(), before)

    def test_successful_rollback_preserves_prior_build_in_safety_backup(self):
        outcome = self.rollback()
        self.assertTrue(outcome["ok"])
        self.assertEqual((self.base / "VERSION").read_text(), "old-version")
        self.assertEqual((self.base / "static" / "index.html").read_text(), "old-static")
        self.assertEqual((self.backup_dir / "VERSION").read_text(), "new-version")
        self.assertEqual((self.backup_dir / "static" / "index.html").read_text(), "new-static")

if __name__ == "__main__":
    unittest.main()
