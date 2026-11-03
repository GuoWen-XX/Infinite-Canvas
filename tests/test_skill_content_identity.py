"""S05: body-only Skill edits preserve metadata and stable variant identity.

Only temporary synthetic SKILL.md fixtures are used; no real user Skills,
keys, network requests, models or external directories are touched.
Run: python -m unittest tests.test_skill_content_identity -v
"""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

import main
from fastapi import HTTPException


FIXTURE = """---
name: Ink Skill
description: Sample
version: 2.4
license: MIT
x-artist:
  school: sumi-e
  colors: [black, blue]
variants:
  - id: sumi-custom-17
    label: Old Ink
    prompt: old prompt
    x-brush: dry
---
# Original body
"""


class SkillContentIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="s05_skill_")
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(main, "SKILLS_CUSTOM_DIR", self.temp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.target = os.path.join(self.temp.name, "ink-skill")
        os.mkdir(self.target)
        self.skill_md = os.path.join(self.target, "SKILL.md")
        with open(self.skill_md, "w", encoding="utf-8") as f:
            f.write(FIXTURE)

    def source(self):
        with open(self.skill_md, encoding="utf-8") as f:
            return f.read()

    def update(self, body, variants=None, content_format="body"):
        payload = main.SkillUpdateRequest(
            content=body, variants=variants, content_format=content_format)
        return asyncio.run(main.api_skill_update("ink-skill", payload))

    def test_body_only_update_keeps_unknown_metadata_and_comments(self):
        before_header = self.source().split("---\n# Original body")[0]
        self.update("# Updated body\n")
        updated = self.source()
        self.assertTrue(updated.startswith(before_header))
        metadata, body = main.parse_skill_markdown_text(updated)
        self.assertEqual(body, "# Updated body\n")
        self.assertEqual(metadata["x-artist"]["school"], "sumi-e")
        self.assertEqual(metadata["version"], 2.4)
        self.assertEqual(metadata["variants"][0]["id"], "sumi-custom-17")

    def test_label_rename_keeps_custom_id_and_extra_variant_keys(self):
        variants = [main.SkillVariantItem(
            id="sumi-custom-17", label="New display name", prompt="new prompt")]
        self.update("# Revised body\n", variants)
        metadata, body = main.parse_skill_markdown_text(self.source())
        variant = metadata["variants"][0]
        self.assertEqual(variant["id"], "sumi-custom-17")
        self.assertEqual(variant["x-brush"], "dry")
        self.assertEqual(variant["label"], "New display name")
        self.assertEqual(metadata["x-artist"]["colors"], ["black", "blue"])
        self.assertEqual(body, "# Revised body\n")

    def test_unchanged_variants_preserve_original_yaml_header(self):
        items = [main.SkillVariantItem(
            id="sumi-custom-17", label="Old Ink", prompt="old prompt")]
        self.update("New body", items)
        self.assertTrue(self.source().startswith(FIXTURE.split("---\n# Original body")[0]))
        self.assertTrue(self.source().endswith("---\nNew body"))

    def test_unknown_supplied_id_refused_and_original_untouched(self):
        original = self.source()
        with self.assertRaises(HTTPException) as ctx:
            self.update("bad", [main.SkillVariantItem(
                id="nonexistent-stable-id", label="New", prompt="")])
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(self.source(), original)

    def test_duplicate_ids_refused_without_writing(self):
        original = self.source()
        with self.assertRaises(HTTPException) as ctx:
            self.update("bad", [
                main.SkillVariantItem(id="sumi-custom-17", label="A"),
                main.SkillVariantItem(id="sumi-custom-17", label="B"),
            ])
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(self.source(), original)

    def test_malformed_original_yaml_refuses_destructive_update(self):
        broken = "---\nname: [unterminated\n---\n# Protected body\n"
        with open(self.skill_md, "w", encoding="utf-8") as f:
            f.write(broken)
        with self.assertRaises(HTTPException) as ctx:
            self.update("new content")
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(self.source(), broken)

    def test_explicit_markdown_mode_can_replace_full_document(self):
        replacement = "---\nname: Replaced\ncustom: true\n---\nWhole new document\n"
        self.update(replacement, content_format="markdown")
        self.assertEqual(self.source(), replacement)

    def test_whole_markdown_mode_requires_valid_header(self):
        original = self.source()
        with self.assertRaises(HTTPException) as ctx:
            self.update("Bare markdown", content_format="markdown")
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(self.source(), original)

    def test_atomic_replace_failure_preserves_original_and_cleans_temp(self):
        original = self.source()
        with patch.object(main, "replace_with_retry", side_effect=OSError("disk full")):
            with self.assertRaises(HTTPException) as ctx:
                self.update("# Would be lost")
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(self.source(), original)
        self.assertEqual([x for x in os.listdir(self.target) if x.startswith(".skill-")], [])

    def test_missing_yaml_dependency_refuses_before_writing(self):
        original = self.source()
        with patch.object(main, "_skill_yaml", None):
            with self.assertRaises(HTTPException) as ctx:
                self.update("Unsafe edit")
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(self.source(), original)

    def test_opaque_custom_variant_id_survives_label_edit(self):
        original = self.source().replace("sumi-custom-17", "Ink@Version2")
        with open(self.skill_md, "w", encoding="utf-8") as file:
            file.write(original)
        self.update("Body edited", [main.SkillVariantItem(
            id="Ink@Version2", label="Renamed display", prompt="new directive")])
        meta, _ = main.parse_skill_markdown_text(self.source())
        self.assertEqual(meta["variants"][0]["id"], "Ink@Version2")
        entry = main.skill_entry_from_dir(self.target, "custom", include_body=True)
        self.assertEqual(entry["variants"][0]["id"], "Ink@Version2")

    def test_preexisting_normalized_canvas_variant_id_remains_resolvable(self):
        original = self.source().replace("sumi-custom-17", "Ink@Version2")
        with open(self.skill_md, "w", encoding="utf-8") as file:
            file.write(original)
        # Previous UI emitted a normalized slug even for an opaque author ID.
        selection = main.SkillSelection(
            source="custom", id="ink-skill", mode="fast", variant="ink-version2")
        selected = main.skill_diff_for_preview(selection, "user prompt")
        self.assertIn("old prompt", selected["compiled_prompt"])

    def test_preview_rejects_missing_variant_id(self):
        selection = main.SkillSelection(
            source="custom", id="ink-skill", mode="fast", variant="deleted-variant")
        with self.assertRaises(HTTPException) as ctx:
            main.skill_diff_for_preview(selection, "prompt")
        self.assertEqual(ctx.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
