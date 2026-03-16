"""Tests for structured context compression."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from velo.agent.context_compressor import compress_context
from velo.providers.base import LLMProvider, LLMResponse


def _make_messages(n: int) -> list[dict]:
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"Message {i}"})
    return msgs


@pytest.mark.asyncio
async def test_protect_first_and_last_configurable():
    provider = AsyncMock(spec=LLMProvider)
    provider.chat = AsyncMock(return_value=LLMResponse(content="Summary text"))
    msgs = _make_messages(20)
    compressed, summary, _ = await compress_context(
        messages=msgs,
        provider=provider,
        model="test",
        context_window=100,
        threshold=0.01,
        protect_first=5,
        protect_last=6,
    )
    assert summary is not None
    assert len(compressed) <= 12


@pytest.mark.asyncio
async def test_summary_prompt_has_structured_sections():
    provider = AsyncMock(spec=LLMProvider)
    provider.chat = AsyncMock(return_value=LLMResponse(content="Summary"))
    msgs = _make_messages(20)
    await compress_context(
        messages=msgs,
        provider=provider,
        model="test",
        context_window=100,
        threshold=0.01,
    )
    call_args = provider.chat.call_args
    summary_messages = call_args.kwargs.get("messages") or call_args.args[0]
    system_content = summary_messages[0]["content"]
    assert "SESSION_INTENT" in system_content
    assert "USER_IDENTITY" in system_content
    assert "ARTIFACTS" in system_content
    assert "NEXT_STEPS" in system_content


@pytest.mark.asyncio
async def test_compress_with_provider_failure_returns_original():
    provider = AsyncMock(spec=LLMProvider)
    provider.chat = AsyncMock(side_effect=Exception("LLM down"))
    msgs = _make_messages(20)
    compressed, summary, _ = await compress_context(
        messages=msgs,
        provider=provider,
        model="test",
        context_window=100,
        threshold=0.01,
    )
    assert summary is None
    assert len(compressed) == 20
