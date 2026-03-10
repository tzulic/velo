"""Rate limiter plugin — sliding-window throttling (global and per-channel).

Hooks registered:
    before_response (modifying) — blocks response if limit exceeded; returns cooldown message.

Config keys:
    window_seconds (int): Window size in seconds. Default 60.
    max_messages (int): Max messages per window (global). Default 60.
    per_channel_max (int): Max messages per channel per window. 0 = disabled. Default 0.
    cooldown_response (str): Reply when throttled. Default "Rate limit reached. Please wait a moment."
"""

from __future__ import annotations

import logging
from collections import deque
from time import time
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.plugins.types import PluginContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiter core
# ---------------------------------------------------------------------------


class _RateLimiter:
    """Sliding-window rate limiter with optional per-channel tracking.

    Args:
        window_seconds: Duration of the sliding window in seconds.
        max_messages: Global message limit within the window.
        per_channel_max: Per-channel limit (0 = disabled).
    """

    def __init__(
        self,
        window_seconds: int = 60,
        max_messages: int = 60,
        per_channel_max: int = 0,
    ) -> None:
        self._window = window_seconds
        self._max = max_messages
        self._per_channel_max = per_channel_max
        self._global_times: deque[float] = deque()
        # Reason: only allocate per-channel tracking when feature is enabled
        self._per_channel: dict[str, deque[float]] = {}

    def _purge_old(self, times: deque[float], now: float) -> None:
        """Remove timestamps that have fallen outside the current window.

        Args:
            times: Deque of epoch timestamps to prune.
            now: Current epoch time.
        """
        cutoff = now - self._window
        while times and times[0] < cutoff:
            times.popleft()

    def check(self, chat_id: str) -> bool:
        """Check whether a message is allowed and record it if so.

        Args:
            chat_id: Channel/chat identifier used for per-channel tracking.

        Returns:
            True if the message is allowed, False if throttled.
        """
        now = time()
        self._purge_old(self._global_times, now)

        if len(self._global_times) >= self._max:
            return False

        if self._per_channel_max > 0 and chat_id:
            channel_times = self._per_channel.setdefault(chat_id, deque())
            self._purge_old(channel_times, now)
            if len(channel_times) >= self._per_channel_max:
                return False
            channel_times.append(now)

        self._global_times.append(now)
        return True

    def get_status(self, chat_id: str = "") -> str:
        """Return human-readable rate limit usage.

        Args:
            chat_id: Optional channel ID for per-channel stats.

        Returns:
            Status string like "N/max in last Xs".
        """
        now = time()
        self._purge_old(self._global_times, now)
        lines = [
            f"Global: {len(self._global_times)}/{self._max} in last {self._window}s"
        ]
        if self._per_channel_max > 0 and chat_id and chat_id in self._per_channel:
            ch = self._per_channel[chat_id]
            self._purge_old(ch, now)
            lines.append(
                f"Channel '{chat_id}': {len(ch)}/{self._per_channel_max}"
                f" in last {self._window}s"
            )
        return "\n".join(lines)

    def get_global_summary(self) -> str:
        """Return a brief global usage line for the context provider.

        Returns:
            One-line summary string.
        """
        now = time()
        self._purge_old(self._global_times, now)
        return (
            f"Rate limiter: {len(self._global_times)}/{self._max}"
            f" msgs in last {self._window}s"
        )


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class GetRateLimitStatusTool(Tool):
    """Tool: query current rate limit usage.

    Args:
        limiter: The rate limiter instance to query.
    """

    def __init__(self, limiter: _RateLimiter) -> None:
        self._limiter = limiter

    @property
    def name(self) -> str:
        """Tool name."""
        return "get_rate_limit_status"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Get current rate limit usage (global and per-channel if enabled)."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "default": "",
                    "description": "Channel ID to include per-channel stats (optional).",
                }
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Return current rate limit status.

        Args:
            **kwargs: chat_id (str) — optional channel for per-channel stats.

        Returns:
            Formatted status string.
        """
        chat_id = str(kwargs.get("chat_id", ""))
        return self._limiter.get_status(chat_id)


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def setup(ctx: PluginContext) -> None:
    """Plugin entry point — register rate limiter hook, tool, and context.

    Args:
        ctx: Plugin context with config and workspace.
    """
    window_seconds = int(ctx.config.get("window_seconds", 60))
    max_messages = int(ctx.config.get("max_messages", 60))
    per_channel_max = int(ctx.config.get("per_channel_max", 0))
    cooldown_response: str = ctx.config.get(
        "cooldown_response", "Rate limit reached. Please wait a moment."
    )

    limiter = _RateLimiter(
        window_seconds=window_seconds,
        max_messages=max_messages,
        per_channel_max=per_channel_max,
    )

    def on_before_response(value: str, chat_id: str = "", **_: Any) -> str:
        """Check rate limit; return cooldown message if throttled.

        Args:
            value: The outgoing response text.
            chat_id: Channel identifier for per-channel tracking.

        Returns:
            Original value if allowed, cooldown_response if throttled.
        """
        if not limiter.check(chat_id):
            logger.info("rate_limiter.throttled: chat_id=%s", chat_id)
            return cooldown_response
        return value

    ctx.on("before_response", on_before_response)
    ctx.register_tool(GetRateLimitStatusTool(limiter))
    ctx.add_context_provider(limiter.get_global_summary)

    logger.debug(
        "rate_limiter.setup_completed: window=%ds max=%d per_channel_max=%d",
        window_seconds,
        max_messages,
        per_channel_max,
    )
