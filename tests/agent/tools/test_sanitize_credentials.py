"""Tests for credential stripping in sanitizer."""

from velo.agent.tools.sanitize import sanitize_tool_result


class TestCredentialStripping:
    def test_strips_telegram_token_from_tool_output(self):
        result = sanitize_tool_result(
            '{"token": "bot123456789:ABCDefGhIjKlMnOpQrStUvWxYz123456789"}'
        )
        assert "ABCDefGhIjKlMnOpQrStUvWxYz" not in result

    def test_strips_slack_token(self):
        result = sanitize_tool_result("SLACK_TOKEN=xoxb-1234-5678-abcdefghijklmnop")
        assert "xoxb-" not in result

    def test_preserves_normal_json(self):
        result = sanitize_tool_result('{"name": "test", "status": "ok"}')
        assert "test" in result
        assert "ok" in result
