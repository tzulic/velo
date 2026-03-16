"""Subagent manager for background task execution."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from velo.agent.tools.browse import BrowserSession, WebBrowseTool
from velo.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from velo.agent.tools.registry import ToolRegistry
from velo.agent.tools.shell import ExecTool
from velo.agent.tools.web import WebFetchTool, WebSearchTool
from velo.bus.events import InboundMessage
from velo.bus.queue import MessageBus
from velo.config.schema import BrowseConfig, ExecToolConfig
from velo.providers.base import LLMProvider

if TYPE_CHECKING:
    from velo.agent.budget import IterationBudget
    from velo.plugins.manager import PluginManager


class SubagentManager:
    """Manages background subagent execution."""

    MAX_SPAWN_DEPTH: int = 1  # Subagents cannot spawn other subagents
    MAX_CHILDREN_PER_SESSION: int = 5  # Max concurrent subagents per session

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
        parallel_api_key: str | None = None,
        web_proxy: str | None = None,
        browse_config: BrowseConfig | None = None,
        exec_config: ExecToolConfig | None = None,
        restrict_to_workspace: bool = False,
        on_complete_callback: Callable[[dict[str, Any]], None] | None = None,
        plugin_manager: "PluginManager | None" = None,
    ):
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.parallel_api_key = parallel_api_key
        self.web_proxy = web_proxy
        self._browse_config = browse_config or BrowseConfig()
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        # Optional callback invoked when a subagent completes (for event-driven heartbeat).
        self.on_complete_callback = on_complete_callback
        self.plugin_manager = plugin_manager
        # Per-session iteration budgets (parent + subagents draw from the same pool).
        self._session_budgets: dict[str, IterationBudget | None] = {}
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}

    def set_budget(self, session_key: str, budget: IterationBudget | None) -> None:
        """Set the iteration budget for subagents spawned under a session.

        Args:
            session_key: Session key to associate the budget with.
            budget: Shared budget, or None for unlimited.
        """
        if budget is not None:
            self._session_budgets[session_key] = budget
        else:
            self._session_budgets.pop(session_key, None)

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        depth: int = 0,
        parent_run_id: str | None = None,
    ) -> str:
        """Spawn a subagent to execute a task in the background.

        Args:
            task (str): Task description for the subagent.
            label (str | None): Short display label.
            origin_channel (str): Channel to report results to.
            origin_chat_id (str): Chat ID to report results to.
            session_key (str | None): Session key for concurrency tracking.
            depth (int): Spawn depth — 0 = top-level, 1+ = nested (blocked).
            parent_run_id (str | None): Run ID of the spawning agent loop.

        Returns:
            str: Confirmation message or error string if limits exceeded.
        """
        # Depth guard: subagents cannot spawn subagents
        if depth >= self.MAX_SPAWN_DEPTH:
            logger.warning(
                "subagent.spawn_blocked_depth: depth={} parent_run_id={}", depth, parent_run_id
            )
            return (
                f"Error: Subagent spawn blocked — maximum spawn depth "
                f"({self.MAX_SPAWN_DEPTH}) reached."
            )

        # Concurrency guard: cap active subagents per session
        if session_key:
            active = len(self._session_tasks.get(session_key, set()))
            if active >= self.MAX_CHILDREN_PER_SESSION:
                logger.warning(
                    "subagent.spawn_blocked_concurrency: session={} active={}",
                    session_key,
                    active,
                )
                return (
                    f"Error: Subagent spawn blocked — maximum concurrent subagents "
                    f"({self.MAX_CHILDREN_PER_SESSION}) already running for this session."
                )

        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin = {"channel": origin_channel, "chat_id": origin_chat_id}

        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin, parent_run_id=parent_run_id)
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            if session_key:
                if ids := self._session_tasks.get(session_key):
                    ids.discard(task_id)
                    if not ids:
                        del self._session_tasks[session_key]

        bg_task.add_done_callback(_cleanup)

        logger.info(
            "subagent.spawned: id={} label={} parent_run_id={}",
            task_id,
            display_label,
            parent_run_id,
        )

        # Plugin hook: subagent_spawned (fire-and-forget, non-blocking)
        if self.plugin_manager:
            asyncio.create_task(self.plugin_manager.fire(
                "subagent_spawned",
                child_session_key=task_id,
                parent_session_key=session_key or "",
            ))

        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        parent_run_id: str | None = None,
    ) -> None:
        """Execute the subagent task and announce the result.

        Args:
            task_id (str): Unique task identifier.
            task (str): Full task description.
            label (str): Short display label.
            origin (dict): Channel and chat_id for result reporting.
            parent_run_id (str | None): Run ID of the parent agent loop for tracing.
        """
        run_id = str(uuid.uuid4())[:8]

        # Scoped browser session for this subagent run (created before try for cleanup)
        browser_session = BrowserSession(
            proxy=self.web_proxy,
            headless=self._browse_config.headless,
            timeout=self._browse_config.timeout,
        )

        with logger.contextualize(run_id=run_id, parent_run_id=parent_run_id or "none"):
            logger.info("subagent.started: id={} label={}", task_id, label)

            try:
                # Build subagent tools (no message tool, no spawn tool)
                tools = ToolRegistry()
                allowed_dir = self.workspace if self.restrict_to_workspace else None
                tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
                tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
                tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
                tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))
                tools.register(
                    ExecTool(
                        working_dir=str(self.workspace),
                        timeout=self.exec_config.timeout,
                        restrict_to_workspace=self.restrict_to_workspace,
                        path_append=self.exec_config.path_append,
                        exec_config=self.exec_config,
                        workspace=self.workspace,
                    )
                )
                tools.register(WebSearchTool(api_key=self.parallel_api_key))
                tools.register(WebFetchTool(api_key=self.parallel_api_key))
                tools.register(WebBrowseTool(session=browser_session))

                system_prompt = self._build_subagent_prompt()
                messages: list[dict[str, Any]] = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": task},
                ]

                # Run agent loop (limited iterations)
                max_iterations = 15
                iteration = 0
                final_result: str | None = None

                while iteration < max_iterations:
                    iteration += 1

                    # Shared budget pre-flight: stop if parent+subagents exhausted the pool
                    session_key = f"{origin['channel']}:{origin['chat_id']}"
                    _budget = self._session_budgets.get(session_key)
                    if _budget is not None and not await _budget.consume():
                        logger.info("subagent.budget_exhausted: id={}", task_id)
                        final_result = (
                            "Subagent stopped — iteration budget exhausted. "
                            "Partial progress has been made."
                        )
                        break

                    response = await self.provider.chat(
                        messages=messages,
                        tools=tools.get_definitions(),
                        model=self.model,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        reasoning_effort=self.reasoning_effort,
                    )

                    if response.has_tool_calls:
                        # Add assistant message with tool calls
                        tool_call_dicts = [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                                },
                            }
                            for tc in response.tool_calls
                        ]
                        messages.append(
                            {
                                "role": "assistant",
                                "content": response.content or "",
                                "tool_calls": tool_call_dicts,
                            }
                        )

                        # Execute tools
                        for tool_call in response.tool_calls:
                            args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                            logger.debug(
                                "subagent.tool_call: id={} tool={} args={}",
                                task_id,
                                tool_call.name,
                                args_str[:200],
                            )
                            result = await tools.execute(tool_call.name, tool_call.arguments)
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": tool_call.name,
                                    "content": result,
                                }
                            )
                    else:
                        final_result = response.content
                        break

                if final_result is None:
                    final_result = "Task completed but no final response was generated."

                logger.info("subagent.completed: id={}", task_id)

                # Plugin hook: subagent_ended (fire-and-forget)
                if self.plugin_manager:
                    await self.plugin_manager.fire(
                        "subagent_ended",
                        child_session_key=task_id,
                        outcome="ok",
                        error=None,
                    )

                await self._announce_result(task_id, label, task, final_result, origin, "ok")

                # Notify heartbeat service of subagent completion (event-driven wake)
                if self.on_complete_callback is not None:
                    try:
                        self.on_complete_callback(
                            {
                                "type": "subagent_complete",
                                "run_id": task_id,
                                "summary": (final_result or "")[:200],
                            }
                        )
                    except Exception:
                        pass  # Never let callback failures kill the subagent

            except Exception as e:
                error_msg = f"Error: {str(e)}"
                logger.error("subagent.failed: id={} error={}", task_id, e)

                # Plugin hook: subagent_ended (fire-and-forget)
                if self.plugin_manager:
                    await self.plugin_manager.fire(
                        "subagent_ended",
                        child_session_key=task_id,
                        outcome="error",
                        error=str(e),
                    )

                await self._announce_result(task_id, label, task, error_msg, origin, "error")
            finally:
                # Always cleanup subagent browser session
                await browser_session.close()

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"

        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""

        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )

        await self.bus.publish_inbound(msg)
        logger.debug(
            "Subagent [{}] announced result to {}:{}", task_id, origin["channel"], origin["chat_id"]
        )

    def _build_subagent_prompt(self) -> str:
        """Build a focused system prompt for the subagent."""
        from velo.agent.context import ContextBuilder
        from velo.agent.skills import SkillsLoader

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        parts = [
            f"""# Subagent

{time_ctx}

You are a subagent spawned by the main agent to complete a specific task.
Stay focused on the assigned task. Your final response will be reported back to the main agent.

## Workspace
{self.workspace}"""
        ]

        skills_summary = SkillsLoader(self.workspace).build_skills_summary()
        if skills_summary:
            parts.append(
                f"## Skills\n\nRead SKILL.md with read_file to use a skill.\n\n{skills_summary}"
            )

        return "\n\n".join(parts)

    async def cancel_by_session(self, session_key: str) -> int:
        """Cancel all subagents for the given session. Returns count cancelled."""
        tasks = [
            self._running_tasks[tid]
            for tid in self._session_tasks.get(session_key, [])
            if tid in self._running_tasks and not self._running_tasks[tid].done()
        ]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)
