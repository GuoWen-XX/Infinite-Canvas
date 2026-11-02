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

    def test_posix_root_replaced_with_symlink_cannot_escape(self):
        if os.name == "nt":
            self.skipTest("POSIX root replacement fixture")
        file = self.root / "image.png"
        file.write_bytes(b"INSIDE")
        (self.outside / "image.png").write_bytes(b"OUTSIDE")
        original = storage_guard._parts_beneath
        moved = self.root.with_name("original_moved")

        def replace_root(root, path, **kwargs):
            parts = original(root, path, **kwargs)
            self.root.rename(moved)
            self._link(self.root, self.outside)
            return parts

        with patch.object(storage_guard, "_parts_beneath", side_effect=replace_root):
            with self.assertRaises((OSError, storage_guard.UnsafeStoragePath)):
                storage_guard.open_scoped_file(str(self.root), str(file))
        self.assertEqual((self.outside / "image.png").read_bytes(), b"OUTSIDE")

    def test_posix_search_only_directory_remains_accessible(self):
        if os.name == "nt":
            self.skipTest("POSIX search-only directory")
        if not (getattr(os, "O_PATH", None) is not None
                or getattr(os, "O_SEARCH", None) is not None):
            self.skipTest("platform lacks search-only directory FD")
        # Do not use TMPDIR: under root it may be /root/private/0700 and
        # nobody cannot traverse its *ancestors*. Never chmod TMPDIR itself.
        public_base = Path("/tmp")
        if not public_base.is_dir():
            self.skipTest("No public POSIX test fixture base")
        import stat
        for ancestor in (public_base.resolve(), *public_base.resolve().parents):
            if not (ancestor.stat().st_mode & stat.S_IXOTH):
                self.skipTest("Public POSIX test fixture has private ancestor")

        privileged = hasattr(os, "geteuid") and os.geteuid() == 0
        if privileged:
            try:
                import pwd
                pwd.getpwnam("nobody")
            except (ImportError, KeyError):
                self.skipTest("nobody account unavailable for unprivileged fixture")

        # This is a new isolated fixture under a verified public base, not a
        # change to an existing user-controlled or configured media folder.
        with tempfile.TemporaryDirectory(prefix="s03_search_perm_", dir=str(public_base)) as temp:
            sandbox = Path(temp)
            sandbox.chmod(0o755)
            root = sandbox / "allowed"
            root.mkdir(mode=0o755)
            # mkdir mode is filtered by umask (e.g. 077 -> 0700).
            # Ensure the unprivileged child can search this isolated root.
            root.chmod(0o755)
            folder = root / "search_only"
            folder.mkdir()
            target = folder / "readable.png"
            target.write_bytes(b"READABLE")
            target.chmod(0o644)
            folder.chmod(0o733 if privileged else 0o311)

            # -I isolates imports from checkout cwd and PYTHONPATH. Staging
            # an exact helper copy also avoids relying on checkout permissions.
            helper_copy = sandbox / "storage_guard.py"
            helper_copy.write_bytes(Path(storage_guard.__file__).read_bytes())
            helper_copy.chmod(0o644)
            script = r"""
import os
import sys
root, path, restricted, helper_dir, drop = sys.argv[1:6]
sys.path.insert(0, helper_dir)
import storage_guard
assert os.path.realpath(storage_guard.__file__) == os.path.realpath(
    os.path.join(helper_dir, "storage_guard.py")
)
# The interpreter, stdlib and helper have ALL been loaded before changing UID.
# This permits Python installed under private /root/.pyenv or similar.
if drop == "1":
    import pwd
    nobody = pwd.getpwnam("nobody")
    os.setgroups([])
    os.setgid(nobody.pw_gid)
    os.setuid(nobody.pw_uid)
    assert os.geteuid() == nobody.pw_uid
flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
try:
    old_fd = os.open(restricted, flags)
except PermissionError:
    pass
else:
    os.close(old_fd)
    sys.exit("old O_RDONLY unexpectedly opened a directory without read")
with storage_guard.open_scoped_file(root, path) as source:
    assert source.read() == b"READABLE"
storage_guard.unlink_scoped_file(root, path)
assert not os.path.lexists(path)
"""
            try:
                result = subprocess.run(
                    [sys.executable, "-I", "-c", script, str(root), str(target),
                     str(folder), str(sandbox), "1" if privileged else "0"],
                    cwd=str(sandbox), capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            finally:
                # Preserve TemporaryDirectory cleanup even after a test
                # failure; owner needs read permission for rmtree/scandir.
                folder.chmod(0o755)

    def test_windows_handle_compare_does_not_reresolve_mutable_root(self):
        trusted = r"C:\\media\\allowed"
        outside = r"C:\\external\\secret.png"
        with patch.object(storage_guard, "_windows_handle_path", return_value=outside), \
             patch.object(storage_guard.os.path, "realpath", return_value=r"C:\\external"):
            self.assertFalse(storage_guard._windows_handle_inside(trusted, 1234))

    def test_windows_extended_unc_path_normalizes(self):
        self.assertEqual(
            storage_guard._normalize_windows_path("\\\\?\\UNC\\server\\share\\dir\\file.png"),
            storage_guard._normalize_windows_path("\\\\server\\share\\dir\\file.png"),
        )


if __name__ == "__main__":
    unittest.main()
