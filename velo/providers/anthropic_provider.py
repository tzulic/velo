"""Native Anthropic provider — direct SDK calls, no LiteLLM."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import json_repair
from loguru import logger

from velo.providers.base import (
    LLMProvider,
    LLMResponse,
    StreamChunk,
    ToolCallRequest,
    strip_model_prefix,
)

# Stop-reason → finish_reason mapping.
_STOP_REASON_MAP = {
    "end_turn": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
    "stop_sequence": "stop",
}

# Effort → (output_config effort, budget_tokens for older models).
_EFFORT_MAP: dict[str, tuple[str, int]] = {
    "xhigh": ("max", 32768),
    "high": ("high", 16384),
    "medium": ("medium", 8192),
    "low": ("low", 4096),
}


class AnthropicProvider(LLMProvider):
    """LLM provider using the native Anthropic SDK.

    Supports prompt caching, extended thinking (adaptive on Claude 4.6,
    budget-based on older models), and streaming via messages.stream().
    """

    def __init__(
        self,
        api_key: str,
        api_base: str | None = None,
        default_model: str = "claude-sonnet-4-6",
    ):
        super().__init__(api_key, api_base)
        from anthropic import AsyncAnthropic

        self._default_model = default_model
        self._is_oauth = "sk-ant-oat" in api_key

        # Reason: OAuth tokens (from Claude Max) require specific beta headers
        # to authenticate against the Anthropic API.
        betas = ["interleaved-thinking-2025-05-14"]
        if self._is_oauth:
            betas = ["claude-code-20250219", "oauth-2025-04-20"] + betas

        client_kwargs: dict[str, Any] = {
            "base_url": api_base or None,
            "timeout": httpx.Timeout(timeout=900.0, connect=10.0),
            "default_headers": {"anthropic-beta": ",".join(betas)},
        }
        if self._is_oauth:
            client_kwargs["auth_token"] = api_key
        else:
            client_kwargs["api_key"] = api_key

        self._client = AsyncAnthropic(**client_kwargs)

    # ------------------------------------------------------------------
    # Message conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Convert OpenAI-format messages to Anthropic format.

        Returns:
            tuple: (system_blocks, converted_messages) where system_blocks are
            extracted system message content blocks and converted_messages are
            user/assistant messages in Anthropic format.
        """
        system_blocks: list[dict[str, Any]] = []
        converted: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "")

            if role == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    system_blocks.append({"type": "text", "text": content})
                elif isinstance(content, list):
                    system_blocks.extend(content)

            elif role == "assistant":
                blocks = _build_assistant_blocks(msg)
                if blocks:
                    converted.append({"role": "assistant", "content": blocks})

            elif role == "tool":
                # Tool results → user message with tool_result type.
                content = msg.get("content", "")
                if not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False) if content else "(empty)"
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id", ""),
                                "content": content or "(empty)",
                            }
                        ],
                    }
                )

            elif role == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    converted.append({"role": "user", "content": content or "(empty)"})
                elif isinstance(content, list):
                    converted.append({"role": "user", "content": content})
                else:
                    converted.append({"role": "user", "content": "(empty)"})

        # Enforce role alternation by merging consecutive same-role messages.
        merged = _merge_consecutive_roles(converted)
        return system_blocks, merged

    # ------------------------------------------------------------------
    # Tool conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI function-calling tool schemas to Anthropic format.

        Args:
            tools: List of OpenAI-format tool definitions.

        Returns:
            list: Anthropic-format tool definitions with name, description, input_schema.
        """
        result: list[dict[str, Any]] = []
        for tool in tools:
            fn = tool.get("function", tool) if tool.get("type") == "function" else tool
            name = fn.get("name")
            if not name:
                continue
            result.append(
                {
                    "name": name,
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return result

    @staticmethod
    def _map_tool_choice(
        tool_choice: str,
        has_tools: bool,
    ) -> tuple[dict[str, str] | None, bool]:
        """Map OpenAI tool_choice to Anthropic format.

        Returns:
            tuple: (anthropic_tool_choice, should_include_tools).
        """
        if tool_choice == "none" or not has_tools:
            return None, False
        if tool_choice == "required":
            return {"type": "any"}, True
        return {"type": "auto"}, True

    # ------------------------------------------------------------------
    # Prompt caching
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_cache_control(
        system_blocks: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Inject cache_control markers on last system block and last tool.

        Returns:
            tuple: (updated_system_blocks, updated_tools).
        """
        new_system = list(system_blocks)
        if new_system:
            new_system[-1] = {**new_system[-1], "cache_control": {"type": "ephemeral"}}

        new_tools = tools
        if tools:
            new_tools = list(tools)
            new_tools[-1] = {**new_tools[-1], "cache_control": {"type": "ephemeral"}}

        return new_system, new_tools

    # ------------------------------------------------------------------
    # Extended thinking
    # ------------------------------------------------------------------

    @staticmethod
    def _build_thinking_params(
        model: str,
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        """Build thinking/effort parameters based on model and effort level.

        Args:
            model: Model identifier.
            reasoning_effort: Effort level (low/medium/high/xhigh) or None.

        Returns:
            dict: Extra kwargs to pass to the API (thinking, output_config, temperature).
        """
        if not reasoning_effort:
            return {}

        effort_key = reasoning_effort.lower()
        effort_cfg = _EFFORT_MAP.get(effort_key, _EFFORT_MAP["medium"])

        # Claude 4.6 models support adaptive thinking with effort levels.
        model_lower = model.lower()
        if "4.6" in model_lower or "4-6" in model_lower:
            return {
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": effort_cfg[0]},
            }

        # Older Claude models use budget-based thinking.
        return {
            "thinking": {"type": "enabled", "budget_tokens": effort_cfg[1]},
            "temperature": 1,  # Required for thinking mode on older models.
        }

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_prefix(model: str) -> str:
        """Strip provider prefix from model name (e.g. 'anthropic/claude-...' → 'claude-...')."""
        return strip_model_prefix(model, "anthropic/")

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
        """Build kwargs shared between chat() and chat_stream().

        Returns:
            dict: Keyword arguments for the Anthropic messages API.
        """
        resolved_model = self._strip_prefix(model or self._default_model)
        sanitized = self._sanitize_empty_content(messages)
        system_blocks, converted = self._convert_messages(sanitized)

        # Convert and filter tools.
        anthropic_tools: list[dict[str, Any]] | None = None
        if tools:
            anthropic_tools = self._convert_tools(tools)

        # Apply prompt caching.
        system_blocks, anthropic_tools = self._apply_cache_control(system_blocks, anthropic_tools)

        # Tool choice mapping.
        tc_value, include_tools = self._map_tool_choice(
            tool_choice,
            bool(anthropic_tools),
        )

        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "messages": converted,
            "max_tokens": max(1, max_tokens),
        }

        if system_blocks:
            kwargs["system"] = system_blocks

        # Thinking params may override temperature.
        thinking_params = self._build_thinking_params(resolved_model, reasoning_effort)
        if thinking_params:
            kwargs.update(thinking_params)
        else:
            kwargs["temperature"] = temperature

        if include_tools and anthropic_tools:
            kwargs["tools"] = anthropic_tools
            if tc_value:
                kwargs["tool_choice"] = tc_value

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
        reasoning_effort: str | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        """Send a chat completion request via the Anthropic SDK.

        Args:
            messages: List of message dicts (OpenAI format).
            tools: Optional tool definitions (OpenAI format).
            model: Model identifier (e.g. 'claude-sonnet-4-6').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            reasoning_effort: Optional thinking effort level.
            tool_choice: Tool selection mode.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        kwargs = self._build_kwargs(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
        )
        try:
            response = await self._client.messages.create(**kwargs)
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
        """Stream chat completion via the Anthropic SDK.

        Yields text deltas incrementally and a final chunk with tool calls,
        thinking blocks, usage, and finish reason.

        Yields:
            StreamChunk with incremental deltas and final metadata.
        """
        kwargs = self._build_kwargs(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
        )
        try:
            async with self._client.messages.stream(**kwargs) as stream:
                thinking_parts: list[str] = []
                thinking_blocks: list[dict[str, Any]] = []
                current_tool: dict[str, Any] | None = None
                tool_input_json = ""
                completed_tools: list[ToolCallRequest] = []

                async for event in stream:
                    etype = getattr(event, "type", "")

                    if etype == "content_block_start":
                        block = event.content_block
                        if getattr(block, "type", "") == "tool_use":
                            current_tool = {
                                "id": block.id,
                                "name": block.name,
                            }
                            tool_input_json = ""

                    elif etype == "content_block_delta":
                        delta = event.delta
                        dtype = getattr(delta, "type", "")
                        if dtype == "text_delta":
                            yield StreamChunk(delta=delta.text)
                        elif dtype == "thinking_delta":
                            thinking_parts.append(delta.thinking)
                        elif dtype == "input_json_delta":
                            tool_input_json += delta.partial_json

                    elif etype == "content_block_stop":
                        if current_tool:
                            args = json_repair.loads(tool_input_json) if tool_input_json else {}
                            completed_tools.append(
                                ToolCallRequest(
                                    id=current_tool["id"],
                                    name=current_tool["name"],
                                    arguments=args if isinstance(args, dict) else {},
                                )
                            )
                            current_tool = None
                            tool_input_json = ""
                        # Finalize thinking block if we accumulated thinking text.
                        if thinking_parts:
                            thinking_blocks.append(
                                {
                                    "type": "thinking",
                                    "thinking": "".join(thinking_parts),
                                }
                            )
                            thinking_parts = []

                # Get final message for usage and stop reason.
                final = await stream.get_final_message()
                stop = _STOP_REASON_MAP.get(final.stop_reason or "", "stop")
                usage = _extract_usage(final)

                yield StreamChunk(
                    finish_reason=stop,
                    tool_calls=completed_tools or None,
                    usage=usage or None,
                    reasoning_content="".join(tb["thinking"] for tb in thinking_blocks) or None,
                )

        except Exception as e:
            # Streaming failed — fall back to non-streaming within same provider.
            logger.warning("provider.stream_fallback_triggered: {}", str(e)[:200])
            try:
                response = await self.chat(
                    messages=messages,
                    tools=tools,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    tool_choice=tool_choice,
                )
                yield StreamChunk(
                    delta=response.content or "",
                    tool_calls=response.tool_calls or None,
                    finish_reason=response.finish_reason,
                    usage=response.usage or None,
                    reasoning_content=response.reasoning_content,
                    error_code=response.error_code,
                )
            except Exception as fallback_err:
                resp = _handle_error(fallback_err)
                yield StreamChunk(
                    delta=resp.content or "",
                    finish_reason="error",
                    error_code=resp.error_code,
                )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(message: Any) -> LLMResponse:
        """Parse an Anthropic Message into LLMResponse.

        Args:
            message: Anthropic Message object.

        Returns:
            LLMResponse with normalized content, tool calls, and metadata.
        """
        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        thinking_blocks: list[dict[str, Any]] = []
        reasoning_parts: list[str] = []

        for block in message.content:
            btype = getattr(block, "type", "")
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "thinking":
                thinking_blocks.append(
                    {
                        "type": "thinking",
                        "thinking": block.thinking,
                        "signature": getattr(block, "signature", ""),
                    }
                )
                reasoning_parts.append(block.thinking)
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCallRequest(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        stop_reason = _STOP_REASON_MAP.get(message.stop_reason or "", "stop")
        usage = _extract_usage(message)

        return LLMResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            finish_reason=stop_reason,
            usage=usage,
            reasoning_content="\n".join(reasoning_parts) if reasoning_parts else None,
            thinking_blocks=thinking_blocks or None,
        )

    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        return self._default_model


# ======================================================================
# Module-level helpers (keep class body lean)
# ======================================================================


def _build_assistant_blocks(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """Build Anthropic content blocks from an OpenAI-format assistant message."""
    blocks: list[dict[str, Any]] = []

    # Preserve thinking blocks from previous turns.
    for tb in msg.get("thinking_blocks") or []:
        blocks.append(
            {
                "type": "thinking",
                "thinking": tb.get("thinking", ""),
                "signature": tb.get("signature", ""),
            }
        )

    # Text content.
    content = msg.get("content")
    if isinstance(content, str) and content:
        blocks.append({"type": "text", "text": content})
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                blocks.append({"type": "text", "text": item["text"]})

    # Tool calls → tool_use blocks.
    for tc in msg.get("tool_calls") or []:
        if isinstance(tc, dict):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = json_repair.loads(args) if args else {}
            blocks.append(
                {
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "input": args if isinstance(args, dict) else {},
                }
            )

    return blocks


def _merge_consecutive_roles(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge consecutive same-role messages to enforce Anthropic's alternation requirement."""
    if not messages:
        return []

    merged: list[dict[str, Any]] = []
    for msg in messages:
        if merged and merged[-1]["role"] == msg["role"]:
            prev = merged[-1]["content"]
            curr = msg["content"]
            # Normalize both to lists.
            if isinstance(prev, str):
                prev = [{"type": "text", "text": prev}]
            if isinstance(curr, str):
                curr = [{"type": "text", "text": curr}]
            if isinstance(prev, list) and isinstance(curr, list):
                merged[-1]["content"] = prev + curr
            else:
                merged.append(msg)
        else:
            merged.append(msg)

    return merged


