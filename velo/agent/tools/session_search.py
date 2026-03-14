"""Session search tool for recalling past conversations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from velo.agent.tools.base import Tool

if TYPE_CHECKING:
    from velo.session.sqlite_store import SQLiteSessionStore


class SessionSearchTool(Tool):
    """Tool to search past conversations by keyword."""

    def __init__(self, store: SQLiteSessionStore) -> None:
        """Initialize with a SQLite session store.

        Args:
            store: SQLiteSessionStore instance for searching.
        """
        self._store = store

    @property
    def name(self) -> str:
        """Tool name used in function calls."""
        return "session_search"

    @property
    def description(self) -> str:
        """Description of what the tool does."""
        return (
            "Search past conversations by keyword to recall prior context, "
            "decisions, and file paths discussed in earlier sessions."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keywords",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, max_results: int = 5, **kwargs: Any) -> str:
        """Execute session search and format results.

        Args:
            query: Search keywords.
            max_results: Maximum number of results to return.
            **kwargs: Additional keyword arguments (ignored).

        Returns:
            Formatted string of search results or a no-match message.
        """
        results = self._store.search_messages(query, max_results)

        if not results:
            return f"No matching sessions found for: {query}"

        lines: list[str] = [f"Found {len(results)} result(s) for '{query}':\n"]
        for i, hit in enumerate(results, start=1):
            content_snippet = hit["content"]  # Already truncated by store
            lines.append(
                f"{i}. [{hit['session_key']}] ({hit.get('created_at', 'unknown date')})\n"
                f"   {content_snippet}\n"
            )

        return "\n".join(lines)
