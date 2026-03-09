"""Shared fixtures for agent tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus


@pytest.fixture
def make_loop():
    """Factory fixture for creating a minimal AgentLoop for testing."""
    def _factory(**overrides: Any) -> AgentLoop:
        bus = MessageBus()
        provider = AsyncMock()
        provider.get_default_model = lambda: "test-model"
        return AgentLoop(
            bus=bus,
            provider=provider,
            workspace=Path("/tmp/test-workspace"),
            **overrides,
        )
    return _factory
