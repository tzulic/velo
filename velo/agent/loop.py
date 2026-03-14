"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import re
import signal
import sys
import time
import uuid
import weakref
from collections import deque
from collections.abc import Awaitable
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal

from loguru import logger

from velo.agent.context import ContextBuilder
from velo.agent.context_compressor import compress_context
from velo.agent.llm_helpers import (
    COMPRESSION_THRESHOLD,
    PROACTIVE_TRIM_TARGET,
    PROACTIVE_TRIM_THRESHOLD,
    REACTIVE_TRIM_TARGET,
    chat_with_retry,
    trim_to_budget,
)
from velo.agent.provider_health import get_provider_health
from velo.agent.subagent import SubagentManager
from velo.agent.tools.browse import BrowserSession, WebBrowseTool
from velo.agent.tools.cron import CronTool
from velo.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from velo.agent.tools.message import MessageTool
from velo.agent.tools.registry import ToolRegistry
from velo.agent.tools.search import SearchToolsTool
from velo.agent.tools.shell import ExecTool
from velo.agent.tools.spawn import SpawnTool
from velo.agent.tools.web import WebFetchTool, WebSearchTool
from velo.bus.events import InboundMessage, OutboundMessage
# Honcho integration (lazy import of adapter/tools in __init__)
from velo.bus.queue import MessageBus
from velo.providers.base import LLMProvider, LLMResponse
from velo.providers.context_limits import estimate_tokens, get_context_window
from velo.providers.errors import RETRYABLE_ERRORS
from velo.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from velo.agent.honcho.config import HonchoConfig
    from velo.config.schema import A2APeerConfig, BrowseConfig, ChannelsConfig, ExecToolConfig
    from velo.cron.service import CronService
    from velo.plugins.manager import PluginManager


