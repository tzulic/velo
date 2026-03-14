"""Tests for HonchoAdapter."""

from __future__ import annotations

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
def mock_honcho_client():
    """Mock AsyncHoncho client with lazy peer/session.

    Uses MagicMock for the client since peer() and session() are sync
    (lazy constructors). Only truly async methods use AsyncMock.
    """
    # Reason: client must be MagicMock so .peer() is sync (lazy, no API call).
    # AsyncMock would make .peer() return a coroutine.
    client = MagicMock()

    # Mock peer objects (lazy — no API call until used)
    user_peer = MagicMock()
    ai_peer = MagicMock()
    session = MagicMock()

    # peer() returns lazy peer (sync)
    client.peer.return_value = user_peer
    # peer.session() returns lazy session (sync)
    user_peer.session.return_value = session

    # Async session methods
    session.add_messages = AsyncMock()
    context_result = MagicMock()
    context_result.content = "User prefers concise responses."
    session.get_context = AsyncMock(return_value=context_result)

    # Async peer methods
    user_peer.search = AsyncMock(return_value=[])
    chat_result = MagicMock()
    chat_result.content = "The user is a software developer."
    user_peer.chat = AsyncMock(return_value=chat_result)

    # Async close
    client.close = AsyncMock()

    return client, user_peer, ai_peer, session


class TestGetOrCreate:
    """Tests for session lifecycle."""

    async def test_creates_new_session(self, config, mock_honcho_client):
        """get_or_create creates peers and session on first call."""
        client, user_peer, _, session = mock_honcho_client
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            state = await adapter.get_or_create("telegram:123")

        assert state.session_key == "telegram:123"
        assert state.user_peer is user_peer
        assert state.session is session
        assert state.last_synced_idx == 0

    async def test_returns_cached_session(self, config, mock_honcho_client):
        """get_or_create returns same state on second call."""
        client, _, _, _ = mock_honcho_client
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            state1 = await adapter.get_or_create("telegram:123")
            state2 = await adapter.get_or_create("telegram:123")

        assert state1 is state2

    async def test_handles_client_error_gracefully(self, config):
        """get_or_create returns bare state on SDK error."""
        adapter = HonchoAdapter(config)

        with patch(
            "velo.agent.honcho.adapter.HonchoAdapter._ensure_client",
            side_effect=RuntimeError("connection failed"),
        ):
            state = await adapter.get_or_create("telegram:123")

        assert state.session_key == "telegram:123"
        assert state.session is None  # No session due to error


class TestSyncMessages:
    """Tests for message synchronization."""

    async def test_syncs_new_messages_only(self, config, mock_honcho_client):
        """sync_messages only sends messages after last_synced_idx."""
        client, _, _, session = mock_honcho_client
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            messages = [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
                {"role": "user", "content": "New message"},
            ]

            # First sync: all messages
            await adapter.sync_messages("key1", messages)
            session.add_messages.assert_called_once()
            call_args = session.add_messages.call_args[0][0]
            assert len(call_args) == 3

            session.add_messages.reset_mock()

            # Second sync: only new message
            messages.append({"role": "assistant", "content": "Response"})
            await adapter.sync_messages("key1", messages)
            session.add_messages.assert_called_once()
            call_args = session.add_messages.call_args[0][0]
            assert len(call_args) == 1
            assert call_args[0]["content"] == "Response"

    async def test_skips_non_user_assistant_roles(self, config, mock_honcho_client):
        """sync_messages skips tool and system messages."""
        client, _, _, session = mock_honcho_client
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            messages = [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
                {"role": "tool", "content": "file contents"},
                {"role": "assistant", "content": "Response"},
            ]
            await adapter.sync_messages("key1", messages)
            call_args = session.add_messages.call_args[0][0]
            assert len(call_args) == 2  # Only user + assistant

    async def test_handles_empty_messages(self, config, mock_honcho_client):
        """sync_messages does nothing for empty message list."""
        client, _, _, session = mock_honcho_client
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            await adapter.sync_messages("key1", [])
            session.add_messages.assert_not_called()

    async def test_handles_multimodal_content(self, config, mock_honcho_client):
        """sync_messages extracts text from multimodal messages."""
        client, _, _, session = mock_honcho_client
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
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
            call_args = session.add_messages.call_args[0][0]
            assert call_args[0]["content"] == "Look at this"

    async def test_sync_error_is_logged_not_raised(self, config, mock_honcho_client):
        """sync_messages catches exceptions and does not raise."""
        client, _, _, session = mock_honcho_client
        session.add_messages.side_effect = RuntimeError("API error")
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            # Should not raise
            await adapter.sync_messages("key1", [{"role": "user", "content": "test"}])


