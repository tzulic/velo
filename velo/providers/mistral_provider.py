"""Native Mistral AI provider — direct SDK calls via mistralai."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import json_repair
from loguru import logger

from velo.providers.base import (
    LLMProvider,
    LLMResponse,
    StreamChunk,
    ToolCallRequest,
    short_tool_id,
    strip_model_prefix,
)

# Message keys accepted by the Mistral API (OpenAI-compatible format).
_ALLOWED_MSG_KEYS = frozenset(
    {"role", "content", "tool_calls", "tool_call_id", "name"}
)


class MistralProvider(LLMProvider):
    """LLM provider using the native Mistral AI SDK.

    Key SDK differences from OpenAI:
    - Async methods: ``chat.complete_async()`` / ``chat.stream_async()``
    - Stream chunks have an extra ``.data`` wrapper
    - tool_choice ``"required"`` maps to ``"any"``
    - ``seed`` maps to ``random_seed``
    """

    def __init__(
        self,
        api_key: str,
        api_base: str | None = None,
        default_model: str = "mistral-large-latest",
        server: str = "eu",
    ):
        super().__init__(api_key, api_base)
        from mistralai.client import Mistral

        self._default_model = default_model
        if api_base:
            self._client = Mistral(api_key=api_key, server_url=api_base)
        else:
            self._client = Mistral(api_key=api_key, server=server)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_prefix(model: str) -> str:
        """Strip 'mistral/' prefix from model name."""
        return strip_model_prefix(model, "mistral/")

    @staticmethod
    def _map_tool_choice(tool_choice: str) -> str:
        """Map OpenAI tool_choice to Mistral format ('required' → 'any')."""
        if tool_choice == "required":
            return "any"
        return tool_choice

    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Strip non-standard keys from messages."""
        return LLMProvider._sanitize_request_messages(messages, _ALLOWED_MSG_KEYS)

    @staticmethod
    def _normalize_tool_call_id(tool_call_id: str | None) -> str:
        """Normalize tool_call_id to Mistral's 9-char alphanumeric format."""
        if not tool_call_id:
            return short_tool_id()
        if len(tool_call_id) == 9 and tool_call_id.isalnum():
            return tool_call_id
        import hashlib
        return hashlib.sha1(tool_call_id.encode()).hexdigest()[:9]

    @staticmethod
    def _normalize_tool_ids_in_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Normalize all tool_call_ids in messages to Mistral's 9-char format.

        Keeps assistant tool_calls[].id and tool tool_call_id in sync.

        Args:
            messages: Sanitized message list.

        Returns:
            list: Messages with normalized tool_call_ids.
        """
        id_map: dict[str, str] = {}
        result: list[dict[str, Any]] = []

        for msg in messages:
            clean = dict(msg)

            # Normalize assistant tool_calls IDs.
            if isinstance(clean.get("tool_calls"), list):
                normalized = []
                for tc in clean["tool_calls"]:
                    if not isinstance(tc, dict):
                        normalized.append(tc)
                        continue
                    tc_copy = dict(tc)
                    old_id = tc_copy.get("id", "")
                    new_id = id_map.setdefault(
                        old_id, MistralProvider._normalize_tool_call_id(old_id),
                    )
                    tc_copy["id"] = new_id
                    normalized.append(tc_copy)
                clean["tool_calls"] = normalized

            # Normalize tool result tool_call_id.
            if "tool_call_id" in clean and clean["tool_call_id"]:
                old_id = clean["tool_call_id"]
                clean["tool_call_id"] = id_map.setdefault(
                    old_id, MistralProvider._normalize_tool_call_id(old_id),
                )

            result.append(clean)
        return result

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    def _build_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str,
    ) -> dict[str, Any]:
        """Build kwargs for Mistral chat methods.

        Returns:
            dict: Keyword arguments for the Mistral chat API.
        """
        resolved = self._strip_prefix(model or self._default_model)
        sanitized = self._sanitize_messages(self._sanitize_empty_content(messages))
        normalized = self._normalize_tool_ids_in_messages(sanitized)

        kwargs: dict[str, Any] = {
            "model": resolved,
            "messages": normalized,
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = self._map_tool_choice(tool_choice)

        return kwargs

    # ------------------------------------------------------------------
    # Non-streaming
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,  # noqa: ARG002 — interface conformance
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """Send a chat completion request via the Mistral SDK.

        Args:
            messages: List of message dicts (OpenAI format).
            tools: Optional tool definitions.
            model: Model identifier.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            reasoning_effort: Unused by Mistral (interface conformance).
            tool_choice: Tool selection mode.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        kwargs = self._build_kwargs(
            messages, tools, model, max_tokens, temperature, reasoning_effort, tool_choice,
        )
        try:
            response = await self._client.chat.complete_async(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            return _handle_error(e)

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str = "auto",
    ) -> AsyncIterator[StreamChunk]:
        """Stream chat completion via the Mistral SDK.

        Yields text deltas and a final chunk with tool calls, usage, and finish reason.

        Yields:
            StreamChunk with incremental deltas and final metadata.
        """
        kwargs = self._build_kwargs(
            messages, tools, model, max_tokens, temperature, reasoning_effort, tool_choice,
        )
        try:
            stream = await self._client.chat.stream_async(**kwargs)
        except Exception as e:
            resp = _handle_error(e)
            yield StreamChunk(
                delta=resp.content or "",
                finish_reason="error",
                error_code=resp.error_code,
            )
            return

        accumulated_tool_calls: dict[int, dict[str, str]] = {}

        async for event in stream:
            # Mistral stream events have an extra .data wrapper.
            chunk = getattr(event, "data", event)
            if not chunk or not getattr(chunk, "choices", None):
                continue

            delta = chunk.choices[0].delta
            finish = chunk.choices[0].finish_reason

            # Yield text deltas.
            content = getattr(delta, "content", None)
            if content:
                yield StreamChunk(delta=content)

            # Accumulate tool call deltas.
            tool_calls = getattr(delta, "tool_calls", None)
            if tool_calls:
                for tc_delta in tool_calls:
                    idx = getattr(tc_delta, "index", 0) or 0
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {"name": "", "arguments": ""}
                    fn = getattr(tc_delta, "function", None)
                    if fn and getattr(fn, "name", None):
                        accumulated_tool_calls[idx]["name"] = fn.name
                    if fn and getattr(fn, "arguments", None):
                        accumulated_tool_calls[idx]["arguments"] += fn.arguments

            # Final chunk.
            if finish:
                final_tool_calls = None
                if accumulated_tool_calls:
                    final_tool_calls = [
                        ToolCallRequest(
                            id=short_tool_id(),
                            name=tc["name"],
                            arguments=json_repair.loads(tc["arguments"]) if tc["arguments"] else {},
                        )
                        for tc in accumulated_tool_calls.values()
                    ]

                usage = {}
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage:
                    usage = {
                        "prompt_tokens": getattr(chunk_usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(chunk_usage, "completion_tokens", 0) or 0,
                        "total_tokens": getattr(chunk_usage, "total_tokens", 0) or 0,
                    }

                yield StreamChunk(
                    finish_reason=finish,
                    tool_calls=final_tool_calls,
                    usage=usage or None,
                )
                return

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(response: Any) -> LLMResponse:
        """Parse Mistral ChatCompletionResponse into LLMResponse.

        Args:
            response: Mistral response object.

        Returns:
            LLMResponse with normalized content and metadata.
        """
        if not response or not response.choices:
            return LLMResponse(content=None, finish_reason="error", error_code="bad_request")

        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ToolCallRequest] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                fn = tc.function
                args = fn.arguments
                if isinstance(args, str):
                    args = json_repair.loads(args)
                tool_calls.append(ToolCallRequest(
                    id=short_tool_id(),
                    name=fn.name,
                    arguments=args if isinstance(args, dict) else {},
                ))

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
                "total_tokens": response.usage.total_tokens or 0,
            }

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )

    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        return self._default_model


# ======================================================================
# Module-level helpers
# ======================================================================


def _handle_error(exc: Exception) -> LLMResponse:
    """Classify a Mistral SDK exception into an LLMResponse with error_code."""
    from velo.providers.errors import classify_error

    error_msg = str(exc)
    code = classify_error(error_msg)

    logger.warning("mistral.request_failed: {}", error_msg[:200])
    return LLMResponse(
        content=f"Error calling Mistral: {error_msg}",
        finish_reason="error",
        error_code=code,
    )
