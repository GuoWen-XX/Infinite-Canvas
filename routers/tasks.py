"""Task Center, History & WebSocket Gateway Router for Infinite-Canvas.

Decoupled from monolithic main.py to provide clean, modular, and thread-safe
task history tracking, cost estimation, generation history CRUD, and real-time stats WebSocket.
"""

import os
import re
import time
import json
import logging
from threading import RLock
from typing import Dict, Any, List, Optional, Callable
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from core.providers import read_api_env_value

logger = logging.getLogger("infinite_canvas.tasks")

router = APIRouter(tags=["tasks"])

# ===== 路径与锁常量 =====
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
TASK_HISTORY_FILE = os.path.join(DATA_DIR, "task_history.jsonl")

TASK_HISTORY_LOCK = RLock()

DASHSCOPE_VIDEO_PRICE_PER_SEC: Dict[str, Dict[str, float]] = {
    "wan3.0-video": {"480P": 0.3, "720P": 0.6, "1080P": 1.2},
    "wan3.0-video-prime": {"480P": 0.45, "720P": 0.9, "1080P": 1.8},
    "happyhorse-1.1-t2v": {"480P": 0.45, "720P": 0.9, "1080P": 1.2},
    "happyhorse-1.1-i2v": {"480P": 0.45, "720P": 0.9, "1080P": 1.2},
    "happyhorse-1.1-r2v": {"480P": 0.45, "720P": 0.9, "1080P": 1.2},
}

# ===== Pydantic 模型 =====

class DeleteHistoryRequest(BaseModel):
    timestamp: float


# ===== 内部状态引用 =====

_history_manager: Optional[Any] = None
_ws_manager: Optional[Any] = None
_queue_ref: Optional[List[Any]] = None
_queue_lock: Optional[Any] = None
_output_file_resolver: Optional[Callable[[str], Optional[str]]] = None


def set_tasks_history_manager(mgr: Any) -> None:
    global _history_manager
    _history_manager = mgr


def set_tasks_ws_manager(mgr: Any) -> None:
    global _ws_manager
    _ws_manager = mgr


def set_tasks_queue(queue_list: List[Any], queue_lock: Any) -> None:
    global _queue_ref, _queue_lock
    _queue_ref = queue_list
    _queue_lock = queue_lock


def set_tasks_output_file_resolver(resolver: Callable[[str], Optional[str]]) -> None:
    global _output_file_resolver
    _output_file_resolver = resolver


# ===== 任务记录与费用预估工具函数 =====

MAX_TASK_HISTORY_RECORDS = 5000
TASK_HISTORY_COMPACT_THRESHOLD = 6000
_task_history_write_count = 0

def compact_task_history(max_records: int = MAX_TASK_HISTORY_RECORDS) -> bool:
    """Compacts task_history.jsonl down to the newest max_records records using atomic replace."""
    if not os.path.exists(TASK_HISTORY_FILE):
        return False
    try:
        with TASK_HISTORY_LOCK:
            with open(TASK_HISTORY_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) <= max_records:
                return False
            retained = lines[-max_records:]
            tmp_path = f"{TASK_HISTORY_FILE}.tmp-{os.getpid()}"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.writelines(retained)
            os.replace(tmp_path, TASK_HISTORY_FILE)
            return True
    except Exception as exc:
        logger.warning(f"task history compaction failed: {exc}")
        return False

