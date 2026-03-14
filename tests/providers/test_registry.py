"""Tests for provider registry — structure and lookup correctness."""

import pytest

from velo.providers.registry import PROVIDERS, find_by_model, find_by_name, find_gateway


class TestProviderSpec:
    """Verify structural invariants of the registry."""

    def test_all_have_unique_names(self) -> None:
        names = [s.name for s in PROVIDERS]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_all_have_provider_type(self) -> None:
        valid = {"anthropic", "openai", "mistral", "gemini", "azure", "codex", "cli", "custom"}
        for spec in PROVIDERS:
            assert spec.provider_type in valid, f"{spec.name} has invalid provider_type: {spec.provider_type}"


class TestFindByName:
    def test_anthropic(self) -> None:
        spec = find_by_name("anthropic")
        assert spec is not None
        assert spec.provider_type == "anthropic"

    def test_xai(self) -> None:
        spec = find_by_name("xai")
        assert spec is not None
        assert spec.provider_type == "openai"
        assert spec.default_api_base == "https://api.x.ai/v1"

    def test_mistral(self) -> None:
        spec = find_by_name("mistral")
        assert spec is not None
        assert spec.provider_type == "mistral"

    def test_gemini(self) -> None:
        spec = find_by_name("gemini")
        assert spec is not None
        assert spec.provider_type == "gemini"


class TestMistralRegistry:
    @pytest.mark.parametrize("model", [
        "mistral-large-latest",
        "mistral-small-latest",
        "magistral-small-latest",
        "codestral-latest",
        "devstral-small-2",
        "ministral-3b-latest",
    ])
    def test_model_keyword_matching(self, model: str) -> None:
        spec = find_by_model(model)
        assert spec is not None, f"No provider matched model '{model}'"
        assert spec.name == "mistral"


class TestXAIRegistry:
    @pytest.mark.parametrize("model", ["grok-4", "xai/grok-4-1-fast-reasoning"])
    def test_model_keyword_matching(self, model: str) -> None:
        spec = find_by_model(model)
        assert spec is not None, f"No provider matched model '{model}'"
        assert spec.name == "xai"


class TestFindByModel:
    def test_claude_matches_anthropic(self) -> None:
        spec = find_by_model("claude-sonnet-4-6")
        assert spec is not None
        assert spec.name == "anthropic"

    def test_gpt_matches_openai(self) -> None:
        spec = find_by_model("gpt-5-mini")
        assert spec is not None
        assert spec.name == "openai"

    def test_gemini_matches(self) -> None:
        spec = find_by_model("gemini-2.5-flash")
        assert spec is not None
        assert spec.name == "gemini"

    def test_deepseek_matches(self) -> None:
        spec = find_by_model("deepseek-chat")
        assert spec is not None
        assert spec.name == "deepseek"
        assert spec.default_api_base == "https://api.deepseek.com"

    def test_unknown_model_returns_none(self) -> None:
        assert find_by_model("totally-unknown-model") is None


class TestFindGateway:
    def test_openrouter_by_key_prefix(self) -> None:
        spec = find_gateway(api_key="sk-or-test123")
        assert spec is not None
        assert spec.name == "openrouter"

    def test_custom_by_name(self) -> None:
        spec = find_gateway(provider_name="custom")
        assert spec is not None
        assert spec.provider_type == "custom"

    def test_vllm_by_name(self) -> None:
        spec = find_gateway(provider_name="vllm")
        assert spec is not None
        assert spec.is_local
