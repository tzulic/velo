"""Resolution guard plugin — policy enforcement and audit trail for consequential actions.

Tools registered:
    get_audit_log         — recent resolution actions, filterable by tool name pattern
    get_resolution_stats  — stats for the last N days (totals, blocked, refund amounts)

Hook registered:
    before_tool_call (priority=50) — intercepts tracked tools, enforces policies,
    blocks or allows based on blocked_actions / require_approval / max_refund_amount.

Context provider:
    One-line summary: "Resolutions: 5 actions today (2 refunds totaling $150, 1 blocked)"

Config keys:
    track_patterns (list[str]): Tool name substrings to intercept. Default: refund,
        cancel, delete, update_order, modify_subscription.
    max_refund_amount (int): Max allowed amount (cents) before blocking. Default 100.
        Set to 0 to disable amount checking.
    require_approval_actions (list[str]): Tools that always require human approval.
    blocked_actions (list[str]): Tools the agent must never take.
    max_audit_entries (int): FIFO cap on audit log size. Default 1000.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from velo.agent.tools.base import Tool
from velo.plugins.types import PluginContext
from velo.utils.helpers import atomic_write

logger = logging.getLogger(__name__)

_DEFAULT_TRACK_PATTERNS = ["refund", "cancel", "delete", "update_order", "modify_subscription"]
_DEFAULT_REQUIRE_APPROVAL = ["cancel_subscription", "delete_account"]


# ---------------------------------------------------------------------------
# AuditStore
# ---------------------------------------------------------------------------


class AuditStore:
    """JSON-backed audit log for resolution actions.

    Args:
        path: Path to resolution_audit.json file.
        max_audit_entries: Maximum entries before FIFO eviction. Default 1000.
    """

    def __init__(self, path: Path, max_audit_entries: int = 1000) -> None:
        self._path = path
        self._max_entries = max_audit_entries
        self._log: list[dict[str, Any]] = []
        self._next_id = 1
        self._load()

    def _load(self) -> None:
        """Load audit log from disk."""
        if self._path.is_file():
            try:
                self._log = json.loads(self._path.read_text(encoding="utf-8"))
                if self._log:
                    # Recover next ID from highest existing RES-NNNN
                    max_num = max(
                        int(e["id"].split("-")[1]) for e in self._log if "id" in e
                    )
                    self._next_id = max_num + 1
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.warning("resolution_guard.load_failed: %s", self._path)
                self._log = []

    def _save(self) -> None:
        """Write audit log to disk atomically."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self._path, json.dumps(self._log, indent=2, ensure_ascii=False))

    def log_action(
        self,
        tool_name: str,
        params: Any,
        outcome: str,
        reason: str = "",
    ) -> None:
        """Append an audit entry, evicting oldest if at capacity.

        Args:
            tool_name: Name of the tool that was called.
            params: Parameters passed to the tool (stored as-is).
            outcome: "allowed" or "blocked".
            reason: Optional explanation for a block.
        """
        entry: dict[str, Any] = {
            "id": f"RES-{self._next_id:04d}",
            "tool_name": tool_name,
            "params": params,
            "outcome": outcome,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if reason:
            entry["reason"] = reason
        self._next_id += 1
        self._log.append(entry)
        # FIFO cap — remove oldest entries when over limit
        if len(self._log) > self._max_entries:
            self._log = self._log[-self._max_entries :]
        self._save()

    def get_log(
        self,
        limit: int = 20,
        action_type: str = "",
    ) -> list[dict[str, Any]]:
        """Return recent audit entries, optionally filtered by tool name pattern.

        Args:
            limit: Maximum number of entries to return. Most recent first.
            action_type: Substring filter on tool_name (case-insensitive). Empty = all.

        Returns:
            List of matching audit entry dicts, newest first.
        """
        entries = self._log
        if action_type:
            pattern = action_type.lower()
            entries = [e for e in entries if pattern in e.get("tool_name", "").lower()]
        # Return most recent entries first
        return list(reversed(entries[-limit:])) if limit > 0 else list(reversed(entries))

    def get_stats(self, days: int = 7) -> dict[str, Any]:
        """Compute resolution stats for the last N days (single-pass).

        Args:
            days: Lookback window in calendar days. Must be >= 1; invalid values default to 7.

        Returns:
            Dict with keys: total, blocked, refund_total (sum of allowed refund amounts),
            most_common (list of (tool_name, count) tuples sorted desc).
        """
        if days < 1:
            days = 7
        now = datetime.now(timezone.utc)
        total = 0
        blocked = 0
        refund_total: float = 0.0
        tool_counts: dict[str, int] = {}

        for entry in self._log:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
            except (KeyError, ValueError):
                continue
            delta = now - ts
            if delta.days >= days:
                continue
            total += 1
            tool_name = entry.get("tool_name", "")
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
            if entry.get("outcome") == "blocked":
                blocked += 1
            elif entry.get("outcome") == "allowed":
                # Sum refund-like amounts from allowed actions
                params = entry.get("params", {})
                if isinstance(params, dict):
                    for key in ("amount", "refund_amount", "total"):
                        val = params.get(key)
                        if isinstance(val, (int, float)):
                            refund_total += val
                            break

        most_common = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)
        return {
            "total": total,
            "blocked": blocked,
            "refund_total": refund_total,
            "most_common": most_common,
        }

    def get_today_summary(self) -> dict[str, Any]:
        """Compute summary counts for today (UTC).

        Returns:
            Dict with keys: total, blocked, refund_count, refund_total.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        total = 0
        blocked = 0
        refund_count = 0
        refund_total: float = 0.0

        for entry in self._log:
            ts_str = entry.get("timestamp", "")
            if not ts_str.startswith(today):
                continue
            total += 1
            if entry.get("outcome") == "blocked":
                blocked += 1
            elif entry.get("outcome") == "allowed":
                params = entry.get("params", {})
                if isinstance(params, dict):
                    for key in ("amount", "refund_amount", "total"):
                        val = params.get(key)
                        if isinstance(val, (int, float)):
                            refund_total += val
                            refund_count += 1
                            break

        return {
            "total": total,
            "blocked": blocked,
            "refund_count": refund_count,
            "refund_total": refund_total,
        }

    def context_string(self) -> str:
        """One-line context for system prompt injection.

        Returns:
            Summary string like "Resolutions: 5 actions today (2 refunds totaling $150, 1 blocked)"
            or "Resolutions: none today" when there are no actions.
        """
        s = self.get_today_summary()
        if s["total"] == 0:
            return "Resolutions: none today"
        parts: list[str] = []
        if s["refund_count"]:
            total_dollars = s["refund_total"] / 100
            parts.append(f"{s['refund_count']} refunds totaling ${total_dollars:.0f}")
        if s["blocked"]:
            parts.append(f"{s['blocked']} blocked")
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Resolutions: {s['total']} actions today{detail}"


# ---------------------------------------------------------------------------
# Guard hook factory
# ---------------------------------------------------------------------------


def _make_guard(
    store: AuditStore,
    track_patterns: list[str],
    blocked_actions: list[str],
    require_approval: list[str],
    max_refund: int,
) -> Any:
    """Create and return the before_tool_call guard hook.

    Args:
        store: AuditStore instance for logging actions.
        track_patterns: Substrings; tool names containing any pattern are intercepted.
        blocked_actions: Tool names that are permanently blocked.
        require_approval: Tool names that require human approval.
        max_refund: Maximum allowed amount (cents). 0 = disabled.

    Returns:
        Async guard callable compatible with the before_tool_call hook.
    """

    async def guard(value: Any, tool_name: str, **kwargs: Any) -> Any:
        """Intercept tool calls and enforce resolution policies.

        Args:
            value: The tool call parameters dict.
            tool_name: Name of the tool being called.
            **kwargs: Additional hook context (ignored).

        Returns:
            Original value if allowed, or a ``{"__block": True, "reason": "..."}``
            dict if blocked.
        """
        name_lower = tool_name.lower()
        if not any(p in name_lower for p in track_patterns):
            return value  # Not tracked, pass through

        # Check permanently blocked
        if tool_name in blocked_actions:
            store.log_action(tool_name, value, "blocked", "Action permanently blocked")
            return {"__block": True, "reason": f"Action '{tool_name}' is blocked by policy."}

        # Check approval required
        if tool_name in require_approval:
            store.log_action(tool_name, value, "blocked", "Requires human approval")
            return {
                "__block": True,
                "reason": f"Action '{tool_name}' requires human approval. Please escalate.",
            }

        # Check amount limit
        amount: float = 0
        if isinstance(value, dict):
            for key in ("amount", "refund_amount", "total"):
                v = value.get(key)
                if isinstance(v, (int, float)):
                    amount = v
                    break
        if amount > max_refund > 0:
            store.log_action(
                tool_name,
                value,
                "blocked",
                f"Amount {amount} exceeds limit {max_refund}",
            )
            return {
                "__block": True,
                "reason": f"Amount exceeds policy limit of {max_refund}. Please escalate.",
            }

        # Allowed — log and pass through
        store.log_action(tool_name, value, "allowed")
        return value

    return guard


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class GetAuditLogTool(Tool):
    """Tool: retrieve recent resolution audit log entries.

    Args:
        store: AuditStore instance to read from.
    """

    def __init__(self, store: AuditStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "get_audit_log"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Retrieve recent resolution actions from the audit trail. "
            "Shows timestamp, tool name, outcome (allowed/blocked), and key params. "
            "Optionally filter by action type (tool name pattern)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum number of entries to return",
                },
                "action_type": {
                    "type": "string",
                    "default": "",
                    "description": "Filter by tool name pattern (case-insensitive substring)",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Return formatted audit log.

        Args:
            **kwargs: limit (int), action_type (str).

        Returns:
            Formatted audit log string or "No resolution actions recorded yet."
        """
        limit = int(kwargs.get("limit", 20))
        action_type = str(kwargs.get("action_type", ""))
        entries = self._store.get_log(limit=limit, action_type=action_type)
        if not entries:
            return "No resolution actions recorded yet."
        lines = [f"Found {len(entries)} resolution action(s):\n"]
        for e in entries:
            ts = e.get("timestamp", "")[:19].replace("T", " ")
            outcome = e.get("outcome", "?")
            tool = e.get("tool_name", "?")
            reason = e.get("reason", "")
            params = e.get("params", {})
            # Show amount if present
            amount_str = ""
            if isinstance(params, dict):
                for key in ("amount", "refund_amount", "total"):
                    val = params.get(key)
                    if isinstance(val, (int, float)):
                        amount_str = f" amount={val}"
                        break
            reason_str = f" — {reason}" if reason else ""
            lines.append(f"  [{ts}] {tool} → {outcome}{amount_str}{reason_str}")
        return "\n".join(lines)


