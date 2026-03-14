"""LLM call helpers: retry, streaming, and context trimming."""

from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable

from loguru import logger

from velo.providers.base import LLMProvider, LLMResponse
from velo.providers.context_limits import estimate_tokens
from velo.providers.errors import RETRYABLE_ERRORS

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds

# Context trimming thresholds
PROACTIVE_TRIM_THRESHOLD = 0.90  # Trim when > 90% of context window
PROACTIVE_TRIM_TARGET = 0.70  # Trim down to 70%
REACTIVE_TRIM_TARGET = 0.50  # Aggressive trim on overflow error
COMPRESSION_THRESHOLD = 0.50  # Summarize at 50% context usage

# Streaming buffer size
STREAM_BUFFER_CHARS = 80  # Emit buffered text every N chars


async def chat_with_retry(provider: LLMProvider, **kwargs: Any) -> LLMResponse:
    """Call provider.chat() with exponential backoff for transient errors.

    Args:
        provider: The LLM provider to use.
        **kwargs: Forwarded to provider.chat().

    Returns:
        LLMResponse: The final response (success or non-retryable error).
    """
    response: LLMResponse | None = None
    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            delay = BASE_DELAY * (2 ** (attempt - 1)) * random.uniform(0.5, 1.0)
            logger.warning(
                "llm.retry_attempt: {} ({}/{}), backoff {:.1f}s",
                response.error_code if response else "unknown",  # type: ignore[union-attr]
                attempt,
                MAX_RETRIES,
                delay,
            )
            await asyncio.sleep(delay)
        response = await provider.chat(**kwargs)
        if response.finish_reason != "error":
            return response
        if response.error_code not in RETRYABLE_ERRORS:
            return response
    # Exhausted retries — return last error response.
    assert response is not None  # noqa: S101
    return response


async def chat_stream_to_response(
    provider: LLMProvider,
    on_progress: Callable[..., Awaitable[None]],
    **kwargs: Any,
) -> LLMResponse:
    """Stream LLM response, emitting text chunks via on_progress.

    Buffers text and emits on sentence boundaries or every STREAM_BUFFER_CHARS.
    Returns a reconstructed LLMResponse for message history.

    Args:
        provider: The LLM provider to use.
        on_progress: Callback for streaming text to the user.
        **kwargs: Forwarded to provider.chat_stream().

    Returns:
        LLMResponse: Reconstructed from accumulated stream data.
    """
    content_parts: list[str] = []
    buffer = ""
    tool_calls: list = []
    finish_reason = "stop"
    usage: dict[str, int] = {}
    reasoning_content: str | None = None
    error_code: str | None = None

    async for chunk in provider.chat_stream(**kwargs):
        if chunk.delta:
            content_parts.append(chunk.delta)
            buffer += chunk.delta
            # Emit on sentence boundaries or when buffer is large enough
            if len(buffer) >= STREAM_BUFFER_CHARS or buffer.rstrip().endswith(
                (".", "!", "?", "\n")
            ):
                await on_progress(buffer)
                buffer = ""
        if chunk.tool_calls:
            tool_calls = chunk.tool_calls
        if chunk.finish_reason:
            finish_reason = chunk.finish_reason
        if chunk.usage:
            usage = chunk.usage
        if chunk.reasoning_content:
            reasoning_content = chunk.reasoning_content
        if chunk.error_code:
            error_code = chunk.error_code

    # Flush remaining buffer
    if buffer:
        await on_progress(buffer)

    full_content = "".join(content_parts) or None

    return LLMResponse(
        content=full_content,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=usage,
        reasoning_content=reasoning_content,
        error_code=error_code,
    )


def _msg_tokens(msg: dict[str, Any]) -> int:
    """Estimate tokens for a single message (chars/4 heuristic)."""
    return estimate_tokens([msg])


def trim_to_budget(messages: list[dict[str, Any]], token_budget: int) -> list[dict[str, Any]]:
    """Trim messages to fit within a token budget.

    Preserves:
    - System message (index 0)
    - Tail: last user message + any trailing assistant/tool messages
    Removes oldest messages from the middle, maintaining tool call/result integrity.

    Args:
        messages: The full message list.
        token_budget: Maximum tokens to target.

    Returns:
        list: Trimmed message list.
    """
    total_tokens = estimate_tokens(messages)
    if total_tokens <= token_budget:
        return messages
    if len(messages) <= 2:
        return messages

    # Identify the protected tail: last user message + trailing msgs.
    tail_start = len(messages)
    for i in range(len(messages) - 1, 0, -1):
        tail_start = i
        if messages[i].get("role") == "user":
            break

    system = messages[:1]  # Always keep system
    middle = list(messages[1:tail_start])
    tail = list(messages[tail_start:])

    # Incremental token tracking to avoid O(n²) re-scanning.
    current_tokens = total_tokens
    idx = 0
    while idx < len(middle) and current_tokens > token_budget:
        removed = middle[idx]
        removed_tokens = _msg_tokens(removed)

        # Reason: If we removed an assistant message with tool_calls,
        # also remove subsequent tool result messages that reference those
        # call IDs — orphaned tool results cause provider 400 errors.
        if removed.get("role") == "assistant" and removed.get("tool_calls"):
            orphan_ids = {
                tc["id"]
                for tc in removed.get("tool_calls", [])
                if isinstance(tc, dict) and "id" in tc
            }
            # Mark current message for removal
            middle[idx] = None  # type: ignore[assignment]
            current_tokens -= removed_tokens
            # Also remove orphaned tool results
            for j in range(idx + 1, len(middle)):
                if middle[j] is None:
                    continue
                if (
                    middle[j].get("role") == "tool"  # type: ignore[union-attr]
                    and middle[j].get("tool_call_id") in orphan_ids
                ):  # type: ignore[union-attr]
                    current_tokens -= _msg_tokens(middle[j])  # type: ignore[arg-type]
                    middle[j] = None  # type: ignore[assignment]
        else:
            middle[idx] = None  # type: ignore[assignment]
            current_tokens -= removed_tokens
        idx += 1

    # Filter out removed (None) entries
    middle = [m for m in middle if m is not None]

    result = system + middle + tail
    trimmed_count = len(messages) - len(result)
    if trimmed_count > 0:
        logger.info(
            "context.trim_completed: removed {} messages, {} → {} est. tokens",
            trimmed_count,
            total_tokens,
            current_tokens,
        )
    return result
