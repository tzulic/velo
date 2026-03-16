"""Tests for pattern-triggered memory nudges."""

from velo.agent.memory_triggers import should_trigger_memory_nudge, get_triggered_nudge


class TestShouldTriggerMemoryNudge:
    def test_preference_pattern_matches(self):
        assert should_trigger_memory_nudge("I prefer dark mode for everything")

    def test_identity_pattern_matches(self):
        assert should_trigger_memory_nudge("My name is Tin")

    def test_remember_pattern_matches(self):
        assert should_trigger_memory_nudge("Remember that I hate spicy food")

    def test_no_match_on_normal_message(self):
        assert not should_trigger_memory_nudge("What's the weather like?")

    def test_empty_string(self):
        assert not should_trigger_memory_nudge("")

    def test_code_fence_skipped(self):
        msg = '```python\nmy_name = "I prefer this"\n```'
        assert not should_trigger_memory_nudge(msg)

    def test_inline_code_skipped(self):
        msg = "Use the `i prefer` flag in config"
        assert not should_trigger_memory_nudge(msg)

    def test_blockquote_skipped(self):
        msg = "> My name is John said the character"
        assert not should_trigger_memory_nudge(msg)

    def test_pattern_outside_code_still_matches(self):
        msg = "```code```\nI prefer Python over JS"
        assert should_trigger_memory_nudge(msg)


class TestGetTriggeredNudge:
    def test_returns_string(self):
        result = get_triggered_nudge()
        assert isinstance(result, str)
        assert "save_memory" in result
