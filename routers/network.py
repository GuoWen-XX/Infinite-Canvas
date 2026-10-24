# -*- coding: utf-8 -*-
"""Network and ports management router for MeansCanvas.

Provides status monitoring, atomic configuration persistence,
proxy connection testing, and ComfyUI instance probing.
"""
import ipaddress
import os
import socket
import time
import urllib.parse
from typing import List, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.providers import COMFYUI_INSTANCES, update_env_values, read_api_env_value
from core.security import is_cloud_metadata_or_link_local, CLOUD_METADATA_HOSTS
from routers.comfyui import sync_comfy_no_proxy

router = APIRouter(prefix="/api/network/ports", tags=["network"])


class NetworkPortsSavePayload(BaseModel):
    proxy_enabled: bool = True
    proxy_host: str = Field(default="127.0.0.1")
    proxy_port: int = Field(default=7897, ge=1, le=65535)
    comfy_instances: List[str] = Field(default_factory=list)
    server_port: int = Field(default=3333, ge=1, le=65535)


class TestProxyPayload(BaseModel):
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=7897, ge=1, le=65535)


class TestComfyPayload(BaseModel):
    instance: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None


def parse_proxy_url(proxy_url: str) -> Tuple[bool, str, int]:
    text = str(proxy_url or "").strip()
    if not text:
        return False, "127.0.0.1", 7897
    try:
        parsed = urllib.parse.urlsplit(text if "://" in text else f"http://{text}")
        host = (parsed.hostname or "127.0.0.1").strip()
        port = int(parsed.port or 7899)
        return True, host, port
    except Exception:
        return False, "127.0.0.1", 7897


def detect_active_local_port(candidate_ports: Optional[List[int]] = None) -> int:
    ports = candidate_ports or [7897, 7899, 7890]
    for p in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.15)
        try:
            if s.connect_ex(("127.0.0.1", p)) == 0:
                return p
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
    return 0


async def probe_proxy_handshake(host: str, port: int, timeout: float = 3.0) -> Tuple[bool, int, int, str]:
    proxy_url = f"http://{host}:{port}"
    target_url = "https://www.google.com/generate_204"
    start_t = time.perf_counter()
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout, verify=False) as client:
            resp = await client.get(target_url)
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            return True, max(1, elapsed_ms), resp.status_code, ""
    except Exception as e:
        # Fallback to test with api.openai.com
        try:
            async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout, verify=False) as client:
                resp = await client.get("https://api.openai.com/v1/models")
                elapsed_ms = int((time.perf_counter() - start_t) * 1000)
                return True, max(1, elapsed_ms), resp.status_code, ""
        except Exception as e2:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            err_msg = str(e2) or str(e)
            return False, elapsed_ms, 0, err_msg


def _check_host_not_metadata_or_link_local(host_or_url: str) -> bool:
    clean = str(host_or_url or "").strip().lower()
    if not clean:
        return False
    if "://" in clean:
        clean = (urllib.parse.urlsplit(clean).hostname or "").lower().strip()
    elif ":" in clean:
        clean = clean.split(":")[0].strip()
    if not clean or clean in CLOUD_METADATA_HOSTS:
        return False
    try:
        ip = ipaddress.ip_address(clean)
        return not is_cloud_metadata_or_link_local(ip)
    except ValueError:
        pass
    try:
        addr_infos = socket.getaddrinfo(clean, None)
        for info in addr_infos:
            ip_str = info[4][0]
            if is_cloud_metadata_or_link_local(ipaddress.ip_address(ip_str)):
                return False
    except (socket.gaierror, ValueError, IndexError):
        pass
    return True


async def probe_comfy_stats(instance: str, timeout: float = 2.5) -> Tuple[bool, int, str, int, str]:
    text = str(instance or "").strip()
    if not text.startswith("http://") and not text.startswith("https://"):
        text = f"http://{text}"
    try:
        parsed = urllib.parse.urlsplit(text)
        host = (parsed.hostname or "").lower().strip()
        if not host:
            return False, 0, "invalid_host", 0, "缺少有效的主机名"
        if not _check_host_not_metadata_or_link_local(text):
            return False, 0, "forbidden", 0, "禁止访问受限云元数据或链路本地地址"
    except Exception as e:
        return False, 0, "invalid_instance", 0, str(e)

    stats_url = f"{text.rstrip('/')}/system_stats"
    start_t = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(stats_url)
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            if resp.status_code == 200:
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                return True, max(1, elapsed_ms), "ready", 0, ""
            return False, elapsed_ms, f"http_{resp.status_code}", 0, f"HTTP {resp.status_code}"
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start_t) * 1000)
        return False, elapsed_ms, "unreachable", 0, str(e)


@router.get("/status")
def get_network_ports_status():
    raw_proxy = read_api_env_value("HTTP_PROXY") or os.getenv("HTTP_PROXY", "")
    proxy_enabled, proxy_host, proxy_port = parse_proxy_url(raw_proxy)
    detected_port = detect_active_local_port([proxy_port, 7897, 7899, 7890])

    instances = list(COMFYUI_INSTANCES) if COMFYUI_INSTANCES else [s.strip() for s in (read_api_env_value("COMFYUI_INSTANCES") or os.getenv("COMFYUI_INSTANCES", "127.0.0.1:8188")).split(",") if s.strip()]
    if not instances:
        instances = ["127.0.0.1:8188"]

    current_port = int(os.getenv("IC_ACTIVE_PORT") or os.getenv("PORT", "3333"))
    active_host = os.getenv("IC_ACTIVE_HOST") or os.getenv("HOST", "127.0.0.1")
    configured_port_val = read_api_env_value("PORT") or str(current_port)
    try:
        configured_port = int(configured_port_val)
    except Exception:
        configured_port = current_port

    return {
        "proxy": {
            "enabled": proxy_enabled,
            "host": proxy_host,
            "port": proxy_port,
            "url": f"http://{proxy_host}:{proxy_port}" if proxy_enabled else "",
            "detected_active_port": detected_port,
        },
        "comfy": {
            "instances": instances,
            "active_address": instances[0] if instances else "127.0.0.1:8188",
        },
        "server": {
            "current_port": current_port,
            "configured_port": configured_port,
            "is_lan": active_host in ("0.0.0.0", "::"),
        },
    }


