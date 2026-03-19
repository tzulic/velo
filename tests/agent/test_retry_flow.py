"""Tests for user-facing error messages."""

import pytest

from velo.agent.loop import _user_error_message


class TestUserFacingErrorMessages:
    """Verify that classified error codes map to helpful, natural-language messages."""

    def test_rate_limit_message(self) -> None:
        msg = _user_error_message("rate_limit")
        assert "try again" in msg.lower() or "moment" in msg.lower()

    def test_auth_error_message(self) -> None:
        msg = _user_error_message("auth_error")
        assert "authentication" in msg.lower() or "check" in msg.lower()

    def test_budget_exceeded_message(self) -> None:
        msg = _user_error_message("budget_exceeded")
        assert "limit" in msg.lower()

    def test_unknown_error_fallback(self) -> None:
        msg = _user_error_message("unknown")
        assert len(msg) > 10

    def test_context_overflow_message(self) -> None:
        msg = _user_error_message("context_overflow")
        assert "conversation" in msg.lower() or "compress" in msg.lower()

    def test_server_error_message(self) -> None:
        msg = _user_error_message("server_error")
        assert "temporary" in msg.lower() or "retry" in msg.lower()

    def test_timeout_message(self) -> None:
        msg = _user_error_message("timeout")
        assert "took too long" in msg.lower() or "try again" in msg.lower()

    def test_bad_request_message(self) -> None:
        msg = _user_error_message("bad_request")
        assert "rephrasing" in msg.lower() or "wrong" in msg.lower()

    def test_completely_unknown_code_returns_generic(self) -> None:
        """An unmapped code should still produce a reasonable fallback."""
        msg = _user_error_message("never_seen_before_xyz")
        assert "sorry" in msg.lower()
        assert "try again" in msg.lower()
