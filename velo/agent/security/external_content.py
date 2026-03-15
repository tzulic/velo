"""Boundary marking for untrusted external content.

Wraps web fetches, email, and webhook content with injection-resistant
markers before injecting into LLM context. Detects prompt injection
patterns and logs warnings (defense-in-depth, not denial).
"""

from __future__ import annotations

import secrets

from loguru import logger

from velo.agent.security import THREAT_PATTERNS


def wrap_external_content(content: str) -> str:
    """Wrap untrusted content with boundary markers.

    Args:
        content: Raw external content.

    Returns:
        Content wrapped with unique-ID boundary markers.
    """
    marker_id = secrets.token_hex(8)
    findings = detect_injection_patterns(content)
    if findings:
        logger.warning(
            "security.external_content_suspicious",
            findings=findings,
            content_length=len(content),
        )
    return (
        f'<<<EXTERNAL_UNTRUSTED_CONTENT id="{marker_id}">>>\n'
        f"{content}\n"
        f'<<<END_EXTERNAL_UNTRUSTED_CONTENT id="{marker_id}">>>'
    )


def detect_injection_patterns(content: str) -> list[str]:
    """Detect prompt injection patterns in external content.

    Args:
        content: Text to scan.

    Returns:
        List of threat type strings found.
    """
    found: list[str] = []
    for pattern, threat_type in THREAT_PATTERNS:
        if pattern.search(content):
            found.append(threat_type)
    return found