def _task_history_append(record: Dict[str, Any]) -> None:
    global _task_history_write_count
    try:
        os.makedirs(os.path.dirname(TASK_HISTORY_FILE), exist_ok=True)
        with TASK_HISTORY_LOCK:
            with open(TASK_HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            _task_history_write_count += 1
            if _task_history_write_count >= 100:
                _task_history_write_count = 0
                compact_task_history(MAX_TASK_HISTORY_RECORDS)
    except Exception as exc:
        logger.warning(f"task history write failed: {exc}")


def _estimate_video_cost(provider_id: Any, model: Any, raw: Any, duration_hint: Optional[float] = None) -> tuple:
    """Best-effort cost estimate in RMB. Returns (cost, currency, source)."""
    pid = str(provider_id or "").lower()
    model_l = str(model or "").lower()
    raw_dict = raw if isinstance(raw, dict) else {}
    usage = raw_dict.get("usage") if isinstance(raw_dict.get("usage"), dict) else {}
    data = raw_dict.get("data") if isinstance(raw_dict.get("data"), dict) else {}
    data_usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}

    if pid == "runninghub":
        for container in (usage, data_usage, data, raw_dict):
            for key in ("thirdPartyConsumeMoney", "thirdpartyconsumemoney", "consumeMoney", "consumemoney", "consume", "cost"):
                val = container.get(key)
                if val is not None:
                    try:
                        num = float(val)
                        if num >= 0:
                            return round(num, 3), "CNY", "runninghub-usage"
                    except Exception:
                        pass
        return None, None, None

    if pid == "dashscope":
        seconds = None
        for key in ("duration", "video_duration", "output_seconds"):
            v = usage.get(key) or data.get(key)
            if v:
                try:
                    seconds = float(v)
                    break
                except Exception:
                    pass
        if not seconds and duration_hint:
            try:
                seconds = float(duration_hint)
            except Exception:
                seconds = None
        table = None
        for key, price in DASHSCOPE_VIDEO_PRICE_PER_SEC.items():
            if model_l.startswith(key):
                table = price
                break
        if not table and (
            model_l.startswith("wan2.6")
            or model_l.startswith("wan2.5")
            or model_l.startswith("wan2.2")
        ):
            table = DASHSCOPE_VIDEO_PRICE_PER_SEC.get("wan3.0-video")
        if seconds and table:
            resolution = str((raw_dict or {}).get("parameters", {}).get("resolution") or data.get("resolution") or "1080P").upper()
            rate = table.get(resolution) or table.get("720P") or 0.9
            return round(seconds * rate, 3), "CNY", "dashscope-price-table"
        return None, None, None

    return None, None, None


def record_task_event(
    provider_id: Any,
    model: Any,
    status: str,
    task_id: str = "",
    duration_ms: int = 0,
    outputs: Optional[List[str]] = None,
    error: str = "",
    raw: Any = None,
    kind: str = "video",
    duration_hint: Optional[float] = None,
    prompt: str = "",
) -> Dict[str, Any]:
    """Append a terminal task record. Called from canvas-video / online-image flows."""
    cost, currency, source = _estimate_video_cost(provider_id, model, raw, duration_hint)
    if not prompt and isinstance(raw, dict):
        prompt = str(raw.get("prompt") or (raw.get("parameters") or {}).get("prompt") or "")
    record = {
        "ts": int(time.time() * 1000),
        "kind": kind,
        "provider": provider_id,
        "model": model,
        "status": status,
        "task_id": str(task_id or ""),
        "duration_ms": int(duration_ms or 0),
        "outputs": [str(u) for u in (outputs or [])][:10],
        "error": str(error or "")[:500],
        "cost": cost,
        "currency": currency,
        "cost_source": source,
        "prompt": str(prompt or "").strip(),
    }
    _task_history_append(record)
    return record


# ===== 路由端点 =====

