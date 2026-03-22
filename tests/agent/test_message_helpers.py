"""Tests for message helper utilities."""

from unittest.mock import MagicMock

from velo.agent.message_helpers import format_tool_calls


def _make_tool_call(id: str, name: str, arguments: dict) -> MagicMock:
    tc = MagicMock()
    tc.id = id
    tc.name = name
    tc.arguments = arguments
    return tc


def test_format_tool_calls_basic():
    tcs = [_make_tool_call("1", "read_file", {"path": "/foo"})]
    result = format_tool_calls(tcs)
    assert len(result) == 1
    assert result[0]["id"] == "1"
    assert result[0]["type"] == "function"
    assert result[0]["function"]["name"] == "read_file"
    assert '"path": "/foo"' in result[0]["function"]["arguments"]


def test_format_tool_calls_empty():
    assert format_tool_calls([]) == []


def test_format_tool_calls_unicode():
    tcs = [_make_tool_call("2", "write", {"text": "café ☕"})]
    result = format_tool_calls(tcs)
    assert "café" in result[0]["function"]["arguments"]
    assert "☕" in result[0]["function"]["arguments"]
