import os
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import core.providers as providers_mod
import routers.comfyui as comfy_mod
import routers.online_image as online_mod


def test_comfy_instances_shared_reference_on_save(monkeypatch):
    orig = list(comfy_mod.COMFYUI_INSTANCES)
    try:
        monkeypatch.setattr(comfy_mod, "_env_updater", lambda d: None)
        app = FastAPI()
        app.include_router(comfy_mod.router)
        client = TestClient(app)

        res = client.put(
            "/api/comfyui/instances",
            json={"instances": ["192.0.2.10:8188", "127.0.0.1:8188"]},
        )
        assert res.status_code == 200
        assert comfy_mod.COMFYUI_INSTANCES == ["192.0.2.10:8188", "127.0.0.1:8188"]
        assert providers_mod.COMFYUI_INSTANCES == ["192.0.2.10:8188", "127.0.0.1:8188"]
        assert online_mod.COMFYUI_INSTANCES == ["192.0.2.10:8188", "127.0.0.1:8188"]
    finally:
        comfy_mod.COMFYUI_INSTANCES[:] = orig


def test_instances_status_endpoint(monkeypatch):
    orig = list(comfy_mod.COMFYUI_INSTANCES)
    try:
        comfy_mod.COMFYUI_INSTANCES[:] = ["192.0.2.10:8188", "127.0.0.1:8188"]

        def fake_probe(addr, timeout=1.5):
            if addr == "192.0.2.10:8188":
                return {
                    "address": addr,
                    "online": True,
                    "latency_ms": 12,
                    "gpu_name": "NVIDIA GeForce RTX 5070",
                    "gpu_short": "RTX 5070",
                    "vram_total_gb": 12.0,
                    "vram_free_gb": 11.5,
                    "queue_running": 0,
                    "queue_pending": 0,
                    "local_load": 0,
                    "comfyui_version": "0.37.0",
                }
            return {
                "address": addr,
                "online": False,
                "latency_ms": None,
                "gpu_name": "",
                "gpu_short": "",
                "vram_total_gb": 0.0,
                "vram_free_gb": 0.0,
                "queue_running": 0,
                "queue_pending": 0,
                "local_load": 0,
                "comfyui_version": "",
            }

        monkeypatch.setattr(comfy_mod, "probe_comfy_node_status", fake_probe)
        app = FastAPI()
        app.include_router(comfy_mod.router)
        client = TestClient(app)

        res = client.get("/api/comfyui/instances/status")
        assert res.status_code == 200
        body = res.json()
        assert len(body["nodes"]) == 2
        assert body["nodes"][0]["online"] is True
        assert body["nodes"][0]["gpu_short"] == "RTX 5070"
        assert body["nodes"][1]["online"] is False
    finally:
        comfy_mod.COMFYUI_INSTANCES[:] = orig


def test_reserve_best_backend_auto_skips_offline_and_honors_manual(monkeypatch):
    orig = list(comfy_mod.COMFYUI_INSTANCES)
    try:
        comfy_mod.COMFYUI_INSTANCES[:] = ["127.0.0.1:8188", "192.0.2.10:8188"]
        comfy_mod.BACKEND_LOCAL_LOAD.clear()

        def fake_fetch_queue(addr, required_images=None, timeout=1.2):
            if addr == "127.0.0.1:8188":
                return None
            return {"remote_load": 0, "has_images": True}

        monkeypatch.setattr(comfy_mod, "_probe_backend_queue", fake_fetch_queue)

        # Auto mode skips offline 127.0.0.1:8188 and picks online 192.0.2.10:8188
        chosen = comfy_mod.reserve_best_backend(required_images=[], target_backend="auto")
        assert chosen == "192.0.2.10:8188"

        # Manual target_backend not in whitelist -> HTTP 400
        with pytest.raises(HTTPException) as exc400:
            comfy_mod.reserve_best_backend(required_images=[], target_backend="192.168.99.99:8188")
        assert exc400.value.status_code == 400

        # Manual target_backend offline -> HTTP 503
        with pytest.raises(HTTPException) as exc503:
            comfy_mod.reserve_best_backend(required_images=[], target_backend="127.0.0.1:8188")
        assert exc503.value.status_code == 503
    finally:
        comfy_mod.COMFYUI_INSTANCES[:] = orig