@router.get("/api/task-history")
def api_task_history(limit: int = 200, status: str = "", provider: str = ""):
    """Recent generation tasks, newest first. Optional filters: status, provider."""
    if not os.path.exists(TASK_HISTORY_FILE):
        return {"tasks": [], "total": 0}
    rows = []
    try:
        with TASK_HISTORY_LOCK:
            with open(TASK_HISTORY_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
    except Exception as exc:
        return {"tasks": [], "total": 0, "error": str(exc)}
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if provider:
        rows = [r for r in rows if r.get("provider") == provider]
    rows.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    return {"tasks": rows[: max(1, min(1000, limit))], "total": len(rows)}


@router.get("/api/task-stats")
def api_task_stats(days: int = 7):
    """Aggregate cost & counts by day and by provider for the last N days."""
    if not os.path.exists(TASK_HISTORY_FILE):
        return {"days": [], "providers": [], "total_cost": 0, "currency": "CNY"}
    cutoff = (time.time() - days * 86400) * 1000
    rows = []
    try:
        with TASK_HISTORY_LOCK:
            with open(TASK_HISTORY_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    if (r.get("ts") or 0) >= cutoff:
                        rows.append(r)
    except Exception as exc:
        logger.warning(f"Reading task history for stats failed: {exc}")
        return {"days": [], "providers": [], "total_cost": 0, "currency": "CNY"}

    by_day: Dict[str, Dict[str, Any]] = {}
    by_provider: Dict[str, Dict[str, Any]] = {}
    total_cost = 0.0
    for r in rows:
        day = time.strftime("%Y-%m-%d", time.localtime((r.get("ts") or 0) / 1000))
        d = by_day.setdefault(day, {"date": day, "count": 0, "success": 0, "failed": 0, "cost": 0.0})
        d["count"] += 1
        d["success" if r.get("status") == "success" else "failed"] += 1
        if r.get("cost"):
            d["cost"] += r["cost"]
            total_cost += r["cost"]
        prov_name = r.get("provider") or "?"
        p = by_provider.setdefault(prov_name, {
            "provider": prov_name,
            "count": 0,
            "success": 0,
            "failed": 0,
            "cost": 0.0,
            "latest_ts": 0,
            "latest_duration_ms": 0,
            "latest_model": "",
            "latest_status": "",
            "_durations": [],
        })
        p["count"] += 1
        p["success" if r.get("status") == "success" else "failed"] += 1
        if r.get("cost"):
            p["cost"] += r["cost"]
        ts = r.get("ts") or 0
        dur = r.get("duration_ms") or 0
        if dur > 0:
            p["_durations"].append(dur)
        if ts >= p["latest_ts"]:
            p["latest_ts"] = ts
            p["latest_duration_ms"] = dur
            p["latest_model"] = r.get("model") or ""
            p["latest_status"] = r.get("status") or "success"

    for d in by_day.values():
        d["cost"] = round(d["cost"], 4)
    endpoint_speeds = []
    for p in by_provider.values():
        p["cost"] = round(p["cost"], 4)
        dur_list = p.pop("_durations", [])
        p["avg_duration_ms"] = round(sum(dur_list) / len(dur_list)) if dur_list else (p.get("latest_duration_ms") or 0)
        if p.get("latest_ts"):
            endpoint_speeds.append({
                "provider": p["provider"],
                "model": p.get("latest_model") or "",
                "status": p.get("latest_status") or "success",
                "latest_duration_ms": p.get("latest_duration_ms") or 0,
                "avg_duration_ms": p.get("avg_duration_ms") or 0,
                "latest_ts": p.get("latest_ts") or 0,
                "count": p["count"],
            })

    days_list = sorted(by_day.values(), key=lambda x: x["date"])
    prov_list = sorted(by_provider.values(), key=lambda x: x["count"], reverse=True)
    endpoint_speeds.sort(key=lambda x: x["latest_ts"], reverse=True)
    return {
        "days": days_list,
        "providers": prov_list,
        "endpoint_speeds": endpoint_speeds,
        "total_cost": round(total_cost, 4),
        "currency": "CNY",
    }


@router.get("/api/history")
async def get_history_api(type: Optional[str] = None, limit: Optional[int] = None):
    if _history_manager is None:
        return []
    return _history_manager.list_records(record_type=type, limit=limit)


@router.get("/api/queue_status")
async def get_queue_status(client_id: str):
    if _queue_ref is not None and _queue_lock is not None:
        with _queue_lock:
            total = len(_queue_ref)
            positions = [i + 1 for i, t in enumerate(_queue_ref) if isinstance(t, dict) and t.get("client_id") == client_id]
            position = positions[0] if positions else 0
        return {"total": total, "position": position}
    return {"total": 0, "position": 0}


@router.post("/api/history/delete")
async def delete_history(req: DeleteHistoryRequest):
    if _history_manager is None:
        raise HTTPException(status_code=500, detail="History manager not configured")
    try:
        target_record = _history_manager.delete(req.timestamp)
        if target_record:
            if _output_file_resolver:
                for img_url in target_record.get("images", []):
                    file_path = _output_file_resolver(img_url)
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except Exception as e:
                            logger.warning(f"Failed to delete file {file_path}: {e}")
            return {"success": True}
        else:
            return {"success": False, "message": "Record not found"}
    except Exception as e:
        logger.error(f"Delete history error: {e}")
        return {"success": False, "message": str(e)}


_ALLOWED_WS_ORIGIN_PATTERN = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|::1|\[::1\]|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+)(:\d+)?$",
    re.IGNORECASE,
)


