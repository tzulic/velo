"""Plugin type definitions and the PluginContext API surface."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Union

from nanobot.agent.tools.base import Tool

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

HookFn = Callable[..., Any]
"""A hook callback — sync or async. Signature varies by hook name."""

ContextProvider = Union[Callable[[], str], Callable[[], Awaitable[str]]]
"""Returns extra context to inject into the system prompt. May be sync or async."""

HookType = Literal["fire_and_forget", "modifying"]

# ---------------------------------------------------------------------------
# Hook definitions
# ---------------------------------------------------------------------------

HOOKS: dict[str, HookType] = {
    "on_startup": "fire_and_forget",
    "on_shutdown": "fire_and_forget",
    "after_prompt_build": "modifying",
    "before_tool_call": "modifying",
    "after_tool_call": "modifying",
    "before_response": "modifying",
}


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
# PluginContext — the API surface plugins receive in setup()
# ---------------------------------------------------------------------------

class PluginContext:
    """
    Context object passed to each plugin's ``setup()`` function.

    Plugins use this to register tools, context providers, and hook callbacks.
    """

    def __init__(self, plugin_name: str, config: dict[str, Any], workspace: Path) -> None:
        self.plugin_name = plugin_name
        self.config = config
        self.workspace = workspace
        self._tools: list[Tool] = []
        self._context_providers: list[ContextProvider] = []
        self._hooks: dict[str, list[HookEntry]] = {name: [] for name in HOOKS}

    def register_tool(self, tool: Tool) -> None:
        """Register a tool that the agent can use.

        Args:
            tool: A Tool instance to register.
        """
        self._tools.append(tool)

    def add_context_provider(self, fn: ContextProvider) -> None:
        """Register a function that returns extra system-prompt context.

        Args:
            fn: A sync or async callable returning a string.
        """
        self._context_providers.append(fn)

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
            raise ValueError(
                f"Unknown hook '{hook_name}'. Valid hooks: {', '.join(HOOKS)}"
            )
        self._hooks[hook_name].append(HookEntry(callback=callback, priority=priority))

    # -- Internal helpers (used by PluginManager) --

    def _collect_tools(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._tools)

    def _collect_context_providers(self) -> list[ContextProvider]:
        """Return all registered context providers."""
        return list(self._context_providers)

    def _collect_hooks(self) -> dict[str, list[HookEntry]]:
        """Return all registered hooks."""
        return {name: list(entries) for name, entries in self._hooks.items()}

    async def _resolve_provider(self, fn: ContextProvider) -> str:
        """Call a context provider, handling both sync and async."""
        result = fn()
        if asyncio.iscoroutine(result):
            return await result
        return result  # type: ignore[return-value]
