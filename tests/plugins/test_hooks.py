"""Tests for expanded hook system."""

from velo.plugins.types import HOOKS


class TestHookDefinitions:
    """Verify all 18 hooks are defined with correct strategies."""

    def test_hook_count(self):
        assert len(HOOKS) == 18

    def test_fire_and_forget_hooks(self):
        expected = {
            "on_startup", "on_shutdown", "message_received", "message_sent",
            "agent_end", "before_reset", "session_start", "session_end",
            "subagent_spawned", "subagent_ended",
        }
        actual = {name for name, typ in HOOKS.items() if typ == "fire_and_forget"}
        assert actual == expected

    def test_modifying_hooks(self):
        expected = {
            "before_model_resolve", "before_prompt_build", "after_prompt_build",
            "before_tool_call", "after_tool_call", "message_sending",
            "before_message_write",
        }
        actual = {name for name, typ in HOOKS.items() if typ == "modifying"}
        assert actual == expected

    def test_claiming_hooks(self):
        expected = {"inbound_claim"}
        actual = {name for name, typ in HOOKS.items() if typ == "claiming"}
        assert actual == expected

    def test_before_response_removed(self):
        assert "before_response" not in HOOKS

    def test_hook_type_literal(self):
        valid_types = {"fire_and_forget", "modifying", "claiming"}
        for name, typ in HOOKS.items():
            assert typ in valid_types, f"Hook '{name}' has invalid type '{typ}'"
