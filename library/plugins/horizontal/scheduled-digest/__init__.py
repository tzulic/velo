"""Scheduled digest plugin — sends periodic AI-generated digests via the agent.

Starts a background asyncio task that fires at the configured time and injects
a digest prompt via process_direct. The digest prompt instructs the agent to
gather the configured sections and deliver them to the owner.

Config keys:
    frequency (str): "daily" or "weekly". Default "daily".
    time (str): HH:MM in 24-hour format. Default "08:00".
    timezone (str): IANA timezone name. Default "UTC".
    owner_telegram_id (str): Telegram chat ID for delivery. Default "".
    sections (list[str]): Topics to include. Default [].
    channel (str): Delivery channel name. Default "telegram".
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from velo.agent.tools.base import Tool
from velo.plugins.types import PluginContext, RuntimeRefs

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scheduling helper
# ---------------------------------------------------------------------------


def _compute_next_fire(frequency: str, time_str: str, tz_name: str) -> datetime:
    """Compute the next scheduled fire time.

    Args:
        frequency: "daily" or "weekly" (Monday).
        time_str: HH:MM string in 24-hour format.
        tz_name: IANA timezone name (e.g. "Europe/London").

    Returns:
        Next fire datetime (timezone-aware).

    Raises:
        ValueError: If time_str cannot be parsed as HH:MM.
    """
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning("scheduled_digest.invalid_timezone: %s, falling back to UTC", tz_name)
        tz = ZoneInfo("UTC")

    # Raises ValueError if malformed — intentional, caller logs and aborts
    hour, minute = (int(part) for part in time_str.split(":"))

    now = datetime.now(tz)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if frequency == "weekly":
        # Next Monday at the given time
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0 and now >= candidate:
            days_until_monday = 7
        candidate = (now + timedelta(days=days_until_monday)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
    else:
        # Daily — advance by one day if today's slot already passed
        if now >= candidate:
            candidate += timedelta(days=1)

    return candidate


# ---------------------------------------------------------------------------
# Digest service
# ---------------------------------------------------------------------------


class _DigestService:
    """Background service that fires scheduled digests via process_direct.

    Implements ServiceLike and RuntimeAware protocols.

    Args:
        frequency: "daily" or "weekly".
        time_str: HH:MM string.
        timezone: IANA timezone name.
        owner_telegram_id: Telegram chat ID for delivery.
        sections: Digest topics to include.
    """

    def __init__(
        self,
        frequency: str,
        time_str: str,
        timezone: str,
        owner_telegram_id: str,
        sections: list[str],
    ) -> None:
        self._frequency = frequency
        self._time_str = time_str
        self._timezone = timezone
        self._owner_telegram_id = owner_telegram_id
        self._sections = sections
        self._process_direct: Callable[..., Awaitable[str]] | None = None
        self._task: asyncio.Task[None] | None = None
        self._next_fire: datetime | None = None

    def set_runtime(self, refs: RuntimeRefs) -> None:
        """Store process_direct from late-bound runtime refs.

        Args:
            refs: Runtime references provided after agent loop creation.
        """
        self._process_direct = refs.process_direct

    async def start(self) -> None:
        """Compute next fire time and start the scheduler task."""
        try:
            self._next_fire = _compute_next_fire(self._frequency, self._time_str, self._timezone)
        except ValueError:
            logger.error("scheduled_digest.invalid_time: %s — service not started", self._time_str)
            return
        self._task = asyncio.create_task(self._run())
        logger.info("scheduled_digest.started: next=%s", self._get_next_str())

    def stop(self) -> None:
        """Cancel the scheduler task."""
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        """Main scheduler loop — sleep until fire time, send, recompute."""
        while True:
            if self._next_fire is None:
                break
            now = datetime.now(self._next_fire.tzinfo)
            wait_seconds = (self._next_fire - now).total_seconds()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            try:
                await self._send_digest()
            except Exception:
                logger.exception("scheduled_digest.send_failed")
            # Recompute after every fire to handle DST drift
            try:
                self._next_fire = _compute_next_fire(
                    self._frequency, self._time_str, self._timezone
                )
            except ValueError:
                break

    async def _send_digest(self) -> None:
        """Inject the digest prompt via process_direct."""
        if self._process_direct is None:
            logger.warning("scheduled_digest.send_skipped: process_direct not available")
            return

        sections_text = "\n".join(f"- {s}" for s in self._sections)
        prompt = (
            f"[Scheduled digest] Please prepare the {self._frequency} digest.\n"
            f"Include these sections:\n{sections_text}\n"
            "Keep it concise and actionable."
        )
        if self._owner_telegram_id:
            prompt += f" Deliver to {self._owner_telegram_id} via Telegram."

        logger.info("scheduled_digest.sending")
        await self._process_direct(
            prompt,
            session_key="digest",
            channel="cli",
            chat_id="digest",
        )

    async def send_now(self) -> str:
        """Send the digest immediately (called by the tool).

        Returns:
            Confirmation or error message.
        """
        try:
            await self._send_digest()
            return "Digest sent successfully."
        except Exception as exc:
            logger.exception("scheduled_digest.send_now_failed")
            return f"Failed to send digest: {exc}"

    def _get_next_str(self) -> str:
        """Return human-readable next-fire description for context provider.

        Returns:
            Next digest schedule string.
        """
        if self._next_fire is None:
            return "Next digest: not scheduled"
        return f"Next digest: {self._next_fire.strftime('%a %Y-%m-%d %H:%M')} {self._timezone}"


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class SendDigestNowTool(Tool):
    """Tool to immediately trigger a digest without waiting for the schedule.

    Args:
        service: The digest service to invoke.
    """

    def __init__(self, service: _DigestService) -> None:
        self._service = service

    @property
    def name(self) -> str:
        """Tool name."""
        return "send_digest_now"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Send the scheduled digest immediately without waiting for the next scheduled time."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema — no parameters required."""
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> str:
        """Trigger immediate digest delivery.

        Args:
            **kwargs: Not used.

        Returns:
            Confirmation or error message.
        """
        return await self._service.send_now()


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def setup(ctx: PluginContext) -> None:
    """Plugin entry point — register digest service, tool, and context provider.

    Args:
        ctx: Plugin context with config and workspace.
    """
    service = _DigestService(
        frequency=ctx.config.get("frequency", "daily"),
        time_str=ctx.config.get("time", "08:00"),
        timezone=ctx.config.get("timezone", "UTC"),
        owner_telegram_id=ctx.config.get("owner_telegram_id", ""),
        sections=ctx.config.get("sections", []),
    )

    ctx.register_service(service)
    ctx.register_tool(SendDigestNowTool(service))
    ctx.add_context_provider(service._get_next_str)

    logger.debug("scheduled_digest.setup_completed")