class _SafeWriter:
    """Wraps a stream so OSError (broken pipe, closed fd) is silently swallowed.

    Installed over sys.stdout in daemon/systemd/Docker contexts to prevent
    EPIPE from crashing the process when a downstream consumer closes the pipe.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "_inner", inner)

    def write(self, data: str | bytes) -> int:
        """Write data, discarding OSError (e.g. broken pipe)."""
        try:
            return self._inner.write(data)  # type: ignore[no-any-return]
        except OSError:
            return len(data) if isinstance(data, str) else 0

    def flush(self) -> None:
        """Flush, discarding OSError."""
        try:
            self._inner.flush()
        except OSError:
            pass

    def fileno(self) -> int:
        """Return underlying file descriptor (needed by some stdlib code)."""
        return self._inner.fileno()  # type: ignore[no-any-return]

    def isatty(self) -> bool:
        """Return whether the underlying stream is a TTY."""
        try:
            return self._inner.isatty()  # type: ignore[no-any-return]
        except OSError:
            return False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class RateLimiter:
    """Fixed-window per-key rate limiter for outbound messages.

    Tracks send times per session key using a sliding window of 60 seconds.
    """

    def __init__(self, max_per_minute: int = 10) -> None:
        """Initialize rate limiter.

        Args:
            max_per_minute (int): Maximum messages allowed per session per 60s window.
        """
        self._max = max_per_minute
        self._windows: dict[str, deque[float]] = {}

    def is_allowed(self, key: str) -> bool:
        """Check whether a message from ``key`` is within rate limits.

        Slides the window to evict entries older than 60s, then checks if the
        count is below the cap.  Records the current time on approval.

        Args:
            key (str): Session key to check.

        Returns:
            bool: True if the message should be sent, False if rate-limited.
        """
        now = time.monotonic()
        window = self._windows.get(key)
        if window is not None:
            # Evict entries older than 60 seconds
            cutoff = now - 60.0
            while window and window[0] < cutoff:
                window.popleft()
            # Remove empty windows so terminated sessions don't accumulate
            if not window:
                del self._windows[key]
                window = None
        if window is None:
            window = deque()
            self._windows[key] = window
        if len(window) >= self._max:
            return False
        window.append(now)
        return True


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    _TOOL_RESULT_MAX_CHARS = 500

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        memory_char_limit: int = 8000,
        user_char_limit: int = 4000,
        memory_nudge_interval: int = 20,
        reasoning_effort: str | None = None,
        parallel_api_key: str | None = None,
        web_proxy: str | None = None,
        browse_config: "BrowseConfig | None" = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        session_backend: Literal["jsonl", "sqlite"] = "jsonl",
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        plugin_manager: PluginManager | None = None,
        context_window: int | None = None,
        a2a_peers: "list[A2APeerConfig] | None" = None,
        fallback_provider: LLMProvider | None = None,
        subagent_model: str | None = None,
        save_trajectories: bool = False,
        clarify_callback: Callable[[str, list[str] | None], Awaitable[str]] | None = None,
        honcho_config: "HonchoConfig | None" = None,
    ):
        from velo.config.schema import BrowseConfig, ExecToolConfig

        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        self.memory_nudge_interval = memory_nudge_interval
        self.reasoning_effort = reasoning_effort
        self.parallel_api_key = parallel_api_key
        self.web_proxy = web_proxy
        self._browse_config = browse_config or BrowseConfig()
        self.browser_session = BrowserSession(
            proxy=web_proxy,
            headless=self._browse_config.headless,
            timeout=self._browse_config.timeout,
        )
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        self.context_window_override = context_window
        self.subagent_model = subagent_model

        # Provider fallback: activated at most once per session when primary exhausts retries.
        self._fallback_provider: LLMProvider | None = fallback_provider
        self._fallback_activated: bool = False

        # Trajectory saving: append JSONL turn records for debugging/fine-tuning.
        self._save_trajectories = save_trajectories
        self._trajectories_dir = workspace / "trajectories"
        if save_trajectories:
            self._trajectories_dir.mkdir(parents=True, exist_ok=True)

        self.plugin_manager = plugin_manager
        self.context = ContextBuilder(
            workspace,
            plugin_manager=plugin_manager,
            memory_limit=memory_char_limit,
            user_limit=user_char_limit,
        )
        # Reason: track turns per session to inject periodic memory nudges.
        self._turn_counts: dict[str, int] = {}
        self.sessions = session_manager or SessionManager(workspace, backend=session_backend)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.subagent_model or self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            reasoning_effort=reasoning_effort,
            parallel_api_key=parallel_api_key,
            web_proxy=web_proxy,
            browse_config=self._browse_config,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._shutting_down: bool = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task] = set()  # Strong refs to in-flight tasks
        self._consolidation_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        # Per-session serialization: replaces global _processing_lock so sessions
        # run concurrently while messages within the same session queue behind each other.
        self._session_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._rate_limiter = RateLimiter()
        self._register_default_tools(a2a_peers, clarify_callback)
        self._register_plugin_tools()

        # Honcho user-modeling integration
        self._honcho: Any = None
        if honcho_config and honcho_config.enabled and honcho_config.api_key:
            from velo.agent.honcho.adapter import HonchoAdapter
            from velo.agent.honcho.tools import HonchoNoteTool, HonchoQueryTool, HonchoSearchTool

            self._honcho = HonchoAdapter(honcho_config)
            self.context.set_honcho(self._honcho)
            self.tools.register(HonchoSearchTool(self._honcho))
            self.tools.register(HonchoQueryTool(self._honcho))
            self.tools.register(HonchoNoteTool(self._honcho))

    def _register_default_tools(
        self,
        a2a_peers: "list[A2APeerConfig] | None" = None,
        clarify_callback: Callable[[str, list[str] | None], Awaitable[str]] | None = None,
    ) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
                path_append=self.exec_config.path_append,
                extended_safety=self.exec_config.extended_safety,
            )
        )
        self.tools.register(WebSearchTool(api_key=self.parallel_api_key))
        self.tools.register(WebFetchTool(api_key=self.parallel_api_key))
        self.tools.register(WebBrowseTool(session=self.browser_session))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))
        self.tools.register(SearchToolsTool(self.tools))
        if a2a_peers:
            from velo.agent.tools.a2a_call import CallAgentTool

            self.tools.register(CallAgentTool(peers=a2a_peers))
        if clarify_callback is not None:
            from velo.agent.tools.clarify import ClarifyTool

            self.tools.register(ClarifyTool(clarify_callback))

        # Session search: register when SQLite backend is active
        search_store = self.sessions.get_search_store() if self.sessions else None
        if search_store is not None:
            from velo.agent.tools.session_search import SessionSearchTool

            self.tools.register(SessionSearchTool(search_store))

    def _register_plugin_tools(self) -> None:
        """Register tools from all loaded plugins, respecting their deferred flag."""
        if not self.plugin_manager:
            return
        for tool, deferred in self.plugin_manager.get_all_tools():
            self.tools.register(tool, deferred=deferred)

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from velo.agent.tools.mcp import connect_mcp_servers

        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except Exception as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        for name in ("message", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    tool.set_context(channel, chat_id, *([message_id] if name == "message" else []))

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""

        def _fmt(tc):
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'

        return ", ".join(_fmt(tc) for tc in tool_calls)

    def _try_activate_fallback(self) -> bool:
        """Swap to fallback provider in-place. One-shot — returns False if already done or not configured.

        Returns:
            bool: True if fallback was activated, False if already active or not configured.
        """
        if self._fallback_activated or self._fallback_provider is None:
            return False
        logger.info(
            "provider.fallback_activated: primary exhausted retries, switching to {}",
            self._fallback_provider.get_default_model(),
        )
        self.provider = self._fallback_provider
        self._fallback_activated = True
        return True

    def _save_trajectory(
        self, messages: list[dict[str, Any]], session_key: str, completed: bool
    ) -> None:
        """Append one trajectory record to JSONL. Sync write is fine for append-only.

        Args:
            messages (list[dict]): Full message list from the turn.
            session_key (str): Session key for identifying the source session.
            completed (bool): True if the turn completed without error.
        """
        if not self._save_trajectories:
            return

        # Convert to ShareGPT format (human/gpt role pairs).
        trajectory: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content") or ""
            if isinstance(content, list):
                # Flatten multimodal content to text.
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
                )
            if role == "user":
                trajectory.append({"from": "human", "value": str(content)})
            elif role == "assistant":
                trajectory.append({"from": "gpt", "value": str(content)})

        filename = "trajectory_samples.jsonl" if completed else "failed_trajectories.jsonl"
        path = self._trajectories_dir / filename
        record = {
            "conversations": trajectory,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": self.model,
            "session_key": session_key,
            "completed": completed,
        }
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("trajectory.save_failed: {}", str(e))

    async def _chat_with_retry(self, **kwargs: Any) -> LLMResponse:
        """Call provider.chat() with retry. Delegates to llm_helpers."""
        return await chat_with_retry(self.provider, **kwargs)

    async def _chat_stream_to_response(
        self,
        on_progress: Callable[..., Awaitable[None]],
        **kwargs: Any,
    ) -> LLMResponse:
        """Stream LLM response. Delegates to llm_helpers."""
        from velo.agent.llm_helpers import chat_stream_to_response

        return await chat_stream_to_response(self.provider, on_progress, **kwargs)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        session_key: str = "",
    ) -> tuple[str | None, list[str], list[dict]]:
        """Run the agent iteration loop. Returns (final_content, tools_used, messages).

        Args:
            initial_messages (list[dict]): Pre-built message list including system + history.
            on_progress (Callable | None): Optional streaming progress callback.
            session_key (str): Session key for usage logging.

        Returns:
            tuple[str | None, list[str], list[dict]]: final content, tools used, all messages.
        """
        run_id = str(uuid.uuid4())[:8]
        start_ms = int(time.monotonic() * 1000)
        _provider_id = f"{self.provider.__class__.__name__}:{self.model}"

        with logger.contextualize(run_id=run_id):
            return await self._run_agent_loop_inner(
                initial_messages,
                on_progress=on_progress,
                session_key=session_key,
                run_id=run_id,
                start_ms=start_ms,
                provider_id=_provider_id,
            )

    async def _run_agent_loop_inner(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None,
        session_key: str,
        run_id: str,
        start_ms: int,
        provider_id: str,
    ) -> tuple[str | None, list[str], list[dict]]:
        """Inner loop body, called within a logger.contextualize block."""
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []
        ctx_window = get_context_window(self.model, self.context_window_override)
        health = get_provider_health(provider_id)
        total_tokens_in = 0
        total_tokens_out = 0

        last_compressed_iter = -999  # Cooldown: don't re-compress within 3 iterations

        while iteration < self.max_iterations:
            iteration += 1
            # Refresh tool definitions each iteration so newly activated tools are included.
            tool_defs = self.tools.get_definitions()

            # Context compression: summarize middle messages at 50% usage.
            # Cooldown prevents repeated LLM calls on consecutive iterations.
            est = estimate_tokens(messages)
            if est > ctx_window * COMPRESSION_THRESHOLD and (iteration - last_compressed_iter) >= 3:
                messages, _summary, est = await compress_context(
                    messages, self.provider,
                    self.subagent_model or self.model,
                    ctx_window,
                    est_tokens=est,
                )
                if _summary:
                    last_compressed_iter = iteration

            # Proactive context trim: if still close to the limit, trim before calling LLM.
            if est > ctx_window * PROACTIVE_TRIM_THRESHOLD:
                budget = int(ctx_window * PROACTIVE_TRIM_TARGET)
                messages = trim_to_budget(messages, budget)

            llm_kwargs: dict[str, Any] = {
                "messages": messages,
                "tools": tool_defs,
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "reasoning_effort": self.reasoning_effort,
            }

            # Provider health: if primary is in cooldown, probe or skip to fallback
            if not health.is_available():
                if health.should_probe():
                    health.mark_probed()
                    logger.info("provider.probing: cooldown expiring soon, sending probe")
                    # Fall through to attempt normally (this IS the probe)
                elif self._try_activate_fallback():
                    logger.info(
                        "provider.cooldown_fallback: {:.0f}s remaining on primary",
                        health.seconds_until_available(),
                    )
                    health = get_provider_health(
                        f"{self.provider.__class__.__name__}:{self.model}"
                    )

            # Use streaming when a progress callback is available.
            if on_progress:
                response = await self._chat_stream_to_response(
                    on_progress,
                    **llm_kwargs,
                )
            else:
                response = await self._chat_with_retry(**llm_kwargs)

            # Record provider health based on response
            if response.finish_reason == "error" and response.error_code in RETRYABLE_ERRORS:
                health.record_failure(response.error_code or "unknown")
            elif response.finish_reason != "error":
                health.record_success()

            # Accumulate token usage for cost tracking
            if response.usage:
                total_tokens_in += response.usage.get("input_tokens", 0)
                total_tokens_out += response.usage.get("output_tokens", 0)

            # Provider fallback: if primary exhausted all retries with a transient error,
            # swap to the backup provider and retry once. One-shot — stays active for session.
            if (
                response.finish_reason == "error"
                and response.error_code in RETRYABLE_ERRORS
                and self._try_activate_fallback()
            ):
                response = await self._chat_with_retry(**llm_kwargs)

            # Reactive trim: context overflow → trim aggressively and retry once.
            if response.finish_reason == "error" and response.error_code == "context_overflow":
                budget = int(ctx_window * REACTIVE_TRIM_TARGET)
                trimmed = trim_to_budget(messages, budget)
                if len(trimmed) < len(messages):
                    logger.warning(
                        "context.overflow_recovery: trimmed {} → {} messages, retrying",
                        len(messages),
                        len(trimmed),
                    )
                    messages = trimmed
                    llm_kwargs["messages"] = messages
                    response = await self._chat_with_retry(**llm_kwargs)

            if response.has_tool_calls:
                if on_progress:
                    # Streaming already emitted thoughts; emit tool hints.
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

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
                messages = self.context.add_assistant_message(
                    messages,
                    response.content,
                    tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )

                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    params = tool_call.arguments
                    # Plugin hook: before_tool_call
                    if self.plugin_manager:
                        params = await self.plugin_manager.pipe(
                            "before_tool_call",
                            value=params,
                            tool_name=tool_call.name,
                        )
                    args_str = json.dumps(params, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                    result = await self.tools.execute(tool_call.name, params)
                    # Plugin hook: after_tool_call
                    if self.plugin_manager:
                        result = await self.plugin_manager.pipe(
                            "after_tool_call",
                            value=result,
                            tool_name=tool_call.name,
                            params=params,
                        )
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                clean = self._strip_think(response.content)
                # Don't persist error responses to session history — they can
                # poison the context and cause permanent 400 loops (#1303).
                if response.finish_reason == "error":
                    if response.error_code == "budget_exceeded":
                        logger.info("budget_exceeded for session {}", session_key)
                        final_content = (
                            "I've reached the monthly usage limit for your account. "
                            "You can purchase a credit pack at volos.app/billing to continue."
                        )
                        break
                    logger.error("LLM returned error: {}", (clean or "")[:200])
                    final_content = clean or "Sorry, I encountered an error calling the AI model."
                    break
                messages = self.context.add_assistant_message(
                    messages,
                    clean,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                final_content = clean
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )

        # Plugin hook: before_response
        if final_content and self.plugin_manager:
            final_content = await self.plugin_manager.pipe(
                "before_response",
                value=final_content,
                channel="",
                chat_id="",
            )

        # Record usage metrics
        if total_tokens_in > 0 or total_tokens_out > 0:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            try:
                from velo.metrics.usage import record_usage

                record_usage(
                    workspace=self.workspace,
                    run_id=run_id,
                    session_key=session_key,
                    model=self.model,
                    tokens_in=total_tokens_in,
                    tokens_out=total_tokens_out,
                    duration_ms=duration_ms,
                    tool_calls_count=len(tools_used),
                )
            except Exception as e:
                logger.warning("usage.record_error: {}", e)

        return final_content, tools_used, messages

    def _request_shutdown(self) -> None:
        """Set shutdown flag — called from signal handlers."""
        if not self._shutting_down:
            logger.info("agent.shutdown_started")
        self._shutting_down = True
        self._running = False

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        self._shutting_down = False
        await self._connect_mcp()
        logger.info("Agent loop started")

        # Register graceful shutdown handlers (main thread only; silently skip otherwise)
        try:
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(signal.SIGTERM, self._request_shutdown)
            loop.add_signal_handler(signal.SIGINT, self._request_shutdown)
        except (NotImplementedError, ValueError):
            # Windows or non-main-thread: fall back to no-op
            pass

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except TimeoutError:
                continue

            if msg.content.strip().lower() == "/stop":
                await self._handle_stop(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(
                    lambda t, k=msg.session_key: (
                        self._active_tasks.get(k, []) and self._active_tasks[k].remove(t)
                        if t in self._active_tasks.get(k, [])
                        else None
                    )
                )

            # After dispatching, check shutdown flag and drain active tasks
            if self._shutting_down:
                break

        # Drain active tasks on graceful shutdown
        if self._shutting_down:
            all_tasks = [t for tasks in self._active_tasks.values() for t in tasks if not t.done()]
            if all_tasks:
                logger.info("agent.shutdown_draining: waiting for {} task(s)", len(all_tasks))
                try:
                    await asyncio.wait_for(asyncio.gather(*all_tasks, return_exceptions=True), timeout=60.0)
                except asyncio.TimeoutError:
                    logger.warning("agent.shutdown_timeout: forcing stop after 60s drain")
            logger.info("agent.shutdown_completed")

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        total = cancelled + sub_cancelled
        content = f"⏹ Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=content,
            )
        )

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message under the per-session lock.

        Sessions run concurrently; messages within the same session are serialized.
        """
        # Per-session lock: setdefault is atomic in CPython's event loop (single-threaded)
        lock = self._session_locks.setdefault(msg.session_key, asyncio.Lock())
        async with lock:
            try:
                response = await self._process_message(msg)
                if response is not None:
                    # Rate limiting for outbound messages
                    if not self._rate_limiter.is_allowed(msg.session_key):
                        logger.warning("message.rate_limited: session={}", msg.session_key)
                    await self.bus.publish_outbound(response)
                elif msg.channel == "cli":
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content="",
                            metadata=msg.metadata or {},
                        )
                    )
            except MemoryError:
                logger.critical("agent.fatal_memory_error — exiting")
                sys.exit(1)
            except (ConnectionError, TimeoutError, asyncio.TimeoutError):
                logger.warning("agent.transient_network_error: session={}", msg.session_key)
                # Transient — do not crash, let the next message proceed
            except asyncio.CancelledError:
                logger.info("Task cancelled for session {}", msg.session_key)
                raise
            except Exception:
                logger.exception("agent.unhandled_error: session={}", msg.session_key)
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="Sorry, I encountered an error.",
                    )
                )

    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    async def cleanup(self) -> None:
        """Async cleanup for all resources that need await."""
        await self.browser_session.close()
        await self.close_mcp()
        if self._honcho:
            await self._honcho.flush_all()
            await self._honcho.shutdown()

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        # Guard against broken-pipe crashes in systemd/Docker/daemon contexts.
        if not isinstance(sys.stdout, _SafeWriter):
            sys.stdout = _SafeWriter(sys.stdout)

        deferred_hint = self.tools.get_deferred_summary()
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (
                msg.chat_id.split(":", 1) if ":" in msg.chat_id else ("cli", msg.chat_id)
            )
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=self.memory_window)
            messages = await self.context.build_messages(
                history=history,
                current_message=msg.content,
                channel=channel,
                chat_id=chat_id,
                deferred_tools_hint=deferred_hint,
            )
            final_content, _, all_msgs = await self._run_agent_loop(messages, session_key=key)
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            return OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=final_content or "Background task completed.",
            )

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())
            self._consolidating.add(session.key)
            try:
                async with lock:
                    snapshot = session.messages[session.last_consolidated :]
                    if snapshot:
                        temp = Session(key=session.key)
                        temp.messages = list(snapshot)
                        if not await self._consolidate_memory(temp, archive_all=True):
                            return OutboundMessage(
                                channel=msg.channel,
                                chat_id=msg.chat_id,
                                content="Memory archival failed, session not cleared. Please try again.",
                            )
            except Exception:
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Memory archival failed, session not cleared. Please try again.",
                )
            finally:
                self._consolidating.discard(session.key)

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            self._turn_counts.pop(key, None)
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content="New session started."
            )
        if cmd == "/help":
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="🐈 velo commands:\n/new — Start a new conversation\n/stop — Stop the current task\n/help — Show available commands",
            )

        unconsolidated = len(session.messages) - session.last_consolidated
        if unconsolidated >= self.memory_window and session.key not in self._consolidating:
            self._consolidating.add(session.key)
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())

            async def _consolidate_and_unlock():
                try:
                    async with lock:
                        await self._consolidate_memory(session)
                finally:
                    self._consolidating.discard(session.key)
                    _task = asyncio.current_task()
                    if _task is not None:
                        self._consolidation_tasks.discard(_task)

            _task = asyncio.create_task(_consolidate_and_unlock())
            self._consolidation_tasks.add(_task)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        # Reason: nudge every N turns when there are unconsolidated messages, so
        # important facts aren't lost between auto-consolidation cycles.
        turn_count = self._turn_counts.get(key, 0) + 1
        self._turn_counts[key] = turn_count
        nudge: str | None = None
        if (
            self.memory_nudge_interval > 0
            and turn_count % self.memory_nudge_interval == 0
            and unconsolidated > 0
        ):
            nudge = (
                "[System: If anything important was discussed, "
                "consider saving it to memory/MEMORY.md or memory/USER.md now.]"
            )

        history = session.get_history(max_messages=self.memory_window)
        initial_messages = await self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            deferred_tools_hint=deferred_hint,
            memory_nudge=nudge,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        # Set active session for Honcho tools before the agent loop
        if self._honcho:
            self._honcho.set_current_session(key)

        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress or _bus_progress,
            session_key=key,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)
        self._save_trajectory(all_msgs, session.key, completed=True)

        # Sync messages to Honcho and prefetch context for next turn (non-blocking)
        if self._honcho:
            self._honcho.track_task(
                key, asyncio.create_task(self._honcho.sync_messages(key, session.messages))
            )
            self._honcho.track_task(
                key, asyncio.create_task(self._honcho.prefetch_context(key))
            )

        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=msg.metadata or {},
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if (
                role == "tool"
                and isinstance(content, str)
                and len(content) > self._TOOL_RESULT_MAX_CHARS
            ):
                entry["content"] = content[: self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            elif role == "user":
                if isinstance(content, str) and content.startswith(
                    ContextBuilder._RUNTIME_CONTEXT_TAG
                ):
                    # Strip the runtime-context prefix, keep only the user text.
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
                if isinstance(content, list):
                    filtered = []
                    for c in content:
                        if (
                            c.get("type") == "text"
                            and isinstance(c.get("text"), str)
                            and c["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG)
                        ):
                            continue  # Strip runtime context from multimodal messages
                        if c.get("type") == "image_url" and c.get("image_url", {}).get(
                            "url", ""
                        ).startswith("data:image/"):
                            filtered.append({"type": "text", "text": "[image]"})
                        else:
                            filtered.append(c)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def _consolidate_memory(self, session: Any, archive_all: bool = False) -> bool:
        """Delegate to MemoryStore.consolidate(). Returns True on success."""
        return await self.context.memory.consolidate(
            session,
            self.provider,
            self.model,
            archive_all=archive_all,
            memory_window=self.memory_window,
            memory_limit=self.memory_char_limit,
            user_limit=self.user_char_limit,
            honcho_active=bool(self._honcho),
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(
            msg, session_key=session_key, on_progress=on_progress
        )
        return response.content if response else ""
