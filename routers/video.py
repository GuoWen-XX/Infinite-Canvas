"""Cloud AI Video Generation & Timeline Export Router for Infinite-Canvas.

Decoupled router providing video generation engines and endpoints for:
- Canvas Video Dispatch (DashScope WanX, Agnes, Lingjing, Yuli, Meigen, Tudou/Grok, Volcengine, RunningHub, Jimeng)
- MiniMax Timeline Video Export
- Cloud Video Storage & Upload (Litterbox, Temp.sh)
"""
import os
import re
import sys
import json
import time
import math
import uuid
import shutil
import base64
import hashlib
import asyncio
import logging
import subprocess
import tempfile
import mimetypes
from io import BytesIO
from typing import Dict, Any, List, Optional, Tuple, Set, Union
import urllib.parse
from urllib.parse import urlparse, quote, unquote, urlsplit

import httpx
from PIL import Image
from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, File, Form, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.security import validate_safe_url

from core.providers import (
    BASE_DIR,
    DATA_DIR,
    OUTPUT_DIR,
    OUTPUT_INPUT_DIR,
    OUTPUT_OUTPUT_DIR,
    ASSETS_DIR,
    ASSET_LIBRARY_DIR,
    LOCAL_UPLOAD_DIR,
    CONVERSATION_DIR,
    PUBLIC_BASE_URL,
    PUBLIC_MEDIA_BASE_URL,
    AI_API_KEY,
    VIDEO_POLL_TIMEOUT,
    AI_REQUEST_TIMEOUT,
    VIDEO_PROMPT_MAX_LENGTH,
    DASHSCOPE_DEFAULT_VIDEO_MODELS,
    AGNES_DEFAULT_VIDEO_MODELS,
    MEIGEN_DEFAULT_VIDEO_MODELS,
    now_ms,
    get_api_provider,
    get_api_provider_exact,
    bearer_auth_value,
    provider_endpoint_url,
    provider_env_key_value,
    read_api_env_value,
    load_api_providers,
    save_api_providers,
    update_env_values,
    dump_pydantic,
    model_list_from_values,
    volcengine_access_key_value,
    volcengine_secret_key_value,
    is_apimart_provider,
    selected_model,
    _upstream_request_hook,
    _upstream_response_hook,
)
from core.media import (
    output_file_from_url,
    content_type_for_path,
    is_image_reference_value,
    is_video_reference_value,
    convert_output_to_jpg,
    reference_to_data_url,
    is_image_reference,
    image_references,
    media_reference_to_url,
    compress_data_url_image,
    looks_like_image_media_url,
    is_private_asset_url,
)
from routers.models import (
    CanvasVideoRequest,
    CloudVideoUploadRequest,
    MiniMaxTimelineClip,
    MiniMaxTimelineExportRequest,
    AIReference,
)
from routers.assets import (
    output_url_for,
    output_path_for,
    ensure_same_origin_request,
    sanitize_export_filename,
)
from routers.tasks import (
    record_task_event,
)
from routers.common import (
    save_to_history,
    WsProxy,
    api_headers,
    is_volcengine_provider,
    is_runninghub_provider,
    is_jimeng_provider,
    is_meigen_provider,
    is_tudou_provider,
    is_dashscope_provider,
    is_agnes_provider,
    is_yuli_provider,
    is_lingjing_provider,
    public_base_url,
    public_media_url_suffix,
    local_asset_public_url,
    save_ai_image_to_output,
    image_output_meta,
    save_remote_video_to_output,
    save_video_bytes_to_output,
    parse_size_pair,
    snap_size_to_multiple,
    friendly_image_error_detail,
    _collect_video_url,
    video_output_urls,
    video_api_root,
    looks_like_html_response,
    video_submit_url_candidates,
    video_task_url_candidates,
    humanize_video_task_failure,
    wait_for_video_task,
    extract_task_id,
    log_net_error,
    meigen_env_key,
    _meigen_rpc,
    is_tudou_grok_video_model,
    VIDEO_TASK_SUCCESS_STATUSES,
    VIDEO_TASK_FAILURE_STATUSES,
    friendly_video_error_detail,
    video_reference_to_frame_data_urls,
)
from routers.integrations import (
    generate_runninghub_video,
    generate_jimeng_video,
)

logger = logging.getLogger("infinite_canvas.video")
_server_logger = logging.getLogger("dx.server")

router = APIRouter(tags=["video"])


# --- Sliced from online.py lines 3979-4061 ---
def volcengine_content_role(role: str, kind: str = "image") -> Optional[str]:
    value = str(role or "").strip().lower()
    allowed = {
        "first_frame", "last_frame", "reference_image",
        "reference_video", "reference_audio", "video", "audio", "image"
    }
    if value in allowed:
        if value == "audio" and kind == "audio":
            return "reference_audio"
        return "reference_video" if value == "video" and kind == "video" else value
    if kind == "audio":
        return "reference_audio"
    if kind == "video":
        return "reference_video"
    # 修复：未显式指定 role 的纯生图请求不应兜底为 reference_image，
    # 否则火山后端会误判为 r2v(参考图生视频)，导致 seedance/seedream 等生图模型失败。
    return None

def volcengine_video_duration(duration) -> int:
    try:
        value = int(duration)
    except Exception:
        value = 5
    return max(1, min(60, value))

def volcengine_video_resolution(value: str) -> str:
    text = str(value or "").strip().lower()
    aliases = {"": "", "auto": "", "480": "480p", "720": "720p", "1080": "1080p"}
    text = aliases.get(text, text)
    return text if text in {"480p", "720p", "1080p"} else ""

def is_volcengine_seedance2_model(model: str) -> bool:
    value = str(model or "").strip().lower().replace("_", "-").replace(".", "-")
    return "seedance-2-0" in value

def probe_local_audio_duration_seconds(value: str) -> Optional[float]:
    path = output_file_from_url(value)
    if not path or not os.path.isfile(path):
        return None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode != 0:
            return None
        duration = float(str(proc.stdout or "").strip())
        return duration if math.isfinite(duration) and duration > 0 else None
    except Exception:
        return None

def volcengine_media_reference_url(value, max_image_size=1536):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value:
        return ""
    if is_private_asset_url(value):
        return value
    if value.startswith("/output/") or value.startswith("/assets/"):
        return reference_to_data_url({"url": value}, max_size=max_image_size)
    return value

async def volcengine_video_reference_content_items(value, max_frames=4, max_size=768):
    text = str(value or "").strip()
    if not text:
        return []
    if is_private_asset_url(text):
        return [{
            "type": "video_url",
            "video_url": {"url": text},
            "role": "reference_video",
        }]
    frame_urls = await video_reference_to_frame_data_urls(text, max_frames=max_frames, max_size=max_size)
    return [
        {
            "type": "image_url",
            "image_url": {"url": frame_url},
            "role": "reference_image",
        }
        for frame_url in frame_urls
        if frame_url
    ]



# --- Sliced from online.py lines 4153-4185 ---
def valid_video_image_input(value: str) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    return (
        value.startswith("http://") or
        value.startswith("https://") or
        value.startswith("asset://") or
        (value.startswith("data:image/") and ";base64," in value)
    )

def valid_apimart_video_image_input(value: str) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    return value.startswith("http://") or value.startswith("https://") or value.startswith("asset://")

def apply_trusted_asset_prompt_index(prompt: str, image_count: int, video_count: int, audio_count: int) -> str:
    """可信素材模式下，按平台规则在 prompt 里补「图片N/视频N/音频N」索引。
    若用户已手动引用了某类素材（如已写「图片1」），则不重复追加该类。"""
    text = str(prompt or "").strip()
    segments = []
    for label, count in (("图片", image_count), ("视频", video_count), ("音频", audio_count)):
        if count <= 0:
            continue
        if any(f"{label}{i}" in text for i in range(1, count + 1)):
            continue
        segments.append("、".join(f"{label}{i}" for i in range(1, count + 1)))
    if not segments:
        return text
    hint = "参考素材：" + "，".join(segments) + "。"
    return f"{text}\n{hint}" if text else hint



