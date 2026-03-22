"""Tests for the PostTurnReviewer background skill review agent."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from velo.agent.review import PostTurnReviewer


def _make_reviewer(tmp_path):
    provider = MagicMock()
    response = MagicMock()
    response.has_tool_calls = False
    response.content = "No skill needed."
    provider.chat = AsyncMock(return_value=response)
    return PostTurnReviewer(provider=provider, workspace=tmp_path, model="test")


def test_maybe_review_below_threshold(tmp_path):
    reviewer = _make_reviewer(tmp_path)
    reviewer.maybe_review(["tool1", "tool2"], [], "test:1")
    assert len(reviewer._active_tasks) == 0


@pytest.mark.asyncio
async def test_maybe_review_above_threshold(tmp_path):
    reviewer = _make_reviewer(tmp_path)
    tools = [f"tool{i}" for i in range(6)]
    reviewer.maybe_review(tools, [], "test:1")
    assert len(reviewer._active_tasks) == 1
    # Clean up the spawned task
    await asyncio.gather(*list(reviewer._active_tasks), return_exceptions=True)


@pytest.mark.asyncio
async def test_review_runs_and_completes(tmp_path):
    reviewer = _make_reviewer(tmp_path)
    tools = [f"tool{i}" for i in range(6)]
    reviewer.maybe_review(tools, [{"role": "user", "content": "do stuff"}], "test:1")
    tasks = list(reviewer._active_tasks)  # capture before event loop clears
    assert len(tasks) == 1
    await asyncio.gather(*tasks, return_exceptions=True)
    reviewer._provider.chat.assert_called_once()


def test_summarize_tools(tmp_path):
    reviewer = _make_reviewer(tmp_path)
    result = reviewer._summarize_tools(["read_file", "write_file", "read_file"])
    assert "read_file: 2x" in result
    assert "write_file: 1x" in result


def test_list_existing_skills_empty(tmp_path):
    reviewer = _make_reviewer(tmp_path)
    result = reviewer._list_existing_skills()
    assert "no existing skills" in result


def test_list_existing_skills_found(tmp_path):
    reviewer = _make_reviewer(tmp_path)
    skill_dir = tmp_path / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---")
    result = reviewer._list_existing_skills()
    assert "my-skill" in result
