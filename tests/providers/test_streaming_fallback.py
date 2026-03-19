"""Tests for within-provider streaming fallback to non-streaming."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from velo.providers.base import LLMResponse, StreamChunk


@pytest.mark.asyncio
async def test_anthropic_stream_fallback_to_chat():
    """When streaming fails, Anthropic provider falls back to chat()."""
    from velo.providers.anthropic_provider import AnthropicProvider

    with patch.object(AnthropicProvider, "__init__", lambda self, *a, **k: None):
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._default_model = "claude-sonnet-4-6"
        provider._is_oauth = False
        provider._client = MagicMock()

        # Make streaming raise, but chat succeed
        mock_response = LLMResponse(content="fallback worked", finish_reason="stop")
        provider.chat = AsyncMock(return_value=mock_response)

        # Simulate stream context manager that raises
        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(side_effect=Exception("stream failed"))
        provider._client.messages.stream = MagicMock(return_value=mock_stream_ctx)

        chunks = []
        async for chunk in provider.chat_stream(messages=[{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].delta == "fallback worked"
        assert chunks[0].finish_reason == "stop"
        provider.chat.assert_called_once()


@pytest.mark.asyncio
async def test_anthropic_stream_both_fail():
    """When both streaming and fallback chat fail, yield error chunk."""
    from velo.providers.anthropic_provider import AnthropicProvider

    with patch.object(AnthropicProvider, "__init__", lambda self, *a, **k: None):
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._default_model = "claude-sonnet-4-6"
        provider._is_oauth = False
        provider._client = MagicMock()

        # Make both streaming AND chat fail
        provider.chat = AsyncMock(side_effect=Exception("chat also failed"))

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(side_effect=Exception("stream failed"))
        provider._client.messages.stream = MagicMock(return_value=mock_stream_ctx)

        chunks = []
        async for chunk in provider.chat_stream(messages=[{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].finish_reason == "error"


@pytest.mark.asyncio
async def test_openai_stream_fallback_to_chat():
    """When streaming fails, OpenAI provider falls back to chat()."""
    from velo.providers.openai_provider import OpenAIProvider

    with patch.object(OpenAIProvider, "__init__", lambda self, *a, **k: None):
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._default_model = "gpt-5-mini"
        provider._backend = "openai"
        provider._client = MagicMock()

        # Make streaming raise, but chat succeed
        mock_response = LLMResponse(content="openai fallback", finish_reason="stop")
        provider.chat = AsyncMock(return_value=mock_response)

        # Simulate create() raising
        provider._client.chat.completions.create = AsyncMock(
            side_effect=Exception("stream failed")
        )

        chunks = []
        async for chunk in provider.chat_stream(messages=[{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].delta == "openai fallback"
        assert chunks[0].finish_reason == "stop"
        provider.chat.assert_called_once()


@pytest.mark.asyncio
async def test_openai_stream_both_fail():
    """When both streaming and fallback chat fail, yield error chunk."""
    from velo.providers.openai_provider import OpenAIProvider

    with patch.object(OpenAIProvider, "__init__", lambda self, *a, **k: None):
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._default_model = "gpt-5-mini"
        provider._backend = "openai"
        provider._client = MagicMock()

        # Make both streaming AND chat fail
        provider.chat = AsyncMock(side_effect=Exception("chat also failed"))
        provider._client.chat.completions.create = AsyncMock(
            side_effect=Exception("stream failed")
        )

        chunks = []
        async for chunk in provider.chat_stream(messages=[{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0].finish_reason == "error"