# --- Sliced from online.py lines 4217-4695 ---
async def openai_video_proxy_public_reference_url(ref) -> str:
    """异步生图（openai-video-proxy）的参考图公网化。
    不走公网隧道（暴露本机服务风险高）：本地文件上传图床（Litterbox/temp.sh，72h 短链），
    与 RS 模式同一通道；真正的公网 URL 原样透传；若手动配置了 PUBLIC_MEDIA_BASE_URL 则作为兜底。"""
    raw = ref.get("url", "") if isinstance(ref, dict) else ref
    text = str(raw or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlsplit(text)
    local_path = ""
    if parsed.scheme in {"http", "https"}:
        host = (parsed.hostname or "").lower()
        if host in {"127.0.0.1", "localhost", "::1"} or re.match(r"^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)", host):
            local_path = urllib.parse.unquote(parsed.path or "")
        else:
            return text
    elif text.startswith(("/output/", "/assets/")):
        local_path = text
    if local_path and output_file_from_url(local_path):
        upload_error = ""
        try:
            uploaded = await upload_local_video_to_cloud(local_path)
            url = str((uploaded or {}).get("url") or "")
            if url.startswith(("http://", "https://")):
                return url
        except HTTPException as exc:
            upload_error = str(exc.detail)
        public_url = local_asset_public_url(local_path)
        if public_url:
            return public_url
        raise HTTPException(
            status_code=400,
            detail=f"参考图上传图床失败，无法转成公网 URL：{upload_error[:200] or '未知错误'}。请检查网络后重试。"
        )
    raise HTTPException(status_code=400, detail=f"参考图不是公网 URL，无法传给上游：{text[:160]}")

def openai_video_proxy_local_image_path(ref) -> str:
    raw = ref.get("url", "") if isinstance(ref, dict) else ref
    text = str(raw or "").strip()
    if not text:
        return ""
    local_path = ""
    if re.match(r"^https?://", text, re.I):
        parsed = urllib.parse.urlsplit(text)
        host = (parsed.hostname or "").lower()
        if host in {"127.0.0.1", "localhost", "::1"} or re.match(r"^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)", host):
            local_path = urllib.parse.unquote(parsed.path or "")
    elif text.startswith(("/output/", "/assets/")):
        local_path = text
    path = output_file_from_url(local_path) if local_path else None
    if not path:
        return ""
    return path if content_type_for_path(path).startswith("image/") else ""

def normalize_apimart_video_reference(value: str) -> str:
    text = str(value or "").strip()
    if valid_apimart_video_image_input(text):
        return text
    return local_asset_public_url(text)

def apimart_video_reference_error(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "空的视频地址"
    if text.startswith(("/output/", "/assets/")):
        if not output_file_from_url(text):
            return "这是本地画布文件路径，但后端没有找到对应文件，请重新上传视频后再试。"
        return (
            "这是本地画布文件，APIMart 无法访问 127.0.0.1/局域网路径；"
            "请在 API/.env 配置 PUBLIC_MEDIA_BASE_URL 或 PUBLIC_BASE_URL 为可公网访问的媒体地址（例如内网穿透 HTTPS 地址），"
            "或改用公网 http/https 视频 URL、审核后的 asset:// 地址。"
        )
    if text.startswith("data:") or text.startswith("blob:") or text.startswith("file:"):
        return (
            "APIMart 的 video_urls 不支持 data/blob/file 地址；"
            "请改用公网 http/https 视频 URL，或审核后的 asset:// 地址。"
        )
    return "APIMart 的 video_urls 只支持公网 http/https URL 或 asset:// 私域素材 URL。"

def apimart_video_duration(duration) -> int:
    try:
        value = int(duration)
    except Exception:
        value = 5
    return max(4, min(15, value))

def apimart_veo31_duration(duration) -> int:
    try:
        value = int(duration)
    except Exception:
        value = 8
    # APIMart VEO 3.1 currently accepts a narrower duration window than
    # the generic UI. Clamp instead of silently forcing every request to 8s.
    return max(4, min(8, value))

def is_apimart_veo31_model(model: str) -> bool:
    return str(model or "").strip().lower().startswith("veo3.1")

def apimart_veo31_model(model: str) -> str:
    value = str(model or "").strip().lower()
    aliases = {
        "veo3.1": "veo3.1-fast",
        "veo3.1-pro": "veo3.1-quality",
        "veo3.1-preview": "veo3.1-fast",
    }
    value = aliases.get(value, value or "veo3.1-fast")
    allowed = {"veo3.1-fast", "veo3.1-quality", "veo3.1-lite"}
    return value if value in allowed else "veo3.1-fast"

def apimart_veo31_aspect(aspect: str) -> str:
    value = str(aspect or "16:9").strip()
    return value if value in {"16:9", "9:16"} else "16:9"

def apimart_veo31_resolution(resolution: str) -> str:
    value = str(resolution or "").strip().lower()
    aliases = {"": "720p", "auto": "720p", "480p": "720p", "780p": "720p", "1080": "1080p", "4k": "4k"}
    value = aliases.get(value, value)
    return value if value in {"720p", "1080p", "4k"} else "720p"

def apimart_upload_file_payload(path: str):
    """Return (filename, bytes, content_type), keeping APIMart VEO images under the documented 10MB limit."""
    max_bytes = 9_500_000
    size = os.path.getsize(path)
    if size <= max_bytes:
        with open(path, "rb") as fh:
            return os.path.basename(path), fh.read(), content_type_for_path(path)
    with Image.open(path) as img:
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        quality = 92
        while quality >= 62:
            buf = BytesIO()
            bg.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
            if len(data) <= max_bytes:
                name = os.path.splitext(os.path.basename(path))[0] + ".jpg"
                return name, data, "image/jpeg"
            quality -= 8
    raise ValueError("图片超过 10MB，且压缩后仍无法满足 VEO3.1 图片限制")

def invalid_video_image_preview(value: str) -> str:
    text = str(value or "")
    if text.startswith("data:"):
        return text.split(";base64,", 1)[0] + ";base64,..."
    return text[:120]

def extract_apimart_asset_url(payload):
    if isinstance(payload, list):
        for item in payload:
            found = extract_apimart_asset_url(item)
            if found:
                return found
        return ""
    if not isinstance(payload, dict):
        return ""
    url_keys = ("url", "asset_url", "assetUrl", "uri", "file_url", "fileUrl")
    for key in url_keys:
        value = str(payload.get(key) or "").strip()
        if valid_apimart_video_image_input(value):
            return value
    id_keys = ("asset_id", "assetId", "file_id", "fileId", "id")
    for key in id_keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value if value.startswith("asset://") else f"asset://{value}"
    for key in ("data", "file", "asset", "result"):
        found = extract_apimart_asset_url(payload.get(key))
        if found:
            return found
    return ""

def apimart_upload_payload_from_bytes(data: bytes, mime: str, name_hint: str = "image"):
    """把内存中的图片字节按 APIMart 的 10MB 限制压缩为可上传 payload。"""
    max_bytes = 9_500_000
    ext = mimetypes.guess_extension(mime or "image/png") or ".png"
    if len(data) <= max_bytes and (mime or "").lower() in ("image/png", "image/jpeg", "image/webp"):
        return f"{name_hint}{ext}", data, (mime or "image/png")
    with Image.open(BytesIO(data)) as img:
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        if has_alpha:
            base = img.convert("RGBA")
            bg = Image.new("RGB", base.size, (255, 255, 255))
            bg.paste(base, mask=base.split()[-1])
            target = bg
        else:
            target = img.convert("RGB")
        quality = 92
        while quality >= 62:
            buf = BytesIO()
            target.save(buf, format="JPEG", quality=quality, optimize=True)
            payload = buf.getvalue()
            if len(payload) <= max_bytes:
                return f"{name_hint}.jpg", payload, "image/jpeg"
            quality -= 8
    raise ValueError("data URL 图片超过 10MB，且压缩后仍无法满足 APIMart 限制")

def apimart_upload_raw_file_payload(path: str):
    with open(path, "rb") as fh:
        return os.path.basename(path), fh.read(), content_type_for_path(path)

APIMART_UPLOAD_RETRY_ATTEMPTS = 3

def is_transient_tls_error(exc) -> bool:
    """识别可重试的瞬时 TLS/传输错误，如 SSLV3_ALERT_BAD_RECORD_MAC、EOF occurred 等，
    这类错误多由连接池中被污染/复用坏掉的 TLS 连接引起，换新连接重试通常即可成功。"""
    if isinstance(exc, httpx.TransportError):
        return True
    msg = f"{type(exc).__name__}: {exc}".upper()
    return any(token in msg for token in (
        "SSL", "BAD RECORD MAC", "EOF OCCURRED", "DECRYPTION FAILED", "WRONG VERSION NUMBER",
    ))

async def apimart_upload_post(client, upstream_upload_url, headers, file_tuple, timeout=60):
    """上传文件到 APIMart，对瞬时 TLS 错误自动重试；重试时改用全新连接，避免复用坏掉的 TLS 连接。
    file_tuple 形如 (filename, content_bytes, content_type)，content 为已读入内存的 bytes，可跨重试复用。"""
    last_exc = None
    for attempt in range(APIMART_UPLOAD_RETRY_ATTEMPTS):
        files = {"file": file_tuple}
        try:
            if attempt == 0:
                return await client.post(upstream_upload_url, headers=headers, files=files, timeout=timeout)
            async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, 
                timeout=httpx.Timeout(connect=20.0, read=max(120.0, float(timeout)), write=120.0, pool=20.0),
                follow_redirects=True,
            ) as fresh:
                return await fresh.post(upstream_upload_url, headers=headers, files=files, timeout=timeout)
        except Exception as e:
            if not is_transient_tls_error(e) or attempt == APIMART_UPLOAD_RETRY_ATTEMPTS - 1:
                raise
            last_exc = e
            logger.info(f"APIMart 上传遇到瞬时 TLS 错误，换新连接重试（第 {attempt + 1} 次）：{e}")
            await asyncio.sleep(0.6 * (attempt + 1))
    if last_exc:
        raise last_exc

async def upload_image_for_apimart(client, provider, ref_url: str) -> str:
    """把本地图片转成上游可接受的输入。
    按 APIMart 文档上传到 /v1/uploads/images，拿到可用于生成接口的 http/https URL。
    绝不把 /output/* 或 /assets/* 这类本地路径直接传给上游。
    返回上游可用 URL；返回值以 "ERR:" 开头表示具体失败原因（供前端展示）。"""
    ref_url = str(ref_url or "").strip()
    if not ref_url:
        return "ERR:空地址"
    # 已经是网络 URL 或 asset:// → 直接可用，无需上传
    if ref_url.startswith("http://") or ref_url.startswith("https://") or ref_url.startswith("asset://"):
        return ref_url
    base_url = video_api_root(provider)
    upload_url = f"{base_url}/v1/uploads/images"
    # data URL: 解码后直接上传到 APIMart
    if ref_url.startswith("data:"):
        try:
            if ";base64," not in ref_url:
                return "ERR:不支持的 data URL（缺少 base64 段）"
            header, encoded = ref_url.split(";base64,", 1)
            mime = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else "image/png"
            raw = base64.b64decode(encoded)
            filename, content, ct = apimart_upload_payload_from_bytes(raw, mime, name_hint="canvas_image")
            resp = await apimart_upload_post(client, upload_url, api_headers(json_body=False, provider=provider), (filename, content, ct), timeout=60)
            if resp.status_code in (200, 201):
                rj = resp.json()
                url = extract_apimart_asset_url(rj)
                if valid_apimart_video_image_input(url):
                    return url
                logger.info(f"APIMart 上传 data URL 返回中未找到可用 asset/url: {str(rj)[:300]}")
                return "ERR:APIMart 上传响应未包含可用 URL"
            logger.warning(f"APIMart 上传 data URL 失败 ({resp.status_code}): {resp.text[:300]}")
            return f"ERR:APIMart 上传失败({resp.status_code})"
        except ValueError as e:
            return f"ERR:{e}"
        except Exception as e:
            logger.warning(f"APIMart 上传 data URL 异常: {e}")
            return f"ERR:上传异常 {e}"
    # 本地 /output/ 或 /assets/ 路径：先确认文件存在再上传
    if ref_url.startswith("/output/") or ref_url.startswith("/assets/"):
        path = output_file_from_url(ref_url)
        if not path:
            logger.info(f"APIMart 上传跳过：本地文件不存在 {ref_url}")
            return "ERR:本地文件不存在或已被删除"
        try:
            filename, content, ct = apimart_upload_file_payload(path)
            resp = await apimart_upload_post(client, upload_url, api_headers(json_body=False, provider=provider), (filename, content, ct), timeout=60)
            if resp.status_code in (200, 201):
                rj = resp.json()
                url = extract_apimart_asset_url(rj)
                if valid_apimart_video_image_input(url):
                    return url
                logger.info(f"APIMart 文件上传返回中未找到可用 asset/url: {str(rj)[:300]}")
                return "ERR:APIMart 上传响应未包含可用 URL"
            logger.warning(f"APIMart 文件上传失败 ({resp.status_code}): {resp.text[:300]}")
            return f"ERR:APIMart 上传失败({resp.status_code})"
        except ValueError as e:
            return f"ERR:{e}"
        except Exception as e:
            logger.warning(f"APIMart 文件上传异常: {e}")
            return f"ERR:上传异常 {e}"
    return "ERR:不支持的图片来源（仅支持 http/https/asset/data 或本地 /output/ /assets/ 路径）"

async def upload_video_for_apimart(client, provider, ref_url: str) -> str:
    """尽力把本地参考视频转换为 APIMart 可接受的 http/https 或 asset:// URL。
    文档只公开了图片上传；如果视频上传端点不可用，会回退到 PUBLIC_BASE_URL 方案。"""
    ref_url = str(ref_url or "").strip()
    if not ref_url:
        return "ERR:空地址"
    if valid_apimart_video_image_input(ref_url):
        return ref_url
    public_url = local_asset_public_url(ref_url)
    if public_url:
        return public_url
    if not (ref_url.startswith("/output/") or ref_url.startswith("/assets/")):
        return f"ERR:{apimart_video_reference_error(ref_url)}"
    path = output_file_from_url(ref_url)
    if not path:
        return "ERR:本地视频不存在或已被删除"
    ct = content_type_for_path(path)
    if not ct.startswith("video/"):
        return "ERR:参考视频不是可识别的视频文件"
    if str(os.getenv("APIMART_TRY_VIDEO_UPLOAD") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        return f"ERR:{apimart_video_reference_error(ref_url)}"
    base_url = video_api_root(provider)
    filename, content, content_type = apimart_upload_raw_file_payload(path)
    upload_paths = ("/v1/uploads/videos", "/v1/uploads/files", "/v1/uploads/images")
    last_error = ""
    for upload_path in upload_paths:
        upload_url = f"{base_url}{upload_path}"
        try:
            files = {"file": (filename, content, content_type)}
            resp = await client.post(upload_url, headers=api_headers(json_body=False, provider=provider), files=files, timeout=180)
            if resp.status_code in (200, 201):
                rj = resp.json()
                url = extract_apimart_asset_url(rj)
                if valid_apimart_video_image_input(url):
                    return url
                last_error = "上传响应未包含可用 URL"
                logger.info(f"APIMart 视频上传返回中未找到可用 asset/url ({upload_path}): {str(rj)[:300]}")
                continue
            last_error = f"{upload_path} 返回 {resp.status_code}: {resp.text[:200]}"
            logger.warning(f"APIMart 视频上传失败 {last_error}")
        except Exception as e:
            last_error = f"{upload_path} 异常：{e}"
            logger.warning(f"APIMart 视频上传异常: {last_error}")
    return f"ERR:APIMart 未提供可用的视频文件上传入口（{last_error}）。请配置 PUBLIC_BASE_URL，或使用公网 http/https / asset:// 视频地址。"

async def upload_audio_for_apimart(client, provider, ref_url: str) -> str:
    """把本地参考音频转换为 APIMart 可接受的 http/https 或 asset:// URL。
    优先用公网地址（PUBLIC_BASE_URL），否则尝试上传到 APIMart 文件端点。
    返回值以 "ERR:" 开头表示失败原因。"""
    ref_url = str(ref_url or "").strip()
    if not ref_url:
        return "ERR:空地址"
    if valid_apimart_video_image_input(ref_url):
        return ref_url
    public_url = local_asset_public_url(ref_url)
    if public_url:
        return public_url
    base_url = video_api_root(provider)
    upload_paths = ("/v1/uploads/audios", "/v1/uploads/files", "/v1/uploads/images")
    last_error = ""
    if ref_url.startswith("data:"):
        if ";base64," not in ref_url:
            return "ERR:不支持的 data URL（缺少 base64 段）"
        header, encoded = ref_url.split(";base64,", 1)
        mime = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else "audio/mpeg"
        try:
            raw = base64.b64decode(encoded)
        except Exception as exc:
            return f"ERR:音频 data URL 解码失败：{exc}"
        ext = mimetypes.guess_extension(mime) or ".mp3"
        filename, content, content_type = (f"canvas_audio{ext}", raw, mime or "audio/mpeg")
    elif ref_url.startswith("/output/") or ref_url.startswith("/assets/"):
        path = output_file_from_url(ref_url)
        if not path:
            return "ERR:本地音频不存在或已被删除"
        ct = content_type_for_path(path)
        if not ct.startswith("audio/"):
            return "ERR:参考音频不是可识别的音频文件"
        filename, content, content_type = apimart_upload_raw_file_payload(path)
    else:
        return f"ERR:{apimart_video_reference_error(ref_url)}"
    for upload_path in upload_paths:
        upload_url = f"{base_url}{upload_path}"
        try:
            files = {"file": (filename, content, content_type)}
            resp = await client.post(upload_url, headers=api_headers(json_body=False, provider=provider), files=files, timeout=180)
            if resp.status_code in (200, 201):
                rj = resp.json()
                url = extract_apimart_asset_url(rj)
                if valid_apimart_video_image_input(url):
                    return url
                last_error = "上传响应未包含可用 URL"
                continue
            last_error = f"{upload_path} 返回 {resp.status_code}: {resp.text[:200]}"
        except Exception as exc:
            last_error = f"{upload_path} 异常：{exc}"
    return f"ERR:APIMart 未提供可用的音频文件上传入口（{last_error}）。请配置 PUBLIC_BASE_URL，或使用公网 http/https / asset:// 音频地址。"

async def upload_media_for_apimart(client, provider, ref_url: str, kind: str) -> str:
    """按 kind 分派到对应的 APIMart 上传器，拿回上游可用的 http/https/asset:// URL。"""
    if kind == "video":
        return await upload_video_for_apimart(client, provider, ref_url)
    if kind == "audio":
        return await upload_audio_for_apimart(client, provider, ref_url)
    return await upload_image_for_apimart(client, provider, ref_url)

def apimart_avatar_asset_type(kind: str) -> str:
    return {"video": "Video", "audio": "Audio"}.get(str(kind or "").lower(), "Image")

def extract_apimart_avatar_asset_uri(payload) -> str:
    """从 /v1/tasks 审核结果里取出 asset://<id> 形式的可信素材 URI。"""
    if isinstance(payload, list):
        for item in payload:
            found = extract_apimart_avatar_asset_uri(item)
            if found:
                return found
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("asset_url", "assetUrl", "uri", "url"):
        value = str(payload.get(key) or "").strip()
        if value.startswith("asset://"):
            return value
    for key in ("usable_assets", "assets", "result", "data"):
        found = extract_apimart_avatar_asset_uri(payload.get(key))
        if found:
            return found
    asset_id = str(payload.get("asset_id") or payload.get("assetId") or "").strip()
    if asset_id:
        return f"asset://{asset_id}"
    return ""

async def submit_apimart_avatar_asset(provider, public_url: str, name: str, kind: str, project_name: str = "default", group_name: str = "") -> str:
    """把一个公网可访问的素材提交到 APIMart private-avatar 审核，立即返回任务 ID（不阻塞轮询）。"""
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    register_url = f"{base_url}/v1/seedance2/private-avatar"
    body = {
        "project_name": str(project_name or "default").strip() or "default",
        "asset_type": apimart_avatar_asset_type(kind),
        "group": {"name": (group_name or name or "数字人素材")[:60]},
        "assets": [{"url": public_url, "name": (name or "asset")[:60]}],
    }
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=120) as client:
        resp = await client.post(register_url, headers=api_headers(provider=provider), json=body, timeout=120)
        if resp.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"APIMart 数字人注册失败（{resp.status_code}）：{resp.text[:300]}")
        data = resp.json()
        task = data.get("data") if isinstance(data.get("data"), dict) else data
        task_id = str(task.get("id") or task.get("task_id") or "").strip()
        if not task_id:
            raise HTTPException(status_code=502, detail=f"APIMart 数字人注册返回中未找到任务 ID：{str(data)[:300]}")
        return task_id

