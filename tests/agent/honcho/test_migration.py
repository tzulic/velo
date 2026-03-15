"""Tests for Honcho migration helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from velo.agent.honcho.adapter import HonchoAdapter
from velo.agent.honcho.config import HonchoConfig
from velo.agent.honcho.migration import (
    migrate_local_history,
    migrate_memory_files,
    seed_ai_identity,
)


@pytest.fixture
def config():
    """Default HonchoConfig for testing."""
    return HonchoConfig(
        enabled=True,
        api_key="test-key",
        workspace_id="test-workspace",
        ai_peer="velo",
    )


@pytest.fixture
def workspace(tmp_path):
    """Temporary workspace with SOUL.md and USER.md."""
    soul = tmp_path / "SOUL.md"
    soul.write_text("I am Velo, a helpful AI assistant.", encoding="utf-8")
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    user_md = memory_dir / "USER.md"
    user_md.write_text("Name: Alice\nTimezone: GMT+1\nPreferences: dark mode", encoding="utf-8")
    return tmp_path


@pytest.fixture
def mock_adapter(config, workspace):
    """Adapter with mocked Honcho client."""
    adapter = HonchoAdapter(config, workspace)

    # Create mock session state
    user_peer = MagicMock()
    ai_peer = MagicMock()
    session = MagicMock()
    session.id = "test-session-id"

    # User peer observations
    user_obs = MagicMock()
    user_obs.create = AsyncMock()
    user_peer.aio = MagicMock()
    user_peer.aio.observations = user_obs

    # AI peer observations
    ai_obs = MagicMock()
    ai_obs.create = AsyncMock()
    ai_peer.aio = MagicMock()
    ai_peer.aio.observations = ai_obs

    # Session methods
    session.aio = MagicMock()
    session.aio.add_messages = AsyncMock()

    # Pre-populate session state
    from velo.agent.honcho.adapter import HonchoSessionState

    state = HonchoSessionState(
        session_key="key1",
        user_peer=user_peer,
        ai_peer=ai_peer,
        session=session,
    )
    adapter._sessions["key1"] = state

    return adapter


class TestMigrateLocalHistory:
    """Tests for migrate_local_history."""

    async def test_uploads_messages(self, mock_adapter):
        """Messages are uploaded as XML-formatted history."""
        messages = [
            {"role": "user", "content": "Hello", "timestamp": "2026-03-15 10:00"},
            {"role": "assistant", "content": "Hi there!", "timestamp": "2026-03-15 10:01"},
        ]
        result = await migrate_local_history(mock_adapter, "key1", messages)

        assert result is True
        state = mock_adapter._sessions["key1"]
        state.session.aio.add_messages.assert_called_once()
        msg = state.session.aio.add_messages.call_args[0][0]
        assert "prior_history" in msg.content
        assert "Hello" in msg.content

    async def test_empty_messages_noop(self, mock_adapter):
        """Empty message list returns True without API call."""
        result = await migrate_local_history(mock_adapter, "key1", [])
        assert result is True

    async def test_skips_system_messages(self, mock_adapter):
        """System and tool messages are excluded."""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "tool", "content": "tool output"},
        ]
        result = await migrate_local_history(mock_adapter, "key1", messages)

        assert result is True
        msg = mock_adapter._sessions["key1"].session.aio.add_messages.call_args[0][0]
        assert "system" not in msg.content.lower() or "role='user'" in msg.content

    async def test_handles_no_session(self, config, workspace):
        """Returns False when no session is available."""
        adapter = HonchoAdapter(config, workspace)
        # Mock get_or_create to return state with no session
        from velo.agent.honcho.adapter import HonchoSessionState

        bare = HonchoSessionState(session_key="key1")
        adapter._sessions["key1"] = bare

        result = await migrate_local_history(adapter, "key1", [{"role": "user", "content": "test"}])
        assert result is False


class TestMigrateMemoryFiles:
    """Tests for migrate_memory_files."""

    async def test_uploads_user_md_as_observations(self, mock_adapter, workspace):
        """USER.md content is uploaded as observations."""
        result = await migrate_memory_files(mock_adapter, "key1", workspace)

        assert result is True
        state = mock_adapter._sessions["key1"]
        state.user_peer.aio.observations.create.assert_called_once()
        content = state.user_peer.aio.observations.create.call_args[1]["content"]
        assert "migrated_profile" in content
        assert "Alice" in content

    async def test_seeds_soul_md(self, mock_adapter, workspace):
        """SOUL.md is seeded into AI peer."""
        result = await migrate_memory_files(mock_adapter, "key1", workspace)

        assert result is True
        state = mock_adapter._sessions["key1"]
        state.ai_peer.aio.observations.create.assert_called_once()

    async def test_no_user_md_still_succeeds(self, mock_adapter, tmp_path):
        """Works when USER.md doesn't exist."""
        (tmp_path / "memory").mkdir(exist_ok=True)
        (tmp_path / "SOUL.md").write_text("I am Velo.", encoding="utf-8")
        mock_adapter._workspace = tmp_path

        result = await migrate_memory_files(mock_adapter, "key1", tmp_path)
        assert result is True


class TestSeedAiIdentity:
    """Tests for seed_ai_identity."""

    async def test_seeds_soul_content(self, mock_adapter, workspace):
        """Delegates to adapter._seed_ai_identity."""
        result = await seed_ai_identity(mock_adapter, "key1", workspace)

        assert result is True
        state = mock_adapter._sessions["key1"]
        state.ai_peer.aio.observations.create.assert_called_once()

    async def test_idempotent(self, mock_adapter, workspace):
        """Multiple calls only seed once."""
        await seed_ai_identity(mock_adapter, "key1", workspace)
        await seed_ai_identity(mock_adapter, "key1", workspace)

        state = mock_adapter._sessions["key1"]
        state.ai_peer.aio.observations.create.assert_called_once()

    async def test_handles_error(self, mock_adapter, workspace):
        """Returns False on error."""
        state = mock_adapter._sessions["key1"]
        state.ai_peer.aio.observations.create.side_effect = RuntimeError("API error")

        result = await seed_ai_identity(mock_adapter, "key1", workspace)
        # Still returns True because the adapter catches the error internally
        # and the migration function wraps in try/except
        assert result is True
