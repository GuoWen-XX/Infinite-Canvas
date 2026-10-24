"""Unit tests for core/providers.py.

Tests API key masking checks, effective protocol resolution, provider normalization,
model lists, and provider-specific configurations.
"""

import pytest
from fastapi import HTTPException

from core.providers import (
    key_looks_masked,
    effective_protocol,
    normalize_provider,
    provider_protocol,
    normalize_model_protocols,
    normalize_model_name_map,
    normalize_ms_loras,
    mask_secret,
    strip_auth_scheme,
    bearer_auth_value,
    is_jimeng_provider,
    is_gemini_provider,
    is_tudou_provider,
    is_apimart_provider,
    friendly_validation_error,
    provider_key_env,
    runninghub_is_workflow_link_value,
    runninghub_infer_workflow_field_type,
    runninghub_normalize_field,
)


# =========================================================================
# 1. key_looks_masked
# =========================================================================

class TestKeyLooksMasked:
    def test_masked_patterns(self):
        # Unicode bullets
        assert key_looks_masked("sk-•••••••") is True
        assert key_looks_masked("••••••••abcd") is True
        assert key_looks_masked("sk-\u2022\u2022\u2022\u20221234") is True

        # Asterisks
        assert key_looks_masked("sk-****abcd") is True
        assert key_looks_masked("sk-********1234") is True
        assert key_looks_masked("****1234") is True

        # Question marks
        assert key_looks_masked("sk-????????") is True
        assert key_looks_masked("????????abcd") is True

        # Ellipsis variants
        assert key_looks_masked("sk-…abcd") is True
        assert key_looks_masked("sk-...abcd") is True
        assert key_looks_masked("sk-......abcd") is True

    def test_real_valid_keys(self):
        assert key_looks_masked("sk-real-valid-key-123") is False
        assert key_looks_masked("sk-proj-abc123xyz789") is False
        assert key_looks_masked("AIzaSyA1234567890abcdef") is False
        assert key_looks_masked("sk-key.with.periods.123") is False
        assert key_looks_masked("1234567890") is False

    def test_empty_and_none(self):
        assert key_looks_masked("") is False
        assert key_looks_masked(None) is False
        assert key_looks_masked("   ") is False


# =========================================================================
# 2. effective_protocol
# =========================================================================

class TestEffectiveProtocol:
    def test_default_and_none_provider(self):
        assert effective_protocol(None) == "openai"
        assert effective_protocol({}) == "openai"

    def test_standard_protocols(self):
        assert effective_protocol({"protocol": "openai"}) == "openai"
        assert effective_protocol({"protocol": "gemini"}) == "gemini"
        assert effective_protocol({"protocol": "runninghub"}) == "runninghub"
        assert effective_protocol({"protocol": "fal"}) == "fal"
        assert effective_protocol({"protocol": "polling"}) == "polling"

    def test_model_level_protocol_overrides(self):
        provider = {
            "id": "my-provider",
            "protocol": "openai",
            "model_protocols": {
                "gemini-2.5-flash": "gemini",
                "gpt-4o": "openai",
            },
        }
        # Overridden model
        assert effective_protocol(provider, "gemini-2.5-flash") == "gemini"
        assert effective_protocol(provider, "gpt-4o") == "openai"
        # Non-overridden model defaults to provider base protocol
        assert effective_protocol(provider, "claude-3-5-sonnet") == "openai"
        assert effective_protocol(provider, "") == "openai"

    def test_unsupported_model_protocol_override_ignored(self):
        provider = {
            "id": "my-provider",
            "protocol": "openai",
            "model_protocols": {
                "custom-fal": "fal",  # Only openai and gemini are valid per-model overrides
            },
        }
        assert effective_protocol(provider, "custom-fal") == "openai"

    def test_fixed_protocol_providers_ignore_model_overrides(self):
        fixed_ids = ["modelscope", "volcengine", "jimeng", "runninghub"]
        for pid in fixed_ids:
            provider = {
                "id": pid,
                "protocol": pid,
                "model_protocols": {
                    "override-model": "gemini",
                },
            }
            # Must return fixed base protocol, ignoring model override
            assert effective_protocol(provider, "override-model") == pid


# =========================================================================
# 3. normalize_provider
# =========================================================================

