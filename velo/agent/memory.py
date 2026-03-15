"""Memory system for persistent agent memory."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from velo.agent.security import scan_content
from velo.utils.helpers import atomic_write, ensure_dir

if TYPE_CHECKING:
    from velo.providers.base import LLMProvider
    from velo.session.manager import Session

_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                    "user_update": {
                        "type": "string",
                        "description": (
                            "Full updated user profile — name, role, preferences, timezone, communication style. "
                            "Return the CURRENT content unchanged if nothing new about the user was learned. "
                            "TWO TARGETS: memory_update = agent notes (env, projects, conventions); "
                            "user_update = who the user is (identity, habits, preferences)."
                        ),
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


def _format_usage_section(label: str, content: str, limit: int) -> str:
    """Format a memory section string with a usage-indicator header.

    Args:
        label: Section title shown in the header (e.g. "MEMORY (agent notes)").
        content: The section body text.
        limit: Soft char limit used to compute the usage percentage.

    Returns:
        Formatted string with separator header and usage indicator.
    """
    current = len(content)
    pct = int(current * 100 / limit) if limit > 0 else 0
    header = (
        "══════════════════════════════════════════════\n"
        f"{label} [{pct}% — {current:,}/{limit:,} chars]\n"
        "══════════════════════════════════════════════"
    )
    return f"{header}\n{content}"


class MemoryStore:
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log).

    Also manages USER.md (user profile) as a third auto-updated target.
    """

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.user_file = self.memory_dir / "USER.md"

    def read_long_term(self) -> str:
        """Read MEMORY.md content."""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def _write_with_scan(self, path: Path, content: str) -> bool:
        """Security-scan content then atomically write to path.

        Returns:
            True on success, False if blocked by security scan.
        """
        threat = scan_content(content)
        if threat:
            logger.warning("{}", threat)
            return False
        atomic_write(path, content)
        return True

    def write_long_term(self, content: str) -> bool:
        """Write content to MEMORY.md atomically after security scan.

        Args:
            content: Markdown content to write.

        Returns:
            True on success, False if blocked by security scan.
        """
        return self._write_with_scan(self.memory_file, content)

    def read_user_profile(self) -> str:
        """Read USER.md user profile content."""
        if self.user_file.exists():
            return self.user_file.read_text(encoding="utf-8")
        return ""

    def write_user_profile(self, content: str) -> bool:
        """Write content to USER.md atomically after security scan.

        Args:
            content: User profile markdown to write.

        Returns:
            True on success, False if blocked by security scan.
        """
        return self._write_with_scan(self.user_file, content)

    def append_history(self, entry: str) -> None:
        """Append an entry to HISTORY.md with fsync for durability."""
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")
            f.flush()
            os.fsync(f.fileno())

    def get_memory_context(self, memory_limit: int = 8000, user_limit: int = 4000) -> str:
        """Build formatted memory context string with usage indicators.

        Args:
            memory_limit: Soft char limit for MEMORY.md (shown as usage %).
            user_limit: Soft char limit for USER.md (shown as usage %).

        Returns:
            Formatted string with separator headers and usage indicators.
        """
        parts = []

        if long_term := self.read_long_term():
            parts.append(_format_usage_section("MEMORY (agent notes)", long_term, memory_limit))

        if user_profile := self.read_user_profile():
            parts.append(_format_usage_section("USER PROFILE", user_profile, user_limit))

        return "\n\n".join(parts) if parts else ""

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
        memory_limit: int = 8000,
        user_limit: int = 4000,
        honcho_active: bool = False,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md via LLM tool call.

        Args:
            session: Session containing messages to consolidate.
            provider: LLM provider for the consolidation call.
            model: Model identifier to use for consolidation.
            archive_all: If True, consolidate all messages (used by /new).
            memory_window: Number of recent messages to keep unconsolidated.
            memory_limit: Soft char limit for MEMORY.md (injected into prompt).
            user_limit: Soft char limit for USER.md (injected into prompt).
            honcho_active: If True, skip user_update (managed by Honcho).

        Returns:
            True on success (including no-op), False on failure.
        """
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
        else:
            keep_count = memory_window // 2
            if len(session.messages) <= keep_count:
                return True
            if len(session.messages) - session.last_consolidated <= 0:
                return True
            old_messages = session.messages[session.last_consolidated : -keep_count]
            if not old_messages:
                return True
            logger.info(
                "Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count
            )

        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(
                f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}"
            )

        current_memory = self.read_long_term()
        current_user = self.read_user_profile()

        memory_pct = int(len(current_memory) * 100 / memory_limit) if memory_limit > 0 else 0
        user_pct = int(len(current_user) * 100 / user_limit) if user_limit > 0 else 0

        # Reason: warn the LLM to compress when approaching limits so MEMORY.md
        # doesn't grow unboundedly over months of use.
        compress_hint = ""
        if memory_pct >= 80:
            compress_hint += (
                f"\n⚠️ MEMORY.md is {memory_pct}% full "
                f"({len(current_memory):,}/{memory_limit:,} chars). "
                "Compress aggressively — remove outdated facts, merge duplicates."
            )
        if user_pct >= 80:
            compress_hint += (
                f"\n⚠️ USER.md is {user_pct}% full "
                f"({len(current_user):,}/{user_limit:,} chars). "
                "Compress aggressively — keep only essential user profile facts."
            )

        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory (agent notes) [{memory_pct}% of {memory_limit:,} char limit]
{current_memory or "(empty)"}

## Current User Profile [{user_pct}% of {user_limit:,} char limit]
{current_user or "(empty)"}

## TWO MEMORY TARGETS
- memory_update: agent notes — env facts, project context, tool quirks, conventions
- user_update: user profile — who they are, preferences, timezone, communication style
{("⚠️ user_update is managed externally by Honcho — return it unchanged." if honcho_active else "")}{compress_hint}

## Conversation to Process
{chr(10).join(lines)}"""

        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation.",
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
                tool_choice="required",
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = response.tool_calls[0].arguments
            # Some providers return arguments as a JSON string instead of dict
            if isinstance(args, str):
                args = json.loads(args)
            # Some providers return arguments as a list (handle edge case)
            if isinstance(args, list):
                if args and isinstance(args[0], dict):
                    args = args[0]
                else:
                    logger.warning(
                        "Memory consolidation: unexpected arguments as empty or non-dict list"
                    )
                    return False
            if not isinstance(args, dict):
                logger.warning(
                    "Memory consolidation: unexpected arguments type {}", type(args).__name__
                )
                return False

            if entry := args.get("history_entry"):
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                self.append_history(entry)

            if update := args.get("memory_update"):
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != current_memory:
                    if not self.write_long_term(update):
                        return False

            # Reason: When Honcho is active, it manages user modeling externally.
            # Skip writing USER.md to avoid conflicts with Honcho's peer cards.
            if not honcho_active:
                if user_update := args.get("user_update"):
                    if not isinstance(user_update, str):
                        user_update = json.dumps(user_update, ensure_ascii=False)
                    if user_update != current_user:
                        if not self.write_user_profile(user_update):
                            return False

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            logger.info(
                "Memory consolidation done: {} messages, last_consolidated={}",
                len(session.messages),
                session.last_consolidated,
            )
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
