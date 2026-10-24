"""Providers, Models & Configuration Router for Infinite-Canvas.

Decoupled router providing API provider management, model introspection,
upstream connectivity probing, and runtime configuration endpoints.
"""
import os
import re
import sys
import json
import time
import base64
import logging
from typing import Dict, Any, List, Optional, Callable
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
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
    GLOBAL_CONFIG_FILE,
    AI_BASE_URL,
    AI_API_KEY,
    CHAT_MODEL,
    CHAT_MODELS,
    IMAGE_MODEL,
    IMAGE_MODELS,
    VIDEO_MODELS,
    COMFYUI_INSTANCES,
    MODELSCOPE_CHAT_MODELS,
    POLLINATIONS_DEFAULT_IMAGE_MODELS,
    VOLCENGINE_DEFAULT_PROJECT_NAME,
    VOLCENGINE_DEFAULT_REGION,
    RUNNINGHUB_CN_BASE_URL,
    RUNNINGHUB_AI_BASE_URL,
    RUNNINGHUB_DEFAULT_BASE_URL,
    SUPPORTED_PROVIDER_PROTOCOLS,
    public_api_providers,
    load_api_providers,
    modelscope_api_key,
    normalize_provider,
    get_api_provider_exact,
    preserve_runninghub_hidden_overrides,
    prune_runninghub_workflow_store_for_provider,
    provider_key_env,
    key_looks_masked,
    log_upstream_call,
    runninghub_wallet_key_env,
    volcengine_access_key_env,
    volcengine_secret_key_env,
    save_api_providers,
    sync_runninghub_provider_workflows_to_static_template,
    update_env_values,
    reload_env_globals,
    public_provider,
    mask_secret,
    bearer_auth_value,
    provider_endpoint_url,
    provider_env_key_value,
    provider_protocol,
    volcengine_provider_api_key,
    JIMENG_DEFAULT_IMAGE_MODELS,
    JIMENG_DEFAULT_VIDEO_MODELS,
    normalize_image_request_mode,
    apply_locked_recommended_model_rules,
    runninghub_openapi_url,
    detect_image_request_mode,
    AGNES_DEFAULT_VIDEO_MODELS,
    DASHSCOPE_DEFAULT_VIDEO_MODELS,
    is_tudou_base_url,
    _upstream_request_hook,
    _upstream_response_hook,
)
from core.pydantic_compat import dump_pydantic
from routers.common import (
    looks_like_html_response,
    is_pollinations_provider,
    is_dashscope_provider,
    is_codex_provider,
    is_gemini_cli_provider,
)

logger = logging.getLogger("infinite_canvas.providers")
_server_logger = logging.getLogger("dx.server")

router = APIRouter(tags=["providers"])

class ApiProviderPayload(BaseModel):
    id: str = ""
    name: str = ""
    base_url: str = ""
    protocol: str = "openai"
    image_request_mode: str = "openai"
    image_generation_endpoint: str = ""
    image_edit_endpoint: str = ""
    # 显式声明修图分发模式（instruction / edits）。此前该键既不在 payload 上、
    # 也不由 normalize_provider 产出，导致 openai-edits 分支实际不可达。
    image_edit_mode: str = ""
    enabled: bool = True
    primary: bool = False
    image_models: List[str] = Field(default_factory=list)
    chat_models: List[str] = Field(default_factory=list)
    video_models: List[str] = Field(default_factory=list)
    model_names: Dict[str, str] = Field(default_factory=dict)
    model_protocols: Dict[str, str] = Field(default_factory=dict)
    ms_loras: List[Dict[str, Any]] = Field(default_factory=list)
    ms_defaults_version: int = 0
    rh_apps: List[Dict[str, Any]] = Field(default_factory=list)
    rh_workflows: List[Dict[str, Any]] = Field(default_factory=list)
    volcengine_project_name: str = VOLCENGINE_DEFAULT_PROJECT_NAME
    volcengine_region: str = VOLCENGINE_DEFAULT_REGION
    volcengine_access_key_id: Optional[str] = None
    volcengine_secret_access_key: Optional[str] = None
    api_key: Optional[str] = None
    wallet_api_key: Optional[str] = None
    clear_key: bool = False
    clear_wallet_key: bool = False
    clear_volcengine_access_key_id: bool = False
    clear_volcengine_secret_access_key: bool = False


class TestConnectionPayload(BaseModel):
    base_url: str = ""
    api_key: str = ""
    protocol: str = "openai"
    image_request_mode: str = "openai"
    model: str = ""
    provider_id: str = ""
    models: List[str] = Field(default_factory=list)
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Dict[str, Any] = Field(default_factory=dict)
    probe_type: str = "all"
    auth_header_key: str = "Authorization"
    auth_header_prefix: str = "Bearer "
    volcengine_access_key_id: str = ""
    volcengine_secret_access_key: str = ""
    volcengine_project_name: str = "default"
    volcengine_region: str = "cn-beijing"

@router.get("/api/config")
async def ai_config():
    preferred_chat_model = next((m for m in CHAT_MODELS if m == "gpt-5.5"), CHAT_MODELS[0] if CHAT_MODELS else CHAT_MODEL)
    providers = public_api_providers()
    return {
        "base_url": AI_BASE_URL,
        "chat_model": preferred_chat_model,
        "image_model": IMAGE_MODEL,
        "chat_models": CHAT_MODELS,
        "image_models": IMAGE_MODELS,
        "video_models": VIDEO_MODELS,
        "comfy_instances": COMFYUI_INSTANCES,
        "api_providers": providers,
        "has_api_key": bool(AI_API_KEY),
        "ms_chat_models": MODELSCOPE_CHAT_MODELS,
        "has_ms_key": bool(modelscope_api_key()),
    }

@router.get("/api/models")
async def ai_models():
    return {"chat_models": CHAT_MODELS, "image_models": IMAGE_MODELS, "video_models": VIDEO_MODELS}

@router.get("/api/providers")
async def api_providers():
    return {"providers": public_api_providers()}

