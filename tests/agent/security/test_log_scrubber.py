"""Tests for structlog log scrubber."""

from velo.agent.security.log_scrubber import scrub_log_event


class TestLogScrubber:
    def test_scrubs_token_in_event(self):
        event = {"event": "tool.exec_completed", "output": "token=xoxb-1234-abcdefghijklmnop"}
        result = scrub_log_event(None, None, event)
        assert "xoxb-" not in str(result)

    def test_preserves_clean_events(self):
        event = {"event": "agent.loop_started", "session": "telegram:123"}
        result = scrub_log_event(None, None, event)
        assert result["session"] == "telegram:123"

    def test_scrubs_nested_strings(self):
        event = {"event": "mcp.error", "details": {"stderr": "Bearer eyJhbGciOiJIUzI1NiJ9.x.y"}}
        result = scrub_log_event(None, None, event)
        assert "eyJhbGci" not in str(result)
