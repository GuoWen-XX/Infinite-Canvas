"""Cloud AI Integrations Router for Infinite-Canvas.

Decoupled router providing endpoints and execution engines for:
- RunningHub (WebApps, Workflows, Assets, Status & Registry)
- 即梦 Jimeng (CLI, Login, QR, Credits, Image/Video Generation & Query)
- Codex CLI & GPT-Image-2 (Execution, Models, Health & Generation)
- Gemini CLI / Antigravity CLI (Execution, Models, Health & Generation)
- Volcengine Ark (Sign V4, Asset Groups & Avatar Task Management)
"""
import os
import re
import sys
import json
import time
import math
import uuid
import hmac
import base64
import hashlib
import asyncio
import logging
import datetime
import subprocess
import shutil
import tempfile
import mimetypes
import functools
import shlex
import glob
import random
import urllib
import urllib.parse
from io import BytesIO
from typing import Dict, Any, List, Optional, Tuple, Set, Union
from urllib.parse import urlparse, quote, unquote

import httpx
from PIL import Image, ImageOps
from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, File, Form, Depends
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
    ONLINE_IMAGE_REFERENCE_MAX,
    MAX_HISTORY_MESSAGES,
    VIDEO_POLL_TIMEOUT,
    AI_REQUEST_TIMEOUT,
    CODEX_DEFAULT_CHAT_MODELS,
    CODEX_DEFAULT_IMAGE_MODELS,
    CODEX_DEFAULT_TIMEOUT,
    GEMINI_CLI_DEFAULT_CHAT_MODELS,
    GEMINI_CLI_DEFAULT_IMAGE_MODELS,
    GEMINI_CLI_DEFAULT_TIMEOUT,
    JIMENG_DEFAULT_POLL_SECONDS,
    JIMENG_DEFAULT_IMAGE_MODELS,
    JIMENG_DEFAULT_VIDEO_MODELS,
    JIMENG_LEGACY_IMAGE_MODELS,
    JIMENG_LEGACY_VIDEO_MODELS,
    JIMENG_LOGIN_SESSION,
    RUNNINGHUB_DEFAULT_BASE_URL,
    RUNNINGHUB_DEFAULT_IMAGE_MODELS,
    RUNNINGHUB_DEFAULT_VIDEO_MODELS,
    RUNNINGHUB_FALLBACK_CHAT_MODELS,
    RUNNINGHUB_FILE_HOST_REWRITES,
    RUNNINGHUB_LLM_MODELS_URLS,
    RUNNINGHUB_MODEL_ENDPOINT_ALIASES,
    RUNNINGHUB_MODEL_REGISTRY_URL,
    RUNNINGHUB_OPENAPI_BASE_URL,
    RUNNINGHUB_THUMBNAIL_EXTS,
    RUNNINGHUB_WORKFLOW_LOCK,
    RUNNINGHUB_WORKFLOW_STORE_FILE,
    STATIC_RUNNINGHUB_MODEL_REGISTRY_FILE,
    VOLCENGINE_DEFAULT_BASE_URL,
    VOLCENGINE_DEFAULT_PROJECT_NAME,
    VOLCENGINE_DEFAULT_REGION,
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
    load_runninghub_workflow_store,
    save_runninghub_workflow_store,
    runninghub_collect_workflow_fields,
    runninghub_endpoint_url,
    runninghub_entry_id,
    runninghub_is_saved_link_field,
    runninghub_is_workflow_link_value,
    runninghub_normalize_field,
    runninghub_openapi_base_url,
    runninghub_openapi_url,
    runninghub_provider_workflow_config,
    runninghub_saved_hidden_workflow_ids,
    runninghub_select_workflow_config,
    runninghub_wallet_key_value,
    runninghub_workflow_store_key,
    sync_runninghub_workflow_to_provider,
    remove_runninghub_workflow_from_provider,
    volcengine_access_key_value,
    volcengine_secret_key_value,
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
from core.security import safe_download_bytes, validate_safe_url
from routers.models import (
    RunningHubSubmitRequest,
    RunningHubWorkflowSubmitRequest,
    RunningHubUploadAssetRequest,
    JimengHelpRequest,
    CodexHelpRequest,
    GeminiCliHelpRequest,
    JimengQueryMediaRequest,
    RunningHubWorkflowConfigField,
    RunningHubWorkflowConfig,
    CanvasVideoRequest,
)
from routers.common import (
    save_to_history,
    WsProxy,
    api_headers,
    is_volcengine_provider,
    is_runninghub_provider,
    is_jimeng_provider,
    is_codex_provider,
    is_gemini_cli_provider,
    is_yuli_provider,
    is_lingjing_provider,
    is_pollinations_provider,
    is_meigen_provider,
    meigen_env_key,
    _meigen_rpc,
    is_dashscope_provider,
    is_agnes_provider,
    avatar_platform_for_provider,
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
    save_video_bytes_to_output,
    parse_size_pair,
    snap_size_to_multiple,
    friendly_image_error_detail,
    parse_error_payload_text,
    friendly_chat_error_detail,
    _collect_video_url,
    video_output_urls,
    video_api_root,
    looks_like_html_response,
    video_submit_url_candidates,
    video_task_url_candidates,
    humanize_video_task_failure,
    CHAT_RATIO_SIZE_OPTIONS,
)
from routers.assets import (
    output_url_for,
    output_path_for,
)
from routers.providers import (
    classify_upstream_model,
    parse_upstream_models,
)

logger = logging.getLogger("infinite_canvas.integrations")
_server_logger = logging.getLogger("dx.server")

router = APIRouter(tags=["integrations"])

# Volcengine Ark constants
VOLCENGINE_ARK_ASSET_SERVICE = "cv"
VOLCENGINE_ARK_ASSET_REGION = "cn-beijing"
VOLCENGINE_ARK_ASSET_HOST = "open.volcengineapi.com"
VOLCENGINE_ARK_ASSET_VERSION = "2024-01-01"

# Codex constants
GPT_IMAGE2_MIN_PIXELS = 1024 * 1024

def apimart_avatar_asset_type(kind: str) -> str:
    k = (kind or "image").strip().lower()
    return "video" if k == "video" else "image"


# --- Sliced from online.py lines 1430-2357 ---
def codex_env_value(key):
    return os.getenv(key, "") or read_api_env_value(key)

def codex_cli_executable():
    configured = str(codex_env_value("CODEX_BIN") or "").strip()
    if configured:
        return configured
    return shutil.which("codex") or shutil.which("codex.exe") or shutil.which("codex.cmd") or ""

def codex_timeout(default=CODEX_DEFAULT_TIMEOUT):
    try:
        return max(30, min(3600, int(os.getenv("CODEX_CLI_TIMEOUT", str(default)) or default)))
    except Exception:
        return default

def codex_model_for_exec(model="", fallback=""):
    value = str(model or fallback or "").strip()
    low = value.lower()
    if not value or low.startswith("$imagegen") or low.startswith("gpt-image"):
        return ""
    return value

def codex_decode_output(stdout, stderr):
    out_text = (stdout or b"").decode("utf-8", errors="replace").strip()
    err_text = (stderr or b"").decode("utf-8", errors="replace").strip()
    return out_text, err_text

def cli_subprocess_env(extra_env=None):
    env = os.environ.copy()
    import core.providers as cp
    env_file = getattr(cp, "API_ENV_FILE", os.path.join(BASE_DIR, "API", ".env"))
    raw_empty_keys = set()
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8-sig") as f:
                for line in f.read().splitlines():
                    s = line.strip()
                    if s and not s.startswith("#") and "=" in s:
                        k, v = s.split("=", 1)
                        if not v.strip().strip("'\""):
                            raw_empty_keys.add(k.strip())
        except Exception:
            pass
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        val = read_api_env_value(key)
        if val:
            env[key] = val
        elif key in raw_empty_keys or key.upper() in raw_empty_keys:
            env.pop(key, None)
    if extra_env:
        env.update(extra_env)
    return env

async def run_codex_cli(prompt, model="", image_paths=None, timeout=None, output_last_message=True):
    exe = codex_cli_executable()
    if not exe:
        raise HTTPException(status_code=400, detail="未找到 OpenAI Codex CLI。请先运行 CLI/windows/openai/install_openai_codex_cli.bat，并完成 codex 登录。")
    image_paths = [str(path) for path in (image_paths or []) if path and os.path.isfile(str(path))]
    last_path = ""
    args = [
        exe,
        "exec",
        "--cd",
        BASE_DIR,
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
    ]
    exec_model = codex_model_for_exec(model)
    if exec_model:
        args.extend(["--model", exec_model])
    for path in image_paths:
        args.extend(["--image", path])
    if output_last_message:
        fd, last_path = tempfile.mkstemp(prefix="codex_last_", suffix=".txt", dir=OUTPUT_OUTPUT_DIR)
        os.close(fd)
        args.extend(["--output-last-message", last_path])
    args.append("-")
    prompt_bytes = str(prompt or "").encode("utf-8")
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=BASE_DIR,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=cli_subprocess_env(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=prompt_bytes), timeout=timeout or codex_timeout())
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="OpenAI Codex CLI 执行超时。可设置 CODEX_CLI_TIMEOUT 增大等待时间。") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"未找到 OpenAI Codex CLI：{exe}") from exc
    out_text, err_text = codex_decode_output(stdout, stderr)
    last_text = ""
    if last_path and os.path.exists(last_path):
        try:
            with open(last_path, "r", encoding="utf-8-sig") as f:
                last_text = f.read().strip()
        except Exception:
            last_text = ""
        try:
            os.remove(last_path)
        except Exception:
            pass
    if proc.returncode != 0:
        message = err_text or out_text or last_text or f"exit={proc.returncode}"
        raise HTTPException(status_code=502, detail=f"OpenAI Codex CLI 调用失败：{message[:1200]}")
    return {"text": last_text or out_text, "_stdout": out_text, "_stderr": err_text}

def codex_output_image_files(since_time=0):
    exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    root = os.path.abspath(OUTPUT_OUTPUT_DIR)
    files = []
    try:
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in exts:
                continue
            mtime = os.path.getmtime(path)
            if mtime + 1 < float(since_time or 0):
                continue
            files.append((mtime, path))
    except Exception:
        return []
    return [path for _mtime, path in sorted(files, reverse=True)]

def codex_output_url_from_path(path):
    path = os.path.abspath(str(path or ""))
    root = os.path.abspath(OUTPUT_OUTPUT_DIR)
    try:
        if os.path.commonpath([root, path]) == root:
            return output_url_for(os.path.basename(path), "output")
    except Exception:
        return ""
    return ""

def gpt_image_2_skill_executable():
    configured = str(codex_env_value("GPT_IMAGE_2_SKILL_BIN") or "").strip()
    if configured:
        return configured
    return (
        shutil.which("gpt-image-2-skill")
        or shutil.which("gpt-image-2-skill.exe")
        or shutil.which("gpt-image-2-skill.cmd")
        or ""
    )

