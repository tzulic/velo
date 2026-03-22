"""Factory for constructing AgentLoop instances from config."""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from velo.agent.loop import AgentLoop
    from velo.bus.queue import MessageBus
    from velo.config.schema import Config
    from velo.cron.service import CronService
    from velo.plugins.manager import PluginManager
    from velo.providers.base import LLMProvider
    from velo.session.manager import SessionManager


def build_agent_loop(
    *,
    config: Config,
    bus: MessageBus,
    provider: LLMProvider,
    cron_service: CronService | None = None,
    plugin_manager: PluginManager | None = None,
    fallback_provider: LLMProvider | None = None,
    session_manager: SessionManager | None = None,
    clarify_callback: Callable[[str, list[str] | None], Awaitable[str]] | None = None,
) -> AgentLoop:
    """Construct an AgentLoop by unpacking config defaults.

    Centralizes the mapping from Config to AgentLoop constructor
    params so both gateway and CLI agent commands use a single source.

    Args:
        config: Loaded Velo configuration.
        bus: Message bus for inbound/outbound queues.
        provider: Primary LLM provider.
        cron_service: Optional cron scheduler instance.
        plugin_manager: Optional plugin manager instance.
        fallback_provider: Optional fallback LLM provider.
        session_manager: Optional pre-built session manager.
        clarify_callback: Optional interactive clarification callback.

    Returns:
        Fully configured AgentLoop instance.
    """
    from velo.agent.loop import AgentLoop

    defaults = config.agents.defaults
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=defaults.model,
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        max_iterations=defaults.max_tool_iterations,
        memory_window=defaults.memory_window,
        memory_char_limit=defaults.memory_char_limit,
        user_char_limit=defaults.user_char_limit,
        memory_nudge_interval=defaults.memory_nudge_interval,
        compress_protect_first=defaults.compress_protect_first,
        compress_protect_last=defaults.compress_protect_last,
        reasoning_effort=defaults.reasoning_effort,
        parallel_api_key=config.tools.web.search.api_key or None,
        web_proxy=config.tools.web.proxy or None,
        browse_config=config.tools.web.browse,
        exec_config=config.tools.exec,
        cron_service=cron_service,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        session_manager=session_manager,
        session_backend=defaults.session_backend,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        plugin_manager=plugin_manager,
        context_window=defaults.context_window,
        a2a_peers=config.a2a.peers,
        fallback_provider=fallback_provider,
        subagent_model=defaults.subagent_model,
        save_trajectories=defaults.save_trajectories,
        clarify_callback=clarify_callback,
        honcho_config=config.honcho,
        max_iteration_budget=defaults.max_iteration_budget,
    )
