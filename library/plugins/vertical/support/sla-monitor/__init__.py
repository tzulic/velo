"""SLA monitor plugin — breach detection for tickets in workspace/tickets.json.

Reads the same tickets.json produced by the ticket-tracker plugin (no shared
module — direct file read). Sends SLA alerts via process_direct when tickets
breach or are approaching their deadline.

Config keys:
    check_interval_minutes (int): How often to check SLAs. Default 30.
    warning_hours (int): Hours before deadline to flag as at-risk. Default 2.
    sla_rules (dict): Priority → hours until breach. Default P0=4, P1=8, P2=24, P3=72.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from velo.agent.tools.base import Tool
from velo.plugins.types import PluginContext, RuntimeRefs

logger = logging.getLogger(__name__)

_DEFAULT_SLA: dict[str, int] = {"P0": 4, "P1": 8, "P2": 24, "P3": 72}


# ---------------------------------------------------------------------------
# SLA monitor service
# ---------------------------------------------------------------------------


class _SLAMonitor:
    """Background SLA checking service.

    Implements ServiceLike and RuntimeAware protocols.

    Args:
        sla_rules: Priority → SLA hours mapping.
        check_interval_minutes: How often to run checks.
        warning_hours: Hours before deadline to flag as at-risk.
        tickets_path: Path to tickets.json (shared with ticket-tracker).
    """

    def __init__(
        self,
        sla_rules: dict[str, int],
        check_interval_minutes: int,
        warning_hours: int,
        tickets_path: Path,
    ) -> None:
        self._sla_rules = sla_rules
        self._interval = check_interval_minutes * 60
        self._warning_delta = timedelta(hours=warning_hours)
        self._tickets_path = tickets_path
        self._process_direct: Callable[..., Awaitable[str]] | None = None
        self._task: asyncio.Task[None] | None = None

    def set_runtime(self, refs: RuntimeRefs) -> None:
        """Store process_direct callback from late-bound runtime refs.

        Args:
            refs: Runtime references provided after agent loop creation.
        """
        self._process_direct = refs.process_direct

    async def start(self) -> None:
        """Start the background SLA monitoring task."""
        self._task = asyncio.create_task(self._run())
        logger.info(
            "sla_monitor.started: interval=%ds warning_delta=%s",
            self._interval,
            self._warning_delta,
        )

    def stop(self) -> None:
        """Cancel the monitoring task."""
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        """Main monitoring loop — sleep, then check for SLA breaches."""
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._check()
            except Exception:
                logger.exception("sla_monitor.check_failed")

    async def _check(self) -> None:
        """Load tickets.json and alert on breached or at-risk tickets."""
        if not self._tickets_path.exists():
            logger.warning("sla_monitor.tickets_file_missing: %s", self._tickets_path)
            return

        try:
            raw: list[dict[str, Any]] = json.loads(self._tickets_path.read_text())
        except (OSError, json.JSONDecodeError):
            logger.exception("sla_monitor.load_failed")
            return

        now = datetime.now(timezone.utc)
        alerts: list[str] = []

        for item in raw:
            status = item.get("status", "open")
            if status in ("resolved", "closed"):
                continue

            priority = item.get("priority", "P2")
            ticket_id = item.get("id", "?")
            title = item.get("title", "")
            created_at_str = item.get("created_at", "")

            try:
                created_at = datetime.fromisoformat(created_at_str)
            except (ValueError, TypeError):
                continue

            sla_hours = self._sla_rules.get(priority, 24)
            deadline = created_at + timedelta(hours=sla_hours)

            if deadline < now:
                elapsed = now - deadline
                hours_ago = int(elapsed.total_seconds() / 3600)
                mins_ago = int((elapsed.total_seconds() % 3600) / 60)
                elapsed_str = f"{hours_ago}h {mins_ago}m" if hours_ago else f"{mins_ago}m"
                alerts.append(
                    f'- {ticket_id} ({priority}): BREACHED {elapsed_str} ago — "{title}"'
                )
            elif deadline < now + self._warning_delta:
                remaining = deadline - now
                rem_hours = int(remaining.total_seconds() / 3600)
                rem_mins = int((remaining.total_seconds() % 3600) / 60)
                rem_str = f"{rem_hours}h {rem_mins}m" if rem_hours else f"{rem_mins}m"
                alerts.append(
                    f'- {ticket_id} ({priority}): deadline in {rem_str} — "{title}"'
                )

        if alerts and self._process_direct is not None:
            alert_text = (
                f"[SLA Alert] {len(alerts)} ticket(s) at risk or breached:\n"
                + "\n".join(alerts)
            )
            logger.warning("sla_monitor.alerts_triggered: count=%d", len(alerts))
            await self._process_direct(
                alert_text,
                session_key="sla_alert",
                channel="cli",
                chat_id="sla_alert",
            )

    def get_report(self) -> str:
        """Return a formatted SLA status report for all open tickets.

        Returns:
            Multi-line SLA report string.
        """
        if not self._tickets_path.exists():
            return "SLA report: tickets.json not found."

        try:
            raw: list[dict[str, Any]] = json.loads(self._tickets_path.read_text())
        except (OSError, json.JSONDecodeError):
            return "SLA report: failed to load tickets."

        now = datetime.now(timezone.utc)
        col = f"{'ID':<12} {'Priority':<10} {'Status':<12} {'SLA Deadline':<25} {'State'}"
        lines = ["SLA Status Report:", col, "-" * 75]

        for item in sorted(raw, key=lambda x: x.get("id", "")):
            status = item.get("status", "open")
            if status in ("resolved", "closed"):
                continue

            priority = item.get("priority", "P2")
            ticket_id = item.get("id", "?")
            created_at_str = item.get("created_at", "")

            try:
                created_at = datetime.fromisoformat(created_at_str)
            except (ValueError, TypeError):
                continue

            sla_hours = self._sla_rules.get(priority, 24)
            deadline = created_at + timedelta(hours=sla_hours)
            deadline_str = deadline.strftime("%Y-%m-%d %H:%M UTC")

            if deadline < now:
                state = "BREACHED"
            elif deadline < now + self._warning_delta:
                state = "AT RISK"
            else:
                state = "OK"

            lines.append(
                f"{ticket_id:<12} {priority:<10} {status:<12} {deadline_str:<25} {state}"
            )

        if len(lines) <= 3:
            lines.append("  No open tickets.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class GetSLAReportTool(Tool):
    """Tool: retrieve the current SLA status report.

    Args:
        monitor: The SLA monitor instance to query.
    """

    def __init__(self, monitor: _SLAMonitor) -> None:
        self._monitor = monitor

    @property
    def name(self) -> str:
        """Tool name."""
        return "get_sla_report"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Get the current SLA status report for all open tickets."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema — no parameters required."""
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> str:
        """Return the SLA report.

        Args:
            **kwargs: Not used.

        Returns:
            Formatted SLA report string.
        """
        return self._monitor.get_report()


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def setup(ctx: PluginContext) -> None:
    """Plugin entry point — register SLA monitor service, tool, and context.

    Args:
        ctx: Plugin context with config and workspace.
    """
    sla_rules: dict[str, int] = dict(ctx.config.get("sla_rules", _DEFAULT_SLA))
    check_interval_minutes = int(ctx.config.get("check_interval_minutes", 30))
    warning_hours = int(ctx.config.get("warning_hours", 2))

    monitor = _SLAMonitor(
        sla_rules=sla_rules,
        check_interval_minutes=check_interval_minutes,
        warning_hours=warning_hours,
        tickets_path=ctx.workspace / "tickets.json",
    )

    def context_provider() -> str:
        """Return SLA monitor status for agent context.

        Returns:
            One-line SLA monitor summary.
        """
        return (
            f"SLA monitor: checking every {check_interval_minutes}m, "
            f"warning at {warning_hours}h before breach"
        )

    ctx.register_service(monitor)
    ctx.register_tool(GetSLAReportTool(monitor))
    ctx.add_context_provider(context_provider)

    logger.debug(
        "sla_monitor.setup_completed: interval=%dm warning=%dh",
        check_interval_minutes,
        warning_hours,
    )
