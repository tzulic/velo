"""Tests for streaming support in providers."""

from __future__ import annotations

import pytest

from velo.providers.base import LLMProvider, LLMResponse, StreamChunk, ToolCallRequest


class FakeProvider(LLMProvider):
    """Minimal provider for testing the default chat_stream fallback."""

    async def chat(self, messages, tools=None, model=None, max_tokens=4096,
                   temperature=0.7, reasoning_effort=None):
        """Return a canned response."""
        return LLMResponse(
            content="Hello from fake",
            tool_calls=[ToolCallRequest(id="tc1", name="read_file", arguments={"path": "/tmp"})],
            finish_reason="tool_calls",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            reasoning_content="thinking...",
        )

    def get_default_model(self):
        return "fake-model"


class TestStreamChunk:
    """Test StreamChunk dataclass."""

    def test_defaults(self) -> None:
        """Default StreamChunk has empty values."""
        chunk = StreamChunk()
        assert chunk.delta == ""
        assert chunk.tool_calls is None
        assert chunk.finish_reason is None
        assert chunk.usage is None

    def test_with_values(self) -> None:
        """StreamChunk can hold all fields."""
        tc = ToolCallRequest(id="tc1", name="exec", arguments={"cmd": "ls"})
        chunk = StreamChunk(
            delta="Hello",
            tool_calls=[tc],
            finish_reason="stop",
            usage={"total_tokens": 10},
            reasoning_content="thinking",
        )
        assert chunk.delta == "Hello"
        assert chunk.tool_calls == [tc]
        assert chunk.finish_reason == "stop"


class TestDefaultChatStream:
    """Test the default chat_stream fallback on LLMProvider base class."""

    @pytest.mark.asyncio
    async def test_fallback_yields_single_chunk(self) -> None:
        """Default chat_stream calls chat() and yields one chunk."""
        provider = FakeProvider()
        chunks = []
        async for chunk in provider.chat_stream(messages=[]):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].delta == "Hello from fake"
        assert chunks[0].finish_reason == "tool_calls"
        assert chunks[0].tool_calls is not None
        assert len(chunks[0].tool_calls) == 1
        assert chunks[0].tool_calls[0].name == "read_file"
        assert chunks[0].usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        assert chunks[0].reasoning_content == "thinking..."
