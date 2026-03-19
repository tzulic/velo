"""Tests for context overflow protection in the agent loop."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from velo.agent.llm_helpers import trim_to_budget
from velo.providers.base import LLMResponse


def _make_messages(count: int, chars_per_msg: int = 100) -> list[dict[str, Any]]:
    """Create a list of test messages with a system message and alternating user/assistant."""
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": "System prompt."},
    ]
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"Message {i}: " + "x" * chars_per_msg})
    return msgs


class TestTrimToBudget:
    """Test _trim_to_budget static method."""

    def test_no_trim_when_under_budget(self) -> None:
        """Messages under budget are returned unchanged."""
        msgs = _make_messages(4, chars_per_msg=10)
        result = trim_to_budget(msgs, token_budget=10000)
        assert len(result) == len(msgs)

    def test_system_message_preserved(self) -> None:
        """System message (index 0) is always kept."""
        msgs = _make_messages(20, chars_per_msg=200)
        result = trim_to_budget(msgs, token_budget=200)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "System prompt."

    def test_tail_preserved(self) -> None:
        """Last user message and trailing messages are preserved."""
        msgs = _make_messages(20, chars_per_msg=200)
        # Last user message should be in the result
        last_user_content = None
        for m in reversed(msgs):
            if m["role"] == "user":
                last_user_content = m["content"]
                break
        result = trim_to_budget(msgs, token_budget=200)
        assert any(m["content"] == last_user_content for m in result if m.get("content"))

    def test_middle_messages_removed(self) -> None:
        """Older middle messages are removed first."""
        msgs = _make_messages(10, chars_per_msg=200)
        result = trim_to_budget(msgs, token_budget=300)
        assert len(result) < len(msgs)

    def test_tool_pair_integrity(self) -> None:
        """Removing an assistant+tool_calls also removes orphaned tool results."""
        msgs = [
            {"role": "system", "content": "System."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc_001",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"x"}'},
                    },
                ],
            },
            {"role": "tool", "content": "file contents here " * 50, "tool_call_id": "tc_001"},
            {"role": "user", "content": "Thanks! " + "y" * 500},
        ]
        # Budget so small that the tool pair must be removed
        result = trim_to_budget(msgs, token_budget=150)
        # Neither the assistant+tool_calls nor the orphaned tool result should remain
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 0

    def test_two_messages_not_trimmed(self) -> None:
        """Lists with <= 2 messages are returned as-is."""
        msgs = [
            {"role": "system", "content": "x" * 10000},
            {"role": "user", "content": "y" * 10000},
        ]
        result = trim_to_budget(msgs, token_budget=10)
        assert len(result) == 2


class TestProactiveTrim:
    """Test proactive trimming in _run_agent_loop."""

    @pytest.mark.asyncio
    async def test_proactive_trim_triggers(self, make_loop) -> None:
        """When messages exceed 90% of context window, they are trimmed before LLM call."""
        loop = make_loop(context_window=1000)  # 1000 tokens = 4000 chars
        # Create messages that exceed 90% of 1000 tokens
        big_messages = _make_messages(5, chars_per_msg=900)

        loop.provider.chat = AsyncMock(
            return_value=LLMResponse(content="Done", finish_reason="stop"),
        )

        with patch("velo.agent.loop.trim_to_budget", wraps=trim_to_budget) as mock_trim:
            await loop._run_agent_loop(big_messages)
            mock_trim.assert_called()


class TestReactiveTrim:
    """Test reactive overflow recovery in _run_agent_loop."""

    @pytest.mark.asyncio
    async def test_overflow_error_triggers_trim_and_retry(self, make_loop) -> None:
        """Context overflow error triggers compress + trim + retry."""
        loop = make_loop(context_window=1000)

        overflow_response = LLMResponse(
            content="Error: context_length_exceeded",
            finish_reason="error",
            error_code="context_overflow",
        )
        ok_response = LLMResponse(content="Recovered", finish_reason="stop")

        loop.provider.chat = AsyncMock(side_effect=[overflow_response, ok_response])

        messages = _make_messages(10, chars_per_msg=200)

        # Patch compress_context to pass-through so we test the trim path cleanly.
        async def _passthrough(msgs, *a, **kw):
            return msgs, None, 0

        with patch("velo.agent.loop.compress_context", side_effect=_passthrough):
            final_content, _, _ = await loop._run_agent_loop(messages)

        assert final_content == "Recovered"
        # Called twice: first overflow, then retry after trim
        assert loop.provider.chat.call_count == 2

    @pytest.mark.asyncio
    async def test_overflow_no_trim_possible_returns_error(self, make_loop) -> None:
        """If trimming can't reduce message count, the error is returned."""
        loop = make_loop(context_window=1000)

        overflow_response = LLMResponse(
            content="Error: context_length_exceeded",
            finish_reason="error",
            error_code="context_overflow",
        )

        loop.provider.chat = AsyncMock(return_value=overflow_response)

        # Only 2 messages — can't trim further
        messages = [
            {"role": "system", "content": "x" * 4000},
            {"role": "user", "content": "y" * 4000},
        ]

        # Patch compress_context to pass-through (can't compress 2 msgs either).
        async def _passthrough(msgs, *a, **kw):
            return msgs, None, 0

        with patch("velo.agent.loop.compress_context", side_effect=_passthrough):
            final_content, _, _ = await loop._run_agent_loop(messages)

        # User-facing error message mentions "conversation" and "long"
        assert "conversation" in (final_content or "").lower() or "too long" in (final_content or "").lower()
        # Only called once since neither compress nor trim reduces message count
        assert loop.provider.chat.call_count == 1


class TestCompressBeforeTrim:
    """Compression is attempted before aggressive trimming on overflow."""

    @pytest.mark.asyncio
    async def test_compress_context_signature_correct(self):
        """compress_context accepts model and context_window params."""
        import inspect
        from velo.agent.context_compressor import compress_context
        sig = inspect.signature(compress_context)
        assert "model" in sig.parameters
        assert "context_window" in sig.parameters
        # Returns a 3-tuple (check annotation contains tuple)
        assert "tuple" in str(sig.return_annotation).lower()
