import os
import sys
import re
import json
import shutil
import time
import logging
import urllib.parse
import subprocess
import traceback
from typing import Any, Dict, List, Optional, Tuple, Set
from threading import Lock, Thread
import requests
from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from core.security import is_safe_remote_url, unpin_host_dns, validate_safe_url

logger = logging.getLogger("infinite_canvas.system")
from routers.assets import (
    output_path_for,
    output_file_from_url,
    local_media_file_by_basename,
    filename_from_media_url,
    sanitize_export_filename,
    content_type_for_path,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
UPDATE_LOCK = Lock()
EXECUTABLE_UPDATE_ENABLED = False

GITHUB_REPO_URL = 'https://github.com/zhoushimiaov/MeansCanvas'
GITHUB_VERSION_URL = 'https://raw.githubusercontent.com/zhoushimiaov/MeansCanvas/main/VERSION'
GITHUB_RAW_ROOT = 'https://raw.githubusercontent.com/zhoushimiaov/MeansCanvas/main'
GITHUB_TREE_URL = 'https://api.github.com/repos/zhoushimiaov/MeansCanvas/git/trees/main?recursive=1'
GITHUB_UPDATE_NOTES_URL = GITHUB_RAW_ROOT + '/static/update-notes.json'

MODELSCOPE_REPO_URL = 'https://modelscope.cn/api/v1/models/wuli/Infinite-Canvas'
MODELSCOPE_TREE_URL = 'https://modelscope.cn/api/v1/models/wuli/Infinite-Canvas/repo/files?Recursive=true'
MODELSCOPE_FILE_API_ROOT = 'https://modelscope.cn/api/v1/models/wuli/Infinite-Canvas/repo?Revision=master&FilePath='
MODELSCOPE_VERSION_URL = MODELSCOPE_FILE_API_ROOT + 'VERSION'
MODELSCOPE_UPDATE_NOTES_URL = MODELSCOPE_FILE_API_ROOT + 'static%2Fupdate-notes.json'

_get_comfyui_instances = lambda: ['127.0.0.1:8188']
_rewrite_runninghub_url = lambda u: u

def set_system_comfyui_instances_resolver(fn):
    global _get_comfyui_instances
    _get_comfyui_instances = fn

def set_system_runninghub_url_rewriter(fn):
    global _rewrite_runninghub_url
    _rewrite_runninghub_url = fn

router = APIRouter(tags=['system'])

def current_app_version():
    version_file = os.path.join(BASE_DIR, "VERSION")
    try:
        if os.path.exists(version_file):
            with open(version_file, "r", encoding="utf-8") as f:
                version = (f.read().strip().splitlines() or [""])[0].strip()
                if version:
                    return version
    except Exception:
        pass
    try:
        return time.strftime("%Y.%m.%d", time.localtime())
    except Exception:
        return ""

def update_notes_path() -> str:
    return os.path.join(STATIC_DIR, "update-notes.json")

def safe_update_notes(payload: Any, version: str = "") -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    clean_items = []
    for item in items[:30]:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("title") or "").strip()
            if not text:
                continue
            clean_items.append({
                "type": str(item.get("type") or "update").strip()[:32],
                "text": text[:500],
            })
        else:
            text = str(item or "").strip()
            if text:
                clean_items.append({"type": "update", "text": text[:500]})
    notes_version = str(payload.get("version") or version or "").strip()
    history = payload.get("history")
    selected_history = {}
    if version and isinstance(history, list):
        for entry in history:
            if isinstance(entry, dict) and str(entry.get("version") or "").strip() == version:
                selected_history = safe_update_notes(entry, version)
                break
    if selected_history:
        return selected_history
    return {
        "version": notes_version,
        "updated_at": str(payload.get("updated_at") or payload.get("date") or "").strip(),
        "items": clean_items,
    }

def read_local_update_notes(version: str = "") -> Dict[str, Any]:
    try:
        path = update_notes_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return safe_update_notes(json.load(f), version)
    except Exception:
        pass
    return {"version": version or current_app_version(), "updated_at": "", "items": []}

def fetch_remote_update_notes(url: str, version: str = "", timeout: float = 5.0) -> Dict[str, Any]:
    info: Dict[str, Any] = {"ok": False, "error": "", "url": url, "version": version, "items": []}
    if not url:
        info["error"] = "missing url"
        return info
    validate_safe_url(url, allow_private=False)
    try:
        resp = requests.get(
            f"{url}{'&' if '?' in url else '?'}t={int(time.time())}",
            headers={"User-Agent": "Infinite-Canvas-Updater"},
            timeout=timeout,
            proxies=urllib.request.getproxies() or None,
        )
        if 200 <= resp.status_code < 400:
            payload = json.loads(resp.content.decode("utf-8", errors="replace"))
            notes = safe_update_notes(payload, version)
            info.update(notes)
            info["ok"] = True
        else:
            info["error"] = f"HTTP {resp.status_code}"
    except Exception as exc:
        info["error"] = str(exc)
    return info

def fetch_update_notes_with_fallback(preferred_source: str, version: str, timeout: float = 3.0) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    urls = {
        "github": GITHUB_UPDATE_NOTES_URL,
        "modelscope": MODELSCOPE_UPDATE_NOTES_URL,
    }
    preferred = preferred_source if preferred_source in urls else "github"
    order = [preferred, "modelscope" if preferred == "github" else "github"]
    notes_by_source: Dict[str, Any] = {}
    best_notes: Dict[str, Any] = {"version": version, "items": []}
    for source in order:
        notes = fetch_remote_update_notes(urls[source], version, timeout=timeout)
        notes["source"] = source
        notes_by_source[source] = notes
        if notes.get("ok") and (notes.get("items") or []):
            best_notes = notes
            break
    for source, url in urls.items():
        if source not in notes_by_source:
            notes_by_source[source] = {
                "ok": False,
                "error": "未尝试：已有更新说明可用" if best_notes.get("items") else "未尝试",
                "url": url,
                "source": source,
                "version": version,
                "items": [],
            }
    return best_notes, notes_by_source