@router.put("/api/providers")
async def save_providers(payload: List[ApiProviderPayload]):
    providers = []
    env_updates = {}
    # 收集每个 item 的 primary 字段
    raw_primary_flags = [bool(getattr(item, "primary", False)) for item in payload]
    for item in payload:
        provider = normalize_provider(dump_pydantic(item, exclude={"api_key"}))
        base_url = str(provider.get("base_url") or "").strip()
        if base_url:
            try:
                # allow_private=True：Provider 的 base_url 允许指向局域网自建服务
                # （本项目的核心场景之一，如自建 OneAPI / ComfyUI 网关），
                # 云元数据与保留网段仍由 validate_safe_url 内部无条件拦截。
                # 密钥外泄的真正防线是下面的 check_key_host_binding，而非收紧此处：
                # 收紧会让用户无法配置任何内网 Provider，属功能回归。
                validate_safe_url(base_url, allow_private=True)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"API 平台 [{provider.get('name') or provider.get('id')}] 请求地址非法或受限: {e}")
            # 写入路径同样要校验密钥主机绑定，否则改写 base_url 后
            # 服务端会把 .env 中的真实 Key 发往攻击者地址（见 round 8 审查 CRITICAL）
            check_key_host_binding(provider["id"], base_url, bool(item.api_key))
        if provider["id"] in {"runninghub", "runninghub-ai"}:
            provider = preserve_runninghub_hidden_overrides(provider)
            prune_runninghub_workflow_store_for_provider(provider)
        if any(existing["id"] == provider["id"] for existing in providers):
            raise HTTPException(status_code=400, detail=f"API 平台 ID 重复：{provider['id']}")
        providers.append(provider)
        key_env = provider_key_env(provider["id"])
        if item.clear_key:
            env_updates[key_env] = ""
        elif item.api_key is not None and item.api_key.strip():
            if key_looks_masked(item.api_key):
                log_upstream_call("KEY-GUARD", provider["id"], provider=provider["id"],
                                  error="masked api_key ignored, keeping stored key")
            else:
                env_updates[key_env] = item.api_key.strip()
        if provider["id"] in {"runninghub", "runninghub-ai"}:
            wallet_env = runninghub_wallet_key_env(provider["id"])
            if item.clear_wallet_key:
                env_updates[wallet_env] = ""
            elif item.wallet_api_key is not None and item.wallet_api_key.strip():
                if key_looks_masked(item.wallet_api_key):
                    log_upstream_call("KEY-GUARD", provider["id"], provider=provider["id"],
                                      error="masked wallet_key ignored, keeping stored key")
                else:
                    env_updates[wallet_env] = item.wallet_api_key.strip()
        if provider["id"] == "volcengine":
            ak_env = volcengine_access_key_env()
            sk_env = volcengine_secret_key_env()
            if item.clear_volcengine_access_key_id:
                env_updates[ak_env] = ""
            elif item.volcengine_access_key_id is not None and item.volcengine_access_key_id.strip():
                if not key_looks_masked(item.volcengine_access_key_id):
                    env_updates[ak_env] = item.volcengine_access_key_id.strip()
            if item.clear_volcengine_secret_access_key:
                env_updates[sk_env] = ""
            elif item.volcengine_secret_access_key is not None and item.volcengine_secret_access_key.strip():
                if not key_looks_masked(item.volcengine_secret_access_key):
                    env_updates[sk_env] = item.volcengine_secret_access_key.strip()
        if provider["id"] == "comfly":
            env_updates["COMFLY_BASE_URL"] = provider["base_url"]
            env_updates["IMAGE_MODELS"] = ",".join(provider["image_models"])
            env_updates["CHAT_MODELS"] = ",".join(provider["chat_models"])
            env_updates["VIDEO_MODELS"] = ",".join(provider.get("video_models") or [])
        if provider["id"] == "modelscope":
            env_updates["MODELSCOPE_CHAT_MODELS"] = ",".join(provider["chat_models"])
        if provider["id"] in {"runninghub", "runninghub-ai"}:
            provider["protocol"] = "runninghub"
        if provider["id"] == "volcengine":
            provider["protocol"] = "volcengine"
    if not providers:
        raise HTTPException(status_code=400, detail="至少保留一个 API 平台")
    # 强制最多一个 primary（取最后被标记的；都没标记则保持原样不强制）
    primary_indices = [i for i, flag in enumerate(raw_primary_flags) if flag]
    if primary_indices:
        winner = primary_indices[-1]
        for i, p in enumerate(providers):
            p["primary"] = (i == winner)
    save_api_providers(providers)
    for rh_id in ("runninghub", "runninghub-ai"):
        runninghub_provider = next((item for item in providers if item.get("id") == rh_id), None)
        if runninghub_provider:
            sync_runninghub_provider_workflows_to_static_template(runninghub_provider)
    if env_updates:
        update_env_values(env_updates)
        reload_env_globals()   # 立即将最新 env 值同步回模块全局变量，无需重启
    return {"providers": [public_provider(p) for p in providers]}

# --- ModelScope Token (从 env 读取，不再支持通过 UI 修改) ---

