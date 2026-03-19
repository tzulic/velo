"""Progress tracking for subagent execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProgressTracker:
    """Accumulates tool execution events during subagent runs.

    Produces a natural language summary of what the subagent did,
    suitable for displaying to the user on task completion.
    """

    _events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def record_tool(self, tool_name: str, args: dict[str, Any]) -> None:
        """Record a tool execution event.

        Args:
            tool_name: Name of the tool that was called.
            args: Arguments passed to the tool.
        """
        self._events.append((tool_name, args))

    @property
    def count(self) -> int:
        """Number of recorded events."""
        return len(self._events)

    def summary(self) -> str:
        """Produce a concise natural language summary of tool usage.

        Returns:
            str: Summary like "Completed: web search (2x), read file"
                 or empty string if no events.
        """
        if not self._events:
            return ""

        counts: dict[str, int] = {}
        for name, _ in self._events:
            counts[name] = counts.get(name, 0) + 1

        parts: list[str] = []
        for name, count in counts.items():
            label = name.replace("_", " ")
            if count > 1:
                parts.append(f"{label} ({count}x)")
            else:
                parts.append(label)

        return "Completed: " + ", ".join(parts)
