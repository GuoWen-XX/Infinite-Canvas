"""开卷画布 · MeansCanvas (原 Infinite-Canvas) Main Application Entry Point.

Refactored using the Strangler Fig pattern to decouple monolithic functionality
into modular, testable, and maintainable domain routers and core utilities:
- core/providers.py: Provider catalog, credentials, RunningHub workflow store, secret masking
- core/canvas_cache.py: High performance mtime-indexed canvas cache
- core/history_manager.py: Thread-safe ring buffer history manager
- core/security.py: SSRF protection and security validation
- core/ws_manager.py: Safe connection manager with DoS protection
- routers/canvas.py: Canvas CRUD, projects, trash, serialization
- routers/assets.py: Asset library, storage, uploads, media preview
- routers/tasks.py: Task history, cost estimation, generation history CRUD, WebSocket gateway
- routers/prompts.py: Prompt library management
- routers/system.py: System info, connectivity probe, updater & rollback
- routers/comfyui.py: ComfyUI execution, workflows, instance load balancing
- routers/providers.py: AI provider endpoints, upstream models, testing
- routers/online_image.py: Cloud AI image generation & task dispatch
- routers/chat.py: Multimodal LLM streaming conversation
- routers/video.py: Cloud video generation & canvas export
- routers/integrations.py: Skill CLI, RunningHub, MeiGen external tool bridges
"""

import os
import sys
import re
import json
import time
import uuid
import asyncio
import logging
import logging.handlers
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# --- Current dir on sys.path ---
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

# --- Core Modules ---
from core.pydantic_compat import dump_pydantic
from core.security import is_safe_remote_url, is_valid_comfy_address
from core.history_manager import HistoryManager
from core.ws_manager import SafeConnectionManager
from core.providers import (
    ASSETS_DIR,
    ASSET_LIBRARY_DIR,
    BASE_DIR,
    COMFYUI_INSTANCES,
    FIELD_LABELS,
    HISTORY_FILE,
    LOCAL_UPLOAD_DIR,
    OUTPUT_DIR,
    OUTPUT_INPUT_DIR,
    OUTPUT_OUTPUT_DIR,
    STATIC_DIR,
    STATIC_RUNNINGHUB_DIR,
    STATIC_RUNNINGHUB_THUMBNAIL_DIR,
    friendly_validation_error,
    update_env_values,
    read_api_env_value,
    get_configured_access_token,
)

# --- Domain Routers & Re-exports ---
from routers.canvas import (
    router as canvas_router,
    canvas_cache,
    save_canvas,
    load_canvas,
    load_canvas_any,
    new_canvas,
    canvas_path,
    canvas_record,
    cleanup_expired_canvas_trash,
    iter_canvas_records,
    list_canvases,
    list_deleted_canvases,
    ensure_default_project,
    load_projects,
    save_projects,
    project_record,
    new_project,
    list_projects,
    CANVAS_DIR,
    CANVAS_LOCK,
    CANVAS_TRASH_RETENTION_MS,
    PROJECTS_PATH,
    DEFAULT_PROJECT_ID,
    CANVAS_COLORS,
    normalize_canvas_kind,
    normalize_canvas_color,
    CanvasCreateRequest,
    CanvasMetaUpdate,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    CanvasSaveRequest,
    set_ws_manager as set_canvas_ws_manager,
)

