"""Tool that delegates tasks to peer A2A agents."""

from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.config.schema import A2APeerConfig


class CallAgentTool(Tool):
    """Delegate a task to a specialized peer A2A agent.

    Configured peers are looked up by name from the A2A config.
    A direct URL may also be used when the peer name is not in config.
    """

    def __init__(self, peers: list[A2APeerConfig]) -> None:
        """Initialise with the list of configured peer agents.

        Args:
            peers: List of A2APeerConfig objects from A2AConfig.peers.
        """
        self._peers: dict[str, A2APeerConfig] = {p.name: p for p in peers}

    @property
    def name(self) -> str:
        """Tool name used in function calls."""
        return "call_agent"

    @property
    def description(self) -> str:
        """Description of what the tool does."""
        return (
            "Delegate a task to a specialized peer agent in your team.\n\n"
            "Use when the task matches another agent's expertise. "
            "The peer list is pre-configured — use the agent's name as listed. "
            "Returns the peer agent's response."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "peer": {
                    "type": "string",
                    "description": (
                        "Peer agent name from config (e.g. 'ResearchBot') "
                        "or a direct URL (e.g. 'http://1.2.3.4:18791')."
                    ),
                },
                "task": {
                    "type": "string",
                    "description": "The task or question for the peer agent.",
                },
            },
            "required": ["peer", "task"],
        }

    async def execute(self, peer: str, task: str, **kwargs: Any) -> str:
        """Send a task to a peer agent and return its response.

        Args:
            peer: Peer name (from config) or direct URL.
            task: Task description to send to the peer.
            **kwargs: Ignored extra arguments.

        Returns:
            Text response from the peer agent, or an error message.
        """
        config = self._peers.get(peer)
        if config:
            url, api_key = config.url, config.api_key
        elif peer.startswith("http"):
            url, api_key = peer, ""
        else:
            available = ", ".join(self._peers) or "none configured"
            return f"Unknown peer '{peer}'. Available: {available}"

        try:
            # Lazy import so the tool works even if a2a-sdk is not installed
            # and A2A is not configured (the import only runs when we have a peer).
            from nanobot.a2a.client import send_task_to_peer
            return await send_task_to_peer(url, api_key, task)
        except Exception as exc:
            return f"Failed to reach agent at {url}: {exc}"
