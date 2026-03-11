"""Tests for PluginManager: discovery, loading, error isolation, hook dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from velo.plugins.manager import PluginManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_plugin(base_dir: Path, name: str, setup_code: str) -> Path:
    """Create a plugin package under base_dir/plugins/{name}/__init__.py."""
    plugin_dir = base_dir / "plugins" / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "__init__.py").write_text(setup_code, encoding="utf-8")
    return plugin_dir


_TOOL_PLUGIN = '''
from velo.plugins.types import PluginContext
from velo.agent.tools.base import Tool
from typing import Any

class GreetTool(Tool):
    @property
    def name(self) -> str:
        return "greet"

    @property
    def description(self) -> str:
        return "Says hello."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}

    async def execute(self, **kwargs: Any) -> str:
        return f"Hello, {kwargs['name']}!"

def setup(ctx: PluginContext) -> None:
    ctx.register_tool(GreetTool())
'''

_CONTEXT_PLUGIN = '''
from velo.plugins.types import PluginContext

def setup(ctx: PluginContext) -> None:
    ctx.add_context_provider(lambda: "Plugin context from test_context_plugin")
'''

_HOOK_PLUGIN = '''
from velo.plugins.types import PluginContext

def setup(ctx: PluginContext) -> None:
    def modify_prompt(value: str) -> str:
        return value + "\\n[HOOK INJECTED]"
    ctx.on("after_prompt_build", modify_prompt, priority=50)
'''

_FAILING_PLUGIN = '''
from velo.plugins.types import PluginContext

def setup(ctx: PluginContext) -> None:
    raise RuntimeError("Plugin setup intentionally failed!")
'''

_NO_SETUP_PLUGIN = '''
# This plugin has no setup() function
x = 42
'''

_STARTUP_SHUTDOWN_PLUGIN = '''
from velo.plugins.types import PluginContext

_state = {"started": False, "stopped": False}

def setup(ctx: PluginContext) -> None:
    def on_start():
        _state["started"] = True
    def on_stop():
        _state["stopped"] = True
    ctx.on("on_startup", on_start)
    ctx.on("on_shutdown", on_stop)
'''

_CONFIG_PLUGIN = '''
from velo.plugins.types import PluginContext

captured_config = {}

def setup(ctx: PluginContext) -> None:
    captured_config.update(ctx.config)
'''

# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------

class TestDiscovery:
    """Tests for plugin discovery."""

    def test_discover_workspace_plugins(self, tmp_path: Path) -> None:
        """Plugins in workspace/plugins/ should be discovered."""
        _write_plugin(tmp_path, "my_plugin", _TOOL_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        metas = mgr.discover()
        workspace_metas = [m for m in metas if m.source == "workspace"]
        assert len(workspace_metas) == 1
        assert workspace_metas[0].name == "my_plugin"

    def test_discover_ignores_files(self, tmp_path: Path) -> None:
        """Non-directory items in plugins/ should be ignored."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "not_a_plugin.py").write_text("x = 1")
        mgr = PluginManager(workspace=tmp_path, config={})
        workspace_metas = [m for m in mgr.discover() if m.source == "workspace"]
        assert workspace_metas == []

    def test_discover_ignores_dirs_without_init(self, tmp_path: Path) -> None:
        """Directories without __init__.py should be skipped."""
        (tmp_path / "plugins" / "no_init").mkdir(parents=True)
        mgr = PluginManager(workspace=tmp_path, config={})
        workspace_metas = [m for m in mgr.discover() if m.source == "workspace"]
        assert workspace_metas == []

    def test_discover_disabled_plugin(self, tmp_path: Path) -> None:
        """Plugins with enabled=false in config should be skipped."""
        _write_plugin(tmp_path, "disabled_one", _TOOL_PLUGIN)
        mgr = PluginManager(
            workspace=tmp_path,
            config={"disabled_one": {"enabled": False}},
        )
        workspace_metas = [m for m in mgr.discover() if m.source == "workspace"]
        assert workspace_metas == []

    def test_discover_no_plugins_dir(self, tmp_path: Path) -> None:
        """No crash when plugins/ directory doesn't exist (only builtins found)."""
        mgr = PluginManager(workspace=tmp_path, config={})
        workspace_metas = [m for m in mgr.discover() if m.source == "workspace"]
        assert workspace_metas == []

    def test_discover_multiple_sorted(self, tmp_path: Path) -> None:
        """Multiple workspace plugins should be discovered in sorted order."""
        _write_plugin(tmp_path, "beta", _TOOL_PLUGIN)
        _write_plugin(tmp_path, "alpha", _CONTEXT_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        workspace_names = [m.name for m in mgr.discover() if m.source == "workspace"]
        assert workspace_names == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# Loading tests
# ---------------------------------------------------------------------------

class TestLoading:
    """Tests for plugin loading and setup()."""

    @pytest.mark.asyncio
    async def test_load_registers_tool(self, tmp_path: Path) -> None:
        """A plugin that registers a tool should appear in get_all_tools()."""
        _write_plugin(tmp_path, "tool_plugin", _TOOL_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        tools = mgr.get_all_tools()
        assert len(tools) == 1
        tool, deferred = tools[0]
        assert tool.name == "greet"
        assert deferred is False

    @pytest.mark.asyncio
    async def test_load_registers_context_provider(self, tmp_path: Path) -> None:
        """A plugin context provider should contribute to get_context_additions()."""
        _write_plugin(tmp_path, "ctx_plugin", _CONTEXT_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        ctx = await mgr.get_context_additions()
        assert "Plugin context from test_context_plugin" in ctx

    @pytest.mark.asyncio
    async def test_failing_plugin_does_not_block_others(self, tmp_path: Path) -> None:
        """A plugin whose setup() raises should not prevent other plugins from loading."""
        _write_plugin(tmp_path, "aaa_failing", _FAILING_PLUGIN)
        _write_plugin(tmp_path, "bbb_good", _TOOL_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        # The good plugin should still have loaded
        assert len(mgr.get_all_tools()) == 1
        assert mgr.get_all_tools()[0][0].name == "greet"

    @pytest.mark.asyncio
    async def test_no_setup_function_is_error(self, tmp_path: Path) -> None:
        """A plugin without setup() should fail gracefully (error isolation)."""
        _write_plugin(tmp_path, "no_setup", _NO_SETUP_PLUGIN)
        _write_plugin(tmp_path, "good_plugin", _TOOL_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        assert len(mgr.get_all_tools()) == 1

    @pytest.mark.asyncio
    async def test_load_all_idempotent(self, tmp_path: Path) -> None:
        """Calling load_all() twice should be a no-op the second time."""
        _write_plugin(tmp_path, "plugin_idem", _TOOL_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        assert len(mgr.get_all_tools()) == 1
        # Second call shouldn't double-register
        await mgr.load_all()
        assert len(mgr.get_all_tools()) == 1

    @pytest.mark.asyncio
    async def test_plugin_receives_config(self, tmp_path: Path) -> None:
        """Plugin config (minus 'enabled') should be passed to setup()."""
        _write_plugin(tmp_path, "cfg_plugin", _CONFIG_PLUGIN)
        mgr = PluginManager(
            workspace=tmp_path,
            config={"cfg_plugin": {"enabled": True, "api_key": "sk-test", "model": "gpt-4"}},
        )
        await mgr.load_all()
        # Import the module to check captured_config
        import importlib
        mod = importlib.import_module("velo_plugin_cfg_plugin")
        assert mod.captured_config == {"api_key": "sk-test", "model": "gpt-4"}


# ---------------------------------------------------------------------------
# Hook dispatch tests
# ---------------------------------------------------------------------------

class TestHookDispatch:
    """Tests for fire() and pipe() hook dispatch."""

    @pytest.mark.asyncio
    async def test_pipe_modifies_value(self, tmp_path: Path) -> None:
        """pipe() should pass value through modifying hooks sequentially."""
        _write_plugin(tmp_path, "hook_plugin", _HOOK_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        result = await mgr.pipe("after_prompt_build", value="Original prompt")
        assert result == "Original prompt\n[HOOK INJECTED]"

    @pytest.mark.asyncio
    async def test_pipe_priority_order(self, tmp_path: Path) -> None:
        """Lower priority hooks should run first in pipe()."""
        plugin_code = '''
from velo.plugins.types import PluginContext

def setup(ctx: PluginContext) -> None:
    ctx.on("after_prompt_build", lambda value: value + " [B]", priority=200)
    ctx.on("after_prompt_build", lambda value: value + " [A]", priority=10)
'''
        _write_plugin(tmp_path, "priority_plugin", plugin_code)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        result = await mgr.pipe("after_prompt_build", value="Start")
        assert result == "Start [A] [B]"

    @pytest.mark.asyncio
    async def test_pipe_skips_failing_callback(self, tmp_path: Path) -> None:
        """A failing callback in pipe() should be skipped, passing value through."""
        plugin_code = '''
from velo.plugins.types import PluginContext

def setup(ctx: PluginContext) -> None:
    def fail_hook(value):
        raise RuntimeError("boom")
    def good_hook(value):
        return value + " [OK]"
    ctx.on("after_prompt_build", fail_hook, priority=10)
    ctx.on("after_prompt_build", good_hook, priority=20)
'''
        _write_plugin(tmp_path, "mixed_plugin", plugin_code)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        result = await mgr.pipe("after_prompt_build", value="Start")
        assert result == "Start [OK]"

    @pytest.mark.asyncio
    async def test_fire_does_not_propagate_errors(self, tmp_path: Path) -> None:
        """fire() should log but not raise on callback errors."""
        plugin_code = '''
from velo.plugins.types import PluginContext

def setup(ctx: PluginContext) -> None:
    def crash():
        raise RuntimeError("startup crash")
    ctx.on("on_startup", crash)
'''
        _write_plugin(tmp_path, "crash_plugin", plugin_code)
        mgr = PluginManager(workspace=tmp_path, config={})
        # Should not raise
        await mgr.load_all()

    @pytest.mark.asyncio
    async def test_fire_and_forget_runs_all(self, tmp_path: Path) -> None:
        """fire() should run all callbacks even if one fails."""
        plugin_code = '''
from velo.plugins.types import PluginContext

results = []

def setup(ctx: PluginContext) -> None:
    def crash():
        raise RuntimeError("boom")
    def succeed():
        results.append("ran")
    ctx.on("on_startup", crash, priority=10)
    ctx.on("on_startup", succeed, priority=20)
'''
        _write_plugin(tmp_path, "mixed_fire", plugin_code)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        import importlib
        mod = importlib.import_module("velo_plugin_mixed_fire")
        assert mod.results == ["ran"]

    @pytest.mark.asyncio
    async def test_shutdown_fires_on_shutdown(self, tmp_path: Path) -> None:
        """shutdown() should fire on_shutdown hooks."""
        _write_plugin(tmp_path, "lifecycle", _STARTUP_SHUTDOWN_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        import importlib
        mod = importlib.import_module("velo_plugin_lifecycle")
        assert mod._state["started"] is True
        assert mod._state["stopped"] is False
        await mgr.shutdown()
        assert mod._state["stopped"] is True

    @pytest.mark.asyncio
    async def test_pipe_no_hooks_returns_original(self, tmp_path: Path) -> None:
        """pipe() with no registered hooks should return the original value."""
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        result = await mgr.pipe("after_prompt_build", value="unchanged")
        assert result == "unchanged"

    @pytest.mark.asyncio
    async def test_async_hook(self, tmp_path: Path) -> None:
        """Async hook callbacks should work correctly."""
        plugin_code = '''
from velo.plugins.types import PluginContext

def setup(ctx: PluginContext) -> None:
    async def async_modify(value):
        return value + " [ASYNC]"
    ctx.on("after_prompt_build", async_modify)
'''
        _write_plugin(tmp_path, "async_plugin", plugin_code)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        result = await mgr.pipe("after_prompt_build", value="Start")
        assert result == "Start [ASYNC]"


# ---------------------------------------------------------------------------
# Context additions tests
# ---------------------------------------------------------------------------

class TestContextAdditions:
    """Tests for get_context_additions()."""

    @pytest.mark.asyncio
    async def test_empty_when_no_providers(self, tmp_path: Path) -> None:
        """Should return empty string with no context providers."""
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        assert await mgr.get_context_additions() == ""

    @pytest.mark.asyncio
    async def test_async_context_provider(self, tmp_path: Path) -> None:
        """Async context providers should work."""
        plugin_code = '''
from velo.plugins.types import PluginContext

def setup(ctx: PluginContext) -> None:
    async def async_ctx():
        return "async context data"
    ctx.add_context_provider(async_ctx)
'''
        _write_plugin(tmp_path, "async_ctx_plugin", plugin_code)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        result = await mgr.get_context_additions()
        assert "async context data" in result

    @pytest.mark.asyncio
    async def test_failing_provider_skipped(self, tmp_path: Path) -> None:
        """A failing context provider should be skipped."""
        plugin_code = '''
from velo.plugins.types import PluginContext

def setup(ctx: PluginContext) -> None:
    def fail():
        raise RuntimeError("ctx fail")
    def succeed():
        return "good context"
    ctx.add_context_provider(fail)
    ctx.add_context_provider(succeed)
'''
        _write_plugin(tmp_path, "mixed_ctx", plugin_code)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        result = await mgr.get_context_additions()
        assert "good context" in result


# ---------------------------------------------------------------------------
# Introspection tests
# ---------------------------------------------------------------------------

class TestIntrospection:
    """Tests for PluginManager property accessors."""

    @pytest.mark.asyncio
    async def test_plugin_names(self, tmp_path: Path) -> None:
        """plugin_names should list all discovered plugin names."""
        _write_plugin(tmp_path, "alpha", _TOOL_PLUGIN)
        _write_plugin(tmp_path, "beta", _CONTEXT_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        assert "alpha" in mgr.plugin_names
        assert "beta" in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_loaded_flag(self, tmp_path: Path) -> None:
        """loaded should be True after load_all()."""
        mgr = PluginManager(workspace=tmp_path, config={})
        assert mgr.loaded is False
        await mgr.load_all()
        assert mgr.loaded is True
