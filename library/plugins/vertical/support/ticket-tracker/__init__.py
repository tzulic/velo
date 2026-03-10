"""Ticket tracker plugin — CRUD ticket management with JSON persistence.

Hooks: before_response (modifying) enriches TKT-XXXX refs with live status;
on_startup/on_shutdown load/save tickets.json.
Config: auto_link_responses (bool) — default true.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.plugins.types import PluginContext

logger = logging.getLogger(__name__)

_TICKET_RE = re.compile(r"TKT-(\d{4})")
_TICKETS_FILE = "tickets.json"
VALID_STATUSES = {"open", "in-progress", "resolved", "closed"}
VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}


@dataclass
class _Ticket:
    id: str
    title: str
    description: str
    status: str
    priority: str
    created_at: str
    updated_at: str


class _TicketStore:
    """Manages ticket CRUD and JSON persistence.

    Args:
        workspace: Agent workspace directory.
    """

    def __init__(self, workspace: Path) -> None:
        self._path = workspace / _TICKETS_FILE
        self._tickets: dict[str, _Ticket] = {}
        self._counter: int = 0

    def load(self) -> None:
        """Load tickets from workspace/tickets.json."""
        try:
            raw: list[dict[str, Any]] = json.loads(self._path.read_text())
            for item in raw:
                t = _Ticket(**item)
                self._tickets[t.id] = t
            nums = [int(tid.split("-")[1]) for tid in self._tickets]
            self._counter = max(nums, default=0)
            logger.info("ticket_tracker.load_completed: %d tickets", len(self._tickets))
        except FileNotFoundError:
            logger.info("ticket_tracker.no_file_found: starting fresh")
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            logger.exception("ticket_tracker.load_failed")

    def save(self) -> None:
        """Persist tickets to workspace/tickets.json."""
        try:
            self._path.write_text(
                json.dumps([asdict(t) for t in self._tickets.values()], indent=2)
            )
        except OSError:
            logger.exception("ticket_tracker.save_failed")

    def create(self, title: str, description: str = "", priority: str = "P2") -> _Ticket:
        """Create, store, and return a new ticket."""
        if priority not in VALID_PRIORITIES:
            priority = "P2"
        self._counter += 1
        now = datetime.now(timezone.utc).isoformat()
        t = _Ticket(
            id=f"TKT-{self._counter:04d}",
            title=title,
            description=description,
            status="open",
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        self._tickets[t.id] = t
        logger.info("ticket_tracker.created: %s %s", t.id, priority)
        return t

    def update(self, ticket_id: str, **fields: Any) -> _Ticket | None:
        """Update allowed fields on a ticket. Returns ticket or None if not found."""
        t = self._tickets.get(ticket_id.upper())
        if t is None:
            return None
        for key, val in fields.items():
            if key == "status" and val in VALID_STATUSES:
                t.status = str(val)
            elif key == "priority" and val in VALID_PRIORITIES:
                t.priority = str(val)
            elif key in ("title", "description"):
                setattr(t, key, str(val))
        t.updated_at = datetime.now(timezone.utc).isoformat()
        self.save()
        return t

    def get(self, ticket_id: str) -> _Ticket | None:
        """Retrieve a ticket by ID."""
        return self._tickets.get(ticket_id.upper())

    def list(self, status_filter: str = "", priority_filter: str = "") -> list[_Ticket]:
        """List tickets with optional status/priority filters, sorted by ID."""
        tickets = list(self._tickets.values())
        if status_filter:
            tickets = [t for t in tickets if t.status == status_filter]
        if priority_filter:
            tickets = [t for t in tickets if t.priority == priority_filter]
        return sorted(tickets, key=lambda t: t.id)

    def get_summary(self) -> str:
        """Return open-ticket count and priority breakdown for context provider."""
        open_t = [t for t in self._tickets.values() if t.status == "open"]
        if not open_t:
            return "Open tickets: 0"
        by_p: dict[str, int] = {}
        for t in open_t:
            by_p[t.priority] = by_p.get(t.priority, 0) + 1
        detail = ", ".join(f"{p}: {c}" for p, c in sorted(by_p.items()))
        return f"Open tickets: {len(open_t)} ({detail})"


def _fmt(t: _Ticket) -> str:
    """Format a ticket for display."""
    return (
        f"{t.id} [{t.priority}] {t.status.upper()}\n"
        f"  Title: {t.title}\n"
        f"  Description: {t.description}\n"
        f"  Created: {t.created_at} | Updated: {t.updated_at}"
    )



class CreateTicketTool(Tool):
    def __init__(self, store: _TicketStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "create_ticket"

    @property
    def description(self) -> str:
        return "Create a new support ticket with title, description, and priority."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short ticket title"},
                "description": {"type": "string", "default": ""},
                "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"], "default": "P2"},
            },
            "required": ["title"],
        }

    async def execute(self, **kwargs: Any) -> str:
        t = self._store.create(
            title=str(kwargs.get("title", "")),
            description=str(kwargs.get("description", "")),
            priority=str(kwargs.get("priority", "P2")),
        )
        return f"Created {_fmt(t)}"


class UpdateTicketTool(Tool):
    def __init__(self, store: _TicketStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "update_ticket"

    @property
    def description(self) -> str:
        return "Update status, title, description, or priority of an existing ticket."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "Ticket ID (e.g. TKT-0001)"},
                "status": {"type": "string", "enum": ["open", "in-progress", "resolved", "closed"]},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
            },
            "required": ["ticket_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        ticket_id = str(kwargs.get("ticket_id", ""))
        fields = {k: v for k, v in kwargs.items() if k != "ticket_id"}
        t = self._store.update(ticket_id, **fields)
        return f"Updated {_fmt(t)}" if t else f"Ticket not found: {ticket_id}"


class GetTicketTool(Tool):
    def __init__(self, store: _TicketStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "get_ticket"

    @property
    def description(self) -> str:
        return "Retrieve a support ticket by its ID."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "Ticket ID (e.g. TKT-0001)"},
            },
            "required": ["ticket_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        ticket_id = str(kwargs.get("ticket_id", ""))
        t = self._store.get(ticket_id)
        return _fmt(t) if t else f"Ticket not found: {ticket_id}"


class ListTicketsTool(Tool):
    def __init__(self, store: _TicketStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "list_tickets"

    @property
    def description(self) -> str:
        return "List support tickets, optionally filtered by status or priority."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string", "default": "", "description": "Filter by status (empty = all)"},
                "priority": {"type": "string", "default": "", "description": "Filter by priority (empty = all)"},
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        tickets = self._store.list(
            status_filter=str(kwargs.get("status", "")),
            priority_filter=str(kwargs.get("priority", "")),
        )
        return "\n\n".join(_fmt(t) for t in tickets) if tickets else "No tickets found."


def setup(ctx: PluginContext) -> None:
    """Plugin entry point — register ticket tools, hooks, and context provider.

    Args:
        ctx: Plugin context with config and workspace.
    """
    auto_link: bool = bool(ctx.config.get("auto_link_responses", True))
    store = _TicketStore(ctx.workspace)

    if auto_link:

        def _replace(match: re.Match[str]) -> str:
            tid = f"TKT-{match.group(1)}"
            t = store.get(tid)
            return f"{tid} (status: {t.status}, {t.priority})" if t else tid

        ctx.on("before_response", lambda value, **_: _TICKET_RE.sub(_replace, value))

    ctx.on("on_startup", lambda: store.load())
    ctx.on("on_shutdown", lambda: store.save())
    ctx.register_tool(CreateTicketTool(store))
    ctx.register_tool(UpdateTicketTool(store))
    ctx.register_tool(GetTicketTool(store))
    ctx.register_tool(ListTicketsTool(store))
    ctx.add_context_provider(store.get_summary)

    logger.debug("ticket_tracker.setup_completed: auto_link=%s", auto_link)
