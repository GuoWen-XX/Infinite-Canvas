"""Common shared utilities, output persistence, and upstream communication helpers for Infinite-Canvas routers.

Decoupled to provide clean shared services across integrations, video, image, and chat domain routers.
"""
import os
import re
import sys
import json
import time
import uuid
import base64
import logging
import math
import shutil
import tempfile
import subprocess
import asyncio
import urllib
import urllib.parse
import urllib.request
from io import BytesIO
from typing import Dict, Any, List, Optional, Tuple, Set, Union
from urllib.parse import urlparse, quote, unquote

import httpx
from PIL import Image
from fastapi import HTTPException

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
    IMAGE_POLL_INTERVAL,
    VIDEO_POLL_TIMEOUT,
    AI_REQUEST_TIMEOUT,
    now_ms,
    get_api_provider,
    get_api_provider_exact,
    bearer_auth_value,
    provider_endpoint_url,
    provider_env_key_value,
    provider_protocol,
    read_api_env_value,
    load_api_providers,
    log_upstream_call,
    is_apimart_provider,
    is_tudou_provider,
    is_gemini_provider,
    effective_protocol,
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
)
from core.security import (
    is_safe_remote_url,
    validate_safe_url,
    safe_download_bytes,
    sanitize_secret_tokens,
)
from routers.assets import (
    output_url_for,
    output_path_for,
)

logger = logging.getLogger("infinite_canvas.common")
_server_logger = logging.getLogger("dx.server")

IMAGE_OUTPUT_KEY_HINTS = (
    "image_url", "image", "url", "file_url", "img_url", "img", "output", "result",
    "download_url", "picture", "pic", "preview_url", "cover_url", "video_url",
    "video", "audio_url", "audio", "sample",
)
IMAGE_CONTAINER_KEY_HINTS = (
    "images", "image", "output", "outputs", "result", "results", "data", "items", "files", "sample",
)
IMAGE_BASE64_KEY_HINTS = ("b64_json", "base64", "image_base64", "imageBase64")


# --- Section lines 83-126 ---
_history_saver = lambda rec: None
_ws_manager = None
GLOBAL_LOOP = None

def set_online_history_saver(fn):
    global _history_saver
    _history_saver = fn

def set_online_ws_manager(mgr, loop=None):
    global _ws_manager, GLOBAL_LOOP
    _ws_manager = mgr
    GLOBAL_LOOP = loop

def save_to_history(record):
    if _history_saver:
        try:
            _history_saver(record)
        except Exception as e:
            logger.warning("save_to_history failed: %s", e)

def get_ws_manager():
    """返回全局 WebSocket 管理器，供其他 router 复用（避免直接 import main.py 造成循环依赖）。"""
    return _ws_manager

def get_global_loop():
    """返回主事件循环；lifespan 启动前为 None。"""
    return GLOBAL_LOOP

class WsProxy:
    async def send_personal_message(self, message: dict, websocket=None):
        if _ws_manager:
            try:
                await _ws_manager.send_personal_message(message, websocket)
            except Exception:
                pass

    async def broadcast_new_image(self, record: dict):
        if _ws_manager:
            try:
                await _ws_manager.broadcast_new_image(record)
            except Exception:
                pass

    async def broadcast_json(self, message: dict):
        if _ws_manager:
            try:
                await _ws_manager.broadcast_json(message)
            except Exception:
                pass

manager = WsProxy()



# --- Section lines 510-531 ---
def api_headers(json_body=True, provider=None, model=""):
    if provider:
        if is_codex_provider(provider) or is_gemini_cli_provider(provider):
            raise HTTPException(status_code=400, detail="CLI 协议使用本机登录态，不需要 API Key。当前入口应走对应 CLI 专用通道。")
        api_key = provider_env_key_value(provider["id"])
        provider_name = provider.get("name") or provider["id"]
        if not api_key:
            raise HTTPException(status_code=400, detail=f"未配置 {provider_name} 的 API Key，请在 API 平台管理中填写。")
    else:
        api_key = AI_API_KEY
        if not api_key:
            raise HTTPException(status_code=400, detail="未配置 COMFLY_API_KEY，请在 API/.env 中填写。")
    # APIMart proxies Gemini's request format but authenticates with its normal
    # OpenAI-compatible Bearer key. Direct Gemini-compatible providers use x-goog.
    if provider and effective_protocol(provider, model) == "gemini" and not is_apimart_provider(provider):
        headers = {"Accept": "application/json", "x-goog-api-key": api_key, "Authorization": bearer_auth_value(api_key)}
    else:
        headers = {"Accept": "application/json", "Authorization": bearer_auth_value(api_key)}
    # BFL (Black Forest Labs) 原生支持 x-key 请求头鉴权
    if provider and ("bfl" in str(provider.get("id", "")).lower() or "bfl.ml" in str(provider.get("base_url", "")).lower()):
        headers["x-key"] = api_key
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers



# --- Section lines 621-913 ---
def looks_like_generated_image_url(value):
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith("data:image/"):
        return True
    clean = text.split("?", 1)[0].split("#", 1)[0].lower()
    return text.startswith(("http://", "https://", "/output/", "/assets/")) and re.search(r"\.(png|jpe?g|webp|gif|bmp|tiff?)$", clean)

def looks_like_image_base64(value):
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith("data:image/"):
        return True
    if len(text) < 200:
        return False
    sample = re.sub(r"\s+", "", text[:4096])
    if not re.fullmatch(r"[A-Za-z0-9+/=_-]+", sample):
        return False
    padded = sample.replace("-", "+").replace("_", "/")
    padded += "=" * (-len(padded) % 4)
    try:
        head = base64.b64decode(padded[:256], validate=False)
    except Exception:
        return False
    return (
        head.startswith(b"\x89PNG\r\n\x1a\n")
        or head.startswith(b"\xff\xd8\xff")
        or head.startswith(b"RIFF") and head[8:12] == b"WEBP"
        or head.startswith(b"GIF87a")
        or head.startswith(b"GIF89a")
    )

