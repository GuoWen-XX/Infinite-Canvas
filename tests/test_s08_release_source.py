"""S08 release-source gate: no updater execution or real downloads."""
import ast
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

    def test_live_main_file_uses_safe_github_urls(self):
        path = Path(__file__).resolve().parents[1] / "main.py"
        self.assertTrue(checker.audit(path, "GuoWen-XX/Infinite-Canvas", "main")["passed"])
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        paths = {"GITHUB_VERSION_URL", "GITHUB_TREE_URL", "GITHUB_RAW_ROOT"}
        checked = set()
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id not in paths:
                continue
            self.assertIsInstance(node.value, ast.JoinedStr)
            literals = "".join(part.value for part in node.value.values
                               if isinstance(part, ast.Constant) and isinstance(part.value, str))
            self.assertIn("GuoWen-XX/Infinite-Canvas", literals)
            self.assertNotIn("benkwok1983-cmd/Infinite-Canvas", literals)
            self.assertTrue(any(isinstance(part, ast.FormattedValue)
                                and isinstance(part.value, ast.Name)
                                and part.value.id == "GITHUB_BRANCH"
                                for part in node.value.values))
            checked.add(target.id)
        self.assertEqual(checked, paths)


if __name__ == "__main__":
    unittest.main()
