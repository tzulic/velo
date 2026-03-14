"""Tests for the native Google Gemini provider."""

import pytest

from velo.providers.gemini_provider import GeminiProvider, _synthetic_tool_id


class TestSyntheticToolId:
    """Test deterministic tool_call_id generation for Gemini."""

    def test_deterministic(self) -> None:
        """Same name+args always produce the same ID."""
        id1 = _synthetic_tool_id("search", {"q": "test"})
        id2 = _synthetic_tool_id("search", {"q": "test"})
        assert id1 == id2

    def test_different_args_different_id(self) -> None:
        id1 = _synthetic_tool_id("search", {"q": "foo"})
        id2 = _synthetic_tool_id("search", {"q": "bar"})
        assert id1 != id2

    def test_length(self) -> None:
        tid = _synthetic_tool_id("fn", {})
        assert len(tid) == 9


class TestStripPrefix:
    def test_strips_gemini_prefix(self) -> None:
        assert GeminiProvider._strip_prefix("gemini/gemini-2.5-flash") == "gemini-2.5-flash"

    def test_no_prefix_unchanged(self) -> None:
        assert GeminiProvider._strip_prefix("gemini-2.5-flash") == "gemini-2.5-flash"


class TestConvertMessages:
    """Test OpenAI → Gemini message format conversion."""

    def test_system_extraction(self) -> None:
        """System messages are extracted as system_instruction."""
        messages = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hello"},
        ]
        system_instruction, contents = GeminiProvider._convert_messages(messages)

        assert system_instruction == "Be helpful."
        assert len(contents) == 1
        assert contents[0].role == "user"

    def test_assistant_role_becomes_model(self) -> None:
        """Assistant messages use role 'model' in Gemini."""
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        _, contents = GeminiProvider._convert_messages(messages)

        assert len(contents) == 2
        assert contents[1].role == "model"

    def test_tool_result_becomes_function_response(self) -> None:
        """Tool results are converted to function_response parts."""
        messages = [
            {"role": "tool", "name": "search", "content": '{"result": "found"}'},
        ]
        _, contents = GeminiProvider._convert_messages(messages)

        assert len(contents) == 1
        assert contents[0].role == "user"

    def test_role_alternation_merging(self) -> None:
        """Consecutive same-role messages are merged."""
        messages = [
            {"role": "user", "content": "Part 1"},
            {"role": "user", "content": "Part 2"},
        ]
        _, contents = GeminiProvider._convert_messages(messages)

        assert len(contents) == 1
        assert len(contents[0].parts) == 2


class TestConvertTools:
    def test_basic_tool_conversion(self) -> None:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather info",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                },
            }
        ]
        result = GeminiProvider._convert_tools(tools)
        assert result is not None
        assert len(result) == 1  # One Tool object

    def test_no_tools_returns_none(self) -> None:
        result = GeminiProvider._convert_tools([])
        assert result is None


class TestToolChoiceMapping:
    def test_auto(self) -> None:
        config = GeminiProvider._map_tool_choice("auto")
        assert config is not None

    def test_required(self) -> None:
        config = GeminiProvider._map_tool_choice("required")
        assert config is not None

    def test_none(self) -> None:
        config = GeminiProvider._map_tool_choice("none")
        assert config is not None


class TestGetDefaultModel:
    def test_returns_configured_default(self) -> None:
        provider = GeminiProvider(api_key="test-key", default_model="gemini-2.5-pro")
        assert provider.get_default_model() == "gemini-2.5-pro"