from routers.assets import (
    router as assets_router,
    set_ws_manager as set_assets_ws_manager,
    set_image_captioner,
    set_image_classifier,
    set_avatar_handlers,
    set_runninghub_url_rewriter,
    DEFAULT_STORAGE_DIRS,
    STORAGE_SETTINGS_FILE,
    SHARED_FOLDERS_FILE,
    ASSET_LIBRARY_PATH,
    ASSET_LIBRARY_DIR,
    LOCAL_UPLOAD_DIR,
    MEDIA_PREVIEW_DIR,
    STORAGE_IMAGE_EXTS,
    SHARED_MEDIA_EXTS,
    ASSET_CLASSIFICATION_PROMPT,
    ASSET_CLASSIFICATION_PROMPT_FILE,
    ASSET_CLASSIFICATION_DIMENSION_NAMES,
    AVATAR_SUPPORTED_PLATFORMS,
    AVATAR_LEGACY_FLAT_FIELDS,
    load_storage_settings,
    save_storage_settings,
    apply_storage_settings,
    storage_kind_dir,
    storage_file_path,
    storage_file_item,
    output_storage,
    output_url_for,
    output_path_for,
    output_file_from_url,
    local_media_file_by_basename,
    filename_from_media_url,
    fetch_remote_media_bytes,
    media_preview_cache_paths,
    is_video_preview_file,
    generate_video_preview_image,
    image_has_alpha,
    default_asset_library,
    normalize_asset_library,
    sort_asset_library_items,
    migrate_asset_item_registrations,
    load_asset_library,
    save_asset_library,
    find_asset_library,
    find_asset_category,
    find_asset_category_in_library,
    find_asset_category_with_library,
    find_asset_item_in_library,
    asset_library_media_kind,
    asset_library_safe_extension,
    unique_asset_category_dir,
    remove_asset_library_file,
    make_asset_library_item,
    asset_library_workflow_category,
    make_workflow_library_item_from_bytes,
    load_asset_classification_prompt,
    save_asset_classification_prompt,
    normalize_asset_classification,
    parse_asset_classification_text,
    asset_classification_prompt,
    classify_asset_image_best_effort,
    migrate_asset_library_into_dirs,
    migrate_double_extension_uploads,
    shared_folders_load,
    shared_folders_save,
    shared_folder_by_id,
    shared_folder_abs,
    shared_resolve_register,
    shared_child_abs,
    scan_shared_tree,
    _local_upload_kind_ext,
    _local_upload_display_name,
    _local_upload_rel_path,
    _local_upload_abs,
    _local_upload_safe_path,
    AssetAvatarRegisterRequest,
)

from routers.prompts import (
    router as prompts_router,
    PROMPT_LIBRARY_PATH,
    STATIC_PROMPT_TEMPLATE_MD,
    PROMPT_TEMPLATE_PATHS,
    PROMPT_TEMPLATE_EN,
    PROMPT_LOCK,
    PROMPT_BUILTIN_CATEGORY_IDS,
    PromptLibraryRequest,
    PromptLibraryItemRequest,
    PromptLibraryBatchDeleteRequest,
    PromptLibraryCategoryRequest,
    prompt_template_markdown_path,
    prompt_template_category,
    extract_prompt_template_section,
    parse_prompt_template_markdown,
    builtin_prompt_templates,
    normalize_prompt_category_id,
    normalize_prompt_library_item,
    seed_system_prompt_library,
    default_prompt_libraries,
    defaultPromptTemplateCategories,
    normalize_prompt_template_categories,
    normalize_prompt_libraries,
    load_prompt_libraries,
    save_prompt_libraries,
    public_prompt_libraries,
    find_prompt_library,
)

from routers.providers import (
    router as providers_router,
    configure_providers_handlers,
    ApiProviderPayload,
    TestConnectionPayload,
    classify_upstream_model,
    parse_upstream_models,
    upstream_models_url,
    upstream_model_headers,
    volcengine_default_model_payload,
    protocol_from_payload,
    api_key_from_payload,
)

from routers.tasks import (
    router as tasks_router,
    set_tasks_history_manager,
    set_tasks_ws_manager,
    set_tasks_queue,
    set_tasks_output_file_resolver,
    record_task_event,
    _task_history_append,
    _estimate_video_cost,
    TASK_HISTORY_FILE,
    DASHSCOPE_VIDEO_PRICE_PER_SEC,
    DeleteHistoryRequest,
)

from routers.system import (
    router as system_router,
    set_system_comfyui_instances_resolver,
    set_system_runninghub_url_rewriter,
    current_app_version,
    safe_update_notes,
    read_local_update_notes,
    fetch_remote_update_notes,
    fetch_update_notes_with_fallback,
    versioned_static_html,
    sync_static_html_versions,
    static_html_response,
    app_info,
    update_connectivity_probe,
    update_connectivity,
    check_update,
    update_from_github,
    get_update_backups,
    rollback_update,
    view_image,
    download_output,
    UPDATE_LOCK,
    UpdateRequest,
    RollbackRequest,
)

