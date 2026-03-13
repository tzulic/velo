"""Tests for Phase 2 Stream B: Velo model routing and budget errors."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from velo.agent.loop import AgentLoop
from velo.bus.queue import MessageBus
from velo.providers.errors import RETRYABLE_ERRORS, classify_error


@pytest.fixture
def make_loop():
    """Factory fixture for creating a minimal AgentLoop for testing."""

    def _factory(**overrides: Any) -> AgentLoop:
        bus = MessageBus()
        provider = AsyncMock()
        provider.get_default_model = lambda: "test-model"
        workspace = overrides.pop("workspace", Path("/tmp/test-workspace"))
        return AgentLoop(
            bus=bus,
            provider=provider,
            workspace=workspace,
            **overrides,
        )

    return _factory


class TestBudgetExceededClassification:
    """Tests for budget_exceeded error classification."""

    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("budget_exceeded: monthly limit reached", "budget_exceeded"),
            ("Your monthly budget has been exhausted", "budget_exceeded"),
        ],
    )
    def test_budget_exceeded_classified(self, msg: str, expected: str) -> None:
        """Budget exceeded patterns are classified correctly."""
        assert classify_error(msg) == expected

    def test_budget_exceeded_not_retryable(self) -> None:
        """budget_exceeded is NOT in RETRYABLE_ERRORS — budget won't reset during retries."""
        assert "budget_exceeded" not in RETRYABLE_ERRORS

    def test_quota_still_matches_rate_limit(self) -> None:
        """Plain 'quota' without budget keywords still classifies as rate_limit."""
        assert classify_error("You have exceeded your quota") == "rate_limit"


class TestSubagentModelRouting:
    """Tests for subagent model routing via AgentLoop."""

    def test_subagent_uses_dedicated_model(self, make_loop) -> None:
        """When subagent_model is set, SubagentManager receives it instead of the main model."""
        loop = make_loop(model="anthropic/claude-sonnet-4-6", subagent_model="anthropic/claude-haiku-4-5")
        assert loop.subagents.model == "anthropic/claude-haiku-4-5"

    def test_subagent_falls_back_to_main_model(self, make_loop) -> None:
        """When subagent_model is None, SubagentManager uses the main model."""
        loop = make_loop(model="anthropic/claude-sonnet-4-6")
        assert loop.subagents.model == "anthropic/claude-sonnet-4-6"


class TestConfigSchemaSubagentModel:
    """Tests for subagent_model config field."""

    def test_subagent_model_default_none(self) -> None:
        """subagent_model defaults to None."""
        from velo.config.schema import AgentDefaults

        defaults = AgentDefaults()
        assert defaults.subagent_model is None

    def test_subagent_model_camel_case_serialization(self) -> None:
        """subagent_model serializes as 'subagentModel' in JSON."""
        from velo.config.schema import AgentDefaults

        defaults = AgentDefaults(subagent_model="anthropic/claude-haiku-4-5")
        dumped = defaults.model_dump(by_alias=True)
        assert "subagentModel" in dumped
        assert dumped["subagentModel"] == "anthropic/claude-haiku-4-5"
