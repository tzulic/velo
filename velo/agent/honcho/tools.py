"""Honcho tools: search, query, and note tools for the agent.

Three tools following the velo/agent/tools/base.py ABC pattern.
Each takes a HonchoAdapter reference and reads the current session
key from the adapter at execution time.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from velo.agent.tools.base import Tool

if TYPE_CHECKING:
    from velo.agent.honcho.adapter import HonchoAdapter


class HonchoSearchTool(Tool):
    """Semantic search across the user's conversation history and context.

    Free operation. Searches all Honcho sessions for this user and returns
    relevant context matches.
    """

    name = "honcho_search"
    description = (
        "Search the user's conversation history and profile for relevant context. "
        "Use when you need to recall something the user mentioned in past conversations. "
        "Free and fast (~200ms)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query about the user or past conversations.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, adapter: HonchoAdapter) -> None:
        """Initialize search tool.

        Args:
            adapter: HonchoAdapter instance (provides current session key).
        """
        self._adapter = adapter

    async def execute(self, query: str, **kwargs: Any) -> str:
        """Execute semantic search against Honcho.

        Args:
            query: Natural language search query.
            **kwargs: Additional parameters (ignored).

        Returns:
            Search results as formatted text.
        """
        key = self._adapter.current_session_key
        if not key:
            return json.dumps({"error": "No active session for Honcho search."})

        return await self._adapter.search_context(key, query)


class HonchoQueryTool(Tool):
    """Ask Honcho about the user via dialectic reasoning.

    Costs $0.001-$0.50 per query. Use sparingly for complex questions
    about the user's preferences, patterns, or history.
    """

    name = "honcho_query"
    description = (
        "Ask a question about the user based on their conversation history and profile. "
        "Use for deeper questions like 'What topics does this user care about?' or "
        "'What is the user's communication style?'. Costs a small amount per query."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Question about the user to ask the user-modeling system.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, adapter: HonchoAdapter) -> None:
        """Initialize query tool.

        Args:
            adapter: HonchoAdapter instance (provides current session key).
        """
        self._adapter = adapter

    async def execute(self, query: str, **kwargs: Any) -> str:
        """Execute dialectic query against Honcho.

        Args:
            query: Question about the user.
            **kwargs: Additional parameters (ignored).

        Returns:
            Honcho's response about the user.
        """
        key = self._adapter.current_session_key
        if not key:
            return json.dumps({"error": "No active session for Honcho query."})

        return await self._adapter.dialectic_query(key, query)


class HonchoNoteTool(Tool):
    """Record a fact or observation about the user.

    Triggers Honcho's background reasoning pipeline to update the user's
    peer card. Use when you learn something important about the user.
    """

    name = "honcho_note"
    description = (
        "Record an important observation or fact about the user. "
        "Examples: their timezone, preferred communication style, a project they're working on, "
        "or a preference they expressed. Triggers background processing to update the user model."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The fact or observation to record about the user.",
            },
        },
        "required": ["content"],
    }

    def __init__(self, adapter: HonchoAdapter) -> None:
        """Initialize note tool.

        Args:
            adapter: HonchoAdapter instance (provides current session key).
        """
        self._adapter = adapter

    async def execute(self, content: str, **kwargs: Any) -> str:
        """Record a note about the user in Honcho.

        Args:
            content: Fact or observation to record.
            **kwargs: Additional parameters (ignored).

        Returns:
            Confirmation message.
        """
        key = self._adapter.current_session_key
        if not key:
            return json.dumps({"error": "No active session for Honcho note."})

        await self._adapter.add_note(key, content)
        return "Note recorded. It will be incorporated into the user model."
