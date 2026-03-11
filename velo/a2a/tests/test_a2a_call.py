"""Tests for CallAgentTool.

The a2a-sdk package may not be installed in all environments.  These tests
mock the ``nanobot.a2a.client`` module so they run independently of whether
the SDK is present.
"""

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from velo.agent.tools.a2a_call import CallAgentTool
from velo.config.schema import A2APeerConfig


def _make_peer(name: str, url: str, api_key: str = "") -> A2APeerConfig:
    return A2APeerConfig(name=name, url=url, api_key=api_key)


@pytest.fixture()
def mock_client(monkeypatch):
    """Fixture that installs a fake nanobot.a2a.client in sys.modules.

    Yields the mock module so tests can configure ``send_task_to_peer``.
    """
    mock_mod = MagicMock(spec=ModuleType)
    monkeypatch.setitem(sys.modules, "velo.a2a.client", mock_mod)
    yield mock_mod


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
    async def test_execute_known_peer(self, mock_client):
        """Named peer is resolved and task is sent with correct url and api_key."""
        peer = _make_peer("ResearchBot", "http://1.2.3.4:18791", api_key="secret")
        tool = CallAgentTool(peers=[peer])

        mock_client.send_task_to_peer = AsyncMock(return_value="Response from peer")
        result = await tool.execute(peer="ResearchBot", task="Find info")

        mock_client.send_task_to_peer.assert_called_once_with(
            "http://1.2.3.4:18791", "secret", "Find info"
        )
        assert result == "Response from peer"

    @pytest.mark.asyncio
    async def test_execute_unknown_peer_returns_error(self):
        """Unknown peer name returns an error message listing available peers."""
        tool = CallAgentTool(peers=[_make_peer("Alpha", "http://a:18791")])
        result = await tool.execute(peer="Unknown", task="Do something")
        assert "Unknown" in result
        assert "Alpha" in result

    @pytest.mark.asyncio
    async def test_execute_direct_url(self, mock_client):
        """Direct URL bypasses peer lookup and uses empty api_key."""
        tool = CallAgentTool(peers=[])
        mock_client.send_task_to_peer = AsyncMock(return_value="ok")

        result = await tool.execute(peer="http://direct:18791", task="Go")

        mock_client.send_task_to_peer.assert_called_once_with("http://direct:18791", "", "Go")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_execute_network_error_returns_message(self, mock_client):
        """Network failure returns a descriptive error message, does not raise."""
        tool = CallAgentTool(peers=[_make_peer("Bot", "http://bot:18791")])

        async def _fail(*args, **kwargs):
            raise ConnectionError("refused")

        mock_client.send_task_to_peer = _fail
        result = await tool.execute(peer="Bot", task="Do something")

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
