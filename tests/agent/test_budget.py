"""Tests for iteration budget."""

from __future__ import annotations

import asyncio

import pytest

from velo.agent.budget import IterationBudget


@pytest.mark.asyncio
class TestIterationBudget:
    """Test IterationBudget consume/remaining/warning behavior."""

    async def test_consume_and_remaining(self) -> None:
        """Consuming decrements remaining and increments used."""
        budget = IterationBudget(total=5)
        assert budget.remaining == 5
        assert budget.used == 0

        assert await budget.consume() is True
        assert budget.remaining == 4
        assert budget.used == 1

    async def test_exhaustion_returns_false(self) -> None:
        """consume() returns False once total is reached."""
        budget = IterationBudget(total=2)
        assert await budget.consume() is True
        assert await budget.consume() is True
        assert await budget.consume() is False
        assert budget.remaining == 0

    async def test_refund(self) -> None:
        """Refunding restores available iterations."""
        budget = IterationBudget(total=3)
        await budget.consume()
        await budget.consume()
        assert budget.remaining == 1

        await budget.refund(1)
        assert budget.remaining == 2
        assert budget.used == 1

    async def test_refund_does_not_go_negative(self) -> None:
        """Refunding more than used clamps to zero used."""
        budget = IterationBudget(total=3)
        await budget.consume()
        await budget.refund(5)
        assert budget.used == 0
        assert budget.remaining == 3

    async def test_warning_at_70_percent(self) -> None:
        """Warning message appears at 70% usage."""
        budget = IterationBudget(total=10)
        for _ in range(7):
            await budget.consume()
        msg = budget.warning_message()
        assert msg is not None
        assert "7/10" in msg
        assert "Start wrapping up" in msg

    async def test_warning_at_90_percent(self) -> None:
        """Warning escalates at 90% usage."""
        budget = IterationBudget(total=10)
        for _ in range(9):
            await budget.consume()
        msg = budget.warning_message()
        assert msg is not None
        assert "9/10" in msg
        assert "Wrap up immediately" in msg

    async def test_no_warning_below_70_percent(self) -> None:
        """No warning when usage is below 70%."""
        budget = IterationBudget(total=10)
        for _ in range(6):
            await budget.consume()
        assert budget.warning_message() is None

    async def test_concurrent_usage(self) -> None:
        """Concurrent consume calls don't exceed total."""
        budget = IterationBudget(total=10)

        async def _consume_one() -> bool:
            return await budget.consume()

        results = await asyncio.gather(*[_consume_one() for _ in range(15)])
        granted = sum(1 for r in results if r)
        assert granted == 10
        assert budget.remaining == 0
