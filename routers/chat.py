"""Cloud AI Chat, Conversations & Multi-modal Agent Router for Infinite-Canvas.

Decoupled router providing endpoints and execution engines for:
- Chat Streaming (OpenAI, ModelScope, Gemini, Codex, Jimeng, Volcengine)
- Multi-modal Intelligent Agent (Heuristic action decision, parallel image dispatch)
- Canvas LLM (Direct multi-modal context node generation)
- Conversation Management (CRUD & persistence under data/conversations/)
- Image Captioning, Classification & Avatar Certification Hooks
"""
import os
import re
import sys
import json
import time
import math
import uuid
import zipfile
import base64
import hashlib
import asyncio
import logging
import html
import shutil
import tempfile
import subprocess
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from io import BytesIO
from typing import Dict, Any, List, Optional, Tuple, Set, Union
from urllib.parse import urlparse, quote, unquote

import httpx
from PIL import Image
from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, File, Form, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

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
    AI_BASE_URL,
    IMAGE_MODEL,
    VIDEO_POLL_TIMEOUT,
    AI_REQUEST_TIMEOUT,
    CHAT_MODEL,
    CHAT_MODELS,
    LLM_MESSAGE_MAX_LENGTH,
    MAX_HISTORY_MESSAGES,
    CHAT_ATTACHMENT_MAX,
    SYSTEM_PROMPT,
    MODELSCOPE_CHAT_BASE_URL,
    MODELSCOPE_DEFAULT_CHAT_MODEL,
    MODELSCOPE_DEFAULT_CHAT_MODELS,
    MODELSCOPE_CHAT_MODELS,
    RUNNINGHUB_LLM_BASE_URL,
    CODEX_DEFAULT_CHAT_MODELS,
    GEMINI_CLI_DEFAULT_CHAT_MODELS,
    VOLCENGINE_DEFAULT_PROJECT_NAME,
    effective_protocol,
    get_primary_provider_id,
    now_ms,
    get_api_provider,
    get_api_provider_exact,
    bearer_auth_value,
    provider_endpoint_url,
    provider_env_key_value,
    provider_protocol,
    read_api_env_value,
    load_api_providers,
    save_api_providers,
    update_env_values,
    dump_pydantic,
    model_list_from_values,
    modelscope_api_key,
    modelscope_api_root,
    modelscope_provider_config,
    log_upstream_call,
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
)
from core.security import safe_download_bytes
from routers.models import (
    ChatRequest,
    CanvasLLMRequest,
    ConversationCreateRequest,
    AIReference,
    OnlineImageRequest,
)
from routers.assets import (
    output_url_for,
    output_path_for,
    ensure_same_origin_request,
    AssetAvatarRegisterRequest,
    asset_classification_prompt,
    parse_asset_classification_text,
)
from routers.online_image import chat_prompt_size_override
from routers.video import upload_media_for_apimart, valid_apimart_video_image_input
from routers.integrations import volcengine_public_asset_url
from routers.common import (
    save_to_history,
    WsProxy,
    api_headers,
    is_volcengine_provider,
    is_runninghub_provider,
    is_jimeng_provider,
    is_codex_provider,
    is_gemini_cli_provider,
    is_gemini_provider,
    is_tudou_provider,
    is_apimart_provider,
    is_meigen_provider,
    is_pollinations_provider,
    avatar_platform_for_provider,
    AVATAR_SUPPORTED_PLATFORMS,
    looks_like_generated_image_url,
    looks_like_image_base64,
    image_payload_from_string,
    extract_image_flexible,
    extract_images,
    extract_image,
    extract_task_id,
    extract_task_id_from_text,
    public_base_url,
    public_media_url_suffix,
    local_asset_public_url,
    save_ai_image_to_output,
    image_output_meta,
    save_remote_video_to_output,
    parse_size_pair,
    snap_size_to_multiple,
    friendly_image_error_detail,
    parse_error_payload_text,
    friendly_chat_error_detail,
    sanitize_error_detail,
    post_openai_responses_stream,
    video_reference_to_frame_data_urls,
)
from routers.integrations import (
    codex_chat_text,
    gemini_cli_chat_text,
    submit_volcengine_avatar_asset,
    check_volcengine_avatar_task,
)
from routers.video import (
    submit_apimart_avatar_asset,
    check_apimart_avatar_task,
)
from routers.online_image import (
    generate_ai_image,
)

logger = logging.getLogger("infinite_canvas.chat")
_server_logger = logging.getLogger("dx.server")

router = APIRouter(tags=["chat"])

import threading
CONVERSATION_LOCK = threading.Lock()

def unwrap_apimart_response(payload):
    if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], (dict, list)):
        return payload["data"]
    return payload


# --- Sliced from online.py lines 312-315 ---
def chat_system_prompt(payload):
    prompt = str(getattr(payload, "system_prompt", "") or "").strip()
    return prompt or SYSTEM_PROMPT



# --- Sliced from online.py lines 360-438 ---
def safe_user_id(user_id, request: Request = None):
    candidate = str(getattr(user_id, "default", user_id) or "").strip()
    if not candidate and request and getattr(request, "client", None):
        candidate = f"ip-{request.client.host}"
    if not candidate:
        candidate = "anonymous"
    candidate = re.sub(r"[^a-zA-Z0-9_.-]", "-", candidate)[:80].strip(".-")
    return candidate or "anonymous"

def user_dir(user_id):
    path = os.path.join(CONVERSATION_DIR, user_id)
    os.makedirs(path, exist_ok=True)
    return path

def conversation_path(user_id, conversation_id):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", conversation_id or "")
    if not cleaned:
        raise HTTPException(status_code=400, detail="无效的对话 ID")
    return os.path.join(user_dir(user_id), f"{cleaned}.json")

def now_ms():
    return int(time.time() * 1000)

def save_conversation(user_id, conversation):
    with CONVERSATION_LOCK:
        path = conversation_path(user_id, conversation["id"])
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(conversation, f, ensure_ascii=False, indent=2)

def new_conversation(user_id, title="新对话"):
    timestamp = now_ms()
    conversation = {
        "id": uuid.uuid4().hex,
        "title": (title or "新对话")[:80],
        "created_at": timestamp,
        "updated_at": timestamp,
        "messages": [],
    }
    save_conversation(user_id, conversation)
    return conversation