def gpt_image_2_skill_auth_file():
    configured = str(codex_env_value("GPT_IMAGE_2_SKILL_AUTH_FILE") or codex_env_value("CODEX_AUTH_FILE") or "").strip()
    if configured:
        return configured
    project_auth = os.path.join(BASE_DIR, "API", "openai-gpt-account-auth.json")
    user_profile = os.getenv("USERPROFILE", "").strip()
    candidates = [
        project_auth,
        os.path.join(user_profile, ".codex", "auth.json") if user_profile else "",
        os.path.join(os.path.expanduser("~"), ".codex", "auth.json"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return candidates[0] if candidates and candidates[0] else ""

def gpt_image_2_skill_auth_json(auth_file=""):
    path = str(auth_file or "").strip()
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def gpt_image_2_skill_access_token(auth_data):
    if not isinstance(auth_data, dict):
        return ""
    for key in ("access_token", "accessToken"):
        value = str(auth_data.get(key) or "").strip()
        if value:
            return value
    tokens = auth_data.get("tokens")
    if isinstance(tokens, dict):
        for key in ("access_token", "accessToken"):
            value = str(tokens.get(key) or "").strip()
            if value:
                return value
    return ""

def gpt_image_2_skill_api_key(auth_data=None):
    for key in ("GPT_IMAGE_2_SKILL_API_KEY", "OPENAI_API_KEY"):
        value = str(codex_env_value(key) or "").strip()
        if value:
            return value
    if isinstance(auth_data, dict):
        value = str(auth_data.get("OPENAI_API_KEY") or auth_data.get("api_key") or auth_data.get("apiKey") or "").strip()
        if value:
            return value
    user_profile = os.getenv("USERPROFILE", "").strip()
    user_auth = os.path.join(user_profile, ".codex", "auth.json") if user_profile else ""
    if user_auth:
        user_data = gpt_image_2_skill_auth_json(user_auth)
        value = str(user_data.get("OPENAI_API_KEY") or user_data.get("api_key") or user_data.get("apiKey") or "").strip()
        if value:
            return value
    return ""

def gpt_image_2_skill_provider_args(auth_file=""):
    auth_data = gpt_image_2_skill_auth_json(auth_file)
    if gpt_image_2_skill_access_token(auth_data):
        return ["--provider", "codex", "--auth-file", auth_file] if auth_file else ["--provider", "codex"], "codex"
    api_key = gpt_image_2_skill_api_key(auth_data)
    if api_key:
        return ["--provider", "openai", "--api-key", api_key], "openai"
    return (["--provider", "codex", "--auth-file", auth_file] if auth_file else ["--provider", "codex"]), "codex"

def gpt_image_2_skill_model_arg(model="", provider="openai"):
    value = str(model or "").strip()
    low = value.lower()
    provider = str(provider or "").strip().lower()
    if provider == "codex":
        if not value or low.startswith("$imagegen") or low.startswith("gpt-image"):
            return "gpt-5.4"
        return value
    if not value or low.startswith("$imagegen"):
        return "gpt-image-2"
    return value

def codex_wxh_size(width, height):
    # Codex backend rejects preset names other than 2K/4K for small sizes (invalid value 1K).

    width = int(width or 0)
    height = int(height or 0)
    if width <= 0 or height <= 0:
        return "1024x1024"
    total = width * height
    if total < GPT_IMAGE2_MIN_PIXELS:
        scale = (GPT_IMAGE2_MIN_PIXELS / float(total)) ** 0.5
        width = max(64, int(width * scale) // 16 * 16)
        height = max(64, int(height * scale) // 16 * 16)
        # 16 对齐取整后可能仍略低于下限（如 736x880 = 647680 < 655360），把长边补足。
        while width * height < GPT_IMAGE2_MIN_PIXELS:
            if width >= height:
                width += 16
            else:
                height += 16
    return f"{width}x{height}"

def gpt_image_2_skill_size_arg(size="", model="", prompt="", provider="openai"):
    text = " ".join([str(size or ""), str(model or ""), str(prompt or "")]).lower()
    size_text = str(size or "").strip()
    if str(provider or "").strip().lower() == "codex":
        if "1k" in text or "1024" in text:
            return "1024x1024"
        if "2k" in text or "2048" in text:
            return "2K"
        if "4k" in text or "3840" in text:
            return "4K"
        width, height = parse_size_pair(size_text)
        if 0 < max(width, height) < 1800:
            return codex_wxh_size(width, height)
        if 1800 <= max(width, height) < 3000:
            return "2K"
        return "4K"
    match = re.search(r"(\d{3,5})\s*[x×*]\s*(\d{3,5})", size_text, flags=re.I)
    if match:
        width = int(match.group(1))
        height = int(match.group(2))
        if width > 0 and height > 0:
            from routers.online_image import normalize_gpt_image_2_size
            return normalize_gpt_image_2_size(f"{width}x{height}")
    ratio_match = re.fullmatch(r"\s*(\d{1,2})\s*:\s*(\d{1,2})\s*", size_text)
    if ratio_match:
        ratio = f"{int(ratio_match.group(1))}:{int(ratio_match.group(2))}"
        options = CHAT_RATIO_SIZE_OPTIONS.get(ratio)
        if options:
            if "4k" in text or "3840" in text:
                return options[-1]
            if "1k" in text or "1024" in text:
                return options[0]
            return options[1] if len(options) > 1 else options[0]
    if "4k" in text or "3840" in text:
        return "4K"
    if "1k" in text or "1024" in text:
        return "1K"
    return "2K"

def gpt_image_2_skill_prompt_arg(prompt="", size="", provider="openai"):
    prompt_text = str(prompt or "").strip()
    if str(provider or "").strip().lower() != "codex":
        return prompt_text
    size_arg = gpt_image_2_skill_size_arg(size, "", prompt, provider)
    size_text = str(size or "").strip()
    width, height = parse_size_pair(size_text)
    ratio_text = ""
    if width and height:
        divisor = math.gcd(width, height) or 1
        ratio_text = f"{width // divisor}:{height // divisor}"
    else:
        ratio_match = re.fullmatch(r"\s*(\d{1,2})\s*:\s*(\d{1,2})\s*", size_text)
        if ratio_match:
            width = int(ratio_match.group(1))
            height = int(ratio_match.group(2))
            ratio_text = f"{width}:{height}"
    if not ratio_text:
        return f"{prompt_text} 画质要求：目标输出 {size_arg} 高分辨率图片。 Image quality requirement: output a {size_arg} high-resolution image."
    orientation_zh = "横版/宽幅" if width > height else ("竖版/长幅" if height > width else "正方形")
    orientation_en = "landscape/wide" if width > height else ("portrait/tall" if height > width else "square")
    return (
        f"{prompt_text} "
        f"画质要求：目标输出 {size_arg} 高分辨率图片。"
        f"画幅要求：必须生成 {orientation_zh} 图片，宽高比 {ratio_text}。"
        f"请不要交换宽高，不要输出反向比例。"
        f" Image quality requirement: output a {size_arg} high-resolution image."
        f" Canvas requirement: generate a {orientation_en} image with aspect ratio {ratio_text}; "
        "do not swap width and height."
    )

def parse_gpt_image_2_skill_output(stdout_text="", stderr_text=""):
    items = []
    for line in (stdout_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except Exception:
            continue
    if not items and stdout_text:
        try:
            parsed = json.loads(stdout_text)
            items = parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            pass
    paths = []
    for item in items:
        if not isinstance(item, dict):
            continue
        candidates = [
            item.get("path"),
            item.get("file"),
            item.get("output"),
            item.get("out"),
            item.get("url"),
        ]
        for image in item.get("images") or []:
            if isinstance(image, dict):
                candidates.extend([image.get("path"), image.get("file"), image.get("url")])
            else:
                candidates.append(image)
        for candidate in candidates:
            value = str(candidate or "").strip()
            if value:
                paths.append(value)
    text = stdout_text or stderr_text or ""
    pattern = r"([A-Za-z]:\\[^\r\n\"'<>]+\.(?:png|jpe?g|webp|gif)|/[^\r\n\"'<>]+\.(?:png|jpe?g|webp|gif))"
    paths.extend(re.findall(pattern, text, flags=re.I))
    return items, paths

def gpt_image_2_skill_failure_message(stdout_text="", stderr_text="", returncode=0):
    combined = "\n".join([str(stdout_text or "").strip(), str(stderr_text or "").strip()]).strip()
    if not combined:
        return f"exit={returncode}"
    objects = []
    plain_lines = []
    for line in combined.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            objects.append(json.loads(line))
        except Exception:
            plain_lines.append(line)
    if not objects:
        try:
            parsed = json.loads(combined)
            objects = parsed if isinstance(parsed, list) else [parsed]
            plain_lines = []
        except Exception:
            pass
    messages = []
    progress = []
    for item in objects:
        if not isinstance(item, dict):
            continue
        error = item.get("error")
        if isinstance(error, dict):
            msg = error.get("message") or error.get("detail") or error.get("code")
            if msg:
                messages.append(str(msg))
        elif isinstance(error, str) and error.strip():
            messages.append(error.strip())
        if item.get("ok") is False:
            msg = item.get("message") or item.get("detail")
            if msg:
                messages.append(str(msg))
        data = item.get("data")
        if isinstance(data, dict):
            msg = data.get("error") or data.get("message") or data.get("status")
            event_type = str(item.get("type") or data.get("phase") or "").strip()
            if msg and event_type not in {"request.started", "request_started"}:
                progress.append(f"{event_type}: {msg}" if event_type else str(msg))
    if messages:
        return "；".join(dict.fromkeys(messages))[:1600]
    if plain_lines:
        return "\n".join(plain_lines)[:1600]
    if progress:
        return ("只收到了进度事件，没有收到最终错误详情：" + "；".join(dict.fromkeys(progress)))[:1600]
    return combined[:1600]

def codex_postprocess_image_to_requested_size(path="", requested_size="", provider=""):
    provider_text = str(provider or "").strip().lower()
    if provider_text not in {"codex", "gemini-cli"}:
        return ""
    width, height = parse_size_pair(requested_size)
    if not width or not height or not path or not os.path.isfile(path):
        return ""
    try:
        with Image.open(path) as img:
            img.load()
            if img.width == width and img.height == height:
                return ""
            resample = getattr(Image, "Resampling", Image).LANCZOS
            oriented = ImageOps.exif_transpose(img)
            converted = oriented.convert("RGBA") if oriented.mode in ("RGBA", "LA", "P") else oriented.convert("RGB")
            resized = ImageOps.fit(converted, (width, height), method=resample, centering=(0.5, 0.5))
            base, _ext = os.path.splitext(path)
            upscaled_path = f"{base}_upscaled_{width}x{height}.png"
            resized.save(upscaled_path, format="PNG")
            return upscaled_path
    except Exception as exc:
        label = "Gemini CLI" if provider_text == "gemini-cli" else "Codex GPT Image 2"
        print(f"{label} 图片尺寸后处理失败：{exc}")
        return ""

async def generate_codex_provider_image_via_gpt_image_2_skill(prompt, size, model, ref_paths=None):
    exe = gpt_image_2_skill_executable()
    if not exe:
        return None
    ref_paths = [str(path) for path in (ref_paths or []) if path and os.path.isfile(str(path))]
    auth_file = gpt_image_2_skill_auth_file()
    auth_data = gpt_image_2_skill_auth_json(auth_file)
    provider_args, tool_provider = gpt_image_2_skill_provider_args(auth_file)
    attempts = [(provider_args, tool_provider)]
    fallback_api_key = gpt_image_2_skill_api_key(auth_data)
    if tool_provider == "codex" and fallback_api_key:
        attempts.append((["--provider", "openai", "--api-key", fallback_api_key], "openai"))
    last_message = ""
    for attempt_index, (attempt_provider_args, attempt_provider) in enumerate(attempts):
        out_path = os.path.join(OUTPUT_OUTPUT_DIR, f"gpt_image_2_{uuid.uuid4().hex}.png")
        mode = "edit" if ref_paths else "generate"
        args = [
            exe,
            "--json",
        ]
        args.extend(attempt_provider_args)
        args.extend([
            "images",
            mode,
            "--prompt",
            gpt_image_2_skill_prompt_arg(prompt, size, attempt_provider),
            "--out",
            out_path,
            "--model",
            gpt_image_2_skill_model_arg(model, attempt_provider),
            "--format",
            "png",
            "--size",
            gpt_image_2_skill_size_arg(size, model, prompt, attempt_provider),
            "--quality",
            "high",
        ])
        for path in ref_paths:
            args.extend(["--ref-image", path])
        if ref_paths and attempt_provider == "openai":
            args.extend(["--input-fidelity", "high"])
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=BASE_DIR,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=cli_subprocess_env(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=codex_timeout())
        except asyncio.TimeoutError as exc:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            raise HTTPException(status_code=504, detail="GPT Image 2 Skill 执行超时。可设置 CODEX_CLI_TIMEOUT 增大等待时间。") from exc
        except FileNotFoundError:
            return None
        out_text, err_text = codex_decode_output(stdout, stderr)
        if proc.returncode != 0:
            message = gpt_image_2_skill_failure_message(out_text, err_text, proc.returncode)
            last_message = f"{attempt_provider}: {message}"
            auth_failed = bool(re.search(r"\b401\b|unauthori[sz]ed|access[_ -]?token|api[_ -]?key", message, re.I))
            if attempt_provider == "codex" and attempt_index + 1 < len(attempts) and auth_failed:
                continue
            if auth_failed:
                return None
            raise HTTPException(status_code=502, detail=f"GPT Image 2 Skill 调用失败：{last_message[:1200]}")
        parsed, reported_paths = parse_gpt_image_2_skill_output(out_text, err_text)
        candidate_paths = []
        if os.path.isfile(out_path):
            candidate_paths.append(out_path)
        candidate_paths.extend([path for path in reported_paths if path and os.path.isfile(path)])
        urls = []
        for path in candidate_paths:
            processed_path = codex_postprocess_image_to_requested_size(path, size, attempt_provider)
            url = codex_output_url_from_path(processed_path or path)
            if url:
                urls.append(url)
        if not urls:
            status_text = (out_text or err_text or "")[:1200]
            raise HTTPException(status_code=502, detail=f"GPT Image 2 Skill 已返回，但没有在输出目录发现图片：{status_text}")
        return {"type": "url", "value": urls[0]}, {
            "images": urls,
            "text": out_text,
            "provider": "codex",
            "tool": "gpt-image-2-skill",
            "tool_provider": attempt_provider,
            "raw": parsed or {"stdout": out_text, "stderr": err_text},
        }
    raise HTTPException(status_code=502, detail=f"GPT Image 2 Skill 调用失败：{last_message[:1200]}")

def _is_confined_local_media_path(path: str) -> bool:
    if not path:
        return False
    try:
        real = os.path.realpath(path)
        for root in (ASSETS_DIR, OUTPUT_DIR, LOCAL_UPLOAD_DIR):
            if not root:
                continue
            real_root = os.path.realpath(root)
            if real == real_root or real.startswith(real_root + os.sep):
                return os.path.isfile(real)
    except Exception:
        return False
    return False

async def codex_prepare_local_media(ref_url):
    text = str(ref_url or "").strip()
    if not text:
        return "", []
    if text.startswith(("/output/", "/assets/")):
        path = output_file_from_url(text)
        if path:
            return path, []
        raise HTTPException(status_code=404, detail=f"OpenAI CLI 参考素材不存在：{text}")
    if text.startswith("file://"):
        path = urllib.parse.unquote(urllib.parse.urlparse(text).path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        if _is_confined_local_media_path(path):
            return path, []
    if _is_confined_local_media_path(text):
        return text, []
    temp_paths = []
    suffix = ".png"
    if text.startswith("data:"):
        if ";base64," not in text:
            raise HTTPException(status_code=400, detail="OpenAI CLI 参考素材 data URL 缺少 base64 数据")
        header, encoded = text.split(";base64,", 1)
        mime = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else ""
        suffix = mimetypes.guess_extension(mime) or suffix
        fd, path = tempfile.mkstemp(prefix="codex_ref_", suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64decode(encoded))
        temp_paths.append(path)
        return path, temp_paths
    if text.startswith(("http://", "https://")):
        try:
            content, content_type = await safe_download_bytes(text, timeout=60.0, max_bytes=50 * 1024 * 1024)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"OpenAI CLI 下载参考素材失败: {e}")
        clean_path = urllib.parse.urlparse(text).path
        suffix = os.path.splitext(clean_path)[1] or mimetypes.guess_extension(content_type) or suffix
        fd, path = tempfile.mkstemp(prefix="codex_ref_", suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        temp_paths.append(path)
        return path, temp_paths
    raise HTTPException(status_code=400, detail=f"OpenAI CLI 无法读取参考素材：{text[:120]}")

async def codex_reference_paths(reference_images=None):
    paths = []
    temp_paths = []
    try:
        for ref in (reference_images or [])[:ONLINE_IMAGE_REFERENCE_MAX]:
            url = ref.get("url") if isinstance(ref, dict) else getattr(ref, "url", "")
            if not url:
                continue
            path, created = await codex_prepare_local_media(url)
            if path:
                paths.append(path)
            temp_paths.extend(created)
        return paths, temp_paths
    except Exception:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass
        raise

def codex_models_payload(raw=None):
    all_models = [*CODEX_DEFAULT_IMAGE_MODELS, *CODEX_DEFAULT_CHAT_MODELS]
    return {
        "ok": True,
        "protocol": "codex",
        "status": 200,
        "message": "OpenAI Codex CLI 可用，模型列表来自本机 CLI 默认配置。",
        "model_count": len(all_models),
        "total": len(all_models),
        "image_models": CODEX_DEFAULT_IMAGE_MODELS,
        "chat_models": CODEX_DEFAULT_CHAT_MODELS,
        "video_models": [],
        "all": all_models,
        "raw": raw or {},
    }

async def generate_codex_provider_image(prompt, size, model, reference_images=None, provider=None):
    ref_paths, temp_paths = await codex_reference_paths(reference_images)
    try:
        skill_result = await generate_codex_provider_image_via_gpt_image_2_skill(prompt, size, model, ref_paths)
        if skill_result:
            return skill_result
        raise HTTPException(status_code=400, detail="未找到 GPT Image 2 helper，OpenAI CLI 生图已禁用 $imagegen 回退。请先安装 gpt-image-2-skill 后再生成图片。")
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass

def codex_chat_prompt(payload, history_messages=None):
    parts = []
    system_prompt = str(getattr(payload, "system_prompt", "") or "").strip()
    if system_prompt:
        parts.append(f"系统要求：\n{system_prompt}")
    for item in (history_messages or [])[-MAX_HISTORY_MESSAGES:]:
        role = str(item.get("role") or "").strip()
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            label = "用户" if role == "user" else "助手"
            parts.append(f"{label}：\n{content}")
    message = str(getattr(payload, "message", "") or "").strip()
    parts.append(f"用户：\n{message}")
    parts.append("请直接回答用户，输出纯文本，不要修改项目文件。")
    return "\n\n".join(part for part in parts if part).strip()

async def codex_chat_text(payload, history_messages=None):
    image_paths = []
    temp_paths = []
    try:
        image_values = []
        if hasattr(payload, "images"):
            image_values.extend([{"url": item} for item in (getattr(payload, "images", None) or []) if item])
        if hasattr(payload, "reference_images"):
            image_values.extend([dump_pydantic(ref) for ref in (getattr(payload, "reference_images", None) or []) if getattr(ref, "url", "")])
        image_paths, temp_paths = await codex_reference_paths(image_values)
        raw = await run_codex_cli(
            codex_chat_prompt(payload, history_messages),
            model=getattr(payload, "model", "") or CODEX_DEFAULT_CHAT_MODELS[0],
            image_paths=image_paths,
            timeout=codex_timeout(),
            output_last_message=True,
        )
        text = str(raw.get("text") or "").strip()
        return text or "Codex CLI 返回了空回复。", raw
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass

def gemini_cli_env_value(key):
    return os.getenv(key, "") or read_api_env_value(key)

def antigravity_cli_winget_candidates():
    patterns = [
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Microsoft", "WinGet", "Packages", "Google.AntigravityCLI_*", "agy.exe"),
        os.path.join(os.getenv("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages", "Google.AntigravityCLI_*", "agy.exe"),
    ]
    candidates = []
    for pattern in patterns:
        if not pattern:
            continue
        candidates.extend(glob.glob(pattern))
    return sorted(dict.fromkeys(path for path in candidates if os.path.exists(path)), reverse=True)

def gemini_cli_executable():
    for key in ("ANTIGRAVITY_BIN", "AGY_BIN", "GEMINI_BIN"):
        configured = str(gemini_cli_env_value(key) or "").strip().strip('"')
        if configured:
            return configured
    for name in ("agy", "agy.exe"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in antigravity_cli_winget_candidates():
        return candidate
    return shutil.which("gemini") or shutil.which("gemini.exe") or shutil.which("gemini.cmd") or ""

def is_antigravity_cli(exe):
    text = str(exe or "").lower()
    return os.path.basename(text).startswith("agy") or "antigravity" in text

def gemini_cli_display_name(exe=None):
    return "Antigravity CLI" if is_antigravity_cli(exe or gemini_cli_executable()) else "Gemini CLI"

def gemini_cli_timeout(default=GEMINI_CLI_DEFAULT_TIMEOUT):
    try:
        return max(30, min(3600, int(os.getenv("GEMINI_CLI_TIMEOUT", str(default)) or default)))
    except Exception:
        return default

def gemini_cli_image_timeout():
    raw = os.getenv("ANTIGRAVITY_IMAGE_TIMEOUT") or os.getenv("GEMINI_CLI_IMAGE_TIMEOUT") or "300"
    try:
        return max(60, min(1800, int(raw)))
    except Exception:
        return 300

def gemini_cli_model(model="", fallback=""):
    value = str(model or fallback or "").strip()
    return value or "auto"

def gemini_cli_text_from_raw(raw, fallback_text=""):
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        for key in ("response", "text", "content", "message", "output"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        candidates = []
        for value in raw.values():
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        text = gemini_cli_text_from_raw(item)
                        if text:
                            candidates.append(text)
                    elif isinstance(item, str) and item.strip():
                        candidates.append(item.strip())
        if candidates:
            return "\n".join(candidates).strip()
    if isinstance(raw, list):
        parts = [gemini_cli_text_from_raw(item) for item in raw]
        return "\n".join(part for part in parts if part).strip()
    return str(fallback_text or "").strip()

def gemini_cli_parse_stdout(out_text):
    text = str(out_text or "").strip()
    if not text:
        return {}, ""
    try:
        raw = json.loads(text)
        return raw, gemini_cli_text_from_raw(raw, text)
    except Exception:
        pass
    parsed = jimeng_extract_json(text)
    if isinstance(parsed, (dict, list)) and parsed != {"text": text}:
        return parsed, gemini_cli_text_from_raw(parsed, text)
    return {"text": text}, text

async def run_gemini_cli(prompt, model="", timeout=None, allow_tools=False):
    exe = gemini_cli_executable()
    if not exe:
        raise HTTPException(status_code=400, detail="未找到 Antigravity CLI。请先安装 Google Antigravity CLI，并完成 agy 登录。")
    timeout_seconds = timeout or gemini_cli_timeout()
    if is_antigravity_cli(exe):
        args = [exe, "--print-timeout", f"{int(timeout_seconds)}s"]
        selected = gemini_cli_model(model)
        if selected and selected != "auto":
            args.extend(["--model", selected])
        if allow_tools:
            args.append("--dangerously-skip-permissions")
        args.extend(["-p", str(prompt or "")])
    else:
        args = [
            exe,
            "--model",
            gemini_cli_model(model),
            "--output-format",
            "json",
            "--skip-trust",
        ]
        args.extend(["--prompt", str(prompt or "")])
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=cli_subprocess_env(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        raise HTTPException(status_code=504, detail=f"{gemini_cli_display_name(exe)} 执行超时。可设置 GEMINI_CLI_TIMEOUT 增大等待时间。") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"未找到 {gemini_cli_display_name(exe)}：{exe}") from exc
    out_text, err_text = codex_decode_output(stdout, stderr)
    raw, text = gemini_cli_parse_stdout(out_text)
    if proc.returncode != 0:
        message = err_text or out_text or f"exit={proc.returncode}"
        raise HTTPException(status_code=502, detail=f"{gemini_cli_display_name(exe)} 调用失败：{message[:1200]}")
    return {"text": text or out_text, "raw": raw, "_stdout": out_text, "_stderr": err_text}

def gemini_cli_models_payload(raw=None):
    all_models = [*GEMINI_CLI_DEFAULT_IMAGE_MODELS, *GEMINI_CLI_DEFAULT_CHAT_MODELS]
    all_models = model_list_from_values(all_models)
    return {
        "ok": True,
        "protocol": "gemini-cli",
        "status": 200,
        "message": "Antigravity CLI 可用，模型列表使用 auto 默认模型。",
        "model_count": len(all_models),
        "total": len(all_models),
        "image_models": GEMINI_CLI_DEFAULT_IMAGE_MODELS,
        "chat_models": GEMINI_CLI_DEFAULT_CHAT_MODELS,
        "video_models": [],
        "all": all_models,
        "raw": raw or {},
    }

def gemini_cli_reference_note(reference_images=None):
    refs = []
    temp_paths = []
    for ref in (reference_images or [])[:ONLINE_IMAGE_REFERENCE_MAX]:
        url = ref.get("url") if isinstance(ref, dict) else getattr(ref, "url", "")
        if not url:
            continue
        refs.append(url)
    return refs, temp_paths

async def gemini_cli_reference_paths(reference_images=None):
    return await codex_reference_paths(reference_images)

def gemini_cli_image_size_instruction(size="", model=""):
    size_text = str(size or "").strip()
    model_text = str(model or "").strip()
    match = re.match(r"^\s*(\d{2,5})\s*[xX*]\s*(\d{2,5})\s*$", size_text)
    if match:
        width, height = int(match.group(1)), int(match.group(2))
        if width > 0 and height > 0:
            orientation = "正方形" if width == height else ("横版" if width > height else "竖版")
            return (
                f"目标输出分辨率：{width}x{height} 像素（宽 x 高），画面方向：{orientation}。"
                f"最终保存到输出目录的图片文件实际像素必须是 {width}x{height}。"
                "如果生成器先得到较小图片，请在保存前放大或导出到目标尺寸，不要返回 1024px 小图。"
            )
    combined = f"{size_text} {model_text}".lower()
    if "4k" in combined:
        return "目标输出为 4K 高分辨率图片；最终保存文件需要达到当前画幅对应的 4K 像素尺寸，不要默认输出 1024px 小图。"
    if "2k" in combined:
        return "目标输出为 2K 高分辨率图片；最终保存文件需要达到当前画幅对应的 2K 像素尺寸，不要默认输出 1024px 小图。"
    return f"尺寸/比例参考：{size_text or 'auto'}。如果可以指定分辨率，请优先输出高分辨率图片。"

async def generate_gemini_cli_provider_image(prompt, size, model, reference_images=None, provider=None):
    ref_paths, temp_paths = await gemini_cli_reference_paths(reference_images)
    since = time.time()
    try:
        ref_text = ""
        if ref_paths:
            ref_text = "\n参考图片本地路径：\n" + "\n".join(ref_paths)
        size_context = f"{model or ''} {prompt or ''}"
        image_prompt = (
            f"你正在为 Infinite Canvas 生成图片。\n"
            f"任务：{prompt}\n\n"
            f"{gemini_cli_image_size_instruction(size, size_context)}\n"
            f"{ref_text}\n\n"
            f"如果当前 Antigravity CLI/模型支持图片生成或图片编辑，请把最终图片保存到这个本地目录：{OUTPUT_OUTPUT_DIR}\n"
            "文件格式优先 png 或 jpg。只输出最终文件路径和一句简短说明；不要修改项目代码，不要创建额外文档。\n"
            "如果你无法真正创建图片文件，请在 60 秒内直接回复“无法生成图片文件”，不要只写计划，也不要持续尝试。"
        )
        try:
            raw = await run_gemini_cli(
                image_prompt,
                model=model or GEMINI_CLI_DEFAULT_IMAGE_MODELS[0],
                timeout=gemini_cli_image_timeout() if is_antigravity_cli(gemini_cli_executable()) else gemini_cli_timeout(),
                allow_tools=True,
            )
        except Exception as cli_exc:
            files = codex_output_image_files(since)
            if files:
                raw = {"text": "Disk fallback detected image on error", "raw": str(cli_exc)}
            else:
                raise
        files = codex_output_image_files(since)
        urls = []
        for path in files:
            processed_path = codex_postprocess_image_to_requested_size(path, size, "gemini-cli")
            url = codex_output_url_from_path(processed_path or path)
            if url and url not in urls:
                urls.append(url)
        if not urls:
            text = f"{raw.get('text') or raw.get('_stdout') or ''}\n{raw.get('_stderr') or ''}"
            pattern = r"([A-Za-z]:\\[^\r\n\"'<>]+\.(?:png|jpe?g|webp|gif)|/[^\r\n\"'<>]+\.(?:png|jpe?g|webp|gif))"
            for match in re.findall(pattern, text, flags=re.I):
                match_path = match.strip()
                processed_path = codex_postprocess_image_to_requested_size(match_path, size, "gemini-cli")
                url = codex_output_url_from_path(processed_path or match_path)
                if url and url not in urls:
                    urls.append(url)
        if not urls:
            status_text = (raw.get("text") or raw.get("_stdout") or raw.get("_stderr") or "")[:1200]
            raise HTTPException(status_code=502, detail=f"{gemini_cli_display_name()} 已返回，但没有在输出目录发现图片：{status_text}")
        return {"type": "url", "value": urls[0]}, {"images": urls, "text": raw.get("text"), "provider": "gemini-cli", "raw": raw.get("raw")}
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass

def gemini_cli_chat_prompt(payload, history_messages=None):
    parts = []
    system_prompt = str(getattr(payload, "system_prompt", "") or "").strip()
    if system_prompt:
        parts.append(f"系统要求：\n{system_prompt}")
    for item in (history_messages or [])[-MAX_HISTORY_MESSAGES:]:
        role = str(item.get("role") or "").strip()
        content = item.get("content")
        if role in {"user", "assistant"} and content:
            label = "用户" if role == "user" else "助手"
            parts.append(f"{label}：\n{content}")
    message = str(getattr(payload, "message", "") or "").strip()
    parts.append(f"用户：\n{message}")
    image_values = []
    if hasattr(payload, "images"):
        image_values.extend([{"url": item} for item in (getattr(payload, "images", None) or []) if item])
    if hasattr(payload, "reference_images"):
        image_values.extend([dump_pydantic(ref) for ref in (getattr(payload, "reference_images", None) or []) if getattr(ref, "url", "")])
    refs = []
    temp_paths = []
    return "\n\n".join(part for part in parts if part).strip(), image_values

async def gemini_cli_chat_text(payload, history_messages=None):
    temp_paths = []
    try:
        prompt, image_values = gemini_cli_chat_prompt(payload, history_messages)
        image_paths, temp_paths = await gemini_cli_reference_paths(image_values)
        if image_paths:
            prompt = f"{prompt}\n\n可参考的本地图片路径：\n" + "\n".join(image_paths)
        prompt = f"{prompt}\n\n请直接回答用户，输出纯文本，不要修改项目文件。"
        raw = await run_gemini_cli(
            prompt,
            model=getattr(payload, "model", "") or GEMINI_CLI_DEFAULT_CHAT_MODELS[0],
            timeout=gemini_cli_timeout(),
            allow_tools=False,
        )
        text = str(raw.get("text") or "").strip()
        return text or f"{gemini_cli_display_name()} 返回了空回复。", raw
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass



# --- Sliced from online.py lines 2472-3420 ---
def jimeng_env_value(key):
    return os.getenv(key, "") or read_api_env_value(key)

def jimeng_use_wsl():
    value = str(jimeng_env_value("JIMENG_USE_WSL") or "").strip().lower()
    return value in {"1", "true", "yes", "on", "wsl"}

def jimeng_cli_executable():
    if jimeng_use_wsl():
        return shutil.which("wsl.exe") or shutil.which("wsl") or "wsl.exe"
    configured = str(
        jimeng_env_value("JIMENG_BIN")
        or jimeng_env_value("DREAMINA_BIN")
        or ""
    ).strip()
    if configured:
        return configured
    return shutil.which("dreamina") or shutil.which("dreamina.exe") or shutil.which("dreamina.cmd") or ""

def decode_utf16_auto(raw: bytes) -> str:
    # WSL/Windows interop emits UTF-16 for null-heavy diagnostics, but the
    # endianness varies by source (console vs proxy vs subprocess), so a
    # hard-coded "utf-16le" silently byte-swaps UTF-16BE text into garbage
    # (e.g. "localhost" -> 氀漀挀愀氀栀漀猀琀). Decode both ways and keep
    # whichever produces more plain ASCII, since diagnostics are ASCII-heavy.
    try:
        le = raw.decode("utf-16le", errors="ignore")
    except Exception:
        le = ""
    try:
        be = raw.decode("utf-16be", errors="ignore")
    except Exception:
        be = ""
    def ascii_score(text):
        return sum(1 for ch in text if 0x20 <= ord(ch) <= 0x7e)
    return le if ascii_score(le) >= ascii_score(be) else be

def decode_wsl_output(data: bytes) -> str:
    data = data or b""
    if not data:
        return ""

    # WSL can mix UTF-16 diagnostics with UTF-8 command output in the same
    # stream. Decode per line so a WSL proxy warning does not corrupt CLI errors.
    if b"\x00" in data[:400]:
        lines = []
        for raw_line in data.splitlines():
            if not raw_line:
                lines.append("")
                continue
            sample = raw_line[:200]
            nul_ratio = sample.count(0) / max(1, len(sample))
            if nul_ratio > 0.2:
                try:
                    lines.append(decode_utf16_auto(raw_line))
                    continue
                except Exception:
                    pass
            lines.append(raw_line.decode("utf-8-sig", errors="ignore"))
        return "\n".join(lines)
    if b"\x00" in data[:200]:
        try:
            return decode_utf16_auto(data)
        except Exception:
            pass
    return data.decode("utf-8-sig", errors="ignore")

def jimeng_wsl_base_args(exe="wsl.exe"):
    configured = str(jimeng_env_value("JIMENG_WSL_DISTRO") or "").strip()
    names = []
    try:
        proc = subprocess.run(
            [exe, "-l", "-q"],
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        names = [
            line.replace("\x00", "").strip().lstrip("*").strip()
            for line in decode_wsl_output(proc.stdout).splitlines()
            if line.replace("\x00", "").strip()
        ]
    except Exception:
        names = []
    if configured and (not names or configured in names):
        return ["-d", configured]
    if configured and names:
        print(f"JIMENG_WSL_DISTRO={configured} 不存在，已回退自动选择。可用发行版：{names}")
    try:
        ubuntu = next((name for name in names if re.match(r"^Ubuntu($|-)", name)), "")
        if ubuntu:
            return ["-d", ubuntu]
    except Exception:
        pass
    return []

def jimeng_clean_wsl_stderr(text):
    lines = []
    skip_next_warning_context = False
    for line in str(text or "").splitlines():
        clean = line.replace("\x00", "").strip()
        low = clean.lower()
        is_proxy_warning = "localhost" in low and "wsl" in low and ("nat" in low or "proxy" in low or "代理" in clean)
        # Windows/WSL can mojibake the proxy warning. Keep explicit failures, but
        # do not turn a completed Dreamina task into a failed request for this noise.
        is_proxy_mojibake = "localhost" in low and len(clean) < 120 and not any(
            token in low for token in ("error", "failed", "traceback", "exception", "refused", "denied")
        )
        is_python_warning = "requestsdependencywarning" in low or (skip_next_warning_context and clean.startswith("warnings.warn("))
        skip_next_warning_context = "requestsdependencywarning" in low
        if clean and not is_proxy_warning and not is_proxy_mojibake and not is_python_warning:
            lines.append(clean)
    return "\n".join(lines).strip()

def jimeng_has_result_payload(raw):
    """Recognize CLI output that is usable even when its process exit code is non-zero."""
    found = False
    def visit(value):
        nonlocal found
        if found:
            return
        if isinstance(value, dict):
            keys = {str(key).lower() for key in value}
            if keys & {"submit_id", "submitid", "task_id", "taskid", "gen_status", "result_json", "images", "videos", "data"}:
                found = True
                return
            for item in value.values():
                if isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(raw)
    return found

def windows_path_to_wsl(path):
    text = str(path or "").replace("\\", "/")
    match = re.match(r"^([A-Za-z]):/(.*)$", text)
    if match:
        return f"/mnt/{match.group(1).lower()}/{match.group(2)}"
    return text

def wsl_path_to_windows(path):
    text = str(path or "").strip()
    match = re.match(r"^/mnt/([A-Za-z])/(.*)$", text)
    if match:
        tail = match.group(2).replace("/", "\\")
        return f"{match.group(1).upper()}:\\{tail}"
    return text

def jimeng_cli_path_arg(path):
    return windows_path_to_wsl(path) if jimeng_use_wsl() else path

def jimeng_poll_seconds(default=JIMENG_DEFAULT_POLL_SECONDS):
    try:
        return max(1, min(3600, int(os.getenv("JIMENG_POLL_SECONDS", str(default)) or default)))
    except Exception:
        return default

def jimeng_video_submit_poll_seconds():
    """Keep the HTTP submission short; pending jobs continue through query_result polling."""
    try:
        return max(0, min(30, int(os.getenv("JIMENG_VIDEO_SUBMIT_POLL", "12") or 12)))
    except Exception:
        return 12

def jimeng_extract_json(text):
    text = str(text or "").strip()
    if not text:
        return {}
    decoder = json.JSONDecoder()
    parsed = []
    for i, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            obj, _end = decoder.raw_decode(text[i:])
            if not text[:i].strip():
                return obj
            parsed.append((i, obj))
        except Exception:
            continue
    def score(item):
        _idx, obj = item
        if not isinstance(obj, dict):
            return 1
        keys = {str(key).lower() for key in obj.keys()}
        weight = 0
        for key in ("submit_id", "gen_status", "result_json", "images", "videos", "data", "total_credit"):
            if key in keys:
                weight += 10
        return weight
    return max(parsed, key=score)[1] if parsed else {"text": text}

async def run_jimeng_cli(args, timeout=120, raw_text=False):
    exe = jimeng_cli_executable()
    if not exe:
        raise HTTPException(status_code=400, detail="未找到 dreamina CLI。请先安装：curl -fsSL https://jimeng.jianying.com/cli | bash，并完成 dreamina login。")
    clean_args = [str(arg) for arg in args if str(arg) != ""]
    command = jimeng_command(clean_args, exe)
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=cli_subprocess_env(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"即梦 CLI 执行超时：{' '.join(command[:3])}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"未找到即梦 CLI：{exe}") from exc
    out_text, clean_err_text = jimeng_decode_cli_output(stdout, stderr)
    if proc.returncode != 0:
        # Some Dreamina CLI versions return a non-zero code after already emitting
        # a usable task payload. Preserve that task so the canvas can continue polling.
        if out_text:
            raw = jimeng_extract_json(out_text)
            if isinstance(raw, dict) and jimeng_has_result_payload(raw):
                raw.setdefault("_stdout", out_text)
                if clean_err_text:
                    raw.setdefault("_stderr", clean_err_text)
                return raw
        message = clean_err_text or out_text or f"exit={proc.returncode}"
        raise HTTPException(status_code=502, detail=f"即梦 CLI 调用失败：{jimeng_friendly_error_detail(message[:1000])}")
    # 帮助等纯文本输出不应被 JSON 提取吞掉（如 [0.5, 8] 会被误判为结果）
    if raw_text:
        return {"_stdout": out_text, "_stderr": clean_err_text}
    raw = jimeng_extract_json(f"{out_text}\n{clean_err_text}".strip())
    if isinstance(raw, dict):
        raw.setdefault("_stdout", out_text)
        if clean_err_text:
            raw.setdefault("_stderr", clean_err_text)
    return raw

# 旧版 dreamina CLI 将 submit_id 用 16 位 hex，v1.4.2 起升级为 UUID，
# 与当前轮询逻辑不兼容。这里做尽力而为的版本探测，失败不阻断主流程。
JIMENG_MIN_CLI_VERSION = (1, 4, 2)

def jimeng_parse_version(text):
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", str(text or ""))
    if not match:
        return None
    return tuple(int(part) for part in match.groups())

async def jimeng_cli_version():
    for flag in ("--version", "-V", "version"):
        try:
            raw = await run_jimeng_cli([flag], timeout=15)
        except HTTPException:
            continue
        text = raw if isinstance(raw, str) else (raw.get("_stdout") or raw.get("_stderr") or "" if isinstance(raw, dict) else "")
        version = jimeng_parse_version(text)
        if version:
            return version, str(text).strip()
    return None, ""

def jimeng_command(clean_args, exe=None):
    exe = exe or jimeng_cli_executable()
    if jimeng_use_wsl():
        shell_line = (
            ". ~/.profile >/dev/null 2>&1 || true; . ~/.bashrc >/dev/null 2>&1 || true; "
            "DREAMINA_BIN=$(command -v dreamina || find \"$HOME\" -maxdepth 4 -type f -name dreamina 2>/dev/null | head -n 1); "
            "if [ -z \"$DREAMINA_BIN\" ]; then echo 'dreamina CLI not found in WSL' >&2; exit 127; fi; "
            "\"$DREAMINA_BIN\" " + " ".join(shlex.quote(arg) for arg in clean_args)
        )
        return [exe, *jimeng_wsl_base_args(exe), "-e", "sh", "-lc", shell_line]
    return [exe, *clean_args]

def jimeng_decode_cli_output(stdout, stderr):
    out_text = (decode_wsl_output(stdout) if jimeng_use_wsl() else stdout.decode("utf-8", errors="replace")).strip()
    err_text = (decode_wsl_output(stderr) if jimeng_use_wsl() else stderr.decode("utf-8", errors="replace")).strip()
    clean_err_text = jimeng_clean_wsl_stderr(err_text) if jimeng_use_wsl() else err_text
    return out_text, clean_err_text

def jimeng_login_text():
    parts = []
    for key in ("stdout", "stderr"):
        value = str(JIMENG_LOGIN_SESSION.get(key) or "").strip()
        if value:
            parts.append(value)
    return "\n".join(parts).strip()

def jimeng_login_qr_from_text(text):
    text = str(text or "")
    candidates = []
    patterns = [
        r"(https?://[^\s\"'<>]+)",
        r"(dreamina://[^\s\"'<>]+)",
        r"(data:image/[^\s\"'<>]+)",
    ]
    for pattern in patterns:
        candidates.extend(re.findall(pattern, text))
    for value in candidates:
        if "login" in value.lower() or "qr" in value.lower() or value.startswith(("data:image", "dreamina://")):
            return value
    return candidates[0] if candidates else ""

async def jimeng_login_reader(proc):
    async def read_stream(stream, key):
        while True:
            chunk = await stream.readline()
            if not chunk:
                break
            text = (decode_wsl_output(chunk) if jimeng_use_wsl() else chunk.decode("utf-8", errors="replace"))
            if key == "stderr":
                text = jimeng_clean_wsl_stderr(text)
            if text:
                JIMENG_LOGIN_SESSION[key] = str(JIMENG_LOGIN_SESSION.get(key) or "") + text
    await asyncio.gather(read_stream(proc.stdout, "stdout"), read_stream(proc.stderr, "stderr"))

def jimeng_submit_id(raw):
    found = []
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in {"submit_id", "submitid", "task_id", "taskid"} and item:
                    found.append(str(item))
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(raw)
    return found[0] if found else ""

class JimengPendingError(Exception):
    """即梦任务还在云端排队/生成（轮询超时但未失败）。submit_id 可用于后续续查。"""
    def __init__(self, submit_id, kind="image", queue_info=None, raw=None):
        self.submit_id = str(submit_id or "")
        self.kind = kind or "image"
        self.queue_info = queue_info if isinstance(queue_info, dict) else {}
        self.raw = raw
        super().__init__(f"jimeng pending submit_id={self.submit_id}")

def jimeng_queue_info(raw):
    """从即梦原始返回里就近取出 queue_info（含 queue_idx/queue_length/queue_status）。"""
    found = []
    def visit(value):
        if isinstance(value, dict):
            qi = value.get("queue_info")
            if isinstance(qi, dict) and qi:
                found.append(qi)
            for item in value.values():
                if isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(raw)
    return found[0] if found else {}

def jimeng_pending_payload(exc: "JimengPendingError"):
    qi = exc.queue_info or {}
    idx = qi.get("queue_idx")
    length = qi.get("queue_length")
    if idx is not None and length is not None:
        msg = f"即梦云端排队中（第 {idx}/{length} 位），任务未丢失，可继续等待或手动查询。submit_id={exc.submit_id}"
    else:
        msg = f"即梦任务仍在生成中，任务未丢失。submit_id={exc.submit_id}"
    return {
        "jimeng_pending": True,
        "submit_id": exc.submit_id,
        "kind": exc.kind,
        "queue_info": qi,
        "message": msg,
    }

def register_online_exception_handlers(app):
    @app.exception_handler(JimengPendingError)
    async def jimeng_pending_exception_handler(request: Request, exc: JimengPendingError):
        return JSONResponse(status_code=202, content=jimeng_pending_payload(exc))

async def jimeng_pending_exception_handler(request: Request, exc: JimengPendingError):
    return JSONResponse(status_code=202, content=jimeng_pending_payload(exc))

def jimeng_failure_reason(raw):
    found = []
    def visit(value):
        if isinstance(value, dict):
            status = str(value.get("gen_status") or value.get("status") or "").strip().lower()
            reason = value.get("fail_reason") or value.get("failReason") or value.get("error") or value.get("message") or value.get("msg")
            if reason and (status in {"fail", "failed", "error"} or "fail" in str(reason).lower() or "invalid param" in str(reason).lower()):
                found.append(str(reason))
            for item in value.values():
                if isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(raw)
    return jimeng_friendly_error_detail(found[0]) if found else ""

def jimeng_friendly_error_detail(detail):
    text = str(detail or "").strip()
    if "aigccomplianceconfirmationrequired" in text.lower():
        return "即梦要求先完成内容安全授权。请在 Dreamina 网页端按提示确认授权后，再返回此处重试。"
    return text

def jimeng_collect_media_values(value, outputs):
    media_ext = re.compile(r"\.(png|jpe?g|webp|gif|bmp|mp4|webm|mov|m4v|avi|mkv)(\?|#|$)", re.I)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return
        if text.startswith(("http://", "https://", "/output/", "/assets/", "file://")) or media_ext.search(text):
            outputs.append(text)
        return
    if isinstance(value, list):
        for item in value:
            jimeng_collect_media_values(item, outputs)
        return
    if isinstance(value, dict):
        for key in (
            "url", "urls", "image", "images", "image_url", "image_urls",
            "video", "videos", "video_url", "video_urls", "output", "outputs",
            "result", "results", "file", "files", "path", "paths",
            "download_url", "download_urls", "downloadUrl", "file_path", "filePath",
        ):
            if key in value:
                jimeng_collect_media_values(value.get(key), outputs)
        for item in value.values():
            if isinstance(item, (dict, list)):
                jimeng_collect_media_values(item, outputs)

def jimeng_output_values(raw):
    outputs = []
    jimeng_collect_media_values(raw, outputs)
    deduped = []
    for value in outputs:
        if value not in deduped:
            deduped.append(value)
    return deduped

JIMENG_RATIO_CHOICES = [(21, 9), (16, 9), (3, 2), (4, 3), (1, 1), (3, 4), (2, 3), (9, 16)]
def jimeng_ratio_from_size(size, fallback="1:1"):
    width, height = parse_size_pair(size)
    if not width or not height:
        return fallback
    ratio = width / max(1, height)
    left, right = min(JIMENG_RATIO_CHOICES, key=lambda item: abs(ratio - item[0] / item[1]))
    return f"{left}:{right}"

# 官方 dreamina 支持的图片模型（来自 text2image/image2image -h）。
# image2image 不支持 3.0/3.1。
JIMENG_TEXT2IMAGE_MODELS = {"3.0", "3.1", "4.0", "4.1", "4.5", "4.6", "4.7", "5.0", "5.0Pro"}
JIMENG_IMAGE2IMAGE_MODELS = {"4.0", "4.1", "4.5", "4.6", "4.7", "5.0", "5.0Pro"}

def jimeng_normalize_image_model(model):
    text = str(model or "").strip()
    if re.search(r"\b5(?:\.0)?\s*[-_ ]?pro\b", text, re.IGNORECASE):
        return "5.0Pro"
    match = re.search(r"(\d+\.\d+)", text)
    return match.group(1) if match else ""

def jimeng_image_model_version(model, mode="text2image"):
    version = jimeng_normalize_image_model(model)
    allowed = JIMENG_IMAGE2IMAGE_MODELS if mode == "image2image" else JIMENG_TEXT2IMAGE_MODELS
    return version if version in allowed else ""

def jimeng_image_resolution(model, size, mode="text2image"):
    text = str(model or "").lower()
    if "4k" in text:
        desired = "4k"
    elif "1k" in text:
        desired = "1k"
    elif "2k" in text:
        desired = "2k"
    else:
        width, height = parse_size_pair(size)
        longest_side = max(width, height)
        pixel_count = width * height
        if longest_side > 3072 or pixel_count > 6000000:
            desired = "4k"
        elif longest_side > 1536 or pixel_count > 1572864:
            desired = "2k"
        else:
            desired = "1k"
    # 按官方规则收敛到模型允许的分辨率
    version = jimeng_normalize_image_model(model)
    if mode == "image2image":
        if version == "5.0Pro":
            return desired if desired in {"1k", "2k", "4k"} else "1k"
        return "4k" if desired == "4k" else "2k"
    if version in ("3.0", "3.1", "5.0Pro"):
        if version == "5.0Pro" and desired == "4k":
            return "4k"
        return "1k" if desired == "1k" else "2k"
    # 4.x/5.0 只支持 2k/4k
    return "4k" if desired == "4k" else "2k"

JIMENG_VIDEO_HIGH_RES_MODELS = {"seedance2.0_vip"}
JIMENG_VIDEO_MODEL_VERSIONS = {
    "seedance1.0fast", "seedance1.5pro", "seedance2.0", "seedance2.0fast",
    "seedance2.0_vip", "seedance2.0fast_vip", "seedance2.0mini",
}
JIMENG_VIDEO_MODELS_BY_COMMAND = {
    "text2video": {"seedance2.0", "seedance2.0fast", "seedance2.0_vip", "seedance2.0fast_vip", "seedance2.0mini"},
    "image2video": {"seedance1.0fast", "seedance1.5pro", "seedance2.0", "seedance2.0fast", "seedance2.0_vip", "seedance2.0fast_vip", "seedance2.0mini"},
    "multimodal2video": {"seedance2.0", "seedance2.0fast", "seedance2.0_vip", "seedance2.0fast_vip", "seedance2.0mini"},
    "frames2video": {"seedance1.5pro", "seedance2.0", "seedance2.0fast", "seedance2.0_vip", "seedance2.0fast_vip", "seedance2.0mini"},
}

def jimeng_video_resolution(model, resolution):
    version = jimeng_video_model_version(model)
    requested = str(resolution or "").strip().lower()
    if not requested:
        requested = "720p"
    elif requested in {"4k", "4kp"}:
        requested = "4k"
    elif requested in {"1080p", "1080"}:
        requested = "1080p"
    elif requested in {"720p", "720"}:
        requested = "720p"
    else:
        raise HTTPException(status_code=400, detail="即梦视频只支持 720p；seedance2.0_vip 额外支持 1080p 和 4k。")
    if version not in JIMENG_VIDEO_HIGH_RES_MODELS:
        if requested != "720p":
            raise HTTPException(status_code=400, detail=f"即梦模型 {version or model} 只支持 720p。")
        return requested
    return requested

# 各模型支持的时长区间（秒）：3.0 系列 3-10，3.5pro 4-12，seedance 4-15
def jimeng_video_duration_range(model, command=""):
    version = jimeng_video_model_version(model)
    if command in {"image2video", "frames2video"} and version == "seedance1.5pro":
        return 5, 12
    if command == "image2video" and version == "seedance1.0fast":
        return 5, 10
    return 4, 15

def jimeng_video_duration(duration, model=None, command=""):
    low, high = jimeng_video_duration_range(model, command)
    default = max(low, min(high, 5))
    try:
        text = str(duration).strip() if duration is not None else ""
        value = default if text == "" else int(text)
    except Exception:
        raise HTTPException(status_code=400, detail=f"即梦视频时长必须是 {low}-{high} 秒的整数。")
    if not low <= value <= high:
        raise HTTPException(status_code=400, detail=f"即梦模型 {jimeng_video_model_version(model) or model} 只支持 {low}-{high} 秒时长。")
    return value

def jimeng_transition_duration(total_duration, transition_count):
    count = max(1, int(transition_count or 1))
    try:
        total = float(total_duration) if str(total_duration).strip() else 0.0
    except Exception:
        total = 0.0
    return max(1, min(8, int(round(3.0 if total <= 0 else total / count))))

def jimeng_multiframe_transition_prompts(prompt, segments):
    segments = max(1, int(segments or 1))
    prompts = [line.strip() for line in str(prompt or "").splitlines() if line.strip()]
    if not prompts:
        return []
    if len(prompts) == 1:
        prompts *= segments
    elif len(prompts) < segments:
        prompts.extend([prompts[-1]] * (segments - len(prompts)))
    return prompts[:segments]

def jimeng_video_model_version(model):
    value = str(model or "").strip()
    low = value.lower()
    aliases = {
        "seedance1.0fast": "seedance1.0fast",
        "seedance1.5pro": "seedance1.5pro",
        "seedance2.0fast_vip": "seedance2.0fast_vip",
        "seedance2.0_vip": "seedance2.0_vip",
        "seedance2.0mini": "seedance2.0mini",
        "seedance2.0fast": "seedance2.0fast",
        "seedance2.0": "seedance2.0",
    }
    for key, mapped in aliases.items():
        if key in low:
            return mapped if mapped in JIMENG_VIDEO_MODEL_VERSIONS else ""
    return ""

def jimeng_video_model_for_command(model, command):
    version = jimeng_video_model_version(model)
    allowed = JIMENG_VIDEO_MODELS_BY_COMMAND.get(command) or set()
    if version in allowed:
        return version
    supported = "、".join(sorted(allowed))
    raise HTTPException(status_code=400, detail=f"即梦 {command} 不支持模型「{model}」。可用模型：{supported}。")

def jimeng_video_resolution_arg(model, resolution):
    return jimeng_video_resolution(model, resolution)

def jimeng_video_ratio_arg(aspect_ratio):
    value = str(aspect_ratio or "").strip()
    allowed = {"1:1", "3:4", "16:9", "4:3", "9:16", "21:9"}
    if value in allowed:
        return value
    return ""

def jimeng_video_ratio(aspect_ratio, default="16:9"):
    value = str(aspect_ratio or "").strip()
    if not value:
        return default
    ratio = jimeng_video_ratio_arg(value)
    if not ratio:
        raise HTTPException(status_code=400, detail="即梦视频比例仅支持 1:1、3:4、16:9、4:3、9:16、21:9。")
    return ratio

def jimeng_append_model_resolution_args(args, payload: CanvasVideoRequest, model_version=""):
    if model_version:
        args.append(f"--model_version={model_version}")
    args.append(f"--video_resolution={jimeng_video_resolution_arg(model_version or payload.model, payload.resolution)}")

def jimeng_multiframe_resolution(resolution):
    value = str(resolution or "").strip().lower()
    if not value:
        return "720p"
    if value in {"720", "720p"}:
        return "720p"
    if value in {"1080", "1080p"}:
        return "1080p"
    raise HTTPException(status_code=400, detail="即梦多帧视频只支持 720p 或 1080p。")

def jimeng_video_ref_role(ref):
    role = getattr(ref, "role", "")
    if isinstance(ref, dict):
        role = ref.get("role", role)
    return str(role or "").lower()

def jimeng_video_ref_url(ref):
    url = getattr(ref, "url", "")
    if isinstance(ref, dict):
        url = ref.get("url", url)
    return str(url or "").strip()

def jimeng_local_output_url(path, kind="image"):
    path = os.path.abspath(str(path or ""))
    if not os.path.isfile(path):
        return ""
    output_root = os.path.abspath(OUTPUT_OUTPUT_DIR)
    try:
        if os.path.commonpath([output_root, path]) == output_root:
            return output_url_for(os.path.basename(path), "output")
    except Exception:
        pass
    ext = os.path.splitext(path)[1].lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}
    if ext not in allowed:
        ct = content_type_for_path(path)
        ext = ".mp4" if ct.startswith("video/") else ".png"
    prefix = "jimeng_video_" if kind == "video" else "jimeng_"
    filename = f"{prefix}{uuid.uuid4().hex[:10]}{ext}"
    dest = output_path_for(filename, "output")
    shutil.copyfile(path, dest)
    return output_url_for(filename, "output")

async def jimeng_store_output_value(value, kind="image"):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("/output/") or text.startswith("/assets/"):
        return text
    if text.startswith("file://"):
        text = urllib.parse.unquote(urllib.parse.urlparse(text).path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", text):
            text = text[1:]
    if jimeng_use_wsl() and text.startswith("/mnt/"):
        text = wsl_path_to_windows(text)
    if text.startswith(("http://", "https://")):
        if kind == "video":
            return await save_remote_video_to_output(text, prefix="jimeng_video_")
        return await save_ai_image_to_output({"type": "url", "value": text}, prefix="jimeng_")
    if os.path.isfile(text):
        return jimeng_local_output_url(text, kind)
    return ""

async def jimeng_query_result(submit_id, kind="image"):
    args = [
        "query_result",
        f"--submit_id={submit_id}",
        f"--download_dir={jimeng_cli_path_arg(OUTPUT_OUTPUT_DIR)}",
    ]
    return await run_jimeng_cli(args, timeout=min(300, jimeng_poll_seconds() + 60))

async def jimeng_store_outputs(raw, kind="image", allow_query=True):
    failure = jimeng_failure_reason(raw)
    if failure:
        raise HTTPException(status_code=502, detail=f"即梦生成失败：{failure}")
    values = jimeng_output_values(raw)
    urls = []
    for value in values:
        local_url = await jimeng_store_output_value(value, kind)
        if local_url and local_url not in urls:
            urls.append(local_url)
    if urls:
        return urls
    submit_id = jimeng_submit_id(raw)
    if submit_id and allow_query:
        queried = await jimeng_query_result(submit_id, kind)
        try:
            return await jimeng_store_outputs(queried, kind, allow_query=False)
        except HTTPException as exc:
            if getattr(exc, "status_code", None) == 502:
                status_text = json.dumps(queried, ensure_ascii=False)[:800] if isinstance(queried, (dict, list)) else str(queried)[:800]
                raise HTTPException(status_code=502, detail=f"即梦任务已返回但没有下载到媒体：{status_text}") from exc
            raise
    status_text = json.dumps(raw, ensure_ascii=False)[:800] if isinstance(raw, (dict, list)) else str(raw)[:800]
    if submit_id:
        raise JimengPendingError(submit_id, kind, jimeng_queue_info(raw), raw)
    raise HTTPException(status_code=502, detail=f"即梦 CLI 未返回可用媒体结果：{status_text}")

async def jimeng_prepare_local_media(ref_url, kind="image"):
    text = str(ref_url or "").strip()
    if not text:
        return "", []
    if text.startswith("/output/") or text.startswith("/assets/"):
        path = output_file_from_url(text)
        if path:
            return path, []
        raise HTTPException(status_code=404, detail=f"即梦参考素材不存在：{text}")
    if text.startswith("file://"):
        path = urllib.parse.unquote(urllib.parse.urlparse(text).path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", path):
            path = path[1:]
        if _is_confined_local_media_path(path):
            return path, []
    if _is_confined_local_media_path(text):
        return text, []
    suffix = ".mp4" if kind == "video" else (".mp3" if kind == "audio" else ".png")
    temp_paths = []
    if text.startswith("data:"):
        if ";base64," not in text:
            raise HTTPException(status_code=400, detail="即梦参考素材 data URL 缺少 base64 数据")
        header, encoded = text.split(";base64,", 1)
        mime = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else ""
        suffix = mimetypes.guess_extension(mime) or suffix
        fd, path = tempfile.mkstemp(prefix="jimeng_ref_", suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64decode(encoded))
        temp_paths.append(path)
        return path, temp_paths
    if text.startswith(("http://", "https://")):
        try:
            content, content_type = await safe_download_bytes(text, timeout=60.0, max_bytes=50 * 1024 * 1024)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"即梦 CLI 下载参考素材失败: {e}")
        clean_path = urllib.parse.urlparse(text).path
        suffix = os.path.splitext(clean_path)[1] or mimetypes.guess_extension(content_type) or suffix
        fd, path = tempfile.mkstemp(prefix="jimeng_ref_", suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        temp_paths.append(path)
        return path, temp_paths
    raise HTTPException(status_code=400, detail=f"即梦 CLI 只支持本地文件参考素材，无法读取：{text[:120]}")

async def generate_jimeng_provider_image(prompt, size, model, reference_images=None, provider=None):
    refs = [ref for ref in (reference_images or []) if ref.get("url")]
    temp_paths = []
    try:
        args = []
        if refs:
            image_paths = []
            for ref in refs[:10]:
                image_path, created = await jimeng_prepare_local_media(ref.get("url"), "image")
                image_paths.append(jimeng_cli_path_arg(image_path))
                temp_paths.extend(created)
            model_version = jimeng_image_model_version(model, "image2image")
            args = [
                "image2image",
                f"--images={','.join(image_paths)}",
                f"--prompt={prompt}",
                f"--resolution_type={jimeng_image_resolution(model, size, 'image2image')}",
                f"--poll={jimeng_poll_seconds()}",
            ]
            if model_version:
                args.append(f"--model_version={model_version}")
        else:
            model_version = jimeng_image_model_version(model, "text2image")
            args = [
                "text2image",
                f"--prompt={prompt}",
                f"--ratio={jimeng_ratio_from_size(size)}",
                f"--resolution_type={jimeng_image_resolution(model, size, 'text2image')}",
                f"--poll={jimeng_poll_seconds()}",
            ]
            if model_version:
                args.append(f"--model_version={model_version}")
        raw = await run_jimeng_cli(args, timeout=jimeng_poll_seconds() + 120)
        urls = await jimeng_store_outputs(raw, "image")
        return {"type": "url", "value": urls[0]}, raw
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass

JIMENG_UPSCALE_RESOLUTIONS = {"2k", "4k", "8k"}

def jimeng_normalize_upscale_resolution(value):
    resolution = str(value or "").strip().lower()
    return resolution if resolution in JIMENG_UPSCALE_RESOLUTIONS else "2k"

async def generate_jimeng_upscale_image(reference_images, resolution_type):
    refs = [ref for ref in (reference_images or []) if ref.get("url")]
    if not refs:
        raise HTTPException(status_code=400, detail="请先选择要放大的图片")
    temp_paths = []
    try:
        image_path, created = await jimeng_prepare_local_media(refs[0]["url"], "image")
        temp_paths.extend(created)
        raw = await run_jimeng_cli([
            "image_upscale",
            f"--image={jimeng_cli_path_arg(image_path)}",
            f"--resolution_type={jimeng_normalize_upscale_resolution(resolution_type)}",
            f"--poll={jimeng_poll_seconds()}",
        ], timeout=jimeng_poll_seconds() + 120)
        urls = await jimeng_store_outputs(raw, "image")
        return {"type": "url", "value": urls[0]}, raw
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass

async def generate_jimeng_video(payload: CanvasVideoRequest, provider):
    image_refs = [ref for ref in (payload.images or []) if jimeng_video_ref_url(ref)]
    video_refs = [url for url in (payload.videos or []) if str(url or "").strip()]
    audio_refs = [url for url in (payload.audios or []) if str(url or "").strip()][:3]
    temp_paths = []
    try:
        if payload.multimodal or video_refs or audio_refs:
            if not image_refs and not video_refs:
                raise HTTPException(status_code=400, detail="即梦全能参考至少需要一张图片或一个视频，音频不能单独生成视频。")
            model_version = jimeng_video_model_for_command(payload.model, "multimodal2video")
            duration = jimeng_video_duration(payload.duration, model_version, "multimodal2video")
            image_paths = []
            video_paths = []
            audio_paths = []
            for ref in image_refs[:9]:
                image_path, created = await jimeng_prepare_local_media(jimeng_video_ref_url(ref), "image")
                temp_paths.extend(created)
                image_paths.append(image_path)
            for ref_url in video_refs[:3]:
                video_path, created = await jimeng_prepare_local_media(ref_url, "video")
                temp_paths.extend(created)
                video_paths.append(video_path)
            for ref_url in audio_refs:
                audio_path, created = await jimeng_prepare_local_media(ref_url, "audio")
                temp_paths.extend(created)
                audio_paths.append(audio_path)
            args = [
                "multimodal2video",
                f"--prompt={payload.prompt}",
                f"--duration={duration}",
                f"--poll={jimeng_poll_seconds()}",
            ]
            args.append(f"--ratio={jimeng_video_ratio(payload.aspect_ratio)}")
            jimeng_append_model_resolution_args(args, payload, model_version)
            for image_path in image_paths:
                args.append(f"--image={jimeng_cli_path_arg(image_path)}")
            for video_path in video_paths:
                args.append(f"--video={jimeng_cli_path_arg(video_path)}")
            for audio_path in audio_paths:
                args.append(f"--audio={jimeng_cli_path_arg(audio_path)}")
        elif len(image_refs) >= 2:
            if len(image_refs) > 20:
                raise HTTPException(status_code=400, detail="即梦多帧视频最多支持 20 张图片。")
            first_frame = next((ref for ref in image_refs if jimeng_video_ref_role(ref) == "first_frame"), None)
            last_frame = next((ref for ref in image_refs if jimeng_video_ref_role(ref) == "last_frame"), None)
            if first_frame and last_frame:
                model_version = jimeng_video_model_for_command(payload.model, "frames2video")
                duration = jimeng_video_duration(payload.duration, model_version, "frames2video")
                first_path, created = await jimeng_prepare_local_media(jimeng_video_ref_url(first_frame), "image")
                temp_paths.extend(created)
                last_path, created = await jimeng_prepare_local_media(jimeng_video_ref_url(last_frame), "image")
                temp_paths.extend(created)
                args = [
                    "frames2video",
                    f"--first={jimeng_cli_path_arg(first_path)}",
                    f"--last={jimeng_cli_path_arg(last_path)}",
                    f"--prompt={payload.prompt}",
                    f"--duration={duration}",
                    f"--poll={jimeng_poll_seconds()}",
                ]
                jimeng_append_model_resolution_args(args, payload, model_version)
            else:
                image_paths = []
                for ref in image_refs:
                    image_path, created = await jimeng_prepare_local_media(jimeng_video_ref_url(ref), "image")
                    temp_paths.extend(created)
                    image_paths.append(image_path)
                args = [
                    "multiframe2video",
                    f"--images={','.join(jimeng_cli_path_arg(path) for path in image_paths)}",
                    f"--poll={jimeng_poll_seconds()}",
                ]
                # multiframe2video has its own transition arguments and does not
                # accept model_version. The CLI requires an explicit resolution.
                args.append(f"--video_resolution={jimeng_multiframe_resolution(payload.resolution)}")
                segments = max(1, len(image_paths) - 1)
                segment_duration = jimeng_transition_duration(payload.duration, segments)
                if len(image_paths) <= 2:
                    if str(payload.prompt or "").strip():
                        args.append(f"--prompt={payload.prompt}")
                    args.append(f"--duration={segment_duration}")
                else:
                    for segment_prompt in jimeng_multiframe_transition_prompts(payload.prompt, segments):
                        args.append(f"--transition-prompt={segment_prompt}")
                    for _ in range(segments):
                        args.append(f"--transition-duration={segment_duration}")
        elif image_refs:
            model_version = jimeng_video_model_for_command(payload.model, "image2video")
            duration = jimeng_video_duration(payload.duration, model_version, "image2video")
            image_path, created = await jimeng_prepare_local_media(jimeng_video_ref_url(image_refs[0]), "image")
            temp_paths.extend(created)
            args = [
                "image2video",
                f"--image={jimeng_cli_path_arg(image_path)}",
                f"--prompt={payload.prompt}",
                f"--duration={duration}",
                f"--poll={jimeng_poll_seconds()}",
            ]
            jimeng_append_model_resolution_args(args, payload, model_version)
        else:
            model_version = jimeng_video_model_for_command(payload.model, "text2video")
            duration = jimeng_video_duration(payload.duration, model_version, "text2video")
            args = [
                "text2video",
                f"--prompt={payload.prompt}",
                f"--duration={duration}",
                f"--ratio={jimeng_video_ratio(payload.aspect_ratio)}",
                f"--poll={jimeng_poll_seconds()}",
            ]
            jimeng_append_model_resolution_args(args, payload, model_version)
        # Do not hold the canvas request open for the full cloud generation.
        # A pending result carries submit_id and is resumed by the existing UI poller.
        submit_poll = jimeng_video_submit_poll_seconds()
        args = [f"--poll={submit_poll}" if str(arg).startswith("--poll=") else arg for arg in args]
        raw = await run_jimeng_cli(args, timeout=submit_poll + 180)
        urls = await jimeng_store_outputs(raw, "video")
        return {"videos": urls, "task_id": jimeng_submit_id(raw) or None, "raw": raw}
    finally:
        for path in temp_paths:
            try:
                os.remove(path)
            except Exception:
                pass



# --- Sliced from online.py lines 4701-4839 ---
def _volc_hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

def volcengine_sign_v4_headers(ak: str, sk: str, action: str, body_str: str,
                               service: str = VOLCENGINE_ARK_ASSET_SERVICE,
                               region: str = VOLCENGINE_ARK_ASSET_REGION,
                               version: str = VOLCENGINE_ARK_ASSET_VERSION,
                               host: str = VOLCENGINE_ARK_ASSET_HOST) -> Dict[str, str]:
    """火山引擎 OpenAPI 签名 V4（POST + JSON body）。返回需随请求发送的鉴权头。"""
    method = "POST"
    content_type = "application/json"
    now = datetime.datetime.now(datetime.timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    payload_hash = hashlib.sha256(body_str.encode("utf-8")).hexdigest()
    # 查询串按键排序：Action < Version
    canonical_query = f"Action={urllib.parse.quote(action, safe='')}&Version={urllib.parse.quote(version, safe='')}"
    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-content-sha256:{payload_hash}\n"
        f"x-date:{x_date}\n"
    )
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_request = "\n".join([method, "/", canonical_query, canonical_headers, signed_headers, payload_hash])
    algorithm = "HMAC-SHA256"
    credential_scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join([
        algorithm, x_date, credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    k_date = _volc_hmac(sk.encode("utf-8"), short_date)
    k_region = _volc_hmac(k_date, region)
    k_service = _volc_hmac(k_region, service)
    k_signing = _volc_hmac(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"{algorithm} Credential={ak}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Content-Type": content_type,
        "Host": host,
        "X-Date": x_date,
        "X-Content-Sha256": payload_hash,
        "Authorization": authorization,
    }

async def volcengine_ark_asset_call(client, action: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """调用一次火山 Ark Assets OpenAPI，返回 Result 内容；出错抛 HTTPException。"""
    ak = volcengine_access_key_value()
    sk = volcengine_secret_key_value()
    if not ak or not sk:
        raise HTTPException(status_code=400, detail="未配置火山引擎 AK/SK，请在 API 设置中填写 Access Key ID / Secret Access Key。")
    body_str = json.dumps(body, ensure_ascii=False)
    headers = volcengine_sign_v4_headers(ak, sk, action, body_str)
    url = f"https://{VOLCENGINE_ARK_ASSET_HOST}/?Action={urllib.parse.quote(action, safe='')}&Version={urllib.parse.quote(VOLCENGINE_ARK_ASSET_VERSION, safe='')}"
    resp = await client.post(url, headers=headers, content=body_str.encode("utf-8"), timeout=120)
    try:
        payload = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"火山 {action} 返回非 JSON（{resp.status_code}）：{resp.text[:300]}")
    meta = payload.get("ResponseMetadata") if isinstance(payload, dict) else None
    if isinstance(meta, dict) and isinstance(meta.get("Error"), dict):
        err = meta["Error"]
        code = err.get("Code") or err.get("CodeN") or ""
        msg = err.get("Message") or ""
        raise HTTPException(status_code=502, detail=f"火山 {action} 失败：{code} {msg}".strip())
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"火山 {action} 失败（{resp.status_code}）：{resp.text[:300]}")
    result = payload.get("Result") if isinstance(payload, dict) and isinstance(payload.get("Result"), dict) else None
    return result if result is not None else (payload if isinstance(payload, dict) else {})

async def volcengine_ensure_asset_group(client, project_name: str, group_name: str) -> str:
    """复用同名素材组合，没有则新建。返回 GroupId。"""
    name = (group_name or "可信素材").strip()[:60] or "可信素材"
    project_name = (project_name or "default").strip() or "default"
    # 先按 Name 模糊查找复用
    try:
        listed = await volcengine_ark_asset_call(client, "ListAssetGroups", {
            "Filter": {"Name": name, "GroupType": "AIGC"},
            "PageNumber": 1, "PageSize": 10, "ProjectName": project_name,
        })
        for item in (listed.get("Items") or []):
            if str(item.get("Name") or "").strip() == name and str(item.get("ProjectName") or "default") == project_name:
                gid = str(item.get("Id") or "").strip()
                if gid:
                    return gid
    except HTTPException:
        pass  # 查询失败不致命，继续走新建
    created = await volcengine_ark_asset_call(client, "CreateAssetGroup", {
        "Name": name, "Description": name, "ProjectName": project_name,
    })
    gid = str(created.get("Id") or "").strip()
    if not gid:
        raise HTTPException(status_code=502, detail=f"火山 CreateAssetGroup 未返回 GroupId：{str(created)[:200]}")
    return gid

async def submit_volcengine_avatar_asset(public_url: str, name: str, kind: str,
                                         project_name: str = "default", group_name: str = "") -> str:
    """把公网可访问素材提交到火山 Ark 私域素材库（异步）。返回 Asset Id 作为任务 ID。"""
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=120) as client:
        group_id = await volcengine_ensure_asset_group(client, project_name, group_name)
        created = await volcengine_ark_asset_call(client, "CreateAsset", {
            "GroupId": group_id,
            "URL": public_url,
            "AssetType": apimart_avatar_asset_type(kind),
            "Name": (name or "asset")[:60],
            "ProjectName": (project_name or "default").strip() or "default",
        })
    asset_id = str(created.get("Id") or "").strip()
    if not asset_id:
        raise HTTPException(status_code=502, detail=f"火山 CreateAsset 未返回 Asset Id：{str(created)[:200]}")
    return asset_id

async def check_volcengine_avatar_task(asset_id: str, project_name: str = "default") -> Dict[str, Any]:
    """查询一次火山素材状态。返回 {status: Active/Processing/Failed, asset_uri, detail}。"""
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=60) as client:
        info = await volcengine_ark_asset_call(client, "GetAsset", {
            "Id": asset_id,
            "ProjectName": (project_name or "default").strip() or "default",
        })
    status = str(info.get("Status") or "").strip()
    if status == "Active":
        return {"status": "Active", "asset_uri": f"asset://{asset_id}", "detail": ""}
    if status == "Failed":
        return {"status": "Failed", "asset_uri": "", "detail": "火山素材处理失败，无法用于推理。"}
    return {"status": "Processing", "asset_uri": "", "detail": "火山素材处理中"}

def volcengine_public_asset_url(url: str) -> str:
    """火山 CreateAsset 要求 URL 公网可访问；本地文件需 PUBLIC_BASE_URL，否则返回 ERR:。"""
    text = str(url or "").strip()
    if text.startswith("http://") or text.startswith("https://"):
        return text
    public = local_asset_public_url(text)
    if public:
        return public
    return "ERR:火山要求素材是公网可访问的 http/https URL；本地画布文件需配置 PUBLIC_BASE_URL/PUBLIC_MEDIA_BASE_URL 暴露为公网地址。"



# --- Sliced from online.py lines 5446-5473 ---
def volcengine_endpoint_url(provider):
    return provider_endpoint_url(provider, "image_generation_endpoint", "/api/v3/images/generations")

def volcengine_image_payload(ref):
    value = reference_to_data_url(ref, max_size=1536)
    if not value:
        return None
    return value

async def generate_volcengine_provider_image(prompt, size, model, reference_images=None, provider=None):
    from routers.online_image import normalize_volcengine_size
    endpoint = volcengine_endpoint_url(provider)
    size = normalize_volcengine_size(size, model)
    body = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "response_format": "url",
    }
    images = [volcengine_image_payload(ref) for ref in (reference_images or [])[:ONLINE_IMAGE_REFERENCE_MAX]]
    images = [value for value in images if value]
    if images:
        body["image"] = images
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=httpx.Timeout(connect=20.0, read=1800.0, write=120.0, pool=20.0)) as client:
        response = await client.post(endpoint, headers=api_headers(provider=provider), json=body)
        response.raise_for_status()
        raw = response.json()
        return extract_image(raw), raw



# --- Sliced from online.py lines 5474-6663 ---
def runninghub_api_headers(provider, use_wallet=True):
    api_key = runninghub_api_key(provider, use_wallet=use_wallet)
    if not api_key:
        raise HTTPException(status_code=400, detail="未配置 RunningHub API Key，请在 API 设置中填写。")
    return {"Authorization": bearer_auth_value(api_key), "Accept": "application/json", "Content-Type": "application/json"}

def runninghub_json_headers(provider, use_wallet=True):
    return runninghub_api_headers(provider, use_wallet=use_wallet)

def runninghub_provider():
    return get_api_provider_exact("runninghub")

def runninghub_api_key(provider=None, use_wallet=False, prefer_wallet=False):
    provider = provider or runninghub_provider()
    provider_id = (provider or {}).get("id") or "runninghub"
    free_key = str((provider or {}).get("api_key") or "").strip() or provider_env_key_value(provider_id)
    wallet_key = str((provider or {}).get("wallet_api_key") or "").strip() or runninghub_wallet_key_value(provider_id)
    if use_wallet and not wallet_key:
        raise HTTPException(status_code=400, detail="未配置 RunningHub 账户余额 API Key。标准模型接口只能走账户余额，请在 RH 设置中填写账户余额 Key。")
    api_key = wallet_key if (use_wallet or prefer_wallet) and wallet_key else free_key
    if not api_key:
        raise HTTPException(status_code=400, detail="未配置 RunningHub API Key，请在 RH 设置中填写。")
    return api_key

def runninghub_app_headers(json_body=True, use_wallet=False, provider=None):
    provider = provider or runninghub_provider()
    default_host = "www.runninghub.ai" if str((provider or {}).get("id") or "").strip().lower() in {"runninghub-ai", "runninghub-global"} else "www.runninghub.cn"
    host = urllib.parse.urlsplit(str((provider or {}).get("base_url") or RUNNINGHUB_DEFAULT_BASE_URL)).netloc or default_host
    headers = {"Host": host}
    if provider:
        api_key = runninghub_api_key(provider, use_wallet=use_wallet)
        if api_key:
            headers["Authorization"] = bearer_auth_value(api_key)
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers

def runninghub_local_asset_path(url):
    text = str(url or "").strip()
    if not text:
        return None
    if text.startswith("/assets/input/") or text.startswith("/input/"):
        clean = urllib.parse.unquote(text.split("?", 1)[0]).replace("\\", "/")
        rel = clean[len("/assets/input/"):] if clean.startswith("/assets/input/") else clean[len("/input/"):]
        root = OUTPUT_INPUT_DIR
    elif text.startswith("/assets/output/"):
        clean = urllib.parse.unquote(text.split("?", 1)[0]).replace("\\", "/")
        rel = clean[len("/assets/output/"):]
        root = OUTPUT_OUTPUT_DIR
    elif text.startswith("/output/") or text.startswith("/assets/"):
        return output_file_from_url(text)
    else:
        return None
    rel = rel.lstrip("/")
    if not rel:
        return None
    path = os.path.abspath(os.path.join(root, rel))
    root_abs = os.path.abspath(root)
    if os.path.commonpath([root_abs, path]) != root_abs or not os.path.exists(path):
        return None
    return path

def runninghub_output_ext(remote, content_type=""):
    tail = str(remote or "").split("?", 1)[0].split("#", 1)[0]
    ext = os.path.splitext(tail)[1].lower().strip(".")
    allowed = {"png","jpg","jpeg","webp","gif","bmp","mp4","webm","mov","m4v","mkv","mp3","wav","ogg","m4a","flac","aac"}
    if ext in allowed:
        return ext
    ct = str(content_type or "").lower()
    if "mp4" in ct:
        return "mp4"
    if "webm" in ct:
        return "webm"
    if "quicktime" in ct:
        return "mov"
    if "mpeg" in ct:
        return "mp3"
    if "wav" in ct:
        return "wav"
    if "ogg" in ct:
        return "ogg"
    if "webp" in ct:
        return "webp"
    if "jpeg" in ct:
        return "jpg"
    return "png"

def rewrite_runninghub_file_url(url):
    text = str(url or "")
    if not text:
        return text
    try:
        parsed = urllib.parse.urlsplit(text)
    except Exception:
        return text
    target = RUNNINGHUB_FILE_HOST_REWRITES.get((parsed.netloc or "").lower())
    return parsed._replace(netloc=target).geturl() if target else text

def runninghub_extract_outputs(data):
    arr = []
    if isinstance(data, list):
        arr = data
    elif isinstance(data, dict):
        for key in ("outputs", "results", "files", "data"):
            value = data.get(key)
            if isinstance(value, list):
                arr = value
                break
        if not arr and (data.get("fileUrl") or data.get("url")):
            arr = [data]
    outputs = []
    for item in arr:
        if isinstance(item, str):
            outputs.append(rewrite_runninghub_file_url(item))
        elif isinstance(item, dict):
            url = item.get("fileUrl") or item.get("file_url") or item.get("url") or item.get("downloadUrl") or item.get("download_url")
            if isinstance(url, list):
                outputs.extend([rewrite_runninghub_file_url(u) for u in url if u])
            elif url:
                outputs.append(rewrite_runninghub_file_url(url))
    return outputs

async def runninghub_store_remote_output(client, remote):
    remote = rewrite_runninghub_file_url(remote)
    if not str(remote or "").startswith(("http://", "https://")):
        return remote
    try:
        content, content_type = await safe_download_bytes(
            remote, timeout=240.0, max_bytes=50 * 1024 * 1024, allow_private=False
        )
    except Exception as exc:
        logger.warning(f"runninghub_store_remote_output SSRF/下载拦截: {exc}")
        return remote
    ext = runninghub_output_ext(remote, content_type or "")
    filename = f"rh_{uuid.uuid4().hex[:12]}.{ext}"
    path = output_path_for(filename, "output")
    with open(path, "wb") as f:
        f.write(content)
    return output_url_for(filename, "output")

def runninghub_fail_reason(raw):
    data = raw.get("data") if isinstance(raw, dict) else None
    values = []
    if isinstance(data, dict):
        values.extend([data.get("failedReason"), data.get("failReason"), data.get("message"), data.get("error"), data.get("errorMessage")])
    if isinstance(raw, dict):
        values.extend([raw.get("msg"), raw.get("message"), raw.get("error"), raw.get("errorMessage")])
    for value in values:
        if not value:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("exception_message") or value.get("message") or json.dumps(value, ensure_ascii=False)
        return str(value)
    if isinstance(raw, dict) and raw.get("errorCode"):
        return f"RunningHub errorCode={raw.get('errorCode')}"
    return ""

def runninghub_error_detail(message, raw=None, **extra):
    detail = {"message": str(message or "RunningHub 请求失败")}
    detail.update({k: v for k, v in extra.items() if v not in (None, "")})
    if raw is not None:
        detail["raw"] = raw
    return detail

def log_runninghub_error(stage, raw=None, **extra):
    try:
        payload = {"stage": stage, **{k: v for k, v in extra.items() if v not in (None, "")}}
        if raw is not None:
            payload["raw"] = raw
        print(f"RunningHub error: {json.dumps(payload, ensure_ascii=False)[:4000]}")
    except Exception:
        print(f"RunningHub error: {stage}")

def runninghub_infer_workflow_field_type(field_name, field_value):
    key = f"{field_name or ''} {field_value or ''}".lower()
    if re.search(r"\b(image|img|mask|photo|picture)\b", key) or re.search(r"\.(png|jpe?g|webp|gif|bmp)(\?|$)", key, re.I):
        return "IMAGE"
    if re.search(r"\b(video|movie|mp4)\b", key) or re.search(r"\.(mp4|webm|mov|m4v|mkv)(\?|$)", key, re.I):
        return "VIDEO"
    if re.search(r"\b(audio|sound|music|voice)\b", key) or re.search(r"\.(mp3|wav|ogg|m4a|flac|aac)(\?|$)", key, re.I):
        return "AUDIO"
    text = str(field_value or "").strip()
    if text.lower() in {"true", "false"}:
        return "BOOLEAN"
    try:
        if text:
            float(text)
            return "NUMBER"
    except Exception:
        pass
    return "TEXT"

def runninghub_is_workflow_link_value(value):
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )

def runninghub_workflow_node_info_list(workflow_json):
    result = []
    if not isinstance(workflow_json, dict):
        return result
    for node_id, node_content in workflow_json.items():
        inputs = node_content.get("inputs") if isinstance(node_content, dict) else None
        if not isinstance(inputs, dict):
            continue
        for field_name, raw_value in inputs.items():
            if runninghub_is_workflow_link_value(raw_value):
                continue
            if isinstance(raw_value, (dict, list)):
                field_value = json.dumps(raw_value, ensure_ascii=False)
            elif raw_value is None:
                field_value = ""
            else:
                field_value = str(raw_value)
            result.append({
                "nodeId": str(node_id),
                "fieldName": str(field_name),
                "fieldValue": field_value,
                "fieldType": runninghub_infer_workflow_field_type(field_name, field_value),
                "source": "workflow",
            })
    return result

def runninghub_task_endpoint(provider, model):
    raw_model_path = str(model or "").strip()
    model_path = raw_model_path.strip("/")
    if not model_path:
        model_path = RUNNINGHUB_DEFAULT_IMAGE_MODELS[0]
    if raw_model_path.startswith("/openapi/"):
        return runninghub_endpoint_url(provider, raw_model_path)
    if model_path.startswith("openapi/"):
        return runninghub_endpoint_url(provider, f"/{model_path}")
    return runninghub_openapi_url(provider, model_path)

def runninghub_endpoint_alias_for_model(model):
    model_id = str(model or "").strip().strip("/")
    if not model_id:
        return ""
    direct = RUNNINGHUB_MODEL_ENDPOINT_ALIASES.get(model_id)
    if direct:
        return direct
    lowered = model_id.lower()
    if lowered.startswith("gpt-image-2.0/") or lowered.startswith("gpt-image-2/"):
        if "/text-to-image-" in lowered or lowered.endswith("/text-to-image"):
            return "rhart-image-g-2/text-to-image"
        if "/edit-" in lowered or lowered.endswith("/edit"):
            return "rhart-image-g-2/image-to-image"
        if "/image-to-image-" in lowered or lowered.endswith("/image-to-image"):
            return "rhart-image-g-2/image-to-image"
    if lowered.startswith("nano-banana/"):
        if "/text-to-image-" in lowered or lowered.endswith("/text-to-image"):
            return "rhart-image-v1/text-to-image"
        if "/edit-" in lowered or lowered.endswith("/edit"):
            return "rhart-image-v1/edit"
    return ""

def runninghub_registry_fallback():
    image = [
        {"name_en": "gpt-image-2.0/text-to-image-channel-low-price", "endpoint": "rhart-image-g-2/text-to-image", "output_type": "image"},
        {"name_en": "gpt-image-2.0/edit-channel-low-price", "endpoint": "rhart-image-g-2/image-to-image", "output_type": "image"},
        {"name_en": "gpt-image-2/text-to-image-official-stable", "endpoint": "rhart-image-g-2-official/text-to-image", "output_type": "image"},
        {"name_en": "gpt-image-2/image-to-image-official-stable", "endpoint": "rhart-image-g-2-official/image-to-image", "output_type": "image"},
        {"name_en": "nano-banana/text-to-image-official-stable", "endpoint": "rhart-image-v1-official/text-to-image", "output_type": "image"},
        {"name_en": "nano-banana/edit-official-stable", "endpoint": "rhart-image-v1-official/edit", "output_type": "image"},
    ]
    video = [
        {"name_en": "google/veo3.1-fast/text-to-video-channel-low-price", "endpoint": "rhart-video-v3.1-fast/text-to-video", "output_type": "video"},
        {"name_en": "sora-2/text-to-video-official-stable", "endpoint": "rhart-video-s-official/text-to-video", "output_type": "video"},
        {"name_en": "seedance-2.0-global/text-to-video", "endpoint": "bytedance/seedance-2.0-global/text-to-video", "output_type": "video"},
        {"name_en": "seedance-2.0-global/image-to-video", "endpoint": "bytedance/seedance-2.0-global/image-to-video", "output_type": "video"},
    ]
    return image + video

def runninghub_registry_items_from_raw(raw):
    candidates = [raw]
    if isinstance(raw, dict):
        candidates.extend([
            raw.get("data"),
            raw.get("models"),
            raw.get("list"),
            raw.get("items"),
            raw.get("records"),
            raw.get("result"),
        ])
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        if isinstance(candidate, dict):
            nested = (
                candidate.get("models")
                or candidate.get("list")
                or candidate.get("items")
                or candidate.get("records")
                or candidate.get("data")
            )
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []

def runninghub_registry_model_from_id(model_id, output_type=""):
    model_id = str(model_id or "").strip()
    if not model_id:
        return None
    output_type = str(output_type or "").strip().lower() or classify_upstream_model(model_id)
    return {"name_en": model_id, "endpoint": model_id, "output_type": output_type}

async def fetch_runninghub_llm_models(provider=None):
    headers = runninghub_api_headers(provider)
    errors = []
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=20, follow_redirects=True) as client:
        for url in RUNNINGHUB_LLM_MODELS_URLS:
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code >= 400 or looks_like_html_response(resp.text):
                    errors.append(f"{url}: HTTP {resp.status_code} {resp.text[:180]}")
                    continue
                raw = resp.json() if resp.text else {}
                grouped, ids = parse_upstream_models(raw, "openai")
                if ids:
                    return [runninghub_registry_model_from_id(mid, "chat") for mid in ids], {"source": url, "count": len(ids)}
                errors.append(f"{url}: empty")
            except Exception as exc:
                errors.append(f"{url}: {str(exc)[:180]}")
    return [], {"source": "", "count": 0, "errors": errors[-3:]}

async def fetch_runninghub_model_registry(provider=None, include_fallback=True, include_meta=False):
    urls = [
        ("openapi", runninghub_openapi_url(provider, "models")),
        ("github", RUNNINGHUB_MODEL_REGISTRY_URL),
    ]
    if os.path.exists(STATIC_RUNNINGHUB_MODEL_REGISTRY_FILE):
        urls.append(("local", STATIC_RUNNINGHUB_MODEL_REGISTRY_FILE))
    headers = runninghub_api_headers(provider)
    errors = []
    source = ""
    items = []
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=30, follow_redirects=True) as client:
        for source_name, url in urls:
            try:
                if source_name == "local":
                    with open(url, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                else:
                    if source_name == "openapi":
                        validate_safe_url(url, allow_private=False)
                    req_headers = headers if source_name == "openapi" else {"Accept": "application/json"}
                    resp = await client.get(url, headers=req_headers)
                    if resp.status_code >= 400 or looks_like_html_response(resp.text):
                        errors.append(f"{source_name}: HTTP {resp.status_code} {resp.text[:180]}")
                        continue
                    raw = resp.json() if resp.text else []
                parsed = runninghub_registry_items_from_raw(raw)
                if parsed:
                    items = parsed
                    source = source_name
                    break
                errors.append(f"{source_name}: empty")
            except Exception as exc:
                errors.append(f"{source_name}: {str(exc)[:180]}")
                continue
    llm_items, llm_meta = await fetch_runninghub_llm_models(provider)
    combined = [*items]
    seen = {runninghub_model_id(item) for item in combined if runninghub_model_id(item)}
    for item in llm_items:
        mid = runninghub_model_id(item)
        if mid and mid not in seen:
            combined.append(item)
            seen.add(mid)
    if combined:
        meta = {
            "source": source or "llm",
            "openapi_count": len(items),
            "llm_count": len(llm_items),
            "llm_source": llm_meta.get("source") or "",
            "errors": [*errors[-3:], *((llm_meta.get("errors") or [])[-3:])],
        }
        return (combined, meta) if include_meta else combined
    if include_fallback:
        fallback = runninghub_registry_fallback()
        meta = {
            "source": "fallback",
            "openapi_count": 0,
            "llm_count": 0,
            "llm_source": "",
            "errors": [*errors[-3:], *((llm_meta.get("errors") or [])[-3:])],
        }
        return (fallback, meta) if include_meta else fallback
    raise HTTPException(status_code=502, detail=f"拉取 RunningHub 模型注册表失败：{'; '.join(errors[-4:]) or 'unknown error'}")

def runninghub_model_id(item):
    if not isinstance(item, dict):
        return ""
    return str(item.get("name_en") or item.get("id") or item.get("name") or item.get("endpoint") or "").strip()

def runninghub_model_display_name(item, model_id=""):
    if not isinstance(item, dict):
        return ""
    raw_id = str(model_id or runninghub_model_id(item) or "").strip()
    for key in (
        "name_cn", "name_zh", "zh_name", "cn_name", "display_name", "displayName",
        "title", "label", "nameCn", "nameZh", "chinese_name", "chineseName",
    ):
        value = re.sub(r"\s+", " ", str(item.get(key) or "").strip())
        if value and value != raw_id:
            return value[:160]
    name = re.sub(r"\s+", " ", str(item.get("name") or "").strip())
    if name and name != raw_id and not re.fullmatch(r"[A-Za-z0-9_./:-]+", name):
        return name[:160]
    return ""

def runninghub_registry_payload(items):
    grouped = {"image": [], "chat": RUNNINGHUB_FALLBACK_CHAT_MODELS[:], "video": []}
    model_names = {}
    all_ids = []
    for item in items or []:
        mid = runninghub_model_id(item)
        if not mid:
            continue
        display_name = runninghub_model_display_name(item, mid)
        if display_name:
            model_names[mid] = display_name
        output_type = str(item.get("output_type") or item.get("outputType") or "").strip().lower()
        if output_type in ("image", "video"):
            grouped[output_type].append(mid)
            all_ids.append(mid)
    for model in RUNNINGHUB_DEFAULT_IMAGE_MODELS:
        if model not in grouped["image"]:
            grouped["image"].append(model)
            all_ids.append(model)
    for model in RUNNINGHUB_DEFAULT_VIDEO_MODELS:
        if model not in grouped["video"]:
            grouped["video"].append(model)
            all_ids.append(model)
    for model in RUNNINGHUB_FALLBACK_CHAT_MODELS:
        if model not in all_ids:
            all_ids.append(model)
    for key in grouped:
        grouped[key] = sorted(set(grouped[key]))
    return {
        "total": len(set(all_ids)),
        "image_models": grouped["image"],
        "chat_models": grouped["chat"],
        "video_models": grouped["video"],
        "all": sorted(set(all_ids)),
        "model_names": model_names,
        "protocol": "runninghub",
    }

async def runninghub_models_payload(provider=None):
    registry, meta = await fetch_runninghub_model_registry(provider, include_fallback=True, include_meta=True)
    payload = runninghub_registry_payload(registry)
    payload["raw"] = {"registry_count": len(registry), **meta}
    if meta.get("source") == "fallback":
        payload["message"] = "RunningHub 模型接口未返回完整列表，当前显示内置兜底模型。"
    else:
        payload["message"] = f"RunningHub 模型列表来自 {meta.get('source')}"
    return payload

async def runninghub_model_definition(provider, model):
    requested = str(model or "").strip().strip("/")
    registry = await fetch_runninghub_model_registry(provider, include_fallback=True)
    for item in registry:
        mid = runninghub_model_id(item)
        endpoint = str(item.get("endpoint") or "").strip().strip("/")
        if requested and requested in {mid, endpoint, f"/openapi/v2/{endpoint}", f"openapi/v2/{endpoint}"}:
            if endpoint:
                return item
            alias = runninghub_endpoint_alias_for_model(mid or requested)
            if alias:
                patched = dict(item)
                patched["endpoint"] = alias
                return patched
            return item
    endpoint = requested
    if endpoint.startswith("/openapi/v2/"):
        endpoint = endpoint[len("/openapi/v2/"):]
    elif endpoint.startswith("openapi/v2/"):
        endpoint = endpoint[len("openapi/v2/"):]
    endpoint = runninghub_endpoint_alias_for_model(requested) or endpoint
    return {"name_en": requested, "endpoint": endpoint or RUNNINGHUB_DEFAULT_IMAGE_MODELS[0], "output_type": classify_upstream_model(requested), "params": []}

def runninghub_schema_options(field):
    values = []
    for item in (field or {}).get("options") or []:
        if isinstance(item, dict):
            value = item.get("value")
        else:
            value = item
        if value is not None and str(value) != "":
            values.append(str(value))
    return values

def runninghub_schema_value(field, preferred=None):
    preferred = "" if preferred is None else str(preferred).strip()
    options = runninghub_schema_options(field)
    if preferred and (not options or preferred in options):
        return preferred
    default = (field or {}).get("defaultValue")
    if default is not None and str(default) != "":
        return default
    return options[0] if options else preferred

def runninghub_schema_field(params, *keys):
    wanted = {str(k).lower() for k in keys if k}
    for field in params or []:
        if not isinstance(field, dict):
            continue
        names = {str(field.get("fieldKey") or "").lower(), str(field.get("label") or "").lower()}
        if names & wanted:
            return field
    return None

def runninghub_aspect_from_size(size, fallback="1:1"):
    width, height = parse_size_pair(size)
    if width and height:
        divisor = math.gcd(width, height) or 1
        return f"{width // divisor}:{height // divisor}"
    raw = str(size or "").strip().lower()
    if re.fullmatch(r"(auto|\d+\s*:\s*\d+)", raw):
        return raw.replace(" ", "")
    return fallback

def runninghub_resolution_from_size(size, fallback="2k"):
    width, height = parse_size_pair(size)
    if width and height:
        long_edge = max(width, height)
        if long_edge >= 3200:
            return "4k"
        if long_edge >= 1400:
            return "2k"
        return "1k"
    raw = str(size or "").strip().lower()
    return raw if raw in {"1k", "2k", "4k", "480p", "720p", "1080p", "native1080p"} else fallback

def runninghub_size_for_aspect(aspect_ratio, fallback="1280x720"):
    ratio = str(aspect_ratio or "").strip()
    return {
        "9:16": "720x1280",
        "16:9": "1280x720",
        "1:1": "1024x1024",
        "4:3": "1024x768",
        "3:4": "768x1024",
    }.get(ratio, fallback)

def runninghub_is_image_to_video(value):
    text = str(value or "").strip().lower()
    compact = re.sub(r"[\s_/]+", "-", text)
    return "image-to-video" in compact or "-i2v" in compact or compact.endswith("i2v")

def runninghub_apply_schema_defaults(body, params):
    for field in params or []:
        if not isinstance(field, dict):
            continue
        key = str(field.get("fieldKey") or "").strip()
        if not key or key in body:
            continue
        default = field.get("defaultValue")
        options = runninghub_schema_options(field)
        if default is None or default == "":
            if field.get("required") is True and options:
                default = options[0]
            else:
                continue
        ftype = str(field.get("type") or "").upper()
        if ftype == "BOOLEAN":
            body[key] = bool(default) if not isinstance(default, str) else default.lower() == "true"
        elif ftype in {"INT", "INTEGER"}:
            try:
                body[key] = int(default)
            except Exception:
                body[key] = default
        elif ftype == "FLOAT":
            try:
                body[key] = float(default)
            except Exception:
                body[key] = default
        else:
            body[key] = default
    return body

def runninghub_query_status(raw):
    if not isinstance(raw, dict):
        return ""
    values = [
        raw.get("status"),
        raw.get("state"),
        raw.get("taskStatus"),
        raw.get("task_status"),
    ]
    data = raw.get("data")
    if isinstance(data, dict):
        values.extend([data.get("status"), data.get("state"), data.get("taskStatus"), data.get("task_status")])
    for value in values:
        if value is not None:
            return str(value).lower()
    return ""

def runninghub_extract_task_id(raw):
    if not isinstance(raw, dict):
        return ""
    for key in ("taskId", "task_id", "id"):
        if raw.get(key):
            return str(raw[key])
    data = raw.get("data")
    if isinstance(data, dict):
        for key in ("taskId", "task_id", "id"):
            if data.get(key):
                return str(data[key])
    return ""

def runninghub_extract_image(raw):
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail="RunningHub 返回格式不是 JSON 对象")
    containers = [raw]
    data = raw.get("data")
    if isinstance(data, dict):
        containers.append(data)
    for container in containers:
        results = container.get("results") or container.get("result") or container.get("outputs") or container.get("output")
        if isinstance(results, dict):
            results = [results]
        if isinstance(results, list):
            for item in results:
                if isinstance(item, str) and item.startswith(("http://", "https://")):
                    return {"type": "url", "value": rewrite_runninghub_file_url(item)}
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "url" and item.get("value"):
                    return {"type": "url", "value": rewrite_runninghub_file_url(item["value"])}
                if item.get("type") == "b64" and item.get("value"):
                    return {"type": "b64", "value": item["value"], "mime_type": item.get("mime_type") or "image/png"}
                url = item.get("url") or item.get("fileUrl") or item.get("file_url") or item.get("download_url") or item.get("imageUrl") or item.get("image_url")
                if isinstance(url, list) and url:
                    url = url[0]
                if isinstance(url, str) and url:
                    return {"type": "url", "value": rewrite_runninghub_file_url(url)}
    image = extract_image(raw)
    if image.get("type") == "url":
        image["value"] = rewrite_runninghub_file_url(image.get("value"))
    return image

async def runninghub_upload_reference(client, provider, ref):
    path = output_file_from_url(ref.get("url", ""))
    if not path:
        value = ref.get("url", "")
        return value if str(value).startswith(("http://", "https://")) else ""
    upload_url = runninghub_openapi_url(provider, "media/upload/binary")
    headers = {"Authorization": bearer_auth_value(runninghub_api_key(provider, use_wallet=True)), "Accept": "application/json"}
    with open(path, "rb") as fh:
        files = {"file": (os.path.basename(path), fh, content_type_for_path(path))}
        response = await client.post(upload_url, headers=headers, files=files, timeout=120)
    response.raise_for_status()
    raw = response.json()
    data = raw.get("data") if isinstance(raw, dict) else None
    candidates = [raw, data] if isinstance(data, dict) else [raw]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        value = item.get("download_url") or item.get("downloadUrl") or item.get("url") or item.get("fileUrl") or item.get("file_url")
        if value:
            return str(value)
    raise HTTPException(status_code=502, detail=f"RunningHub 上传图片未返回 download_url：{raw}")

async def wait_for_runninghub_image_task(client, provider, task_id):
    query_url = runninghub_openapi_url(provider, "query")
    deadline = time.monotonic() + 1800
    last_payload = None
    while time.monotonic() < deadline:
        await asyncio.sleep(2)
        response = await client.post(query_url, headers=runninghub_api_headers(provider), json={"taskId": task_id})
        response.raise_for_status()
        raw = response.json()
        last_payload = raw
        status = runninghub_query_status(raw)
        if status in {"success", "succeeded", "completed", "complete", "finished", "finish", "done", "3"}:
            return raw
        if status in {"failed", "fail", "error", "canceled", "cancelled", "4"}:
            raise HTTPException(status_code=502, detail=f"RunningHub 任务失败：{raw}")
        try:
            return {"data": {"results": [runninghub_extract_image(raw)]}}
        except HTTPException:
            pass
    raise HTTPException(status_code=504, detail=f"RunningHub 生图任务超时：{last_payload}")

RUNNINGHUB_ENTRY_MODEL_RE = re.compile(r"^(app|workflow):(.+)$")

def rh_field_kind(field):
    field = field or {}
    t = str(field.get("fieldType") or "").strip().upper()
    if t == "IMAGE":
        return "image"
    if t == "VIDEO":
        return "video"
    if t == "AUDIO":
        return "audio"
    if t == "SLIDER":
        return "slider"
    if t in ("NUMBER", "FLOAT", "INTEGER", "INT"):
        return "number"
    if t in ("BOOLEAN", "BOOL"):
        return "boolean"
    key = f"{field.get('fieldName') or ''} {field.get('fieldValue') or ''}".lower()
    if re.search(r"\b(image|img|mask|photo|picture)\b", key) or re.search(r"\.(png|jpe?g|webp|gif|bmp)(\?|$)", key, re.I):
        return "image"
    if re.search(r"\b(video|movie|mp4)\b", key) or re.search(r"\.(mp4|webm|mov|m4v|mkv)(\?|$)", key, re.I):
        return "video"
    if re.search(r"\b(audio|sound|music|voice)\b", key) or re.search(r"\.(mp3|wav|ogg|m4a|flac|aac)(\?|$)", key, re.I):
        return "audio"
    return "text"

def rh_field_role(field):
    kind = rh_field_kind(field)
    if kind in ("image", "video", "audio", "number", "slider", "boolean"):
        return kind
    field = field or {}
    text = f"{field.get('fieldName') or ''} {field.get('label') or ''} {field.get('group') or ''}".lower()
    if re.search(r"prompt|positive|negative|text|caption|description|关键词|提示词|正向|负向", text):
        return "prompt"
    return "text"

def _rh_natural_cmp(x, y):
    if x == y:
        return 0
    if x.isdigit() and y.isdigit():
        ix, iy = int(x), int(y)
        return (ix > iy) - (ix < iy)
    return (x > y) - (x < y)

def _rh_field_cmp(a, b):
    ak, bk = rh_field_kind(a), rh_field_kind(b)
    if ak == "image" and bk == "image":
        try:
            ao = int(a.get("imageOrder") or 0) or 9999
        except Exception:
            ao = 9999
        try:
            bo = int(b.get("imageOrder") or 0) or 9999
        except Exception:
            bo = 9999
        if ao != bo:
            return ao - bo
    if ak == "image" and bk != "image":
        return -1
    if ak != "image" and bk == "image":
        return 1
    node_cmp = _rh_natural_cmp(str(a.get("nodeId") or ""), str(b.get("nodeId") or ""))
    if node_cmp != 0:
        return node_cmp
    fa, fb = str(a.get("fieldName") or ""), str(b.get("fieldName") or "")
    return (fa > fb) - (fa < fb)

def rh_sort_fields(fields):
    return sorted(list(fields or []), key=functools.cmp_to_key(_rh_field_cmp))

def rh_field_indexes(fields):
    counters = {"image": 0, "video": 0, "audio": 0}
    mapping = {}
    for field in rh_sort_fields(fields):
        kind = rh_field_kind(field)
        if kind in counters:
            mapping[(str(field.get("nodeId") or ""), str(field.get("fieldName") or ""))] = counters[kind]
            counters[kind] += 1
    return mapping

def rh_default_value(field):
    value = (field or {}).get("fieldValue")
    if isinstance(value, list):
        value = value[0] if value else ""
    if value is None or isinstance(value, dict):
        return ""
    return str(value)

SEED_UINT32_MAX = 4294967295

def rh_is_seed_like_name(*parts) -> bool:
    text = " ".join(str(part or "") for part in parts).lower()
    return any(key in text for key in ("seed", "noise", "随机", "种子", "噪"))

def normalize_seed_uint32(value):
    try:
        if isinstance(value, bool):
            return value
        raw = str(value).strip()
        if not raw:
            return value
        num = int(float(raw))
    except Exception:
        return value
    if 0 <= num <= SEED_UINT32_MAX:
        return value
    safe = ((abs(num) - 1) % SEED_UINT32_MAX) + 1
    return str(safe) if isinstance(value, str) else safe

def sanitize_seed_like_workflow_values(value, parent_key=""):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if rh_is_seed_like_name(key) and not isinstance(item, (dict, list)):
                result[key] = normalize_seed_uint32(item)
            else:
                result[key] = sanitize_seed_like_workflow_values(item, key)
        return result
    if isinstance(value, list):
        return [sanitize_seed_like_workflow_values(item, parent_key) for item in value]
    if rh_is_seed_like_name(parent_key):
        return normalize_seed_uint32(value)
    return value

def sanitize_runninghub_node_info_list(items):
    result = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        clean = dict(item)
        if rh_is_seed_like_name(clean.get("fieldName"), clean.get("label"), clean.get("note")):
            clean["fieldValue"] = normalize_seed_uint32(clean.get("fieldValue"))
        result.append(clean)
    return result

def rh_random_field_value(field):
    def _num(raw, default):
        try:
            s = str(raw).strip()
            if s == "" or s.lower() == "none":
                return default
            return float(s)
        except Exception:
            return default
    looks_seed = rh_is_seed_like_name((field or {}).get("fieldName"), (field or {}).get("label"), (field or {}).get("note"))
    lo = _num((field or {}).get("min"), 0.0)
    hi = _num((field or {}).get("max"), float(SEED_UINT32_MAX) if looks_seed else 999999.0)
    if looks_seed:
        hi = min(hi, float(SEED_UINT32_MAX))
        lo = max(0.0, min(lo, hi))
    if hi < lo:
        lo, hi = hi, lo
    step = _num((field or {}).get("step"), 1.0)
    value = random.uniform(lo, hi)
    if step and step > 0:
        value = lo + round((value - lo) / step) * step
    if float(step).is_integer() and float(lo).is_integer() and float(hi).is_integer():
        return str(int(round(value)))
    return str(value)

def runninghub_entry_config_from_model(provider, model):
    """解析 model=app:ID / workflow:ID，返回 {kind,id,fields,optionalImageMode,workflowJson} 或 None。"""
    text = str(model or "").strip()
    match = RUNNINGHUB_ENTRY_MODEL_RE.match(text)
    if not match:
        return None
    kind = match.group(1)
    entry_id = match.group(2).strip()
    if not entry_id:
        return None
    if kind == "workflow":
        key = runninghub_workflow_store_key(entry_id)
        with RUNNINGHUB_WORKFLOW_LOCK:
            store = load_runninghub_workflow_store()
        cfg = runninghub_select_workflow_config(store.get(key), runninghub_provider_workflow_config(key), key)
        if not isinstance(cfg, dict):
            # 退回到 provider 列表中的内联条目
            entry = next(
                (e for e in (provider.get("rh_workflows") or []) if runninghub_entry_id(e, "workflow") == entry_id),
                None,
            )
            if not entry:
                return None
            cfg = {
                "fields": entry.get("fields") or [],
                "optionalImageMode": entry.get("optionalImageMode") or "prune-workflow",
                "workflowJson": entry.get("workflowJson") if isinstance(entry.get("workflowJson"), dict) else {},
            }
        return {
            "kind": "workflow",
            "id": entry_id,
            "fields": cfg.get("fields") or [],
            "optionalImageMode": cfg.get("optionalImageMode") or "prune-workflow",
            "workflowJson": cfg.get("workflowJson") if isinstance(cfg.get("workflowJson"), dict) else {},
        }
    entry = next(
        (e for e in (provider.get("rh_apps") or []) if runninghub_entry_id(e, "app") == entry_id),
        None,
    )
    if not entry:
        return None
    return {
        "kind": "app",
        "id": entry_id,
        "fields": entry.get("fields") or [],
        "optionalImageMode": "",
        "workflowJson": {},
    }

async def runninghub_upload_local_to_filename(client, provider, url, use_wallet=False):
    """把本地/远程素材上传到 RunningHub /task/openapi/upload，返回 fileName（供 nodeInfoList 使用）。"""
    text = str(url or "").strip()
    if not text:
        return ""
    path = runninghub_local_asset_path(text)
    if path:
        filename = os.path.basename(path)
        content_type = content_type_for_path(path)
        with open(path, "rb") as fh:
            content = fh.read()
    elif text.startswith(("http://", "https://")):
        try:
            content, content_type = await safe_download_bytes(
                text, timeout=120.0, max_bytes=50 * 1024 * 1024, allow_private=False
            )
        except Exception as exc:
            logger.warning(f"runninghub_upload_asset_from_reference SSRF拦截: {exc}")
            raise HTTPException(status_code=400, detail=f"下载素材失败或被安全策略拦截: {exc}") from exc
        content_type = content_type or "application/octet-stream"
        filename = os.path.basename(urllib.parse.urlsplit(text).path) or "asset.bin"
    else:
        return ""
    if not content:
        return ""
    api_key = runninghub_api_key(provider, use_wallet=use_wallet)
    upload_url = runninghub_endpoint_url(provider, "/task/openapi/upload")
    files = {"file": (filename, content, content_type)}
    data = {"apiKey": api_key, "fileType": "input"}
    response = await client.post(upload_url, headers=runninghub_app_headers(False, use_wallet), data=data, files=files)
    raw = response.json()
    if isinstance(raw, dict) and raw.get("code") in (0, "0") and isinstance(raw.get("data"), dict) and raw["data"].get("fileName"):
        return raw["data"]["fileName"]
    raise HTTPException(status_code=502, detail=(raw.get("msg") if isinstance(raw, dict) else "") or f"RunningHub 上传素材失败：{raw}")

async def generate_runninghub_entry_image(prompt, size, model, reference_images, provider, entry):
    """运行 RunningHub 工作流 / AI 应用（与智能画布一致的运行方式），返回首张图片结果。"""
    kind = entry["kind"]
    entry_id = entry["id"]
    fields = rh_sort_fields([f for f in (entry.get("fields") or []) if isinstance(f, dict) and f.get("enabled") is True])
    idx_map = rh_field_indexes(fields)
    use_wallet = False
    timeout = httpx.Timeout(connect=20.0, read=1800.0, write=240.0, pool=20.0)
    aspect = runninghub_aspect_from_size(size, "")
    resolution = runninghub_resolution_from_size(size, "")
    width, height = parse_size_pair(size)
    def requested_size_field_value(field):
        names = {
            str(field.get("fieldName") or "").strip().lower(),
            str(field.get("fieldKey") or "").strip().lower(),
            str(field.get("label") or "").strip().lower(),
        }
        if aspect and names & {"aspectratio", "aspect_ratio", "ratio"}:
            return runninghub_schema_value(field, aspect)
        if resolution and "resolution" in names:
            return runninghub_schema_value(field, resolution)
        if width and "width" in names:
            return width
        if height and "height" in names:
            return height
        return None
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=timeout) as client:
        uploaded = []
        for ref in (reference_images or [])[:ONLINE_IMAGE_REFERENCE_MAX]:
            ref_url = ref.get("url") if isinstance(ref, dict) else ref
            if not ref_url:
                continue
            file_name = await runninghub_upload_local_to_filename(client, provider, ref_url, use_wallet)
            if file_name:
                uploaded.append(file_name)

        node_info_list = []
        prompt_text = str(prompt or "").strip()
        for field in fields:
            node_id = str(field.get("nodeId") or "").strip()
            field_name = str(field.get("fieldName") or "").strip()
            if not node_id or not field_name:
                continue
            kind_f = rh_field_kind(field)
            if kind_f in ("image", "video", "audio"):
                if kind_f != "image":
                    continue  # 在线生图仅提供图片素材
                index = idx_map.get((node_id, field_name), 0)
                value = uploaded[index] if index < len(uploaded) else ""
                if not value:
                    # 工作流可选图（required!=True）无输入则跳过；必填图回退默认值
                    if field.get("required") is True:
                        value = rh_default_value(field)
                        if not value:
                            continue
                    else:
                        continue
                node_info_list.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": value})
            elif rh_field_role(field) == "prompt":
                value = prompt_text or rh_default_value(field)
                node_info_list.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": value})
            elif kind_f == "number" and field.get("random_enabled") is True:
                node_info_list.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": rh_random_field_value(field)})
            else:
                value = requested_size_field_value(field)
                if value is None:
                    value = rh_default_value(field)
                node_info_list.append({"nodeId": node_id, "fieldName": field_name, "fieldValue": value})

        api_key = runninghub_api_key(provider, use_wallet=use_wallet)
        if kind == "workflow":
            submit_url = runninghub_endpoint_url(provider, "/task/openapi/create")
            body = {"apiKey": api_key, "workflowId": entry_id, "addMetadata": True}
            if node_info_list:
                body["nodeInfoList"] = node_info_list
        else:
            submit_url = runninghub_endpoint_url(provider, "/task/openapi/ai-app/run")
            body = {"apiKey": api_key, "webappId": entry_id, "nodeInfoList": node_info_list}

        response = await client.post(submit_url, headers=runninghub_app_headers(True, use_wallet), json=body)
        raw = response.json()
        if not (isinstance(raw, dict) and raw.get("code") in (0, "0")):
            raise HTTPException(status_code=502, detail=(raw.get("msg") if isinstance(raw, dict) else "") or f"RunningHub 提交失败：{raw}")
        task_id = raw.get("data", {}).get("taskId") if isinstance(raw.get("data"), dict) else ""
        if not task_id:
            raise HTTPException(status_code=502, detail=f"RunningHub 未返回 taskId：{raw}")

        query_url = runninghub_endpoint_url(provider, "/task/openapi/outputs")
        deadline = time.monotonic() + 1800
        last_payload = None
        while time.monotonic() < deadline:
            await asyncio.sleep(2.5)
            query_response = await client.post(query_url, headers=runninghub_app_headers(True), json={"apiKey": api_key, "taskId": task_id})
            query_raw = query_response.json()
            last_payload = query_raw
            code = query_raw.get("code") if isinstance(query_raw, dict) else None
            if code in (0, "0"):
                outputs = runninghub_extract_outputs(query_raw.get("data"))
                for remote in outputs:
                    if str(remote or "").startswith(("http://", "https://", "/output/", "/assets/")):
                        return {"type": "url", "value": str(remote)}, query_raw
                raise HTTPException(status_code=502, detail=f"RunningHub 任务无图片输出：{query_raw}")
            if code in (805, "805"):
                raise HTTPException(status_code=502, detail=f"RunningHub 任务失败：{runninghub_fail_reason(query_raw) or query_raw}")
            # 804 运行中 / 813 排队中 / 其他状态继续轮询
        raise HTTPException(status_code=504, detail=f"RunningHub 任务超时：{last_payload}")

async def generate_runninghub_provider_image(prompt, size, model, reference_images=None, provider=None):
    entry = runninghub_entry_config_from_model(provider, model)
    if entry:
        return await generate_runninghub_entry_image(prompt, size, model, reference_images, provider, entry)
    model_def = await runninghub_model_definition(provider, model)
    endpoint = runninghub_task_endpoint(provider, model_def.get("endpoint") or model)
    params = model_def.get("params") if isinstance(model_def.get("params"), list) else []
    aspect = runninghub_aspect_from_size(size, "1:1")
    resolution = runninghub_resolution_from_size(size, "2k")
    body = {"prompt": prompt}
    if runninghub_schema_field(params, "aspectRatio"):
        field = runninghub_schema_field(params, "aspectRatio")
        body["aspectRatio"] = runninghub_schema_value(field, aspect)
    elif runninghub_schema_field(params, "ratio"):
        field = runninghub_schema_field(params, "ratio")
        body["ratio"] = runninghub_schema_value(field, aspect)
    if runninghub_schema_field(params, "resolution"):
        field = runninghub_schema_field(params, "resolution")
        body["resolution"] = runninghub_schema_value(field, resolution)
    width, height = parse_size_pair(size)
    if width and height:
        if runninghub_schema_field(params, "width"):
            body["width"] = width
        if runninghub_schema_field(params, "height"):
            body["height"] = height
    quality_field = runninghub_schema_field(params, "quality")
    if quality_field:
        body["quality"] = runninghub_schema_value(quality_field, "medium")
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=httpx.Timeout(connect=20.0, read=1800.0, write=180.0, pool=20.0)) as client:
        image_urls = []
        for ref in (reference_images or [])[:ONLINE_IMAGE_REFERENCE_MAX]:
            url = await runninghub_upload_reference(client, provider, ref)
            if url:
                image_urls.append(url)
        if image_urls:
            image_field = runninghub_schema_field(params, "imageUrls", "imageUrl", "images", "image")
            key = str((image_field or {}).get("fieldKey") or "imageUrls")
            if key.endswith("s") or (image_field or {}).get("multipleInputs") is True:
                body[key] = image_urls
            else:
                body[key] = image_urls[0]
        runninghub_apply_schema_defaults(body, params)
        response = await client.post(endpoint, headers=runninghub_json_headers(provider), json=body)
        response.raise_for_status()
        raw = response.json()
        try:
            return runninghub_extract_image(raw), raw
        except HTTPException:
            task_id = runninghub_extract_task_id(raw)
            if not task_id:
                raise HTTPException(status_code=502, detail=f"RunningHub 未返回 taskId 或图片结果：{raw}")
        result = await wait_for_runninghub_image_task(client, provider, task_id)
        return runninghub_extract_image(result), result

async def wait_for_runninghub_openapi_task(client, provider, task_id, output_kind=""):
    query_url = runninghub_openapi_url(provider, "query")
    deadline = time.monotonic() + 1800
    last_payload = None
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        response = await client.post(query_url, headers=runninghub_json_headers(provider), json={"taskId": task_id})
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # RunningHub gateway may return transient empty-body 5xx while the task is
            # still running. Skip this poll round instead of failing the whole task.
            if 500 <= exc.response.status_code < 600 or exc.response.status_code == 429:
                last_payload = last_payload or {"transient": exc.response.status_code}
                continue
            raise
        raw = response.json()
        last_payload = raw
        status = runninghub_query_status(raw).upper()
        if status in {"SUCCESS", "SUCCEEDED", "COMPLETED", "COMPLETE", "FINISHED", "DONE", "3"}:
            return raw
        if status in {"FAILED", "FAIL", "ERROR", "CANCEL", "CANCELED", "CANCELLED", "4"}:
            raise HTTPException(status_code=502, detail=f"RunningHub 任务失败（task_id={task_id}）：{runninghub_fail_reason(raw) or raw}")
        if output_kind == "video" and video_output_urls(raw):
            return raw
    raise HTTPException(status_code=504, detail=f"RunningHub 任务超时（task_id={task_id}）：{last_payload or task_id}")

async def generate_runninghub_video(payload, provider):
    model_def = await runninghub_model_definition(provider, payload.model)
    endpoint = runninghub_task_endpoint(provider, model_def.get("endpoint") or payload.model)
    image_to_video = runninghub_is_image_to_video(payload.model) or runninghub_is_image_to_video(model_def.get("endpoint")) or runninghub_is_image_to_video(endpoint)
    params = model_def.get("params") if isinstance(model_def.get("params"), list) else []
    body = {"prompt": str(payload.prompt or "")}
    aspect = str(payload.aspect_ratio or "16:9").strip() or "16:9"
    if runninghub_schema_field(params, "aspectRatio"):
        field = runninghub_schema_field(params, "aspectRatio")
        body["aspectRatio"] = runninghub_schema_value(field, aspect)
    if runninghub_schema_field(params, "ratio"):
        field = runninghub_schema_field(params, "ratio")
        body["ratio"] = runninghub_schema_value(field, aspect)
    if runninghub_schema_field(params, "size"):
        field = runninghub_schema_field(params, "size")
        body["size"] = runninghub_schema_value(field, runninghub_size_for_aspect(aspect))
    if runninghub_schema_field(params, "duration"):
        field = runninghub_schema_field(params, "duration")
        body["duration"] = runninghub_schema_value(field, str(max(1, min(60, int(payload.duration or 5)))))
    if runninghub_schema_field(params, "resolution"):
        field = runninghub_schema_field(params, "resolution")
        body["resolution"] = runninghub_schema_value(field, str(payload.resolution or "720p").lower())
    if runninghub_schema_field(params, "generateAudio"):
        body["generateAudio"] = bool(payload.generate_audio)
    if runninghub_schema_field(params, "watermark"):
        body["watermark"] = bool(payload.watermark)
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=VIDEO_POLL_TIMEOUT) as client:
        image_refs = []
        for ref in (payload.images or [])[:10]:
            ref_url = getattr(ref, "url", "") or ""
            if ref_url:
                up = await runninghub_upload_reference(client, provider, {"url": ref_url})
                if up:
                    image_refs.append({"url": up, "role": str(getattr(ref, "role", "") or "").strip().lower()})
        image_urls = [item["url"] for item in image_refs if item.get("url")]
        if image_urls:
            first_url = next((item["url"] for item in image_refs if item.get("role") in {"first_frame", "first"}), image_urls[0])
            last_url = next((item["url"] for item in image_refs if item.get("role") in {"last_frame", "last"}), image_urls[1] if len(image_urls) > 1 else "")
            first_field = runninghub_schema_field(params, "firstFrameUrl", "first_frame_url", "firstFrameImage", "first_frame_image")
            last_field = runninghub_schema_field(params, "lastFrameUrl", "last_frame_url", "lastFrameImage", "last_frame_image")
            if first_field and first_url:
                body[str(first_field.get("fieldKey"))] = first_url
            if last_field and last_url:
                body[str(last_field.get("fieldKey"))] = last_url
            image_field = runninghub_schema_field(params, "imageUrls", "image_urls", "imageUrl", "image_url", "referenceImages", "referenceImageUrls")
            key = str((image_field or {}).get("fieldKey") or "")
            if key and key in body:
                pass
            elif key and (key.endswith("s") or (image_field or {}).get("multipleInputs") is True):
                body[key] = image_urls
            elif key:
                body[key] = image_urls[0]
            elif image_to_video and "firstFrameUrl" not in body:
                body["firstFrameUrl"] = first_url
        first_required = runninghub_schema_field(params, "firstFrameUrl", "first_frame_url", "firstFrameImage", "first_frame_image")
        if first_required and not body.get(str(first_required.get("fieldKey") or "")):
            raise HTTPException(status_code=400, detail="当前 RunningHub 模型是图生视频，需要连接一张首帧图片后再生成。")
        if image_to_video and not body.get("firstFrameUrl") and not image_urls:
            raise HTTPException(status_code=400, detail="当前 RunningHub 模型是图生视频，需要连接一张首帧图片后再生成。")
        runninghub_apply_schema_defaults(body, params)
        response = await client.post(endpoint, headers=runninghub_json_headers(provider), json=body)
        response.raise_for_status()
        raw = response.json()
        task_id = runninghub_extract_task_id(raw)
        if not task_id:
            fail_reason = runninghub_fail_reason(raw)
            if fail_reason:
                raise HTTPException(status_code=502, detail=f"RunningHub 视频接口错误：{fail_reason}")
        result = raw
        if task_id and not video_output_urls(raw):
            result = await wait_for_runninghub_openapi_task(client, provider, task_id, "video")
        urls = video_output_urls(result)
        if not urls:
            outputs = runninghub_extract_outputs(result)
            urls = [url for url in outputs if str(url).startswith(("http://", "https://", "/output/", "/assets/"))]
        if not urls:
            raise HTTPException(status_code=502, detail=f"RunningHub 视频生成成功但没有返回视频：{result}")
        local_urls = [await save_remote_video_to_output(url, prefix="rh_video_") for url in urls]
        return {"videos": local_urls, "task_id": task_id, "raw": result}



# --- Sliced from online.py lines 7450-8064 ---
@router.get("/api/runninghub/app-info")
async def runninghub_app_info(webappId: str = ""):
    webapp_id = str(webappId or "").strip()
    if not webapp_id:
        raise HTTPException(status_code=400, detail="webappId 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider)
    url = runninghub_endpoint_url(provider, f"/api/webapp/apiCallDemo?apiKey={urllib.parse.quote(api_key)}&webappId={urllib.parse.quote(webapp_id)}")
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=httpx.Timeout(connect=20.0, read=120.0, write=30.0, pool=20.0)) as client:
        try:
            response = await client.get(url, headers=runninghub_app_headers(False))
            raw = response.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text[:500]) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"请求 RunningHub 应用信息失败：{exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=json.dumps(raw, ensure_ascii=False)[:500])
    if isinstance(raw, dict) and raw.get("code") not in (0, "0", None):
        raise HTTPException(status_code=400, detail=raw.get("msg") or f"RunningHub 查询失败 code={raw.get('code')}")
    data = raw.get("data") if isinstance(raw, dict) else {}
    return {"success": True, "data": data or {}}

@router.post("/api/runninghub/submit")
async def runninghub_submit(payload: RunningHubSubmitRequest):
    webapp_id = str(payload.webappId or "").strip()
    if not webapp_id:
        raise HTTPException(status_code=400, detail="webappId 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider, use_wallet=payload.useWallet)
    body = {
        "apiKey": api_key,
        "webappId": webapp_id,
        "nodeInfoList": sanitize_runninghub_node_info_list(payload.nodeInfoList or []),
    }
    instance_type = str(payload.instanceType or "").strip()
    if instance_type:
        body["instanceType"] = instance_type
    url = runninghub_endpoint_url(provider, "/task/openapi/ai-app/run")
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=httpx.Timeout(connect=20.0, read=180.0, write=120.0, pool=20.0)) as client:
        try:
            response = await client.post(url, headers=runninghub_app_headers(True, payload.useWallet), json=body)
            raw = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=runninghub_error_detail(f"提交 RunningHub 任务失败：{exc}", endpoint=url, webappId=webapp_id)) from exc
    if response.status_code >= 400:
        log_runninghub_error("submit-http", raw, endpoint=url, webappId=webapp_id, status=response.status_code)
        raise HTTPException(status_code=response.status_code, detail=runninghub_error_detail(f"RunningHub HTTP {response.status_code}", raw, endpoint=url, webappId=webapp_id))
    if isinstance(raw, dict) and raw.get("code") in (0, "0"):
        task_id = raw.get("data", {}).get("taskId") if isinstance(raw.get("data"), dict) else ""
        if not task_id:
            raise HTTPException(status_code=502, detail=runninghub_error_detail("RunningHub 未返回 taskId", raw, endpoint=url, webappId=webapp_id))
        return {"success": True, "data": {"taskId": task_id, "raw": raw}}
    log_runninghub_error("submit-rejected", raw, endpoint=url, webappId=webapp_id)
    raise HTTPException(status_code=400, detail=runninghub_error_detail(runninghub_fail_reason(raw) or "RunningHub 提交失败", raw, endpoint=url, webappId=webapp_id))

@router.post("/api/runninghub/workflow-submit")
async def runninghub_workflow_submit(payload: RunningHubWorkflowSubmitRequest):
    workflow_id = str(payload.workflowId or "").strip()
    if not workflow_id:
        raise HTTPException(status_code=400, detail="workflowId 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider, use_wallet=payload.useWallet)
    body = {
        "apiKey": api_key,
        "workflowId": workflow_id,
        "addMetadata": True,
    }
    if payload.nodeInfoList:
        body["nodeInfoList"] = sanitize_runninghub_node_info_list(payload.nodeInfoList)
    workflow_payload = payload.workflow
    if workflow_payload:
        if isinstance(workflow_payload, (dict, list)):
            body["workflow"] = json.dumps(sanitize_seed_like_workflow_values(workflow_payload), ensure_ascii=False)
        else:
            body["workflow"] = str(workflow_payload)
    url = runninghub_endpoint_url(provider, "/task/openapi/create")
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=httpx.Timeout(connect=20.0, read=180.0, write=120.0, pool=20.0)) as client:
        try:
            response = await client.post(url, headers=runninghub_app_headers(True, payload.useWallet), json=body)
            raw = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=runninghub_error_detail(f"提交 RunningHub 工作流失败：{exc}", endpoint=url, workflowId=workflow_id)) from exc
    if response.status_code >= 400:
        log_runninghub_error("workflow-submit-http", raw, endpoint=url, workflowId=workflow_id, status=response.status_code)
        raise HTTPException(status_code=response.status_code, detail=runninghub_error_detail(f"RunningHub HTTP {response.status_code}", raw, endpoint=url, workflowId=workflow_id))
    if isinstance(raw, dict) and raw.get("code") in (0, "0"):
        task_id = raw.get("data", {}).get("taskId") if isinstance(raw.get("data"), dict) else ""
        if not task_id:
            raise HTTPException(status_code=502, detail=runninghub_error_detail("RunningHub 工作流未返回 taskId", raw, endpoint=url, workflowId=workflow_id))
        return {"success": True, "data": {"taskId": task_id, "raw": raw}}
    log_runninghub_error("workflow-submit-rejected", raw, endpoint=url, workflowId=workflow_id)
    raise HTTPException(status_code=400, detail=runninghub_error_detail(runninghub_fail_reason(raw) or "RunningHub 工作流提交失败", raw, endpoint=url, workflowId=workflow_id))

