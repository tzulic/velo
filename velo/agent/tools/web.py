"""Web tools: web_search and web_fetch using Parallel.ai."""

import json
import os
from typing import Any

from loguru import logger
from parallel import AsyncParallel

from velo.agent.tools.base import Tool


def _resolve_parallel_api_key(init_key: str | None) -> str:
    """Resolve Parallel.ai API key from init value or environment.

    Args:
        init_key: Explicitly provided API key (takes priority).

    Returns:
        The resolved API key, or empty string if not configured.
    """
    return init_key or os.environ.get("PARALLEL_API_KEY", "")


_PARALLEL_KEY_ERROR = (
    "Error: Parallel.ai API key not configured. Set it in "
    "~/.velo/config.json under tools.web.search.apiKey "
    "(or export PARALLEL_API_KEY), then restart the gateway."
)


class WebSearchTool(Tool):
    """Search the web using Parallel.ai."""

    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {
                "type": "integer",
                "description": "Results (1-10)",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        api_key: str | None = None,
        max_results: int = 5,
    ):
        """Initialize web search tool.

        Args:
            api_key: Parallel.ai API key. Falls back to PARALLEL_API_KEY env var.
            max_results: Default number of results to return.
        """
        self._init_api_key = api_key
        self.max_results = max_results
        self._client: AsyncParallel | None = None
        self._client_key: str = ""

    def _get_client(self) -> AsyncParallel:
        """Return a cached AsyncParallel client, recreating if API key changed."""
        key = _resolve_parallel_api_key(self._init_api_key)
        if self._client is None or key != self._client_key:
            self._client = AsyncParallel(api_key=key)
            self._client_key = key
        return self._client

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        """Execute a web search via Parallel.ai.

        Args:
            query: Search query string.
            count: Number of results to return.
            **kwargs: Additional parameters (ignored).

        Returns:
            Formatted search results or error message.
        """
        api_key = _resolve_parallel_api_key(self._init_api_key)
        if not api_key:
            return _PARALLEL_KEY_ERROR

        try:
            n = min(max(count or self.max_results, 1), 10)
            logger.debug("WebSearch: querying Parallel.ai for '{}' (max {})", query, n)

            client = self._get_client()
            search = await client.beta.search(
                objective=query,
                search_queries=[query],
                mode="fast",
                max_results=n,
                excerpts={"max_chars_per_result": 500},
            )

            results = search.results[:n] if search.results else []
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results, 1):
                title = getattr(item, "title", "") or ""
                url = getattr(item, "url", "") or ""
                excerpts = getattr(item, "excerpts", []) or []
                lines.append(f"{i}. {title}\n   {url}")
                if excerpts:
                    # Reason: Join excerpts for a richer snippet
                    snippet = " ".join(excerpts)[:500]
                    lines.append(f"   {snippet}")
            return "\n".join(lines)
        except Exception as e:
            logger.error("WebSearch error: {}", e)
            return f"Error: {e}"


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using Parallel.ai."""

    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML -> markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "max_chars": {"type": "integer", "minimum": 100},
        },
        "required": ["url"],
    }

    def __init__(
        self,
        api_key: str | None = None,
        max_chars: int = 50000,
    ):
        """Initialize web fetch tool.

        Args:
            api_key: Parallel.ai API key. Falls back to PARALLEL_API_KEY env var.
            max_chars: Maximum characters to return in content.
        """
        self._init_api_key = api_key
        self.max_chars = max_chars
        self._client: AsyncParallel | None = None
        self._client_key: str = ""

    def _get_client(self) -> AsyncParallel:
        """Return a cached AsyncParallel client, recreating if API key changed."""
        key = _resolve_parallel_api_key(self._init_api_key)
        if self._client is None or key != self._client_key:
            self._client = AsyncParallel(api_key=key)
            self._client_key = key
        return self._client

    async def execute(
        self,
        url: str,
        max_chars: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Fetch and extract content from a URL via Parallel.ai.

        Args:
            url: URL to fetch.
            max_chars: Override for max characters to return.
            **kwargs: Additional parameters (ignored).

        Returns:
            JSON string with url, content, length, and truncated flag.
        """
        if not url.startswith(("http://", "https://")):
            return json.dumps(
                {"error": "URL must start with http:// or https://", "url": url},
                ensure_ascii=False,
            )

        api_key = _resolve_parallel_api_key(self._init_api_key)
        if not api_key:
            return json.dumps(
                {"error": _PARALLEL_KEY_ERROR, "url": url},
                ensure_ascii=False,
            )

        max_chars = max_chars or self.max_chars

        try:
            logger.debug("WebFetch: extracting content from '{}'", url)

            client = self._get_client()
            extract = await client.beta.extract(
                urls=[url],
                objective="Extract the main content from this page",
                excerpts=True,
                full_content=True,
            )

            # Reason: Parallel returns a list of results matching the urls list
            results = getattr(extract, "results", []) or []
            if results:
                item = results[0]
                # Reason: full_content holds the full page text; excerpts is a list of snippets
                text = (
                    getattr(item, "full_content", "")
                    or " ".join(getattr(item, "excerpts", []) or [])
                    or ""
                )
                final_url = getattr(item, "url", url) or url
            else:
                text = str(extract) if extract else ""
                final_url = url

            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            return json.dumps(
                {
                    "url": url,
                    "finalUrl": final_url,
                    "extractor": "parallel",
                    "truncated": truncated,
                    "length": len(text),
                    "text": text,
                },
                ensure_ascii=False,
            )
        except Exception as e:
            logger.error("WebFetch error for {}: {}", url, e)
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)
