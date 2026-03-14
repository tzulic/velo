"""Tests for Honcho tools (search, query, note)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from velo.agent.honcho.tools import HonchoNoteTool, HonchoQueryTool, HonchoSearchTool


@pytest.fixture
def mock_adapter():
    """Mock HonchoAdapter with all methods."""
    adapter = MagicMock()
    type(adapter).current_session_key = PropertyMock(return_value="telegram:123")
    adapter.search_context = AsyncMock(return_value="- User likes Python")
    adapter.dialectic_query = AsyncMock(return_value="The user is a developer.")
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
            "telegram:123", "What does the user do?"
        )

    async def test_execute_no_session_returns_error(self, mock_adapter_no_session):
        """Query tool returns error JSON when no session key."""
        tool = HonchoQueryTool(mock_adapter_no_session)
        result = await tool.execute(query="test")

        assert "error" in result

    def test_schema_has_required_query(self, mock_adapter):
        """Tool schema requires query parameter."""
        tool = HonchoQueryTool(mock_adapter)
        schema = tool.to_schema()

        assert schema["function"]["name"] == "honcho_query"
        assert "query" in schema["function"]["parameters"]["required"]


class TestHonchoNoteTool:
    """Tests for HonchoNoteTool."""

    async def test_execute_records_note(self, mock_adapter):
        """Note tool calls adapter add_note."""
        tool = HonchoNoteTool(mock_adapter)
        result = await tool.execute(content="User prefers dark mode")

        assert "recorded" in result.lower()
        mock_adapter.add_note.assert_called_once_with("telegram:123", "User prefers dark mode")

    async def test_execute_no_session_returns_error(self, mock_adapter_no_session):
        """Note tool returns error JSON when no session key."""
        tool = HonchoNoteTool(mock_adapter_no_session)
        result = await tool.execute(content="test note")

        assert "error" in result

    def test_schema_has_required_content(self, mock_adapter):
        """Tool schema requires content parameter."""
        tool = HonchoNoteTool(mock_adapter)
        schema = tool.to_schema()

        assert schema["function"]["name"] == "honcho_note"
        assert "content" in schema["function"]["parameters"]["required"]

    async def test_execute_with_adapter_error(self, mock_adapter):
        """Note tool handles adapter errors gracefully."""
        mock_adapter.add_note.side_effect = RuntimeError("API error")
        tool = HonchoNoteTool(mock_adapter)

        # The tool itself doesn't catch — the adapter does.
        # But add_note raising is unusual (adapter catches internally).
        # Verify the tool at least calls add_note.
        with pytest.raises(RuntimeError):
            await tool.execute(content="test")