def versioned_static_html(html: str) -> str:
    version = current_app_version()
    if not version:
        return html
    safe_version = urllib.parse.quote(version, safe="._-")
    pattern = re.compile(r'(?P<prefix>(?:src|href)=["\']|@import\s+url\(["\'])(?P<url>/static/[^"\')?#]+(?:\.(?:js|css|html)))(?:\?v=[^"\')#]*)?', re.I)
    def replace(match):
        url = match.group("url")
        cache_version = safe_version
        try:
            rel = urllib.parse.unquote(url[len("/static/"):]).replace("/", os.sep)
            path = os.path.abspath(os.path.join(STATIC_DIR, rel))
            static_root = os.path.abspath(STATIC_DIR)
            if path.startswith(static_root + os.sep) and os.path.isfile(path):
                cache_version = f"{safe_version}.{int(os.path.getmtime(path))}"
        except Exception:
            pass
        return f"{match.group('prefix')}{url}?v={cache_version}"
    return pattern.sub(replace, html)

def sync_static_html_versions():
    version = current_app_version()
    if not version:
        return
    safe_version = urllib.parse.quote(version, safe="._-")
    try:
        for name in os.listdir(STATIC_DIR):
            # 跳过 macOS 在外置硬盘(ExFAT/NTFS)生成的 ._* Apple Double 元数据文件，
            # 这些是二进制文件，按 UTF-8 读取会抛 UnicodeDecodeError。
            if name.startswith("._"):
                continue
            if not name.lower().endswith(".html"):
                continue
            path = os.path.join(STATIC_DIR, name)
            if not os.path.isfile(path):
                continue
            # 单文件容错：某个文件读写失败不应中断整批同步。
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = f.read()
                new = versioned_static_html(re.sub(r'([?&]v=)[^"\'`\s<>)]*', rf'\g<1>{safe_version}', old))
                if new != old:
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        f.write(new)
            except Exception as e:
                logger.info(f"同步静态页面版本号失败({name}): {e}")
    except Exception as e:
        logger.info(f"同步静态页面版本号失败: {e}")

def static_html_response(filename: str):
    path = os.path.join(STATIC_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    return Response(
        versioned_static_html(html),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )

# --- 提示词模板 Markdown 解析器及常量已解耦迁移至 routers/prompts.py ---

@router.get("/api/app-info")
def app_info():
    version = current_app_version()
    return {
        "version": version,
        "repo_url": GITHUB_REPO_URL,
        "version_url": GITHUB_VERSION_URL,
        "tree_url": GITHUB_TREE_URL,
        "sources": {
            "github": {
                "label": "GitHub",
                "repo_url": GITHUB_REPO_URL,
                "version_url": GITHUB_VERSION_URL,
                "tree_url": GITHUB_TREE_URL,
                "update_notes_url": GITHUB_UPDATE_NOTES_URL,
            },
            "modelscope": {
                "label": "ModelScope",
                "repo_url": MODELSCOPE_REPO_URL,
                "version_url": MODELSCOPE_VERSION_URL,
                "tree_url": MODELSCOPE_TREE_URL,
                "update_notes_url": MODELSCOPE_UPDATE_NOTES_URL,
            },
        },
        "update_notes": read_local_update_notes(version),
    }

def connectivity_probe(name: str, url: str, timeout: float = 5.0) -> Dict[str, Any]:
    started = time.time()
    item = {
        "name": name,
        "url": url,
        "ok": False,
        "status": 0,
        "elapsed_ms": 0,
        "error": "",
        "timed_out": False,
    }
    try:
        validate_safe_url(url, allow_private=False)
    except Exception as e:
        item["error"] = f"地址受限或非法: {e}"
        return item
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Infinite-Canvas-Updater"},
            timeout=timeout,
            stream=True,
            proxies=urllib.request.getproxies() or None,
        )
        item["status"] = response.status_code
        item["ok"] = 200 <= response.status_code < 400
        if not item["ok"]:
            item["error"] = f"HTTP {response.status_code} {response.reason}"
        response.close()
    except requests.Timeout:
        item["timed_out"] = True
        item["error"] = f"连接超时（超过 {timeout:g}s）"
    except requests.RequestException as exc:
        item["error"] = str(exc)
    finally:
        item["elapsed_ms"] = int((time.time() - started) * 1000)
    return item

def update_connectivity_targets() -> List[Tuple[str, str, str, bool]]:
    return [
        ("GitHub 更新列表", GITHUB_TREE_URL, "github", True),
        ("GitHub 版本文件", GITHUB_VERSION_URL, "github", True),
        ("GitHub 主页", "https://github.com/", "github", False),
        ("ModelScope 版本文件", MODELSCOPE_VERSION_URL, "modelscope", True),
        ("ModelScope 空间页面", MODELSCOPE_REPO_URL, "modelscope", False),
        ("ModelScope 主页", "https://modelscope.cn/", "modelscope", False),
        ("Google 连通性", "https://www.google.com/generate_204", "reference", False),
    ]

@router.get("/api/update-connectivity/probe")
def update_connectivity_probe(name: str):
    """实时检测：只探测单个目标，前端可并发调用并逐条刷新。"""
    for t_name, url, source, required in update_connectivity_targets():
        if t_name == name:
            item = connectivity_probe(t_name, url)
            item["source"] = source
            item["required"] = required
            return item
    raise HTTPException(status_code=404, detail="未知的连通性检测目标")

@router.get("/api/update-connectivity")
def update_connectivity():
    targets = update_connectivity_targets()
    results = []
    for name, url, source, required in targets:
        item = connectivity_probe(name, url)
        item["source"] = source
        item["required"] = required
        results.append(item)
    sources = {}
    for source in ("github", "modelscope"):
        source_required = [item for item in results if item.get("source") == source and item.get("required")]
        sources[source] = {
            "ok": all(item["ok"] for item in source_required),
            "required": [item["name"] for item in source_required],
        }
    return {
        "ok": sources["github"]["ok"],
        "results": results,
        "sources": sources,
        "required": sources["github"]["required"],
        "optional": ["GitHub 主页", "ModelScope 空间页面", "ModelScope 主页", "Google 连通性"],
    }

