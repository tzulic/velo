"""CSAT survey plugin — post-resolution satisfaction surveys.

Detects when a ticket is resolved (via update_ticket tool call) and appends
a survey invitation. Persists survey responses to workspace/csat.json.

Hooks registered:
    after_tool_call (modifying) — appends survey prompt when ticket is resolved.
    on_startup / on_shutdown (fire_and_forget) — load / save csat.json.

Config keys:
    survey_message (str): Survey invitation text appended after resolution.
    min_surveys_for_report (int): Minimum responses required to show average. Default 3.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.plugins.types import PluginContext

logger = logging.getLogger(__name__)

_CSAT_FILE = "csat.json"
_DEFAULT_SURVEY_MSG = (
    "How satisfied were you with this resolution? "
    "Please rate 1-5 and use record_csat to log your response."
)


# ---------------------------------------------------------------------------
# CSAT store
# ---------------------------------------------------------------------------


class _CSATStore:
    """Persists CSAT survey responses to a JSON file.

    Args:
        workspace: Agent workspace directory.
    """

    def __init__(self, workspace: Path) -> None:
        self._path = workspace / _CSAT_FILE
        self._responses: list[dict[str, Any]] = []

    def load(self) -> None:
        """Load CSAT responses from workspace/csat.json."""
        try:
            self._responses = json.loads(self._path.read_text())
            logger.info("csat_survey.load_completed: %d responses", len(self._responses))
        except FileNotFoundError:
            logger.info("csat_survey.no_file_found: starting fresh")
        except (OSError, json.JSONDecodeError):
            logger.exception("csat_survey.load_failed")

    def save(self) -> None:
        """Persist CSAT responses to workspace/csat.json."""
        try:
            self._path.write_text(json.dumps(self._responses, indent=2))
        except OSError:
            logger.exception("csat_survey.save_failed")

    def record(self, ticket_id: str, score: int, comment: str = "") -> None:
        """Record a CSAT survey response.

        Args:
            ticket_id: Ticket the survey is for.
            score: Satisfaction score 1–5 (clamped to valid range).
            comment: Optional free-text comment.
        """
        clamped = max(1, min(5, score))
        self._responses.append(
            {
                "ticket_id": ticket_id,
                "score": clamped,
                "comment": comment,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.save()
        logger.info("csat_survey.recorded: ticket=%s score=%d", ticket_id, clamped)

    def get_report(self, min_surveys: int = 3) -> str:
        """Return aggregated CSAT statistics.

        Args:
            min_surveys: Minimum responses needed to display the average.

        Returns:
            Formatted CSAT report string.
        """
        total = len(self._responses)
        if total == 0:
            return "CSAT: No surveys recorded yet."
        scores = [r["score"] for r in self._responses]
        avg = sum(scores) / total
        if total < min_surveys:
            return f"CSAT: {total} survey(s) recorded (need {min_surveys} for average)."
        dist: dict[int, int] = {}
        for s in scores:
            dist[s] = dist.get(s, 0) + 1
        dist_str = ", ".join(f"{k}★:{v}" for k, v in sorted(dist.items()))
        return f"CSAT: {avg:.1f}/5 avg ({total} surveys) — {dist_str}"

    def get_summary(self) -> str:
        """Return a one-line summary for the context provider.

        Returns:
            Brief CSAT status string.
        """
        total = len(self._responses)
        if total == 0:
            return "CSAT: 0 surveys"
        avg = sum(r["score"] for r in self._responses) / total
        return f"CSAT: {avg:.1f}/5 avg ({total} surveys)"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class RecordCSATTool(Tool):
    """Tool: record a CSAT survey response.

    Args:
        store: CSAT store to write to.
    """

    def __init__(self, store: _CSATStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "record_csat"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Record a customer satisfaction score (1–5) for a resolved ticket."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "Ticket ID (e.g. TKT-0001)",
                },
                "score": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Satisfaction score 1 (very dissatisfied) to 5 (very satisfied)",
                },
                "comment": {
                    "type": "string",
                    "default": "",
                    "description": "Optional free-text feedback",
                },
            },
            "required": ["ticket_id", "score"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Record the CSAT response and confirm.

        Args:
            **kwargs: ticket_id (str), score (int), comment (str).

        Returns:
            Confirmation message.
        """
        ticket_id = str(kwargs.get("ticket_id", ""))
        score = int(kwargs.get("score", 3))
        comment = str(kwargs.get("comment", ""))
        self._store.record(ticket_id, score, comment)
        return f"CSAT recorded for {ticket_id}: {score}/5. Thank you for your feedback!"


class GetCSATReportTool(Tool):
    """Tool: retrieve the CSAT survey report.

    Args:
        store: CSAT store to query.
        min_surveys: Minimum responses required to show average.
    """

    def __init__(self, store: _CSATStore, min_surveys: int) -> None:
        self._store = store
        self._min_surveys = min_surveys

    @property
    def name(self) -> str:
        """Tool name."""
        return "get_csat_report"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Get the CSAT satisfaction survey report with average scores and distribution."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema — no parameters required."""
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> str:
        """Return the full CSAT report.

        Args:
            **kwargs: Not used.

        Returns:
            Formatted CSAT report string.
        """
        return self._store.get_report(self._min_surveys)


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def setup(ctx: PluginContext) -> None:
    """Plugin entry point — register CSAT tools, survey hook, and context.

    Args:
        ctx: Plugin context with config and workspace.
    """
    survey_message: str = ctx.config.get("survey_message", _DEFAULT_SURVEY_MSG)
    min_surveys = int(ctx.config.get("min_surveys_for_report", 3))

    store = _CSATStore(ctx.workspace)

    def on_after_tool_call(
        value: str, tool_name: str = "", params: str = "", **_: Any
    ) -> str:
        """Append survey invitation when a ticket is marked resolved.

        Args:
            value: Tool call result text.
            tool_name: Name of the tool that was called.
            params: JSON-encoded parameters passed to the tool.

        Returns:
            Result with survey invitation appended if applicable.
        """
        if tool_name != "update_ticket":
            return value
        try:
            parsed: dict[str, Any] = json.loads(params)
        except (json.JSONDecodeError, TypeError):
            return value
        if parsed.get("status") != "resolved":
            return value
        ticket_id = str(parsed.get("ticket_id", ""))
        return value + f"\n\n[Survey] {survey_message} (ticket: {ticket_id})"

    def on_startup() -> None:
        """Load persisted CSAT responses on startup."""
        store.load()

    def on_shutdown() -> None:
        """Persist CSAT responses on shutdown."""
        store.save()

    ctx.on("after_tool_call", on_after_tool_call)
    ctx.on("on_startup", on_startup)
    ctx.on("on_shutdown", on_shutdown)
    ctx.register_tool(RecordCSATTool(store))
    ctx.register_tool(GetCSATReportTool(store, min_surveys))
    ctx.add_context_provider(store.get_summary)

    logger.debug("csat_survey.setup_completed: min_surveys=%d", min_surveys)