def image_payload_from_string(value, mime_type="image/png", assume_b64=False):
    text = str(value or "").strip()
    if not text:
        return None
    # Some Gemini-compatible proxies (including APIMart's image models) return
    # the generated image as Markdown: ![image](data:image/jpeg;base64,...).
    # Extract the embedded data URL before handling plain URLs/base64 values.
    embedded_data_url = re.search(r"data:(image/[A-Za-z0-9.+-]+);base64,([A-Za-z0-9+/_=-]+)", text)
    if embedded_data_url:
        return {
            "type": "b64",
            "value": embedded_data_url.group(2),
            "mime_type": embedded_data_url.group(1),
        }
    if text.startswith("data:image/"):
        header, sep, encoded = text.partition(",")
        if sep and encoded:
            return {
                "type": "b64",
                "value": encoded.strip(),
                "mime_type": header.split(";", 1)[0].replace("data:", "", 1) or mime_type or "image/png",
            }
    if looks_like_generated_image_url(text):
        return {"type": "url", "value": text}
    if assume_b64 or looks_like_image_base64(text):
        return {"type": "b64", "value": text, "mime_type": mime_type or "image/png"}
    return None

def extract_image_flexible(value, depth=0):
    if depth > 8 or value is None:
        return None
    if isinstance(value, str):
        return image_payload_from_string(value)
    if isinstance(value, list):
        for item in value:
            found = extract_image_flexible(item, depth + 1)
            if found:
                return found
        return None
    if not isinstance(value, dict):
        return None
    for key in IMAGE_BASE64_KEY_HINTS:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return image_payload_from_string(item, value.get("mime_type") or value.get("mimeType") or "image/png", assume_b64=True)
    for key in IMAGE_OUTPUT_KEY_HINTS:
        item = value.get(key)
        if isinstance(item, str):
            found = image_payload_from_string(item, value.get("mime_type") or value.get("mimeType") or "image/png")
            if found:
                return found
        found = extract_image_flexible(item, depth + 1)
        if found:
            return found
    for key in IMAGE_CONTAINER_KEY_HINTS:
        found = extract_image_flexible(value.get(key), depth + 1)
        if found:
            return found
    return None

def extract_images(data):
    found = []
    seen = set()

    def add_image(item):
        if not isinstance(item, dict):
            return
        img_type = item.get("type") or "url"
        value = item.get("value")
        if not value:
            return
        key = (img_type, value)
        if key in seen:
            return
        seen.add(key)
        found.append(item)

    def collect(value, depth=0):
        if depth > 8 or value is None:
            return
        if isinstance(value, str):
            found = image_payload_from_string(value)
            if found:
                add_image(found)
            return
        if isinstance(value, list):
            for item in value:
                collect(item, depth + 1)
            return
        if not isinstance(value, dict):
            return
        if value.get("type") == "image_generation_call":
            result = value.get("result")
            if isinstance(result, str) and result.strip():
                add_image(image_payload_from_string(
                    result,
                    value.get("mime_type") or value.get("mimeType") or "image/png",
                    assume_b64=not looks_like_generated_image_url(result),
                ))
            else:
                collect(result, depth + 1)
        has_direct_url = any(
            isinstance(value.get(key), str) and looks_like_generated_image_url(value.get(key))
            for key in IMAGE_OUTPUT_KEY_HINTS
        )
        if not has_direct_url:
            for key in IMAGE_BASE64_KEY_HINTS:
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    add_image(image_payload_from_string(item, value.get("mime_type") or value.get("mimeType") or "image/png", assume_b64=True))
        for key in IMAGE_OUTPUT_KEY_HINTS:
            item = value.get(key)
            if isinstance(item, str):
                add_image(image_payload_from_string(item, value.get("mime_type") or value.get("mimeType") or "image/png"))
            else:
                collect(item, depth + 1)
        for key in IMAGE_CONTAINER_KEY_HINTS:
            collect(value.get(key), depth + 1)

    candidates = data.get("candidates") if isinstance(data, dict) else None
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content") or {}
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                inline = part.get("inlineData") or part.get("inline_data") or {}
                if not isinstance(inline, dict):
                    inline = {}
                value = inline.get("data")
                if value:
                    add_image({
                        "type": "b64",
                        "value": value,
                        "mime_type": inline.get("mimeType") or inline.get("mime_type") or "image/png",
                    })
                # APIMart Gemini image models can return a Markdown data URL in
                # the text part instead of the native inlineData structure.
                embedded = image_payload_from_string(part.get("text"))
                if embedded:
                    add_image(embedded)

    current = data
    if isinstance(current, dict) and isinstance(current.get("data"), dict) and isinstance(current["data"].get("result"), dict):
        current = current["data"]
    if isinstance(current, dict) and isinstance(current.get("result"), dict):
        for item in current["result"].get("images") or []:
            if not isinstance(item, dict):
                collect(item)
                continue
            url = item.get("url")
            if isinstance(url, list):
                for one in url:
                    collect(one)
            else:
                collect(url)
            collect(item)

    collect(data)
    if isinstance(data, dict) and isinstance(data.get("data"), dict) and isinstance(data["data"].get("data"), dict):
        collect(data["data"]["data"])
    if found:
        return found
    raise HTTPException(status_code=502, detail="无法识别生图接口返回格式")

def extract_image(data):
    try:
        images = extract_images(data)
        if images:
            return images[0]
    except HTTPException:
        pass
    candidates = data.get("candidates") if isinstance(data, dict) else None
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content") or {}
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                inline = part.get("inlineData") or part.get("inline_data") or {}
                if not isinstance(inline, dict):
                    continue
                value = inline.get("data")
                if value:
                    return {
                        "type": "b64",
                        "value": value,
                        "mime_type": inline.get("mimeType") or inline.get("mime_type") or "image/png",
                    }
    if isinstance(data.get("data"), dict) and isinstance(data["data"].get("result"), dict):
        data = data["data"]
    if isinstance(data.get("result"), dict):
        result_images = data["result"].get("images") or []
        if result_images:
            first = result_images[0]
            url = first.get("url")
            if isinstance(url, list) and url:
                return {"type": "url", "value": url[0]}
            if isinstance(url, str) and url:
                return {"type": "url", "value": url}
    flexible = extract_image_flexible(data)
    if flexible:
        return flexible
    if isinstance(data.get("data"), dict) and isinstance(data["data"].get("data"), dict):
        data = data["data"]["data"]
    images = data.get("data") or []
    if not isinstance(images, list) or not images:
        raise HTTPException(status_code=502, detail="生图接口没有返回图片数据")
    first = images[0]
    if first.get("url"):
        return {"type": "url", "value": first["url"]}
    if first.get("b64_json"):
        return {"type": "b64", "value": first["b64_json"]}
    flexible = extract_image_flexible(first)
    if flexible:
        return flexible
    raise HTTPException(status_code=502, detail="无法识别生图接口返回格式")

