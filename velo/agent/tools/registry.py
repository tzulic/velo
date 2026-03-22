"""Tool registry for dynamic tool management."""

from typing import Any

from velo.agent.tools.base import Tool
from velo.agent.tools.sanitize import sanitize_tool_result

# Sentinel for cache invalidation (distinct from None which is a valid return value)
_SENTINEL = object()

# Tools restricted in group chat sessions
_GROUP_RESTRICTED_TOOLS: frozenset[str] = frozenset(
    {
        "exec",
        "write_file",
        "edit_file",
        "skill_manage",
        "skill_create",
        "skill_edit",
        "skill_patch",
        "skill_delete",
        "cron",
        "cron_create",
        "cron_delete",
        "spawn",
    }
)


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    Tools can be registered as active (immediately available) or deferred
    (available on-demand via search_tools). Deferred tools are not included
    in get_definitions() and do not consume LLM context until activated.
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._deferred: dict[str, Tool] = {}
        self._cached_deferred_summary: str | None | object = _SENTINEL

    def register(self, tool: Tool, *, deferred: bool = False) -> None:
        """Register a tool.

        Args:
            tool: Tool instance to register.
            deferred: If True, register as deferred (not sent to LLM until activated).
        """
        if deferred:
            self._deferred[tool.name] = tool
            self._invalidate_deferred_cache()
        else:
            self._tools[tool.name] = tool

    def activate(self, name: str) -> bool:
        """Move a tool from deferred pool into active tools.

        Args:
            name: Tool name to activate.

        Returns:
            True if the tool was found and activated, False if not in deferred pool.
        """
        tool = self._deferred.pop(name, None)
        if tool is None:
            return False
        self._tools[name] = tool
        self._invalidate_deferred_cache()
        return True

    def search_deferred(self, query: str, limit: int = 5) -> list[tuple[str, str]]:
        """BM25 search against deferred tools name+description corpus.

        Uses BM25 as primary ranking. Falls back to substring matching when BM25
        returns no positive-scored results (common with very small corpora where
        IDF weights collapse to zero).

        Args:
            query: Keywords to search for.
            limit: Maximum number of results to return.

        Returns:
            List of (name, description) tuples ranked by relevance.
        """
        if not self._deferred:
            return []

        from rank_bm25 import BM25Okapi

        corpus_items = list(self._deferred.items())
        corpus = [f"{name} {tool.description}".lower().split() for name, tool in corpus_items]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(query.lower().split())
        ranked = sorted(zip(scores, corpus_items), reverse=True)
        results = [(name, tool.description) for score, (name, tool) in ranked[:limit] if score > 0]

        # Fallback: substring matching when BM25 gives no positive scores.
        # This happens with small corpora where IDF weights collapse to zero.
        if not results:
            query_words = query.lower().split()
            for name, tool in self._deferred.items():
                corpus_str = f"{name} {tool.description}".lower()
                if any(w in corpus_str for w in query_words):
                    results.append((name, tool.description))
                    if len(results) >= limit:
                        break

        return results

    # Prefixes used to group deferred tools in summaries.
    # (prefix_to_strip, display_prefix): "mcp_github_foo" → group key "github"
    _TOOL_PREFIXES: list[tuple[str, str]] = [
        ("mcp_", ""),
        ("composio_", "composio:"),
    ]

    def get_deferred_summary(self) -> str | None:
        """Return a concise summary of deferred tools grouped by source.

        Groups tools by known prefixes (``mcp_``, ``composio_``). Ungrouped
        deferred tools are listed by name. Results are cached until the deferred
        pool changes (register, activate, or unregister).

        Returns:
            Comma-separated string like "github (12 tools), composio:gmail (5 tools)",
            or None if no deferred tools.
        """
        if self._cached_deferred_summary is not _SENTINEL:
            return self._cached_deferred_summary  # type: ignore[return-value]

        if not self._deferred:
            result = None
        else:
            groups: dict[str, int] = {}
            for name in self._deferred:
                key = self._deferred_group_key(name)
                groups[key] = groups.get(key, 0) + 1
            result = ", ".join(f"{g} ({c} tools)" for g, c in sorted(groups.items()))

        self._cached_deferred_summary = result
        return result

    def _deferred_group_key(self, name: str) -> str:
        """Derive the display group key for a deferred tool name.

        Args:
            name: Full tool name (e.g., ``mcp_github_create_issue``).

        Returns:
            Group key (e.g., ``github``).
        """
        for prefix, display_prefix in self._TOOL_PREFIXES:
            if name.startswith(prefix):
                segment = name[len(prefix) :].split("_")[0]
                return f"{display_prefix}{segment}"
        return name

    def _invalidate_deferred_cache(self) -> None:
        """Reset the cached deferred summary so the next call recomputes it."""
        self._cached_deferred_summary = _SENTINEL

    def unregister(self, name: str) -> None:
        """Unregister a tool by name (active or deferred)."""
        self._tools.pop(name, None)
        if self._deferred.pop(name, None) is not None:
            self._invalidate_deferred_cache()

    def get(self, name: str) -> Tool | None:
        """Get an active tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered (active only)."""
        return name in self._tools

    def get_definitions(
        self, session_metadata: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Get all active tool definitions in OpenAI format.

        Args:
            session_metadata: Optional session context. If is_group=True,
                dangerous tools are filtered out.

        Returns:
            List of tool schemas.
        """
        is_group = (session_metadata or {}).get("is_group", False)
        tools = self._tools.values()
        if is_group:
            tools = [t for t in tools if t.name not in _GROUP_RESTRICTED_TOOLS]
        return [tool.to_schema() for tool in tools]

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """Execute a tool by name with given parameters."""
        hint = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        try:
            # Attempt to cast parameters to match schema types
            params = tool.cast_params(params)

            # Validate parameters
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + hint
            result = await tool.execute(**params)
            result = sanitize_tool_result(result)
            if isinstance(result, str) and result.startswith("Error"):
                return result + hint
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + hint

    @property
    def tool_names(self) -> list[str]:
        """Get list of active registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
