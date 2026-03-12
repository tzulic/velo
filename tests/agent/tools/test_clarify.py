"""Tests for the ClarifyTool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from velo.agent.tools.clarify import ClarifyTool, MAX_CHOICES


@pytest.fixture
def mock_callback() -> AsyncMock:
    """A mock async callback that returns a fixed answer."""
    cb = AsyncMock(return_value="Option 1")
    return cb


@pytest.fixture
def clarify(mock_callback: AsyncMock) -> ClarifyTool:
    """ClarifyTool wired to the mock callback."""
    return ClarifyTool(mock_callback)


@pytest.mark.asyncio
class TestClarifyToolExpectedUse:
    """Expected use: valid questions are forwarded to callback."""

    async def test_open_ended_question(self, clarify: ClarifyTool, mock_callback: AsyncMock) -> None:
        """Open-ended question calls callback with no choices."""
        result = await clarify.execute(question="What is your preference?")
        mock_callback.assert_awaited_once_with("What is your preference?", None)
        data = json.loads(result)
        assert data["question"] == "What is your preference?"
        assert data["choices_offered"] is None
        assert data["user_response"] == "Option 1"

    async def test_multiple_choice_question(self, clarify: ClarifyTool, mock_callback: AsyncMock) -> None:
        """Multiple-choice question passes choices to callback."""
        choices = ["Python", "JavaScript", "Go"]
        result = await clarify.execute(question="Pick a language", choices=choices)
        mock_callback.assert_awaited_once_with("Pick a language", choices)
        data = json.loads(result)
        assert data["choices_offered"] == choices

    async def test_result_is_valid_json(self, clarify: ClarifyTool) -> None:
        """Execute always returns a valid JSON string."""
        result = await clarify.execute(question="Hello?")
        data = json.loads(result)
        assert isinstance(data, dict)


@pytest.mark.asyncio
class TestClarifyToolEdgeCases:
    """Edge cases: choices truncation, whitespace stripping."""

    async def test_choices_capped_at_max(self, mock_callback: AsyncMock) -> None:
        """More than MAX_CHOICES choices are silently truncated."""
        callback = AsyncMock(return_value="1")
        tool = ClarifyTool(callback)
        too_many = [f"Option {i}" for i in range(MAX_CHOICES + 3)]
        result = await tool.execute(question="Pick one", choices=too_many)
        data = json.loads(result)
        assert len(data["choices_offered"]) == MAX_CHOICES

    async def test_empty_choices_treated_as_open_ended(self, mock_callback: AsyncMock) -> None:
        """Empty choices list is normalised to None (open-ended)."""
        callback = AsyncMock(return_value="free text")
        tool = ClarifyTool(callback)
        result = await tool.execute(question="Anything?", choices=[])
        data = json.loads(result)
        assert data["choices_offered"] is None

    async def test_whitespace_only_choices_stripped(self, mock_callback: AsyncMock) -> None:
        """Choices containing only whitespace are dropped."""
        callback = AsyncMock(return_value="real")
        tool = ClarifyTool(callback)
        result = await tool.execute(question="Q", choices=["  ", "Real option", ""])
        data = json.loads(result)
        assert data["choices_offered"] == ["Real option"]

    async def test_user_response_stripped(self, mock_callback: AsyncMock) -> None:
        """Trailing whitespace in user response is stripped."""
        callback = AsyncMock(return_value="  answer  ")
        tool = ClarifyTool(callback)
        result = await tool.execute(question="Q?")
        data = json.loads(result)
        assert data["user_response"] == "answer"


@pytest.mark.asyncio
class TestClarifyToolFailureCases:
    """Failure cases: bad input, callback errors."""

    async def test_empty_question_returns_error_json(self, mock_callback: AsyncMock) -> None:
        """Empty question string returns error JSON, not an exception."""
        callback = AsyncMock(return_value="irrelevant")
        tool = ClarifyTool(callback)
        result = await tool.execute(question="")
        data = json.loads(result)
        assert "error" in data
        callback.assert_not_awaited()

    async def test_whitespace_question_returns_error_json(self, mock_callback: AsyncMock) -> None:
        """Whitespace-only question returns error JSON."""
        callback = AsyncMock(return_value="irrelevant")
        tool = ClarifyTool(callback)
        result = await tool.execute(question="   ")
        data = json.loads(result)
        assert "error" in data

    async def test_callback_exception_returns_error_json(self) -> None:
        """Callback raising an exception returns error JSON, not a crash."""
        callback = AsyncMock(side_effect=RuntimeError("input failed"))
        tool = ClarifyTool(callback)
        result = await tool.execute(question="What?")
        data = json.loads(result)
        assert "error" in data
        assert "input failed" in data["error"]
