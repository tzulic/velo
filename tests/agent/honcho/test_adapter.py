"""Tests for HonchoAdapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from velo.agent.honcho.adapter import HonchoAdapter
from velo.agent.honcho.config import HonchoConfig


@pytest.fixture
def config():
    """Default HonchoConfig for testing."""
    return HonchoConfig(
        enabled=True,
        api_key="test-key",
        api_base="https://api.honcho.dev",
        workspace_id="test-workspace",
        ai_peer="velo",
        context_tokens=500,
        dialectic_max_chars=600,
    )


@pytest.fixture
def workspace(tmp_path):
    """Temporary workspace with SOUL.md."""
    soul = tmp_path / "SOUL.md"
    soul.write_text("I am Velo, a helpful AI assistant.", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    return tmp_path


@pytest.fixture
def mock_honcho_aio():
    """Mock Honcho .aio accessor with async peer/session methods.

    Reason: The real SDK uses Honcho(api_key=...).aio for async ops.
    peer() and session() are async (need await), not lazy/sync.
    """
    aio = MagicMock()

    # Mock peer and session objects (returned by await aio.peer()/session())
    user_peer = MagicMock()
    ai_peer = MagicMock()
    session = MagicMock()
    session.id = "test-session-id"

    # aio.peer(id) and aio.session(id) are async
    aio.peer = AsyncMock(return_value=user_peer)
    aio.session = AsyncMock(return_value=session)

    # Session async methods (via session.aio)
    session_aio = MagicMock()
    session.aio = session_aio
    session_aio.add_messages = AsyncMock(return_value=[])
    session_aio.add_peers = AsyncMock()
    context_result = MagicMock()
    context_result.content = "User prefers concise responses."
    session_aio.context = AsyncMock(return_value=context_result)

    # Peer async methods (via user_peer.aio)
    peer_aio = MagicMock()
    user_peer.aio = peer_aio
    peer_aio.search = AsyncMock(return_value=[])
    peer_aio.chat = AsyncMock(return_value="The user is a software developer.")
    peer_aio.get_card = AsyncMock(return_value="Name: Alice\nTimezone: GMT+1")

    # AI peer async methods
    ai_peer_aio = MagicMock()
    ai_peer.aio = ai_peer_aio
    ai_observations = MagicMock()
    ai_observations.create = AsyncMock()
    ai_peer_aio.observations = ai_observations
    ai_peer_aio.chat = AsyncMock(return_value="I am a helpful assistant.")

    # User peer observations (for add_conclusion)
    user_observations = MagicMock()
    user_observations.create = AsyncMock()
    peer_aio.observations = user_observations

    # Make aio.peer return different peers based on arg
    async def peer_factory(name):
        return user_peer if name == "user" else ai_peer

    aio.peer = AsyncMock(side_effect=peer_factory)

    return aio, user_peer, ai_peer, session


class TestGetOrCreate:
    """Tests for session lifecycle."""

    async def test_creates_new_session(self, config, workspace, mock_honcho_aio):
        """get_or_create creates peers and session on first call."""
        aio, user_peer, _, session = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            state = await adapter.get_or_create("telegram:123")

        assert state.session_key == "telegram:123"
        assert state.user_peer is user_peer
        assert state.session is session
        assert state.last_synced_idx == 0

    async def test_returns_cached_session(self, config, workspace, mock_honcho_aio):
        """get_or_create returns same state on second call."""
        aio, _, _, _ = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            state1 = await adapter.get_or_create("telegram:123")
            state2 = await adapter.get_or_create("telegram:123")

        assert state1 is state2

    async def test_handles_client_error_gracefully(self, config, workspace):
        """get_or_create returns bare state on SDK error."""
        adapter = HonchoAdapter(config, workspace)

        with patch.object(
            adapter, "_ensure_client",
            side_effect=RuntimeError("connection failed"),
        ):
            state = await adapter.get_or_create("telegram:123")

        assert state.session_key == "telegram:123"
        assert state.session is None  # No session due to error

    async def test_dual_peer_observation_enabled(self, config, workspace, mock_honcho_aio):
        """get_or_create calls add_peers with observe_others=True."""
        aio, _, _, session = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        # Reason: SessionPeerConfig is imported inside get_or_create, so
        # we mock the honcho module-level import that the adapter uses.
        mock_spc = MagicMock(return_value="mock_config")
        with (
            patch.object(adapter, "_ensure_client", return_value=aio),
            patch.dict("sys.modules", {"honcho": MagicMock(SessionPeerConfig=mock_spc)}),
        ):
            await adapter.get_or_create("telegram:123")

        session.aio.add_peers.assert_called_once()
        # Verify that two peers were added
        call_args = session.aio.add_peers.call_args[0][0]
        assert len(call_args) == 2


class TestIdentitySeeding:
    """Tests for AI identity seeding from SOUL.md."""

    async def test_seeds_soul_md_on_first_session(self, config, workspace, mock_honcho_aio):
        """_seed_ai_identity reads SOUL.md and creates observation."""
        aio, _, ai_peer, _ = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            state = await adapter.get_or_create("telegram:123")

        # Check that observations.create was called on AI peer
        ai_peer.aio.observations.create.assert_called_once()
        content = ai_peer.aio.observations.create.call_args[1]["content"]
        assert "[identity]" in content
        assert "Velo" in content

    async def test_no_seed_without_soul_md(self, config, tmp_path, mock_honcho_aio):
        """No seeding when SOUL.md doesn't exist."""
        (tmp_path / "memory").mkdir()
        aio, _, ai_peer, _ = mock_honcho_aio
        adapter = HonchoAdapter(config, tmp_path)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            await adapter.get_or_create("telegram:123")

        ai_peer.aio.observations.create.assert_not_called()

    async def test_seed_is_idempotent(self, config, workspace, mock_honcho_aio):
        """Identity is only seeded once per session key."""
        aio, _, ai_peer, _ = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            await adapter.get_or_create("telegram:123")
            # Manually call again
            state = adapter._sessions["telegram:123"]
            await adapter._seed_ai_identity(state)

        # Should only be called once (the second call is a no-op)
        ai_peer.aio.observations.create.assert_called_once()

    async def test_seed_disabled_by_config(self, config, workspace, mock_honcho_aio):
        """No seeding when seed_identity=False."""
        config.seed_identity = False
        aio, _, ai_peer, _ = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            await adapter.get_or_create("telegram:123")

        ai_peer.aio.observations.create.assert_not_called()