def load_conversation(user_id, conversation_id):
    path = conversation_path(user_id, conversation_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="对话不存在")
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def list_conversations(user_id):
    records = []
    for filename in os.listdir(user_dir(user_id)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(user_dir(user_id), filename)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        messages = data.get("messages", [])
        last_message = next((m for m in reversed(messages) if m.get("role") != "system"), None)
        records.append({
            "id": data.get("id"),
            "title": data.get("title", "新对话"),
            "created_at": data.get("created_at", 0),
            "updated_at": data.get("updated_at", 0),
            "last_message": (last_message or {}).get("content", ""),
        })
    return sorted(records, key=lambda item: item["updated_at"], reverse=True)
# 画布与项目管理核心函数与缓存已解耦迁移至 routers/canvas.py 并于文件头部引入


# 画布资产提取与索引核心函数已解耦迁移至 routers/assets.py


def display_title(text):
    title = re.sub(r"\s+", " ", text or "").strip()
    return title[:24] or "新对话"



# --- Sliced from online.py lines 439-509 ---
def resolve_chat_provider(provider: str, model: str, ms_model: str):
    if provider == "modelscope":
        clean_token = modelscope_api_key()
        if not clean_token:
            raise HTTPException(status_code=400, detail="未配置 ModelScope API Key，请在 API 设置中填写。")
        base = modelscope_api_root()
        hdrs = {"Authorization": bearer_auth_value(clean_token), "Content-Type": "application/json"}
        mdl = selected_model(ms_model or model, MODELSCOPE_CHAT_MODELS[0] if MODELSCOPE_CHAT_MODELS else "MiniMax/MiniMax-M2.7")
        return base, hdrs, mdl
    api_provider = get_api_provider(provider or "")
    if is_codex_provider(api_provider):
        raise HTTPException(status_code=400, detail="OpenAI CLI 使用本机 codex 登录态，不需要 API Key。请使用画布/聊天里的 OpenAI CLI 专用通道。")
    if is_gemini_cli_provider(api_provider):
        raise HTTPException(status_code=400, detail="Antigravity CLI 使用本机 agy 登录态，不需要 API Key。请使用画布/聊天里的 Antigravity CLI 专用通道。")
    base_root = (api_provider.get("base_url") or AI_BASE_URL).rstrip("/")
    if not base_root:
        raise HTTPException(status_code=400, detail=f"{api_provider.get('name') or api_provider['id']} 未配置 Base URL")
    default_model = preferred_chat_model(api_provider)
    mdl = selected_model(model, default_model)
    protocol = effective_protocol(api_provider, mdl)
    if protocol == "gemini":
        # APIMart's native Gemini API is served from its official API domain.
        # Keep the configured base URL for its OpenAI-compatible models only.
        if is_apimart_provider(api_provider):
            base_root = "https://api.apimart.ai"
        if "generativelanguage.googleapis.com" in base_root:
            base = "https://generativelanguage.googleapis.com/v1beta/openai"
        else:
            base = base_root if base_root.endswith("/v1beta") else base_root + "/v1beta"
    elif protocol == "volcengine":
        base = base_root if base_root.endswith("/api/v3") else base_root + "/api/v3"
    elif protocol == "runninghub":
        base = RUNNINGHUB_LLM_BASE_URL
    else:
        if base_root.endswith("/openai") or base_root.endswith("/v1"):
            base = base_root
        elif "generativelanguage.googleapis.com" in base_root:
            base = "https://generativelanguage.googleapis.com/v1beta/openai"
        else:
            base = base_root + "/v1"
    hdrs = api_headers(provider=api_provider, model=mdl)
    return base, hdrs, mdl

def log_net_error(context, exc, url=""):
    """把网络请求异常的完整链路（含底层 SSL/socket 原因）打到控制台，方便排查 VPN/代理问题。
    httpx 通常把真正的 SSL/连接错误包在 __cause__/__context__ 里，这里把整条链都打出来，
    并附上请求 URL 与当前生效的系统代理，便于判断是「代理瞬时 TLS 错误」还是「线路不通」。
    日志本身绝不能影响主流程，全部包在 try 里。"""
    try:
        chain = []
        cur = exc
        seen = 0
        while cur is not None and seen < 6:
            chain.append(f"{type(cur).__module__}.{type(cur).__name__}: {str(cur)[:200]}")
            nxt = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)
            if nxt is cur:
                break
            cur = nxt
            seen += 1
        if not url:
            req = getattr(exc, "request", None)
            if req is not None:
                url = str(getattr(req, "url", "") or "")
        try:
            proxies = urllib.request.getproxies() or "无"
        except Exception:
            proxies = "?"
        line = f"[NET-ERR] {context} | url={url or '?'} | sys_proxy={proxies} | " + " <- ".join(chain)
        try:
            _server_logger.warning(line)
        except Exception:  # noqa: BLE001
            pass
    except Exception:
        try:
            _server_logger.warning(f"[NET-ERR] {context} | {type(exc).__name__}: {exc}")
        except Exception:
            pass



# --- Sliced from online.py lines 532-563 ---
def selected_model(requested, fallback):
    model = (requested or fallback).strip()
    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if len(model) > 240 or any(ord(ch) < 32 or ord(ch) == 127 for ch in model):
        raise HTTPException(status_code=400, detail=f"模型名称不合法：{model}")
    return model

def looks_like_vision_chat_model(model):
    lc = str(model or "").strip().lower()
    if not lc:
        return False
    vision_keys = [
        "vision", "vl-", "-vl-", "internvl", "qvq", "qwen-vl",
        "doubao-vision", "glm-4v", "minicpm-v",
    ]
    return any(key in lc for key in vision_keys)

def preferred_chat_model(provider):
    values = [str(item or "").strip() for item in (provider.get("chat_models") or [CHAT_MODEL])]
    models = [item for item in values if item]
    if not models:
        return CHAT_MODEL
    if is_volcengine_provider(provider):
        endpoint_models = [item for item in models if item.lower().startswith("ep-")]
        if endpoint_models:
            return endpoint_models[0]
        text_like_models = [item for item in models if not looks_like_vision_chat_model(item)]
        if text_like_models:
            return text_like_models[0]
    return models[0]



# --- Sliced from online.py lines 576-620 ---
def text_from_chat_response(data):
    data = unwrap_apimart_response(data)
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
        return "\n".join(part for part in parts if part)
    return str(content)

def text_delta_from_chat_chunk(data):
    choices = data.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
        return "".join(parts)
    return str(content) if content else ""

def sse_event(data):
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

IMAGE_OUTPUT_KEY_HINTS = (
    "url", "image_url", "imageUrl", "image", "output_url", "outputUrl",
    "result_url", "resultUrl", "download_url", "downloadUrl", "asset_url", "assetUrl",
)
IMAGE_CONTAINER_KEY_HINTS = (
    "images", "image", "output", "outputs", "result", "results", "data", "items", "files",
)
IMAGE_BASE64_KEY_HINTS = ("b64_json", "base64", "image_base64", "imageBase64")

def provider_protocol(provider):
    return str((provider or {}).get("protocol") or "openai").strip().lower()

# 单模型可覆盖的协议（仅 OpenAI / Gemini，二者可共用同一站点的 Base URL + Key）
PER_MODEL_PROTOCOL_OPTIONS = {"openai", "gemini"}
# 协议固定、不支持单模型覆盖的内置平台
FIXED_PROTOCOL_PROVIDER_IDS = {"modelscope", "volcengine", "jimeng", "runninghub"}



# --- Sliced from online.py lines 3727-3945 ---
MAX_ATTACHMENT_TEXT_CHARS = 12000

def _xml_local_name(tag):
    return str(tag or "").rsplit("}", 1)[-1]

def _xlsx_join_text(node):
    parts = []
    for child in node.iter():
        if _xml_local_name(child.tag) == "t" and child.text:
            parts.append(child.text)
    return "".join(parts).strip()

def _xlsx_shared_strings(archive):
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    values = []
    for node in root:
        if _xml_local_name(node.tag) == "si":
            values.append(_xlsx_join_text(node))
    return values

def _xlsx_sheet_paths(archive):
    names = set(archive.namelist())
    fallback = [(os.path.basename(name).rsplit(".", 1)[0], name) for name in sorted(names) if re.match(r"xl/worksheets/sheet\d+\.xml$", name)]
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {}
        for rel in rels:
            rid = rel.attrib.get("Id")
            target = rel.attrib.get("Target") or ""
            if not rid or not target:
                continue
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            rel_map[rid] = target.replace("\\", "/")
        result = []
        for sheet in workbook.iter():
            if _xml_local_name(sheet.tag) != "sheet":
                continue
            title = sheet.attrib.get("name") or "Sheet"
            rid = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_map.get(rid, "")
            if target in names:
                result.append((title, target))
        return result or fallback
    except Exception:
        return fallback

def _xlsx_cell_text(cell, shared_strings):
    cell_type = cell.attrib.get("t", "")
    value_node = None
    formula_node = None
    inline_node = None
    for child in cell:
        name = _xml_local_name(child.tag)
        if name == "v":
            value_node = child
        elif name == "f":
            formula_node = child
        elif name == "is":
            inline_node = child
    raw_value = (value_node.text if value_node is not None else "") or ""
    formula = (formula_node.text if formula_node is not None else "") or ""
    if cell_type == "s" and raw_value.isdigit():
        idx = int(raw_value)
        value = shared_strings[idx] if 0 <= idx < len(shared_strings) else raw_value
    elif cell_type == "inlineStr" and inline_node is not None:
        value = _xlsx_join_text(inline_node)
    elif cell_type == "b":
        value = "TRUE" if raw_value == "1" else "FALSE" if raw_value == "0" else raw_value
    else:
        value = raw_value
    value = str(value or "").strip()
    if formula and value:
        return f"{value} [={formula}]"
    if formula:
        return f"={formula}"

TEXT_ATTACHMENT_EXTS = {
    ".txt", ".md", ".markdown", ".json", ".csv", ".log", ".py", ".js", ".ts",
    ".tsx", ".jsx", ".html", ".css", ".xml", ".yaml", ".yml",
}
XLSX_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
EXCEL_MAX_SHEETS = 8
EXCEL_MAX_ROWS_PER_SHEET = 80
EXCEL_MAX_COLS_PER_ROW = 30
MAX_ATTACHMENT_TEXT_CHARS = 12000