def test_sync_input_media_from_local_disk_to_remote_node(monkeypatch, tmp_path):
    local_img = tmp_path / "test_input.png"
    local_img.write_bytes(b"\x89PNG\r\n\x1a\nlocal_image_bytes")

    monkeypatch.setattr(
        comfy_mod,
        "local_media_file_by_basename",
        lambda name: str(local_img) if name == "test_input.png" else None,
    )
    monkeypatch.setattr(
        comfy_mod,
        "output_path_for",
        lambda name, cat="output": str(tmp_path / "nonexistent" / name),
    )

    uploaded = {}

    class FakeResp:
        def __init__(self, status_code=200, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.content = b""
            self.headers = {"Content-Type": "image/png"}

        def close(self):
            pass

        def json(self):
            return self._payload

    def fake_get(url, *args, **kwargs):
        return FakeResp(status_code=404)

    def fake_post(url, files=None, timeout=10):
        uploaded["url"] = url
        uploaded["files"] = files
        return FakeResp(status_code=200, payload={"name": "test_input.png"})

    # 桩 comfy_session 而非 requests：生产代码已把访问节点的请求切到
    # 这个强制直连的 Session（proxies 置空，绕开系统代理对 Tailnet 的劫持）。
    monkeypatch.setattr(comfy_mod.comfy_session, "get", fake_get)
    monkeypatch.setattr(comfy_mod.comfy_session, "post", fake_post)

    comfy_mod.sync_input_media_to_backend("192.0.2.10:8188", ["test_input.png"])
    assert uploaded["url"] == "http://192.0.2.10:8188/upload/image"
    assert uploaded["files"]["image"][0] == "test_input.png"
    assert uploaded["files"]["image"][1] == b"\x89PNG\r\n\x1a\nlocal_image_bytes"


# ---------------------------------------------------------------------
# 审查修正的回归测试 (2026-10-04)
# ---------------------------------------------------------------------

def test_media_probe_timeout_covers_tailnet_latency():
    """探测超时必须显著大于 Tailnet 往返延迟。

    实测 192.0.2.10 往返 625~812ms；原 0.8s 阈值导致 50% 误判，
    进而把远端已存在的图片重复跨网上传。
    """
    from routers import comfyui as comfy_mod
    assert comfy_mod.MEDIA_PROBE_TIMEOUT >= 2.0, (
        f"探测超时 {comfy_mod.MEDIA_PROBE_TIMEOUT}s 过小，"
        "Tailnet 往返约 0.6~0.8s，会误判并触发重复上传"
    )


def test_node_session_bypasses_system_proxy():
    """访问 ComfyUI 节点必须强制直连。

    requests.sessions.merge_setting 会剔除值为 None 的键；若 trust_env=True，
    merge_environment_settings 仍会从系统注册表填回代理（如 127.0.0.1:7897）。
    因此必须同时断言 trust_env is False 且 proxies 的 http/https 置空。
    """
    from routers import comfyui as comfy_mod
    assert comfy_mod.comfy_session.trust_env is False, "comfy_session 未关闭 trust_env，系统注册表代理仍会生效"
    proxies = comfy_mod.comfy_session.proxies
    assert proxies.get("http") is None, "comfy_session 仍在走系统代理"
    assert proxies.get("https") is None, "comfy_session 仍在走系统代理"


def test_opener_disables_proxy():
    """sync_comfy_no_proxy 安装的 opener 必须真正禁用代理。

    build_opener() 不传 ProxyHandler 会安装一个读系统代理的处理器；
    传入 ProxyHandler({}) 后该处理器会被丢弃（不装任何代理处理器），
    即代理被禁用 —— 因此这里断言「opener 中不存在 ProxyHandler」。

    回归背景：原实现的改动条件里含「NO_PROXY 变化」，而 API/.env 本就带
    NO_PROXY 配置，首次调用时条件不成立，install_opener 从未执行。
    """
    from routers import comfyui as comfy_mod
    opener = comfy_mod.urllib.request._opener
    assert opener is not None, "urllib opener 未初始化"
    proxy_handlers = [h for h in opener.handlers if type(h).__name__ == "ProxyHandler"]
    assert not proxy_handlers, (
        "opener 中仍装有 ProxyHandler，说明未禁用系统代理，"
        "Tailnet 请求会被绕进 Clash 等代理"
    )


def test_get_best_backend_rejects_offline_explicit_node(monkeypatch):
    """get_best_backend 与 reserve_best_backend 行为必须一致。

    修复前：手动指定离线节点时直接返回该节点（不校验在线），
            而 reserve_best_backend 正确抛 503 —— 两条路径行为分叉。
    """
    from fastapi import HTTPException
    from routers import comfyui as comfy_mod

    orig = list(comfy_mod.COMFYUI_INSTANCES)
    try:
        comfy_mod.COMFYUI_INSTANCES[:] = ["192.0.2.10:8188", "127.0.0.1:8188"]
        monkeypatch.setattr(comfy_mod, "_probe_backend_queue", lambda addr, imgs: None)
        with pytest.raises(HTTPException) as exc:
            comfy_mod.get_best_backend(required_images=[], target_backend="192.0.2.10:8188")
        assert exc.value.status_code == 503
    finally:
        comfy_mod.COMFYUI_INSTANCES[:] = orig


def test_get_best_backend_allows_online_explicit_node(monkeypatch):
    """在线的显式节点仍应正常返回（防止上一条修复过头）。"""
    from routers import comfyui as comfy_mod

    orig = list(comfy_mod.COMFYUI_INSTANCES)
    try:
        comfy_mod.COMFYUI_INSTANCES[:] = ["192.0.2.10:8188", "127.0.0.1:8188"]
        monkeypatch.setattr(
            comfy_mod, "_probe_backend_queue",
            lambda addr, imgs: {"load": 0, "has_images": True, "remote_load": 0},
        )
        assert comfy_mod.get_best_backend(
            required_images=[], target_backend="192.0.2.10:8188"
        ) == "192.0.2.10:8188"
    finally:
        comfy_mod.COMFYUI_INSTANCES[:] = orig


def test_dlss5_workflow_builder_modes_and_oversize_downgrade():
    """验证 DLSS5 动态工作流构建（dlaa / 2x / 2pass）及 7680x4320 超限自动降级。"""
    from routers import comfyui as comfy_mod

    # 1. 2pass 模式：应包含两次 DLSS5EnhanceImages（先 1x DLAA，再 2x Performance）及单 SaveImage
    wf_2pass = comfy_mod.build_dlss5_workflow(
        src_name="room.png",
        mode="2pass",
        style="Cinematic",
        structure=1.8,
        prefix="dlss5_out",
    )
    load_nodes = [n for n in wf_2pass.values() if n["class_type"] == "LoadImage"]
    setting_nodes = [n for n in wf_2pass.values() if n["class_type"] == "DLSS5Settings"]
    enhance_nodes = [n for n in wf_2pass.values() if n["class_type"] == "DLSS5EnhanceImages"]
    save_nodes = [n for n in wf_2pass.values() if n["class_type"] == "SaveImage"]

    assert len(load_nodes) == 1
    assert load_nodes[0]["inputs"]["image"] == "room.png"
    assert len(setting_nodes) == 2
    assert setting_nodes[0]["inputs"]["upscaling_mode"] == "1x (DLAA / native)"
    assert setting_nodes[1]["inputs"]["upscaling_mode"] == "2x (Performance)"
    assert setting_nodes[0]["inputs"]["nr_style"] == "Cinematic"
    assert setting_nodes[0]["inputs"]["local_structure_strength"] == 1.8
    assert setting_nodes[0]["inputs"]["dlss_model_preset"] == "M"
    assert len(enhance_nodes) == 2
    assert all(n["inputs"]["verify_neural_rendering"] is True for n in enhance_nodes)
    assert len(save_nodes) == 1

    # 2. 超限尺寸自动降级：2832x2944 在 2x 下短边 5888 > 4320，应自动降级为 dlaa
    eff_mode, reason = comfy_mod.resolve_dlss5_effective_mode("2pass", 2832, 2944)
    assert eff_mode == "dlaa"
    assert "4320" in reason

    # 3. 常规尺寸保持原模式
    eff_ok, reason_ok = comfy_mod.resolve_dlss5_effective_mode("2pass", 1920, 1080)
    assert eff_ok == "2pass"
    assert reason_ok == ""


def test_dlss5_prepare_input_image_converts_rgba_to_rgb(monkeypatch, tmp_path):
    """验证 DLSS5 输入图预处理自动将 RGBA PNG 转为 RGB PNG 并返回宽高。"""
    from PIL import Image
    from routers import comfyui as comfy_mod

    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    img_path = input_dir / "rgba_render.png"
    Image.new("RGBA", (640, 480), (120, 140, 160, 128)).save(img_path, format="PNG")

    monkeypatch.setattr(
        comfy_mod,
        "output_path_for",
        lambda name, sub="": str((tmp_path / sub / name) if sub else (tmp_path / name)),
    )
    monkeypatch.setattr(comfy_mod, "local_media_file_by_basename", lambda name: None)

    w, h = comfy_mod.prepare_dlss5_input_image("rgba_render.png")
    assert (w, h) == (640, 480)
    with Image.open(img_path) as converted:
        assert converted.mode == "RGB"
        assert converted.size == (640, 480)