# --- /api/config/token 路由已解耦迁移至 routers/providers.py ---
@router.get("/api/config/token")
async def get_global_token():
    # 优先读 env，回退到 global_config.json（兼容旧数据）；绝不返回明文密钥
    saved_token = modelscope_api_key()
    if saved_token:
        return {"token": mask_secret(saved_token), "configured": True}
    if os.path.exists(GLOBAL_CONFIG_FILE):
        try:
            with open(GLOBAL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                ms_token = str(config.get("modelscope_token", "") or "").strip()
                if ms_token:
                    return {"token": mask_secret(ms_token), "configured": True}
        except Exception:
            pass
    return {"token": "", "configured": False}

# --- 在线生图 (COMFLY) ---

# --- TestConnectionPayload 已解耦迁移至 routers/providers.py ---

def protocol_from_payload(payload):
    provider_id = str(getattr(payload, "provider_id", "") or "").strip().lower()
    if provider_id == "volcengine":
        return "volcengine"
    if provider_id in {"runninghub", "runninghub-ai"}:
        return "runninghub"
    if provider_id == "jimeng":
        return "jimeng"
    explicit_proto = str(getattr(payload, "protocol", "") or "").strip().lower()
    if explicit_proto and explicit_proto in SUPPORTED_PROVIDER_PROTOCOLS and explicit_proto != "openai":
        return explicit_proto
    if provider_id == "pollinations" or "pollinations" in provider_id or "pollinations" in (payload.base_url or "").lower():
        if explicit_proto == "openai" and "gen.pollinations.ai" in (payload.base_url or "").lower():
            return "openai"
        return "pollinations"
    base_url = str(getattr(payload, "base_url", "") or "").strip().lower()
    if "runninghub.cn" in base_url or "runninghub.ai" in base_url:
        return "runninghub"
    protocol = str(getattr(payload, "protocol", "") or "openai").strip().lower()
    return protocol if protocol in SUPPORTED_PROVIDER_PROTOCOLS else "openai"

def api_key_from_payload(payload, protocol: str = ""):
    explicit = str(getattr(payload, "api_key", "") or "").strip()
    provider_id = str(getattr(payload, "provider_id", "") or "").strip().lower()
    protocol = str(protocol or protocol_from_payload(payload) or "").strip().lower()
    if explicit:
        return explicit
    if provider_id:
        if provider_id in {"runninghub", "runninghub-ai"}:
            value = os.getenv(runninghub_wallet_key_env(provider_id), "")
            if value:
                return value
        value = provider_env_key_value(provider_id)
        if value:
            return value
    if protocol == "volcengine":
        return volcengine_provider_api_key("")
    return ""

def check_key_host_binding(provider_id: str, target_base_url: str, is_explicit_key: bool):
    """防止服务端保存的 API Key 被任意导出到攻击者控制的地址。

    认证边界：
      · 已配置 IC_ACCESS_TOKEN 时，main.access_token_middleware 已拦截所有未认证请求，
        能走到这里的必然是持有有效令牌的用户 —— 他有权把自己的 Key 改绑到新网关，
        因此直接放行（否则合法换主机操作会被误杀且无出路）。
      · 未配置访问令牌时服务对全网段开放，任何人都能调用本端点 —— 此时必须严格
        执行主机绑定，否则局域网攻击者可改写 base_url 把 Key 导出到自己的机器。
    """
    if is_explicit_key or not provider_id or not target_base_url:
        return
    try:
        from core.providers import read_api_env_value
        import os as _os
        if (_os.getenv("IC_ACCESS_TOKEN") or read_api_env_value("IC_ACCESS_TOKEN") or "").strip():
            return  # 已认证，放行
    except Exception:
        pass
    stored = next((p for p in load_api_providers() if p.get("id") == provider_id), None)
    if not stored:
        return
    stored_base = str(stored.get("base_url") or "").strip()
    if not stored_base:
        return
    stored_host = urlparse(stored_base).netloc.lower()
    target_host = urlparse(target_base_url).netloc.lower()
    if stored_host and target_host and stored_host != target_host:
        raise HTTPException(
            status_code=400,
            detail=f"安全拦截：已保存的 API Key 绑定在域名 ({stored_host})，如需改绑到 ({target_host}) 请同时重新填写该 API Key"
        )

def upstream_models_url(base_url: str, protocol: str):
    if protocol == "gemini":
        return f"{base_url}/models" if base_url.endswith("/v1beta") else f"{base_url}/v1beta/models"
    if protocol == "volcengine":
        return f"{base_url}/models" if base_url.endswith("/api/v3") else f"{base_url}/api/v3/models"
    if protocol == "runninghub":
        return runninghub_openapi_url({"base_url": base_url}, "models")
    if base_url.endswith("/openai") or base_url.endswith("/v1") or base_url.endswith("/v1beta"):
        return f"{base_url}/models"
    return f"{base_url}/v1/models"

def upstream_model_headers(api_key: str, protocol: str):
    if protocol == "gemini":
        return {"x-goog-api-key": api_key, "Authorization": bearer_auth_value(api_key), "Accept": "application/json"}
    if protocol == "runninghub":
        return {"Authorization": bearer_auth_value(api_key), "Accept": "application/json"}
    return {"Authorization": bearer_auth_value(api_key), "Accept": "application/json"}

def volcengine_default_model_payload(status=200, message="", raw=None):
    return {
        "ok": True,
        "protocol": "volcengine",
        "status": status,
        "message": message or "方舟任务接口可用，模型列表接口未返回模型。请按实际方舟控制台模型名称手动填写视频模型。",
        "model_count": 0,
        "image_models": [],
        "chat_models": [],
        "video_models": [],
        "all": [],
        "raw": raw,
    }

def volcengine_task_probe_url(base_url: str):
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/api/v3"):
        return f"{base}/contents/generations/tasks/healthcheck_probe_do_not_submit"
    return f"{base}/api/v3/contents/generations/tasks/healthcheck_probe_do_not_submit"

async def probe_volcengine_task_endpoint(client, base_url: str, api_key: str):
    probe_url = volcengine_task_probe_url(base_url)
    if not probe_url:
        return False, {"status": 0, "message": "Base URL 为空"}
    response = await client.get(probe_url, headers=upstream_model_headers(api_key, "volcengine"))
    try:
        raw = response.json() if response.text else {}
    except Exception:
        raw = response.text[:500]
    if response.status_code in (401, 403):
        return False, {"status": response.status_code, "message": "方舟 API Key 无效或无权限", "raw": raw}
    if looks_like_html_response(response.text):
        return False, {"status": response.status_code, "message": "任务接口返回 HTML，Base URL 可能不是 API 地址", "raw": raw}
    if response.status_code < 500:
        return True, {"status": response.status_code, "message": "方舟任务查询端点可达", "raw": raw}
    return False, {"status": response.status_code, "message": f"方舟任务接口服务端错误 {response.status_code}", "raw": raw}

def openai_compat_root_for_probe(base_url: str):
    base = str(base_url or "").strip().rstrip("/")
    if base.endswith("/api/v3"):
        base = base[: -len("/api/v3")]
    if base.endswith("/v1"):
        return base
    return f"{base}/v1" if base else ""

async def probe_openai_compat_bearer_endpoint(client, base_url: str, api_key: str):
    root = openai_compat_root_for_probe(base_url)
    if not root:
        return False, {"status": 0, "message": "Base URL 为空"}
    url = f"{root}/chat/completions"
    response = await client.post(
        url,
        headers={**upstream_model_headers(api_key, "openai"), "Content-Type": "application/json"},
        json={"messages": []},
    )
    try:
        raw = response.json() if response.text else {}
    except Exception:
        raw = response.text[:500]
    if response.status_code in (401, 403):
        return False, {"status": response.status_code, "message": "API Key 无效或无权限", "raw": raw}
    if looks_like_html_response(response.text):
        return False, {"status": response.status_code, "message": "OpenAI 兼容入口返回 HTML，Base URL 可能不是 API 地址", "raw": raw}
    if response.status_code < 500:
        return True, {"status": response.status_code, "message": "OpenAI 兼容 Bearer 鉴权入口可达", "raw": raw}
    return False, {"status": response.status_code, "message": f"OpenAI 兼容入口服务端错误 {response.status_code}", "raw": raw}

async def probe_openai_models_endpoint(client, base_url: str, api_key: str):
    url = upstream_models_url(base_url, "openai")
    response = await client.get(url, headers=upstream_model_headers(api_key, "openai"))
    try:
        raw = response.json() if response.text else {}
    except Exception:
        raw = response.text[:500]
    if response.status_code in (301, 302, 303, 307, 308):
        location = response.headers.get("Location") or response.headers.get("location") or ""
        suffix = f"：{location}" if location else ""
        return False, {"status": response.status_code, "message": f"OpenAI /v1/models 发生跳转{suffix}，请填写 API Base URL，不要填写网页登录地址", "raw": raw}
    if response.status_code in (401, 403):
        return False, {"status": response.status_code, "message": "OpenAI API Key 无效或无权限", "raw": raw}
    if looks_like_html_response(response.text):
        return False, {"status": response.status_code, "message": "OpenAI /v1/models 返回网页 HTML，请检查请求地址是否为 API Base URL", "raw": raw}
    if response.status_code < 300:
        grouped, ids = parse_upstream_models(raw, "openai") if isinstance(raw, dict) else ({"image": [], "chat": [], "video": []}, [])
        grouped, ids = apply_agnes_model_defaults(base_url, grouped, ids)
        grouped = apply_locked_recommended_model_rules(base_url, grouped)
        return True, {
            "status": response.status_code,
            "message": f"OpenAI 兼容模型列表端点可用{f'，找到 {len(ids)} 个模型' if ids else ''}",
            "raw": raw,
            "model_count": len(ids),
            "image_models": grouped["image"],
            "chat_models": grouped["chat"],
            "video_models": grouped["video"],
            "all": ids,
        }
    if 400 <= response.status_code < 500:
        return False, {"status": response.status_code, "message": f"OpenAI /v1/models 不可用 (HTTP {response.status_code})", "raw": raw}
    return False, {"status": response.status_code, "message": f"OpenAI /v1/models 服务端错误 {response.status_code}", "raw": raw}

async def probe_volcengine_auto_detect(client, base_url: str, api_key: str):
    task_ok, task_probe = await probe_volcengine_task_endpoint(client, base_url, api_key)
    if task_ok:
        return True, {
            "status": task_probe.get("status") or 200,
            "message": "检测到方舟/Ark 任务协议",
            "raw": {"task_probe": task_probe.get("raw")},
        }
    compat_ok, compat_probe = await probe_openai_compat_bearer_endpoint(client, base_url, api_key)
    if compat_ok:
        return True, {
            "status": compat_probe.get("status") or 200,
            "message": "检测到方舟/Ark Bearer 鉴权入口（OpenAI 兼容透传）",
            "raw": {"task_probe": task_probe, "openai_compat_probe": compat_probe.get("raw")},
        }
    return False, {
        "status": compat_probe.get("status") or task_probe.get("status") or 0,
        "message": compat_probe.get("message") or task_probe.get("message") or "未检测到方舟/Ark 兼容入口",
        "raw": {"task_probe": task_probe, "openai_compat_probe": compat_probe.get("raw")},
    }

def classify_upstream_model(mid):
    lc = str(mid or "").lower()
    video_keys = ["veo", "sora", "wan2", "wanx", "doubao-seedance", "doubao-1", "kling", "hailuo", "video", "t2v-", "i2v-", "s2v"]
    if any(k in lc for k in video_keys):
        return "video"
    image_keys = ["banana", "image", "dalle", "dall-e", "imagen", "flux", "stable", "sdxl", "midjourney", "nano-banana", "ideogram", "fal-ai", "z-image", "qwen-image", "klein", "seedream", "doubao-seedream", "text-to-image", "image-to-image"]
    if any(k in lc for k in image_keys):
        return "image"
    return "chat"

def parse_upstream_models(raw, protocol="openai"):
    items = raw.get("data") if isinstance(raw, dict) else None
    if not items and isinstance(raw, dict):
        items = raw.get("models") or raw.get("list") or []
    if not isinstance(items, list):
        items = []
    ids = []
    for it in items:
        if isinstance(it, str):
            mid = it
        elif isinstance(it, dict):
            mid = it.get("id") or it.get("name") or it.get("model")
        else:
            mid = ""
        if mid:
            mid = str(mid)
            if protocol == "gemini" and mid.startswith("models/"):
                mid = mid[len("models/"):]
            ids.append(mid)
    ids = sorted(set(ids))
    grouped = {"image": [], "chat": [], "video": []}
    for mid in ids:
        grouped[classify_upstream_model(mid)].append(mid)
    return grouped, ids

def apply_dashscope_model_defaults(provider, grouped, ids):
    if not is_dashscope_provider(provider):
        return grouped, ids
    grouped = {key: list(value or []) for key, value in (grouped or {}).items()}
    ids = list(ids or [])
    for model in DASHSCOPE_DEFAULT_VIDEO_MODELS:
        if model not in ids:
            ids.append(model)
        if model not in grouped.setdefault("video", []):
            grouped["video"].append(model)
    ids = sorted(set(ids))
    grouped["video"] = sorted(set(grouped.get("video") or []))
    return grouped, ids

def apply_agnes_model_defaults(base_url, grouped, ids):
    if "apihub.agnes-ai.com" not in str(base_url or "").strip().lower():
        return grouped, ids
    grouped = {key: list(value or []) for key, value in (grouped or {}).items()}
    ids = list(ids or [])
    for model in AGNES_DEFAULT_VIDEO_MODELS:
        if model not in ids:
            ids.append(model)
        if model not in grouped.setdefault("video", []):
            grouped["video"].append(model)
    ids = sorted(set(ids))
    grouped["video"] = sorted(set(grouped.get("video") or []))
    return grouped, ids

async def fetch_pollinations_models_with_key(api_key: str):
    """当用户提供了 Pollinations API Key 时，通过 https://gen.pollinations.ai/v1/models 获取完整模型清单（250+模型）。"""
    url = "https://gen.pollinations.ai/v1/models"
    headers = {"Authorization": bearer_auth_value(api_key), "User-Agent": "Infinite-Canvas/1.0"}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                models_data = data.get("data", [])
                images, chats, videos = [], [], []
                for m in models_data:
                    mid = m.get("id", "")
                    if not mid:
                        continue
                    out_mods = m.get("output_modalities") or []
                    if "image" in out_mods:
                        images.append(mid)
                    elif "video" in out_mods:
                        videos.append(mid)
                    elif "text" in out_mods:
                        chats.append(mid)
                    else:
                        chats.append(mid)
                all_models = [m.get("id") for m in models_data if m.get("id")]
                return {
                    "total": len(all_models),
                    "image_models": images,
                    "chat_models": chats,
                    "video_models": videos,
                    "all": all_models,
                    "message": f"Pollinations 授权成功，获取到 {len(all_models)} 个模型（生图 {len(images)} 个，对话 {len(chats)} 个）",
                }
    except Exception as e:
        logger.warning("Failed to fetch pollinations models with key: %s", e)
    return None

# --- /api/providers/test-connection 已解耦迁移至 routers/providers.py ---
@router.post("/api/providers/test-connection")
async def test_provider_connection(payload: TestConnectionPayload):
    """测试请求地址是否可用：调上游 /v1/models。验证通过时同时把模型清单按类别返回，避免再调一次拉取接口。"""
    protocol = protocol_from_payload(payload)
    if protocol == "pollinations" or getattr(payload, "id", "") == "pollinations-api" or "gen.pollinations.ai" in (payload.base_url or "").lower():
        api_key = api_key_from_payload(payload, protocol)
        if api_key and "…" not in api_key and "????????" not in api_key:
            res = await fetch_pollinations_models_with_key(api_key)
            if res:
                return {
                    "ok": True,
                    "status": 200,
                    "message": f"Pollinations 授权验证成功 · 找到 {res['total']} 个模型（生图 {len(res['image_models'])} 个，对话 {len(res['chat_models'])} 个）",
                    "model_count": res["total"],
                    "image_models": res["image_models"],
                    "chat_models": res["chat_models"],
                    "video_models": res["video_models"],
                    "all": res["all"],
                    "protocol": "openai" if getattr(payload, "id", "") == "pollinations-api" or "gen.pollinations.ai" in (payload.base_url or "").lower() else "pollinations",
                }
        if getattr(payload, "id", "") == "pollinations-api" or "gen.pollinations.ai" in (payload.base_url or "").lower():
            raise HTTPException(status_code=400, detail="请填写从 enter.pollinations.ai 获取的 API Key (sk_...)")
        return {
            "ok": True,
            "status": 200,
            "message": "Pollinations AI 接口可用（免 API Key 直接生图）",
            "model_count": len(POLLINATIONS_DEFAULT_IMAGE_MODELS),
            "image_models": POLLINATIONS_DEFAULT_IMAGE_MODELS,
            "chat_models": [],
            "video_models": [],
            "all": POLLINATIONS_DEFAULT_IMAGE_MODELS,
            "protocol": "pollinations",
        }
    if protocol == "codex":
        from routers.integrations import codex_status, codex_models_payload
        status = await codex_status()
        payload_models = codex_models_payload(raw={"status": status})
        payload_models.update({
            "ok": bool(status.get("installed")),
            "status": 200 if status.get("installed") else 0,
            "message": status.get("message") or ("OpenAI Codex CLI 可用" if status.get("installed") else "未找到 OpenAI Codex CLI"),
        })
        return payload_models
    if protocol == "gemini-cli":
        from routers.integrations import gemini_cli_status, gemini_cli_models_payload
        status = await gemini_cli_status()
        payload_models = gemini_cli_models_payload(raw={"status": status})
        payload_models.update({
            "ok": bool(status.get("installed")),
            "status": 200 if status.get("installed") else 0,
            "message": status.get("message") or ("Antigravity CLI 可用" if status.get("installed") else "未找到 Antigravity CLI"),
        })
        return payload_models
    if protocol == "jimeng":
        from routers.integrations import jimeng_status
        status = await jimeng_status()
        return {
            "ok": bool(status.get("installed") and status.get("logged_in")),
            "status": 200 if status.get("logged_in") else 0,
            "message": status.get("message") or "即梦 CLI 已登录",
            "model_count": len(JIMENG_DEFAULT_IMAGE_MODELS) + len(JIMENG_DEFAULT_VIDEO_MODELS),
            "image_models": JIMENG_DEFAULT_IMAGE_MODELS,
            "chat_models": [],
            "video_models": JIMENG_DEFAULT_VIDEO_MODELS,
            "all": [*JIMENG_DEFAULT_IMAGE_MODELS, *JIMENG_DEFAULT_VIDEO_MODELS],
            "raw": status.get("raw"),
        }
    if protocol == "runninghub":
        from routers.integrations import runninghub_models_payload
        pid = getattr(payload, "provider_id", "") or "runninghub"
        is_ai = pid in {"runninghub-ai", "runninghub-global"} or "runninghub.ai" in (payload.base_url or "").lower()
        active_id = "runninghub-ai" if is_ai else "runninghub"
        name = "RunningHub (国际站)" if is_ai else "RunningHub (国内站)"
        default_base = RUNNINGHUB_AI_BASE_URL if is_ai else RUNNINGHUB_CN_BASE_URL
        base_url = (payload.base_url or default_base).strip().rstrip("/")
        if not re.match(r"^https?://", base_url):
            raise HTTPException(status_code=400, detail="请求地址必须以 http:// 或 https:// 开头")
        explicit_key = bool(str(getattr(payload, "api_key", "") or "").strip())
        check_key_host_binding(pid, base_url, explicit_key)
        try:
            validate_safe_url(base_url, allow_private=False)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"请求地址非法或受限: {e}")
        provider = {"id": active_id, "name": name, "base_url": base_url, "protocol": "runninghub", "api_key": api_key_from_payload(payload, protocol)}
        payload_models = await runninghub_models_payload(provider)
        return {
            "ok": True,
            "status": 200,
            "message": f"{name} OpenAPI 可用，已拉取官方直连模型注册表。",
            "model_count": payload_models["total"],
            "image_models": payload_models["image_models"],
            "chat_models": payload_models["chat_models"],
            "video_models": payload_models["video_models"],
            "all": payload_models["all"],
            "protocol": "runninghub",
            "raw": payload_models.get("raw"),
        }
    base_url = (payload.base_url or "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="请先填写请求地址")
    if not re.match(r"^https?://", base_url):
        raise HTTPException(status_code=400, detail="请求地址必须以 http:// 或 https:// 开头")
    explicit_key = bool(str(getattr(payload, "api_key", "") or "").strip())
    check_key_host_binding(payload.provider_id, base_url, explicit_key)
    try:
        validate_safe_url(base_url, allow_private=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"请求地址非法或受限: {e}")
    api_key = api_key_from_payload(payload, protocol)
    if not api_key:
        key_name = "方舟 API Key" if protocol == "volcengine" else "API Key"
        raise HTTPException(status_code=400, detail=f"请先填写或保存 {key_name}")
    url = upstream_models_url(base_url, protocol)
    try:
        async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=15) as client:
            resp = await client.get(url, headers=upstream_model_headers(api_key, protocol))
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location") or resp.headers.get("location") or ""
                suffix = f"：{location}" if location else ""
                endpoint_label = "/v1beta/models" if protocol == "gemini" else "/api/v3/models" if protocol == "volcengine" else "/openapi/v2/models" if protocol == "runninghub" else "/v1/models"
                return {"ok": False, "status": resp.status_code, "message": f"上游 {endpoint_label} 发生跳转{suffix}，请填写 API Base URL，不要填写网页登录地址"}
            if looks_like_html_response(resp.text):
                endpoint_label = "/v1beta/models" if protocol == "gemini" else "/api/v3/models" if protocol == "volcengine" else "/openapi/v2/models" if protocol == "runninghub" else "/v1/models"
                return {"ok": False, "status": resp.status_code, "message": f"上游 {endpoint_label} 返回网页 HTML，请检查请求地址是否为 API Base URL"}
            if resp.status_code >= 400:
                if protocol == "volcengine":
                    detected, probe = await probe_volcengine_auto_detect(client, base_url, api_key)
                    if detected:
                        message = f"{probe.get('message') or '方舟任务接口可达'}；但 /api/v3/models 不可用。请按实际方舟控制台模型名称手动填写视频模型。"
                        return volcengine_default_model_payload(status=probe.get("status") or resp.status_code, message=message, raw={"models_error": resp.text[:300], **(probe.get("raw") or {})})
                elif protocol == "openai":
                    detected, probe = await probe_volcengine_auto_detect(client, base_url, api_key)
                    if detected:
                        message = f"{probe.get('message') or '检测到方舟/Ark 兼容入口'}；OpenAI /v1/models 不可用，已自动切换为方舟协议。请按实际方舟控制台模型名称手动填写视频模型。"
                        return volcengine_default_model_payload(status=probe.get("status") or resp.status_code, message=message, raw={"models_error": resp.text[:300], **(probe.get("raw") or {})})
                return {"ok": False, "status": resp.status_code, "message": resp.text[:300]}
            data = resp.json() if resp.text else {}
            grouped, ids = parse_upstream_models(data, protocol)
            grouped, ids = apply_agnes_model_defaults(base_url, grouped, ids)
            grouped = apply_locked_recommended_model_rules(base_url, grouped)
            if protocol == "volcengine" and not ids:
                detected, probe = await probe_volcengine_auto_detect(client, base_url, api_key)
                if detected:
                    return volcengine_default_model_payload(status=resp.status_code, raw=data)
            return {
                "ok": True,
                "status": resp.status_code,
                "model_count": len(ids),
                "image_models": grouped["image"],
                "chat_models": grouped["chat"],
                "video_models": grouped["video"],
                "all": ids,
                "image_request_mode": detect_image_request_mode(base_url, ids) or normalize_image_request_mode(getattr(payload, "image_request_mode", "")),
            }
    except httpx.HTTPError as e:
        if protocol == "volcengine":
            try:
                async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=15) as client:
                    detected, probe = await probe_volcengine_auto_detect(client, base_url, api_key)
                    if detected:
                        message = f"{probe.get('message') or '方舟任务接口可达'}；但模型列表请求失败。请按实际方舟控制台模型名称手动填写视频模型。"
                        return volcengine_default_model_payload(status=probe.get("status") or 0, message=message, raw={"models_error": str(e)[:300], **(probe.get("raw") or {})})
            except Exception:
                pass
        return {"ok": False, "status": 0, "message": str(e)[:300]}

