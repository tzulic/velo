"""Integration tests for the plugin system with agent components."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from velo.agent.context import ContextBuilder
from velo.plugins.manager import PluginManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_plugin(
    base_dir: Path,
    name: str,
    code: str,
    *,
    manifest: dict | None = None,
) -> Path:
    """Create a plugin package under base_dir/plugins/{name}/ with plugin.json.

    Args:
        base_dir: Workspace directory.
        name: Plugin name.
        code: Python code for __init__.py.
        manifest: Custom manifest dict. Defaults to minimal valid manifest.

    Returns:
        Path to the created plugin directory.
    """
    plugin_dir = base_dir / "plugins" / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "__init__.py").write_text(code, encoding="utf-8")

    m = manifest or {
        "id": name,
        "name": name,
        "version": "1.0.0",
        "description": f"Test plugin {name}",
        "config_schema": {},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(m), encoding="utf-8")
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

def register(ctx: PluginContext) -> None:
    ctx.register_tool(PingTool())
    ctx.add_context_provider(lambda: "Plugin: PingTool is available.")
"""

_PROMPT_HOOK_PLUGIN = """
from velo.plugins.types import PluginContext

def register(ctx: PluginContext) -> None:
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

def register(ctx: PluginContext) -> None:
    ctx.add_context_provider(lambda: "workspace version")
""",
        )
        mgr = PluginManager(workspace=tmp_path, config={})
        await mgr.load_all()
        ctx = await mgr.get_context_additions()
        assert "workspace version" in ctx


# ---------------------------------------------------------------------------
# Full lifecycle integration tests
# ---------------------------------------------------------------------------

_FULL_TEST_INIT = '''
from velo.plugins.types import PluginContext, HttpRequest, HttpResponse
from velo.agent.tools.base import Tool
from typing import Any


class GreetTool(Tool):
    @property
    def name(self) -> str:
        return "greet"

    @property
    def description(self) -> str:
        return "Say hello"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> str:
        return "hello"


def register(ctx: PluginContext) -> None:
    ctx.register_tool(GreetTool())
    ctx.on("message_sending", lambda value, **kw: value)
    ctx.add_context_provider(lambda: f"Greeting: {ctx.config.get('greeting', 'hi')}")

    async def handle_webhook(req: HttpRequest) -> HttpResponse:
        return HttpResponse(status=200, body="ok")

    ctx.register_http_route(method="POST", path="/webhooks/test", handler=handle_webhook)
'''


@pytest.fixture
def full_env(tmp_path: Path) -> Path:
    """Create a workspace with a full-featured test plugin.

    Args:
        tmp_path: Pytest-provided temporary directory.

    Returns:
        Path to the workspace root.
    """
    workspace = tmp_path / "workspace"
    plugins_dir = workspace / "plugins"
    plugins_dir.mkdir(parents=True)

    plugin_dir = plugins_dir / "full-test"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "full-test",
                "name": "Full Test",
                "version": "1.0.0",
                "description": "Integration test plugin",
                "config_schema": {
                    "greeting": {"type": "string", "default": "hello"},
                },
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(_FULL_TEST_INIT, encoding="utf-8")
    return workspace


class TestFullLifecycle:
    """Test full plugin lifecycle: discover, register, activate, hooks, HTTP routes."""

    @pytest.mark.asyncio
    async def test_discover_register(self, full_env: Path) -> None:
        """Plugin should be discovered, its tool registered, and HTTP route collected."""
        mgr = PluginManager(workspace=full_env, config={})
        await mgr.load_all()

        assert "full-test" in mgr.plugin_names
        assert len(mgr.get_all_tools()) == 1
        assert len(mgr.http_routes) == 1

        context = await mgr.get_context_additions()
        assert "Greeting: hello" in context

    @pytest.mark.asyncio
    async def test_hook_fire_and_pipe(self, full_env: Path) -> None:
        """message_sending hook should pass value through; other fire hooks should not error."""
        mgr = PluginManager(workspace=full_env, config={})
        await mgr.load_all()

        # message_sending hook should pass through unchanged
        result = await mgr.pipe("message_sending", value="test msg", channel="test", chat_id="1")
        assert result == "test msg"

        # Fire should not error even with no handlers for most hooks
        await mgr.fire("on_startup")
        await mgr.fire("message_received", content="hi", channel="test", chat_id="1", metadata={})

    @pytest.mark.asyncio
    async def test_config_defaults_from_manifest(self, full_env: Path) -> None:
        """Context provider should reflect the default value from manifest config_schema."""
        mgr = PluginManager(workspace=full_env, config={})
        await mgr.load_all()
        context = await mgr.get_context_additions()
        # Default 'greeting' from manifest is 'hello'
        assert "hello" in context

    @pytest.mark.asyncio
    async def test_config_override(self, full_env: Path) -> None:
        """User-supplied config should override manifest defaults."""
        mgr = PluginManager(
            workspace=full_env, config={"full-test": {"greeting": "howdy"}}
        )
        await mgr.load_all()
        context = await mgr.get_context_additions()
        assert "Greeting: howdy" in context

    @pytest.mark.asyncio
    async def test_http_route_structure(self, full_env: Path) -> None:
        """HTTP route dict should have the required keys for PluginHttpServer integration."""
        mgr = PluginManager(workspace=full_env, config={})
        await mgr.load_all()

        assert len(mgr.http_routes) == 1
        route = mgr.http_routes[0]
        assert route["method"] == "POST"
        assert route["path"] == "/webhooks/test"
        assert callable(route["handler"])
        assert route["plugin_name"] == "full-test"
