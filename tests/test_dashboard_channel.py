"""Tests for the Dashboard channel (Supabase Realtime Broadcast)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from velo.bus.events import OutboundMessage
from velo.bus.queue import MessageBus
from velo.channels.dashboard import DashboardChannel
from velo.config.schema import DashboardConfig


def _make_config(**overrides: object) -> DashboardConfig:
    """Create a DashboardConfig with sensible test defaults."""
    defaults = {
        "enabled": True,
        "supabase_url": "https://testref.supabase.co",
        "supabase_key": "test-service-role-key",
        "room_id": "room-123",
        "agent_id": "agent-A",
        "agent_name": "Sales Agent",
        "participants": ["Sales Agent"],
        "allow_from": ["*"],
        "max_agent_turns": 3,
        "agent_cooldown_s": 0.0,  # No delay in tests
    }
    defaults.update(overrides)
    return DashboardConfig(**defaults)


def _make_channel(config: DashboardConfig | None = None) -> DashboardChannel:
    """Create a DashboardChannel with a mocked bus."""
    cfg = config or _make_config()
    bus = MessageBus()
    bus.publish_inbound = AsyncMock()
    ch = DashboardChannel(cfg, bus)
    # Mock the Realtime channel so send() doesn't fail
    ch._channel = MagicMock()
    ch._channel.send_broadcast = AsyncMock()
    return ch


# ── send() tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_response_dropped() -> None:
    """send() with [NO_RESPONSE] content doesn't call send_broadcast."""
    ch = _make_channel()
    msg = OutboundMessage(channel="dashboard", chat_id="room-123", content="[NO_RESPONSE]")
    await ch.send(msg)
    ch._channel.send_broadcast.assert_not_called()


@pytest.mark.asyncio
async def test_no_response_with_whitespace_dropped() -> None:
    """send() with [NO_RESPONSE] surrounded by whitespace is still dropped."""
    ch = _make_channel()
    msg = OutboundMessage(channel="dashboard", chat_id="room-123", content="  [NO_RESPONSE]  ")
    await ch.send(msg)
    ch._channel.send_broadcast.assert_not_called()


@pytest.mark.asyncio
async def test_normal_message_broadcasts() -> None:
    """send() with real content calls send_broadcast with correct payload."""
    ch = _make_channel()
    msg = OutboundMessage(channel="dashboard", chat_id="room-123", content="Hello world")
    await ch.send(msg)

    ch._channel.send_broadcast.assert_called_once()
    call_args = ch._channel.send_broadcast.call_args
    assert call_args[0][0] == "agent_message"
    payload = call_args[0][1]
    assert payload["content"] == "Hello world"
    assert payload["agent_id"] == "agent-A"
    assert payload["agent_name"] == "Sales Agent"
    assert "message_id" in payload


@pytest.mark.asyncio
async def test_progress_sends_typing() -> None:
    """Progress messages broadcast as typing event."""
    ch = _make_channel()
    msg = OutboundMessage(
        channel="dashboard",
        chat_id="room-123",
        content="thinking...",
        metadata={"_progress": True},
    )
    await ch.send(msg)

    ch._channel.send_broadcast.assert_called_once()
    call_args = ch._channel.send_broadcast.call_args
    assert call_args[0][0] == "typing"
    assert call_args[0][1]["agent_id"] == "agent-A"


# ── _handle_user_message tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_resets_turn_count() -> None:
    """User message resets _agent_turn_count to 0."""
    ch = _make_channel()
    ch._agent_turn_count = 5

    payload = {"payload": {"sender_id": "user-1", "content": "hi", "sender_name": "Tin"}}
    await ch._handle_user_message(payload)

    assert ch._agent_turn_count == 0


@pytest.mark.asyncio
async def test_single_agent_no_injection() -> None:
    """Single agent (1 participant) → content is passed as-is."""
    ch = _make_channel(_make_config(participants=["Sales Agent"]))
    ch.bus.publish_inbound = AsyncMock()

    payload = {"payload": {"sender_id": "user-1", "content": "hello", "sender_name": "Tin"}}
    await ch._handle_user_message(payload)

    ch.bus.publish_inbound.assert_called_once()
    msg = ch.bus.publish_inbound.call_args[0][0]
    assert msg.content == "hello"


@pytest.mark.asyncio
async def test_multi_agent_context_injected() -> None:
    """Multiple participants → content gets room context prefix."""
    ch = _make_channel(
        _make_config(participants=["Sales Agent", "Support Agent", "Analytics Agent"])
    )
    ch.bus.publish_inbound = AsyncMock()

    payload = {"payload": {"sender_id": "user-1", "content": "what's new?", "sender_name": "Tin"}}
    await ch._handle_user_message(payload)

    ch.bus.publish_inbound.assert_called_once()
    msg = ch.bus.publish_inbound.call_args[0][0]
    assert "[Room participants: Sales Agent, Support Agent, Analytics Agent]" in msg.content
    assert "[From: Tin]" in msg.content
    assert "[NO_RESPONSE]" in msg.content
    assert "what's new?" in msg.content


@pytest.mark.asyncio
async def test_session_key_format() -> None:
    """Session key is dashboard:{room_id}."""
    ch = _make_channel()
    ch.bus.publish_inbound = AsyncMock()

    payload = {"payload": {"sender_id": "user-1", "content": "hi", "sender_name": "Tin"}}
    await ch._handle_user_message(payload)

    msg = ch.bus.publish_inbound.call_args[0][0]
    assert msg.session_key == "dashboard:room-123"


# ── _handle_agent_message tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_own_agent_message_ignored() -> None:
    """Agent's own agent_id messages are not processed."""
    ch = _make_channel()
    ch.bus.publish_inbound = AsyncMock()

    payload = {
        "payload": {
            "agent_id": "agent-A",  # Same as config agent_id
            "content": "hello from self",
            "agent_name": "Sales Agent",
        }
    }
    await ch._handle_agent_message(payload)

    ch.bus.publish_inbound.assert_not_called()


@pytest.mark.asyncio
async def test_agent_turn_limit() -> None:
    """After max_agent_turns, further agent messages are dropped."""
    ch = _make_channel(_make_config(max_agent_turns=2))
    ch.bus.publish_inbound = AsyncMock()

    base_payload = {
        "payload": {
            "agent_id": "agent-B",
            "content": "reply",
            "agent_name": "Support Agent",
        }
    }

    # First 2 should go through
    await ch._handle_agent_message(base_payload)
    await ch._handle_agent_message(base_payload)
    assert ch.bus.publish_inbound.call_count == 2

    # Third should be dropped
    await ch._handle_agent_message(base_payload)
    assert ch.bus.publish_inbound.call_count == 2


# ── _handle_stop tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_publishes_to_bus() -> None:
    """_on_stop publishes /stop InboundMessage."""
    ch = _make_channel()
    ch.bus.publish_inbound = AsyncMock()

    await ch._handle_stop({})

    ch.bus.publish_inbound.assert_called_once()
    msg = ch.bus.publish_inbound.call_args[0][0]
    assert msg.content == "/stop"
    assert msg.channel == "dashboard"
    assert msg.session_key == "dashboard:room-123"


# ── WebSocket URL builder ─────────────────────────────────────────────


def test_build_ws_url() -> None:
    """_build_ws_url extracts project ref correctly."""
    ch = _make_channel()
    url = ch._build_ws_url()
    assert url == "wss://testref.supabase.co/realtime/v1/websocket"
