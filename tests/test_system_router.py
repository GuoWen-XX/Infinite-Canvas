import os
import sys
import unittest
from fastapi import FastAPI
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.system import (
    router as system_router,
    current_app_version,
    safe_update_notes,
    version_gt,
    version_tuple,
)

class TestSystemRouter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()
        cls.app.include_router(system_router)
        cls.client = TestClient(cls.app)

    def test_01_version_helpers(self):
        v = current_app_version()
        self.assertTrue(bool(v))
        self.assertTrue(version_gt('2026.09.05', '2026.09.04'))
        self.assertFalse(version_gt('2026.09.04', '2026.09.05'))
        self.assertEqual(version_tuple('1.2.3'), [1, 2, 3])

    def test_02_app_info(self):
        resp = self.client.get('/api/app-info')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('sources', data)
        self.assertIn('github', data['sources'])

    def test_03_update_backups_list(self):
        resp = self.client.get('/api/update-backups')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('backups', data)

    def test_04_rollback_missing_name(self):
        from unittest.mock import patch
        with patch("routers.system.EXECUTABLE_UPDATE_ENABLED", True):
            resp = self.client.post('/api/update-rollback', json={'name': ''})
            self.assertEqual(resp.status_code, 400)

    def test_05_update_from_github_fail_closed(self):
        import routers.system as sys_module
        orig_stage = getattr(sys_module, "stage_update_from_source", None)

        def side_effect_guard(*args, **kwargs):
            raise AssertionError("stage_update_from_source must not be called when updates are disabled")

        try:
            sys_module.stage_update_from_source = side_effect_guard
            resp = self.client.post('/api/update-from-github', json={'source': 'github'})
            self.assertEqual(resp.status_code, 503)
            detail = resp.json().get('detail', '')
            self.assertTrue(
                '禁用' in detail and '发布源' in detail,
                f"Unexpected 503 detail message: {detail}",
            )
        finally:
            if orig_stage is not None:
                sys_module.stage_update_from_source = orig_stage

if __name__ == '__main__':
    unittest.main()
