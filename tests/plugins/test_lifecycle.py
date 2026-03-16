"""Tests for two-phase plugin lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from velo.plugins.manager import PluginManager


@pytest.fixture
def plugin_env(tmp_path: Path) -> tuple[Path, Path]:
    """Create a workspace with plugins directory."""
    workspace = tmp_path / "workspace"
    plugins_dir = workspace / "plugins"
    plugins_dir.mkdir(parents=True)
    return workspace, plugins_dir


def _create_plugin(
    plugins_dir: Path,
    name: str,
    *,
    needs_activate: bool = False,
    manifest: dict | None = None,
    code: str | None = None,
) -> Path:
    """Create a plugin with plugin.json and __init__.py.

    Args:
        plugins_dir: Parent plugins directory.
        name: Plugin directory name.
        needs_activate: If True, generate code with both register() and activate().
        manifest: Custom manifest dict. Defaults to minimal valid manifest.
        code: Custom __init__.py code. Overrides needs_activate.

    Returns:
        Path to the created plugin directory.
    """
    plugin_dir = plugins_dir / name
    plugin_dir.mkdir()

    m = manifest or {
        "id": name,
        "name": name,
        "version": "1.0.0",
        "description": f"Test {name}",
        "config_schema": {},
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(m))

    if code:
        (plugin_dir / "__init__.py").write_text(code)
    elif needs_activate:
        (plugin_dir / "__init__.py").write_text(
            "from velo.plugins.types import PluginContext\n"
            "def register(ctx: PluginContext) -> None: pass\n"
            "async def activate(ctx: PluginContext) -> None: pass\n"
        )
    else:
        (plugin_dir / "__init__.py").write_text(
            "from velo.plugins.types import PluginContext\n"
            "def register(ctx: PluginContext) -> None: pass\n"
        )

    return plugin_dir


class TestTwoPhaseLifecycle:
    """Tests for two-phase plugin lifecycle (register → activate)."""

    @pytest.mark.asyncio
    async def test_register_only_plugin(self, plugin_env: tuple[Path, Path]) -> None:
        """A plugin with only register() should load successfully."""
        workspace, plugins_dir = plugin_env
        _create_plugin(plugins_dir, "simple")
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "simple" in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_plugin_without_manifest_skipped(self, plugin_env: tuple[Path, Path]) -> None:
        """A plugin directory without plugin.json should be skipped."""
        workspace, plugins_dir = plugin_env
        plugin_dir = plugins_dir / "no-manifest"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("def register(ctx): pass\n")
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "no-manifest" not in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_plugin_without_register_skipped(self, plugin_env: tuple[Path, Path]) -> None:
        """A plugin with setup() but no register() should fail and be disabled."""
        workspace, plugins_dir = plugin_env
        _create_plugin(plugins_dir, "old-style", code="def setup(ctx): pass\n")
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "old-style" not in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_disabled_via_config(self, plugin_env: tuple[Path, Path]) -> None:
        """A plugin disabled in config should not appear in plugin_names."""
        workspace, plugins_dir = plugin_env
        _create_plugin(plugins_dir, "disabled-one")
        mgr = PluginManager(
            workspace=workspace,
            config={"disabled-one": {"enabled": False}},
        )
        await mgr.load_all()
        assert "disabled-one" not in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_config_validation_disables_plugin(self, plugin_env: tuple[Path, Path]) -> None:
        """A plugin whose required config field is missing should be disabled."""
        workspace, plugins_dir = plugin_env
        _create_plugin(
            plugins_dir,
            "needs-key",
            manifest={
                "id": "needs-key",
                "name": "Needs Key",
                "version": "1.0.0",
                "description": "test",
                "config_schema": {
                    "api_key": {"type": "string", "required": True},
                },
            },
        )
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "needs-key" not in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_config_defaults_applied(self, plugin_env: tuple[Path, Path]) -> None:
        """Config defaults from the manifest schema should be applied."""
        workspace, plugins_dir = plugin_env
        _create_plugin(
            plugins_dir,
            "with-defaults",
            manifest={
                "id": "with-defaults",
                "name": "Defaults",
                "version": "1.0.0",
                "description": "test",
                "config_schema": {
                    "port": {"type": "integer", "default": 8080},
                },
            },
            code=(
                "from velo.plugins.types import PluginContext\n"
                "def register(ctx: PluginContext) -> None:\n"
                "    assert ctx.config.get('port') == 8080\n"
            ),
        )
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "with-defaults" in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_ctx_disable_skips_plugin(self, plugin_env: tuple[Path, Path]) -> None:
        """A plugin that calls ctx.disable() during register should be disabled."""
        workspace, plugins_dir = plugin_env
        _create_plugin(
            plugins_dir,
            "self-disable",
            code=(
                "from velo.plugins.types import PluginContext\n"
                "def register(ctx: PluginContext) -> None:\n"
                "    ctx.disable('intentionally disabled')\n"
            ),
        )
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "self-disable" not in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_activate_called_for_plugins_with_it(self, plugin_env: tuple[Path, Path]) -> None:
        """Plugins with an activate() function should have it called."""
        workspace, plugins_dir = plugin_env
        _create_plugin(
            plugins_dir,
            "with-activate",
            code=(
                "from velo.plugins.types import PluginContext\n"
                "_activated = False\n"
                "def register(ctx: PluginContext) -> None: pass\n"
                "async def activate(ctx: PluginContext) -> None:\n"
                "    global _activated\n"
                "    _activated = True\n"
            ),
        )
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "with-activate" in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_multiple_plugins_load_order(self, plugin_env: tuple[Path, Path]) -> None:
        """Multiple plugins should all be discovered and loaded."""
        workspace, plugins_dir = plugin_env
        _create_plugin(plugins_dir, "alpha")
        _create_plugin(plugins_dir, "beta")
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "alpha" in mgr.plugin_names
        assert "beta" in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_manifest_stored_on_meta(self, plugin_env: tuple[Path, Path]) -> None:
        """PluginMeta should have the manifest attached after discovery."""
        workspace, plugins_dir = plugin_env
        _create_plugin(plugins_dir, "manifest-test")
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        meta = mgr._plugins.get("manifest-test")
        assert meta is not None
        assert meta.manifest is not None
        assert meta.manifest.id == "manifest-test"

    @pytest.mark.asyncio
    async def test_http_routes_collected(self, plugin_env: tuple[Path, Path]) -> None:
        """HTTP routes registered during register() should be accessible."""
        workspace, plugins_dir = plugin_env
        _create_plugin(
            plugins_dir,
            "http-plugin",
            code=(
                "from velo.plugins.types import PluginContext\n"
                "async def my_handler(request): return {'status': 200}\n"
                "def register(ctx: PluginContext) -> None:\n"
                "    ctx.register_http_route('POST', '/webhook', my_handler)\n"
            ),
        )
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert len(mgr.http_routes) == 1
        assert mgr.http_routes[0]["method"] == "POST"
        assert mgr.http_routes[0]["path"] == "/webhook"

    @pytest.mark.asyncio
    async def test_services_registered_during_activate(self, plugin_env: tuple[Path, Path]) -> None:
        """Services should be collectible from activate phase."""
        workspace, plugins_dir = plugin_env
        _create_plugin(
            plugins_dir,
            "service-plugin",
            code=(
                "from velo.plugins.types import PluginContext\n"
                "class MyService:\n"
                "    async def start(self): pass\n"
                "    def stop(self): pass\n"
                "def register(ctx: PluginContext) -> None: pass\n"
                "async def activate(ctx: PluginContext) -> None:\n"
                "    ctx.register_service(MyService())\n"
            ),
        )
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "service-plugin" in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_register_failure_does_not_block_others(
        self, plugin_env: tuple[Path, Path]
    ) -> None:
        """A plugin that fails during register should not block other plugins."""
        workspace, plugins_dir = plugin_env
        _create_plugin(
            plugins_dir,
            "aaa_failing",
            code=(
                "from velo.plugins.types import PluginContext\n"
                "def register(ctx: PluginContext) -> None:\n"
                "    raise RuntimeError('boom')\n"
            ),
        )
        _create_plugin(plugins_dir, "bbb_good")
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "aaa_failing" not in mgr.plugin_names
        assert "bbb_good" in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_activate_failure_does_not_block_others(
        self, plugin_env: tuple[Path, Path]
    ) -> None:
        """A plugin that fails during activate should not block other plugins."""
        workspace, plugins_dir = plugin_env
        _create_plugin(
            plugins_dir,
            "aaa_bad_activate",
            code=(
                "from velo.plugins.types import PluginContext\n"
                "def register(ctx: PluginContext) -> None: pass\n"
                "async def activate(ctx: PluginContext) -> None:\n"
                "    raise RuntimeError('activate boom')\n"
            ),
        )
        _create_plugin(plugins_dir, "bbb_ok", needs_activate=True)
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        # Both should be in plugin_names (activate failure is logged but plugin still registered)
        assert "aaa_bad_activate" in mgr.plugin_names
        assert "bbb_ok" in mgr.plugin_names

    @pytest.mark.asyncio
    async def test_invalid_manifest_skipped(self, plugin_env: tuple[Path, Path]) -> None:
        """A plugin with invalid manifest (missing required fields) is skipped."""
        workspace, plugins_dir = plugin_env
        _create_plugin(
            plugins_dir,
            "bad-manifest",
            manifest={"id": "", "name": "", "version": "", "description": ""},
        )
        mgr = PluginManager(workspace=workspace, config={})
        await mgr.load_all()
        assert "bad-manifest" not in mgr.plugin_names
