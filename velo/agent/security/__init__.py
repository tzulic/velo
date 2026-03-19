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
    # Destructive filesystem operations
    (re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+/", re.IGNORECASE), "destructive_fs"),
    (re.compile(r"\bmkfs\b", re.IGNORECASE), "destructive_fs"),
    (re.compile(r"\bdd\s+if=", re.IGNORECASE), "destructive_fs"),
    # Process manipulation
    (re.compile(r"\b(kill|pkill|killall)\s+(-\d+\s+)?\d+", re.IGNORECASE), "process_kill"),
    (re.compile(r"\bpkill\s+-f\s+", re.IGNORECASE), "process_kill"),
    # Network reconnaissance
    (re.compile(r"\bnmap\b", re.IGNORECASE), "network_recon"),
    (re.compile(r"\bnc\s+-(l|e)", re.IGNORECASE), "network_recon"),
    # Privilege escalation
    (re.compile(r"\bchmod\s+[0-7]*7[0-7]*\s+/", re.IGNORECASE), "priv_escalation"),
    (re.compile(r"\bchmod\s+u\+s\b", re.IGNORECASE), "priv_escalation"),
    # Crypto mining
    (re.compile(r"\b(xmrig|minerd|cpuminer)\b", re.IGNORECASE), "crypto_mining"),
    (re.compile(r"stratum\+tcp://", re.IGNORECASE), "crypto_mining"),
    # Sudoers modification
    (re.compile(r"\bvisudo\b", re.IGNORECASE), "sudoers_mod"),
    (re.compile(r"/etc/sudoers\b", re.IGNORECASE), "sudoers_mod"),
]

# Reason: single regex is faster than char-by-char set lookup for large content.
# Pushes the scan loop into the C-level regex engine.
_INVISIBLE_CHARS_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u202a-\u202e]")


def scan_content(content: str) -> str | None:
    """Scan content for prompt injection, exfiltration, or code execution patterns.

    Args:
        content: Text to scan before writing to a persistent file.

    Returns:
        Error string describing the threat if detected, None if safe.
    """
    match = _INVISIBLE_CHARS_RE.search(content)
    if match:
        return f"security.write_rejected: invisible_char U+{ord(match.group()):04X}"

    for pattern, threat_type in THREAT_PATTERNS:
        if pattern.search(content):
            return f"security.write_rejected: {threat_type}"

    return None