@router.get("/api/runninghub/workflow-info")
async def runninghub_workflow_info(workflowId: str = ""):
    workflow_id = str(workflowId or "").strip()
    if not workflow_id:
        raise HTTPException(status_code=400, detail="workflowId 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider)
    url = runninghub_endpoint_url(provider, "/api/openapi/getJsonApiFormat")
    body = {"apiKey": api_key, "workflowId": workflow_id}
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=20.0)) as client:
        try:
            response = await client.post(url, headers=runninghub_app_headers(True), json=body)
            raw = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"拉取 RunningHub 工作流参数失败：{exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=json.dumps(raw, ensure_ascii=False)[:800])
    if not isinstance(raw, dict) or raw.get("code") not in (0, "0"):
        raise HTTPException(status_code=400, detail=(raw.get("msg") if isinstance(raw, dict) else "") or f"RunningHub 工作流参数拉取失败：{raw}")
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    prompt = data.get("prompt")
    workflow_json = {}
    if isinstance(prompt, str) and prompt.strip():
        try:
            workflow_json = json.loads(prompt)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"RunningHub 工作流 JSON 解析失败：{exc}") from exc
    elif isinstance(prompt, dict):
        workflow_json = prompt
    node_info_list = runninghub_workflow_node_info_list(workflow_json)
    return {"success": True, "data": {"workflowId": workflow_id, "nodeInfoList": node_info_list, "raw": raw}}

