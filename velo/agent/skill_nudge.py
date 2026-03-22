"""Dynamic skill creation nudges based on task complexity.

Two-phase pattern:
1. After a turn completes, call ``should_nudge(tool_call_count)`` — if True,
   call ``mark_nudged()`` to arm the nudge.
2. On the *next* turn's context build, call ``should_inject()`` — if True,
   inject ``get_nudge_text()`` and call ``mark_injected()``.

This ensures the agent sees the nudge while the complex task is still fresh
in its context, without requiring an extra LLM round-trip.
"""

from __future__ import annotations

# Shared threshold: a turn with this many tool calls is considered "complex"
# and triggers both skill nudges and post-turn review.
COMPLEX_TURN_THRESHOLD = 5


class SkillNudge:
    """Tracks tool-call complexity and suggests skill creation.

    Fires once per session when a turn exceeds min_tool_calls.

    Args:
        min_tool_calls: Minimum tool calls in a turn to trigger a nudge.
    """

    def __init__(self, min_tool_calls: int = COMPLEX_TURN_THRESHOLD) -> None:
        self._min_tool_calls = min_tool_calls
        self._nudged: bool = False
        self._injected: bool = False

    def should_nudge(self, tool_call_count: int) -> bool:
        """Return True if a complex turn just completed and nudge should arm.

        Args:
            tool_call_count: Number of tool calls in the completed turn.

        Returns:
            bool: True if threshold met and not yet nudged this session.
        """
        if self._nudged:
            return False
        return tool_call_count >= self._min_tool_calls

    def mark_nudged(self) -> None:
        """Arm the nudge for injection on the next turn."""
        self._nudged = True

    def should_inject(self) -> bool:
        """Return True if the nudge text should be injected into context.

        Returns:
            bool: True if armed but not yet injected.
        """
        return self._nudged and not self._injected

    def mark_injected(self) -> None:
        """Mark that the nudge text was injected (don't repeat)."""
        self._injected = True

    def get_nudge_text(self) -> str:
        """Return the nudge prompt text.

        Returns:
            str: Text to inject into runtime context.
        """
        return (
            "[Skill Hint] You just completed a complex multi-step task. "
            "Consider whether this workflow would be useful to save as a "
            "reusable skill using skill_manage(action='create', ...). "
            "Only create a skill if the user is likely to need this again."
        )

    def reset(self) -> None:
        """Reset for a new session."""
        self._nudged = False
        self._injected = False