class GetResolutionStatsTool(Tool):
    """Tool: get resolution action statistics for the last N days.

    Args:
        store: AuditStore instance to read from.
    """

    def __init__(self, store: AuditStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "get_resolution_stats"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Get resolution statistics for the last N days: total actions, "
            "blocked count, total refund amount, and most common action types."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "default": 7,
                    "description": "Lookback window in days (default 7)",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Return formatted resolution stats.

        Args:
            **kwargs: days (int).

        Returns:
            Formatted stats string.
        """
        days = int(kwargs.get("days", 7))
        stats = self._store.get_stats(days=days)
        lines = [f"Resolution stats — last {days} day(s):"]
        lines.append(f"  Total actions : {stats['total']}")
        lines.append(f"  Blocked       : {stats['blocked']}")
        refund_dollars = stats["refund_total"] / 100
        lines.append(f"  Refund total  : ${refund_dollars:.2f}")
        if stats["most_common"]:
            lines.append("  Most common:")
            for tool_name, count in stats["most_common"][:5]:
                lines.append(f"    {tool_name}: {count}")
        else:
            lines.append("  Most common   : none")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def register(ctx: PluginContext) -> None:
    """Plugin entry point — register guard hook, tools, and context provider.

    Args:
        ctx: Plugin context with config and workspace.
    """
    track_patterns: list[str] = list(ctx.config.get("track_patterns", _DEFAULT_TRACK_PATTERNS))
    max_refund = int(ctx.config.get("max_refund_amount", 100))
    require_approval: list[str] = list(
        ctx.config.get("require_approval_actions", _DEFAULT_REQUIRE_APPROVAL)
    )
    blocked_actions: list[str] = list(ctx.config.get("blocked_actions", []))
    max_audit_entries = int(ctx.config.get("max_audit_entries", 1000))

    store = AuditStore(
        path=ctx.workspace / "resolution_audit.json",
        max_audit_entries=max_audit_entries,
    )

    guard = _make_guard(
        store=store,
        track_patterns=track_patterns,
        blocked_actions=blocked_actions,
        require_approval=require_approval,
        max_refund=max_refund,
    )
    ctx.on("before_tool_call", guard, priority=50)

    ctx.register_tool(GetAuditLogTool(store))
    ctx.register_tool(GetResolutionStatsTool(store))
    ctx.add_context_provider(store.context_string)

    logger.debug(
        "resolution_guard.register: track=%s, max_refund=%d, blocked=%d, require_approval=%d",
        track_patterns,
        max_refund,
        len(blocked_actions),
        len(require_approval),
    )
