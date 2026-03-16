"""Context compression: summarize middle messages to stay within context budget."""

from __future__ import annotations

from typing import Any

from loguru import logger

from velo.providers.base import LLMProvider
from velo.providers.context_limits import estimate_tokens

_SUMMARY_PROMPT = (
    "Create a structured handoff summary for the assistant to continue this conversation.\n"
    "Return the summary in these exact sections:\n\n"
    "SESSION_INTENT: What the user is trying to accomplish (1-2 sentences)\n\n"
    "USER_IDENTITY: Name, timezone, preferences, communication style (if shared)\n\n"
    "PROGRESS: Actions taken and their results (bullet points)\n\n"
    "KEY_DECISIONS: Decisions made and their reasoning (bullet points)\n\n"
    "ARTIFACTS: File paths, URLs, code snippets, and technical specifics referenced\n\n"
    "NEXT_STEPS: What remains to be done\n\n"
    "CONSTRAINTS: Requirements, limitations, or preferences the user stated\n\n"
    "Each section acts as a checklist — populate it or write 'None' if not applicable.\n"
    "Be factual and concise. Target ~500 tokens total."
)
_SUMMARY_CONTENT_TRUNCATE = 800  # Max chars per message in the summary prompt
_SUMMARY_MAX_TOKENS = 1024  # Max tokens for the summarization LLM call


def _sanitize_tool_pairs(
    messages: list[dict[str, Any]],
    keep_indices: set[int],
) -> list[dict[str, Any]]:
    """Remove messages not in keep_indices, ensuring no orphaned tool_call/result pairs.

    When an assistant message with tool_calls is removed, any subsequent tool
    result messages referencing those call IDs are also removed (and vice-versa).

    Args:
        messages: Full message list.
        keep_indices: Set of indices to keep.

    Returns:
        list[dict]: Filtered messages with tool-pair integrity preserved.
    """
    # Collect all tool_call IDs that are being kept.
    kept_call_ids: set[str] = set()
    for idx in keep_indices:
        msg = messages[idx]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg.get("tool_calls", []):
                if isinstance(tc, dict) and "id" in tc:
                    kept_call_ids.add(tc["id"])

    result: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        if idx in keep_indices:
            # Even kept messages must be checked: tool results whose
            # corresponding assistant tool_call was removed become orphans.
            if msg.get("role") == "tool" and msg.get("tool_call_id"):
                if msg["tool_call_id"] not in kept_call_ids:
                    continue
            result.append(msg)
    return result


def _build_summary_prompt(messages_to_summarize: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format messages into a summarization request for the LLM.

    Args:
        messages_to_summarize: The middle messages to be summarized.

    Returns:
        list[dict]: A two-message conversation: system instruction + user content.
    """
    lines: list[str] = []
    for msg in messages_to_summarize:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(str(item) for item in content)
        # Include tool call info if present.
        tool_info = ""
        if msg.get("tool_calls"):
            names = [
                tc.get("function", {}).get("name", "?")
                for tc in msg.get("tool_calls", [])
                if isinstance(tc, dict)
            ]
            tool_info = f" [tool_calls: {', '.join(names)}]"
        if msg.get("tool_call_id"):
            tool_info = f" [tool_result: {msg['tool_call_id'][:12]}...]"
        # Truncate long content for the summary prompt.
        if len(content) > _SUMMARY_CONTENT_TRUNCATE:
            content = content[:_SUMMARY_CONTENT_TRUNCATE] + "..."
        lines.append(f"[{role}]{tool_info}: {content}")

    conversation_text = "\n".join(lines)
    return [
        {"role": "system", "content": _SUMMARY_PROMPT},
        {"role": "user", "content": f"Conversation to summarize:\n\n{conversation_text}"},
    ]


async def compress_context(
    messages: list[dict[str, Any]],
    provider: LLMProvider,
    model: str,
    context_window: int,
    threshold: float = 0.50,
    protect_first: int = 3,
    protect_last: int = 4,
    est_tokens: int | None = None,
) -> tuple[list[dict[str, Any]], str | None, int]:
    """Compress conversation context by summarizing middle messages.

    If the estimated token count of *messages* is below *context_window * threshold*,
    the messages are returned unchanged. Otherwise the middle messages (between
    the protected head and tail) are replaced by a single summary message
    produced by the LLM.

    Args:
        messages: Full message list for the agent loop.
        provider: LLM provider to use for generating the summary.
        model: Model identifier for the summarization call.
        context_window: Total context window size in tokens.
        threshold: Fraction of context_window that triggers compression.
        protect_first: Number of leading messages to keep verbatim.
        protect_last: Number of trailing messages to keep verbatim.
        est_tokens: Pre-computed token estimate (avoids redundant scan).

    Returns:
        tuple: (compressed_messages, summary_text | None, est_tokens).
            summary_text is None when no compression was needed or when
            the LLM call failed. est_tokens is the post-compression estimate.
    """
    est = est_tokens if est_tokens is not None else estimate_tokens(messages)
    budget = int(context_window * threshold)

    if est <= budget:
        return messages, None, est

    # Not enough messages to compress.
    if len(messages) <= protect_first + protect_last:
        logger.debug(
            "context.compress_skipped: only {} messages, need {} protected",
            len(messages),
            protect_first + protect_last,
        )
        return messages, None, est

    middle = messages[protect_first : len(messages) - protect_last]

    if not middle:
        return messages, None, est

    logger.info(
        "context.compress_started: est={} tokens, threshold={}, middle={} msgs",
        est,
        budget,
        len(middle),
    )

    # Build summarization prompt from the middle messages.
    summary_messages = _build_summary_prompt(middle)

    try:
        response = await provider.chat(
            messages=summary_messages,
            tools=None,
            model=model,
            max_tokens=_SUMMARY_MAX_TOKENS,
            temperature=0.3,
        )
        summary_text = response.content
        if not summary_text:
            logger.warning("context.compress_empty_response: LLM returned no content")
            return messages, None, est
    except Exception as exc:
        logger.warning("context.compress_failed: LLM error {}", exc)
        return messages, None, est

    # Sanitize tool pairs in the protected segments.
    keep_indices: set[int] = set(range(protect_first))
    keep_indices.update(range(len(messages) - protect_last, len(messages)))
    sanitized_kept = _sanitize_tool_pairs(messages, keep_indices)

    # Split sanitized output into head and tail. The sanitized list preserves
    # order, so head items come first; count how many survived orphan removal.
    head_count = sum(1 for i in range(protect_first) if i in keep_indices)
    sanitized_head = sanitized_kept[:head_count]
    sanitized_tail = sanitized_kept[head_count:]

    summary_msg: dict[str, Any] = {
        "role": "user",
        "content": f"[Context Summary] {summary_text}",
    }

    compressed = sanitized_head + [summary_msg] + sanitized_tail

    new_est = estimate_tokens(compressed)
    logger.info(
        "context.compress_completed: {} → {} msgs, {} → {} est. tokens",
        len(messages),
        len(compressed),
        est,
        new_est,
    )

    return compressed, summary_text, new_est
