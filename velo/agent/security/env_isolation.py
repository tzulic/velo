"""Environment variable isolation for shell and MCP subprocesses.

Prevents channel tokens (Telegram, Discord, Slack, etc.) and integration
credentials from leaking to child processes. Only safe baseline vars plus
explicitly declared overrides are passed through.
"""

from __future__ import annotations

import os

# Vars safe to pass to any child process.
_SAFE_ENV_KEYS: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        "PWD",
        "TERM",
        "SHELL",
        "HOSTNAME",
        "LOGNAME",
        "SHLVL",
    }
)


def build_safe_env(
    extra_env: dict[str, str] | None = None,
    passthrough: list[str] | None = None,
) -> dict[str, str]:
    """Build a safe environment dict for subprocess execution.

    Starts with safe baseline vars from the current process, adds any
    passthrough vars, then merges explicit overrides. Never returns None.

    Args:
        extra_env: Explicit vars to add (e.g., MCP server config env block).
        passthrough: Additional var names to pull from os.environ.

    Returns:
        Environment dict safe for subprocess use.
    """
    env: dict[str, str] = {}

    # Safe baseline from current environment
    for key, value in os.environ.items():
        if key in _SAFE_ENV_KEYS or key.startswith("XDG_"):
            env[key] = value

    # Passthrough: explicitly named vars from config
    if passthrough:
        for key in passthrough:
            val = os.environ.get(key)
            if val is not None:
                env[key] = val

    # Explicit overrides always win
    if extra_env:
        env.update(extra_env)

    return env
