"""Tests for cross-channel cron delivery override."""

import pytest
from unittest.mock import MagicMock
from velo.agent.tools.cron import CronTool
from velo.cron.service import CronService


@pytest.fixture
def cron_tool():
    service = MagicMock(spec=CronService)
    mock_job = MagicMock()
    mock_job.name = "test"
    mock_job.id = "j123"
    service.add_job.return_value = mock_job
    tool = CronTool(service)
    tool.set_context("telegram", "12345")
    return tool


@pytest.mark.asyncio
async def test_default_delivery_uses_origin(cron_tool):
    """Without deliver_channel, uses origin session context."""
    await cron_tool.execute(action="add", message="remind me", at="2026-04-01T10:00:00")
    call_kwargs = cron_tool._cron.add_job.call_args
    assert call_kwargs.kwargs["channel"] == "telegram"
    assert call_kwargs.kwargs["to"] == "12345"


@pytest.mark.asyncio
async def test_cross_channel_override(cron_tool):
    """deliver_channel overrides the origin channel."""
    await cron_tool.execute(
        action="add",
        message="remind me",
        at="2026-04-01T10:00:00",
        deliver_channel="discord",
        deliver_chat_id="99999",
    )
    call_kwargs = cron_tool._cron.add_job.call_args
    assert call_kwargs.kwargs["channel"] == "discord"
    assert call_kwargs.kwargs["to"] == "99999"
