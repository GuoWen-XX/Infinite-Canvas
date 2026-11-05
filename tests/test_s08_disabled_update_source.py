"""S08: Update checks must not advertise disabled upstream versions.
Execute the real function definitions extracted from main.py, without importing
the app, starting services, downloading code, or accessing user data.
"""
import ast
from functools import lru_cache
from pathlib import Path
from threading import Thread
from typing import Any, Dict, Tuple
import unittest

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = {"check_update", "fetch_update_notes_with_fallback"}


@lru_cache(maxsize=1)
def isolate_main_functions():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8-sig"))
    functions = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            node.decorator_list = []
            functions.append(node)
    assert {node.name for node in functions} == FUNCTIONS
    code = compile(
        ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])),
        str(ROOT / "main.py"), "exec"
    )
    return code


class S08AllowedUpdateSourceTests(unittest.TestCase):
    def make_context(self, allowed=False, github_ver="2026.09.01",
                     modelscope_ver="2099.01.01", notes=None):
        version_calls = []
        notes_calls = []

        def probe_version(url, timeout):
            version_calls.append(url)
            version = github_ver if url == "github-version" else modelscope_ver
            return {"ok": bool(version), "version": version, "url": url}

        def probe_notes(url, version, timeout):
            notes_calls.append(url)
            return {"ok": True, "items": (notes or {}).get(url, []),
                    "version": version, "url": url}

        def version_gt(left, right):
            return tuple(map(int, left.split("."))) > tuple(map(int, right.split(".")))

        ctx = dict(
            Thread=Thread, Dict=Dict, Any=Any, Tuple=Tuple,
            ALLOW_MODELSCOPE_UPDATE_SOURCE=allowed,
            MODELSCOPE_UPDATE_SOURCE_DISABLED_HINT="旧版 ModelScope 更新源已禁用",
            GITHUB_VERSION_URL="github-version", MODELSCOPE_VERSION_URL="modelscope-version",
            GITHUB_UPDATE_NOTES_URL="github-notes", MODELSCOPE_UPDATE_NOTES_URL="modelscope-notes",
            fetch_remote_version=probe_version,
            fetch_remote_update_notes=probe_notes,
            current_app_version=lambda: "2026.08.28",
            version_gt=version_gt,
        )
        exec(isolate_main_functions(), ctx)
        return ctx, version_calls, notes_calls

    def test_disabled_old_modelscope_not_queried(self):
        ctx, calls, _ = self.make_context()
        result = ctx["check_update"]()
        self.assertEqual(calls, ["github-version"])
        self.assertEqual(result["latest"]["source"], "github")
        self.assertTrue(result["modelscope"].get("disabled"))

    def test_disabled_source_not_selected_when_github_unavailable(self):
        ctx, calls, _ = self.make_context(github_ver="")
        result = ctx["check_update"]()
        self.assertEqual(calls, ["github-version"])
        self.assertFalse(result["reachable"])
        self.assertFalse(result["update_available"])

    def test_disabled_source_not_queried_for_notes_fallback(self):
        ctx, _, calls = self.make_context(notes={"github-notes": []})
        result = ctx["fetch_update_notes_with_fallback"]("github", "2026.09.01")
        self.assertEqual(calls, ["github-notes"])
        self.assertIn("已禁用", result[1]["modelscope"]["error"])

    def test_disabled_modelscope_preference_uses_github_notes(self):
        ctx, _, calls = self.make_context(notes={"github-notes": [{"text": "changes"}]})
        ctx["fetch_update_notes_with_fallback"]("modelscope", "2026.09.01")
        self.assertEqual(calls, ["github-notes"])

    def test_enabled_source_can_take_newer_version(self):
        ctx, calls, _ = self.make_context(allowed=True)
        result = ctx["check_update"]()
        self.assertCountEqual(calls, ["github-version", "modelscope-version"])
        self.assertEqual(result["latest"]["source"], "modelscope")

    def test_enabled_notes_can_fallback(self):
        ctx, _, calls = self.make_context(
            allowed=True, notes={"modelscope-notes": [{"text": "changes"}]})
        result = ctx["fetch_update_notes_with_fallback"]("github", "2026.09.01")
        self.assertEqual(calls, ["github-notes", "modelscope-notes"])
        self.assertEqual(result[0]["source"], "modelscope")

    def test_enabled_modelscope_notes_preferred(self):
        ctx, _, calls = self.make_context(
            allowed=True, notes={"modelscope-notes": [{"text": "changes"}]})
        result = ctx["fetch_update_notes_with_fallback"]("modelscope", "2026.09.01")
        self.assertEqual(calls, ["modelscope-notes"])
        self.assertEqual(result[0]["source"], "modelscope")


if __name__ == "__main__":
    unittest.main()
