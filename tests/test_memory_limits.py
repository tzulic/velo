"""Tests for memory char limits and usage indicators."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from velo.agent.memory import MemoryStore
from velo.providers.base import LLMResponse, ToolCallRequest


class TestMemoryContextUsageIndicators:
    """Tests for usage indicator formatting in get_memory_context()."""

    def test_usage_indicator_empty_memory(self, tmp_path: Path) -> None:
        """Empty memory returns empty string (no header shown)."""
        store = MemoryStore(tmp_path)
        result = store.get_memory_context(memory_limit=8000, user_limit=4000)
        assert result == ""

    def test_usage_indicator_with_memory_content(self, tmp_path: Path) -> None:
        """MEMORY.md content shows usage percentage and char counts."""
        store = MemoryStore(tmp_path)
        content = "# Memory\n\nUser prefers Python."
        store.write_long_term(content)

        result = store.get_memory_context(memory_limit=8000, user_limit=4000)
        char_count = len(content)
        pct = int(char_count * 100 / 8000)

        assert "MEMORY (agent notes)" in result
        assert f"{pct}%" in result
        assert f"{char_count:,}/8,000 chars" in result
        assert "═" in result

    def test_usage_indicator_with_user_profile(self, tmp_path: Path) -> None:
        """USER.md content shows user profile header and usage."""
        store = MemoryStore(tmp_path)
        profile = "# User Profile\n\nName: Alice. Timezone: UTC+1."
        store.write_user_profile(profile)

        result = store.get_memory_context(memory_limit=8000, user_limit=4000)
        char_count = len(profile)
        pct = int(char_count * 100 / 4000)

        assert "USER PROFILE" in result
        assert f"{pct}%" in result
        assert f"{char_count:,}/4,000 chars" in result

    def test_usage_indicator_both_files(self, tmp_path: Path) -> None:
        """Both MEMORY.md and USER.md shown with separate headers."""
        store = MemoryStore(tmp_path)
        store.write_long_term("# Memory\n\nAgent notes here.")
        store.write_user_profile("# User Profile\n\nAlice, UTC+1.")

        result = store.get_memory_context(memory_limit=8000, user_limit=4000)

        assert "MEMORY (agent notes)" in result
        assert "USER PROFILE" in result
        # Two separator blocks present
        assert result.count("══") >= 2

    def test_usage_indicator_zero_percent(self, tmp_path: Path) -> None:
        """Very small content shows 0%."""
        store = MemoryStore(tmp_path)
        store.write_long_term("x")  # 1 char out of 8000

        result = store.get_memory_context(memory_limit=8000)
        assert "0%" in result

    def test_large_limit_defaults(self, tmp_path: Path) -> None:
        """Default limits (8000/4000) are used when not specified."""
        store = MemoryStore(tmp_path)
        store.write_long_term("Some content.")

        result_default = store.get_memory_context()
        result_explicit = store.get_memory_context(memory_limit=8000, user_limit=4000)
        assert result_default == result_explicit


class TestConsolidationLimitPrompt:
    """Tests that memory limits are included in the consolidation LLM prompt."""

    @pytest.mark.asyncio
    async def test_memory_limit_in_consolidation_prompt(self, tmp_path: Path) -> None:
        """Consolidation prompt includes memory_limit and user_limit percentages."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        captured_prompt: list[str] = []

        async def fake_chat(**kwargs):
            msgs = kwargs.get("messages", [])
            for m in msgs:
                if m.get("role") == "user":
                    captured_prompt.append(m["content"])
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="save_memory",
                        arguments={
                            "history_entry": "[2026-01-01] Test.",
                            "memory_update": "# Memory\n\nTest fact.",
                        },
                    )
                ],
            )

        provider.chat = fake_chat

        session = MagicMock()
        session.messages = [
            {"role": "user", "content": f"msg{i}", "timestamp": "2026-01-01 00:00"}
            for i in range(60)
        ]
        session.last_consolidated = 0

        await store.consolidate(
            session, provider, "test-model", memory_window=50, memory_limit=8000, user_limit=4000
        )

        assert captured_prompt, "Expected at least one user message in prompt"
        prompt_text = captured_prompt[0]
        assert "8,000 char limit" in prompt_text
        assert "4,000 char limit" in prompt_text
        assert "TWO MEMORY TARGETS" in prompt_text

    @pytest.mark.asyncio
    async def test_compress_hint_injected_at_80_percent(self, tmp_path: Path) -> None:
        """Compress hint is injected when memory exceeds 80% of limit."""
        store = MemoryStore(tmp_path)
        # Write 6,600 chars to hit ~82.5% of 8,000
        large_content = "x" * 6600
        store.write_long_term(large_content)

        provider = AsyncMock()
        captured_prompt: list[str] = []

        async def fake_chat(**kwargs):
            msgs = kwargs.get("messages", [])
            for m in msgs:
                if m.get("role") == "user":
                    captured_prompt.append(m["content"])
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="save_memory",
                        arguments={
                            "history_entry": "[2026-01-01] Test.",
                            "memory_update": "compressed",
                        },
                    )
                ],
            )

        provider.chat = fake_chat

        session = MagicMock()
        session.messages = [
            {"role": "user", "content": f"msg{i}", "timestamp": "2026-01-01 00:00"}
            for i in range(60)
        ]
        session.last_consolidated = 0

        await store.consolidate(
            session, provider, "test-model", memory_window=50, memory_limit=8000, user_limit=4000
        )

        prompt_text = captured_prompt[0]
        assert "Compress aggressively" in prompt_text
        assert "MEMORY.md" in prompt_text

    @pytest.mark.asyncio
    async def test_no_compress_hint_below_80_percent(self, tmp_path: Path) -> None:
        """No compress hint when memory is below 80% of limit."""
        store = MemoryStore(tmp_path)
        # Write 4,000 chars = 50% of 8,000
        store.write_long_term("x" * 4000)

        provider = AsyncMock()
        captured_prompt: list[str] = []

        async def fake_chat(**kwargs):
            msgs = kwargs.get("messages", [])
            for m in msgs:
                if m.get("role") == "user":
                    captured_prompt.append(m["content"])
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="save_memory",
                        arguments={
                            "history_entry": "[2026-01-01] Test.",
                            "memory_update": "some update",
                        },
                    )
                ],
            )

        provider.chat = fake_chat

        session = MagicMock()
        session.messages = [
            {"role": "user", "content": f"msg{i}", "timestamp": "2026-01-01 00:00"}
            for i in range(60)
        ]
        session.last_consolidated = 0

        await store.consolidate(
            session, provider, "test-model", memory_window=50, memory_limit=8000, user_limit=4000
        )

        prompt_text = captured_prompt[0]
        assert "Compress aggressively" not in prompt_text
