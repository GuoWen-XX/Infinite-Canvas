import os
import sys
import re
import json
import shutil
import time
import uuid
import random
import logging
import urllib.request
import urllib.parse
import urllib.error
import asyncio
import base64
from typing import Any, Dict, List, Optional, Tuple, Union
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import requests
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from core.security import is_safe_remote_url, is_valid_comfy_address, validate_safe_url
from core.providers import (
    COMFYUI_INSTANCES,
    COMFYUI_HISTORY_TIMEOUT,
    COMFYUI_DOWNLOAD_TIMEOUT,
)
from routers.assets import (
    output_path_for,
    output_url_for,
    output_file_from_url,
    local_media_file_by_basename,
    content_type_for_path,
    _local_upload_kind_ext,
    sanitize_export_filename,
    dump_pydantic,
)
from routers.tasks import record_task_event
from routers.common import save_to_history, get_ws_manager, get_global_loop

_server_logger = logging.getLogger("infinite_canvas.comfyui")
logger = _server_logger

CLIENT_ID = "infinite_canvas_server"
BUILTIN_WORKFLOWS = {"Z-Image.json", "Z-Image-Enhance.json", "2511.json", "klein-enhance.json", "Flux2-Klein.json", "upscale.json"}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
WORKFLOW_DIR = os.path.join(BASE_DIR, "workflow")
WORKFLOW_PATH = os.path.join(WORKFLOW_DIR, "Z-Image.json")

COMFYUI_ADDRESS = COMFYUI_INSTANCES[0] if COMFYUI_INSTANCES else "127.0.0.1:8188"
BACKEND_LOCAL_LOAD = {addr: 0 for addr in COMFYUI_INSTANCES}
LOAD_LOCK = Lock()

QUEUE = []
QUEUE_LOCK = Lock()
NEXT_TASK_ID = 1

MAX_COMFY_CANVAS_TASKS = 1000
CANVAS_TASKS: Dict[str, Dict[str, Any]] = {}
CANVAS_TASK_LOCK = Lock()

def _prune_comfy_canvas_tasks() -> None:
    if len(CANVAS_TASKS) < MAX_COMFY_CANVAS_TASKS:
        return
    excess = len(CANVAS_TASKS) - MAX_COMFY_CANVAS_TASKS + 1
    to_remove = []
    for tid, tinfo in CANVAS_TASKS.items():
        if tinfo.get("status") in {"succeeded", "failed", "error", "cancelled"}:
            to_remove.append(tid)
            if len(to_remove) >= excess:
                break
    if len(to_remove) < excess:
        for tid in CANVAS_TASKS:
            if tid not in to_remove:
                to_remove.append(tid)
                if len(to_remove) >= excess:
                    break
    for tid in to_remove:
        CANVAS_TASKS.pop(tid, None)

COMFY_PREVIEW_CLASS_HINTS = ("previewimage", "comparer", "imagecompare", "image compare")
COMFY_DEBUG_TEXT_CLASS_HINTS = (
    "showtext", "show text", "showanything", "show any", "preview any", "previewany",
    "displaytext", "display text", "display any", "anything everywhere", "convertanything",
    "easy show", "note", "mathexpression", "cr text", "text multiline", "string function",
    "debug",
)

def is_valid_comfy_address(addr: str) -> bool:
    if not addr or not isinstance(addr, str):
        return False
    parts = addr.split(":")
    if len(parts) != 2:
        return False
    host, port = parts
    return bool(host) and port.isdigit() and 1 <= int(port) <= 65535

def sync_comfy_no_proxy(instances: Optional[List[str]] = None) -> None:
    raw_existing = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "localhost,127.0.0.1,::1"
    entries = [x.strip() for x in raw_existing.split(",") if x.strip()]
    for base_host in ("localhost", "127.0.0.1", "::1"):
        if base_host not in entries:
            entries.append(base_host)
    for item in (instances if instances is not None else COMFYUI_INSTANCES):
        host = str(item or "").strip().rpartition(":")[0].strip()
        if host and host not in entries:
            entries.append(host)
    joined = ",".join(entries)
    changed = os.environ.get("NO_PROXY") != joined or os.environ.get("no_proxy") != joined
    if changed:
        os.environ["NO_PROXY"] = joined
        os.environ["no_proxy"] = joined
    # 必须显式传 ProxyHandler({})：空字典意为「禁用所有代理」。
    # 直接 build_opener() 会沿用系统代理（如 Clash 127.0.0.1:7897），
    # Tailnet / 局域网的直连请求被绕进代理后既变慢又可能失败。
    #
    # 这里不能只在「NO_PROXY 发生变化」时重建 opener：API/.env 中本来就带有
    # NO_PROXY 配置，首次调用时 joined 与现值完全相同，改动条件不成立，
    # opener 永远不会被替换 —— 默认 opener 仍在走系统代理（实测确认）。
    # 因此改为幂等地强制安装一次禁用代理的 opener。
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
    )

# 访问各 ComfyUI 节点用的 requests.Session，强制直连。
# 注意：requests.sessions.merge_setting 会剔除值为 None 的键，若 trust_env=True（默认），
# merge_environment_settings 仍会从系统注册表/环境变量填回代理（如 127.0.0.1:7897）。
# 必须同时设置 trust_env = False 并保留 proxies 显式置空，彻底杜绝代理劫持且复用 Keep-Alive 连接池。
comfy_session = requests.Session()
comfy_session.trust_env = False
comfy_session.proxies.update({"http": None, "https": None})

sync_comfy_no_proxy(COMFYUI_INSTANCES)

def convert_output_to_jpg(url, quality=88):
    path = output_file_from_url(url)
    if not path:
        return url
    root, ext = os.path.splitext(path)
    if ext.lower() in [".jpg", ".jpeg"]:
        return url
    jpg_path = f"{root}.jpg"
    try:
        with Image.open(path) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            img.save(jpg_path, "JPEG", quality=quality, optimize=True)
        try:
            root = ASSETS_DIR if os.path.commonpath([os.path.abspath(ASSETS_DIR), os.path.abspath(jpg_path)]) == os.path.abspath(ASSETS_DIR) else OUTPUT_DIR
        except ValueError:
            root = OUTPUT_DIR
        rel = os.path.relpath(jpg_path, root).replace("\\", "/")
        prefix = "/assets" if root == ASSETS_DIR else "/output"
        return f"{prefix}/{rel}"
    except Exception as e:
        _server_logger.warning(f"转换 JPG 失败: {e}")
        return url

class Base64UploadRequest(BaseModel):
    data: str = Field(..., max_length=70 * 1024 * 1024)
    name: str = ""
    content_type: str = ""

# Hooks
_history_saver = lambda rec: None
_env_updater = lambda d: None

def set_comfyui_history_saver(fn):
    global _history_saver
    _history_saver = fn

def set_comfyui_env_updater(fn):
    global _env_updater
    _env_updater = fn

router = APIRouter(tags=["comfyui"])

# --- Pydantic Models ---
class GenerateRequest(BaseModel):
    prompt: str = ""
    width: int = 1024
    height: int = 1024
    workflow_json: Union[str, Dict[str, Any]] = "Z-Image.json"
    params: Dict[str, Any] = {}
    type: str = "zimage"
    client_id: str = ""
    convert_to_jpg: bool = False
    target_backend: str = ""

