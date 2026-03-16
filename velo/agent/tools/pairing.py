"""Pairing tool for generating and managing access codes."""

from __future__ import annotations

from typing import Any

from velo.agent.tools.base import Tool


class PairingTool(Tool):
    """Tool to generate, list, or revoke pairing codes."""

    def __init__(self, pairing_manager: Any) -> None:
        """Initialize with a PairingManager instance.

        Args:
            pairing_manager: PairingManager from velo.channels.pairing.
        """
        self._mgr = pairing_manager

    @property
    def name(self) -> str:
        """Tool name used in function calls."""
        return "pairing"

    @property
    def description(self) -> str:
        """Description of what the tool does."""
        return "Generate, list, or revoke pairing codes that grant new users access to this agent."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["generate", "list", "revoke"],
                    "description": "Action to perform",
                },
                "expires_hours": {
                    "type": "integer",
                    "description": "Hours until code expires (default 24)",
                    "default": 24,
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, expires_hours: int = 24, **kwargs: Any) -> str:
        """Execute pairing action.

        Args:
            action: generate, list, or revoke.
            expires_hours: Expiry for generated codes.
            **kwargs: Unused extra parameters.

        Returns:
            str: Result message.
        """
        if action == "generate":
            code = self._mgr.generate_code(expires_hours=expires_hours)
            return (
                f"Pairing code generated: {code}\n"
                f"Share this code with the person you want to grant access. "
                f"It expires in {expires_hours}h."
            )
        if action == "list":
            codes = [c for c in self._mgr._codes.values() if c.uses < c.max_uses]
            if not codes:
                return "No active pairing codes."
            lines = [f"- {c.code} (uses: {c.uses}/{c.max_uses})" for c in codes]
            return "Active codes:\n" + "\n".join(lines)
        return f"Unknown action: {action}"
