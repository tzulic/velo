"""Tests for tool result sanitization."""

from __future__ import annotations

import json

from velo.agent.tools.sanitize import sanitize_tool_result


class TestSanitizeToolResult:
    """Test sanitize_tool_result function."""

    def test_short_result_unchanged(self) -> None:
        """Results under the limit pass through untouched."""
        result = "Hello, world!"
        assert sanitize_tool_result(result) == result

    def test_empty_result_unchanged(self) -> None:
        """Empty string is returned as-is."""
        assert sanitize_tool_result("") == ""

    def test_truncation_at_limit(self) -> None:
        """Long results are truncated with an indicator."""
        result = "x" * 20_000
        sanitized = sanitize_tool_result(result, max_chars=1_000)
        assert len(sanitized) <= 1_100  # indicator adds some chars
        assert "truncated" in sanitized
        assert "chars" in sanitized

    def test_base64_data_uri_stripped(self) -> None:
        """Base64 data URIs are replaced with a placeholder."""
        import base64

        b64_blob = base64.b64encode(bytes(range(256)) * 2).decode()
        result = f"Image: data:image/png;base64,{b64_blob} end"
        sanitized = sanitize_tool_result(result, max_chars=50_000)
        assert "base64 data removed" in sanitized
        assert b64_blob not in sanitized

    def test_raw_base64_blob_stripped(self) -> None:
        """Raw base64 blobs (200+ diverse chars) are replaced with a placeholder."""
        import base64

        b64_blob = base64.b64encode(bytes(range(256)) * 2).decode()
        result = f"prefix {b64_blob} suffix"
        sanitized = sanitize_tool_result(result, max_chars=50_000)
        assert "base64 blob removed" in sanitized
        assert b64_blob not in sanitized

    def test_json_error_extraction(self) -> None:
        """JSON with error fields is compacted to just those fields."""
        data = {
            "error": "Something went wrong",
            "message": "Connection refused",
            "large_payload": "x" * 20_000,
        }
        result = json.dumps(data)
        sanitized = sanitize_tool_result(result, max_chars=1_000)
        assert "Something went wrong" in sanitized
        assert "Connection refused" in sanitized
        assert "large_payload" not in sanitized

    def test_json_without_error_fields_truncates(self) -> None:
        """JSON without error fields falls back to truncation."""
        data = {"data": "x" * 20_000}
        result = json.dumps(data)
        sanitized = sanitize_tool_result(result, max_chars=1_000)
        assert "truncated" in sanitized

    def test_non_json_large_result_truncates(self) -> None:
        """Non-JSON large results are truncated with indicator."""
        result = "line\n" * 5_000
        sanitized = sanitize_tool_result(result, max_chars=1_000)
        assert "truncated" in sanitized
        assert "lines removed" in sanitized

    def test_base64_strip_brings_under_limit(self) -> None:
        """If stripping base64 brings result under limit, no further truncation."""
        import base64

        text_part = "Result: OK"
        b64_part = base64.b64encode(bytes(range(256)) * 100).decode()
        result = f"{text_part} data:image/jpeg;base64,{b64_part}"
        sanitized = sanitize_tool_result(result, max_chars=500)
        assert "Result: OK" in sanitized
        assert "truncated" not in sanitized
