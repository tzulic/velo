"""Tests for model context window limits and token estimation."""

import pytest

from velo.providers.context_limits import (
    _DEFAULT_CONTEXT_WINDOW,
    estimate_tokens,
    get_context_window,
)


class TestGetContextWindow:
    """Test get_context_window() lookup."""

    @pytest.mark.parametrize("model,expected", [
        ("anthropic/claude-opus-4-5", 200_000),
        ("claude-sonnet-4-5", 200_000),
        ("gpt-5-turbo", 400_000),
        ("gpt-4o", 128_000),
        ("gpt-4.1-mini", 1_000_000),
        ("gemini-2.5-pro", 1_000_000),
        ("deepseek-v3", 128_000),
        ("qwen-3.5", 262_000),
        ("kimi-k2.5", 1_000_000),
        ("llama-4-scout-17b", 10_000_000),
        ("llama-4-maverick", 1_000_000),
        ("llama-3.1-70b", 128_000),
        ("grok-4.1", 2_000_000),
        ("grok-4", 256_000),
    ])
    def test_known_models(self, model: str, expected: int) -> None:
        """Known model patterns return correct context window."""
        assert get_context_window(model) == expected

    def test_unknown_model_returns_default(self) -> None:
        """Unknown models fall back to the default context window."""
        assert get_context_window("totally-unknown-model") == _DEFAULT_CONTEXT_WINDOW

    def test_override_takes_precedence(self) -> None:
        """User-provided override wins over pattern matching."""
        assert get_context_window("claude-opus-4-5", override=50_000) == 50_000

    def test_case_insensitive(self) -> None:
        """Lookup is case-insensitive."""
        assert get_context_window("CLAUDE-OPUS-4-5") == 200_000


class TestEstimateTokens:
    """Test estimate_tokens() heuristic."""

    def test_empty_messages(self) -> None:
        """Empty message list returns 0."""
        assert estimate_tokens([]) == 0

    def test_simple_text(self) -> None:
        """chars/4 heuristic for simple text messages."""
        messages = [{"role": "user", "content": "a" * 400}]
        assert estimate_tokens(messages) == 100

    def test_list_content(self) -> None:
        """Handles list-style content (multimodal messages)."""
        messages = [{"role": "user", "content": [
            {"type": "text", "text": "Hello world"},
        ]}]
        result = estimate_tokens(messages)
        assert result > 0

    def test_tool_calls_counted(self) -> None:
        """Tool call arguments are included in estimate."""
        messages = [{
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "read_file", "arguments": '{"path": "/etc/hosts"}'}},
            ],
        }]
        result = estimate_tokens(messages)
        assert result > 0

    def test_mixed_messages(self) -> None:
        """Handles a realistic mix of message types."""
        messages = [
            {"role": "system", "content": "You are an assistant."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "Do something"},
        ]
        result = estimate_tokens(messages)
        # Total chars ~60, so ~15 tokens
        assert 10 <= result <= 20
