"""Session search tool for recalling past conversations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from velo.agent.tools.base import Tool

if TYPE_CHECKING:
    from velo.providers.base import LLMProvider
    from velo.session.sqlite_store import SQLiteSessionStore

_SUMMARIZE_PROMPT = (
    "You are a helpful assistant. The user searched their past conversations for: {query}\n\n"
    "Here are the relevant excerpts:\n\n{snippets}\n\n"
    "Please provide a concise, coherent answer based on these past conversations. "
    "Focus on the most relevant information and synthesize it into a direct response."
)
_SUMMARIZE_MAX_TOKENS = 512


class SessionSearchTool(Tool):
    """Tool to search past conversations by keyword."""

    def __init__(
        self,
        store: SQLiteSessionStore,
        summarize_provider: LLMProvider | None = None,
        summarize_model: str | None = None,
    ) -> None:
        """Initialize with a SQLite session store and optional summarization provider.

        Args:
            store: SQLiteSessionStore instance for searching.
            summarize_provider: Optional LLM provider for summarizing results.
            summarize_model: Model identifier to use with summarize_provider.
        """
        self._store = store
        self._summarize_provider = summarize_provider
        self._summarize_model = summarize_model

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

    def _format_results(self, query: str, results: list[dict[str, Any]]) -> str:
        """Format raw search results into a readable string.

        Args:
            query: The original search query.
            results: List of result dicts from the session store.

        Returns:
            Formatted multi-line string of results.
        """
        lines: list[str] = [f"Found {len(results)} result(s) for '{query}':\n"]
        for i, hit in enumerate(results, start=1):
            content_snippet = hit["content"]  # Already truncated by store
            lines.append(
                f"{i}. [{hit['session_key']}] ({hit.get('created_at', 'unknown date')})\n"
                f"   {content_snippet}\n"
            )
        return "\n".join(lines)

    async def _summarize(self, query: str, results: list[dict[str, Any]]) -> str:
        """Summarize search results using the configured LLM provider.

        Args:
            query: The original search query.
            results: List of result dicts to summarize.

        Returns:
            LLM-generated summary string.

        Raises:
            Exception: Propagates any LLM provider errors to the caller.
        """
        snippets = "\n\n".join(
            f"[{hit['session_key']}] ({hit.get('created_at', 'unknown date')})\n{hit['content']}"
            for hit in results
        )
        prompt = _SUMMARIZE_PROMPT.format(query=query, snippets=snippets)
        assert self._summarize_provider is not None  # Caller must check before calling
        response = await self._summarize_provider.chat(
            messages=[{"role": "user", "content": prompt}],
            model=self._summarize_model,
            max_tokens=_SUMMARIZE_MAX_TOKENS,
            temperature=0.3,
        )
        return response.content or self._format_results(query, results)

    async def execute(self, query: str, max_results: int = 5, **kwargs: Any) -> str:
        """Execute session search and return summarized or raw results.

        If a summarize_provider is configured, the results are synthesized into
        a coherent answer by the LLM. On failure, falls back to raw formatted output.

        Args:
            query: Search keywords.
            max_results: Maximum number of results to return.
            **kwargs: Additional keyword arguments (ignored).

        Returns:
            Summarized answer or formatted string of search results, or a no-match message.
        """
        results = self._store.search_messages(query, max_results)

        if not results:
            return f"No matching sessions found for: {query}"

        if self._summarize_provider is not None:
            try:
                return await self._summarize(query, results)
            except Exception:
                logger.warning("session_search.summarize_failed — falling back to raw results")

        return self._format_results(query, results)