def read_xlsx_attachment(path, limit=MAX_ATTACHMENT_TEXT_CHARS):
    parts = []
    used = 0
    with zipfile.ZipFile(path) as archive:
        shared = _xlsx_shared_strings(archive)
        sheets = _xlsx_sheet_paths(archive)
        media_count = sum(1 for name in archive.namelist() if name.startswith("xl/media/") and os.path.splitext(name)[1].lower() in XLSX_IMAGE_EXTS)
        parts.append(f"Excel 工作簿：{os.path.basename(path)}")
        if media_count:
            parts.append(f"内嵌图片数量：{media_count}（已作为图片参考一并提供给模型）")
        for sheet_index, (sheet_name, sheet_path) in enumerate(sheets[:EXCEL_MAX_SHEETS], start=1):
            try:
                root = ET.fromstring(archive.read(sheet_path))
            except Exception:
                continue
            rows = []
            for row in root.iter():
                if _xml_local_name(row.tag) != "row":
                    continue
                cells = []
                for cell in row:
                    if _xml_local_name(cell.tag) != "c":
                        continue
                    ref = cell.attrib.get("r") or ""
                    value = _xlsx_cell_text(cell, shared)
                    if value:
                        cells.append(f"{ref}={value}" if ref else value)
                    if len(cells) >= EXCEL_MAX_COLS_PER_ROW:
                        break
                if cells:
                    row_ref = row.attrib.get("r") or str(len(rows) + 1)
                    rows.append(f"第 {row_ref} 行：" + " | ".join(cells))
                if len(rows) >= EXCEL_MAX_ROWS_PER_SHEET:
                    break
            if rows:
                section = f"\n工作表 {sheet_index}：{sheet_name}\n" + "\n".join(rows)
            else:
                section = f"\n工作表 {sheet_index}：{sheet_name}\n（未读取到非空单元格）"
            if used + len(section) > limit:
                remain = max(0, limit - used)
                if remain:
                    parts.append(section[:remain])
                parts.append("\n（Excel 内容较长，已截断）")
                break
            parts.append(section)
            used += len(section)
    return "\n".join(parts).strip()[:limit]

def xlsx_embedded_image_data_urls(path, max_images=4, max_size=1536):
    urls = []
    try:
        with zipfile.ZipFile(path) as archive:
            media = [name for name in archive.namelist() if name.startswith("xl/media/") and os.path.splitext(name)[1].lower() in XLSX_IMAGE_EXTS]
            for name in sorted(media)[:max_images]:
                try:
                    raw = archive.read(name)
                    with Image.open(BytesIO(raw)) as img:
                        img.load()
                        if max(img.size) > max_size:
                            img.thumbnail((max_size, max_size), Image.LANCZOS)
                        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                            bg = Image.new("RGB", img.size, (255, 255, 255))
                            bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
                            img = bg
                        elif img.mode != "RGB":
                            img = img.convert("RGB")
                        buf = BytesIO()
                        img.save(buf, format="JPEG", quality=88, optimize=True)
                        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
                        urls.append(f"data:image/jpeg;base64,{encoded}")
                except Exception as exc:
                    logger.warning(f"[chat] failed to extract xlsx image {name}: {exc}")
    except Exception as exc:
        logger.warning(f"[chat] failed to read xlsx images {path}: {exc}")
    return urls

def attachment_embedded_image_data_urls(refs, max_images=4):
    urls = []
    for ref in (refs or []):
        if not isinstance(ref, dict) or is_image_reference(ref):
            continue
        path = output_file_from_url(ref.get("url", ""))
        if not path or os.path.splitext(path)[1].lower() != ".xlsx":
            continue
        urls.extend(xlsx_embedded_image_data_urls(path, max_images=max(0, max_images - len(urls))))
        if len(urls) >= max_images:
            break
    return urls[:max_images]

def read_text_attachment(path, limit=MAX_ATTACHMENT_TEXT_CHARS):
    ext = os.path.splitext(path or "")[1].lower()
    if not path or not os.path.isfile(path):
        return ""
    try:
        if ext == ".xlsx":
            return read_xlsx_attachment(path, limit)
        if ext == ".xls":
            return "这是旧版 .xls 二进制 Excel 文件，当前内置解析器暂不支持直接读取内容。请另存为 .xlsx 后重新上传。"
        if ext == ".docx":
            with zipfile.ZipFile(path) as archive:
                raw = archive.read("word/document.xml")
            root = ET.fromstring(raw)
            parts = []
            for node in root.iter():
                if node.tag.endswith("}t") and node.text:
                    parts.append(node.text)
                elif node.tag.endswith("}p"):
                    parts.append("\n")
            return html.unescape("".join(parts)).strip()[:limit]
        if ext in TEXT_ATTACHMENT_EXTS:
            with open(path, "rb") as f:
                data = f.read(min(os.path.getsize(path), limit * 4))
            for encoding in ("utf-8-sig", "utf-8", "gb18030"):
                try:
                    return data.decode(encoding, errors="strict").strip()[:limit]
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="replace").strip()[:limit]
    except Exception as exc:
        logger.warning(f"[chat] failed to read attachment text {path}: {exc}")
    return ""

def attachment_text_blocks(refs, limit_each=MAX_ATTACHMENT_TEXT_CHARS):
    blocks = []
    for ref in (refs or [])[:CHAT_ATTACHMENT_MAX]:
        if not isinstance(ref, dict) or is_image_reference(ref):
            continue
        path = output_file_from_url(ref.get("url", ""))
        text = read_text_attachment(path, limit_each) if path else ""
        if not text:
            continue
        name = ref.get("name") or os.path.basename(path)
        blocks.append(f"附件：{name}\n{text}")
    return blocks



# --- Sliced from online.py lines 6908-7166 ---
def upstream_message_from_record(item):
    role = item.get("role")
    if role not in {"user", "assistant"} or item.get("type") == "image":
        return None
    attachments = item.get("attachments") or []
    if attachments and role == "user":
        text = item.get("content", "")
        blocks = attachment_text_blocks(attachments)
        if blocks:
            text = f"{text}\n\n以下是用户上传附件的可读内容，请在回答时参考：\n\n" + "\n\n---\n\n".join(blocks)
        content = [{"type": "text", "text": text}]
        image_urls = []
        for ref in image_references(attachments[:CHAT_ATTACHMENT_MAX]):
            url = reference_to_data_url(ref)
            if url:
                image_urls.append(url)
        image_urls.extend(attachment_embedded_image_data_urls(attachments[:CHAT_ATTACHMENT_MAX], max_images=max(0, CHAT_ATTACHMENT_MAX - len(image_urls))))
        for url in image_urls[:CHAT_ATTACHMENT_MAX]:
            content.append({"type": "image_url", "image_url": {"url": url}})
        return {"role": role, "content": content}
    return {"role": role, "content": item.get("content", "")}

AGENT_ACTIONS = {"chat", "generate_image", "edit_image"}
AGENT_ANALYSIS_KEYWORDS = [
    "分析", "描述", "识别", "解释", "反推", "理解", "看图", "看下", "看一看",
    "画面里", "图中", "图里", "有什么", "是什么", "介绍", "评价", "点评", "打分",
    "提取", "读取", "caption", "describe", "analyze", "explain", "recognize",
    "json", "结构化",
]
AGENT_IMAGE_KEYWORDS = [
    "生成", "画", "出图", "生图", "图片", "图像", "海报", "头像", "壁纸",
    "插画", "照片", "photo", "image", "picture", "draw", "generate",
]
AGENT_EDIT_KEYWORDS = [
    "修改", "改成", "换成", "调整", "优化", "编辑", "重绘", "上一张", "刚才",
    "这张", "那张", "参考图", "改图", "edit", "modify", "change", "revise",
]
CN_NUMERAL_MAP = {
    "一": 1, "二": 2, "两": 2, "俩": 2, "三": 3, "四": 4,
}

def latest_chat_image_refs(conversation, limit=1):
    refs = []
    for item in reversed(conversation.get("messages") or []):
        url = item.get("image_url") if isinstance(item, dict) else ""
        if url:
            refs.append({"url": url, "name": item.get("content") or "上一张图片", "role": "source"})
        if len(refs) >= limit:
            break
    return refs

