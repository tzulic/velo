"""Iteration budget — shared cap across parent agent and subagents."""

from __future__ import annotations

import asyncio


class IterationBudget:
    """Thread-safe (async) iteration budget shared between parent and subagents.

    Uses an asyncio Lock so concurrent subagent tasks don't race on the counter.
    Warnings are injected at 70% and 90% usage to nudge the LLM toward wrapping up.
    """

    _WARN_70 = 0.70
    _WARN_90 = 0.90

    def __init__(self, total: int) -> None:
        """Initialize budget.

        Args:
            total: Maximum number of LLM iterations allowed across all agents.
        """
        self._total = total
        self._used = 0
        self._lock = asyncio.Lock()

    async def consume(self) -> bool:
        """Consume one iteration. Returns False if budget is exhausted.

        Returns:
            True if the iteration was granted, False if budget is spent.
        """
        async with self._lock:
            if self._used >= self._total:
                return False
            self._used += 1
            return True

    async def refund(self, count: int = 1) -> None:
        """Refund iterations (e.g. on early exit before API call).

        Args:
            count: Number of iterations to refund.
        """
        async with self._lock:
            self._used = max(0, self._used - count)

    @property
    def remaining(self) -> int:
        """Number of iterations still available."""
        return max(0, self._total - self._used)

    @property
    def used(self) -> int:
        """Number of iterations consumed so far."""
        return self._used

    def warning_message(self) -> str | None:
        """Return a warning string when approaching budget limits, or None.

        Returns:
            Warning string at 70%/90% usage, None otherwise.
        """
        if self._total <= 0:
            return None
        ratio = self._used / self._total
        if ratio >= self._WARN_90:
            return (
                f"[Budget warning: {self._used}/{self._total} iterations used "
                f"({self.remaining} remaining). Wrap up immediately — "
                "summarize results and stop using tools.]"
            )
        if ratio >= self._WARN_70:
            return (
                f"[Budget warning: {self._used}/{self._total} iterations used "
                f"({self.remaining} remaining). Start wrapping up.]"
            )
        return None