class TestSyncMessages:
    """Tests for message synchronization."""

    async def test_syncs_new_messages_only(self, config, workspace, mock_honcho_aio):
        """sync_messages only sends messages after last_synced_idx."""
        aio, _, _, session = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            messages = [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
                {"role": "user", "content": "New message"},
            ]

            # First sync: all messages
            await adapter.sync_messages("key1", messages)
            session.aio.add_messages.assert_called_once()

            session.aio.add_messages.reset_mock()

            # Second sync: only new message
            messages.append({"role": "assistant", "content": "Response"})
            await adapter.sync_messages("key1", messages)
            session.aio.add_messages.assert_called_once()

    async def test_skips_non_user_assistant_roles(self, config, workspace, mock_honcho_aio):
        """sync_messages skips tool and system messages."""
        aio, _, _, session = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            messages = [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
                {"role": "tool", "content": "file contents"},
                {"role": "assistant", "content": "Response"},
            ]
            await adapter.sync_messages("key1", messages)
            call_args = session.aio.add_messages.call_args[0][0]
            assert len(call_args) == 2  # Only user + assistant

    async def test_handles_empty_messages(self, config, workspace, mock_honcho_aio):
        """sync_messages does nothing for empty message list."""
        aio, _, _, session = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            await adapter.sync_messages("key1", [])
            session.aio.add_messages.assert_not_called()

    async def test_handles_multimodal_content(self, config, workspace, mock_honcho_aio):
        """sync_messages extracts text from multimodal messages."""
        aio, _, _, session = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Look at this"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                    ],
                },
            ]
            await adapter.sync_messages("key1", messages)
            call_args = session.aio.add_messages.call_args[0][0]
            assert call_args[0].content == "Look at this"

    async def test_sync_error_is_logged_not_raised(self, config, workspace, mock_honcho_aio):
        """sync_messages catches exceptions and does not raise."""
        aio, _, _, session = mock_honcho_aio
        session.aio.add_messages.side_effect = RuntimeError("API error")
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            # Should not raise
            await adapter.sync_messages("key1", [{"role": "user", "content": "test"}])


