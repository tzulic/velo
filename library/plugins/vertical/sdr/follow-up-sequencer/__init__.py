"""Follow-up sequencer plugin — automated multi-step follow-up sequences for SDR outreach.

Tools registered:
    create_sequence — create a follow-up sequence for a lead
    list_sequences — list sequences with optional status filter
    pause_sequence — pause an active sequence
    resume_sequence — resume a paused sequence
    cancel_sequence — cancel a sequence permanently

Background service:
    SequenceRunner — checks for due follow-ups every N minutes, sends via process_direct

Hook:
    agent_end — detects follow-up commitments in assistant responses

Context provider:
    One-line summary: "Follow-ups: N active, X due today, Y due this week"

Config keys:
    check_interval_minutes (int): Minutes between follow-up checks. Default 5.
    max_sequences (int): Maximum active sequences. Default 50.
    default_channel (str): Default delivery channel. Default "email".
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from velo.agent.tools.base import Tool
from velo.plugins.types import PluginContext, RuntimeRefs
from velo.utils.helpers import atomic_write

logger = logging.getLogger(__name__)

VALID_CHANNELS = {"email", "telegram", "whatsapp"}
VALID_STATUSES = {"active", "paused", "completed", "cancelled"}
DONE_STATUSES = {"completed", "cancelled"}

DEFAULT_STEPS = [
    {"delay_days": 1, "message_hint": "Quick follow-up"},
    {"delay_days": 3, "message_hint": "Share relevant resource"},
    {"delay_days": 7, "message_hint": "Final check-in"},
]


# ---------------------------------------------------------------------------
# SequenceStore
# ---------------------------------------------------------------------------


class SequenceStore:
    """JSON-backed follow-up sequence storage with query and summary capabilities.

    Args:
        path: Path to sequences.json file.
        max_sequences: Maximum number of active sequences allowed.
    """

    def __init__(self, path: Path, max_sequences: int = 50) -> None:
        self._path = path
        self._max_sequences = max_sequences
        self._sequences: list[dict[str, Any]] = []
        self._next_id = 1
        self._load()

    def _load(self) -> None:
        """Load sequences from disk."""
        if self._path.is_file():
            try:
                self._sequences = json.loads(self._path.read_text(encoding="utf-8"))
                if self._sequences:
                    max_num = max(int(s["id"].split("-")[1]) for s in self._sequences)
                    self._next_id = max_num + 1
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.warning("sequencer.load_failed: %s", self._path)
                self._sequences = []

    def _save(self) -> None:
        """Write sequences to disk atomically."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self._path, json.dumps(self._sequences, indent=2, ensure_ascii=False))

    def _now_iso(self) -> str:
        """Return current UTC time as ISO string."""
        return datetime.now(timezone.utc).isoformat()

    def create(
        self,
        lead_name: str,
        lead_contact: str,
        channel: str,
        steps: str = "",
    ) -> dict[str, Any] | None:
        """Create a new follow-up sequence. Returns None if at max capacity.

        Args:
            lead_name: Name of the lead.
            lead_contact: Contact info (email, phone, handle).
            channel: Delivery channel — email, telegram, or whatsapp.
            steps: Optional JSON string of steps array. Uses DEFAULT_STEPS if empty.

        Returns:
            New sequence dict, or None if max_sequences limit reached.
        """
        active = [s for s in self._sequences if s["status"] not in DONE_STATUSES]
        if len(active) >= self._max_sequences:
            return None

        # Reason: parse steps from JSON string if provided, otherwise use defaults
        if steps:
            parsed_steps = json.loads(steps)
        else:
            parsed_steps = [dict(s) for s in DEFAULT_STEPS]

        # Reason: ensure each step has a sent_at field for tracking
        for step in parsed_steps:
            if "sent_at" not in step:
                step["sent_at"] = None

        now = self._now_iso()
        first_delay = parsed_steps[0]["delay_days"] if parsed_steps else 1
        next_due = (
            datetime.now(timezone.utc) + timedelta(days=first_delay)
        ).isoformat()

        seq: dict[str, Any] = {
            "id": f"SEQ-{self._next_id:04d}",
            "lead_name": lead_name,
            "lead_contact": lead_contact,
            "channel": channel,
            "status": "active",
            "steps": parsed_steps,
            "current_step": 0,
            "created_at": now,
            "next_due_at": next_due,
        }
        self._next_id += 1
        self._sequences.append(seq)
        self._save()
        return seq

    def list_sequences(self, status: str = "") -> list[dict[str, Any]]:
        """List sequences with optional status filter.

        Args:
            status: Filter by exact status. Empty string returns all.

        Returns:
            Filtered list of sequence dicts.
        """
        if status:
            return [s for s in self._sequences if s["status"] == status]
        return list(self._sequences)

    def pause(self, sequence_id: str) -> bool:
        """Pause an active sequence.

        Args:
            sequence_id: Sequence ID (e.g. SEQ-0001).

        Returns:
            True if paused, False if not found or not active.
        """
        for seq in self._sequences:
            if seq["id"] == sequence_id:
                if seq["status"] != "active":
                    return False
                seq["status"] = "paused"
                self._save()
                return True
        return False

    def resume(self, sequence_id: str) -> dict[str, Any] | None:
        """Resume a paused sequence, recalculating next_due_at from now.

        Args:
            sequence_id: Sequence ID (e.g. SEQ-0001).

        Returns:
            Updated sequence dict if resumed, None if not found, False if not paused.
        """
        for seq in self._sequences:
            if seq["id"] == sequence_id:
                if seq["status"] != "paused":
                    return None
                seq["status"] = "active"
                # Reason: recalculate next_due from now based on current step's delay
                current = seq["current_step"]
                if current < len(seq["steps"]):
                    delay = seq["steps"][current]["delay_days"]
                    seq["next_due_at"] = (
                        datetime.now(timezone.utc) + timedelta(days=delay)
                    ).isoformat()
                self._save()
                return seq
        return None

    def cancel(self, sequence_id: str) -> bool:
        """Cancel a sequence permanently.

        Args:
            sequence_id: Sequence ID (e.g. SEQ-0001).

        Returns:
            True if cancelled, False if not found.
        """
        for seq in self._sequences:
            if seq["id"] == sequence_id:
                seq["status"] = "cancelled"
                self._save()
                return True
        return False

    def get(self, sequence_id: str) -> dict[str, Any] | None:
        """Get a single sequence by ID.

        Args:
            sequence_id: Sequence ID (e.g. SEQ-0001).

        Returns:
            Sequence dict if found, None otherwise.
        """
        for seq in self._sequences:
            if seq["id"] == sequence_id:
                return seq
        return None

    def get_due(self) -> list[dict[str, Any]]:
        """Return sequences where status=active and next_due_at <= now.

        Returns:
            List of due sequence dicts.
        """
        now = datetime.now(timezone.utc).isoformat()
        return [
            s for s in self._sequences
            if s["status"] == "active" and s.get("next_due_at", "") <= now
        ]

    def advance_step(self, sequence_id: str) -> bool:
        """Mark current step as sent, increment current_step, calculate next_due_at.

        If last step, sets status to completed.

        Args:
            sequence_id: Sequence ID (e.g. SEQ-0001).

        Returns:
            True if advanced, False if not found.
        """
        for seq in self._sequences:
            if seq["id"] == sequence_id:
                current = seq["current_step"]
                if current < len(seq["steps"]):
                    seq["steps"][current]["sent_at"] = self._now_iso()

                seq["current_step"] = current + 1

                if seq["current_step"] >= len(seq["steps"]):
                    # Reason: all steps completed
                    seq["status"] = "completed"
                    seq["next_due_at"] = None
                else:
                    # Reason: calculate next due from now using next step's delay
                    next_delay = seq["steps"][seq["current_step"]]["delay_days"]
                    seq["next_due_at"] = (
                        datetime.now(timezone.utc) + timedelta(days=next_delay)
                    ).isoformat()

                self._save()
                return True
        return False

    def get_summary(self) -> dict[str, int]:
        """Get sequence counts for context provider (single-pass).

        Returns:
            Dict with active, due_today, and due_this_week counts.
        """
        now = datetime.now(timezone.utc)
        today_end = now.replace(hour=23, minute=59, second=59)
        week_end = now + timedelta(days=7)

        active = 0
        due_today = 0
        due_this_week = 0

        for s in self._sequences:
            if s["status"] != "active":
                continue
            active += 1
            next_due = s.get("next_due_at")
            if not next_due:
                continue
            try:
                due_dt = datetime.fromisoformat(next_due)
            except (ValueError, TypeError):
                continue
            if due_dt <= today_end:
                due_today += 1
            if due_dt <= week_end:
                due_this_week += 1

        return {"active": active, "due_today": due_today, "due_this_week": due_this_week}

    def context_string(self) -> str:
        """One-line context for system prompt injection.

        Returns:
            Summary string like "Follow-ups: 5 active, 1 due today, 2 due this week".
        """
        s = self.get_summary()
        if s["active"] == 0:
            return "Follow-ups: none"
        parts = [f"{s['active']} active"]
        if s["due_today"]:
            parts.append(f"{s['due_today']} due today")
        if s["due_this_week"]:
            parts.append(f"{s['due_this_week']} due this week")
        return f"Follow-ups: {', '.join(parts)}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class CreateSequenceTool(Tool):
    """Tool: create a new follow-up sequence.

    Args:
        store: SequenceStore instance to write to.
        default_channel: Default delivery channel from config.
    """

    def __init__(self, store: SequenceStore, default_channel: str = "email") -> None:
        self._store = store
        self._default_channel = default_channel

    @property
    def name(self) -> str:
        """Tool name."""
        return "create_sequence"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Create a follow-up sequence for a lead. Specify lead name, contact info, "
            "delivery channel (email/telegram/whatsapp), and optional custom steps."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "lead_name": {"type": "string", "description": "Name of the lead"},
                "lead_contact": {
                    "type": "string",
                    "description": "Contact info (email, phone, or handle)",
                },
                "channel": {
                    "type": "string",
                    "default": self._default_channel,
                    "enum": sorted(VALID_CHANNELS),
                    "description": "Delivery channel for follow-ups",
                },
                "steps": {
                    "type": "string",
                    "default": "",
                    "description": (
                        'JSON array of steps, e.g. '
                        '[{"delay_days": 1, "message_hint": "Follow up on call"}]. '
                        "Uses default 3-step sequence if empty."
                    ),
                },
            },
            "required": ["lead_name", "lead_contact"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Create a sequence and return confirmation.

        Args:
            **kwargs: lead_name (str), lead_contact (str), channel (str), steps (str).

        Returns:
            Confirmation string or error message.
        """
        lead_name = str(kwargs.get("lead_name", ""))
        lead_contact = str(kwargs.get("lead_contact", ""))
        channel = str(kwargs.get("channel", "")) or self._default_channel

        if channel not in VALID_CHANNELS:
            return f"Invalid channel '{channel}'. Valid: email, telegram, whatsapp"

        steps_str = str(kwargs.get("steps", ""))
        if steps_str:
            try:
                parsed = json.loads(steps_str)
                if not isinstance(parsed, list):
                    raise ValueError("not a list")
                for step in parsed:
                    if "delay_days" not in step or "message_hint" not in step:
                        raise ValueError("missing required fields")
            except (json.JSONDecodeError, ValueError):
                return (
                    "Invalid steps format. Provide a JSON array of "
                    "{delay_days, message_hint} objects."
                )

        seq = self._store.create(
            lead_name=lead_name,
            lead_contact=lead_contact,
            channel=channel,
            steps=steps_str,
        )
        if seq is None:
            return (
                f"Sequence limit reached ({self._store._max_sequences}). "
                "Complete or cancel existing sequences."
            )
        step_count = len(seq["steps"])
        return (
            f"Created: {seq['id']} — {lead_name} via {channel}, "
            f"{step_count} steps, next due: {seq['next_due_at']}"
        )


class ListSequencesTool(Tool):
    """Tool: list follow-up sequences with optional status filter.

    Args:
        store: SequenceStore instance to read from.
    """

    def __init__(self, store: SequenceStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "list_sequences"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "List follow-up sequences. Optionally filter by status "
            "(active, paused, completed, cancelled)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "default": "",
                    "description": "Filter by status",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """List sequences matching the given filter.

        Args:
            **kwargs: status (str).

        Returns:
            Formatted sequence list or "No sequences found."
        """
        status = str(kwargs.get("status", ""))
        sequences = self._store.list_sequences(status=status)
        if not sequences:
            return "No sequences found."
        lines = [f"Found {len(sequences)} sequence(s):\n"]
        for s in sequences:
            step_info = f"step {s['current_step'] + 1}/{len(s['steps'])}"
            due = f", next due: {s['next_due_at']}" if s.get("next_due_at") else ""
            lines.append(
                f"  {s['id']} — {s['lead_name']} [{s['status']}] ({step_info}{due})"
            )
        return "\n".join(lines)


class PauseSequenceTool(Tool):
    """Tool: pause an active follow-up sequence.

    Args:
        store: SequenceStore instance to write to.
    """

    def __init__(self, store: SequenceStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "pause_sequence"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Pause an active follow-up sequence by its ID."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "sequence_id": {
                    "type": "string",
                    "description": "Sequence ID (e.g. SEQ-0001)",
                },
            },
            "required": ["sequence_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Pause a sequence and return confirmation.

        Args:
            **kwargs: sequence_id (str) required.

        Returns:
            Confirmation string or error message.
        """
        sequence_id = str(kwargs.get("sequence_id", ""))
        seq = self._store.get(sequence_id)
        if seq is None:
            return f"Sequence {sequence_id} not found."
        if self._store.pause(sequence_id):
            return f"Paused sequence {sequence_id} ({seq['lead_name']})."
        return f"Sequence {sequence_id} is not active (status: {seq['status']})."


class ResumeSequenceTool(Tool):
    """Tool: resume a paused follow-up sequence.

    Args:
        store: SequenceStore instance to write to.
    """

    def __init__(self, store: SequenceStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "resume_sequence"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Resume a paused follow-up sequence, recalculating the next due date from now."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "sequence_id": {
                    "type": "string",
                    "description": "Sequence ID (e.g. SEQ-0001)",
                },
            },
            "required": ["sequence_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Resume a sequence and return confirmation with next due date.

        Args:
            **kwargs: sequence_id (str) required.

        Returns:
            Confirmation string or error message.
        """
        sequence_id = str(kwargs.get("sequence_id", ""))
        seq = self._store.get(sequence_id)
        if seq is None:
            return f"Sequence {sequence_id} not found."
        result = self._store.resume(sequence_id)
        if result is None:
            return f"Sequence {sequence_id} is not paused (status: {seq['status']})."
        return (
            f"Resumed sequence {sequence_id} ({result['lead_name']}). "
            f"Next due: {result['next_due_at']}"
        )


class CancelSequenceTool(Tool):
    """Tool: cancel a follow-up sequence permanently.

    Args:
        store: SequenceStore instance to write to.
    """

    def __init__(self, store: SequenceStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "cancel_sequence"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Permanently cancel a follow-up sequence by its ID."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "sequence_id": {
                    "type": "string",
                    "description": "Sequence ID (e.g. SEQ-0001)",
                },
            },
            "required": ["sequence_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Cancel a sequence and return confirmation.

        Args:
            **kwargs: sequence_id (str) required.

        Returns:
            Confirmation string or error message.
        """
        sequence_id = str(kwargs.get("sequence_id", ""))
        if self._store.cancel(sequence_id):
            return f"Cancelled sequence {sequence_id}."
        return f"Sequence {sequence_id} not found."


# ---------------------------------------------------------------------------
# SequenceRunner — background service
# ---------------------------------------------------------------------------


class SequenceRunner:
    """Background service that checks for due follow-ups and sends them.

    Implements ServiceLike and RuntimeAware protocols.

    Args:
        store: SequenceStore instance to check for due sequences.
        interval_s: Seconds between checks. Default 300 (5 minutes).
    """

    def __init__(self, store: SequenceStore, interval_s: int = 300) -> None:
        self._store = store
        self._interval_s = interval_s
        self._process_direct: Any = None
        self._task: asyncio.Task[None] | None = None

    def set_runtime(self, refs: RuntimeRefs) -> None:
        """Accept late-bound runtime references.

        Args:
            refs: Runtime references including process_direct callback.
        """
        self._process_direct = refs.process_direct

    async def start(self) -> None:
        """Start the background check loop."""
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        """Stop the background check loop."""
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        """Main loop — sleep then check for due sequences."""
        while True:
            await asyncio.sleep(self._interval_s)
            try:
                for seq in self._store.get_due():
                    step = seq["steps"][seq["current_step"]]
                    prompt = (
                        f"[Follow-up Task] Send follow-up #{seq['current_step'] + 1} "
                        f"to {seq['lead_name']} ({seq['lead_contact']}) via {seq['channel']}.\n"
                        f"Message hint: {step['message_hint']}\n"
                        f"Compose and send the message now."
                    )
                    if self._process_direct:
                        await self._process_direct(
                            prompt,
                            session_key=f"sequencer:{seq['id']}",
                            channel="cli",
                            chat_id="direct",
                        )
                    self._store.advance_step(seq["id"])
            except Exception:
                logger.exception("sequencer.tick_failed")


# ---------------------------------------------------------------------------
# Hook callback
# ---------------------------------------------------------------------------


def _on_agent_end(messages: list[Any], duration_ms: int, **kwargs: Any) -> None:
    """Detect follow-up commitments in the last assistant response.

    Scans the final assistant message for phrases indicating a follow-up promise.
    This is advisory only — the agent decides whether to act on it.

    Args:
        messages: Full conversation message list.
        duration_ms: Duration of the agent turn in milliseconds.
        **kwargs: Additional hook arguments (ignored).
    """
    assistant_msgs = [
        m for m in messages
        if isinstance(m, dict) and m.get("role") == "assistant"
    ]
    if not assistant_msgs:
        return
    last_content = str(assistant_msgs[-1].get("content", ""))
    phrases = [
        "i'll follow up",
        "let me check back",
        "i'll send you",
        "i'll get back to you",
        "follow up with you",
    ]
    if any(p in last_content.lower() for p in phrases):
        logger.info("sequencer.follow_up_detected: possible commitment in response")


# ---------------------------------------------------------------------------
# Module-level state shared between register() and activate()
# ---------------------------------------------------------------------------

_runner_instance: SequenceRunner | None = None


# ---------------------------------------------------------------------------
# Plugin entry points
# ---------------------------------------------------------------------------


def register(ctx: PluginContext) -> None:
    """Plugin entry point — register sequence tools, hook, and context provider.

    Args:
        ctx: Plugin context with config and workspace.
    """
    max_sequences = int(ctx.config.get("max_sequences", 50))
    default_channel = str(ctx.config.get("default_channel", "email"))
    interval_minutes = int(ctx.config.get("check_interval_minutes", 5))

    store = SequenceStore(
        path=ctx.workspace / "sequences.json",
        max_sequences=max_sequences,
    )

    # Register 5 tools
    ctx.register_tool(CreateSequenceTool(store, default_channel=default_channel))
    ctx.register_tool(ListSequencesTool(store))
    ctx.register_tool(PauseSequenceTool(store))
    ctx.register_tool(ResumeSequenceTool(store))
    ctx.register_tool(CancelSequenceTool(store))

    # Register agent_end hook
    ctx.on("agent_end", _on_agent_end)

    # Register context provider
    ctx.add_context_provider(store.context_string)

    # Create runner instance for activate()
    global _runner_instance
    runner = SequenceRunner(store, interval_s=interval_minutes * 60)
    _runner_instance = runner

    logger.debug(
        "sequencer.register: max_sequences=%d, default_channel=%s, interval=%dm",
        max_sequences,
        default_channel,
        interval_minutes,
    )


async def activate(ctx: PluginContext) -> None:
    """Activate the sequencer background service.

    Args:
        ctx: Plugin context with config and workspace.
    """
    if _runner_instance is not None:
        ctx.register_service(_runner_instance)
