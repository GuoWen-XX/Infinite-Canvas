import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_get_network_ports_status():
    with patch("routers.network.read_api_env_value") as mock_read:
        mock_read.side_effect = lambda k: {
            "HTTP_PROXY": "http://127.0.0.1:7897",
            "COMFYUI_INSTANCES": "127.0.0.1:8188,192.0.2.10:8188",
            "PORT": "3333",
        }.get(k, "")
        resp = client.get("/api/network/ports/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "proxy" in data
        assert "comfy" in data
        assert "server" in data
        assert data["proxy"]["port"] == 7897
        assert data["proxy"]["host"] == "127.0.0.1"
        assert data["proxy"]["enabled"] is True
        assert len(data["comfy"]["instances"]) >= 1


def test_save_network_ports_valid():
    with patch("routers.network.update_env_values") as mock_update:
        payload = {
            "proxy_enabled": True,
            "proxy_host": "127.0.0.1",
            "proxy_port": 7897,
            "comfy_instances": ["127.0.0.1:8188", "192.0.2.10:8188"],
            "server_port": 3333,
        }
        resp = client.post("/api/network/ports/save", json=payload)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert mock_update.called
        args = mock_update.call_args[0][0]
        assert args["HTTP_PROXY"] == "http://127.0.0.1:7897"
        assert args["HTTPS_PROXY"] == "http://127.0.0.1:7897"
        assert args["ALL_PROXY"] == "http://127.0.0.1:7897"
        assert "127.0.0.1:8188" in args["COMFYUI_INSTANCES"]


def test_save_network_ports_disabled_proxy():
    with patch("routers.network.update_env_values") as mock_update:
        payload = {
            "proxy_enabled": False,
            "proxy_host": "127.0.0.1",
            "proxy_port": 7897,
            "comfy_instances": ["127.0.0.1:8188"],
            "server_port": 3333,
        }
        resp = client.post("/api/network/ports/save", json=payload)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        args = mock_update.call_args[0][0]
        assert args["HTTP_PROXY"] == ""
        assert args["HTTPS_PROXY"] == ""
        assert args["ALL_PROXY"] == ""


def test_save_network_ports_invalid_port():
    payload = {
        "proxy_enabled": True,
        "proxy_host": "127.0.0.1",
        "proxy_port": 70000,
        "comfy_instances": ["127.0.0.1:8188"],
        "server_port": 3333,
    }
    resp = client.post("/api/network/ports/save", json=payload)
    assert resp.status_code in (400, 422)


def test_save_network_ports_invalid_comfy_instance():
    payload = {
        "proxy_enabled": True,
        "proxy_host": "127.0.0.1",
        "proxy_port": 7897,
        "comfy_instances": ["invalid_instance_without_port"],
        "server_port": 3333,
    }
    resp = client.post("/api/network/ports/save", json=payload)
    assert resp.status_code == 400


def test_probe_proxy_connection():
    with patch("routers.network.probe_proxy_handshake") as mock_probe:
        mock_probe.return_value = (True, 42, 204, "")
        resp = client.post("/api/network/ports/test-proxy", json={"host": "127.0.0.1", "port": 7897})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["latency_ms"] == 42


def test_probe_comfy_instance():
    with patch("routers.network.probe_comfy_stats") as mock_probe:
        mock_probe.return_value = (True, 15, "ready", 0, "")
        resp = client.post("/api/network/ports/test-comfy", json={"instance": "127.0.0.1:8188"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["status"] == "ready"


def test_probe_comfy_instance_host_port():
    with patch("routers.network.probe_comfy_stats") as mock_probe:
        mock_probe.return_value = (True, 20, "ready", 0, "")
        resp = client.post("/api/network/ports/test-comfy", json={"host": "127.0.0.1", "port": 8188})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_probe.assert_called_once_with("127.0.0.1:8188")


def test_ssrf_blocked_metadata_proxy():
    resp = client.post("/api/network/ports/test-proxy", json={"host": "169.254.169.254", "port": 80})
    assert resp.status_code == 400
    assert "受限" in resp.json()["detail"] or "禁止" in resp.json()["detail"]

    resp2 = client.post("/api/network/ports/test-proxy", json={"host": "metadata.google.internal", "port": 80})
    assert resp2.status_code == 400


def test_ssrf_blocked_comfy_instance_save():
    payload = {
        "proxy_enabled": True,
        "proxy_host": "127.0.0.1",
        "proxy_port": 7897,
        "comfy_instances": ["169.254.169.254:8188"],
        "server_port": 3333,
    }
    resp = client.post("/api/network/ports/save", json=payload)
    assert resp.status_code == 400
    assert "受限" in resp.json()["detail"] or "禁止" in resp.json()["detail"]


def test_ssrf_blocked_comfy_probe():
    resp = client.post("/api/network/ports/test-comfy", json={"instance": "169.254.169.254:8188"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "forbidden" in data["status"] or "禁止" in data["message"]


def test_save_network_ports_updates_memory_and_active_port():
    import os
    import core.providers as cp

    orig_instances = list(cp.COMFYUI_INSTANCES)
    try:
        with patch("routers.network.update_env_values"):
            with patch("routers.network.sync_comfy_no_proxy") as mock_sync:
                payload = {
                    "proxy_enabled": False,
                    "proxy_host": "127.0.0.1",
                    "proxy_port": 7897,
                    "comfy_instances": ["192.168.1.50:8188", "127.0.0.1:8188"],
                    "server_port": 4000,
                }
                resp = client.post("/api/network/ports/save", json=payload)
                assert resp.status_code == 200
                r_data = resp.json()
                assert r_data["restart_required"] is True
                assert "重启服务后生效" in r_data["message"]
                assert cp.COMFYUI_INSTANCES == ["192.168.1.50:8188", "127.0.0.1:8188"]
                mock_sync.assert_called_once_with(["192.168.1.50:8188", "127.0.0.1:8188"])

        # Test active port in status
        with patch.dict(os.environ, {"IC_ACTIVE_PORT": "5555", "IC_ACTIVE_HOST": "0.0.0.0"}):
            status_resp = client.get("/api/network/ports/status")
            assert status_resp.status_code == 200
            s_data = status_resp.json()
            assert s_data["server"]["current_port"] == 5555
            assert s_data["server"]["is_lan"] is True
            assert s_data["comfy"]["instances"] == ["192.168.1.50:8188", "127.0.0.1:8188"]
    finally:
        cp.COMFYUI_INSTANCES[:] = orig_instances