CUSTOM_WORKFLOW_FOLDER = "custom"
LEGACY_CUSTOM_WORKFLOW_FOLDER = "自定义"
WORKFLOW_NAME_RE = re.compile(rf"^(?:(?:{CUSTOM_WORKFLOW_FOLDER}|{LEGACY_CUSTOM_WORKFLOW_FOLDER})/)?[a-zA-Z0-9_一-龥\.\-]+\.json$")

class WorkflowField(BaseModel):
    id: str
    node: str = ""
    input: str = ""
    name: str = ""
    type: str = "text"
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    options: List[str] = []
    random_enabled: bool = False

class WorkflowConfig(BaseModel):
    title: str = ""
    fields: List[WorkflowField] = []
    mini_cards: Dict[str, Any] = {}

class WorkflowUploadRequest(BaseModel):
    name: str
    workflow: Dict[str, Any]

class WorkflowRunRequest(BaseModel):
    fields: Dict[str, Any] = {}
    config: WorkflowConfig
    client_id: str = ""
    target_backend: str = ""

class ComfyInstancesPayload(BaseModel):
    instances: List[str] = []

# --- ComfyUI Helpers ---
# 探测「节点是否已持有某图」及队列状态的超时。Tailnet/跨网实测往返 600~800ms，
# 冷连接经美西 DERP 中继 + Tailscale disco 唤醒首包实测可达 2.0~5.4s，
# 取 6.5s 以覆盖跨网 DERP 冷启动握手并杜绝假阴性离线误判。
MEDIA_PROBE_TIMEOUT = 6.5


def check_images_exist(backend_addr, images):
    if not images: return True
    for img in images:
        try:
            url = f"http://{backend_addr}/view?filename={urllib.parse.quote(img)}&type=input"
            r = comfy_session.get(url, stream=True, timeout=MEDIA_PROBE_TIMEOUT)
            r.close()
            if r.status_code != 200: return False
        except Exception: return False
    return True

MEDIA_INPUT_KEYS = ("image", "video", "audio", "mask", "filename", "file")
MEDIA_INPUT_EXT_RE = re.compile(r"\.(png|jpe?g|webp|gif|bmp|tiff?|mp4|webm|mov|m4v|avi|mkv|mp3|wav|m4a|aac|ogg|flac)(?:\?|$)", re.I)

def is_comfy_input_media_value(input_name: str, value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    key = str(input_name or "").lower()
    if any(token in key for token in MEDIA_INPUT_KEYS):
        return True
    return bool(MEDIA_INPUT_EXT_RE.search(value))

def collect_required_comfy_media(params: Dict[str, Any]) -> List[str]:
    required = []
    for node_inputs in (params or {}).values():
        if not isinstance(node_inputs, dict):
            continue
        scan_inputs = node_inputs.get("inputs") if isinstance(node_inputs.get("inputs"), dict) else node_inputs
        for input_name, value in scan_inputs.items():
            if is_comfy_input_media_value(input_name, value):
                required.append(value)
    return list(dict.fromkeys(required))

def comfy_prompt_error_message(status_code: int, error_body: str) -> str:
    """Turn ComfyUI's validation payload into a useful canvas error."""
    fallback = str(error_body or "").strip()
    try:
        payload = json.loads(fallback)
    except (TypeError, ValueError):
        return f"ComfyUI 请求失败（HTTP {status_code}）：{fallback[:500] or '未知错误'}"

    parts = []
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        details = str(error.get("details") or "").strip()
        if message:
            parts.append(message)
        if details and details not in parts:
            parts.append(details)

    node_errors = payload.get("node_errors") if isinstance(payload, dict) else None
    if isinstance(node_errors, dict):
        for node_id, node_error in list(node_errors.items())[:3]:
            if not isinstance(node_error, dict):
                continue
            class_type = str(node_error.get("class_type") or "").strip()
            messages = []
            for item in node_error.get("errors") or []:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("message") or item.get("details") or "").strip()
                if text and text not in messages:
                    messages.append(text)
            if messages:
                label = f"节点 {node_id}" + (f"（{class_type}）" if class_type else "")
                parts.append(f"{label}：{'；'.join(messages[:2])}")

    detail = "；".join(part for part in parts if part).strip()
    return f"ComfyUI 拒绝了工作流（HTTP {status_code}）：{detail[:700] or fallback[:500] or '工作流校验失败'}"

def _short_gpu_name(raw_name: str) -> str:
    s = str(raw_name or "").strip()
    if not s:
        return ""
    s = re.sub(r"^cuda:\d+\s*", "", s, flags=re.I)
    s = s.split(":", 1)[0].strip()
    for prefix in ("NVIDIA GeForce ", "NVIDIA ", "AMD Radeon "):
        if s.upper().startswith(prefix.upper()):
            s = s[len(prefix):].strip()
            break
    return s

def probe_comfy_node_status(addr: str, timeout: float = MEDIA_PROBE_TIMEOUT) -> Dict[str, Any]:
    with LOAD_LOCK:
        local_load = BACKEND_LOCAL_LOAD.get(addr, 0)
    info: Dict[str, Any] = {
        "address": addr,
        "online": False,
        "latency_ms": None,
        "gpu_name": "",
        "gpu_short": "",
        "vram_total_gb": 0.0,
        "vram_free_gb": 0.0,
        "queue_running": 0,
        "queue_pending": 0,
        "local_load": local_load,
        "comfyui_version": "",
    }
    if not is_valid_comfy_address(addr):
        return info
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(f"http://{addr}/queue", timeout=timeout) as q_resp:
            q_data = json.loads(q_resp.read())
            info["online"] = True
            info["latency_ms"] = max(1, int(round((time.perf_counter() - t0) * 1000)))
            info["queue_running"] = len(q_data.get("queue_running") or [])
            info["queue_pending"] = len(q_data.get("queue_pending") or [])
    except Exception:
        return info
    try:
        with urllib.request.urlopen(f"http://{addr}/system_stats", timeout=timeout) as s_resp:
            s_data = json.loads(s_resp.read())
            sys_info = s_data.get("system") or {}
            info["comfyui_version"] = str(sys_info.get("comfyui_version") or "")
            devices = s_data.get("devices") or []
            if devices and isinstance(devices[0], dict):
                dev = devices[0]
                raw_gpu = str(dev.get("name") or "")
                info["gpu_name"] = raw_gpu
                info["gpu_short"] = _short_gpu_name(raw_gpu)
                v_tot = float(dev.get("vram_total") or 0)
                v_free = float(dev.get("vram_free") or 0)
                if v_tot > 0:
                    info["vram_total_gb"] = round(v_tot / (1024 ** 3), 1)
                    info["vram_free_gb"] = round(v_free / (1024 ** 3), 1)
    except Exception:
        pass
    return info

def _probe_backend_queue(addr: str, required_images: Optional[List[str]] = None, timeout: float = MEDIA_PROBE_TIMEOUT) -> Optional[Dict[str, Any]]:
    try:
        with urllib.request.urlopen(f"http://{addr}/queue", timeout=timeout) as response:
            data = json.loads(response.read())
            remote_load = len(data.get("queue_running", [])) + len(data.get("queue_pending", []))
            has_images = check_images_exist(addr, required_images)
            return {"remote_load": remote_load, "has_images": has_images}
    except Exception as e:
        logger.debug(f"Backend {addr} unreachable: {e}")
        return None

def _normalize_target_backend(target_backend: str) -> str:
    raw = str(target_backend or "").strip()
    if not raw or raw.lower() == "auto":
        return ""
    return re.sub(r"^https?://", "", raw, flags=re.I).rstrip("/")

