"""Composio tool wrapper — adapts Composio tools to the Velo Tool interface."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from velo.agent.tools.base import Tool


class ComposioToolWrapper(Tool):
    """Wraps a single Composio tool as a Velo Tool.

    Follows the same pattern as ``MCPToolWrapper`` in ``velo/agent/tools/mcp.py``.
    Tool names are prefixed with ``composio_`` to avoid collision with MCP tools.

    Args:
        composio_client: The ``Composio`` SDK client instance.
        user_id: Composio user ID for tool execution.
        slug: Composio tool slug (e.g., ``GMAIL_SEND_EMAIL``).
        description: Human-readable description of the tool.
        input_parameters: JSON Schema dict describing the tool's parameters.
        timeout: Maximum seconds to wait for execution. Defaults to 30.
    """

    def __init__(
        self,
        composio_client: Any,
        user_id: str,
        slug: str,
        description: str,
        input_parameters: dict[str, Any],
        timeout: int = 30,
    ) -> None:
        self._composio = composio_client
        self._user_id = user_id
        self._slug = slug
        self._name = f"composio_{slug.lower()}"
        self._description = description
        self._parameters = input_parameters
        self._timeout = timeout

    @property
    def name(self) -> str:
        """Tool name used in function calls."""
        return self._name

    @property
    def description(self) -> str:
        """Description of what the tool does."""
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        """Execute the Composio tool via the SDK's direct execution API.

        All API calls route through ``COMPOSIO_BASE_URL`` (env var) which
        points to the Volos reverse proxy for key injection and call counting.

        Args:
            **kwargs: Tool-specific parameters matching the input schema.

        Returns:
            String result of the tool execution.
        """
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._composio.tools.execute,
                    self._slug,
                    kwargs,
                    user_id=self._user_id,
                ),
                timeout=self._timeout,
            )
            if isinstance(result, dict):
                if result.get("successful"):
                    return str(result.get("data", "(no output)"))
                return f"(tool error: {result.get('error', 'unknown')})"
            return str(result)
        except TimeoutError:
            logger.warning(
                "composio tool '{}' timed out after {}s", self._name, self._timeout
            )
            return f"(Composio tool '{self._name}' timed out after {self._timeout}s)"
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            logger.warning("composio tool '{}' was cancelled", self._name)
            return "(Composio tool call was cancelled)"
        except Exception as exc:
            logger.exception("composio tool '{}' failed: {}", self._name, exc)
            return f"(Composio tool call failed: {type(exc).__name__})"
