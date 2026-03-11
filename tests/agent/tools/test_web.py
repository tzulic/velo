"""Tests for Parallel.ai-backed web tools."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from velo.agent.tools.web import WebFetchTool, WebSearchTool

# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------


class TestWebSearchTool:
    """Tests for WebSearchTool using Parallel.ai."""

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_error(self) -> None:
        """Missing API key should return a helpful error message."""
        tool = WebSearchTool(api_key=None)
        result = await tool.execute(query="test")
        assert "PARALLEL_API_KEY" in result
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_happy_path_returns_formatted_results(self) -> None:
        """Successful search returns formatted titles, URLs, and excerpts."""
        mock_item = MagicMock()
        mock_item.title = "Example Page"
        mock_item.url = "https://example.com"
        mock_item.excerpts = ["This is a test excerpt."]

        mock_search = MagicMock()
        mock_search.results = [mock_item]

        mock_client = AsyncMock()
        mock_client.beta.search = AsyncMock(return_value=mock_search)

        with patch("velo.agent.tools.web.AsyncParallel", return_value=mock_client):
            tool = WebSearchTool(api_key="test-key")
            result = await tool.execute(query="test query")

        assert "Example Page" in result
        assert "https://example.com" in result
        assert "test excerpt" in result

    @pytest.mark.asyncio
    async def test_empty_results_returns_no_results_message(self) -> None:
        """Empty search results should return a 'No results' message."""
        mock_search = MagicMock()
        mock_search.results = []

        mock_client = AsyncMock()
        mock_client.beta.search = AsyncMock(return_value=mock_search)

        with patch("velo.agent.tools.web.AsyncParallel", return_value=mock_client):
            tool = WebSearchTool(api_key="test-key")
            result = await tool.execute(query="obscure query")

        assert "No results" in result

    @pytest.mark.asyncio
    async def test_network_error_returns_error_message(self) -> None:
        """Network errors should be caught and returned as error strings."""
        mock_client = AsyncMock()
        mock_client.beta.search = AsyncMock(side_effect=ConnectionError("timeout"))

        with patch("velo.agent.tools.web.AsyncParallel", return_value=mock_client):
            tool = WebSearchTool(api_key="test-key")
            result = await tool.execute(query="test")

        assert "Error" in result
        assert "timeout" in result


# ---------------------------------------------------------------------------
# WebFetchTool
# ---------------------------------------------------------------------------


class TestWebFetchTool:
    """Tests for WebFetchTool using Parallel.ai."""

    @pytest.mark.asyncio
    async def test_invalid_url_returns_validation_error(self) -> None:
        """Non-http URL should be rejected."""
        tool = WebFetchTool(api_key="test-key")
        result = await tool.execute(url="ftp://example.com")
        data = json.loads(result)
        assert "error" in data
        assert "http" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_error(self) -> None:
        """Missing API key should return a helpful JSON error."""
        tool = WebFetchTool(api_key=None)
        result = await tool.execute(url="https://example.com")
        data = json.loads(result)
        assert "error" in data
        assert "PARALLEL_API_KEY" in data["error"]

    @pytest.mark.asyncio
    async def test_happy_path_returns_json_with_content(self) -> None:
        """Successful fetch returns JSON with content, url, length."""
        mock_item = MagicMock()
        mock_item.full_content = "# Hello World\n\nSome content here."
        mock_item.excerpts = ["Some excerpt"]
        mock_item.url = "https://example.com"

        mock_extract = MagicMock()
        mock_extract.results = [mock_item]

        mock_client = AsyncMock()
        mock_client.beta.extract = AsyncMock(return_value=mock_extract)

        with patch("velo.agent.tools.web.AsyncParallel", return_value=mock_client):
            tool = WebFetchTool(api_key="test-key")
            result = await tool.execute(url="https://example.com")

        data = json.loads(result)
        assert data["url"] == "https://example.com"
        assert "Hello World" in data["text"]
        assert data["extractor"] == "parallel"
        assert isinstance(data["length"], int)

    @pytest.mark.asyncio
    async def test_truncation_respects_max_chars(self) -> None:
        """Content exceeding maxChars should be truncated."""
        long_content = "x" * 200

        mock_item = MagicMock()
        mock_item.full_content = long_content
        mock_item.excerpts = []
        mock_item.url = "https://example.com"

        mock_extract = MagicMock()
        mock_extract.results = [mock_item]

        mock_client = AsyncMock()
        mock_client.beta.extract = AsyncMock(return_value=mock_extract)

        with patch("velo.agent.tools.web.AsyncParallel", return_value=mock_client):
            tool = WebFetchTool(api_key="test-key", max_chars=100)
            result = await tool.execute(url="https://example.com")

        data = json.loads(result)
        assert data["truncated"] is True
        assert data["length"] == 100

    @pytest.mark.asyncio
    async def test_network_error_returns_error_json(self) -> None:
        """Network errors should be caught and returned as error JSON."""
        mock_client = AsyncMock()
        mock_client.beta.extract = AsyncMock(side_effect=ConnectionError("refused"))

        with patch("velo.agent.tools.web.AsyncParallel", return_value=mock_client):
            tool = WebFetchTool(api_key="test-key")
            result = await tool.execute(url="https://example.com")

        data = json.loads(result)
        assert "error" in data
        assert "refused" in data["error"]
