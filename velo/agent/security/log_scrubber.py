"""Structlog processor that redacts credentials from log entries.

Add to structlog processor chain to prevent secrets from persisting
in log files on shared multi-tenant infrastructure.
"""

from __future__ import annotations

from typing import Any

from velo.agent.security.patterns import redact_credentials


def scrub_log_event(
    logger: Any, method_name: str | None, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that redacts credential patterns from all string values.

    Args:
        logger: Structlog logger (unused).
        method_name: Log method name (unused).
        event_dict: Log event dictionary.

    Returns:
        Event dict with credentials redacted.
    """
    return _scrub_dict(event_dict)


def _scrub_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Recursively scrub string values in a dict."""
    result: dict[str, Any] = {}
    for key, value in d.items():
        if isinstance(value, str):
            result[key] = redact_credentials(value)
        elif isinstance(value, dict):
            result[key] = _scrub_dict(value)
        elif isinstance(value, list):
            result[key] = [redact_credentials(v) if isinstance(v, str) else v for v in value]
        else:
            result[key] = value
    return result