def _extract_usage(message: Any) -> dict[str, int]:
    """Extract usage dict from an Anthropic Message."""
    usage = getattr(message, "usage", None)
    if not usage:
        return {}
    return {
        "prompt_tokens": getattr(usage, "input_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "output_tokens", 0) or 0,
        "total_tokens": (getattr(usage, "input_tokens", 0) or 0)
        + (getattr(usage, "output_tokens", 0) or 0),
    }


def _handle_error(exc: Exception) -> LLMResponse:
    """Classify an Anthropic SDK exception into an LLMResponse with error_code."""
    from anthropic import (
        APITimeoutError,
        AuthenticationError,
        BadRequestError,
        InternalServerError,
        RateLimitError,
    )

    from velo.providers.errors import classify_error

    error_msg = str(exc)
    code = "unknown"

    if isinstance(exc, RateLimitError):
        code = "rate_limit"
    elif isinstance(exc, AuthenticationError):
        code = "auth_error"
    elif isinstance(exc, BadRequestError):
        msg_lower = error_msg.lower()
        code = (
            "context_overflow"
            if ("context" in msg_lower or "token" in msg_lower)
            else "bad_request"
        )
    elif isinstance(exc, InternalServerError):
        code = "server_error"
    elif isinstance(exc, APITimeoutError):
        code = "timeout"
    else:
        # Fallback to string-based classification for codes not covered by
        # isinstance checks (e.g. budget_exceeded).
        code = classify_error(error_msg)

    logger.warning("anthropic.request_failed: {}", error_msg[:200])
    return LLMResponse(
        content=f"Error calling Anthropic: {error_msg}",
        finish_reason="error",
        error_code=code,
    )
