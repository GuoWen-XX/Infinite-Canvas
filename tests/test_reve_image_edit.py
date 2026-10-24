import io
import os
import time
import pytest
from PIL import Image

from core.image_edit import (
    synthesize_feathered_mask,
    build_edit_prompt_with_region,
)

def test_mask_synthesis_no_region_returns_empty():
    mask_bytes = synthesize_feathered_mask(500, 500, None)
    assert mask_bytes == b""

def test_mask_synthesis_with_region_dimensions_and_feathering():
    orig_w, orig_h = 400, 300
    region = {"x": 100, "y": 100, "width": 200, "height": 100}
    mask_bytes = synthesize_feathered_mask(orig_w, orig_h, region, feather_radius=4)
    assert mask_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    img = Image.open(io.BytesIO(mask_bytes))
    assert img.size == (orig_w, orig_h)
    assert img.mode in ("L", "RGBA")

    # Center of region should be white (255)
    gray = img.convert("L")
    center_val = gray.getpixel((200, 150))
    assert center_val > 240

    # Outside the region should be black (0)
    outside_val = gray.getpixel((20, 20))
    assert outside_val == 0

    # Boundary should have transitional feathering
    edge_val = gray.getpixel((100, 150))
    assert 0 < edge_val < 255

def test_mask_synthesis_region_clamping_boundary_safety():
    orig_w, orig_h = 200, 200
    # Region extends beyond bounds
    region = {"x": -50, "y": -50, "width": 500, "height": 500}
    mask_bytes = synthesize_feathered_mask(orig_w, orig_h, region)
    img = Image.open(io.BytesIO(mask_bytes))
    assert img.size == (orig_w, orig_h)

def test_build_edit_prompt_with_region():
    base_prompt = "给人物戴上一副黑色墨镜"
    # No region
    assert build_edit_prompt_with_region(base_prompt, None) == base_prompt

    # With region
    region = {"x": 120, "y": 80, "width": 160, "height": 90}
    prompt_with_reg = build_edit_prompt_with_region(base_prompt, region, orig_w=1000, orig_h=1000)
    assert base_prompt in prompt_with_reg
    assert "局部" in prompt_with_reg or "区域" in prompt_with_reg or "region" in prompt_with_reg


def test_detect_edit_dispatch_mode():
    from core.image_edit import detect_edit_dispatch_mode

    # BFL fill
    assert detect_edit_dispatch_mode({"id": "bfl"}, "flux-pro-1.0-fill") == "bfl-fill"
    assert detect_edit_dispatch_mode({}, "flux-pro-fill") == "bfl-fill"

    # OpenAI edits
    assert detect_edit_dispatch_mode({"id": "openai"}, "dall-e-2") == "openai-edits"
    assert detect_edit_dispatch_mode({"image_edit_mode": "edits"}, "any-model") == "openai-edits"

    # Instruction mode
    assert detect_edit_dispatch_mode({"id": "siliconflow-cn"}, "qwen-image-edit") == "instruction"
    assert detect_edit_dispatch_mode({}, "gpt-image-2") == "instruction"
    assert detect_edit_dispatch_mode({}, "flux-kontext") == "instruction"


def _as_send(post_impl):
    """把 AsyncClient.post 桩适配为 AsyncClient.send 桩。

    core.security.safe_json_post 用 client.build_request(...) + client.send(...)，
    以便在流式响应上复检真实对端 IP，因此不能再桩 post。
    """
    async def _send(self, request, **kwargs):
        return await post_impl(self, str(request.url), headers=dict(request.headers))
    return _send


def _as_send_bfl(post_impl, get_impl):
    """同上，但按请求方法分派到 post / get 桩。"""
    async def _send(self, request, **kwargs):
        url = str(request.url)
        if request.method == "GET":
            return await get_impl(self, url, headers=dict(request.headers))
        return await post_impl(self, url, headers=dict(request.headers))
    return _send


