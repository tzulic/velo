"""Tests for agent loop retry with exponential backoff."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.base import LLMResponse


def _ok_response(content: str = "Hello") -> LLMResponse:
    return LLMResponse(content=content, finish_reason="stop")


def _error_response(error_code: str, msg: str = "Error") -> LLMResponse:
    return LLMResponse(
        content=f"Error calling LLM: {msg}",
        finish_reason="error",
        error_code=error_code,
    )


@pytest.mark.asyncio
class TestChatWithRetry:
    """Test _chat_with_retry method."""

    async def test_success_no_retry(self, make_loop) -> None:
        """Successful response is returned immediately without retry."""
        loop = make_loop()
        loop.provider.chat = AsyncMock(return_value=_ok_response("All good"))

        result = await loop._chat_with_retry(messages=[], tools=None, model="m")

        assert result.content == "All good"
        assert result.finish_reason == "stop"
        assert loop.provider.chat.call_count == 1

    async def test_non_retryable_returns_immediately(self, make_loop) -> None:
        """Non-retryable errors (auth, bad_request) are returned without retry."""
        loop = make_loop()
        loop.provider.chat = AsyncMock(
            return_value=_error_response("auth_error", "Invalid API key"),
        )

        result = await loop._chat_with_retry(messages=[], tools=None, model="m")

        assert result.finish_reason == "error"
        assert result.error_code == "auth_error"
        assert loop.provider.chat.call_count == 1

    @patch("nanobot.agent.llm_helpers.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryable_error_retries_max_times(self, mock_sleep: AsyncMock, make_loop) -> None:
        """Retryable errors cause up to MAX_RETRIES attempts."""
        from nanobot.agent.llm_helpers import MAX_RETRIES

        loop = make_loop()
        loop.provider.chat = AsyncMock(
            return_value=_error_response("rate_limit", "429 Too Many Requests"),
        )

        result = await loop._chat_with_retry(messages=[], tools=None, model="m")

        assert result.finish_reason == "error"
        assert result.error_code == "rate_limit"
        assert loop.provider.chat.call_count == MAX_RETRIES
        # Sleep called between retries (MAX_RETRIES - 1 times).
        assert mock_sleep.call_count == MAX_RETRIES - 1

    @patch("nanobot.agent.llm_helpers.asyncio.sleep", new_callable=AsyncMock)
    async def test_success_on_second_attempt(self, mock_sleep: AsyncMock, make_loop) -> None:
        """Recovery on second attempt stops retrying."""
        loop = make_loop()
        loop.provider.chat = AsyncMock(
            side_effect=[
                _error_response("server_error", "502 Bad Gateway"),
                _ok_response("Recovered"),
            ],
        )

        result = await loop._chat_with_retry(messages=[], tools=None, model="m")

        assert result.content == "Recovered"
        assert result.finish_reason == "stop"
        assert loop.provider.chat.call_count == 2
        assert mock_sleep.call_count == 1

    @patch("nanobot.agent.llm_helpers.asyncio.sleep", new_callable=AsyncMock)
    async def test_backoff_delay_increases(self, mock_sleep: AsyncMock, make_loop) -> None:
        """Delay increases exponentially between retries."""
        loop = make_loop()
        loop.provider.chat = AsyncMock(
            return_value=_error_response("timeout", "Request timed out"),
        )

        await loop._chat_with_retry(messages=[], tools=None, model="m")

        delays = [call.args[0] for call in mock_sleep.call_args_list]
        # Exponential backoff: base * 2^(attempt-1) * jitter(0.5-1.0)
        # attempt 1: 1.0 * 1 * [0.5, 1.0] = [0.5, 1.0]
        # attempt 2: 1.0 * 2 * [0.5, 1.0] = [1.0, 2.0]
        assert 0.5 <= delays[0] <= 1.0
        assert 1.0 <= delays[1] <= 2.0

    async def test_context_overflow_not_retried(self, make_loop) -> None:
        """Context overflow errors are not retried (handled by PR 2)."""
        loop = make_loop()
        loop.provider.chat = AsyncMock(
            return_value=_error_response("context_overflow", "context_length_exceeded"),
        )

        result = await loop._chat_with_retry(messages=[], tools=None, model="m")

        assert result.error_code == "context_overflow"
        assert loop.provider.chat.call_count == 1
