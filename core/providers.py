import os
import sys
import re
import json
import shutil
import glob
import time
import logging
import base64
import urllib.parse
import urllib.request
import hashlib
import hmac
import threading
from typing import Any, Dict, List, Optional, Tuple, Set
from threading import Lock
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field

from core.pydantic_compat import dump_pydantic

logger = logging.getLogger("infinite_canvas.core.providers")
_server_logger = logging.getLogger("infinite_canvas.upstream")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("INFINITE_CANVAS_DATA_DIR") or os.path.join(BASE_DIR, "data")
API_DIR = os.path.join(BASE_DIR, "API")
API_ENV_FILE = os.path.join(API_DIR, ".env")
STATIC_DIR = os.path.join(BASE_DIR, "static")
STATIC_RUNNINGHUB_DIR = os.path.join(STATIC_DIR, "runninghub")
STATIC_RUNNINGHUB_API_PROVIDERS_FILE = os.path.join(STATIC_DIR, "runninghub-api-providers.json")
STATIC_RUNNINGHUB_THUMBNAIL_DIR = os.path.join(STATIC_DIR, "runninghub-thumbnails")
RUNNINGHUB_WORKFLOW_STORE_FILE = os.path.join(DATA_DIR, "runninghub_workflows.json")

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
MODELSCOPE_API_KEY = os.getenv("MODELSCOPE_API_KEY", "")
MODELSCOPE_CHAT_BASE_URL = "https://api-inference.modelscope.cn"
MODELSCOPE_CHAT_MODELS = [
    "Qwen/Qwen2.5-Coder-32B-Instruct",
    "Qwen/Qwen2.5-72B-Instruct",
    "deepseek-ai/DeepSeek-R1",
    "deepseek-ai/DeepSeek-V3",
]
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
AI_API_KEY = os.getenv("AI_API_KEY", "")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "dall-e-3")
CHAT_MODELS = ["gpt-5.5", "gpt-5-turbo", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet-20241022", "gemini-2.5-flash", "gemini-2.5-pro"]
IMAGE_MODELS = ["dall-e-3", "dall-e-2"]
VIDEO_MODELS = ["cogvideox", "minimax"]

def is_jimeng_provider(provider: dict) -> bool:
    if not isinstance(provider, dict):
        return False
    protocol = str(provider.get("protocol") or "").strip().lower()
    pid = str(provider.get("id") or "").strip().lower()
    return protocol == "jimeng" or pid == "jimeng"

def now_ms() -> int:
    return int(time.time() * 1000)

def runninghub_is_workflow_link_value(value):
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )

