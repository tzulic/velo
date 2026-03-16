"""Shell execution tool."""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from velo.agent.security.command_guard import check_command
from velo.agent.security.env_isolation import build_safe_env
from velo.agent.tools.base import Tool

# Directories that must never be used as working_dir for shell commands.
# Resolved at module load for correct symlink handling on macOS (e.g. /etc → /private/etc).
_WORKING_DIR_DENYLIST: frozenset[Path] = frozenset(
    Path(d).resolve() for d in ["/etc", "/proc", "/sys", "/dev", "/root", "/boot", "/run"]
)

# Original 9 core patterns (always active)
_CORE_DENY_PATTERNS: list[str] = [
    r"\brm\s+-[rf]{1,2}\b",  # rm -r, rm -rf, rm -fr
    r"\bdel\s+/[fq]\b",  # del /f, del /q
    r"\brmdir\s+/s\b",  # rmdir /s
    r"(?:^|[;&|]\s*)format\b",  # format (as standalone command only)
    r"\b(mkfs|diskpart)\b",  # disk operations
    r"\bdd\s+if=",  # dd
    r">\s*/dev/sd",  # write to disk
    r"\b(shutdown|reboot|poweroff)\b",  # system power
    r":\(\)\s*\{.*\};\s*:",  # fork bomb
]

# Extended patterns (added when extended_safety=True)
_EXTENDED_DENY_PATTERNS: list[str] = [
    # Permissions
    r"\bchmod\s+777\b",
    r"\bchmod\s+-R\b",
    r"\bchown\s+-R\s+root\b",
    # SQL injection (matched against lowered command)
    r"\bdrop\s+(table|database)\b",
    r"\bdelete\s+from\s+\w+\s*;",  # DELETE FROM without WHERE
    r"\btruncate\b",
    # System config
    r">\s*/etc/",
    r"\bsystemctl\s+(stop|disable|mask)\b",
    # Process killing
    r"\bkill\s+-9\s+-1\b",
    r"\bpkill\s+-9\b",
    # Code execution vectors
    r"\bcurl\b.*\|\s*(sh|bash)\b",
    r"\bbash\s*<\s*\(curl\b",
    r"\bpython\s+-[ce]\b",
    r"\bbash\s+-c\b",
    # Tee writes to sensitive paths
    r"\btee\s+/etc/",
    r"\btee\s+.*\.ssh/",
    # Dangerous command chaining
    r"\bxargs\s+rm\b",
    r"\bfind\b.*-exec\s+rm\b",
    r"\bfind\b.*-delete\b",
    # Privilege escalation
    r"\bsudo\b",
    r"\bsu\s",
    r"\bchroot\b",
    # Network listeners
    r"\bnc\s+-l\b",
    r"\bsocat\b",
]


class CommandAllowlist:
    """Per-session allowlist for pre-approved command patterns.

    Checked before deny patterns in _guard_command(). Not auto-populated ---
    requires explicit config or future channel-based approval.
    """

    def __init__(self) -> None:
        """Initialize empty allowlist."""
        self._allowed: dict[str, set[str]] = {}

    def is_allowed(self, session_key: str, command: str) -> bool:
        """Check if a command is allowed for this session.

        Args:
            session_key: Session identifier.
            command: Exact command string to check.

        Returns:
            True if the command is in the session's allowlist.
        """
        return command in self._allowed.get(session_key, set())

    def add(self, session_key: str, command: str) -> None:
        """Add a command to the session's allowlist.

        Args:
            session_key: Session identifier.
            command: Exact command string to allow.
        """
        if session_key not in self._allowed:
            self._allowed[session_key] = set()
        self._allowed[session_key].add(command)

    def clear(self, session_key: str) -> None:
        """Clear all allowed patterns for a session.

        Args:
            session_key: Session identifier.
        """
        self._allowed.pop(session_key, None)


