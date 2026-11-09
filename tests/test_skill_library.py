import os
import sys
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


def make_skill_dir(root, name="demo", with_md=True, scripts=False, references=False, assets=False):
    path = os.path.join(root, name)
    os.makedirs(path, exist_ok=True)
    if with_md:
        (Path(path) / "SKILL.md").write_text(
            "---\nname: demo\nversion: 1.0\nlicense: MIT\n---\n\nBody text here.\n", encoding="utf-8"
        )
    if scripts:
        (Path(path) / "scripts").mkdir()
        (Path(path) / "scripts" / "run.py").write_text("print('hi')\n", encoding="utf-8")
    if references:
        (Path(path) / "references").mkdir()
        (Path(path) / "references" / "style.md").write_text("style guide\n", encoding="utf-8")
    if assets:
        (Path(path) / "assets").mkdir()
        (Path(path) / "assets" / "palette.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return path


class SkillParseTests(unittest.TestCase):
    def test_parse_standard_frontmatter(self):
        fm, body = main.parse_skill_markdown_text("---\nname: demo\nversion: 1.0\ntags:\n  - a\n  - b\n---\n\nBody\n")
        self.assertEqual(fm["name"], "demo")
        self.assertEqual(str(fm["version"]), "1.0")
        self.assertEqual(fm["tags"], ["a", "b"])
        self.assertTrue(body.strip().startswith("Body"))

    def test_parse_without_frontmatter(self):
        fm, body = main.parse_skill_markdown_text("# Just markdown\n")
        self.assertEqual(fm, {})
        self.assertIn("Just markdown", body)

    def test_parse_broken_yaml_falls_back_to_flat(self):
        text = "---\nname: demo\nbad: [unclosed\n---\nBody\n"
        fm, body = main.parse_skill_markdown_text(text)
        self.assertEqual(fm.get("name"), "demo")
        self.assertIn("Body", body)

    def test_normalize_skill_id(self):
        self.assertEqual(main.normalize_skill_id("My Cool Skill! (v2)"), "my-cool-skill-v2")
        self.assertFalse(main.SKILL_ID_RE.match(main.normalize_skill_id("..")))
        self.assertTrue(main.SKILL_ID_RE.match(main.normalize_skill_id("Watercolor-Style 2")))


class SkillScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_entry_flags_scripts_references_and_warnings(self):
        path = make_skill_dir(self.root, scripts=True, references=True, assets=True)
        entry = main.skill_entry_from_dir(path, "custom", include_body=True)
        self.assertTrue(entry["has_skill_md"])
        self.assertTrue(entry["has_scripts"])
        self.assertEqual(entry["references_count"], 1)
        self.assertEqual(entry["assets_count"], 1)
        self.assertEqual(entry["license"], "MIT")
        self.assertEqual(entry["body"].strip(), "Body text here.")
        self.assertTrue(any("脚本" in w for w in entry["warnings"]))

    def test_entry_missing_md_warns(self):
        path = make_skill_dir(self.root, with_md=False)
        entry = main.skill_entry_from_dir(path, "custom")
        self.assertFalse(entry["has_skill_md"])
        self.assertTrue(any("SKILL.md" in w for w in entry["warnings"]))

    def test_traversal_blocked(self):
        with self.assertRaises(main.HTTPException) as ctx:
            main.skill_dir_for("custom", "../..")
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(main.HTTPException):
            main.skill_dir_for("custom", "..\\evil")
        with self.assertRaises(main.HTTPException):
            main.skill_dir_for("custom", "UPPER/CASE")

    def test_custom_crud_roundtrip(self):
        with patch.object(main, "SKILLS_CUSTOM_DIR", os.path.join(self.root, "custom")):
            os.makedirs(main.SKILLS_CUSTOM_DIR, exist_ok=True)
            created = main.skill_entry_from_dir(make_skill_dir(main.SKILLS_CUSTOM_DIR, "demo"), "custom")
            self.assertEqual(created["id"], "demo")
            self.assertIn("install", created)
            # 删除走 skill_dir_for 校验
            target = main.skill_dir_for("custom", "demo")
            shutil.rmtree(target)
            with self.assertRaises(main.HTTPException):
                main.skill_dir_for("custom", "demo")


class SkillZipSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _zip(self, entries, name="s.zip"):
        zip_path = os.path.join(self.root, name)
        with zipfile.ZipFile(zip_path, "w") as archive:
            for filename, data in entries:
                archive.writestr(filename, data)
        return zip_path

    def test_safe_extract_normal_repo_layout(self):
        zip_path = self._zip([
            ("owner-repo-sha/SKILL.md", "---\nname: demo\n---\nBody"),
            ("owner-repo-sha/references/g.md", "guide"),
        ])
        dest = os.path.join(self.root, "out")
        os.makedirs(dest)
        root, skipped = main.safe_extract_skill_zip(zip_path, dest)
        self.assertIsNone(skipped)
        self.assertTrue(os.path.isfile(os.path.join(root, "SKILL.md")))

    def test_swap_staged_into_target_rollback_on_move_failure(self):
        target = make_skill_dir(self.root, name="target", with_md=True)
        old_md = (Path(target) / "SKILL.md").read_text(encoding="utf-8")
        staged = make_skill_dir(self.root, name="staged", with_md=True)
        (Path(staged) / "SKILL.md").write_text("---\nname: staged\n---\nnew", encoding="utf-8")
        real_move = main.shutil.move
        def failing_move(src, dst, *a, **k):
            if str(dst) == str(target):
                raise OSError("simulated av lock")
            return real_move(src, dst, *a, **k)
        with patch.object(main.shutil, "move", failing_move):
            with self.assertRaises(OSError):
                main.swap_staged_into_target(staged, target, meta_writer=lambda: True)
        # 旧目录自动恢复、无备份残留
        self.assertTrue((Path(target) / "SKILL.md").read_text(encoding="utf-8") == old_md)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".target.install-bak")))

    def test_swap_staged_into_target_success_replaces(self):
        target = make_skill_dir(self.root, name="t2", with_md=True)
        staged = make_skill_dir(self.root, name="s2", with_md=True)
        (Path(staged) / "SKILL.md").write_text("---\nname: t2\n---\nreplaced", encoding="utf-8")
        backup_left, replaced = main.swap_staged_into_target(staged, target, meta_writer=lambda: True)
        self.assertTrue(replaced)
        self.assertFalse(backup_left)
        self.assertIn("replaced", (Path(target) / "SKILL.md").read_text(encoding="utf-8"))

    def test_swap_rollback_on_meta_write_failure(self):
        # 二次校审 P2 回归：元数据写入失败 → 新目录删除、旧目录恢复
        target = make_skill_dir(self.root, name="t3", with_md=True)
        old_md = (Path(target) / "SKILL.md").read_text(encoding="utf-8")
        staged = make_skill_dir(self.root, name="s3", with_md=True)
        (Path(staged) / "SKILL.md").write_text("---\nname: t3\n---\nnew", encoding="utf-8")
        with self.assertRaises(OSError):
            main.swap_staged_into_target(staged, target, meta_writer=lambda: False)
        self.assertEqual((Path(target) / "SKILL.md").read_text(encoding="utf-8"), old_md)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".t3.install-bak")))
        self.assertNotIn("new", (Path(target) / "SKILL.md").read_text(encoding="utf-8"))

    def test_validate_rejects_oversized_skill_md(self):
        src = make_skill_dir(self.root, name="big", with_md=True)
        (Path(src) / "SKILL.md").write_text("x" * (main.SKILLS_MAX_SKILL_MD_BYTES + 1), encoding="utf-8")
        staged = os.path.join(self.root, "staged-big")
        with self.assertRaises(main.HTTPException) as ctx:
            main.validate_and_stage_skill(src, staged)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_safe_extract_skips_large_files_but_keeps_skill_md(self):
        big = "x" * (main.SKILLS_SKIP_FILE_BYTES + 1024)
        zip_path = self._zip([
            ("packaged/SKILL.md", "---\nname: demo\n---\nBody"),
            ("packaged/examples/big.png", big),
            ("packaged/references/g.md", "guide"),
        ])
        dest = os.path.join(self.root, "outskip")
        os.makedirs(dest)
        root, skipped = main.safe_extract_skill_zip(zip_path, dest)
        self.assertIsNotNone(skipped)
        self.assertEqual(skipped["count"], 1)
        self.assertTrue(os.path.isfile(os.path.join(root, "SKILL.md")))
        self.assertTrue(os.path.isfile(os.path.join(root, "references", "g.md")))
        self.assertFalse(os.path.exists(os.path.join(root, "examples", "big.png")))
        self.assertTrue(os.path.isfile(os.path.join(root, ".skipped-large-files.json")))

    def test_zip_slip_entry_rejected(self):
        zip_path = self._zip([
            ("top/SKILL.md", "x"),
            ("top/../../evil.txt", "evil"),
        ])
        dest = os.path.join(self.root, "out2")
        os.makedirs(dest)
        with self.assertRaises(main.HTTPException) as ctx:
            main.safe_extract_skill_zip(zip_path, dest)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_bad_zip_rejected(self):
        bad = os.path.join(self.root, "bad.zip")
        Path(bad).write_bytes(b"not a zip at all")
        dest = os.path.join(self.root, "out3")
        os.makedirs(dest)
        with self.assertRaises(main.HTTPException):
            main.safe_extract_skill_zip(bad, dest)

    def test_locate_root_prefers_repo_root(self):
        repo = make_skill_dir(self.root, name="repo", with_md=True)
        found, rel = main.locate_skill_root(repo)
        self.assertEqual(found, repo)
        self.assertEqual(rel, "")

    def test_locate_root_unique_subdir(self):
        repo = os.path.join(self.root, "repo")
        os.makedirs(repo)
        make_skill_dir(repo, name="sub", with_md=True)
        found, rel = main.locate_skill_root(repo)
        self.assertEqual(os.path.basename(found), "sub")
        self.assertEqual(rel, "sub")

    def test_locate_root_multiple_candidates_rejected(self):
        repo = os.path.join(self.root, "repo2")
        os.makedirs(repo)
        make_skill_dir(repo, name="a", with_md=True)
        make_skill_dir(repo, name="b", with_md=True)
        with self.assertRaises(main.HTTPException) as ctx:
            main.locate_skill_root(repo)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_stage_rejects_missing_skill_md(self):
        src = make_skill_dir(self.root, name="src", with_md=False)
        staged = os.path.join(self.root, "staged")
        with self.assertRaises(main.HTTPException) as ctx:
            main.validate_and_stage_skill(src, staged)
        self.assertEqual(ctx.exception.status_code, 400)