@router.get("/api/runninghub/workflows")
def list_runninghub_workflows():
    providers = load_api_providers()
    hidden_ids = runninghub_saved_hidden_workflow_ids()
    for provider in providers:
        if provider.get("id") != "runninghub":
            continue
        for entry in provider.get("rh_workflows") or []:
            workflow_id = runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id"))
            if workflow_id and entry.get("hidden") is True:
                hidden_ids.add(workflow_id)
    with RUNNINGHUB_WORKFLOW_LOCK:
        store = load_runninghub_workflow_store()
    merged = {workflow_id: cfg for workflow_id, cfg in store.items() if isinstance(cfg, dict) and workflow_id not in hidden_ids}
    for provider in providers:
        if provider.get("id") != "runninghub":
            continue
        for entry in provider.get("rh_workflows") or []:
            workflow_id = runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id"))
            if not workflow_id:
                continue
            if entry.get("hidden") is True:
                merged.pop(workflow_id, None)
                continue
            provider_cfg = runninghub_provider_workflow_config(workflow_id)
            if provider_cfg:
                merged[workflow_id] = runninghub_select_workflow_config(merged.get(workflow_id), provider_cfg, workflow_id)
    items = []
    for workflow_id, cfg in merged.items():
        if not isinstance(cfg, dict):
            continue
        items.append({
            "workflowId": workflow_id,
            "title": cfg.get("title") or workflow_id,
            "fieldCount": len(cfg.get("fields") or []),
            "updatedAt": cfg.get("updatedAt"),
            "description": cfg.get("description") or "",
        })
    items.sort(key=lambda item: item["title"])
    return {"workflows": items}

