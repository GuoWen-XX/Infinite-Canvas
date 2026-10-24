"""Asset Library, Canvas Assets, Storage Files & Media Preview Router for Infinite-Canvas.

Decoupled from monolithic main.py to provide clean, modular, and high-performance
asset library CRUD, canvas asset extraction/indexing, local assets management,
storage files browsing, and multi-tier WebP/PNG thumbnail generation.
"""

import os
import re
import json
import uuid
import time
import shutil
import hashlib
import logging
import zipfile
import tempfile
import asyncio
import subprocess
import urllib.parse
from io import BytesIO
from threading import Lock, RLock
from typing import Dict, Any, List, Optional, Tuple, Callable, Set

import requests
import httpx
from PIL import Image, ImageOps
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from core.security import is_safe_remote_url, safe_download_bytes
from core.media import content_type_for_path, output_file_from_url, set_storage_file_resolver
from routers.canvas import (
    CANVAS_DIR,
    CANVAS_LOCK,
    canvas_record,
    cleanup_expired_canvas_trash,
)

logger = logging.getLogger("infinite_canvas.assets")

router = APIRouter(tags=["assets"])

# ===== 目录与路径常量 =====
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
OUTPUT_INPUT_DIR = os.path.join(ASSETS_DIR, "input")
OUTPUT_OUTPUT_DIR = os.path.join(ASSETS_DIR, "output")
ASSET_LIBRARY_DIR = os.path.join(ASSETS_DIR, "library")
LOCAL_UPLOAD_DIR = os.path.join(ASSETS_DIR, "uploads")
MEDIA_PREVIEW_DIR = os.path.join(DATA_DIR, "media_previews")
ASSET_LIBRARY_PATH = os.path.join(DATA_DIR, "asset_library.json")
STORAGE_SETTINGS_FILE = os.path.join(DATA_DIR, "storage_settings.json")
SHARED_FOLDERS_FILE = os.path.join(DATA_DIR, "shared_folders.json")
ASSET_CLASSIFICATION_PROMPT_FILE = os.path.join(DATA_DIR, "asset_classification_prompt.txt")
TASK_HISTORY_FILE = os.path.join(DATA_DIR, "task_history.jsonl")

_task_history_meta_cache: Dict[str, Any] = {"mtime": 0.0, "meta": {}}

def get_task_history_meta_index() -> Dict[str, Tuple[str, str, str]]:
    global _task_history_meta_cache
    if not os.path.exists(TASK_HISTORY_FILE):
        return {}
    try:
        mtime = os.path.getmtime(TASK_HISTORY_FILE)
        if mtime == _task_history_meta_cache["mtime"]:
            return _task_history_meta_cache["meta"]
        mapping: Dict[str, Tuple[str, str, str]] = {}
        with open(TASK_HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    p = str(row.get("provider") or "").strip()
                    m = str(row.get("model") or "").strip()
                    prompt = str(row.get("prompt") or row.get("params", {}).get("prompt") or row.get("request", {}).get("prompt") or "").strip()
                    if p or m:
                        val = (p, m, prompt)
                        for out in row.get("outputs", []):
                            if out:
                                out_str = str(out).strip()
                                mapping[out_str] = val
                                fname = os.path.basename(out_str)
                                if fname:
                                    mapping[fname] = val
                except Exception:
                    continue
        _task_history_meta_cache = {"mtime": mtime, "meta": mapping}
        return mapping
    except Exception as exc:
        logger.warning(f"Failed to read task history for asset index: {exc}")
        return _task_history_meta_cache.get("meta", {})


def enrich_asset_item_generation_meta(item: Dict[str, Any], task_history_meta: Optional[Dict[str, Any]] = None) -> None:
    if not isinstance(item, dict):
        return
    if task_history_meta is None:
        task_history_meta = get_task_history_meta_index()
    url = str(item.get("url") or "").strip()
    fname = os.path.basename(url)
    th = task_history_meta.get(url) or (task_history_meta.get(fname) if fname else None)
    if th:
        if not item.get("provider_id") and th[0]:
            item["provider_id"] = th[0]
        if not item.get("model") and th[1]:
            item["model"] = th[1]
        if not item.get("prompt") and len(th) > 2 and th[2]:
            item["prompt"] = th[2]


DEFAULT_STORAGE_DIRS = {
    "upload": OUTPUT_INPUT_DIR,
    "generated": OUTPUT_OUTPUT_DIR,
    "local": LOCAL_UPLOAD_DIR,
}
STORAGE_DIRS = dict(DEFAULT_STORAGE_DIRS)

STORAGE_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"}
SHARED_MEDIA_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".mp4", ".webm", ".mov", ".m4v", ".mkv",
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac",
}
SHARED_SCAN_MAX_ENTRIES = 8000
AVATAR_SUPPORTED_PLATFORMS = ("apimart", "volcengine")
AVATAR_LEGACY_FLAT_FIELDS = (
    "platform", "provider_id", "project_name", "avatar_task_id",
    "avatar_status", "avatar_detail", "asset_uri", "asset_id", "registered_at"
)

ASSET_CLASSIFICATION_DIMENSION_NAMES = {
    "environment": "环境",
    "scene": "场景",
    "space": "空间",
    "subject": "主体",
    "model": "模特",
    "people": "人物",
    "style": "风格",
    "lighting": "光影",
    "color": "色彩",
    "composition": "构图",
    "mood": "氛围",
    "use_case": "用途",
    "objects": "物体",
    "materials": "材质",
    "quality": "质量",
}

ASSET_CLASSIFICATION_PROMPT = """请识别这张图片，输出严格 JSON，不要 Markdown，不要解释。
目标是给素材库做非常全面的筛选分类。所有字段都用中文短标签数组，尽量具体但不要虚构。
JSON 结构：
{
  "summary": "一句话描述",
  "categories": {
    "environment": ["室内/室外/自然/城市/棚拍/商业空间等环境大类"],
    "scene": ["室内/室外/棚拍/街景/自然/商业空间等"],
    "space": ["卧室/餐厅/客厅/厨房/浴室/办公室/店铺/展厅/户外道路等"],
    "subject": ["人物/模特/产品/家具/建筑/食物/动物/车辆/植物等"],
    "model": ["无人/单人模特/多人模特/男性模特/女性模特/儿童模特/半身模特/全身模特/手部模特等"],
    "people": ["无人/单人/多人/男性/女性/儿童/半身/全身/手部特写等"],
    "style": ["写实/摄影/插画/3D/极简/奢华/复古/现代/电商/电影感等"],
    "lighting": ["自然光/硬光/柔光/逆光/侧光/夜景/暖光/冷光/高对比/低对比等"],
    "color": ["白色/黑色/暖色/冷色/高饱和/低饱和/莫兰迪/金属色等"],
    "composition": ["近景/中景/远景/俯拍/仰拍/正面/侧面/居中/留白/对称/特写等"],
    "mood": ["温馨/高级/清爽/科技/自然/浪漫/神秘/活力/安静等"],
    "use_case": ["广告/电商主图/海报/社媒/样机/参考图/背景/角色参考/空间参考等"],
    "objects": ["画面中重要物体"],
    "materials": ["木材/金属/玻璃/布料/皮革/石材/陶瓷等"],
    "quality": ["高清/模糊/低清/噪点/水印/截图/透明背景等"]
  },
  "tags": ["综合关键词，20个以内"]
}
要求：只返回可解析 JSON；每个数组最多 8 项；如果不确定就省略该标签。"""

# ===== 线程锁与基础目录确保 =====
ASSET_LIBRARY_LOCK = RLock()
STORAGE_LOCK = RLock()
SHARED_FOLDERS_LOCK = RLock()

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(OUTPUT_INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_OUTPUT_DIR, exist_ok=True)
os.makedirs(ASSET_LIBRARY_DIR, exist_ok=True)
os.makedirs(LOCAL_UPLOAD_DIR, exist_ok=True)
os.makedirs(MEDIA_PREVIEW_DIR, exist_ok=True)


# ===== 依赖注入钩子 =====
_ws_manager = None
_loop = None
_image_captioner = None
_image_classifier = None
_avatar_register = None
_avatar_check = None
_runninghub_url_rewriter = None

def set_ws_manager(mgr, loop=None):
    """注入 WebSocket 管理器与主事件循环。"""
    global _ws_manager, _loop
    _ws_manager = mgr
    if loop is not None:
        _loop = loop

def set_image_captioner(fn):
    """注入图片反推描述函数 (caption_image_with_provider)。"""
    global _image_captioner
    _image_captioner = fn

def set_image_classifier(fn):
    """注入图片智能分类函数 (classify_image_with_provider)。"""
    global _image_classifier
    _image_classifier = fn

def set_avatar_handlers(register_fn, check_fn):
    """注入数字人/真人认证提交与状态检测函数。"""
    global _avatar_register, _avatar_check
    _avatar_register = register_fn
    _avatar_check = check_fn

def set_runninghub_url_rewriter(fn):
    """注入 RunningHub URL 重写函数。"""
    global _runninghub_url_rewriter
    _runninghub_url_rewriter = fn


# ===== 通用辅助函数 =====
def now_ms() -> int:
    return int(time.time() * 1000)

def dump_pydantic(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return obj

def origin_from_url(value: str) -> str:
    parsed = urllib.parse.urlparse(str(value or ""))
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".lower()

def ensure_same_origin_request(request: Request):
    host = str(request.headers.get("host") or "").lower()
    expected = f"{request.url.scheme}://{host}".lower() if host else ""
    origin = origin_from_url(request.headers.get("origin", ""))
    referer = origin_from_url(request.headers.get("referer", ""))
    actual = origin or referer
    if expected and actual != expected:
        raise HTTPException(status_code=403, detail="只允许从当前页面导入本地图片")

def atomic_save_json(path: str, data: Any, indent: int = 2):
    """使用临时文件 + 原子替换安全落盘，杜绝文件损坏与半写。"""
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, path)

def _broadcast_asset_library_updated(updated_at: int):
    if _ws_manager and hasattr(_ws_manager, "broadcast_asset_library_updated"):
        if _loop and _loop.is_running():
            asyncio.run_coroutine_threadsafe(_ws_manager.broadcast_asset_library_updated(updated_at), _loop)
        else:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_ws_manager.broadcast_asset_library_updated(updated_at))
            except RuntimeError:
                pass


# ===== Pydantic 数据传输模型 =====
class CanvasAssetCheckRequest(BaseModel):
    urls: List[str] = []

class CanvasAssetDownloadRequest(BaseModel):
    urls: List[str] = []
    items: List[Dict[str, Any]] = []
    filename: str = "canvas-output-images.zip"

class CanvasWorkflowExportRequest(BaseModel):
    nodes: List[Dict[str, Any]] = []
    connections: List[Dict[str, Any]] = []
    filename: str = "canvas-workflow.zip"
    include_resources: bool = True
    library_id: str = ""
    category_id: str = ""
    name: str = ""

class SmartCanvasGroupExportItem(BaseModel):
    kind: str = ""
    url: str = ""
    text: str = ""
    name: str = ""

class SmartCanvasGroupExportRequest(BaseModel):
    folder: str = ""
    group_name: str = "group"
    items: List[SmartCanvasGroupExportItem] = []

class AssetLibraryCategoryRequest(BaseModel):
    name: str = "新文件夹"
    type: str = "image"
    library_id: str = ""

class AssetLibraryRequest(BaseModel):
    name: str = "资产库"

class AssetLibraryAddRequest(BaseModel):
    category_id: str = ""
    url: str = ""
    name: str = ""
    library_id: str = ""

class AssetLibraryBatchAddRequest(BaseModel):
    category_id: str = ""
    library_id: str = ""
    items: List[AssetLibraryAddRequest] = []

class AssetLibraryRenameRequest(BaseModel):
    name: str = ""
    library_id: str = ""

class AssetLibraryBatchDeleteRequest(BaseModel):
    ids: List[str] = []
    library_id: str = ""

class AssetLibraryBatchMoveRequest(BaseModel):
    ids: List[str] = []
    library_id: str = ""
    target_library_id: str = ""
    target_category_id: str = ""

class AssetLibraryBatchCropRequest(BaseModel):
    ids: List[str] = []
    library_id: str = ""
    target_library_id: str = ""
    target_category_id: str = ""
    mode: str = "square"

class AssetAvatarRegisterRequest(BaseModel):
    library_id: str = ""
    provider_id: str = ""
    project_name: str = "default"
    group_name: str = ""

class AssetLibraryClassifyRequest(BaseModel):
    library_id: str = ""
    ids: List[str] = []
    provider: str = "comfly"
    model: str = ""
    ms_model: str = ""
    prompt: str = ""

class LocalAssetFolderRequest(BaseModel):
    parent: str = ""
    path: str = ""
    name: str = ""

class LocalAssetRenameRequest(BaseModel):
    path: str = ""
    name: str = ""

class LocalAssetCaptionRequest(BaseModel):
    names: List[str] = []
    provider: str = "comfly"
    model: str = ""
    ms_model: str = ""
    prompt: str = "描述图片"

class LocalAssetCaptionSaveRequest(BaseModel):
    name: str = ""
    caption: str = ""

class LocalAssetClassifyRequest(BaseModel):
    names: List[str] = []
    provider: str = "comfly"
    model: str = ""
    ms_model: str = ""
    prompt: str = ""

class LocalAssetUrlImportItem(BaseModel):
    url: str = ""
    name: str = ""
    data: str = ""          # base64 / dataURL
    content_type: str = ""

class LocalAssetUrlImportRequest(BaseModel):
    items: List[LocalAssetUrlImportItem] = []
    folder: str = ""
    classify: bool = False
    provider: str = "comfly"
    model: str = ""
    ms_model: str = ""
    prompt: str = ""

class SharedFolderRegister(BaseModel):
    path: str = ""
    name: str = ""

class SharedFolderImport(BaseModel):
    library_id: str = ""
    category_id: str = ""
    folder_id: str = ""
    paths: List[str] = []


# ===== 存储设置与基础文件定位辅助 =====
def sanitize_asset_name(name: str, fallback: str = "asset") -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", str(name or fallback)).strip()
    return name[:120] or fallback

def sanitize_export_filename(name: str, fallback: str) -> str:
    base = os.path.basename(str(name or "").strip()) or fallback
    base = re.sub(r'[\\/:*?"<>|]+', "_", base)
    return base or fallback

def image_has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA"):
        return True
    if img.mode == "P":
        return "transparency" in img.info
    return False

def _storage_abs_path(value, fallback):
    text = str(value or "").strip()
    if not text:
        return os.path.abspath(fallback)
    text = os.path.expanduser(os.path.expandvars(text))
    if not os.path.isabs(text):
        text = os.path.join(BASE_DIR, text)
    resolved = os.path.abspath(text)
    base = os.path.abspath(BASE_DIR)
    try:
        if os.path.commonpath([resolved, base]) != base:
            raise HTTPException(status_code=400, detail="存储目录必须位于项目目录内")
    except ValueError:
        raise HTTPException(status_code=400, detail="存储目录必须位于项目目录内")
    return resolved

