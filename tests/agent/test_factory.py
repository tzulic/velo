"""Tests for AgentLoop factory."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from velo.agent.factory import build_agent_loop
from velo.config.schema import Config


def _make_config(tmp_path: Path) -> Config:
    """Create a Config with workspace pointing at tmp_path.

    Args:
        tmp_path: Temporary directory for workspace.

    Returns:
        Config instance with overridden workspace path.
    """
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    return config


def _make_provider() -> MagicMock:
    """Create a mock LLM provider.

    Returns:
        MagicMock with get_default_model stub.
    """
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return provider


def test_build_returns_agent_loop(tmp_path: Path) -> None:
    """Factory returns an AgentLoop instance with config defaults applied."""
    from velo.agent.loop import AgentLoop

    config = _make_config(tmp_path)
    bus = MagicMock()
    provider = _make_provider()

    agent = build_agent_loop(config=config, bus=bus, provider=provider)

    assert isinstance(agent, AgentLoop)
    assert agent.temperature == config.agents.defaults.temperature
    assert agent.max_tokens == config.agents.defaults.max_tokens
    assert agent.memory_window == config.agents.defaults.memory_window
    assert agent.workspace == tmp_path


def test_build_forwards_optional_params(tmp_path: Path) -> None:
    """Factory forwards caller-specific params like session_manager and cron_service."""
    config = _make_config(tmp_path)
    bus = MagicMock()
    provider = _make_provider()
    session_mgr = MagicMock()
    cron_svc = MagicMock()

    agent = build_agent_loop(
        config=config,
        bus=bus,
        provider=provider,
        session_manager=session_mgr,
        cron_service=cron_svc,
    )

    assert agent.sessions is session_mgr
    assert agent.cron_service is cron_svc


def test_build_without_optional_params(tmp_path: Path) -> None:
    """Factory works with only required params (no cron, plugin_manager, etc.)."""
    from velo.agent.loop import AgentLoop

    config = _make_config(tmp_path)
    bus = MagicMock()
    provider = _make_provider()

    agent = build_agent_loop(config=config, bus=bus, provider=provider)

    assert isinstance(agent, AgentLoop)
    assert agent.cron_service is None
    # clarify_callback=None means no ClarifyTool registered
    assert agent.tools.get("clarify") is None