def image_size_from_reference(ref):
    path = output_file_from_url(ref)
    if not path:
        return ""
    try:
        with Image.open(path) as img:
            width, height = img.size
        if width > 0 and height > 0:
            return f"{width}x{height}"
    except Exception as exc:
        logger.warning(f"[chat-agent] failed to read reference image size: {exc}")
    return ""

def chat_requested_image_count(message):
    text = str(message or "")
    match = re.search(r"(?<!\d)([1-4])\s*(?:张|幅|个|组|套)(?!\d)", text)
    if match:
        return max(1, min(4, int(match.group(1))))
    match = re.search(r"([一二两俩三四])\s*(?:张|幅|个|组|套)", text)
    if match:
        return max(1, min(4, CN_NUMERAL_MAP.get(match.group(1), 1)))
    return 1

def chat_split_parallel_prompts(prompt, count):
    text = str(prompt or "").strip()
    if count <= 1:
        return [text]
    noun_match = re.search(r"(.+?)(?:的)?(海报|头像|壁纸|插画|照片|图片|图像)\s*$", text)
    if not noun_match:
        return [text] * count
    prefix = noun_match.group(1).strip()
    suffix = noun_match.group(2)
    prefix = re.sub(r"(?:再)?(?:生成|画|绘制|制作|创建)\s*[1-4一二两俩三四]?\s*(?:张|幅|个|组|套)?", "", prefix).strip()
    prefix = re.sub(r"[,，、\s]+$", "", prefix).strip()
    if not prefix:
        return [text] * count
    candidates = [
        item.strip(" ，,、")
        for item in re.split(r"\s*(?:和|与|、|，|,|\+|＋)\s*", prefix)
        if item.strip(" ，,、")
    ]
    if len(candidates) < count:
        return [text] * count
    return [f"{item}的{suffix}" for item in candidates[:count]]

def pick_chat_image_provider(provider_id="", fallback_id=""):
    providers = [p for p in load_api_providers() if p.get("enabled", True) and (p.get("image_models") or [])]
    for target in (provider_id, fallback_id):
        clean = str(target or "").strip().lower()
        if clean:
            matched = next((p for p in providers if p.get("id") == clean), None)
            if matched:
                return matched
    if providers:
        primary = next((p for p in providers if p.get("primary")), None)
        return primary or providers[0]
    return get_api_provider(provider_id or fallback_id or "comfly")

def heuristic_agent_decision(message, refs, has_previous_image):
    text = str(message or "").strip().lower()
    has_analysis_word = any(key.lower() in text for key in AGENT_ANALYSIS_KEYWORDS)
    has_explicit_edit = any(key.lower() in text for key in ["修改", "改成", "换成", "重绘", "改图", "替换", "变更为"])
    has_explicit_generate = any(key.lower() in text for key in ["生成", "画", "绘制", "出图", "制作", "创建"]) and not has_analysis_word

    if has_analysis_word and not (has_explicit_edit or has_explicit_generate):
        return {"action": "chat", "prompt": message, "reply": ""}

    has_image_word = any(key.lower() in text for key in AGENT_IMAGE_KEYWORDS)
    has_edit_word = any(key.lower() in text for key in AGENT_EDIT_KEYWORDS)

    if refs and (has_explicit_edit or (has_edit_word and not has_analysis_word)):
        return {"action": "edit_image", "prompt": message, "reply": ""}
    if has_previous_image and (has_explicit_edit or has_edit_word):
        return {"action": "edit_image", "prompt": message, "reply": ""}
    if has_image_word and not has_edit_word:
        return {"action": "generate_image", "prompt": message, "reply": ""}
    return {"action": "chat", "prompt": message, "reply": ""}

def parse_agent_decision(raw_text, message, refs, has_previous_image):
    text = str(raw_text or "").strip()
    data = None
    if text:
        match = re.search(r"\{[\s\S]*\}", text)
        candidate = match.group(0) if match else text
        try:
            data = json.loads(candidate)
        except Exception:
            data = None
    heuristic = heuristic_agent_decision(message, refs, has_previous_image)
    if not isinstance(data, dict):
        return heuristic
    action = str(data.get("action") or "").strip()
    if action not in AGENT_ACTIONS:
        action = heuristic["action"]
    prompt = str(data.get("prompt") or message).strip() or message
    reply = str(data.get("reply") or "").strip()
    if action == "edit_image" and not (refs or has_previous_image):
        action = "generate_image" if any(key.lower() in str(message).lower() for key in AGENT_IMAGE_KEYWORDS) else "chat"
    return {"action": action, "prompt": prompt, "reply": reply}

async def post_chat_completions_with_retry(client: httpx.AsyncClient, upstream_url: str, headers: dict, json_body: dict, max_retries: int = 2) -> httpx.Response:
    """Send POST to chat completions endpoint with automatic 429 rate limit backoff retry."""
    response = await client.post(upstream_url, headers=headers, json=json_body)
    for attempt in range(max_retries):
        if response.status_code == 429:
            retry_header = response.headers.get("Retry-After")
            wait_seconds = None
            if retry_header:
                try:
                    wait_seconds = float(retry_header)
                except (ValueError, TypeError):
                    pass
            if wait_seconds is None or wait_seconds <= 0:
                wait_seconds = 1.5 * (2 ** attempt)
            else:
                wait_seconds = min(max(wait_seconds, 1.0), 10.0)
            logger.info(f"[chat-completions] upstream 429 rate limit encountered, backing off {wait_seconds:.2f}s for retry {attempt + 1}/{max_retries}...")
            await asyncio.sleep(wait_seconds)
            response = await client.post(upstream_url, headers=headers, json=json_body)
        else:
            break
    return response

async def decide_chat_agent_action(payload, conversation, refs):
    has_previous_image = bool(latest_chat_image_refs(conversation, 1))
    fallback = heuristic_agent_decision(payload.message, refs, has_previous_image)
    # 快速通道：明确识图/分析/反推或平台为 ModelScope 时直接走启发式决策，避免冗余意图网络调用并杜绝 429 限流
    text = str(payload.message or "").strip().lower()
    has_analysis_word = any(key.lower() in text for key in AGENT_ANALYSIS_KEYWORDS)
    has_explicit_edit = any(key.lower() in text for key in ["修改", "改成", "换成", "重绘", "改图", "替换", "变更为"])
    has_explicit_generate = any(key.lower() in text for key in ["生成", "画", "绘制", "出图", "制作", "创建"]) and not has_analysis_word
    if (has_analysis_word and not (has_explicit_edit or has_explicit_generate)) or payload.provider in ("modelscope",):
        fallback["router_model"] = "heuristic_fast_path"
        return fallback

    provider_cfg = get_api_provider(payload.provider) if payload.provider not in ("modelscope",) else {}
    if is_codex_provider(provider_cfg):
        fallback["router_model"] = selected_model(payload.model, (provider_cfg.get("chat_models") or CODEX_DEFAULT_CHAT_MODELS)[0])
        return fallback
    if is_gemini_cli_provider(provider_cfg):
        fallback["router_model"] = selected_model(payload.model, (provider_cfg.get("chat_models") or GEMINI_CLI_DEFAULT_CHAT_MODELS)[0])
        return fallback

    chat_base, chat_hdrs, model = resolve_chat_provider(payload.provider, payload.model, payload.ms_model)
    history = conversation["messages"][-MAX_HISTORY_MESSAGES:]
    custom_system_prompt = str(getattr(payload, "system_prompt", "") or "").strip()
    system = (
        "你是图片创作聊天 Agent 的意图路由器。只返回 JSON，不要 Markdown。\n"
        "action 只能是 chat、generate_image、edit_image。\n"
        "chat: 普通问答、图片深度解析、反推提示词、识别画面内容或不需要调用图片工具。\n"
        "generate_image: 用户要求生成、绘制、创建新图片。\n"
        "edit_image: 用户要求修改参考图、上一张图、刚才生成的图，或上传了参考图并要求基于它做图像变体/重绘。\n"
        "prompt 是交给生图/改图工具的完整中文提示词；普通聊天/反推时填用户原话。\n"
        "reply 是可选的短状态文本。"
    )
    upstream_messages = [{"role": "system", "content": system}]
    # Prior dialogue turns for text context only (do not serialize heavy image base64 into the intent classifier)
    for item in history[:-1][-6:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content and item.get("type") != "image":
            upstream_messages.append({"role": role, "content": str(content)[:300]})
    upstream_messages.append({
        "role": "user",
        "content": (
            f"当前用户输入：{payload.message}\n"
            f"用户设置的系统提示词：{custom_system_prompt or '无'}\n"
            f"本次上传参考图数量：{len(refs)}\n"
            f"对话中是否已有上一张生成图：{'是' if has_previous_image else '否'}\n"
            "请返回 JSON，例如 {\"action\":\"generate_image\",\"prompt\":\"...\",\"reply\":\"...\"}"
        )
    })
    try:
        async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=AI_REQUEST_TIMEOUT) as client:
            req_body = {"model": model, "messages": upstream_messages}
            if is_apimart_provider(provider_cfg):
                req_body["stream"] = False
            response = await post_chat_completions_with_retry(
                client,
                f"{chat_base}/chat/completions",
                headers=chat_hdrs,
                json_body=req_body,
            )
            response.raise_for_status()
            raw = response.json()
            decision = parse_agent_decision(text_from_chat_response(raw), payload.message, refs, has_previous_image)
            decision["router_model"] = model
            return decision
    except Exception as exc:
        logger.info(f"[chat-agent] intent router fallback: {exc}")
        fallback["router_model"] = model
        return fallback

