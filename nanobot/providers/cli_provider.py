"""Claude CLI provider — invokes the claude binary directly via Claude Max subscription."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, StreamChunk


class CliProvider(LLMProvider):
    """
    LLM provider that invokes the Claude Code CLI as a subprocess.

    Uses your Claude Max subscription (OAuth) instead of an API key.
    Maintains conversation context across turns via CLI session IDs.

    Requires the Claude Code CLI to be installed and authenticated:
        npm install -g @anthropic-ai/claude-code
        claude auth login
    """

    def __init__(
        self,
        model: str = "sonnet",
        timeout_s: int = 300,
        permission_mode: str = "bypassPermissions",
        cli_path: str = "claude",
    ):
        """
        Initialize the CLI provider.

        Args:
            model: Claude model alias (e.g. "sonnet", "opus", "haiku",
                   or a versioned name like "claude-sonnet-4-6").
            timeout_s: Max seconds to wait for the CLI process to finish.
            permission_mode: Claude CLI permission mode (default "bypassPermissions").
            cli_path: Path to the claude binary (defaults to PATH lookup).
        """
        super().__init__(api_key=None, api_base=None)
        self.default_model = model
        self.timeout_s = timeout_s
        self.permission_mode = permission_mode
        self.cli_path = cli_path
        # Maps session_key → CLI session UUID for conversation continuity.
        self._sessions: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        """
        Send a chat request via the Claude CLI subprocess.

        Args:
            messages: Conversation history (system + user/assistant turns).
            tools: Ignored — the CLI does not support external tool calls.
            model: Model alias override.
            max_tokens: Ignored — controlled by the CLI internally.
            temperature: Ignored — not supported by the CLI in print mode.
            reasoning_effort: Ignored — not supported in this mode.

        Returns:
            LLMResponse with text content and no tool calls.
        """
        # Always use CliProvider's own model — ignore the external model param,
        # which is typically the nanobot default (e.g. "anthropic/claude-opus-4-5").
        resolved_model = self.default_model
        prompt = self._extract_last_user_message(messages)
        if not prompt:
            return LLMResponse(content="(empty prompt)", finish_reason="stop")

        session_key = self._derive_session_key(messages)
        session_id, is_resume = self._get_or_create_session_id(session_key)
        system_prompt = self._extract_system_prompt(messages) if not is_resume else None

        cmd = self._build_cmd(prompt, session_id, resolved_model, is_resume, system_prompt)
        logger.debug("cli_provider.run: model={} resume={} session={}", resolved_model, is_resume, session_id[:8])

        try:
            stdout, stderr = await self._run_cli(cmd)
        except TimeoutError:
            return LLMResponse(
                content="Error: claude CLI timed out",
                finish_reason="error",
                error_code="timeout",
            )
        except Exception as exc:
            error_msg = str(exc)
            logger.error("cli_provider.error: {}", error_msg)
            from nanobot.providers.errors import classify_error
            return LLMResponse(
                content=f"Error calling claude CLI: {error_msg}",
                finish_reason="error",
                error_code=classify_error(error_msg),
            )

        # If the session ID is already in use (CLI retains sessions across restarts),
        # retry with --resume so we continue the existing session instead of failing.
        if stderr and "is already in use" in stderr and not is_resume:
            logger.debug("cli_provider.session_collision: retrying with --resume session={}", session_id[:8])
            self._sessions[session_key] = session_id  # mark as existing
            cmd = self._build_cmd(prompt, session_id, resolved_model, is_resume=True, system_prompt=None)
            try:
                stdout, stderr = await self._run_cli(cmd)
            except Exception as exc:
                error_msg = str(exc)
                logger.error("cli_provider.error: {}", error_msg)
                from nanobot.providers.errors import classify_error
                return LLMResponse(
                    content=f"Error calling claude CLI: {error_msg}",
                    finish_reason="error",
                    error_code=classify_error(error_msg),
                )

        if stderr:
            logger.debug("cli_provider.stderr: {}", stderr[:300])

        text, returned_session_id = self._parse_output(stdout)
        if returned_session_id:
            self._sessions[session_key] = returned_session_id
            logger.debug("cli_provider.session_stored: {}", returned_session_id[:8])

        return LLMResponse(content=text, tool_calls=[], finish_reason="stop")

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        Stream chat via the CLI (delegates to chat() then yields one final chunk).

        The CLI runs to completion before any output is available, so true
        token-by-token streaming is not supported. The full response is
        yielded as a single final StreamChunk.
        """
        response = await self.chat(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        )
        yield StreamChunk(
            delta=response.content or "",
            finish_reason=response.finish_reason,
            error_code=response.error_code,
        )

    def get_default_model(self) -> str:
        """Return the configured default model alias."""
        return self.default_model

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_cmd(
        self,
        prompt: str,
        session_id: str,
        model: str,
        is_resume: bool,
        system_prompt: str | None,
    ) -> list[str]:
        """
        Build the CLI argument list.

        Args:
            prompt: The user's message text.
            session_id: CLI session UUID.
            model: Model alias.
            is_resume: True to use --resume, False to seed a new --session-id.
            system_prompt: System prompt text injected on first turn only.

        Returns:
            list[str]: Argument list ready for create_subprocess_exec.
        """
        cmd = [
            self.cli_path,
            "--print",
            "--output-format", "json",
            "--permission-mode", self.permission_mode,
            "--model", model,
        ]
        if is_resume:
            cmd += ["--resume", session_id]
        else:
            cmd += ["--session-id", session_id]
            if system_prompt:
                cmd += ["--append-system-prompt", system_prompt]
        cmd.append(prompt)
        return cmd

    async def _run_cli(self, cmd: list[str]) -> tuple[str, str]:
        """
        Invoke the claude CLI subprocess and return (stdout, stderr).

        Args:
            cmd: Full argument list including the binary path.

        Returns:
            tuple[str, str]: Decoded stdout and stderr.

        Raises:
            TimeoutError: If the process exceeds timeout_s.
            OSError: If the binary is not found.
        """
        import asyncio

        # Unset CLAUDECODE so the subprocess can start inside a Claude Code session.
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDECODE_ENTRYPOINT")}

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise TimeoutError(f"claude CLI did not respond within {self.timeout_s}s")

        return (
            stdout_bytes.decode("utf-8", errors="replace"),
            stderr_bytes.decode("utf-8", errors="replace"),
        )

    def _parse_output(self, stdout: str) -> tuple[str, str | None]:
        """
        Extract the response text and session_id from CLI JSON output.

        The CLI outputs a single JSON object like:
            {"type": "result", "result": "...", "session_id": "uuid"}

        Args:
            stdout: Raw stdout from the CLI process.

        Returns:
            tuple[str, str | None]: (response_text, session_id_or_None).
        """
        text_parts: list[str] = []
        session_id: str | None = None

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                # Non-JSON lines are treated as plain text output.
                text_parts.append(line)
                continue

            if not isinstance(data, dict):
                continue

            # Capture session_id from first JSON object that has it.
            if not session_id:
                session_id = (
                    data.get("session_id")
                    or data.get("sessionId")
                    or data.get("conversation_id")
                    or data.get("conversationId")
                ) or None

            # Extract response text from known field names.
            for key in ("result", "message", "content", "text", "response"):
                val = data.get(key)
                if val and isinstance(val, str):
                    text_parts.append(val)
                    break

        text = "\n".join(text_parts).strip()
        return text or "(no response)", session_id

    def _derive_session_key(self, messages: list[dict[str, Any]]) -> str:
        """
        Derive a deterministic session UUID from the system prompt.

        The system prompt is stable for a given agent session, making it
        a reliable key for mapping nanobot sessions to CLI session IDs.

        Args:
            messages: Full conversation message list.

        Returns:
            str: A UUID string derived from the system prompt content.
        """
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content") or ""
                if isinstance(content, list):
                    content = " ".join(
                        item.get("text", "") for item in content if isinstance(item, dict)
                    )
                digest = hashlib.sha256(content[:500].encode("utf-8")).hexdigest()[:32]
                return str(uuid.UUID(digest))
        # No system message — use a stable default key.
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, "nanobot.cli.default"))

    def _get_or_create_session_id(self, session_key: str) -> tuple[str, bool]:
        """
        Return (session_id, is_resume) for the given session key.

        On first call, seeds the session with the key itself as the UUID.
        On subsequent calls, returns the stored session ID with is_resume=True.

        Args:
            session_key: Deterministic UUID string for this session.

        Returns:
            tuple[str, bool]: (session_id, is_resume).
        """
        if session_key in self._sessions:
            return self._sessions[session_key], True
        # Seed the session — the CLI will create a new session with this UUID.
        self._sessions[session_key] = session_key
        return session_key, False

    def _extract_last_user_message(self, messages: list[dict[str, Any]]) -> str:
        """
        Return the text content of the last user message.

        Args:
            messages: Full conversation message list.

        Returns:
            str: The user message text, or "" if not found.
        """
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                return "\n".join(p for p in parts if p)
        return ""

    def _extract_system_prompt(self, messages: list[dict[str, Any]]) -> str | None:
        """
        Return the system prompt text from messages, if present.

        Args:
            messages: Full conversation message list.

        Returns:
            str | None: System prompt text, or None if not found.
        """
        for msg in messages:
            if msg.get("role") != "system":
                continue
            content = msg.get("content") or ""
            if isinstance(content, list):
                content = " ".join(
                    item.get("text", "") for item in content if isinstance(item, dict)
                )
            return content.strip() or None
        return None
