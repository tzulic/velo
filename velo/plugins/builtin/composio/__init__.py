"""Composio builtin plugin — loads connected Composio tools at startup.

Reads ``COMPOSIO_API_KEY`` and ``COMPOSIO_USER_ID`` from the environment
(injected per-container by Volos provisioning). If either is missing the
plugin silently skips. All tools are registered as **deferred** so they
don't consume LLM context until activated via ``search_tools``.

The ``COMPOSIO_BASE_URL`` env var (also set by provisioning) redirects
all SDK calls through the Volos reverse proxy for key injection and
call counting.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from loguru import logger

from velo.plugins.builtin.composio.wrapper import ComposioToolWrapper

try:
    from composio import Composio

    _HAS_COMPOSIO = True
except ImportError:
    _HAS_COMPOSIO = False

if TYPE_CHECKING:
    from velo.plugins.types import PluginContext


def setup(ctx: PluginContext) -> None:
    """Plugin entry point — discover and register Composio tools.

    Args:
        ctx: Plugin context with config and workspace.
    """
    if not _HAS_COMPOSIO:
        logger.warning("composio_plugin.setup: composio package not installed, skipping")
        return

    api_key = os.environ.get("COMPOSIO_API_KEY", "")
    user_id = os.environ.get("COMPOSIO_USER_ID", "")

    if not api_key or not user_id:
        logger.debug(
            "composio_plugin.setup: skipped (COMPOSIO_API_KEY or COMPOSIO_USER_ID not set)"
        )
        return

    try:
        # COMPOSIO_BASE_URL env var is picked up automatically by the SDK
        composio = Composio(api_key=api_key)
        session = composio.create(user_id=user_id)
        tools = session.tools()
    except Exception as exc:
        logger.warning("composio_plugin.setup: failed to load tools: {}", exc)
        return

    for tool_def in tools:
        # session.tools() returns OpenAI-format dicts by default.
        # Handle both wrapped {"type": "function", "function": {...}} and
        # unwrapped {"name": ..., "description": ..., "parameters": {...}} formats.
        func = tool_def.get("function", tool_def) if isinstance(tool_def, dict) else None

        if func is None:
            # Fallback: raw Composio Tool objects with .slug / .description / .input_parameters
            slug = getattr(tool_def, "slug", None) or getattr(tool_def, "name", "unknown")
            desc = getattr(tool_def, "description", slug)
            params = getattr(
                tool_def, "input_parameters", {"type": "object", "properties": {}}
            )
        else:
            slug = func.get("name", "unknown")
            desc = func.get("description", slug)
            params = func.get("parameters", {"type": "object", "properties": {}})

        wrapper = ComposioToolWrapper(
            composio_client=composio,
            user_id=user_id,
            slug=slug,
            description=desc,
            input_parameters=params,
        )
        ctx.register_tool(wrapper, deferred=True)

    logger.info("composio_plugin.setup: registered {} tools (deferred)", len(tools))
