"""Shared credential detection patterns for sanitizer and log scrubber.

Used by sanitize.py (tool output) and log_scrubber.py (structlog processor).
Patterns are tuned for the secrets that exist on Velo containers: channel
tokens (Telegram, Slack, Discord), integration credentials, and common
API key formats.
"""

from __future__ import annotations

import re

# Credential patterns ordered from most specific to most general.
# Specific patterns (Telegram bot token format) have fewer false positives
# than generic ones (key=...), so they run first.
CREDENTIAL_PATTERNS: list[re.Pattern[str]] = [
    # Telegram bot token: bot<digits>:<35 alphanumeric chars>
    re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{35,}"),
    # Slack bot token
    re.compile(r"xoxb-[A-Za-z0-9-]{20,}"),
    # Slack app token
    re.compile(r"xapp-[A-Za-z0-9-]{20,}"),
    # GitHub PAT
    re.compile(r"ghp_[A-Za-z0-9_]{36,}"),
    # Anthropic key
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    # OpenAI-style key (sk-proj-..., sk-...)
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    # Bearer token (20+ chars after Bearer)
    re.compile(r"Bearer\s+\S{20,}"),
    # Generic key/token/password/secret assignments with long values
    re.compile(r"(?:password|secret)=[^\s&,;\"']{8,}"),
    re.compile(r"(?:token|key)=[^\s&,;\"']{20,}"),
]

# Regex to detect fenced code blocks (triple backticks)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)

_REDACTED = "[REDACTED]"


def redact_credentials(text: str) -> str:
    """Redact credential-shaped patterns from text.

    Skips content inside triple-backtick code blocks to reduce false positives
    on documentation and example output.

    Args:
        text: Raw text that may contain credentials.

    Returns:
        Text with credentials replaced by [REDACTED].
    """
    if not text or len(text) < 8:
        return text

    # Extract code blocks, replace with placeholders, redact the rest,
    # then restore code blocks.
    placeholders: list[str] = []

    def _save_block(m: re.Match[str]) -> str:
        placeholders.append(m.group(0))
        return f"\x00CODEBLOCK{len(placeholders) - 1}\x00"

    protected = _CODE_BLOCK_RE.sub(_save_block, text)

    for pattern in CREDENTIAL_PATTERNS:
        protected = pattern.sub(_REDACTED, protected)

    # Restore code blocks
    for i, block in enumerate(placeholders):
        protected = protected.replace(f"\x00CODEBLOCK{i}\x00", block)

    return protected
