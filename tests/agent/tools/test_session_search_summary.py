"""Tests for session search with LLM summarization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from velo.agent.tools.session_search import SessionSearchTool
from velo.providers.base import LLMProvider, LLMResponse


@pytest.mark.asyncio
async def test_summarized_results_when_provider_available():
    """When a summarize_provider is given, execute returns LLM-generated summary."""
    store = MagicMock()
    store.search_messages.return_value = [
        {"session_key": "s1", "content": "We discussed budgets", "created_at": "2026-03-01"},
    ]
    provider = AsyncMock(spec=LLMProvider)
    provider.chat = AsyncMock(return_value=LLMResponse(content="Budget was set to $5000."))
    tool = SessionSearchTool(store, summarize_provider=provider, summarize_model="test")
    result = await tool.execute(query="budget")
    assert "Budget was set to $5000" in result


@pytest.mark.asyncio
async def test_raw_results_as_fallback():
    """Without a summarize_provider, execute returns raw formatted results."""
    store = MagicMock()
    store.search_messages.return_value = [
        {"session_key": "s1", "content": "We discussed budgets", "created_at": "2026-03-01"},
    ]
    tool = SessionSearchTool(store)
    result = await tool.execute(query="budget")
    assert "s1" in result


@pytest.mark.asyncio
async def test_empty_results():
    """When no results found, returns a no-match message."""
    store = MagicMock()
    store.search_messages.return_value = []
    tool = SessionSearchTool(store)
    result = await tool.execute(query="nonexistent")
    assert "No matching" in result


@pytest.mark.asyncio
async def test_summarize_failure_falls_back_to_raw():
    """When LLM summarization fails, falls back to raw results."""
    store = MagicMock()
    store.search_messages.return_value = [
        {"session_key": "s1", "content": "Budget info", "created_at": "2026-03-01"},
    ]
    provider = AsyncMock(spec=LLMProvider)
    provider.chat = AsyncMock(side_effect=Exception("LLM error"))
    tool = SessionSearchTool(store, summarize_provider=provider, summarize_model="test")
    result = await tool.execute(query="budget")
    assert "s1" in result  # Falls back to raw results