class TestNormalizeProvider:
    def test_valid_minimal_provider(self):
        raw = {
            "id": "test-provider",
            "name": "Test Provider",
            "base_url": "https://api.test.com/v1",
        }
        norm = normalize_provider(raw)

        assert norm["id"] == "test-provider"
        assert norm["name"] == "Test Provider"
        assert norm["base_url"] == "https://api.test.com/v1"
        assert norm["protocol"] == "openai"
        assert norm["enabled"] is True
        assert norm["primary"] is False
        assert norm["image_request_mode"] == "openai"
        assert isinstance(norm["image_models"], list)
        assert isinstance(norm["chat_models"], list)
        assert isinstance(norm["video_models"], list)
        assert isinstance(norm["model_names"], dict)
        assert isinstance(norm["model_protocols"], dict)
        assert isinstance(norm["ms_loras"], list)
        assert isinstance(norm["rh_apps"], list)
        assert isinstance(norm["rh_workflows"], list)

    def test_invalid_provider_id(self):
        with pytest.raises(HTTPException) as exc_info:
            normalize_provider({"id": ""})
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException):
            normalize_provider({"id": "a"})  # Too short (< 2)

        with pytest.raises(HTTPException):
            normalize_provider({"id": "invalid id with spaces"})

        with pytest.raises(HTTPException):
            normalize_provider({"id": "toolong" * 10})  # > 40 chars

    def test_invalid_base_url(self):
        with pytest.raises(HTTPException) as exc_info:
            normalize_provider({
                "id": "test-id",
                "base_url": "ftp://not-supported.com",
            })
        assert exc_info.value.status_code == 400

        with pytest.raises(HTTPException):
            normalize_provider({
                "id": "test-id",
                "base_url": "invalid-url",
            })

    def test_protocol_normalization(self):
        # "tudou" is normalized to "openai"
        norm1 = normalize_provider({
            "id": "test-tudou",
            "protocol": "tudou",
        })
        assert norm1["protocol"] == "openai"

        # Unsupported protocol falls back to "openai"
        norm2 = normalize_provider({
            "id": "test-unknown",
            "protocol": "some-unknown-protocol",
        })
        assert norm2["protocol"] == "openai"

        # Supported protocols are preserved
        for proto in ["openai", "apimart", "gemini", "volcengine", "runninghub", "pollinations"]:
            norm = normalize_provider({"id": f"test-{proto}", "protocol": proto})
            assert norm["protocol"] == proto

    def test_volcengine_provider_defaults(self):
        norm = normalize_provider({"id": "volcengine"})
        assert norm["protocol"] == "volcengine"
        assert norm["base_url"].startswith("https://ark.cn-beijing.volces.com")
        assert norm["volcengine_project_name"] == "default"
        assert norm["volcengine_region"] == "cn-beijing"

    def test_jimeng_provider_defaults(self):
        norm = normalize_provider({"id": "jimeng", "base_url": "https://ignored.com"})
        assert norm["protocol"] == "jimeng"
        assert norm["base_url"] == ""

    def test_cli_providers_empty_base_url(self):
        for proto in ("codex", "gemini-cli"):
            norm = normalize_provider({"id": f"test-{proto}", "protocol": proto, "base_url": "https://ignored.com"})
            assert norm["protocol"] == proto
            assert norm["base_url"] == ""

    def test_runninghub_provider_defaults(self):
        norm = normalize_provider({"id": "runninghub"})
        assert norm["protocol"] == "runninghub"
        assert "runninghub.cn" in norm["base_url"]
        assert len(norm["image_models"]) > 0
        assert len(norm["chat_models"]) > 0
        assert len(norm["video_models"]) > 0

    def test_locked_recommended_provider_rules(self):
        # Exellome locked rule
        norm_ex = normalize_provider({
            "id": "exellome",
            "base_url": "https://new.exellome.online",
        })
        assert norm_ex["protocol"] == "apimart"
        assert norm_ex["image_request_mode"] == "openai-video-proxy"
        assert norm_ex["video_models"] == []

        # FHL locked rule
        norm_fhl = normalize_provider({
            "id": "fhl",
            "base_url": "https://www.fhl.mom",
        })
        assert norm_fhl["protocol"] == "openai"
        assert norm_fhl["image_request_mode"] == "openai"
        assert norm_fhl["video_models"] == []

    def test_endpoint_overrides_validation(self):
        # Valid relative and absolute endpoints
        norm = normalize_provider({
            "id": "test-endpoints",
            "image_generation_endpoint": "/v1/images/generations",
            "image_edit_endpoint": "https://custom.api.com/v1/images/edits/",
        })
        assert norm["image_generation_endpoint"] == "/v1/images/generations"
        assert norm["image_edit_endpoint"] == "https://custom.api.com/v1/images/edits"

        # Invalid endpoint (no leading slash)
        with pytest.raises(HTTPException):
            normalize_provider({
                "id": "test-err",
                "image_generation_endpoint": "v1/images/generations",
            })

        # Invalid endpoint (contains space)
        with pytest.raises(HTTPException):
            normalize_provider({
                "id": "test-err",
                "image_edit_endpoint": "/v1/images/ edits",
            })


# =========================================================================
# 4. Helper and utility functions
# =========================================================================

