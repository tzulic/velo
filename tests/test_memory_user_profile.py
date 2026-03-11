"""Tests for USER.md user profile management in MemoryStore."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from velo.agent.memory import MemoryStore
from velo.providers.base import LLMResponse, ToolCallRequest


class TestReadWriteUserProfile:
    """Tests for read_user_profile() and write_user_profile()."""

    def test_read_user_profile_empty_if_missing(self, tmp_path: Path) -> None:
        """read_user_profile returns empty string when USER.md does not exist."""
        store = MemoryStore(tmp_path)
        assert store.read_user_profile() == ""

    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        """Writing and reading USER.md returns the same content."""
        store = MemoryStore(tmp_path)
        content = "# User Profile\n\nAlice. Timezone: UTC+2. Prefers concise replies."
        result = store.write_user_profile(content)
        assert result is True
        assert store.read_user_profile() == content

    def test_user_file_path_is_in_memory_dir(self, tmp_path: Path) -> None:
        """user_file is located at memory/USER.md."""
        store = MemoryStore(tmp_path)
        assert store.user_file == tmp_path / "memory" / "USER.md"

    def test_overwrite_user_profile(self, tmp_path: Path) -> None:
        """Writing twice replaces the previous content."""
        store = MemoryStore(tmp_path)
        store.write_user_profile("First version.")
        store.write_user_profile("Updated version.")
        assert store.read_user_profile() == "Updated version."

    def test_user_profile_separate_from_memory(self, tmp_path: Path) -> None:
        """USER.md and MEMORY.md are independent files."""
        store = MemoryStore(tmp_path)
        store.write_long_term("# Memory\n\nAgent notes.")
        store.write_user_profile("# User\n\nUser profile.")

        assert "Agent notes" in store.read_long_term()
        assert "User profile" in store.read_user_profile()
        assert store.memory_file != store.user_file


class TestConsolidationUserUpdate:
    """Tests that consolidate() writes user_update to USER.md."""

    @pytest.mark.asyncio
    async def test_user_update_written_to_user_file(self, tmp_path: Path) -> None:
        """consolidate() with user_update writes content to USER.md."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="save_memory",
                        arguments={
                            "history_entry": "[2026-01-01 10:00] User introduced herself.",
                            "memory_update": "# Memory\n\nProject is a FastAPI app.",
                            "user_update": "# User Profile\n\nName: Alice. Timezone: UTC+2.",
                        },
                    )
                ],
            )
        )

        session = _make_session(60)
        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is True
        assert store.user_file.exists()
        assert "Alice" in store.user_file.read_text()
        assert "UTC+2" in store.user_file.read_text()

    @pytest.mark.asyncio
    async def test_user_update_optional_field(self, tmp_path: Path) -> None:
        """consolidate() works without user_update — USER.md not created."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="save_memory",
                        arguments={
                            "history_entry": "[2026-01-01 10:00] Brief session.",
                            "memory_update": "# Memory\n\nNo new user info.",
                            # No user_update field
                        },
                    )
                ],
            )
        )

        session = _make_session(60)
        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is True
        assert not store.user_file.exists()

    @pytest.mark.asyncio
    async def test_user_update_unchanged_not_written(self, tmp_path: Path) -> None:
        """If user_update equals current USER.md content, no write occurs."""
        store = MemoryStore(tmp_path)
        existing_profile = "# User Profile\n\nAlice."
        store.write_user_profile(existing_profile)
        mtime_before = store.user_file.stat().st_mtime_ns

        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="save_memory",
                        arguments={
                            "history_entry": "[2026-01-01 10:00] No new user info.",
                            "memory_update": "# Memory\n\nSome agent note.",
                            # Return SAME content as current USER.md
                            "user_update": existing_profile,
                        },
                    )
                ],
            )
        )

        session = _make_session(60)
        await store.consolidate(session, provider, "test-model", memory_window=50)

        mtime_after = store.user_file.stat().st_mtime_ns
        assert mtime_before == mtime_after, "USER.md should not be rewritten when content unchanged"

    @pytest.mark.asyncio
    async def test_both_memory_and_user_written(self, tmp_path: Path) -> None:
        """consolidate() updates both MEMORY.md and USER.md in a single call."""
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="save_memory",
                        arguments={
                            "history_entry": "[2026-01-01 10:00] Good session.",
                            "memory_update": "# Memory\n\nProject uses PostgreSQL.",
                            "user_update": "# User Profile\n\nBob. Prefers dark mode.",
                        },
                    )
                ],
            )
        )

        session = _make_session(60)
        result = await store.consolidate(session, provider, "test-model", memory_window=50)

        assert result is True
        assert "PostgreSQL" in store.read_long_term()
        assert "Bob" in store.read_user_profile()


class TestSyncWorkspaceTemplates:
    """Tests that sync_workspace_templates creates memory/USER.md."""

    def test_user_md_created_in_memory_dir(self, tmp_path: Path) -> None:
        """sync_workspace_templates creates memory/USER.md alongside MEMORY.md."""
        from velo.utils.helpers import sync_workspace_templates

        sync_workspace_templates(tmp_path, silent=True)

        user_file = tmp_path / "memory" / "USER.md"
        assert user_file.exists(), "memory/USER.md should be created by sync_workspace_templates"

    def test_user_md_not_overwritten_if_exists(self, tmp_path: Path) -> None:
        """sync_workspace_templates does not overwrite existing memory/USER.md."""
        from velo.utils.helpers import sync_workspace_templates

        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        user_file = memory_dir / "USER.md"
        user_file.write_text("Existing user profile.", encoding="utf-8")

        sync_workspace_templates(tmp_path, silent=True)

        assert user_file.read_text(encoding="utf-8") == "Existing user profile."

    def test_memory_dir_created_for_user_md(self, tmp_path: Path) -> None:
        """sync_workspace_templates creates the memory/ directory if it doesn't exist."""
        from velo.utils.helpers import sync_workspace_templates

        sync_workspace_templates(tmp_path, silent=True)

        assert (tmp_path / "memory").is_dir()
        assert (tmp_path / "memory" / "USER.md").exists()


def _make_session(message_count: int = 60, memory_window: int = 50) -> MagicMock:
    """Create a mock session with messages."""
    session = MagicMock()
    session.messages = [
        {"role": "user", "content": f"msg{i}", "timestamp": "2026-01-01 00:00"}
        for i in range(message_count)
    ]
    session.last_consolidated = 0
    return session