def clean_cli_raw(raw):
    """Strip sensitive CLI internals (_stdout, _stderr) before returning or saving to conversation history."""
    if not isinstance(raw, dict):
        return raw
    cleaned = dict(raw)
    cleaned.pop("_stdout", None)
    cleaned.pop("_stderr", None)
    return cleaned

async def build_chat_text_reply(payload, conversation):
    provider_cfg = get_api_provider(payload.provider) if payload.provider not in ("modelscope",) else {}
    if is_codex_provider(provider_cfg):
        model = selected_model(payload.model, (provider_cfg.get("chat_models") or CODEX_DEFAULT_CHAT_MODELS)[0])
        payload.model = model
        text, raw = await codex_chat_text(payload, conversation["messages"][-MAX_HISTORY_MESSAGES:])
        return {
            "id": uuid.uuid4().hex,
            "role": "assistant",
            "content": text,
            "created_at": now_ms(),
            "model": model,
            "raw_usage": None,
            "raw": clean_cli_raw(raw),
        }
    if is_gemini_cli_provider(provider_cfg):
        model = selected_model(payload.model, (provider_cfg.get("chat_models") or GEMINI_CLI_DEFAULT_CHAT_MODELS)[0])
        payload.model = model
        text, raw = await gemini_cli_chat_text(payload, conversation["messages"][-MAX_HISTORY_MESSAGES:])
        return {
            "id": uuid.uuid4().hex,
            "role": "assistant",
            "content": text,
            "created_at": now_ms(),
            "model": model,
            "raw_usage": None,
            "raw": clean_cli_raw(raw),
        }
    chat_base, chat_hdrs, model = resolve_chat_provider(payload.provider, payload.model, payload.ms_model)
    is_apimart = is_apimart_provider(provider_cfg)
    upstream_messages = [{"role": "system", "content": chat_system_prompt(payload)}]
    for item in conversation["messages"][-MAX_HISTORY_MESSAGES:]:
        msg = upstream_message_from_record(item)
        if msg:
            upstream_messages.append(msg)
    try:
        async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=AI_REQUEST_TIMEOUT) as client:
            req_body = {"model": model, "messages": upstream_messages}
            if is_apimart:
                req_body["stream"] = False
            response = await post_chat_completions_with_retry(
                client,
                f"{chat_base}/chat/completions",
                headers=chat_hdrs,
                json_body=req_body,
            )
            response.raise_for_status()
            raw = response.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text or ""
        friendly = friendly_chat_error_detail(body, model, provider_cfg)
        detail = friendly or sanitize_error_detail(f"上游接口错误：{body}")[:2000]
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"请求上游接口失败：{exc}") from exc
    raw_data = unwrap_apimart_response(raw) if isinstance(raw, dict) else raw
    return {
        "id": uuid.uuid4().hex,
        "role": "assistant",
        "content": text_from_chat_response(raw).strip() or "接口返回了空回复。",
        "created_at": now_ms(),
        "model": model,
        "raw_usage": raw_data.get("usage") if isinstance(raw_data, dict) else None,
    }

# --- 路由接口 ---

# ============================================================================
# Cloud & Online Route Handlers
# ============================================================================



# --- Sliced from online.py lines 11495-12179 ---
@router.post("/api/canvas-llm")
async def canvas_llm(payload: CanvasLLMRequest):
    _provider = get_api_provider(payload.provider)
    if is_codex_provider(_provider):
        model = selected_model(payload.model, (_provider.get("chat_models") or CODEX_DEFAULT_CHAT_MODELS)[0])
        payload.model = model
        text, raw = await codex_chat_text(payload, payload.messages)
        return {"text": text, "model": model, "raw_usage": None, "raw": clean_cli_raw(raw)}
    if is_gemini_cli_provider(_provider):
        model = selected_model(payload.model, (_provider.get("chat_models") or GEMINI_CLI_DEFAULT_CHAT_MODELS)[0])
        payload.model = model
        text, raw = await gemini_cli_chat_text(payload, payload.messages)
        return {"text": text, "model": model, "raw_usage": None, "raw": clean_cli_raw(raw)}
    chat_base, chat_hdrs, model = resolve_chat_provider(payload.provider, payload.model, payload.ms_model)
    # 判断协议：APIMart 异步 vs 标准 OpenAI
    _llm_provider = get_api_provider(payload.provider) if payload.provider not in ("modelscope",) else {}
    _is_apimart = is_apimart_provider(_llm_provider)
    system_prompt = (payload.system_prompt or "").strip()
    upstream_messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
    for item in payload.messages[-MAX_HISTORY_MESSAGES:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            upstream_messages.append({"role": role, "content": content})
    # 构造用户消息：有图片/视频时用 OpenAI/Gemini 多模态格式
    image_inputs = [img for img in (payload.images or []) if is_image_reference_value(img)]
    video_inputs = [video for video in (payload.videos or []) if is_video_reference_value(video)]
    if image_inputs or video_inputs:
        content_parts = [{"type": "text", "text": payload.message}]
        ok_imgs = 0
        for img in image_inputs[:8]:
            if not img or not isinstance(img, str):
                continue
            ref_url = media_reference_to_url(img, max_image_size=1024)
            if not ref_url:
                continue
            content_parts.append({"type": "image_url", "image_url": {"url": ref_url}})
            ok_imgs += 1
        ok_videos = 0
        for video in video_inputs[:3]:
            if not video or not isinstance(video, str):
                continue
            frame_urls = await video_reference_to_frame_data_urls(video, max_frames=6, max_size=768)
            if frame_urls:
                ok_videos += 1
                content_parts.append({"type": "text", "text": f"以下是视频 {ok_videos} 按时间顺序抽取的关键帧，请结合这些画面理解视频内容。"})
                for frame_url in frame_urls:
                    content_parts.append({"type": "image_url", "image_url": {"url": frame_url}})
            else:
                ref_url = media_reference_to_url(video)
                if not ref_url:
                    continue
                content_parts.append({"type": "video_url", "video_url": {"url": ref_url}})
                ok_videos += 1
        logger.info(f"[canvas-llm] model={model} provider={payload.provider} text_len={len(payload.message)} images={ok_imgs}/{len(payload.images)} videos={ok_videos}/{len(payload.videos)}")
        upstream_messages.append({"role": "user", "content": content_parts})
    else:
        upstream_messages.append({"role": "user", "content": payload.message})
    raw = None
    try:
        async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=AI_REQUEST_TIMEOUT) as client:
            req_body = {"model": model, "messages": upstream_messages}
            if _is_apimart:
                req_body["stream"] = False   # APIMart 默认流式，强制关闭
            response = await post_chat_completions_with_retry(
                client,
                f"{chat_base}/chat/completions",
                headers=chat_hdrs,
                json_body=req_body,
            )
            response.raise_for_status()
            if not response.content:
                raise HTTPException(status_code=502, detail="上游接口返回了空响应")
            raw = response.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text or ""
        friendly = friendly_chat_error_detail(body, model, _llm_provider)
        detail = friendly or sanitize_error_detail(f"上游接口错误：{body}")[:2000]
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"请求上游接口失败：{exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"解析上游响应失败：{exc}") from exc
    try:
        text = text_from_chat_response(raw).strip() if isinstance(raw, dict) else ""
        text = text or "接口返回了空回复。"
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"解析回复内容失败：{exc}") from exc
    raw_data = unwrap_apimart_response(raw) if isinstance(raw, dict) else {}
    return {"text": text, "model": model, "raw_usage": raw_data.get("usage")}

