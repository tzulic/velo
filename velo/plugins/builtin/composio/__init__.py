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
from typing import TYPE_CHECKING, Any

from loguru import logger

from velo.plugins.builtin.composio.wrapper import ComposioToolWrapper

try:
    from composio import Composio

    _HAS_COMPOSIO = True
except ImportError:
    _HAS_COMPOSIO = False

if TYPE_CHECKING:
    from velo.plugins.types import PluginContext


_DEFAULT_PARAMS: dict[str, Any] = {"type": "object", "properties": {}}


def _parse_tool_def(tool_def: Any) -> tuple[str, str, dict[str, Any]] | None:
    """Extract (slug, description, parameters) from a Composio tool definition.

    Handles OpenAI-wrapped dicts, unwrapped dicts, and raw Tool objects.
    Returns None (with a warning) if the tool has no usable name.

    Args:
        tool_def: A single tool definition from ``session.tools()``.

    Returns:
        (slug, description, parameters) tuple, or None if unparseable.
    """
    if isinstance(tool_def, dict):
        # OpenAI-wrapped: {"type": "function", "function": {...}} or unwrapped
        func = tool_def.get("function", tool_def)
        slug = func.get("name")
        desc = func.get("description", slug or "")
        params = func.get("parameters", _DEFAULT_PARAMS)
    else:
        # Raw Composio Tool objects with .slug / .description / .input_parameters
        slug = getattr(tool_def, "slug", None) or getattr(tool_def, "name", None)
        desc = getattr(tool_def, "description", slug or "")
        params = getattr(tool_def, "input_parameters", _DEFAULT_PARAMS)

    if not slug:
        logger.warning("composio_plugin.setup: tool_def has no name, skipping: {}", tool_def)
        return None

    return slug, desc, params


def register(ctx: PluginContext) -> None:
    """Plugin entry point — placeholder for composio (tools loaded in activate).

    Args:
        ctx: Plugin context with config and workspace.
    """
    logger.debug("composio_plugin.register: will discover tools in activate()")


async def activate(ctx: PluginContext) -> None:
    """Discover and register Composio tools (requires I/O).

    Args:
        ctx: Plugin context with config and workspace.
    """
    if not _HAS_COMPOSIO:
        logger.warning("composio_plugin.activate: composio package not installed, skipping")
        return

    api_key = os.environ.get("COMPOSIO_API_KEY", "")
    user_id = os.environ.get("COMPOSIO_USER_ID", "")

    if not api_key or not user_id:
        logger.debug(
            "composio_plugin.activate: skipped (COMPOSIO_API_KEY or COMPOSIO_USER_ID not set)"
        )
        return

    try:
        # Reason: Composio SDK v1.x does NOT read COMPOSIO_BASE_URL from env.
        # Must pass base_url explicitly to route through the Volos proxy.
        base_url = os.environ.get("COMPOSIO_BASE_URL")
        composio = Composio(api_key=api_key, base_url=base_url) if base_url else Composio(api_key=api_key)
        session = composio.create(user_id=user_id)
        tools = session.tools()
    except Exception as exc:
        logger.warning("composio_plugin.activate: failed to load tools: {}", exc)
        return

    registered = 0
    for tool_def in tools:
        parsed = _parse_tool_def(tool_def)
        if parsed is None:
            continue
        slug, desc, params = parsed

        wrapper = ComposioToolWrapper(
            composio_client=composio,
            user_id=user_id,
            slug=slug,
            description=desc,
            input_parameters=params,
        )
        ctx.register_tool(wrapper, deferred=True)
        registered += 1

    logger.info("composio_plugin.activate: registered {} tools (deferred)", registered)