def _real_png(size=(16, 16), color=(120, 30, 30)):
    """生成真实的 PNG 字节。payload 构建器现在会真正解析图片
    （格式探测、遮罩转 alpha），伪造字节会让 PIL 抛 UnidentifiedImageError。"""
    import io as _io
    from PIL import Image as _Image
    buf = _io.BytesIO()
    _Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _real_mask(size=(16, 16), box=(4, 4, 12, 12)):
    """生成真实的灰度遮罩 PNG 字节。"""
    import io as _io
    from PIL import Image as _Image, ImageDraw as _Draw
    img = _Image.new("L", size, 0)
    _Draw.Draw(img).rectangle(list(box), fill=255)
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_prepare_reve_edit_payload_bfl():
    from core.image_edit import prepare_reve_edit_payload
    provider = {"id": "bfl", "base_url": "https://api.bfl.ml/v1"}
    fake_png = _real_png()
    fake_mask = _real_mask()
    payload = prepare_reve_edit_payload(
        provider=provider,
        model="flux-pro-1.0-fill",
        prompt="A cute cat",
        source_image_bytes=fake_png,
        mask_bytes=fake_mask,
    )
    assert payload["mode"] == "bfl-fill"
    assert payload["endpoint_url"] == "https://api.bfl.ml/v1/flux-pro-1.0-fill"
    assert "image" in payload["json_body"]
    assert "mask" in payload["json_body"]
    assert payload["json_body"]["prompt"] == "A cute cat"
    assert payload["is_async_task"] is True


def test_prepare_reve_edit_payload_openai_edits():
    from core.image_edit import prepare_reve_edit_payload
    provider = {"id": "openai", "base_url": "https://api.openai.com/v1", "image_edit_mode": "edits"}
    fake_png = _real_png()
    fake_mask = _real_mask()
    payload = prepare_reve_edit_payload(
        provider=provider,
        model="dall-e-2",
        prompt="Make it red",
        source_image_bytes=fake_png,
        mask_bytes=fake_mask,
    )
    assert payload["mode"] == "openai-edits"
    assert payload["endpoint_url"] == "https://api.openai.com/v1/images/edits"
    assert "image" in payload["files"]
    assert "mask" in payload["files"]
    assert payload["form_data"]["prompt"] == "Make it red"


def test_prepare_reve_edit_payload_instruction():
    from core.image_edit import prepare_reve_edit_payload
    provider = {"id": "siliconflow-cn", "base_url": "https://api.siliconflow.cn/v1"}
    fake_png = _real_png()
    payload = prepare_reve_edit_payload(
        provider=provider,
        model="qwen-image-edit",
        prompt="Change car color",
        source_image_bytes=fake_png,
        mask_bytes=None,
    )
    assert payload["mode"] == "instruction"
    assert "image" in payload["json_body"] or "image_url" in str(payload["json_body"])
    assert payload["json_body"]["prompt"] == "Change car color"


def test_api_canvas_edit_missing_prompt_returns_400():
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from routers.online_image import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post("/api/canvas-edit", json={"source_image_url": "/output/fake.png", "prompt": ""})
    assert resp.status_code == 400
    assert "提示词" in resp.text or "prompt" in resp.text.lower()


def test_api_canvas_edit_missing_source_image_returns_400():
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from routers.online_image import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post("/api/canvas-edit", json={"source_image_url": "", "prompt": "Make it sunny"})
    assert resp.status_code == 400


def test_api_canvas_edit_ssrf_private_url_blocked():
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from routers.online_image import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post("/api/canvas-edit", json={
        "source_image_url": "http://127.0.0.1:8000/output/secret.png",
        "prompt": "Make it sunny"
    })
    assert resp.status_code == 400