from routers.comfyui import (
    router as comfyui_router,
    set_comfyui_history_saver,
    set_comfyui_env_updater,
    COMFYUI_INSTANCES,
    COMFYUI_ADDRESS,
    BACKEND_LOCAL_LOAD,
    LOAD_LOCK,
    QUEUE,
    QUEUE_LOCK,
    NEXT_TASK_ID,
    WORKFLOW_DIR,
    WORKFLOW_PATH,
    COMFYUI_DOWNLOAD_TIMEOUT,
    GenerateRequest,
    WorkflowField,
    WorkflowConfig,
    WorkflowUploadRequest,
    WorkflowRunRequest,
    ComfyInstancesPayload,
    Base64UploadRequest,
    convert_output_to_jpg,
    check_images_exist,
    is_comfy_input_media_value,
    collect_required_comfy_media,
    comfy_prompt_error_message,
    get_best_backend,
    reserve_best_backend,
    download_image,
    comfy_output_extension,
    is_video_output_item,
    comfy_output_kind,
    download_comfy_output,
    save_comfy_text_output,
    comfy_text_values_from_output,
    collect_comfy_file_items,
    comfy_class_is_preview,
    comfy_class_is_debug_text,
    get_comfy_history,
    workflow_path_from_name,
    workflow_config_path,
    is_builtin_workflow,
    run_canvas_comfy_task,
    create_canvas_comfy_task,
    get_canvas_comfy_task,
    generate,
    get_comfyui_instances,
    save_comfyui_instances,
    list_workflows,
    get_workflow,
    upload_workflow,
    save_workflow_config,
    delete_workflow,
    run_workflow,
    upload_comfyui_base64,
)

from routers.common import (
    set_online_history_saver,
    set_online_ws_manager,
    save_to_history,
)

from routers.integrations import (
    router as integrations_router,
    register_online_exception_handlers,
    rewrite_runninghub_file_url,
)

from routers.video import (
    router as video_router,
    MiniMaxTimelineExportRequest,
)

from routers.online_image import (
    router as online_image_router,
    TokenRequest,
    CloudGenRequest,
    OnlineImageRequest,
    LocalImageImportRequest,
)

from routers.chat import (
    router as chat_router,
    caption_image_with_provider,
    classify_image_with_provider,
    register_asset_library_avatar_impl,
    check_asset_library_avatar_impl,
    safe_user_id,
)

from routers.video_breakdown import router as video_breakdown_router
from routers.network import router as network_router

# --- Logging & Quiet Access Filter ---
QUIET_ACCESS_PATHS = {
    "/api/queue_status",
    "/api/canvases",
    "/api/canvases/trash",
    "/api/canvas/rhino-capture/latest",
}
QUIET_ACCESS_PREFIXES = (
    "/api/canvases/",
)

class QuietAccessLogFilter(logging.Filter):
    def filter(self, record):
        args = record.args if isinstance(record.args, tuple) else ()
        if len(args) >= 3:
            path = str(args[2]).split("?", 1)[0]
            status = int(args[4]) if len(args) >= 5 and str(args[4]).isdigit() else 0
            quiet_dynamic = any(path.startswith(prefix) and path.endswith("/meta") for prefix in QUIET_ACCESS_PREFIXES)
            if (path in QUIET_ACCESS_PATHS or quiet_dynamic) and status < 400:
                return False
        message = record.getMessage()
        if any(f'"GET {path}' in message and '" 200' in message for path in QUIET_ACCESS_PATHS):
            return False
        if 'GET /api/canvases/' in message and '/meta' in message and '" 200' in message:
            return False
        return True

logging.getLogger("uvicorn.access").addFilter(QuietAccessLogFilter())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
_server_logger = logging.getLogger("dx.server")
_server_logger.setLevel(logging.INFO)
_log_handler = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, "server.log"),
    maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8",
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_server_logger.addHandler(_log_handler)
_server_logger.propagate = False

# --- App Instance & Middleware ---
app = FastAPI(title="开卷画布 · MeansCanvas")

