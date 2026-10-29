"""Isolated review probes: assert the observed defects, not corrected behavior.
No live providers, accounts, external writes or browser automation.
"""
import asyncio
import io
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import AsyncMock, patch

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'main.py').is_file())
sys.path.insert(0, str(ROOT))
os.environ['TEMP'] = os.environ['TMP'] = str(ROOT / '.review-tmp')
(ROOT / '.review-tmp').mkdir(exist_ok=True)
tempfile.tempdir = str(ROOT / '.review-tmp')
import main


class ReviewProbes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / '.review-tmp')
        self.root = Path(self.tmp.name)
        self.custom = self.root / 'custom'
        self.custom.mkdir()
        self.canvases = self.root / 'canvases'
        self.canvases.mkdir()
        self.addCleanup(self.tmp.cleanup)
        for name, value in [('SKILLS_CUSTOM_DIR', str(self.custom)), ('CANVAS_DIR', str(self.canvases))]:
            p = patch.object(main, name, value)
            p.start()
            self.addCleanup(p.stop)

    def skill(self):
        d = self.custom / 'demo'
        d.mkdir()
        (d / 'SKILL.md').write_text('---\nname: Display Name\ndescription: Preserve me\nversion: 1.2.3\nlicense: MIT\nvariants:\n  - id: cobalt\n    label: Blue Style\n    prompt: COBALT_DIRECTIVE\n---\nOriginal body\n', encoding='utf-8')
        return d

    def test_R2_editor_drops_original_frontmatter(self):
        d = self.skill()
        detail = asyncio.run(main.api_skill_detail('custom', 'demo'))
        payload = main.SkillUpdateRequest(content=detail['body'] + 'Updated.', variants=[main.SkillVariantItem(label=v['label'], prompt=v['prompt']) for v in detail['variants']])
        asyncio.run(main.api_skill_update('demo', payload))
        fm, _ = main.parse_skill_markdown_text((d / 'SKILL.md').read_text(encoding='utf-8'))
        self.assertNotIn('name', fm)
        self.assertNotIn('license', fm)
        self.assertNotIn('version', fm)
        print('R2 remaining frontmatter:', sorted(fm))

    def test_R3_installed_sha_becomes_update_tracking_ref(self):
        old, new = 'a' * 40, 'b' * 40
        archive = self.root / 'repo.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('owner-repo-sha/SKILL.md', '---\nname: demo\n---\nBody')
        # github_resolve_commit returns ref=branch; install calls it with payload.sha.
        async def download(url, sha):
            return str(archive), {'owner':'owner','repo':'repo','ref':sha,'sha':old}
        async def resolve(url, ref):
            return {'sha':old if ref == old else new}
        with patch.object(main, 'github_download_repo_zip', side_effect=download):
            asyncio.run(main.api_skill_github_install(main.SkillGithubInstallRequest(url='https://github.com/owner/repo', sha=old, name='demo')))
        meta = main.skill_read_meta(str(self.custom / 'demo'))
        self.assertEqual(meta['ref'], old)
        with patch.object(main, 'github_resolve_commit', side_effect=resolve):
            status = asyncio.run(main.api_skill_check_update('demo'))
        self.assertTrue(status['up_to_date'])
        self.assertEqual(status['latest_sha'], old)
        print('R3 pinned ref and false up_to_date:', meta['ref'], status['up_to_date'])

    def test_R4_missing_yaml_silently_loses_variants_then_save_fails(self):
        with patch.object(main, '_skill_yaml', None):
            p = main.SkillCreateRequest(name='demo', content='Body', variants=[main.SkillVariantItem(label='Blue', prompt='Blue colors')])
            asyncio.run(main.api_skill_create(p))
            text = (self.custom / 'demo' / 'SKILL.md').read_text(encoding='utf-8')
            self.assertNotIn('variants:', text)
            with self.assertRaises(main.HTTPException) as caught:
                asyncio.run(main.api_skill_update('demo', main.SkillUpdateRequest(content='Edited body', variants=[])))
            self.assertEqual(caught.exception.status_code, 500)
            self.assertEqual((self.custom / 'demo' / 'SKILL.md').read_text(encoding='utf-8'), 'Edited body')
        print('R4 no-yaml create drops variants; edit returns 500 after writing')

    def test_R5_custom_storage_reference_rejected_by_codex(self):
        uploads = self.root / 'external-uploads'
        uploads.mkdir()
        image = uploads / 'demo.png'
        image.write_bytes(b'fixture')
        with patch.object(main, 'OUTPUT_INPUT_DIR', str(uploads)):
            url = main.output_url_for('demo.png', 'input')
            self.assertTrue(url.startswith('/api/storage-files/upload/'))
            self.assertEqual(main.output_file_from_url(url), str(image))
            with self.assertRaises(main.HTTPException) as caught:
                asyncio.run(main.codex_prepare_local_media(url))
            self.assertEqual(caught.exception.status_code, 400)
        print('R5 valid storage URL rejected:', url)

    def test_R6_metadata_rename_lost_on_stale_editor_save(self):
        original = main.new_canvas('Old title')
        cid, base = original['id'], original['updated_at']
        asyncio.run(main.update_canvas_meta(cid, main.CanvasMetaUpdate(title='New title')))
        self.assertEqual(main.load_canvas(cid)['updated_at'], base)
        with patch.object(main.manager, 'broadcast_canvas_updated', new=AsyncMock()):
            asyncio.run(main.update_canvas(cid, main.CanvasSaveRequest(title='Old title', nodes=[{'id':'local'}], base_updated_at=base)))
        self.assertEqual(main.load_canvas(cid)['title'], 'Old title')
        print('R6 rename overwritten without 409')

    def test_R7_editor_rekeys_variant_and_old_canvas_selection_is_ignored(self):
        self.skill()
        detail = asyncio.run(main.api_skill_detail('custom', 'demo'))
        payload = main.SkillUpdateRequest(content=detail['body'], variants=[main.SkillVariantItem(label=v['label'], prompt=v['prompt']) for v in detail['variants']])
        asyncio.run(main.api_skill_update('demo', payload))
        result = asyncio.run(main.compile_skill_prompt(main.SkillSelection(source='custom', id='demo', mode='fast', variant='cobalt'), 'Cat'))
        self.assertIsNone(result['skill_used']['variant'])
        self.assertNotIn('COBALT_DIRECTIVE', result['compiled_prompt'])
        print('R7 old cobalt variant silently ignored after edit')


if __name__ == '__main__':
    unittest.main(verbosity=2)

