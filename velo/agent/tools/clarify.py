"""Clarify tool — lets the agent pause and ask the user a structured question."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from velo.agent.tools.base import Tool

MAX_CHOICES = 4


class ClarifyTool(Tool):
    """Ask the user a clarifying question before proceeding.

    Supports multiple-choice (up to 4 options) or open-ended questions.
    Use when the task is ambiguous or a decision has meaningful trade-offs.
    """

    def __init__(self, callback: Callable[[str, list[str] | None], Awaitable[str]]) -> None:
        """Initialize with an async callback that delivers the question to the user.

        Args:
            callback: Async callable that receives (question, choices) and returns the user's response.
        """
        self._callback = callback

    @property
    def name(self) -> str:
        """Tool name used in function calls."""
        return "clarify"

    @property
    def description(self) -> str:
        """Description of what the tool does."""
        return (
            "Ask the user a question when you need clarification or a decision "
            "before proceeding. Supports multiple-choice (up to 4 options) or "
            "open-ended. Use when the task is ambiguous or a decision has "
            "meaningful trade-offs. Do NOT use for simple yes/no confirmations "
            "of destructive commands — handle those inline."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to present."},
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": MAX_CHOICES,
                    "description": "Up to 4 answer choices. Omit for open-ended.",
                },
            },
            "required": ["question"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Execute clarify tool — present question to user and return JSON response.

        Args:
            **kwargs: Expects 'question' (str) and optional 'choices' (list[str]).

        Returns:
            str: JSON string with question, choices_offered, and user_response.
        """
        question: str = kwargs.get("question", "")
        choices: list[str] | None = kwargs.get("choices")

        if not question or not question.strip():
            return json.dumps({"error": "Question text is required."})

        if choices is not None:
            # Sanitize: strip whitespace and limit to MAX_CHOICES
            choices = [str(c).strip() for c in choices if str(c).strip()][:MAX_CHOICES]
            if not choices:
                choices = None

        try:
            user_response = await self._callback(question, choices)
        except Exception as exc:
            return json.dumps({"error": f"Failed to get user input: {exc}"})

        return json.dumps(
            {
                "question": question,
                "choices_offered": choices,
                "user_response": str(user_response).strip(),
            },
            ensure_ascii=False,
        )