def get_best_backend(required_images: List[str] = None, target_backend: str = ""):
    sync_comfy_no_proxy(COMFYUI_INSTANCES)
    explicit = _normalize_target_backend(target_backend)
    if explicit:
        if explicit not in COMFYUI_INSTANCES:
            raise HTTPException(status_code=400, detail=f"未注册的 ComfyUI 节点地址：{explicit}")
        # 与 reserve_best_backend 保持一致：手动指定的节点也要校验在线。
        # 此前这里直接 return，调用方会拿到一个离线节点并在其上失败，
        # 且与主生成路径的行为不一致（后者抛 503）。
        if _probe_backend_queue(explicit, required_images) is None:
            raise HTTPException(
                status_code=503,
                detail=f"ComfyUI 本地服务未启动或不可达 ({explicit})，请先启动 ComfyUI 或检查节点连接后重试",
            )
        return explicit

    instances = list(COMFYUI_INSTANCES) or ["127.0.0.1:8188"]
    backend_stats = {}
    with ThreadPoolExecutor(max_workers=max(1, len(instances))) as pool:
        futures = {addr: pool.submit(_probe_backend_queue, addr, required_images) for addr in instances}
        for addr, fut in futures.items():
            st = fut.result()
            if st is not None:
                with LOAD_LOCK:
                    local_load = BACKEND_LOCAL_LOAD.get(addr, 0)
                backend_stats[addr] = {
                    "load": max(st["remote_load"], local_load),
                    "has_images": st["has_images"],
                }

    if not backend_stats:
        return instances[0]

    best_backend = next(iter(backend_stats.keys()))
    min_queue_size = float("inf")
    for addr, stats in backend_stats.items():
        load = stats["load"]
        if load < min_queue_size or (load == min_queue_size and stats.get("has_images") and not backend_stats.get(best_backend, {}).get("has_images")):
            min_queue_size = load
            best_backend = addr
    return best_backend

def reserve_best_backend(required_images: List[str] = None, target_backend: str = ""):
    sync_comfy_no_proxy(COMFYUI_INSTANCES)
    explicit = _normalize_target_backend(target_backend)
    if explicit:
        if explicit not in COMFYUI_INSTANCES:
            raise HTTPException(status_code=400, detail=f"未注册的 ComfyUI 节点地址：{explicit}")
        st = _probe_backend_queue(explicit, required_images)
        if st is None:
            raise HTTPException(
                status_code=503,
                detail=f"ComfyUI 本地服务未启动或不可达 ({explicit})，请先启动 ComfyUI 或检查节点连接后重试",
            )
        with LOAD_LOCK:
            BACKEND_LOCAL_LOAD[explicit] = BACKEND_LOCAL_LOAD.get(explicit, 0) + 1
        return explicit

    instances = list(COMFYUI_INSTANCES) or ["127.0.0.1:8188"]
    backend_stats = {}
    with ThreadPoolExecutor(max_workers=max(1, len(instances))) as pool:
        futures = {addr: pool.submit(_probe_backend_queue, addr, required_images) for addr in instances}
        for addr, fut in futures.items():
            st = fut.result()
            if st is not None:
                backend_stats[addr] = st

    with LOAD_LOCK:
        best_backend = instances[0]
        min_load = float("inf")
        if backend_stats:
            best_backend = next(iter(backend_stats.keys()))
            for addr, stats in backend_stats.items():
                load = max(stats["remote_load"], BACKEND_LOCAL_LOAD.get(addr, 0))
                if load < min_load or (load == min_load and stats.get("has_images") and not backend_stats.get(best_backend, {}).get("has_images")):
                    min_load = load
                    best_backend = addr
        BACKEND_LOCAL_LOAD[best_backend] = BACKEND_LOCAL_LOAD.get(best_backend, 0) + 1
        return best_backend

def sync_input_media_to_backend(target_backend: str, required_images: List[str], force_overwrite: bool = False) -> None:
    if not required_images or not target_backend:
        return
    for image_name in required_images:
        safe_name = os.path.basename(str(image_name or "").strip())
        if not safe_name:
            continue
        need_sync = bool(force_overwrite)
        if not need_sync:
            try:
                check_url = f"http://{target_backend}/view?filename={urllib.parse.quote(safe_name)}&type=input"
                resp = comfy_session.get(check_url, stream=True, timeout=MEDIA_PROBE_TIMEOUT)
                resp.close()
                if resp.status_code != 200:
                    need_sync = True
            except Exception:
                need_sync = True

        if not need_sync:
            continue

        image_content = None
        image_type = "image/png"

        # 1. 优先从本机存储目录 (OUTPUT_INPUT_DIR / 资产目录) 查找
        local_candidates = []
        try:
            p_in = output_path_for(safe_name, "input")
            if p_in:
                local_candidates.append(p_in)
        except Exception:
            pass
        p_out_in = os.path.join(OUTPUT_DIR, "input", safe_name)
        if p_out_in not in local_candidates:
            local_candidates.append(p_out_in)
        try:
            p_any = local_media_file_by_basename(safe_name)
            if p_any and p_any not in local_candidates:
                local_candidates.append(p_any)
        except Exception:
            pass
        for cand in local_candidates:
            if cand and os.path.isfile(cand):
                try:
                    with open(cand, "rb") as f:
                        image_content = f.read()
                    image_type = content_type_for_path(cand) or "image/png"
                    break
                except Exception as exc:
                    logger.warning(f"读取本地输入素材失败 ({cand}): {exc}")

        # 2. 若本机磁盘未命中，再从其他在线 ComfyUI 节点拉取
        if not image_content:
            for addr in COMFYUI_INSTANCES:
                if addr == target_backend:
                    continue
                try:
                    src_url = f"http://{addr}/view?filename={urllib.parse.quote(safe_name)}&type=input"
                    r = comfy_session.get(src_url, timeout=15)
                    if r.status_code == 200 and r.content:
                        image_content = r.content
                        image_type = r.headers.get("Content-Type", "image/png")
                        break
                except Exception:
                    continue

        if image_content:
            try:
                files = {"image": (safe_name, image_content, image_type)}
                extra = {"data": {"overwrite": "true"}} if force_overwrite else {}
                comfy_session.post(f"http://{target_backend}/upload/image", files=files, timeout=60, **extra)
            except Exception as e:
                logger.warning(f"Sync upload to {target_backend} failed for {safe_name}: {e}")

# --- DLSS 5 Neural Rendering (ComfyUI-DLSS5-Enhancer) ---
DLSS5_WORKFLOW_SENTINEL = "__dlss5__"
DLSS5_MODE_1X = "1x (DLAA / native)"
DLSS5_MODE_2X = "2x (Performance)"
DLSS5_LONG_CAP = 7680
DLSS5_SHORT_CAP = 4320
DLSS5_VALID_STYLES = ("Default", "Cinematic", "Natural")

def resolve_dlss5_effective_mode(mode: str, width: int, height: int):
    m = str(mode or "2pass").strip().lower()
    if m not in ("dlaa", "2x", "2pass"):
        m = "2pass"
    if m in ("2x", "2pass") and width > 0 and height > 0:
        long_out = max(width, height) * 2
        short_out = min(width, height) * 2
        if long_out > DLSS5_LONG_CAP or short_out > DLSS5_SHORT_CAP:
            return (
                "dlaa",
                f"2x 输出尺寸 {width * 2}x{height * 2} 超出 DLSS5 硬件上限 ({DLSS5_LONG_CAP}x{DLSS5_SHORT_CAP})，已自动降级为 1x DLAA",
            )
    return m, ""

