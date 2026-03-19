"""Context Hub builtin plugin — curated API docs for coding agents.

Provides chub_search, chub_get, chub_annotate as deferred tools.
Requires the chub CLI to be installed (npm install -g @aisuite/chub).
Disabled gracefully if CLI is not found.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from velo.plugins.types import PluginContext

_SYSTEM_HINT = (
    "You have access to Context Hub for looking up curated API documentation. "
    "Use chub_search to find docs, then chub_get to fetch them. "
    "Use chub_annotate to save notes about quirks or workarounds for future sessions."
)


def register(ctx: PluginContext) -> None:
    """Plugin entry point — validate CLI and register tools.

    Args:
        ctx: Plugin context with config and workspace.
    """
    if not shutil.which("chub"):
        ctx.disable("chub CLI not installed (npm install -g @aisuite/chub)")
        logger.warning("chub_plugin.disabled: chub CLI not found in PATH")
        return

    from velo.plugins.builtin.chub.tools import (
        ChubAnnotateTool,
        ChubGetTool,
        ChubSearchTool,
    )

    config = ctx.config
    workspace = ctx.workspace

    ctx.register_tool(ChubSearchTool(workspace, config), deferred=True)
    ctx.register_tool(ChubGetTool(workspace, config), deferred=True)
    ctx.register_tool(ChubAnnotateTool(workspace, config), deferred=True)

    ctx.add_context_provider(lambda: _SYSTEM_HINT)

    logger.debug(
        "chub_plugin.registered: workspace={} lang_default={}",
        workspace,
        config.get("lang_default", "py"),
    )
