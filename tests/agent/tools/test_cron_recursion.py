"""Tests for cron recursion guard — one-shot vs repeating in cron context."""

import pytest

from velo.agent.tools.cron import CronTool


@pytest.mark.asyncio
async def test_repeating_job_blocked_in_cron_context(cron_tool: CronTool):
    """Repeating jobs (every_seconds) must be blocked inside cron context."""
    token = cron_tool.set_cron_context(True)
    try:
        result = await cron_tool.execute(
            action="add",
            message="repeating task",
            every_seconds=300,
        )
        assert "Error" in result
        assert "repeating" in result.lower()
    finally:
        cron_tool.reset_cron_context(token)


@pytest.mark.asyncio
async def test_oneshot_job_allowed_in_cron_context(cron_tool: CronTool):
    """One-shot jobs (at=...) should pass the recursion guard inside cron context."""
    token = cron_tool.set_cron_context(True)
    try:
        result = await cron_tool.execute(
            action="add",
            message="one-shot reminder",
            at="2026-04-01T10:00:00",
        )
        assert "Error" not in result
        assert "Created job" in result
    finally:
        cron_tool.reset_cron_context(token)


@pytest.mark.asyncio
async def test_cron_expr_blocked_in_cron_context(cron_tool: CronTool):
    """Cron expression schedules must be blocked inside cron context."""
    token = cron_tool.set_cron_context(True)
    try:
        result = await cron_tool.execute(
            action="add",
            message="weekly standup",
            cron_expr="0 9 * * 1",
        )
        assert "Error" in result
        assert "repeating" in result.lower()
    finally:
        cron_tool.reset_cron_context(token)


@pytest.mark.asyncio
async def test_list_allowed_in_cron_context(cron_tool: CronTool):
    """Listing jobs should always be allowed, even inside cron context."""
    token = cron_tool.set_cron_context(True)
    try:
        result = await cron_tool.execute(action="list")
        assert "Error" not in result
    finally:
        cron_tool.reset_cron_context(token)