def _dlss5_settings_node(upscaling_mode: str, style: str, structure: float) -> Dict[str, Any]:
    st = style if style in DLSS5_VALID_STYLES else "Default"
    try:
        struct_val = round(max(0.5, min(2.0, float(structure))), 2)
    except (TypeError, ValueError):
        struct_val = 2.0
    return {
        "class_type": "DLSS5Settings",
        "inputs": {
            "upscaling_mode": upscaling_mode,
            "nr_preset": "Default",
            "nr_style": st,
            "nr_intensity": 1.0,
            "local_tone_strength": 1.0,
            "local_structure_strength": struct_val,
            "skin_structure_strength": 2.0,
            "automatic_mask": True,
            "dlss_model_preset": "M",
            "motion": "auto",
            "scene_change_threshold": 0.24,
            "warmup_frames": 0,
            "runtime_dir": "",
        },
    }

def build_dlss5_workflow(
    src_name: str,
    mode: str = "2pass",
    style: str = "Default",
    structure: float = 2.0,
    prefix: str = "dlss5",
) -> Dict[str, Any]:
    m = str(mode or "2pass").strip().lower()
    if m not in ("dlaa", "2x", "2pass"):
        m = "2pass"
    nodes: Dict[str, Any] = {
        "1": {"class_type": "LoadImage", "inputs": {"image": src_name}},
    }
    seq = [1]

    def _add(node_obj: Dict[str, Any]) -> str:
        seq[0] += 1
        nid = str(seq[0])
        nodes[nid] = node_obj
        return nid

    def _enhance(img_nid: str, up_mode: str) -> str:
        s_nid = _add(_dlss5_settings_node(up_mode, style, structure))
        return _add({
            "class_type": "DLSS5EnhanceImages",
            "inputs": {
                "images": [img_nid, 0],
                "settings": [s_nid, 0],
                "verify_neural_rendering": True,
            },
        })

    cur = "1"
    if m in ("dlaa", "2pass"):
        cur = _enhance(cur, DLSS5_MODE_1X)
    if m in ("2x", "2pass"):
        cur = _enhance(cur, DLSS5_MODE_2X)
    _add({
        "class_type": "SaveImage",
        "inputs": {
            "images": [cur, 0],
            "filename_prefix": f"{prefix}_{m}",
        },
    })
    return nodes

def _prepare_dlss5_input_image_meta(image_name: str):
    safe_name = os.path.basename(str(image_name or "").strip())
    if not safe_name:
        return 0, 0, False
    candidates = []
    try:
        p_in = output_path_for(safe_name, "input")
        if p_in:
            candidates.append(p_in)
    except Exception:
        pass
    p_out_in = os.path.join(OUTPUT_DIR, "input", safe_name)
    if p_out_in not in candidates:
        candidates.append(p_out_in)
    try:
        p_any = local_media_file_by_basename(safe_name)
        if p_any and p_any not in candidates:
            candidates.append(p_any)
    except Exception:
        pass
    src_path = next((p for p in candidates if p and os.path.isfile(p)), None)
    if not src_path:
        return 0, 0, False
    try:
        with Image.open(src_path) as img:
            w, h = img.size
            needs_rgb = img.mode != "RGB"
            rgb_img = img.convert("RGB") if needs_rgb else None
        if needs_rgb and rgb_img is not None:
            for dst_path in ({src_path, candidates[0]} if candidates else {src_path}):
                os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                ext = os.path.splitext(dst_path)[1].lower()
                fmt = "JPEG" if ext in (".jpg", ".jpeg") else ("WEBP" if ext == ".webp" else "PNG")
                rgb_img.save(dst_path, format=fmt)
            return w, h, True
        return w, h, False
    except Exception as exc:
        logger.warning(f"DLSS5 预处理输入图像失败 ({src_path}): {exc}")
        return 0, 0, False

def prepare_dlss5_input_image(image_name: str):
    w, h, _ = _prepare_dlss5_input_image_meta(image_name)
    return w, h

# --- 辅助工具 ---

