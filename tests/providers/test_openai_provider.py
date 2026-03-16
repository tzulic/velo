"""Tests for the native OpenAI-compatible provider."""

from unittest.mock import MagicMock

import pytest

from velo.providers.openai_provider import OpenAIProvider, _BACKEND_DEFAULTS


class TestBackendDefaults:
    """Verify backend URL/header resolution."""

    def test_openai_default_no_base(self) -> None:
        provider = OpenAIProvider(api_key="sk-test", backend="openai")
        assert provider._client.base_url is not None  # SDK default

    def test_deepseek_base_url(self) -> None:
        provider = OpenAIProvider(api_key="sk-test", backend="deepseek")
        assert "deepseek" in str(provider._client.base_url)

    def test_xai_base_url(self) -> None:
        provider = OpenAIProvider(api_key="sk-test", backend="xai")
        assert "x.ai" in str(provider._client.base_url)

    def test_user_api_base_overrides_default(self) -> None:
        provider = OpenAIProvider(
            api_key="sk-test",
            api_base="https://custom.endpoint.com/v1",
            backend="deepseek",
        )
        assert "custom.endpoint.com" in str(provider._client.base_url)

    def test_extra_headers_merged(self) -> None:
        provider = OpenAIProvider(
            api_key="sk-test",
            extra_headers={"X-Custom": "value"},
            backend="openrouter",
        )
        # OpenRouter defaults + custom header should be merged.
        headers = provider._client._custom_headers
        assert headers.get("X-Custom") == "value"

    def test_all_backends_defined(self) -> None:
        expected = {
            "openai",
            "openrouter",
            "deepseek",
            "groq",
            "xai",
            "vllm",
            "aihubmix",
            "siliconflow",
            "volcengine",
            "dashscope",
            "moonshot",
            "minimax",
            "zhipu",
        }
        assert expected == set(_BACKEND_DEFAULTS.keys())


class TestStripPrefix:
    def test_strips_openai_prefix(self) -> None:
        provider = OpenAIProvider(api_key="sk-test", backend="openai")
        assert provider._strip_prefix("openai/gpt-5-mini") == "gpt-5-mini"

    def test_strips_backend_prefix(self) -> None:
        provider = OpenAIProvider(api_key="sk-test", backend="deepseek")
        assert provider._strip_prefix("deepseek/deepseek-chat") == "deepseek-chat"

    def test_no_prefix_unchanged(self) -> None:
        provider = OpenAIProvider(api_key="sk-test", backend="openai")
        assert provider._strip_prefix("gpt-5-mini") == "gpt-5-mini"


class TestReasoningExtraction:
    """Test reasoning content extraction from various providers."""

    def test_deepseek_reasoning_content(self) -> None:
        msg = MagicMock()
        msg.reasoning_content = "Step 1: Think..."
        msg.reasoning = None
        msg.reasoning_details = None
        assert OpenAIProvider._extract_reasoning(msg) == "Step 1: Think..."

    def test_openrouter_reasoning(self) -> None:
        msg = MagicMock()
        msg.reasoning_content = None
        msg.reasoning = "OpenRouter reasoning"
        msg.reasoning_details = None
        assert OpenAIProvider._extract_reasoning(msg) == "OpenRouter reasoning"

    def test_no_reasoning_returns_none(self) -> None:
        msg = MagicMock()
        msg.reasoning_content = None
        msg.reasoning = None
        msg.reasoning_details = None
        assert OpenAIProvider._extract_reasoning(msg) is None


class TestModelOverrides:
    def test_kimi_temperature_override(self) -> None:
        kwargs: dict = {"temperature": 0.5}
        OpenAIProvider._apply_model_overrides("kimi-k2.5-latest", kwargs)
        assert kwargs["temperature"] == 1.0

    def test_no_override_for_unknown(self) -> None:
        kwargs: dict = {"temperature": 0.5}
        OpenAIProvider._apply_model_overrides("gpt-5-mini", kwargs)
        assert kwargs["temperature"] == 0.5


class TestBuildKwargs:
    def test_basic_kwargs(self) -> None:
        provider = OpenAIProvider(api_key="sk-test", backend="openai")
        kwargs = provider._build_kwargs(
            messages=[{"role": "user", "content": "Hi"}],
            tools=None,
            model="gpt-5-mini",
            max_tokens=1024,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice="auto",
        )
        assert kwargs["model"] == "gpt-5-mini"
        assert kwargs["max_tokens"] == 1024
        assert "tools" not in kwargs

    def test_with_tools(self) -> None:
        provider = OpenAIProvider(api_key="sk-test", backend="openai")
        tools = [{"type": "function", "function": {"name": "test", "parameters": {}}}]
        kwargs = provider._build_kwargs(
            messages=[{"role": "user", "content": "Hi"}],
            tools=tools,
            model=None,
            max_tokens=4096,
            temperature=0.7,
            reasoning_effort=None,
            tool_choice="required",
        )
        assert kwargs["tools"] == tools
        assert kwargs["tool_choice"] == "required"

    def test_reasoning_effort_passed(self) -> None:
        provider = OpenAIProvider(api_key="sk-test", backend="openai")
        kwargs = provider._build_kwargs(
            messages=[{"role": "user", "content": "Hi"}],
            tools=None,
            model=None,
            max_tokens=4096,
            temperature=0.7,
            reasoning_effort="medium",
            tool_choice="auto",
        )
        assert kwargs["reasoning_effort"] == "medium"


class TestGetDefaultModel:
    def test_returns_configured_default(self) -> None:
        provider = OpenAIProvider(api_key="sk-test", default_model="gpt-5.4")
        assert provider.get_default_model() == "gpt-5.4"
