"""Tests for plugin type definitions and PluginContext."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from velo.agent.tools.base import Tool
from velo.plugins.types import HOOKS, PluginContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DummyTool(Tool):
    """Minimal tool for testing registration."""

    @property
    def name(self) -> str:
        return "dummy_tool"

    @property
    def description(self) -> str:
        return "A dummy tool for testing."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> str:
        return "dummy_result"


def _make_ctx(tmp_path: Path) -> PluginContext:
    return PluginContext(plugin_name="test_plugin", config={"key": "val"}, workspace=tmp_path)


# ---------------------------------------------------------------------------
# Tests: PluginContext basics
# ---------------------------------------------------------------------------


def test_context_stores_metadata(tmp_path: Path) -> None:
    """PluginContext should store plugin_name, config, and workspace."""
    ctx = _make_ctx(tmp_path)
    assert ctx.plugin_name == "test_plugin"
    assert ctx.config == {"key": "val"}
    assert ctx.workspace == tmp_path


def test_register_tool(tmp_path: Path) -> None:
    """Registering a tool should be retrievable via _collect_tools as (tool, deferred) tuple."""
    ctx = _make_ctx(tmp_path)
    tool = _DummyTool()
    ctx.register_tool(tool)
    collected = ctx._collect_tools()
    assert len(collected) == 1
    assert collected[0][0].name == "dummy_tool"
    assert collected[0][1] is False  # not deferred by default


def test_register_tool_deferred(tmp_path: Path) -> None:
    """Registering with deferred=True should store the flag."""
    ctx = _make_ctx(tmp_path)
    ctx.register_tool(_DummyTool(), deferred=True)
    collected = ctx._collect_tools()
    assert len(collected) == 1
    assert collected[0][0].name == "dummy_tool"
    assert collected[0][1] is True


def test_register_multiple_tools(tmp_path: Path) -> None:
    """Multiple tools can be registered."""
    ctx = _make_ctx(tmp_path)
    ctx.register_tool(_DummyTool())
    ctx.register_tool(_DummyTool())
    assert len(ctx._collect_tools()) == 2


def test_add_context_provider(tmp_path: Path) -> None:
    """Context providers should be collectible."""
    ctx = _make_ctx(tmp_path)
    ctx.add_context_provider(lambda: "extra context")
    providers = ctx._collect_context_providers()
    assert len(providers) == 1


def test_register_hook(tmp_path: Path) -> None:
    """Hooks should be registered and collectible."""
    ctx = _make_ctx(tmp_path)

    def my_hook(value: str) -> str:
        return value + " modified"

    ctx.on("after_prompt_build", my_hook, priority=50)
    hooks = ctx._collect_hooks()
    assert len(hooks["after_prompt_build"]) == 1
    assert hooks["after_prompt_build"][0].priority == 50


def test_register_hook_default_priority(tmp_path: Path) -> None:
    """Default hook priority should be 100."""
    ctx = _make_ctx(tmp_path)
    ctx.on("on_startup", lambda: None)
    hooks = ctx._collect_hooks()
    assert hooks["on_startup"][0].priority == 100


def test_register_invalid_hook_raises(tmp_path: Path) -> None:
    """Registering an unknown hook name should raise ValueError."""
    ctx = _make_ctx(tmp_path)
    with pytest.raises(ValueError, match="Unknown hook 'nonexistent'"):
        ctx.on("nonexistent", lambda: None)


def test_all_hook_names_defined() -> None:
    """HOOKS dict should contain the 6 expected hooks."""
    expected = {
        "on_startup",
        "on_shutdown",
        "after_prompt_build",
        "before_tool_call",
        "after_tool_call",
        "before_response",
    }
    assert set(HOOKS.keys()) == expected


@pytest.mark.asyncio
async def test_resolve_provider_sync(tmp_path: Path) -> None:
    """_resolve_provider should handle sync callables."""
    ctx = _make_ctx(tmp_path)
    result = await ctx._resolve_provider(lambda: "sync_context")
    assert result == "sync_context"


@pytest.mark.asyncio
async def test_resolve_provider_async(tmp_path: Path) -> None:
    """_resolve_provider should handle async callables."""
    ctx = _make_ctx(tmp_path)

    async def async_provider() -> str:
        return "async_context"

    result = await ctx._resolve_provider(async_provider)
    assert result == "async_context"
