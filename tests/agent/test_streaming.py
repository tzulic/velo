"""Tests for streaming integration in the agent loop."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from velo.providers.base import LLMResponse, StreamChunk


async def _fake_stream(*chunks: StreamChunk):
    """Create an async iterator from a list of StreamChunk."""
    for chunk in chunks:
        yield chunk


class TestChatStreamToResponse:
    """Test _chat_stream_to_response method."""

    @pytest.mark.asyncio
    async def test_text_chunks_emitted_via_progress(self, make_loop) -> None:
        """Text deltas are buffered and emitted via on_progress."""
        loop = make_loop()
        emitted: list[str] = []

        async def on_progress(text: str, **kwargs: Any) -> None:
            emitted.append(text)

        loop.provider.chat_stream = lambda **kw: _fake_stream(
            StreamChunk(delta="Hello "),
            StreamChunk(delta="world."),  # Ends with period → triggers emit
            StreamChunk(finish_reason="stop"),
        )

        response = await loop._chat_stream_to_response(on_progress, messages=[], tools=None, model="m")

        assert response.content == "Hello world."
        assert response.finish_reason == "stop"
        # Text was emitted (exact buffering depends on boundary detection)
        assert len(emitted) >= 1
        assert "".join(emitted) == "Hello world."

    @pytest.mark.asyncio
    async def test_tool_calls_accumulated(self, make_loop) -> None:
        """Tool calls from the final chunk are included in the response."""
        from velo.providers.base import ToolCallRequest

        loop = make_loop()
        emitted: list[str] = []

        async def on_progress(text: str, **kwargs: Any) -> None:
            emitted.append(text)

        tc = ToolCallRequest(id="tc1", name="read_file", arguments={"path": "/tmp"})
        loop.provider.chat_stream = lambda **kw: _fake_stream(
            StreamChunk(delta="Let me check."),
            StreamChunk(tool_calls=[tc], finish_reason="tool_calls"),
        )

        response = await loop._chat_stream_to_response(on_progress, messages=[], tools=None, model="m")

        assert response.has_tool_calls
        assert response.tool_calls[0].name == "read_file"
        assert response.content == "Let me check."

    @pytest.mark.asyncio
    async def test_empty_stream(self, make_loop) -> None:
        """Empty stream produces response with None content."""
        loop = make_loop()

        async def on_progress(text: str, **kwargs: Any) -> None:
            pass

        loop.provider.chat_stream = lambda **kw: _fake_stream(
            StreamChunk(finish_reason="stop"),
        )

        response = await loop._chat_stream_to_response(on_progress, messages=[], tools=None, model="m")

        assert response.content is None
        assert response.finish_reason == "stop"


class TestRunAgentLoopStreaming:
    """Test streaming integration in _run_agent_loop."""

    @pytest.mark.asyncio
    async def test_streaming_used_when_on_progress_set(self, make_loop) -> None:
        """When on_progress is provided, chat_stream is used."""
        loop = make_loop()
        emitted: list[str] = []

        async def on_progress(text: str, **kwargs: Any) -> None:
            emitted.append(text)

        loop.provider.chat_stream = lambda **kw: _fake_stream(
            StreamChunk(delta="Streaming response."),
            StreamChunk(finish_reason="stop"),
        )

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        final_content, _, _ = await loop._run_agent_loop(messages, on_progress=on_progress)

        assert final_content == "Streaming response."
        assert len(emitted) >= 1

    @pytest.mark.asyncio
    async def test_non_streaming_when_no_progress(self, make_loop) -> None:
        """When on_progress is None, regular chat() is used (via _chat_with_retry)."""
        loop = make_loop()
        loop.provider.chat = AsyncMock(
            return_value=LLMResponse(content="Non-streaming", finish_reason="stop"),
        )

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        final_content, _, _ = await loop._run_agent_loop(messages, on_progress=None)

        assert final_content == "Non-streaming"
        loop.provider.chat.assert_called_once()
