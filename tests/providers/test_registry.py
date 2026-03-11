"""Tests for provider registry — Mistral AI entries."""
import pytest
from velo.providers.registry import find_by_model, find_by_name


class TestMistralRegistry:
    def test_find_by_name(self) -> None:
        spec = find_by_name("mistral")
        assert spec is not None
        assert spec.name == "mistral"
        assert spec.env_key == "MISTRAL_API_KEY"
        assert spec.litellm_prefix == "mistral"

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

    def test_skip_prefixes(self) -> None:
        """Already-prefixed model names must not be double-prefixed."""
        spec = find_by_name("mistral")
        assert spec is not None
        assert "mistral/" in spec.skip_prefixes
        assert "openrouter/" in spec.skip_prefixes
