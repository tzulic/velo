"""Helpers for converting LLM response objects into message dicts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from velo.providers.base import ToolCallRequest


def format_tool_calls(tool_calls: list[ToolCallRequest]) -> list[dict[str, object]]:
    """Convert provider ToolCallRequest objects to OpenAI-format dicts.

    Args:
        tool_calls: List of ToolCallRequest from the LLM response.

    Returns:
        List of dicts with id, type, and function keys.
    """
    return [
        {
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.name,
                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
            },
        }
        for tc in tool_calls
    ]
