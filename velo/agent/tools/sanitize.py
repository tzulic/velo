"""Tool result sanitization — strips waste before sending to LLM."""

from __future__ import annotations

import json
import re

# Regex: data URIs (data:...;base64,...) — greedy but stops at whitespace/quotes
_DATA_URI_RE = re.compile(r"data:[^;]{1,60};base64,[A-Za-z0-9+/=\s]{200,}", re.ASCII)

# Regex: raw base64 blobs (200+ contiguous base64 chars, not inside a word)
_RAW_B64_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/]{200,}={0,2}(?![A-Za-z0-9])", re.ASCII)

# Minimum unique characters for a blob to be considered real base64 (not repeated text)
_B64_MIN_UNIQUE = 10

# JSON fields commonly carrying error information (checked in order)
_ERROR_FIELDS = ("error", "message", "reason", "stderr", "traceback", "detail")


def _is_likely_base64(blob: str) -> bool:
    """Check if a matched blob is likely real base64 (not just repeated ASCII).

    Args:
        blob: The matched string.

    Returns:
        True if it looks like genuine base64 data.
    """
    # Reason: real base64 has high character diversity; "xxx..." or "aaa..." don't.
    sample = blob[:200]
    return len(set(sample)) >= _B64_MIN_UNIQUE


def sanitize_tool_result(result: str, max_chars: int = 16_000) -> str:
    """Sanitize a tool result string before injecting it into the LLM context.

    Steps:
        1. Strip base64 data URIs and raw base64 blobs.
        2. If still over *max_chars* and the result is JSON, extract error-relevant fields.
        3. Truncate with an indicator showing how much was removed.

    Args:
        result: Raw tool result string.
        max_chars: Maximum allowed characters in the output.

    Returns:
        Sanitized (and possibly truncated) result string.
    """
    if not result:
        return result

    # Reason: both regexes require 200+ char matches, so shorter strings can't contain base64.
    # Skip regex scanning entirely for short results that are also under the limit.
    if len(result) < 200 and len(result) <= max_chars:
        return result

    # Step 1: always strip base64 (it's pure waste for the LLM, even if under limit)
    cleaned = _DATA_URI_RE.sub("[base64 data removed]", result)
    cleaned = _RAW_B64_RE.sub(
        lambda m: "[base64 blob removed]" if _is_likely_base64(m.group(0)) else m.group(0),
        cleaned,
    )

    if len(cleaned) <= max_chars:
        return cleaned

    # Step 2: if JSON, try extracting error fields
    extracted = _try_extract_json_errors(cleaned)
    if extracted is not None and len(extracted) <= max_chars:
        return extracted

    # Step 3: hard truncate with indicator
    original_len = len(cleaned)
    # Reason: reserve space for the indicator suffix
    budget = max_chars - 80
    if budget < 0:
        budget = max_chars
    truncated = cleaned[:budget]
    removed_chars = original_len - len(truncated)
    removed_lines = cleaned[budget:].count("\n")
    return f"{truncated}\n... [truncated — {removed_chars:,} chars, ~{removed_lines} lines removed]"


def _try_extract_json_errors(text: str) -> str | None:
    """Try to parse *text* as JSON and extract error-relevant fields.

    Args:
        text: Potentially JSON-formatted string.

    Returns:
        A compact JSON string with only error fields, or None if not applicable.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    extracted: dict[str, object] = {}
    for field in _ERROR_FIELDS:
        if field in data:
            extracted[field] = data[field]

    if not extracted:
        return None

    return json.dumps(extracted, ensure_ascii=False, indent=2)
