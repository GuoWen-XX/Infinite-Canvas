"""Regression for S08 rollback selectors: never treat a backup root or link as a restore point.

Runs without FastAPI or packaged dependencies. It extracts the actual rollback_update
function from main.py and injects a temporary backup tree and mocks.
"""
import ast
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


class FakeHTTPException(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def function_under_test():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "rollback_update")
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    return compile(module, "main.py", "exec")


class RollbackSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = function_under_test()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="s08-rollback-selector-")
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.backups = self.data / "update_backups"
        self.backups.mkdir(parents=True)
        (self.backups / "valid").mkdir()
        (self.backups / "valid" / "subdir").mkdir()
        self.outside = Path(self.temp.name) / "outside"
        self.outside.mkdir()
        self.symlinks_supported = True
        try:
            (self.backups / "linked").symlink_to(self.outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.symlinks_supported = False
        self.lock = threading.Lock()
        self.backup_creation_calls = []

        def next_backup(*args, **kwargs):
            self.backup_creation_calls.append("next")
            raise RuntimeError("test stopped before any restore writes")

        scope = {
            "RollbackRequest": SimpleNamespace,
            "HTTPException": FakeHTTPException,
            "UPDATE_LOCK": self.lock,
            "DATA_DIR": str(self.data),
            "os": os,
            "read_update_backup_manifest": lambda path: {"state": "ready", "root_files": {}},
            "next_update_backup_dir": next_backup,
        }
        exec(self.code, scope)
        self.rollback = scope["rollback_update"]

    def assert_rejected(self, name, status=400):
        with self.assertRaises(FakeHTTPException) as caught:
            self.rollback(SimpleNamespace(name=name, auto_restart=False, restart_delay=3))
        self.assertEqual(caught.exception.status_code, status, str(caught.exception))
        self.assertEqual(self.backup_creation_calls, [], "invalid name must not write files")
        self.assertFalse(self.lock.locked(), "rollback lock was not released")

    def test_rejects_empty_name(self):
        self.assert_rejected("")

    def test_rejects_backup_root_dot(self):
        self.assert_rejected(".")

    def test_rejects_backup_root_dot_slash(self):
        self.assert_rejected("./")

    def test_rejects_nested_backup_selector(self):
        self.assert_rejected("valid/subdir")

    def test_rejects_dotdot_segments_even_if_normalized_inside(self):
        self.assert_rejected("valid/../valid")

    def test_rejects_absolute_selector_inside_backups(self):
        self.assert_rejected(str(self.backups / "valid"))

    def test_rejects_symlink_to_external_directory(self):
        if not self.symlinks_supported:
            self.skipTest("symlinks unavailable on this filesystem")
        self.assert_rejected("linked")

    def test_rejects_windows_separator(self):
        self.assert_rejected("valid\\subdir")

    def test_rejects_nul_name(self):
        self.assert_rejected("valid\x00other")

    def test_rejects_parent_escape(self):
        self.assert_rejected("..")

    def test_unknown_normal_backup_reports_not_found(self):
        self.assert_rejected("missing", status=404)

    def test_valid_name_may_reach_backup_creation_without_selector_rejection(self):
        with self.assertRaises(FakeHTTPException) as caught:
            self.rollback(SimpleNamespace(name="valid", auto_restart=False, restart_delay=3))
        self.assertEqual(caught.exception.status_code, 500)
        self.assertEqual(self.backup_creation_calls, ["next"])
        self.assertFalse(self.lock.locked())


if __name__ == "__main__":
    unittest.main()
