"""S03: legacy (pre-storage_guard) updater first-upgrade compatibility.

Uses only a temporary staging directory and a fresh isolated Python process.
Does not import main.py, contact an update source, or change an installation.
"""
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LegacyUpdaterCompatibilityTests(unittest.TestCase):
    def test_compat_helper_identical_to_new_root_module(self):
        self.assertEqual(
            (ROOT / "storage_guard.py").read_bytes(),
            (ROOT / "static" / "storage_guard.py").read_bytes(),
        )

    def test_pre_s03_allowlist_copies_static_fallback(self):
        # This is the exact policy retained in main@ae042d8; no change to the
        # deployed old updater is assumed or possible at update time.
        def legacy_allows(path):
            path = str(path or "").replace("\\", "/").lstrip("/")
            if not path or any(p in {"", ".", ".."} for p in path.split("/")):
                return False
            return path in {"main.py", "VERSION"} or path.startswith("static/")

        self.assertFalse(legacy_allows("storage_guard.py"))
        self.assertTrue(legacy_allows("static/storage_guard.py"))

    def test_real_main_import_falls_back_in_legacy_staging(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        candidates = [
            node for node in tree.body
            if isinstance(node, ast.Try)
            and any(
                isinstance(n, ast.ImportFrom) and n.module == "storage_guard"
                for n in node.body
            )
        ]
        self.assertEqual(len(candidates), 1)
        import_block = ast.get_source_segment(source, candidates[0])
        with tempfile.TemporaryDirectory(prefix="s03_legacy_update_") as temp:
            stage = Path(temp)
            (stage / "static").mkdir()
            shutil.copyfile(
                ROOT / "static" / "storage_guard.py",
                stage / "static" / "storage_guard.py",
            )
            # -I ignores the repository working directory and PYTHONPATH.
            # Only stage/static/storage_guard.py is available as a module.
            script = (
                "import sys\n"
                "sys.path.insert(0, sys.argv[1])\n"
                + import_block + "\n"
                "assert open_scoped_file.__module__ == 'static.storage_guard'\n"
                "assert unlink_scoped_file.__module__ == 'static.storage_guard'\n"
            )
            result = subprocess.run(
                [sys.executable, "-I", "-c", script, str(stage)],
                cwd=str(stage), capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
