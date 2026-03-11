"""Conversation analytics plugin — tracks messages, tool calls, and escalations.

Hooks registered:
    before_response (modifying) — counts outgoing messages.
    after_tool_call (modifying) — counts tool calls by name.
    on_startup (fire_and_forget) — loads persisted data.
    on_shutdown (fire_and_forget) — persists data to disk.

Config keys:
    persist_every_n_messages (int): Flush analytics.json every N messages. Default 10.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from velo.agent.tools.base import Tool
from velo.plugins.types import PluginContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class _DayStats:
    """Statistics for a single calendar day."""

    messages: int = 0
    tool_calls: dict[str, int] = field(default_factory=dict)
    escalations: int = 0


# ---------------------------------------------------------------------------
# Analytics store
# ---------------------------------------------------------------------------


class _AnalyticsStore:
    """Tracks conversation analytics and persists to disk.

    Args:
        workspace: Agent workspace directory.
        persist_every: Flush to disk every this many messages.
    """

    def __init__(self, workspace: Path, persist_every: int = 10) -> None:
        self._workspace = workspace
        self._persist_every = persist_every
        self._data: dict[str, _DayStats] = {}
        self._msg_since_persist = 0

    def _today(self) -> str:
        """Return today's ISO date string."""
        return date.today().isoformat()

    def _ensure_day(self, key: str) -> _DayStats:
        """Get or create stats entry for a date key."""
        return self._data.setdefault(key, _DayStats())

    def record_message(self) -> None:
        """Increment today's outgoing message counter."""
        self._ensure_day(self._today()).messages += 1
        self._msg_since_persist += 1
        if self._msg_since_persist >= self._persist_every:
            self.persist()
            self._msg_since_persist = 0

    def record_tool_call(self, name: str) -> None:
        """Increment today's tool call counter for the given tool name.

        Args:
            name: Tool name called.
        """
        day = self._ensure_day(self._today())
        day.tool_calls[name] = day.tool_calls.get(name, 0) + 1

    def record_escalation(self) -> None:
        """Increment today's escalation counter."""
        self._ensure_day(self._today()).escalations += 1

    def get_today_summary(self) -> str:
        """Return a one-line summary for today.

        Returns:
            Human-readable today summary string.
        """
        stats = self._data.get(self._today(), _DayStats())
        total_tools = sum(stats.tool_calls.values())
        return (
            f"Today: {stats.messages} msgs, {total_tools} tool calls, "
            f"{stats.escalations} escalations"
        )

    def get_report(self, period: str) -> str:
        """Return a formatted analytics report.

        Args:
            period: One of "today", "yesterday", "week".

        Returns:
            Multi-line report string.
        """
        today = date.today()
        if period == "today":
            keys = [today.isoformat()]
        elif period == "yesterday":
            keys = [(today - timedelta(days=1)).isoformat()]
        else:  # week
            keys = [(today - timedelta(days=i)).isoformat() for i in range(7)]

        lines = [f"Analytics report ({period}):"]
        for key in keys:
            stats = self._data.get(key, _DayStats())
            total_tools = sum(stats.tool_calls.values())
            top_tool = ""
            if stats.tool_calls:
                top = max(stats.tool_calls, key=lambda k: stats.tool_calls[k])
                top_tool = f", top tool: {top} ({stats.tool_calls[top]}x)"
            lines.append(
                f"  {key}: {stats.messages} msgs, {total_tools} tool calls"
                f"{top_tool}, {stats.escalations} escalations"
            )
        return "\n".join(lines)

    def persist(self) -> None:
        """Write analytics data to workspace/analytics.json."""
        path = self._workspace / "analytics.json"
        try:
            payload: dict[str, Any] = {
                key: {
                    "messages": s.messages,
                    "tool_calls": s.tool_calls,
                    "escalations": s.escalations,
                }
                for key, s in self._data.items()
            }
            path.write_text(json.dumps(payload, indent=2))
        except OSError:
            logger.exception("conversation_analytics.persist_failed")

    def load(self) -> None:
        """Read analytics data from workspace/analytics.json if it exists."""
        path = self._workspace / "analytics.json"
        try:
            raw: dict[str, Any] = json.loads(path.read_text())
            for key, val in raw.items():
                self._data[key] = _DayStats(
                    messages=val.get("messages", 0),
                    tool_calls=val.get("tool_calls", {}),
                    escalations=val.get("escalations", 0),
                )
            logger.info("conversation_analytics.load_completed: %d days", len(self._data))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            logger.exception("conversation_analytics.load_failed")


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class GetAnalyticsTool(Tool):
    """Tool to retrieve conversation analytics reports.

    Args:
        store: The analytics store to query.
    """

    def __init__(self, store: _AnalyticsStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "get_analytics"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Get conversation analytics report for today, yesterday, or the past week."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "yesterday", "week"],
                    "default": "today",
                    "description": "Time period for the report.",
                }
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Return analytics report.

        Args:
            **kwargs: period (str) — one of today/yesterday/week.

        Returns:
            Formatted analytics report string.
        """
        period = kwargs.get("period", "today")
        return self._store.get_report(str(period))


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def setup(ctx: PluginContext) -> None:
    """Plugin entry point — register analytics hooks and tool.

    Args:
        ctx: Plugin context with config and workspace.
    """
    persist_every = ctx.config.get("persist_every_n_messages", 10)
    store = _AnalyticsStore(ctx.workspace, persist_every=int(persist_every))

    def on_before_response(value: str, **_: Any) -> str:
        """Count outgoing message and return response unchanged."""
        store.record_message()
        return value

    def on_after_tool_call(value: str, tool_name: str = "", **_: Any) -> str:
        """Count tool call by name and return result unchanged."""
        store.record_tool_call(tool_name)
        return value

    def on_startup() -> None:
        """Load persisted analytics on startup."""
        store.load()

    def on_shutdown() -> None:
        """Persist analytics on shutdown."""
        store.persist()

    ctx.on("before_response", on_before_response)
    ctx.on("after_tool_call", on_after_tool_call)
    ctx.on("on_startup", on_startup)
    ctx.on("on_shutdown", on_shutdown)

    ctx.register_tool(GetAnalyticsTool(store))
    ctx.add_context_provider(store.get_today_summary)

    logger.debug("conversation_analytics.setup_completed: persist_every=%d", int(persist_every))