@router.get("/api/runninghub/workflows/{workflow_id:path}")
def get_runninghub_workflow(workflow_id: str):
    key = runninghub_workflow_store_key(workflow_id)
    if not key:
        raise HTTPException(status_code=400, detail="workflowId 必填")
    with RUNNINGHUB_WORKFLOW_LOCK:
        store = load_runninghub_workflow_store()
    cfg = store.get(key)
    provider_cfg = runninghub_provider_workflow_config(key)
    cfg = runninghub_select_workflow_config(cfg, provider_cfg, key)
    if not isinstance(cfg, dict):
        raise HTTPException(status_code=404, detail="RunningHub 工作流未找到")
    return {"workflow": cfg}

@router.post("/api/runninghub/workflows/fetch")
async def fetch_runninghub_workflow(payload: RunningHubWorkflowConfig):
    workflow_id = runninghub_workflow_store_key(payload.workflowId)
    if not workflow_id:
        raise HTTPException(status_code=400, detail="workflowId 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider)
    url = runninghub_endpoint_url(provider, "/api/openapi/getJsonApiFormat")
    body = {"apiKey": api_key, "workflowId": workflow_id}
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=20.0)) as client:
        try:
            response = await client.post(url, headers=runninghub_app_headers(True), json=body)
            raw = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch RunningHub workflow parameters: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=json.dumps(raw, ensure_ascii=False)[:800])
    if not isinstance(raw, dict) or raw.get("code") not in (0, "0"):
        raise HTTPException(status_code=400, detail=(raw.get("msg") if isinstance(raw, dict) else "") or f"RunningHub workflow fetch failed: {raw}")
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    prompt = data.get("prompt")
    workflow_json = {}
    if isinstance(prompt, str) and prompt.strip():
        try:
            workflow_json = json.loads(prompt)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to parse RunningHub workflow JSON: {exc}") from exc
    elif isinstance(prompt, dict):
        workflow_json = prompt
    fields = runninghub_collect_workflow_fields(workflow_json)
    return {"success": True, "data": {"workflowId": workflow_id, "title": payload.title or workflow_id, "description": payload.description or "", "fields": fields, "workflowJson": workflow_json, "raw": raw}}

