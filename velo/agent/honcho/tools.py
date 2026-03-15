"""Honcho tools: search, query, profile, and conclude tools for the agent.

Tools following the velo/agent/tools/base.py ABC pattern.
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
    """Ask Honcho about the user or the AI assistant via dialectic reasoning.

    Costs $0.001-$0.50 per query. Use sparingly for complex questions
    about preferences, patterns, or history.
    """

    name = "honcho_query"
    description = (
        "Ask a question about the user or AI assistant based on conversation history and profile. "
        "Use for deeper questions like 'What topics does this user care about?' or "
        "'What is the user's communication style?'. Costs a small amount per query."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Question about the user or AI assistant.",
            },
            "peer": {
                "type": "string",
                "enum": ["user", "ai"],
                "description": "Which peer to query. 'user' for the human, 'ai' for the assistant. Default: user.",
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

    async def execute(self, query: str, peer: str = "user", **kwargs: Any) -> str:
        """Execute dialectic query against Honcho.

        Args:
            query: Question about the user or AI assistant.
            peer: Which peer to query — "user" or "ai". Default: "user".
            **kwargs: Additional parameters (ignored).

        Returns:
            Honcho's response.
        """
        key = self._adapter.current_session_key
        if not key:
            return json.dumps({"error": "No active session for Honcho query."})

        return await self._adapter.dialectic_query(key, query, peer=peer)


class HonchoProfileTool(Tool):
    """Get the user's profile — curated facts from past conversations.

    Free and instant. Returns the peer card which is Honcho's accumulated
    understanding of the user.
    """

    name = "honcho_profile"
    description = (
        "Get the user's profile — curated facts from past conversations. "
        "Free, instant, no LLM cost. Returns identity, preferences, goals, "
        "communication style, and other learned facts."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, adapter: HonchoAdapter) -> None:
        """Initialize profile tool.

        Args:
            adapter: HonchoAdapter instance (provides current session key).
        """
        self._adapter = adapter

    async def execute(self, **kwargs: Any) -> str:
        """Get the user's peer card from Honcho.

        Args:
            **kwargs: Additional parameters (ignored).

        Returns:
            User profile text.
        """
        key = self._adapter.current_session_key
        if not key:
            return json.dumps({"error": "No active session for Honcho profile."})

        result = await self._adapter.get_peer_card(key)
        return result if result else "No user profile available yet."


class HonchoConcludeTool(Tool):
    """Record a structured conclusion about the user that directly updates their profile.

    Use when you learn preferences, timezone, goals, skills, or communication style.
    Stronger than notes — directly updates the peer card.
    """

    name = "honcho_conclude"
    description = (
        "Record a structured conclusion about the user that directly updates their profile. "
        "Use when you learn preferences, timezone, goals, skills, or communication style. "
        "Triggers immediate profile update."
    )
    parameters = {
        "type": "object",
        "properties": {
            "conclusion": {
                "type": "string",
                "description": "A structured fact about the user (e.g. 'User prefers dark mode and uses GMT+1').",
            },
        },
        "required": ["conclusion"],
    }

    def __init__(self, adapter: HonchoAdapter) -> None:
        """Initialize conclude tool.

        Args:
            adapter: HonchoAdapter instance (provides current session key).
        """
        self._adapter = adapter

    async def execute(self, conclusion: str, **kwargs: Any) -> str:
        """Record a conclusion about the user in Honcho.

        Args:
            conclusion: Structured fact about the user.
            **kwargs: Additional parameters (ignored).

        Returns:
            Confirmation message.
        """
        key = self._adapter.current_session_key
        if not key:
            return json.dumps({"error": "No active session for Honcho conclude."})

        await self._adapter.add_conclusion(key, conclusion)
        return "Conclusion recorded. The user's profile will be updated."