# --- /api/providers/probe-async 已解耦迁移至 routers/providers.py ---
@router.post("/api/providers/probe-async")
async def probe_async_endpoint(payload: TestConnectionPayload):
    """验证异步协议：用假 task_id 请求 GET /v1/tasks/{fake_id}。
    收到 400 Invalid task ID = 端点存在且 Key 有效；401/403 = Key 无效；404/连接失败 = 不支持异步端点。"""
    base_url = (payload.base_url or "").strip().rstrip("/")
    protocol = protocol_from_payload(payload)
    if protocol == "codex":
        from routers.integrations import codex_status
        status = await codex_status()
        return {
            "ok": bool(status.get("installed")),
            "protocol": "codex",
            "status_code": 200 if status.get("installed") else 0,
            "message": status.get("message") or "OpenAI Codex CLI 本机检测完成",
            "raw": status,
        }
    if protocol == "gemini-cli":
        from routers.integrations import gemini_cli_status
        status = await gemini_cli_status()
        return {
            "ok": bool(status.get("installed")),
            "protocol": "gemini-cli",
            "status_code": 200 if status.get("installed") else 0,
            "message": status.get("message") or "Antigravity CLI 本机检测完成",
            "raw": status,
        }
    if protocol == "pollinations":
        models = ["flux", "sana", "zimage", "nanobanana-2-lite", "qwen-image-3", "seedream5-pro"]
        return {
            "ok": True,
            "protocol": "pollinations",
            "status_code": 200,
            "message": "Pollinations AI 协议无需鉴权，服务可用",
            "models": models,
            "model_count": len(models),
            "image_models": models,
            "chat_models": [],
            "video_models": [],
            "all": models,
            "raw": {"status": "ok"},
        }
    if not base_url:
        raise HTTPException(status_code=400, detail="请先填写请求地址")
    try:
        validate_safe_url(base_url, allow_private=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"请求地址非法或受限: {e}")
    explicit_key = bool(str(getattr(payload, "api_key", "") or "").strip())
    check_key_host_binding(payload.provider_id, base_url, explicit_key)
    api_key = api_key_from_payload(payload, protocol)
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写或保存 API Key")
    is_tudou_async = is_tudou_base_url(base_url)
    if protocol == "volcengine":
        try:
            async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=15) as client:
                task_ok, task_probe = await probe_volcengine_task_endpoint(client, base_url, api_key)
                if task_ok:
                    return {
                        "ok": True,
                        "protocol": "volcengine",
                        "status_code": task_probe.get("status") or 200,
                        "message": "方舟/Ark 任务协议可用",
                        "raw": task_probe.get("raw"),
                    }
                compat_ok, compat_probe = await probe_openai_compat_bearer_endpoint(client, base_url, api_key)
                if compat_ok:
                    return {
                        "ok": True,
                        "protocol": "volcengine",
                        "status_code": compat_probe.get("status") or 200,
                        "message": "方舟/Ark Bearer 鉴权入口可用（OpenAI 兼容透传）",
                        "raw": {"task_probe": task_probe, "openai_compat_probe": compat_probe.get("raw")},
                    }
                return {
                    "ok": False,
                    "protocol": "volcengine",
                    "status_code": compat_probe.get("status") or task_probe.get("status") or 0,
                    "message": compat_probe.get("message") or task_probe.get("message") or "方舟/Ark 任务协议不可用",
                    "raw": {"task_probe": task_probe, "openai_compat_probe": compat_probe.get("raw")},
                }
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=str(e)[:300])
    tasks_base = base_url if base_url.endswith("/v1") else f"{base_url}/v1"
    probe_url = f"{tasks_base}/tasks/healthcheck_probe_do_not_submit"
    try:
        async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=15) as client:
            resp = await client.get(probe_url, headers={"Authorization": bearer_auth_value(api_key), "Accept": "application/json"})
            try:
                body = resp.json()
            except Exception:
                body = resp.text[:500]
            sc = resp.status_code
            # 判断结果
            err_msg = ""
            if isinstance(body, dict):
                err = body.get("error") or {}
                if isinstance(err, dict):
                    err_msg = str(err.get("message") or "").lower()
                else:
                    err_msg = str(err).lower()
            # 400 + "invalid task id" → 端点存在，Key 有效
            if is_tudou_async and sc == 400:
                # 土豆对不存在的 task_id 可能使用不同的 400 错误字段；只要不是
                # 401/403，400 已证明请求命中了异步任务端点且认证通过。
                return {
                    "ok": True,
                    "protocol": "openai",
                    "image_request_mode": "tudou-async",
                    "status_code": sc,
                    "message": "土豆 GPT-Image-2 异步任务端点可用，API Key 已通过认证",
                    "raw": body,
                }
            if sc == 400 and "invalid task id" in err_msg:
                return {"ok": True, "protocol": "apimart", "status_code": sc, "message": "APIMart 异步任务端点可用，API Key 已通过认证", "raw": body}

            async_probe = {"status": sc, "message": "", "raw": body}
            if sc in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location") or resp.headers.get("location") or ""
                async_probe["message"] = f"/v1/tasks/ 发生跳转{f'：{location}' if location else ''}"
            elif looks_like_html_response(resp.text):
                async_probe["message"] = "/v1/tasks/ 返回网页 HTML"
            elif sc in (401, 403):
                async_probe["message"] = "/v1/tasks/ 返回鉴权失败"
            elif sc == 404:
                async_probe["message"] = "平台不支持 /v1/tasks/ 端点，可能不是 APIMart 异步协议"
            elif 400 <= sc < 500:
                async_probe["message"] = f"/v1/tasks/ 返回 {sc}"
            elif sc < 300:
                async_probe["message"] = f"/v1/tasks/ 返回 {sc}（意外成功）"
            else:
                async_probe["message"] = f"/v1/tasks/ 服务端错误 {sc}"

            if is_tudou_async:
                return {
                    "ok": sc < 400,
                    "protocol": "openai",
                    "image_request_mode": "tudou-async" if sc < 400 else "openai",
                    "status_code": sc,
                    "message": async_probe["message"] or "土豆 GPT-Image-2 异步任务端点验证完成",
                    "raw": body,
                }

            if protocol == "apimart":
                return {"ok": False, "protocol": "apimart", "status_code": sc, "message": async_probe["message"], "raw": body}

            openai_ok, openai_probe = await probe_openai_models_endpoint(client, base_url, api_key)
            if not openai_ok and protocol == "openai":
                # /v1/models 不可用，先确认是不是“没实现 models 接口的 OpenAI 兼容站”：探一下 /v1/chat/completions。
                # 可达就判定为 OpenAI 兼容（很多网关不暴露 /v1/models），避免被下面的方舟探测（404 也算可达）误判成方舟。
                compat_ok, compat_probe = await probe_openai_compat_bearer_endpoint(client, base_url, api_key)
                # 仅当 /v1/chat/completions 确实存在（返回 2xx 或我们发空 messages 触发的 400 等，而非 404 路径不存在）
                # 才判为 OpenAI 兼容；404 说明该路径不存在，留给后面的方舟探测。
                if compat_ok and (compat_probe.get("status") or 0) != 404:
                    return {
                        "ok": True,
                        "protocol": "openai",
                        "status_code": compat_probe.get("status") or openai_probe.get("status") or sc,
                        "message": "OpenAI 兼容入口可达（该站未提供 /v1/models，模型请手动填写）",
                        "raw": {"async_probe": async_probe, "openai_probe": openai_probe.get("raw"), "openai_compat_probe": compat_probe.get("raw")},
                        "model_count": 0,
                        "image_models": [],
                        "chat_models": [],
                        "video_models": [],
                        "all": [],
                    }
                detected, volc_probe = await probe_volcengine_auto_detect(client, base_url, api_key)
                if detected:
                    return {
                        "ok": True,
                        "protocol": "volcengine",
                        "status_code": volc_probe.get("status") or openai_probe.get("status") or sc,
                        "message": f"{volc_probe.get('message') or '检测到方舟/Ark 兼容入口'}，已自动切换为方舟/Ark 任务协议",
                        "raw": {"async_probe": async_probe, "openai_probe": openai_probe.get("raw"), **(volc_probe.get("raw") or {})},
                    }
            return {
                "ok": openai_ok,
                "protocol": "openai",
                "status_code": openai_probe.get("status") or sc,
                "message": openai_probe.get("message") or "OpenAI 兼容验证完成",
                "raw": {"async_probe": async_probe, "openai_probe": openai_probe.get("raw")},
                "model_count": openai_probe.get("model_count") or 0,
                "image_models": openai_probe.get("image_models") or [],
                "chat_models": openai_probe.get("chat_models") or [],
                "video_models": openai_probe.get("video_models") or [],
                "all": openai_probe.get("all") or [],
                "image_request_mode": detect_image_request_mode(base_url, openai_probe.get("all") or []) or normalize_image_request_mode(getattr(payload, "image_request_mode", "")),
            }
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e)[:300])

