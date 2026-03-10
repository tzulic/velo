"""Tests for CliProvider."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.base import LLMResponse
from nanobot.providers.cli_provider import CliProvider

SYSTEM_MSG = {"role": "system", "content": "You are a helpful assistant."}
USER_MSG = {"role": "user", "content": "What is 2+2?"}
MESSAGES = [SYSTEM_MSG, USER_MSG]

RESULT_JSON = json.dumps({"type": "result", "result": "Four.", "session_id": "sess-abc-123"})


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestCliProviderInit:
    def test_defaults(self):
        """Provider initializes with expected defaults."""
        p = CliProvider()
        assert p.default_model == "sonnet"
        assert p.timeout_s == 300
        assert p.permission_mode == "bypassPermissions"
        assert p.cli_path == "claude"

    def test_custom_params(self):
        """Provider stores custom parameters."""
        p = CliProvider(model="opus", timeout_s=60, permission_mode="default", cli_path="/usr/bin/claude")
        assert p.default_model == "opus"
        assert p.timeout_s == 60
        assert p.permission_mode == "default"
        assert p.cli_path == "/usr/bin/claude"

    def test_sessions_start_empty(self):
        """Session store starts empty."""
        p = CliProvider()
        assert p._sessions == {}


# ---------------------------------------------------------------------------
# _derive_session_key
# ---------------------------------------------------------------------------


class TestDeriveSessionKey:
    def test_deterministic_from_system_message(self):
        """Same system message always yields the same session key."""
        p = CliProvider()
        assert p._derive_session_key(MESSAGES) == p._derive_session_key(MESSAGES)

    def test_different_system_messages_yield_different_keys(self):
        """Different system messages produce different keys."""
        p = CliProvider()
        msgs_a = [{"role": "system", "content": "You are helpful."}]
        msgs_b = [{"role": "system", "content": "You are strict."}]
        assert p._derive_session_key(msgs_a) != p._derive_session_key(msgs_b)

    def test_no_system_message_uses_stable_default(self):
        """No system message yields the same default key regardless of user content."""
        p = CliProvider()
        k1 = p._derive_session_key([{"role": "user", "content": "Hi"}])
        k2 = p._derive_session_key([{"role": "user", "content": "Different message"}])
        assert k1 == k2

    def test_list_content_system_message(self):
        """System messages with list content are handled."""
        p = CliProvider()
        msgs = [{"role": "system", "content": [{"type": "text", "text": "You are helpful."}]}]
        key = p._derive_session_key(msgs)
        assert isinstance(key, str) and len(key) > 0


# ---------------------------------------------------------------------------
# _extract_last_user_message
# ---------------------------------------------------------------------------


class TestExtractLastUserMessage:
    def test_returns_last_user_message(self):
        p = CliProvider()
        assert p._extract_last_user_message(MESSAGES) == "What is 2+2?"

    def test_list_content(self):
        p = CliProvider()
        msgs = [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]
        assert p._extract_last_user_message(msgs) == "Hello"

    def test_no_user_message_returns_empty(self):
        p = CliProvider()
        assert p._extract_last_user_message([]) == ""

    def test_picks_last_user_message_in_multi_turn(self):
        p = CliProvider()
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "second"},
        ]
        assert p._extract_last_user_message(msgs) == "second"


# ---------------------------------------------------------------------------
# _parse_output
# ---------------------------------------------------------------------------


class TestParseOutput:
    def test_json_result_field(self):
        p = CliProvider()
        text, sid = p._parse_output(RESULT_JSON)
        assert text == "Four."
        assert sid == "sess-abc-123"

    def test_json_message_field(self):
        p = CliProvider()
        out = json.dumps({"message": "Hello.", "session_id": "xyz"})
        text, sid = p._parse_output(out)
        assert text == "Hello."
        assert sid == "xyz"

    def test_non_json_fallback(self):
        p = CliProvider()
        text, sid = p._parse_output("just plain text")
        assert "just plain text" in text
        assert sid is None

    def test_empty_output(self):
        p = CliProvider()
        text, sid = p._parse_output("")
        assert text == "(no response)"
        assert sid is None

    def test_is_error_response_still_parsed(self):
        """Error responses from the CLI are still parsed as text."""
        p = CliProvider()
        out = json.dumps({"result": "Something went wrong.", "is_error": True})
        text, _ = p._parse_output(out)
        assert text == "Something went wrong."


# ---------------------------------------------------------------------------
# _build_cmd
# ---------------------------------------------------------------------------


class TestBuildCmd:
    def test_fresh_session_includes_session_id(self):
        p = CliProvider()
        cmd = p._build_cmd("hi", "abc-uuid", "sonnet", is_resume=False, system_prompt=None)
        assert "--session-id" in cmd
        assert "abc-uuid" in cmd
        assert "--resume" not in cmd
        assert "hi" == cmd[-1]

    def test_resume_session_includes_resume(self):
        p = CliProvider()
        cmd = p._build_cmd("hi", "abc-uuid", "sonnet", is_resume=True, system_prompt=None)
        assert "--resume" in cmd
        assert "--session-id" not in cmd

    def test_system_prompt_injected_on_first_turn(self):
        p = CliProvider()
        cmd = p._build_cmd("hi", "abc-uuid", "sonnet", is_resume=False, system_prompt="Be helpful.")
        assert "--append-system-prompt" in cmd
        assert "Be helpful." in cmd

    def test_system_prompt_not_injected_on_resume(self):
        p = CliProvider()
        cmd = p._build_cmd("hi", "abc-uuid", "sonnet", is_resume=True, system_prompt="Be helpful.")
        assert "--append-system-prompt" not in cmd

    def test_model_included(self):
        p = CliProvider(model="opus")
        cmd = p._build_cmd("hi", "abc-uuid", "opus", is_resume=False, system_prompt=None)
        assert "--model" in cmd
        assert "opus" in cmd


# ---------------------------------------------------------------------------
# chat() — happy path and errors
# ---------------------------------------------------------------------------


class TestChat:
    @pytest.mark.asyncio
    async def test_successful_response(self):
        """Happy path returns LLMResponse with text content."""
        p = CliProvider()
        with patch.object(p, "_run_cli", new=AsyncMock(return_value=(RESULT_JSON, ""))):
            result = await p.chat(MESSAGES)
        assert isinstance(result, LLMResponse)
        assert result.content == "Four."
        assert result.finish_reason == "stop"
        assert result.tool_calls == []

    @pytest.mark.asyncio
    async def test_session_id_stored_after_first_call(self):
        """Session ID from CLI response is stored for future --resume calls."""
        p = CliProvider()
        with patch.object(p, "_run_cli", new=AsyncMock(return_value=(RESULT_JSON, ""))):
            await p.chat(MESSAGES)
        session_key = p._derive_session_key(MESSAGES)
        assert p._sessions[session_key] == "sess-abc-123"

    @pytest.mark.asyncio
    async def test_timeout_returns_error_response(self):
        """TimeoutError maps to error finish_reason with timeout code."""
        p = CliProvider(timeout_s=1)

        async def _timeout(*_args):
            raise TimeoutError("timed out")

        with patch.object(p, "_run_cli", new=_timeout):
            result = await p.chat(MESSAGES)
        assert result.finish_reason == "error"
        assert result.error_code == "timeout"

    @pytest.mark.asyncio
    async def test_oserror_returns_error_response(self):
        """OSError (binary not found) returns an error LLMResponse."""
        p = CliProvider()

        async def _fail(*_args):
            raise OSError("No such file: claude")

        with patch.object(p, "_run_cli", new=_fail):
            result = await p.chat(MESSAGES)
        assert result.finish_reason == "error"
        assert "claude" in result.content

    @pytest.mark.asyncio
    async def test_empty_prompt_returns_immediately(self):
        """Empty message list returns without invoking the CLI."""
        p = CliProvider()
        with patch.object(p, "_run_cli", new=AsyncMock()) as mock_run:
            result = await p.chat([])
        mock_run.assert_not_called()
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_session_collision_retries_with_resume(self):
        """When CLI returns 'already in use', retries automatically with --resume."""
        p = CliProvider()
        captured: list[list[str]] = []
        collision_stderr = "Error: Session ID abc is already in use."

        async def _capture(cmd):
            captured.append(cmd)
            if "--session-id" in cmd:
                return "", collision_stderr  # first call: collision
            return RESULT_JSON, ""  # retry with --resume: success

        with patch.object(p, "_run_cli", new=_capture):
            result = await p.chat(MESSAGES)

        assert len(captured) == 2
        assert "--session-id" in captured[0]
        assert "--resume" in captured[1]
        assert result.content == "Four."

    @pytest.mark.asyncio
    async def test_second_call_uses_resume(self):
        """Second call with same session uses --resume flag."""
        p = CliProvider()
        captured: list[list[str]] = []

        async def _capture(cmd):
            captured.append(cmd)
            return RESULT_JSON, ""

        with patch.object(p, "_run_cli", new=_capture):
            await p.chat(MESSAGES)
            await p.chat(MESSAGES)

        assert "--session-id" in captured[0]
        assert "--resume" in captured[1]
        assert "--session-id" not in captured[1]

    @pytest.mark.asyncio
    async def test_model_param_ignored(self):
        """External model param is ignored; CliProvider always uses its own default_model."""
        p = CliProvider(model="sonnet")
        captured: list[list[str]] = []

        async def _capture(cmd):
            captured.append(cmd)
            return RESULT_JSON, ""

        with patch.object(p, "_run_cli", new=_capture):
            await p.chat(MESSAGES, model="opus")

        idx = captured[0].index("--model")
        # Should use "sonnet" (provider default), not "opus" (external override)
        assert captured[0][idx + 1] == "sonnet"


# ---------------------------------------------------------------------------
# chat_stream()
# ---------------------------------------------------------------------------


class TestChatStream:
    @pytest.mark.asyncio
    async def test_yields_single_chunk_with_content(self):
        """chat_stream yields one StreamChunk with the full response."""
        p = CliProvider()
        with patch.object(p, "_run_cli", new=AsyncMock(return_value=(RESULT_JSON, ""))):
            chunks = [c async for c in p.chat_stream(MESSAGES)]
        assert len(chunks) == 1
        assert chunks[0].delta == "Four."
        assert chunks[0].finish_reason == "stop"


# ---------------------------------------------------------------------------
# get_default_model
# ---------------------------------------------------------------------------


class TestGetDefaultModel:
    def test_returns_configured_model(self):
        assert CliProvider(model="opus").get_default_model() == "opus"
        assert CliProvider(model="haiku").get_default_model() == "haiku"
