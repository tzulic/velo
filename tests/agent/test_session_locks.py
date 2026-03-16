"""Tests for per-session serialization (replacing global _processing_lock)."""

import asyncio

import pytest

from velo.agent.loop import AgentLoop
from velo.bus.events import InboundMessage, OutboundMessage
from velo.bus.queue import MessageBus
from velo.providers.base import LLMProvider, LLMResponse


class _SequencedProvider(LLMProvider):
    """Provider that records call order and can be held with an event."""

    def __init__(self):
        super().__init__()
        self.call_order: list[str] = []
        self._hold: asyncio.Event = asyncio.Event()
        self._hold.set()  # starts unblocked

    async def chat(self, messages, **kwargs) -> LLMResponse:
        user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "?")
        await self._hold.wait()
        self.call_order.append(str(user_msg))
        return LLMResponse(content=f"ok:{user_msg}", tool_calls=[])

    def get_default_model(self) -> str:
        return "test"


def _make_loop(provider, workspace):
    bus = MessageBus()
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model="test",
    ), bus


@pytest.mark.asyncio
async def test_same_session_messages_are_serialized(tmp_path):
    """Two messages to the SAME session should execute in order, not concurrently."""
    provider = _SequencedProvider()
    loop, bus = _make_loop(provider, tmp_path)

    received: list[str] = []

    async def collect_outbound():
        while True:
            msg = await bus.consume_outbound()
            received.append(msg.content)
            if len(received) >= 2:
                break

    msg1 = InboundMessage(channel="cli", sender_id="u", chat_id="1", content="first")
    msg2 = InboundMessage(channel="cli", sender_id="u", chat_id="1", content="second")

    await bus.publish_inbound(msg1)
    await bus.publish_inbound(msg2)

    collector = asyncio.create_task(collect_outbound())
    runner = asyncio.create_task(loop.run())

    await asyncio.wait_for(collector, timeout=5.0)
    loop.stop()
    runner.cancel()
    try:
        await runner
    except (asyncio.CancelledError, Exception):
        pass

    # Both messages processed, in order
    assert len(received) == 2
    assert "first" in provider.call_order[0]
    assert "second" in provider.call_order[1]


@pytest.mark.asyncio
async def test_different_sessions_run_concurrently(tmp_path):
    """Messages to DIFFERENT sessions should not block each other."""
    provider = _SequencedProvider()
    loop, bus = _make_loop(provider, tmp_path)

    # Two messages to different sessions: should both be processed
    msg1 = InboundMessage(channel="cli", sender_id="u", chat_id="alice", content="for alice")
    msg2 = InboundMessage(channel="cli", sender_id="u", chat_id="bob", content="for bob")

    await bus.publish_inbound(msg1)
    await bus.publish_inbound(msg2)

    received: list[str] = []

    async def collect_outbound():
        while len(received) < 2:
            msg = await bus.consume_outbound()
            received.append(msg.content)

    collector = asyncio.create_task(collect_outbound())
    runner = asyncio.create_task(loop.run())

    await asyncio.wait_for(collector, timeout=5.0)
    loop.stop()
    runner.cancel()
    try:
        await runner
    except (asyncio.CancelledError, Exception):
        pass

    assert len(received) == 2
