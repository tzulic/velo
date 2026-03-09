"""Tests for deferred tool registry and SearchToolsTool."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.search import SearchToolsTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str, description: str = "A test tool.") -> Tool:
    """Create a minimal concrete Tool with the given name and description."""

    class _T(Tool):
        @property
        def name(self) -> str:
            return name

        @property
        def description(self) -> str:
            return description

        @property
        def parameters(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}, "required": []}

        async def execute(self, **kwargs: Any) -> str:
            return f"result:{name}"

    return _T()


# ---------------------------------------------------------------------------
# ToolRegistry deferred pool tests
# ---------------------------------------------------------------------------


class TestDeferredRegistration:
    """Tests for register(deferred=True) and related methods."""

    def test_active_by_default(self) -> None:
        """register() without deferred=True adds to active pool."""
        reg = ToolRegistry()
        reg.register(_make_tool("active_tool"))
        assert "active_tool" in reg
        assert len(reg) == 1

    def test_deferred_not_in_active(self) -> None:
        """register(deferred=True) does not add to active pool."""
        reg = ToolRegistry()
        reg.register(_make_tool("lazy_tool"), deferred=True)
        assert "lazy_tool" not in reg
        assert len(reg) == 0

    def test_deferred_in_deferred_pool(self) -> None:
        """register(deferred=True) adds to _deferred pool."""
        reg = ToolRegistry()
        reg.register(_make_tool("lazy_tool"), deferred=True)
        assert "lazy_tool" in reg._deferred

    def test_activate_moves_to_active(self) -> None:
        """activate() moves a tool from deferred to active pool."""
        reg = ToolRegistry()
        reg.register(_make_tool("lazy_tool"), deferred=True)
        result = reg.activate("lazy_tool")
        assert result is True
        assert "lazy_tool" in reg
        assert "lazy_tool" not in reg._deferred

    def test_activate_returns_false_for_unknown(self) -> None:
        """activate() returns False if the tool is not in deferred pool."""
        reg = ToolRegistry()
        assert reg.activate("nonexistent") is False

    def test_activate_returns_false_for_active_tool(self) -> None:
        """activate() returns False for a tool already in active pool."""
        reg = ToolRegistry()
        reg.register(_make_tool("active_tool"))
        assert reg.activate("active_tool") is False

    def test_get_definitions_excludes_deferred(self) -> None:
        """get_definitions() only returns active tools."""
        reg = ToolRegistry()
        reg.register(_make_tool("active_tool"))
        reg.register(_make_tool("lazy_tool"), deferred=True)
        defs = reg.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "active_tool" in names
        assert "lazy_tool" not in names

    def test_unregister_removes_from_both_pools(self) -> None:
        """unregister() removes from active and deferred pools."""
        reg = ToolRegistry()
        reg.register(_make_tool("active_tool"))
        reg.register(_make_tool("lazy_tool"), deferred=True)
        reg.unregister("active_tool")
        reg.unregister("lazy_tool")
        assert "active_tool" not in reg
        assert "lazy_tool" not in reg._deferred


class TestSearchDeferred:
    """Tests for search_deferred() BM25 search."""

    def test_empty_registry_returns_empty(self) -> None:
        """search_deferred() returns [] when no deferred tools exist."""
        reg = ToolRegistry()
        assert reg.search_deferred("github") == []

    def test_returns_matching_tools(self) -> None:
        """search_deferred() finds tools whose description matches the query."""
        reg = ToolRegistry()
        reg.register(_make_tool("mcp_github_list_repos", "List GitHub repositories"), deferred=True)
        reg.register(_make_tool("mcp_slack_send", "Send a Slack message"), deferred=True)
        results = reg.search_deferred("github repository")
        names = [r[0] for r in results]
        assert "mcp_github_list_repos" in names

    def test_irrelevant_query_returns_empty(self) -> None:
        """search_deferred() returns [] if no tools match the query."""
        reg = ToolRegistry()
        reg.register(_make_tool("mcp_github_list_repos", "List GitHub repositories"), deferred=True)
        # Completely unrelated term with zero BM25 score
        results = reg.search_deferred("xyzzy_does_not_match")
        assert results == []

    def test_returns_tuples_of_name_and_description(self) -> None:
        """Results are (name, description) tuples."""
        reg = ToolRegistry()
        reg.register(_make_tool("mcp_github_create_pr", "Create a GitHub pull request"), deferred=True)
        results = reg.search_deferred("pull request")
        assert len(results) >= 1
        name, desc = results[0]
        assert isinstance(name, str)
        assert isinstance(desc, str)

    def test_limit_respected(self) -> None:
        """search_deferred() returns at most `limit` results."""
        reg = ToolRegistry()
        for i in range(10):
            reg.register(_make_tool(f"mcp_test_tool{i}", f"Tool number {i} for testing"), deferred=True)
        results = reg.search_deferred("tool testing", limit=3)
        assert len(results) <= 3

    def test_searches_only_deferred_not_active(self) -> None:
        """Active tools are not returned by search_deferred()."""
        reg = ToolRegistry()
        reg.register(_make_tool("mcp_github_list_repos", "List GitHub repositories"))  # active
        results = reg.search_deferred("github")
        assert results == []


class TestGetDeferredSummary:
    """Tests for get_deferred_summary()."""

    def test_empty_returns_none(self) -> None:
        """Returns None when no deferred tools."""
        reg = ToolRegistry()
        assert reg.get_deferred_summary() is None

    def test_mcp_tools_grouped_by_server(self) -> None:
        """MCP tools are grouped by server name extracted from prefix."""
        reg = ToolRegistry()
        reg.register(_make_tool("mcp_github_list_repos", "List repos"), deferred=True)
        reg.register(_make_tool("mcp_github_create_pr", "Create PR"), deferred=True)
        reg.register(_make_tool("mcp_slack_send", "Send message"), deferred=True)
        summary = reg.get_deferred_summary()
        assert "github (2 tools)" in summary
        assert "slack (1 tools)" in summary

    def test_non_mcp_tools_listed_by_name(self) -> None:
        """Non-mcp_ tools are listed individually."""
        reg = ToolRegistry()
        reg.register(_make_tool("custom_tool", "Custom"), deferred=True)
        summary = reg.get_deferred_summary()
        assert "custom_tool" in summary


# ---------------------------------------------------------------------------
# SearchToolsTool tests
# ---------------------------------------------------------------------------


class TestSearchToolsTool:
    """Tests for the SearchToolsTool agent tool."""

    @pytest.mark.asyncio
    async def test_activates_matching_tools(self) -> None:
        """execute() activates tools matching the query and confirms in result."""
        reg = ToolRegistry()
        reg.register(_make_tool("mcp_github_list_repos", "List GitHub repositories"), deferred=True)
        tool = SearchToolsTool(reg)
        result = await tool.execute(query="github repositories")
        assert "mcp_github_list_repos" in result
        assert "mcp_github_list_repos" in reg  # now active

    @pytest.mark.asyncio
    async def test_no_match_returns_hint_message(self) -> None:
        """execute() returns a helpful message when no tools match."""
        reg = ToolRegistry()
        reg.register(_make_tool("mcp_slack_send", "Send Slack messages"), deferred=True)
        tool = SearchToolsTool(reg)
        result = await tool.execute(query="xyzzy_no_match_possible")
        assert "No deferred tools matched" in result

    @pytest.mark.asyncio
    async def test_empty_registry_returns_hint(self) -> None:
        """execute() is safe when no deferred tools are registered at all."""
        reg = ToolRegistry()
        tool = SearchToolsTool(reg)
        result = await tool.execute(query="anything")
        assert "No deferred tools matched" in result

    @pytest.mark.asyncio
    async def test_result_lists_activated_tools(self) -> None:
        """Result message lists activated tool names."""
        reg = ToolRegistry()
        reg.register(_make_tool("mcp_github_create_pr", "Create a GitHub pull request"), deferred=True)
        tool = SearchToolsTool(reg)
        result = await tool.execute(query="create pull request")
        assert "Activated" in result
        assert "mcp_github_create_pr" in result

    @pytest.mark.asyncio
    async def test_max_results_respected(self) -> None:
        """Only up to max_results tools are activated per call."""
        reg = ToolRegistry()
        for i in range(10):
            reg.register(_make_tool(f"mcp_test_op{i}", f"Operation {i} for testing"), deferred=True)
        tool = SearchToolsTool(reg, max_results=2)
        await tool.execute(query="operation testing")
        # At most 2 tools should have been activated
        assert len(reg) <= 2

    def test_tool_name_and_description(self) -> None:
        """SearchToolsTool has expected name and description."""
        reg = ToolRegistry()
        tool = SearchToolsTool(reg)
        assert tool.name == "search_tools"
        assert "search" in tool.description.lower()

    def test_schema_has_query_parameter(self) -> None:
        """Tool schema requires 'query' parameter."""
        reg = ToolRegistry()
        tool = SearchToolsTool(reg)
        params = tool.parameters
        assert "query" in params["properties"]
        assert "query" in params["required"]
