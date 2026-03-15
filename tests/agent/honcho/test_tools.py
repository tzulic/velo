"""Tests for Honcho tools (search, query, profile, conclude)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from velo.agent.honcho.tools import (
    HonchoConcludeTool,
    HonchoProfileTool,
    HonchoQueryTool,
    HonchoSearchTool,
)


@pytest.fixture
def mock_adapter():
    """Mock HonchoAdapter with all methods."""
    adapter = MagicMock()
    type(adapter).current_session_key = PropertyMock(return_value="telegram:123")
    adapter.search_context = AsyncMock(return_value="- User likes Python")
    adapter.dialectic_query = AsyncMock(return_value="The user is a developer.")
    adapter.get_peer_card = AsyncMock(return_value="Name: Alice\nTimezone: GMT+1")
    adapter.add_conclusion = AsyncMock()
    adapter.add_note = AsyncMock()
    return adapter


@pytest.fixture
def mock_adapter_no_session():
    """Mock HonchoAdapter with no active session."""
    adapter = MagicMock()
    type(adapter).current_session_key = PropertyMock(return_value="")
    return adapter


class TestHonchoSearchTool:
    """Tests for HonchoSearchTool."""

    async def test_execute_returns_results(self, mock_adapter):
        """Search tool returns adapter search results."""
        tool = HonchoSearchTool(mock_adapter)
        result = await tool.execute(query="What language does user prefer?")

        assert "Python" in result
        mock_adapter.search_context.assert_called_once_with(
            "telegram:123", "What language does user prefer?"
        )

    async def test_execute_no_session_returns_error(self, mock_adapter_no_session):
        """Search tool returns error JSON when no session key."""
        tool = HonchoSearchTool(mock_adapter_no_session)
        result = await tool.execute(query="test")

        assert "error" in result
        assert "No active session" in result

    def test_schema_has_required_query(self, mock_adapter):
        """Tool schema requires query parameter."""
        tool = HonchoSearchTool(mock_adapter)
        schema = tool.to_schema()

        assert schema["function"]["name"] == "honcho_search"
        assert "query" in schema["function"]["parameters"]["required"]

    async def test_execute_passes_kwargs(self, mock_adapter):
        """Extra kwargs are accepted and ignored."""
        tool = HonchoSearchTool(mock_adapter)
        result = await tool.execute(query="test", extra_param="ignored")

        assert "Python" in result


class TestHonchoQueryTool:
    """Tests for HonchoQueryTool."""

    async def test_execute_returns_response(self, mock_adapter):
        """Query tool returns adapter dialectic response."""
        tool = HonchoQueryTool(mock_adapter)
        result = await tool.execute(query="What does the user do?")

        assert "developer" in result
        mock_adapter.dialectic_query.assert_called_once_with(
            "telegram:123", "What does the user do?", peer="user"
        )

    async def test_execute_with_ai_peer(self, mock_adapter):
        """Query tool passes peer parameter to adapter."""
        tool = HonchoQueryTool(mock_adapter)
        await tool.execute(query="What is my personality?", peer="ai")

        mock_adapter.dialectic_query.assert_called_once_with(
            "telegram:123", "What is my personality?", peer="ai"
        )

    async def test_execute_no_session_returns_error(self, mock_adapter_no_session):
        """Query tool returns error JSON when no session key."""
        tool = HonchoQueryTool(mock_adapter_no_session)
        result = await tool.execute(query="test")

        assert "error" in result

    def test_schema_has_peer_enum(self, mock_adapter):
        """Tool schema includes peer parameter with enum."""
        tool = HonchoQueryTool(mock_adapter)
        schema = tool.to_schema()

        params = schema["function"]["parameters"]
        assert "peer" in params["properties"]
        assert params["properties"]["peer"]["enum"] == ["user", "ai"]

    def test_schema_has_required_query(self, mock_adapter):
        """Tool schema requires query parameter."""
        tool = HonchoQueryTool(mock_adapter)
        schema = tool.to_schema()

        assert schema["function"]["name"] == "honcho_query"
        assert "query" in schema["function"]["parameters"]["required"]


class TestHonchoProfileTool:
    """Tests for HonchoProfileTool."""

    async def test_execute_returns_profile(self, mock_adapter):
        """Profile tool returns peer card content."""
        tool = HonchoProfileTool(mock_adapter)
        result = await tool.execute()

        assert "Alice" in result
        assert "GMT+1" in result
        mock_adapter.get_peer_card.assert_called_once_with("telegram:123")

    async def test_execute_empty_profile(self, mock_adapter):
        """Profile tool returns fallback when no card available."""
        mock_adapter.get_peer_card.return_value = ""
        tool = HonchoProfileTool(mock_adapter)
        result = await tool.execute()

        assert "No user profile" in result

    async def test_execute_no_session_returns_error(self, mock_adapter_no_session):
        """Profile tool returns error JSON when no session key."""
        tool = HonchoProfileTool(mock_adapter_no_session)
        result = await tool.execute()

        assert "error" in result

    def test_schema_has_no_required_params(self, mock_adapter):
        """Profile tool has no required parameters."""
        tool = HonchoProfileTool(mock_adapter)
        schema = tool.to_schema()

        assert schema["function"]["name"] == "honcho_profile"
        assert schema["function"]["parameters"]["required"] == []


class TestHonchoConcludeTool:
    """Tests for HonchoConcludeTool."""

    async def test_execute_records_conclusion(self, mock_adapter):
        """Conclude tool calls adapter add_conclusion."""
        tool = HonchoConcludeTool(mock_adapter)
        result = await tool.execute(conclusion="User prefers dark mode")

        assert "recorded" in result.lower() or "updated" in result.lower()
        mock_adapter.add_conclusion.assert_called_once_with(
            "telegram:123", "User prefers dark mode"
        )

    async def test_execute_no_session_returns_error(self, mock_adapter_no_session):
        """Conclude tool returns error JSON when no session key."""
        tool = HonchoConcludeTool(mock_adapter_no_session)
        result = await tool.execute(conclusion="test")

        assert "error" in result

    def test_schema_has_required_conclusion(self, mock_adapter):
        """Tool schema requires conclusion parameter."""
        tool = HonchoConcludeTool(mock_adapter)
        schema = tool.to_schema()

        assert schema["function"]["name"] == "honcho_conclude"
        assert "conclusion" in schema["function"]["parameters"]["required"]

    async def test_execute_with_adapter_error(self, mock_adapter):
        """Conclude tool propagates adapter errors (adapter catches internally)."""
        mock_adapter.add_conclusion.side_effect = RuntimeError("API error")
        tool = HonchoConcludeTool(mock_adapter)

        with pytest.raises(RuntimeError):
            await tool.execute(conclusion="test")
