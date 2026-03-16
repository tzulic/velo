"""Catastrophic command blocking with context classification.

Blocks only truly destructive commands (rm -rf /, mkfs, fork bombs, reverse
shells, privilege escalation, credential leakage). Uses simple context
classification to avoid false positives on echo/heredoc/quoted content.

Returns None if command is safe, or a dict with error details if blocked.
"""

from __future__ import annotations

import re

# Catastrophic patterns — these are ALWAYS dangerous as executed commands.
_CATASTROPHIC_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # Recursive delete of root/home/current dir
    (
        re.compile(r"\brm\s+-[rf]{1,2}\s+/\s*$"),
        "recursive_delete_root",
        "Use a specific path instead of /",
    ),
    (re.compile(r"\brm\s+-[rf]{1,2}\s+~"), "recursive_delete_home", "Use a specific subdirectory"),
    (
        re.compile(r"\brm\s+-[rf]{1,2}\s+\.\s*$"),
        "recursive_delete_cwd",
        "Use a specific subdirectory",
    ),
    # Filesystem formatting
    (re.compile(r"\bmkfs\b"), "filesystem_format", "Do not format disks"),
    (
        re.compile(r"(?:^|[;&|]\s*)format\s+[A-Z]:", re.IGNORECASE),
        "disk_format",
        "Do not format disks",
    ),
    # Disk destruction
    (re.compile(r"\bdd\s+.*of=/dev/sd"), "disk_write", "Do not write directly to block devices"),
    (re.compile(r">\s*/dev/sd"), "disk_redirect", "Do not redirect to block devices"),
    # Fork bomb
    (re.compile(r":\(\)\s*\{.*\};\s*:"), "fork_bomb", "Fork bombs crash the system"),
    # Reverse shells
    (re.compile(r"bash\s+-i\s+>&\s*/dev/tcp/"), "reverse_shell", "Reverse shells are not allowed"),
    (re.compile(r"\bnc\s+-e\b"), "reverse_shell_nc", "Netcat exec is not allowed"),
    # Privilege escalation
    (re.compile(r"(?:^|[;&|]\s*)sudo\b"), "privilege_escalation", "sudo is not allowed"),
    (re.compile(r"(?:^|[;&|]\s*)su\s"), "privilege_escalation_su", "su is not allowed"),
    (re.compile(r"\bchroot\b"), "chroot", "chroot is not allowed"),
    # System power
    (re.compile(r"\b(shutdown|reboot|poweroff|halt)\b"), "system_power", "Cannot shutdown/reboot"),
    # Credential leakage via shell
    (re.compile(r"\bcat\s+.*config\.json"), "read_config", "Cannot read config files"),
    (
        re.compile(r"\bcat\s+/proc/(self|\d+)/environ"),
        "read_proc_environ",
        "Cannot read process environment",
    ),
    (re.compile(r"(?:^|[;&|]\s*)printenv\b"), "dump_env", "Cannot dump environment variables"),
    (re.compile(r"(?:^|[;&|]\s*)env\s*\|"), "dump_env_pipe", "Cannot pipe environment variables"),
    (re.compile(r"\bcat\s+.*\.env\b"), "read_dotenv", "Cannot read .env files"),
]

# Pre-compiled patterns for context classification
_ECHO_RE = re.compile(r"^(echo|printf)\s")
_HEREDOC_RE = re.compile(r"^cat\s*<<")


def _is_safe_context(command: str) -> bool:
    """Check if the command is in a safe output context (echo, heredoc, comment).

    Args:
        command: Full command string.

    Returns:
        True if the dangerous pattern is likely in a non-executable context.
    """
    stripped = command.strip()
    # Comment
    if stripped.startswith("#"):
        return True
    # Echo / printf — entire command is output, not execution
    if _ECHO_RE.match(stripped):
        return True
    # Heredoc
    if _HEREDOC_RE.match(stripped):
        return True
    return False


def _pattern_in_single_quotes(command: str, pattern_match: re.Match[str]) -> bool:
    """Check if the pattern match falls entirely within single quotes.

    Args:
        command: Full command string.
        pattern_match: The regex match object.

    Returns:
        True if the match is inside single-quoted string.
    """
    start = pattern_match.start()
    # Count single quotes before the match position
    prefix = command[:start]
    open_quotes = prefix.count("'")
    # Odd number of single quotes means we're inside a quoted string
    return open_quotes % 2 == 1


def check_command(command: str) -> dict[str, str] | None:
    """Check a command against catastrophic patterns.

    Args:
        command: Shell command to check.

    Returns:
        None if safe. Dict with error/reason/command/suggestion if blocked.
    """
    if not command or not command.strip():
        return None

    # Context classification: skip if entire command is echo/heredoc/comment
    if _is_safe_context(command):
        return None

    for pattern, reason, suggestion in _CATASTROPHIC_PATTERNS:
        match = pattern.search(command)
        if match and not _pattern_in_single_quotes(command, match):
            return {
                "error": "command_blocked",
                "reason": reason,
                "command": command,
                "suggestion": suggestion,
            }

    return None
