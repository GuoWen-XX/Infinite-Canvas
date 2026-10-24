import os
from unittest.mock import patch
import pytest

from core.providers import load_env_file


def test_cli_subprocess_env_preserves_7899():
    from routers.integrations import cli_subprocess_env

    with patch.dict(os.environ, {
        "HTTP_PROXY": "http://127.0.0.1:7899",
        "HTTPS_PROXY": "http://127.0.0.1:7899",
        "ALL_PROXY": "http://127.0.0.1:7899",
    }):
        with patch("routers.integrations.read_api_env_value", return_value=""):
            env = cli_subprocess_env()
            assert env["HTTP_PROXY"] == "http://127.0.0.1:7899"
            assert env["HTTPS_PROXY"] == "http://127.0.0.1:7899"
            assert env["ALL_PROXY"] == "http://127.0.0.1:7899"


def test_cli_subprocess_env_preserves_custom_proxy():
    from routers.integrations import cli_subprocess_env

    with patch.dict(os.environ, {
        "HTTP_PROXY": "http://127.0.0.1:8888",
        "HTTPS_PROXY": "http://127.0.0.1:8888",
    }):
        with patch("routers.integrations.read_api_env_value", return_value=""):
            env = cli_subprocess_env()
            assert env["HTTP_PROXY"] == "http://127.0.0.1:8888"
            assert env["HTTPS_PROXY"] == "http://127.0.0.1:8888"


def test_cli_subprocess_env_prioritizes_api_env():
    from routers.integrations import cli_subprocess_env

    def mock_read(key):
        if key == "HTTPS_PROXY":
            return "http://127.0.0.1:7897"
        return ""

    with patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:1080"}):
        with patch("routers.integrations.read_api_env_value", side_effect=mock_read):
            env = cli_subprocess_env()
            assert env["HTTPS_PROXY"] == "http://127.0.0.1:7897"


def test_cli_subprocess_env_clears_proxy_when_explicitly_disabled(tmp_path):
    from routers.integrations import cli_subprocess_env

    env_file = tmp_path / ".env"
    env_file.write_text("HTTP_PROXY=\nHTTPS_PROXY=\nALL_PROXY=\n", encoding="utf-8")
    with patch("core.providers.API_ENV_FILE", str(env_file)):
        with patch.dict(os.environ, {
            "HTTP_PROXY": "http://127.0.0.1:7897",
            "HTTPS_PROXY": "http://127.0.0.1:7897",
            "ALL_PROXY": "http://127.0.0.1:7897",
        }):
            with patch("routers.integrations.read_api_env_value", return_value=""):
                env = cli_subprocess_env()
                assert "HTTP_PROXY" not in env
                assert "HTTPS_PROXY" not in env
                assert "ALL_PROXY" not in env


def test_load_env_file_proxy_override(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("HTTP_PROXY=http://127.0.0.1:7897\nNORMAL_KEY=new_val\n", encoding="utf-8")
    with patch("core.providers.API_ENV_FILE", str(env_file)):
        with patch.dict(os.environ, {
            "HTTP_PROXY": "http://127.0.0.1:7899",
            "NORMAL_KEY": "old_val",
        }):
            load_env_file()
            # Proxy is overridden by API/.env
            assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
            # Normal key preserves setdefault behavior (keeps existing)
            assert os.environ["NORMAL_KEY"] == "old_val"
