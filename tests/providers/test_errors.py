"""Tests for LLM error classification."""

import pytest

from velo.providers.errors import RETRYABLE_ERRORS, classify_error


class TestClassifyError:
    """Test classify_error() categorizes error messages correctly."""

    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("Rate limit exceeded", "rate_limit"),
            ("Error code: 429", "rate_limit"),
            ("Too many requests, please slow down", "rate_limit"),
            ("You have exceeded your quota", "rate_limit"),
        ],
    )
    def test_rate_limit(self, msg: str, expected: str) -> None:
        """Rate limit patterns are classified correctly."""
        assert classify_error(msg) == expected

    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("Request timeout after 30s", "timeout"),
            ("Connection timed out", "timeout"),
            ("Deadline exceeded for operation", "timeout"),
        ],
    )
    def test_timeout(self, msg: str, expected: str) -> None:
        """Timeout patterns are classified correctly."""
        assert classify_error(msg) == expected

    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("This model's maximum context length is 128000", "context_overflow"),
            ("Too many tokens: 150000 > 128000", "context_overflow"),
            ("context_length_exceeded", "context_overflow"),
            ("Maximum context window exceeded", "context_overflow"),
        ],
    )
    def test_context_overflow(self, msg: str, expected: str) -> None:
        """Context overflow patterns are classified correctly."""
        assert classify_error(msg) == expected

    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("Internal server error", "server_error"),
            ("Error 502 Bad Gateway", "server_error"),
            ("503 Service Unavailable", "server_error"),
            ("504 Gateway Timeout", "server_error"),
            ("The server is overloaded", "server_error"),
            ("500 Internal Server Error", "server_error"),
        ],
    )
    def test_server_error(self, msg: str, expected: str) -> None:
        """Server error patterns are classified correctly."""
        assert classify_error(msg) == expected

    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("401 Unauthorized", "auth_error"),
            ("Invalid API key provided", "auth_error"),
            ("403 Forbidden", "auth_error"),
            ("Authentication failed", "auth_error"),
        ],
    )
    def test_auth_error(self, msg: str, expected: str) -> None:
        """Auth error patterns are classified correctly."""
        assert classify_error(msg) == expected

    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("400 Bad Request", "bad_request"),
            ("Invalid request body", "bad_request"),
            ("Malformed JSON in request", "bad_request"),
        ],
    )
    def test_bad_request(self, msg: str, expected: str) -> None:
        """Bad request patterns are classified correctly."""
        assert classify_error(msg) == expected

    def test_unknown(self) -> None:
        """Unrecognized errors return 'unknown'."""
        assert classify_error("Something completely unexpected happened") == "unknown"

    def test_case_insensitive(self) -> None:
        """Classification is case-insensitive."""
        assert classify_error("RATE LIMIT EXCEEDED") == "rate_limit"
        assert classify_error("Timeout") == "timeout"


class TestRetryableErrors:
    """Test the RETRYABLE_ERRORS set."""

    def test_retryable_contains_expected(self) -> None:
        """RETRYABLE_ERRORS includes transient failure codes."""
        assert "rate_limit" in RETRYABLE_ERRORS
        assert "server_error" in RETRYABLE_ERRORS
        assert "timeout" in RETRYABLE_ERRORS

    def test_non_retryable_excluded(self) -> None:
        """Non-transient errors are not in RETRYABLE_ERRORS."""
        assert "auth_error" not in RETRYABLE_ERRORS
        assert "bad_request" not in RETRYABLE_ERRORS
        assert "context_overflow" not in RETRYABLE_ERRORS
        assert "unknown" not in RETRYABLE_ERRORS