def _responses_wrap(url, status_code, payload):
    return httpx.Response(
        status_code,
        headers={"content-type": "application/json"},
        content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        request=httpx.Request("POST", url),
    )

async def post_openai_responses_stream(client, upstream_url, headers, body):
    """RS / Responses 的 SSE 流式请求：流式从一开始就持续有事件字节返回，
    不会触发中转的 Cloudflare 120s 读超时。收到 response.completed 后
    把完整 response 对象包装成普通 httpx.Response，下游解析逻辑不变。"""
    request = httpx.Request("POST", upstream_url)

    def wrap(status_code, payload):
        return _responses_wrap(upstream_url, status_code, payload)

    stream_body = dict(body)
    stream_body["stream"] = True
    try:
        async with client.stream("POST", upstream_url, headers=headers, json=stream_body) as resp:
            ctype = (resp.headers.get("content-type") or "").lower()
            if resp.status_code >= 400 or "text/event-stream" not in ctype:
                content = await resp.aread()
                if resp.status_code in {400, 404, 405, 415, 422}:
                    logger.info(f"RS 流式请求被拒（{resp.status_code}），回退非流式：{content[:200]!r}")
                    return await client.post(upstream_url, headers=headers, json=body)
                return httpx.Response(resp.status_code, headers=resp.headers, content=content, request=request)
            completed = None
            error_payload = None
            stream_images = []
            stream_seen_images = set()

            def remember_stream_image(image):
                if not isinstance(image, dict):
                    return
                value = image.get("value")
                if not value:
                    return
                key = (image.get("type") or "url", value)
                if key in stream_seen_images:
                    return
                stream_seen_images.add(key)
                stream_images.append(image)

            def remember_stream_images_from(value):
                try:
                    for image in extract_images(value):
                        remember_stream_image(image)
                except HTTPException:
                    pass

            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    event = json.loads(chunk)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                etype = str(event.get("type") or "")
                if etype in {"response.completed", "response.incomplete"} and isinstance(event.get("response"), dict):
                    completed = event["response"]
                elif etype == "response.failed":
                    failed = event.get("response")
                    error_payload = failed if isinstance(failed, dict) else {"error": {"message": "response.failed"}}
                elif etype == "error":
                    message = event.get("message") or event.get("error") or chunk[:300]
                    error_payload = {"error": {"message": str(message)}}
                if isinstance(event.get("item"), dict):
                    item = event["item"]
                    if item.get("type") not in {"input_image", "input_text"}:
                        remember_stream_images_from(item)
                for key in ("partial_image_b64", "image_b64", "b64_json"):
                    image = image_payload_from_string(event.get(key), assume_b64=True)
                    if image:
                        remember_stream_image(image)
                for key in ("result", "image", "image_url"):
                    image = image_payload_from_string(event.get(key))
                    if image:
                        remember_stream_image(image)
            if completed is not None and stream_images:
                try:
                    has_completed_image = bool(extract_images(completed))
                except HTTPException:
                    has_completed_image = False
                if not has_completed_image:
                    completed = dict(completed)
                    completed["output"] = list(completed.get("output") or [])
                    for image in stream_images:
                        if image.get("type") == "b64":
                            completed["output"].append({
                                "type": "image_generation_call",
                                "status": "completed",
                                "result": image.get("value"),
                                "mime_type": image.get("mime_type") or "image/png",
                            })
                        else:
                            completed["output"].append({"type": "image", "image_url": image.get("value")})
            if completed is None and error_payload is None and stream_images:
                image = stream_images[-1]
                if image.get("type") == "b64":
                    completed = {"output": [{"type": "image_generation_call", "status": "completed", "result": image.get("value"), "mime_type": image.get("mime_type") or "image/png"}]}
                else:
                    completed = {"output": [{"type": "image", "image_url": image.get("value")}]}
            if completed is not None:
                return wrap(200, completed)
            return wrap(502, error_payload or {"error": {"message": "RS 流式响应结束但没有 response.completed 事件"}})
    except httpx.HTTPError as e:
        logger.info(f"RS 流式请求传输失败，回退非流式：{e}")
        return await client.post(upstream_url, headers=headers, json=body)

def extract_task_id(data):
    if data.get("task_id"):
        return str(data["task_id"])
    if data.get("taskId"):
        return str(data["taskId"])
    if data.get("submit_id"):
        return str(data["submit_id"])
    if data.get("video_id"):
        return str(data["video_id"])
    if data.get("videoId"):
        return str(data["videoId"])
    if data.get("id") and str(data.get("id", "")).startswith("task"):
        return str(data["id"])
    nested = data.get("data")
    if isinstance(nested, list) and nested:
        first = nested[0]
        if isinstance(first, dict):
            return extract_task_id(first)
    if isinstance(nested, dict):
        return extract_task_id(nested)
    return None

def extract_task_id_from_text(text):
    value = str(text or "")
    match = re.search(r"(?:task_id|taskId|task id)\s*[=:：]\s*([A-Za-z0-9_.:-]+)", value, re.IGNORECASE)
    return match.group(1) if match else ""

def images_api_unsupported(response):
    text = str(getattr(response, "text", "") or "").lower()
    return "images api is not supported" in text or "not supported for this platform" in text



# --- Section lines 1409-1429 ---
def is_tudou_grok_image_model(model):
    return str(model or "").strip().lower().startswith("grok-imagine-image")

def is_tudou_grok_video_model(model):
    return str(model or "").strip().lower().startswith("grok-imagine-video")

def is_volcengine_provider(provider):
    return provider_protocol(provider) == "volcengine"

def is_runninghub_provider(provider):
    return provider_protocol(provider) == "runninghub" or str((provider or {}).get("id") or "").strip().lower() in {"runninghub", "runninghub-ai"}

def is_jimeng_provider(provider):
    return provider_protocol(provider) == "jimeng" or str((provider or {}).get("id") or "").strip().lower() == "jimeng"

def is_codex_provider(provider):
    return provider_protocol(provider) == "codex"

def is_gemini_cli_provider(provider):
    return provider_protocol(provider) == "gemini-cli"



# --- Section lines 2358-2471 ---
def is_yuli_provider(provider):
    # 玉玉API（yuli.host）的视频接口走自有格式（/v1/video/create + /v1/video/query），
    # 与通用 OpenAI /v1/videos/generations 不同，需单独识别。
    base_url = str((provider or {}).get("base_url") or "").lower()
    return "yuli.host" in base_url

