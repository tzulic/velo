"""Shared security scanning for memory writes and skill content.

Pre-compiled patterns detect prompt injection, exfiltration, and backdoor
attempts before content is persisted to MEMORY.md, USER.md, or SKILL.md.
"""

from __future__ import annotations

import re

# Patterns that guard against prompt injection from external content (web pages,
# files) being written into persistent files loaded every turn.
THREAT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Prompt injection
    (
        re.compile(r"ignore\s+(previous|all|above|prior)\s+instructions", re.IGNORECASE),
        "prompt_injection",
    ),
    (re.compile(r"you\s+are\s+now\s+", re.IGNORECASE), "role_hijack"),
    (re.compile(r"do\s+not\s+tell\s+the\s+user", re.IGNORECASE), "deception_hide"),
    (re.compile(r"system\s+prompt\s+override", re.IGNORECASE), "sys_prompt_override"),
    (
        re.compile(r"disregard\s+(your|all|any)\s+(instructions|rules|guidelines)", re.IGNORECASE),
        "disregard_rules",
    ),
    (
        re.compile(
            r"act\s+as\s+(if|though)\s+you\s+(have\s+no|don't\s+have)\s+(restrictions|limits|rules)",
            re.IGNORECASE,
        ),
        "bypass_restrictions",
    ),
    # Exfiltration
    (
        re.compile(
            r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", re.IGNORECASE
        ),
        "exfil_curl",
    ),
    (
        re.compile(
            r"wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", re.IGNORECASE
        ),
        "exfil_wget",
    ),
    (
        re.compile(
            r"cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)", re.IGNORECASE
        ),
        "read_secrets",
    ),
    # Backdoors
    (re.compile(r"authorized_keys", re.IGNORECASE), "ssh_backdoor"),
    # Skill-specific: code execution in markdown
    (re.compile(r"^#!.*/bin/", re.MULTILINE), "shebang_in_content"),
    (re.compile(r"\beval\s*\(", re.IGNORECASE), "eval_call"),
    (re.compile(r"\bexec\s*\(", re.IGNORECASE), "exec_call"),
]

# Unicode invisible/directional chars used to hide injected instructions.
INVISIBLE_CHARS: set[str] = {
    "\u200b",
    "\u200c",
    "\u200d",
    "\u2060",
    "\ufeff",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
}


def scan_content(content: str) -> str | None:
    """Scan content for prompt injection, exfiltration, or code execution patterns.

    Args:
        content: Text to scan before writing to a persistent file.

    Returns:
        Error string describing the threat if detected, None if safe.
    """
    found = next((c for c in content if c in INVISIBLE_CHARS), None)
    if found:
        return f"security.write_rejected: invisible_char U+{ord(found):04X}"

    for pattern, threat_type in THREAT_PATTERNS:
        if pattern.search(content):
            return f"security.write_rejected: {threat_type}"

    return None