def download_image(comfy_address, comfy_url_path, prefix="studio_"):
    if not is_valid_comfy_address(comfy_address):
        _server_logger.warning(f"Invalid ComfyUI address: {comfy_address}")
        return ""
    filename = f"{prefix}{uuid.uuid4().hex[:10]}.png"
    local_path = output_path_for(filename, "output")
    full_url = f"http://{comfy_address}{comfy_url_path}"
    try:
        with urllib.request.urlopen(full_url, timeout=COMFYUI_DOWNLOAD_TIMEOUT) as response, open(local_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return output_url_for(filename, "output")
    except Exception as e:
        _server_logger.warning(f"下载图片失败 ({full_url}): {e}")
        if comfy_url_path.startswith("/view"):
            return comfy_url_path.replace("/view", "/api/view", 1)
        return full_url

def comfy_output_extension(item):
    filename = str((item or {}).get("filename") or "")
    ext = os.path.splitext(filename)[1].lower()
    if ext in {
        ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
        ".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv",
        ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac",
        ".txt", ".json", ".csv", ".srt", ".vtt", ".md",
    }:
        return ext
    fmt = str((item or {}).get("format") or "").lower()
    if "mpeg" in fmt or "mp3" in fmt:
        return ".mp3"
    if "wav" in fmt or "wave" in fmt:
        return ".wav"
    if "ogg" in fmt:
        return ".ogg"
    if "flac" in fmt:
        return ".flac"
    if "text" in fmt or "plain" in fmt:
        return ".txt"
    if "json" in fmt:
        return ".json"
    if "webm" in fmt:
        return ".webm"
    if "quicktime" in fmt or "mov" in fmt:
        return ".mov"
    if "mp4" in fmt or "h264" in fmt or "video" in fmt:
        return ".mp4"
    return ext or ".bin"

def is_video_output_item(item):
    ext = comfy_output_extension(item)
    fmt = str((item or {}).get("format") or "").lower()
    return ext in {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"} or "video" in fmt

def comfy_output_kind(item):
    ext = comfy_output_extension(item)
    fmt = str((item or {}).get("format") or "").lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"} or "image" in fmt:
        return "image"
    if ext in {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"} or "video" in fmt:
        return "video"
    if ext in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"} or "audio" in fmt or "sound" in fmt:
        return "audio"
    if ext in {".txt", ".json", ".csv", ".srt", ".vtt", ".md"} or "text" in fmt or "json" in fmt:
        return "text"
    return "file"

def download_comfy_output(comfy_address, item, prefix="studio_"):
    if not is_valid_comfy_address(comfy_address):
        _server_logger.warning(f"Invalid ComfyUI address: {comfy_address}")
        return ""
    ext = comfy_output_extension(item)
    filename = f"{prefix}{uuid.uuid4().hex[:10]}{ext}"
    local_path = output_path_for(filename, "output")
    subfolder = urllib.parse.quote(str(item.get("subfolder") or ""))
    file_type = urllib.parse.quote(str(item.get("type") or "output"))
    comfy_url_path = f"/view?filename={urllib.parse.quote(str(item['filename']))}&subfolder={subfolder}&type={file_type}"
    full_url = f"http://{comfy_address}{comfy_url_path}"
    try:
        with urllib.request.urlopen(full_url, timeout=COMFYUI_DOWNLOAD_TIMEOUT) as response, open(local_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return output_url_for(filename, "output")
    except Exception as e:
        _server_logger.warning(f"下载 ComfyUI 输出失败 ({full_url}): {e}")
        if comfy_url_path.startswith("/view"):
            return comfy_url_path.replace("/view", "/api/view", 1)
        return full_url

def save_comfy_text_output(value, prefix="studio_", name=""):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    stem = sanitize_export_filename(name or "comfy_text.txt", "comfy_text.txt")
    _, ext = os.path.splitext(stem)
    if ext.lower() not in {".txt", ".json", ".csv", ".srt", ".vtt", ".md"}:
        stem += ".txt"
    filename = f"{prefix}{uuid.uuid4().hex[:10]}_{stem}"
    path = output_path_for(filename, "output")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return output_url_for(filename, "output")

def comfy_text_values_from_output(node_output):
    values = []
    text_keys = ("text", "texts", "prompt", "prompts", "string", "strings", "caption", "captions")
    for key in text_keys:
        if key not in node_output:
            continue
        value = node_output.get(key)
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, dict):
                text = item.get("text") or item.get("prompt") or item.get("caption") or item.get("value")
                name = item.get("filename") or item.get("name") or f"{key}.txt"
            else:
                text = item
                name = f"{key}.txt"
            if text is None:
                continue
            text = str(text)
            if text.strip():
                values.append((text, name))
    return values

def collect_comfy_file_items(node_output):
    items = []
    for key, value in (node_output or {}).items():
        if key in {"text", "texts", "prompt", "prompts", "string", "strings", "caption", "captions"}:
            continue
        candidates = value if isinstance(value, list) else [value]
        for item in candidates:
            if isinstance(item, dict) and item.get("filename"):
                items.append((key, item))
    return items

# 纯预览/对比类节点：其输出只用于界面展示（PreviewImage、rgthree 的 Image Comparer 等），
# 工作流里通常还有 SaveImage 产出真正结果，故有正式产出时应丢弃这些冗余预览/对比图。
COMFY_PREVIEW_CLASS_HINTS = ("previewimage", "comparer", "imagecompare", "image compare")
# show/utility 类调试文本节点：ShowText、各种 *Anything、CR Text、MathExpression、note 等，
# 它们的 ui 文本基本是调试信息，不应混进最终结果。
COMFY_DEBUG_TEXT_CLASS_HINTS = (
    "showtext", "show text", "showanything", "show any", "preview any", "previewany",
    "displaytext", "display text", "display any", "anything everywhere", "convertanything",
    "easy show", "note", "mathexpression", "cr text", "text multiline", "string function",
    "debug",
)

def comfy_class_is_preview(class_type):
    ct = str(class_type or "").lower()
    return bool(ct) and any(h in ct for h in COMFY_PREVIEW_CLASS_HINTS)

def comfy_class_is_debug_text(class_type):
    ct = str(class_type or "").lower()
    return bool(ct) and any(h in ct for h in COMFY_DEBUG_TEXT_CLASS_HINTS)

def get_comfy_history(comfy_address, prompt_id):
    if not is_valid_comfy_address(comfy_address):
        _server_logger.warning(f"Invalid ComfyUI address: {comfy_address}")
        return {}
    if not prompt_id:
        return {}
    history_url = f"http://{comfy_address}/history/{urllib.parse.quote(str(prompt_id), safe='')}"
    try:
        with urllib.request.urlopen(history_url, timeout=10) as response:
            return json.loads(response.read())
    except Exception as exc:
        _server_logger.warning(f"ComfyUI history 查询失败 prompt_id={prompt_id}: {exc}")
        return {}

# --- Canvas Comfy Tasks ---
async def run_canvas_comfy_task(task_id: str, payload: GenerateRequest):
    start_t = time.time()
    with CANVAS_TASK_LOCK:
        if task_id in CANVAS_TASKS:
            CANVAS_TASKS[task_id]["status"] = "running"
            CANVAS_TASKS[task_id]["updated_at"] = time.time()
    try:
        result = await asyncio.to_thread(generate, payload)
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(str(result.get("error") or "ComfyUI 生成失败"))
        duration_ms = int((time.time() - start_t) * 1000)
        with CANVAS_TASK_LOCK:
            CANVAS_TASKS[task_id].update({
                "status": "succeeded",
                "result": result,
                "error": "",
                "updated_at": time.time(),
            })
        try:
            outs = []
            if isinstance(result, dict) and result.get("images"):
                outs = [img.get("url", "") if isinstance(img, dict) else str(img) for img in result["images"]]
            record_task_event("comfyui", "workflow", "success", task_id=task_id, duration_ms=duration_ms, outputs=outs, kind="comfyui")
        except Exception:
            pass
    except Exception as exc:
        duration_ms = int((time.time() - start_t) * 1000)
        detail = getattr(exc, "detail", None) or str(exc)
        status_code = getattr(exc, "status_code", 500)
        with CANVAS_TASK_LOCK:
            CANVAS_TASKS[task_id].update({
                "status": "failed",
                "error": str(detail),
                "status_code": status_code,
                "updated_at": time.time(),
            })
        try:
            record_task_event("comfyui", "workflow", "failed", task_id=task_id, duration_ms=duration_ms, error=str(detail), kind="comfyui")
        except Exception:
            pass

@router.post("/api/canvas-comfy-tasks")
async def create_canvas_comfy_task(payload: GenerateRequest):
    task_id = f"canvas_comfy_{uuid.uuid4().hex}"
    with CANVAS_TASK_LOCK:
        _prune_comfy_canvas_tasks()
        CANVAS_TASKS[task_id] = {
            "id": task_id,
            "type": "comfy",
            "status": "queued",
            "created_at": time.time(),
            "updated_at": time.time(),
            "result": None,
            "error": "",
            "workflow_json": payload.workflow_json,
        }
    asyncio.create_task(run_canvas_comfy_task(task_id, payload))
    return {"task_id": task_id, "status": "queued"}

@router.get("/api/canvas-comfy-tasks/{task_id}")
async def get_canvas_comfy_task(task_id: str):
    with CANVAS_TASK_LOCK:
        task = dict(CANVAS_TASKS.get(task_id) or {})
    if not task:
        raise HTTPException(status_code=404, detail="ComfyUI 任务不存在，可能服务已重启或任务已过期")
    return task

# --- Generate ---
@router.post("/api/generate")
def generate(req: GenerateRequest):
    workflow_path = None
    is_dlss5 = (
        req.type == "dlss5"
        or str(req.workflow_json or "").strip() in (DLSS5_WORKFLOW_SENTINEL, "dlss5", "DLSS5.json")
    )
    if is_dlss5:
        workflow = {}
    elif isinstance(req.workflow_json, dict):
        workflow = dict(req.workflow_json)
    else:
        wf_name = os.path.normpath(str(req.workflow_json or "")).replace("\\", "/")
        if ".." in wf_name or wf_name.startswith("/"):
            raise HTTPException(status_code=400, detail="非法的工作流文件名")
        workflow_path = os.path.normpath(os.path.join(WORKFLOW_DIR, wf_name))
        try:
            if os.path.commonpath([os.path.realpath(WORKFLOW_DIR), os.path.realpath(workflow_path)]) != os.path.realpath(WORKFLOW_DIR):
                raise HTTPException(status_code=400, detail="检测到工作流路径穿越")
        except ValueError:
            raise HTTPException(status_code=400, detail="检测到工作流路径穿越")
        if not os.path.exists(workflow_path) and req.workflow_json == "Z-Image.json":
            workflow_path = WORKFLOW_PATH
        if not os.path.exists(workflow_path) or not os.path.isfile(workflow_path):
            raise HTTPException(status_code=404, detail=f"工作流文件未找到: {req.workflow_json}")

    global NEXT_TASK_ID
    current_task = None
    target_backend = None
    with QUEUE_LOCK:
        task_id = NEXT_TASK_ID
        NEXT_TASK_ID += 1
        current_task = {"task_id": task_id, "client_id": req.client_id}
        QUEUE.append(current_task)

    try:
        required_images = collect_required_comfy_media(req.params)
        dlss_effective_mode = ""
        dlss_downgrade_reason = ""
        force_overwrite_sync = False

        if is_dlss5:
            dlss_cfg = (req.params or {}).get("1") or (req.params or {}).get("dlss5") or {}
            if not isinstance(dlss_cfg, dict):
                dlss_cfg = {}
            src_img = os.path.basename(str(dlss_cfg.get("image") or (required_images[0] if required_images else "")).strip())
            if not src_img:
                raise HTTPException(status_code=400, detail="DLSS5 增强需要提供输入图像")
            if src_img not in required_images:
                required_images.insert(0, src_img)
            img_w, img_h, force_overwrite_sync = _prepare_dlss5_input_image_meta(src_img)
            dlss_effective_mode, dlss_downgrade_reason = resolve_dlss5_effective_mode(
                str(dlss_cfg.get("dlss_mode") or "2pass"), img_w, img_h
            )
            workflow = build_dlss5_workflow(
                src_name=src_img,
                mode=dlss_effective_mode,
                style=str(dlss_cfg.get("dlss_style") or "Default"),
                structure=dlss_cfg.get("dlss_structure", 2.0),
                prefix=f"dlss5_{int(time.time())}",
            )

        try:
            target_backend = reserve_best_backend(required_images, req.target_backend)
        except TypeError:
            target_backend = reserve_best_backend(required_images)

        sync_input_media_to_backend(target_backend, required_images, force_overwrite=force_overwrite_sync)

        if workflow_path:
            with open(workflow_path, 'r', encoding='utf-8') as f:
                workflow = json.load(f)

        seed = random.randint(1, 4294967295)

        if not is_dlss5:
            if "23" in workflow and req.prompt:
                workflow["23"]["inputs"]["text"] = req.prompt
            if "144" in workflow:
                workflow["144"]["inputs"]["width"] = req.width
                workflow["144"]["inputs"]["height"] = req.height
            if "22" in workflow:
                workflow["22"]["inputs"]["seed"] = seed
            if "158" in workflow:
                workflow["158"]["inputs"]["noise_seed"] = seed
            for node_id in ["146", "181"]:
                if node_id in workflow and "inputs" in workflow[node_id] and "seed" in workflow[node_id]["inputs"]:
                    workflow[node_id]["inputs"]["seed"] = seed
            if "184" in workflow and "inputs" in workflow["184"] and "seed" in workflow["184"]["inputs"]:
                workflow["184"]["inputs"]["seed"] = seed
            if "172" in workflow and "inputs" in workflow["172"] and "seed" in workflow["172"]["inputs"]:
                workflow["172"]["inputs"]["seed"] = seed
            if "14" in workflow and "inputs" in workflow["14"] and "seed" in workflow["14"]["inputs"]:
                workflow["14"]["inputs"]["seed"] = seed

            for node_id, node_inputs in req.params.items():
                if node_id in workflow:
                    if "inputs" not in workflow[node_id]:
                        workflow[node_id]["inputs"] = {}
                    for input_name, value in node_inputs.items():
                        if value is None:
                            workflow[node_id]["inputs"].pop(input_name, None)
                            continue
                        workflow[node_id]["inputs"][input_name] = value
                elif isinstance(node_inputs, dict) and node_inputs.get("class_type") and isinstance(node_inputs.get("inputs"), dict):
                    workflow[str(node_id)] = {
                        "class_type": str(node_inputs.get("class_type")),
                        "inputs": node_inputs.get("inputs") or {},
                        "_meta": node_inputs.get("_meta") if isinstance(node_inputs.get("_meta"), dict) else {"title": str(node_inputs.get("class_type"))},
                    }

        p = {"prompt": workflow, "client_id": CLIENT_ID}
        try:
            resp = comfy_session.post(f"http://{target_backend}/prompt", json=p, timeout=60)
            if resp.status_code != 200:
                raise Exception(comfy_prompt_error_message(resp.status_code, resp.text))
            prompt_id = resp.json()['prompt_id']
        except (requests.exceptions.HTTPError, urllib.error.HTTPError) as e:
            error_body = getattr(getattr(e, "response", None), "text", None) or (e.read().decode('utf-8') if hasattr(e, "read") else str(e))
            code = getattr(getattr(e, "response", None), "status_code", None) or getattr(e, "code", 500)
            raise Exception(comfy_prompt_error_message(code, error_body))

        history_data = None
        for i in range(COMFYUI_HISTORY_TIMEOUT):
            try:
                res = get_comfy_history(target_backend, prompt_id)
                if prompt_id in res:
                    history_data = res[prompt_id]
                    break
            except Exception:
                pass
            time.sleep(1)

        if not history_data:
            raise Exception("ComfyUI 渲染超时")

        status_obj = history_data.get("status") if isinstance(history_data, dict) else {}
        if isinstance(status_obj, dict) and status_obj.get("status_str") == "error":
            err_detail = ""
            for m in status_obj.get("messages") or []:
                if isinstance(m, (list, tuple)) and len(m) >= 2 and m[0] == "execution_error" and isinstance(m[1], dict):
                    nt = m[1].get("node_type") or m[1].get("node_id") or ""
                    em = str(m[1].get("exception_message") or "").strip()
                    err_detail = f"{nt}: {em}" if nt else em
                    break
            raise Exception(f"ComfyUI 节点执行失败：{err_detail or status_obj}")

        local_images = []
        local_videos = []
        local_audios = []
        local_texts = []
        local_files = []
        local_items = []
        local_urls = []
        current_timestamp = time.time()
        if 'outputs' in history_data:
            # 先把所有节点的输出收集为候选（带上 class_type），再决定下载哪些，
            # 避免把冗余的预览/对比图、调试文本一起下载进结果（后端层过滤，历史记录也更干净）。
            workflow_nodes = workflow if isinstance(workflow, dict) else {}
            def _class_type_of(nid):
                node_def = workflow_nodes.get(str(nid))
                return str(node_def.get("class_type") or "") if isinstance(node_def, dict) else ""
            file_candidates = []   # (node_id, class_type, output_key, item, kind)
            text_candidates = []   # (node_id, class_type, text, name)
            for node_id in history_data['outputs']:
                node_output = history_data['outputs'][node_id]
                class_type = _class_type_of(node_id)
                for output_key, item in collect_comfy_file_items(node_output):
                    file_candidates.append((node_id, class_type, output_key, item, comfy_output_kind(item)))
                for text, name in comfy_text_values_from_output(node_output):
                    text_candidates.append((node_id, class_type, text, name))

            # 只要存在“非预览节点”产出的图片，就把 PreviewImage/对比节点的图片视为冗余丢弃；
            # 若整个工作流只有预览图（没有 SaveImage 等），则保留预览图作为唯一结果，避免零输出。
            has_primary_image = any(
                kind == "image" and not comfy_class_is_preview(ct)
                for (_nid, ct, _ok, _it, kind) in file_candidates
            )
            prefix = f"{req.type}_{int(current_timestamp)}_"
            for node_id, class_type, output_key, item, kind in file_candidates:
                if kind == "image" and has_primary_image and comfy_class_is_preview(class_type):
                    continue  # 跳过冗余的预览/对比图
                local_path = download_comfy_output(target_backend, item, prefix=prefix)
                if kind == "image" and req.convert_to_jpg:
                    local_path = convert_output_to_jpg(local_path)
                name = os.path.basename(str(item.get("filename") or "")) or os.path.basename(str(local_path).split("?", 1)[0])
                entry = {
                    "url": local_path,
                    "kind": kind,
                    "name": name,
                    "node_id": str(node_id),
                    "output_key": str(output_key),
                    "class_type": class_type,
                }
                if kind == "image":
                    local_images.append(local_path)
                elif kind == "video":
                    local_videos.append(local_path)
                elif kind == "audio":
                    local_audios.append(local_path)
                elif kind == "text":
                    local_texts.append(local_path)
                else:
                    local_files.append(local_path)
                local_items.append(entry)
                local_urls.append(local_path)

            # 默认抑制 show/utility 类节点的调试文本，避免 .txt 噪声混入结果。
            for node_id, class_type, text, name in text_candidates:
                if comfy_class_is_debug_text(class_type):
                    continue
                local_path = save_comfy_text_output(text, prefix=prefix, name=name)
                entry = {
                    "url": local_path,
                    "kind": "text",
                    "name": os.path.basename(str(local_path).split("?", 1)[0]),
                    "node_id": str(node_id),
                    "output_key": "text",
                    "class_type": class_type,
                }
                local_texts.append(local_path)
                local_items.append(entry)
                local_urls.append(local_path)

        result = {
            "prompt": req.prompt if req.prompt else ("DLSS 5 Enhance" if is_dlss5 else "Detail Enhance"),
            "images": local_images,
            "videos": local_videos,
            "audios": local_audios,
            "texts": local_texts,
            "files": local_files,
            "items": local_items,
            "outputs": local_urls,
            "seed": seed,
            "timestamp": current_timestamp,
            "type": req.type,
            "workflow_json": req.workflow_json,
            "task_id": task_id,
            "prompt_id": prompt_id,
            "backend": target_backend,
            "params": req.params
        }
        if is_dlss5:
            result["dlss_effective_mode"] = dlss_effective_mode
            if dlss_downgrade_reason:
                result["dlss_downgrade_reason"] = dlss_downgrade_reason
        save_to_history(result)
        mgr = get_ws_manager()
        loop = get_global_loop()
        if mgr is not None and loop is not None:
            asyncio.run_coroutine_threadsafe(mgr.broadcast_new_image(result), loop)
        return result

    except HTTPException:
        raise
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, urllib.error.URLError) as e:
        raise HTTPException(
            status_code=503,
            detail=f"ComfyUI 本地服务未启动或不可达 ({target_backend or '127.0.0.1:8188'})，请先启动 ComfyUI 后重试: {e}"
        )
    except Exception as e:
        err_msg = str(e).lower()
        if "connection refused" in err_msg or "actively refused" in err_msg or "failed to establish a new connection" in err_msg:
            raise HTTPException(
                status_code=503,
                detail=f"ComfyUI 本地服务未启动或不可达 ({target_backend or '127.0.0.1:8188'})，请先启动 ComfyUI 后重试: {e}"
            )
        _server_logger.exception("ComfyUI 生成失败")
        raise HTTPException(status_code=502, detail=f"ComfyUI 生成失败: {e}") from e
    finally:
        if target_backend:
            with LOAD_LOCK:
                if BACKEND_LOCAL_LOAD.get(target_backend, 0) > 0:
                    BACKEND_LOCAL_LOAD[target_backend] -= 1
        if current_task:
            with QUEUE_LOCK:
                if current_task in QUEUE:
                    QUEUE.remove(current_task)

# --- Workflow Helpers & Routes ---
def workflow_path_from_name(name: str) -> str:
    if not WORKFLOW_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid workflow name")
    path = os.path.abspath(os.path.join(WORKFLOW_DIR, *name.split("/")))
    workflow_root = os.path.abspath(WORKFLOW_DIR)
    if os.path.commonpath([workflow_root, path]) != workflow_root:
        raise HTTPException(status_code=400, detail="Invalid workflow name")
    return path

def workflow_config_path(name: str) -> str:
    return workflow_path_from_name(name).replace(".json", ".config.json")

def is_builtin_workflow(name: str) -> bool:
    return "/" not in name and os.path.basename(name) in BUILTIN_WORKFLOWS

@router.get("/api/comfyui/instances")
def get_comfyui_instances():
    return {"instances": COMFYUI_INSTANCES}

@router.get("/api/comfyui/instances/status")
def get_comfyui_instances_status():
    instances = list(COMFYUI_INSTANCES)
    if not instances:
        return {"instances": [], "nodes": []}
    sync_comfy_no_proxy(instances)
    with ThreadPoolExecutor(max_workers=max(1, len(instances))) as pool:
        nodes = list(pool.map(probe_comfy_node_status, instances))
    return {"instances": instances, "nodes": nodes}

@router.put("/api/comfyui/instances")
def save_comfyui_instances(payload: ComfyInstancesPayload):
    cleaned = []
    for item in payload.instances:
        raw = str(item or "").strip()
        if not raw:
            continue
        if "," in raw or any(c.isspace() for c in raw):
            raise HTTPException(status_code=400, detail=f"地址不能包含逗号或空白字符：{item}")
        s = re.sub(r"^https?://", "", raw, flags=re.IGNORECASE).rstrip("/")
        if not is_valid_comfy_address(s):
            raise HTTPException(status_code=400, detail=f"地址格式不合法：{item}（应为 host:port，例如 127.0.0.1:8188）")
        if ":" not in s:
            raise HTTPException(status_code=400, detail=f"地址缺少端口号：{item}（应为 host:port，例如 127.0.0.1:8188）")
        host, _, port = s.rpartition(":")
        if not host or not port.isdigit() or not (1 <= int(port) <= 65535):
            raise HTTPException(status_code=400, detail=f"地址端口号不合法：{item}（端口应在 1~65535 之间）")
        # 防 SSRF：允许局域网/回环私有IP，但无条件拦截云元数据与保留网段 (如 169.254.169.254)
        try:
            validate_safe_url(f"http://{s}", allow_private=True)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"非法实例地址（禁止访问云元数据/保留网段）：{item}")
        if s in cleaned:
            continue
        cleaned.append(s)
    if not cleaned:
        raise HTTPException(status_code=400, detail="至少保留一个 ComfyUI 后端地址")
    # 写入 env 文件
    try:
        _env_updater({"COMFYUI_INSTANCES": ",".join(cleaned)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入 env 失败：{e}")
    # 原地更新进程中的共享列表，保持跨模块引用一致
    global COMFYUI_ADDRESS, BACKEND_LOCAL_LOAD
    COMFYUI_INSTANCES[:] = cleaned
    COMFYUI_ADDRESS = cleaned[0]
    sync_comfy_no_proxy(cleaned)
    new_load = {addr: 0 for addr in cleaned}
    for addr, n in (BACKEND_LOCAL_LOAD or {}).items():
        if addr in new_load:
            new_load[addr] = n
    BACKEND_LOCAL_LOAD = new_load
    return {"instances": COMFYUI_INSTANCES}

@router.get("/api/workflows")
def list_workflows():
    if not os.path.isdir(WORKFLOW_DIR):
        return {"workflows": []}
    items = []
    for root, dirs, files in os.walk(WORKFLOW_DIR):
        if os.path.abspath(root) == os.path.abspath(WORKFLOW_DIR):
            dirs[:] = [d for d in dirs if d in {CUSTOM_WORKFLOW_FOLDER, LEGACY_CUSTOM_WORKFLOW_FOLDER}]
        for fn in sorted(files):
            if not fn.endswith(".json") or fn.endswith(".config.json"):
                continue
            rel = os.path.relpath(os.path.join(root, fn), WORKFLOW_DIR).replace("\\", "/")
            if is_builtin_workflow(rel):
                continue
            cfg = {}
            cfg_path = workflow_config_path(rel)
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f) or {}
                except Exception:
                    cfg = {}
            items.append({
                "name": rel,
                "title": cfg.get("title") or fn.replace(".json", ""),
                "builtin": False,
                "field_count": len(cfg.get("fields") or []),
            })
    items.sort(key=lambda item: (0 if item["name"].startswith(f"{CUSTOM_WORKFLOW_FOLDER}/") else 1, item["title"]))
    return {"workflows": items}

@router.get("/api/workflows/{name:path}")
def get_workflow(name: str):
    if not WORKFLOW_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid workflow name")
    workflow_path = workflow_path_from_name(name)
    if not os.path.exists(workflow_path):
        raise HTTPException(status_code=404, detail="Workflow not found")
    with open(workflow_path, "r", encoding="utf-8") as f:
        workflow = json.load(f)
    cfg = {"title": name.replace(".json", ""), "fields": []}
    cfg_path = workflow_config_path(name)
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f) or cfg
        except Exception:
            pass
    return {"name": name, "workflow": workflow, "config": cfg, "builtin": is_builtin_workflow(name)}

@router.post("/api/workflows")
def upload_workflow(payload: WorkflowUploadRequest):
    name = os.path.basename(payload.name.strip())
    if not name.endswith(".json"):
        name = name + ".json"
    if not WORKFLOW_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="工作流名称不合法，请使用中文/英文/数字/_-.")
    if not isinstance(payload.workflow, dict) or not payload.workflow:
        raise HTTPException(status_code=400, detail="工作流 JSON 为空")
    # 简单校验：是 API 格式（节点 id 为 key，含 class_type）
    sample = next(iter(payload.workflow.values()), None)
    if not isinstance(sample, dict) or "class_type" not in sample:
        raise HTTPException(status_code=400, detail="不是有效的 ComfyUI API 工作流 JSON（需包含 class_type）")
    custom_dir = os.path.join(WORKFLOW_DIR, CUSTOM_WORKFLOW_FOLDER)
    os.makedirs(custom_dir, exist_ok=True)
    stored_name = f"{CUSTOM_WORKFLOW_FOLDER}/{name}"
    path = workflow_path_from_name(stored_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload.workflow, f, ensure_ascii=False, indent=2)
    return {"name": stored_name}

