"""Tests for group chat tool restriction."""

from unittest.mock import MagicMock

from velo.agent.tools.registry import ToolRegistry

# Tools that should be blocked in group chats
_GROUP_RESTRICTED = {"exec", "write_file", "edit_file", "skill_manage", "cron", "spawn"}
# Tools that should always be available
_GROUP_ALLOWED = {"read_file", "web_search", "clarify", "session_search"}


def _make_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = f"Test tool {name}"
    tool.to_schema.return_value = {"type": "function", "function": {"name": name}}
    return tool


class TestGroupChatRestriction:
    def test_dm_gets_all_tools(self):
        registry = ToolRegistry()
        for name in _GROUP_RESTRICTED | _GROUP_ALLOWED:
            registry.register(_make_tool(name))
        defs = registry.get_definitions(session_metadata={"is_group": False})
        names = {d["function"]["name"] for d in defs}
        assert _GROUP_RESTRICTED.issubset(names)

    def test_group_restricts_dangerous_tools(self):
        registry = ToolRegistry()
        for name in _GROUP_RESTRICTED | _GROUP_ALLOWED:
            registry.register(_make_tool(name))
        defs = registry.get_definitions(session_metadata={"is_group": True})
        names = {d["function"]["name"] for d in defs}
        assert not _GROUP_RESTRICTED.intersection(names)
        assert _GROUP_ALLOWED.issubset(names)

    def test_no_metadata_returns_all(self):
        registry = ToolRegistry()
        for name in _GROUP_RESTRICTED | _GROUP_ALLOWED:
            registry.register(_make_tool(name))
        defs = registry.get_definitions()
        names = {d["function"]["name"] for d in defs}
        assert len(names) == len(_GROUP_RESTRICTED | _GROUP_ALLOWED)