class TestProviderHelpers:
    def test_provider_protocol(self):
        assert provider_protocol(None) == "openai"
        assert provider_protocol({}) == "openai"
        assert provider_protocol({"protocol": "GEMINI"}) == "gemini"

    def test_normalize_model_protocols(self):
        raw = {
            "model-1": "openai",
            "model-2": "GEMINI",
            "model-3": "fal",        # Invalid, not in PER_MODEL_PROTOCOL_OPTIONS
            "": "openai",              # Empty model name
        }
        res = normalize_model_protocols(raw)
        assert res == {"model-1": "openai", "model-2": "gemini"}

    def test_normalize_model_name_map(self):
        raw = {
            "gpt-4o": "  GPT 4o  ",
            "claude-3": "claude-3",     # Same as key, filtered
            "": "Empty",                # Empty key
        }
        res = normalize_model_name_map(raw)
        assert res == {"gpt-4o": "GPT 4o"}

    def test_normalize_ms_loras(self):
        raw = [
            {"id": "lora-1", "target_model": "model-a", "strength": 1.5, "name": "Lora 1"},
            {"id": "lora-2", "target_model": "model-a", "strength": 3.0},   # Clamped to 2.0
            {"id": "lora-1", "target_model": "model-a"},                    # Duplicate (model, id)
            {"id": "", "target_model": "model-a"},                           # Empty id
            "not-a-dict",
        ]
        res = normalize_ms_loras(raw)
        assert len(res) == 2
        assert res[0]["id"] == "lora-1"
        assert res[0]["strength"] == 1.5
        assert res[1]["id"] == "lora-2"
        assert res[1]["strength"] == 2.0

    def test_mask_secret(self):
        assert mask_secret("") == ""
        assert mask_secret(None) == ""
        assert mask_secret("sk-12345678") == "••••••••5678"
        assert mask_secret("ab") == "••••••••ab"

    def test_strip_auth_scheme_and_bearer(self):
        assert strip_auth_scheme("Bearer token123") == "token123"
        assert strip_auth_scheme("bearer token123") == "token123"
        assert strip_auth_scheme("token123") == "token123"
        assert strip_auth_scheme("") == ""

        assert bearer_auth_value("token123") == "Bearer token123"
        assert bearer_auth_value("Bearer token123") == "Bearer token123"
        assert bearer_auth_value("") == ""

    def test_provider_type_identifiers(self):
        assert is_jimeng_provider({"protocol": "jimeng"}) is True
        assert is_jimeng_provider({"id": "jimeng"}) is True
        assert is_jimeng_provider({"id": "openai"}) is False

        assert is_gemini_provider({"protocol": "gemini"}) is True
        assert is_gemini_provider({"protocol": "openai"}) is False

        assert is_tudou_provider({"id": "tudou"}) is True
        assert is_tudou_provider({"base_url": "https://api.ai-tudou.net/v1"}) is True
        assert is_tudou_provider({"id": "other", "base_url": "https://other.com"}) is False

        assert is_apimart_provider({"protocol": "apimart"}) is True
        assert is_apimart_provider({"base_url": "https://api.apimart.ai/v1"}) is True
        assert is_apimart_provider({"protocol": "openai"}) is False

    def test_provider_key_env(self):
        assert provider_key_env("comfly") == "COMFLY_API_KEY"
        assert provider_key_env("modelscope") == "MODELSCOPE_API_KEY"
        assert provider_key_env("runninghub") == "RUNNINGHUB_API_KEY"
        assert provider_key_env("volcengine") == "ARK_API_KEY"
        assert provider_key_env("gemini") == "GEMINI_API_KEY"
        assert provider_key_env("siliconflow-cn") == "SILICONFLOW_CN_API_KEY"
        assert provider_key_env("siliconflow-com") == "SILICONFLOW_COM_API_KEY"
        assert provider_key_env("bfl") == "BFL_API_KEY"
        assert provider_key_env("custom-service") == "API_PROVIDER_CUSTOM_SERVICE_KEY"

    def test_friendly_validation_error(self):
        errors = [
            {"loc": ["body", "prompt"], "type": "value_error.max_length", "ctx": {"limit_value": 20000}},
            {"loc": ["body", "image"], "type": "value_error.min_length"},
        ]
        msg = friendly_validation_error(errors)
        assert "提示词过长" in msg
        assert "参考图片不能为空" in msg

    def test_runninghub_field_and_workflow_helpers(self):
        assert runninghub_is_workflow_link_value(["node-1", 0]) is True
        assert runninghub_is_workflow_link_value(["node-1", "0"]) is False
        assert runninghub_is_workflow_link_value("not-a-list") is False

        assert runninghub_infer_workflow_field_type("image_input", "pic.png") == "IMAGE"
        assert runninghub_infer_workflow_field_type("video_path", "test.mp4") == "VIDEO"
        assert runninghub_infer_workflow_field_type("audio_source", "test.mp3") == "AUDIO"
        assert runninghub_infer_workflow_field_type("flag", "true") == "BOOLEAN"
        assert runninghub_infer_workflow_field_type("steps", "25") == "NUMBER"
        assert runninghub_infer_workflow_field_type("prompt", "a scenic view") == "TEXT"

        field = runninghub_normalize_field({
            "id": "10::seed",
            "nodeId": "10",
            "fieldName": "seed",
            "fieldValue": 12345,
            "fieldType": "NUMBER",
        })
        assert field["id"] == "10::seed"
        assert field["fieldValue"] == "12345"
        assert field["fieldType"] == "NUMBER"
        assert field["enabled"] is True