@router.put("/api/runninghub/workflows/{workflow_id:path}")
def save_runninghub_workflow(workflow_id: str, payload: RunningHubWorkflowConfig):
    key = runninghub_workflow_store_key(workflow_id)
    if not key:
        raise HTTPException(status_code=400, detail="workflowId 必填")
    fields = [
        field for field in (runninghub_normalize_field(item) for item in (payload.fields or []))
        if not runninghub_is_saved_link_field(field)
    ]
    cfg = {
        "workflowId": key,
        "title": (payload.title or key).strip() or key,
        "description": payload.description or "",
        "fields": fields,
        "workflowJson": payload.workflowJson or {},
        "optionalImageMode": payload.optionalImageMode or "prune-workflow",
        "raw": payload.raw or {},
        "updatedAt": now_ms(),
    }
    with RUNNINGHUB_WORKFLOW_LOCK:
        store = load_runninghub_workflow_store()
        store[key] = cfg
        save_runninghub_workflow_store(store)
    sync_runninghub_workflow_to_provider(cfg)
    return {"success": True, "workflow": cfg}

@router.delete("/api/runninghub/workflows/{workflow_id:path}")
def delete_runninghub_workflow(workflow_id: str):
    key = runninghub_workflow_store_key(workflow_id)
    if not key:
        raise HTTPException(status_code=400, detail="workflowId 必填")
    with RUNNINGHUB_WORKFLOW_LOCK:
        store = load_runninghub_workflow_store()
        provider_cfg = runninghub_provider_workflow_config(key)
        if key not in store and not provider_cfg:
            raise HTTPException(status_code=404, detail="RunningHub 工作流未找到")
        store.pop(key, None)
        save_runninghub_workflow_store(store)
    remove_runninghub_workflow_from_provider(key)
    return {"success": True}

