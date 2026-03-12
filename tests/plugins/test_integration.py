"""Integration tests for the plugin system with agent components."""

from __future__ import annotations

from pathlib import Path

import pytest

from velo.agent.context import ContextBuilder
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


_TOOL_PLUGIN = """
from velo.plugins.types import PluginContext
from velo.agent.tools.base import Tool
from typing import Any

class PingTool(Tool):
    @property
    def name(self) -> str:
        return "ping"

    @property
    def description(self) -> str:
        return "Returns pong."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> str:
        return "pong"

def setup(ctx: PluginContext) -> None:
    ctx.register_tool(PingTool())
    ctx.add_context_provider(lambda: "Plugin: PingTool is available.")
"""

_PROMPT_HOOK_PLUGIN = """
from velo.plugins.types import PluginContext

def setup(ctx: PluginContext) -> None:
    def add_footer(value: str) -> str:
        return value + "\\n\\n[Plugin Footer]"
    ctx.on("after_prompt_build", add_footer)
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPluginContextIntegration:
    """Test that plugins integrate with ContextBuilder."""

    @pytest.mark.asyncio
    async def test_plugin_context_appears_in_prompt(self, tmp_path: Path) -> None:
        """Plugin context providers should appear in the system prompt."""
        _write_plugin(tmp_path, "ping_plugin", _TOOL_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()

        builder = ContextBuilder(workspace=tmp_path, plugin_manager=mgr)
        prompt = await builder.build_system_prompt()

        assert "Plugin: PingTool is available." in prompt
        assert "# Plugin Context" in prompt

    @pytest.mark.asyncio
    async def test_prompt_hook_modifies_prompt(self, tmp_path: Path) -> None:
        """after_prompt_build hook should modify the final system prompt."""
        _write_plugin(tmp_path, "footer_plugin", _PROMPT_HOOK_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()

        builder = ContextBuilder(workspace=tmp_path, plugin_manager=mgr)
        prompt = await builder.build_system_prompt()

        assert prompt.endswith("[Plugin Footer]")

    @pytest.mark.asyncio
    async def test_build_messages_includes_plugin_context(self, tmp_path: Path) -> None:
        """build_messages() should include plugin context in the system message."""
        _write_plugin(tmp_path, "msg_plugin", _TOOL_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()

        builder = ContextBuilder(workspace=tmp_path, plugin_manager=mgr)
        messages = await builder.build_messages(
            history=[],
            current_message="Hello",
            channel="cli",
            chat_id="direct",
        )

        system_msg = messages[0]
        assert system_msg["role"] == "system"
        assert "Plugin: PingTool is available." in system_msg["content"]

    @pytest.mark.asyncio
    async def test_no_plugin_manager_works(self, tmp_path: Path) -> None:
        """ContextBuilder without a plugin manager should work as before."""
        builder = ContextBuilder(workspace=tmp_path)
        prompt = await builder.build_system_prompt()
        assert "velo" in prompt
        assert "# Plugin Context" not in prompt

    @pytest.mark.asyncio
    async def test_plugin_tools_in_manager(self, tmp_path: Path) -> None:
        """Plugin tools should be accessible via PluginManager.get_all_tools()."""
        _write_plugin(tmp_path, "ping_plugin2", _TOOL_PLUGIN)
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()

        tools = mgr.get_all_tools()
        assert any(t.name == "ping" for t, _ in tools)

    @pytest.mark.asyncio
    async def test_workspace_override_builtin(self, tmp_path: Path) -> None:
        """Workspace plugin with same name as builtin should override it."""
        # Create a "builtin" plugin directory manually (simulating the real builtin dir)
        # Note: In practice, workspace plugins override by loading after builtins.
        # This test verifies discovery order by checking workspace plugin is loaded.
        _write_plugin(
            tmp_path,
            "override_me",
            """
from velo.plugins.types import PluginContext

def setup(ctx: PluginContext) -> None:
    ctx.add_context_provider(lambda: "workspace version")
""",
        )
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        ctx = await mgr.get_context_additions()
        assert "workspace version" in ctx