# Restrict CORS to local loopback and local network origins (including Tailscale RFC 6598)
ALLOWED_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+)(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3333",
        "http://localhost:3333",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    # B12-3: the app has no cookie/token session, so no legitimate flow needs
    # credentialed cross-origin requests. Disabling credentials removes the
    # "any LAN origin can read authenticated responses" amplifier while leaving
    # same-origin requests (which never consult CORS) completely unaffected.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip compression: reduce ~7.3MB static text/JS/CSS to ~1.5MB over Tailscale/WAN
import starlette.middleware.gzip as gz
gz.DEFAULT_EXCLUDED_CONTENT_TYPES = (
    "text/event-stream",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/avif",
    "video/",
    "audio/",
)
from starlette.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

_ALLOWED_HOST_PATTERN = re.compile(
    r"^(localhost|127\.0\.0\.1|0\.0\.0\.0|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+)(:\d+)?$"
)

@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    """CSRF Guard: block cross-origin state-modifying requests from untrusted web domains."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        check_url = origin or referer
        if check_url:
            from urllib.parse import urlparse
            parsed = urlparse(check_url)
            host = parsed.netloc or parsed.path
            req_host = request.headers.get("host", "")
            if host != req_host and not _ALLOWED_HOST_PATTERN.match(host):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin request forbidden by CSRF protection."}
                )
    return await call_next(request)

@app.middleware("http")
async def access_token_middleware(request: Request, call_next):
    """Enforce IC_ACCESS_TOKEN if configured in API/.env or environment."""
    configured_token = get_configured_access_token()
    if configured_token:
        path = request.url.path
        # 素材文件(/output/ /assets/)与 API 同属令牌保护范围；浏览器 <img>/<video> 自动携带登录 Cookie。
        # 需要让上游模型服务回源抓取本机素材时，可设 IC_PUBLIC_MEDIA=1 保持旧的公开读取行为。
        media_protected = path.startswith(("/output/", "/assets/")) and os.getenv("IC_PUBLIC_MEDIA", "").strip() != "1"
        if media_protected or (path.startswith("/api/") and not path.startswith(("/api/auth/", "/api/ping"))):
            auth_header = request.headers.get("authorization", "")
            provided_token = ""
            if auth_header.lower().startswith("bearer "):
                provided_token = auth_header[7:].strip()
            if not provided_token:
                provided_token = request.headers.get("x-access-token", "").strip()
            if not provided_token:
                provided_token = request.query_params.get("token", "").strip()
            if not provided_token:
                provided_token = request.cookies.get("ic_access_token", "").strip()

            import hmac
            if not provided_token or not hmac.compare_digest(provided_token, configured_token):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "未授权访问，请提供有效的访问凭据 (IC_ACCESS_TOKEN)"},
                )
    response = await call_next(request)
    if configured_token:
        query_token = request.query_params.get("token", "").strip()
        if query_token:
            import hmac
            if hmac.compare_digest(query_token, configured_token):
                response.set_cookie(key="ic_access_token", value=query_token, httponly=True, samesite="lax")
    return response

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Inject standard security hardening headers and smart caching headers into all HTTP responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if "Content-Security-Policy" not in response.headers:
        # B12-4: tighten the previously script-src-less policy. All first-party
        # scripts/styles are self-hosted under /static/vendor (Tailwind included),
        # so script-src/style-src 'self' blocks injection of externally-hosted
        # scripts while 'unsafe-inline'/'unsafe-eval' keep the existing large
        # inline blocks and the Tailwind runtime working. Data sources
        # (img/media/connect/font) stay permissive because the canvas legitimately
        # loads remote provider images and opens same-origin WebSockets — over-
        # restricting them would silently break generation previews.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https: http:; "
            "media-src 'self' data: blob: https: http:; "
            "font-src 'self' data:; "
            "connect-src 'self' ws: wss: https: http:; "
            "worker-src 'self' blob:; "
            "frame-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'self';"
        )

    # Accelerated Browser Caching: dramatically speeds up remote Tailscale / WAN asset loads
    if "Cache-Control" not in response.headers:
        path = request.url.path
        if path.endswith(".html") or path == "/":
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif path.startswith(("/static/vendor/", "/static/fonts/")) or ("v=" in str(request.url.query) and path.startswith("/static/")):
            response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
        elif path.startswith(("/api/media-preview", "/api/image-jpeg")):
            response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        elif path.startswith(("/static/", "/output/", "/assets/")):
            private = bool(get_configured_access_token()) and path.startswith(("/output/", "/assets/"))
            response.headers["Cache-Control"] = "private, max-age=86400" if private else "public, max-age=86400"
    return response

# --- Managers & History ---
manager = SafeConnectionManager()
ConnectionManager = SafeConnectionManager
history_manager = HistoryManager(HISTORY_FILE)

def save_to_history(record):
    history_manager.save(record)

# Wire initial task center hooks
set_canvas_ws_manager(manager)
set_tasks_history_manager(history_manager)
set_tasks_ws_manager(manager)
set_tasks_queue(QUEUE, QUEUE_LOCK)
set_tasks_output_file_resolver(output_file_from_url)
set_online_history_saver(save_to_history)
set_comfyui_history_saver(save_to_history)
set_comfyui_env_updater(update_env_values)

@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": friendly_validation_error(exc.errors()), "errors": exc.errors()},
    )

register_online_exception_handlers(app)

# --- Mount Domain Routers ---
app.include_router(canvas_router)
app.include_router(assets_router)
app.include_router(prompts_router)
app.include_router(providers_router)
app.include_router(tasks_router)
app.include_router(system_router)
app.include_router(comfyui_router)
app.include_router(chat_router)
app.include_router(online_image_router)
app.include_router(video_router)
app.include_router(video_breakdown_router)
app.include_router(integrations_router)
app.include_router(network_router)

# --- Auth Endpoints (Token Verification & Cookie Session) ---
class AuthLoginPayload(BaseModel):
    token: str

@app.get("/api/auth/token-status")
def auth_token_status(request: Request):
    configured = bool(get_configured_access_token())
    if not configured:
        return {"auth_required": False, "authenticated": True}
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.headers.get("x-access-token", "").strip()
    if not token:
        token = request.query_params.get("token", "").strip()
    if not token:
        token = request.cookies.get("ic_access_token", "").strip()
    import hmac
    authenticated = bool(token and hmac.compare_digest(token, get_configured_access_token()))
    return {"auth_required": True, "authenticated": authenticated}

@app.post("/api/auth/login")
def auth_login(payload: AuthLoginPayload):
    configured = get_configured_access_token()
    if not configured:
        return {"ok": True, "message": "未配置访问凭据，无需登录"}
    import hmac
    if not hmac.compare_digest(payload.token.strip(), configured):
        raise HTTPException(status_code=401, detail="凭据无效，请重试")
    resp = JSONResponse(content={"ok": True, "message": "认证成功"})
    resp.set_cookie(key="ic_access_token", value=payload.token.strip(), httponly=True, samesite="lax")
    return resp

# --- Directories & Static Files Mount ---
STATIC_DIR = os.path.join(BASE_DIR, "static")
STATIC_RUNNINGHUB_DIR = os.path.join(STATIC_DIR, "runninghub")
STATIC_RUNNINGHUB_THUMBNAIL_DIR = os.path.join(STATIC_DIR, "runninghub-thumbnails")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(STATIC_RUNNINGHUB_DIR, exist_ok=True)
os.makedirs(STATIC_RUNNINGHUB_THUMBNAIL_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_OUTPUT_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(ASSET_LIBRARY_DIR, exist_ok=True)
os.makedirs(LOCAL_UPLOAD_DIR, exist_ok=True)
os.makedirs(CANVAS_DIR, exist_ok=True)

apply_storage_settings()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
app.mount("/runninghub-thumbnails", StaticFiles(directory=STATIC_RUNNINGHUB_THUMBNAIL_DIR), name="runninghub-thumbnails")

# --- Root HTML Pages ---
MOBILE_UA_PATTERN = re.compile(r"Mobile|Android|iPhone|iPad|iPod", re.IGNORECASE)

@app.get("/")
def index(request: Request):
    # 移动端 UA → 移动改图页；?desktop=1 或 prefer_desktop cookie 可切换回桌面版
    if request.query_params.get("desktop") == "1":
        response = FileResponse(os.path.join(STATIC_DIR, "index.html"))
        response.set_cookie("prefer_desktop", "1", max_age=2592000)  # 30 天
        return response
    if request.cookies.get("prefer_desktop") == "1":
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
    if MOBILE_UA_PATTERN.search(request.headers.get("user-agent", "")):
        return RedirectResponse("/static/mobile.html")
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/mobile")
def mobile_shortcut():
    return RedirectResponse("/static/mobile.html")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    fav_path = os.path.join(STATIC_DIR, "images", "favicon.ico")
    if os.path.exists(fav_path):
        return FileResponse(fav_path, media_type="image/x-icon")
    raise HTTPException(status_code=404, detail="Favicon not found")

@app.get("/{page_name}.html")
def html_pages(page_name: str):
    file_path = os.path.join(STATIC_DIR, f"{page_name}.html")
    # Path traversal guard: ensure resolved path stays within STATIC_DIR
    if not os.path.realpath(file_path).startswith(os.path.realpath(STATIC_DIR)):
        raise HTTPException(status_code=404, detail="Page not found")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Page not found")

# --- App Lifecycle & Wire Hooks ---
GLOBAL_LOOP = None

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    global GLOBAL_LOOP
    GLOBAL_LOOP = asyncio.get_running_loop()
    set_canvas_ws_manager(manager)
    set_assets_ws_manager(manager, GLOBAL_LOOP)
    set_tasks_ws_manager(manager)
    set_online_ws_manager(manager, GLOBAL_LOOP)
    set_online_history_saver(save_to_history)
    set_comfyui_history_saver(save_to_history)
    set_comfyui_env_updater(update_env_values)
    set_image_captioner(caption_image_with_provider)
    set_image_classifier(classify_image_with_provider)
    set_avatar_handlers(register_asset_library_avatar_impl, check_asset_library_avatar_impl)
    set_runninghub_url_rewriter(rewrite_runninghub_file_url)
    set_system_comfyui_instances_resolver(lambda: COMFYUI_INSTANCES)
    set_system_runninghub_url_rewriter(rewrite_runninghub_file_url)
    sync_static_html_versions()
    try:
        await asyncio.to_thread(migrate_asset_library_into_dirs)
    except Exception as exc:
        _server_logger.warning(f"资产库分组整理失败: {exc}")
    try:
        await asyncio.to_thread(migrate_double_extension_uploads)
    except Exception as exc:
        _server_logger.warning(f"修复双重扩展名素材失败: {exc}")
    try:
        await asyncio.to_thread(history_manager._ensure_loaded)
    except Exception as exc:
        _server_logger.warning(f"预热历史缓存失败: {exc}")
    try:
        await asyncio.to_thread(canvas_cache.iter_records, False)
    except Exception as exc:
        _server_logger.warning(f"预热画布缓存失败: {exc}")

    # Tailscale 代理白名单自动守护（默认关闭；仅在显式配置 IC_ENABLE_TAILSCALE_BYPASS_WATCHDOG=1 时启用）
    async def _tailscale_bypass_watchdog():
        try:
            from scripts.ensure_tailscale_bypass import check_and_patch
            while True:
                try:
                    await asyncio.to_thread(check_and_patch, False)
                except Exception:
                    pass
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass

    enable_watchdog = (
        os.getenv("IC_ENABLE_TAILSCALE_BYPASS_WATCHDOG")
        or read_api_env_value("IC_ENABLE_TAILSCALE_BYPASS_WATCHDOG")
        or ""
    ).strip() == "1"
    watchdog_task = asyncio.create_task(_tailscale_bypass_watchdog()) if enable_watchdog else None
    try:
        yield
    finally:
        if watchdog_task is not None:
            watchdog_task.cancel()

app.router.lifespan_context = lifespan

if __name__ == "__main__":
    import argparse
    import socket
    import uvicorn
    parser = argparse.ArgumentParser(description="MeansCanvas Server (开卷画布)")
    parser.add_argument("--host", type=str, default=os.getenv("HOST", "127.0.0.1"), help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "3333")), help="Port to bind (default: 3333)")
    args = parser.parse_args()
    os.environ["IC_ACTIVE_HOST"] = str(args.host)
    os.environ["IC_ACTIVE_PORT"] = str(args.port)

    if args.host in ("0.0.0.0", "::"):
        token = get_configured_access_token()
        print("\n" + "=" * 60)
        print("  开卷画布 · MeansCanvas 局域网服务启动 (0.0.0.0)")
        if token:
            print(f"  - 本机访问:   http://127.0.0.1:{args.port}/?token={token}")
        else:
            print(f"  - 本机访问:   http://127.0.0.1:{args.port}/")
        try:
            _, _, ips = socket.gethostbyname_ex(socket.gethostname())
            for ip in ips:
                if not ip.startswith("127."):
                    if token:
                        print(f"  - 局域网访问: http://{ip}:{args.port}/?token={token}")
                    else:
                        print(f"  - 局域网访问: http://{ip}:{args.port}/")
        except Exception:
            pass
        if not token:
            print("  [提示] 当前未设置 IC_ACCESS_TOKEN，局域网免密极简模式运行。")
            print("         如需访问凭据保护，可在 API/.env 中设置 IC_ACCESS_TOKEN。")
        print("=" * 60 + "\n")

    uvicorn.run("main:app", host=args.host, port=args.port, reload=False)
