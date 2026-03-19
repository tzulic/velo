"""Tests for auth error messaging with OAuth token detection."""

import pytest
from unittest.mock import patch


def test_base_provider_has_auth_method():
    """Base provider has get_auth_error_message method."""
    from velo.providers.base import LLMProvider
    assert hasattr(LLMProvider, "get_auth_error_message")


def test_anthropic_oauth_message():
    """Anthropic provider detects OAuth token and returns specific message."""
    from velo.providers.anthropic_provider import AnthropicProvider

    with patch.object(AnthropicProvider, "__init__", lambda self, *a, **k: None):
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._is_oauth = True
        msg = provider.get_auth_error_message()
        assert "expired" in msg.lower() or "re-authenticate" in msg.lower()


def test_anthropic_apikey_message():
    """Anthropic provider returns API key message for regular keys."""
    from velo.providers.anthropic_provider import AnthropicProvider

    with patch.object(AnthropicProvider, "__init__", lambda self, *a, **k: None):
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider._is_oauth = False
        msg = provider.get_auth_error_message()
        assert "api key" in msg.lower() or "anthropic" in msg.lower()
