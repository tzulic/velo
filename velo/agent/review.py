"""Post-turn review agent for autonomous skill creation.

After a complex turn (5+ tool calls), spawns a lightweight background agent
that analyzes what happened and decides whether to create or update a skill.
Runs after the response is delivered — never blocks the main loop or steals
model cycles from the primary task.

Inspired by Hermes' nudge-based self-improvement pattern.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from velo.agent.message_helpers import format_tool_calls
from velo.agent.skill_nudge import COMPLEX_TURN_THRESHOLD
from velo.agent.tools.registry import ToolRegistry
from velo.agent.tools.skill_manage import SkillManageTool
from velo.providers.base import LLMProvider

_REVIEW_SYSTEM_PROMPT = """\
You are a skill reviewer. You analyse completed agent turns and decide whether
the workflow should be saved as a reusable skill.

Rules:
- Only create a skill if the workflow is genuinely reusable (not a one-off task).
- Skills must have clear When/Procedure/Pitfalls/Verification sections.
- Use the skill_manage tool with action='create' to save the skill.
- If an existing skill should be updated, use action='patch' instead.
- If the turn was routine (simple Q&A, single tool call), respond with "No skill needed."
- Keep skill names lowercase with hyphens, max 64 chars.
- Keep descriptions under 100 chars.

Available actions: create, edit, patch, list, read
"""

_REVIEW_USER_TEMPLATE = """\
Review this completed agent turn and decide if a reusable skill should be created.

## Tools Used ({tool_count} calls)
{tools_summary}

## Conversation Summary
{conversation_summary}

## Existing Skills
{existing_skills}

Decide: should a new skill be created, an existing one updated, or no action needed?
If creating/updating, use the skill_manage tool now.
"""


class PostTurnReviewer:
    """Spawns a background review agent after complex turns.

    Args:
        provider: LLM provider for the review agent.
        workspace: Path to the Velo workspace.
        model: Model to use for reviews (can be cheaper than main model).
        invalidate_callback: Callback to invalidate prompt cache after skill changes.
    """

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        invalidate_callback: Any | None = None,
    ) -> None:
        self._provider = provider
        self._workspace = workspace
        self._model = model or provider.get_default_model()
        self._invalidate = invalidate_callback
        self._active_tasks: set[asyncio.Task[None]] = set()

    def maybe_review(
        self,
        tools_used: list[str],
        messages: list[dict[str, Any]],
        session_key: str,
        min_tool_calls: int = COMPLEX_TURN_THRESHOLD,
    ) -> None:
        """Spawn a background review if the turn was complex enough.

        Args:
            tools_used: List of tool names called during the turn.
            messages: Full message list from the turn.
            session_key: Session identifier for logging.
            min_tool_calls: Minimum tool calls to trigger review.
        """
        if len(tools_used) < min_tool_calls:
            return

        task = asyncio.create_task(self._run_review(tools_used, messages, session_key))
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    async def _run_review(
        self,
        tools_used: list[str],
        messages: list[dict[str, Any]],
        session_key: str,
    ) -> None:
        """Execute the review agent in the background.

        Args:
            tools_used: Tool names from the completed turn.
            messages: Conversation messages from the turn.
            session_key: Session key for logging context.
        """
        run_id = session_key.split(":")[-1][:8] if ":" in session_key else "review"

        with logger.contextualize(review_run=run_id):
            logger.info(
                "review.started session={} tool_calls={}",
                session_key,
                len(tools_used),
            )

            try:
                tools = ToolRegistry()
                tools.register(
                    SkillManageTool(
                        workspace=self._workspace,
                        invalidate_callback=self._invalidate,
                    )
                )

                conversation_summary = self._summarize_turn(messages)
                tools_summary = self._summarize_tools(tools_used)
                existing_skills = self._list_existing_skills()

                user_prompt = _REVIEW_USER_TEMPLATE.format(
                    tool_count=len(tools_used),
                    tools_summary=tools_summary,
                    conversation_summary=conversation_summary,
                    existing_skills=existing_skills,
                )

                review_messages: list[dict[str, Any]] = [
                    {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ]

                # Run a short agent loop (max 3 iterations — review + maybe create)
                for iteration in range(3):
                    response = await self._provider.chat(
                        messages=review_messages,
                        tools=tools.get_definitions(),
                        model=self._model,
                        temperature=0.1,
                        max_tokens=2048,
                    )

                    if not response.has_tool_calls:
                        logger.info(
                            "review.completed session={} result={}",
                            session_key,
                            (response.content or "no output")[:80],
                        )
                        break

                    # Execute tool calls
                    tool_call_dicts = format_tool_calls(response.tool_calls)
                    review_messages.append(
                        {
                            "role": "assistant",
                            "content": response.content or "",
                            "tool_calls": tool_call_dicts,
                        }
                    )

                    for tc in response.tool_calls:
                        tool = tools.get(tc.name)
                        if tool is None:
                            result = f"Unknown tool: {tc.name}"
                        else:
                            result = await tool.execute(**tc.arguments)
                        review_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": result,
                            }
                        )

                    logger.info(
                        "review.iteration session={} iter={} tools={}",
                        session_key,
                        iteration + 1,
                        [tc.name for tc in response.tool_calls],
                    )

            except Exception as e:
                # Reason: review failures must never crash the main loop.
                logger.warning("review.failed session={}: {}", session_key, e)

    def _summarize_turn(self, messages: list[dict[str, Any]]) -> str:
        """Extract a concise summary of the conversation turn.

        Args:
            messages: Full message list from the turn.

        Returns:
            str: Condensed summary of user requests and agent actions.
        """
        lines: list[str] = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "system":
                continue
            if role == "user" and isinstance(content, str):
                # Trim long user messages
                text = content[:300] + "..." if len(content) > 300 else content
                lines.append(f"User: {text}")
            elif role == "assistant":
                if m.get("tool_calls"):
                    names = [tc.get("function", {}).get("name", "?") for tc in m["tool_calls"]]
                    lines.append(f"Agent called: {', '.join(names)}")
                elif isinstance(content, str) and content:
                    text = content[:200] + "..." if len(content) > 200 else content
                    lines.append(f"Agent: {text}")
            elif role == "tool" and isinstance(content, str):
                text = content[:100] + "..." if len(content) > 100 else content
                lines.append(f"  Result: {text}")

        # Cap total summary length
        summary = "\n".join(lines)
        if len(summary) > 2000:
            summary = summary[:2000] + "\n... (truncated)"
        return summary

    def _summarize_tools(self, tools_used: list[str]) -> str:
        """Format tool usage summary.

        Args:
            tools_used: List of tool names called.

        Returns:
            str: Formatted tool usage with counts.
        """
        counts: dict[str, int] = {}
        for name in tools_used:
            counts[name] = counts.get(name, 0) + 1
        return "\n".join(f"- {name}: {count}x" for name, count in counts.items())

    def _list_existing_skills(self) -> str:
        """List existing workspace skills for deduplication.

        Returns:
            str: Newline-separated list of existing skill names.
        """
        from velo.agent.skills import SkillsLoader

        # Reason: only workspace skills matter — agent can only create/modify those.
        skills = [
            s
            for s in SkillsLoader(self._workspace).list_skills(filter_unavailable=False)
            if s.get("source") == "workspace"
        ]
        if not skills:
            return "(no existing skills)"
        return "\n".join(f"- {s['name']}" for s in skills)

    async def shutdown(self) -> None:
        """Cancel any running review tasks."""
        for task in list(self._active_tasks):
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        self._active_tasks.clear()