async def fetch_models_from_upstream(base_url: str, api_key: str, protocol: str = "openai", image_request_mode: str = "openai"):
    """从上游模型列表端点拉取模型，并按名称做轻量分类。"""
    protocol = protocol if protocol in SUPPORTED_PROVIDER_PROTOCOLS else "openai"
    if protocol == "codex":
        from routers.integrations import codex_status, codex_models_payload
        status = await codex_status()
        payload = codex_models_payload(raw={"status": status})
        payload["message"] = status.get("message") or payload["message"]
        return payload
    if protocol == "gemini-cli":
        from routers.integrations import gemini_cli_status, gemini_cli_models_payload
        status = await gemini_cli_status()
        payload = gemini_cli_models_payload(raw={"status": status})
        payload["message"] = status.get("message") or payload["message"]
        return payload
    if protocol == "jimeng":
        return {
            "total": len(JIMENG_DEFAULT_IMAGE_MODELS) + len(JIMENG_DEFAULT_VIDEO_MODELS),
            "image_models": JIMENG_DEFAULT_IMAGE_MODELS,
            "chat_models": [],
            "video_models": JIMENG_DEFAULT_VIDEO_MODELS,
            "all": [*JIMENG_DEFAULT_IMAGE_MODELS, *JIMENG_DEFAULT_VIDEO_MODELS],
        }
    if protocol == "runninghub":
        from routers.integrations import runninghub_models_payload
        is_ai = "runninghub.ai" in (base_url or "").lower()
        default_base = RUNNINGHUB_AI_BASE_URL if is_ai else RUNNINGHUB_CN_BASE_URL
        pid = "runninghub-ai" if is_ai else "runninghub"
        name = "RunningHub (国际站)" if is_ai else "RunningHub (国内站)"
        provider = {"id": pid, "name": name, "base_url": base_url or default_base, "protocol": "runninghub", "api_key": api_key}
        return await runninghub_models_payload(provider)
    if protocol == "pollinations" or "gen.pollinations.ai" in (base_url or "").lower():
        if api_key and "…" not in api_key and "????????" not in api_key:
            res = await fetch_pollinations_models_with_key(api_key)
            if res:
                return res
        if "gen.pollinations.ai" in (base_url or "").lower():
            raise HTTPException(status_code=400, detail="请先填写并保存从 enter.pollinations.ai 获取的 API Key (sk_...)")
        models = ["flux", "sana", "zimage", "nanobanana-2-lite", "qwen-image-3", "seedream5-pro"]
        return {
            "total": len(models),
            "image_models": models,
            "chat_models": [],
            "video_models": [],
            "all": models,
            "message": "Pollinations 生图模型获取成功",
        }
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="请先填写请求地址")
    if not re.match(r"^https?://", base_url):
        raise HTTPException(status_code=400, detail="请求地址必须以 http:// 或 https:// 开头")
    try:
        validate_safe_url(base_url, allow_private=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"请求地址非法或受限: {e}")
    api_key = volcengine_provider_api_key(api_key) if protocol == "volcengine" else (api_key or "").strip()
    if not api_key:
        key_name = "方舟 API Key" if protocol == "volcengine" else "API Key"
        raise HTTPException(status_code=400, detail=f"请先填写或保存 {key_name}")
    url = upstream_models_url(base_url, protocol)
    try:
        async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=30) as client:
            resp = await client.get(url, headers=upstream_model_headers(api_key, protocol))
            endpoint_label = "/v1beta/models" if protocol == "gemini" else "/api/v3/models" if protocol == "volcengine" else "/openapi/v2/models" if protocol == "runninghub" else "/v1/models"
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location") or resp.headers.get("location") or ""
                suffix = f"：{location}" if location else ""
                raise HTTPException(status_code=400, detail=f"上游 {endpoint_label} 发生跳转{suffix}，请填写 API Base URL，不要填写网页登录地址")
            if looks_like_html_response(resp.text):
                raise HTTPException(status_code=400, detail=f"上游 {endpoint_label} 返回网页 HTML，请检查请求地址是否为 API Base URL")
            if resp.status_code >= 400:
                if protocol == "volcengine":
                    detected, probe = await probe_volcengine_auto_detect(client, base_url, api_key)
                    if detected:
                        payload = volcengine_default_model_payload(
                            status=probe.get("status") or resp.status_code,
                            message=f"{probe.get('message') or '方舟任务接口可达'}；但 /api/v3/models 不可用。请按实际方舟控制台模型名称手动填写视频模型。",
                            raw={"models_error": resp.text[:300], **(probe.get("raw") or {})},
                        )
                        return {
                            "total": payload["model_count"],
                            "protocol": payload["protocol"],
                            "image_models": payload["image_models"],
                            "chat_models": payload["chat_models"],
                            "video_models": payload["video_models"],
                            "all": payload["all"],
                            "message": payload["message"],
                            "raw": payload["raw"],
                        }
                elif protocol == "openai":
                    detected, probe = await probe_volcengine_auto_detect(client, base_url, api_key)
                    if detected:
                        payload = volcengine_default_model_payload(
                            status=probe.get("status") or resp.status_code,
                            message=f"{probe.get('message') or '检测到方舟/Ark 兼容入口'}；OpenAI /v1/models 不可用，已自动切换为方舟协议。请按实际方舟控制台模型名称手动填写视频模型。",
                            raw={"models_error": resp.text[:300], **(probe.get("raw") or {})},
                        )
                        return {
                            "total": payload["model_count"],
                            "protocol": payload["protocol"],
                            "image_models": payload["image_models"],
                            "chat_models": payload["chat_models"],
                            "video_models": payload["video_models"],
                            "all": payload["all"],
                            "message": payload["message"],
                            "raw": payload["raw"],
                        }
                raise HTTPException(status_code=resp.status_code, detail=f"上游 {endpoint_label} 失败：{resp.text[:300]}")
            raw = resp.json()
    except httpx.HTTPError as e:
        if protocol == "volcengine":
            try:
                async with httpx.AsyncClient(event_hooks={"response": [_upstream_response_hook], "request": [_upstream_request_hook]}, timeout=15) as client:
                    detected, probe = await probe_volcengine_auto_detect(client, base_url, api_key)
                    if detected:
                        payload = volcengine_default_model_payload(
                            status=probe.get("status") or 0,
                            message=f"{probe.get('message') or '方舟任务接口可达'}；但模型列表请求失败。请按实际方舟控制台模型名称手动填写视频模型。",
                            raw={"models_error": str(e)[:300], **(probe.get("raw") or {})},
                        )
                        return {
                            "total": payload["model_count"],
                            "protocol": payload["protocol"],
                            "image_models": payload["image_models"],
                            "chat_models": payload["chat_models"],
                            "video_models": payload["video_models"],
                            "all": payload["all"],
                            "message": payload["message"],
                            "raw": payload["raw"],
                        }
            except Exception:
                pass
        raise HTTPException(status_code=502, detail=f"请求上游模型列表失败：{e}")
    grouped, ids = parse_upstream_models(raw, protocol)
    grouped, ids = apply_agnes_model_defaults(base_url, grouped, ids)
    grouped = apply_locked_recommended_model_rules(base_url, grouped)
    if protocol == "volcengine" and not ids:
        payload = volcengine_default_model_payload(raw=raw)
        return {
            "total": payload["model_count"],
            "image_models": payload["image_models"],
            "chat_models": payload["chat_models"],
            "video_models": payload["video_models"],
            "all": payload["all"],
            "message": payload["message"],
            "raw": payload["raw"],
        }
    return {
        "total": len(ids),
        "image_models": grouped["image"],
        "chat_models": grouped["chat"],
        "video_models": grouped["video"],
        "all": ids,
        "image_request_mode": detect_image_request_mode(base_url, ids) or normalize_image_request_mode(image_request_mode),
    }