AVATAR_TASK_DONE_STATUSES = {"completed", "complete", "succeeded", "success", "active", "done"}
AVATAR_TASK_FAIL_STATUSES = {"failed", "fail", "error", "rejected", "canceled", "cancelled", "expired"}

async def check_apimart_avatar_task(provider, task_id: str) -> Dict[str, Any]:
    """查询一次 APIMart 审核任务。返回 {status: Active/Processing/Failed, asset_uri, detail}。"""
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    task_url = f"{base_url}/v1/tasks/{task_id}"
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=60) as client:
        resp = await client.get(task_url, headers=api_headers(provider=provider), timeout=60)
        if resp.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"查询审核状态失败（{resp.status_code}）：{resp.text[:200]}")
        payload = resp.json()
    node = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    status = str(node.get("status") or "").strip().lower()
    if status in AVATAR_TASK_DONE_STATUSES:
        asset_uri = extract_apimart_avatar_asset_uri(payload)
        if not asset_uri:
            return {"status": "Failed", "asset_uri": "", "detail": "审核完成，但未返回可用的 asset:// 地址（可能部分素材被拒）。"}
        return {"status": "Active", "asset_uri": asset_uri, "detail": ""}
    if status in AVATAR_TASK_FAIL_STATUSES:
        return {"status": "Failed", "asset_uri": "", "detail": f"审核未通过（{status}）。"}
    return {"status": "Processing", "asset_uri": "", "detail": "审核中"}

# ---- 火山 Ark 私域素材资产（Assets）API：AK/SK 签名 V4 + CreateAssetGroup/CreateAsset/GetAsset ----


# --- Sliced from online.py lines 4840-4923 ---
def local_media_path_for_cloud_upload(ref_url: str, allowed_prefixes=("image/", "video/")) -> str:
    ref_url = str(ref_url or "").strip()
    if not ref_url:
        raise HTTPException(status_code=400, detail="没有可上传的媒体文件")
    if ref_url.startswith("http://") or ref_url.startswith("https://"):
        return ""
    if not (ref_url.startswith("/output/") or ref_url.startswith("/assets/")):
        raise HTTPException(status_code=400, detail="云端上传只支持画布里的本地图片或视频文件")
    path = output_file_from_url(ref_url)
    if not path:
        raise HTTPException(status_code=404, detail="本地媒体文件不存在或已被删除")
    ct = content_type_for_path(path)
    if not any(ct.startswith(prefix) for prefix in allowed_prefixes):
        raise HTTPException(status_code=400, detail="请选择图片或视频文件再上传云端")
    max_bytes = int(os.getenv("TEMP_SH_MAX_BYTES", str(4 * 1024 * 1024 * 1024)))
    size = os.path.getsize(path)
    if size > max_bytes:
        raise HTTPException(status_code=400, detail=f"媒体文件超过云端上传大小限制：{size} bytes")
    return path

def local_video_path_for_cloud_upload(ref_url: str) -> str:
    return local_media_path_for_cloud_upload(ref_url, ("video/",))

async def upload_video_to_litterbox(path: str, source_url: str) -> Dict[str, str]:
    upload_url = os.getenv("LITTERBOX_UPLOAD_URL", "https://litterbox.catbox.moe/resources/internals/api.php").strip() or "https://litterbox.catbox.moe/resources/internals/api.php"
    time_value = os.getenv("LITTERBOX_TIME", "72h").strip() or "72h"
    ct = content_type_for_path(path)
    try:
        async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=httpx.Timeout(connect=20.0, read=600.0, write=600.0, pool=20.0), follow_redirects=True) as client:
            with open(path, "rb") as fh:
                files = {"fileToUpload": (os.path.basename(path), fh, ct)}
                data = {"reqtype": "fileupload", "time": time_value}
                response = await client.post(upload_url, data=data, files=files)
        if not response.is_success:
            raise HTTPException(status_code=response.status_code, detail=f"Litterbox 上传失败：{response.text[:300]}")
        direct_url = response.text.strip().splitlines()[0].strip()
        if not re.match(r"^https?://", direct_url, re.I):
            raise HTTPException(status_code=502, detail=f"Litterbox 返回了无法识别的链接：{response.text[:300]}")
        return {"url": direct_url, "source": source_url, "name": os.path.basename(path), "expires": time_value, "service": "litterbox"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Litterbox 上传异常：{exc}") from exc

async def upload_video_to_temp_sh(path: str, source_url: str) -> Dict[str, str]:
    upload_url = os.getenv("TEMP_SH_UPLOAD_URL", "https://temp.sh/upload").strip() or "https://temp.sh/upload"
    ct = content_type_for_path(path)
    try:
        async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=httpx.Timeout(connect=20.0, read=600.0, write=600.0, pool=20.0), follow_redirects=True) as client:
            with open(path, "rb") as fh:
                files = {"file": (os.path.basename(path), fh, ct)}
                response = await client.post(upload_url, files=files)
        if not response.is_success:
            raise HTTPException(status_code=response.status_code, detail=f"Temp.sh 上传失败：{response.text[:300]}")
        direct_url = response.text.strip().splitlines()[0].strip()
        if not re.match(r"^https?://", direct_url, re.I):
            raise HTTPException(status_code=502, detail=f"Temp.sh 返回了无法识别的链接：{response.text[:300]}")
        return {"url": direct_url, "source": source_url, "name": os.path.basename(path), "expires": "3 days", "service": "temp.sh"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Temp.sh 上传异常：{exc}") from exc

async def upload_local_video_to_cloud(ref_url: str, service: str = "auto") -> Dict[str, str]:
    ref_url = str(ref_url or "").strip()
    if ref_url.startswith("http://") or ref_url.startswith("https://"):
        return {"url": ref_url, "source": ref_url, "service": "existing"}
    path = local_media_path_for_cloud_upload(ref_url)
    service = str(service or os.getenv("CLOUD_VIDEO_UPLOAD_SERVICE", "auto") or "auto").strip().lower()
    if service in {"litterbox", "catbox"}:
        return await upload_video_to_litterbox(path, ref_url)
    if service in {"temp", "temp.sh", "tempsh"}:
        return await upload_video_to_temp_sh(path, ref_url)
    errors = []
    for name, func in (("litterbox", upload_video_to_litterbox), ("temp.sh", upload_video_to_temp_sh)):
        try:
            return await func(path, ref_url)
        except HTTPException as exc:
            errors.append(f"{name}: {exc.detail}")
    raise HTTPException(status_code=502, detail="云端上传失败：" + "；".join(errors))

async def upload_local_video_to_temp_sh(ref_url: str) -> Dict[str, str]:
    return await upload_local_video_to_cloud(ref_url, "auto")



# --- Sliced from online.py lines 7167-7251 ---
@router.post("/api/smart-canvas/minimax-export")
async def export_minimax_timeline(payload: MiniMaxTimelineExportRequest):
    clips = [clip for clip in (payload.clips or []) if clip.url]
    if not clips:
        raise HTTPException(status_code=400, detail="时间轴里还没有可导出的视频")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=500, detail="未找到 ffmpeg，无法导出完整剪辑")
    tmpdir = tempfile.mkdtemp(prefix="minimax_timeline_")
    try:
        clip_sources = []
        for clip in clips:
            src = output_file_from_url(clip.url)
            if not src:
                raise HTTPException(status_code=400, detail="完整剪辑导出只支持本地生成素材")
            clip_sources.append(src)
        ffprobe = shutil.which("ffprobe")
        preserve_audio = bool(ffprobe)
        if ffprobe:
            for src in clip_sources:
                probe_cmd = [
                    ffprobe, "-v", "error", "-select_streams", "a:0",
                    "-show_entries", "stream=index", "-of", "csv=p=0", src,
                ]
                probe = await asyncio.to_thread(subprocess.run, probe_cmd, capture_output=True, text=True, timeout=30)
                if probe.returncode != 0 or not (probe.stdout or "").strip():
                    preserve_audio = False
                    break
        part_paths = []
        normalize_video = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
        for index, (clip, src) in enumerate(zip(clips, clip_sources)):
            start = max(0.0, float(clip.start or 0))
            end = float(clip.end or 0)
            source_duration = max(0.0, float(clip.duration or 0))
            if end <= start:
                end = source_duration if source_duration > start else start + 0.1
            trim_duration = max(0.1, end - start)
            part_path = os.path.join(tmpdir, f"part_{index:03d}.mp4")
            if preserve_audio:
                cmd = [
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{start:.3f}", "-t", f"{trim_duration:.3f}", "-i", src,
                    "-map", "0:v:0", "-map", "0:a:0", "-vf", normalize_video,
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2",
                    "-movflags", "+faststart", part_path,
                ]
            else:
                cmd = [
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{start:.3f}", "-t", f"{trim_duration:.3f}", "-i", src,
                    "-f", "lavfi", "-t", f"{trim_duration:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                    "-map", "0:v:0", "-map", "1:a:0", "-vf", normalize_video, "-shortest",
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2",
                    "-movflags", "+faststart", part_path,
                ]
            proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                raise HTTPException(status_code=500, detail=(proc.stderr or "视频裁剪失败").strip()[:300])
            part_paths.append(part_path)
        filename = sanitize_export_filename(payload.filename or "minimax-timeline.mp4", "minimax-timeline.mp4")
        if not filename.lower().endswith(".mp4"):
            filename += ".mp4"
        output_path = output_path_for(filename, "output")
        if len(part_paths) == 1:
            shutil.copyfile(part_paths[0], output_path)
        else:
            concat_path = os.path.join(tmpdir, "concat.txt")
            with open(concat_path, "w", encoding="utf-8") as fh:
                for part in part_paths:
                    safe_part = part.replace("\\", "/").replace("'", "'\\''")
                    fh.write(f"file '{safe_part}'\n")
            cmd = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", concat_path,
                "-c", "copy", "-movflags", "+faststart", output_path,
            ]
            proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                raise HTTPException(status_code=500, detail=(proc.stderr or "视频拼接失败").strip()[:300])
        return {"url": output_url_for(filename, "output"), "name": filename, "kind": "video"}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)



# --- Sliced from online.py lines 7435-7439 ---
@router.post("/api/cloud-video/upload")
async def cloud_video_upload(payload: CloudVideoUploadRequest, request: Request):
    ensure_same_origin_request(request)
    return await upload_local_video_to_cloud(payload.url, payload.service)



# --- Sliced from online.py lines 9079-9111 ---
VIDEO_PROMPT_LIMITS = {
    "default": (2000, "general providers"),
    "dashscope": (2500, "happyhorse/wan3.0 accept 2500 CJK chars"),
}