def load_storage_settings() -> Dict[str, Any]:
    raw = {}
    try:
        if os.path.exists(STORAGE_SETTINGS_FILE):
            with open(STORAGE_SETTINGS_FILE, "r", encoding="utf-8-sig") as f:
                raw = json.load(f) if f else {}
    except Exception as exc:
        logger.debug(f"加载存储目录设置失败: {exc}")
        raw = {}
    dirs = {}
    for key, fallback in DEFAULT_STORAGE_DIRS.items():
        dirs[key] = _storage_abs_path((raw or {}).get(key), fallback)
    return {"dirs": dirs}

def save_storage_settings(payload: Dict[str, str]) -> Dict[str, Any]:
    with STORAGE_LOCK:
        dirs = {}
        for key, fallback in DEFAULT_STORAGE_DIRS.items():
            dirs[key] = _storage_abs_path((payload or {}).get(key), fallback)
        for path in dirs.values():
            os.makedirs(path, exist_ok=True)
        os.makedirs(DATA_DIR, exist_ok=True)
        atomic_save_json(STORAGE_SETTINGS_FILE, dirs)
        apply_storage_settings(dirs)
        return {"dirs": dirs}

def apply_storage_settings(dirs: Optional[Dict[str, str]] = None):
    global OUTPUT_INPUT_DIR, OUTPUT_OUTPUT_DIR, LOCAL_UPLOAD_DIR, STORAGE_DIRS
    dirs = dirs or load_storage_settings().get("dirs") or {}
    OUTPUT_INPUT_DIR = dirs.get("upload") or OUTPUT_INPUT_DIR
    OUTPUT_OUTPUT_DIR = dirs.get("generated") or OUTPUT_OUTPUT_DIR
    LOCAL_UPLOAD_DIR = dirs.get("local") or LOCAL_UPLOAD_DIR
    STORAGE_DIRS["upload"] = OUTPUT_INPUT_DIR
    STORAGE_DIRS["generated"] = OUTPUT_OUTPUT_DIR
    STORAGE_DIRS["local"] = LOCAL_UPLOAD_DIR

apply_storage_settings()

def storage_kind_dir(kind: str) -> str:
    kind = str(kind or "").strip().lower()
    if kind in STORAGE_DIRS:
        return os.path.abspath(STORAGE_DIRS[kind])
    raise HTTPException(status_code=404, detail="未知存储目录")

def storage_file_path(kind: str, rel: str) -> Optional[str]:
    root = storage_kind_dir(kind)
    rel_path = str(rel or "").replace("\\", "/").lstrip("/")
    rel_path = os.path.normpath(rel_path).replace("\\", "/")
    if not rel_path or rel_path == "." or rel_path == ".." or rel_path.startswith("../") or os.path.isabs(rel_path):
        raise HTTPException(status_code=400, detail="非法文件路径")
    path = os.path.abspath(os.path.join(root, rel_path))
    try:
        if os.path.commonpath([root, path]) != root:
            raise HTTPException(status_code=400, detail="非法文件路径")
    except ValueError:
        raise HTTPException(status_code=400, detail="非法文件路径")
    return path if os.path.exists(path) else None

set_storage_file_resolver(storage_file_path)

def output_storage(category: str = "output") -> Tuple[str, str]:
    return (OUTPUT_INPUT_DIR, "input") if category == "input" else (OUTPUT_OUTPUT_DIR, "output")

def output_url_for(filename: str, category: str = "output") -> str:
    folder, _ = output_storage(category)
    rel = str(filename or "").replace("\\", "/").lstrip("/")
    try:
        asset_rel = os.path.relpath(os.path.join(folder, rel), ASSETS_DIR).replace("\\", "/")
        if not asset_rel.startswith("../") and asset_rel != "..":
            return f"/assets/{urllib.parse.quote(asset_rel, safe='/')}"
    except Exception:
        pass
    kind = "upload" if category == "input" else "generated"
    return f"/api/storage-files/{kind}/{urllib.parse.quote(rel, safe='/')}"

def output_path_for(filename: str, category: str = "output") -> str:
    folder, _ = output_storage(category)
    return os.path.join(folder, filename)

def storage_file_item(kind: str, root: str, path: str) -> Optional[Dict[str, Any]]:
    rel = os.path.relpath(path, root).replace("\\", "/")
    try:
        stat = os.stat(path)
    except OSError:
        return None
    item = {
        "id": f"{kind}:{rel}",
        "kind": kind,
        "rel": rel,
        "name": os.path.basename(path),
        "folder": os.path.dirname(rel).replace("\\", "/"),
        "url": f"/api/storage-files/{kind}/{urllib.parse.quote(rel, safe='/')}",
        "size": stat.st_size,
        "created_at": stat.st_mtime,
    }
    try:
        with Image.open(path) as img:
            item["width"], item["height"] = img.size
    except Exception:
        pass
    th_meta = get_task_history_meta_index()
    th = th_meta.get(item["name"]) or th_meta.get(rel)
    if th:
        item["provider_id"] = th[0]
        item["model"] = th[1]
        if len(th) > 2 and th[2]:
            item["prompt"] = th[2]
    return item

def local_media_file_by_basename(name: str) -> Optional[str]:
    safe = os.path.basename(urllib.parse.unquote(str(name or "")))
    if not safe:
        return None
    roots = [
        OUTPUT_OUTPUT_DIR,
        OUTPUT_INPUT_DIR,
        os.path.join(ASSETS_DIR, "output"),
        os.path.join(ASSETS_DIR, "input"),
        os.path.join(ASSETS_DIR, "library"),
    ]
    for root in roots:
        path = os.path.abspath(os.path.join(root, safe))
        root_abs = os.path.abspath(root)
        try:
            if os.path.commonpath([root_abs, path]) == root_abs and os.path.isfile(path):
                return path
        except ValueError:
            continue
    return None

def filename_from_media_url(url: str, fallback: str = "download.bin") -> str:
    path = urllib.parse.urlsplit(str(url or "")).path
    name = os.path.basename(urllib.parse.unquote(path))
    return sanitize_export_filename(name or fallback, fallback)

def fetch_remote_media_bytes(url: str, timeout: float = 30.0, max_bytes: int = 200 * 1024 * 1024) -> Optional[Tuple[bytes, str]]:
    text = str(url or "").strip()
    if _runninghub_url_rewriter:
        try:
            text = _runninghub_url_rewriter(text)
        except Exception:
            pass
    if not text.startswith(("http://", "https://")):
        return None
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                return pool.submit(asyncio.run, safe_download_bytes(text, timeout=timeout, max_bytes=max_bytes, allow_private=False)).result()
        return asyncio.run(safe_download_bytes(text, timeout=timeout, max_bytes=max_bytes, allow_private=False))
    except Exception as exc:
        logger.warning(f"下载远程素材失败: {exc}; url={text}")
        return None


# ===== 媒体预览与缩略图 =====
def media_preview_cache_paths(path: str, width: int) -> Tuple[str, str]:
    stat = os.stat(path)
    key = hashlib.sha1(
        f"{os.path.abspath(path)}|{stat.st_mtime_ns}|{stat.st_size}|{width}".encode("utf-8", "ignore")
    ).hexdigest()
    return (
        os.path.join(MEDIA_PREVIEW_DIR, f"{key}.webp"),
        os.path.join(MEDIA_PREVIEW_DIR, f"{key}.png"),
    )

def is_video_preview_file(path: str) -> bool:
    return os.path.splitext(str(path or "").split("?", 1)[0])[1].lower() in {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}

def generate_video_preview_image(path: str, width: int) -> Image.Image:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法生成视频预览图")
    fd, frame_path = tempfile.mkstemp(prefix="media_preview_frame_", suffix=".jpg")
    os.close(fd)
    try:
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", "0.5",
            "-i", path,
            "-frames:v", "1",
            "-vf", f"scale='min({width},iw)':-2",
            frame_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0 or not os.path.exists(frame_path) or os.path.getsize(frame_path) <= 0:
            raise RuntimeError((proc.stderr or "ffmpeg 未能抽取视频首帧").strip()[:300])
        with Image.open(frame_path) as frame:
            img = ImageOps.exif_transpose(frame).copy()
            img.thumbnail((width, width), Image.LANCZOS)
            return img.convert("RGB")
    finally:
        try:
            os.remove(frame_path)
        except OSError:
            pass


# ===== 资产库持久化核心 =====
def default_asset_library() -> Dict[str, Any]:
    categories = [
        {"id": "characters", "name": "角色", "type": "image", "items": []},
        {"id": "scenes", "name": "场景", "type": "image", "items": []},
        {"id": "workflows", "name": "工作流", "type": "workflow", "items": []},
    ]
    return {
        "active_library_id": "default",
        "libraries": [{"id": "default", "name": "默认资产库", "type": "asset", "categories": categories}],
        "categories": categories,
        "updated_at": now_ms(),
    }

def migrate_asset_item_registrations(item: Any):
    """一个素材可注册到多平台：把旧的单平台扁平字段折叠进 item['registrations'][platform]，再清掉旧字段。"""
    if not isinstance(item, dict):
        return
    regs = item.get("registrations")
    if not isinstance(regs, dict):
        regs = {}
    legacy_platform = str(item.get("platform") or "").strip()
    if legacy_platform and legacy_platform not in regs and (item.get("asset_uri") or item.get("avatar_task_id")):
        regs[legacy_platform] = {
            "provider_id": item.get("provider_id") or "",
            "project_name": item.get("project_name") or "default",
            "task_id": item.get("avatar_task_id") or "",
            "status": item.get("avatar_status") or "",
            "detail": item.get("avatar_detail") or "",
            "asset_uri": item.get("asset_uri") or "",
            "asset_id": item.get("asset_id") or "",
            "registered_at": item.get("registered_at") or 0,
        }
    item["registrations"] = regs if isinstance(regs, dict) else {}
    for key in AVATAR_LEGACY_FLAT_FIELDS:
        item.pop(key, None)

def sort_asset_library_items(lib: Dict[str, Any]):
    cats = list(lib.get("categories", []))
    for library in lib.get("libraries", []) if isinstance(lib.get("libraries"), list) else []:
        cats.extend(library.get("categories") or [])
    seen = set()
    for cat in cats:
        if id(cat) in seen:
            continue
        seen.add(id(cat))
        items = cat.get("items")
        if isinstance(items, list):
            def created_at_key(item):
                if not isinstance(item, dict):
                    return 0
                try:
                    return int(float(item.get("created_at") or 0))
                except (TypeError, ValueError):
                    return 0
            items.sort(key=created_at_key, reverse=True)

def normalize_asset_library(lib: Any) -> Dict[str, Any]:
    if not isinstance(lib, dict):
        lib = default_asset_library()
    legacy_categories = lib.get("categories") if isinstance(lib.get("categories"), list) else None
    libraries = lib.get("libraries") if isinstance(lib.get("libraries"), list) else []
    if not libraries:
        libraries = [{
            "id": "default",
            "name": "默认资产库",
            "type": "asset",
            "categories": legacy_categories or default_asset_library()["categories"],
        }]
    for library in libraries:
        library["id"] = re.sub(r"[^A-Za-z0-9_-]+", "_", str(library.get("id") or f"lib_{uuid.uuid4().hex[:8]}"))[:40]
        library["name"] = sanitize_asset_name(library.get("name") or "资产库", "资产库")
        cats = library.get("categories") if isinstance(library.get("categories"), list) else []
        if library.get("id") == "default" and not any(c.get("type") == "workflow" for c in cats):
            cats.append({"id": "workflows", "name": "工作流", "type": "workflow", "items": []})
        for cat in cats:
            for item in (cat.get("items") or []):
                migrate_asset_item_registrations(item)
        library["categories"] = cats
    active = str(lib.get("active_library_id") or libraries[0].get("id") or "default")
    if not any(item.get("id") == active for item in libraries):
        active = libraries[0].get("id") or "default"
    active_library = next((item for item in libraries if item.get("id") == active), libraries[0])
    lib["libraries"] = libraries
    lib["active_library_id"] = active
    lib["categories"] = active_library.get("categories") or []
    lib["updated_at"] = int(lib.get("updated_at") or now_ms())
    sort_asset_library_items(lib)
    return lib

def load_asset_library() -> Dict[str, Any]:
    with ASSET_LIBRARY_LOCK:
        if not os.path.exists(ASSET_LIBRARY_PATH):
            lib = default_asset_library()
            save_asset_library(lib)
            return lib
        try:
            with open(ASSET_LIBRARY_PATH, "r", encoding="utf-8") as f:
                lib = json.load(f)
        except Exception:
            lib = default_asset_library()
        return normalize_asset_library(lib)

def save_asset_library(lib: Dict[str, Any]):
    with ASSET_LIBRARY_LOCK:
        lib = normalize_asset_library(lib)
        sort_asset_library_items(lib)
        lib["updated_at"] = now_ms()
        os.makedirs(DATA_DIR, exist_ok=True)
        atomic_save_json(ASSET_LIBRARY_PATH, lib)
    _broadcast_asset_library_updated(int(lib["updated_at"]))

def find_asset_library(lib: Dict[str, Any], library_id: str = "") -> Optional[Dict[str, Any]]:
    lib = normalize_asset_library(lib)
    target_id = str(library_id or lib.get("active_library_id") or "").strip()
    return next((item for item in lib.get("libraries", []) if item.get("id") == target_id), None) or (lib.get("libraries") or [None])[0]

def find_asset_category(lib: Dict[str, Any], category_id: str) -> Optional[Dict[str, Any]]:
    for cat in lib.get("categories", []):
        if cat.get("id") == category_id:
            return cat
    return None

def find_asset_category_in_library(lib: Dict[str, Any], category_id: str, library_id: str = "") -> Optional[Dict[str, Any]]:
    library = find_asset_library(lib, library_id)
    if not library:
        return None
    for cat in library.get("categories", []):
        if cat.get("id") == category_id:
            return cat
    return None

def find_asset_category_with_library(lib: Dict[str, Any], category_id: str, library_id: str = "") -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    lib = normalize_asset_library(lib)
    preferred = str(library_id or "").strip()
    libraries = lib.get("libraries", []) or []
    if preferred:
        libraries = [item for item in libraries if item.get("id") == preferred]
    for library in libraries:
        for cat in library.get("categories", []) or []:
            if cat.get("id") == category_id:
                return library, cat
    return None, None

