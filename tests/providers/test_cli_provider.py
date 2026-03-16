"""Tests for CliProvider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from velo.providers.base import LLMResponse
from velo.providers.cli_provider import CliProvider

SYSTEM_MSG = {"role": "system", "content": "You are a helpful assistant."}
USER_MSG = {"role": "user", "content": "What is 2+2?"}
MESSAGES = [SYSTEM_MSG, USER_MSG]

RESULT_JSON = json.dumps({"type": "result", "result": "Four.", "session_id": "sess-abc-123"})


class TestCliProviderInit:
    def test_defaults(self) -> None:
        p = CliProvider()
        assert p.default_model == "sonnet"
        assert p.timeout_s == 900
        assert p.permission_mode == "bypassPermissions"
        assert p.cli_path == "claude"

    def test_custom_params(self) -> None:
        p = CliProvider(
            model="opus", timeout_s=60, permission_mode="default", cli_path="/usr/bin/claude"
        )
        assert p.default_model == "opus"
        assert p.timeout_s == 60
        assert p.permission_mode == "default"
        assert p.cli_path == "/usr/bin/claude"

    def test_sessions_start_empty(self) -> None:
        assert CliProvider()._sessions == {}


class TestDeriveSessionKey:
    def test_deterministic_from_system_message(self) -> None:
        p = CliProvider()
        assert p._derive_session_key(MESSAGES) == p._derive_session_key(MESSAGES)

    def test_different_system_messages_yield_different_keys(self) -> None:
        p = CliProvider()
        msgs_a = [{"role": "system", "content": "You are helpful."}]
        msgs_b = [{"role": "system", "content": "You are strict."}]
        assert p._derive_session_key(msgs_a) != p._derive_session_key(msgs_b)

    def test_no_system_message_uses_stable_default(self) -> None:
        p = CliProvider()
        k1 = p._derive_session_key([{"role": "user", "content": "Hi"}])
        k2 = p._derive_session_key([{"role": "user", "content": "Different message"}])
        assert k1 == k2

    def test_list_content_system_message(self) -> None:
        p = CliProvider()
        msgs = [{"role": "system", "content": [{"type": "text", "text": "You are helpful."}]}]
        key = p._derive_session_key(msgs)
        assert isinstance(key, str) and len(key) > 0


class TestExtractLastUserMessage:
    def test_returns_last_user_message(self) -> None:
        assert CliProvider()._extract_last_user_message(MESSAGES) == "What is 2+2?"

    def test_list_content(self) -> None:
        msgs = [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]
        assert CliProvider()._extract_last_user_message(msgs) == "Hello"

    def test_no_user_message_returns_empty(self) -> None:
        assert CliProvider()._extract_last_user_message([]) == ""

    def test_picks_last_user_message_in_multi_turn(self) -> None:
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "second"},
        ]
        assert CliProvider()._extract_last_user_message(msgs) == "second"


class TestParseOutput:
    def test_json_result_field(self) -> None:
        text, sid = CliProvider()._parse_output(RESULT_JSON)
        assert text == "Four."
        assert sid == "sess-abc-123"

    def test_json_message_field(self) -> None:
        out = json.dumps({"message": "Hello.", "session_id": "xyz"})
        text, sid = CliProvider()._parse_output(out)
        assert text == "Hello."
        assert sid == "xyz"

    def test_non_json_fallback(self) -> None:
        text, sid = CliProvider()._parse_output("just plain text")
        assert "just plain text" in text
        assert sid is None

    def test_empty_output(self) -> None:
        text, sid = CliProvider()._parse_output("")
        assert text == "(no response)"
        assert sid is None

    def test_is_error_response_still_parsed(self) -> None:
        out = json.dumps({"result": "Something went wrong.", "is_error": True})
        text, _ = CliProvider()._parse_output(out)
        assert text == "Something went wrong."


class TestBuildCmd:
    def test_fresh_session_includes_session_id(self) -> None:
        cmd = CliProvider()._build_cmd(
            "hi", "abc-uuid", "sonnet", is_resume=False, system_prompt=None
        )
        assert "--session-id" in cmd
        assert "abc-uuid" in cmd
        assert "--resume" not in cmd
        assert cmd[-1] == "hi"

    def test_resume_session_includes_resume(self) -> None:
        cmd = CliProvider()._build_cmd(
            "hi", "abc-uuid", "sonnet", is_resume=True, system_prompt=None
        )
        assert "--resume" in cmd
        assert "--session-id" not in cmd

    def test_system_prompt_injected_on_first_turn(self) -> None:
        cmd = CliProvider()._build_cmd(
            "hi", "abc-uuid", "sonnet", is_resume=False, system_prompt="Be helpful."
        )
        assert "--append-system-prompt" in cmd
        assert "Be helpful." in cmd

    def test_system_prompt_not_injected_on_resume(self) -> None:
        cmd = CliProvider()._build_cmd(
            "hi", "abc-uuid", "sonnet", is_resume=True, system_prompt="Be helpful."
        )
        assert "--append-system-prompt" not in cmd

    def test_model_included(self) -> None:
        cmd = CliProvider(model="opus")._build_cmd(
            "hi", "abc-uuid", "opus", is_resume=False, system_prompt=None
        )
        assert "--model" in cmd
        assert "opus" in cmd


class TestChat:
    @pytest.mark.asyncio
    async def test_successful_response(self) -> None:
        p = CliProvider()
        with patch.object(p, "_run_cli", new=AsyncMock(return_value=(RESULT_JSON, ""))):
            result = await p.chat(MESSAGES)
        assert isinstance(result, LLMResponse)
        assert result.content == "Four."
        assert result.finish_reason == "stop"
        assert result.tool_calls == []

    @pytest.mark.asyncio
    async def test_session_id_stored_after_first_call(self) -> None:
        p = CliProvider()
        with patch.object(p, "_run_cli", new=AsyncMock(return_value=(RESULT_JSON, ""))):
            await p.chat(MESSAGES)
        session_key = p._derive_session_key(MESSAGES)
        assert p._sessions[session_key] == "sess-abc-123"

    @pytest.mark.asyncio
    async def test_timeout_returns_error_response(self) -> None:
        p = CliProvider(timeout_s=1)

        async def _timeout(*_args: object) -> tuple[str, str]:
            raise TimeoutError("timed out")

        with patch.object(p, "_run_cli", new=_timeout):
            result = await p.chat(MESSAGES)
        assert result.finish_reason == "error"
        assert result.error_code == "timeout"

    @pytest.mark.asyncio
    async def test_oserror_returns_error_response(self) -> None:
        p = CliProvider()

        async def _fail(*_args: object) -> tuple[str, str]:
            raise OSError("No such file: claude")

        with patch.object(p, "_run_cli", new=_fail):
            result = await p.chat(MESSAGES)
        assert result.finish_reason == "error"
        assert "claude" in result.content

    @pytest.mark.asyncio
    async def test_empty_prompt_returns_immediately(self) -> None:
        p = CliProvider()
        with patch.object(p, "_run_cli", new=AsyncMock()) as mock_run:
            result = await p.chat([])
        mock_run.assert_not_called()
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_session_collision_retries_with_resume(self) -> None:
        p = CliProvider()
        captured: list[list[str]] = []
        collision_stderr = "Error: Session ID abc is already in use."

        async def _capture(cmd: list[str]) -> tuple[str, str]:
            captured.append(cmd)
            if "--session-id" in cmd:
                return "", collision_stderr
            return RESULT_JSON, ""

        with patch.object(p, "_run_cli", new=_capture):
            result = await p.chat(MESSAGES)

        assert len(captured) == 2
        assert "--session-id" in captured[0]
        assert "--resume" in captured[1]
        assert result.content == "Four."

    @pytest.mark.asyncio
    async def test_second_call_uses_resume(self) -> None:
        p = CliProvider()
        captured: list[list[str]] = []

        async def _capture(cmd: list[str]) -> tuple[str, str]:
            captured.append(cmd)
            return RESULT_JSON, ""

        with patch.object(p, "_run_cli", new=_capture):
            await p.chat(MESSAGES)
            await p.chat(MESSAGES)

        assert "--session-id" in captured[0]
        assert "--resume" in captured[1]
        assert "--session-id" not in captured[1]

    @pytest.mark.asyncio
    async def test_model_param_ignored(self) -> None:
        p = CliProvider(model="sonnet")
        captured: list[list[str]] = []

        async def _capture(cmd: list[str]) -> tuple[str, str]:
            captured.append(cmd)
            return RESULT_JSON, ""

        with patch.object(p, "_run_cli", new=_capture):
            await p.chat(MESSAGES, model="opus")

        idx = captured[0].index("--model")
        assert captured[0][idx + 1] == "sonnet"


class TestChatStream:
    @pytest.mark.asyncio
    async def test_yields_single_chunk_with_content(self) -> None:
        p = CliProvider()
        with patch.object(p, "_run_cli", new=AsyncMock(return_value=(RESULT_JSON, ""))):
            chunks = [c async for c in p.chat_stream(MESSAGES)]
        assert len(chunks) == 1
        assert chunks[0].delta == "Four."
        assert chunks[0].finish_reason == "stop"


class TestGetDefaultModel:
    def test_returns_configured_model(self) -> None:
        assert CliProvider(model="opus").get_default_model() == "opus"
        assert CliProvider(model="haiku").get_default_model() == "haiku"
