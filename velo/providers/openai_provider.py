"""Native OpenAI-compatible provider — replaces LiteLLM for OpenAI, xAI, DeepSeek, Groq, etc."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import json_repair
from loguru import logger
from openai import AsyncOpenAI

from velo.providers.base import (
    LLMProvider,
    LLMResponse,
    StreamChunk,
    ToolCallRequest,
    short_tool_id,
    strip_model_prefix,
)

# Standard chat-completion message keys (OpenAI format).
_ALLOWED_MSG_KEYS = frozenset(
    {"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content"}
)

# Backend-specific defaults: (base_url, default_headers).
_BACKEND_DEFAULTS: dict[str, tuple[str | None, dict[str, str]]] = {
    "openai": (None, {}),
    "openrouter": (
        "https://openrouter.ai/api/v1",
        {"HTTP-Referer": "https://github.com/Volos-AI/velo", "X-OpenRouter-Title": "Velo"},
    ),
    "deepseek": ("https://api.deepseek.com", {}),
    "groq": ("https://api.groq.com/openai/v1", {}),
    "xai": ("https://api.x.ai/v1", {}),
    "vllm": (None, {}),
    "aihubmix": (None, {}),
    "siliconflow": ("https://api.siliconflow.cn/v1", {}),
    "volcengine": ("https://ark.cn-beijing.volces.com/api/v3", {}),
    "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", {}),
    "moonshot": ("https://api.moonshot.ai/v1", {}),
    "minimax": ("https://api.minimax.io/v1", {}),
    "zhipu": ("https://open.bigmodel.cn/api/paas/v4/", {}),
}

# Per-model parameter overrides (substring match).
_MODEL_OVERRIDES: tuple[tuple[str, dict[str, Any]], ...] = (("kimi-k2.5", {"temperature": 1.0}),)


class OpenAIProvider(LLMProvider):
    """OpenAI Chat Completions provider — works with any OpenAI-compatible API.

    One class handles OpenAI, OpenRouter, DeepSeek, Groq, xAI, vLLM,
    AiHubMix, SiliconFlow, VolcEngine, DashScope, Moonshot, MiniMax, and Zhipu
    via the ``backend`` parameter.
    """

    def __init__(
        self,
        api_key: str = "no-key",
        api_base: str | None = None,
        default_model: str = "gpt-5-mini",
        extra_headers: dict[str, str] | None = None,
        backend: str = "openai",
    ):
        super().__init__(api_key, api_base)
        self._default_model = default_model
        self._backend = backend

        # Resolve base URL and headers from backend defaults.
        default_base, default_headers = _BACKEND_DEFAULTS.get(backend, (None, {}))
        resolved_base = api_base or default_base
        merged_headers = {**default_headers, **(extra_headers or {})}

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=resolved_base,
            default_headers=merged_headers or None,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _strip_prefix(self, model: str) -> str:
        """Strip known provider prefixes from model name."""
        return strip_model_prefix(model, f"{self._backend}/", "openai/")

    @staticmethod
    def _extract_reasoning(message: Any) -> str | None:
        """Extract reasoning content from various provider formats.

        Different providers expose reasoning differently:
        - DeepSeek/Kimi: message.reasoning_content
        - OpenRouter: message.reasoning or message.reasoning_details
        """
        # DeepSeek / Kimi style.
        rc = getattr(message, "reasoning_content", None)
        if rc:
            return rc

        # OpenRouter style.
        reasoning = getattr(message, "reasoning", None)
        if reasoning:
            return reasoning

        # OpenRouter metadata list.
        details = getattr(message, "reasoning_details", None)
        if isinstance(details, list):
            parts = [str(d) for d in details if d]
            return "\n".join(parts) if parts else None

        return None

    @staticmethod
    def _apply_model_overrides(model: str, kwargs: dict[str, Any]) -> None:
        """Apply per-model parameter overrides."""
        model_lower = model.lower()
        for pattern, overrides in _MODEL_OVERRIDES:
            if pattern in model_lower:
                kwargs.update(overrides)
                return

    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Strip non-standard keys and ensure assistant messages have a content key."""
        return LLMProvider._sanitize_request_messages(messages, _ALLOWED_MSG_KEYS)

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
        """Send a chat completion request via the OpenAI SDK.

        Args:
            messages: List of message dicts (OpenAI format).
            tools: Optional tool definitions.
            model: Model identifier.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            reasoning_effort: Optional reasoning effort level.
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
            response = await self._client.chat.completions.create(**kwargs)
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
        """Stream chat completion via the OpenAI SDK.

        Yields text deltas and a final chunk with tool calls, usage, and finish reason.

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
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as e:
            resp = _handle_error(e)
            yield StreamChunk(
                delta=resp.content or "",
                finish_reason="error",
                error_code=resp.error_code,
            )
            return

        accumulated_tool_calls: dict[int, dict[str, str]] = {}
        reasoning_parts: list[str] = []
        final_usage: dict[str, int] = {}
        final_finish: str | None = None

        async for chunk in response:
            # Capture usage from any chunk (OpenAI sends it on a separate
            # usage-only chunk after the finish chunk).
            if hasattr(chunk, "usage") and chunk.usage:
                final_usage = {
                    "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(chunk.usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(chunk.usage, "total_tokens", 0) or 0,
                }

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            finish = chunk.choices[0].finish_reason

            # Yield text deltas.
            if delta.content:
                yield StreamChunk(delta=delta.content)

            # Accumulate reasoning content.
            reasoning_delta = getattr(delta, "reasoning_content", None)
            if reasoning_delta:
                reasoning_parts.append(reasoning_delta)

            # Accumulate tool call deltas.
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {"name": "", "arguments": ""}
                    if tc_delta.function and tc_delta.function.name:
                        accumulated_tool_calls[idx]["name"] = tc_delta.function.name
                    if tc_delta.function and tc_delta.function.arguments:
                        accumulated_tool_calls[idx]["arguments"] += tc_delta.function.arguments

            if finish:
                final_finish = finish

        # Emit final chunk after stream is exhausted (captures usage-only trailing chunk).
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

        yield StreamChunk(
            finish_reason=final_finish or "stop",
            tool_calls=final_tool_calls,
            usage=final_usage or None,
            reasoning_content="".join(reasoning_parts) or None,
        )

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
        """Build kwargs for chat.completions.create().

        Returns:
            dict: Keyword arguments for the OpenAI Chat Completions API.
        """
        resolved = self._strip_prefix(model or self._default_model)

        kwargs: dict[str, Any] = {
            "model": resolved,
            "messages": self._sanitize_messages(self._sanitize_empty_content(messages)),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }

        self._apply_model_overrides(resolved, kwargs)

        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        return kwargs

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse OpenAI ChatCompletion response into LLMResponse.

        Args:
            response: OpenAI ChatCompletion response object.

        Returns:
            LLMResponse with normalized content and metadata.
        """
        choice = response.choices[0]
        message = choice.message
        content = message.content

        # Merge tool calls from all choices (e.g. GitHub Copilot splits them).
        raw_tool_calls: list[Any] = []
        finish_reason = choice.finish_reason
        for ch in response.choices:
            msg = ch.message
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                raw_tool_calls.extend(msg.tool_calls)
                if ch.finish_reason in ("tool_calls", "stop"):
                    finish_reason = ch.finish_reason
            if not content and msg.content:
                content = msg.content

        tool_calls = []
        for tc in raw_tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                args = json_repair.loads(args)
            tool_calls.append(
                ToolCallRequest(
                    id=tc.id or short_tool_id(),
                    name=tc.function.name,
                    arguments=args if isinstance(args, dict) else {},
                )
            )

        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
                "total_tokens": response.usage.total_tokens or 0,
            }

        reasoning_content = self._extract_reasoning(message)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason or "stop",
            usage=usage,
            reasoning_content=reasoning_content,
        )

    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        return self._default_model


# ======================================================================
# Module-level helpers
# ======================================================================


def _handle_error(exc: Exception) -> LLMResponse:
    """Classify an OpenAI SDK exception into an LLMResponse with error_code."""
    from openai import (
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

    logger.warning("openai.request_failed: {}", error_msg[:200])
    return LLMResponse(
        content=f"Error calling LLM: {error_msg}",
        finish_reason="error",
        error_code=code,
    )