# --- /api/providers/fetch-models, /api/providers/{provider_id}/fetch-models 已解耦迁移至 routers/providers.py ---
@router.post("/api/providers/fetch-models")
async def fetch_upstream_models_from_payload(payload: TestConnectionPayload):
    """按页面当前表单值拉取模型，支持新增平台未保存时直接使用临时 Base URL / Key。"""
    protocol = protocol_from_payload(payload)
    explicit_key = bool(str(getattr(payload, "api_key", "") or "").strip())
    check_key_host_binding(payload.provider_id, payload.base_url, explicit_key)
    api_key = api_key_from_payload(payload, protocol)
    return await fetch_models_from_upstream(payload.base_url, api_key, protocol, payload.image_request_mode)

@router.get("/api/providers/{provider_id}/fetch-models")
async def fetch_upstream_models(provider_id: str):
    """从已保存的上游 OpenAI 兼容接口拉取 /v1/models 列表，按名称智能分类为 image/chat/video。"""
    provider = get_api_provider_exact(provider_id)
    if is_codex_provider(provider):
        return await fetch_models_from_upstream("", "", "codex", provider.get("image_request_mode") or "openai")
    if is_gemini_cli_provider(provider):
        return await fetch_models_from_upstream("", "", "gemini-cli", provider.get("image_request_mode") or "openai")
    if is_pollinations_provider(provider) or provider_protocol(provider) == "pollinations":
        api_key = provider_env_key_value(provider["id"])
        return await fetch_models_from_upstream(provider.get("base_url") or "", api_key, provider_protocol(provider), provider.get("image_request_mode") or "pollinations")
    api_key = os.getenv(runninghub_wallet_key_env(provider["id"]), "") if provider["id"] in {"runninghub", "runninghub-ai"} else ""
    if not api_key:
        api_key = provider_env_key_value(provider["id"])
    if not api_key:
        raise HTTPException(status_code=400, detail=f"{provider.get('name') or provider_id} 未配置 API Key")
    return await fetch_models_from_upstream(provider.get("base_url") or "", api_key, provider_protocol(provider), provider.get("image_request_mode") or "openai")


# Legacy handler configuration hook for backward compatibility
def configure_providers_handlers(**kwargs):
    pass