@router.get("/api/runninghub/query")
async def runninghub_query(taskId: str = "", useWallet: bool = False):
    task_id = str(taskId or "").strip()
    if not task_id:
        raise HTTPException(status_code=400, detail="taskId 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider, use_wallet=useWallet)
    url = runninghub_endpoint_url(provider, "/task/openapi/outputs")
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=httpx.Timeout(connect=20.0, read=240.0, write=30.0, pool=20.0)) as client:
        try:
            response = await client.post(url, headers=runninghub_app_headers(True, useWallet), json={"apiKey": api_key, "taskId": task_id})
            raw = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=runninghub_error_detail(f"查询 RunningHub 任务失败：{exc}", endpoint=url, taskId=task_id)) from exc
        if response.status_code >= 400:
            log_runninghub_error("query-http", raw, endpoint=url, taskId=task_id, status=response.status_code)
            raise HTTPException(status_code=response.status_code, detail=runninghub_error_detail(f"RunningHub HTTP {response.status_code}", raw, endpoint=url, taskId=task_id))
        code = raw.get("code") if isinstance(raw, dict) else None
        status = "PENDING"
        urls = []
        image_items = []
        if code in (0, "0"):
            status = "SUCCESS"
            for remote in runninghub_extract_outputs(raw.get("data")):
                try:
                    local_url = await runninghub_store_remote_output(client, remote)
                except Exception:
                    local_url = remote
                urls.append(local_url)
                image_items.append(image_output_meta(local_url))
        elif code in (804, "804"):
            status = "RUNNING"
        elif code in (813, "813"):
            status = "QUEUED"
        elif code in (805, "805"):
            status = "FAILED"
            log_runninghub_error("query-failed", raw, endpoint=url, taskId=task_id, code=code)
        else:
            status = "UNKNOWN"
            log_runninghub_error("query-unknown", raw, endpoint=url, taskId=task_id, code=code)
        return {"success": True, "data": {"status": status, "urls": urls, "image_items": image_items, "failReason": runninghub_fail_reason(raw), "code": code, "raw": raw}}

