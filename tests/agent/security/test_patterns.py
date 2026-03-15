"""Tests for credential pattern detection."""

import pytest

from velo.agent.security.patterns import redact_credentials


class TestRedactCredentials:
    """Test credential redaction in tool output."""

    def test_telegram_bot_token(self):
        text = "Token: bot123456789:ABCDefGhIjKlMnOpQrStUvWxYz123456789"
        result = redact_credentials(text)
        assert "[REDACTED]" in result
        assert "ABCDefGhIjKlMnOpQrStUvWxYz123456789" not in result

    def test_slack_bot_token(self):
        text = "SLACK_TOKEN=xoxb-1234-5678-abcdefghijklmnop"
        result = redact_credentials(text)
        assert "xoxb-" not in result

    def test_slack_app_token(self):
        text = "APP_TOKEN=xapp-1-ABCDEFG-1234567890-abcdef"
        result = redact_credentials(text)
        assert "xapp-" not in result

    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
        result = redact_credentials(text)
        assert "eyJhbGci" not in result

    def test_github_pat(self):
        text = "GH_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        result = redact_credentials(text)
        assert "ghp_" not in result

    def test_openai_key(self):
        text = "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwx"
        result = redact_credentials(text)
        assert "sk-proj-" not in result

    def test_anthropic_key(self):
        text = "key=sk-ant-api03-abcdefghijklmnopqrstuvwx"
        result = redact_credentials(text)
        assert "sk-ant-" not in result

    def test_preserves_normal_text(self):
        text = "The key to success is persistence. Token efforts won't work."
        result = redact_credentials(text)
        assert result == text

    def test_preserves_short_key_values(self):
        """Short key= values are not credentials."""
        text = "key=abc"
        result = redact_credentials(text)
        assert result == text

    def test_skips_inside_code_blocks(self):
        text = "```\nBearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig\n```"
        result = redact_credentials(text)
        assert "eyJhbGci" in result  # preserved inside code block

    def test_password_field(self):
        text = 'password=SuperSecretPassword123!'
        result = redact_credentials(text)
        assert "SuperSecretPassword123" not in result