@router.put("/api/workflows/{name:path}/config")
def save_workflow_config(name: str, payload: WorkflowConfig):
    if not WORKFLOW_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid workflow name")
    workflow_path = workflow_path_from_name(name)
    if not os.path.exists(workflow_path):
        raise HTTPException(status_code=404, detail="Workflow not found")
    cfg_path = workflow_config_path(name)
    cfg_data = dump_pydantic(payload)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg_data, f, ensure_ascii=False, indent=2)
    return {"config": cfg_data}

@router.delete("/api/workflows/{name:path}")
def delete_workflow(name: str):
    if not WORKFLOW_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid workflow name")
    if is_builtin_workflow(name):
        raise HTTPException(status_code=400, detail="内置工作流不可删除")
    workflow_path = workflow_path_from_name(name)
    cfg_path = workflow_config_path(name)
    if not os.path.exists(workflow_path):
        raise HTTPException(status_code=404, detail="Workflow not found")
    os.remove(workflow_path)
    if os.path.exists(cfg_path):
        os.remove(cfg_path)
    return {"ok": True}

@router.post("/api/workflows/{name:path}/run")
def run_workflow(name: str, payload: WorkflowRunRequest):
    if not WORKFLOW_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid workflow name")
    if not os.path.exists(workflow_path_from_name(name)):
        raise HTTPException(status_code=404, detail="Workflow not found")
    # 根据 config 的字段把值映射成 params 节点覆盖
    params: Dict[str, Dict[str, Any]] = {}
    for field in payload.config.fields:
        if not field.node or not field.input:
            continue
        if field.id in payload.fields:
            value = payload.fields[field.id]
            # 类型转换
            if field.type in ("number", "slider"):
                try:
                    value = float(value) if (field.step and field.step < 1) else int(float(value))
                except Exception:
                    pass
            elif field.type == "boolean":
                value = bool(value)
            elif field.type == "dropdown":
                # 下拉值如果看起来是数字（如 "1024" / "2048" / "0.8"），自动转成 int/float
                if isinstance(value, str):
                    s = value.strip()
                    try:
                        if s and ('.' in s or 'e' in s.lower()):
                            value = float(s)
                        elif s and (s.lstrip('-').isdigit()):
                            value = int(s)
                    except (ValueError, TypeError):
                        pass
            params.setdefault(field.node, {})[field.input] = value
    req = GenerateRequest(
        prompt="",
        workflow_json=name,
        params=params,
        type="workflow-test",
        client_id=payload.client_id or str(uuid.uuid4()),
        target_backend=payload.target_backend,
    )
    return generate(req)

