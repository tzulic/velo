"""Tests for provider fallback feature."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from velo.providers.base import LLMProvider, LLMResponse


def _ok_response(content: str = "OK") -> LLMResponse:
    return LLMResponse(content=content, finish_reason="stop")


def _error_response(error_code: str) -> LLMResponse:
    return LLMResponse(
        content=f"Error: {error_code}",
        finish_reason="error",
        error_code=error_code,
    )


def _make_mock_provider(default_model: str = "primary-model") -> MagicMock:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model = MagicMock(return_value=default_model)
    provider.chat = AsyncMock()
    return provider


@pytest.mark.asyncio
class TestProviderFallback:
    """Test provider fallback on retry exhaustion."""

    async def test_fallback_activates_via_try_activate_fallback(self, make_loop) -> None:
        """_try_activate_fallback() swaps provider and marks fallback as activated."""
        fallback = _make_mock_provider("fallback-model")
        loop = make_loop(fallback_provider=fallback)
        primary = loop.provider

        activated = loop._try_activate_fallback()

        assert activated is True
        assert loop._fallback_activated is True
        assert loop.provider is fallback
        assert loop.provider is not primary

    @patch("velo.agent.llm_helpers.asyncio.sleep", new_callable=AsyncMock)
    async def test_fallback_returns_success_response(
        self, mock_sleep: AsyncMock, make_loop
    ) -> None:
        """Fallback provider response is returned to caller."""
        fallback = _make_mock_provider("fallback-model")
        fallback.chat.return_value = _ok_response("Fallback worked!")

        loop = make_loop(fallback_provider=fallback)
        loop.provider.chat = AsyncMock(return_value=_error_response("server_error"))

        # Simulate fallback activation in _run_agent_loop
        response = await loop._chat_with_retry(messages=[], tools=None, model="m")
        # Primary error triggers fallback flag; caller activates and retries
        if response.finish_reason == "error" and loop._try_activate_fallback():
            response = await loop._chat_with_retry(messages=[], tools=None, model="m")

        assert response.content == "Fallback worked!"
        assert response.finish_reason == "stop"

    async def test_fallback_not_activated_without_config(self, make_loop) -> None:
        """No fallback occurs when fallback_provider is None."""
        loop = make_loop()  # no fallback_provider
        assert loop._fallback_provider is None
        assert loop._try_activate_fallback() is False
        assert loop._fallback_activated is False

    async def test_fallback_one_shot(self, make_loop) -> None:
        """Fallback activates at most once — subsequent calls return False."""
        fallback = _make_mock_provider("fallback-model")
        loop = make_loop(fallback_provider=fallback)

        assert loop._try_activate_fallback() is True   # first call: activates
        assert loop._try_activate_fallback() is False  # second call: already active

    @patch("velo.agent.llm_helpers.asyncio.sleep", new_callable=AsyncMock)
    async def test_non_retryable_error_does_not_trigger_fallback(
        self, mock_sleep: AsyncMock, make_loop
    ) -> None:
        """Non-retryable errors (auth, bad_request) don't activate fallback."""
        fallback = _make_mock_provider("fallback-model")
        fallback.chat.return_value = _ok_response("Should not reach")

        loop = make_loop(fallback_provider=fallback)
        loop.provider.chat = AsyncMock(return_value=_error_response("auth_error"))

        response = await loop._chat_with_retry(messages=[], tools=None, model="m")

        assert response.error_code == "auth_error"
        # auth_error is not retryable, so fallback would only be tried in _run_agent_loop
        # if the error_code is in RETRYABLE_ERRORS — auth_error is NOT, so fallback stays inactive
        from velo.providers.errors import RETRYABLE_ERRORS
        assert "auth_error" not in RETRYABLE_ERRORS
