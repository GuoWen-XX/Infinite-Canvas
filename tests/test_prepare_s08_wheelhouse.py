"""Synthetic, no-network tests for the S08 wheelhouse staging command."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "tools" / "prepare_s08_wheelhouse.py"
SPEC = importlib.util.spec_from_file_location("prepare_s08", MODULE)
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


class PrepareWheelhouseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.repo = self.home / "repo"
        self.repo.mkdir()
        (self.repo / "requirements.txt").write_text("fastapi==0.141.1\n")
        (self.repo / "packages").mkdir()

    def run_tool(self, output, *flags):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return prepare.main(["--root", str(self.repo), "--output", str(output), *flags])

    def test_targets_windows_cp310_and_all_transitives(self):
        args = prepare.download_command("python", self.repo / "requirements.txt", self.home / "stage")
        self.assertEqual(args[args.index("--python-version") + 1], "3.10")
        self.assertEqual(args[args.index("--platform") + 1], "win_amd64")
        self.assertEqual(args[args.index("--abi") + 1], "cp310")
        self.assertIn("--only-binary=:all:", args)
        self.assertNotIn("--no-deps", args)

    def test_dry_run_does_not_download_or_create_output(self):
        output = self.home / "stage"
        with patch.object(prepare.subprocess, "run") as call:
            self.assertEqual(self.run_tool(output, "--dry-run"), 0)
            call.assert_not_called()
        self.assertFalse(output.exists())

    def test_nonempty_staging_is_rejected(self):
        output = self.home / "stage"
        output.mkdir()
        (output / "stale.whl").touch()
        with self.assertRaises(SystemExit):
            self.run_tool(output, "--dry-run")

    def test_cannot_overwrite_shipped_packages(self):
        with self.assertRaises(SystemExit):
            self.run_tool(self.repo / "packages", "--dry-run")

    def test_download_failure_does_not_claim_success(self):
        output = self.home / "stage"
        with patch.object(prepare.subprocess, "run", return_value=type("Result", (), {"returncode": 9})()):
            self.assertEqual(self.run_tool(output), 9)


if __name__ == "__main__":
    unittest.main()
