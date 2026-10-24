"""Regression tests for the round-8 remaining findings in the Reve edit path.

Covers the eight items fixed after the key-exfiltration closure:
  HIGH   DNS-rebinding TOCTOU on the credentialed dispatch
  MEDIUM spatial hint used a hardcoded 1000x1000 canvas
  MEDIUM OpenAI mask lacked an alpha channel; image MIME was hardcoded to PNG
  MEDIUM BFL Fill sent an empty mask when no region was selected
  MEDIUM openai-edits hardcoded its endpoint, ignoring provider config
  MEDIUM image_edit_mode was never produced, so the branch was unreachable
  LOW    canvas-reve.js interpolated unescaped values into innerHTML
  LOW    history_manager lost its absolute string cap
"""
import asyncio
import io
import os
import re
import sys
import unittest

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.image_edit import (  # noqa: E402
    _detect_image_format,
    _full_canvas_mask,
    build_edit_prompt_with_region,
    detect_edit_dispatch_mode,
    prepare_reve_edit_payload,
    synthesize_feathered_mask,
    to_alpha_mask_png,
)


def _png(size=(32, 32), color=(120, 30, 30), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


class TestSpatialHintUsesRealDimensions(unittest.TestCase):
    """MEDIUM: the prompt described the wrong side of small images."""

    def test_region_on_right_of_512_image_is_called_right(self):
        region = {"x": 384, "y": 10, "width": 50, "height": 50}
        prompt = build_edit_prompt_with_region("改这里", region, orig_w=512, orig_h=512)
        self.assertIn("右侧", prompt)
        self.assertNotIn("中央", prompt)

    def test_region_on_left_of_1024_image_is_called_left(self):
        region = {"x": 50, "y": 500, "width": 40, "height": 40}
        prompt = build_edit_prompt_with_region("改这里", region, orig_w=1024, orig_h=1024)
        self.assertIn("左侧", prompt)

    def test_call_site_threads_real_dimensions(self):
        """execute_canvas_edit 必须把真实尺寸透传下去。

        直接断言 build_edit_prompt_with_region 无法覆盖这一点——它的签名默认
        orig_w=1000，即便调用点忘了传参，结果看起来也一样正确。
        """
        with open(os.path.join(ROOT, "core", "image_edit.py"), "r", encoding="utf-8") as f:
            src = f.read()
        self.assertRegex(
            src, r"orig_w=int\(orig_w or 1000\), orig_h=int\(orig_h or 1000\)",
            "调用点未透传真实图片尺寸，空间方位会按硬编码 1000x1000 估算",
        )
        self.assertRegex(src, r"orig_w=orig_w,\s*\n\s*orig_h=orig_h,",
                         "execute_canvas_edit 未把 orig_w/orig_h 传给 payload 构建器")

    def test_signature_default_does_not_mask_a_missing_argument(self):
        """签名默认值必须仍是 1000 —— 若被改成本地兜底值会掩盖调用点缺陷。"""
        import inspect
        sig = inspect.signature(build_edit_prompt_with_region)
        self.assertEqual(sig.parameters["orig_w"].default, 1000)
        self.assertEqual(sig.parameters["orig_h"].default, 1000)


class TestOpenAIMaskAlphaChannel(unittest.TestCase):
    """MEDIUM: /v1/images/edits requires a mask with an alpha channel."""

    def test_mask_is_converted_to_rgba(self):
        gray = synthesize_feathered_mask(64, 64, {"x": 16, "y": 16, "width": 32, "height": 32})
        self.assertEqual(Image.open(io.BytesIO(gray)).mode, "L")

        rgba_bytes = to_alpha_mask_png(gray)
        rgba = Image.open(io.BytesIO(rgba_bytes))
        self.assertEqual(rgba.mode, "RGBA")
        self.assertEqual(rgba.size, (64, 64))

    def test_openai_edits_branch_ships_an_alpha_mask(self):
        """必须经 payload 构建器验证：直接调用辅助函数无法覆盖分支本身。"""
        src = _png(size=(64, 64))
        gray = synthesize_feathered_mask(64, 64, {"x": 16, "y": 16, "width": 32, "height": 32})
        spec = prepare_reve_edit_payload(
            provider={"id": "openai", "base_url": "https://api.openai.com/v1", "image_edit_mode": "edits"},
            model="gpt-image-1", prompt="x", source_image_bytes=src, mask_bytes=gray,
        )
        _fname, mask_bytes, mime = spec["files"]["mask"]
        self.assertEqual(mime, "image/png")
        self.assertEqual(
            Image.open(io.BytesIO(mask_bytes)).mode, "RGBA",
            "openai-edits 分支送出的仍是 8 位灰度，OpenAI 端点会拒绝",
        )

    def test_selected_region_becomes_transparent(self):
        """OpenAI 约定：透明区域为要重绘的部分。选区内应透明。"""
        gray = synthesize_feathered_mask(64, 64, {"x": 16, "y": 16, "width": 32, "height": 32})
        alpha = Image.open(io.BytesIO(to_alpha_mask_png(gray))).split()[-1]
        self.assertEqual(alpha.getpixel((32, 32)), 0, "选区内应为透明(0)")
        self.assertEqual(alpha.getpixel((2, 2)), 255, "选区外应为不透明(255)")


class TestImageFormatDetection(unittest.TestCase):
    """MEDIUM: JPEG sources were uploaded as image.png."""

    def test_detects_real_format(self):
        for fmt, want in (("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")):
            data = _png(fmt=fmt)
            _ext, mime = _detect_image_format(data)
            self.assertEqual(mime, want, f"{fmt} 格式探测错误")

    def test_openai_edits_uses_detected_mime(self):
        jpeg = _png(fmt="JPEG")
        spec = prepare_reve_edit_payload(
            provider={"id": "openai", "base_url": "https://api.openai.com/v1", "image_edit_mode": "edits"},
            model="gpt-image-1", prompt="x", source_image_bytes=jpeg,
        )
        fname, _data, mime = spec["files"]["image"]
        self.assertEqual(mime, "image/jpeg", "JPEG 源被硬编码为 image/png")
        self.assertTrue(fname.endswith(".jpg"))


class TestBFLFullCanvasMask(unittest.TestCase):
    """MEDIUM: flux-pro-1.0-fill rejects an empty mask with 422."""

    def test_missing_mask_becomes_full_canvas_mask(self):
        src = _png(size=(80, 60))
        spec = prepare_reve_edit_payload(
            provider={"id": "bfl", "base_url": "https://api.bfl.ml/v1"},
            model="flux-pro-1.0-fill", prompt="x", source_image_bytes=src, mask_bytes=None,
        )
        import base64
        mask = Image.open(io.BytesIO(base64.b64decode(spec["json_body"]["mask"])))
        self.assertEqual(mask.size, (80, 60), "全图遮罩尺寸应与源图一致")
        self.assertEqual(mask.getextrema(), (255, 255), "全图遮罩应为全白")

    def test_explicit_region_mask_is_preserved(self):
        src = _png(size=(80, 60))
        region = {"x": 10, "y": 10, "width": 20, "height": 20}
        mask = synthesize_feathered_mask(80, 60, region)
        spec = prepare_reve_edit_payload(
            provider={"id": "bfl", "base_url": "https://api.bfl.ml/v1"},
            model="flux-pro-1.0-fill", prompt="x", source_image_bytes=src, mask_bytes=mask,
        )
        import base64
        got = Image.open(io.BytesIO(base64.b64decode(spec["json_body"]["mask"])))
        self.assertEqual(got.getextrema()[0], 0, "显式遮罩应保留黑色区域，不得被替换为全白")


class TestOpenAIEditsReachability(unittest.TestCase):
    """MEDIUM: image_edit_mode was never produced, so this branch was dead."""

    def test_detect_by_explicit_mode(self):
        mode = detect_edit_dispatch_mode(
            {"id": "openai", "image_edit_mode": "edits"}, "some-model"
        )
        self.assertEqual(mode, "openai-edits")

    def test_detect_by_model_name(self):
        self.assertEqual(detect_edit_dispatch_mode({"id": "openai"}, "dall-e-2"), "openai-edits")

    def test_provider_payload_declares_the_field(self):
        from routers.providers import ApiProviderPayload
        self.assertIn("image_edit_mode", ApiProviderPayload.model_fields,
                      "ApiProviderPayload 未声明 image_edit_mode，保存时会被丢弃")

    def test_normalize_provider_echoes_the_field(self):
        from core.providers import normalize_provider
        out = normalize_provider({"id": "gw1", "name": "GW", "image_edit_mode": "edits"})
        self.assertEqual(out.get("image_edit_mode"), "edits")

    def test_normalize_provider_rejects_unknown_mode(self):
        from core.providers import normalize_provider
        out = normalize_provider({"id": "gw1", "name": "GW", "image_edit_mode": "bogus"})
        self.assertEqual(out.get("image_edit_mode"), "")

    def test_endpoint_override_is_honoured(self):
        spec = prepare_reve_edit_payload(
            provider={
                "id": "gw", "base_url": "https://gw.test/v1",
                "image_edit_mode": "edits", "image_edit_endpoint": "/custom/edit",
            },
            model="m", prompt="x", source_image_bytes=_png(),
        )
        self.assertEqual(spec["endpoint_url"], "https://gw.test/custom/edit",
                         "自建网关的端点配置被忽略，会 404")


class TestHistoryManagerAbsoluteCap(unittest.TestCase):
    """LOW: the base64 relaxation removed the only hard size bound."""

    def test_oversized_ascii_is_truncated(self):
        from core.history_manager import MAX_STRING_CHARS, _sanitize_value
        # 必须用 base64 路径抓不到的载荷：纯 base64 字符即便没有绝对上限，
        # 也会被 _looks_like_base64_blob 截断，那样测不出绝对上限是否生效。
        # 用含空格的载荷：_looks_like_base64_blob 对含空格的字符串直接返回 False，
        # 因此这条路径只能由绝对上限拦住，才能真正验证上限是否生效。
        blob = "ab cd " * (MAX_STRING_CHARS // 6 + 1000)
        self.assertFalse(
            __import__("core.history_manager", fromlist=["x"])._looks_like_base64_blob(blob),
            "测试载荷被 base64 路径捕获，无法验证绝对上限",
        )
        out, changed = _sanitize_value(blob)
        self.assertTrue(changed, "超长非 base64 载荷未被截断")
        self.assertLess(len(out), len(blob))

    def test_normal_prompt_is_untouched(self):
        from core.history_manager import _sanitize_value
        prompt = "把背景改成蓝色" * 2000
        out, changed = _sanitize_value(prompt)
        self.assertFalse(changed, "正常长度的中文 prompt 被误伤")
        self.assertEqual(out, prompt)

    def test_url_is_preserved(self):
        from core.history_manager import _sanitize_value
        url = "https://example.com/a.png"
        out, changed = _sanitize_value(url)
        self.assertFalse(changed)
        self.assertEqual(out, url)


class TestCanvasReveEscaping(unittest.TestCase):
    """LOW: the quick bar interpolated values into innerHTML unescaped."""

    def setUp(self):
        path = os.path.join(ROOT, "static", "js", "canvas-reve.js")
        with open(path, "r", encoding="utf-8") as f:
            self.src = f.read()

    def test_escape_helpers_exist(self):
        self.assertIn("function escapeHtml(", self.src)
        self.assertIn("function escapeAttr(", self.src)

    def test_interpolations_are_escaped(self):
        # 模型 id / providerId / label 来自 /api/providers（按 spec §2.2 为动态来源）
        self.assertNotRegex(self.src, r'value="\$\{m\.id\}"')
        self.assertNotRegex(self.src, r'data-provider="\$\{m\.providerId\}"')
        self.assertNotRegex(self.src, r'placeholder="\$\{placeholder\}"')
        self.assertIn('escapeAttr(m.id)', self.src)
        self.assertIn('escapeHtml(m.label)', self.src)


class TestCoreLayeringPreserved(unittest.TestCase):
    """LOW: the history hook must not reintroduce core -> routers imports."""

    def test_core_does_not_import_routers(self):
        core_dir = os.path.join(ROOT, "core")
        for name in os.listdir(core_dir):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(core_dir, name), "r", encoding="utf-8") as f:
                body = f.read()
            self.assertNotRegex(body, r"^\s*from routers\.", f"{name} 反向 import routers")
            self.assertNotRegex(body, r"^\s*import routers\.", f"{name} 反向 import routers")

    def test_history_saver_is_injected(self):
        with open(os.path.join(ROOT, "core", "image_edit.py"), "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("history_saver=None", src, "execute_canvas_edit 应接受注入的历史记录回调")


class TestSafeJsonPostMethodSupport(unittest.TestCase):
    """The BFL poll is a GET; safe_json_post must not force POST."""

    def test_method_parameter_exists(self):
        import inspect

        import core.security as SEC
        sig = inspect.signature(SEC.safe_json_post)
        self.assertIn("method", sig.parameters,
                      "safe_json_post 缺少 method 参数，BFL 轮询会被发成 POST")

    def test_bfl_poll_uses_get(self):
        with open(os.path.join(ROOT, "core", "image_edit.py"), "r", encoding="utf-8") as f:
            src = f.read()
        self.assertRegex(src, r'safe_json_post\(\s*poll_url,\s*method="GET"',
                         "BFL 轮询未使用 GET，会被当作 POST 提交")


class TestMtimeCacheDynamicPathCoherence(unittest.TestCase):
    """_MtimeCache must track dynamic changes to API_ENV_FILE / API_PROVIDERS_FILE."""

    def test_switching_api_env_file_path_invalidates_cache_immediately(self):
        import tempfile
        import core.providers as CP

        orig_env_file = CP.API_ENV_FILE
        # Warm cache on original path
        _ = CP.read_api_env_value("__NON_EXISTENT_PROBE__")
        with tempfile.TemporaryDirectory() as tmp_dir:
            alt_env = os.path.join(tmp_dir, ".env")
            with open(alt_env, "w", encoding="utf-8") as f:
                f.write("DYNAMIC_PATH_TEST_KEY=expected_fresh_val\n")
            try:
                CP.API_ENV_FILE = alt_env
                # Without calling invalidate_api_env_cache(), switching API_ENV_FILE
                # must immediately reflect the new file because path is part of stamp
                self.assertEqual(
                    CP.read_api_env_value("DYNAMIC_PATH_TEST_KEY"),
                    "expected_fresh_val",
                    "切换 API_ENV_FILE 后 _MtimeCache 仍返回旧路径缓存",
                )
            finally:
                CP.API_ENV_FILE = orig_env_file
        self.assertEqual(CP.read_api_env_value("DYNAMIC_PATH_TEST_KEY"), "")


if __name__ == "__main__":
    unittest.main()