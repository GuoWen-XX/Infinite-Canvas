"""Adversarial regression tests for scripts/check_ssrf_guards.py (audit E03)."""
import ast
import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.check_ssrf_guards import SSRFVisitor  # noqa: E402


def _errors(src):
    src = textwrap.dedent(src)
    v = SSRFVisitor("fixture.py", src.splitlines(True))
    v.visit(ast.parse(src))
    return v.errors


@pytest.mark.parametrize("name", ["client", "gateway_cache", "REMOTE", "app_meta", "svc_store"])
def test_unvalidated_fetch_is_caught_for_any_client_name(name):
    src = f"""
    @router.post('/demo')
    async def route(payload: Payload):
        async with httpx.AsyncClient() as {name}:
            await {name}.get(payload.url)
    """
    assert _errors(src), f"client named {name!r} escaped the gate"


def test_validated_fetch_passes():
    src = """
    @router.post('/demo')
    async def route(payload: Payload):
        validate_safe_url(payload.url)
        async with httpx.AsyncClient() as client:
            await client.get(payload.url)
    """
    assert _errors(src) == []


def test_plain_dict_get_is_not_flagged():
    src = """
    def f(payload):
        cache = {}
        return cache.get(payload.url)
    """
    assert _errors(src) == []


def test_reassignment_revokes_guard():
    src = """
    async def f(payload, url):
        validate_safe_url(url)
        url = payload.url
        async with httpx.AsyncClient() as client:
            await client.get(url)
    """
    assert _errors(src), "validated variable overwritten with tainted value must be flagged"


def test_guard_in_single_branch_does_not_cover_outer_call():
    src = """
    @router.post('/demo')
    async def route(payload: Payload):
        if payload.flag:
            validate_safe_url(payload.url)
        async with httpx.AsyncClient() as client:
            await client.get(payload.url)
    """
    assert _errors(src), "guard on one branch only must not protect the unconditional fetch"


def test_guard_on_both_branches_or_early_exit_passes():
    src = """
    @router.post('/demo')
    async def route(payload: Payload):
        if payload.flag:
            validate_safe_url(payload.url)
        else:
            validate_safe_url(payload.url)
        async with httpx.AsyncClient() as client:
            await client.get(payload.url)
    """
    assert _errors(src) == []
    src_exit = """
    @router.post('/demo')
    async def route(payload: Payload):
        if not is_safe_remote_url(payload.url):
            raise HTTPException(400)
        async with httpx.AsyncClient() as client:
            await client.get(payload.url)
    """
    assert _errors(src_exit) == []


def test_repository_passes_gate():
    r = subprocess.run([sys.executable, "scripts/check_ssrf_guards.py"], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