def fetch_remote_version(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    info: Dict[str, Any] = {"version": "", "ok": False, "error": "", "url": url}
    if not url:
        info["error"] = "missing url"
        return info
    validate_safe_url(url, allow_private=False)
    try:
        resp = requests.get(
            f"{url}{'&' if '?' in url else '?'}t={int(time.time())}",
            headers={"User-Agent": "Infinite-Canvas-Updater"},
            timeout=timeout,
            proxies=urllib.request.getproxies() or None,
        )
        if 200 <= resp.status_code < 400:
            text = resp.content.decode("utf-8", errors="replace").strip()
            version = text.splitlines()[0].strip() if text else ""
            # 防御：raw 网页/错误页会返回 HTML 或 JSON，必须长得像版本号（含数字、无尖括号/花括号）
            if version and "<" not in version and "{" not in version and re.search(r"\d", version):
                info["version"] = version
                info["ok"] = True
            elif not version:
                info["error"] = "空版本文件"
            else:
                info["error"] = "版本文件格式异常"
        else:
            info["error"] = f"HTTP {resp.status_code}"
    except requests.RequestException as exc:
        info["error"] = str(exc)
    return info

def version_tuple(value: str) -> List[int]:
    return [int(x) for x in re.findall(r"\d+", str(value or ""))]

def version_gt(a: str, b: str) -> bool:
    ta, tb = version_tuple(a), version_tuple(b)
    n = max(len(ta), len(tb))
    ta += [0] * (n - len(ta))
    tb += [0] * (n - len(tb))
    return ta > tb

@router.get("/api/check-update")
def check_update():
    """服务端检测 GitHub 与 ModelScope 两个源的远端版本（走系统代理，避免浏览器跨域/被墙）。"""
    current = current_app_version()
    # 并发检测两个源，避免串行 8s+8s 拖慢首屏更新提示
    holder: Dict[str, Dict[str, Any]] = {}
    def _probe(key: str, url: str):
        item = fetch_remote_version(url, timeout=5.0)
        item["source"] = key
        holder[key] = item
    threads = [
        Thread(target=_probe, args=("github", GITHUB_VERSION_URL), daemon=True),
        Thread(target=_probe, args=("modelscope", MODELSCOPE_VERSION_URL), daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.5)
    github = holder.get("github") or {"version": "", "ok": False, "error": "检测超时（超过 5s）", "url": GITHUB_VERSION_URL, "source": "github"}
    modelscope = holder.get("modelscope") or {"version": "", "ok": False, "error": "检测超时（超过 5s）", "url": MODELSCOPE_VERSION_URL, "source": "modelscope"}
    best: Dict[str, Any] = {}
    for item in (github, modelscope):
        if item["ok"] and item["version"]:
            if not best or version_gt(item["version"], best["version"]):
                best = {"source": item["source"], "version": item["version"]}
    update_available = bool(best and version_gt(best["version"], current))
    notes_by_source: Dict[str, Any] = {}
    if best and best.get("version"):
        best_notes, notes_by_source = fetch_update_notes_with_fallback(str(best.get("source") or "github"), best["version"], timeout=3.0)
        best["update_notes"] = best_notes if best_notes.get("ok") else {"version": best["version"], "items": []}
    return {
        "current": current,
        "github": github,
        "modelscope": modelscope,
        "latest": best,
        "update_notes": best.get("update_notes") if best else {},
        "update_notes_sources": notes_by_source,
        "update_available": update_available,
        "reachable": bool(github["ok"] or modelscope["ok"]),
    }

def update_allowed_file(path: str) -> bool:
    path = str(path or "").replace("\\", "/").lstrip("/")
    if not path or any(part in {"", ".", ".."} for part in path.split("/")):
        return False
    return path in {"main.py", "VERSION"} or path.startswith("static/")

# 缓存 GitHub Tree API 响应（含 ETag），减少 60 次/h 限流压力
GITHUB_TREE_CACHE: Dict[str, Any] = {"etag": "", "data": None, "expires_at": 0.0}

def github_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 30) -> requests.Response:
    validate_safe_url(url, allow_private=False)
    try:
        response = requests.get(
            url,
            headers=headers or {},
            timeout=timeout,
            proxies=urllib.request.getproxies() or None,
        )
    except requests.RequestException as exc:
        raise urllib.error.URLError(str(exc)) from exc
    if response.status_code >= 400 or response.status_code == 304:
        raise urllib.error.HTTPError(url, response.status_code, response.reason, response.headers, None)
    return response

def github_json(url: str, use_etag_cache: bool = False):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Infinite-Canvas-Updater",
    }
    cache_key = url
    if use_etag_cache and cache_key == GITHUB_TREE_URL:
        if GITHUB_TREE_CACHE["data"] and time.time() < GITHUB_TREE_CACHE["expires_at"]:
            return GITHUB_TREE_CACHE["data"]
        if GITHUB_TREE_CACHE["etag"]:
            headers["If-None-Match"] = GITHUB_TREE_CACHE["etag"]
    try:
        resp = github_get(url, headers=headers, timeout=30)
        etag = resp.headers.get("ETag", "")
        payload = json.loads(resp.content.decode("utf-8", errors="replace"))
        if use_etag_cache and cache_key == GITHUB_TREE_URL:
            GITHUB_TREE_CACHE.update({
                "etag": etag,
                "data": payload,
                "expires_at": time.time() + 600,  # 10 分钟内复用
            })
        return payload
    except urllib.error.HTTPError as exc:
        # 304 表示对方树未变，沿用缓存
        if exc.code == 304 and use_etag_cache and GITHUB_TREE_CACHE["data"]:
            GITHUB_TREE_CACHE["expires_at"] = time.time() + 600
            return GITHUB_TREE_CACHE["data"]
        raise

def github_bytes(url: str) -> bytes:
    resp = github_get(url, headers={"User-Agent": "Infinite-Canvas-Updater"}, timeout=60)
    return resp.content

def download_github_update_files(files: List[str], staging_root: str) -> None:
    staging_root_abs = os.path.abspath(staging_root)
    for rel in files:
        safe_update_target(rel)
        raw_url = f"{GITHUB_RAW_ROOT}/{urllib.parse.quote(rel, safe='/')}"
        data = github_bytes(raw_url)
        stage_path = os.path.abspath(os.path.join(staging_root_abs, *rel.split("/")))
        if os.path.commonpath([staging_root_abs, stage_path]) != staging_root_abs:
            raise ValueError(f"更新暂存路径不安全：{rel}")
        os.makedirs(os.path.dirname(stage_path), exist_ok=True)
        with open(stage_path, "wb") as f:
            f.write(data)