# --- ComfyUI Upload Base64 ---
@router.post("/api/comfyui/upload-base64")
async def upload_comfyui_base64(payload: Base64UploadRequest):
    """base64 方式把图片传到 ComfyUI 各后端的 input 目录，返回 comfy 用文件名（供 UXP 做 ComfyUI 图生图）。"""
    raw = (payload.data or "").strip()
    ct = (payload.content_type or "").split(";", 1)[0].strip().lower()
    if raw.startswith("data:"):
        header, _, raw = raw.partition(",")
        if not ct:
            ct = header[5:].split(";", 1)[0].strip().lower()
    try:
        content = base64.b64decode(raw, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="数据无法解码")
    if not content:
        raise HTTPException(status_code=400, detail="内容为空")
    _, ext = _local_upload_kind_ext(payload.name or "", ct or "image/png")
    filename = f"dx_{uuid.uuid4().hex[:12]}{ext or '.png'}"
    local_saved = False
    try:
        local_path = output_path_for(filename, "input")
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(content)
        local_saved = True
    except Exception as exc:
        logger.warning(f"Local input backup failed for {filename}: {exc}")
    comfy_name = None
    for addr in COMFYUI_INSTANCES:
        try:
            resp = await asyncio.to_thread(
                comfy_session.post,
                f"http://{addr}/upload/image",
                files={'image': (filename, content, ct or 'image/png')},
                timeout=30,
            )
            if resp.status_code == 200:
                comfy_name = resp.json().get("name", filename)
        except Exception as exc:
            logger.debug(f"ComfyUI base64 upload skipped for {addr}: {exc}")
    if not comfy_name and not local_saved:
        raise HTTPException(status_code=502, detail="上传到 ComfyUI 失败")
    return {"name": comfy_name or filename}
