"""S08 release-source gate: no updater execution or real downloads."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

_MODULE = Path(__file__).resolve().parents[1] / "tools" / "check_s08_release_source.py"
_SPEC = importlib.util.spec_from_file_location("s08_updater_check", _MODULE)
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)


class ReleaseSourceGateTests(unittest.TestCase):
    def audit(self, content):
        with tempfile.TemporaryDirectory(prefix="s08_updater_") as root:
            path = Path(root) / "main.py"
            path.write_text(content, encoding="utf-8")
            return checker.audit(path, "GuoWen-XX/Infinite-Canvas", "main")

    def test_matching_fork_source_passes(self):
        result = self.audit('GITHUB_REPO_URL = "https://github.com/GuoWen-XX/Infinite-Canvas"\n'
                            'GITHUB_BRANCH = "main"\n')
        self.assertTrue(result["passed"])

    def test_upstream_repo_source_fails_even_if_branch_matches(self):
        result = self.audit('GITHUB_REPO_URL = "https://github.com/benkwok1983-cmd/Infinite-Canvas"\n'
                            'GITHUB_BRANCH = "main"\n')
        self.assertFalse(result["passed"])

    def test_wrong_branch_fails_even_if_repo_matches(self):
        result = self.audit('GITHUB_REPO_URL = "https://github.com/GuoWen-XX/Infinite-Canvas"\n'
                            'GITHUB_BRANCH = "zcode/iteration-01"\n')
        self.assertFalse(result["passed"])

    def test_nonconstant_source_fails_closed(self):
        result = self.audit('GITHUB_REPO_URL = get_repo_from_env()\nGITHUB_BRANCH = "main"\n')
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
