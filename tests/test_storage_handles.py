"""S03: independently executable handle-level race and symlink regressions.

This module imports only Python stdlib + storage_guard; no main.py import
or paid network access. Exercise actual file descriptors, not lexical paths.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import storage_guard


class StorageGuardHandleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="s03_handle_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "allowed"
        self.root.mkdir()
        self.outside = Path(self.temp.name) / "outside"
        self.outside.mkdir()
        self.secret = self.outside / "secret.txt"
        self.secret.write_bytes(b"OUTSIDE-SECRET")

    def _link(self, dest, target):
        try:
            dest.symlink_to(target, target_is_directory=target.is_dir())
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")

    def test_nested_legitimate_file_is_readable(self):
        folder = self.root / "nested"
        folder.mkdir()
        file = folder / "good.png"
        file.write_bytes(b"good")
        with storage_guard.open_scoped_file(str(self.root), str(file)) as source:
            self.assertEqual(source.read(), b"good")

    def test_file_link_to_outside_refused(self):
        link = self.root / "leak.png"
        self._link(link, self.secret)
        with self.assertRaises(storage_guard.UnsafeStoragePath):
            storage_guard.open_scoped_file(str(self.root), str(link))

    def test_already_opened_handle_cannot_be_redirected_after_swap(self):
        if os.name == "nt":
            self.skipTest("Windows file replacement semantics require native fixture")
        file = self.root / "safe.png"
        file.write_bytes(b"ORIGINAL")
        with storage_guard.open_scoped_file(str(self.root), str(file)) as source:
            file.unlink()
            self._link(file, self.secret)
            self.assertEqual(source.read(), b"ORIGINAL")
        self.assertEqual(self.secret.read_bytes(), b"OUTSIDE-SECRET")

    def test_parent_symlink_swap_is_not_followed_after_path_check(self):
        if os.name == "nt":
            self.skipTest("POSIX directory-fd race regression")
        folder = self.root / "nested"
        folder.mkdir()
        file = folder / "image.png"
        file.write_bytes(b"GOOD")
        original = storage_guard._parts_beneath

        def attacker_swap(root, path, **kwargs):
            result = original(root, path, **kwargs)
            folder.rename(self.root / "renamed")
            self._link(folder, self.outside)
            return result

        (self.outside / "image.png").write_bytes(b"OUTSIDE")
        with patch.object(storage_guard, "_parts_beneath", side_effect=attacker_swap):
            with self.assertRaises((OSError, storage_guard.UnsafeStoragePath)):
                storage_guard.open_scoped_file(str(self.root), str(file))
        self.assertEqual((self.outside / "image.png").read_bytes(), b"OUTSIDE")

    def test_unlink_alias_keeps_original_within_root(self):
        original = self.root / "original.png"
        original.write_bytes(b"PRESERVE-ME")
        alias = self.root / "alias.png"
        self._link(alias, original)
        storage_guard.unlink_scoped_file(str(self.root), str(alias))
        self.assertFalse(os.path.lexists(alias))
        self.assertEqual(original.read_bytes(), b"PRESERVE-ME")

    def test_unlink_external_target_alias_refused(self):
        alias = self.root / "forbidden.png"
        self._link(alias, self.secret)
        with self.assertRaises(storage_guard.UnsafeStoragePath):
            storage_guard.unlink_scoped_file(str(self.root), str(alias))
        self.assertTrue(os.path.lexists(alias))
        self.assertEqual(self.secret.read_bytes(), b"OUTSIDE-SECRET")

    def test_unlink_stays_in_open_parent_if_parent_moved(self):
        if os.name == "nt":
            self.skipTest("POSIX directory-fd unlink race regression")
        folder = self.root / "nested"
        folder.mkdir()
        original = folder / "image.png"
        original.write_bytes(b"ORIGINAL")
        external = self.outside / "image.png"
        external.write_bytes(b"OUTSIDE")
        actual = storage_guard._open_posix_parent

        def move_after_open(root, parts):
            parent_fd = actual(root, parts)
            folder.rename(self.root / "moved")
            self._link(folder, self.outside)
            return parent_fd

        with patch.object(storage_guard, "_open_posix_parent", side_effect=move_after_open):
            storage_guard.unlink_scoped_file(str(self.root), str(original))
        self.assertFalse((self.root / "moved" / "image.png").exists())
        self.assertEqual(external.read_bytes(), b"OUTSIDE")

    def test_fifo_without_writer_rejected_without_blocking(self):
        if os.name == "nt" or not hasattr(os, "mkfifo"):
            self.skipTest("POSIX FIFO test")
        pipe = self.root / "unexpected.png"
        os.mkfifo(pipe)
        # A regression must fail with a timeout rather than hang the suite.
        script = (
            "import storage_guard, sys\n"
            "try:\n"
            "    storage_guard.open_scoped_file(sys.argv[1], sys.argv[2])\n"
            "except storage_guard.UnsafeStoragePath:\n"
            "    sys.exit(0)\n"
            "sys.exit(3)\n"
        )
        run = subprocess.run(
            [sys.executable, "-c", script, str(self.root), str(pipe)],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_regular_file_swapped_to_fifo_before_open_is_rejected(self):
        if os.name == "nt" or not hasattr(os, "mkfifo"):
            self.skipTest("POSIX FIFO race test")
        file = self.root / "image.png"
        file.write_bytes(b"ORIGINAL")
        script = """
import os
import sys
from unittest.mock import patch
import storage_guard
root, filename = sys.argv[1:3]
original = storage_guard._parts_beneath
def swap(root_arg, path, **kwargs):
    result = original(root_arg, path, **kwargs)
    os.unlink(filename)
    os.mkfifo(filename)
    return result
with patch.object(storage_guard, "_parts_beneath", side_effect=swap):
    try:
        storage_guard.open_scoped_file(root, filename)
    except storage_guard.UnsafeStoragePath:
        sys.exit(0)
sys.exit(3)
"""
        run = subprocess.run(
            [sys.executable, "-c", script, str(self.root), str(file)],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_windows_extended_unc_path_normalizes(self):
        self.assertEqual(
            storage_guard._normalize_windows_path("\\\\?\\UNC\\server\\share\\dir\\file.png"),
            storage_guard._normalize_windows_path("\\\\server\\share\\dir\\file.png"),
        )


if __name__ == "__main__":
    unittest.main()