def sanitize_video_prompt(text, provider_id="", model=""):
    """Clean an LLM-rewritten prompt before sending to video/image providers:
    strip markdown artifacts, LLM preamble phrases, collapse whitespace,
    truncate to provider limit. Never raises."""
    try:
        s = str(text or "")
        if not s.strip():
            return s
        s = re.sub(r"`{3}[a-zA-Z0-9_-]*", "", s)
        s = re.sub(r"^#{1,6}\s*", "", s, flags=re.M)
        s = s.replace("**", "").replace("__", "")
        s = re.sub(r"^[ \t]*[-*\u2022][ \t]+", "", s, flags=re.M)
        s = re.sub(r"^[ \t]*\d+[.\u3001)]\s*", "", s, flags=re.M)
        for pat in (
            r"^\u597d\u7684[\uff0c,].{0,30}[:\uff1a]?\s*",
            r"^\u4ee5\u4e0b\u662f.{0,30}[:\uff1a]?\s*",
            r"^(Sure|Certainly)[^.]{0,40}[.:]\s*",
            r"^Here(?:'s| is).{0,40}[:\uff1a]?\s*",
        ):
            s = re.sub(pat, "", s, flags=re.I)
        s = re.sub(r"\s*\n\s*", " ", s)
        s = re.sub(r"[ \t]{2,}", " ", s).strip()
        pid = str(provider_id or "").lower()
        limit = VIDEO_PROMPT_LIMITS["default"][0]
        if pid == "dashscope":
            limit = VIDEO_PROMPT_LIMITS["dashscope"][0]
        if len(s) > limit:
            s = s[: limit - 1].rstrip() + "\u2026"
        return s
    except (re.error, TypeError, ValueError, KeyError):
        _server_logger.warning("sanitize_video_prompt 净化失败，返回原文", exc_info=True)
        return str(text or "")




# --- Sliced from online.py lines 9209-9294 ---
async def generate_meigen_video(client, payload, provider, base_url=None, requested_model=None):
    """MeiGen Cloud video generation: MCP generate_video (submit) + check_generation poll."""
    token = meigen_env_key(provider)
    if not token:
        raise HTTPException(status_code=401, detail="MeiGen API token 缺失：请在 API/.env 配置 MEIGEN_API_TOKEN")
    model = str(requested_model or payload.model or "seedance-2-5").strip()
    session = "dx-" + uuid.uuid4().hex[:12]
    rpc_id = 20

    def _rpc(method, params, rid, notify=False):
        return _meigen_rpc(method, params, rid, token, session=session, notify=notify)

    await _rpc("initialize", {"protocolVersion": "2026-07-28", "capabilities": {},
                        "clientInfo": {"name": "infinite-canvas", "version": "1.0"}}, rpc_id)
    rpc_id += 1
    try:
        await _rpc("notifications/initialized", None, None, notify=True)
    except Exception:  # noqa: BLE001
        pass
    rpc_id += 1

    arguments = {"prompt": sanitize_video_prompt(payload.prompt, "meigen", model), "model": model}
    duration_value = getattr(payload, "duration", None)
    if duration_value:
        arguments["duration"] = int(duration_value)
    resolution_value = getattr(payload, "resolution", "")
    if resolution_value:
        arguments["resolution"] = str(resolution_value).lower()

    first_url = ""
    for ref in (payload.images or [])[:2]:
        url = str(getattr(ref, "url", "") or "").strip()
        role = str(getattr(ref, "role", "") or "").strip().lower()
        if not url:
            continue
        public = volcengine_media_reference_url(url, max_image_size=1536)
        if not public:
            continue
        if role == "last_frame":
            arguments["lastFrameUrl"] = public
        else:
            first_url = first_url or public
    if first_url:
        arguments["firstFrameUrl"] = first_url

    t0 = time.monotonic()
    try:
        res = await _rpc("tools/call", {"name": "generate_video", "arguments": arguments}, rpc_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"MeiGen 视频提交失败：HTTP {exc.response.status_code} {exc.response.text[:200]}") from exc

    text_out = "\n".join(c.get("text", "") for c in res.get("result", {}).get("content", []) if c.get("type") == "text")
    gen_match = re.search(r"(?:generationId|generation_id|id)\s*[:=]\s*[\"']?([A-Za-z0-9_-]{8,64})", text_out)
    video_urls = [u for u in re.findall(r"https://[^\s\)\"']+\.(?:mp4|webm)[^\s\)\"']*", text_out)]
    generation_id = gen_match.group(1) if gen_match else ""

    if not video_urls:
        if not generation_id:
            raise HTTPException(status_code=502, detail=f"MeiGen 视频未返回 generationId：{text_out[:300]}")
        deadline = time.monotonic() + VIDEO_POLL_TIMEOUT
        delay = 15.0
        while time.monotonic() < deadline:
            await asyncio.sleep(delay)
            try:
                res = await _rpc("tools/call", {"name": "check_generation",
                                          "arguments": {"generationId": generation_id}}, rpc_id)
            except Exception:  # noqa: BLE001
                delay = min(delay * 1.3, 30)
                continue
            rpc_id += 1
            text_out = "\n".join(c.get("text", "") for c in res.get("result", {}).get("content", []) if c.get("type") == "text")
            video_urls = [u for u in re.findall(r"https://[^\s\)\"']+\.(?:mp4|webm)[^\s\)\"']*", text_out)]
            low = text_out.lower()
            if video_urls:
                break
            if any(k in low for k in ("failed", "error", "cancel")) and "running" not in low and "pending" not in low:
                raise HTTPException(status_code=502, detail=f"MeiGen 视频生成失败（task_id={generation_id}）：{text_out[:300]}")
            delay = min(delay * 1.25, 30)
        if not video_urls:
            raise HTTPException(status_code=504, detail=f"MeiGen 视频超时（task_id={generation_id}）")

    video_url = video_urls[0]
    video_path = await save_remote_video_to_output(video_url, prefix="meigen_")
    return {"videos": [video_path], "task_id": generation_id or f"meigen-{uuid.uuid4().hex[:8]}", "raw": {}}




# --- Sliced from online.py lines 10153-10638 ---
def apimart_video_size(size):
    value = str(size or "16:9").strip()
    if value == "keep_ratio":
        return "adaptive"
    allowed = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"}
    return value if value in allowed else "16:9"

def agnes_video_dimensions(aspect_ratio="", resolution=""):
    ratio = str(aspect_ratio or "16:9").strip()
    width, height = {
        "16:9": (1152, 648),
        "9:16": (648, 1152),
        "4:3": (1024, 768),
        "3:4": (768, 1024),
        "1:1": (768, 768),
        "21:9": (1280, 544),
        "9:21": (544, 1280),
    }.get(ratio, (1152, 768))
    scale = {"480p": 0.625, "720p": 1.0, "780p": 1.0, "1080p": 1.5}.get(str(resolution or "").strip().lower(), 1.0)
    width = max(64, int(round(width * scale / 8) * 8))
    height = max(64, int(round(height * scale / 8) * 8))
    return width, height

def agnes_video_frame_count(duration, fps=24):
    try:
        seconds = max(1, min(18, int(duration or 5)))
    except Exception:
        seconds = 5
    try:
        frame_rate = max(1, min(60, int(fps or 24)))
    except Exception:
        frame_rate = 24
    target = min(441, max(9, seconds * frame_rate))
    n = max(1, round((target - 1) / 8))
    return min(441, max(9, 8 * n + 1)), frame_rate

async def agnes_video_image_url(ref):
    url = str(getattr(ref, "url", "") or "").strip()
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    uploaded = await upload_local_video_to_cloud(url, "auto")
    return uploaded.get("url") or ""

async def wait_for_agnes_video_task(client, provider, video_id, model):
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    validate_safe_url(base_url, allow_private=False)
    query_url = f"{base_url}/agnesapi?{urllib.parse.urlencode({'video_id': video_id, 'model_name': model})}"
    legacy_url = f"{base_url}/v1/videos/{urllib.parse.quote(str(video_id), safe='')}"
    deadline = time.monotonic() + VIDEO_POLL_TIMEOUT
    delay = 5.0
    last_payload = {}
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        raw = None
        last_error = None
        for url in (query_url, legacy_url):
            try:
                validate_safe_url(url, allow_private=False)
                response = await client.get(url, headers=api_headers(provider=provider, model=model))
                response.raise_for_status()
                raw = response.json()
                break
            except Exception as exc:
                last_error = exc
        if raw is None:
            if last_error:
                raise last_error
            raise HTTPException(status_code=502, detail=f"Agnes 视频任务查询失败：{video_id}")
        last_payload = raw
        task_data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        status = str(task_data.get("status") or raw.get("status") or "").upper()
        if status in VIDEO_TASK_SUCCESS_STATUSES or video_output_urls(raw):
            return raw
        if status in VIDEO_TASK_FAILURE_STATUSES:
            error = task_data.get("error") if isinstance(task_data.get("error"), dict) else {}
            reason = task_data.get("message") or error.get("message") or raw.get("error") or raw.get("message") or str(raw)
            raise HTTPException(status_code=502, detail=humanize_video_task_failure(reason))
        delay = min(delay * 1.35, 12)
    raise HTTPException(status_code=504, detail=f"Agnes 视频生成任务超时：{last_payload or video_id}")