def _ws_origin_allowed(websocket: Any) -> bool:
    headers = getattr(websocket, "headers", {})
    origin = None
    host = ""
    if hasattr(headers, "get"):
        origin = headers.get("origin") or headers.get("Origin")
        host = headers.get("host") or headers.get("Host") or ""
    elif isinstance(headers, dict):
        for k, v in headers.items():
            if k.lower() == "origin":
                origin = v
            elif k.lower() == "host":
                host = v
    if not origin:
        return True

    # Allow local filesystem (Photoshop CEP/UXP plugin, local HTML files) and browser extensions
    clean_origin = str(origin).strip().lower()
    if clean_origin in ("file://", "file:") or clean_origin.startswith(("file://", "chrome-extension://", "moz-extension://")):
        return True

    try:
        parsed = urlparse(origin)
        netloc = (parsed.netloc or parsed.path or "").strip()
        if not netloc:
            return False
        req_host = str(host).strip()
        if req_host:
            req_hostname = req_host.split(":")[0]
            parsed_hostname = (parsed.hostname or "").strip()
            if netloc.lower() == req_host.lower() or (parsed_hostname and parsed_hostname.lower() == req_hostname.lower()):
                return True
        if _ALLOWED_WS_ORIGIN_PATTERN.match(netloc):
            return True
        if parsed.hostname and _ALLOWED_WS_ORIGIN_PATTERN.match(parsed.hostname):
            return True
    except Exception as exc:
        logger.warning(f"Failed to parse WS origin '{origin}': {exc}")
        return False
    return False


@router.websocket("/ws/stats")
async def websocket_endpoint(websocket: WebSocket, client_id: Optional[str] = None):
    configured_token = (os.getenv("IC_ACCESS_TOKEN") or read_api_env_value("IC_ACCESS_TOKEN") or "").strip()
    if configured_token:
        token = (
            websocket.query_params.get("token")
            or websocket.cookies.get("ic_access_token")
            or websocket.headers.get("x-access-token")
        )
        import hmac
        if not token or not hmac.compare_digest(str(token).strip(), configured_token):
            await websocket.close(code=1008)
            return
    if not _ws_origin_allowed(websocket):
        headers = getattr(websocket, "headers", {})
        origin = headers.get("origin") or headers.get("Origin") if hasattr(headers, "get") else None
        logger.warning(f"Rejected WS connection from disallowed origin: {origin}")
        await websocket.close(code=1008)
        return
    if _ws_manager is None:
        await websocket.close()
        return
    if not await _ws_manager.connect(websocket, client_id):
        return

    # Extract and sanitize workstation IP address
    headers = getattr(websocket, "headers", {})
    x_forwarded = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if x_forwarded:
        raw_ip = str(x_forwarded).split(",")[0].strip()
    else:
        raw_ip = getattr(getattr(websocket, "client", None), "host", "") or "127.0.0.1"

    raw_ip = re.sub(r"[^0-9a-zA-Z\.:\-_]", "", raw_ip)[:64]
    if raw_ip in ("::1", "::ffff:127.0.0.1"):
        client_ip = "127.0.0.1"
    else:
        client_ip = raw_ip or "127.0.0.1"

    effective_client_id = client_id or f"client_{id(websocket)}"
    last_cursor_time = 0.0

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            if not data or not data.strip().startswith("{"):
                continue
            try:
                msg = json.loads(data)
                if isinstance(msg, dict) and msg.get("type") == "cursor":
                    now = time.time()
                    if now - last_cursor_time < 0.025:  # Rate limit to ~40 msgs/s
                        continue
                    last_cursor_time = now
                    payload = {
                        "type": "cursor_presence",
                        "clientId": effective_client_id,
                        "ip": client_ip,
                        "x": msg.get("x", 0),
                        "y": msg.get("y", 0),
                        "canvasId": msg.get("canvasId", ""),
                        "timestamp": time.time(),
                    }
                    if hasattr(_ws_manager, "broadcast_cursor"):
                        await _ws_manager.broadcast_cursor(payload, sender_ws=websocket)
            except Exception:
                pass
    except WebSocketDisconnect:
        if hasattr(_ws_manager, "broadcast_cursor"):
            try:
                await _ws_manager.broadcast_cursor({
                    "type": "cursor_leave",
                    "clientId": effective_client_id,
                    "ip": client_ip,
                }, sender_ws=websocket)
            except Exception:
                pass
        await _ws_manager.disconnect(websocket, client_id)
    except Exception as e:
        logger.warning(f"WS Error: {e}")
        if hasattr(_ws_manager, "broadcast_cursor"):
            try:
                await _ws_manager.broadcast_cursor({
                    "type": "cursor_leave",
                    "clientId": effective_client_id,
                    "ip": client_ip,
                }, sender_ws=websocket)
            except Exception:
                pass
        await _ws_manager.disconnect(websocket, client_id)