# --- 对话管理 ---

@router.get("/api/conversations")
async def conversations(request: Request, x_user_id: str = Header(default="")):
    user_id = safe_user_id(x_user_id, request)
    return {"user_id": user_id, "conversations": list_conversations(user_id)}

@router.post("/api/conversations")
async def create_conversation(payload: ConversationCreateRequest, request: Request, x_user_id: str = Header(default="")):
    user_id = safe_user_id(x_user_id, request)
    return {"conversation": new_conversation(user_id, payload.title)}

@router.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, request: Request, x_user_id: str = Header(default="")):
    user_id = safe_user_id(x_user_id, request)
    return {"conversation": load_conversation(user_id, conversation_id)}

@router.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, request: Request, x_user_id: str = Header(default="")):
    user_id = safe_user_id(x_user_id, request)
    path = conversation_path(user_id, conversation_id)
    if os.path.exists(path):
        os.remove(path)
    return {"ok": True}
# --- 画布与项目管理路由已解耦迁移至 routers/canvas.py ---

# --- 画布资产列表路由已解耦迁移至 routers/assets.py ---

# --- 提示词库与模板路由已解耦迁移至 routers/prompts.py ---

# --- 资产库操作、分类、条目管理路由已解耦迁移至 routers/assets.py ---


def image_path_to_data_url(path, max_size=1024):
    if max_size:
        try:
            with Image.open(path) as img:
                img.load()
                if max(img.size) > max_size:
                    img.thumbnail((max_size, max_size), Image.LANCZOS)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                buf = BytesIO()
                fmt = "PNG" if img.mode == "RGBA" else "JPEG"
                img.save(buf, format=fmt, quality=88 if fmt == "JPEG" else None)
                encoded = base64.b64encode(buf.getvalue()).decode("ascii")
                mime = "image/png" if fmt == "PNG" else "image/jpeg"
                return f"data:{mime};base64,{encoded}"
        except Exception as e:
            logger.warning(f"shared caption image resize failed: {e}")
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    mime = content_type_for_path(path) or "image/jpeg"
    return f"data:{mime};base64,{encoded}"


async def caption_image_with_provider(abs_path, prompt, provider_id, model, ms_model=""):
    llm_provider = get_api_provider(provider_id) if provider_id not in ("modelscope",) else {}
    if is_codex_provider(llm_provider):
        resolved_model = selected_model(model, (llm_provider.get("chat_models") or CODEX_DEFAULT_CHAT_MODELS)[0])
        payload = CanvasLLMRequest(
            message=(prompt or "描述图片").strip() or "描述图片",
            provider=provider_id or "codex",
            model=resolved_model,
            images=[abs_path],
        )
        text, _raw = await codex_chat_text(payload, [])
        return text, resolved_model
    if is_gemini_cli_provider(llm_provider):
        resolved_model = selected_model(model, (llm_provider.get("chat_models") or GEMINI_CLI_DEFAULT_CHAT_MODELS)[0])
        payload = CanvasLLMRequest(
            message=(prompt or "描述图片").strip() or "描述图片",
            provider=provider_id or "gemini-cli",
            model=resolved_model,
            images=[abs_path],
        )
        text, _raw = await gemini_cli_chat_text(payload, [])
        return text, resolved_model
    chat_base, chat_hdrs, resolved_model = resolve_chat_provider(provider_id, model, ms_model)
    is_apimart = is_apimart_provider(llm_provider)
    prompt_text = (prompt or "描述图片").strip() or "描述图片"
    data_url = image_path_to_data_url(abs_path, max_size=1024)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }]
    raw = None
    try:
        async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=AI_REQUEST_TIMEOUT) as client:
            req_body = {"model": resolved_model, "messages": messages}
            if is_apimart:
                req_body["stream"] = False
            response = await post_chat_completions_with_retry(
                client,
                f"{chat_base}/chat/completions",
                headers=chat_hdrs,
                json_body=req_body,
            )
            response.raise_for_status()
            raw = response.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text or ""
        friendly = friendly_chat_error_detail(body, resolved_model, llm_provider)
        detail = friendly or sanitize_error_detail(f"上游接口错误：{body}")[:2000]
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        log_net_error(f"对话 网络/TLS错误 provider={llm_provider} model={resolved_model}", exc)
        raise HTTPException(status_code=502, detail=f"请求上游接口失败：{exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"解析上游响应失败：{exc}") from exc
    text = text_from_chat_response(raw).strip() if isinstance(raw, dict) else ""
    return text or "接口返回了空回复。", resolved_model


async def classify_image_with_provider(abs_path, provider_id="", model="", ms_model="", prompt=""):
    text, resolved_model = await caption_image_with_provider(
        abs_path,
        asset_classification_prompt(prompt),
        provider_id or get_primary_provider_id(),
        model,
        ms_model,
    )
    classification = parse_asset_classification_text(text)
    classification["model"] = resolved_model
    classification["provider"] = provider_id or get_primary_provider_id()
    return classification


async def register_asset_library_avatar_impl(item_id: str, payload: AssetAvatarRegisterRequest, target_item: dict, lib: dict) -> dict:
    provider = get_api_provider(payload.provider_id)
    platform = avatar_platform_for_provider(provider)
    if platform not in AVATAR_SUPPORTED_PLATFORMS:
        name = (provider or {}).get("name") or (provider or {}).get("id") or "该平台"
        raise HTTPException(status_code=400, detail=f"「{name}」暂不支持数字人/真人认证（目前仅 APIMart 可用，火山等平台待接入官方资产 API）。")
    kind = str(target_item.get("kind") or "image").lower()
    if kind not in ("image", "video", "audio"):
        kind = "image"
    if platform == "apimart":
        project_name = str(payload.project_name or "default").strip() or "default"
        async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=VIDEO_POLL_TIMEOUT) as client:
            public_url = await upload_media_for_apimart(client, provider, target_item.get("url") or "", kind)
        if not valid_apimart_video_image_input(public_url):
            reason = public_url[4:] if isinstance(public_url, str) and public_url.startswith("ERR:") else "无法获取公网可访问地址"
            raise HTTPException(status_code=400, detail=f"素材无法提交到 APIMart：{reason}\n请配置 PUBLIC_BASE_URL，或确认本地文件存在。")
        task_id = await submit_apimart_avatar_asset(
            provider, public_url, target_item.get("name") or "asset", kind,
            project_name=project_name, group_name=payload.group_name,
        )
    elif platform == "volcengine":
        project_name = str(provider.get("volcengine_project_name") or VOLCENGINE_DEFAULT_PROJECT_NAME).strip() or VOLCENGINE_DEFAULT_PROJECT_NAME
        public_url = volcengine_public_asset_url(target_item.get("url") or "")
        if public_url.startswith("ERR:"):
            raise HTTPException(status_code=400, detail=public_url[4:])
        task_id = await submit_volcengine_avatar_asset(
            public_url, target_item.get("name") or "asset", kind,
            project_name=project_name, group_name=payload.group_name or "",
        )
    else:
        raise HTTPException(status_code=400, detail="该平台的认证后端尚未接入。")
    regs = target_item.get("registrations")
    if not isinstance(regs, dict):
        regs = {}
    regs[platform] = {
        "provider_id": provider["id"],
        "project_name": project_name,
        "task_id": task_id,
        "status": "Processing",
        "detail": "已提交，审核中",
        "asset_uri": "",
        "asset_id": "",
        "registered_at": now_ms(),
    }
    target_item["registrations"] = regs
    return target_item


