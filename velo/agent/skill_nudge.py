"""Dynamic skill creation nudges based on task complexity."""

from __future__ import annotations

from pathlib import Path


class SkillNudge:
    """Tracks tool-call complexity and suggests skill creation.

    Fires once per session when a turn exceeds min_tool_calls. This replaces
    the static "Skill Self-Improvement" block that was injected into the
    system prompt, providing a dynamic nudge only when warranted.

    Args:
        workspace: Agent workspace path.
        min_tool_calls: Minimum tool calls in a turn to trigger a nudge.
    """

    def __init__(self, workspace: Path, min_tool_calls: int = 5) -> None:
        self._workspace = workspace
        self._min_tool_calls = min_tool_calls
        self._nudged_this_session: bool = False

    def should_nudge(self, tool_call_count: int) -> bool:
        """Return True if the agent should consider creating a skill.

        Args:
            tool_call_count: Number of tool calls in the current turn.

        Returns:
            bool: True if threshold met and not yet nudged this session.
        """
        if self._nudged_this_session:
            return False
        return tool_call_count >= self._min_tool_calls

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

    def mark_nudged(self) -> None:
        """Mark that a nudge was shown this session (don't repeat)."""
        self._nudged_this_session = True

    def reset(self) -> None:
        """Reset for a new session."""
        self._nudged_this_session = False