async def generate_dashscope_video(client, payload, provider, base_url, requested_model):
    """阿里云百炼(DashScope) 视频异步接口：wan3.0-video / wan3.0-video-prime 等。
    提交: POST {base}/api/v1/services/aigc/video-generation/video-synthesis (X-DashScope-Async: enable)
    查询: GET  {base}/api/v1/tasks/{task_id}
    结果: output.task_status SUCCEEDED 时 output.video_url 可用。
    """
    model = selected_model(requested_model, "wan3.0-video")
    headers = dict(api_headers(provider=provider))
    headers["X-DashScope-Async"] = "enable"

    # ---- input: prompt + media ----
    image_urls = []
    image_roles = []
    for ref in (payload.images or [])[:10]:
        url = str(getattr(ref, "url", "") or "").strip()
        if not url:
            continue
        public = volcengine_media_reference_url(url, max_image_size=1536)
        if public:
            image_urls.append(public)
            image_roles.append(str(getattr(ref, "role", "") or "").strip().lower())
    first_url = next((u for u, r in zip(image_urls, image_roles) if r in {"first_frame", "first"}), "")
    last_url = next((u for u, r in zip(image_urls, image_roles) if r in {"last_frame", "last"}), "")
    ref_urls = [u for u, r in zip(image_urls, image_roles) if r not in {"first_frame", "first", "last_frame", "last"}]

    media = []
    model_low_ds = str(model or "").strip().lower()
    is_hh = model_low_ds.startswith("happyhorse")
    has_frames = bool(first_url or last_url)
    if is_hh:
        # HappyHorse 1.1 按官方文档分专用模型与媒体类型：
        #   -t2v: 纯文本（不传 media）
        #   -i2v: 有且仅有 1 个 first_frame（不支持 last_frame / reference）
        #   -r2v: 1~9 个 reference_image（不支持 frame 类型）
        if has_frames or image_urls:
            base_imgs = [first_url or last_url] if has_frames else image_urls
            if model_low_ds.endswith("-i2v"):
                if first_url or base_imgs:
                    media.append({"type": "first_frame", "url": first_url or base_imgs[0]})
            elif model_low_ds.endswith("-r2v"):
                pool = image_urls if image_urls else ([first_url, last_url] if last_url else [first_url])
                for u in pool[:9]:
                    if u:
                        media.append({"type": "reference_image", "url": u})
            elif model_low_ds.endswith("-t2v"):
                media = []
        if not media and model_low_ds.endswith("-t2v"):
            media = []
    else:
        # wan3.0 全能模型：frame 与 reference 互斥
        if has_frames:
            if first_url:
                media.append({"type": "first_frame", "url": first_url})
            if last_url:
                media.append({"type": "last_frame", "url": last_url})
        elif image_urls:
            for u in image_urls[:10]:
                media.append({"type": "reference_image", "url": u})

    video_payload = []
    for ref_url in (payload.videos or [])[:5]:
        text_url = str(ref_url or "").strip()
        if not text_url or looks_like_image_media_url(text_url):
            continue
        media_url = volcengine_media_reference_url(text_url, max_image_size=None)
        if media_url:
            video_payload.append(media_url)
    if not has_frames and video_payload and not is_hh:
        for u in video_payload[:5]:
            media.append({"type": "reference_video", "url": u})

    audio_urls = []
    for ref_url in (payload.audios or [])[:5]:
        text_url = str(ref_url or "").strip()
        if not text_url:
            continue
        audio_url = volcengine_media_reference_url(text_url, max_image_size=None)
        if audio_url:
            audio_urls.append(audio_url)
    if not has_frames and audio_urls and not is_hh:
        for u in audio_urls[:5]:
            media.append({"type": "reference_audio", "url": u})

    input_obj = {"prompt": str(payload.prompt or "")}
    if is_hh and model_low_ds.endswith("-i2v") and not media:
        raise HTTPException(status_code=400, detail="happyhorse-1.1-i2v 需要一张首帧图片：请在节点上接入一张图片（会作为视频首帧）。文生视频请改用 happyhorse-1.1-t2v。")
    if is_hh and model_low_ds.endswith("-r2v") and not media:
        raise HTTPException(status_code=400, detail="happyhorse-1.1-r2v 需要至少 1 张参考图（最多 9 张）：请在节点上接入参考图片。")
    if media:
        input_obj["media"] = media

    # ---- parameters ----
    ratio = str(payload.aspect_ratio or "").strip()
    if is_hh:
        # HappyHorse 1.1: 16:9(默认)/9:16/1:1/4:3/3:4/4:5/5:4/9:21/21:9，无 adaptive
        if ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4", "4:5", "5:4", "9:21", "21:9"}:
            ratio = "16:9"
    else:
        if ratio not in {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9"}:
            ratio = "adaptive"
    resolution = str(payload.resolution or "").strip().upper()
    if resolution not in {"1080P", "720P", "480P"}:
        resolution = "1080P"
    try:
        duration = int(payload.duration or 5)
    except Exception:
        duration = 5
    if is_hh:
        # HappyHorse 1.1: 3~15 秒整数；不支持 audio 开关与智能时长(-1)
        duration = max(3, min(15, duration))
        parameters = {
            "resolution": resolution,
            "ratio": ratio,
            "duration": duration,
        }
    else:
        parameters = {
            "resolution": resolution,
            "ratio": ratio,
            "duration": max(-1, min(30, duration)),
            "audio": bool(payload.generate_audio),
        }
    if payload.enhance_prompt is False:
        parameters["prompt_extend"] = False
    if payload.watermark:
        parameters["watermark"] = True
    if payload.seed is not None:
        parameters["seed"] = payload.seed

    body = {"model": model, "input": input_obj, "parameters": parameters}

    submit_url = f"{base_url}/api/v1/services/aigc/video-generation/video-synthesis"
    response = await client.post(submit_url, headers=headers, json=body)
    response.raise_for_status()
    raw = response.json()
    task_id = str(raw.get("output", {}).get("task_id") or raw.get("task_id") or "").strip()
    if not task_id:
        raise HTTPException(status_code=502, detail=f"DashScope 未返回 task_id：{raw}")

    # ---- poll ----
    task_url = f"{base_url}/api/v1/tasks/{urllib.parse.quote(task_id, safe='')}"
    deadline = time.monotonic() + VIDEO_POLL_TIMEOUT
    delay = 8.0
    last_payload = raw
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        poll = await client.get(task_url, headers=api_headers(provider=provider))
        poll.raise_for_status()
        result = poll.json()
        last_payload = result
        output = result.get("output") if isinstance(result.get("output"), dict) else {}
        status = str(output.get("task_status") or "").upper()
        if status in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
            video_url = output.get("video_url") or output.get("video_url_1") or ""
            if video_url:
                return {"output": output, "task_id": task_id, "raw": result}
            raise HTTPException(status_code=502, detail=f"DashScope 任务成功但没有返回 video_url：{result}")
        if status in {"FAILED", "CANCELED", "UNKNOWN"}:
            reason = output.get("message") or output.get("code") or str(result)[:400]
            raise HTTPException(status_code=502, detail=f"DashScope 任务失败（task_id={task_id}）：{reason}")
        delay = min(delay * 1.35, 15)
    raise HTTPException(status_code=504, detail=f"DashScope 任务超时（task_id={task_id}）：{last_payload}")

async def generate_agnes_video(client, payload, provider, base_url, requested_model):
    model = selected_model(requested_model, "agnes-video-v2.0")
    model_low = str(model or "").strip().lower()

    image_urls = []
    image_roles = []
    for ref in (payload.images or [])[:4]:
        url = await agnes_video_image_url(ref)
        if url:
            image_urls.append(url)
            image_roles.append(str(getattr(ref, "role", "") or "").strip().lower())
    # Agnes 2.5 系列按官方规则必须显式传 mode：text / keyframe / reference。
    first_url = next((u for u, r in zip(image_urls, image_roles) if r in {"first_frame", "first"}), "")
    last_url = next((u for u, r in zip(image_urls, image_roles) if r in {"last_frame", "last"}), "")
    if model_low.startswith("agnes-video-2.5") or model_low.startswith("agnes-video-v2.5"):
        ratio = str(payload.aspect_ratio or "16:9").strip() or "16:9"
        if ratio not in {"21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}:
            ratio = "16:9"
        try:
            seconds = max(4, min(12, int(payload.duration or 5)))
        except Exception:
            seconds = 5
        if first_url and last_url:
            mode = "keyframe"
        elif len(image_urls) > 1:
            mode = "reference"
        elif image_urls:
            mode = "keyframe"
        else:
            mode = "text"
        body = {
            "model": model,
            "prompt": str(payload.prompt or ""),
            "mode": mode,
            "aspect_ratio": ratio,
            "seconds": str(seconds),
        }
        if mode == "keyframe":
            if first_url:
                body["first_frame"] = first_url
            if last_url:
                body["last_frame"] = last_url
            if not body.get("first_frame") and not body.get("last_frame"):
                body["mode"] = "text"
                body.pop("first_frame", None)
                body.pop("last_frame", None)
        elif mode == "reference":
            body["images"] = image_urls[:5]
    else:
        width, height = agnes_video_dimensions(payload.aspect_ratio, payload.resolution)
        num_frames, frame_rate = agnes_video_frame_count(payload.duration, 24)
        body = {
            "model": model,
            "prompt": str(payload.prompt or ""),
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "frame_rate": frame_rate,
        }
        if len(image_urls) == 1:
            body["image"] = image_urls[0]
        elif len(image_urls) > 1:
            body["extra_body"] = {"image": image_urls}
            has_frame_roles = any(role in {"first_frame", "last_frame"} for role in image_roles)
            if payload.multimodal or has_frame_roles:
                body["extra_body"]["mode"] = "keyframes"
    if payload.seed is not None:
        body["seed"] = payload.seed
    submit_url = f"{base_url}/v1/videos"
    response = await client.post(submit_url, headers=api_headers(provider=provider, model=model), json=body)
    response.raise_for_status()
    raw = response.json()
    video_id = str(raw.get("video_id") or "").strip()
    task_id = str(raw.get("task_id") or raw.get("id") or "").strip()
    result = raw
    if video_id and not video_output_urls(raw):
        result = await wait_for_agnes_video_task(client, provider, video_id, model)
    elif task_id and not video_output_urls(raw):
        result = await wait_for_video_task(client, provider, task_id, submit_url)
    urls = video_output_urls(result)
    if not urls:
        raise HTTPException(status_code=502, detail=f"Agnes 视频生成成功但没有返回视频：{result}")
    local_urls = [await save_remote_video_to_output(url) for url in urls]
    return {"videos": local_urls, "task_id": task_id or video_id, "video_id": video_id or None, "raw": result}

# ---- 玉玉API（yuli.host）OpenAI 视频格式：/v1/videos（multipart，支持 seconds 时长）----
def _yuli_model_norm(model: str) -> str:
    return str(model or "").strip().lower().replace("_", "").replace(".", "").replace("-", "")

def yuli_is_veo_openai_model(model: str) -> bool:
    # OpenAI multipart 格式当前只支持 veo_3_1 和 veo_3_1-fast
    return _yuli_model_norm(model) in {"veo31", "veo31fast"}

def yuli_openai_model_name(model: str) -> str:
    return "veo_3_1-fast" if _yuli_model_norm(model) == "veo31fast" else "veo_3_1"

def yuli_openai_size(aspect_ratio: str) -> str:
    value = str(aspect_ratio or "").strip()
    if value == "9:16":
        return "9x16"
    return "16x9"

def lingjing_openai_video_model(model: str) -> str:
    value = str(model or "").strip() or "veo_3_1-fast"
    lower = value.lower()
    if lower.startswith("veo3.1"):
        value = "veo_3_1" + value[len("veo3.1"):]
    elif lower.startswith("veo3_1"):
        value = "veo_3_1" + value[len("veo3_1"):]
    if value.lower().endswith("-4k"):
        value = value[:-2] + "4K"
    return value

def yuli_video_seconds(duration) -> str:
    try:
        value = int(duration)
    except Exception:
        value = 8
    if value <= 0:
        value = 8
    return str(value)

async def yuli_fetch_reference_bytes(client, ref_url):
    """把参考图（input_reference 垫图）取成 (filename, bytes, mime)，
    支持 /output、/assets 本地文件、data URL、http(s) URL。失败返回 None。"""
    ref_url = str(ref_url or "").strip()
    if not ref_url:
        return None
    if ref_url.startswith("data:"):
        header, _, b64 = ref_url.partition(",")
        mime = (header[5:].split(";")[0] or "image/png").strip()
        try:
            raw = base64.b64decode(b64)
        except Exception:
            return None
        ext = (mime.split("/")[-1] or "png").split("+")[0]
        return (f"input_reference.{ext}", raw, mime)
    path = output_file_from_url(ref_url)
    if path:
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception:
            return None
        mime = content_type_for_path(path)
        return (os.path.basename(path) or "input_reference", raw, mime)
    if ref_url.startswith("http://") or ref_url.startswith("https://"):
        try:
            from core.security import safe_download_bytes
            raw, ctype = await safe_download_bytes(ref_url, max_bytes=50 * 1024 * 1024, allow_private=False)
        except Exception:
            return None
        mime = (ctype or "image/png").split(";")[0].strip()
        ext = (mime.split("/")[-1] or "png").split("+")[0]
        return (f"input_reference.{ext}", raw, mime)
    return None

async def generate_lingjing_openai_video(client, payload, provider, base_url, requested_model):
    """灵境 API OpenAI 视频格式：POST /v1/videos，参考图走 multipart input_reference。"""
    submit_url = f"{base_url}/v1/videos"
    data = {
        "model": lingjing_openai_video_model(selected_model(requested_model, "veo_3_1-fast")),
        "prompt": str(payload.prompt or ""),
        "seconds": yuli_video_seconds(payload.duration),
        "size": yuli_openai_size(payload.aspect_ratio or payload.size),
        "watermark": "true" if payload.watermark else "false",
    }
    files = []
    for ref in (payload.images or [])[:3]:
        ref_file = await yuli_fetch_reference_bytes(client, getattr(ref, "url", ""))
        if ref_file:
            files.append(("input_reference", ref_file))
    headers = api_headers(json_body=False, provider=provider)
    if files:
        response = await client.post(submit_url, headers=headers, data=data, files=files)
    else:
        multipart_fields = [(key, (None, value)) for key, value in data.items()]
        response = await client.post(submit_url, headers=headers, files=multipart_fields)
    response.raise_for_status()
    try:
        raw = response.json()
    except Exception as exc:
        resp_text = (response.text or "")[:500]
        raise HTTPException(status_code=502, detail=f"灵境 API 视频接口返回非 JSON 响应（状态 {response.status_code}）：{resp_text}") from exc
    task_id = str(raw.get("id") or extract_task_id(raw) or raw.get("task_id") or "").strip()
    result = raw
    if task_id and not video_output_urls(raw):
        result = await wait_for_video_task(client, provider, task_id, submit_url)
    urls = video_output_urls(result)
    if not urls:
        raise HTTPException(status_code=502, detail=f"灵境 API 视频生成成功但没有返回视频：{result}")
    local_urls = [await save_remote_video_to_output(url) for url in urls]
    return {"videos": local_urls, "task_id": task_id, "raw": result}

async def generate_yuli_openai_video(client, payload, provider, base_url, requested_model):
    """玉玉API veo3.1 走 OpenAI multipart 格式 /v1/videos，支持 seconds 时长控制。"""
    submit_url = f"{base_url}/v1/videos"
    data = {
        "model": yuli_openai_model_name(requested_model),
        "prompt": str(payload.prompt or ""),
        "seconds": yuli_video_seconds(payload.duration),
        "size": yuli_openai_size(payload.aspect_ratio),
        "watermark": "true" if payload.watermark else "false",
    }
    files = {}
    for ref in (payload.images or [])[:1]:
        ref_file = await yuli_fetch_reference_bytes(client, getattr(ref, "url", ""))
        if ref_file:
            files["input_reference"] = ref_file
            break
    headers = api_headers(json_body=False, provider=provider)
    if files:
        response = await client.post(submit_url, headers=headers, data=data, files=files)
    else:
        # 文生视频无垫图时，仍以 multipart/form-data 提交（把文本字段作为表单分块），
        # 避免 httpx 在只有 data 时退化成 application/x-www-form-urlencoded。
        multipart_fields = {key: (None, value) for key, value in data.items()}
        response = await client.post(submit_url, headers=headers, files=multipart_fields)
    response.raise_for_status()
    try:
        raw = response.json()
    except Exception as exc:
        resp_text = (response.text or "")[:500]
        raise HTTPException(status_code=502, detail=f"玉玉API 视频接口返回非 JSON 响应（状态 {response.status_code}）：{resp_text}") from exc
    task_id = raw.get("id") or extract_task_id(raw) or raw.get("task_id")
    result = raw
    if task_id and not video_output_urls(raw):
        result = await wait_for_video_task(client, provider, task_id, submit_url)
    urls = video_output_urls(result)
    if not urls:
        raise HTTPException(status_code=502, detail=f"视频生成成功但没有返回视频：{result}")
    local_urls = [await save_remote_video_to_output(url) for url in urls]
    return {"videos": local_urls, "task_id": task_id, "raw": result}

TUDOU_GROK_IMAGE_SIZES = {"1024x1024", "1280x720", "720x1280", "1792x1024", "1024x1792"}
TUDOU_GROK_IMAGE_ASPECT_SIZES = {
    "1:1": "1024x1024", "16:9": "1280x720", "9:16": "720x1280",
    "3:2": "1792x1024", "2:3": "1024x1792",
}



# --- Sliced from online.py lines 10722-10892 ---
def tudou_video_family(model):
    value = str(model or "").strip().lower()
    if value.startswith("sora2"):
        return "sora2"
    if value.startswith("veo3.1"):
        return "veo31"
    if value.startswith("kling-v3"):
        return "kling"
    if value.startswith("pixverse-v6"):
        return "pixverse"
    if "seedance-2.0" in value:
        return "seedance"
    return ""

def is_tudou_video_model(model):
    return bool(tudou_video_family(model)) or is_tudou_grok_video_model(model)

def tudou_snap_choice(value, choices, default):
    try:
        parsed = int(round(float(value)))
    except Exception:
        return default
    return parsed if parsed in choices else min(choices, key=lambda choice: abs(choice - parsed))

def tudou_video_aspect(value, allowed=("16:9", "9:16"), default="16:9"):
    value = str(value or "").strip()
    return value if value in allowed else default

def tudou_task_data(raw):
    return raw.get("data") if isinstance(raw, dict) and isinstance(raw.get("data"), dict) else raw if isinstance(raw, dict) else {}

def tudou_extract_task_id(raw):
    data = tudou_task_data(raw)
    return str(data.get("id") or data.get("task_id") or (raw or {}).get("id") or (raw or {}).get("task_id") or "").strip()

def tudou_video_result_urls(raw):
    result = tudou_task_data(raw).get("result")
    result = result if isinstance(result, dict) else {}
    urls = []
    def add(value):
        if isinstance(value, list):
            for item in value:
                add(item)
        elif isinstance(value, dict):
            add(value.get("url") or value.get("video_url"))
        elif isinstance(value, str) and value.strip() and value.strip() not in urls:
            urls.append(value.strip())
    add(result.get("video_url"))
    for key in ("videos", "images", "outputs", "result"):
        add(result.get(key))
    return urls

async def tudou_public_image_urls(images, limit):
    urls = []
    for ref in list(images or [])[:limit]:
        value = str(getattr(ref, "url", "") or "").strip()
        if value:
            urls.append(await openai_video_proxy_public_reference_url({"url": value}))
    return urls

async def tudou_public_media_urls(items, limit):
    urls = []
    for item in list(items or [])[:limit]:
        value = str(item or "").strip()
        if value:
            urls.append(await openai_video_proxy_public_reference_url(value))
    return urls

TUDOU_VIDEO_SUCCESS_STATUSES = {"COMPLETED", "COMPLETE", "DONE", "FINISHED", "SUCCESS",
                                "SUCCEED", "SUCCEEDED", "SUCCESSFUL", "OK", "READY"}
TUDOU_VIDEO_FAILED_STATUSES = {"FAILED", "FAIL", "FAILURE", "ERROR", "ERRORED",
                               "CANCELED", "CANCELLED", "TIMEOUT", "REJECTED", "EXPIRED"}

async def tudou_wait_video_task(client, provider, base_url, task_id):
    deadline = time.monotonic() + VIDEO_POLL_TIMEOUT
    await asyncio.sleep(min(12.0, VIDEO_POLL_TIMEOUT))
    delay = 5.0
    last_payload = {}
    task_url = f"{base_url}/v1/tasks/{urllib.parse.quote(str(task_id), safe='')}"
    while time.monotonic() < deadline:
        response = await client.get(task_url, headers=api_headers(provider=provider))
        response.raise_for_status()
        last_payload = response.json()
        data = tudou_task_data(last_payload)
        status = str(data.get("status") or data.get("task_status") or "").upper()
        if status in TUDOU_VIDEO_SUCCESS_STATUSES or tudou_video_result_urls(last_payload):
            return last_payload
        if status in TUDOU_VIDEO_FAILED_STATUSES:
            error = data.get("error") if isinstance(data.get("error"), dict) else {}
            reason = error.get("message") or data.get("message") or data.get("fail_reason") or str(last_payload)[:300]
            raise HTTPException(status_code=502, detail=f"土豆视频生成失败：{reason}")
        await asyncio.sleep(delay)
        delay = min(delay * 1.4, 10.0)
    raise HTTPException(status_code=504, detail=f"土豆视频任务超时：{task_id}")

async def generate_tudou_video(client, payload, provider, base_url, requested_model):
    family = tudou_video_family(requested_model)
    model = selected_model(requested_model, requested_model)
    aspect = tudou_video_aspect(payload.aspect_ratio or payload.size)
    body = {"model": model, "prompt": str(payload.prompt or "")}
    if family == "sora2":
        body.update(duration=tudou_snap_choice(payload.duration, (4, 8, 12), 8), aspect_ratio=aspect, generate_audio=bool(payload.generate_audio))
        images = await tudou_public_image_urls(payload.images, 1)
        if images: body["images"] = images
    elif family == "veo31":
        body.update(resolution="1080p" if model.lower().endswith("1080p") else "720p", duration=tudou_snap_choice(payload.duration, (4, 6, 8), 8), aspect_ratio=aspect, generate_audio=bool(payload.generate_audio))
        images = await tudou_public_image_urls(payload.images, 3)
        if images:
            body["reference_mode"] = "image" if len(images) > 2 else "frame"
            body["images"] = images
    elif family == "kling":
        images = await tudou_public_image_urls(payload.images, 2)
        if not images:
            raise HTTPException(status_code=400, detail="土豆 Kling v3 系列只支持图生视频，请至少提供 1 张参考图。")
        durations = (5, 10, 15) if model.lower() == "kling-v3" else (5, 15)
        body.update(duration=tudou_snap_choice(payload.duration, durations, 10 if model.lower() == "kling-v3" else 15), aspect_ratio=aspect, generate_audio=bool(payload.generate_audio), images=images)
    elif family == "pixverse":
        lower = model.lower()
        body.update(resolution="1080p" if "1080p" in lower else "720p", audio=lower.endswith("-audio"), size=tudou_video_aspect(payload.aspect_ratio or payload.size, allowed=("16:9", "4:3", "1:1", "3:4", "9:16", "2:3", "3:2", "21:9")))
        first = next((ref for ref in payload.images if str(ref.role or "").lower() == "first_frame"), None)
        last = next((ref for ref in payload.images if str(ref.role or "").lower() == "last_frame"), None)
        if first and last:
            body.update(first_frame_image=await openai_video_proxy_public_reference_url({"url": first.url}), last_frame_image=await openai_video_proxy_public_reference_url({"url": last.url}), duration=tudou_snap_choice(payload.duration, (5, 8), 5))
        else:
            images = await tudou_public_image_urls(payload.images, 7)
            if images: body["img_references"] = images
            body["duration"] = max(1, min(15, tudou_snap_choice(payload.duration, tuple(range(1, 16)), 5)))
    elif family == "seedance":
        body.update(model="seedance-2.0-fast" if "fast" in model.lower() else "seedance-2.0", duration=tudou_snap_choice(payload.duration, tuple(range(4, 16)), 4), aspect_ratio=aspect, resolution="1080p" if str(payload.resolution or "").lower().startswith("1080") else "720p", generate_audio=bool(payload.generate_audio))
        images, videos = await tudou_public_image_urls(payload.images, 9), await tudou_public_media_urls(payload.videos, 3)
        if images: body["images"] = images
        if videos: body["videos"] = videos
        if images or videos:
            audios = await tudou_public_media_urls(payload.audios, 3)
            if audios: body["audios"] = audios
    else:
        raise HTTPException(status_code=400, detail=f"未知的土豆视频模型：{model}")
    response = await client.post(f"{base_url}/v1/videos/generations", headers=api_headers(provider=provider, model=model), json=body)
    response.raise_for_status()
    try:
        raw = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"土豆视频接口返回非 JSON 响应：{(response.text or '')[:500]}") from exc
    task_id = tudou_extract_task_id(raw)
    if not task_id:
        raise HTTPException(status_code=502, detail=f"土豆视频提交未返回任务 ID：{str(raw)[:400]}")
    result = raw if tudou_video_result_urls(raw) else await tudou_wait_video_task(client, provider, base_url, task_id)
    urls = tudou_video_result_urls(result)
    if not urls:
        raise HTTPException(status_code=502, detail=f"土豆视频任务完成但未返回视频地址：{str(result)[:400]}")
    return {"videos": [await save_remote_video_to_output(url, prefix="tudou_video_") for url in urls], "task_id": task_id, "raw": result}

def tudou_grok_video_seconds(duration):
    allowed = (6, 10, 12, 16, 20)
    try:
        value = int(duration)
    except Exception:
        value = 6
    return str(value if value in allowed else next((item for item in allowed if item >= value), allowed[-1]))

def tudou_grok_video_size(aspect_ratio="", resolution=""):
    ratio = str(aspect_ratio or "").strip()
    high = str(resolution or "").strip().lower() in {"1080p", "4k", "high", "hd"}
    if ratio == "9:16": return "1024x1792" if high else "720x1280"
    if ratio == "1:1": return "1024x1024"
    return "1792x1024" if high else "1280x720"

async def tudou_grok_video_part(client, ref):
    for value in (str(getattr(ref, key, "") or "").strip() for key in ("url", "original_url", "originalLocalUrl", "source_url")):
        if not value or value.lower().startswith("asset://"):
            continue
        ref_file = await yuli_fetch_reference_bytes(client, value)
        if ref_file:
            return ("input_reference[]", ref_file)
    return None



# --- Sliced from online.py lines 10905-10961 ---
async def download_tudou_grok_video_content(client, provider, base_url, task_id):
    response = await client.get(
        f"{base_url}/v1/videos/{urllib.parse.quote(str(task_id), safe='')}/content",
        headers=api_headers(provider=provider),
    )
    response.raise_for_status()
    content_type = (response.headers.get("content-type") or "").lower()
    extension = ".webm" if "webm" in content_type else ".mov" if "quicktime" in content_type or "mov" in content_type else ".mp4"
    return await save_video_bytes_to_output(response.content, prefix="tudou_grok_video_", ext=extension)

async def generate_tudou_grok_video(client, payload, provider, base_url, requested_model):
    model = selected_model(requested_model, "grok-imagine-video")
    parts = [(key, (None, str(value))) for key, value in {
        "model": model, "prompt": str(payload.prompt or ""), "seconds": tudou_grok_video_seconds(payload.duration),
        "size": tudou_grok_video_size(payload.aspect_ratio or payload.size, payload.resolution),
        "resolution_name": "480p" if str(payload.resolution or "").lower() == "480p" else "720p", "preset": "custom",
    }.items()]
    attached = 0
    for ref in (payload.images or [])[:7]:
        part = await tudou_grok_video_part(client, ref)
        if part:
            parts.append(part)
            attached += 1
    if payload.images and not attached:
        raise HTTPException(status_code=400, detail="土豆 Grok 图生视频没有成功读取参考图。请使用本地图片、公网图片 URL 或 data:image;base64。")
    response = await client.post(f"{base_url}/v1/videos", headers=api_headers(json_body=False, provider=provider, model=model), files=parts)
    response.raise_for_status()
    try:
        raw = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"土豆 Grok 视频接口返回非 JSON 响应：{(response.text or '')[:500]}") from exc
    task_id = str(raw.get("id") or extract_task_id(raw) or raw.get("task_id") or "").strip()
    result = raw if video_output_urls(raw) else await wait_for_video_task(client, provider, task_id, f"{base_url}/v1/videos") if task_id else raw
    urls = video_output_urls(result)
    if urls:
        videos = [await save_remote_video_to_output(url, prefix="tudou_grok_video_") for url in urls]
    elif task_id:
        videos = [await download_tudou_grok_video_content(client, provider, base_url, task_id)]
    else:
        raise HTTPException(status_code=502, detail=f"土豆 Grok 视频没有返回视频地址：{str(result)[:400]}")
    return {"videos": videos, "task_id": task_id, "raw": result}

