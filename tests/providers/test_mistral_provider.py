"""Tests for the native Mistral AI provider."""

import pytest

from velo.providers.mistral_provider import MistralProvider


class TestToolChoiceMapping:
    def test_auto_stays_auto(self) -> None:
        assert MistralProvider._map_tool_choice("auto") == "auto"

    def test_required_becomes_any(self) -> None:
        assert MistralProvider._map_tool_choice("required") == "any"

    def test_none_stays_none(self) -> None:
        assert MistralProvider._map_tool_choice("none") == "none"


class TestStripPrefix:
    def test_strips_mistral_prefix(self) -> None:
        assert (
            MistralProvider._strip_prefix("mistral/mistral-large-latest") == "mistral-large-latest"
        )

    def test_no_prefix_unchanged(self) -> None:
        assert MistralProvider._strip_prefix("mistral-large-latest") == "mistral-large-latest"


class TestNormalizeToolCallId:
    def test_short_alnum_unchanged(self) -> None:
        assert MistralProvider._normalize_tool_call_id("abc123XYZ") == "abc123XYZ"

    def test_long_id_hashed(self) -> None:
        result = MistralProvider._normalize_tool_call_id("call_very_long_id_12345")
        assert len(result) == 9
        assert result.isalnum()

    def test_none_generates_new(self) -> None:
        result = MistralProvider._normalize_tool_call_id(None)
        assert len(result) == 9
        assert result.isalnum()

    def test_consistent_hashing(self) -> None:
        """Same input always produces same output."""
        id1 = MistralProvider._normalize_tool_call_id("call_123456789")
        id2 = MistralProvider._normalize_tool_call_id("call_123456789")
        assert id1 == id2


class TestNormalizeToolIds:
    def test_assistant_and_tool_ids_stay_synced(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_very_long_id", "function": {"name": "fn"}}],
            },
            {"role": "tool", "tool_call_id": "call_very_long_id", "content": "result"},
        ]
        result = MistralProvider._normalize_tool_ids_in_messages(messages)

        assistant_id = result[0]["tool_calls"][0]["id"]
        tool_id = result[1]["tool_call_id"]
        assert assistant_id == tool_id
        assert len(assistant_id) == 9


class TestGetDefaultModel:
    def test_returns_configured_default(self) -> None:
        provider = MistralProvider(api_key="test-key", default_model="mistral-small-latest")
        assert provider.get_default_model() == "mistral-small-latest"