@router.post("/save")
def save_network_ports(payload: NetworkPortsSavePayload):
    # Validate proxy port
    if payload.proxy_port < 1 or payload.proxy_port > 65535:
        raise HTTPException(status_code=400, detail="代理端口必须在 1 到 65535 之间")

    # Validate proxy host SSRF
    proxy_h = payload.proxy_host.strip().lower()
    if proxy_h in CLOUD_METADATA_HOSTS:
        raise HTTPException(status_code=400, detail="代理主机地址禁止设置为受限云元数据服务")
    try:
        ip = ipaddress.ip_address(proxy_h)
        if is_cloud_metadata_or_link_local(ip):
            raise HTTPException(status_code=400, detail="代理主机地址禁止设置为链路本地或云元数据地址")
    except ValueError:
        pass

    # Validate server port
    if payload.server_port < 1 or payload.server_port > 65535:
        raise HTTPException(status_code=400, detail="画布服务端口必须在 1 到 65535 之间")

    # Validate comfy instances
    cleaned_instances = []
    for inst in payload.comfy_instances:
        item = str(inst or "").strip()
        if not item:
            continue
        cleaned = item.replace("http://", "").replace("https://", "").rstrip("/")
        if ":" not in cleaned:
            raise HTTPException(status_code=400, detail=f"ComfyUI 实例格式不合法，须为 host:port 形式：{item}")
        parts = cleaned.split(":")
        host_part = parts[0].strip().lower()
        if host_part in CLOUD_METADATA_HOSTS:
            raise HTTPException(status_code=400, detail=f"禁止添加受限云元数据地址：{item}")
        try:
            ip = ipaddress.ip_address(host_part)
            if is_cloud_metadata_or_link_local(ip):
                raise HTTPException(status_code=400, detail=f"禁止添加受限云元数据或链路本地地址：{item}")
        except ValueError:
            pass
        try:
            port_num = int(parts[-1])
            if port_num < 1 or port_num > 65535:
                raise ValueError()
        except ValueError:
            raise HTTPException(status_code=400, detail=f"ComfyUI 实例端口不合法：{item}")
        cleaned_instances.append(cleaned)

    if not cleaned_instances:
        cleaned_instances = ["127.0.0.1:8188"]

    proxy_url = f"http://{payload.proxy_host.strip()}:{payload.proxy_port}" if payload.proxy_enabled else ""
    updates = {
        "HTTP_PROXY": proxy_url,
        "HTTPS_PROXY": proxy_url,
        "ALL_PROXY": proxy_url,
        "COMFYUI_INSTANCES": ",".join(cleaned_instances),
        "PORT": str(payload.server_port),
    }

    try:
        update_env_values(updates)
        COMFYUI_INSTANCES[:] = cleaned_instances
        try:
            sync_comfy_no_proxy(cleaned_instances)
        except Exception:
            pass
        if payload.proxy_enabled and proxy_url:
            os.environ["http_proxy"] = proxy_url
            os.environ["https_proxy"] = proxy_url
            os.environ["all_proxy"] = proxy_url
        else:
            os.environ.pop("http_proxy", None)
            os.environ.pop("https_proxy", None)
            os.environ.pop("all_proxy", None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入环境配置文件失败: {e}")

    return {
        "ok": True,
        "message": "网络与端口配置已保存并热生效",
        "updates": updates,
    }


@router.post("/test-proxy")
async def test_proxy_connection(payload: TestProxyPayload):
    if payload.port < 1 or payload.port > 65535:
        raise HTTPException(status_code=400, detail="待测试的代理端口不合法")
    clean_host = str(payload.host or "").strip().lower()
    if not _check_host_not_metadata_or_link_local(clean_host):
        raise HTTPException(status_code=400, detail="禁止将代理测试地址指向受限云元数据或链路本地地址")
    ok, latency_ms, status_code, err = await probe_proxy_handshake(payload.host, payload.port)
    return {
        "ok": ok,
        "latency_ms": latency_ms,
        "status_code": status_code,
        "error": err,
        "message": f"连通正常 ({latency_ms}ms)" if ok else f"连接失败: {err or '握手超时'}",
    }


@router.post("/test-comfy")
async def test_comfy_instance(payload: TestComfyPayload):
    instance = str(payload.instance or "").strip()
    if not instance and payload.host:
        instance = f"{payload.host}:{payload.port or 8188}"
    if not instance:
        raise HTTPException(status_code=400, detail="ComfyUI 实例地址不可为空")
    ok, latency_ms, status, queue_remaining, err = await probe_comfy_stats(instance)
    return {
        "ok": ok,
        "latency_ms": latency_ms,
        "status": status,
        "queue_remaining": queue_remaining,
        "error": err,
        "message": "实例在线就绪" if ok else f"无法连接: {err or '服务未启动'}",
    }