def find_asset_item_in_library(lib: Dict[str, Any], item_id: str, library_id: str = "") -> Optional[Dict[str, Any]]:
    for library in lib.get("libraries", []):
        if library_id and library.get("id") != library_id:
            continue
        for cat in library.get("categories", []):
            for item in cat.get("items", []):
                if item.get("id") == item_id:
                    return item
    return None

def asset_library_media_kind(path: str, content_type: str = "") -> str:
    ext = os.path.splitext(path or "")[1].lower()
    ct = (content_type or "").lower()
    if ext in {".json", ".zip"}:
        return "workflow"
    if ext in {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"} or ct.startswith("video/"):
        return "video"
    if ext in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"} or ct.startswith("audio/"):
        return "audio"
    return "image"

def asset_library_safe_extension(path: str, kind: str) -> str:
    ext = os.path.splitext(path or "")[1].lower()
    allowed = {
        "image": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
        "video": {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"},
        "audio": {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"},
        "workflow": {".json", ".zip"},
    }
    fallback = {"image": ".png", "video": ".mp4", "audio": ".mp3", "workflow": ".zip"}
    return ext if ext in allowed.get(kind, allowed["image"]) else fallback.get(kind, ".png")

def unique_asset_category_dir(library: Dict[str, Any], base_name: str) -> str:
    base = sanitize_asset_name(base_name, "分组").strip(" .") or "分组"
    existing = {
        str(c.get("dir")) for c in (library.get("categories") or [])
        if isinstance(c, dict) and c.get("dir")
    }
    candidate = base
    i = 2
    while candidate in existing or os.path.exists(os.path.join(ASSET_LIBRARY_DIR, candidate)):
        candidate = f"{base}_{i}"
        i += 1
    return candidate

def remove_asset_library_file(item: Any) -> None:
    try:
        url = item.get("url") if isinstance(item, dict) else ""
        path = output_file_from_url(url)
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception as exc:
        logger.debug(f"删除资产文件失败: {exc}")

def make_asset_library_item(src: str, name: str = "", subdir: str = "") -> Tuple[str, Dict[str, Any]]:
    kind = asset_library_media_kind(src)
    ext = asset_library_safe_extension(src, kind)
    safe_name = sanitize_asset_name(name or os.path.basename(src), "asset")
    if not os.path.splitext(safe_name)[1]:
        safe_name += ext
    dest_name = f"lib_{uuid.uuid4().hex[:12]}_{safe_name}"
    subdir = str(subdir or "").strip("/").strip()
    if subdir:
        dest_dir = os.path.join(ASSET_LIBRARY_DIR, subdir)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, dest_name)
        rel = f"{subdir}/{dest_name}"
    else:
        dest_path = os.path.join(ASSET_LIBRARY_DIR, dest_name)
        rel = dest_name
    shutil.copy2(src, dest_path)
    item = {
        "id": f"asset_{uuid.uuid4().hex[:12]}",
        "name": os.path.splitext(safe_name)[0][:120],
        "url": "/assets/library/" + urllib.parse.quote(rel, safe="/"),
        "kind": kind,
        "created_at": now_ms(),
    }
    return dest_name, item

def asset_library_workflow_category(lib: Dict[str, Any], library_id: str = "", category_id: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    library = find_asset_library(lib, library_id)
    if not library:
        raise HTTPException(status_code=404, detail="资产库不存在")
    categories = library.setdefault("categories", [])
    cat = None
    if category_id:
        cat = next((c for c in categories if c.get("id") == category_id), None)
        if not cat:
            raise HTTPException(status_code=404, detail="工作流分类不存在")
        if cat.get("type") != "workflow":
            raise HTTPException(status_code=400, detail="目标分组不是工作流分类")
    if not cat:
        cat = next((c for c in categories if c.get("type") == "workflow"), None)
    if not cat:
        cat = {"id": f"wf_{uuid.uuid4().hex[:12]}", "name": "工作流", "type": "workflow", "items": []}
        categories.append(cat)
    lib["active_library_id"] = library.get("id") or lib.get("active_library_id")
    return library, cat

def make_workflow_library_item_from_bytes(raw: bytes, filename: str, name: str = "") -> Dict[str, Any]:
    if not raw:
        raise HTTPException(status_code=400, detail="工作流文件为空")
    safe_filename = sanitize_export_filename(filename or "canvas-workflow.zip", "canvas-workflow.zip")
    ext = os.path.splitext(safe_filename)[1].lower()
    if ext not in {".json", ".zip"}:
        safe_filename += ".zip"
        ext = ".zip"
    dest_name = f"workflow_{uuid.uuid4().hex[:12]}_{safe_filename}"
    dest_path = os.path.join(ASSET_LIBRARY_DIR, dest_name)
    os.makedirs(ASSET_LIBRARY_DIR, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(raw)
    display_name = sanitize_asset_name(name or os.path.splitext(safe_filename)[0], "工作流")
    return {
        "id": f"wf_{uuid.uuid4().hex[:12]}",
        "name": display_name[:120],
        "url": f"/assets/library/{dest_name}",
        "kind": "workflow",
        "type": "workflow",
        "format": "zip" if ext == ".zip" else "json",
        "size": len(raw),
        "created_at": now_ms(),
    }


# ===== 素材智能分类打标辅助 =====
def load_asset_classification_prompt() -> str:
    try:
        if os.path.isfile(ASSET_CLASSIFICATION_PROMPT_FILE):
            with open(ASSET_CLASSIFICATION_PROMPT_FILE, "r", encoding="utf-8-sig") as f:
                text = f.read().strip()
                if text:
                    return text
    except Exception as exc:
        logger.debug(f"读取素材分类规则失败: {exc}")
    return ASSET_CLASSIFICATION_PROMPT

def save_asset_classification_prompt(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="分类规则不能为空")
    if len(value) > 20000:
        raise HTTPException(status_code=400, detail="分类规则过长")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ASSET_CLASSIFICATION_PROMPT_FILE, "w", encoding="utf-8") as f:
        f.write(value)
    return value

def _safe_asset_tag(value: Any, limit: int = 24) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = re.sub(r"^[#＃]+", "", text).strip(" ,，、;；|/")
    return text[:limit]

def normalize_asset_classification(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    categories = raw.get("categories") if isinstance(raw.get("categories"), dict) else {}
    clean_categories = {}
    flat = []
    for key, values in categories.items():
        norm_key = re.sub(r"[^A-Za-z0-9_-]+", "_", str(key or "").strip().lower())[:40]
        if not norm_key:
            continue
        if isinstance(values, str):
            values = re.split(r"[,，、/|;；\n]+", values)
        if not isinstance(values, list):
            continue
        clean_values = []
        seen = set()
        for value in values:
            tag = _safe_asset_tag(value)
            if not tag or tag in seen:
                continue
            seen.add(tag)
            clean_values.append(tag)
            flat.append({"dimension": norm_key, "label": ASSET_CLASSIFICATION_DIMENSION_NAMES.get(norm_key, norm_key), "tag": tag})
            if len(clean_values) >= 8:
                break
        if clean_values:
            clean_categories[norm_key] = clean_values
    tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    clean_tags = []
    seen_tags = set()
    for value in tags:
        tag = _safe_asset_tag(value)
        if not tag or tag in seen_tags:
            continue
        seen_tags.add(tag)
        clean_tags.append(tag)
        flat.append({"dimension": "tags", "label": "标签", "tag": tag})
        if len(clean_tags) >= 20:
            break
    seen_flat = set()
    flat_unique = []
    for item in flat:
        key = f"{item['dimension']}::{item['tag']}"
        if key in seen_flat:
            continue
        seen_flat.add(key)
        flat_unique.append(item)
    return {
        "summary": str(raw.get("summary") or "").strip()[:240],
        "categories": clean_categories,
        "tags": clean_tags,
        "flat": flat_unique,
        "updated_at": now_ms(),
    }

def parse_asset_classification_text(text: str) -> Dict[str, Any]:
    value = str(text or "").strip()
    if not value:
        return normalize_asset_classification({})
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\s*```$", "", value).strip()
    try:
        data = json.loads(value)
    except Exception:
        match = re.search(r"\{.*\}", value, re.S)
        data = json.loads(match.group(0)) if match else {}
    return normalize_asset_classification(data)

def _local_upload_classification_path(filename: str) -> str:
    return os.path.splitext(os.path.join(LOCAL_UPLOAD_DIR, filename))[0] + ".classification.json"

def _read_local_upload_classification(filename: str) -> Optional[Dict[str, Any]]:
    path = _local_upload_classification_path(filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return normalize_asset_classification(json.load(f))
    except Exception:
        return None

def _write_local_upload_classification(filename: str, classification: Any):
    path = _local_upload_classification_path(filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalize_asset_classification(classification), f, ensure_ascii=False, indent=2)

def asset_classification_prompt(extra_prompt: str = "") -> str:
    base = load_asset_classification_prompt()
    extra = str(extra_prompt or "").strip()
    if not extra:
        return base
    return base + "\n\n用户补充分类要求：\n" + extra[:4000]

async def classify_asset_image_best_effort(abs_path: str, provider_id: str = "", model: str = "", ms_model: str = "", prompt: str = ""):
    if _image_classifier:
        try:
            return await _image_classifier(abs_path, provider_id, model, ms_model, prompt)
        except Exception as exc:
            logger.debug(f"素材智能分类失败: {exc}")
            return None
    return None

def migrate_asset_library_into_dirs():
    """一次性整理：给所有图片分组补上真实文件夹，并把仍在 library/ 根目录的素材搬进各自文件夹。"""
    try:
        lib = load_asset_library()
    except Exception as exc:
        logger.debug(f"资产库分组整理加载失败: {exc}")
        return
    changed = False
    for library in lib.get("libraries", []) or []:
        for cat in library.get("categories", []) or []:
            if (cat.get("type") or "image") != "image":
                continue
            if not cat.get("dir"):
                cat["dir"] = unique_asset_category_dir(library, cat.get("name") or "分组")
                changed = True
            cat_dir = str(cat.get("dir") or "").strip("/").strip()
            if not cat_dir:
                continue
            try:
                os.makedirs(os.path.join(ASSET_LIBRARY_DIR, cat_dir), exist_ok=True)
            except Exception as exc:
                logger.debug(f"资产库建分组文件夹失败: {exc}")
                continue
            for item in (cat.get("items") or []):
                raw_url = urllib.parse.unquote(str(item.get("url") or "").split("?", 1)[0])
                m = re.match(r"^/assets/library/([^/]+)$", raw_url)
                if not m:
                    continue
                fname = m.group(1)
                src = os.path.join(ASSET_LIBRARY_DIR, fname)
                if not os.path.isfile(src):
                    continue
                dst = os.path.join(ASSET_LIBRARY_DIR, cat_dir, fname)
                try:
                    if not os.path.exists(dst):
                        shutil.move(src, dst)
                    item["url"] = "/assets/library/" + urllib.parse.quote(f"{cat_dir}/{fname}", safe="/")
                    changed = True
                except Exception as exc:
                    logger.debug(f"资产库搬运 {fname} 失败: {exc}")
    if changed:
        try:
            save_asset_library(lib)
        except Exception as exc:
            logger.debug(f"资产库分组整理保存失败: {exc}")


# ===== 共享文件夹辅助 =====
def shared_folders_load() -> Dict[str, Any]:
    with SHARED_FOLDERS_LOCK:
        try:
            with open(SHARED_FOLDERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        folders = data.get("folders")
        if not isinstance(folders, list):
            folders = []
        return {"folders": [f for f in folders if isinstance(f, dict)]}

def shared_folders_save(data: Any):
    with SHARED_FOLDERS_LOCK:
        os.makedirs(DATA_DIR, exist_ok=True)
        atomic_save_json(SHARED_FOLDERS_FILE, data)

def shared_folder_by_id(folder_id: str) -> Optional[Dict[str, Any]]:
    for entry in shared_folders_load().get("folders", []):
        if entry.get("id") == folder_id:
            return entry
    return None

def shared_folder_abs(entry: Any) -> str:
    rel = (entry or {}).get("rel") or ""
    return os.path.normpath(os.path.join(BASE_DIR, rel))

def shared_resolve_register(path: str) -> Tuple[str, str]:
    raw = (path or "").strip().strip('"').strip("'")
    if not raw:
        raise HTTPException(status_code=400, detail="请提供文件夹路径")
    candidate = raw if os.path.isabs(raw) else os.path.join(BASE_DIR, raw)
    abs_path = os.path.normpath(os.path.abspath(candidate))
    base = os.path.normpath(os.path.abspath(BASE_DIR))
    try:
        common = os.path.commonpath([abs_path, base])
    except ValueError:
        raise HTTPException(status_code=400, detail="只允许登记项目目录内的文件夹")
    if common != base:
        raise HTTPException(status_code=400, detail="只允许登记项目目录内的文件夹")
    if abs_path == base:
        raise HTTPException(status_code=400, detail="不能直接登记项目根目录，请选择子文件夹")
    if not os.path.isdir(abs_path):
        raise HTTPException(status_code=400, detail="文件夹不存在")
    rel = os.path.relpath(abs_path, base)
    return abs_path, rel

def shared_child_abs(folder_abs: str, rel: str) -> str:
    rel = (rel or "").replace("\\", "/").lstrip("/")
    abs_path = os.path.normpath(os.path.join(folder_abs, rel))
    base = os.path.normpath(os.path.abspath(folder_abs))
    try:
        common = os.path.commonpath([os.path.abspath(abs_path), base])
    except ValueError:
        raise HTTPException(status_code=400, detail="非法路径")
    if common != base:
        raise HTTPException(status_code=400, detail="非法路径")
    return abs_path

def scan_shared_tree(folder_id: str, folder_abs: str, rel_prefix: str = "", display: str = "", counter: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    if counter is None:
        counter = {"n": 0}
    node = {
        "id": f"{folder_id}:{rel_prefix or '__root__'}",
        "name": display or os.path.basename(folder_abs) or folder_abs,
        "path": rel_prefix,
        "items": [],
        "children": [],
    }
    try:
        entries = sorted(os.scandir(folder_abs), key=lambda e: (not e.is_dir(), e.name.lower()))
    except OSError:
        return node
    for ent in entries:
        if counter["n"] >= SHARED_SCAN_MAX_ENTRIES:
            break
        if ent.name.startswith(".") or ent.name.startswith("._"):
            continue
        child_rel = f"{rel_prefix}/{ent.name}".lstrip("/")
        if ent.is_dir():
            child = scan_shared_tree(folder_id, ent.path, child_rel, ent.name, counter)
            if child["items"] or child["children"]:
                node["children"].append(child)
        elif ent.is_file():
            ext = os.path.splitext(ent.name)[1].lower()
            if ext not in SHARED_MEDIA_EXTS:
                continue
            counter["n"] += 1
            try:
                st = ent.stat()
                size = st.st_size
                mtime = int(st.st_mtime * 1000)
            except OSError:
                size = 0
                mtime = 0
            kind = "video" if ext in {".mp4", ".webm", ".mov", ".m4v", ".mkv"} else "audio" if ext in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"} else "image"
            node["items"].append({
                "id": f"{folder_id}:{child_rel}",
                "name": ent.name,
                "rel": child_rel,
                "path": child_rel,
                "url": f"/api/shared-folders/{folder_id}/file?path={urllib.parse.quote(child_rel)}",
                "kind": kind,
                "size": size,
                "created_at": mtime,
            })
    return node


# ===== 本地上传辅助 =====
def _local_upload_kind_ext(filename: str, content_type: str) -> Tuple[Optional[str], str]:
    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    video_exts = {".mp4", ".webm", ".mov", ".m4v", ".flv"}
    audio_exts = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
    ext = os.path.splitext(filename or "")[1].lower()
    ct = (content_type or "").lower()
    if ext in video_exts or ct.startswith("video/"):
        if ext not in video_exts:
            ext = ".webm" if "webm" in ct else ".mov" if "quicktime" in ct else ".mp4"
        return "video", ext
    if ext in audio_exts or ct.startswith("audio/"):
        if ext not in audio_exts:
            ext = ".wav" if "wav" in ct else ".ogg" if "ogg" in ct else ".m4a" if "mp4" in ct else ".mp3"
        return "audio", ext
    if ext in image_exts or ct.startswith("image/"):
        if ext not in image_exts:
            ext = ".jpg" if "jpeg" in ct else ".webp" if "webp" in ct else ".gif" if "gif" in ct else ".png"
        return "image", ext
    return None, ext

def _local_upload_display_name(filename: str) -> str:
    base = os.path.basename(str(filename or ""))
    m = re.match(r"^up_[0-9a-f]{12}_(.+)$", base)
    return m.group(1) if m else base

def _local_upload_rel_path(value: str) -> str:
    text = str(value or "").replace("\\", "/").strip().lstrip("/")
    if not text:
        return ""
    norm = os.path.normpath(text).replace("\\", "/")
    if norm in {".", ""}:
        return ""
    if norm.startswith("../") or norm == ".." or os.path.isabs(norm):
        raise HTTPException(status_code=400, detail="非法路径")
    return norm

def _local_upload_abs(rel: str) -> Tuple[str, str]:
    rel_path = _local_upload_rel_path(rel)
    path = os.path.abspath(os.path.join(LOCAL_UPLOAD_DIR, rel_path))
    root = os.path.abspath(LOCAL_UPLOAD_DIR)
    try:
        common = os.path.commonpath([root, path])
    except ValueError:
        raise HTTPException(status_code=400, detail="非法路径")
    if common != root:
        raise HTTPException(status_code=400, detail="非法路径")
    return rel_path, path

def _local_upload_safe_path(name: str) -> Tuple[str, str]:
    filename, path = _local_upload_abs(name)
    if not filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    return filename, path

def _local_upload_safe_folder(path_value: str) -> Tuple[str, str]:
    return _local_upload_abs(path_value)

def _local_upload_safe_folder_name(name: str) -> str:
    cleaned = sanitize_asset_name(os.path.basename(str(name or "").strip()), "")
    cleaned = re.sub(r"[\\/]+", "_", cleaned).strip(" ._")
    if not cleaned:
        raise HTTPException(status_code=400, detail="文件夹名称不能为空")
    return cleaned[:60]

def _local_upload_safe_file_stem(name: str) -> str:
    raw = os.path.splitext(os.path.basename(str(name or "").strip()))[0]
    cleaned = sanitize_asset_name(raw, "")
    cleaned = re.sub(r"[\\/]+", "_", cleaned).strip(" ._")
    if not cleaned:
        raise HTTPException(status_code=400, detail="文件名称不能为空")
    return cleaned[:120]

def _local_upload_caption_path(filename: str) -> str:
    return os.path.splitext(os.path.join(LOCAL_UPLOAD_DIR, filename))[0] + ".txt"

def _read_local_upload_caption(filename: str) -> Tuple[str, str]:
    caption_path = _local_upload_caption_path(filename)
    if not os.path.isfile(caption_path):
        return "", ""
    try:
        with open(caption_path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except UnicodeDecodeError:
        try:
            with open(caption_path, "r", encoding="gb18030", errors="replace") as f:
                text = f.read()
        except OSError:
            return "", ""
    except OSError:
        return "", ""
    return text, os.path.basename(caption_path)

def _local_upload_item(filename: str) -> Dict[str, Any]:
    path = os.path.join(LOCAL_UPLOAD_DIR, filename)
    rel = _local_upload_rel_path(filename)
    try:
        stat = os.stat(path)
        size = stat.st_size
        created_at = stat.st_mtime
    except OSError:
        size = 0
        created_at = 0
    kind, _ = _local_upload_kind_ext(filename, "")
    item = {
        "id": rel,
        "file": rel,
        "name": _local_upload_display_name(rel),
        "url": f"/api/storage-files/local/{urllib.parse.quote(rel, safe='/')}",
        "kind": kind or "image",
        "size": size,
        "created_at": created_at,
        "folder": os.path.dirname(rel).replace("\\", "/"),
    }
    if kind == "image":
        try:
            with Image.open(path) as img:
                item["natural_w"], item["natural_h"] = img.size
                item["width"], item["height"] = img.size
        except Exception:
            pass
        caption, caption_file = _read_local_upload_caption(filename)
        item["caption"] = caption
        item["caption_file"] = caption_file
        classification = _read_local_upload_classification(filename)
        if classification:
            item["classification"] = classification
    th_meta = get_task_history_meta_index()
    th = th_meta.get(os.path.basename(filename)) or th_meta.get(rel)
    if th:
        item["provider_id"] = th[0]
        item["model"] = th[1]
        if not item.get("caption") and len(th) > 2 and th[2]:
            item["caption"] = th[2]
            item["prompt"] = th[2]
    return item

def _local_upload_folder_node(path: str = "", name: str = "全部上传") -> Dict[str, Any]:
    rel = _local_upload_rel_path(path)
    return {
        "id": rel or "__root__",
        "path": rel,
        "name": name if not rel else os.path.basename(rel),
        "items": [],
        "children": [],
    }

def _local_upload_tree_and_items() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    root_node = _local_upload_folder_node("", "全部上传")
    folder_map = {"": root_node}
    items = []
    for current, dirs, files in os.walk(LOCAL_UPLOAD_DIR):
        dirs[:] = sorted([d for d in dirs if not d.startswith(".") and not d.startswith("._")], key=str.lower)
        rel_dir = os.path.relpath(current, LOCAL_UPLOAD_DIR).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        node = folder_map.get(rel_dir)
        if node is None:
            node = _local_upload_folder_node(rel_dir)
            folder_map[rel_dir] = node
        for dirname in dirs:
            child_rel = f"{rel_dir}/{dirname}".lstrip("/")
            child = _local_upload_folder_node(child_rel)
            folder_map[child_rel] = child
            node["children"].append(child)
        for name in sorted(files, key=str.lower):
            if name.startswith(".") or name.startswith("._"):
                continue
            rel_file = f"{rel_dir}/{name}".lstrip("/")
            kind, _ = _local_upload_kind_ext(name, "")
            if kind is None:
                continue
            item = _local_upload_item(rel_file)
            node["items"].append(item)
            items.append(item)
    def fill_counts(node):
        total = len(node.get("items") or [])
        for child in node.get("children") or []:
            total += fill_counts(child)
        node["count"] = total
        return total
    fill_counts(root_node)
    items.sort(key=lambda it: it.get("created_at") or 0, reverse=True)
    return root_node, items

_DOUBLE_EXT_RE = re.compile(r'(\.[A-Za-z0-9]{1,5})\1$', re.IGNORECASE)
_DOUBLE_EXT_MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif",
                     ".mp4", ".webm", ".mov", ".m4v", ".flv"}

def migrate_double_extension_uploads():
    """修复历史遗留的双重扩展名（如 foo.png.png）。"""
    if not os.path.isdir(LOCAL_UPLOAD_DIR):
        return
    renamed = 0
    for current, _dirs, files in os.walk(LOCAL_UPLOAD_DIR):
        for name in files:
            m = _DOUBLE_EXT_RE.search(name)
            if not m or m.group(1).lower() not in _DOUBLE_EXT_MEDIA:
                continue
            old_path = os.path.join(current, name)
            new_path = os.path.join(current, name[:-len(m.group(1))])
            if os.path.exists(new_path):
                continue
            try:
                os.rename(old_path, new_path)
            except OSError:
                continue
            renamed += 1
            old_base = os.path.splitext(old_path)[0]
            new_base = os.path.splitext(new_path)[0]
            for suffix in (".classification.json", ".txt"):
                src_side, dst_side = old_base + suffix, new_base + suffix
                if os.path.exists(src_side) and not os.path.exists(dst_side):
                    try:
                        os.rename(src_side, dst_side)
                    except OSError:
                        pass
    if renamed:
        logger.info(f"修复双重扩展名素材: {renamed} 个")

def _sniff_image_ext_bytes(head: bytes) -> Optional[str]:
    head = head or b""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if head[:2] == b"BM":
        return ".bmp"
    return None

def _sniff_image_ext(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return _sniff_image_ext_bytes(f.read(16))
    except OSError:
        return None

def migrate_mislabeled_image_extensions():
    """按真实魔数纠正扩展名，并同步重命名 caption/classification 旁车。"""
    if not os.path.isdir(LOCAL_UPLOAD_DIR):
        return
    img_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
    fixed = 0
    for current, _dirs, files in os.walk(LOCAL_UPLOAD_DIR):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in img_exts:
                continue
            path = os.path.join(current, name)
            real = _sniff_image_ext(path)
            if not real:
                continue
            if real == ext or (real == ".jpg" and ext == ".jpeg"):
                continue
            new_name = os.path.splitext(name)[0] + real
            new_path = os.path.join(current, new_name)
            if os.path.exists(new_path):
                continue
            try:
                os.rename(path, new_path)
            except OSError:
                continue
            fixed += 1
            old_base = os.path.splitext(path)[0]
            new_base = os.path.splitext(new_path)[0]
            for suffix in (".classification.json", ".txt"):
                src_side, dst_side = old_base + suffix, new_base + suffix
                if os.path.isfile(src_side) and not os.path.exists(dst_side):
                    try:
                        os.rename(src_side, dst_side)
                    except OSError:
                        pass
    if fixed:
        logger.info(f"纠正图片扩展名(内容与后缀不符): {fixed} 个")


# ===== 画布资产提取与聚合 =====
def canvas_asset_url_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("url", "path", "src", "uri", "output", "output_url", "outputUrl", "video", "video_url", "videoUrl"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
    return ""

def canvas_asset_downloadable_url(url: str) -> str:
    text = str(url or "").strip()
    return text if text.startswith(("/output/", "/assets/", "http://", "https://")) else ""

def canvas_asset_kind(value: Any, url: str = "") -> str:
    explicit = ""
    if isinstance(value, dict):
        explicit = str(value.get("kind") or value.get("mediaKind") or value.get("type") or "").lower()
    if "video" in explicit:
        return "video"
    if "audio" in explicit:
        return "audio"
    if "text" in explicit:
        return "text"
    if "workflow" in explicit:
        return "workflow"
    return asset_library_media_kind(url or canvas_asset_url_value(value))

def canvas_asset_name(value: Any, url: str = "", fallback: str = "asset") -> str:
    if isinstance(value, dict):
        for key in ("name", "filename", "file", "title"):
            name = str(value.get(key) or "").strip()
            if name:
                return sanitize_asset_name(name, fallback)
    return sanitize_asset_name(filename_from_media_url(url, fallback), fallback)

def iter_canvas_asset_values(value: Any, path: str = ""):
    if isinstance(value, dict):
        url = canvas_asset_downloadable_url(canvas_asset_url_value(value))
        if url:
            yield path, value, url
        for key, child in value.items():
            if key in {"run", "runs", "settings", "params", "metadata", "meta", "prompt", "text", "caption", "logs"}:
                continue
            yield from iter_canvas_asset_values(child, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_canvas_asset_values(child, f"{path}[{index}]")
    elif isinstance(value, str):
        url = canvas_asset_downloadable_url(value)
        if url:
            yield path, value, url

def canvas_node_title(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    return str(node.get("title") or node.get("name") or node.get("label") or node.get("type") or "节点")[:120]

def canvas_node_generation_meta(node: Any, asset_kind: str = "") -> Tuple[str, str]:
    if not isinstance(node, dict):
        return "", ""
    settings = node.get("runSettings") if isinstance(node.get("runSettings"), dict) else {}
    is_video = (asset_kind == "video") or (str(node.get("outputKind") or "").strip() == "video") or (str(settings.get("apiKind") or "").strip() == "video")
    provider = ""
    model = ""

    if is_video:
        for key in ("videoProvider", "video_provider", "apiProvider", "provider_id", "provider"):
            val = str(settings.get(key) or node.get(key) or "").strip()
            if val:
                provider = val
                break
        for key in ("videoModel", "video_model", "model", "image_model", "imageModel"):
            val = str(settings.get(key) or node.get(key) or "").strip()
            if val:
                model = val
                break
    else:
        for key in ("apiProvider", "provider_id", "provider", "videoProvider"):
            val = str(node.get(key) or settings.get(key) or "").strip()
            if val:
                provider = val
                break
        for key in ("model", "image_model", "imageModel", "msCustomModel", "videoModel"):
            val = str(node.get(key) or settings.get(key) or "").strip()
            if val:
                model = val
                break

    if not provider or not model:
        stack = [node]
        seen = 0
        while stack and seen < 40:
            cur = stack.pop(0)
            seen += 1
            if isinstance(cur, dict):
                if not provider:
                    keys = ("videoProvider", "provider_id") if is_video else ("provider_id", "videoProvider")
                    for key in keys:
                        value = str(cur.get(key) or "").strip()
                        if value:
                            provider = value
                            break
                if not model:
                    keys = ("videoModel", "model") if is_video else ("model", "videoModel")
                    for key in keys:
                        value = str(cur.get(key) or "").strip()
                        if value:
                            model = value
                            break
                for value in cur.values():
                    if isinstance(value, (dict, list)):
                        stack.append(value)
            elif isinstance(cur, list):
                stack.extend(item for item in cur if isinstance(item, (dict, list)))
            if provider and model:
                break
    if not model and not provider:
        workflow = str(node.get("workflow") or "").strip()
        if workflow:
            model = re.sub(r"\.json$", "", workflow, flags=re.I)
            provider = "comfy-workflow"
    return provider, model

def extract_canvas_assets(canvas: Dict[str, Any]) -> List[Dict[str, Any]]:
    record = canvas_record(canvas)
    canvas_id = str(record.get("id") or "")
    items = []
    seen = set()
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []

    node_by_id = {str(n.get("id")): n for n in nodes if isinstance(n, dict) and n.get("id")}
    upstream_nodes_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for c in canvas.get("connections", []):
        if isinstance(c, dict):
            c_to = str(c.get("to") or "")
            c_from = str(c.get("from") or "")
            if c_to and c_from in node_by_id:
                upstream_nodes_by_id.setdefault(c_to, []).append(node_by_id[c_from])

    logs_meta: Dict[str, Tuple[str, str]] = {}
    for log in (canvas.get("logs") or []):
        if isinstance(log, dict):
            p = str(log.get("platform") or log.get("request", {}).get("provider_name") or log.get("request", {}).get("provider_id") or "").strip()
            m = str(log.get("model") or log.get("request", {}).get("model") or "").strip()
            for out in log.get("outputs", []):
                if out:
                    out_str = str(out).strip()
                    logs_meta[out_str] = (p, m)
                    fname = os.path.basename(out_str)
                    if fname:
                        logs_meta[fname] = (p, m)

    task_history_meta = get_task_history_meta_index()

    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or f"node_{node_index}")
        node_title = canvas_node_title(node)
        for field_path, raw, url in iter_canvas_asset_values(node):
            dedupe_key = url
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            kind = canvas_asset_kind(raw, url)
            if kind not in {"image", "video", "audio", "text"}:
                continue
            fallback = f"{record.get('title') or 'canvas'}-{len(items) + 1}"
            item = {
                "id": hashlib.sha1(f"{canvas_id}:{url}".encode("utf-8")).hexdigest()[:24],
                "url": url,
                "name": canvas_asset_name(raw, url, fallback),
                "kind": kind,
                "canvas_id": canvas_id,
                "canvas_title": record.get("title") or "未命名画布",
                "canvas_kind": record.get("kind") or "classic",
                "canvas_icon": record.get("icon") or "layers",
                "canvas_owner": record.get("owner") or "",
                "canvas_color": record.get("color") or "",
                "canvas_created_at": record.get("created_at") or 0,
                "canvas_updated_at": record.get("updated_at") or 0,
                "node_id": node_id,
                "node_title": node_title,
                "node_type": str(node.get("type") or ""),
                "source_path": field_path,
                "created_at": node.get("created_at") or record.get("updated_at") or record.get("created_at") or 0,
            }
            provider_id, model_name = canvas_node_generation_meta(node, kind)

            # 1. Exact historical record from task_history.jsonl
            if not provider_id or not model_name:
                th = task_history_meta.get(url) or task_history_meta.get(os.path.basename(url))
                if th:
                    if not provider_id and th[0]:
                        provider_id = th[0]
                    if not model_name and th[1]:
                        model_name = th[1]

            # 2. Check raw item dict
            if isinstance(raw, dict):
                if not provider_id:
                    provider_id = raw.get("provider") or raw.get("provider_id") or raw.get("run", {}).get("provider_name") or raw.get("run", {}).get("provider_id") or ""
                if not model_name:
                    model_name = raw.get("model") or raw.get("run", {}).get("model") or ""

            # 3. Check canvas logs
            if not provider_id or not model_name:
                log_meta = logs_meta.get(url) or logs_meta.get(os.path.basename(url))
                if log_meta:
                    if not provider_id and log_meta[0]:
                        provider_id = log_meta[0]
                    if not model_name and log_meta[1]:
                        model_name = log_meta[1]

            # 4. Check connected upstream generator node(s)
            if not provider_id or not model_name:
                for upstream in upstream_nodes_by_id.get(node_id, []):
                    up_p, up_m = canvas_node_generation_meta(upstream, kind)
                    if not provider_id and up_p:
                        provider_id = up_p
                    if not model_name and up_m:
                        model_name = up_m
                    if provider_id and model_name:
                        break

            # 5. Check image node explicit fields
            if node.get("type") == "image":
                if not provider_id:
                    provider_id = node.get("provider") or node.get("provider_id") or ""
                if not model_name:
                    model_name = node.get("model") or node.get("modelLabel") or ""

            if provider_id:
                item["provider_id"] = provider_id
            if model_name:
                item["model"] = model_name
            prompt_val = ""
            if isinstance(raw, dict):
                prompt_val = str(raw.get("prompt") or raw.get("positive") or raw.get("text") or "").strip()
            if not prompt_val:
                th = task_history_meta.get(url) or task_history_meta.get(os.path.basename(url))
                if th and len(th) > 2 and th[2]:
                    prompt_val = th[2]
            if not prompt_val:
                for upstream in upstream_nodes_by_id.get(node_id, []):
                    u_text = str(upstream.get("text") or upstream.get("prompt") or "").strip()
                    if u_text:
                        prompt_val = u_text
                        break
                    for gen_up in upstream_nodes_by_id.get(str(upstream.get("id")), []):
                        if gen_up.get("type") == "prompt" and gen_up.get("text"):
                            prompt_val = str(gen_up.get("text")).strip()
                            break
                    if prompt_val:
                        break
            if prompt_val:
                item["prompt"] = prompt_val
            if isinstance(raw, dict):
                for key in ("natural_w", "natural_h", "width", "height", "size", "duration", "runMs"):
                    if raw.get(key) is not None:
                        item[key] = raw.get(key)
            items.append(item)
    return items


def canvas_assets_index() -> Dict[str, Any]:
    canvases = []
    items = []
    canvas_counts = {"all": 0, "smart": 0, "classic": 0}
    item_counts = {"all": 0, "smart": 0, "classic": 0}
    cleanup_expired_canvas_trash()
    for filename in os.listdir(CANVAS_DIR):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(CANVAS_DIR, filename), "r", encoding="utf-8") as f:
                canvas = json.load(f)
        except Exception:
            continue
        if canvas.get("deleted_at"):
            continue
        record = canvas_record(canvas)
        canvas_items = extract_canvas_assets(canvas)
        record["asset_count"] = len(canvas_items)
        canvases.append(record)
        items.extend(canvas_items)
        kind = record.get("kind") or "classic"
        canvas_counts["all"] += 1
        canvas_counts[kind] = canvas_counts.get(kind, 0) + 1
        item_counts["all"] += len(canvas_items)
        item_counts[kind] = item_counts.get(kind, 0) + len(canvas_items)
    canvases.sort(key=lambda item: (0 if item.get("pinned") else 1, -int(item.get("updated_at") or item.get("created_at") or 0)))
    items.sort(key=lambda item: int(item.get("canvas_updated_at") or item.get("created_at") or 0), reverse=True)
    categories = [
        {"id": "all", "name": "全部画布", "count": item_counts.get("all", 0), "canvas_count": canvas_counts.get("all", 0)},
        {"id": "smart", "name": "智能画布", "count": item_counts.get("smart", 0), "canvas_count": canvas_counts.get("smart", 0)},
        {"id": "classic", "name": "全能画布", "count": item_counts.get("classic", 0), "canvas_count": canvas_counts.get("classic", 0)},
    ]
    return {"categories": categories, "canvases": canvases, "items": items}

def canvas_workflow_collect_resource_refs(value: Any, found: Optional[List[str]] = None) -> List[str]:
    if found is None:
        found = []
    if isinstance(value, dict):
        for item in value.values():
            canvas_workflow_collect_resource_refs(item, found)
    elif isinstance(value, list):
        for item in value:
            canvas_workflow_collect_resource_refs(item, found)
    elif isinstance(value, str):
        text = value.strip()
        if (text.startswith("/assets/") or text.startswith("/output/")) and output_file_from_url(text):
            found.append(text)
    return found

def canvas_workflow_unique_archive_name(base: str, used: Set[str]) -> str:
    safe = sanitize_export_filename(base, "resource.bin")
    name, ext = os.path.splitext(safe)
    archive = safe
    idx = 2
    while archive in used:
        archive = f"{name}-{idx}{ext}"
        idx += 1
    used.add(archive)
    return archive

def canvas_workflow_replace_strings(value: Any, mapping: Dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: canvas_workflow_replace_strings(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [canvas_workflow_replace_strings(item, mapping) for item in value]
    if isinstance(value, str):
        return mapping.get(value, value)
    return value

def canvas_workflow_payload(nodes: List[Dict[str, Any]], connections: List[Dict[str, Any]], resources: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "format": "infinite-canvas-workflow",
        "version": 1,
        "exported_at": now_ms(),
        "nodes": nodes or [],
        "connections": connections or [],
        "resources": resources or [],
    }

def build_canvas_workflow_archive(payload: CanvasWorkflowExportRequest) -> Tuple[bytes, Dict[str, Any]]:
    nodes_payload = payload.nodes or []
    connections_payload = payload.connections or []
    if not nodes_payload:
        raise HTTPException(status_code=400, detail="没有可导出的节点")
    buffer = BytesIO()
    resources = []
    used = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if payload.include_resources:
            for url in canvas_workflow_collect_resource_refs(nodes_payload):
                if any(item.get("url") == url for item in resources):
                    continue
                path = output_file_from_url(url)
                if not path or not os.path.isfile(path):
                    continue
                archive_name = canvas_workflow_unique_archive_name(os.path.basename(path), used)
                archive_path = f"resources/{archive_name}"
                zf.write(path, archive_path)
                resources.append({
                    "url": url,
                    "archive": archive_path,
                    "name": os.path.basename(path),
                    "size": os.path.getsize(path),
                })
        workflow = canvas_workflow_payload(nodes_payload, connections_payload, resources)
        zf.writestr("workflow.json", json.dumps(workflow, ensure_ascii=False, indent=2))
    buffer.seek(0)
    return buffer.getvalue(), {"resources": resources, "node_count": len(nodes_payload), "connection_count": len(connections_payload)}

def smart_group_export_folder(folder: str, group_name: str) -> str:
    text = str(folder or "").strip()
    base = os.path.abspath(BASE_DIR)
    if text:
        path = os.path.abspath(os.path.expanduser(text))
        try:
            if os.path.commonpath([path, base]) != base:
                raise HTTPException(status_code=400, detail="导出目录必须位于项目目录内")
        except ValueError:
            raise HTTPException(status_code=400, detail="导出目录必须位于项目目录内")
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe_group = sanitize_export_filename(group_name or "group", "group")
        path = os.path.abspath(os.path.join(OUTPUT_DIR, "smart-groups", f"{safe_group}-{stamp}"))
    os.makedirs(path, exist_ok=True)
    return path


# ======================================================================
# API 路由端点实现
# ======================================================================

# --- 1. 画布资产提取与工作流导入导出 ---
@router.get("/api/canvas-assets")
async def api_list_canvas_assets():
    return await asyncio.to_thread(canvas_assets_index)

@router.post("/api/canvas-assets/check")
def api_check_canvas_assets(payload: CanvasAssetCheckRequest):
    result = {}
    for url in payload.urls[:3000]:
        text = str(url or "").strip()
        if not text:
            continue
        if text.startswith("/output/") or text.startswith("/assets/"):
            result[text] = bool(output_file_from_url(text))
        else:
            result[text] = True
    return {"exists": result}

@router.post("/api/canvas-assets/download")
def api_download_canvas_assets(payload: CanvasAssetDownloadRequest):
    buffer = BytesIO()
    used_names = set()
    count = 0
    raw_items = payload.items or [{"url": url} for url in payload.urls]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for raw in raw_items[:1000]:
            if isinstance(raw, dict):
                text = str(raw.get("url") or "").strip()
                requested_name = str(raw.get("name") or "").strip()
            else:
                text = str(raw or "").strip()
                requested_name = ""
            if not text:
                continue
            path = output_file_from_url(text)
            content = None
            content_type = ""
            if path and os.path.isfile(path):
                base = sanitize_export_filename(requested_name or os.path.basename(path), os.path.basename(path) or f"image-{count + 1}.png")
            else:
                local_by_name = local_media_file_by_basename(filename_from_media_url(text, ""))
                if local_by_name and os.path.isfile(local_by_name):
                    path = local_by_name
                    base = sanitize_export_filename(requested_name or os.path.basename(path), os.path.basename(path) or f"image-{count + 1}.png")
                else:
                    try:
                        remote = fetch_remote_media_bytes(text)
                    except Exception:
                        remote = None
                    if not remote:
                        continue
                    content, content_type = remote
                    base = sanitize_export_filename(requested_name or filename_from_media_url(text, f"image-{count + 1}.bin"), f"image-{count + 1}.bin")
            name, ext = os.path.splitext(base)
            archive_name = base
            suffix = 2
            while archive_name in used_names:
                archive_name = f"{name}-{suffix}{ext}"
                suffix += 1
            used_names.add(archive_name)
            if path and os.path.isfile(path):
                zf.write(path, archive_name)
            else:
                zf.writestr(archive_name, content)
            count += 1
    if count <= 0:
        raise HTTPException(status_code=404, detail="没有可下载的本地图片")
    buffer.seek(0)
    filename = re.sub(r'[\\/:*?"<>|]+', "_", payload.filename or "canvas-output-images.zip")
    if not filename.lower().endswith(".zip"):
        filename += ".zip"
    encoded = urllib.parse.quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    return Response(buffer.getvalue(), media_type="application/zip", headers=headers)

@router.post("/api/canvas-workflows/export")
def api_export_canvas_workflow(payload: CanvasWorkflowExportRequest):
    archive, _ = build_canvas_workflow_archive(payload)
    filename = sanitize_export_filename(payload.filename or "canvas-workflow.zip", "canvas-workflow.zip")
    if not filename.lower().endswith(".zip"):
        filename += ".zip"
    encoded = urllib.parse.quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    return Response(archive, media_type="application/zip", headers=headers)

@router.post("/api/canvas-workflows/export-to-library")
def api_export_canvas_workflow_to_library(payload: CanvasWorkflowExportRequest):
    archive, meta = build_canvas_workflow_archive(payload)
    filename = sanitize_export_filename(payload.filename or "canvas-workflow.zip", "canvas-workflow.zip")
    if not filename.lower().endswith(".zip"):
        filename += ".zip"
    lib = load_asset_library()
    _, cat = asset_library_workflow_category(lib, payload.library_id, payload.category_id)
    item = make_workflow_library_item_from_bytes(archive, filename, payload.name or os.path.splitext(filename)[0])
    item["node_count"] = meta.get("node_count") or len(payload.nodes or [])
    item["connection_count"] = meta.get("connection_count") or len(payload.connections or [])
    item["resource_count"] = len(meta.get("resources") or [])
    cat.setdefault("items", []).append(item)
    save_asset_library(lib)
    return {"library": lib, "item": item}

@router.post("/api/canvas-workflows/import")
async def api_import_canvas_workflow(file: UploadFile = File(...)):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件为空")
    name = str(file.filename or "").lower()
    resource_mapping = {}
    workflow = None
    try:
        if name.endswith(".zip") or raw[:2] == b"PK":
            with zipfile.ZipFile(BytesIO(raw), "r") as zf:
                candidates = [n for n in zf.namelist() if n.lower().endswith("workflow.json")]
                workflow_name = "workflow.json" if "workflow.json" in zf.namelist() else (candidates[0] if candidates else "")
                if not workflow_name:
                    raise HTTPException(status_code=400, detail="压缩包中没有 workflow.json")
                workflow = json.loads(zf.read(workflow_name).decode("utf-8-sig"))
                stamp = time.strftime("%Y%m%d-%H%M%S")
                import_dir = os.path.join(OUTPUT_INPUT_DIR, f"workflow_import_{stamp}_{uuid.uuid4().hex[:6]}")
                os.makedirs(import_dir, exist_ok=True)
                for res in workflow.get("resources") or []:
                    archive = str(res.get("archive") or "").replace("\\", "/").lstrip("/")
                    if not archive or archive not in zf.namelist():
                        continue
                    base = sanitize_export_filename(res.get("name") or os.path.basename(archive), os.path.basename(archive) or "resource.bin")
                    target = os.path.join(import_dir, f"{uuid.uuid4().hex[:8]}_{base}")
                    with zf.open(archive) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    rel = os.path.relpath(target, ASSETS_DIR).replace("\\", "/")
                    new_url = f"/assets/{rel}"
                    old_url = str(res.get("url") or "").strip()
                    if old_url:
                        resource_mapping[old_url] = new_url
                    resource_mapping[archive] = new_url
                    resource_mapping[f"./{archive}"] = new_url
                    resource_mapping[os.path.basename(archive)] = new_url
        else:
            workflow = json.loads(raw.decode("utf-8-sig"))
    except HTTPException:
        raise
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="无法读取压缩包") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法解析工作流文件：{exc}") from exc
    if isinstance(workflow, list):
        workflow = {"nodes": workflow, "connections": []}
    if not isinstance(workflow, dict):
        raise HTTPException(status_code=400, detail="工作流格式不正确")
    nodes_payload = workflow.get("nodes")
    connections_payload = workflow.get("connections")
    if nodes_payload is None and isinstance(workflow.get("workflow"), dict):
        nodes_payload = workflow["workflow"].get("nodes")
        connections_payload = workflow["workflow"].get("connections")
    if not isinstance(nodes_payload, list):
        raise HTTPException(status_code=400, detail="工作流 JSON 缺少 nodes")
    if not isinstance(connections_payload, list):
        connections_payload = []
    if resource_mapping:
        nodes_payload = canvas_workflow_replace_strings(nodes_payload, resource_mapping)
        connections_payload = canvas_workflow_replace_strings(connections_payload, resource_mapping)
    return {
        "workflow": canvas_workflow_payload(nodes_payload, connections_payload, workflow.get("resources") or []),
        "nodes": nodes_payload,
        "connections": connections_payload,
        "resource_map": resource_mapping,
    }

@router.post("/api/smart-canvas/group-export")
def api_export_smart_canvas_group(payload: SmartCanvasGroupExportRequest):
    target_dir = smart_group_export_folder(payload.folder, payload.group_name)
    used_names = set()
    count = 0
    text_index = 1
    for item in payload.items[:2000]:
        kind = str(item.kind or "").lower()
        if kind == "text":
            text = str(item.text or "")
            if not text.strip():
                continue
            base = sanitize_export_filename(item.name or f"{text_index}.txt", f"{text_index}.txt")
            if not base.lower().endswith(".txt"):
                base += ".txt"
            text_index += 1
            name, ext = os.path.splitext(base)
            out_name = base
            suffix = 2
            while out_name in used_names:
                out_name = f"{name}-{suffix}{ext}"
                suffix += 1
            used_names.add(out_name)
            with open(os.path.join(target_dir, out_name), "w", encoding="utf-8") as f:
                f.write(text)
            count += 1
            continue
        src = output_file_from_url(item.url)
        if not src or not os.path.isfile(src):
            continue
        base = sanitize_export_filename(item.name or os.path.basename(src), os.path.basename(src) or f"asset-{count + 1}")
        name, ext = os.path.splitext(base)
        if not ext:
            _, src_ext = os.path.splitext(src)
            ext = src_ext or ".bin"
            base = name + ext
        out_name = base
        suffix = 2
        while out_name in used_names:
            out_name = f"{name}-{suffix}{ext}"
            suffix += 1
        used_names.add(out_name)
        shutil.copy2(src, os.path.join(target_dir, out_name))
        count += 1
    if count <= 0:
        raise HTTPException(status_code=404, detail="没有可导出的内容")
    return {"ok": True, "folder": target_dir, "count": count}


# --- 2. 存储设置与文件浏览 ---
@router.get("/api/storage-settings")
def api_get_storage_settings():
    settings = load_storage_settings()
    return {
        "dirs": settings["dirs"],
        "defaults": {key: os.path.abspath(value) for key, value in DEFAULT_STORAGE_DIRS.items()},
    }

@router.patch("/api/storage-settings")
def api_update_storage_settings(payload: Dict[str, str]):
    return save_storage_settings(payload or {})

@router.get("/api/storage-files")
def api_list_storage_files(kind: str = "generated", offset: int = 0, limit: int = 80):
    root = storage_kind_dir(kind)
    os.makedirs(root, exist_ok=True)
    offset = max(0, int(offset or 0))
    limit = max(20, min(200, int(limit or 80)))
    raw_entries = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted([d for d in dirs if not d.startswith(".") and not d.startswith("._")], key=str.lower)
        for name in sorted(files, key=str.lower):
            if name.startswith(".") or name.startswith("._"):
                continue
            if os.path.splitext(name)[1].lower() not in STORAGE_IMAGE_EXTS:
                continue
            full_path = os.path.join(current, name)
            try:
                mtime = os.stat(full_path).st_mtime
                raw_entries.append((mtime, full_path))
            except OSError:
                continue
    raw_entries.sort(key=lambda entry: entry[0], reverse=True)
    total = len(raw_entries)
    page_entries = raw_entries[offset:offset + limit]
    page_items = []
    for _, full_path in page_entries:
        item = storage_file_item(kind, root, full_path)
        if item:
            page_items.append(item)
    return {
        "kind": kind,
        "root": root,
        "items": page_items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page_items) < total,
    }

@router.get("/api/storage-files/{kind}/{rel_path:path}")
def api_get_storage_file(kind: str, rel_path: str):
    path = storage_file_path(kind, rel_path)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, media_type=content_type_for_path(path))

@router.post("/api/storage-files/delete")
def api_delete_storage_files(payload: Dict[str, Any]):
    kind = str((payload or {}).get("kind") or "").strip()
    rels = [str(item or "").strip() for item in ((payload or {}).get("items") or []) if str(item or "").strip()]
    if not rels:
        raise HTTPException(status_code=400, detail="请选择要删除的文件")
    removed = 0
    for rel in rels:
        path = storage_file_path(kind, rel)
        if not path or not os.path.isfile(path):
            continue
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    return {"removed": removed}

@router.get("/api/asset-classification-prompt")
def api_get_asset_classification_prompt():
    current = load_asset_classification_prompt()
    return {
        "prompt": current,
        "default_prompt": ASSET_CLASSIFICATION_PROMPT,
        "custom": current.strip() != ASSET_CLASSIFICATION_PROMPT.strip(),
    }

@router.patch("/api/asset-classification-prompt")
def api_update_asset_classification_prompt(payload: Dict[str, str]):
    prompt = save_asset_classification_prompt((payload or {}).get("prompt") or "")
    return {"prompt": prompt, "custom": True}

@router.get("/api/media-preview")
async def api_media_preview(url: str, w: int = 512):
    path = output_file_from_url(url)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="媒体文件不存在")

    width = max(64, min(2048, int(w or 512)))
    webp_path, png_path = media_preview_cache_paths(path, width)

    if os.path.exists(webp_path):
        return FileResponse(webp_path, media_type="image/webp")
    if os.path.exists(png_path):
        return FileResponse(png_path, media_type="image/png")

    def _build_preview():
        os.makedirs(MEDIA_PREVIEW_DIR, exist_ok=True)
        if is_video_preview_file(path):
            img = generate_video_preview_image(path, width)
        else:
            with Image.open(path) as source:
                img = ImageOps.exif_transpose(source)
                img.thumbnail((width, width), Image.LANCZOS)
                img = img.convert("RGBA" if image_has_alpha(img) else "RGB")
        try:
            img.save(webp_path, format="WEBP", quality=80, method=1)
            return webp_path, "image/webp"
        except Exception:
            img.save(png_path, format="PNG")
            return png_path, "image/png"

    try:
        out_path, media_type = await asyncio.to_thread(_build_preview)
        return FileResponse(out_path, media_type=media_type)
    except Exception as exc:
        raise HTTPException(status_code=415, detail=f"无法生成预览图：{exc}") from exc

@router.get("/api/image-jpeg")
async def api_image_jpeg(url: str, w: int = 0):
    path = output_file_from_url(url)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    width = max(0, min(4096, int(w or 0)))
    stat = os.stat(path)
    key = hashlib.sha1(f"{os.path.abspath(path)}|{stat.st_mtime_ns}|{stat.st_size}|{width}|jpg".encode("utf-8", "ignore")).hexdigest()
    cache_path = os.path.join(MEDIA_PREVIEW_DIR, f"{key}.jpg")
    if os.path.exists(cache_path):
        return FileResponse(cache_path, media_type="image/jpeg")

    def _build():
        os.makedirs(MEDIA_PREVIEW_DIR, exist_ok=True)
        with Image.open(path) as src:
            img = ImageOps.exif_transpose(src)
            if width:
                img.thumbnail((width, width), Image.LANCZOS)
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                rgba = img.convert("RGBA")
                bg.paste(rgba, mask=rgba.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            img.save(cache_path, format="JPEG", quality=86)
        return cache_path

    try:
        out_path = await asyncio.to_thread(_build)
        return FileResponse(out_path, media_type="image/jpeg")
    except Exception as exc:
        raise HTTPException(status_code=415, detail=f"无法转换图片：{exc}") from exc


# --- 3. 本地素材 (Local Assets) ---
@router.get("/api/local-assets")
def api_list_local_assets():
    tree, items = _local_upload_tree_and_items()
    return {"items": items, "tree": tree}

@router.post("/api/local-assets/upload")
async def api_upload_local_assets(files: List[UploadFile] = File(...), folder: str = Form("")):
    uploaded = []
    folder_rel, folder_abs = _local_upload_safe_folder(folder)
    os.makedirs(folder_abs, exist_ok=True)
    for file in files:
        content = await file.read()
        if not content:
            continue
        kind, ext = _local_upload_kind_ext(file.filename, file.content_type)
        if kind is None:
            continue
        base = os.path.splitext(os.path.basename(file.filename or "file"))[0]
        base = re.sub(r"[^0-9A-Za-z一-鿿._-]+", "_", base).strip("_") or "file"
        base = base[:60]
        filename = f"up_{uuid.uuid4().hex[:12]}_{base}{ext}"
        rel_name = f"{folder_rel}/{filename}".lstrip("/")
        path = os.path.join(folder_abs, filename)
        with open(path, "wb") as f:
            f.write(content)
        if kind == "image":
            classification = await classify_asset_image_best_effort(path)
            if classification:
                _write_local_upload_classification(rel_name, classification)
        uploaded.append(_local_upload_item(rel_name))
    return {"files": uploaded}

@router.post("/api/local-assets/import-urls")
async def api_import_local_assets_from_urls(payload: LocalAssetUrlImportRequest):
    import base64
    uploaded = []
    results = []
    folder_rel, folder_abs = _local_upload_safe_folder(payload.folder)
    os.makedirs(folder_abs, exist_ok=True)
    for entry in (payload.items or [])[:200]:
        src_url = str(entry.url or "").strip()
        inline_data = str(entry.data or "").strip()
        result = {"url": src_url, "ok": False, "file": "", "error": ""}
        if not inline_data and not src_url.startswith(("http://", "https://")):
            result["error"] = "仅支持 http(s) 素材地址"
            results.append(result)
            continue
        try:
            if inline_data:
                content_type = str(entry.content_type or "").split(";", 1)[0].strip().lower()
                b64 = inline_data
                if inline_data.startswith("data:"):
                    header, _, b64 = inline_data.partition(",")
                    if not content_type:
                        content_type = header[5:].split(";", 1)[0].strip().lower()
                try:
                    content = base64.b64decode(b64, validate=False)
                except Exception:
                    raise HTTPException(status_code=400, detail="素材数据无法解码")
                name_path = urllib.parse.urlparse(src_url).path
            else:
                content, content_type = await safe_download_bytes(
                    src_url,
                    timeout=60.0,
                    max_bytes=50 * 1024 * 1024,
                    headers={"User-Agent": "Infinite-Canvas-Asset-Importer/1.0"},
                )
                content_type = content_type.split(";", 1)[0].strip().lower()
                name_path = urllib.parse.urlparse(src_url).path
            kind, ext = _local_upload_kind_ext(name_path, content_type)
            if kind == "image":
                real = _sniff_image_ext_bytes(content[:16])
                if real and not (real == ".jpg" and ext == ".jpeg"):
                    ext = real
            if kind not in ("image", "video"):
                raise HTTPException(status_code=400, detail=f"不是图片或视频资源：{content_type or src_url}")
            if not content:
                raise HTTPException(status_code=400, detail="素材内容为空")
            if entry.name:
                base = os.path.splitext(entry.name)[0]
            else:
                base = os.path.splitext(os.path.basename(urllib.parse.unquote(name_path)))[0]
            base = base or ("web-video" if kind == "video" else "web-image")
            base = re.sub(r"[^0-9A-Za-z一-鿿._-]+", "_", base).strip("_") or ("web-video" if kind == "video" else "web-image")
            base = base[:60]
            if ext and base.lower().endswith(ext.lower()):
                base = base[:-len(ext)].rstrip(".") or ("web-video" if kind == "video" else "web-image")
            filename = f"up_{uuid.uuid4().hex[:12]}_{base}{ext}"
            rel_name = f"{folder_rel}/{filename}".lstrip("/")
            path = os.path.join(folder_abs, filename)
            with open(path, "wb") as f:
                f.write(content)
            if payload.classify and kind == "image":
                classification = await classify_asset_image_best_effort(path, payload.provider, payload.model, payload.ms_model, payload.prompt)
                if classification:
                    _write_local_upload_classification(rel_name, classification)
            item = _local_upload_item(rel_name)
            uploaded.append(item)
            result.update({"ok": True, "file": rel_name, "item": item})
        except HTTPException as exc:
            result["error"] = str(exc.detail or "导入失败")
        except Exception as exc:
            result["error"] = str(exc) or "导入失败"
        results.append(result)
    return {"ok": True, "count": len(uploaded), "files": uploaded, "items": results}

@router.post("/api/local-assets/folders")
def api_create_local_asset_folder(payload: LocalAssetFolderRequest, request: Request):
    ensure_same_origin_request(request)
    parent_rel, parent_abs = _local_upload_safe_folder(payload.parent)
    if not os.path.isdir(parent_abs):
        raise HTTPException(status_code=404, detail="父文件夹不存在")
    name = _local_upload_safe_folder_name(payload.name)
    rel = f"{parent_rel}/{name}".lstrip("/")
    _, abs_path = _local_upload_safe_folder(rel)
    if os.path.exists(abs_path):
        raise HTTPException(status_code=400, detail="同名文件夹已存在")
    os.makedirs(abs_path, exist_ok=False)
    tree, items = _local_upload_tree_and_items()
    return {"ok": True, "folder": {"path": rel, "name": name}, "tree": tree, "items": items}

@router.patch("/api/local-assets/folders")
def api_rename_local_asset_folder(payload: LocalAssetFolderRequest, request: Request):
    ensure_same_origin_request(request)
    rel, abs_path = _local_upload_safe_folder(payload.path)
    if not rel:
        raise HTTPException(status_code=400, detail="根目录不能重命名")
    if not os.path.isdir(abs_path):
        raise HTTPException(status_code=404, detail="文件夹不存在")
    name = _local_upload_safe_folder_name(payload.name)
    parent = os.path.dirname(rel).replace("\\", "/")
    new_rel = f"{parent}/{name}".lstrip("/")
    _, new_abs = _local_upload_safe_folder(new_rel)
    if os.path.exists(new_abs):
        raise HTTPException(status_code=400, detail="同名文件夹已存在")
    os.rename(abs_path, new_abs)
    tree, items = _local_upload_tree_and_items()
    return {"ok": True, "folder": {"path": new_rel, "name": name}, "tree": tree, "items": items}

@router.patch("/api/local-assets/items")
def api_rename_local_asset_item(payload: LocalAssetRenameRequest, request: Request):
    ensure_same_origin_request(request)
    rel, abs_path = _local_upload_safe_path(payload.path)
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="本地素材不存在")
    kind, ext = _local_upload_kind_ext(rel, "")
    if kind is None:
        raise HTTPException(status_code=400, detail="不支持的素材类型")
    new_stem = _local_upload_safe_file_stem(payload.name)
    old_ext = os.path.splitext(rel)[1] or ext
    parent = os.path.dirname(rel).replace("\\", "/")
    new_rel = f"{parent}/{new_stem}{old_ext}".lstrip("/")
    if new_rel == rel:
        tree, items = _local_upload_tree_and_items()
        return {"ok": True, "item": _local_upload_item(rel), "tree": tree, "items": items}
    _, new_abs = _local_upload_abs(new_rel)
    if os.path.exists(new_abs):
        raise HTTPException(status_code=400, detail="同名素材已存在")
    os.rename(abs_path, new_abs)
    old_caption = _local_upload_caption_path(rel)
    new_caption = _local_upload_caption_path(new_rel)
    if os.path.isfile(old_caption) and not os.path.exists(new_caption):
        os.rename(old_caption, new_caption)
    old_classification = _local_upload_classification_path(rel)
    new_classification = _local_upload_classification_path(new_rel)
    if os.path.isfile(old_classification) and not os.path.exists(new_classification):
        os.rename(old_classification, new_classification)
    tree, items = _local_upload_tree_and_items()
    return {"ok": True, "item": _local_upload_item(new_rel), "old_path": rel, "tree": tree, "items": items}

@router.post("/api/local-assets/delete")
def api_delete_local_assets(payload: dict, request: Request):
    ensure_same_origin_request(request)
    names = payload.get("names") if isinstance(payload, dict) else None
    if not isinstance(names, list):
        names = []
    deleted = []
    for name in names:
        try:
            rel, path = _local_upload_safe_path(name)
        except HTTPException:
            continue
        if os.path.isfile(path):
            try:
                os.remove(path)
                txt_path = _local_upload_caption_path(rel)
                if os.path.isfile(txt_path):
                    os.remove(txt_path)
                cls_path = _local_upload_classification_path(rel)
                if os.path.isfile(cls_path):
                    os.remove(cls_path)
                deleted.append(rel)
            except OSError:
                pass
    return {"deleted": deleted}

@router.post("/api/local-assets/move")
def api_move_local_assets(payload: dict, request: Request):
    ensure_same_origin_request(request)
    names = payload.get("names") if isinstance(payload, dict) else None
    if not isinstance(names, list) or not names:
        raise HTTPException(status_code=400, detail="没有选择素材")
    folder_value = str(payload.get("folder") or "").strip() if isinstance(payload, dict) else ""
    target_rel, target_abs = _local_upload_safe_folder(folder_value)
    if target_rel and not os.path.isdir(target_abs):
        raise HTTPException(status_code=404, detail="目标文件夹不存在")
    moved = 0
    for name in names:
        try:
            rel, abs_path = _local_upload_safe_path(name)
        except HTTPException:
            continue
        if not os.path.isfile(abs_path):
            continue
        base = os.path.basename(rel)
        new_rel = f"{target_rel}/{base}".lstrip("/") if target_rel else base
        if new_rel == rel:
            continue
        _, new_abs = _local_upload_abs(new_rel)
        if os.path.exists(new_abs):
            stem, ext = os.path.splitext(base)
            base = f"{stem}_{uuid.uuid4().hex[:6]}{ext}"
            new_rel = f"{target_rel}/{base}".lstrip("/") if target_rel else base
            _, new_abs = _local_upload_abs(new_rel)
        try:
            os.makedirs(os.path.dirname(new_abs), exist_ok=True)
            os.rename(abs_path, new_abs)
            for src_sib, dst_sib in (
                (_local_upload_caption_path(rel), _local_upload_caption_path(new_rel)),
                (_local_upload_classification_path(rel), _local_upload_classification_path(new_rel)),
            ):
                if os.path.isfile(src_sib) and not os.path.exists(dst_sib):
                    os.rename(src_sib, dst_sib)
            moved += 1
        except OSError:
            continue
    tree, items = _local_upload_tree_and_items()
    return {"ok": True, "moved": moved, "items": items, "tree": tree}

@router.post("/api/local-assets/caption")
async def api_caption_local_assets(payload: LocalAssetCaptionRequest):
    if not _image_captioner:
        raise HTTPException(status_code=501, detail="图片反推服务未就绪")
    prompt = (payload.prompt or "描述图片").strip() or "描述图片"
    items = []
    ok_count = 0
    for name in (payload.names or [])[:100]:
        item = {"name": name, "ok": False, "caption": "", "caption_file": "", "error": ""}
        try:
            filename, path = _local_upload_safe_path(name)
            if not os.path.isfile(path):
                raise HTTPException(status_code=404, detail="文件不存在")
            kind, _ = _local_upload_kind_ext(filename, "")
            if kind != "image":
                raise HTTPException(status_code=400, detail="仅支持图片素材反推提示词")
            caption, resolved_model = await _image_captioner(
                path,
                prompt,
                payload.provider,
                payload.model,
                payload.ms_model,
            )
            txt_path = _local_upload_caption_path(filename)
            with open(txt_path, "w", encoding="utf-8", newline="") as f:
                f.write(caption)
            item.update({
                "ok": True,
                "name": filename,
                "caption": caption,
                "caption_file": os.path.basename(txt_path),
                "model": resolved_model,
            })
            ok_count += 1
        except HTTPException as exc:
            item["error"] = str(exc.detail or "反推失败")
        except Exception as exc:
            item["error"] = str(exc) or "反推失败"
        items.append(item)
    return {"ok": True, "count": ok_count, "items": items}

@router.post("/api/local-assets/classify")
async def api_classify_local_assets(payload: LocalAssetClassifyRequest):
    if not _image_classifier:
        raise HTTPException(status_code=501, detail="图片分类服务未就绪")
    items = []
    ok_count = 0
    for name in (payload.names or [])[:80]:
        item = {"name": name, "ok": False, "classification": None, "classification_file": "", "error": ""}
        try:
            filename, path = _local_upload_safe_path(name)
            if not os.path.isfile(path):
                raise HTTPException(status_code=404, detail="文件不存在")
            kind, _ = _local_upload_kind_ext(filename, "")
            if kind != "image":
                raise HTTPException(status_code=400, detail="仅支持图片素材智能分类")
            classification = await _image_classifier(
                path,
                payload.provider,
                payload.model,
                payload.ms_model,
                payload.prompt,
            )
            _write_local_upload_classification(filename, classification)
            item.update({
                "ok": True,
                "name": filename,
                "classification": classification,
                "classification_file": os.path.basename(_local_upload_classification_path(filename)),
                "model": classification.get("model") or "",
            })
            ok_count += 1
        except HTTPException as exc:
            item["error"] = str(exc.detail or "智能分类失败")
        except Exception as exc:
            item["error"] = str(exc) or "智能分类失败"
        items.append(item)
    return {"ok": True, "count": ok_count, "items": items}

@router.patch("/api/local-assets/caption")
def api_save_local_asset_caption(payload: LocalAssetCaptionSaveRequest):
    filename, path = _local_upload_safe_path(payload.name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    kind, _ = _local_upload_kind_ext(filename, "")
    if kind != "image":
        raise HTTPException(status_code=400, detail="仅支持图片素材保存提示词")
    caption = str(payload.caption or "")[:100000]
    txt_path = _local_upload_caption_path(filename)
    with open(txt_path, "w", encoding="utf-8", newline="") as f:
        f.write(caption)
    return {"ok": True, "caption": caption, "caption_file": os.path.basename(txt_path)}


# --- 4. 共享文件夹 (Shared Folders) ---
@router.get("/api/shared-folders")
def api_list_shared_folders():
    data = shared_folders_load()
    folders = []
    for entry in data.get("folders", []):
        abs_path = shared_folder_abs(entry)
        folders.append({
            "id": entry.get("id"),
            "name": entry.get("name") or os.path.basename(abs_path) or abs_path,
            "rel": entry.get("rel") or "",
            "path": abs_path,
            "exists": os.path.isdir(abs_path),
            "created_at": entry.get("created_at"),
        })
    return {"folders": folders}

@router.post("/api/shared-folders")
def api_register_shared_folder(payload: SharedFolderRegister):
    abs_path, rel = shared_resolve_register(payload.path)
    name = sanitize_asset_name(payload.name or os.path.basename(abs_path), "共享文件夹")
    with SHARED_FOLDERS_LOCK:
        data = shared_folders_load()
        for entry in data.get("folders", []):
            if os.path.normpath(shared_folder_abs(entry)) == os.path.normpath(abs_path):
                entry["name"] = name
                shared_folders_save(data)
                return {"folder": {**entry, "path": abs_path, "exists": True}}
        entry = {
            "id": f"shared_{uuid.uuid4().hex[:12]}",
            "name": name,
            "rel": rel,
            "created_at": now_ms(),
        }
        data.setdefault("folders", []).append(entry)
        shared_folders_save(data)
    return {"folder": {**entry, "path": abs_path, "exists": True}}

@router.delete("/api/shared-folders/{folder_id}")
def api_unregister_shared_folder(folder_id: str):
    with SHARED_FOLDERS_LOCK:
        data = shared_folders_load()
        before = len(data.get("folders", []))
        data["folders"] = [f for f in data.get("folders", []) if f.get("id") != folder_id]
        if len(data["folders"]) == before:
            raise HTTPException(status_code=404, detail="共享文件夹不存在")
        shared_folders_save(data)
    return {"ok": True}

@router.get("/api/shared-folders/{folder_id}/tree")
def api_get_shared_folder_tree(folder_id: str):
    entry = shared_folder_by_id(folder_id)
    if not entry:
        raise HTTPException(status_code=404, detail="共享文件夹不存在")
    abs_path = shared_folder_abs(entry)
    if not os.path.isdir(abs_path):
        raise HTTPException(status_code=404, detail="文件夹已不存在")
    tree = scan_shared_tree(folder_id, abs_path, "", entry.get("name") or os.path.basename(abs_path))
    return {"folder": {"id": folder_id, "name": entry.get("name"), "path": abs_path}, "tree": tree}

@router.get("/api/shared-folders/{folder_id}/file")
def api_get_shared_folder_file(folder_id: str, path: str = ""):
    entry = shared_folder_by_id(folder_id)
    if not entry:
        raise HTTPException(status_code=404, detail="共享文件夹不存在")
    folder_abs = shared_folder_abs(entry)
    abs_path = shared_child_abs(folder_abs, path)
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in SHARED_MEDIA_EXTS:
        raise HTTPException(status_code=400, detail="不支持的文件类型")
    return FileResponse(abs_path, media_type=content_type_for_path(abs_path))

@router.post("/api/shared-folders/import")
async def api_import_shared_folder_files(payload: SharedFolderImport):
    entry = shared_folder_by_id(payload.folder_id)
    if not entry:
        raise HTTPException(status_code=404, detail="共享文件夹不存在")
    folder_abs = shared_folder_abs(entry)
    lib = load_asset_library()
    cat = find_asset_category_in_library(lib, payload.category_id, payload.library_id)
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    if cat.get("type") != "image":
        raise HTTPException(status_code=400, detail="该分类暂不支持添加媒体")
    added = []
    for rel in (payload.paths or [])[:200]:
        abs_path = shared_child_abs(folder_abs, rel)
        if not os.path.isfile(abs_path):
            continue
        ext = os.path.splitext(abs_path)[1].lower()
        if ext not in SHARED_MEDIA_EXTS:
            continue
        _, item = make_asset_library_item(abs_path, os.path.basename(abs_path), subdir=cat.get("dir") or "")
        if item.get("kind") == "image":
            classification = await classify_asset_image_best_effort(output_file_from_url(item.get("url") or "") or abs_path)
            if classification:
                item["classification"] = classification
        cat.setdefault("items", []).append(item)
        added.append(item)
    save_asset_library(lib)
    return {"library": lib, "items": added}


# --- 5. 资产库核心 CRUD (Asset Library) ---
@router.get("/api/asset-library")
def api_get_asset_library():
    lib = load_asset_library()
    th_meta = get_task_history_meta_index()
    for cat in lib.get("categories", []):
        for it in (cat.get("items") or []):
            enrich_asset_item_generation_meta(it, th_meta)
    for l in lib.get("libraries", []):
        for cat in (l.get("categories") or []):
            for it in (cat.get("items") or []):
                enrich_asset_item_generation_meta(it, th_meta)
    return {"library": lib}

@router.post("/api/asset-library/workflows/upload")
async def api_upload_asset_library_workflows(
    files: List[UploadFile] = File(...),
    library_id: str = Form(""),
    category_id: str = Form(""),
):
    lib = load_asset_library()
    _, cat = asset_library_workflow_category(lib, library_id, category_id)
    added = []
    for file in files[:100]:
        raw = await file.read()
        filename = file.filename or "canvas-workflow.zip"
        lower = filename.lower()
        if not (lower.endswith(".json") or lower.endswith(".zip") or raw[:2] == b"PK"):
            continue
        item = make_workflow_library_item_from_bytes(raw, filename, os.path.splitext(filename)[0])
        cat.setdefault("items", []).append(item)
        added.append(item)
    if not added:
        raise HTTPException(status_code=400, detail="没有可上传的工作流文件")
    save_asset_library(lib)
    return {"library": lib, "items": added}

@router.post("/api/asset-library/libraries")
def api_create_asset_library(payload: AssetLibraryRequest):
    lib = load_asset_library()
    library = {"id": f"lib_{uuid.uuid4().hex[:12]}", "name": sanitize_asset_name(payload.name, "资产库"), "type": "asset", "categories": []}
    library["categories"].append({"id": f"cat_{uuid.uuid4().hex[:12]}", "name": "默认分组", "type": "image", "items": []})
    library["categories"].append({"id": f"wf_{uuid.uuid4().hex[:12]}", "name": "工作流", "type": "workflow", "items": []})
    lib.setdefault("libraries", []).append(library)
    lib["active_library_id"] = library["id"]
    save_asset_library(lib)
    return {"library": lib, "asset_library": library}

@router.patch("/api/asset-library/libraries/{library_id}")
def api_rename_asset_library(library_id: str, payload: AssetLibraryRenameRequest):
    lib = load_asset_library()
    library = find_asset_library(lib, library_id)
    if not library or library.get("id") != library_id:
        raise HTTPException(status_code=404, detail="资产库不存在")
    library["name"] = sanitize_asset_name(payload.name, library.get("name") or "资产库")
    save_asset_library(lib)
    return {"library": lib, "asset_library": library}

@router.delete("/api/asset-library/libraries/{library_id}")
def api_delete_asset_library(library_id: str):
    lib = load_asset_library()
    libraries = lib.get("libraries") or []
    if len(libraries) <= 1:
        raise HTTPException(status_code=400, detail="至少保留一个资产库")
    if not any(item.get("id") == library_id for item in libraries):
        raise HTTPException(status_code=404, detail="资产库不存在")
    lib["libraries"] = [item for item in libraries if item.get("id") != library_id]
    if lib.get("active_library_id") == library_id:
        lib["active_library_id"] = lib["libraries"][0].get("id")
    save_asset_library(lib)
    return {"library": lib}

@router.post("/api/asset-library/categories")
def api_create_asset_library_category(payload: AssetLibraryCategoryRequest):
    lib = load_asset_library()
    library = find_asset_library(lib, payload.library_id)
    if not library:
        raise HTTPException(status_code=404, detail="资产库不存在")
    cat_type = "workflow" if str(payload.type or "").lower() == "workflow" else "image"
    category = {"id": f"cat_{uuid.uuid4().hex[:12]}", "name": sanitize_asset_name(payload.name, "新文件夹"), "type": cat_type, "items": []}
    if cat_type == "image":
        category["dir"] = unique_asset_category_dir(library, payload.name)
        try:
            os.makedirs(os.path.join(ASSET_LIBRARY_DIR, category["dir"]), exist_ok=True)
        except Exception as exc:
            logger.debug(f"创建分组文件夹失败: {exc}")
    library.setdefault("categories", []).append(category)
    lib["active_library_id"] = library.get("id") or lib.get("active_library_id")
    save_asset_library(lib)
    return {"library": lib, "category": category}

@router.patch("/api/asset-library/categories/{category_id}")
def api_rename_asset_library_category(category_id: str, payload: AssetLibraryRenameRequest):
    lib = load_asset_library()
    _, cat = find_asset_category_with_library(lib, category_id, payload.library_id)
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    cat["name"] = sanitize_asset_name(payload.name, cat.get("name") or "新文件夹")
    save_asset_library(lib)
    return {"library": lib, "category": cat}

@router.delete("/api/asset-library/categories/{category_id}")
def api_delete_asset_library_category(category_id: str, library_id: str = ""):
    lib = load_asset_library()
    library, cat = find_asset_category_with_library(lib, category_id, library_id)
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    if cat.get("type") == "workflow" and category_id == "workflows" and (library.get("id") or "") == "default":
        raise HTTPException(status_code=400, detail="默认工作流分类不能删除")
    for item in (cat.get("items") or []):
        remove_asset_library_file(item)
    cat_dir = str(cat.get("dir") or "").strip("/").strip()
    if cat_dir:
        try:
            target = os.path.join(ASSET_LIBRARY_DIR, cat_dir)
            if os.path.isdir(target) and os.path.abspath(target).startswith(os.path.abspath(ASSET_LIBRARY_DIR) + os.sep):
                shutil.rmtree(target, ignore_errors=True)
        except Exception as exc:
            logger.debug(f"删除分组文件夹失败: {exc}")
    library["categories"] = [c for c in library.get("categories", []) if c.get("id") != category_id]
    save_asset_library(lib)
    return {"library": lib}

@router.post("/api/asset-library/items")
async def api_add_asset_library_item(payload: AssetLibraryAddRequest):
    lib = load_asset_library()
    cat = find_asset_category_in_library(lib, payload.category_id, payload.library_id)
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    if cat.get("type") != "image":
        raise HTTPException(status_code=400, detail="该分类暂不支持添加媒体")
    src = output_file_from_url(payload.url)
    if not src:
        raise HTTPException(status_code=400, detail="只支持保存本地 /assets 或 /output 媒体")
    _, item = make_asset_library_item(src, payload.name or os.path.basename(src), subdir=cat.get("dir") or "")
    if item.get("kind") == "image":
        classification = await classify_asset_image_best_effort(output_file_from_url(item.get("url") or "") or src)
        if classification:
            item["classification"] = classification
    cat.setdefault("items", []).append(item)
    save_asset_library(lib)
    return {"library": lib, "item": item}

@router.post("/api/asset-library/items/batch")
async def api_batch_add_asset_library_items(payload: AssetLibraryBatchAddRequest):
    added = []
    lib = load_asset_library()
    cat = find_asset_category_in_library(lib, payload.category_id, payload.library_id)
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    if cat.get("type") != "image":
        raise HTTPException(status_code=400, detail="该分类暂不支持添加媒体")
    for entry in (payload.items or [])[:200]:
        entry.category_id = payload.category_id
        entry.library_id = payload.library_id
        src = output_file_from_url(entry.url)
        if not src:
            continue
        _, item = make_asset_library_item(src, entry.name or os.path.basename(src), subdir=cat.get("dir") or "")
        if item.get("kind") == "image":
            classification = await classify_asset_image_best_effort(output_file_from_url(item.get("url") or "") or src)
            if classification:
                item["classification"] = classification
        cat.setdefault("items", []).append(item)
        added.append(item)
    save_asset_library(lib)
    return {"library": lib, "items": added}

@router.patch("/api/asset-library/items/{item_id}")
def api_rename_asset_library_item(item_id: str, payload: AssetLibraryRenameRequest):
    lib = load_asset_library()
    for library in lib.get("libraries", []):
        for cat in library.get("categories", []):
            for item in cat.get("items", []):
                if item.get("id") == item_id:
                    item["name"] = sanitize_asset_name(payload.name, item.get("name") or "asset")
                    save_asset_library(lib)
                    return {"library": lib, "item": item}
    raise HTTPException(status_code=404, detail="资产不存在")

@router.post("/api/asset-library/items/classify")
async def api_classify_asset_library_items(payload: AssetLibraryClassifyRequest):
    if not _image_classifier:
        raise HTTPException(status_code=501, detail="图片分类服务未就绪")
    lib = load_asset_library()
    results = []
    changed = False
    for item_id in (payload.ids or [])[:80]:
        item = find_asset_item_in_library(lib, item_id, payload.library_id)
        result = {"id": item_id, "ok": False, "classification": None, "error": ""}
        if not item:
            result["error"] = "资产不存在"
            results.append(result)
            continue
        if asset_library_media_kind(item.get("url") or "") != "image" and item.get("kind") != "image":
            result["error"] = "仅支持图片素材智能分类"
            results.append(result)
            continue
        path = output_file_from_url(item.get("url") or "")
        if not path or not os.path.isfile(path):
            result["error"] = "文件不存在"
            results.append(result)
            continue
        try:
            classification = await _image_classifier(path, payload.provider, payload.model, payload.ms_model, payload.prompt)
            item["classification"] = classification
            changed = True
            result.update({"ok": True, "classification": classification})
        except Exception as exc:
            result["error"] = str(getattr(exc, "detail", "") or exc)
        results.append(result)
    if changed:
        save_asset_library(lib)
    return {"library": lib, "count": sum(1 for item in results if item.get("ok")), "items": results}

@router.post("/api/asset-library/items/{item_id}/register-avatar")
async def api_register_asset_library_avatar(item_id: str, payload: AssetAvatarRegisterRequest):
    if not _avatar_register:
        raise HTTPException(status_code=501, detail="数字人认证服务未就绪")
    lib = load_asset_library()
    target_item = find_asset_item_in_library(lib, item_id, payload.library_id)
    if not target_item:
        raise HTTPException(status_code=404, detail="资产不存在")
    target_item = await _avatar_register(item_id, payload, target_item, lib)
    save_asset_library(lib)
    return {"library": lib, "item": target_item}

@router.post("/api/asset-library/items/{item_id}/avatar-status")
async def api_check_asset_library_avatar(item_id: str, payload: AssetAvatarRegisterRequest):
    if not _avatar_check:
        raise HTTPException(status_code=501, detail="数字人认证审核服务未就绪")
    lib = load_asset_library()
    target_item = find_asset_item_in_library(lib, item_id, payload.library_id)
    if not target_item:
        raise HTTPException(status_code=404, detail="资产不存在")
    target_item = await _avatar_check(item_id, payload, target_item, lib)
    save_asset_library(lib)
    return {"library": lib, "item": target_item}

@router.delete("/api/asset-library/items/{item_id}")
def api_delete_asset_library_item(item_id: str):
    lib = load_asset_library()
    removed = None
    for library in lib.get("libraries", []):
        for cat in library.get("categories", []):
            keep = []
            for item in cat.get("items", []):
                if item.get("id") == item_id:
                    removed = item
                else:
                    keep.append(item)
            cat["items"] = keep
    if not removed:
        raise HTTPException(status_code=404, detail="资产不存在")
    remove_asset_library_file(removed)
    save_asset_library(lib)
    return {"library": lib}

@router.post("/api/asset-library/items/delete")
def api_batch_delete_asset_library_items(payload: AssetLibraryBatchDeleteRequest):
    ids = {str(item) for item in (payload.ids or []) if str(item)}
    if not ids:
        raise HTTPException(status_code=400, detail="没有选择资产")
    lib = load_asset_library()
    removed = 0
    removed_items = []
    for library in lib.get("libraries", []):
        if payload.library_id and library.get("id") != payload.library_id:
            continue
        for cat in library.get("categories", []):
            keep = []
            for item in cat.get("items", []):
                if item.get("id") in ids:
                    removed += 1
                    removed_items.append(item)
                else:
                    keep.append(item)
            cat["items"] = keep
    for item in removed_items:
        remove_asset_library_file(item)
    save_asset_library(lib)
    return {"library": lib, "removed": removed}

@router.post("/api/asset-library/items/move")
def api_batch_move_asset_library_items(payload: AssetLibraryBatchMoveRequest):
    ids = {str(item) for item in (payload.ids or []) if str(item)}
    if not ids:
        raise HTTPException(status_code=400, detail="没有选择资产")
    lib = load_asset_library()
    target_cat = find_asset_category_in_library(lib, payload.target_category_id, payload.target_library_id)
    if not target_cat:
        raise HTTPException(status_code=404, detail="目标分组不存在")
    target_type = target_cat.get("type") or "image"
    moved = []
    for library in lib.get("libraries", []):
        if payload.library_id and library.get("id") != payload.library_id:
            continue
        for cat in library.get("categories", []):
            if (cat.get("type") or "image") != target_type:
                continue
            keep = []
            for item in cat.get("items", []):
                if item.get("id") in ids:
                    moved.append(item)
                else:
                    keep.append(item)
            cat["items"] = keep
    existing_ids = {item.get("id") for item in target_cat.get("items", [])}
    for item in moved:
        if item.get("id") not in existing_ids:
            target_cat.setdefault("items", []).append(item)
            existing_ids.add(item.get("id"))
    save_asset_library(lib)
    return {"library": lib, "moved": len(moved)}

@router.post("/api/asset-library/items/crop")
def api_batch_crop_asset_library_items(payload: AssetLibraryBatchCropRequest):
    ids = {str(item) for item in (payload.ids or []) if str(item)}
    if not ids:
        raise HTTPException(status_code=400, detail="没有选择资产")
    lib = load_asset_library()
    target_cat = None
    if payload.target_category_id:
        target_cat = find_asset_category_in_library(lib, payload.target_category_id, payload.target_library_id)
        if not target_cat:
            raise HTTPException(status_code=404, detail="目标分组不存在")
        if target_cat.get("type") != "image":
            raise HTTPException(status_code=400, detail="目标分组不支持媒体")
    added = []
    for library in lib.get("libraries", []):
        if payload.library_id and library.get("id") != payload.library_id:
            continue
        for cat in library.get("categories", []):
            if cat.get("type") != "image":
                continue
            source_items = [item for item in (cat.get("items", []) or []) if item.get("id") in ids]
            for item in source_items:
                src = output_file_from_url(item.get("url") or "")
                if not src or not os.path.isfile(src):
                    continue
                try:
                    with Image.open(src) as img:
                        img = img.convert("RGBA")
                        w, h = img.size
                        side = min(w, h)
                        if side <= 0:
                            continue
                        left = max(0, (w - side) // 2)
                        top = max(0, (h - side) // 2)
                        cropped = img.crop((left, top, left + side, top + side))
                        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                        tmp_path = tmp.name
                        tmp.close()
                        try:
                            cropped.save(tmp_path, "PNG")
                            base_name = os.path.splitext(item.get("name") or "asset")[0] + "_crop.png"
                            dest_cat = target_cat or cat
                            _, next_item = make_asset_library_item(tmp_path, base_name, subdir=dest_cat.get("dir") or "")
                            dest_cat.setdefault("items", []).append(next_item)
                            added.append(next_item)
                        finally:
                            try:
                                os.remove(tmp_path)
                            except Exception:
                                pass
                except Exception:
                    continue
    save_asset_library(lib)
    return {"library": lib, "added": len(added), "items": added}