class TestContextPrefetch:
    """Tests for context prefetch/pop lifecycle."""

    async def test_prefetch_and_pop(self, config, workspace, mock_honcho_aio):
        """prefetch_context caches result, pop_context_result consumes it."""
        aio, _, _, session = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            await adapter.get_or_create("key1")
            await adapter.prefetch_context("key1")
            # Wait for the background task
            state = adapter._sessions["key1"]
            if state._prefetch_task:
                await state._prefetch_task

            result = adapter.pop_context_result("key1")
            assert "User prefers concise responses." in result

            # Second pop returns empty (consumed)
            result2 = adapter.pop_context_result("key1")
            assert result2 == ""

    async def test_prefetch_includes_peer_card(self, config, workspace, mock_honcho_aio):
        """prefetch_context also fetches peer card."""
        aio, _, _, _ = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            await adapter.get_or_create("key1")
            await adapter.prefetch_context("key1")
            state = adapter._sessions["key1"]
            if state._prefetch_task:
                await state._prefetch_task

            result = adapter.pop_context_result("key1")
            assert "Alice" in result
            assert "User Profile (from Honcho)" in result

    async def test_pop_returns_empty_on_cold_start(self, config, workspace):
        """pop_context_result returns empty string for unknown session."""
        adapter = HonchoAdapter(config, workspace)
        assert adapter.pop_context_result("unknown") == ""

    async def test_prefetch_passes_tokens_config(self, config, workspace, mock_honcho_aio):
        """prefetch_context passes context_tokens from config."""
        aio, _, _, session = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            await adapter.get_or_create("key1")
            await adapter.prefetch_context("key1")
            state = adapter._sessions["key1"]
            if state._prefetch_task:
                await state._prefetch_task

            session.aio.context.assert_called_once_with(tokens=500)

    async def test_peer_card_synced_to_user_md(self, config, workspace, mock_honcho_aio):
        """prefetch_context writes peer card to USER.md when configured."""
        aio, _, _, _ = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            await adapter.get_or_create("key1")
            await adapter.prefetch_context("key1")
            state = adapter._sessions["key1"]
            if state._prefetch_task:
                await state._prefetch_task

        user_md = workspace / "memory" / "USER.md"
        assert user_md.exists()
        content = user_md.read_text(encoding="utf-8")
        assert "Alice" in content


class TestDialecticQuery:
    """Tests for dialectic (chat) queries."""

    async def test_returns_response(self, config, workspace, mock_honcho_aio):
        """dialectic_query returns Honcho's response."""
        aio, user_peer, _, _ = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            result = await adapter.dialectic_query("key1", "What does the user do?")

        assert result == "The user is a software developer."
        user_peer.aio.chat.assert_called_once_with(query="What does the user do?")

    async def test_query_ai_peer(self, config, workspace, mock_honcho_aio):
        """dialectic_query with peer='ai' queries the AI peer."""
        aio, _, ai_peer, _ = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            result = await adapter.dialectic_query("key1", "What is my personality?", peer="ai")

        assert "helpful assistant" in result
        ai_peer.aio.chat.assert_called_once_with(query="What is my personality?")

    async def test_truncates_long_response(self, config, workspace, mock_honcho_aio):
        """dialectic_query truncates response to dialectic_max_chars."""
        aio, user_peer, _, _ = mock_honcho_aio
        user_peer.aio.chat.return_value = "x" * 1000

        config.dialectic_max_chars = 100
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            result = await adapter.dialectic_query("key1", "query")

        assert len(result) == 103  # 100 + "..."
        assert result.endswith("...")

    async def test_handles_none_response(self, config, workspace, mock_honcho_aio):
        """dialectic_query returns fallback when chat returns None."""
        aio, user_peer, _, _ = mock_honcho_aio
        user_peer.aio.chat.return_value = None
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            result = await adapter.dialectic_query("key1", "query")

        assert "No information" in result

    async def test_error_returns_message(self, config, workspace, mock_honcho_aio):
        """dialectic_query returns error message on failure."""
        aio, user_peer, _, _ = mock_honcho_aio
        user_peer.aio.chat.side_effect = RuntimeError("API error")
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            result = await adapter.dialectic_query("key1", "query")

        assert "Error" in result


