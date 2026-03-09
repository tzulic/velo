"""SearchToolsTool: activates deferred tools on demand via BM25 keyword search."""

from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry


class SearchToolsTool(Tool):
    """Search for and activate deferred tools by keyword.

    Use this when you need a capability not currently available — for example,
    accessing GitHub, Slack, databases, or other MCP server integrations.
    Activated tools become available immediately in your next action.
    """

    def __init__(self, registry: ToolRegistry, max_results: int = 5) -> None:
        """Initialize the tool with a reference to the shared registry.

        Args:
            registry: The ToolRegistry instance to search and activate from.
            max_results: Maximum number of tools to activate per search.
        """
        self._registry = registry
        self._max_results = max_results

    @property
    def name(self) -> str:
        return "search_tools"

    @property
    def description(self) -> str:
        return (
            "Search for available tools by keyword and activate them for use. "
            "Use this when you need a capability not currently available — for example, "
            "accessing GitHub, Slack, databases, or other MCP server integrations. "
            "Activated tools become available immediately in your next action."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Keywords describing the capability you need "
                        "(e.g. 'github pull request', 'send slack message')"
                    ),
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, **kwargs: Any) -> str:
        """Search for deferred tools matching the query and activate them.

        Args:
            query: Keywords describing the needed capability.

        Returns:
            Summary of activated tools, or a message if none matched.
        """
        results = self._registry.search_deferred(query, limit=self._max_results)
        if not results:
            return f"No deferred tools matched '{query}'. Try broader keywords."

        lines = [f"Activated {len(results)} tool(s) — now available:"]
        for name, desc in results:
            self._registry.activate(name)
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)
