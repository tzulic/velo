"""Tests for cross-channel cron delivery override."""

import pytest


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