class TestContextPrefetch:
    """Tests for context prefetch/pop lifecycle."""

    async def test_prefetch_and_pop(self, config, mock_honcho_client):
        """prefetch_context caches result, pop_context_result consumes it."""
        client, _, _, session = mock_honcho_client
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            await adapter.get_or_create("key1")
            await adapter.prefetch_context("key1")
            # Wait for the background task
            state = adapter._sessions["key1"]
            if state._prefetch_task:
                await state._prefetch_task

            result = adapter.pop_context_result("key1")
            assert result == "User prefers concise responses."

            # Second pop returns empty (consumed)
            result2 = adapter.pop_context_result("key1")
            assert result2 == ""

    async def test_pop_returns_empty_on_cold_start(self, config):
        """pop_context_result returns empty string for unknown session."""
        adapter = HonchoAdapter(config)
        assert adapter.pop_context_result("unknown") == ""

    async def test_prefetch_passes_tokens_config(self, config, mock_honcho_client):
        """prefetch_context passes context_tokens from config."""
        client, _, _, session = mock_honcho_client
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            await adapter.get_or_create("key1")
            await adapter.prefetch_context("key1")
            state = adapter._sessions["key1"]
            if state._prefetch_task:
                await state._prefetch_task

            session.get_context.assert_called_once_with(tokens=500)


class TestDialecticQuery:
    """Tests for dialectic (chat) queries."""

    async def test_returns_response(self, config, mock_honcho_client):
        """dialectic_query returns Honcho's response."""
        client, user_peer, _, _ = mock_honcho_client
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            result = await adapter.dialectic_query("key1", "What does the user do?")

        assert result == "The user is a software developer."
        user_peer.chat.assert_called_once_with(query="What does the user do?")

    async def test_truncates_long_response(self, config, mock_honcho_client):
        """dialectic_query truncates response to dialectic_max_chars."""
        client, user_peer, _, _ = mock_honcho_client
        long_response = MagicMock()
        long_response.content = "x" * 1000
        user_peer.chat.return_value = long_response

        config.dialectic_max_chars = 100
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            result = await adapter.dialectic_query("key1", "query")

        assert len(result) == 103  # 100 + "..."
        assert result.endswith("...")

    async def test_error_returns_message(self, config, mock_honcho_client):
        """dialectic_query returns error message on failure."""
        client, user_peer, _, _ = mock_honcho_client
        user_peer.chat.side_effect = RuntimeError("API error")
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            result = await adapter.dialectic_query("key1", "query")

        assert "Error" in result


class TestSearchContext:
    """Tests for semantic search."""

    async def test_returns_results(self, config, mock_honcho_client):
        """search_context formats results."""
        client, user_peer, _, _ = mock_honcho_client
        search_result = MagicMock()
        search_result.content = "User mentioned they prefer Python"
        user_peer.search.return_value = [search_result]
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            result = await adapter.search_context("key1", "programming language")

        assert "Python" in result

    async def test_returns_no_results_message(self, config, mock_honcho_client):
        """search_context returns message when nothing found."""
        client, user_peer, _, _ = mock_honcho_client
        user_peer.search.return_value = []
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            result = await adapter.search_context("key1", "nonexistent")

        assert "No relevant" in result


class TestAddNote:
    """Tests for note recording."""

    async def test_adds_note_as_message(self, config, mock_honcho_client):
        """add_note sends a prefixed message to Honcho."""
        client, _, _, session = mock_honcho_client
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            await adapter.add_note("key1", "User prefers dark mode")

        session.add_messages.assert_called_once()
        msg = session.add_messages.call_args[0][0][0]
        assert msg["role"] == "assistant"
        assert "[note]" in msg["content"]
        assert "dark mode" in msg["content"]


class TestCurrentSession:
    """Tests for session key tracking."""

    def test_set_and_get_current_session(self, config):
        """set_current_session updates current_session_key."""
        adapter = HonchoAdapter(config)
        assert adapter.current_session_key == ""

        adapter.set_current_session("telegram:456")
        assert adapter.current_session_key == "telegram:456"


class TestShutdown:
    """Tests for cleanup and shutdown."""

    async def test_shutdown_closes_client(self, config, mock_honcho_client):
        """shutdown closes the Honcho client."""
        client, _, _, _ = mock_honcho_client
        adapter = HonchoAdapter(config)
        adapter._client = client

        await adapter.shutdown()

        client.close.assert_called_once()
        assert adapter._client is None
        assert len(adapter._sessions) == 0

    async def test_shutdown_handles_close_error(self, config, mock_honcho_client):
        """shutdown catches client close errors."""
        client, _, _, _ = mock_honcho_client
        client.close.side_effect = RuntimeError("close failed")
        adapter = HonchoAdapter(config)
        adapter._client = client

        # Should not raise
        await adapter.shutdown()


class TestConcurrentSessions:
    """Tests for concurrent session handling."""

    async def test_multiple_sessions(self, config, mock_honcho_client):
        """Adapter handles multiple concurrent sessions."""
        client, _, _, _ = mock_honcho_client
        adapter = HonchoAdapter(config)

        with patch("velo.agent.honcho.adapter.HonchoAdapter._ensure_client", return_value=client):
            state1 = await adapter.get_or_create("telegram:111")
            state2 = await adapter.get_or_create("discord:222")

        assert state1.session_key == "telegram:111"
        assert state2.session_key == "discord:222"
        assert state1 is not state2
