"""Tests for CallAgentTool.

The a2a-sdk package may not be installed in all environments.  These tests
mock the ``nanobot.a2a.client`` module so they run independently of whether
the SDK is present.
"""

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.tools.a2a_call import CallAgentTool
from nanobot.config.schema import A2APeerConfig


def _make_peer(name: str, url: str, api_key: str = "") -> A2APeerConfig:
    return A2APeerConfig(name=name, url=url, api_key=api_key)


def _install_client_mock(send_fn) -> tuple[ModuleType, str]:
    """Install a fake nanobot.a2a.client module in sys.modules.

    Returns the mock module and the previous value (or sentinel) so the
    caller can restore sys.modules after the test.
    """
    previous = sys.modules.get("nanobot.a2a.client")
    mock_mod = MagicMock(spec=ModuleType)
    mock_mod.send_task_to_peer = send_fn
    sys.modules["nanobot.a2a.client"] = mock_mod
    return mock_mod, previous


def _restore_client_mock(previous) -> None:
    if previous is None:
        sys.modules.pop("nanobot.a2a.client", None)
    else:
        sys.modules["nanobot.a2a.client"] = previous


class TestCallAgentTool:
    """Tests for CallAgentTool."""

    def test_tool_name_and_schema(self):
        """Tool has correct name and required parameters in schema."""
        tool = CallAgentTool(peers=[])
        assert tool.name == "call_agent"
        assert "peer" in tool.parameters["properties"]
        assert "task" in tool.parameters["properties"]
        assert tool.parameters["required"] == ["peer", "task"]

    @pytest.mark.asyncio
    async def test_execute_known_peer(self):
        """Named peer is resolved and task is sent with correct url and api_key."""
        peer = _make_peer("ResearchBot", "http://1.2.3.4:18791", api_key="secret")
        tool = CallAgentTool(peers=[peer])

        send_mock = AsyncMock(return_value="Response from peer")
        _, prev = _install_client_mock(send_mock)
        try:
            result = await tool.execute(peer="ResearchBot", task="Find info")
        finally:
            _restore_client_mock(prev)

        send_mock.assert_called_once_with("http://1.2.3.4:18791", "secret", "Find info")
        assert result == "Response from peer"

    @pytest.mark.asyncio
    async def test_execute_unknown_peer_returns_error(self):
        """Unknown peer name returns an error message listing available peers."""
        tool = CallAgentTool(peers=[_make_peer("Alpha", "http://a:18791")])
        result = await tool.execute(peer="Unknown", task="Do something")
        assert "Unknown" in result
        assert "Alpha" in result

    @pytest.mark.asyncio
    async def test_execute_direct_url(self):
        """Direct URL bypasses peer lookup and uses empty api_key."""
        tool = CallAgentTool(peers=[])
        send_mock = AsyncMock(return_value="ok")
        _, prev = _install_client_mock(send_mock)
        try:
            result = await tool.execute(peer="http://direct:18791", task="Go")
        finally:
            _restore_client_mock(prev)

        send_mock.assert_called_once_with("http://direct:18791", "", "Go")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_execute_network_error_returns_message(self):
        """Network failure returns a descriptive error message, does not raise."""
        tool = CallAgentTool(peers=[_make_peer("Bot", "http://bot:18791")])

        async def _fail(*args, **kwargs):
            raise ConnectionError("refused")

        _, prev = _install_client_mock(_fail)
        try:
            result = await tool.execute(peer="Bot", task="Do something")
        finally:
            _restore_client_mock(prev)

        assert "Failed" in result
        assert "http://bot:18791" in result

    def test_empty_peers_list(self):
        """Tool initialises with empty peers without error."""
        tool = CallAgentTool(peers=[])
        assert not tool._peers

    def test_multiple_peers_indexed_by_name(self):
        """Multiple peers are all indexed by name."""
        tool = CallAgentTool(peers=[
            _make_peer("Alpha", "http://a:18791"),
            _make_peer("Beta", "http://b:18791"),
        ])
        assert "Alpha" in tool._peers
        assert "Beta" in tool._peers
        assert tool._peers["Alpha"].url == "http://a:18791"
