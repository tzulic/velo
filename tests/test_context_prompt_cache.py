"""Tests for cache-friendly prompt construction."""

from __future__ import annotations

import datetime as datetime_module
from datetime import datetime as real_datetime
from importlib.resources import files as pkg_files
from pathlib import Path

import pytest

from velo.agent.context import ContextBuilder


class _FakeDatetime(real_datetime):
    current = real_datetime(2026, 2, 24, 13, 59)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return cls.current


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


def test_bootstrap_files_are_backed_by_templates() -> None:
    template_dir = pkg_files("velo") / "templates"

    for filename in ContextBuilder.BOOTSTRAP_FILES:
        assert (template_dir / filename).is_file(), f"missing bootstrap template: {filename}"


@pytest.mark.asyncio
async def test_system_prompt_stays_stable_when_clock_changes(tmp_path, monkeypatch) -> None:
    """System prompt should not change just because wall clock minute changes."""
    monkeypatch.setattr(datetime_module, "datetime", _FakeDatetime)

    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    _FakeDatetime.current = real_datetime(2026, 2, 24, 13, 59)
    prompt1 = await builder.build_system_prompt()

    _FakeDatetime.current = real_datetime(2026, 2, 24, 14, 0)
    prompt2 = await builder.build_system_prompt()

    assert prompt1 == prompt2


@pytest.mark.asyncio
async def test_runtime_context_is_separate_untrusted_user_message(tmp_path) -> None:
    """Runtime metadata should be merged with the user message."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = await builder.build_messages(
        history=[],
        current_message="Return exactly: OK",
        channel="cli",
        chat_id="direct",
    )

    assert messages[0]["role"] == "system"
    assert "## Current Session" not in messages[0]["content"]

    # Runtime context is now merged with user message into a single message
    assert messages[-1]["role"] == "user"
    user_content = messages[-1]["content"]
    assert isinstance(user_content, str)
    assert ContextBuilder._RUNTIME_CONTEXT_TAG in user_content
    assert "Current Time:" in user_content
    assert "Channel: cli" in user_content
    assert "Chat ID: direct" in user_content
    assert "Return exactly: OK" in user_content


@pytest.mark.asyncio
async def test_system_prompt_cached_across_calls(tmp_path) -> None:
    """System prompt should be identical object on repeated calls (cache hit)."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt1 = await builder.build_system_prompt()
    prompt2 = await builder.build_system_prompt()

    assert prompt1 is prompt2  # Same object identity = cache hit


@pytest.mark.asyncio
async def test_cache_invalidation_resets(tmp_path) -> None:
    """After invalidation, the prompt is rebuilt (different object)."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    prompt1 = await builder.build_system_prompt()
    builder.invalidate_prompt_cache()
    prompt2 = await builder.build_system_prompt()

    # Content should be the same, but it's a freshly built string
    assert prompt1 == prompt2
    assert prompt1 is not prompt2


@pytest.mark.asyncio
async def test_honcho_not_in_system_prompt(tmp_path) -> None:
    """Honcho context should NOT appear in the system prompt (it goes in runtime context)."""
    from unittest.mock import MagicMock

    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    mock_honcho = MagicMock()
    mock_honcho.get_prefetched_context.return_value = "User likes cats"
    builder.set_honcho(mock_honcho)

    prompt = await builder.build_system_prompt()
    assert "User likes cats" not in prompt
    assert "Honcho" not in prompt


@pytest.mark.asyncio
async def test_honcho_context_in_user_message(tmp_path) -> None:
    """Honcho context should appear in the runtime context block of the user message."""
    from unittest.mock import MagicMock

    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    mock_honcho = MagicMock()
    mock_honcho.get_prefetched_context.return_value = "User likes cats"
    builder.set_honcho(mock_honcho)

    messages = await builder.build_messages(
        history=[],
        current_message="Hello",
        channel="cli",
        chat_id="direct",
    )

    user_content = messages[-1]["content"]
    assert "User likes cats" in user_content
    assert ContextBuilder._RUNTIME_END_TAG in user_content


@pytest.mark.asyncio
async def test_runtime_end_tag_present(tmp_path) -> None:
    """Runtime context block should end with the end tag marker."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = await builder.build_messages(
        history=[],
        current_message="Test",
        channel="cli",
        chat_id="direct",
    )

    user_content = messages[-1]["content"]
    assert ContextBuilder._RUNTIME_END_TAG in user_content
