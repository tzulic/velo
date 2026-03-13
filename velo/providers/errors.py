"""LLM error classification for retry decisions."""

# Error codes that are safe to retry (transient failures).
RETRYABLE_ERRORS = frozenset({"rate_limit", "server_error", "timeout"})


def classify_error(error_msg: str) -> str:
    """Classify an LLM error string into a canonical error code.

    Args:
        error_msg: The raw error message from the LLM provider.

    Returns:
        str: One of "budget_exceeded", "rate_limit", "timeout",
             "context_overflow", "server_error", "auth_error",
             "bad_request", or "unknown".
    """
    msg = error_msg.lower()

    # Order matters: check specific patterns first.
    # Reason: Budget errors must be caught before rate_limit — "quota" could
    # match either, but "budget_exceeded" is a distinct non-retryable condition.
    if any(k in msg for k in ("budget_exceeded", "monthly budget")):
        return "budget_exceeded"
    if any(k in msg for k in ("rate limit", "429", "too many requests", "quota")):
        return "rate_limit"
    if any(
        k in msg
        for k in (
            "context length",
            "too many tokens",
            "maximum context",
            "context_length_exceeded",
        )
    ):
        return "context_overflow"
    # Reason: Check server errors before timeout — "504 Gateway Timeout"
    # contains "timeout" but is a server error, not a client timeout.
    if any(
        k in msg
        for k in (
            "500",
            "502",
            "503",
            "504",
            "internal server error",
            "overloaded",
            "bad gateway",
        )
    ):
        return "server_error"
    if any(k in msg for k in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(k in msg for k in ("401", "403", "invalid api key", "authentication", "unauthorized")):
        return "auth_error"
    if any(k in msg for k in ("400", "invalid", "malformed")):
        return "bad_request"

    return "unknown"