class ExecTool(Tool):
    """Tool to execute shell commands."""

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        path_append: str = "",
        extended_safety: bool = True,
    ):
        """Initialize ExecTool with safety configuration.

        Args:
            timeout: Max seconds before command is killed.
            working_dir: Default working directory for commands.
            deny_patterns: Custom deny patterns (overrides defaults).
            allow_patterns: If set, only matching commands are allowed.
            restrict_to_workspace: Block commands targeting paths outside cwd.
            path_append: Extra PATH entries appended to env.
            extended_safety: Use full deny list (True) or core-only (False).
        """
        self.timeout = timeout
        self.working_dir = working_dir
        if deny_patterns is not None:
            self.deny_patterns = deny_patterns
        elif extended_safety:
            self.deny_patterns = _CORE_DENY_PATTERNS + _EXTENDED_DENY_PATTERNS
        else:
            self.deny_patterns = list(_CORE_DENY_PATTERNS)
        self._compiled_deny = [re.compile(p) for p in self.deny_patterns]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
        self.path_append = path_append
        self._allowlist = CommandAllowlist()
        self._current_session_key: str = ""

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Use with caution."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"},
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command",
                },
            },
            "required": ["command"],
        }

    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        # Catastrophic command guard (runs first, before deny patterns)
        blocked = check_command(command)
        if blocked:
            return json.dumps(blocked)

        cwd = working_dir or self.working_dir or os.getcwd()
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        env = build_safe_env()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
            except TimeoutError:
                process.kill()
                # Wait for the process to fully terminate so pipes are
                # drained and file descriptors are released.
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except TimeoutError:
                    pass
                return f"Error: Command timed out after {self.timeout} seconds"

            output_parts = []

            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")

            if process.returncode != 0:
                output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"

            # Truncate very long output
            max_len = 10000
            if len(result) > max_len:
                result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"

            return result

        except Exception as e:
            return f"Error executing command: {str(e)}"

    def set_session_key(self, session_key: str) -> None:
        """Set the current session key for allowlist checks.

        Args:
            session_key: Session identifier for per-session allowlist lookups.
        """
        self._current_session_key = session_key

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """Best-effort safety guard for potentially destructive commands.

        Args:
            command: The shell command string to evaluate.
            cwd: Current working directory for the command.

        Returns:
            Error message string if blocked, None if safe.
        """
        cmd = command.strip()
        lower = cmd.lower()

        # Denylist: block commands run from sensitive system directories
        try:
            cwd_resolved = Path(cwd).resolve()
            if any(
                cwd_resolved == d or cwd_resolved.is_relative_to(d) for d in _WORKING_DIR_DENYLIST
            ):
                return "Error: Command blocked by safety guard (restricted working directory)"
        except Exception:
            pass

        # Symlink resolution: check extracted paths against denylist
        for raw in self._extract_absolute_paths(cmd):
            try:
                resolved = Path(raw.strip()).resolve(strict=False)
                if any(resolved == d or resolved.is_relative_to(d) for d in _WORKING_DIR_DENYLIST):
                    return "Error: Command blocked by safety guard (symlink to restricted path)"
            except Exception:
                continue

        # Per-session allowlist: skip deny check if command is pre-approved
        if self._current_session_key:
            for pat in self._compiled_deny:
                if pat.search(lower) and self._allowlist.is_allowed(self._current_session_key, cmd):
                    return None

        for pat in self._compiled_deny:
            if pat.search(lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked by safety guard (not in allowlist)"

        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()

            for raw in self._extract_absolute_paths(cmd):
                try:
                    # Resolve symlinks to prevent escape via symlinked paths
                    p = Path(raw.strip()).resolve(strict=False)
                except Exception:
                    continue
                if p.is_absolute() and cwd_path not in p.parents and p != cwd_path:
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None

    @staticmethod
    def _extract_absolute_paths(command: str) -> list[str]:
        win_paths = re.findall(r"[A-Za-z]:\\[^\s\"'|><;]+", command)  # Windows: C:\...
        posix_paths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", command)  # POSIX: /absolute only
        return win_paths + posix_paths
