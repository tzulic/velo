"""Plugin manager: discovery, loading, and hook dispatch."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.plugins.types import (
    HOOKS,
    ContextProvider,
    HookEntry,
    HookFn,
    PluginContext,
    PluginMeta,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUILTIN_DIR = Path(__file__).parent / "builtin"


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------

class PluginManager:
    """
    Discovers, loads, and manages nanobot plugins.

    Discovery order (later overrides earlier):
    1. ``nanobot/plugins/builtin/`` — shipped with nanobot
    2. ``{workspace}/plugins/`` — workspace-local (Volos drops plugins here via SSH)
    """

    def __init__(self, workspace: Path, config: dict[str, Any]) -> None:
        self._workspace = workspace
        self._config = config
        self._plugins: dict[str, PluginMeta] = {}
        self._tools: list[Tool] = []
        self._context_providers: list[ContextProvider] = []
        self._hooks: dict[str, list[HookEntry]] = {name: [] for name in HOOKS}
        self._loaded = False

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> list[PluginMeta]:
        """Scan builtin and workspace plugin directories.

        Returns:
            List of discovered plugin metadata, in load order.
        """
        found: dict[str, PluginMeta] = {}

        for source, base_dir in [("builtin", _BUILTIN_DIR), ("workspace", self._workspace / "plugins")]:
            if not base_dir.is_dir():
                continue
            for candidate in sorted(base_dir.iterdir()):
                if not candidate.is_dir():
                    continue
                init_file = candidate / "__init__.py"
                if not init_file.is_file():
                    continue
                name = candidate.name
                # Skip if explicitly disabled in config
                plugin_conf = self._config.get(name, {})
                if isinstance(plugin_conf, dict) and not plugin_conf.get("enabled", True):
                    logger.debug("plugin.discover_skipped: {} (disabled)", name)
                    continue
                found[name] = PluginMeta(
                    name=name,
                    source=source,  # type: ignore[arg-type]
                    path=candidate,
                    enabled=True,
                )

        self._plugins = found
        logger.info(
            "plugin.discover_completed: {} plugin(s) found",
            len(found),
        )
        return list(found.values())

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_plugin(self, meta: PluginMeta) -> None:
        """Import a single plugin and call its ``setup()`` function.

        Args:
            meta: Plugin metadata from discovery.

        Raises:
            Exception: Propagated if the plugin's setup() raises.
        """
        module_name = f"nanobot_plugin_{meta.name}"
        init_path = meta.path / "__init__.py"

        spec = importlib.util.spec_from_file_location(module_name, init_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for plugin '{meta.name}' at {init_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        setup_fn = getattr(module, "setup", None)
        if setup_fn is None:
            raise AttributeError(f"Plugin '{meta.name}' has no setup() function")

        # Build per-plugin config (everything under plugins.{name} except 'enabled')
        plugin_conf = dict(self._config.get(meta.name, {}))
        plugin_conf.pop("enabled", None)

        ctx = PluginContext(
            plugin_name=meta.name,
            config=plugin_conf,
            workspace=self._workspace,
        )
        setup_fn(ctx)

        # Collect registrations
        self._tools.extend(ctx._collect_tools())
        self._context_providers.extend(ctx._collect_context_providers())

        for hook_name, entries in ctx._collect_hooks().items():
            self._hooks[hook_name].extend(entries)

        logger.info(
            "plugin.load_completed: {} (tools={}, hooks={}, context_providers={})",
            meta.name,
            len(ctx._collect_tools()),
            sum(len(e) for e in ctx._collect_hooks().values()),
            len(ctx._collect_context_providers()),
        )

    async def load_all(self) -> None:
        """Discover plugins, load them, and fire ``on_startup`` hooks.

        Safe to call multiple times — subsequent calls are no-ops.
        """
        if self._loaded:
            return
        self._loaded = True

        metas = self.discover()
        for meta in metas:
            try:
                self._load_plugin(meta)
            except Exception:
                logger.exception("plugin.load_failed: {}", meta.name)

        # Sort all hooks by priority (lower first)
        for hook_name in self._hooks:
            self._hooks[hook_name].sort(key=lambda e: e.priority)

        # Fire startup hooks
        await self.fire("on_startup")

    # ------------------------------------------------------------------
    # Hook dispatch
    # ------------------------------------------------------------------

    async def _call(self, fn: HookFn, **kwargs: Any) -> Any:
        """Call a hook function, handling both sync and async.

        Args:
            fn: The hook callback.
            **kwargs: Arguments to pass.

        Returns:
            The return value of the callback.
        """
        result = fn(**kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def fire(self, hook: str, **kwargs: Any) -> None:
        """Fire-and-forget hook dispatch (parallel).

        All callbacks run concurrently. Exceptions are logged but do not propagate.

        Args:
            hook: Hook name (must be a fire_and_forget hook).
            **kwargs: Arguments passed to each callback.
        """
        entries = self._hooks.get(hook, [])
        if not entries:
            return

        async def _safe_call(entry: HookEntry) -> None:
            try:
                await self._call(entry.callback, **kwargs)
            except Exception:
                logger.exception("plugin.hook_failed: {}", hook)

        await asyncio.gather(*[_safe_call(e) for e in entries])

    async def pipe(self, hook: str, value: Any, **kwargs: Any) -> Any:
        """Sequential modifying hook dispatch.

        Each callback receives the output of the previous one.
        Exceptions skip that callback and pass the value through unchanged.

        Args:
            hook: Hook name (must be a modifying hook).
            value: The initial value to pipe through callbacks.
            **kwargs: Additional arguments passed to each callback.

        Returns:
            The final transformed value.
        """
        entries = self._hooks.get(hook, [])
        for entry in entries:
            try:
                result = await self._call(entry.callback, value=value, **kwargs)
                if result is not None:
                    value = result
            except Exception:
                logger.exception("plugin.pipe_failed: {} (skipping callback)", hook)
        return value

    # ------------------------------------------------------------------
    # Context providers
    # ------------------------------------------------------------------

    async def get_context_additions(self) -> str:
        """Collect output from all registered context providers.

        Returns:
            Concatenated context strings, separated by newlines.
            Empty string if no providers or all fail.
        """
        if not self._context_providers:
            return ""

        parts: list[str] = []
        for provider in self._context_providers:
            try:
                result = provider()
                if asyncio.iscoroutine(result):
                    result = await result
                if result:
                    parts.append(str(result))
            except Exception:
                logger.exception("plugin.context_provider_failed")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def get_all_tools(self) -> list[Tool]:
        """Return all tools registered by plugins.

        Returns:
            List of Tool instances.
        """
        return list(self._tools)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Fire ``on_shutdown`` hooks for cleanup."""
        await self.fire("on_shutdown")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def plugin_names(self) -> list[str]:
        """Names of all discovered plugins."""
        return list(self._plugins.keys())

    @property
    def loaded(self) -> bool:
        """Whether load_all() has been called."""
        return self._loaded
