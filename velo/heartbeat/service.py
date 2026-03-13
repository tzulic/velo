"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

if TYPE_CHECKING:
    from velo.providers.base import LLMProvider
    from velo.session.manager import SessionManager

_HEARTBEAT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "heartbeat",
            "description": "Report heartbeat decision after reviewing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["skip", "run"],
                        "description": "skip = nothing to do, run = has active tasks",
                    },
                    "tasks": {
                        "type": "string",
                        "description": "Natural-language summary of active tasks (required for run)",
                    },
                },
                "required": ["action"],
            },
        },
    }
]

_DEDUP_WINDOW_H = 24  # Suppress identical heartbeat within this window


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    Phase 1 (decision): reads HEARTBEAT.md and asks the LLM — via a virtual
    tool call — whether there are active tasks.  This avoids free-text parsing
    and the unreliable HEARTBEAT_OK token.

    Phase 2 (execution): only triggered when Phase 1 returns ``run``.  The
    ``on_execute`` callback runs the task through the full agent loop and
    returns the result to deliver.

    Features:
    - Deduplication: suppresses re-delivery of identical responses within 24h.
    - Quiet hours: suppresses ``on_notify`` delivery during a configured window.
    - Event-driven wake: ``push_event()`` triggers an immediate tick without
      waiting for the full interval.
    """

    def __init__(
        self,
        workspace: Path,
        provider: "LLMProvider",
        model: str,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,
        enabled: bool = True,
        quiet_start: str | None = None,
        quiet_end: str | None = None,
        quiet_timezone: str = "UTC",
        session_manager: "SessionManager | None" = None,
    ):
        """Initialize the heartbeat service.

        Args:
            workspace (Path): Agent workspace directory.
            provider (LLMProvider): LLM provider for Phase 1 decisions.
            model (str): Model identifier to use for heartbeat decisions.
            on_execute (Callable | None): Callback to run agent task; returns result text.
            on_notify (Callable | None): Callback to deliver result to user.
            interval_s (int): Seconds between heartbeat ticks (default 30 min).
            enabled (bool): Whether the service should run.
            quiet_start (str | None): Quiet hours start "HH:MM" (e.g. "23:00").
            quiet_end (str | None): Quiet hours end "HH:MM" (e.g. "07:00").
            quiet_timezone (str): IANA timezone name for quiet hours (default "UTC").
            session_manager (SessionManager | None): If provided, dedup state is persisted
                to the "heartbeat" session so it survives process restarts.
        """
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.interval_s = interval_s
        self.enabled = enabled
        self.quiet_start = quiet_start
        self.quiet_end = quiet_end
        self.quiet_timezone = quiet_timezone
        # Pre-parse quiet hours config to avoid repeated string parsing on every tick
        self._quiet_tz: ZoneInfo | None = None
        self._quiet_start_minutes: int | None = None
        self._quiet_end_minutes: int | None = None
        if quiet_start and quiet_end:
            try:
                self._quiet_tz = ZoneInfo(quiet_timezone)
                sh, sm = (int(x) for x in quiet_start.split(":"))
                eh, em = (int(x) for x in quiet_end.split(":"))
                self._quiet_start_minutes = sh * 60 + sm
                self._quiet_end_minutes = eh * 60 + em
            except (ZoneInfoNotFoundError, ValueError, AttributeError):
                logger.warning(
                    "heartbeat.quiet_hours_invalid: start={} end={} tz={}",
                    quiet_start,
                    quiet_end,
                    quiet_timezone,
                )
        self._session_manager = session_manager
        self._running = False
        self._task: asyncio.Task | None = None
        # Event queue for immediate wake (event-driven heartbeat)
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # In-memory deduplication state (seeded from persisted session on start)
        self._last_heartbeat_text: str | None = None
        self._last_heartbeat_at: datetime | None = None

    @property
    def heartbeat_file(self) -> Path:
        """Path to HEARTBEAT.md in the workspace."""
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        """Read HEARTBEAT.md contents, returning None if missing or unreadable."""
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def push_event(self, event: dict[str, Any]) -> None:
        """Push an event to trigger an immediate heartbeat tick.

        Args:
            event (dict): Event payload, e.g. {"type": "subagent_complete", "summary": "…"}.
        """
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # Drop if queue is full; next scheduled tick will pick it up

    async def _decide(self, content: str) -> tuple[str, str]:
        """Phase 1: ask LLM to decide skip/run via virtual tool call.

        Args:
            content (str): HEARTBEAT.md content.

        Returns:
            tuple[str, str]: (action, tasks) where action is 'skip' or 'run'.
        """
        response = await self.provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision.",
                },
                {
                    "role": "user",
                    "content": (
                        "Review the following HEARTBEAT.md and decide whether there are active tasks.\n\n"
                        f"{content}"
                    ),
                },
            ],
            tools=_HEARTBEAT_TOOL,
            model=self.model,
        )

        if not response.has_tool_calls:
            return "skip", ""

        args = response.tool_calls[0].arguments
        return args.get("action", "skip"), args.get("tasks", "")

    def _in_quiet_hours(self) -> bool:
        """Return True if the current time falls within the configured quiet window.

        Handles midnight wrap-around (e.g. 23:00 → 07:00).

        Returns:
            bool: True if notifications should be suppressed.
        """
        if self._quiet_tz is None or self._quiet_start_minutes is None or self._quiet_end_minutes is None:
            return False
        now = datetime.now(self._quiet_tz)
        now_minutes = now.hour * 60 + now.minute
        start = self._quiet_start_minutes
        end = self._quiet_end_minutes
        if start <= end:
            # Same-day window: e.g. 09:00–17:00
            return start <= now_minutes < end
        else:
            # Midnight wrap: e.g. 23:00–07:00
            return now_minutes >= start or now_minutes < end

    def _is_duplicate(self, text: str) -> bool:
        """Check if a heartbeat response is identical to the last one within 24h.

        Args:
            text (str): Candidate response text.

        Returns:
            bool: True if this response should be suppressed.
        """
        if self._last_heartbeat_text != text:
            return False
        if self._last_heartbeat_at is None:
            return False
        age_h = (datetime.now(timezone.utc) - self._last_heartbeat_at).total_seconds() / 3600
        return age_h < _DEDUP_WINDOW_H

    def _record_delivery(self, text: str) -> None:
        """Record that a heartbeat was delivered.

        Updates in-memory state and persists to the session store so dedup
        survives process restarts.

        Args:
            text (str): The delivered response text.
        """
        self._last_heartbeat_text = text
        self._last_heartbeat_at = datetime.now(timezone.utc)
        if self._session_manager is not None:
            try:
                session = self._session_manager.get_or_create("heartbeat")
                session.last_heartbeat_text = text
                session.last_heartbeat_at = self._last_heartbeat_at
                self._session_manager.save(session)
            except Exception as e:
                logger.warning("heartbeat.dedup_persist_failed: {}", e)

    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return
        if self._running:
            logger.warning("Heartbeat already running")
            return

        # Seed in-memory dedup state from persisted session so restarts don't
        # re-deliver the same response that was already sent before the restart.
        if self._session_manager is not None:
            session = self._session_manager.get_or_create("heartbeat")
            self._last_heartbeat_text = session.last_heartbeat_text
            self._last_heartbeat_at = session.last_heartbeat_at
            if self._last_heartbeat_text:
                logger.debug(
                    "heartbeat.dedup_loaded: last_at={}",
                    self._last_heartbeat_at,
                )

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started (every {}s)", self.interval_s)

    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """Main heartbeat loop — sleeps for interval_s or until an event arrives."""
        while self._running:
            try:
                # Wait for the interval or an external event, whichever comes first.
                try:
                    event = await asyncio.wait_for(
                        self._event_queue.get(), timeout=self.interval_s
                    )
                    logger.debug("heartbeat.event_wake: type={}", event.get("type"))
                    await self._tick(event=event)
                except asyncio.TimeoutError:
                    if self._running:
                        await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error: {}", e)

    async def _tick(self, event: dict[str, Any] | None = None) -> None:
        """Execute a single heartbeat tick.

        Args:
            event (dict | None): If provided, an event that triggered this tick
                                  (e.g. subagent completion). When present, Phase 1
                                  is skipped and the event summary feeds Phase 2.
        """
        # If triggered by an event, skip Phase 1 and build the task summary from the event.
        if event is not None:
            summary = event.get("summary", "")
            task_prompt = f"Background task completed: {summary}" if summary else "Background task completed."
            await self._execute_and_notify(task_prompt)
            return

        content = self._read_heartbeat_file()
        if not content:
            logger.debug("Heartbeat: HEARTBEAT.md missing or empty")
            return

        logger.info("Heartbeat: checking for tasks...")

        try:
            action, tasks = await self._decide(content)

            if action != "run":
                logger.info("Heartbeat: OK (nothing to report)")
                return

            logger.info("Heartbeat: tasks found, executing...")
            await self._execute_and_notify(tasks)
        except Exception:
            logger.exception("Heartbeat execution failed")

    async def _execute_and_notify(self, task_prompt: str) -> None:
        """Run Phase 2 (execute) and deliver the result if not suppressed.

        Args:
            task_prompt (str): Task summary to pass to on_execute.
        """
        if not self.on_execute:
            return

        response = await self.on_execute(task_prompt)

        if not response:
            return

        # Deduplication: suppress if identical response was delivered within 24h
        if self._is_duplicate(response):
            logger.info("heartbeat.suppressed_duplicate: identical response within {}h", _DEDUP_WINDOW_H)
            return

        # Quiet hours: suppress notification but record delivery state
        if self._in_quiet_hours():
            logger.info("heartbeat.quiet_hours_suppressed: skipping on_notify")
            self._record_delivery(response)
            return

        if self.on_notify:
            logger.info("Heartbeat: completed, delivering response")
            await self.on_notify(response)
            self._record_delivery(response)

    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat.

        Returns:
            str | None: The agent's response, or None if nothing to do.
        """
        content = self._read_heartbeat_file()
        if not content:
            return None
        action, tasks = await self._decide(content)
        if action != "run" or not self.on_execute:
            return None
        return await self.on_execute(tasks)