class TestSearchContext:
    """Tests for semantic search."""

    async def test_returns_results(self, config, workspace, mock_honcho_aio):
        """search_context formats results."""
        aio, user_peer, _, _ = mock_honcho_aio
        search_result = MagicMock()
        search_result.content = "User mentioned they prefer Python"
        user_peer.aio.search.return_value = [search_result]
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            result = await adapter.search_context("key1", "programming language")

        assert "Python" in result

    async def test_returns_no_results_message(self, config, workspace, mock_honcho_aio):
        """search_context returns message when nothing found."""
        aio, user_peer, _, _ = mock_honcho_aio
        user_peer.aio.search.return_value = []
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            result = await adapter.search_context("key1", "nonexistent")

        assert "No relevant" in result


class TestAddConclusion:
    """Tests for conclusion recording."""

    async def test_adds_conclusion_via_observations(self, config, workspace, mock_honcho_aio):
        """add_conclusion creates an observation on user peer."""
        aio, user_peer, _, _ = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            await adapter.add_conclusion("key1", "User prefers dark mode")

        user_peer.aio.observations.create.assert_called_once()
        content = user_peer.aio.observations.create.call_args[1]["content"]
        assert "dark mode" in content

    async def test_fallback_to_message_when_no_observations(self, config, workspace, mock_honcho_aio):
        """add_conclusion falls back to add_messages when observations unavailable."""
        aio, user_peer, _, session = mock_honcho_aio
        # Reason: MagicMock auto-creates attributes on access.
        # Use spec=[] so only explicitly-set attributes exist.
        bare_aio = MagicMock(spec=["chat", "search", "get_card"])
        bare_aio.chat = user_peer.aio.chat
        bare_aio.search = user_peer.aio.search
        bare_aio.get_card = user_peer.aio.get_card
        user_peer.aio = bare_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            await adapter.add_conclusion("key1", "User prefers dark mode")

        session.aio.add_messages.assert_called()


class TestGetPeerCard:
    """Tests for peer card retrieval."""

    async def test_returns_peer_card(self, config, workspace, mock_honcho_aio):
        """get_peer_card returns user peer card."""
        aio, _, _, _ = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            result = await adapter.get_peer_card("key1")

        assert "Alice" in result


class TestCurrentSession:
    """Tests for session key tracking."""

    def test_set_and_get_current_session(self, config):
        """set_current_session updates current_session_key."""
        adapter = HonchoAdapter(config)
        assert adapter.current_session_key == ""

        adapter.set_current_session("telegram:456")
        assert adapter.current_session_key == "telegram:456"

    def test_get_prefetched_context_delegates(self, config):
        """get_prefetched_context calls pop_context_result with current key."""
        adapter = HonchoAdapter(config)
        assert adapter.get_prefetched_context() == ""


class TestShutdown:
    """Tests for cleanup and shutdown."""

    async def test_shutdown_clears_state(self, config):
        """shutdown clears client and sessions."""
        adapter = HonchoAdapter(config)
        adapter._client = MagicMock()
        adapter._aio = MagicMock()

        await adapter.shutdown()

        assert adapter._client is None
        assert adapter._aio is None
        assert len(adapter._sessions) == 0


class TestConcurrentSessions:
    """Tests for concurrent session handling."""

    async def test_multiple_sessions(self, config, workspace, mock_honcho_aio):
        """Adapter handles multiple concurrent sessions."""
        aio, _, _, _ = mock_honcho_aio
        adapter = HonchoAdapter(config, workspace)

        with patch.object(adapter, "_ensure_client", return_value=aio):
            state1 = await adapter.get_or_create("telegram:111")
            state2 = await adapter.get_or_create("discord:222")

        assert state1.session_key == "telegram:111"
        assert state2.session_key == "discord:222"
        assert state1 is not state2
