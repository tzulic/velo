"""Plugin type definitions and the PluginContext API surface."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Literal,
    Protocol,
    Union,
    runtime_checkable,
)

from velo.agent.tools.base import Tool

if TYPE_CHECKING:
    from velo.bus.queue import MessageBus
    from velo.providers.base import LLMProvider
    from velo.session.manager import SessionManager

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

HookFn = Callable[..., Any]
"""A hook callback — sync or async. Signature varies by hook name."""

ContextProvider = Union[Callable[[], str], Callable[[], Awaitable[str]]]
"""Returns extra context to inject into the system prompt. May be sync or async."""

HookType = Literal["fire_and_forget", "modifying", "claiming"]

# ---------------------------------------------------------------------------
# Hook definitions
# ---------------------------------------------------------------------------

HOOKS: dict[str, HookType] = {
    # Agent lifecycle
    "before_model_resolve": "modifying",
    "before_prompt_build": "modifying",
    "after_prompt_build": "modifying",
    "agent_end": "fire_and_forget",
    "before_reset": "fire_and_forget",
    # Message flow
    "message_received": "fire_and_forget",
    "inbound_claim": "claiming",
    "message_sending": "modifying",
    "message_sent": "fire_and_forget",
    # Tool execution
    "before_tool_call": "modifying",
    "after_tool_call": "modifying",
    "before_message_write": "modifying",
    # Session
    "session_start": "fire_and_forget",
    "session_end": "fire_and_forget",
    "subagent_spawned": "fire_and_forget",
    "subagent_ended": "fire_and_forget",
    # Gateway
    "on_startup": "fire_and_forget",
    "on_shutdown": "fire_and_forget",
}


# ---------------------------------------------------------------------------
# Runtime references (late-bound, set after AgentLoop creation)
# ---------------------------------------------------------------------------


@dataclass
class RuntimeRefs:
    """Late-bound references to runtime objects that aren't available at plugin load time.

    Set after AgentLoop creation via ``PluginManager.set_runtime()``.
    Propagated to services/channels implementing ``RuntimeAware``.
    """

    provider: LLMProvider
    model: str
    bus: MessageBus
    process_direct: Callable[..., Awaitable[str]] | None = None
    publish_outbound: Callable[..., Awaitable[None]] | None = None
    session_manager: "SessionManager | None" = None


# ---------------------------------------------------------------------------
# Service / RuntimeAware protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class ServiceLike(Protocol):
    """Structural type for plugin services (start/stop lifecycle)."""

    async def start(self) -> None: ...
    def stop(self) -> None: ...


@runtime_checkable
class RuntimeAware(Protocol):
    """Structural type for objects that accept late-bound runtime refs."""

    def set_runtime(self, refs: RuntimeRefs) -> None: ...


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


@dataclass
class PluginMeta:
    """Metadata about a discovered plugin."""

    name: str
    source: Literal["builtin", "workspace"]
    path: Path
    enabled: bool = True


# ---------------------------------------------------------------------------
# Registered hook entry (callback + priority)
# ---------------------------------------------------------------------------


@dataclass
class HookEntry:
    """A single registered hook callback with its priority."""

    callback: HookFn
    priority: int = 100


# ---------------------------------------------------------------------------
# HTTP types for plugin route handlers
# ---------------------------------------------------------------------------


@dataclass
class HttpRequest:
    """Incoming HTTP request for plugin route handlers."""

    method: str
    path: str
    body: bytes
    headers: dict[str, str]
    query_params: dict[str, str]


@dataclass
class HttpResponse:
    """Response from a plugin route handler."""

    status: int = 200
    body: str | bytes = ""
    headers: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# PluginContext — the API surface plugins receive in register()/activate()
# ---------------------------------------------------------------------------


class PluginContext:
    """
    Context object passed to each plugin's ``register()``/``activate()`` function.

    Plugins use this to register tools, context providers, hook callbacks, HTTP
    routes, and to optionally disable themselves during registration.
    """

    def __init__(self, plugin_name: str, config: dict[str, Any], workspace: Path) -> None:
        self.plugin_name = plugin_name
        self.config = config
        self.workspace = workspace
        self._tools: list[tuple[Tool, bool]] = []  # (tool, deferred)
        self._context_providers: list[ContextProvider] = []
        self._hooks: dict[str, list[HookEntry]] = {name: [] for name in HOOKS}
        self._services: list[ServiceLike] = []
        self._channels: list[Any] = []  # BaseChannel instances
        self._http_routes: list[dict[str, Any]] = []
        self._disabled: bool = False
        self._disable_reason: str = ""

    def register_tool(self, tool: Tool, *, deferred: bool = False) -> None:
        """Register a tool that the agent can use.

        Args:
            tool: A Tool instance to register.
            deferred: If True, the tool is loaded on-demand via search_tools
                rather than being sent to the LLM on every call.
        """
        self._tools.append((tool, deferred))

    def add_context_provider(self, fn: ContextProvider) -> None:
        """Register a function that returns extra system-prompt context.

        Args:
            fn: A sync or async callable returning a string.
        """
        self._context_providers.append(fn)

    def register_service(self, service: ServiceLike) -> None:
        """Register a background service with start/stop lifecycle.

        Args:
            service: An object implementing the ``ServiceLike`` protocol.
        """
        self._services.append(service)

    def register_channel(self, channel: Any) -> None:
        """Register a custom channel (BaseChannel subclass).

        Args:
            channel: A BaseChannel instance to add to the channel manager.
        """
        self._channels.append(channel)

    def disable(self, reason: str) -> None:
        """Gracefully disable this plugin during registration.

        Args:
            reason: Human-readable explanation (e.g., "missing api_key").
        """
        self._disabled = True
        self._disable_reason = reason

    def register_http_route(
        self,
        method: str,
        path: str,
        handler: Callable[..., Awaitable[Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register an HTTP route on the gateway.

        Args:
            method: HTTP method (e.g., "GET", "POST").
            path: URL path (e.g., "/webhooks/stripe").
            handler: Async callable that accepts an HttpRequest and returns an HttpResponse.
            metadata: Optional dict of extra metadata attached to the route entry.
        """
        self._http_routes.append(
            {
                "method": method.upper(),
                "path": path,
                "handler": handler,
                "metadata": metadata or {},
                "plugin_name": self.plugin_name,
            }
        )

    def on(self, hook_name: str, callback: HookFn, priority: int = 100) -> None:
        """Register a hook callback.

        Args:
            hook_name: One of the valid hook names (see ``HOOKS``).
            callback: Sync or async callable matching the hook signature.
            priority: Lower runs first. Default 100.

        Raises:
            ValueError: If hook_name is not a valid hook.
        """
        if hook_name not in HOOKS:
            raise ValueError(f"Unknown hook '{hook_name}'. Valid hooks: {', '.join(HOOKS)}")
        self._hooks[hook_name].append(HookEntry(callback=callback, priority=priority))

    # -- Internal helpers (used by PluginManager) --

    def _collect_tools(self) -> list[tuple[Tool, bool]]:
        """Return all registered tools as (tool, deferred) pairs."""
        return list(self._tools)

    def _collect_context_providers(self) -> list[ContextProvider]:
        """Return all registered context providers."""
        return list(self._context_providers)

    def _collect_hooks(self) -> dict[str, list[HookEntry]]:
        """Return all registered hooks."""
        return {name: list(entries) for name, entries in self._hooks.items()}

    def _collect_services(self) -> list[ServiceLike]:
        """Return all registered services."""
        return list(self._services)

    def _collect_channels(self) -> list[Any]:
        """Return all registered channels."""
        return list(self._channels)

    def _collect_http_routes(self) -> list[dict[str, Any]]:
        """Return all registered HTTP routes."""
        return list(self._http_routes)

    async def _resolve_provider(self, fn: ContextProvider) -> str:
        """Call a context provider, handling both sync and async."""
        result = fn()
        if asyncio.iscoroutine(result):
            return await result
        return result  # type: ignore[return-value]
