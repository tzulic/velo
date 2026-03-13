"""Tests for subagent depth and concurrency limits."""

import asyncio

import pytest

from velo.agent.subagent import SubagentManager
from velo.providers.base import LLMProvider, LLMResponse


class _DummyProvider(LLMProvider):
    async def chat(self, *args, **kwargs) -> LLMResponse:
        return LLMResponse(content="done", tool_calls=[])

    def get_default_model(self) -> str:
        return "dummy"


@pytest.fixture
def manager(tmp_path):
    from velo.bus.queue import MessageBus

    return SubagentManager(
        provider=_DummyProvider(),
        workspace=tmp_path,
        bus=MessageBus(),
    )


@pytest.mark.asyncio
async def test_depth_zero_allowed(manager):
    """Top-level spawn (depth=0) should be accepted."""
    result = await manager.spawn(
        "write a haiku", session_key="cli:user", depth=0
    )
    assert "started" in result.lower() or "subagent" in result.lower()


@pytest.mark.asyncio
async def test_depth_limit_blocks_nested_spawn(manager):
    """Spawn at depth >= MAX_SPAWN_DEPTH should return error string."""
    result = await manager.spawn(
        "spawn inside spawn", session_key="cli:user", depth=1
    )
    assert "blocked" in result.lower() or "Error" in result


@pytest.mark.asyncio
async def test_concurrency_limit_blocks_excess(manager):
    """Spawning more than MAX_CHILDREN_PER_SESSION returns error string."""
    session = "test:session"
    manager.MAX_CHILDREN_PER_SESSION = 2  # type: ignore[assignment]
    manager._active_count_per_session[session] = 2  # Simulate 2 already running

    result = await manager.spawn("extra task", session_key=session)
    assert "blocked" in result.lower() or "Error" in result


@pytest.mark.asyncio
async def test_active_count_incremented_on_spawn(manager):
    """Successful spawn increments the per-session active count."""
    session = "test:sess2"
    await manager.spawn("task1", session_key=session)
    assert manager._active_count_per_session.get(session, 0) >= 1


@pytest.mark.asyncio
async def test_active_count_decremented_after_completion(manager):
    """Active count returns to 0 after the task completes."""
    session = "test:sess3"
    await manager.spawn("quick task", session_key=session)
    # Allow the background task to run
    await asyncio.sleep(0.1)
    # After completion the count should be 0 (cleaned up)
    assert manager._active_count_per_session.get(session, 0) == 0
