"""Pure Python release-source checks; never execute updater or contact network."""
import ast
import importlib.util
import tempfile
import unittest
from pathlib import Path

_MODULE = Path(__file__).resolve().parents[1] / "tools" / "check_s08_release_source.py"
_SPEC = importlib.util.spec_from_file_location("s08_updater_check", _MODULE)
checker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(checker)


def source(repo="GuoWen-XX/Infinite-Canvas", branch="main"):
    return (f'GITHUB_REPO_URL = "https://github.com/{repo}"\n'
            f'GITHUB_BRANCH = "{branch}"\n'
            f'GITHUB_VERSION_URL = f"https://raw.githubusercontent.com/{repo}/{{GITHUB_BRANCH}}/VERSION"\n'
            f'GITHUB_TREE_URL = f"https://api.github.com/repos/{repo}/git/trees/{{GITHUB_BRANCH}}?recursive=1"\n'
            f'GITHUB_RAW_ROOT = f"https://raw.githubusercontent.com/{repo}/{{GITHUB_BRANCH}}"\n'
            'GITHUB_UPDATE_NOTES_URL = GITHUB_RAW_ROOT + "/static/update-notes.json"\n')


class ReleaseSourceGateTests(unittest.TestCase):
    def audit(self, content):
        with tempfile.TemporaryDirectory(prefix="s08_updater_") as root:
            path = Path(root) / "main.py"
            path.write_text(content, encoding="utf-8")
            return checker.audit(path, "GuoWen-XX/Infinite-Canvas", "main")

    def test_matching_fork_source_passes(self):
        self.assertTrue(self.audit(source())["passed"])

    def test_upstream_repo_source_fails_even_if_branch_matches(self):
        self.assertFalse(self.audit(source(repo="benkwok1983-cmd/Infinite-Canvas"))["passed"])

    def test_wrong_branch_fails_even_if_repo_matches(self):
        self.assertFalse(self.audit(source(branch="zcode/iteration-01"))["passed"])

    def test_nonconstant_source_fails_closed(self):
        self.assertFalse(self.audit(source().replace(
            'GITHUB_REPO_URL = "https://github.com/GuoWen-XX/Infinite-Canvas"',
            'GITHUB_REPO_URL = get_repo_from_env()'))["passed"])

    def test_duplicate_later_override_fails_closed(self):
        self.assertFalse(self.audit(source()+'GITHUB_BRANCH = "zcode/iteration-01"\n')["passed"])

    def test_unsupported_augmented_assignment_fails_closed(self):
        self.assertFalse(self.audit(source()+'GITHUB_BRANCH += "-unsafe"\n')["passed"])

    def test_derived_version_url_wrong_repo_fails(self):
        self.assertFalse(self.audit(source().replace(
            'raw.githubusercontent.com/GuoWen-XX', 'raw.githubusercontent.com/other', 1))["passed"])

    def test_wrong_tree_ref_fails(self):
        self.assertFalse(self.audit(source().replace(
            '/git/trees/{GITHUB_BRANCH}', '/git/trees/zcode'))["passed"])

    def test_non_literal_derived_url_fails(self):
        self.assertFalse(self.audit(source().replace(
            'GITHUB_RAW_ROOT = f"https://raw.githubusercontent.com/GuoWen-XX/Infinite-Canvas/{GITHUB_BRANCH}"',
            'GITHUB_RAW_ROOT = get_override()'))["passed"])

    def test_missing_update_notes_url_fails(self):
        self.assertFalse(self.audit(source().replace(
            'GITHUB_UPDATE_NOTES_URL = GITHUB_RAW_ROOT + "/static/update-notes.json"', ''))["passed"])

    def test_tuple_unpacking_cannot_bypass_branch_gate(self):
        result = self.audit(source().replace(
            'GITHUB_BRANCH = "main"', 'GITHUB_BRANCH, *_ = "main"'))
        self.assertFalse(result["passed"])
        self.assertIn("unsupported destructuring/chained assignment to GITHUB_BRANCH",
                      result["problems"])

    def test_list_unpacking_cannot_bypass_branch_gate(self):
        self.assertFalse(self.audit(source().replace(
            'GITHUB_BRANCH = "main"', '[GITHUB_BRANCH] = ["main"]'))["passed"])

    def test_starred_branch_target_fails_closed(self):
        self.assertFalse(self.audit(source().replace(
            'GITHUB_BRANCH = "main"', '*GITHUB_BRANCH, other = "main"'))["passed"])

    def test_chained_assignment_cannot_bypass_branch_gate(self):
        self.assertFalse(self.audit(source().replace(
            'GITHUB_BRANCH = "main"', 'GITHUB_BRANCH = branch_alias = "main"'))["passed"])

    def test_unrelated_unpacking_does_not_block_valid_source(self):
        self.assertTrue(self.audit(source() + 'dummy, other = "ab"\n')["passed"])

    def test_live_main_file_uses_safe_github_urls(self):
        path = Path(__file__).resolve().parents[1] / "main.py"
        self.assertTrue(checker.audit(path, "GuoWen-XX/Infinite-Canvas", "main")["passed"])
        ast.parse(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
