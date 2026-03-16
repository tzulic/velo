"""Plugin manager: manifest-first discovery, two-phase lifecycle, and hook dispatch."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from loguru import logger

from velo.agent.tools.base import Tool
from velo.plugins.manifest import load_manifest, validate_manifest
from velo.plugins.types import (
    HOOKS,
    ContextProvider,
    HookEntry,
    HookFn,
    PluginContext,
    PluginMeta,
    RuntimeAware,
    RuntimeRefs,
    ServiceLike,
)
from velo.plugins.validation import validate_config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUILTIN_DIR = Path(__file__).parent / "builtin"


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------


class PluginManager:
    """Discovers, loads, and manages plugins with two-phase lifecycle.

    Discovery uses manifest-first approach: every plugin must have a
    ``plugin.json`` file. Loading is split into two phases:

    1. **Register** (synchronous): declarations only — tools, hooks, context
       providers, HTTP routes.
    2. **Activate** (async): services, IO, background tasks.

    Discovery order (later overrides earlier):
    1. ``velo/plugins/builtin/`` — shipped with velo
    2. ``{workspace}/plugins/`` — workspace-local (Volos drops plugins via SSH)
    """

    def __init__(self, workspace: Path, config: dict[str, Any]) -> None:
        self._workspace = workspace
        self._config = config
        self._plugins: dict[str, PluginMeta] = {}
        self._tools: list[tuple[Tool, bool]] = []  # (tool, deferred)
        self._context_providers: list[ContextProvider] = []
        self._hooks: dict[str, list[HookEntry]] = {name: [] for name in HOOKS}
        self._services: list[ServiceLike] = []
        self._channels: list[Any] = []
        self._http_routes: list[dict[str, Any]] = []
        self._runtime: RuntimeRefs | None = None
        self._loaded = False

        # Internal state for two-phase lifecycle
        self._plugin_modules: dict[str, ModuleType] = {}
        self._plugin_contexts: dict[str, PluginContext] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> list[PluginMeta]:
        """Scan builtin and workspace plugin directories.

        For each candidate directory:
        1. Load plugin.json via ``load_manifest()`` — skip if missing.
        2. Validate manifest — skip if invalid.
        3. Check if disabled in config.
        4. Store manifest on PluginMeta.

        Returns:
            List of discovered plugin metadata, in load order.
        """
        found: dict[str, PluginMeta] = {}

        for source, base_dir in [
            ("builtin", _BUILTIN_DIR),
            ("workspace", self._workspace / "plugins"),
        ]:
            if not base_dir.is_dir():
                continue
            for candidate in sorted(base_dir.iterdir()):
                if not candidate.is_dir():
                    continue
                init_file = candidate / "__init__.py"
                if not init_file.is_file():
                    continue

                name = candidate.name

                # Manifest-first: require plugin.json
                manifest = load_manifest(candidate)
                if manifest is None:
                    logger.warning(
                        "plugin.discover_skipped: {} (no plugin.json)",
                        name,
                    )
                    continue

                # Validate manifest required fields
                manifest_errors = validate_manifest(manifest)
                if manifest_errors:
                    logger.warning(
                        "plugin.discover_skipped: {} (invalid manifest: {})",
                        name,
                        "; ".join(manifest_errors),
                    )
                    continue

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
                    manifest=manifest,
                )

        self._plugins = found
        logger.info(
            "plugin.discover_completed: {} plugin(s) found",
            len(found),
        )
        return list(found.values())

    # ------------------------------------------------------------------
    # Two-phase loading
    # ------------------------------------------------------------------

    def _register_plugin(self, meta: PluginMeta) -> None:
        """Phase 1: Import module and call register() — synchronous, declarations only.

        Args:
            meta: Plugin metadata from discovery (must have manifest).

        Raises:
            AttributeError: If plugin has no register() function.
            Exception: Propagated from register() call.
        """
        manifest = meta.manifest
        config_schema = manifest.config_schema if manifest else {}

        # Build per-plugin config (everything under plugins.{name} except 'enabled')
        plugin_conf = dict(self._config.get(meta.name, {}))
        plugin_conf.pop("enabled", None)

        # Validate config against manifest schema
        if config_schema:
            validated_conf, config_errors = validate_config(plugin_conf, config_schema, meta.name)
            if config_errors:
                meta.enabled = False
                for err in config_errors:
                    logger.warning("plugin.config_invalid: {}", err)
                return
            plugin_conf = validated_conf

        # Import the module
        module_name = f"velo_plugin_{meta.name}"
        init_path = meta.path / "__init__.py"

        spec = importlib.util.spec_from_file_location(module_name, init_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for plugin '{meta.name}' at {init_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        # Require register() — no backward compat with setup()
        register_fn = getattr(module, "register", None)
        if register_fn is None:
            has_setup = hasattr(module, "setup")
            if has_setup:
                raise AttributeError(
                    f"Plugin '{meta.name}' has setup() but no register(). "
                    f"Migrate to the two-phase lifecycle: register() + activate()."
                )
            raise AttributeError(f"Plugin '{meta.name}' has no register() function")

        # Build context and call register()
        ctx = PluginContext(
            plugin_name=meta.name,
            config=plugin_conf,
            workspace=self._workspace,
        )
        register_fn(ctx)

        # Check if plugin disabled itself during registration
        if ctx._disabled:
            meta.enabled = False
            logger.info(
                "plugin.register_self_disabled: {} ({})",
                meta.name,
                ctx._disable_reason,
            )
            return

        # Collect declarations from registration phase
        tools = ctx._collect_tools()
        context_providers = ctx._collect_context_providers()
        hooks = ctx._collect_hooks()
        channels = ctx._collect_channels()
        http_routes = ctx._collect_http_routes()

        self._tools.extend(tools)
        self._context_providers.extend(context_providers)
        self._channels.extend(channels)
        self._http_routes.extend(http_routes)

        for hook_name, entries in hooks.items():
            self._hooks[hook_name].extend(entries)

        # Store module + context for activate phase
        self._plugin_modules[meta.name] = module
        self._plugin_contexts[meta.name] = ctx

        logger.info(
            "plugin.register_completed: {} (tools={}, hooks={}, channels={}, "
            "context_providers={}, http_routes={})",
            meta.name,
            len(tools),
            sum(len(e) for e in hooks.values()),
            len(channels),
            len(context_providers),
            len(http_routes),
        )

    async def _activate_plugin(self, meta: PluginMeta) -> None:
        """Phase 2: Call activate() if present — async, services/IO allowed.

        Args:
            meta: Plugin metadata (must be enabled and registered).
        """
        module = self._plugin_modules.get(meta.name)
        ctx = self._plugin_contexts.get(meta.name)
        if module is None or ctx is None:
            return

        activate_fn = getattr(module, "activate", None)
        if activate_fn is None:
            return

        await activate_fn(ctx)

        # Collect services registered during activate phase
        services = ctx._collect_services()
        self._services.extend(services)

        logger.info(
            "plugin.activate_completed: {} (services={})",
            meta.name,
            len(services),
        )

    async def load_all(self) -> None:
        """Discover plugins and run two-phase lifecycle: register → activate.

        Safe to call multiple times — subsequent calls are no-ops.

        Phase 1 (Register): Synchronous declarations — tools, hooks, context.
        Phase 2 (Activate): Async — services, IO, background tasks.
        Phase 3: Start services and fire on_startup hooks.
        """
        if self._loaded:
            return
        self._loaded = True

        metas = self.discover()

        # Phase 1: Register (synchronous)
        for meta in metas:
            try:
                self._register_plugin(meta)
            except Exception:
                logger.exception("plugin.register_failed: {}", meta.name)
                meta.enabled = False

        # Sort all hooks by priority (lower first)
        for hook_name in self._hooks:
            self._hooks[hook_name].sort(key=lambda e: e.priority)

        # Remove disabled plugins from the registry
        self._plugins = {name: meta for name, meta in self._plugins.items() if meta.enabled}

        # Phase 2: Activate (async, only enabled plugins)
        for meta in [m for m in metas if m.enabled]:
            try:
                await self._activate_plugin(meta)
            except Exception:
                logger.exception("plugin.activate_failed: {}", meta.name)

        # Phase 3: Start services and fire startup hooks
        await self.start_services()
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
        Returns a dict with 'cancel' or '__block' for short-circuit.

        Args:
            hook: Hook name (must be a modifying hook).
            value: The initial value to pipe through callbacks.
            **kwargs: Additional arguments passed to each callback.

        Returns:
            The final transformed value, or a dict with cancel/__block.
        """
        entries = self._hooks.get(hook, [])
        for entry in entries:
            try:
                result = await self._call(entry.callback, value=value, **kwargs)
                if result is not None:
                    # Short-circuit on cancel or block
                    if isinstance(result, dict) and (result.get("cancel") or result.get("__block")):
                        return result
                    value = result
            except Exception:
                logger.exception("plugin.pipe_failed: {} (skipping callback)", hook)
        return value

    async def claim(self, hook: str, **kwargs: Any) -> Any:
        """First-claim-wins hook dispatch.

        Callbacks run sequentially by priority. The first to return a truthy
        result wins; remaining callbacks are skipped.

        Args:
            hook: Hook name (must be a claiming hook).
            **kwargs: Arguments passed to each callback.

        Returns:
            The first truthy result, or None if no callback claimed.
        """
        entries = self._hooks.get(hook, [])
        for entry in entries:
            try:
                result = await self._call(entry.callback, **kwargs)
                if result:
                    return result
            except Exception:
                logger.exception("plugin.claim_failed: {}", hook)
        return None

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

    def get_all_tools(self) -> list[tuple[Tool, bool]]:
        """Return all tools registered by plugins as (tool, deferred) pairs.

        Returns:
            List of (Tool, deferred) tuples. deferred=True means the tool
            should be registered in the deferred pool (loaded on-demand).
        """
        return list(self._tools)

    # ------------------------------------------------------------------
    # HTTP Routes
    # ------------------------------------------------------------------

    @property
    def http_routes(self) -> list[dict[str, Any]]:
        """Return all HTTP routes registered by plugins.

        Returns:
            List of route dicts with method, path, handler, metadata, plugin_name.
        """
        return list(self._http_routes)

    # ------------------------------------------------------------------
    # Services & Runtime
    # ------------------------------------------------------------------

    def set_runtime(self, refs: RuntimeRefs) -> None:
        """Inject late-bound runtime references into RuntimeAware services/channels.

        Args:
            refs: The runtime references to propagate.
        """
        self._runtime = refs
        for obj in (*self._services, *self._channels):
            if isinstance(obj, RuntimeAware):
                try:
                    obj.set_runtime(refs)
                except Exception:
                    logger.exception("plugin.set_runtime_failed")

    async def start_services(self) -> None:
        """Start all registered services (error-isolated).

        Each service is started sequentially. A failing service does not
        block others from starting.
        """
        for service in self._services:
            try:
                await service.start()
            except Exception:
                logger.exception("plugin.service_start_failed")

    async def stop_services(self) -> None:
        """Stop all registered services in reverse order (error-isolated)."""
        for service in reversed(self._services):
            try:
                service.stop()
            except Exception:
                logger.exception("plugin.service_stop_failed")

    def get_plugin_channels(self) -> list[Any]:
        """Return all channels registered by plugins.

        Returns:
            List of BaseChannel instances from plugins.
        """
        return list(self._channels)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Stop services and fire ``on_shutdown`` hooks for cleanup."""
        await self.stop_services()
        await self.fire("on_shutdown")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def plugin_names(self) -> list[str]:
        """Names of all successfully registered (enabled) plugins."""
        return list(self._plugins.keys())

    @property
    def loaded(self) -> bool:
        """Whether load_all() has been called."""
        return self._loaded
