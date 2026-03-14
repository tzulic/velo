"""Tests for agent context compression."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from velo.agent.context_compressor import compress_context
from velo.providers.base import LLMResponse


def _make_msg(role: str, content: str, **kwargs) -> dict:
    """Create a message dict with the given role and content."""
    msg = {"role": role, "content": content}
    msg.update(kwargs)
    return msg


def _pad(text: str, target_chars: int) -> str:
    """Pad text to target_chars so estimate_tokens (chars/4) yields target_chars/4 tokens."""
    if len(text) >= target_chars:
        return text
    return text + "x" * (target_chars - len(text))


def _make_provider(summary_text: str = "Summary of conversation") -> AsyncMock:
    """Create a mock LLMProvider that returns a canned summary."""
    provider = AsyncMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(content=summary_text, finish_reason="stop"),
    )
    return provider


@pytest.mark.asyncio
class TestNoCompressionUnderThreshold:
    """Messages under 50% context window should not trigger compression."""

    async def test_no_compression_under_threshold(self) -> None:
        """Short conversations are returned unchanged with no summary."""
        # 10 messages, each ~25 chars = ~250 chars total = ~62 tokens.
        # context_window = 1000, threshold = 0.50 => budget = 500 tokens.
        messages = [_make_msg("user", f"short message {i}") for i in range(10)]
        provider = _make_provider()

        result, summary, _est = await compress_context(
            messages=messages,
            provider=provider,
            model="test-model",
            context_window=1000,
            threshold=0.50,
        )

        assert result is messages  # Same list object returned.
        assert summary is None
        provider.chat.assert_not_called()


@pytest.mark.asyncio
class TestProtectedMessagesPreserved:
    """Protected head and tail messages must survive compression."""

    async def test_protected_messages_preserved(self) -> None:
        """First 3 and last 4 messages are kept intact after compression."""
        # Build 15 messages, each ~400 chars => ~6000 chars total => ~1500 tokens.
        # context_window = 2000, threshold = 0.50 => budget = 1000 tokens.
        messages = [_make_msg("user", _pad(f"msg-{i}", 400)) for i in range(15)]
        provider = _make_provider("Compressed summary")

        result, summary, _est = await compress_context(
            messages=messages,
            provider=provider,
            model="test-model",
            context_window=2000,
            threshold=0.50,
            protect_first=3,
            protect_last=4,
        )

        assert summary == "Compressed summary"
        # Head messages preserved.
        for i in range(3):
            assert result[i]["content"] == messages[i]["content"]
        # Tail messages preserved (last 4 of original).
        for i in range(1, 5):
            assert result[-i]["content"] == messages[-i]["content"]
        # Summary injected between head and tail.
        assert "[Context Summary]" in result[3]["content"]
        provider.chat.assert_called_once()


@pytest.mark.asyncio
class TestToolPairsNotSplit:
    """Tool call/result pairs must stay together or be removed together."""

    async def test_tool_pairs_not_split(self) -> None:
        """When middle messages are removed, orphaned tool results are dropped."""
        # Build messages: protected head (3) + middle with tool pair + protected tail (4).
        head = [_make_msg("user", _pad("head-msg", 400)) for _ in range(3)]
        # Middle: assistant with tool_call + tool result referencing it.
        tool_call_msg = _make_msg(
            "assistant",
            _pad("calling tool", 400),
            tool_calls=[
                {"id": "call_abc123", "function": {"name": "read_file", "arguments": "{}"}}
            ],
        )
        tool_result_msg = _make_msg(
            "tool",
            _pad("file contents here", 400),
            tool_call_id="call_abc123",
            name="read_file",
        )
        # Extra filler in middle.
        filler = [_make_msg("user", _pad("filler", 400)) for _ in range(3)]
        tail = [_make_msg("user", _pad("tail-msg", 400)) for _ in range(4)]

        messages = head + [tool_call_msg, tool_result_msg] + filler + tail
        provider = _make_provider("Tool pair summary")

        result, summary, _est = await compress_context(
            messages=messages,
            provider=provider,
            model="test-model",
            context_window=2000,
            threshold=0.50,
            protect_first=3,
            protect_last=4,
        )

        assert summary is not None
        # No orphaned tool results: no message should have tool_call_id
        # without a preceding assistant message that has matching tool_calls.
        for msg in result:
            if msg.get("role") == "tool" and msg.get("tool_call_id"):
                # Find a preceding assistant with the matching call ID.
                found = False
                for prev in result:
                    if prev.get("role") == "assistant" and prev.get("tool_calls"):
                        ids = {
                            tc["id"]
                            for tc in prev["tool_calls"]
                            if isinstance(tc, dict) and "id" in tc
                        }
                        if msg["tool_call_id"] in ids:
                            found = True
                            break
                assert found, f"Orphaned tool result: {msg.get('tool_call_id')}"


@pytest.mark.asyncio
class TestSummaryInjectedWithPrefix:
    """Summary message must have the [Context Summary] prefix."""

    async def test_summary_injected_with_prefix(self) -> None:
        """Compressed messages contain a summary with the correct prefix."""
        messages = [_make_msg("user", _pad(f"msg-{i}", 400)) for i in range(12)]
        provider = _make_provider("Actions taken and next steps")

        result, summary, _est = await compress_context(
            messages=messages,
            provider=provider,
            model="test-model",
            context_window=2000,
            threshold=0.50,
            protect_first=3,
            protect_last=4,
        )

        assert summary == "Actions taken and next steps"
        # Find the summary message.
        summary_msgs = [m for m in result if "[Context Summary]" in m.get("content", "")]
        assert len(summary_msgs) == 1
        assert summary_msgs[0]["role"] == "user"
        assert summary_msgs[0]["content"].startswith("[Context Summary] ")


@pytest.mark.asyncio
class TestFallbackOnLlmError:
    """On LLM error, messages should be returned unchanged."""

    async def test_fallback_on_llm_error(self) -> None:
        """If the summarization LLM call fails, original messages are returned."""
        messages = [_make_msg("user", _pad(f"msg-{i}", 400)) for i in range(12)]
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=RuntimeError("API exploded"))

        result, summary, _est = await compress_context(
            messages=messages,
            provider=provider,
            model="test-model",
            context_window=2000,
            threshold=0.50,
        )

        assert result is messages  # Same list object returned.
        assert summary is None

    async def test_fallback_on_empty_response(self) -> None:
        """If the LLM returns empty content, original messages are returned."""
        messages = [_make_msg("user", _pad(f"msg-{i}", 400)) for i in range(12)]
        provider = _make_provider("")  # Empty summary response.
        # Override: LLMResponse with None content.
        provider.chat = AsyncMock(
            return_value=LLMResponse(content=None, finish_reason="stop"),
        )

        result, summary, _est = await compress_context(
            messages=messages,
            provider=provider,
            model="test-model",
            context_window=2000,
            threshold=0.50,
        )

        assert result is messages
        assert summary is None