def is_lingjing_provider(provider):
    base_url = str((provider or {}).get("base_url") or "").lower()
    provider_id = str((provider or {}).get("id") or "").strip().lower()
    return provider_id == "lingjing" or "apistudio.vip" in base_url

def is_pollinations_provider(provider):
    # 兼容两种入参：provider dict 或 provider_id 字符串
    if isinstance(provider, str):
        return "pollinations" in provider.strip().lower()
    base_url = str((provider or {}).get("base_url") or "").lower()
    provider_id = str((provider or {}).get("id") or "").strip().lower()
    return "pollinations" in provider_id or "pollinations" in base_url


def is_meigen_provider(provider):
    # 兼容 provider dict 或 provider_id 字符串
    if isinstance(provider, str):
        return "meigen" in provider.strip().lower()
    base_url = str((provider or {}).get("base_url") or "").lower()
    provider_id = str((provider or {}).get("id") or "").strip().lower()
    return "meigen" in provider_id or "meigen" in base_url


def meigen_env_key(provider):
    """Read MEIGEN_API_TOKEN from provider env mapping or API/.env."""
    provider_id = provider.get("id") if isinstance(provider, dict) else provider
    key = provider_env_key_value(provider_id or "meigen")
    if key and "…" not in key and "????????" not in key and key.startswith("meigen_"):
        return key
    # fallback: read the .env directly (provider id may differ)
    try:
        env_file = os.path.join(BASE_DIR, "API", ".env")
        with open(env_file, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line.startswith("MEIGEN_API_TOKEN="):
                    value = line.split("=", 1)[1].strip()
                    if value:
                        return value
    except Exception:  # noqa: BLE001
        pass
    return ""


_MEIGEN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
_MEIGEN_MCP_URL = "https://www.meigen.ai/api/mcp"


async def _meigen_rpc(method, params, rpc_id, token, session=None, notify=False):
    """Single JSON-RPC call to MeiGen MCP endpoint (SSE body tolerated)."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": bearer_auth_value(token),
        "User-Agent": _MEIGEN_UA,
        "Origin": "https://www.meigen.ai",
    }
    if session:
        headers["Mcp-Session-Id"] = session
    body = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if rpc_id is not None:
        body["id"] = rpc_id
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.post(_MEIGEN_MCP_URL, headers=headers, json=body)
    log_upstream_call("POST", _MEIGEN_MCP_URL + f" {method}", status=resp.status_code,
                      provider="meigen", error="" if resp.status_code == 200 else resp.text[:150])
    resp.raise_for_status()
    if notify:
        return {}
    raw = resp.text
    for line in raw.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return json.loads(raw) if raw.strip() else {}


def is_dashscope_provider(provider):
    base_url = str((provider or {}).get("base_url") or "").lower()
    model_id = str((provider or {}).get("model") or "").lower()
    if "maas.aliyuncs.com" in base_url or "dashscope.aliyuncs.com" in base_url:
        return True
    return "dashscope" in str((provider or {}).get("protocol") or "").lower()

def is_agnes_provider(provider, model=""):
    base_url = str((provider or {}).get("base_url") or "").lower()
    model_id = str(model or "").strip().lower()
    return "apihub.agnes-ai.com" in base_url or model_id.startswith("agnes-video-")

# ---- 数字人/真人认证：平台无关分发 ----
# 认证是一个跨平台功能。每个平台用不同的资产 API 实现，但对外是统一入口。
# 新增平台时：在 avatar_platform_for_provider 里加一条识别，并把平台键加进
# AVATAR_SUPPORTED_PLATFORMS，再在 register/avatar-status 端点里补一个分发分支即可。
AVATAR_SUPPORTED_PLATFORMS = {"apimart", "volcengine"}  # 已接入官方资产 API 的平台

def avatar_platform_for_provider(provider) -> str:
    if not provider:
        return ""
    if is_apimart_provider(provider):
        return "apimart"
    if is_volcengine_provider(provider):
        return "volcengine"
    return ""

def provider_supports_avatar(provider) -> bool:
    return avatar_platform_for_provider(provider) in AVATAR_SUPPORTED_PLATFORMS



# --- Section lines 4186-4216 ---
def public_base_url() -> str:
    # 实时读 API/.env 且文件优先：公网隧道重启后地址会变，隧道脚本只改 .env；
    # 启动时 load_env_file 会把旧值复制进 os.environ，若 env 优先会永远读到过期地址
    value = (
        read_api_env_value("PUBLIC_MEDIA_BASE_URL") or
        os.getenv("PUBLIC_MEDIA_BASE_URL") or
        PUBLIC_MEDIA_BASE_URL or
        read_api_env_value("PUBLIC_BASE_URL") or
        os.getenv("PUBLIC_BASE_URL") or
        PUBLIC_BASE_URL or
        ""
    ).strip().rstrip("/")
    if value and re.match(r"^https?://", value, re.I):
        return value
    return ""

def public_media_url_suffix() -> str:
    token = str(os.getenv("PUBLIC_MEDIA_TOKEN") or "").strip()
    return f"?token={urllib.parse.quote(token)}" if token else ""

def local_asset_public_url(value: str) -> str:
    text = str(value or "").strip()
    if not text.startswith(("/output/", "/assets/")):
        return ""
    if not output_file_from_url(text):
        return ""
    base = public_base_url()
    if not base:
        return ""
    return f"{base}{urllib.parse.quote(text, safe='/:?&=%#.-_~')}{public_media_url_suffix()}"



def rewrite_runninghub_file_url(url):
    try:
        from routers.integrations import rewrite_runninghub_file_url as _rewrite
        return _rewrite(url)
    except Exception:
        return url

# --- Section lines 4924-5071 ---
async def save_ai_image_to_output(image_data, prefix="online_", category="output"):
    filename = f"{prefix}{uuid.uuid4().hex[:10]}.png"
    path = output_path_for(filename, category)
    if image_data["type"] == "b64":
        mime_type = str(image_data.get("mime_type") or "").lower()
        if "jpeg" in mime_type or "jpg" in mime_type:
            filename = filename[:-4] + ".jpg"
            path = output_path_for(filename, category)
        elif "webp" in mime_type:
            filename = filename[:-4] + ".webp"
            path = output_path_for(filename, category)
        with open(path, "wb") as f:
            f.write(base64.b64decode(image_data["value"]))
        return output_url_for(filename, category)
    value = image_data["value"]
    if value.startswith("/output/") or value.startswith("/assets/"):
        return value
    value = rewrite_runninghub_file_url(value)
    if value.startswith("http://") or value.startswith("https://"):
        try:
            validate_safe_url(value, allow_private=False)
            content, content_type = await safe_download_bytes(
                value,
                timeout=300.0,
                max_bytes=50 * 1024 * 1024,
                allow_private=False,
            )
            content_type = (content_type or "").lower()
            if "jpeg" in content_type or "jpg" in content_type:
                filename = filename[:-4] + ".jpg"
                path = output_path_for(filename, category)
            elif "webp" in content_type:
                filename = filename[:-4] + ".webp"
                path = output_path_for(filename, category)
            with open(path, "wb") as f:
                f.write(content)
            return output_url_for(filename, category)
        except Exception as e:
            logger.info(f"保存上游图片失败: {e}; url={value}")
            return value

def log_net_error(context, exc, url=""):
    """把网络请求异常的完整链路（含底层 SSL/socket 原因）打到控制台，方便排查 VPN/代理问题。"""
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
            logger.warning(line)
        except Exception:
            pass
    except Exception:
        try:
            logger.warning(f"[NET-ERR] {context} | {type(exc).__name__}: {exc}")
        except Exception:
            pass

def image_output_meta(url, source_item=None):
    meta = {"url": url, "kind": "image"}
    if not url:
        return meta
    parsed_name = os.path.basename(urllib.parse.urlparse(str(url)).path)
    if parsed_name:
        meta["name"] = parsed_name
    if isinstance(source_item, dict):
        for key in ("natural_w", "natural_h", "width", "height", "w", "h", "layout_w", "layout_h"):
            try:
                value = int(float(source_item.get(key) or 0))
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                meta[key] = value
    path = output_file_from_url(url)
    if path and os.path.exists(path):
        try:
            with Image.open(path) as img:
                width, height = img.size
            if width > 0 and height > 0:
                meta.update({
                    "natural_w": width,
                    "natural_h": height,
                    "width": width,
                    "height": height,
                })
        except Exception:
            pass
    return meta

async def save_remote_video_to_output(url, prefix="video_", category="output"):
    if not url:
        return ""
    if url.startswith("/output/") or url.startswith("/assets/"):
        return url
    video_exts = {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv", ".flv"}
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return url
    try:
        validate_safe_url(url)
    except Exception as ssrf_err:
        logger.warning(f"SSRF 防护拦截视频下载: {ssrf_err}")
        return url
    clean_ext = os.path.splitext(parsed.path)[1].lower()
    stem = f"{prefix}{uuid.uuid4().hex[:10]}"
    filename = f"{stem}{clean_ext if clean_ext in video_exts else '.mp4'}"
    path = output_path_for(filename, category)
    try:
        headers = {
            "User-Agent": "ComfyUI-API-Modelscope/1.0",
            "Accept": "video/*,application/octet-stream,*/*;q=0.8",
        }
        content, content_type = await safe_download_bytes(
            url,
            timeout=VIDEO_POLL_TIMEOUT,
            max_bytes=500 * 1024 * 1024,
            headers=headers,
            allow_private=False,
        )
        content_type = (content_type or "").lower()
        if "text/html" in content_type or "application/json" in content_type:
            raise RuntimeError(f"unexpected video content type: {content_type}")
        ext = clean_ext
        if ext in video_exts:
            filename = f"{stem}{ext}"
            path = output_path_for(filename, category)
        elif "webm" in content_type:
            filename = f"{stem}.webm"
            path = output_path_for(filename, category)
        elif "quicktime" in content_type or "mov" in content_type:
            filename = f"{stem}.mov"
            path = output_path_for(filename, category)
        elif "x-matroska" in content_type or "mkv" in content_type:
            filename = f"{stem}.mkv"
            path = output_path_for(filename, category)
        elif "x-flv" in content_type or "flv" in content_type:
            filename = f"{stem}.flv"
            path = output_path_for(filename, category)
        with open(path, "wb") as f:
            f.write(content)
        if os.path.getsize(path) <= 0:
            raise RuntimeError("empty video response")
        return output_url_for(filename, category)
    except Exception as e:
        logger.info(f"保存上游视频失败: {e}")
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        return url

def parse_size_pair(size):
    match = re.fullmatch(r"\s*(\d+)\s*[xX*]\s*(\d+)\s*", str(size or ""))
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))

def snap_size_to_multiple(size, multiple=16):
    width, height = parse_size_pair(size)
    if not width or not height:
        return size
    step = max(1, int(multiple or 16))
    snapped_w = max(step, int(math.ceil(width / step) * step))
    snapped_h = max(step, int(math.ceil(height / step) * step))
    return f"{snapped_w}x{snapped_h}"

CHAT_RATIO_SIZE_OPTIONS = {
    "1:1": ("1024x1024", "1536x1536", "2048x2048"),
    "2:3": ("720x1080", "1024x1536", "1365x2048"),
    "3:2": ("1080x720", "1536x1024", "2048x1365"),
    "3:4": ("1008x1344", "1536x2048", "2448x3264"),
    "4:3": ("1344x1008", "2048x1536", "3264x2448"),
    "9:16": ("720x1280", "1080x1920", "1440x2560"),
    "16:9": ("1280x720", "1920x1080", "2560x1440"),
}



GPT_IMAGE2_MAX_EDGE = 3840
GPT_IMAGE2_MAX_PIXELS = 8_294_400
GPT_IMAGE2_MIN_PIXELS = 655_360

def is_gpt_image_2_model(model):
    raw = str(model or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    compact = re.sub(r"[^a-z0-9]+", "", raw)
    return (
        normalized == "gpt-image-2"
        or normalized.startswith("gpt-image-2-")
        or normalized.endswith("-gpt-image-2")
        or "-gpt-image-2-" in normalized
        or compact == "gptimage2"
        or compact.startswith("gptimage2")
        or compact.endswith("gptimage2")
    )

def gpt_image_2_size_error_message(size):
    display_size = size or "未指定"
    return (
        f"GPT-Image-2 不支持当前尺寸 {display_size}：它有最大像素限制"
        "（长边最大 3840、总像素约 829 万）。请改用更小的尺寸，"
        "或切换到 nano-banana 生成更高分辨率。"
    )

def gpt_image_2_size_exceeds_supported(size):
    width, height = parse_size_pair(size)
    return bool(width and height and (max(width, height) > GPT_IMAGE2_MAX_EDGE or width * height > GPT_IMAGE2_MAX_PIXELS))



# --- Section lines 5246-5327 ---
def friendly_image_error_detail(text, size="", model=""):
    text = str(text or "")
    lower_text = text.lower()
    if is_gpt_image_2_model(model) and gpt_image_2_size_exceeds_supported(size):
        return gpt_image_2_size_error_message(size)
    mentions_size = any(token in lower_text for token in ["size", "resolution", "dimension"])
    is_gpt_size_error = is_gpt_image_2_model(model) and mentions_size and (
        "invalid" in lower_text
        or "unsupported" in lower_text
        or "not supported" in lower_text
        or "exceed" in lower_text
        or "must be one of" in lower_text
    )
    m = re.search(r"longest edge must be less than or equal to (\d+)", text)
    if m and is_gpt_image_2_model(model):
        limit = m.group(1)
        return f"GPT-Image-2 不支持当前尺寸 {size or '未指定'}：最长边超过 {limit}px。如果需要更高分辨率，请切换到 nano-banana；继续使用 GPT 时请调低分辨率。"
    if m:
        limit = m.group(1)
        return f"该模型不支持当前分辨率：最长边超过 {limit}px。请把图片分辨率调低（例如换到 2K 或更小），或更换支持高分辨率的模型。"
    if "image size must be at least" in lower_text:
        pixel_match = re.search(r"at least (\d+) pixels", lower_text)
        pixels = pixel_match.group(1) if pixel_match else "3686400"
        return f"该模型要求更高分辨率，当前尺寸 {size or '过小'} 不满足最低像素要求（至少 {pixels} 像素）。火山 Seedream 5.0 建议从 2K 起步。"
    if is_gpt_size_error or (("invalid size" in lower_text or "invalid_value" in lower_text) and is_gpt_image_2_model(model)):
        return gpt_image_2_size_error_message(size)
    if "invalid size" in lower_text or "invalid_value" in lower_text:
        return f"该模型不支持当前尺寸：{size or '未指定'}。请尝试更换分辨率或模型。"
    if "inputtextsensitivecontentdetected" in lower_text or "policyviolation" in lower_text or "copyright restrictions" in lower_text:
        return "上游内容安全拦截了这段提示词，原因偏向版权/敏感内容限制。请改写提示词，避免直接出现具体 IP、角色名、品牌名、影视/动漫作品名，改成风格特征描述再试。"
    if "rejected by the safety system" in lower_text or "image_generation_user_error" in lower_text or "safety system" in lower_text or "content_policy_violation" in lower_text or "content policy" in lower_text:
        return "上游（Azure/OpenAI 系）内容安全系统拒绝了本次生图请求。可能是提示词或参考图触发了内容审核。请改写提示词、避免敏感/暴力/成人/名人/版权角色等描述；若使用了人物参考图，可换一张图再试。这是上游平台的审核策略，并非本系统报错。"
    if "rate limit" in lower_text or "429" in lower_text:
        return "请求过于频繁，已被上游限流，请稍后再试。"
    if "unauthorized" in lower_text or "401" in lower_text:
        return "API Key 无效或已过期，请到「API 设置」检查 Key。"
    if "model_not_found" in lower_text or "channel not found" in lower_text:
        return f"上游平台找不到模型「{model}」可用通道。可能该模型未在此账号开通，请换一个已开通的模型。"
    return ""

def parse_error_payload_text(text):
    body = str(text or "").strip()
    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}

def friendly_chat_error_detail(text, model="", provider=None):
    raw_text = str(text or "")
    lower_text = raw_text.lower()
    payload = parse_error_payload_text(raw_text)
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = str(error.get("code") or payload.get("code") or "").strip()
    message = str(error.get("message") or payload.get("message") or "").strip()
    code_lc = code.lower()
    message_lc = message.lower()
    model_name = str(model or "").strip()

    if is_volcengine_provider(provider):
        if code_lc in {"invalidendpointormodel.notfound", "invalidendpointormodel.modelidaccessdisabled"}:
            provider_name = provider.get("name") or provider.get("id") or "火山方舟"
            return (
                f"{provider_name} 当前不接受模型名「{model_name or '未指定'}」直接调用聊天接口，"
                f"请在火山方舟控制台创建并使用推理接入点 ID（形如 `ep-...`）作为聊天模型。\n\n"
                f"补充说明：`/api/v3/models` 能拉到公开模型列表，但你的账号未必能直接用这些模型名调用 `/chat/completions`；"
                f"很多账号只允许传自己已开通的 `ep-...` 接入点。"
            )
        if "does not exist or you do not have access to it" in message_lc:
            return (
                f"火山方舟找不到或无权访问聊天模型「{model_name or '未指定'}」。"
                f"如果你现在填的是模型名，请改成已开通的推理接入点 ID（`ep-...`）；"
                f"如果已经是 `ep-...`，请检查这个接入点是否绑定了聊天模型、区域是否正确、以及账号是否有调用权限。"
            )
    if "unauthorized" in lower_text or "401" in lower_text:
        return "API Key 无效或已过期，请到「API 设置」检查 Key。"
    if "rate limit" in lower_text or "429" in lower_text:
        return "请求过于频繁，已被上游限流，请稍后再试。"
    return ""

def friendly_video_error_detail(text, model="", provider=None):
    """把上游视频接口的常见错误翻译成用户能看懂的中文提示；无法识别时返回空串。"""
    body = str(text or "")
    if not body:
        return ""
    low = body.lower()

    if "insufficient" in low or "余额不足" in body or "arrears" in low:
        return "账户余额不足，请前往对应平台充值后重试"
    if "rate limit" in low or "429" in low or "too many requests" in low:
        return "请求过于频繁，请稍后重试"
    if "api key" in low and ("invalid" in low or "unauthorized" in low or "401" in low):
        return "API Key 无效或已过期，请在设置中重新填写"
    if "model" in low and ("not found" in low or "not support" in low or "does not exist" in low):
        return f"模型 {model} 不被当前平台支持，请更换模型"
    if "content" in low and ("policy" in low or "risk" in low or "审核" in body):
        return "提示词未通过内容安全审核，请修改后重试"
    if "timeout" in low or "504" in low:
        return "上游响应超时，请稍后重试"
    return ""

def sanitize_error_detail(detail: str) -> str:
    """Mask any sensitive API keys, tokens, or authorization headers in error details."""
    return sanitize_secret_tokens(str(detail or ""))

async def video_reference_to_frame_data_urls(value, max_frames=6, max_size=768):
    if not isinstance(value, str) or not value:
        return []
    path = output_file_from_url(value)
    cleanup_path = ""
    if not path and value.startswith(("http://", "https://")):
        suffix = os.path.splitext(urllib.parse.urlparse(value).path)[1] or ".mp4"
        fd, cleanup_path = tempfile.mkstemp(prefix="canvas_llm_video_", suffix=suffix)
        os.close(fd)
        try:
            content, _ = await safe_download_bytes(value, timeout=120.0, max_bytes=100 * 1024 * 1024)
            with open(cleanup_path, "wb") as f:
                f.write(content)
            path = cleanup_path
        except Exception as e:
            logger.warning(f"[canvas-llm] video download failed: {e}")
            if cleanup_path and os.path.exists(cleanup_path):
                try: os.remove(cleanup_path)
                except OSError: pass
            return []
    if not path or not os.path.exists(path):
        return []
    frame_dir = tempfile.mkdtemp(prefix="canvas_llm_frames_")
    try:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return []
        pattern = os.path.join(frame_dir, "frame_%03d.jpg")
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", path,
            "-vf", f"fps=1,scale='min({max_size},iw)':-2",
            "-frames:v", str(max(1, max_frames)),
            pattern
        ]
        proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode != 0:
            logger.warning(f"[canvas-llm] ffmpeg frame extract failed: {proc.stderr[:300]}")
            return []
        frames = []
        for name in sorted(os.listdir(frame_dir)):
            if not name.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            frame_path = os.path.join(frame_dir, name)
            with open(frame_path, "rb") as f:
                frames.append(f"data:image/jpeg;base64,{base64.b64encode(f.read()).decode('ascii')}")
        return frames
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)

VIDEO_URL_KEYS = (
    "url", "video_url", "videoUrl", "mp4_url", "mp4Url",
    "output", "output_url", "outputUrl", "download_url", "downloadUrl",
    "video", "src", "uri", "preview_url", "previewUrl", "path",
    "last_frame_url", "lastFrameUrl", "remixed_from_video_id",
)

# --- Section lines 9926-10152 ---
def _collect_video_url(value, urls):
    if not value:
        return
    if isinstance(value, str):
        if value.startswith("http://") or value.startswith("https://") or value.startswith("/output/") or value.startswith("/assets/"):
            urls.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _collect_video_url(item, urls)
        return
    if isinstance(value, dict):
        for key in ("videos", "outputs", "data", "detail", "result", "results", "content"):
            if key in value:
                _collect_video_url(value.get(key), urls)
        for key in VIDEO_URL_KEYS:
            if key in value:
                _collect_video_url(value.get(key), urls)

def video_output_urls(raw):
    urls = []
    if not isinstance(raw, dict):
        return urls
    candidates = [raw]
    data = raw.get("data")
    detail = raw.get("detail")
    content = raw.get("content")
    if isinstance(data, dict):
        candidates.append(data)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                candidates.append(item)
    if isinstance(detail, dict):
        candidates.append(detail)
    elif isinstance(detail, list):
        for item in detail:
            if isinstance(item, dict):
                candidates.append(item)
    if isinstance(content, dict):
        candidates.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                candidates.append(item)
    for node in list(candidates):
        result = node.get("result") if isinstance(node, dict) else None
        results = node.get("results") if isinstance(node, dict) else None
        if isinstance(result, dict):
            candidates.append(result)
        elif isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    candidates.append(item)
        if isinstance(results, dict):
            candidates.append(results)
        elif isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    candidates.append(item)
    for node in candidates:
        if not isinstance(node, dict):
            continue
        for key in ("videos", "outputs", "results", "content"):
            value = node.get(key)
            if value:
                _collect_video_url(value, urls)
        for key in VIDEO_URL_KEYS:
            if key in node:
                _collect_video_url(node.get(key), urls)
    deduped = []
    for url in urls:
        if isinstance(url, str) and url and url not in deduped:
            deduped.append(url)
    return deduped

def video_api_root(provider):
    base_url = (provider.get("base_url") or AI_BASE_URL).rstrip("/")
    if is_volcengine_provider(provider):
        if base_url.endswith("/api/v3"):
            base_url = base_url[: -len("/api/v3")]
        return base_url
    if base_url.endswith("/v1") or base_url.endswith("/v2"):
        base_url = base_url.rsplit("/", 1)[0]
    return base_url

def looks_like_html_response(text: str) -> bool:
    sample = str(text or "").lstrip()[:200].lower()
    return sample.startswith("<!doctype html") or sample.startswith("<html") or "<head" in sample

def video_submit_url_candidates(provider, base_url):
    if is_dashscope_provider(provider):
        # 阿里云百炼(DashScope) 视频异步接口：wan3.0 系列等
        return [f"{base_url}/api/v1/services/aigc/video-generation/video-synthesis"]
    if is_agnes_provider(provider):
        return [f"{base_url}/v1/videos"]
    if is_lingjing_provider(provider):
        return [f"{base_url}/v1/videos"]
    if is_apimart_provider(provider):
        return [f"{base_url}/videos/generations" if base_url.endswith("/v1") else f"{base_url}/v1/videos/generations"]
    if is_volcengine_provider(provider):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.path and parsed.path.rstrip("/"):
            return [base_url]
        return [f"{base_url}/api/v3/contents/generations/tasks"]
    if is_yuli_provider(provider):
        return [f"{base_url}/v1/video/create"]
    return [f"{base_url}/v1/videos/generations", f"{base_url}/v2/videos/generations"]

def video_task_url_candidates(provider, base_url, task_id, submit_url=""):
    if is_dashscope_provider(provider):
        quoted_id = urllib.parse.quote(str(task_id), safe="")
        return [f"{base_url}/api/v1/tasks/{quoted_id}"]
    if is_tudou_provider(provider):
        quoted_id = urllib.parse.quote(str(task_id), safe="")
        return [f"{base_url}/v1/videos/{quoted_id}"]
    if is_agnes_provider(provider):
        quoted_id = urllib.parse.quote(str(task_id), safe="")
        return [
            f"{base_url}/agnesapi?{urllib.parse.urlencode({'video_id': task_id})}",
            f"{base_url}/v1/videos/{quoted_id}",
        ]
    if is_lingjing_provider(provider):
        quoted_id = urllib.parse.quote(str(task_id), safe="")
        return [
            f"{base_url}/v1/videos/{quoted_id}",
            f"{base_url}/v1/video/query?{urllib.parse.urlencode({'id': task_id})}",
        ]
    if is_apimart_provider(provider):
        task_path = f"{base_url}/tasks/{task_id}" if base_url.endswith("/v1") else f"{base_url}/v1/tasks/{task_id}"
        return [f"{task_path}?language=zh"]
    if is_volcengine_provider(provider):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.path and parsed.path.rstrip("/"):
            return [f"{base_url}/{task_id}"]
        return [f"{base_url}/api/v3/contents/generations/tasks/{task_id}"]
    if is_yuli_provider(provider):
        # 玉玉API 两种视频格式：OpenAI（/v1/videos/{id}）与原生（/v1/video/query?id=）。
        # 两个都试，谁返回成功就用谁，兼容 veo OpenAI 路径与 doubao 原生路径。
        return [f"{base_url}/v1/videos/{task_id}", f"{base_url}/v1/video/query?id={task_id}"]
    v1_task = f"{base_url}/v1/videos/generations/{task_id}"
    v1_generic_task = f"{base_url}/v1/tasks/{task_id}"
    v2_task = f"{base_url}/v2/videos/generations/{task_id}"
    if "/v2/videos/generations" in str(submit_url or ""):
        return [v2_task, v1_task, v1_generic_task]
    return [v1_task, v1_generic_task, v2_task]

VIDEO_TASK_SUCCESS_STATUSES = {
    "SUCCESS", "SUCCEED", "SUCCEEDED", "COMPLETED", "COMPLETE",
    "DONE", "FINISHED", "FINISH", "OK", "READY",
}
VIDEO_TASK_FAILURE_STATUSES = {
    "FAILURE", "FAILED", "FAIL", "ERROR", "ERRORED",
    "CANCELED", "CANCELLED", "TIMEOUT", "TIMEDOUT", "REJECTED", "EXPIRED",
}

def humanize_video_task_failure(reason) -> str:
    """把上游视频任务的失败原因转成对用户友好的中文提示。
    目前主要处理 veo（Google）的内容安全过滤码。"""
    text = str(reason or "").strip()
    upper = text.upper()
    # veo 知名人物/真人面孔过滤
    if "PROMINENT_PEOPLE_FILTER" in upper or "PROMINENT_PEOPLE" in upper:
        return (
            "视频生成被上游内容安全策略拦截：检测到提示词或参考图里包含知名人物 / 真人面孔"
            f"（错误码：{text}）。\n\n"
            "这不是代码错误，而是 veo（Google）的内容审核规则——它会拒绝生成涉及真实/知名人物的视频。\n\n"
            "建议这样处理：\n"
            "  1. 去掉提示词里的人名、明星、公众人物等指向具体真人的描述；\n"
            "  2. 换用非真人参考图，例如插画、AI 头像、卡通形象、商品图、场景图；\n"
            "  3. 如果用了真人照片做参考图，先做模糊/遮挡/转成明显的二次元插画风，或干脆只用文字提示词测试。"
        )
    # veo 其它常见安全过滤
    if "SAFETY" in upper or "CONTENT_FILTER" in upper or "POLICY" in upper:
        return (
            "视频生成被上游内容安全策略拦截"
            f"（错误码：{text}）。\n\n"
            "这是 veo 的内容审核规则，提示词或参考图触发了安全过滤。\n"
            "请调整提示词/参考图后重试，避免涉及真人、暴力、敏感或受限内容。"
        )
    return f"视频生成任务失败：{text}"

async def wait_for_video_task(client, provider, task_id, submit_url=""):
    base_url = video_api_root(provider)
    if not base_url:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider['id']} 未配置 Base URL")
    validate_safe_url(base_url, allow_private=False)
    task_urls = video_task_url_candidates(provider, base_url, task_id, submit_url)
    deadline = time.monotonic() + VIDEO_POLL_TIMEOUT
    delay = max(2.0, IMAGE_POLL_INTERVAL)
    last_payload = {}
    while time.monotonic() < deadline:
        await asyncio.sleep(delay)
        raw = None
        last_error = None
        for task_url in task_urls:
            try:
                validate_safe_url(task_url, allow_private=False)
                response = await client.get(task_url, headers=api_headers(provider=provider))
                response.raise_for_status()
                raw = response.json()
                break
            except Exception as exc:
                last_error = exc
                continue
        if raw is None:
            if last_error:
                raise last_error
            raise HTTPException(status_code=502, detail=f"视频任务查询失败：{task_id}")
        last_payload = raw
        task_data = (
            raw.get("data") if isinstance(raw.get("data"), dict)
            else raw.get("detail") if isinstance(raw.get("detail"), dict)
            else raw
        )
        status = str(task_data.get("status") or task_data.get("task_status") or raw.get("status") or raw.get("task_status") or "").upper()
        if status in VIDEO_TASK_SUCCESS_STATUSES:
            return raw
        # 部分上游（如玉玉API）status 字段非标准或为空，但已经返回了视频 URL ——
        # 只要不是明确的失败状态，且拿到了真实视频地址，就直接当成功处理。
        if status not in VIDEO_TASK_FAILURE_STATUSES and video_output_urls(raw):
            return raw
        if status in VIDEO_TASK_FAILURE_STATUSES:
            error = task_data.get("error") if isinstance(task_data.get("error"), dict) else {}
            reason = task_data.get("fail_reason") or task_data.get("message") or error.get("message") or raw.get("error") or raw.get("message") or str(raw)
            raise HTTPException(status_code=502, detail=humanize_video_task_failure(reason))
        delay = min(delay * 1.6, 12)
    raise HTTPException(status_code=504, detail=f"视频生成任务超时：{last_payload or task_id}")



# --- Section lines 10893-10904 ---
async def save_video_bytes_to_output(data, prefix="video_", ext=".mp4"):
    if not data:
        raise HTTPException(status_code=502, detail="上游视频下载为空")
    extension = ext if ext in {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv", ".flv"} else ".mp4"
    filename = f"{prefix}{uuid.uuid4().hex[:10]}{extension}"
    path = output_path_for(filename, "output")
    with open(path, "wb") as file:
        file.write(data)
    if os.path.getsize(path) <= 0:
        raise HTTPException(status_code=502, detail="上游视频下载为空")
    return output_url_for(filename, "output")

