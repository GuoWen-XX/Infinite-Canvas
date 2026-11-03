"""S06: tracked branch and installed commit must never be conflated.

No GitHub network, user Skill folders or credentials. Run:
python -m unittest tests.test_skill_upgrade_tracking -v
"""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import main
from fastapi import HTTPException

A = "a" * 40
B = "b" * 40
C = "c" * 40


class SkillUpgradeTrackingTests(unittest.TestCase):
    def test_abc_upgrade_keeps_tracking_branch(self):
        meta = main.skill_github_version_meta(
            {"source": "github", "repo_url": "https://github.com/example/styles"},
            A, "main", "")
        self.assertEqual(meta["tracking_ref"], "main")
        self.assertEqual(meta["commit_sha"], A)
        meta = main.skill_github_version_meta(meta, B, main.skill_github_tracking_ref(meta), "skills/ink")
        self.assertEqual(meta["commit_sha"], B)
        self.assertEqual(meta["tracking_ref"], "main")
        meta = main.skill_github_version_meta(meta, C, main.skill_github_tracking_ref(meta), "skills/ink")
        self.assertEqual(meta["commit_sha"], C)
        self.assertEqual(meta["ref"], "main")
        self.assertEqual(meta["tracking_ref"], "main")

    def test_nondefault_tracking_branch_not_replaced_with_commit_sha(self):
        meta = main.skill_github_version_meta({}, A, "develop", "subdir")
        self.assertEqual(main.skill_github_tracking_ref(meta), "develop")
        meta = main.skill_github_version_meta(meta, B, main.skill_github_tracking_ref(meta), "subdir")
        self.assertEqual(meta["tracking_ref"], "develop")
        self.assertEqual(meta["commit_sha"], B)

    def test_old_install_with_sha_in_ref_uses_default_branch(self):
        legacy = {"ref": A, "commit_sha": A}
        self.assertEqual(main.skill_github_tracking_ref(legacy), "")

    def test_legacy_branch_ref_migrates_without_losing_branch(self):
        legacy = {"ref": "release-v2", "commit_sha": A}
        self.assertEqual(main.skill_github_tracking_ref(legacy), "release-v2")
        upgraded = main.skill_github_version_meta(
            legacy, B, main.skill_github_tracking_ref(legacy), "styles")
        self.assertEqual(upgraded["tracking_ref"], "release-v2")

    def test_installing_exact_sha_tracks_default_branch_for_future_updates(self):
        meta = main.skill_github_version_meta({}, A, A, "")
        self.assertEqual(meta["commit_sha"], A)
        self.assertEqual(meta["tracking_ref"], "")
        self.assertEqual(main.skill_github_tracking_ref(meta), "")

    def test_dependency_missing_blocks_github_install_before_download(self):
        download = AsyncMock()
        payload = main.SkillGithubInstallRequest(
            url="https://github.com/example/styles", sha=A, tracking_ref="main")
        with patch.object(main, "_skill_yaml", None), patch.object(
                main, "github_download_repo_zip", download):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(main.api_skill_github_install(payload))
        self.assertEqual(ctx.exception.status_code, 503)
        download.assert_not_awaited()

    def test_dependency_missing_blocks_upgrade_before_filesystem_access(self):
        with patch.object(main, "_skill_yaml", None), patch.object(
                main, "skill_dir_for", side_effect=AssertionError("filesystem touched")):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(main.api_skill_upgrade("ink", main.SkillUpgradeRequest(sha=B)))
        self.assertEqual(ctx.exception.status_code, 503)

    def test_check_update_resolves_default_for_legacy_sha_ref(self):
        resolver = AsyncMock(return_value={"sha": B, "commit_message": "updated"})
        meta = {
            "source": "github", "repo_url": "https://github.com/example/styles",
            "ref": A, "commit_sha": A
        }
        with patch.object(main, "skill_dir_for", return_value="/unused"), patch.object(
                main, "skill_read_meta", return_value=meta), patch.object(
                main, "github_resolve_commit", resolver):
            data = asyncio.run(main.api_skill_check_update("ink"))
        resolver.assert_awaited_once_with("https://github.com/example/styles", "")
        self.assertEqual(data["current_sha"], A)
        self.assertEqual(data["latest_sha"], B)
        self.assertFalse(data["up_to_date"])

    def test_transactional_overwrite_rolls_back_on_meta_failure(self):
        with tempfile.TemporaryDirectory(prefix="s06_skill_") as temp:
            target = os.path.join(temp, "ink")
            staged = os.path.join(temp, "new")
            os.makedirs(target)
            os.makedirs(staged)
            with open(os.path.join(target, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("original A")
            with open(os.path.join(staged, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("replacement B")
            with self.assertRaises(OSError):
                main.swap_staged_into_target(staged, target, meta_writer=lambda: False)
            with open(os.path.join(target, "SKILL.md"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "original A")

    def test_require_pyyaml_missing_does_not_touch_files(self):
        with patch.object(main, "_skill_yaml", None):
            with self.assertRaises(HTTPException) as ctx:
                main.require_skill_yaml()
        self.assertEqual(ctx.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
