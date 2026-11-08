"""Failure-injection regression for updater static replacement.

Extract the real update_from_github function from main.py. Mock only network
source, backup bookkeeping, and isolated application/data paths. Never run
the application, download remote files or touch a user's canvas.
"""
import ast
import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import time
import traceback
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class HttpError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code

class UpdateStaticFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='s08_update_static_')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / 'app'
        self.data = Path(self.tmp.name) / 'data'
        self.backup = self.data / 'update_backups' / 'saved'
        self.base.mkdir()
        self.data.mkdir()
        self.write(self.base / 'main.py', 'old-main')
        self.write(self.base / 'VERSION', 'old-version')
        self.write(self.base / 'static' / 'index.html', 'old-index')
        self.write(self.base / 'static' / 'css' / 'app.css', 'old-css')

        script = (ROOT / 'main.py').read_text(encoding='utf-8-sig')
        tree = ast.parse(script)
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == 'update_from_github')
        function.decorator_list = []
        function.args.defaults = []
        code = compile(ast.fix_missing_locations(
            ast.Module(body=[function], type_ignores=[])), str(ROOT / 'main.py'), 'exec')

        def stage(candidate, directory):
            directory = Path(directory)
            self.write(directory / 'main.py', 'new-main')
            self.write(directory / 'VERSION', 'new-version')
            self.write(directory / 'static' / 'index.html', 'new-index')
            self.write(directory / 'static' / 'css' / 'app.css', 'new-css')
            roots = ['VERSION', 'main.py']
            statics = ['static/index.html', 'static/css/app.css']
            return roots, statics, roots + statics

        def create_backup(directory, root_files, static_files, **kwargs):
            directory = Path(directory)
            directory.mkdir(parents=True)
            for rel in root_files:
                if (self.base / rel).exists():
                    shutil.copy2(self.base / rel, directory / rel)
            shutil.copytree(self.base / 'static', directory / 'static')
            return {'root_files': {
                rel: {'existed': (self.base / rel).exists()}
                for rel in root_files}}

        self.lock = threading.Lock()
        ctx = dict(UpdateRequest=object, HTTPException=HttpError,
                   UPDATE_LOCK=self.lock, Dict=Dict, List=List, Any=Any,
                   normalize_update_source=lambda value: 'github',
                   UPDATE_SOURCE_LABELS={'github': 'GitHub'},
                   os=os, shutil=shutil, time=time, json=json, traceback=traceback,
                   DATA_DIR=str(self.data),
                   stage_update_from_source=stage,
                   validate_staged_update=lambda *args: None,
                   safe_update_notes=lambda notes, version: notes,
                   next_update_backup_dir=lambda: str(self.backup),
                   create_update_backup=create_backup,
                   safe_static_dir=lambda: str(self.base / 'static'),
                   safe_update_target=lambda rel: str(self.base / rel),
                   schedule_self_restart=lambda delay: False,
                   prune_update_backups=lambda keep: [])
        exec(code, ctx)
        self.update = ctx['update_from_github']

    @staticmethod
    def write(path, text):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def current_files(self):
        return {str(p.relative_to(self.base)): p.read_text(encoding='utf-8')
                for p in self.base.rglob('*') if p.is_file()}

    def perform_update(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.update(SimpleNamespace(source='github', fallback=False,
                                               auto_restart=False, restart_delay=3))

    def test_success_still_replaces_static_and_root_files_and_keeps_backup(self):
        result = self.perform_update()
        self.assertTrue(result['ok'])
        self.assertEqual((self.base / 'static' / 'index.html').read_text(), 'new-index')
        self.assertEqual((self.base / 'VERSION').read_text(), 'new-version')
        self.assertEqual((self.backup / 'static' / 'index.html').read_text(), 'old-index')
        self.assertFalse(self.lock.locked())

    def test_partial_static_delete_failure_restores_all_live_files(self):
        previous = self.current_files()
        original = shutil.rmtree
        faulted = False
        def inject(directory, *args, **kwargs):
            nonlocal faulted
            if str(directory) == str(self.base / 'static') and not faulted:
                faulted = True
                (self.base / 'static' / 'index.html').unlink()
                raise OSError('injected halfway static directory deletion failure')
            return original(directory, *args, **kwargs)
        with patch.object(shutil, 'rmtree', side_effect=inject):
            with self.assertRaises(HttpError):
                self.perform_update()
        self.assertTrue(faulted)
        self.assertEqual(self.current_files(), previous)
        self.assertFalse(self.lock.locked())

    def test_partial_static_copy_failure_restores_previous_release(self):
        previous = self.current_files()
        original = shutil.copytree
        faulted = False
        def inject(src, dst, *args, **kwargs):
            nonlocal faulted
            if str(src).startswith(str(self.data / 'update_staging')) and not faulted:
                faulted = True
                self.write(Path(dst) / 'index.html', 'partial-new-content')
                raise OSError('injected static copy error')
            return original(src, dst, *args, **kwargs)
        with patch.object(shutil, 'copytree', side_effect=inject):
            with self.assertRaises(HttpError):
                self.perform_update()
        self.assertTrue(faulted)
        self.assertEqual(self.current_files(), previous)
        self.assertFalse(self.lock.locked())

    def test_root_replacement_failure_removes_temp_and_restores_previous_release(self):
        previous = self.current_files()
        original = os.replace
        faulted = False
        def inject(src, dst):
            nonlocal faulted
            if str(dst) == str(self.base / 'main.py') and not faulted:
                faulted = True
                raise OSError('injected root-file replace error')
            return original(src, dst)
        with patch.object(os, 'replace', side_effect=inject):
            with self.assertRaises(HttpError):
                self.perform_update()
        self.assertTrue(faulted)
        self.assertEqual(self.current_files(), previous)
        self.assertFalse(self.lock.locked())

    def test_update_then_rollback_then_roll_forward_restores_exact_bytes(self):
        """Exercise actual update and rollback handlers with disposable on-disk files."""
        original = self.current_files()
        update_result = self.perform_update()
        changed = self.current_files()
        self.assertNotEqual(changed, original)
        self.assertTrue(update_result['ok'])
        backups = iter(('rollback-safety-one', 'rollback-safety-two'))
        self.update.__globals__['next_update_backup_dir'] = lambda prefix='': str(
            self.data / 'update_backups' / next(backups))
        context = self.update.__globals__
        context['read_update_backup_manifest'] = lambda path: {
            'state': 'ready', 'from_version': 'old-version',
            'root_files': {'main.py': {'existed': True}, 'VERSION': {'existed': True}},
            'static_snapshot': {'exists': True},
        }
        context['current_app_version'] = lambda: 'new-version'
        context['update_allowed_file'] = lambda path: path in {'main.py', 'VERSION'}
        context['restore_failed_rollback'] = lambda *args: self.fail(
            'unexpected rollback error; safety recovery was invoked')
        script = (ROOT / 'main.py').read_text(encoding='utf-8-sig')
        function = next(node for node in ast.parse(script).body
                        if isinstance(node, ast.FunctionDef) and node.name == 'rollback_update')
        function.decorator_list = []
        code = compile(ast.fix_missing_locations(
            ast.Module(body=[function], type_ignores=[])), str(ROOT / 'main.py'), 'exec')
        context['RollbackRequest'] = object
        exec(code, context)
        rollback = context['rollback_update']
        first = rollback(SimpleNamespace(name='saved', auto_restart=False, restart_delay=3))
        self.assertTrue(first['ok'])
        self.assertEqual(self.current_files(), original)
        self.assertEqual((self.data / 'update_backups' / 'rollback-safety-one'
                          / 'static' / 'index.html').read_text(), 'new-index')
        second = rollback(SimpleNamespace(
            name='rollback-safety-one', auto_restart=False, restart_delay=3))
        self.assertTrue(second['ok'])
        self.assertEqual(self.current_files(), changed)
        self.assertFalse(self.lock.locked())

    def test_root_copy_failure_removes_partial_temp_and_restores_previous_release(self):
        previous = self.current_files()
        original = shutil.copy2
        faulted = False
        def inject(src, dst, *args, **kwargs):
            nonlocal faulted
            if str(dst) == str(self.base / 'main.py.update_tmp') and not faulted:
                faulted = True
                self.write(dst, 'partial-root-content')
                raise OSError('injected root-file temp copy failure')
            return original(src, dst, *args, **kwargs)
        with patch.object(shutil, 'copy2', side_effect=inject):
            with self.assertRaises(HttpError):
                self.perform_update()
        self.assertTrue(faulted)
        self.assertEqual(self.current_files(), previous)
        self.assertFalse(self.lock.locked())

    def test_new_root_module_is_removed_on_rollback_and_recovered_on_rollforward(self):
        # The legacy installed build has no root storage_guard.py; a new
        # upgrade adds it, rollback removes it, and roll-forward restores it.
        original = self.current_files()
        context = self.update.__globals__
        previous_stage = context['stage_update_from_source']
        def stage_with_module(candidate, directory):
            roots, statics, files = previous_stage(candidate, directory)
            self.write(Path(directory) / 'storage_guard.py', 'new-safe-guard')
            roots.append('storage_guard.py')
            files.append('storage_guard.py')
            return roots, statics, files
        context['stage_update_from_source'] = stage_with_module
        update_result = self.perform_update()
        self.assertTrue(update_result['ok'])
        updated = self.current_files()
        self.assertEqual((self.base / 'storage_guard.py').read_text(), 'new-safe-guard')

        backups = iter(('rollback-safety-one', 'rollback-safety-two'))
        context['next_update_backup_dir'] = lambda prefix='': str(
            self.data / 'update_backups' / next(backups))
        original_roots = {
            'main.py': {'existed': True}, 'VERSION': {'existed': True},
            'storage_guard.py': {'existed': False}}
        safety_roots = {
            'main.py': {'existed': True}, 'VERSION': {'existed': True},
            'storage_guard.py': {'existed': True}}
        context['read_update_backup_manifest'] = lambda path: {
            'state': 'ready',
            'root_files': safety_roots if Path(path).name.startswith('rollback-') else original_roots,
            'static_snapshot': {'exists': True},
        }
        context['current_app_version'] = lambda: 'new-version'
        context['update_allowed_file'] = lambda rel: rel in {
            'main.py', 'VERSION', 'storage_guard.py'}
        context['RollbackRequest'] = object
        context['restore_failed_rollback'] = lambda *args: self.fail(
            'unexpected safety restoration')
        script = (ROOT / 'main.py').read_text(encoding='utf-8-sig')
        function = next(n for n in ast.parse(script).body
                        if isinstance(n, ast.FunctionDef) and n.name == 'rollback_update')
        function.decorator_list = []
        compiled = compile(ast.fix_missing_locations(
            ast.Module(body=[function], type_ignores=[])), str(ROOT / 'main.py'), 'exec')
        exec(compiled, context)
        rollback = context['rollback_update']
        result = rollback(SimpleNamespace(name='saved', auto_restart=False, restart_delay=3))
        self.assertTrue(result['ok'])
        self.assertEqual(self.current_files(), original)
        self.assertFalse((self.base / 'storage_guard.py').exists())
        second = rollback(SimpleNamespace(
            name='rollback-safety-one', auto_restart=False, restart_delay=3))
        self.assertTrue(second['ok'])
        self.assertEqual(self.current_files(), updated)
        self.assertFalse(self.lock.locked())

if __name__ == '__main__':
    unittest.main()