def modelscope_update_file_list() -> List[str]:
    """通过 ModelScope 仓库文件 API 列出所有允许更新的文件（不依赖 git）。"""
    resp = github_get(MODELSCOPE_TREE_URL, headers={"User-Agent": "Infinite-Canvas-Updater"}, timeout=30)
    payload = json.loads(resp.content.decode("utf-8", errors="replace"))
    files_node = ((payload.get("Data") or {}).get("Files")) or []
    out: List[str] = []
    for entry in files_node:
        if not isinstance(entry, dict):
            continue
        if entry.get("Type") != "blob":
            continue
        path = str(entry.get("Path") or "").replace("\\", "/")
        if update_allowed_file(path):
            out.append(path)
    return sorted(set(out))

def modelscope_file_bytes(rel: str) -> bytes:
    url = MODELSCOPE_FILE_API_ROOT + urllib.parse.quote(rel, safe="/")
    resp = github_get(url, headers={"User-Agent": "Infinite-Canvas-Updater"}, timeout=60)
    return resp.content

def download_modelscope_update_files(staging_root: str) -> List[str]:
    # 用 HTTP 仓库文件 API 下载（与 GitHub raw 同样思路），不依赖本机安装 Git。
    # 之前用 git clone 会要求目标机装 Git for Windows，很多用户没装 → 一键更新失败。
    files = modelscope_update_file_list()
    if not files:
        raise RuntimeError("ModelScope 未返回任何文件")
    if "main.py" not in files or "VERSION" not in files:
        raise RuntimeError("ModelScope 更新源缺少 main.py 或 VERSION")
    if not any(f.startswith("static/") for f in files):
        raise RuntimeError("ModelScope 未返回 static 文件，已取消更新")
    staging_root_abs = os.path.abspath(staging_root)
    for rel in files:
        safe_update_target(rel)
        data = modelscope_file_bytes(rel)
        stage_path = os.path.abspath(os.path.join(staging_root_abs, *rel.split("/")))
        if os.path.commonpath([staging_root_abs, stage_path]) != staging_root_abs:
            raise ValueError(f"更新暂存路径不安全：{rel}")
        os.makedirs(os.path.dirname(stage_path), exist_ok=True)
        with open(stage_path, "wb") as f:
            f.write(data)
    return files

def safe_update_target(path: str) -> str:
    rel = str(path or "").replace("\\", "/").lstrip("/")
    if not update_allowed_file(rel):
        raise ValueError(f"更新文件不在允许范围：{rel}")
    target = os.path.abspath(os.path.join(BASE_DIR, *rel.split("/")))
    base = os.path.abspath(BASE_DIR)
    if os.path.commonpath([base, target]) != base:
        raise ValueError(f"更新路径不安全：{rel}")
    return target

def safe_static_dir() -> str:
    target = os.path.abspath(STATIC_DIR)
    expected = os.path.abspath(os.path.join(BASE_DIR, "static"))
    base = os.path.abspath(BASE_DIR)
    if target != expected or os.path.commonpath([base, target]) != base:
        raise RuntimeError(f"static 路径不安全：{target}")
    return target