def volcengine_video_prompt_text(prompt, aspect_ratio="", duration=None):
    text = str(prompt or "").strip()
    suffixes = []
    ratio = str(aspect_ratio or "").strip()
    if ratio:
        suffixes.append(f"--ratio {ratio}")
    if not suffixes:
        return text
    suffix_text = " ".join(suffixes)
    return f"{text} {suffix_text}".strip() if text else suffix_text



# --- 任务中心及生成记录注册表已解耦迁移至 routers/tasks.py ---



# --- Sliced from online.py lines 10962-11494 ---
@router.post("/api/canvas-video")
async def canvas_video(payload: CanvasVideoRequest):
    _t0 = time.monotonic()
    try:
        result = await _canvas_video_dispatch(payload)
    except HTTPException as exc:
        record_task_event(payload.provider_id, payload.model, "failed",
                          duration_ms=int((time.monotonic() - _t0) * 1000),
                          error=exc.detail, kind="video")
        raise
    except Exception as exc:  # noqa: BLE001
        record_task_event(payload.provider_id, payload.model, "failed",
                          duration_ms=int((time.monotonic() - _t0) * 1000),
                          error=str(exc), kind="video")
        raise
    try:
        raw = result.get("raw") if isinstance(result, dict) else None
        outputs = result.get("videos") or result.get("images") or result.get("output_urls") or []
        if isinstance(outputs, str):
            outputs = [outputs]
        record_task_event(payload.provider_id, payload.model, "success",
                          task_id=(result or {}).get("task_id", ""),
                          duration_ms=int((time.monotonic() - _t0) * 1000),
                          outputs=outputs, raw=raw, kind="video",
                          duration_hint=payload.duration,
                          prompt=getattr(payload, "prompt", ""))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"task record failed: {exc}")
    return result


