"""S08 GitHub updater must fail closed on incomplete trees and changed bytes.

Tests extract the two real main.py functions without importing the app or network.
All staging occurs in a temporary directory and no live files are touched.
"""
import ast
import hashlib
import inspect
import os
import re
import tempfile
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = {"github_update_file_list", "download_github_update_files"}


def git_blob_digest(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


class GithubUpdateIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="s08_github_integrity_")
        self.addCleanup(self.tmp.cleanup)
        self.staging = Path(self.tmp.name) / "staging"
        self.files = {
            "VERSION": b"2026.11.06\n",
            "main.py": b"print('updater fixture')\n",
            "static/index.html": b"<html>safe fixture</html>\n",
        }
        self.tree = {
            "truncated": False,
            "tree": [{"path": k, "type": "blob", "sha": git_blob_digest(v)}
                     for k, v in self.files.items()],
        }
        script = (ROOT / "main.py").read_text(encoding="utf-8-sig")
        tree = ast.parse(script)
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
        self.assertEqual({n.name for n in functions}, NAMES)
        for n in functions:
            n.decorator_list = []
        code = compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])),
                       str(ROOT / "main.py"), "exec")
        def github_bytes(url):
            rel = urllib.parse.unquote(url.removeprefix("https://raw.invalid/"))
            return self.files[rel]
        self.ctx = dict(Tuple=tuple, List=list, Dict=dict, os=os, urllib=urllib,
                        hashlib=hashlib, re=re,
                        GITHUB_TREE_URL="https://api.invalid/tree",
                        GITHUB_RAW_ROOT="https://raw.invalid",
                        github_json=lambda url, use_etag_cache: self.tree,
                        github_bytes=github_bytes,
                        safe_update_target=lambda p: str(self.staging / p),
                        update_allowed_file=lambda p: p in self.files)
        exec(code, self.ctx)

    def file_list(self):
        return self.ctx["github_update_file_list"]()

    def download(self, listing):
        # Run the original two-argument function as well when demonstrating
        # the missing hash check on the pre-fix source.
        fn = self.ctx["download_github_update_files"]
        if len(inspect.signature(fn).parameters) == 2:
            return fn(listing[2], str(self.staging))
        return fn(listing[2], str(self.staging), listing[3])

    def test_complete_tree_download_verifies_and_stages_bytes(self):
        listing = self.file_list()
        self.download(listing)
        for rel, data in self.files.items():
            self.assertEqual((self.staging / rel).read_bytes(), data)

    def test_truncated_tree_must_abort_before_replacing_live_static(self):
        self.tree["truncated"] = True
        with self.assertRaises(RuntimeError):
            self.file_list()

    def test_missing_required_file_in_tree_is_not_synthesized(self):
        self.tree["tree"] = [e for e in self.tree["tree"] if e["path"] != "main.py"]
        with self.assertRaises(RuntimeError):
            self.file_list()

    def test_missing_expected_blob_hash_must_abort(self):
        self.tree["tree"][0].pop("sha")
        with self.assertRaises(RuntimeError):
            self.file_list()

    def test_drifted_raw_file_is_not_staged(self):
        listing = self.file_list()
        self.files["static/index.html"] = b"<html>changed after tree fetch</html>\n"
        with self.assertRaises(RuntimeError):
            self.download(listing)
        self.assertFalse((self.staging / "static/index.html").exists())

    def test_corrupt_download_is_rejected_even_if_http_succeeded(self):
        listing = self.file_list()
        self.files["VERSION"] = b"<html>200 OK but not VERSION</html>"
        with self.assertRaises(RuntimeError):
            self.download(listing)
        self.assertFalse((self.staging / "VERSION").exists())


if __name__ == "__main__":
    unittest.main()
