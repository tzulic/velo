"""Campaign reporter plugin — structured marketing report storage with trend tracking.

Tools registered:
    save_report      — save a marketing report for a given period with metrics
    get_report       — retrieve a report by period label or ID
    compare_periods  — compare metrics between two saved reports (deltas + percentages)
    list_reports     — list recent reports, newest first

Background service:
    ReportScheduler — sends a weekly report-generation prompt on configured day/time

Context provider:
    One-line summary: "Marketing: N reports saved, latest: <period> (<key metrics>)"

Config keys:
    schedule_day (str): Day of week to fire. Default "monday".
    schedule_time (str): HH:MM time in configured timezone. Default "09:00".
    timezone (str): IANA timezone name. Default "UTC".
    max_reports (int): Maximum reports stored (FIFO eviction). Default 200.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from velo.agent.tools.base import Tool
from velo.plugins.types import PluginContext, RuntimeRefs
from velo.utils.helpers import atomic_write

logger = logging.getLogger(__name__)

# Day-of-week name → isoweekday (Monday=1 … Friday=5)
_DAY_MAP = {
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
    "sunday": 7,
}


# ---------------------------------------------------------------------------
# ReportStore
# ---------------------------------------------------------------------------


class ReportStore:
    """JSON-backed marketing report storage with comparison and summary.

    Args:
        path: Path to marketing_reports.json file.
        max_reports: Maximum number of reports stored (oldest removed when exceeded).
    """

    def __init__(self, path: Path, max_reports: int = 200) -> None:
        self._path = path
        self._max_reports = max_reports
        self._reports: list[dict[str, Any]] = []
        self._next_id = 1
        self._load()

    def _load(self) -> None:
        """Load reports from disk."""
        if self._path.is_file():
            try:
                self._reports = json.loads(self._path.read_text(encoding="utf-8"))
                if self._reports:
                    max_num = max(int(r["id"].split("-")[1]) for r in self._reports)
                    self._next_id = max_num + 1
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.warning("campaign_reporter.load_failed: %s", self._path)
                self._reports = []

    def _save(self) -> None:
        """Write reports to disk atomically."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self._path, json.dumps(self._reports, indent=2, ensure_ascii=False))

    def _now_iso(self) -> str:
        """Return current UTC time as ISO string."""
        return datetime.now(timezone.utc).isoformat()

    def save(
        self,
        period: str,
        metrics_dict: dict[str, Any],
        summary: str = "",
    ) -> dict[str, Any]:
        """Save a marketing report, evicting the oldest if max_reports is reached.

        IDs keep incrementing even after eviction (no reuse).

        Args:
            period: Report period label (e.g. "2026-W12", "2026-03").
            metrics_dict: Key-value pairs of metric name to value.
            summary: Optional narrative summary of the period.

        Returns:
            The saved report dict.
        """
        report: dict[str, Any] = {
            "id": f"RPT-{self._next_id:04d}",
            "period": period,
            "metrics": metrics_dict,
            "summary": summary,
            "created_at": self._now_iso(),
        }
        self._next_id += 1
        self._reports.append(report)

        # Reason: FIFO eviction — remove the oldest when over cap
        if len(self._reports) > self._max_reports:
            self._reports.pop(0)

        self._save()
        return report

    def get(self, period: str = "", report_id: str = "") -> dict[str, Any] | None:
        """Find a report by period label or report ID.

        Searches by period first if provided, then by ID.

        Args:
            period: Period label to search for.
            report_id: Report ID (e.g. RPT-0001) to search for.

        Returns:
            Report dict if found, None otherwise.
        """
        if period:
            # Reason: most-recent match wins for duplicate periods
            for r in reversed(self._reports):
                if r["period"] == period:
                    return r
        if report_id:
            for r in self._reports:
                if r["id"] == report_id:
                    return r
        return None

    def compare(self, period_a: str, period_b: str) -> str:
        """Compare metrics between two saved periods.

        Computes delta and percentage for shared metric keys. Keys only in A
        are marked "(removed)"; keys only in B are marked "(new)".

        Args:
            period_a: Period label for the baseline report.
            period_b: Period label for the comparison report.

        Returns:
            Formatted comparison string, or an error message if a period is not found.
        """
        report_a = self.get(period=period_a)
        if report_a is None:
            return f"No report found for period '{period_a}'."
        report_b = self.get(period=period_b)
        if report_b is None:
            return f"No report found for period '{period_b}'."

        metrics_a: dict[str, Any] = report_a.get("metrics", {})
        metrics_b: dict[str, Any] = report_b.get("metrics", {})

        # Union all keys for full coverage
        all_keys = sorted(set(metrics_a) | set(metrics_b))

        lines = [f"Comparing {period_a} vs {period_b}:"]
        for key in all_keys:
            in_a = key in metrics_a
            in_b = key in metrics_b
            label = key.replace("_", " ").capitalize()

            if in_a and in_b:
                val_a = metrics_a[key]
                val_b = metrics_b[key]
                try:
                    a_f = float(val_a)
                    b_f = float(val_b)
                    delta = b_f - a_f
                    sign = "+" if delta >= 0 else ""
                    if a_f != 0:
                        pct = (delta / a_f) * 100
                        lines.append(
                            f"  {label}: {val_a} → {val_b} ({sign}{delta:g}, {sign}{pct:.1f}%)"
                        )
                    else:
                        lines.append(f"  {label}: {val_a} → {val_b} ({sign}{delta:g})")
                except (TypeError, ValueError):
                    lines.append(f"  {label}: {val_a} → {val_b}")
            elif in_a and not in_b:
                lines.append(f"  {label}: {metrics_a[key]} (removed)")
            else:
                lines.append(f"  {label}: {metrics_b[key]} (new)")

        return "\n".join(lines)

    def list_reports(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return reports sorted newest first, up to limit.

        Args:
            limit: Maximum number of reports to return.

        Returns:
            List of report dicts, newest first.
        """
        return list(reversed(self._reports))[:limit]

    def get_summary(self) -> dict[str, Any]:
        """Return summary data for the context provider.

        Returns:
            Dict with count and latest report metadata.
        """
        count = len(self._reports)
        latest = self._reports[-1] if self._reports else None
        return {"count": count, "latest": latest}

    def context_string(self) -> str:
        """One-line context for system prompt injection.

        Returns:
            Summary string like "Marketing: 12 reports saved, latest: 2026-W11 (...)".
        """
        s = self.get_summary()
        if s["count"] == 0:
            return "Marketing: no reports yet"
        latest = s["latest"]
        period = latest["period"]
        metrics: dict[str, Any] = latest.get("metrics", {})
        # Reason: show up to 3 key metrics in the context string for quick reference
        metric_parts = [f"{k}: {v}" for k, v in list(metrics.items())[:3]]
        metric_str = ", ".join(metric_parts)
        if metric_str:
            return f"Marketing: {s['count']} reports saved, latest: {period} ({metric_str})"
        return f"Marketing: {s['count']} reports saved, latest: {period}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class SaveReportTool(Tool):
    """Tool: save a marketing report for a period.

    Args:
        store: ReportStore instance to write to.
    """

    def __init__(self, store: ReportStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "save_report"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Save a marketing report for a given period. Provide a period label "
            "(e.g. '2026-W12', '2026-03'), a JSON object of metrics, and an optional "
            "narrative summary."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Period label (e.g. '2026-W12', '2026-03', '2026-03-16')",
                },
                "metrics": {
                    "type": "string",
                    "description": (
                        'JSON object of metric key-value pairs, '
                        'e.g. {"sessions": 1200, "conversions": 45}'
                    ),
                },
                "summary": {
                    "type": "string",
                    "default": "",
                    "description": "Optional narrative summary of the period",
                },
            },
            "required": ["period", "metrics"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Save a report and return confirmation with the assigned ID.

        Args:
            **kwargs: period (str), metrics (str JSON), summary (str).

        Returns:
            Confirmation string or error message.
        """
        period = str(kwargs.get("period", ""))
        metrics_raw = str(kwargs.get("metrics", ""))
        summary = str(kwargs.get("summary", ""))

        try:
            metrics_dict = json.loads(metrics_raw)
        except (json.JSONDecodeError, ValueError):
            return "Invalid metrics format. Provide a JSON object with numeric values."

        if not isinstance(metrics_dict, dict):
            return "Invalid metrics format. Provide a JSON object with numeric values."

        report = self._store.save(period=period, metrics_dict=metrics_dict, summary=summary)
        metric_count = len(metrics_dict)
        return (
            f"Saved: {report['id']} — {period} "
            f"({metric_count} metric{'s' if metric_count != 1 else ''})"
        )


class GetReportTool(Tool):
    """Tool: retrieve a report by period label or report ID.

    Args:
        store: ReportStore instance to read from.
    """

    def __init__(self, store: ReportStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "get_report"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Retrieve a saved marketing report by period label (e.g. '2026-W12') "
            "or report ID (e.g. 'RPT-0001')."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "default": "",
                    "description": "Period label to search for",
                },
                "report_id": {
                    "type": "string",
                    "default": "",
                    "description": "Report ID (e.g. RPT-0001)",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Retrieve a report and return it formatted.

        Args:
            **kwargs: period (str), report_id (str).

        Returns:
            Formatted report string or error message.
        """
        period = str(kwargs.get("period", ""))
        report_id = str(kwargs.get("report_id", ""))

        report = self._store.get(period=period, report_id=report_id)
        if report is None:
            if report_id:
                return f"Report {report_id} not found."
            if period:
                return f"No report found for period '{period}'."
            return "Provide a period label or report ID."

        lines = [f"Report {report['id']} — {report['period']} ({report['created_at'][:10]})"]
        metrics: dict[str, Any] = report.get("metrics", {})
        for key, val in metrics.items():
            lines.append(f"  {key}: {val}")
        if report.get("summary"):
            lines.append(f"  Summary: {report['summary']}")
        return "\n".join(lines)


class ComparePeriodsTool(Tool):
    """Tool: compare metrics between two saved period reports.

    Args:
        store: ReportStore instance to read from.
    """

    def __init__(self, store: ReportStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "compare_periods"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Compare metrics between two saved marketing reports. "
            "Shows delta and percentage change for each metric."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "period_a": {
                    "type": "string",
                    "description": "Baseline period label (e.g. '2026-W11')",
                },
                "period_b": {
                    "type": "string",
                    "description": "Comparison period label (e.g. '2026-W12')",
                },
            },
            "required": ["period_a", "period_b"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Compare two periods and return formatted deltas.

        Args:
            **kwargs: period_a (str), period_b (str).

        Returns:
            Formatted comparison string or error message.
        """
        period_a = str(kwargs.get("period_a", ""))
        period_b = str(kwargs.get("period_b", ""))
        return self._store.compare(period_a, period_b)


class ListReportsTool(Tool):
    """Tool: list recent marketing reports, newest first.

    Args:
        store: ReportStore instance to read from.
    """

    def __init__(self, store: ReportStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "list_reports"

    @property
    def description(self) -> str:
        """Tool description."""
        return "List saved marketing reports, newest first. Shows period, date, metric count, and summary."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of reports to return",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """List reports and return formatted list.

        Args:
            **kwargs: limit (int).

        Returns:
            Formatted report list or "No reports saved yet."
        """
        limit = int(kwargs.get("limit", 10))
        reports = self._store.list_reports(limit=limit)
        if not reports:
            return "No reports saved yet."
        lines = [f"Found {len(reports)} report(s):\n"]
        for r in reports:
            metric_count = len(r.get("metrics", {}))
            date_str = r["created_at"][:10]
            summary_preview = r.get("summary", "")
            if len(summary_preview) > 60:
                summary_preview = summary_preview[:57] + "..."
            summary_part = f" — {summary_preview}" if summary_preview else ""
            lines.append(
                f"  {r['id']} — {r['period']} ({date_str}, "
                f"{metric_count} metric{'s' if metric_count != 1 else ''}){summary_part}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ReportScheduler — background service
# ---------------------------------------------------------------------------


class ReportScheduler:
    """Background service that sends a weekly report-generation prompt on schedule.

    Implements ServiceLike and RuntimeAware protocols.

    Args:
        schedule_day: Day of week to fire (e.g. "monday").
        schedule_time: HH:MM time string in the configured timezone.
        tz_name: IANA timezone name (e.g. "Europe/Berlin").
    """

    def __init__(
        self,
        schedule_day: str = "monday",
        schedule_time: str = "09:00",
        tz_name: str = "UTC",
    ) -> None:
        self._schedule_day = schedule_day.lower()
        self._schedule_time = schedule_time
        self._tz_name = tz_name
        self._process_direct: Any = None
        self._task: asyncio.Task[None] | None = None

    def set_runtime(self, refs: RuntimeRefs) -> None:
        """Accept late-bound runtime references.

        Args:
            refs: Runtime references including process_direct callback.
        """
        self._process_direct = refs.process_direct

    async def start(self) -> None:
        """Start the background scheduler loop."""
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        """Stop the background scheduler loop."""
        if self._task:
            self._task.cancel()

    def _seconds_until_next_fire(self) -> float:
        """Calculate seconds until the next scheduled fire time.

        Uses zoneinfo for timezone-aware scheduling. Falls back to UTC on error.

        Returns:
            Seconds until the next scheduled fire time (minimum 60 seconds).
        """
        try:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                tz = ZoneInfo(self._tz_name)
            except (ZoneInfoNotFoundError, Exception):
                logger.warning(
                    "campaign_reporter.unknown_tz: %s, falling back to UTC", self._tz_name
                )
                tz = ZoneInfo("UTC")

            now = datetime.now(tz)
            target_day = _DAY_MAP.get(self._schedule_day, 1)  # default Monday

            # Reason: parse schedule_time safely, default to 09:00 on error
            try:
                hour, minute = (int(p) for p in self._schedule_time.split(":"))
            except (ValueError, AttributeError):
                hour, minute = 9, 0

            # Find the next occurrence of the target weekday at target time
            days_ahead = (target_day - now.isoweekday()) % 7
            if days_ahead == 0:
                # Same weekday — check if we've already passed the time today
                if now.hour > hour or (now.hour == hour and now.minute >= minute):
                    days_ahead = 7  # fire next week

            from datetime import timedelta

            fire_dt = now.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            ) + timedelta(days=days_ahead)

            seconds = (fire_dt - now).total_seconds()
            return max(seconds, 60.0)

        except Exception:
            logger.exception("campaign_reporter.schedule_calc_failed")
            # Reason: fall back to 1 week in seconds to avoid tight loops
            return 7 * 24 * 3600.0

    async def _run(self) -> None:
        """Main loop — sleep until next scheduled time, then fire prompt."""
        while True:
            sleep_s = self._seconds_until_next_fire()
            await asyncio.sleep(sleep_s)
            try:
                prompt = (
                    "Generate this week's marketing report. "
                    "Check connected analytics sources, compile key metrics, "
                    "and save with `save_report`."
                )
                if self._process_direct:
                    await self._process_direct(
                        prompt,
                        session_key="reporter:weekly",
                        channel="cli",
                        chat_id="direct",
                    )
            except Exception:
                logger.exception("campaign_reporter.scheduler_fire_failed")


# ---------------------------------------------------------------------------
# Module-level state shared between register() and activate()
# ---------------------------------------------------------------------------

_scheduler_instance: ReportScheduler | None = None


# ---------------------------------------------------------------------------
# Plugin entry points
# ---------------------------------------------------------------------------


def register(ctx: PluginContext) -> None:
    """Plugin entry point — register report tools, context provider, and scheduler.

    Args:
        ctx: Plugin context with config and workspace.
    """
    max_reports = int(ctx.config.get("max_reports", 200))
    schedule_day = str(ctx.config.get("schedule_day", "monday"))
    schedule_time = str(ctx.config.get("schedule_time", "09:00"))
    tz_name = str(ctx.config.get("timezone", "UTC"))

    store = ReportStore(
        path=ctx.workspace / "marketing_reports.json",
        max_reports=max_reports,
    )

    ctx.register_tool(SaveReportTool(store))
    ctx.register_tool(GetReportTool(store))
    ctx.register_tool(ComparePeriodsTool(store))
    ctx.register_tool(ListReportsTool(store))

    ctx.add_context_provider(store.context_string)

    global _scheduler_instance
    scheduler = ReportScheduler(
        schedule_day=schedule_day,
        schedule_time=schedule_time,
        tz_name=tz_name,
    )
    _scheduler_instance = scheduler

    logger.debug(
        "campaign_reporter.register: max_reports=%d, schedule=%s %s (%s)",
        max_reports,
        schedule_day,
        schedule_time,
        tz_name,
    )


async def activate(ctx: PluginContext) -> None:
    """Activate the report scheduler background service.

    Args:
        ctx: Plugin context with config and workspace.
    """
    if _scheduler_instance is not None:
        ctx.register_service(_scheduler_instance)