async def _canvas_video_dispatch(payload: CanvasVideoRequest):
    provider = get_api_provider(payload.provider_id)
    if is_jimeng_provider(provider):
        return await generate_jimeng_video(payload, provider)
    if is_runninghub_provider(provider):
        try:
            return await generate_runninghub_video(payload, provider)
        except HTTPException as exc:
            logger.info(f"RunningHub 视频生成失败 model={payload.model}: {exc.detail}")
            raise
        except httpx.HTTPStatusError as exc:
            text = (exc.response.text or "").strip()
            status = exc.response.status_code
            hint = text or (
                f"RunningHub 网关返回了 HTTP {status} 且响应体为空。"
                "这通常是 RunningHub 服务端瞬时故障（网关 5xx），请直接重试一次；"
                f"若持续出现，请到 runninghub.cn 检查账户余额与 API Key 状态。"
            )
            raise HTTPException(status_code=status if status >= 400 else 502, detail=f"RunningHub 视频接口错误：{hint}") from exc
        except httpx.HTTPError as exc:
            log_net_error(f"视频(RunningHub) 网络/TLS错误 model={payload.model}", exc)
            raise HTTPException(status_code=502, detail=f"请求 RunningHub 视频接口失败：{exc}") from exc
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    validate_safe_url(base_url, allow_private=False)
    api_key = provider_env_key_value(provider["id"])
    if not api_key:
        raise HTTPException(status_code=400, detail=f"未配置 {provider.get('name') or provider['id']} 的 API Key，请在 API 设置中填写。")
    is_apimart = is_apimart_provider(provider)
    is_volcengine = is_volcengine_provider(provider)
    is_yuli = is_yuli_provider(provider)
    is_lingjing = is_lingjing_provider(provider)
    is_agnes = is_agnes_provider(provider, payload.model)
    volc_is_proxy = bool(is_volcengine and urllib.parse.urlparse(base_url).path.rstrip("/"))
    submit_urls = video_submit_url_candidates(provider, base_url)
    submit_url = submit_urls[0]
    requested_model = selected_model(payload.model, "agnes-video-v2.0" if is_agnes else "veo3-fast")
    if is_tudou_provider(provider) and is_tudou_video_model(requested_model):
        try:
            async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=VIDEO_POLL_TIMEOUT) as tudou_client:
                if is_tudou_grok_video_model(requested_model):
                    return await generate_tudou_grok_video(tudou_client, payload, provider, base_url, requested_model)
                return await generate_tudou_video(tudou_client, payload, provider, base_url, requested_model)
        except httpx.HTTPStatusError as exc:
            text = exc.response.text
            friendly = friendly_video_error_detail(text, requested_model, provider)
            raise HTTPException(status_code=exc.response.status_code, detail=friendly or f"土豆视频接口错误：{text}") from exc
        except httpx.HTTPError as exc:
            log_net_error(f"视频(土豆) 网络/TLS错误 model={requested_model}", exc)
            raise HTTPException(status_code=502, detail=f"请求土豆视频接口失败：{exc}") from exc
    is_veo31 = is_apimart and is_apimart_veo31_model(requested_model)
    if is_agnes:
        try:
            async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=VIDEO_POLL_TIMEOUT) as agnes_client:
                return await generate_agnes_video(agnes_client, payload, provider, base_url, requested_model)
        except httpx.HTTPStatusError as exc:
            text = exc.response.text
            raise HTTPException(status_code=exc.response.status_code, detail=f"Agnes 视频接口错误：{text}") from exc
        except httpx.HTTPError as exc:
            log_net_error(f"视频(Agnes) 网络/TLS错误 model={requested_model}", exc)
            raise HTTPException(status_code=502, detail=f"请求 Agnes 视频接口失败：{exc}") from exc
    if is_dashscope_provider(provider):
        try:
            async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=VIDEO_POLL_TIMEOUT) as ds_client:
                return await generate_dashscope_video(ds_client, payload, provider, base_url, requested_model)
        except httpx.HTTPStatusError as exc:
            text = (exc.response.text or "").strip()
            raise HTTPException(status_code=exc.response.status_code, detail=f"阿里百炼视频接口错误：{text}") from exc
        except httpx.HTTPError as exc:
            log_net_error(f"视频(DashScope) 网络/TLS错误 model={requested_model}", exc)
            raise HTTPException(status_code=502, detail=f"请求阿里百炼视频接口失败：{exc}") from exc
    if is_meigen_provider(provider):
        try:
            async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=VIDEO_POLL_TIMEOUT) as meigen_client:
                return await generate_meigen_video(meigen_client, payload, provider, base_url, requested_model)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"MeiGen 视频生成失败：{exc}") from exc
    if is_lingjing:
        try:
            async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=VIDEO_POLL_TIMEOUT) as lingjing_client:
                return await generate_lingjing_openai_video(lingjing_client, payload, provider, base_url, requested_model)
        except httpx.HTTPStatusError as exc:
            text = exc.response.text
            raise HTTPException(status_code=exc.response.status_code, detail=f"灵境 API 视频接口错误：{text}") from exc
        except httpx.HTTPError as exc:
            log_net_error(f"视频(灵境) 网络/TLS错误 model={requested_model}", exc)
            raise HTTPException(status_code=502, detail=f"请求灵境 API 视频接口失败：{exc}") from exc
    # 玉玉API veo3.1 走 OpenAI multipart 格式（支持 seconds 时长）；其余模型（doubao 等）
    # 沿用下方原生 /v1/video/create JSON 流程。
    if is_yuli and yuli_is_veo_openai_model(requested_model):
        try:
            async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=VIDEO_POLL_TIMEOUT) as yuli_client:
                return await generate_yuli_openai_video(yuli_client, payload, provider, base_url, requested_model)
        except httpx.HTTPStatusError as exc:
            text = exc.response.text
            raise HTTPException(status_code=exc.response.status_code, detail=f"上游视频接口错误：{text}") from exc
        except httpx.HTTPError as exc:
            log_net_error(f"视频(玉玉) 网络/TLS错误 model={requested_model}", exc)
            raise HTTPException(status_code=502, detail=f"请求上游视频接口失败：{exc}") from exc
    try:
        async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=VIDEO_POLL_TIMEOUT) as client:
            # --- 构造图片载荷 ---
            if is_apimart:
                # APIMart 只接受 http/https 或 asset:// URL，先上传本地图片取回网络 URL
                image_with_roles = []
                invalid_images = []  # 每项为 (原始 URL, 失败原因)
                video_payload = []
                invalid_videos = []
                for ref_url in payload.videos[:3]:
                    ref_url = str(ref_url or "").strip()
                    if not ref_url:
                        continue
                    if looks_like_image_media_url(ref_url):
                        invalid_videos.append((ref_url, "该地址是图片，不能作为参考视频。请将图片放入图片输入。"))
                        continue
                    normalized_video_url = await upload_video_for_apimart(client, provider, ref_url)
                    if valid_apimart_video_image_input(normalized_video_url):
                        video_payload.append(normalized_video_url)
                    else:
                        reason = normalized_video_url[4:] if isinstance(normalized_video_url, str) and normalized_video_url.startswith("ERR:") else apimart_video_reference_error(ref_url)
                        invalid_videos.append((ref_url, reason))
                if invalid_videos:
                    first_url, first_reason = invalid_videos[0]
                    sample = invalid_video_image_preview(first_url)
                    raise HTTPException(
                        status_code=400,
                        detail=f"输入视频无法转换为 APIMart 支持的格式：{sample}\n原因：{first_reason}"
                    )
                apimart_model = apimart_veo31_model(requested_model) if is_veo31 else ""
                if apimart_model == "veo3.1-lite" and payload.images:
                    raise HTTPException(status_code=400, detail="veo3.1-lite 不支持图片输入，请改用 veo3.1-fast 或 veo3.1-quality。")
                image_limit = 0 if apimart_model == "veo3.1-lite" else (3 if is_veo31 else 9)
                for ref in payload.images[:image_limit]:
                    if not ref.url:
                        continue
                    role = str(ref.role or "").strip()
                    if not is_veo31 and role in {"first_frame", "last_frame", "reference_image"}:
                        up_url = await upload_image_for_apimart(client, provider, ref.url)
                        if valid_apimart_video_image_input(up_url):
                            image_with_roles.append({"url": up_url, "role": role})
                        else:
                            reason = up_url[4:] if isinstance(up_url, str) and up_url.startswith("ERR:") else "未知错误"
                            invalid_images.append((ref.url, reason))
                image_payload = []
                if not image_with_roles:
                    for ref in payload.images[:image_limit]:
                        if not ref.url:
                            continue
                        up_url = await upload_image_for_apimart(client, provider, ref.url)
                        if valid_apimart_video_image_input(up_url):
                            image_payload.append(up_url)
                        else:
                            reason = up_url[4:] if isinstance(up_url, str) and up_url.startswith("ERR:") else "未知错误"
                            invalid_images.append((ref.url, reason))
                if payload.images and not image_with_roles and not image_payload:
                    first_url, first_reason = invalid_images[0] if invalid_images else ("", "未知错误")
                    sample = invalid_video_image_preview(first_url)
                    raise HTTPException(status_code=400, detail=f"输入图片无法转换为视频接口支持的格式：{sample}\n原因：{first_reason}\n请确认本地文件存在且不超过 10MB；VEO3.1 需要图片是 APIMart 可访问的 http/https / asset:// / data URL。")
                # --- APIMart 请求体 ---
                if is_veo31:
                    model = apimart_model
                    body = {
                        "prompt": payload.prompt,
                        "model": model,
                        "duration": apimart_veo31_duration(payload.duration),
                        "aspect_ratio": apimart_veo31_aspect(payload.aspect_ratio),
                        "resolution": apimart_veo31_resolution(payload.resolution),
                    }
                    if image_payload and model != "veo3.1-lite":
                        video_images = image_payload[:3]
                        if model == "veo3.1-quality" and len(video_images) > 2:
                            video_images = video_images[:2]
                        body["image_urls"] = video_images
                        if len(video_images) == 2:
                            body["generation_type"] = "frame"
                        elif len(video_images) >= 3 and model != "veo3.1-quality":
                            body["generation_type"] = "reference"
                    if model != "veo3.1-lite":
                        body["official_fallback"] = False
                else:
                    body = {
                        "prompt": payload.prompt,
                        "model": selected_model(payload.model, "doubao-seedance-2.0"),
                        "duration": apimart_video_duration(payload.duration),
                        "size": apimart_video_size(payload.aspect_ratio or payload.size),
                        "resolution": payload.resolution or "480p",
                    }
                    if image_with_roles and video_payload:
                        raise HTTPException(status_code=400, detail="APIMart Seedance 的 image_with_roles 不能和 video_urls 同时使用，请只保留图片首尾帧或参考视频其中一种。")
                    if image_with_roles:
                        body["image_with_roles"] = image_with_roles
                    elif image_payload:
                        body["image_urls"] = image_payload[:9]
                    if video_payload:
                        body["video_urls"] = video_payload
                    audio_payload = []
                    invalid_audios = []
                    for ref_url in (payload.audios or [])[:3]:
                        ref_url = str(ref_url or "").strip()
                        if not ref_url:
                            continue
                        normalized_audio_url = await upload_audio_for_apimart(client, provider, ref_url)
                        if valid_apimart_video_image_input(normalized_audio_url):
                            audio_payload.append(normalized_audio_url)
                        else:
                            reason = normalized_audio_url[4:] if isinstance(normalized_audio_url, str) and normalized_audio_url.startswith("ERR:") else "未知错误"
                            invalid_audios.append((ref_url, reason))
                    if invalid_audios:
                        first_url, first_reason = invalid_audios[0]
                        raise HTTPException(status_code=400, detail=f"参考音频无法转换为 APIMart 支持的地址：{invalid_video_image_preview(first_url)}\n原因：{first_reason}")
                    if audio_payload:
                        body["audio_urls"] = audio_payload
                    if payload.trusted_asset:
                        img_count = len(body.get("image_urls") or []) or len(image_with_roles)
                        body["prompt"] = apply_trusted_asset_prompt_index(
                            body["prompt"], img_count, len(video_payload), len(audio_payload)
                        )
                    if payload.seed is not None:
                        body["seed"] = payload.seed
                    if payload.return_last_frame:
                        body["return_last_frame"] = True
                    if payload.generate_audio:
                        body["generate_audio"] = True
            else:
                # 非 APIMart：data URL 方式（OpenAI / ComflyAI 接口）
                if is_volcengine and not volc_is_proxy:
                    text = str(payload.prompt or "").strip()
                    volc_model = selected_model(payload.model, "doubao-seedance-2-0-fast-260128")
                    body = {
                        "model": volc_model,
                        "content": [
                            {
                                "type": "text",
                                "text": text,
                            }
                        ],
                    }
                    # 火山方舟视频接口（含 Seedance 2.0 图生视频）均通过 body 的 duration 字段控制时长；
                    # 之前对 seedance-2.0 + 参考图的情况省略了 duration，导致接口回退到默认 5s。
                    body["duration"] = volcengine_video_duration(payload.duration)
                    if payload.aspect_ratio:
                        body["ratio"] = payload.aspect_ratio
                    resolution = volcengine_video_resolution(payload.resolution)
                    if resolution:
                        body["resolution"] = resolution
                    if payload.watermark:
                        body["watermark"] = True
                    if payload.generate_audio:
                        body["generate_audio"] = True
                    if payload.camerafixed:
                        body["camerafixed"] = True
                    image_like_urls = set()
                    frame_roles_used = {"first_frame": False, "last_frame": False}
                    volc_video_count = 0

                    def append_volcengine_image(url: str, role: str):
                        if role in {"first_frame", "last_frame"}:
                            if frame_roles_used.get(role):
                                return False
                            frame_roles_used[role] = True
                        elif role != "reference_image":
                            return False
                        body["content"].append({
                            "type": "image_url",
                            "image_url": {"url": url},
                            "role": role,
                        })
                        image_like_urls.add(url)
                        return True

                    for ref in payload.images[:9]:
                        url = volcengine_media_reference_url(ref.url, max_image_size=1536)
                        if not url:
                            continue
                        role = volcengine_content_role(ref.role, "image")
                        if role in {"first_frame", "last_frame"}:
                            append_volcengine_image(url, role)
                        elif payload.multimodal:
                            # 智能多帧/多参模式：多张图作为参考图提交，不能全部伪装成首帧。
                            append_volcengine_image(url, "reference_image")
                        elif not frame_roles_used["first_frame"]:
                            # 普通图生视频没有显式 role 时，只取第一张作为首帧。
                            append_volcengine_image(url, "first_frame")
                    for url in (payload.videos or [])[:3]:
                        text_url = str(url or "").strip()
                        if not text_url:
                            continue
                        media_url = volcengine_media_reference_url(text_url, max_image_size=1536 if looks_like_image_media_url(text_url) else None)
                        if not media_url:
                            continue
                        if media_url in image_like_urls or looks_like_image_media_url(media_url):
                            append_volcengine_image(media_url, "reference_image" if payload.multimodal else "first_frame")
                            continue
                        video_items = await volcengine_video_reference_content_items(media_url)
                        body["content"].extend(video_items)
                        volc_video_count += 1
                    for url in (payload.audios or [])[:3]:
                        duration = probe_local_audio_duration_seconds(url)
                        if duration is not None and (duration < 1.8 or duration > 15.2):
                            raise HTTPException(
                                status_code=400,
                                detail=f"参考音频时长 {duration:.2f} 秒超出范围：方舟 Seedance 参考音频要求在 1.8 ~ 15.2 秒之间，请裁剪后再插入。"
                            )
                        audio_url = volcengine_media_reference_url(url, max_image_size=None)
                        if not audio_url:
                            continue
                        body["content"].append({
                            "type": "audio_url",
                            "audio_url": {"url": audio_url},
                            "role": volcengine_content_role("", "audio"),
                        })
                    if payload.trusted_asset and body["content"] and body["content"][0].get("type") == "text":
                        body["content"][0]["text"] = apply_trusted_asset_prompt_index(
                            body["content"][0].get("text") or "", len(image_like_urls), volc_video_count, 0
                        )
                    if payload.seed is not None:
                        body["seed"] = payload.seed
                elif is_yuli:
                    # 玉玉API（yuli.host）视频走自有 veo 统一格式：POST /v1/video/create。
                    # 字段：model / prompt / images[]（http(s) URL）/ enhance_prompt /
                    # enable_upsample / aspect_ratio（仅 16:9、9:16）。无 duration 字段，
                    # 时长由模型本身决定，所以这里不传 duration/seconds。
                    yuli_images = []
                    for ref in payload.images[:3]:
                        ref_url = str(getattr(ref, "url", "") or "").strip()
                        if not ref_url:
                            continue
                        if ref_url.startswith("http://") or ref_url.startswith("https://"):
                            yuli_images.append(ref_url)
                        else:
                            # 本地/dataURL 图片转成 data URL 兜底传递
                            data_url = reference_to_data_url(dump_pydantic(ref), max_size=1536)
                            if data_url:
                                yuli_images.append(data_url)
                    prompt_text = str(payload.prompt or "")
                    # veo 只支持英文提示词：仅在含中文等非 ASCII 字符时才开启翻译增强，
                    # 纯英文原样传递（避免增强改写时引入人物等触发安全过滤的描述）。
                    needs_enhance = any(ord(ch) > 127 for ch in prompt_text)
                    body = {
                        "model": selected_model(payload.model, "veo3.1-fast"),
                        "prompt": prompt_text,
                        "enhance_prompt": needs_enhance,
                    }
                    if yuli_images:
                        body["images"] = yuli_images
                    ratio = str(payload.aspect_ratio or "").strip()
                    if ratio in {"16:9", "9:16"}:
                        body["aspect_ratio"] = ratio
                    if payload.enable_upsample:
                        body["enable_upsample"] = True
                else:
                    image_payload = []
                    for ref in payload.images[:4]:
                        if ref.url:
                            image_payload.append(reference_to_data_url(dump_pydantic(ref), max_size=1536))
                    body = {
                        "prompt": payload.prompt,
                        "model": selected_model(payload.model, "veo3-fast"),
                        "duration": payload.duration,
                        "watermark": payload.watermark,
                    }
                    if payload.aspect_ratio:
                        body["aspect_ratio"] = payload.aspect_ratio
                        body["ratio"] = payload.aspect_ratio
                    if payload.size:
                        body["size"] = payload.size
                    if payload.resolution:
                        body["resolution"] = payload.resolution
                    if image_payload:
                        body["images"] = image_payload
                    if payload.videos:
                        body["videos"] = [v for v in payload.videos if v]
                    if payload.enhance_prompt:
                        body["enhance_prompt"] = True
                    if payload.enable_upsample:
                        body["enable_upsample"] = True
                    if payload.seed is not None:
                        body["seed"] = payload.seed
                    if payload.camerafixed:
                        body["camerafixed"] = True
                    if payload.return_last_frame:
                        body["return_last_frame"] = True
                    if payload.generate_audio:
                        body["generate_audio"] = True
            # --- 发起视频生成请求 ---
            raw = None
            html_response = None
            last_response = None
            last_json_error = None
            total_candidates = len(submit_urls)
            for idx, candidate_url in enumerate(submit_urls):
                submit_url = candidate_url
                validate_safe_url(submit_url, allow_private=False)
                is_last = idx == total_candidates - 1
                response = await client.post(submit_url, headers=api_headers(provider=provider), json=body)
                last_response = response
                if response.status_code >= 400:
                    # 404/405（或直接返回网页 HTML）通常表示该平台不支持这个端点路径——
                    # 例如有的站点只实现了统一格式的 /v2/videos/generations，而我们先试了 /v1。
                    # 这种情况要继续尝试下一个候选端点（关键修复：以前在这里直接 raise_for_status，
                    # 第一个 /v1 报错就抛出，永远轮不到 /v2，表现为“接口错误”）。
                    # 其它错误（模型不支持/时长/额度等请求被拒）说明端点是存在的，直接抛出交给外层友好提示。
                    endpoint_missing = response.status_code in (404, 405) or looks_like_html_response(response.text)
                    if endpoint_missing and not is_last:
                        continue
                    response.raise_for_status()
                try:
                    raw = response.json()
                    break
                except Exception as exc:
                    last_json_error = exc
                    if looks_like_html_response(response.text):
                        html_response = response
                        continue
                    if not is_last:
                        continue
                    resp_text = response.text[:500]
                    raise HTTPException(status_code=502, detail=f"上游视频接口返回非 JSON 响应（状态 {response.status_code}）：{resp_text}")
            if raw is None:
                resp = html_response or last_response
                status_code = getattr(resp, "status_code", 200)
                resp_text = (getattr(resp, "text", "") or "")[:500]
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"上游视频接口返回了网页 HTML，而不是 JSON（状态 {status_code}）。\n\n"
                        f"这通常表示 API 设置里的 Base URL 指到了第三方聚合平台的管理后台/网页入口，"
                        f"或该平台不支持当前视频接口路径。请确认 Base URL 是接口地址，例如以 /v1 结尾的 OpenAI 兼容地址，"
                        f"并确认该平台实际支持视频生成端点。\n\n原始响应：{resp_text}"
                    )
                ) from last_json_error
            task_id = extract_task_id(raw) or raw.get("task_id") or raw.get("id")
            result = raw
            if task_id and not video_output_urls(raw):
                result = await wait_for_video_task(client, provider, task_id, submit_url)
            urls = video_output_urls(result)
            if not urls:
                raise HTTPException(status_code=502, detail=f"视频生成成功但没有返回视频：{result}")
            local_urls = [await save_remote_video_to_output(url) for url in urls]
            return {"videos": local_urls, "task_id": task_id, "raw": result}
    except httpx.HTTPStatusError as exc:
        text = exc.response.text
        try:
            requested_model = body.get("model", "") or payload.model or ""
        except NameError:
            requested_model = payload.model or ""
        provider_name = provider.get('name') or provider['id']
        # 1) 模型名不在上游支持范围 → 从错误信息里抽取合法列表展示
        valid_models_match = re.search(r"not in\s*\[([^\]]+)\]", text)
        if valid_models_match:
            valid_models = [m.strip() for m in valid_models_match.group(1).split(",") if m.strip()]
            sample = valid_models[:30]
            more = f"（共 {len(valid_models)} 个，仅显示前 {len(sample)} 个）" if len(valid_models) > len(sample) else ""
            hint = (
                f"上游「{provider_name}」不识别模型「{requested_model}」。\n\n"
                f"上游支持的视频模型清单{more}：\n  {', '.join(sample)}\n\n"
                f"请到「API 设置」里把视频模型改成上面列表中的一个。"
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        # 2) 模型名合法但账号没开通通道
        if "channel not found" in text or "model_not_found" in text:
            hint = (
                f"上游「{provider_name}」识别了模型「{requested_model}」，但你的 API Key 账号下**没有该模型的可用通道**。\n\n"
                f"原因：你的账号没开通这个模型的访问权限（付费/订阅相关）。\n\n"
                f"解决方法：\n"
                f"  1. 登录 {provider.get('base_url') or '上游平台'} 控制台，开通该模型 / 充值；\n"
                f"  2. 或在「API 设置」里把视频模型改成你账号已开通的型号（如 veo3-fast / veo2-fast / sora-2 等）。"
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        if "text.duration" in text or "specified duration is not supported" in text:
            hint = (
                f"上游「{provider_name}」模型「{requested_model}」不支持当前时长参数。\n\n"
                f"不同视频模型支持的时长不一样；如果选择了模型不支持的时长，上游可能报错，"
                f"也可能自动按平台默认时长生成，例如 5 秒。\n\n"
                f"请把视频时长切回该模型支持的值，或改用支持更长时长的视频模型。"
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        if "audio duration" in text.lower():
            too_long = "less than or equal" in text.lower() or "15.2" in text
            bound_hint = "太长（超过 15.2 秒）" if too_long else "太短（不足 1.8 秒）"
            hint = (
                f"上游「{provider_name}」模型「{requested_model}」拒绝了参考音频：时长{bound_hint}。\n\n"
                f"方舟 Seedance 的参考音频时长必须在 1.8 ~ 15.2 秒之间，"
                f"请把音频裁剪到这个区间后再作为参考音频输入。"
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        if "inputimagesensitivecontentdetected" in text.lower() or "privacyinformation" in text.lower() or "may contain real person" in text.lower():
            hint = (
                f"上游「{provider_name}」拦截了输入参考图，原因是图片里可能包含真人身份/隐私信息。\n\n"
                f"这不是代码协议错误，而是火山视频模型的内容安全策略。\n\n"
                f"建议你这样处理：\n"
                f"  1. 改用非真人参考图，例如插画、AI 头像、商品图、场景图；\n"
                f"  2. 先把真人脸做模糊、遮挡、裁掉，或转成明显的二次元/插画风；\n"
                f"  3. 如果只是想做文生视频，先去掉参考图只保留文字提示词测试。"
            )
            raise HTTPException(status_code=exc.response.status_code, detail=hint) from exc
        raise HTTPException(status_code=exc.response.status_code, detail=f"上游视频接口错误：{text}") from exc
    except httpx.HTTPError as exc:
        log_net_error(f"视频 网络/TLS错误 provider={provider.get('id')} model={payload.model}", exc)
        raise HTTPException(status_code=502, detail=f"请求上游视频接口失败：{exc}") from exc

# --- Canvas LLM ---