class SkillSlugTests(unittest.TestCase):
    def test_repo_slug_variants(self):
        self.assertEqual(main.github_repo_slug("https://github.com/owner/repo"), ("owner", "repo", ""))
        self.assertEqual(main.github_repo_slug("https://github.com/owner/repo.git"), ("owner", "repo", ""))
        self.assertEqual(main.github_repo_slug("https://github.com/owner/repo/tree/dev"), ("owner", "repo", "dev"))
        self.assertEqual(main.github_repo_slug("https://evil.com/owner/repo"), ("", "", ""))
        self.assertEqual(main.github_repo_slug("not a url"), ("", "", ""))


class SkillsApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.custom_dir = os.path.join(self.tmp.name, "custom")
        os.makedirs(self.custom_dir)
        self._patcher = patch.object(main, "SKILLS_CUSTOM_DIR", self.custom_dir)
        self._patcher.start()
        from fastapi.testclient import TestClient

        self.client = TestClient(main.app)

    def tearDown(self):
        self._patcher.stop()
        self.tmp.cleanup()

    def test_create_list_update_delete_flow(self):
        resp = self.client.post("/api/skills/custom", json={"name": "My Style", "description": "测试风格", "content": "Body content here."})
        self.assertEqual(resp.status_code, 200)
        skill_id = resp.json()["id"]
        self.assertEqual(skill_id, "my-style")
        md_path = Path(self.custom_dir) / skill_id / "SKILL.md"
        self.assertTrue(md_path.is_file())
        self.assertIn("name: My Style", md_path.read_text(encoding="utf-8"))

        listed = self.client.get("/api/skills").json()["skills"]
        match = [s for s in listed if s["source"] == "custom" and s["id"] == skill_id]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["name"], "My Style")

        dup = self.client.post("/api/skills/custom", json={"name": "my style"})
        self.assertEqual(dup.status_code, 409)

        detail = self.client.get(f"/api/skills/custom/{skill_id}")
        self.assertEqual(detail.status_code, 200)
        detail_data = detail.json()
        self.assertIn("Body", detail_data["body"])

        updated = self.client.put(
            f"/api/skills/custom/{skill_id}",
            json={"content": "---\nname: My Style\n---\n\nNew body\n",
                  "base_sha256": detail_data["content_sha256"]},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertIn("New body", md_path.read_text(encoding="utf-8"))

        deleted = self.client.delete(f"/api/skills/custom/{skill_id}")
        self.assertEqual(deleted.status_code, 200)
        gone = self.client.get(f"/api/skills/custom/{skill_id}")
        self.assertEqual(gone.status_code, 404)

    def test_allow_api_fallback_put_get_roundtrip(self):
        # 校审 P1-2 回归：保存开关后重新 GET 应保持 true。
        # 二次校审 P1 修复：必须完全隔离——API_PROVIDERS_FILE 指向临时文件、
        # update_env_values 屏蔽（PUT 会同步写 API/.env），绝不触碰用户真实配置。
        temp_providers = os.path.join(self.tmp.name, "api_providers.json")
        env_locker = patch.object(main, "update_env_values", lambda updates: None)
        env_locker.start()
        self.addCleanup(env_locker.stop)
        rh_locker = patch.object(main, "sync_runninghub_provider_workflows_to_static_template", lambda provider: None)
        rh_locker.start()
        self.addCleanup(rh_locker.stop)
        file_locker = patch.object(main, "API_PROVIDERS_FILE", temp_providers)
        file_locker.start()
        self.addCleanup(file_locker.stop)
        # 播种临时配置（含 codex 平台）——默认集里没有 codex
        seed = main.default_api_providers() + [{
            "id": "codex", "name": "GPT CLI", "protocol": "codex",
            "chat_models": ["gpt-5.5"], "image_models": ["gpt-image-2"],
            "allow_api_fallback": False,
        }]
        Path(temp_providers).write_text(json.dumps(seed), encoding="utf-8")
        current = self.client.get("/api/providers").json()["providers"]
        payload = []
        for p in current:
            item = dict(p)
            item.pop("has_key", None); item.pop("key_preview", None); item.pop("key_env", None)
            item.pop("has_wallet_key", None); item.pop("wallet_key_preview", None); item.pop("wallet_key_env", None)
            item.pop("has_volcengine_access_key", None); item.pop("volcengine_access_key_preview", None)
            item.pop("has_volcengine_secret_access_key", None); item.pop("volcengine_secret_access_key_preview", None)
            if item.get("id") == "codex":
                item["allow_api_fallback"] = True
            payload.append(item)
        put = self.client.put("/api/providers", json=payload)
        self.assertEqual(put.status_code, 200, put.text[:200])
        after = {p["id"]: p for p in self.client.get("/api/providers").json()["providers"]}
        self.assertTrue(after["codex"]["allow_api_fallback"] is True)
        # 临时文件随 tearDown 自动清理，真实配置从未被触碰

    def test_create_rejects_unusable_name(self):
        # 纯符号名规范化后为空 → 400
        resp = self.client.post("/api/skills/custom", json={"name": "!!!"})
        self.assertEqual(resp.status_code, 400)

    def test_create_frontmatter_injection_is_neutralized(self):
        resp = self.client.post("/api/skills/custom", json={
            "name": "injection-test",
            "description": "d1\nversion: 9.9\nname: hacked",
        })
        self.assertEqual(resp.status_code, 200)
        md = (Path(self.custom_dir) / "injection-test" / "SKILL.md").read_text(encoding="utf-8")
        fm, _body = main.parse_skill_markdown_text(md)
        self.assertEqual(fm.get("name"), "injection-test")
        self.assertNotEqual(str(fm.get("version")), "9.9")
        self.assertIn("hacked", str(fm.get("description")))

    def test_check_update_and_upgrade_reject_non_github(self):
        created = self.client.post("/api/skills/custom", json={"name": "local-only"})
        self.assertEqual(created.status_code, 200)
        check = self.client.get("/api/skills/custom/local-only/check-update")
        self.assertEqual(check.status_code, 400)
        self.assertIn("GitHub", check.json()["detail"])
        upgrade = self.client.post("/api/skills/custom/local-only/upgrade", json={})
        self.assertEqual(upgrade.status_code, 400)

    def test_zip_install_409_then_overwrite(self):
        def zip_bytes():
            import io as _io
            buf = _io.BytesIO()
            with zipfile.ZipFile(buf, "w") as archive:
                archive.writestr("packaged/SKILL.md", "---\nname: zip-skill\n---\nfrom zip\n")
            return buf.getvalue()
        first = self.client.post("/api/skills/zip/install", files={"file": ("s.zip", zip_bytes(), "application/zip")})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["id"], "zip-skill")
        self.assertIn("from zip", (Path(self.custom_dir) / "zip-skill" / "SKILL.md").read_text(encoding="utf-8"))
        dup = self.client.post("/api/skills/zip/install", files={"file": ("s.zip", zip_bytes(), "application/zip")})
        self.assertEqual(dup.status_code, 409)
        over = self.client.post(
            "/api/skills/zip/install",
            files={"file": ("s.zip", zip_bytes(), "application/zip")},
            data={"overwrite": "true"},
        )
        self.assertEqual(over.status_code, 200)
        cleanup = self.client.delete("/api/skills/custom/zip-skill")
        self.assertEqual(cleanup.status_code, 200)

    def test_yaml_alias_bomb_is_neutralized(self):
        bomb = "a: &a [" + ",".join(["*a"] * 50) + "]\n" + "b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a,*a]\n"
        text = f"---\n{bomb}---\nBody"
        # 应快速返回（回退或截断），不得挂起或抛出
        fm, body = main.parse_skill_markdown_text(text)
        self.assertIn("Body", body)


class SkillLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_safe_extract_file_count_limit(self):
        entries = [(f"packaged/f{i}.txt", "x") for i in range(main.SKILLS_MAX_FILES + 2)]
        entries.insert(0, ("packaged/SKILL.md", "x"))
        zip_path = os.path.join(self.root, "many.zip")
        with zipfile.ZipFile(zip_path, "w") as archive:
            for filename, data in entries:
                archive.writestr(filename, data)
        dest = os.path.join(self.root, "outmany")
        os.makedirs(dest)
        with self.assertRaises(main.HTTPException) as ctx:
            main.safe_extract_skill_zip(zip_path, dest)
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
