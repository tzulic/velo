"""Tests for the Context Hub builtin plugin."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from velo.plugins.builtin.chub.tools import ChubSearchTool


class TestChubSearchTool:
    """Tests for chub_search tool."""

    def test_tool_name_and_schema(self) -> None:
        """Tool has correct name and required query parameter."""
        tool = ChubSearchTool(workspace=Path("/tmp"), config={})
        assert tool.name == "chub_search"
        assert "query" in tool.parameters["properties"]
        assert "query" in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_search_success(self) -> None:
        """Successful search returns CLI stdout."""
        tool = ChubSearchTool(workspace=Path("/tmp"), config={})

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"stripe/api - Stripe API docs\n", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            result = await tool.execute(query="stripe")
            assert "stripe/api" in result

    @pytest.mark.asyncio
    async def test_search_timeout(self) -> None:
        """Timeout returns human-readable error."""
        tool = ChubSearchTool(workspace=Path("/tmp"), config={"search_timeout": 1})

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await tool.execute(query="stripe")
            assert "timed out" in result.lower()

    @pytest.mark.asyncio
    async def test_search_cli_not_found(self) -> None:
        """Missing CLI returns clear error."""
        tool = ChubSearchTool(workspace=Path("/tmp"), config={})

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await tool.execute(query="stripe")
            assert "not available" in result.lower() or "not found" in result.lower()