def schedule_self_restart(delay_seconds: int = 3) -> bool:
    """派生脱离父进程的小脚本，等几秒后启动启动服务脚本，并干掉当前 PID。"""
    delay = max(1, int(delay_seconds or 3))
    pid = os.getpid()
    try:
        if os.name == "nt":
            launcher = os.path.join(BASE_DIR, "启动服务.bat")
            if not os.path.exists(launcher):
                launcher = os.path.join(BASE_DIR, "start.bat")
            bat_path = os.path.join(BASE_DIR, "_self_restart.bat")
            log_path = os.path.join(BASE_DIR, "_self_restart.log")
            script = (
                "@echo off\r\n"
                "chcp 65001 >nul\r\n"
                "setlocal\r\n"
                f"set \"APP_DIR={BASE_DIR}\"\r\n"
                f"set \"LAUNCHER={launcher}\"\r\n"
                f"set \"LOG_FILE={log_path}\"\r\n"
                "echo [%date% %time%] restart scheduled >> \"%LOG_FILE%\"\r\n"
                f"timeout /t {delay} /nobreak >nul\r\n"
                "echo [%date% %time%] stopping old process >> \"%LOG_FILE%\"\r\n"
                f"taskkill /F /PID {pid} >nul 2>&1\r\n"
                "timeout /t 2 /nobreak >nul\r\n"
                "cd /d \"%APP_DIR%\"\r\n"
                "if exist \"%LAUNCHER%\" (\r\n"
                "  echo [%date% %time%] starting launcher: %LAUNCHER% >> \"%LOG_FILE%\"\r\n"
                "  start \"ComfyUI-API-Modelscope\" /D \"%APP_DIR%\" cmd /k call \"%LAUNCHER%\"\r\n"
                ") else (\r\n"
                "  echo [%date% %time%] launcher missing, fallback to python main.py >> \"%LOG_FILE%\"\r\n"
                "  if exist \"%APP_DIR%\\python\\python.exe\" (\r\n"
                "    start \"ComfyUI-API-Modelscope\" /D \"%APP_DIR%\" cmd /k \"\"%APP_DIR%\\python\\python.exe\" main.py\"\r\n"
                "  ) else (\r\n"
                "    start \"ComfyUI-API-Modelscope\" /D \"%APP_DIR%\" cmd /k python main.py\r\n"
                "  )\r\n"
                ")\r\n"
                "del \"%~f0\"\r\n"
            )
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(script)
            subprocess.Popen(
                ["cmd", "/c", bat_path],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        else:
            launcher = os.path.join(BASE_DIR, "mac-启动服务.command")
            if not os.path.exists(launcher):
                launcher = os.path.join(BASE_DIR, "start.sh")
            sh_path = os.path.join(BASE_DIR, "_self_restart.sh")
            script = (
                "#!/bin/sh\n"
                f"sleep {delay}\n"
                f"kill -9 {pid} 2>/dev/null\n"
                f"cd \"{BASE_DIR}\"\n"
                f"if [ -x \"{launcher}\" ]; then nohup \"{launcher}\" >/dev/null 2>&1 &\n"
                f"elif [ -f \"{launcher}\" ]; then nohup /bin/sh \"{launcher}\" >/dev/null 2>&1 &\n"
                "fi\n"
                "rm -- \"$0\"\n"
            )
            with open(sh_path, "w", encoding="utf-8") as f:
                f.write(script)
            os.chmod(sh_path, 0o755)
            subprocess.Popen(
                ["/bin/sh", sh_path],
                start_new_session=True,
                close_fds=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True
    except Exception as exc:
        logging.exception("schedule_self_restart failed: %s", exc)
        return False

class UpdateRequest(BaseModel):
    auto_restart: bool = False
    restart_delay: int = 3
    source: str = "github"
    fallback: bool = True

def github_update_file_list() -> Tuple[List[str], List[str], List[str]]:
    tree_data = github_json(GITHUB_TREE_URL, use_etag_cache=True)
    entries = tree_data.get("tree") or []
    static_files = []
    root_files = []
    for entry in entries:
        path = str(entry.get("path") or "").replace("\\", "/")
        if entry.get("type") == "blob" and update_allowed_file(path):
            if path.startswith("static/"):
                static_files.append(path)
            else:
                root_files.append(path)
    if "main.py" not in root_files:
        root_files.append("main.py")
    if "VERSION" not in root_files:
        root_files.append("VERSION")
    static_files = sorted(set(static_files))
    root_files = sorted(set(root_files))
    files = root_files + static_files
    if not static_files:
        raise RuntimeError("GitHub 未返回 static 文件，已取消更新")
    return root_files, static_files, files

def staged_update_file_list(staging_root: str) -> Tuple[List[str], List[str], List[str]]:
    root_files = []
    static_files = []
    for root_dir, _, names in os.walk(staging_root):
        for name in names:
            path = os.path.abspath(os.path.join(root_dir, name))
            rel = os.path.relpath(path, staging_root).replace("\\", "/")
            if not update_allowed_file(rel):
                continue
            if rel.startswith("static/"):
                static_files.append(rel)
            else:
                root_files.append(rel)
    if "main.py" not in root_files or "VERSION" not in root_files:
        raise RuntimeError("更新源缺少 main.py 或 VERSION")
    if not static_files:
        raise RuntimeError("更新源未返回 static 文件，已取消更新")
    root_files = sorted(set(root_files))
    static_files = sorted(set(static_files))
    return root_files, static_files, root_files + static_files

UPDATE_SOURCE_LABELS = {"github": "GitHub", "modelscope": "ModelScope"}

def normalize_update_source(value: str) -> str:
    source = str(value or "github").strip().lower()
    if source == "ms":
        return "modelscope"
    if source not in {"github", "modelscope"}:
        return "github"
    return source

def stage_update_from_source(source: str, staging_root: str) -> Tuple[List[str], List[str], List[str]]:
    """下载指定源的更新文件到 staging，返回 (root_files, static_files, files)。失败抛异常。"""
    if source == "modelscope":
        download_modelscope_update_files(staging_root)
        return staged_update_file_list(staging_root)
    root_files, static_files, files = github_update_file_list()
    download_github_update_files(files, staging_root)
    return root_files, static_files, files

def validate_staged_update(staging_root: str, root_files: List[str], static_files: List[str]) -> None:
    """Reject incomplete or syntactically invalid downloads before touching live code."""
    main_path = os.path.join(staging_root, "main.py")
    version_path = os.path.join(staging_root, "VERSION")
    if not os.path.isfile(main_path) or not os.path.isfile(version_path):
        raise RuntimeError("更新暂存缺少 main.py 或 VERSION")
    with open(main_path, "rb") as f:
        compile(f.read(), main_path, "exec")
    with open(version_path, "r", encoding="utf-8") as f:
        version = (f.read().strip().splitlines() or [""])[0].strip()
    if not version or len(version) > 80 or any(ch in version for ch in "<>\\r\\n"):
        raise RuntimeError("更新暂存的 VERSION 格式异常")
    for rel in list(root_files or []) + list(static_files or []):
        safe_update_target(rel)
        staged_path = os.path.join(staging_root, *str(rel).replace("\\", "/").split("/"))
        if not os.path.isfile(staged_path):
            raise RuntimeError(f"更新暂存缺少文件：{rel}")

UPDATE_BACKUP_MANIFEST = "manifest.json"
UPDATE_BACKUP_FORMAT = 2
UPDATE_BACKUP_RETENTION = 10

def update_backup_root() -> str:
    return os.path.abspath(os.path.join(DATA_DIR, "update_backups"))

def next_update_backup_dir(prefix: str = "") -> str:
    root = update_backup_root()
    os.makedirs(root, exist_ok=True)
    base = f"{prefix}{time.strftime('%Y%m%d-%H%M%S')}"
    candidate = os.path.join(root, base)
    suffix = 2
    while os.path.exists(candidate):
        candidate = os.path.join(root, f"{base}-{suffix}")
        suffix += 1
    return candidate

def update_backup_manifest_path(backup_dir: str) -> str:
    return os.path.join(backup_dir, UPDATE_BACKUP_MANIFEST)

def read_update_backup_manifest(backup_dir: str) -> Dict[str, Any]:
    try:
        with open(update_backup_manifest_path(backup_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def write_update_backup_manifest(backup_dir: str, payload: Dict[str, Any]) -> None:
    path = update_backup_manifest_path(backup_dir)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)

def count_regular_files(path: str) -> int:
    return sum(len(files) for _, _, files in os.walk(path)) if os.path.isdir(path) else 0

def prune_update_backups(keep_names: Optional[set] = None) -> List[str]:
    """Keep the newest restore points while never deleting an active protected point."""
    keep_names = {str(name) for name in (keep_names or set()) if str(name)}
    backups = sorted(list_update_backups(), key=lambda item: float(item.get("created_at") or 0), reverse=True)
    selected_names = []
    for item in backups:
        name = str(item.get("name") or "")
        if name in keep_names and name not in selected_names:
            selected_names.append(name)
    for item in backups:
        name = str(item.get("name") or "")
        if len(selected_names) >= UPDATE_BACKUP_RETENTION:
            break
        if name and name not in selected_names:
            selected_names.append(name)
    selected = set(selected_names)
    removed: List[str] = []
    for item in backups:
        name = str(item.get("name") or "")
        if name in selected:
            continue
        path = os.path.join(update_backup_root(), name)
        try:
            shutil.rmtree(path)
            removed.append(name)
        except OSError as exc:
            logger.info(f"[update] 清理旧恢复点失败 {name}: {exc}")
    return removed

def create_update_backup(
    backup_dir: str,
    root_files: List[str],
    static_files: List[str],
    *,
    kind: str,
    source: str = "",
    target_version: str = "",
    parent_backup: str = "",
    update_notes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a complete, self-describing restore point before replacing update payloads."""
    backup_root_abs = update_backup_root()
    backup_dir = os.path.abspath(backup_dir)
    if os.path.commonpath([backup_root_abs, backup_dir]) != backup_root_abs:
        raise ValueError("备份路径不安全")
    if os.path.exists(backup_dir):
        raise FileExistsError("备份目录已存在")
    clean_root_files = sorted({str(item or "").replace("\\", "/") for item in root_files if update_allowed_file(item) and not str(item).startswith("static/")})
    clean_static_files = sorted({str(item or "").replace("\\", "/") for item in static_files if str(item).startswith("static/") and update_allowed_file(item)})
    manifest: Dict[str, Any] = {
        "format": UPDATE_BACKUP_FORMAT,
        "state": "creating",
        "kind": kind,
        "created_at": time.time(),
        "from_version": current_app_version(),
        "target_version": str(target_version or "").strip(),
        "source": str(source or "").strip(),
        "parent_backup": str(parent_backup or "").strip(),
        "update_notes": safe_update_notes(update_notes or {}, str(target_version or "").strip()),
        "root_files": {},
        "static_snapshot": {"exists": False, "file_count": 0},
        "affected_files": clean_root_files + clean_static_files,
    }
    try:
        os.makedirs(backup_dir, exist_ok=False)
        write_update_backup_manifest(backup_dir, manifest)
        for rel in clean_root_files:
            target = safe_update_target(rel)
            existed = os.path.isfile(target)
            manifest["root_files"][rel] = {"existed": existed}
            if existed:
                backup_path = os.path.join(backup_dir, *rel.split("/"))
                os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                shutil.copy2(target, backup_path)
        static_dir = safe_static_dir()
        if os.path.isdir(static_dir):
            backup_static_dir = os.path.join(backup_dir, "static")
            shutil.copytree(static_dir, backup_static_dir)
            manifest["static_snapshot"] = {
                "exists": True,
                "file_count": count_regular_files(backup_static_dir),
            }
        manifest["state"] = "ready"
        write_update_backup_manifest(backup_dir, manifest)
        return manifest
    except Exception:
        if os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)
        raise

@router.post("/api/update-from-github")
def update_from_github(req: UpdateRequest = UpdateRequest()):
    if not EXECUTABLE_UPDATE_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="当前定制分叉版本未配置可信的发布源，在线可执行更新已禁用；请通过项目维护者提供的渠道更新。",
        )
    if not UPDATE_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="正在更新中，请稍后再试")
    staging_root = ""
    requested_source = normalize_update_source(req.source)
    # 冗余设计：先用用户选择的源，失败后自动切换到另一个源兜底，全部失败才报错
    source_order = [requested_source]
    if req.fallback:
        other = "modelscope" if requested_source == "github" else "github"
        source_order.append(other)
    try:
        backup_root = ""
        backup_manifest: Dict[str, Any] = {}

        # 下载阶段（带兜底切换），任意源成功即停止
        source = requested_source
        root_files = static_files = files = None
        download_errors: List[str] = []
        fallback_used = False
        for idx, candidate in enumerate(source_order):
            attempt_staging = os.path.join(
                DATA_DIR, "update_staging",
                f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{candidate}",
            )
            if os.path.isdir(attempt_staging):
                shutil.rmtree(attempt_staging, ignore_errors=True)
            label = UPDATE_SOURCE_LABELS.get(candidate, candidate)
            logger.info(f"[update] 尝试下载源 [{idx + 1}/{len(source_order)}] {label}（{candidate}）→ {attempt_staging}")
            try:
                root_files, static_files, files = stage_update_from_source(candidate, attempt_staging)
                source = candidate
                staging_root = attempt_staging
                fallback_used = idx > 0
                logger.info(f"[update] 下载源 {label} 成功，共 {len(files or [])} 个文件")
                break
            except Exception as exc:  # noqa: BLE001 — 记录后尝试下一个源
                if os.path.isdir(attempt_staging):
                    shutil.rmtree(attempt_staging, ignore_errors=True)
                logger.info(f"[update] 下载源 {label} 失败：{exc}")
                traceback.print_exc()
                download_errors.append(f"{label}：{exc}")
        if not staging_root:
            detail = "；".join(download_errors) or "未知错误"
            logger.info(f"[update] 所有下载源均失败 → {detail}")
            raise HTTPException(status_code=502, detail=f"所有下载源均失败 → {detail}")

        validate_staged_update(staging_root, root_files, static_files)

        new_version = ""
        try:
            with open(os.path.join(staging_root, "VERSION"), "r", encoding="utf-8") as f:
                new_version = (f.read().strip().splitlines() or [""])[0].strip()
        except Exception:
            pass
        notes_file = os.path.join(staging_root, "static", "update-notes.json")
        update_notes: Dict[str, Any] = {}
        try:
            if os.path.exists(notes_file):
                with open(notes_file, "r", encoding="utf-8") as f:
                    update_notes = safe_update_notes(json.load(f), new_version)
        except Exception:
            update_notes = {}
        # A restore point must be complete before any live file is replaced.
        backup_root = next_update_backup_dir()
        backup_manifest = create_update_backup(
            backup_root,
            root_files,
            static_files,
            kind="update",
            source=source,
            target_version=new_version,
            update_notes=update_notes,
        )
        updated = []

        staged_static_dir = os.path.join(staging_root, "static")
        if not os.path.isdir(staged_static_dir):
            raise RuntimeError("GitHub static 暂存目录不存在，已取消更新")
        static_dir = safe_static_dir()
        backup_static_dir = os.path.join(backup_root, "static")
        if os.path.isdir(static_dir):
            shutil.rmtree(static_dir)
        try:
            shutil.copytree(staged_static_dir, static_dir)
        except Exception:
            if os.path.isdir(static_dir):
                shutil.rmtree(static_dir, ignore_errors=True)
            if os.path.isdir(backup_static_dir):
                shutil.copytree(backup_static_dir, static_dir)
            raise
        updated.extend(static_files)

        replaced_root_files = []
        try:
            for rel in root_files:
                target = safe_update_target(rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                temp_path = f"{target}.update_tmp"
                shutil.copy2(os.path.join(staging_root, *rel.split("/")), temp_path)
                os.replace(temp_path, target)
                replaced_root_files.append(rel)
                updated.append(rel)
        except Exception:
            for rel in reversed(replaced_root_files):
                backup_path = os.path.join(backup_root, *rel.split("/"))
                target = safe_update_target(rel)
                if os.path.exists(backup_path):
                    temp_path = f"{target}.rollback_tmp"
                    shutil.copy2(backup_path, temp_path)
                    os.replace(temp_path, target)
                elif not bool((backup_manifest.get("root_files") or {}).get(rel, {}).get("existed")) and os.path.exists(target):
                    os.remove(target)
            if os.path.isdir(static_dir):
                shutil.rmtree(static_dir, ignore_errors=True)
            if os.path.isdir(backup_static_dir):
                shutil.copytree(backup_static_dir, static_dir)
            raise

        restart_scheduled = False
        if req.auto_restart and updated:
            restart_scheduled = schedule_self_restart(req.restart_delay)
        pruned_backups = prune_update_backups({os.path.basename(backup_root)})
        return {
            "ok": True,
            "source": source,
            "source_label": UPDATE_SOURCE_LABELS.get(source, source),
            "requested_source": requested_source,
            "fallback_used": fallback_used,
            "download_errors": download_errors,
            "updated": updated,
            "count": len(updated),
            "version": new_version,
            "update_notes": update_notes,
            "backup_dir": backup_root,
            "backup": backup_manifest,
            "pruned_backups": pruned_backups,
            "restart_required": True,
            "restart_scheduled": restart_scheduled,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"更新失败：{exc}") from exc
    finally:
        if staging_root and os.path.isdir(staging_root):
            shutil.rmtree(staging_root, ignore_errors=True)
        UPDATE_LOCK.release()

def list_update_backups() -> List[Dict[str, Any]]:
    root = update_backup_root()
    if not os.path.isdir(root):
        return []
    items = []
    for name in sorted(os.listdir(root), reverse=True):
        bp = os.path.join(root, name)
        if not os.path.isdir(bp):
            continue
        manifest = read_update_backup_manifest(bp)
        if manifest and manifest.get("state") != "ready":
            continue
        file_count = count_regular_files(bp) - (1 if manifest else 0)
        try:
            created_at = float(manifest.get("created_at") or os.path.getmtime(bp))
        except OSError:
            created_at = 0.0
        items.append({
            "name": name,
            "file_count": max(0, file_count),
            "created_at": created_at,
            "format": manifest.get("format") if manifest else 1,
            "kind": manifest.get("kind") if manifest else "legacy",
            "from_version": manifest.get("from_version") if manifest else "",
            "target_version": manifest.get("target_version") if manifest else "",
            "source": manifest.get("source") if manifest else "",
            "update_notes": manifest.get("update_notes") if manifest else {},
            "affected_file_count": len(manifest.get("affected_files") or []) if manifest else file_count,
            "affected_files": list(manifest.get("affected_files") or [])[:30] if manifest else [],
        })
    return sorted(items, key=lambda item: float(item.get("created_at") or 0), reverse=True)

@router.get("/api/update-backups")
def get_update_backups():
    return {"backups": list_update_backups()}

class RollbackRequest(BaseModel):
    name: str = ""
    auto_restart: bool = False
    restart_delay: int = 3

@router.post("/api/update-rollback")
def rollback_update(req: RollbackRequest):
    if not EXECUTABLE_UPDATE_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="当前定制分叉版本未配置可信的发布源，在线可执行更新已禁用；请通过项目维护者提供的渠道更新。",
        )
    if not req.name:
        raise HTTPException(status_code=400, detail="缺少备份名称")
    if not UPDATE_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="正在更新中，请稍后再试")
    try:
        backup_root_abs = os.path.abspath(os.path.join(DATA_DIR, "update_backups"))
        backup_dir = os.path.abspath(os.path.join(backup_root_abs, req.name))
        if os.path.commonpath([backup_root_abs, backup_dir]) != backup_root_abs:
            raise HTTPException(status_code=400, detail="备份路径不安全")
        if not os.path.isdir(backup_dir):
            raise HTTPException(status_code=404, detail="备份不存在")
        manifest = read_update_backup_manifest(backup_dir)
        if manifest and manifest.get("state") != "ready":
            raise HTTPException(status_code=409, detail="备份尚未完整创建，不能还原")
        manifest_roots = manifest.get("root_files") if isinstance(manifest.get("root_files"), dict) else {}
        root_files = sorted(manifest_roots.keys()) if manifest_roots else ["main.py", "VERSION"]
        # Restoring is itself a risky operation. Preserve the live version first so
        # the user can roll forward again if the selected historical build is worse.
        rollback_backup_dir = next_update_backup_dir("rollback-")
        rollback_backup = create_update_backup(
            rollback_backup_dir,
            root_files,
            [],
            kind="rollback_safety",
            source="local-rollback",
            target_version=str(manifest.get("from_version") or "").strip(),
            parent_backup=req.name,
            update_notes={
                "version": current_app_version(),
                "items": [{"type": "rollback", "text": f"还原恢复点 {req.name}"}],
            },
        )
        restored = []
        skipped = []
        removed = []
        backup_static_dir = os.path.join(backup_dir, "static")
        if os.path.isdir(backup_static_dir):
            static_dir = safe_static_dir()
            if os.path.isdir(static_dir):
                shutil.rmtree(static_dir)
            try:
                shutil.copytree(backup_static_dir, static_dir)
            except Exception:
                if os.path.isdir(static_dir):
                    shutil.rmtree(static_dir, ignore_errors=True)
                raise
            for dirpath, _, filenames in os.walk(backup_static_dir):
                for fn in filenames:
                    src = os.path.join(dirpath, fn)
                    restored.append(os.path.relpath(src, backup_dir).replace("\\", "/"))
        elif manifest and isinstance(manifest.get("static_snapshot"), dict) and not manifest["static_snapshot"].get("exists"):
            static_dir = safe_static_dir()
            if os.path.isdir(static_dir):
                shutil.rmtree(static_dir)
                removed.append("static/")
        for dirpath, _, filenames in os.walk(backup_dir):
            for fn in filenames:
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(src, backup_dir).replace("\\", "/")
                if rel.startswith("static/"):
                    continue
                if not update_allowed_file(rel):
                    skipped.append(rel)
                    continue
                try:
                    target = safe_update_target(rel)
                except ValueError:
                    skipped.append(rel)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                temp_path = f"{target}.rollback_tmp"
                with open(src, "rb") as fin, open(temp_path, "wb") as fout:
                    shutil.copyfileobj(fin, fout)
                os.replace(temp_path, target)
                restored.append(rel)
        for rel, info in manifest_roots.items():
            if not update_allowed_file(rel) or str(rel).startswith("static/"):
                continue
            if bool((info or {}).get("existed")):
                continue
            target = safe_update_target(rel)
            if os.path.isfile(target):
                os.remove(target)
                removed.append(rel)
        restart_scheduled = False
        if req.auto_restart and restored:
            restart_scheduled = schedule_self_restart(req.restart_delay)
        pruned_backups = prune_update_backups({req.name, os.path.basename(rollback_backup_dir)})
        return {
            "ok": True,
            "restored": restored,
            "skipped": skipped,
            "removed": removed,
            "count": len(restored),
            "rollback_backup_dir": rollback_backup_dir,
            "rollback_backup": rollback_backup,
            "pruned_backups": pruned_backups,
            "restart_required": True,
            "restart_scheduled": restart_scheduled,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"回滚失败：{exc}") from exc
    finally:
        UPDATE_LOCK.release()


@router.get("/api/view")
def view_image(filename: str, type: str = "input", subfolder: str = ""):
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    safe_name = os.path.basename(filename or "")
    if not safe_name or not re.fullmatch(r"[\w.\-]+", safe_name):
        raise HTTPException(status_code=400, detail="非法文件名")
    safe_sub = subfolder or ""
    if not re.fullmatch(r"[\w.\-/]*", safe_sub) or ".." in safe_sub or safe_sub.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail="非法子目录")
    if type not in ("input", "output", "temp"):
        raise HTTPException(status_code=400, detail="非法类型")

    # 先按原逻辑去各 ComfyUI 后端找
    for addr in _get_comfyui_instances():
        try:
            url = f"http://{addr}/view"
            params = {"filename": safe_name, "type": type, "subfolder": safe_sub}
            r = requests.get(url, params=params, timeout=1)
            if r.status_code == 200:
                return Response(content=r.content, media_type=r.headers.get('Content-Type'))
        except Exception:
            continue
    # 后端都拿不到时回退本地 assets/<input|output>/
    # 适用场景：画布通过 /api/ai/upload 把参考图直接落到本地 assets/input/，
    # 但 ComfyUI 的 input 可能因为重启/清理而丢失，导致 enhance/klein 等页面预览对比图 404
    if not safe_sub and type in ("input", "output"):
        local_path = output_path_for(safe_name, "input" if type == "input" else "output")
        if os.path.isfile(local_path):
            return FileResponse(local_path, media_type=content_type_for_path(local_path))
    raise HTTPException(status_code=404, detail="Image not found on any available backend")

@router.get("/api/download-output")
def download_output(request: Request, url: str, name: str = "", inline: bool = False):
    url = _rewrite_runninghub_url(url)
    path = output_file_from_url(url)
    if not path:
        path = local_media_file_by_basename(filename_from_media_url(url, ""))
    if path:
        filename = sanitize_export_filename(os.path.basename(name) if name else os.path.basename(path), os.path.basename(path))
        return FileResponse(path, media_type=content_type_for_path(path), filename=None if inline else filename)
    # 远程文件：流式代理，逐跳校验重定向目标防止 SSRF 绕过，并流式传输避免大文件占爆内存。
    current_url = str(url or "").strip()
    redirects_left = 5
    pinned_hosts = []
    upstream = None
    try:
        while True:
            parsed = urllib.parse.urlparse(current_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise HTTPException(status_code=400, detail="无效的下载地址")
            safe, reason = is_safe_remote_url(current_url, pin_dns=True)
            if not safe:
                raise HTTPException(status_code=403, detail=f"安全拦截：禁止代理下载受限目标或私有内网地址 ({reason})")
            h = (parsed.hostname or "").strip().lower()
            if h:
                pinned_hosts.append(h)
            upstream_headers = {"User-Agent": "ComfyUI-API-Modelscope/1.0"}
            range_header = request.headers.get("range")
            if range_header:
                upstream_headers["Range"] = range_header
            upstream = requests.get(
                current_url, stream=True, timeout=(10, 60),
                headers=upstream_headers,
                allow_redirects=False,
            )
            if upstream.status_code in (301, 302, 303, 307, 308):
                upstream.close()
                if redirects_left <= 0:
                    raise HTTPException(status_code=400, detail="重定向次数过多")
                location = upstream.headers.get("Location")
                if not location:
                    raise HTTPException(status_code=400, detail="重定向缺少 Location 头")
                next_url = urllib.parse.urljoin(current_url, location)
                current_url = next_url
                redirects_left -= 1
                continue
            upstream.raise_for_status()
            break
    except HTTPException:
        for ph in pinned_hosts:
            unpin_host_dns(ph)
        raise
    except requests.RequestException as exc:
        for ph in pinned_hosts:
            unpin_host_dns(ph)
        raise HTTPException(status_code=502, detail=f"远程文件下载失败：{exc}")

    content_type = upstream.headers.get("content-type") or "application/octet-stream"
    fallback = filename_from_media_url(current_url, "download.bin")
    filename = sanitize_export_filename(os.path.basename(name) if name else fallback, fallback)
    disposition = "inline" if inline else "attachment"
    headers = {"Content-Disposition": f"{disposition}; filename*=UTF-8''{urllib.parse.quote(filename)}"}
    for key in ("content-range", "accept-ranges"):
        value = upstream.headers.get(key)
        if value:
            headers["-".join(part.capitalize() for part in key.split("-"))] = value

    MAX_STREAM_BYTES = 500 * 1024 * 1024

    def stream_remote():
        total_bytes = 0
        try:
            for chunk in upstream.iter_content(chunk_size=256 * 1024):
                if chunk:
                    total_bytes += len(chunk)
                    if total_bytes > MAX_STREAM_BYTES:
                        break
                    yield chunk
        finally:
            upstream.close()
            for ph in pinned_hosts:
                unpin_host_dns(ph)

    return StreamingResponse(stream_remote(), media_type=content_type, headers=headers, status_code=upstream.status_code)