async def check_asset_library_avatar_impl(item_id: str, payload: AssetAvatarRegisterRequest, target_item: dict, lib: dict) -> dict:
    regs = target_item.get("registrations") if isinstance(target_item.get("registrations"), dict) else {}
    provider = get_api_provider(payload.provider_id or "")
    platform = avatar_platform_for_provider(provider)
    if platform not in AVATAR_SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=400, detail="该平台暂不支持数字人/真人认证审核。")
    reg = regs.get(platform) if isinstance(regs.get(platform), dict) else {}
    task_id = str(reg.get("task_id") or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="该素材还没有提交到这个平台的认证审核。")
    if platform == "apimart":
        result = await check_apimart_avatar_task(provider, task_id)
    elif platform == "volcengine":
        result = await check_volcengine_avatar_task(
            task_id, str(reg.get("project_name") or VOLCENGINE_DEFAULT_PROJECT_NAME).strip() or VOLCENGINE_DEFAULT_PROJECT_NAME,
        )
    else:
        raise HTTPException(status_code=400, detail="该平台的认证后端尚未接入。")
    reg["status"] = result["status"]
    reg["detail"] = result.get("detail") or ""
    if result["status"] == "Active" and result.get("asset_uri"):
        reg["asset_uri"] = result["asset_uri"]
        reg["asset_id"] = result["asset_uri"].replace("asset://", "")
    regs[platform] = reg
    target_item["registrations"] = regs
    return target_item


# --- GPT 对话 ---

@router.post("/api/chat")
async def chat(payload: ChatRequest, request: Request, x_user_id: str = Header(default="")):
    user_id = safe_user_id(x_user_id, request)
    conversation = (
        load_conversation(user_id, payload.conversation_id)
        if payload.conversation_id
        else new_conversation(user_id, display_title(payload.message))
    )
    if not conversation.get("messages"):
        conversation["title"] = display_title(payload.message)

    refs = [dump_pydantic(ref) for ref in payload.reference_images if ref.url]
    image_refs = image_references(refs)
    user_message = {
        "id": uuid.uuid4().hex,
        "role": "user",
        "content": payload.message,
        "created_at": now_ms(),
        "attachments": refs,
        "mode": payload.mode,
    }
    conversation["messages"].append(user_message)
    conversation["updated_at"] = now_ms()
    save_conversation(user_id, conversation)

    if payload.mode == "image":
        image_provider_id = payload.provider if payload.provider not in {"modelscope"} else "comfly"
        provider = get_api_provider(image_provider_id)
        default_model = (provider.get("image_models") or [IMAGE_MODEL])[0]
        model = selected_model(payload.image_model or payload.model, default_model)
        image_size = chat_prompt_size_override(payload.message, payload.size) or payload.size
        try:
            image_data, raw = await generate_ai_image(
                payload.message,
                image_size,
                payload.quality,
                model,
                image_refs,
                provider["id"],
                payload.aspect_ratio,
                payload.resolution,
            )
            local_url = await save_ai_image_to_output(image_data, prefix="chat_")
        except httpx.HTTPStatusError as exc:
            text = exc.response.text or ""
            detail = friendly_image_error_detail(text, image_size, model) or f"上游生图接口错误：{text[:300]}"
            raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
        except httpx.HTTPError as exc:
            log_net_error(f"对话生图 网络/TLS错误 model={model}", exc)
            raise HTTPException(status_code=502, detail=f"请求上游生图接口失败：{exc}") from exc
        assistant_message = {
            "id": uuid.uuid4().hex,
            "role": "assistant",
            "type": "image",
            "content": payload.message,
            "image_url": local_url,
            "created_at": now_ms(),
            "model": model,
            "size": image_size,
            "raw_usage": raw.get("usage") if isinstance(raw, dict) else None,
        }
    else:
        _codex_provider = get_api_provider(payload.provider)
        if is_codex_provider(_codex_provider):
            model = selected_model(payload.model, (_codex_provider.get("chat_models") or CODEX_DEFAULT_CHAT_MODELS)[0])
            payload.model = model
            text, raw = await codex_chat_text(payload, conversation["messages"][-MAX_HISTORY_MESSAGES:])
            assistant_message = {
                "id": uuid.uuid4().hex,
                "role": "assistant",
                "content": text,
                "created_at": now_ms(),
                "model": model,
                "raw_usage": None,
                "raw": clean_cli_raw(raw),
            }
            conversation["messages"].append(assistant_message)
            conversation["updated_at"] = now_ms()
            save_conversation(user_id, conversation)
            return {"conversation": conversation, "message": assistant_message}
        if is_gemini_cli_provider(_codex_provider):
            model = selected_model(payload.model, (_codex_provider.get("chat_models") or GEMINI_CLI_DEFAULT_CHAT_MODELS)[0])
            payload.model = model
            text, raw = await gemini_cli_chat_text(payload, conversation["messages"][-MAX_HISTORY_MESSAGES:])
            assistant_message = {
                "id": uuid.uuid4().hex,
                "role": "assistant",
                "content": text,
                "created_at": now_ms(),
                "model": model,
                "raw_usage": None,
                "raw": clean_cli_raw(raw),
            }
            conversation["messages"].append(assistant_message)
            conversation["updated_at"] = now_ms()
            save_conversation(user_id, conversation)
            return {"conversation": conversation, "message": assistant_message}
        chat_base, chat_hdrs, model = resolve_chat_provider(payload.provider, payload.model, payload.ms_model)
        _conv_provider = get_api_provider(payload.provider) if payload.provider not in ("modelscope",) else {}
        _conv_is_apimart = is_apimart_provider(_conv_provider)
        history = conversation["messages"][-MAX_HISTORY_MESSAGES:]
        upstream_messages = [{"role": "system", "content": chat_system_prompt(payload)}]
        for item in history:
            msg = upstream_message_from_record(item)
            if msg:
                upstream_messages.append(msg)
        try:
            async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=AI_REQUEST_TIMEOUT) as client:
                conv_req_body = {"model": model, "messages": upstream_messages}
                if _conv_is_apimart:
                    conv_req_body["stream"] = False
                response = await post_chat_completions_with_retry(
                    client,
                    f"{chat_base}/chat/completions",
                    headers=chat_hdrs,
                    json_body=conv_req_body,
                )
                response.raise_for_status()
                raw = response.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text or ""
            friendly = friendly_chat_error_detail(body, model, _conv_provider)
            detail = friendly or sanitize_error_detail(f"上游接口错误：{body}")[:2000]
            raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"请求上游接口失败：{exc}") from exc
        raw_data = unwrap_apimart_response(raw) if isinstance(raw, dict) else raw
        assistant_message = {
            "id": uuid.uuid4().hex,
            "role": "assistant",
            "content": text_from_chat_response(raw).strip() or "接口返回了空回复。",
            "created_at": now_ms(),
            "model": model,
            "raw_usage": raw_data.get("usage") if isinstance(raw_data, dict) else None,
        }

    conversation["messages"].append(assistant_message)
    conversation["updated_at"] = now_ms()
    save_conversation(user_id, conversation)
    return {"conversation": conversation, "message": assistant_message}

