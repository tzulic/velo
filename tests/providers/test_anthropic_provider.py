"""Tests for the native Anthropic provider."""

from unittest.mock import patch

import pytest

from velo.providers.anthropic_provider import (
    AnthropicProvider,
    _build_assistant_blocks,
    _merge_consecutive_roles,
)


class TestConvertMessages:
    """Test OpenAI → Anthropic message format conversion."""

    def test_system_extraction(self) -> None:
        """System messages are extracted to separate system blocks."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        system_blocks, converted = AnthropicProvider._convert_messages(messages)

        assert len(system_blocks) == 1
        assert system_blocks[0] == {"type": "text", "text": "You are helpful."}
        assert len(converted) == 1
        assert converted[0]["role"] == "user"

    def test_multiple_system_messages(self) -> None:
        """Multiple system messages are collected."""
        messages = [
            {"role": "system", "content": "Rule 1"},
            {"role": "system", "content": "Rule 2"},
            {"role": "user", "content": "Hi"},
        ]
        system_blocks, _ = AnthropicProvider._convert_messages(messages)
        assert len(system_blocks) == 2

    def test_tool_calls_to_tool_use(self) -> None:
        """Assistant tool_calls are converted to tool_use content blocks."""
        messages = [
            {"role": "user", "content": "Search for X"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"q": "X"}'},
                    }
                ],
            },
        ]
        _, converted = AnthropicProvider._convert_messages(messages)

        assert len(converted) == 2
        assistant = converted[1]
        assert assistant["role"] == "assistant"
        blocks = assistant["content"]
        assert any(b["type"] == "tool_use" and b["name"] == "search" for b in blocks)

    def test_tool_result_becomes_user(self) -> None:
        """Tool results are converted to user messages with tool_result type."""
        messages = [
            {"role": "tool", "tool_call_id": "call_123", "content": "result text"},
        ]
        _, converted = AnthropicProvider._convert_messages(messages)

        assert len(converted) == 1
        msg = converted[0]
        assert msg["role"] == "user"
        assert msg["content"][0]["type"] == "tool_result"
        assert msg["content"][0]["tool_use_id"] == "call_123"

    def test_thinking_blocks_preserved(self) -> None:
        """Thinking blocks from previous turns are preserved."""
        messages = [
            {
                "role": "assistant",
                "content": "Answer",
                "thinking_blocks": [
                    {"type": "thinking", "thinking": "Let me think...", "signature": "sig123"}
                ],
            },
        ]
        _, converted = AnthropicProvider._convert_messages(messages)

        blocks = converted[0]["content"]
        thinking = [b for b in blocks if b["type"] == "thinking"]
        assert len(thinking) == 1
        assert thinking[0]["thinking"] == "Let me think..."


class TestRoleAlternation:
    """Test consecutive same-role message merging."""

    def test_consecutive_user_messages_merged(self) -> None:
        """Two consecutive user messages are merged into one."""
        messages = [
            {"role": "user", "content": "Part 1"},
            {"role": "user", "content": "Part 2"},
        ]
        merged = _merge_consecutive_roles(messages)
        assert len(merged) == 1
        assert isinstance(merged[0]["content"], list)

    def test_alternating_roles_unchanged(self) -> None:
        """Properly alternating roles are not modified."""
        messages = [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A"},
            {"role": "user", "content": "Q2"},
        ]
        merged = _merge_consecutive_roles(messages)
        assert len(merged) == 3

    def test_tool_results_merged_with_user(self) -> None:
        """Tool results (user role) followed by user message are merged."""
        messages = [
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "r"}]},
            {"role": "user", "content": "Follow-up"},
        ]
        merged = _merge_consecutive_roles(messages)
        assert len(merged) == 1


class TestConvertTools:
    """Test OpenAI → Anthropic tool schema conversion."""

    def test_basic_conversion(self) -> None:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                },
            }
        ]
        result = AnthropicProvider._convert_tools(tools)
        assert len(result) == 1
        assert result[0]["name"] == "get_weather"
        assert "input_schema" in result[0]

    def test_skips_nameless_tools(self) -> None:
        tools = [{"type": "function", "function": {"description": "no name"}}]
        result = AnthropicProvider._convert_tools(tools)
        assert len(result) == 0


class TestToolChoiceMapping:
    def test_auto(self) -> None:
        tc, include = AnthropicProvider._map_tool_choice("auto", True)
        assert tc == {"type": "auto"}
        assert include is True

    def test_required(self) -> None:
        tc, include = AnthropicProvider._map_tool_choice("required", True)
        assert tc == {"type": "any"}
        assert include is True

    def test_none(self) -> None:
        tc, include = AnthropicProvider._map_tool_choice("none", True)
        assert tc is None
        assert include is False


class TestThinkingParams:
    def test_no_effort_returns_empty(self) -> None:
        result = AnthropicProvider._build_thinking_params("claude-sonnet-4-6", None)
        assert result == {}

    def test_claude_46_adaptive(self) -> None:
        result = AnthropicProvider._build_thinking_params("claude-sonnet-4-6", "high")
        assert result["thinking"]["type"] == "adaptive"
        assert "output_config" in result

    def test_older_claude_budget(self) -> None:
        result = AnthropicProvider._build_thinking_params("claude-3-5-sonnet", "medium")
        assert result["thinking"]["type"] == "enabled"
        assert result["thinking"]["budget_tokens"] == 8192
        assert result["temperature"] == 1


class TestCacheControl:
    def test_system_block_marked(self) -> None:
        system = [{"type": "text", "text": "Hello"}]
        new_system, _ = AnthropicProvider._apply_cache_control(system, None)
        assert new_system[-1]["cache_control"] == {"type": "ephemeral"}

    def test_last_tool_marked(self) -> None:
        tools = [{"name": "a"}, {"name": "b"}]
        _, new_tools = AnthropicProvider._apply_cache_control([], tools)
        assert new_tools[-1]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in new_tools[0]


class TestStripPrefix:
    def test_strips_anthropic_prefix(self) -> None:
        assert AnthropicProvider._strip_prefix("anthropic/claude-sonnet-4-6") == "claude-sonnet-4-6"

    def test_no_prefix_unchanged(self) -> None:
        assert AnthropicProvider._strip_prefix("claude-sonnet-4-6") == "claude-sonnet-4-6"


class TestOAuthTokenDetection:
    """Test OAuth token detection and beta header configuration."""

    @patch("anthropic.AsyncAnthropic")
    def test_oauth_token_detected(self, _mock_client: object) -> None:
        """OAuth tokens (sk-ant-oat prefix) set _is_oauth = True."""
        provider = AnthropicProvider(api_key="sk-ant-oat01-abc123")
        assert provider._is_oauth is True

    @patch("anthropic.AsyncAnthropic")
    def test_regular_api_key_not_flagged(self, _mock_client: object) -> None:
        """Regular API keys are not flagged as OAuth."""
        provider = AnthropicProvider(api_key="sk-ant-api03-xyz789")
        assert provider._is_oauth is False

    @patch("anthropic.AsyncAnthropic")
    def test_oauth_beta_headers(self, mock_client: object) -> None:
        """OAuth tokens include required beta headers in client construction."""
        AnthropicProvider(api_key="sk-ant-oat01-abc123")
        call_kwargs = mock_client.call_args[1]  # type: ignore[union-attr]
        beta_header = call_kwargs["default_headers"]["anthropic-beta"]
        assert "claude-code-20250219" in beta_header
        assert "oauth-2025-04-20" in beta_header
        assert "interleaved-thinking-2025-05-14" in beta_header

    @patch("anthropic.AsyncAnthropic")
    def test_oauth_uses_auth_token(self, mock_client: object) -> None:
        """OAuth tokens are passed via auth_token, not api_key."""
        AnthropicProvider(api_key="sk-ant-oat01-abc123")
        call_kwargs = mock_client.call_args[1]  # type: ignore[union-attr]
        assert call_kwargs["auth_token"] == "sk-ant-oat01-abc123"
        assert "api_key" not in call_kwargs

    @patch("anthropic.AsyncAnthropic")
    def test_regular_key_uses_api_key(self, mock_client: object) -> None:
        """Regular API keys are passed via api_key, not auth_token."""
        AnthropicProvider(api_key="sk-ant-api03-xyz789")
        call_kwargs = mock_client.call_args[1]  # type: ignore[union-attr]
        assert call_kwargs["api_key"] == "sk-ant-api03-xyz789"
        assert "auth_token" not in call_kwargs


class TestBuildAssistantBlocks:
    def test_text_only(self) -> None:
        msg = {"role": "assistant", "content": "Hello"}
        blocks = _build_assistant_blocks(msg)
        assert len(blocks) == 1
        assert blocks[0] == {"type": "text", "text": "Hello"}

    def test_empty_content_no_blocks(self) -> None:
        msg = {"role": "assistant", "content": None}
        blocks = _build_assistant_blocks(msg)
        assert blocks == []

    def test_tool_call_arguments_parsed(self) -> None:
        """JSON string arguments are parsed to dict."""
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "tc1", "function": {"name": "fn", "arguments": '{"key": "val"}'}}
            ],
        }
        blocks = _build_assistant_blocks(msg)
        tool_block = [b for b in blocks if b["type"] == "tool_use"][0]
        assert tool_block["input"] == {"key": "val"}