@router.post("/api/runninghub/upload-asset")
async def runninghub_upload_asset(payload: RunningHubUploadAssetRequest):
    source_url = rewrite_runninghub_file_url(str(payload.url or "").strip())
    if not source_url:
        raise HTTPException(status_code=400, detail="url 必填")
    provider = runninghub_provider()
    api_key = runninghub_api_key(provider, use_wallet=payload.useWallet)
    filename = "asset.bin"
    content_type = "application/octet-stream"
    content = b""
    async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=httpx.Timeout(connect=20.0, read=240.0, write=240.0, pool=20.0), follow_redirects=True) as client:
        path = runninghub_local_asset_path(source_url)
        if path:
            filename = os.path.basename(path)
            content_type = content_type_for_path(path)
            with open(path, "rb") as f:
                content = f.read()
        elif source_url.startswith(("http://", "https://")):
            try:
                content, content_type = await safe_download_bytes(
                    source_url, timeout=240.0, max_bytes=200 * 1024 * 1024, allow_private=False
                )
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"下载素材失败: {exc}") from exc
            filename = os.path.basename(urllib.parse.urlsplit(source_url).path) or filename
        else:
            raise HTTPException(status_code=400, detail=f"不支持的素材地址：{source_url}")
        if not content:
            raise HTTPException(status_code=400, detail="素材为空，无法上传到 RunningHub")
        upload_url = runninghub_endpoint_url(provider, "/task/openapi/upload")
        files = {"file": (filename, content, content_type)}
        data = {"apiKey": api_key, "fileType": "input"}
        try:
            response = await client.post(upload_url, headers=runninghub_app_headers(False, payload.useWallet), data=data, files=files)
            raw = response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"上传素材到 RunningHub 失败：{exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=json.dumps(raw, ensure_ascii=False)[:800])
    if isinstance(raw, dict) and raw.get("code") in (0, "0") and isinstance(raw.get("data"), dict) and raw["data"].get("fileName"):
        return {"success": True, "data": {"fileName": raw["data"]["fileName"], "fileType": raw["data"].get("fileType") or content_type}}
    raise HTTPException(status_code=400, detail=(raw.get("msg") if isinstance(raw, dict) else "") or f"RunningHub 上传失败：{raw}")

@router.get("/api/codex/status")
async def codex_status():
    exe = codex_cli_executable()
    image2_exe = gpt_image_2_skill_executable()
    if not exe:
        return {
            "installed": False,
            "logged_in": False,
            "image2_helper_installed": bool(image2_exe),
            "image2_helper_path": image2_exe,
            "message": "未找到 OpenAI Codex CLI，请先安装。",
        }
    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            "--version",
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=cli_subprocess_env(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        out_text, err_text = codex_decode_output(stdout, stderr)
        ok = proc.returncode == 0
        helper_message = "GPT Image 2 helper 已安装，OpenAI CLI 生图会使用 GPT Image 2。" if image2_exe else "未找到 GPT Image 2 helper，OpenAI CLI 生图不可用；已禁用 Codex 内置 $imagegen 回退。"
        return {
            "installed": ok,
            "logged_in": None,
            "version": out_text or err_text,
            "path": exe,
            "image2_helper_installed": bool(image2_exe),
            "image2_helper_path": image2_exe,
            "message": f"OpenAI Codex CLI 已安装。{helper_message} 登录状态会在首次执行 codex exec 时由 CLI 校验。" if ok else (err_text or out_text or "Codex CLI 检测失败"),
            "raw": {"stdout": out_text, "stderr": err_text, "returncode": proc.returncode},
        }
    except Exception as exc:
        return {
            "installed": False,
            "logged_in": False,
            "path": exe,
            "image2_helper_installed": bool(image2_exe),
            "image2_helper_path": image2_exe,
            "message": f"Codex CLI 检测失败：{exc}",
        }

@router.post("/api/codex/help")
async def codex_help(payload: CodexHelpRequest):
    exe = codex_cli_executable()
    if not exe:
        raise HTTPException(status_code=400, detail="未找到 OpenAI Codex CLI。")
    allowed = {"", "exec", "login", "logout", "doctor", "mcp", "app", "update"}
    command = str(payload.command or "").strip()
    if command not in allowed:
        raise HTTPException(status_code=400, detail="不允许的 Codex CLI 命令")
    args = [exe]
    if command:
        args.append(command)
    args.append("--help")
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=BASE_DIR,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=cli_subprocess_env(),
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
    out_text, err_text = codex_decode_output(stdout, stderr)
    if proc.returncode != 0:
        raise HTTPException(status_code=502, detail=(err_text or out_text or f"exit={proc.returncode}")[:1000])
    return {"text": out_text or err_text, "raw": {"stdout": out_text, "stderr": err_text}}

@router.get("/api/gemini-cli/status")
async def gemini_cli_status():
    exe = gemini_cli_executable()
    display_name = gemini_cli_display_name(exe)
    if not exe:
        return {
            "installed": False,
            "logged_in": False,
            "provider": "antigravity",
            "message": "未找到 Antigravity CLI，请先安装。",
        }
    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            "--version",
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=cli_subprocess_env(),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        out_text, err_text = codex_decode_output(stdout, stderr)
        ok = proc.returncode == 0
        is_agy = is_antigravity_cli(exe)
        return {
            "installed": ok,
            "logged_in": None,
            "version": out_text or err_text,
            "path": exe,
            "provider": "antigravity" if is_agy else "gemini",
            "message": f"{display_name} 已安装。登录状态会在首次执行 {'agy' if is_agy else 'gemini'} 时由 CLI 校验。" if ok else (err_text or out_text or f"{display_name} 检测失败"),
            "raw": {"stdout": out_text, "stderr": err_text, "returncode": proc.returncode},
        }
    except Exception as exc:
        return {
            "installed": False,
            "logged_in": False,
            "path": exe,
            "provider": "antigravity" if is_antigravity_cli(exe) else "gemini",
            "message": f"{display_name} 检测失败：{exc}",
        }

@router.post("/api/gemini-cli/help")
async def gemini_cli_help(payload: GeminiCliHelpRequest):
    exe = gemini_cli_executable()
    if not exe:
        raise HTTPException(status_code=400, detail="未找到 Antigravity CLI。")
    is_agy = is_antigravity_cli(exe)
    allowed = {"", "help", "install", "models", "plugin", "plugins", "update", "changelog"} if is_agy else {"", "help", "mcp", "extensions"}
    command = str(payload.command or "").strip()
    if command not in allowed:
        raise HTTPException(status_code=400, detail=f"不允许的 {gemini_cli_display_name(exe)} 命令")
    args = [exe]
    if command:
        args.append(command)
    args.append("--help")
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=BASE_DIR,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=cli_subprocess_env(),
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
    out_text, err_text = codex_decode_output(stdout, stderr)
    if proc.returncode != 0:
        raise HTTPException(status_code=502, detail=(err_text or out_text or f"exit={proc.returncode}")[:1000])
    return {"text": out_text or err_text, "raw": {"stdout": out_text, "stderr": err_text}}

@router.get("/api/jimeng/status")
async def jimeng_status():
    exe = jimeng_cli_executable()
    if not exe:
        return {"installed": False, "logged_in": False, "message": "未找到 dreamina CLI"}
    version, version_text = await jimeng_cli_version()
    version_str = ".".join(str(part) for part in version) if version else None
    version_ok = version >= JIMENG_MIN_CLI_VERSION if version else None
    min_version_str = ".".join(str(part) for part in JIMENG_MIN_CLI_VERSION)
    try:
        raw = await run_jimeng_cli(["user_credit"], timeout=30)
        return {
            "installed": True,
            "logged_in": True,
            "raw": raw,
            "cli_version": version_str,
            "version_ok": version_ok,
            "min_version": min_version_str,
        }
    except HTTPException as exc:
        return {
            "installed": True,
            "logged_in": False,
            "message": str(exc.detail),
            "cli_version": version_str,
            "version_ok": version_ok,
            "min_version": min_version_str,
        }

@router.get("/api/jimeng/credit")
async def jimeng_credit():
    raw = await run_jimeng_cli(["user_credit"], timeout=30)
    return {"success": True, "raw": raw}

@router.post("/api/jimeng/logout")
async def jimeng_logout():
    raw = await run_jimeng_cli(["logout"], timeout=30)
    return {"success": True, "raw": raw}

@router.post("/api/jimeng/login/start")
async def jimeng_login_start():
    old_proc = JIMENG_LOGIN_SESSION.get("proc")
    if old_proc and getattr(old_proc, "returncode", None) is None:
        try:
            old_proc.terminate()
        except Exception:
            pass
    exe = jimeng_cli_executable()
    if not exe:
        raise HTTPException(status_code=400, detail="未找到 dreamina CLI")
    JIMENG_LOGIN_SESSION.update({"proc": None, "stdout": "", "stderr": "", "started_at": time.time()})
    args = ["login", "--headless"]
    command = jimeng_command(args, exe)
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=cli_subprocess_env(),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"未找到即梦 CLI：{exe}") from exc
    JIMENG_LOGIN_SESSION["proc"] = proc
    asyncio.create_task(jimeng_login_reader(proc))
    await asyncio.sleep(2)
    text = jimeng_login_text()
    if proc.returncode not in (None, 0) and ("unknown" in text.lower() or "no such option" in text.lower()):
        # 旧版 CLI 可能没有 --headless，退回 debug 输出。
        JIMENG_LOGIN_SESSION.update({"proc": None, "stdout": "", "stderr": "", "started_at": time.time()})
        proc = await asyncio.create_subprocess_exec(
            *jimeng_command(["login", "--debug"], exe),
            cwd=BASE_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=cli_subprocess_env(),
        )
        JIMENG_LOGIN_SESSION["proc"] = proc
        asyncio.create_task(jimeng_login_reader(proc))
        await asyncio.sleep(2)
        text = jimeng_login_text()
    return {
        "success": True,
        "running": JIMENG_LOGIN_SESSION.get("proc") is not None and JIMENG_LOGIN_SESSION["proc"].returncode is None,
        "text": text,
        "qr_url": jimeng_login_qr_from_text(text),
        "started_at": JIMENG_LOGIN_SESSION.get("started_at") or 0,
    }

@router.get("/api/jimeng/login/status")
async def jimeng_login_status():
    proc = JIMENG_LOGIN_SESSION.get("proc")
    text = jimeng_login_text()
    running = proc is not None and getattr(proc, "returncode", None) is None
    logged_in = False
    credit_raw = None
    if not running:
        try:
            credit_raw = await run_jimeng_cli(["user_credit"], timeout=20)
            logged_in = True
        except HTTPException:
            logged_in = False
    return {
        "success": True,
        "running": running,
        "logged_in": logged_in,
        "text": text,
        "qr_url": jimeng_login_qr_from_text(text),
        "raw": credit_raw,
    }

@router.post("/api/jimeng/help")
async def jimeng_help(payload: JimengHelpRequest):
    command = str(payload.command or "").strip()
    allowed = {"", "login", "logout", "user_credit", "text2image", "image2image", "image_upscale", "text2video", "image2video", "multimodal2video", "frames2video", "multiframe2video", "list_task", "query_result"}
    if command not in allowed:
        raise HTTPException(status_code=400, detail="不支持的帮助命令")
    args = [command, "-h"] if command else ["-h"]
    raw = await run_jimeng_cli(args, timeout=30, raw_text=True)
    text = raw.get("_stdout") or ""
    if raw.get("_stderr"):
        text = f"{text}\n{raw.get('_stderr')}".strip()
    return {"success": True, "command": command, "text": text, "raw": raw}

@router.post("/api/jimeng/query-media")
async def jimeng_query_media(payload: JimengQueryMediaRequest):
    """按 submit_id 续查即梦任务：出图返回 succeeded+urls；仍排队返回 pending+queue_info；失败返回 failed。
    供画布「排队中」卡片自动轮询与手动查询复用。"""
    submit_id = str(payload.submit_id or "").strip()
    if not submit_id:
        raise HTTPException(status_code=400, detail="缺少 submit_id")
    kind = str(payload.kind or "image").strip().lower()
    if kind not in ("image", "video", "audio"):
        kind = "image"
    queried = await jimeng_query_result(submit_id, kind)
    try:
        urls = await jimeng_store_outputs(queried, kind, allow_query=False)
        return {"status": "succeeded", "submit_id": submit_id, "kind": kind, "urls": urls}
    except JimengPendingError as exc:
        return {"status": "pending", "submit_id": submit_id, "kind": kind, "queue_info": exc.queue_info, "message": jimeng_pending_payload(exc)["message"]}
    except HTTPException as exc:
        return {"status": "failed", "submit_id": submit_id, "kind": kind, "error": str(getattr(exc, "detail", "") or exc)}

