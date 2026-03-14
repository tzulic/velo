"""Tool registry for dynamic tool management."""

from typing import Any

from velo.agent.tools.base import Tool


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

    def register(self, tool: Tool, *, deferred: bool = False) -> None:
        """Register a tool.

        Args:
            tool: Tool instance to register.
            deferred: If True, register as deferred (not sent to LLM until activated).
        """
        if deferred:
            self._deferred[tool.name] = tool
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

    def get_deferred_summary(self) -> str | None:
        """Return a concise summary of deferred tools grouped by MCP server.

        Groups tools by their mcp_{server_name} prefix. Non-MCP deferred tools
        are listed by name.

        Returns:
            Comma-separated string like "github (12 tools), slack (8 tools)", or
            None if no deferred tools.
        """
        if not self._deferred:
            return None

        groups: dict[str, int] = {}
        for name in self._deferred:
            if name.startswith("mcp_"):
                # mcp_{server_name}_{tool_name}: extract server_name as first segment
                rest = name[4:]  # strip "mcp_"
                server = rest.split("_")[0]
                groups[server] = groups.get(server, 0) + 1
            elif name.startswith("composio_"):
                # composio_{toolkit}_{action}: extract toolkit as first segment
                rest = name[9:]  # strip "composio_"
                toolkit = rest.split("_")[0]
                key = f"composio:{toolkit}"
                groups[key] = groups.get(key, 0) + 1
            else:
                groups[name] = groups.get(name, 0) + 1

        return ", ".join(f"{g} ({c} tools)" for g, c in sorted(groups.items()))

    def unregister(self, name: str) -> None:
        """Unregister a tool by name (active or deferred)."""
        self._tools.pop(name, None)
        self._deferred.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Get an active tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered (active only)."""
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get all active tool definitions in OpenAI format."""
        return [tool.to_schema() for tool in self._tools.values()]

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
