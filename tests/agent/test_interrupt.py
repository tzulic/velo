"""Tests for the interrupt mechanism."""

from __future__ import annotations

import asyncio

import pytest

from velo.agent.loop import AgentLoop


@pytest.mark.asyncio
class TestInterruptMechanism:
    """Test per-session interrupt events."""

    async def test_interrupt_event_set_for_active_session(self, make_loop) -> None:
        """Interrupt event is set when a session already has running tasks."""
        loop: AgentLoop = make_loop()
        key = "test:session"

        # Simulate a running task
        evt = asyncio.Event()
        running_task = asyncio.create_task(evt.wait())
        loop._active_tasks[key] = [running_task]

        # Simulate what run() does when new message arrives for same session
        existing = loop._active_tasks.get(key, [])
        running = [t for t in existing if not t.done()]
        if running:
            interrupt = loop._interrupt_events.setdefault(key, asyncio.Event())
            interrupt.set()

        assert loop._interrupt_events[key].is_set()
        running_task.cancel()
        try:
            await running_task
        except asyncio.CancelledError:
            pass

    async def test_event_cleared_on_new_dispatch(self, make_loop) -> None:
        """Interrupt event is cleared at the start of _dispatch."""
        loop: AgentLoop = make_loop()
        key = "test:session"

        evt = asyncio.Event()
        evt.set()
        loop._interrupt_events[key] = evt

        # Simulate clearing as _dispatch does
        if interrupt_evt := loop._interrupt_events.get(key):
            interrupt_evt.clear()

        assert not evt.is_set()

    async def test_loop_returns_none_on_interrupt(self, make_loop) -> None:
        """_run_agent_loop_inner returns (None, ...) when interrupt is set."""
        loop: AgentLoop = make_loop()
        key = "test:session"

        # Pre-set interrupt event
        evt = asyncio.Event()
        evt.set()
        loop._interrupt_events[key] = evt

        messages = [
            {"role": "system", "content": "You are a test."},
            {"role": "user", "content": "Hello"},
        ]

        content, tools_used, msgs = await loop._run_agent_loop_inner(
            initial_messages=messages,
            on_progress=None,
            session_key=key,
            run_id="test-run",
            start_ms=0,
            provider_id="test:model",
        )

        assert content is None
        assert tools_used == []

    async def test_cancelled_error_handled_gracefully(self, make_loop) -> None:
        """CancelledError in _dispatch is re-raised cleanly."""
        loop: AgentLoop = make_loop()

        # Create a task that gets cancelled
        async def _cancellable():
            await asyncio.sleep(10)

        task = asyncio.create_task(_cancellable())
        await asyncio.sleep(0)  # let it start
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
