"""Base LLM provider interface."""

import secrets
import string
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

_ALNUM = string.ascii_letters + string.digits


def short_tool_id() -> str:
    """Generate a 9-char alphanumeric ID compatible with all providers (incl. Mistral)."""
    return "".join(secrets.choice(_ALNUM) for _ in range(9))


def strip_model_prefix(model: str, *prefixes: str) -> str:
    """Strip known provider prefixes from a model name.

    Args:
        model: Model identifier (e.g. 'anthropic/claude-sonnet-4-6').
        *prefixes: Prefixes to strip (e.g. 'anthropic/').

    Returns:
        str: Model name with prefix removed if matched.
    """
    for prefix in prefixes:
        if model.startswith(prefix):
            return model[len(prefix) :]
    return model


@dataclass
class ToolCallRequest:
    """A tool call request from the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    reasoning_content: str | None = None  # Kimi, DeepSeek-R1 etc.
    thinking_blocks: list[dict] | None = None  # Anthropic extended thinking
    error_code: str | None = None  # Classified error code (see providers/errors.py)

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response."""

    delta: str = ""  # Incremental text
    tool_calls: list[ToolCallRequest] | None = None  # Complete tool calls (final chunk only)
    finish_reason: str | None = None  # Set on final chunk
    usage: dict[str, int] | None = None  # Set on final chunk
    reasoning_content: str | None = None
    error_code: str | None = None  # Classified error code (on error chunks)


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    Implementations should handle the specifics of each provider's API
    while maintaining a consistent interface.
    """

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base

    @staticmethod
    def _sanitize_empty_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace empty text content that causes provider 400 errors.

        Empty content can appear when MCP tools return nothing. Most providers
        reject empty-string content or empty text blocks in list content.
        """
        result: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")

            if isinstance(content, str) and not content:
                clean = dict(msg)
                clean["content"] = (
                    None
                    if (msg.get("role") == "assistant" and msg.get("tool_calls"))
                    else "(empty)"
                )
                result.append(clean)
                continue

            if isinstance(content, list):
                filtered = [
                    item
                    for item in content
                    if not (
                        isinstance(item, dict)
                        and item.get("type") in ("text", "input_text", "output_text")
                        and not item.get("text")
                    )
                ]
                if len(filtered) != len(content):
                    clean = dict(msg)
                    if filtered:
                        clean["content"] = filtered
                    elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                        clean["content"] = None
                    else:
                        clean["content"] = "(empty)"
                    result.append(clean)
                    continue

            if isinstance(content, dict):
                clean = dict(msg)
                clean["content"] = [content]
                result.append(clean)
                continue

            result.append(msg)
        return result

    @staticmethod
    def _sanitize_request_messages(
        messages: list[dict[str, Any]],
        allowed_keys: frozenset[str],
    ) -> list[dict[str, Any]]:
        """Keep only provider-safe message keys and normalize assistant content."""
        sanitized = []
        for msg in messages:
            clean = {k: v for k, v in msg.items() if k in allowed_keys}
            if clean.get("role") == "assistant" and "content" not in clean:
                clean["content"] = None
            sanitized.append(clean)
        return sanitized

    @abstractmethod
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
        """
        Send a chat completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions.
            model: Model identifier (provider-specific).
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        pass

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
        """Stream chat completion. Default fallback calls chat() and yields one chunk.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions.
            model: Model identifier.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            reasoning_effort: Optional reasoning effort level.
            tool_choice: Tool selection mode ("auto", "required", "none").

        Yields:
            StreamChunk with incremental text or final metadata.
        """
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
            usage=response.usage,
            reasoning_content=response.reasoning_content,
        )

    @abstractmethod
    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        pass