def selected_model(requested: str, fallback: str) -> str:
    model = (requested or fallback or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if len(model) > 240 or any(ord(ch) < 32 or ord(ch) == 127 for ch in model):
        raise HTTPException(status_code=400, detail=f"模型名称不合法：{model}")
    return model

def provider_protocol(provider):
    return str((provider or {}).get("protocol") or "openai").strip().lower()

# 单模型可覆盖的协议（仅 OpenAI / Gemini，二者可共用同一站点的 Base URL + Key）
PER_MODEL_PROTOCOL_OPTIONS = {"openai", "gemini"}
# 协议固定、不支持单模型覆盖的内置平台
FIXED_PROTOCOL_PROVIDER_IDS = {"modelscope", "volcengine", "jimeng", "runninghub"}

def normalize_model_protocols(value):
    """规整 {模型名: 协议} 覆盖表，仅保留 openai/gemini。"""
    out = {}
    if isinstance(value, dict):
        for raw_name, raw_proto in value.items():
            name = str(raw_name or "").strip()
            proto = str(raw_proto or "").strip().lower()
            if name and proto in PER_MODEL_PROTOCOL_OPTIONS:
                out[name] = proto
    return out

def normalize_model_name_map(value):
    """规整 {模型ID: 展示名}，只保存真正有意义的显示标签。"""
    normalized = {}
    if isinstance(value, dict):
        for raw_model, raw_label in value.items():
            model = str(raw_model or "").strip()
            label = re.sub(r"\s+", " ", str(raw_label or "").strip())[:160]
            if model and label and label != model:
                normalized[model] = label
    return normalized

def effective_protocol(provider, model=""):
    """返回某模型实际生效的协议：优先单模型覆盖，否则用平台全局协议。"""
    base = provider_protocol(provider)
    pid = str((provider or {}).get("id") or "").strip().lower()
    if pid in FIXED_PROTOCOL_PROVIDER_IDS:
        return base
    overrides = (provider or {}).get("model_protocols")
    if isinstance(overrides, dict):
        val = str(overrides.get(str(model or "").strip()) or "").strip().lower()
        if val in PER_MODEL_PROTOCOL_OPTIONS:
            return val
    return base

def is_apimart_provider(provider):
    base_url = str((provider or {}).get("base_url") or "").lower()
    return provider_protocol(provider) == "apimart" or "apimart.ai" in base_url

def detect_image_request_mode(base_url="", models=None):
    base = str(base_url or "").strip().lower()
    if "apihub.agnes-ai.com" in base:
        return "openai-json"
    for model in models or []:
        if str(model or "").strip().lower().startswith("agnes-image-"):
            return "openai-json"
    return ""

def effective_image_request_mode(provider, model=""):
    detected = detect_image_request_mode((provider or {}).get("base_url"), [model])
    if detected:
        return detected
    return normalize_image_request_mode((provider or {}).get("image_request_mode"))

def is_gemini_provider(provider):
    return provider_protocol(provider) == "gemini"

def is_tudou_provider(provider):
    if not isinstance(provider, dict):
        return False
    return str(provider.get("id") or "").strip().lower() == "tudou" or is_tudou_base_url(provider.get("base_url") or "")

def log_upstream_call(method, url, status=None, elapsed_ms=None, task_id="", provider="", model="", error=""):
    """Uniform upstream API call record: logs/server.log + stdout.
    Never raises; logging must not break the request flow."""
    try:
        parts = [f"{method.upper()} {url}"]
        if status is not None:
            parts.append(f"status={status}")
        if elapsed_ms is not None:
            parts.append(f"{int(elapsed_ms)}ms")
        if provider:
            parts.append(f"provider={provider}")
        if model:
            parts.append(f"model={model}")
        if task_id:
            parts.append(f"task_id={task_id}")
        if error:
            parts.append(f"error={str(error)[:200]}")
        line = " | ".join(parts)
        _server_logger.info(line)
    except Exception:  # noqa: BLE001
        pass


async def _upstream_request_hook(request):
    try:
        request.headers.setdefault("x-dx-start", str(time.monotonic()))
    except Exception:  # noqa: BLE001
        pass


async def _upstream_response_hook(response):
    """Log every upstream API response: method url status elapsed."""
    try:
        request = response.request
        start = request.headers.get("x-dx-start")
        elapsed = (time.monotonic() - float(start)) * 1000 if start else None
        method = request.method
        url = str(request.url)
        # strip query strings that may carry keys
        if "key=" in url or "api_key=" in url:
            url = url.split("?")[0] + "?<redacted>"
        log_upstream_call(method, url, status=response.status_code, elapsed_ms=elapsed)
    except Exception:  # noqa: BLE001
        pass

def runninghub_workflow_store_path() -> str:
    return RUNNINGHUB_WORKFLOW_STORE_FILE

def load_runninghub_workflow_store():
    if not os.path.exists(RUNNINGHUB_WORKFLOW_STORE_FILE):
        return {}
    try:
        with open(RUNNINGHUB_WORKFLOW_STORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_runninghub_workflow_store(store):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(RUNNINGHUB_WORKFLOW_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)

def prune_runninghub_workflow_store_for_provider(provider):
    if not isinstance(provider, dict) or provider.get("id") not in {"runninghub", "runninghub-ai", "runninghub-cn"}:
        return
    store = load_runninghub_workflow_store()
    if not store:
        return
    keep_ids = {
        runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id"))
        for entry in provider.get("rh_workflows") or []
        if isinstance(entry, dict) and entry.get("hidden") is not True
    }
    keep_ids.discard("")
    removed = False
    for workflow_id in list(store.keys()):
        if runninghub_workflow_store_key(workflow_id) not in keep_ids:
            store.pop(workflow_id, None)
            removed = True
    if removed:
        save_runninghub_workflow_store(store)

def runninghub_workflow_config_has_payload(cfg):
    if not isinstance(cfg, dict):
        return False
    return bool(cfg.get("fields") or cfg.get("workflowJson") or cfg.get("raw"))

def runninghub_static_workflow_entry(workflow_id: str):
    key = runninghub_workflow_store_key(workflow_id)
    if not key:
        return None
    static_provider = load_static_runninghub_provider()
    for entry in (static_provider or {}).get("rh_workflows", []) or []:
        if runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id")) == key:
            return entry
    return None

def runninghub_static_workflow_config(workflow_id: str):
    entry = runninghub_static_workflow_entry(workflow_id)
    if not isinstance(entry, dict):
        return None
    key = runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id"))
    cfg = {
        "workflowId": key,
        "title": entry.get("title") or key,
        "description": entry.get("note") or entry.get("description") or "",
        "fields": [
            field for field in (runninghub_normalize_field(item) for item in (entry.get("fields") or []))
            if not runninghub_is_saved_link_field(field)
        ],
        "workflowJson": entry.get("workflowJson") if isinstance(entry.get("workflowJson"), dict) else {},
        "optionalImageMode": entry.get("optionalImageMode") or "prune-workflow",
        "raw": entry.get("raw") if isinstance(entry.get("raw"), dict) else {},
        "updatedAt": entry.get("updatedAt") or 0,
        "source": "static_template",
    }
    return cfg if runninghub_workflow_config_has_payload(cfg) else None

def runninghub_workflow_entry_from_config(cfg, fallback=None):
    fallback = fallback if isinstance(fallback, dict) else {}
    key = runninghub_workflow_store_key((cfg or {}).get("workflowId") or fallback.get("workflowId") or fallback.get("id"))
    if not key:
        return None
    return normalize_runninghub_entry({
        "id": key,
        "workflowId": key,
        "title": (cfg or {}).get("title") or fallback.get("title") or fallback.get("name") or f"工作流 {key[-6:]}",
        "note": (cfg or {}).get("description") or fallback.get("note") or fallback.get("description") or "",
        "thumbnail": fallback.get("thumbnail") or "",
        "enabled": fallback.get("enabled", True),
        "fields": (cfg or {}).get("fields") or fallback.get("fields") or [],
        "workflowJson": (cfg or {}).get("workflowJson") if isinstance((cfg or {}).get("workflowJson"), dict) else fallback.get("workflowJson") or {},
        "optionalImageMode": (cfg or {}).get("optionalImageMode") or fallback.get("optionalImageMode") or "prune-workflow",
        "raw": (cfg or {}).get("raw") if isinstance((cfg or {}).get("raw"), dict) else fallback.get("raw") or {},
        "updatedAt": (cfg or {}).get("updatedAt") or fallback.get("updatedAt") or 0,
    }, "workflow")

def runninghub_saved_hidden_workflow_ids():
    if not os.path.exists(API_PROVIDERS_FILE):
        return set()
    try:
        with open(API_PROVIDERS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return set()
    hidden = set()
    for provider in raw if isinstance(raw, list) else []:
        if not isinstance(provider, dict) or str(provider.get("id") or "").strip().lower() != "runninghub":
            continue
        for entry in provider.get("rh_workflows") or []:
            if not isinstance(entry, dict) or entry.get("hidden") is not True:
                continue
            key = runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id"))
            if key:
                hidden.add(key)
    return hidden

def runninghub_provider_with_workflow_store(provider):
    if not isinstance(provider, dict) or provider.get("id") not in {"runninghub", "runninghub-ai", "runninghub-cn"}:
        return provider
    store = load_runninghub_workflow_store()
    if not store:
        return provider
    merged = dict(provider)
    workflows = [dict(item) for item in (merged.get("rh_workflows") or []) if isinstance(item, dict)]
    hidden_ids = {
        runninghub_workflow_store_key(item.get("workflowId") or item.get("id"))
        for item in workflows
        if item.get("hidden") is True and runninghub_workflow_store_key(item.get("workflowId") or item.get("id"))
    }
    hidden_ids.update(runninghub_saved_hidden_workflow_ids())
    by_id = {
        runninghub_workflow_store_key(item.get("workflowId") or item.get("id")): item
        for item in workflows
        if runninghub_workflow_store_key(item.get("workflowId") or item.get("id"))
    }
    for workflow_id, cfg in store.items():
        if workflow_id in hidden_ids:
            continue
        if not isinstance(cfg, dict) or not runninghub_workflow_config_has_payload(cfg):
            continue
        existing = by_id.get(workflow_id)
        selected = runninghub_select_workflow_config(existing, cfg, workflow_id)
        entry = runninghub_workflow_entry_from_config(selected, existing)
        if not entry:
            continue
        if existing is None:
            workflows.append(entry)
        else:
            existing.update(entry)
    merged["rh_workflows"] = normalize_runninghub_entries(workflows, "workflow")
    return merged

def runninghub_provider_workflow_config(workflow_id: str):
    key = runninghub_workflow_store_key(workflow_id)
    if not key:
        return None
    if key in runninghub_saved_hidden_workflow_ids():
        return None
    providers = load_api_providers()
    provider = next((item for item in providers if item.get("id") == "runninghub"), None)
    if not provider:
        return None
    for entry in provider.get("rh_workflows") or []:
        entry_key = runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id"))
        if entry_key != key:
            continue
        if entry.get("hidden") is True:
            return None
        cfg = {
            "workflowId": key,
            "title": entry.get("title") or key,
            "description": entry.get("note") or entry.get("description") or "",
            "fields": [
                field for field in (runninghub_normalize_field(item) for item in (entry.get("fields") or []))
                if not runninghub_is_saved_link_field(field)
            ],
            "workflowJson": entry.get("workflowJson") if isinstance(entry.get("workflowJson"), dict) else {},
            "optionalImageMode": entry.get("optionalImageMode") or "prune-workflow",
            "raw": entry.get("raw") if isinstance(entry.get("raw"), dict) else {},
            "updatedAt": entry.get("updatedAt") or 0,
            "source": "api_providers",
        }
        return cfg if runninghub_workflow_config_has_payload(cfg) else None
    return None

def runninghub_select_workflow_config(local_cfg, provider_cfg, workflow_id: str = ""):
    static_cfg = runninghub_static_workflow_config(workflow_id)
    if isinstance(local_cfg, dict) and isinstance(provider_cfg, dict):
        try:
            local_updated = int(local_cfg.get("updatedAt") or 0)
        except Exception:
            local_updated = 0
        try:
            provider_updated = int(provider_cfg.get("updatedAt") or 0)
        except Exception:
            provider_updated = 0
        return provider_cfg if provider_updated > local_updated else local_cfg
    if isinstance(local_cfg, dict):
        return local_cfg
    if isinstance(provider_cfg, dict):
        return provider_cfg
    if static_cfg:
        return static_cfg
    return None

def sync_runninghub_workflow_to_provider(cfg):
    if not isinstance(cfg, dict):
        return
    key = runninghub_workflow_store_key(cfg.get("workflowId"))
    if not key:
        return
    providers = load_api_providers()
    provider = next((item for item in providers if item.get("id") == "runninghub"), None)
    if not provider:
        provider = {
            "id": "runninghub",
            "name": "RunningHub",
            "base_url": RUNNINGHUB_DEFAULT_BASE_URL,
            "protocol": "runninghub",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [],
            "chat_models": [],
            "video_models": [],
            "ms_loras": [],
            "ms_defaults_version": 0,
            "rh_apps": RUNNINGHUB_DEFAULT_APPS,
            "rh_workflows": [],
        }
        providers.append(provider)
    workflows = provider.setdefault("rh_workflows", [])
    entry = None
    for item in workflows:
        item_key = runninghub_workflow_store_key(item.get("workflowId") or item.get("id"))
        if item_key == key:
            entry = item
            break
    if entry is None:
        entry = {
            "id": key,
            "workflowId": key,
            "title": cfg.get("title") or f"工作流 {key[-6:]}",
            "note": cfg.get("description") or "",
            "thumbnail": "",
            "enabled": True,
        }
        workflows.append(entry)
    entry.update({
        "id": key,
        "workflowId": key,
        "title": cfg.get("title") or entry.get("title") or f"工作流 {key[-6:]}",
        "note": cfg.get("description") or "",
        "fields": [
            field for field in (runninghub_normalize_field(item) for item in (cfg.get("fields") or []))
            if not runninghub_is_saved_link_field(field)
        ],
        "workflowJson": cfg.get("workflowJson") if isinstance(cfg.get("workflowJson"), dict) else {},
        "optionalImageMode": cfg.get("optionalImageMode") or "prune-workflow",
        "raw": cfg.get("raw") if isinstance(cfg.get("raw"), dict) else {},
        "updatedAt": cfg.get("updatedAt") or now_ms(),
    })
    if "enabled" not in entry:
        entry["enabled"] = True
    if "thumbnail" not in entry:
        entry["thumbnail"] = ""
    normalized_providers = [normalize_provider(item) for item in providers]
    save_api_providers(normalized_providers)
    runninghub_provider = next((item for item in normalized_providers if item.get("id") == "runninghub"), None)
    if runninghub_provider:
        sync_runninghub_provider_workflows_to_static_template(runninghub_provider)

def remove_runninghub_workflow_from_provider(workflow_id: str):
    key = runninghub_workflow_store_key(workflow_id)
    if not key:
        return
    providers = load_api_providers()
    changed = False
    for provider in providers:
        if provider.get("id") != "runninghub":
            continue
        workflows = provider.get("rh_workflows") or []
        removed = next((
            item for item in workflows
            if runninghub_workflow_store_key(item.get("workflowId") or item.get("id")) == key
        ), None)
        kept = [
            item for item in workflows
            if runninghub_workflow_store_key(item.get("workflowId") or item.get("id")) != key
        ]
        static_provider = load_static_runninghub_provider()
        static_workflow = next((
            item for item in (static_provider or {}).get("rh_workflows", [])
            if runninghub_workflow_store_key(item.get("workflowId") or item.get("id")) == key
        ), None)
        if static_workflow:
            tombstone = normalize_runninghub_entry({**static_workflow, **(removed or {}), "enabled": False, "hidden": True}, "workflow")
            if tombstone:
                kept.append(tombstone)
        if static_workflow or len(kept) != len(workflows):
            provider["rh_workflows"] = kept
            changed = True
    if changed:
        normalized_providers = [normalize_provider(item) for item in providers]
        save_api_providers(normalized_providers)
        runninghub_provider = next((item for item in normalized_providers if item.get("id") == "runninghub"), None)
        if runninghub_provider:
            sync_runninghub_provider_workflows_to_static_template(runninghub_provider)

def runninghub_workflow_store_key(workflow_id: str) -> str:
    return str(workflow_id or "").strip()

def runninghub_normalize_field(raw, fallback=None):
    fallback = fallback or {}
    raw = dump_pydantic(raw)
    if not isinstance(raw, dict):
        raw = {}
    options = raw.get("options", fallback.get("options", []))
    if isinstance(options, str):
        options = [item.strip() for item in re.split(r"[\r\n,]+", options) if item.strip()]
    elif isinstance(options, list):
        options = [str(item).strip() for item in options if str(item).strip()]
    else:
        options = []
    field_id = str(raw.get("id") or raw.get("fieldId") or raw.get("key") or raw.get("nodeId") or fallback.get("id") or "").strip()
    node_id = str(raw.get("nodeId") or fallback.get("nodeId") or raw.get("node_id") or "").strip()
    field_name = str(raw.get("fieldName") or raw.get("inputName") or raw.get("name") or fallback.get("fieldName") or "").strip()
    field_value = raw.get("fieldValue")
    if field_value is None:
        field_value = raw.get("defaultValue")
    if field_value is None:
        field_value = raw.get("value")
    if field_value is None:
        field_value = fallback.get("fieldValue", "")
    if isinstance(field_value, (dict, list)):
        field_value = json.dumps(field_value, ensure_ascii=False)
    elif field_value is None:
        field_value = ""
    else:
        field_value = str(field_value)
    return {
        "id": field_id or f"{node_id}::{field_name}",
        "nodeId": node_id,
        "fieldName": field_name,
        "fieldValue": field_value,
        "fieldType": str(raw.get("fieldType") or fallback.get("fieldType") or "TEXT"),
        "label": str(raw.get("label") or raw.get("title") or field_name or fallback.get("label") or ""),
        "enabled": bool(raw.get("enabled", fallback.get("enabled", True))),
        "sourceFromUpstream": bool(raw.get("sourceFromUpstream", fallback.get("sourceFromUpstream", True))),
        "group": str(raw.get("group") or fallback.get("group") or ""),
        "note": str(raw.get("note") or fallback.get("note") or ""),
        "options": options,
        "random_enabled": bool(raw.get("random_enabled", fallback.get("random_enabled", False))),
        "min": raw.get("min", fallback.get("min", "")),
        "max": raw.get("max", fallback.get("max", "")),
        "step": raw.get("step", fallback.get("step", "")),
        "imageOrder": int(raw.get("imageOrder") or raw.get("image_order") or fallback.get("imageOrder") or 0),
        "required": bool(raw.get("required", fallback.get("required", False))),
    }

def runninghub_is_saved_link_field(field):
    if not isinstance(field, dict):
        return False
    value = field.get("fieldValue")
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return False
    try:
        parsed = json.loads(text)
    except Exception:
        return False
    return runninghub_is_workflow_link_value(parsed)

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

def runninghub_collect_workflow_fields(workflow_json):
    fields = []
    if not isinstance(workflow_json, dict):
        return fields
    for node_id, node_content in workflow_json.items():
        if not isinstance(node_content, dict):
            continue
        inputs = node_content.get("inputs")
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
            field_type = runninghub_infer_workflow_field_type(field_name, field_value)
            fields.append({
                "id": f"{node_id}::{field_name}",
                "nodeId": str(node_id),
                "fieldName": str(field_name),
                "fieldValue": field_value,
                "fieldType": field_type,
                "label": str(field_name),
                "enabled": False,
                "sourceFromUpstream": True,
                "group": str(
                    (node_content.get("_meta") or {}).get("title")
                    or node_content.get("class_type")
                    or node_content.get("_class")
                    or node_content.get("type")
                    or ""
                ),
                "note": "",
                "imageOrder": 0,
                "required": field_type == "IMAGE",
            })
    return fields

STATIC_RUNNINGHUB_MODEL_REGISTRY_FILE = os.path.join(STATIC_RUNNINGHUB_DIR, "models_registry.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
OUTPUT_INPUT_DIR = os.path.join(ASSETS_DIR, "input")
OUTPUT_OUTPUT_DIR = os.path.join(ASSETS_DIR, "output")
ASSET_LIBRARY_DIR = os.path.join(ASSETS_DIR, "library")
LOCAL_UPLOAD_DIR = os.path.join(ASSETS_DIR, "uploads")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
API_ENV_FILE = os.path.join(BASE_DIR, "API", ".env")
CONVERSATION_DIR = os.path.join(DATA_DIR, "conversations")
CANVAS_DIR = os.path.join(DATA_DIR, "canvases")
MEDIA_PREVIEW_DIR = os.path.join(DATA_DIR, "media_previews")
ASSET_LIBRARY_PATH = os.path.join(DATA_DIR, "asset_library.json")
PROMPT_LIBRARY_PATH = os.path.join(DATA_DIR, "prompt_libraries.json")
API_PROVIDERS_FILE = os.path.join(DATA_DIR, "api_providers.json")
RUNNINGHUB_WORKFLOW_STORE_FILE = os.path.join(DATA_DIR, "runninghub_workflows.json")
SHARED_FOLDERS_FILE = os.path.join(DATA_DIR, "shared_folders.json")
GLOBAL_CONFIG_FILE = os.path.join(BASE_DIR, "global_config.json")
CANVAS_TRASH_RETENTION_MS = 30 * 24 * 60 * 60 * 1000
LOCAL_IMAGE_IMPORT_MAX_BYTES = int(os.getenv("LOCAL_IMAGE_IMPORT_MAX_BYTES", str(50 * 1024 * 1024)))
LOCAL_IMAGE_IMPORT_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
RUNNINGHUB_THUMBNAIL_EXTS = (".jpg",)



GLOBAL_CONFIG_LOCK = Lock()
RUNNINGHUB_WORKFLOW_LOCK = Lock()
JIMENG_LOGIN_SESSION = {
    "proc": None,
    "stdout": "",
    "stderr": "",
    "started_at": 0.0,
}

PROVIDER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{2,40}$")
SUPPORTED_PROVIDER_PROTOCOLS = {"openai", "apimart", "gemini", "gemini-cli", "volcengine", "runninghub", "jimeng", "codex", "pollinations"}
SUPPORTED_IMAGE_REQUEST_MODES = {"openai", "openai-json", "openai-video-proxy", "openai-responses", "tudou-async"}
RUNNINGHUB_CN_BASE_URL = "https://www.runninghub.cn"
RUNNINGHUB_AI_BASE_URL = "https://www.runninghub.ai"
RUNNINGHUB_DEFAULT_BASE_URL = "https://www.runninghub.cn"
RUNNINGHUB_OPENAPI_BASE_URL = "https://www.runninghub.cn/openapi/v2"
RUNNINGHUB_MODEL_REGISTRY_URL = "https://raw.githubusercontent.com/HM-RunningHub/ComfyUI_RH_OpenAPI/main/models_registry.json"
RUNNINGHUB_LLM_BASE_URL = "https://llm.runninghub.ai/v1"
RUNNINGHUB_FILE_HOST_REWRITES = {
    "rh-images-1252422369.cos.ap-beijing.myqcloud.com": "rh-images.xiaoyaoyou.com",
}
LINGJING_DEFAULT_BASE_URL = "https://apistudio.vip"
RUNNINGHUB_LLM_MODELS_URLS = [
    "https://llm.runninghub.ai/v1/models",
]
RUNNINGHUB_FALLBACK_CHAT_MODELS = [
    "google/gemini-3.1-flash-lite-preview",
    "qwen/qwen3-vl-235b-a22b-instruct",
    "qwen/qwen-plus",
    "openai/gpt-5.1",
]
JIMENG_DEFAULT_IMAGE_MODELS = [
    "5.0Pro",
    "5.0",
    "4.7",
    "4.6",
    "4.5",
    "4.1",
    "4.0",
    "3.1",
    "3.0",
]
JIMENG_DEFAULT_VIDEO_MODELS = [
    "seedance2.0_vip",
    "seedance2.0fast_vip",
    "seedance2.0",
    "seedance2.0fast",
    "seedance2.0mini",
]
CODEX_DEFAULT_IMAGE_MODELS = ["gpt-image-2"]
CODEX_DEFAULT_CHAT_MODELS = ["gpt-5.5"]
GEMINI_CLI_DEFAULT_IMAGE_MODELS = ["auto"]
GEMINI_CLI_DEFAULT_CHAT_MODELS = ["auto"]
try:
    CODEX_DEFAULT_TIMEOUT = max(30, min(3600, int(os.getenv("CODEX_CLI_TIMEOUT", "900"))))
except Exception:
    CODEX_DEFAULT_TIMEOUT = 900
try:
    GEMINI_CLI_DEFAULT_TIMEOUT = max(30, min(3600, int(os.getenv("GEMINI_CLI_TIMEOUT", "900"))))
except Exception:
    GEMINI_CLI_DEFAULT_TIMEOUT = 900
AGNES_DEFAULT_VIDEO_MODELS = ["agnes-video-v2.0"]
MEIGEN_DEFAULT_IMAGE_MODELS = [
    "gpt-image-2", "nanobanana-2", "gemini-3-pro-image-preview", "midjourney-v8.1",
    "grok-image", "seedream-5.0-pro", "flux2-klein", "agnes-image-2.1-flash",
]
MEIGEN_DEFAULT_VIDEO_MODELS = [
    "seedance-2-5", "seedance-2-0", "veo-3.1", "grok-video", "agnes-video-2.0",
]
POLLINATIONS_DEFAULT_IMAGE_MODELS = [
    "flux", "sana", "zimage", "nanobanana-2-lite", "qwen-image-3", "seedream5-pro",
]
DASHSCOPE_DEFAULT_VIDEO_MODELS = [
    "wan3.0-video",
    "wan3.0-video-prime",
    "happyhorse-1.1-t2v",
    "happyhorse-1.1-i2v",
    "happyhorse-1.1-r2v",
]
JIMENG_LEGACY_IMAGE_MODELS = {
    "jimeng-image-2k",
    "jimeng-image-4k",
}
JIMENG_LEGACY_VIDEO_MODELS = {
    "jimeng-video-720p",
    "jimeng-video-1080p",
}
try:
    JIMENG_DEFAULT_POLL_SECONDS = max(1, min(3600, int(os.getenv("JIMENG_POLL_SECONDS", "900"))))
except Exception:
    JIMENG_DEFAULT_POLL_SECONDS = 900
VOLCENGINE_DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
VOLCENGINE_DEFAULT_PROJECT_NAME = "default"
VOLCENGINE_DEFAULT_REGION = "cn-beijing"
RUNNINGHUB_DEFAULT_IMAGE_MODELS = [
    "midjourney-text-to-image-v7",
    "midjourney-text-to-image-v61",
    "gpt-image-2.0/text-to-image-channel-low-price",
    "gpt-image-2.0/edit-channel-low-price",
    "gpt-image-2/text-to-image-official-stable",
    "gpt-image-2/image-to-image-official-stable",
    "nano-banana/text-to-image-official-stable",
    "nano-banana/edit-official-stable",
]
RUNNINGHUB_DEFAULT_VIDEO_MODELS = [
    "google/veo3.1-fast/text-to-video-channel-low-price",
    "sora-2/text-to-video-official-stable",
    "seedance-2.0-global/text-to-video",
    "seedance-2.0-global/image-to-video",
]
RUNNINGHUB_MODEL_ENDPOINT_ALIASES = {
    "Seedance2.0 Image to Video": "bytedance/seedance-2.0-global/image-to-video",
    "Seedance2.0 Text to Video": "bytedance/seedance-2.0-global/text-to-video",
    "seedance2.0 image to video": "bytedance/seedance-2.0-global/image-to-video",
    "seedance2.0 text to video": "bytedance/seedance-2.0-global/text-to-video",
    "gpt-image-2.0/text-to-image-channel-low-price": "rhart-image-g-2/text-to-image",
    "gpt-image-2/text-to-image-channel-low-price": "rhart-image-g-2/text-to-image",
    "gpt-image-2.0/edit-channel-low-price": "rhart-image-g-2/image-to-image",
    "gpt-image-2/edit-channel-low-price": "rhart-image-g-2/image-to-image",
    "gpt-image-2.0/image-to-image-channel-low-price": "rhart-image-g-2/image-to-image",
    "gpt-image-2/image-to-image-channel-low-price": "rhart-image-g-2/image-to-image",
    "nano-banana/text-to-image-channel-low-price": "rhart-image-v1/text-to-image",
    "nano-banana/edit-channel-low-price": "rhart-image-v1/edit",
}
RUNNINGHUB_DEFAULT_APPS = [
    {
        "id": "2058517022748798977",
        "appId": "2058517022748798977",
        "title": "2511-风格迁移",
        "note": "",
        "thumbnail": "",
        "enabled": True,
        "fields": [
            {
                "id": "100::image",
                "nodeId": "100",
                "fieldName": "image",
                "fieldValue": "pasted/57ef7dc980b6446bca366caaf3f94eb12b22b23f78aa30e294b39cabd7d0187b.png",
                "fieldType": "IMAGE",
                "label": "image",
                "enabled": True,
                "sourceFromUpstream": True,
                "group": "AI 应用参数",
                "note": "image",
                "options": [],
                "random_enabled": False,
                "min": "",
                "max": "",
                "step": "",
                "imageOrder": 0,
                "required": False,
            },
            {
                "id": "112::image",
                "nodeId": "112",
                "fieldName": "image",
                "fieldValue": "8cff63ee4b3e0285ca85ab90a52e26746df84ed0dec0be9d76c679cbb62a247d.png",
                "fieldType": "IMAGE",
                "label": "image",
                "enabled": True,
                "sourceFromUpstream": True,
                "group": "AI 应用参数",
                "note": "image",
                "options": [],
                "random_enabled": False,
                "min": "",
                "max": "",
                "step": "",
                "imageOrder": 0,
                "required": False,
            },
            {
                "id": "14::seed",
                "nodeId": "14",
                "fieldName": "seed",
                "fieldValue": "3250470112",
                "fieldType": "INT",
                "label": "seed",
                "enabled": True,
                "sourceFromUpstream": True,
                "group": "AI 应用参数",
                "note": "seed",
                "options": [],
                "random_enabled": True,
                "min": "1",
                "max": "4294967295",
                "step": "1",
                "imageOrder": 0,
                "required": False,
            },
        ],
    },
    {
        "id": "1997622492837646338",
        "appId": "1997622492837646338",
        "title": "2511-光线迁移",
        "note": "",
        "thumbnail": "",
        "enabled": True,
    },
]
RUNNINGHUB_DEFAULT_WORKFLOWS = [
    {
        "id": "2058554058318897153",
        "workflowId": "2058554058318897153",
        "title": "GPT-Image-2-图片编辑",
        "note": "",
        "thumbnail": "",
        "enabled": True,
        "optionalImageMode": "prune-workflow",
    },
    {
        "id": "2058541134623891458",
        "workflowId": "2058541134623891458",
        "title": "NanoBanana-2-图片编辑",
        "note": "",
        "thumbnail": "",
        "enabled": True,
        "optionalImageMode": "prune-workflow",
    },
]

def ensure_runtime_config_files():
    """首次运行时提前创建配置目录，避免第一次保存 API Key 时才创建目录/文件。"""
    try:
        os.makedirs(os.path.dirname(API_ENV_FILE), exist_ok=True)
        os.makedirs(DATA_DIR, exist_ok=True)
        if not os.path.exists(API_ENV_FILE):
            with open(API_ENV_FILE, "a", encoding="utf-8"):
                pass
    except Exception as e:
        logger.warning(f"初始化 API 配置目录失败: {e}")

def env_unquote(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        inner = text[1:-1]
        result = []
        i = 0
        n = len(inner)
        while i < n:
            if inner[i] == "\\" and i + 1 < n:
                next_c = inner[i + 1]
                if next_c in ('"', '\\', 'n', 'r', 't'):
                    if next_c == '"':
                        result.append('"')
                    elif next_c == '\\':
                        result.append('\\')
                    elif next_c == 'n':
                        result.append('\n')
                    elif next_c == 'r':
                        result.append('\r')
                    elif next_c == 't':
                        result.append('\t')
                    i += 2
                    continue
            result.append(inner[i])
            i += 1
        return "".join(result)
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    return text

def load_env_file():
    if not os.path.exists(API_ENV_FILE):
        return
    try:
        with open(API_ENV_FILE, 'r', encoding='utf-8-sig') as f:
            for raw_line in f.read().splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = env_unquote(value)
                if key in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"}:
                    os.environ[key] = value
                else:
                    os.environ.setdefault(key, value)
    except Exception as e:
        logger.warning(f"加载 API/.env 失败: {e}")
ensure_runtime_config_files()
load_env_file()

COMFYUI_INSTANCES = [s.strip() for s in os.getenv("COMFYUI_INSTANCES", "127.0.0.1:8188").split(",") if s.strip()]
COMFYUI_ADDRESS = COMFYUI_INSTANCES[0] if COMFYUI_INSTANCES else "127.0.0.1:8188"

AI_BASE_URL = os.getenv("COMFLY_BASE_URL", "https://ai.comfly.chat").rstrip("/")
AI_API_KEY = os.getenv("COMFLY_API_KEY", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
PUBLIC_MEDIA_BASE_URL = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip().rstrip("/")
MODELSCOPE_API_KEY = os.getenv("MODELSCOPE_API_KEY", "")
MODELSCOPE_CHAT_BASE_URL = "https://api-inference.modelscope.cn/v1"
MODELSCOPE_DEFAULT_IMAGE_MODELS = [
    "Tongyi-MAI/Z-Image-Turbo",
    "Qwen/Qwen-Image-2512",
    "Qwen/Qwen-Image-Edit-2511",
    "black-forest-labs/FLUX.2-klein-9B",
]
MODELSCOPE_DEFAULT_CHAT_MODELS = [
    "Qwen/Qwen3-235B-A22B",
    "Qwen/Qwen3-VL-235B-A22B-Instruct",
    "MiniMax/MiniMax-M2.7:MiniMax",
]
_MODELSCOPE_CONFIGURED_CHAT_MODELS = [m.strip() for m in os.getenv("MODELSCOPE_CHAT_MODELS", "").split(",") if m.strip()]
MODELSCOPE_CHAT_MODELS = list(dict.fromkeys([m for m in [*MODELSCOPE_DEFAULT_CHAT_MODELS, *_MODELSCOPE_CONFIGURED_CHAT_MODELS] if m]))
MODELSCOPE_DEFAULT_IMAGE_MODEL = MODELSCOPE_DEFAULT_IMAGE_MODELS[0]
MODELSCOPE_DEFAULT_CHAT_MODEL = "Qwen/Qwen3-235B-A22B"
MODELSCOPE_DEFAULT_LORAS = [
    {
        "id": "Daniel8152/film",
        "name": "Z-Image Film",
        "target_model": "Tongyi-MAI/Z-Image-Turbo",
        "strength": 0.8,
        "enabled": True,
        "note": "",
    },
    {
        "id": "Daniel8152/Qwen-Image-2512-Film",
        "name": "Qwen Image 2512 Film",
        "target_model": "Qwen/Qwen-Image-2512",
        "strength": 0.8,
        "enabled": True,
        "note": "",
    },
    {
        "id": "Daniel8152/Klein-enhance",
        "name": "Klein enhance",
        "target_model": "black-forest-labs/FLUX.2-klein-9B",
        "strength": 0.8,
        "enabled": True,
        "note": "",
    },
]
MODELSCOPE_DEFAULTS_VERSION = 3
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are a helpful assistant.")
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "30"))
AI_REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "1800"))
IMAGE_POLL_INTERVAL = float(os.getenv("IMAGE_POLL_INTERVAL", "2"))
IMAGE_TASK_TIMEOUT = float(os.getenv("IMAGE_TASK_TIMEOUT", str(AI_REQUEST_TIMEOUT)))
COMFYUI_HISTORY_TIMEOUT = int(float(os.getenv("COMFYUI_HISTORY_TIMEOUT", "1800")))
# 下载 ComfyUI 产物的 socket 超时（秒，作用于连接和每次 read）。没有它时一次网络卡顿会让 urlopen 永久挂起，
# 导致 generate() 不返回、画布卡片一直转圈拿不到结果。给得足够大以容纳大视频/大图的正常下载。
COMFYUI_DOWNLOAD_TIMEOUT = float(os.getenv("COMFYUI_DOWNLOAD_TIMEOUT", "120"))
APIMART_IMAGE_TASK_TIMEOUT = float(os.getenv("APIMART_IMAGE_TASK_TIMEOUT", "1800"))
APIMART_IMAGE_POLL_INTERVAL = float(os.getenv("APIMART_IMAGE_POLL_INTERVAL", "5"))
APIMART_IMAGE_INITIAL_POLL_DELAY = float(os.getenv("APIMART_IMAGE_INITIAL_POLL_DELAY", "10"))
TUDOU_ASYNC_IMAGE_TASK_TIMEOUT = float(os.getenv("TUDOU_ASYNC_IMAGE_TASK_TIMEOUT", "1800"))
TUDOU_ASYNC_IMAGE_POLL_INTERVAL = float(os.getenv("TUDOU_ASYNC_IMAGE_POLL_INTERVAL", "4"))
TUDOU_ASYNC_IMAGE_INITIAL_POLL_DELAY = float(os.getenv("TUDOU_ASYNC_IMAGE_INITIAL_POLL_DELAY", "12"))
VIDEO_POLL_TIMEOUT = float(os.getenv("VIDEO_POLL_TIMEOUT", "1800"))
ONLINE_IMAGE_PROMPT_MAX_LENGTH = int(os.getenv("ONLINE_IMAGE_PROMPT_MAX_LENGTH", "20000"))
VIDEO_PROMPT_MAX_LENGTH = int(os.getenv("VIDEO_PROMPT_MAX_LENGTH", "4000"))
LLM_MESSAGE_MAX_LENGTH = int(os.getenv("LLM_MESSAGE_MAX_LENGTH", "20000"))
CHAT_ATTACHMENT_MAX = int(os.getenv("CHAT_ATTACHMENT_MAX", "20"))
ONLINE_IMAGE_REFERENCE_MAX = int(os.getenv("ONLINE_IMAGE_REFERENCE_MAX", "20"))

FIELD_LABELS = {
    "positive": "正面提示词",
    "prompt": "提示词",
    "workflow": "工作流内容",
    "image": "参考图片",
    "video": "参考视频",
    "client_id": "客户端标识",
    "system_prompt": "系统提示词",
    "message": "文本",
}

def friendly_validation_error(errors):
    parts = []
    for err in errors or []:
        loc = [str(item) for item in err.get("loc", []) if item != "body"]
        field = loc[-1] if loc else ""
        label = FIELD_LABELS.get(field, field or "请求参数")
        ctx = err.get("ctx") or {}
        limit = ctx.get("limit_value") or ctx.get("max_length") or ctx.get("min_length")
        err_type = str(err.get("type") or "")
        msg = str(err.get("msg") or "")
        if "max_length" in err_type or "at most" in msg:
            parts.append(f"{label}过长：当前内容超过后端上限 {limit} 个字符。请拆分为多个提示词节点，或先用 LLM 节点压缩后再生成。")
        elif "min_length" in err_type:
            parts.append(f"{label}不能为空。")
        else:
            parts.append(f"{label}格式不正确：{msg}")
    return "\n".join(parts) or "请求参数不正确。"


def model_list(env_name, primary, defaults):
    configured = os.getenv(env_name, "")
    configured_values = [item.strip() for item in configured.split(",") if item.strip()]
    values = configured_values or [primary, *defaults]
    deduped = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped

def reload_env_globals():
    """保存 API 设置后，将 os.environ 里最新的值同步回模块级全局变量，
    避免保存后需要重启才能生效。"""
    global MODELSCOPE_API_KEY, AI_API_KEY, AI_BASE_URL
    global IMAGE_MODELS, CHAT_MODELS, VIDEO_MODELS, MODELSCOPE_CHAT_MODELS
    MODELSCOPE_API_KEY = os.getenv("MODELSCOPE_API_KEY", "")
    AI_API_KEY = os.getenv("COMFLY_API_KEY", "")
    AI_BASE_URL = os.getenv("COMFLY_BASE_URL", "https://ai.comfly.chat").rstrip("/")
    IMAGE_MODELS = model_list("IMAGE_MODELS", os.getenv("IMAGE_MODEL", IMAGE_MODEL), ["nano-banana-pro"])
    CHAT_MODELS = model_list("CHAT_MODELS", os.getenv("CHAT_MODEL", CHAT_MODEL), ["gpt-4o-mini", "gemini-3.1-flash-image-preview-2k"])
    VIDEO_MODELS = model_list("VIDEO_MODELS", "veo3-fast", [
        "veo2", "veo2-fast", "veo2-pro",
        "veo3", "veo3-fast", "veo3-pro",
        "veo3.1", "veo3.1-fast", "veo3.1-quality", "veo3.1-lite",
        "sora-2", "sora-2-pro",
        "wan2.6-t2v", "wan2.6-i2v",
        "wan2.5-t2v-preview", "wan2.5-i2v-preview",
        "wan2.2-t2v-plus", "wan2.2-i2v-plus", "wan2.2-i2v-flash",
        "doubao-seedance-2-0-260128",
        "doubao-seedance-2-0-fast-260128",
        "doubao-seedance-1-5-pro-251215",
        "doubao-seedance-1-0-pro-250528",
        "doubao-seedance-1-0-lite-t2v-250428",
        "doubao-seedance-1-0-lite-i2v-250428",
    ])
    _configured = [m.strip() for m in os.getenv("MODELSCOPE_CHAT_MODELS", "").split(",") if m.strip()]
    MODELSCOPE_CHAT_MODELS = list(dict.fromkeys([m for m in [*MODELSCOPE_DEFAULT_CHAT_MODELS, *_configured] if m]))

CHAT_MODELS = model_list("CHAT_MODELS", CHAT_MODEL, ["gpt-4o-mini", "gemini-3.1-flash-image-preview-2k"])
IMAGE_MODELS = model_list("IMAGE_MODELS", IMAGE_MODEL, ["nano-banana-pro"])
VIDEO_MODELS = model_list("VIDEO_MODELS", "veo3-fast", [
    # —— Veo 系列 ——
    "veo2", "veo2-fast", "veo2-pro",
    "veo3", "veo3-fast", "veo3-pro",
    "veo3.1", "veo3.1-fast", "veo3.1-quality", "veo3.1-lite",
    # —— Sora ——
    "sora-2", "sora-2-pro",
    # —— 阿里 通义万相 ——
    "wan2.6-t2v", "wan2.6-i2v",
    "wan2.5-t2v-preview", "wan2.5-i2v-preview",
    "wan2.2-t2v-plus", "wan2.2-i2v-plus", "wan2.2-i2v-flash",
    # —— 火山 豆包 Seedance ——
    "doubao-seedance-2-0-260128",
    "doubao-seedance-2-0-fast-260128",
    "doubao-seedance-1-5-pro-251215",
    "doubao-seedance-1-0-pro-250528",
    "doubao-seedance-1-0-lite-t2v-250428",
    "doubao-seedance-1-0-lite-i2v-250428",
])

class _MtimeCache:
    """按文件 (mtime_ns, size) 缓存解析结果的小型缓存。

    仓库内 CanvasCache 已用同一思路：文件一变缓存自动失效，避免高频路径
    反复读盘 + 全量重新解析。这里把该模式抽成通用构件，供 API/.env 与
    api_providers.json 两处复用，并额外加 30s 时间兜底，防止极端情况下
    mtime 精度不足导致长期读到旧值。
    """

    __slots__ = ("_path", "_lock", "_stamp", "_value", "_ttl_until", "_builder")

    def __init__(self, path, builder):
        self._path = path
        self._lock = threading.Lock()
        self._stamp = None
        self._value = None
        self._ttl_until = 0.0
        self._builder = builder

    def _current_stamp(self):
        p = self._path() if callable(self._path) else self._path
        try:
            st = os.stat(p)
            return (p, st.st_mtime_ns, st.st_size)
        except OSError:
            return (p, None, None)

    def get(self):
        stamp = self._current_stamp()
        now = time.time()
        with self._lock:
            if (
                self._value is not None
                and self._stamp == stamp
                and now < self._ttl_until
            ):
                return self._value
        value = self._builder()
        with self._lock:
            self._value = value
            self._stamp = stamp
            self._ttl_until = now + 30.0
        return value

    def invalidate(self):
        with self._lock:
            self._stamp = None
            self._value = None
            self._ttl_until = 0.0


def _read_api_env_file():
    try:
        with open(API_ENV_FILE, "r", encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except Exception:
        return {}
    out = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = env_unquote(v)
    return out


def _read_api_providers_file():
    defaults = default_api_providers()
    if not os.path.exists(API_PROVIDERS_FILE):
        return merge_default_api_providers(defaults)
    try:
        with open(API_PROVIDERS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        providers = [normalize_provider(item) for item in raw if isinstance(item, dict)]
        return merge_default_api_providers(providers or defaults, inject_missing=not bool(providers))
    except Exception as e:
        logger.warning(f"加载 API 平台配置失败: {e}")
        return defaults


_api_env_cache = _MtimeCache(lambda: API_ENV_FILE, _read_api_env_file)
_api_providers_cache = _MtimeCache(lambda: API_PROVIDERS_FILE, _read_api_providers_file)


def invalidate_api_env_cache():
    _api_env_cache.invalidate()


def provider_key_env(provider_id):
    if provider_id == "comfly":
        return "COMFLY_API_KEY"
    if provider_id == "modelscope":
        return "MODELSCOPE_API_KEY"
    if provider_id in {"runninghub", "runninghub-cn", "runninghub_cn"}:
        return "RUNNINGHUB_API_KEY"
    if provider_id in {"runninghub-ai", "runninghub-global", "runninghub_ai", "runninghub_global"}:
        return "RUNNINGHUB_AI_API_KEY"
    if provider_id == "volcengine":
        return "ARK_API_KEY"
    if provider_id == "gemini":
        return "GEMINI_API_KEY"
    if provider_id in {"siliconflow-cn", "siliconflow_cn"}:
        return "SILICONFLOW_CN_API_KEY"
    if provider_id in {"siliconflow-com", "siliconflow_com"}:
        return "SILICONFLOW_COM_API_KEY"
    if provider_id == "bfl":
        return "BFL_API_KEY"
    if provider_id in {"ltx-official", "ltx_official"}:
        return "LTX_API_KEY"
    return f"API_PROVIDER_{re.sub(r'[^A-Za-z0-9]', '_', provider_id).upper()}_KEY"

def runninghub_wallet_key_env(provider_id="runninghub"):
    pid = str(provider_id or "").strip().lower()
    if pid in {"runninghub-ai", "runninghub-global", "runninghub_ai", "runninghub_global"}:
        return "RUNNINGHUB_AI_WALLET_API_KEY"
    return "RUNNINGHUB_WALLET_API_KEY"

def volcengine_access_key_env():
    return "VOLCENGINE_ACCESS_KEY_ID"

def volcengine_secret_key_env():
    return "VOLCENGINE_SECRET_ACCESS_KEY"

def read_api_env_value(key: str) -> str:
    key = str(key or "").strip()
    if not key:
        return ""
    return _api_env_cache.get().get(key, "")


def get_configured_access_token() -> str:
    """IC_ACCESS_TOKEN from the environment or API/.env (no side effects; shared by main.py and launchers)."""
    return (os.getenv("IC_ACCESS_TOKEN") or read_api_env_value("IC_ACCESS_TOKEN") or "").strip()



def provider_env_key_value(provider_id: str) -> str:
    provider_id = str(provider_id or "").strip().lower()
    env_key = provider_key_env(provider_id)
    key = os.getenv(env_key, "") or read_api_env_value(env_key)
    if key:
        return key
    if provider_id in {"runninghub-ai", "runninghub-global"}:
        for alt in ["RUNNINGHUB_GLOBAL_API_KEY"]:
            val = os.getenv(alt, "") or read_api_env_value(alt)
            if val:
                return val
    if provider_id in {"siliconflow-cn", "siliconflow-com"}:
        shared_key = os.getenv("SILICONFLOW_API_KEY", "") or read_api_env_value("SILICONFLOW_API_KEY")
        if shared_key:
            return shared_key
    if provider_id == "modelscope":
        return MODELSCOPE_API_KEY or ""
    if provider_id == "gemini":
        alt_key = os.getenv("API_PROVIDER_GEMINI_KEY", "") or read_api_env_value("API_PROVIDER_GEMINI_KEY")
        if alt_key:
            return alt_key
    return ""

def runninghub_wallet_key_value(provider_id="runninghub") -> str:
    env_key = runninghub_wallet_key_env(provider_id)
    val = os.getenv(env_key, "") or read_api_env_value(env_key)
    if val:
        return val
    pid = str(provider_id or "").strip().lower()
    if pid in {"runninghub-ai", "runninghub-global", "runninghub_ai", "runninghub_global"}:
        alt = "RUNNINGHUB_GLOBAL_WALLET_API_KEY"
        return os.getenv(alt, "") or read_api_env_value(alt)
    return ""

def volcengine_access_key_value() -> str:
    env_key = volcengine_access_key_env()
    return os.getenv(env_key, "") or read_api_env_value(env_key)

def volcengine_secret_key_value() -> str:
    env_key = volcengine_secret_key_env()
    return os.getenv(env_key, "") or read_api_env_value(env_key)

def volcengine_provider_api_key(explicit_key: str = "") -> str:
    explicit_key = str(explicit_key or "").strip()
    if explicit_key:
        return explicit_key
    return provider_env_key_value("volcengine")

def mask_secret(value):
    if not value:
        return ""
    tail = value[-4:] if len(value) > 4 else value
    return f"••••••••{tail}"

def key_looks_masked(value):
    """True when the incoming key is a masked preview round-tripped from the UI
    (e.g. '••••••••' + tail, '****' + tail, '********' + tail) or a stale ellipsis placeholder."""
    text = str(value or "").strip()
    if not text:
        return False
    if "••••••••" in text or "********" in text or "****" in text:
        return True
    if "\u2022" in text or "\u2026" in text or "…" in text or "????????" in text:
        return True
    if re.fullmatch(r"\S*\.{3,}\S*", text):
        return True
    return False


def strip_auth_scheme(value, scheme="Bearer"):
    text = str(value or "").strip()
    if not text:
        return ""
    pattern = rf"^{re.escape(scheme)}\s+"
    return re.sub(pattern, "", text, flags=re.I).strip()

def bearer_auth_value(value):
    token = strip_auth_scheme(value, "Bearer")
    return f"Bearer {token}" if token else ""

def default_api_providers():
    # 独立入口平台强制保留，其他平台均可自定义增删
    return [
        {
            "id": "modelscope",
            "name": "ModelScope",
            "base_url": MODELSCOPE_CHAT_BASE_URL,
            "protocol": "openai",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": MODELSCOPE_DEFAULT_IMAGE_MODELS,
            "chat_models": MODELSCOPE_CHAT_MODELS,
            "video_models": [],
            "ms_loras": MODELSCOPE_DEFAULT_LORAS,
            "ms_defaults_version": MODELSCOPE_DEFAULTS_VERSION,
        },
        {
            "id": "runninghub",
            "name": "RunningHub (国内站)",
            "base_url": RUNNINGHUB_CN_BASE_URL,
            "protocol": "runninghub",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": RUNNINGHUB_DEFAULT_IMAGE_MODELS,
            "chat_models": RUNNINGHUB_FALLBACK_CHAT_MODELS,
            "video_models": RUNNINGHUB_DEFAULT_VIDEO_MODELS,
            "ms_loras": [],
            "ms_defaults_version": 0,
            "rh_apps": RUNNINGHUB_DEFAULT_APPS,
            "rh_workflows": RUNNINGHUB_DEFAULT_WORKFLOWS,
        },
        {
            "id": "runninghub-ai",
            "name": "RunningHub (国际站)",
            "base_url": RUNNINGHUB_AI_BASE_URL,
            "protocol": "runninghub",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": RUNNINGHUB_DEFAULT_IMAGE_MODELS,
            "chat_models": RUNNINGHUB_FALLBACK_CHAT_MODELS,
            "video_models": RUNNINGHUB_DEFAULT_VIDEO_MODELS,
            "ms_loras": [],
            "ms_defaults_version": 0,
            "rh_apps": [],
            "rh_workflows": [],
        },
        {
            "id": "volcengine",
            "name": "火山引擎",
            "base_url": VOLCENGINE_DEFAULT_BASE_URL,
            "protocol": "volcengine",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [],
            "chat_models": [],
            "video_models": [],
            "ms_loras": [],
            "ms_defaults_version": 0,
            "volcengine_project_name": VOLCENGINE_DEFAULT_PROJECT_NAME,
            "volcengine_region": VOLCENGINE_DEFAULT_REGION,
        },
        {
            "id": "pollinations",
            "name": "Pollinations (免Key)",
            "base_url": "https://image.pollinations.ai",
            "protocol": "pollinations",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": POLLINATIONS_DEFAULT_IMAGE_MODELS,
            "chat_models": [],
            "video_models": [],
            "ms_loras": [],
            "ms_defaults_version": 0,
        },
        {
            "id": "pollinations-api",
            "name": "Pollinations (API Key)",
            "base_url": "https://gen.pollinations.ai/v1",
            "protocol": "openai",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [
                "flux", "gpt-image-2", "sdxl-lightning", "kontext", "dreamshaper",
                "nova-canvas", "klein", "qwen-image-3.0-pro", "luma-photon-1", "agnes-image-2.1-flash"
            ],
            "chat_models": [
                "openai", "deepseek", "claude-3.5-sonnet", "glm-5.3", "grok-4.6"
            ],
            "video_models": ["nova-reel"],
            "ms_loras": [],
            "ms_defaults_version": 0,
        },
        {
            "id": "gemini",
            "name": "Google Gemini (AI Studio)",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "protocol": "openai",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [
                "gemini-3.1-flash-image-preview", "gemini-3-pro-image-preview", "imagen-3.0-generate-002"
            ],
            "chat_models": [
                "gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-flash"
            ],
            "video_models": [],
            "ms_loras": [],
            "ms_defaults_version": 0,
        },
        {
            "id": "siliconflow-cn",
            "name": "硅基流动 (国内站)",
            "base_url": "https://api.siliconflow.cn/v1",
            "protocol": "openai",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [
                "black-forest-labs/FLUX.1-schnell",
                "black-forest-labs/FLUX.1-dev",
                "stabilityai/stable-diffusion-3-5-large",
                "stabilityai/stable-diffusion-3-medium",
                "Kwai-Kolors/Kolors",
            ],
            "chat_models": [
                "deepseek-ai/DeepSeek-V3",
                "deepseek-ai/DeepSeek-R1",
                "Qwen/Qwen2.5-72B-Instruct",
                "THUDM/glm-4-9b-chat",
            ],
            "video_models": ["Lightricks/LTX-Video"],
            "ms_loras": [],
            "ms_defaults_version": 0,
        },
        {
            "id": "siliconflow-com",
            "name": "SiliconFlow (国际站)",
            "base_url": "https://api.siliconflow.com/v1",
            "protocol": "openai",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [
                "black-forest-labs/FLUX.1-schnell",
                "black-forest-labs/FLUX.1-dev",
                "stabilityai/stable-diffusion-3-5-large",
                "stabilityai/stable-diffusion-3-medium",
            ],
            "chat_models": [
                "deepseek-ai/DeepSeek-V3",
                "deepseek-ai/DeepSeek-R1",
                "Qwen/Qwen2.5-72B-Instruct",
            ],
            "video_models": ["Lightricks/LTX-Video"],
            "ms_loras": [],
            "ms_defaults_version": 0,
        },
        {
            "id": "bfl",
            "name": "FLUX 官方 (BFL)",
            "base_url": "https://api.bfl.ml/v1",
            "protocol": "openai",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [
                "flux-pro-1.1-ultra",
                "flux-pro-1.1",
                "flux-pro",
                "flux-dev",
                "flux-pro-1.0-fill",
                "flux-pro-1.0-canny",
                "flux-pro-1.0-depth",
            ],
            "chat_models": [],
            "video_models": [],
            "ms_loras": [],
            "ms_defaults_version": 0,
        },
        {
            "id": "ltx-official",
            "name": "LTX 官方 (Lightricks)",
            "base_url": "https://api.lightricks.com/v1",
            "protocol": "openai",
            "image_request_mode": "openai",
            "image_generation_endpoint": "",
            "image_edit_endpoint": "",
            "enabled": True,
            "primary": False,
            "image_models": [],
            "chat_models": [],
            "video_models": [
                "ltx-video",
                "ltx-video-0.9.1",
                "ltx-2.3-22b-dev",
            ],
            "ms_loras": [],
            "ms_defaults_version": 0,
        },
    ]

def merge_default_api_providers(providers, inject_missing=True):
    merged = [dict(item) for item in providers]
    # 强制保留独立入口平台（不再强制 comfly）
    ms_default = next((d for d in default_api_providers() if d["id"] == "modelscope"), None)
    if ms_default:
        current = next((item for item in merged if item.get("id") == "modelscope"), None)
        if not current:
            if inject_missing:
                merged.append(ms_default)
        else:
            if not current.get("base_url"):
                current["base_url"] = ms_default["base_url"]
            seeded_version = int(current.get("ms_defaults_version") or 0)
            if seeded_version < MODELSCOPE_DEFAULTS_VERSION:
                image_models = model_list_from_values([*MODELSCOPE_DEFAULT_IMAGE_MODELS, *(current.get("image_models") or [])])
                chat_models = model_list_from_values([*MODELSCOPE_DEFAULT_CHAT_MODELS, *(current.get("chat_models") or [])])
                loras = normalize_ms_loras([*MODELSCOPE_DEFAULT_LORAS, *(current.get("ms_loras") or [])])
                current["image_models"] = image_models
                current["chat_models"] = chat_models
                current["ms_loras"] = loras
                current["ms_defaults_version"] = MODELSCOPE_DEFAULTS_VERSION
    rh_default = load_static_runninghub_provider() or next((d for d in default_api_providers() if d["id"] == "runninghub"), None)
    if rh_default:
        current = next((item for item in merged if item.get("id") == "runninghub"), None)
        if not current:
            if inject_missing:
                merged.append(rh_default)
        else:
            if not current.get("base_url") or current.get("base_url") == "https://www.runninghub.ai":
                current["base_url"] = RUNNINGHUB_CN_BASE_URL
            if current.get("name") == "RunningHub":
                current["name"] = "RunningHub (国内站)"
            if not current.get("protocol") or current.get("protocol") == "openai":
                current["protocol"] = "runninghub"
            current["image_models"] = model_list_from_values(current.get("image_models") or rh_default.get("image_models") or RUNNINGHUB_DEFAULT_IMAGE_MODELS)
            current["chat_models"] = model_list_from_values(current.get("chat_models") or rh_default.get("chat_models") or RUNNINGHUB_FALLBACK_CHAT_MODELS)
            current["video_models"] = model_list_from_values(current.get("video_models") or rh_default.get("video_models") or RUNNINGHUB_DEFAULT_VIDEO_MODELS)
            current["rh_apps"] = merge_runninghub_system_entries(rh_default.get("rh_apps") or [], current.get("rh_apps") or [], "app")
            current["rh_workflows"] = merge_runninghub_system_entries(rh_default.get("rh_workflows") or [], current.get("rh_workflows") or [], "workflow")
    rh_ai_default = next((d for d in default_api_providers() if d["id"] == "runninghub-ai"), None)
    if rh_ai_default:
        current_ai = next((item for item in merged if item.get("id") == "runninghub-ai"), None)
        if not current_ai:
            merged.append(rh_ai_default)
        else:
            if not current_ai.get("base_url"):
                current_ai["base_url"] = RUNNINGHUB_AI_BASE_URL
            if not current_ai.get("protocol") or current_ai.get("protocol") == "openai":
                current_ai["protocol"] = "runninghub"
    volc_default = next((d for d in default_api_providers() if d["id"] == "volcengine"), None)
    if volc_default:
        current = next((item for item in merged if item.get("id") == "volcengine"), None)
        legacy = next((item for item in merged if item.get("id") != "volcengine" and str(item.get("protocol") or "").lower() == "volcengine"), None)
        if not current:
            if legacy:
                legacy_image_models = model_list_from_values(legacy.get("image_models") or [])
                legacy_video_models = model_list_from_values(legacy.get("video_models") or [])
                current = {
                    **volc_default,
                    "base_url": legacy.get("base_url") or volc_default["base_url"],
                    "image_models": legacy_image_models or model_list_from_values(volc_default.get("image_models") or []),
                    "chat_models": model_list_from_values(legacy.get("chat_models") or []),
                    "video_models": legacy_video_models,
                }
                merged.append(current)
            elif inject_missing:
                merged.append(volc_default)
        else:
            if not current.get("base_url"):
                current["base_url"] = volc_default["base_url"]
            current["protocol"] = "volcengine"
            current["volcengine_project_name"] = str(current.get("volcengine_project_name") or VOLCENGINE_DEFAULT_PROJECT_NAME).strip() or VOLCENGINE_DEFAULT_PROJECT_NAME
            current["volcengine_region"] = str(current.get("volcengine_region") or VOLCENGINE_DEFAULT_REGION).strip() or VOLCENGINE_DEFAULT_REGION
    # 即梦 CLI 不再是强制保留的默认平台：仅在用户已添加了即梦协议的平台时，规范化其默认模型/地址。
    for current in merged:
        if not is_jimeng_provider(current):
            continue
        current["protocol"] = "jimeng"
        current["base_url"] = ""
        current["image_models"] = model_list_from_values([
            *[item for item in (current.get("image_models") or []) if str(item or "").strip() not in JIMENG_LEGACY_IMAGE_MODELS],
            *JIMENG_DEFAULT_IMAGE_MODELS,
        ])
        current["video_models"] = model_list_from_values([
            *[item for item in (current.get("video_models") or []) if str(item or "").strip() not in JIMENG_LEGACY_VIDEO_MODELS],
            *JIMENG_DEFAULT_VIDEO_MODELS,
        ])
    # OpenAI/Antigravity CLI 和即梦一样作为协议使用：用户选中 CLI 协议时再规范化模型与地址，不强制额外注入平台。
    for current in merged:
        current_protocol = str((current or {}).get("protocol") or "").strip().lower()
        if current_protocol not in {"codex", "gemini-cli"}:
            continue
        current["protocol"] = current_protocol
        current["base_url"] = ""
        default_image_models = CODEX_DEFAULT_IMAGE_MODELS if current_protocol == "codex" else GEMINI_CLI_DEFAULT_IMAGE_MODELS
        default_chat_models = CODEX_DEFAULT_CHAT_MODELS if current_protocol == "codex" else GEMINI_CLI_DEFAULT_CHAT_MODELS
        image_models = current.get("image_models") or []
        if current_protocol == "codex":
            image_models = [item for item in image_models if str(item or "").strip().lower() != "$imagegen"]
        current["image_models"] = model_list_from_values([*image_models, *default_image_models])
        current["chat_models"] = model_list_from_values([*(current.get("chat_models") or []), *default_chat_models])
        current["video_models"] = []
    poll_default = next((d for d in default_api_providers() if d["id"] == "pollinations"), None)
    if poll_default:
        current = next((item for item in merged if item.get("id") == "pollinations"), None)
        if not current:
            merged.append(poll_default)
        else:
            if not current.get("base_url"):
                current["base_url"] = poll_default["base_url"]
            if not current.get("image_models"):
                current["image_models"] = poll_default["image_models"]
            current["protocol"] = "pollinations"
            current["name"] = poll_default["name"]
    poll_api_default = next((d for d in default_api_providers() if d["id"] == "pollinations-api"), None)
    if poll_api_default:
        current = next((item for item in merged if item.get("id") == "pollinations-api"), None)
        if not current:
            merged.append(poll_api_default)
        else:
            if not current.get("base_url"):
                current["base_url"] = poll_api_default["base_url"]
            if not current.get("protocol"):
                current["protocol"] = "openai"
    gemini_default = next((d for d in default_api_providers() if d["id"] == "gemini"), None)
    if gemini_default:
        current = next((item for item in merged if item.get("id") == "gemini"), None)
        if not current:
            merged.append(gemini_default)
        else:
            if not current.get("base_url"):
                current["base_url"] = gemini_default["base_url"]
            current["chat_models"] = model_list_from_values([*(current.get("chat_models") or []), *gemini_default["chat_models"]])
            if not current.get("image_models"):
                current["image_models"] = gemini_default["image_models"]
    return merged

def normalize_model_list(values):
    return model_list_from_values(values)

def model_list_from_values(values):
    deduped = []
    for value in values or []:
        item = str(value or "").strip()
        if item and item not in deduped:
            selected_model(item, item)
            deduped.append(item)
    return deduped

def normalize_ms_loras(values):
    normalized = []
    seen = set()
    for raw in values or []:
        if not isinstance(raw, dict):
            continue
        lora_id = str(raw.get("id") or "").strip()
        if not lora_id:
            continue
        target_model = str(raw.get("target_model") or raw.get("model") or "").strip()
        if not target_model:
            continue
        key = (target_model, lora_id)
        if key in seen:
            continue
        seen.add(key)
        try:
            strength = float(raw.get("strength", raw.get("default_strength", 0.8)))
        except Exception:
            strength = 0.8
        strength = max(0.0, min(2.0, strength))
        name = re.sub(r"\s+", " ", str(raw.get("name") or "").strip())[:80]
        normalized.append({
            "id": lora_id[:180],
            "name": name or lora_id,
            "target_model": target_model[:180],
            "strength": strength,
            "enabled": bool(raw.get("enabled", True)),
            "note": str(raw.get("note") or "").strip()[:300],
        })
    return normalized

def normalize_runninghub_entry(raw, kind):
    if not isinstance(raw, dict):
        return None
    raw_id = raw.get("appId") if kind == "app" else raw.get("workflowId")
    entry_id = str(raw_id or raw.get("id") or "").strip()
    match = re.search(r"/run/(ai-app|workflow)/([0-9A-Za-z_-]+)", entry_id)
    if match:
        entry_id = match.group(2)
    if not entry_id:
        return None
    title = re.sub(r"\s+", " ", str(raw.get("title") or raw.get("name") or "").strip())[:80]
    note = str(raw.get("note") or raw.get("description") or "").strip()[:500]
    thumb = str(raw.get("thumbnail") or "").strip()
    if len(thumb) > 1500000:
        thumb = ""
    entry = {
        "id": entry_id[:80],
        "title": title or (f"AI 应用 {entry_id[-6:]}" if kind == "app" else f"工作流 {entry_id[-6:]}"),
        "note": note,
        "thumbnail": thumb,
        "enabled": bool(raw.get("enabled", True)),
    }
    if raw.get("hidden") is True:
        entry["hidden"] = True
    fields = raw.get("fields")
    if isinstance(fields, list):
        entry["fields"] = [runninghub_normalize_field(field) for field in fields if isinstance(field, dict)]
    if kind == "workflow":
        mode = str(raw.get("optionalImageMode") or raw.get("optional_image_mode") or "prune-workflow").strip()
        entry["optionalImageMode"] = mode or "prune-workflow"
        workflow_json = raw.get("workflowJson") or raw.get("workflow_json")
        if isinstance(workflow_json, dict):
            entry["workflowJson"] = workflow_json
    raw_payload = raw.get("raw")
    if isinstance(raw_payload, dict):
        entry["raw"] = raw_payload
    try:
        updated_at = int(raw.get("updatedAt") or raw.get("updated_at") or 0)
        if updated_at > 0:
            entry["updatedAt"] = updated_at
    except Exception:
        pass
    if kind == "app":
        entry["appId"] = entry["id"]
    else:
        entry["workflowId"] = entry["id"]
    return entry

def normalize_runninghub_entries(values, kind):
    normalized = []
    seen = set()
    for raw in values or []:
        entry = normalize_runninghub_entry(raw, kind)
        if not entry or entry["id"] in seen:
            continue
        seen.add(entry["id"])
        normalized.append(entry)
    return normalized

def runninghub_entry_id(entry, kind):
    if not isinstance(entry, dict):
        return ""
    raw_id = entry.get("workflowId") if kind == "workflow" else entry.get("appId")
    return str(raw_id or entry.get("id") or "").strip()

def static_runninghub_thumbnail_url(entry_id, kind):
    entry_id = re.sub(r"[^0-9A-Za-z_-]", "", str(entry_id or "").strip())
    kind_prefix = "workflow" if kind == "workflow" else "app"
    if not entry_id:
        return ""
    candidates = []
    for name in (f"{kind_prefix}-{entry_id}", entry_id):
        for ext in RUNNINGHUB_THUMBNAIL_EXTS:
            candidates.append((STATIC_RUNNINGHUB_THUMBNAIL_DIR, f"{name}{ext}"))
            candidates.append((STATIC_RUNNINGHUB_DIR, f"{name}{ext}"))
    for root, filename in candidates:
        path = os.path.abspath(os.path.join(root, filename))
        if not path.startswith(os.path.abspath(STATIC_RUNNINGHUB_DIR) + os.sep):
            continue
        if os.path.exists(path) and os.path.isfile(path):
            rel = os.path.relpath(path, STATIC_DIR).replace(os.sep, "/")
            return f"/static/{urllib.parse.quote(rel, safe='/._-')}?v={int(os.path.getmtime(path))}"
    return ""

def apply_runninghub_system_thumbnails(entries, kind):
    result = []
    for entry in normalize_runninghub_entries(entries or [], kind):
        if not entry.get("thumbnail"):
            thumb = static_runninghub_thumbnail_url(runninghub_entry_id(entry, kind), kind)
            if thumb:
                entry["thumbnail"] = thumb
        result.append(entry)
    return result

def merge_runninghub_entry_overlay(system_entry, user_entry):
    # 系统模板只提供默认值；同 ID 的用户配置优先，允许用户修改/隐藏内置模板。
    if not isinstance(system_entry, dict):
        return user_entry
    if not isinstance(user_entry, dict):
        return system_entry
    merged = {**system_entry, **user_entry}
    if not merged.get("thumbnail") and system_entry.get("thumbnail"):
        merged["thumbnail"] = system_entry.get("thumbnail")
    return merged

def merge_runninghub_system_entries(system_entries, user_entries, kind):
    merged = []
    index = {}
    hidden_ids = set()
    for entry in apply_runninghub_system_thumbnails(system_entries or [], kind):
        entry_id = runninghub_entry_id(entry, kind)
        if not entry_id:
            continue
        index[entry_id] = len(merged)
        merged.append(entry)
    for entry in apply_runninghub_system_thumbnails(user_entries or [], kind):
        entry_id = runninghub_entry_id(entry, kind)
        if not entry_id:
            continue
        if entry.get("hidden") is True:
            hidden_ids.add(entry_id)
            if entry_id in index:
                merged.pop(index[entry_id])
                index = {runninghub_entry_id(item, kind): idx for idx, item in enumerate(merged)}
            index[entry_id] = len(merged)
            merged.append(entry)
            continue
        if entry_id in index:
            merged[index[entry_id]] = merge_runninghub_entry_overlay(merged[index[entry_id]], entry)
        else:
            index[entry_id] = len(merged)
            merged.append(entry)
    return merged

def load_static_runninghub_provider():
    if not os.path.exists(STATIC_RUNNINGHUB_API_PROVIDERS_FILE):
        return None
    try:
        with open(STATIC_RUNNINGHUB_API_PROVIDERS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        candidates = raw if isinstance(raw, list) else raw.get("providers") if isinstance(raw, dict) else []
        if isinstance(raw, dict) and raw.get("id") == "runninghub":
            candidates = [raw]
        for item in candidates or []:
            if isinstance(item, dict) and str(item.get("id") or "").strip().lower() == "runninghub":
                provider = normalize_provider(item)
                provider["rh_apps"] = apply_runninghub_system_thumbnails(provider.get("rh_apps") or [], "app")
                provider["rh_workflows"] = apply_runninghub_system_thumbnails(provider.get("rh_workflows") or [], "workflow")
                return provider
    except Exception as e:
        logger.warning(f"加载 static RunningHub 配置失败: {e}")
    return None

def merge_runninghub_provider_with_static(provider):
    static_provider = load_static_runninghub_provider()
    if not static_provider:
        return provider
    if not isinstance(provider, dict):
        return static_provider
    merged = {**static_provider, **provider}
    merged["protocol"] = "runninghub"
    merged["image_models"] = model_list_from_values(provider.get("image_models") or static_provider.get("image_models") or RUNNINGHUB_DEFAULT_IMAGE_MODELS)
    merged["chat_models"] = model_list_from_values(provider.get("chat_models") or static_provider.get("chat_models") or RUNNINGHUB_FALLBACK_CHAT_MODELS)
    merged["video_models"] = model_list_from_values(provider.get("video_models") or static_provider.get("video_models") or RUNNINGHUB_DEFAULT_VIDEO_MODELS)
    merged["rh_apps"] = merge_runninghub_system_entries(static_provider.get("rh_apps") or [], provider.get("rh_apps") or [], "app")
    merged["rh_workflows"] = merge_runninghub_system_entries(static_provider.get("rh_workflows") or [], provider.get("rh_workflows") or [], "workflow")
    return normalize_provider(merged)

def preserve_runninghub_hidden_overrides(provider):
    if not isinstance(provider, dict) or provider.get("id") not in {"runninghub", "runninghub-ai", "runninghub-cn"}:
        return provider
    static_provider = load_static_runninghub_provider()
    if not static_provider:
        return provider
    provider = dict(provider)
    for list_key, kind in (("rh_apps", "app"), ("rh_workflows", "workflow")):
        current = normalize_runninghub_entries(provider.get(list_key) or [], kind)
        current_ids = {runninghub_entry_id(item, kind) for item in current}
        for static_entry in static_provider.get(list_key) or []:
            entry_id = runninghub_entry_id(static_entry, kind)
            if entry_id and entry_id not in current_ids:
                tombstone = normalize_runninghub_entry({**static_entry, "enabled": False, "hidden": True}, kind)
                if tombstone:
                    current.append(tombstone)
        provider[list_key] = current
    return provider

def normalize_endpoint_override(value, label):
    endpoint = str(value or "").strip()
    if not endpoint:
        return ""
    if len(endpoint) > 300 or re.search(r"\s", endpoint):
        raise HTTPException(status_code=400, detail=f"{label} 不合法，请填写类似 /v1/images/edits 的路径")
    if re.match(r"^https?://", endpoint, re.I):
        return endpoint.rstrip("/")
    if not endpoint.startswith("/"):
        raise HTTPException(status_code=400, detail=f"{label} 需要以 /v1/... 开头，或填写完整 http(s) 地址")
    return endpoint

def normalize_image_request_mode(value):
    mode = str(value or "").strip().lower()
    return mode if mode in SUPPORTED_IMAGE_REQUEST_MODES else "openai"

LOCKED_RECOMMENDED_PROVIDER_RULES = {
    "exellome": {
        "names": {"exellome"},
        "base_urls": {"https://new.exellome.online"},
        "protocol": "apimart",
        "image_request_mode": "openai-video-proxy",
        "video_models": [],
    },
    "fhl": {
        "names": {"fhl"},
        "base_urls": {"https://www.fhl.mom"},
        "protocol": "openai",
        "image_request_mode": "openai",
        "video_models": [],
    },
}

def is_tudou_base_url(base_url=""):
    """Only recognize the official Tudou host, never a substring in another provider URL."""
    try:
        host = (urllib.parse.urlsplit(str(base_url or "").strip()).hostname or "").lower()
    except Exception:
        host = ""
    return host == "api.ai-tudou.net" or host.endswith(".ai-tudou.net")

def locked_recommended_provider_rule(provider_id="", name="", base_url=""):
    pid = str(provider_id or "").strip().lower()
    pname = str(name or "").strip().lower()
    pbase = str(base_url or "").strip().rstrip("/").lower()
    try:
        phost = urllib.parse.urlsplit(pbase).netloc.lower()
    except Exception:
        phost = ""
    for key, rule in LOCKED_RECOMMENDED_PROVIDER_RULES.items():
        hosts = {urllib.parse.urlsplit(url).netloc.lower() for url in rule["base_urls"]}
        if pid == key or pname in rule["names"] or pbase in rule["base_urls"] or (phost and phost in hosts):
            return rule
    return None

def apply_locked_recommended_model_rules(base_url="", grouped=None):
    rule = locked_recommended_provider_rule("", "", base_url)
    if not rule or "video_models" not in rule:
        return grouped
    grouped = {key: list(value or []) for key, value in (grouped or {}).items()}
    grouped.setdefault("image", [])
    grouped.setdefault("chat", [])
    grouped["video"] = list(rule.get("video_models") or [])
    return grouped

def provider_endpoint_url(provider, key, default_path):
    base_url = str((provider or {}).get("base_url") or AI_BASE_URL).strip().rstrip("/")
    override = str((provider or {}).get(key) or "").strip()
    if override:
        if re.match(r"^https?://", override, re.I):
            return override.rstrip("/")
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}{override}"
        return override
    for prefix in ("/api/v3", "/v1beta", "/v1", "/v2"):
        if base_url.endswith(prefix) and default_path.startswith(f"{prefix}/"):
            return f"{base_url}{default_path[len(prefix):]}"
    return f"{base_url}{default_path}"

def runninghub_endpoint_url(provider, path):
    pid = str((provider or {}).get("id") or "").strip().lower()
    default_base = RUNNINGHUB_AI_BASE_URL if pid in {"runninghub-ai", "runninghub-global"} else RUNNINGHUB_CN_BASE_URL
    base_url = str((provider or {}).get("base_url") or default_base).strip().rstrip("/")
    return f"{base_url}{path}"

def runninghub_openapi_base_url(provider=None):
    pid = str((provider or {}).get("id") or "").strip().lower()
    default_base = RUNNINGHUB_AI_BASE_URL if pid in {"runninghub-ai", "runninghub-global"} else RUNNINGHUB_CN_BASE_URL
    base_url = str((provider or {}).get("base_url") or default_base).strip().rstrip("/")
    if base_url.endswith("/openapi/v2"):
        return base_url
    return f"{base_url}/openapi/v2"

def runninghub_openapi_url(provider, path=""):
    path = str(path or "").strip()
    if path.startswith("http://") or path.startswith("https://"):
        return path
    path = path.lstrip("/")
    base = runninghub_openapi_base_url(provider)
    return f"{base}/{path}" if path else base

def normalize_provider(item):
    provider_id = str(item.get("id") or "").strip().lower()
    if not PROVIDER_ID_RE.fullmatch(provider_id):
        raise HTTPException(status_code=400, detail=f"API 平台 ID 不合法：{provider_id or '(empty)'}")
    name = re.sub(r"\s+", " ", str(item.get("name") or provider_id).strip())[:60] or provider_id
    base_url = str(item.get("base_url") or "").strip().rstrip("/")
    if base_url and not re.match(r"^https?://", base_url):
        raise HTTPException(status_code=400, detail=f"{name} 的 Base URL 需要以 http:// 或 https:// 开头")
    protocol = str(item.get("protocol") or "openai").strip().lower()
    if protocol == "tudou":
        protocol = "openai"
    if protocol not in SUPPORTED_PROVIDER_PROTOCOLS:
        protocol = "openai"
    image_request_mode = detect_image_request_mode(base_url, item.get("image_models") or []) or normalize_image_request_mode(item.get("image_request_mode"))
    image_generation_endpoint = normalize_endpoint_override(item.get("image_generation_endpoint"), "文生图端口")
    image_edit_endpoint = normalize_endpoint_override(item.get("image_edit_endpoint"), "图生图/编辑端口")
    # 修图分发模式：instruction = 图文多模态指令；edits = OpenAI /images/edits。
    # 空串表示未显式指定，由 core.image_edit.detect_edit_dispatch_mode 按模型名推断。
    image_edit_mode = str(item.get("image_edit_mode") or "").strip().lower()
    if image_edit_mode not in ("instruction", "edits"):
        image_edit_mode = ""
    volc_project = re.sub(r"\s+", " ", str(item.get("volcengine_project_name") or "").strip())[:80]
    volc_region = re.sub(r"\s+", " ", str(item.get("volcengine_region") or "").strip())[:40]
    if provider_id == "volcengine":
        protocol = "volcengine"
        base_url = base_url or VOLCENGINE_DEFAULT_BASE_URL
        volc_project = volc_project or VOLCENGINE_DEFAULT_PROJECT_NAME
        volc_region = volc_region or VOLCENGINE_DEFAULT_REGION
    if provider_id == "jimeng" or protocol == "jimeng":
        protocol = "jimeng"
        base_url = ""
    if protocol in {"codex", "gemini-cli"}:
        base_url = ""
    if provider_id in {"runninghub", "runninghub-ai"}:
        protocol = "runninghub"
        default_base = RUNNINGHUB_AI_BASE_URL if provider_id == "runninghub-ai" else RUNNINGHUB_CN_BASE_URL
        base_url = base_url or default_base
    locked_rule = locked_recommended_provider_rule(provider_id, name, base_url)
    if locked_rule:
        protocol = locked_rule["protocol"]
        image_request_mode = locked_rule["image_request_mode"]
    video_models = model_list_from_values(item.get("video_models") or (RUNNINGHUB_DEFAULT_VIDEO_MODELS if provider_id in {"runninghub", "runninghub-ai"} else []))
    if locked_rule and "video_models" in locked_rule:
        video_models = model_list_from_values(locked_rule.get("video_models") or [])
    return {
        "id": provider_id,
        "name": name,
        "base_url": base_url,
        "protocol": protocol,
        "image_request_mode": image_request_mode,
        "image_generation_endpoint": image_generation_endpoint,
        "image_edit_endpoint": image_edit_endpoint,
        "image_edit_mode": image_edit_mode,
        "enabled": bool(item.get("enabled", True)),
        "primary": bool(item.get("primary", False)),
        "image_models": model_list_from_values(item.get("image_models") or (RUNNINGHUB_DEFAULT_IMAGE_MODELS if provider_id in {"runninghub", "runninghub-ai"} else [])),
        "chat_models": model_list_from_values(item.get("chat_models") or (RUNNINGHUB_FALLBACK_CHAT_MODELS if provider_id in {"runninghub", "runninghub-ai"} else [])),
        "video_models": video_models,
        "model_names": normalize_model_name_map(item.get("model_names")),
        "model_protocols": normalize_model_protocols(item.get("model_protocols")),
        "ms_loras": normalize_ms_loras(item.get("ms_loras") or []),
        "ms_defaults_version": int(item.get("ms_defaults_version") or 0),
        "rh_apps": normalize_runninghub_entries(item.get("rh_apps") or [], "app"),
        "rh_workflows": normalize_runninghub_entries(item.get("rh_workflows") or [], "workflow"),
        "volcengine_project_name": volc_project,
        "volcengine_region": volc_region,
    }

def load_api_providers():
    return _deepcopy_providers(_api_providers_cache.get())


def invalidate_api_providers_cache():
    _api_providers_cache.invalidate()


def _deepcopy_providers(providers):
    """对 provider 列表做逐条浅拷贝 + 嵌套可变字段拷贝。

    不用 copy.deepcopy：provider 结构里可能含大列表（模型表 / LoRA / 工作流），
    深拷贝在热路径上的开销不划算。逐条新建 dict 并拷贝其中的可变字段即可阻断
    「调用方原地修改污染缓存」这一类问题。
    """
    out = []
    for item in providers:
        if not isinstance(item, dict):
            out.append(item)
            continue
        new_item = dict(item)
        for key in ("image_models", "chat_models", "video_models", "ms_loras",
                    "rh_apps", "rh_workflows"):
            val = new_item.get(key)
            if isinstance(val, list):
                new_item[key] = list(val)
        models = new_item.get("model_names")
        if isinstance(models, dict):
            new_item["model_names"] = dict(models)
        out.append(new_item)
    return out

def save_api_providers(providers):
    target_dir = os.path.dirname(os.path.abspath(API_PROVIDERS_FILE)) or DATA_DIR
    os.makedirs(target_dir, exist_ok=True)
    with GLOBAL_CONFIG_LOCK:
        if os.path.exists(API_PROVIDERS_FILE):
            try:
                backup_dir = os.path.join(DATA_DIR, ".provider_backups")
                os.makedirs(backup_dir, exist_ok=True)
                ts = time.time_ns()
                backup_path = os.path.join(backup_dir, f"api_providers_{ts}.json")
                shutil.copy2(API_PROVIDERS_FILE, backup_path)
                def _backup_sort_key(p: str):
                    m = re.search(r"api_providers_(\d+)\.json$", p)
                    if m:
                        return (int(m.group(1)), p)
                    return (0, p)
                backups = sorted(glob.glob(os.path.join(backup_dir, "api_providers_*.json")), key=_backup_sort_key)
                if len(backups) > 5:
                    for old_bak in backups[:-5]:
                        try:
                            os.remove(old_bak)
                        except OSError:
                            pass
            except Exception as e:
                logger.warning(f"保存 API 平台备份失败: {e}")
        temp_file = os.path.join(target_dir, f".api_providers_{os.getpid()}_{time.time_ns()}.tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(providers, f, ensure_ascii=False, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(temp_file, API_PROVIDERS_FILE)
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass
        invalidate_api_providers_cache()

def default_runninghub_static_provider():
    return {
        "id": "runninghub",
        "name": "RunningHub",
        "base_url": RUNNINGHUB_DEFAULT_BASE_URL,
        "protocol": "runninghub",
        "image_generation_endpoint": "",
        "image_edit_endpoint": "",
        "enabled": True,
        "primary": False,
        "image_models": list(RUNNINGHUB_DEFAULT_IMAGE_MODELS),
        "chat_models": list(RUNNINGHUB_FALLBACK_CHAT_MODELS),
        "video_models": list(RUNNINGHUB_DEFAULT_VIDEO_MODELS),
        "model_protocols": {},
        "ms_loras": [],
        "ms_defaults_version": 0,
        "rh_apps": [],
        "rh_workflows": [],
    }

def mutate_static_runninghub_provider(mutator):
    os.makedirs(STATIC_RUNNINGHUB_DIR, exist_ok=True)
    raw = []
    if os.path.exists(STATIC_RUNNINGHUB_API_PROVIDERS_FILE):
        try:
            with open(STATIC_RUNNINGHUB_API_PROVIDERS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as exc:
            logger.warning(f"读取 static RunningHub 模板失败，将重建基础模板: {exc}")
            raw = []
    if isinstance(raw, dict) and str(raw.get("id") or "").strip().lower() == "runninghub":
        provider = raw
    else:
        if isinstance(raw, list):
            providers = raw
        elif isinstance(raw, dict):
            providers = raw.setdefault("providers", [])
            if not isinstance(providers, list):
                providers = []
                raw["providers"] = providers
        else:
            raw = []
            providers = raw
        provider = next((
            item for item in providers
            if isinstance(item, dict) and str(item.get("id") or "").strip().lower() == "runninghub"
        ), None)
        if provider is None:
            provider = default_runninghub_static_provider()
            providers.append(provider)
    changed = mutator(provider)
    if changed is False:
        return False
    with open(STATIC_RUNNINGHUB_API_PROVIDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return True

def sync_runninghub_provider_workflows_to_static_template(provider):
    if not isinstance(provider, dict) or str(provider.get("id") or "").strip().lower() != "runninghub":
        return False
    workflows = []
    seen = set()
    for entry in normalize_runninghub_entries(provider.get("rh_workflows") or [], "workflow"):
        key = runninghub_workflow_store_key(entry.get("workflowId") or entry.get("id"))
        if not key or entry.get("hidden") is True or key in seen:
            continue
        seen.add(key)
        workflows.append(entry)
    def apply_workflows(static_provider):
        static_provider["id"] = "runninghub"
        static_provider["name"] = static_provider.get("name") or "RunningHub"
        static_provider["base_url"] = static_provider.get("base_url") or RUNNINGHUB_DEFAULT_BASE_URL
        static_provider["protocol"] = "runninghub"
        static_provider["rh_workflows"] = workflows
        if "rh_apps" not in static_provider or not isinstance(static_provider.get("rh_apps"), list):
            static_provider["rh_apps"] = []
        return True
    return mutate_static_runninghub_provider(apply_workflows)

def public_provider(provider):
    pid = provider.get("id")
    if pid in {"runninghub", "runninghub-ai"}:
        try:
            provider = runninghub_provider_with_workflow_store(provider)
        except Exception:
            pass
    key = provider_env_key_value(provider["id"])
    item = {
        **provider,
        "has_key": bool(key),
        "key_preview": mask_secret(key),
        "key_env": provider_key_env(provider["id"]),
    }
    if pid in {"runninghub", "runninghub-ai"}:
        wallet_key = runninghub_wallet_key_value(pid)
        item.update({
            "has_wallet_key": bool(wallet_key),
            "wallet_key_preview": mask_secret(wallet_key),
            "wallet_key_env": runninghub_wallet_key_env(pid),
        })
    if provider.get("id") == "volcengine":
        ak = volcengine_access_key_value()
        sk = volcengine_secret_key_value()
        item.update({
            "has_volcengine_access_key": bool(ak),
            "volcengine_access_key_preview": mask_secret(ak),
            "volcengine_access_key_env": volcengine_access_key_env(),
            "has_volcengine_secret_key": bool(sk),
            "volcengine_secret_key_preview": mask_secret(sk),
            "volcengine_secret_key_env": volcengine_secret_key_env(),
            "volcengine_project_name": provider.get("volcengine_project_name") or VOLCENGINE_DEFAULT_PROJECT_NAME,
            "volcengine_region": provider.get("volcengine_region") or VOLCENGINE_DEFAULT_REGION,
        })
    return item

def public_api_providers():
    return [public_provider(p) for p in load_api_providers()]

def provider_has_saved_key(provider_id: str) -> bool:
    return bool(provider_env_key_value(provider_id))

def _pick_fallback_provider(providers):
    enabled = [p for p in (providers or []) if p.get("enabled", True)]
    return (
        next((p for p in enabled if p.get("id") != "modelscope" and (provider_has_saved_key(p.get("id", "")) or bool(p.get("api_key")))), None)
        or next((p for p in enabled if p.get("keyless")), None)
        or next((p for p in enabled if p.get("id") != "modelscope"), None)
        or (providers[0] if providers else None)
    )

def get_primary_provider_id(providers=None):
    providers = providers if providers is not None else load_api_providers()
    primary = next((p for p in providers if p.get("primary") and p.get("enabled", True)), None)
    if primary:
        return primary["id"]
    fallback = _pick_fallback_provider(providers)
    return fallback["id"] if fallback else (providers[0]["id"] if providers else "modelscope")

def get_api_provider(provider_id="comfly"):
    providers = load_api_providers()
    target = (provider_id or "").strip().lower()
    # 兼容旧的 "comfly" 硬编码：若 comfly 不存在或未指定，回退到首选 provider
    if not target or not any(p["id"] == target for p in providers):
        target = get_primary_provider_id(providers)
    provider = next((p for p in providers if p["id"] == target), None)
    if not provider:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台：{target}")
    if not provider.get("enabled", True):
        raise HTTPException(status_code=400, detail=f"API 平台已禁用：{provider.get('name') or target}")
    return provider

def get_api_provider_exact(provider_id: str):
    providers = load_api_providers()
    target = (provider_id or "").strip().lower()
    provider = next((p for p in providers if p["id"] == target), None)
    if not provider:
        raise HTTPException(status_code=400, detail=f"未找到 API 平台：{target or '(empty)'}。新增平台未保存时请使用当前表单拉取模型。")
    if not provider.get("enabled", True):
        raise HTTPException(status_code=400, detail=f"API 平台已禁用：{provider.get('name') or target}")
    return provider

def modelscope_provider_config():
    return get_api_provider_exact("modelscope")

def modelscope_api_key(explicit_key: str = ""):
    cleaned = strip_auth_scheme(explicit_key, "Bearer")
    if cleaned and not key_looks_masked(cleaned):
        return cleaned
    return (
        strip_auth_scheme(provider_env_key_value("modelscope"), "Bearer")
        or strip_auth_scheme(MODELSCOPE_API_KEY, "Bearer")
    )

def modelscope_api_root(provider=None):
    provider = provider or modelscope_provider_config()
    base_root = str((provider or {}).get("base_url") or MODELSCOPE_CHAT_BASE_URL).strip().rstrip("/")
    if not base_root:
        base_root = MODELSCOPE_CHAT_BASE_URL
    return base_root if base_root.endswith("/v1") else f"{base_root}/v1"

def modelscope_image_api_root():
    return MODELSCOPE_CHAT_BASE_URL.rstrip("/")

def env_quote(value):
    text = str(value or "")
    if re.search(r"[\r\n\x00]", text):
        raise ValueError("密钥值不得包含换行或空字符")
    if not text or re.search(r"\s|#|['\"]", text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text

def update_env_values(updates):
    target_dir = os.path.dirname(API_ENV_FILE)
    os.makedirs(target_dir, exist_ok=True)
    with GLOBAL_CONFIG_LOCK:
        lines = []
        if os.path.exists(API_ENV_FILE):
            with open(API_ENV_FILE, "r", encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        seen = set()
        next_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                next_lines.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key in updates:
                next_lines.append(f"{key}={env_quote(updates[key])}")
                os.environ[key] = str(updates[key] or "")
                seen.add(key)
            else:
                next_lines.append(line)
        for key, value in updates.items():
            if key not in seen:
                next_lines.append(f"{key}={env_quote(value)}")
                os.environ[key] = str(value or "")
        temp_file = os.path.join(target_dir, f".env_{os.getpid()}_{time.time_ns()}.tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write("\n".join(next_lines).rstrip() + "\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(temp_file, API_ENV_FILE)
            invalidate_api_env_cache()
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass
