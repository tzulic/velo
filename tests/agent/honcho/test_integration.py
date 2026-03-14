"""Integration tests for Honcho + AgentLoop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from velo.agent.honcho.adapter import HonchoSessionState
from velo.agent.honcho.config import HonchoConfig
from velo.agent.loop import AgentLoop
from velo.bus.queue import MessageBus


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace directory with required structure."""
    (tmp_path / "memory").mkdir()
    (tmp_path / "skills").mkdir()
    return tmp_path


@pytest.fixture
def mock_provider():
    """Mock LLM provider."""
    provider = AsyncMock()
    provider.get_default_model.return_value = "test-model"
    return provider


@pytest.fixture
def bus():
    """Message bus."""
    return MessageBus()


class TestHonchoEnabled:
    """Tests for AgentLoop with Honcho enabled."""

    def test_registers_three_tools_when_enabled(self, bus, mock_provider, workspace):
        """AgentLoop registers honcho_search, honcho_query, honcho_note when Honcho is configured."""
        honcho_config = HonchoConfig(
            enabled=True, api_key="test-key", workspace_id="test-ws"
        )

        # Reason: HonchoAdapter.__init__ is lazy — no Honcho import happens
        # until get_or_create() is called, so no patching needed for init.
        loop = AgentLoop(
            bus=bus,
            provider=mock_provider,
            workspace=workspace,
            honcho_config=honcho_config,
        )

        assert loop.tools.has("honcho_search")
        assert loop.tools.has("honcho_query")
        assert loop.tools.has("honcho_note")
        assert loop._honcho is not None

    def test_honcho_adapter_set_on_context(self, bus, mock_provider, workspace):
        """AgentLoop sets Honcho adapter on ContextBuilder."""
        honcho_config = HonchoConfig(
            enabled=True, api_key="test-key", workspace_id="test-ws"
        )

        loop = AgentLoop(
            bus=bus,
            provider=mock_provider,
            workspace=workspace,
            honcho_config=honcho_config,
        )

        assert loop.context._honcho is not None


class TestHonchoDisabled:
    """Tests for AgentLoop with Honcho disabled or unconfigured."""

    def test_no_tools_when_disabled(self, bus, mock_provider, workspace):
        """AgentLoop does not register Honcho tools when disabled."""
        honcho_config = HonchoConfig(enabled=False, api_key="test-key")

        loop = AgentLoop(
            bus=bus,
            provider=mock_provider,
            workspace=workspace,
            honcho_config=honcho_config,
        )

        assert not loop.tools.has("honcho_search")
        assert not loop.tools.has("honcho_query")
        assert not loop.tools.has("honcho_note")
        assert loop._honcho is None

    def test_no_tools_when_no_api_key(self, bus, mock_provider, workspace):
        """AgentLoop does not register Honcho tools when api_key is empty."""
        honcho_config = HonchoConfig(enabled=True, api_key="")

        loop = AgentLoop(
            bus=bus,
            provider=mock_provider,
            workspace=workspace,
            honcho_config=honcho_config,
        )

        assert not loop.tools.has("honcho_search")
        assert loop._honcho is None

    def test_no_crash_without_honcho_config(self, bus, mock_provider, workspace):
        """AgentLoop works fine when honcho_config is None."""
        loop = AgentLoop(
            bus=bus,
            provider=mock_provider,
            workspace=workspace,
        )

        assert loop._honcho is None
        assert not loop.tools.has("honcho_search")


class TestContextInjection:
    """Tests for Honcho context injection into user message runtime block."""

    async def test_context_injected_when_available(self, bus, mock_provider, workspace):
        """build_messages injects Honcho context into user message runtime block."""
        honcho_config = HonchoConfig(
            enabled=True, api_key="test-key", workspace_id="test-ws"
        )

        loop = AgentLoop(
            bus=bus,
            provider=mock_provider,
            workspace=workspace,
            honcho_config=honcho_config,
        )

        # Simulate prefetched context by injecting a session state directly
        loop._honcho.set_current_session("test:session")
        loop._honcho._sessions["test:session"] = HonchoSessionState(
            session_key="test:session",
            context_cache="User is a data scientist",
        )

        # Honcho context should NOT be in system prompt
        prompt = await loop.context.build_system_prompt()
        assert "User Context (Honcho)" not in prompt

        # Honcho context should be in user message (runtime context block)
        messages = await loop.context.build_messages(
            history=[], current_message="Hello", channel="cli", chat_id="direct",
        )
        user_content = messages[-1]["content"]
        assert "User Context (Honcho)" in user_content
        assert "data scientist" in user_content

    async def test_no_context_on_cold_start(self, bus, mock_provider, workspace):
        """build_messages has no Honcho section when no prefetched context."""
        honcho_config = HonchoConfig(
            enabled=True, api_key="test-key", workspace_id="test-ws"
        )

        loop = AgentLoop(
            bus=bus,
            provider=mock_provider,
            workspace=workspace,
            honcho_config=honcho_config,
        )

        prompt = await loop.context.build_system_prompt()
        assert "User Context (Honcho)" not in prompt


class TestConsolidationHybridMode:
    """Tests for memory consolidation with honcho_active flag."""

    async def test_consolidation_skips_user_update(self, workspace):
        """consolidate() skips USER.md write when honcho_active=True."""
        from velo.agent.memory import MemoryStore

        store = MemoryStore(workspace)
        store.write_long_term("initial memory")
        store.write_user_profile("initial user profile")

        # Create a mock session with enough messages to trigger consolidation
        session = MagicMock()
        session.messages = [
            {"role": "user", "content": f"msg {i}", "timestamp": "2026-03-14T10:00:00"}
            for i in range(30)
        ]
        session.last_consolidated = 0

        # Mock provider that returns a save_memory tool call
        mock_tool_call = MagicMock()
        mock_tool_call.name = "save_memory"
        mock_tool_call.arguments = {
            "history_entry": "[2026-03-14 10:00] Test consolidation",
            "memory_update": "updated memory",
            "user_update": "should be ignored when honcho active",
        }

        response = MagicMock()
        response.has_tool_calls = True
        response.tool_calls = [mock_tool_call]

        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)

        # Consolidate with honcho_active=True
        result = await store.consolidate(
            session, provider, "test-model",
            memory_window=50,
            honcho_active=True,
        )

        assert result is True
        # Memory should be updated
        assert store.read_long_term() == "updated memory"
        # User profile should NOT be updated (honcho manages it)
        assert store.read_user_profile() == "initial user profile"

    async def test_consolidation_updates_user_without_honcho(self, workspace):
        """consolidate() writes USER.md normally when honcho_active=False."""
        from velo.agent.memory import MemoryStore

        store = MemoryStore(workspace)
        store.write_long_term("initial memory")
        store.write_user_profile("initial user profile")

        session = MagicMock()
        session.messages = [
            {"role": "user", "content": f"msg {i}", "timestamp": "2026-03-14T10:00:00"}
            for i in range(30)
        ]
        session.last_consolidated = 0

        mock_tool_call = MagicMock()
        mock_tool_call.name = "save_memory"
        mock_tool_call.arguments = {
            "history_entry": "[2026-03-14 10:00] Test consolidation",
            "memory_update": "updated memory",
            "user_update": "updated user profile",
        }

        response = MagicMock()
        response.has_tool_calls = True
        response.tool_calls = [mock_tool_call]

        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)

        result = await store.consolidate(
            session, provider, "test-model",
            memory_window=50,
            honcho_active=False,
        )

        assert result is True
        assert store.read_long_term() == "updated memory"
        assert store.read_user_profile() == "updated user profile"


class TestCleanup:
    """Tests for AgentLoop cleanup with Honcho."""

    async def test_cleanup_calls_honcho_shutdown(self, bus, mock_provider, workspace):
        """cleanup() flushes and shuts down Honcho adapter."""
        honcho_config = HonchoConfig(
            enabled=True, api_key="test-key", workspace_id="test-ws"
        )

        loop = AgentLoop(
            bus=bus,
            provider=mock_provider,
            workspace=workspace,
            honcho_config=honcho_config,
        )

        loop._honcho.flush_all = AsyncMock()
        loop._honcho.shutdown = AsyncMock()

        await loop.cleanup()

        loop._honcho.flush_all.assert_called_once()
        loop._honcho.shutdown.assert_called_once()