@router.post("/api/chat/agent")
async def chat_agent(payload: ChatRequest, request: Request, x_user_id: str = Header(default="")):
    user_id = safe_user_id(x_user_id, request)
    conversation = (
        load_conversation(user_id, payload.conversation_id)
        if payload.conversation_id
        else new_conversation(user_id, display_title(payload.message))
    )
    if not conversation.get("messages"):
        conversation["title"] = display_title(payload.message)

    refs = [dump_pydantic(ref) for ref in payload.reference_images if ref.url]
    image_refs = image_references(refs)
    user_message = {
        "id": uuid.uuid4().hex,
        "role": "user",
        "content": payload.message,
        "created_at": now_ms(),
        "attachments": refs,
        "mode": "agent",
    }
    conversation["messages"].append(user_message)
    conversation["updated_at"] = now_ms()
    save_conversation(user_id, conversation)

    decision = await decide_chat_agent_action(payload, conversation, image_refs)
    action = decision.get("action") or "chat"
    tool_refs = image_refs[:]
    inherited_size = ""
    if action == "edit_image" and not tool_refs:
        tool_refs = latest_chat_image_refs(conversation, 1)
        inherited_size = image_size_from_reference(tool_refs[0]) if tool_refs else ""
    if action == "edit_image" and not tool_refs:
        action = "generate_image"

    if action in {"generate_image", "edit_image"}:
        image_provider = pick_chat_image_provider(payload.image_provider or payload.provider, payload.provider)
        default_model = (image_provider.get("image_models") or [IMAGE_MODEL])[0]
        model = selected_model(payload.image_model or default_model, default_model)
        prompt = decision.get("prompt") or payload.message
        prompt_size = chat_prompt_size_override(payload.message, payload.size) or chat_prompt_size_override(prompt, payload.size)
        image_size = snap_size_to_multiple(prompt_size or inherited_size or payload.size, 16)
        requested_count = 1 if action == "edit_image" else chat_requested_image_count(payload.message)
        prompts = chat_split_parallel_prompts(prompt, requested_count)
        local_urls = []
        raw_items = []
        try:
            for item_prompt in prompts:
                image_data, raw = await generate_ai_image(
                    item_prompt,
                    image_size,
                    payload.quality,
                    model,
                    tool_refs,
                    image_provider["id"],
                    payload.aspect_ratio,
                    payload.resolution,
                )
                local_urls.append(await save_ai_image_to_output(image_data, prefix="chat_"))
                raw_items.append(raw)
        except httpx.HTTPStatusError as exc:
            text = exc.response.text or ""
            detail = friendly_image_error_detail(text, image_size, model) or f"上游生图接口错误：{text[:300]}"
            raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
        except httpx.HTTPError as exc:
            log_net_error(f"对话生图 网络/TLS错误 model={model}", exc)
            raise HTTPException(status_code=502, detail=f"请求上游生图接口失败：{exc}") from exc
        local_url = local_urls[0] if local_urls else ""
        assistant_message = {
            "id": uuid.uuid4().hex,
            "role": "assistant",
            "type": "image",
            "content": prompt,
            "image_url": local_url,
            "image_urls": local_urls,
            "created_at": now_ms(),
            "model": model,
            "provider": image_provider["id"],
            "size": image_size,
            "image_count": len(local_urls),
            "prompts": prompts,
            "agent_action": action,
            "agent_reply": decision.get("reply") or "",
            "used_references": tool_refs,
            "raw_usage": raw_items[0].get("usage") if raw_items and isinstance(raw_items[0], dict) else None,
        }
    else:
        assistant_message = await build_chat_text_reply(payload, conversation)
        assistant_message["agent_action"] = "chat"

    conversation["messages"].append(assistant_message)
    conversation["updated_at"] = now_ms()
    save_conversation(user_id, conversation)
    return {"conversation": conversation, "message": assistant_message, "agent": {"action": action, "decision": decision}}

@router.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request, x_user_id: str = Header(default="")):
    if payload.mode == "image":
        raise HTTPException(status_code=400, detail="图片模式请使用 /api/chat")

    user_id = safe_user_id(x_user_id, request)
    conversation = (
        load_conversation(user_id, payload.conversation_id)
        if payload.conversation_id
        else new_conversation(user_id, display_title(payload.message))
    )
    if not conversation.get("messages"):
        conversation["title"] = display_title(payload.message)

    refs = [dump_pydantic(ref) for ref in payload.reference_images if ref.url]
    user_message = {
        "id": uuid.uuid4().hex,
        "role": "user",
        "content": payload.message,
        "created_at": now_ms(),
        "attachments": refs,
        "mode": payload.mode,
    }
    conversation["messages"].append(user_message)
    conversation["updated_at"] = now_ms()
    save_conversation(user_id, conversation)

    _codex_provider = get_api_provider(payload.provider)
    if is_codex_provider(_codex_provider):
        model = selected_model(payload.model, (_codex_provider.get("chat_models") or CODEX_DEFAULT_CHAT_MODELS)[0])
        payload.model = model

        async def codex_stream():
            yield sse_event({"type": "meta", "conversation": conversation})
            try:
                text, raw = await codex_chat_text(payload, conversation["messages"][-MAX_HISTORY_MESSAGES:])
            except HTTPException as exc:
                yield sse_event({"type": "error", "detail": exc.detail})
                return
            assistant_message = {
                "id": uuid.uuid4().hex,
                "role": "assistant",
                "content": text,
                "created_at": now_ms(),
                "model": model,
                "raw_usage": None,
                "raw": clean_cli_raw(raw),
            }
            conversation["messages"].append(assistant_message)
            conversation["updated_at"] = now_ms()
            save_conversation(user_id, conversation)
            yield sse_event({"type": "delta", "delta": text})
            yield sse_event({"type": "done", "conversation": conversation, "message": assistant_message})

        return StreamingResponse(codex_stream(), media_type="text/event-stream")

    if is_gemini_cli_provider(_codex_provider):
        model = selected_model(payload.model, (_codex_provider.get("chat_models") or GEMINI_CLI_DEFAULT_CHAT_MODELS)[0])
        payload.model = model

        async def gemini_cli_stream():
            yield sse_event({"type": "meta", "conversation": conversation})
            try:
                text, raw = await gemini_cli_chat_text(payload, conversation["messages"][-MAX_HISTORY_MESSAGES:])
            except HTTPException as exc:
                yield sse_event({"type": "error", "detail": exc.detail})
                return
            assistant_message = {
                "id": uuid.uuid4().hex,
                "role": "assistant",
                "content": text,
                "created_at": now_ms(),
                "model": model,
                "raw_usage": None,
                "raw": clean_cli_raw(raw),
            }
            conversation["messages"].append(assistant_message)
            conversation["updated_at"] = now_ms()
            save_conversation(user_id, conversation)
            yield sse_event({"type": "delta", "delta": text})
            yield sse_event({"type": "done", "conversation": conversation, "message": assistant_message})

        return StreamingResponse(gemini_cli_stream(), media_type="text/event-stream")

    chat_base, chat_hdrs, model = resolve_chat_provider(payload.provider, payload.model, payload.ms_model)
    _stream_provider = get_api_provider(payload.provider) if payload.provider not in ("modelscope",) else {}
    history = conversation["messages"][-MAX_HISTORY_MESSAGES:]
    upstream_messages = [{"role": "system", "content": chat_system_prompt(payload)}]
    for item in history:
        msg = upstream_message_from_record(item)
        if msg:
            upstream_messages.append(msg)

    async def stream():
        content_parts = []
        raw_usage = None
        yield sse_event({"type": "meta", "conversation": conversation})
        try:
            async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=AI_REQUEST_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    f"{chat_base}/chat/completions",
                    headers=chat_hdrs,
                    json={"model": model, "messages": upstream_messages, "stream": True},
                ) as response:
                    if response.status_code >= 400:
                        detail = await response.aread()
                        body = detail.decode("utf-8", errors="ignore")
                        friendly = friendly_chat_error_detail(body, model, _stream_provider)
                        detail = friendly or sanitize_error_detail(f"上游接口错误：{body}")[:2000]
                        yield sse_event({"type": "error", "detail": detail})
                        return
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if line == "[DONE]":
                            break
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(chunk, dict) and chunk.get("usage"):
                            raw_usage = chunk.get("usage")
                        delta = text_delta_from_chat_chunk(chunk)
                        if delta:
                            content_parts.append(delta)
                            yield sse_event({"type": "delta", "delta": delta})
        except httpx.HTTPError as exc:
            log_net_error("对话(流式) 网络/TLS错误", exc)
            yield sse_event({"type": "error", "detail": f"请求上游接口失败：{exc}"})
            return

        assistant_message = {
            "id": uuid.uuid4().hex,
            "role": "assistant",
            "content": "".join(content_parts).strip() or "接口返回了空回复。",
            "created_at": now_ms(),
            "model": model,
            "raw_usage": raw_usage,
        }
        conversation["messages"].append(assistant_message)
        conversation["updated_at"] = now_ms()
        save_conversation(user_id, conversation)
        yield sse_event({"type": "done", "conversation": conversation, "message": assistant_message})

    return StreamingResponse(stream(), media_type="text/event-stream")

# --- 历史记录与队列状态路由已解耦迁移至 routers/tasks.py ---

# --- ModelScope 角度控制 ---