def test_api_canvas_edit_mocked_success(monkeypatch, tmp_path):
    import io
    import httpx
    from PIL import Image
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from routers.online_image import router
    from core.providers import OUTPUT_DIR

    # Create dummy local source image
    test_img = Image.new("RGB", (100, 100), color=(255, 0, 0))
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    src_filename = f"test_reve_src_{int(time.time())}.png"
    src_filepath = os.path.join(OUTPUT_DIR, src_filename)
    test_img.save(src_filepath, format="PNG")

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # Mock httpx.AsyncClient.post
    async def mock_post(self, url, *args, **kwargs):
        class MockResp:
            status_code = 200
            extensions = {}
            content = b'{}'
            async def aread(self):
                return self.content
            async def aclose(self):
                return None
            def raise_for_status(self): pass
            def json(self):
                return {"data": [{"b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="}]}
        return MockResp()

    monkeypatch.setattr(httpx.AsyncClient, "send", _as_send(mock_post))

    try:
        resp = client.post("/api/canvas-edit", json={
            "source_image_url": f"/output/{src_filename}",
            "prompt": "Make it green",
            "region": {"x": 10, "y": 10, "width": 50, "height": 50}
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "output_url" in data
        assert data["output_url"].startswith("/output/")
        assert "task_id" in data
    finally:
        if os.path.isfile(src_filepath):
            os.remove(src_filepath)


def test_api_canvas_edit_upstream_http_error_returns_502(monkeypatch):
    import httpx
    from PIL import Image
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from routers.online_image import router
    from core.providers import OUTPUT_DIR

    test_img = Image.new("RGB", (50, 50), color=(0, 255, 0))
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    src_filename = f"test_reve_err_{int(time.time())}.png"
    src_filepath = os.path.join(OUTPUT_DIR, src_filename)
    test_img.save(src_filepath, format="PNG")

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    async def mock_post_fail(self, url, *args, **kwargs):
        req = httpx.Request("POST", url)
        resp = httpx.Response(status_code=401, json={"error": {"message": "Invalid API token"}}, request=req)
        raise httpx.HTTPStatusError("Unauthorized", request=req, response=resp)

    monkeypatch.setattr(httpx.AsyncClient, "send", _as_send(mock_post_fail))

    try:
        resp = client.post("/api/canvas-edit", json={
            "source_image_url": f"/output/{src_filename}",
            "prompt": "Change to blue",
        })
        assert resp.status_code == 502
        # 不使用 `or "上游服务请求失败" in ...` 兜底：那段前缀由实现无条件格式化，
        # 即使错误信息提取完全损坏该断言仍会通过，等于恒真。
        assert "Invalid API token" in resp.json()["detail"], resp.json()["detail"]
    finally:
        if os.path.isfile(src_filepath):
            os.remove(src_filepath)


def test_api_canvas_edit_bfl_async_polling_success(monkeypatch):
    import httpx
    from PIL import Image
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from routers.online_image import router
    import core.security
    from core.providers import OUTPUT_DIR

    test_img = Image.new("RGB", (50, 50), color=(0, 0, 255))
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    src_filename = f"test_reve_bfl_{int(time.time())}.png"
    src_filepath = os.path.join(OUTPUT_DIR, src_filename)
    test_img.save(src_filepath, format="PNG")

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    async def mock_post_bfl(self, url, *args, **kwargs):
        class MockResp:
            status_code = 200
            extensions = {}
            content = b'{}'
            async def aread(self):
                return self.content
            async def aclose(self):
                return None
            def raise_for_status(self): pass
            def json(self):
                return {"id": "bfl_task_789", "status": "Pending"}
        return MockResp()

    async def mock_get_bfl(self, url, *args, **kwargs):
        class MockResp:
            status_code = 200
            extensions = {}
            content = b'{}'
            async def aread(self):
                return self.content
            async def aclose(self):
                return None
            def raise_for_status(self): pass
            def json(self):
                return {
                    "status": "Ready",
                    "result": {"sample": "https://delivery.bfl.ml/sample_output.png"}
                }
        return MockResp()

    dummy_png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    async def mock_safe_download(url, *args, **kwargs):
        return dummy_png_bytes, "image/png"

    monkeypatch.setattr(httpx.AsyncClient, "send", _as_send_bfl(mock_post_bfl, mock_get_bfl))
    monkeypatch.setattr(core.security, "safe_download_bytes", mock_safe_download)

    try:
        resp = client.post("/api/canvas-edit", json={
            "source_image_url": f"/output/{src_filename}",
            "prompt": "Paint a sunflower",
            "model": "flux-pro-1.0-fill",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "output_url" in data
        assert data["output_url"].startswith("/output/")
    finally:
        if os.path.isfile(src_filepath):
            os.remove(src_filepath)


def test_api_canvas_edit_bfl_async_polling_failure(monkeypatch):
    import httpx
    from PIL import Image
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from routers.online_image import router
    from core.providers import OUTPUT_DIR

    test_img = Image.new("RGB", (50, 50), color=(0, 0, 255))
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    src_filename = f"test_reve_bfl_fail_{int(time.time())}.png"
    src_filepath = os.path.join(OUTPUT_DIR, src_filename)
    test_img.save(src_filepath, format="PNG")

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    async def mock_post_bfl(self, url, *args, **kwargs):
        class MockResp:
            status_code = 200
            extensions = {}
            content = b'{}'
            async def aread(self):
                return self.content
            async def aclose(self):
                return None
            def raise_for_status(self): pass
            def json(self):
                return {"id": "bfl_task_fail_999", "status": "Pending"}
        return MockResp()

    async def mock_get_bfl(self, url, *args, **kwargs):
        class MockResp:
            status_code = 200
            extensions = {}
            content = b'{}'
            async def aread(self):
                return self.content
            async def aclose(self):
                return None
            def raise_for_status(self): pass
            def json(self):
                return {
                    "status": "Failed",
                    "error": "Image prompt rejected by safety filter"
                }
        return MockResp()

    monkeypatch.setattr(httpx.AsyncClient, "send", _as_send_bfl(mock_post_bfl, mock_get_bfl))

    try:
        resp = client.post("/api/canvas-edit", json={
            "source_image_url": f"/output/{src_filename}",
            "prompt": "Unsafe prompt",
            "model": "flux-pro-1.0-fill",
        })
        assert resp.status_code == 502
        # 同上：BFL 任务失败 是实现无条件加的前缀，不可作为断言右项
        assert "safety filter" in resp.json()["detail"], resp.json()["detail"]
    finally:
        if os.path.isfile(src_filepath):
            os.remove(src_filepath)


def test_prepare_reve_edit_payload_instruction_base_url_normalization():
    from core.image_edit import prepare_reve_edit_payload
    provider = {"id": "fhl", "base_url": "https://www.fhl.mom"}
    fake_png = _real_png()
    payload = prepare_reve_edit_payload(
        provider=provider,
        model="gpt-image-2",
        prompt="Change lighting to warm sunset",
        source_image_bytes=fake_png,
        mask_bytes=None,
    )
    assert payload["mode"] == "instruction"
    assert payload["endpoint_url"] == "https://www.fhl.mom/v1/images/generations"
    assert payload["json_body"]["model"] == "gpt-image-2"


def test_api_canvas_edit_fallback_to_model_provider_when_pid_unknown(monkeypatch):
    import httpx
    from PIL import Image
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from routers.online_image import router
    from core.providers import OUTPUT_DIR

    test_img = Image.new("RGB", (50, 50), color=(100, 100, 100))
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    src_filename = f"test_reve_fallback_{int(time.time())}.png"
    src_filepath = os.path.join(OUTPUT_DIR, src_filename)
    test_img.save(src_filepath, format="PNG")

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    captured_url = None

    async def mock_post_success(self, url, *args, **kwargs):
        nonlocal captured_url
        captured_url = str(url)
        class MockResp:
            status_code = 200
            extensions = {}
            content = b'{}'
            async def aread(self):
                return self.content
            async def aclose(self):
                return None
            def raise_for_status(self): pass
            def json(self):
                return {"data": [{"b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="}]}
        return MockResp()

    monkeypatch.setattr(httpx.AsyncClient, "send", _as_send(mock_post_success))

    try:
        # User requested unknown provider "openai", but model "gpt-image-2" is supported by configured providers
        resp = client.post("/api/canvas-edit", json={
            "source_image_url": f"/output/{src_filename}",
            "prompt": "Sunset edit",
            "model": "gpt-image-2",
            "provider_id": "openai",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["output_url"].startswith("/output/")
        assert data["model"] == "gpt-image-2"
        # Should not crash with 400 "未找到 API 平台：openai"
    finally:
        if os.path.isfile(src_filepath):
            os.remove(src_filepath)





