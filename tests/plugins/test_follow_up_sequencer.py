"""Tests for the follow-up-sequencer plugin."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Add the plugin directory to the path so we can import it directly.
# The plugin is loaded via importlib at runtime, not installed as a package.
sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[2]
        / "library"
        / "plugins"
        / "vertical"
        / "sdr"
        / "follow-up-sequencer"
    ),
)

# ruff: noqa: E402
from __init__ import (  # type: ignore[import]
    CancelSequenceTool,
    CreateSequenceTool,
    ListSequencesTool,
    PauseSequenceTool,
    ResumeSequenceTool,
    SequenceStore,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path, max_sequences: int = 5) -> SequenceStore:
    """Create a SequenceStore backed by a temp file.

    Args:
        tmp_path: Pytest tmp_path fixture directory.
        max_sequences: Maximum sequences allowed. Default 5 (small for limit tests).

    Returns:
        A fresh SequenceStore instance.
    """
    return SequenceStore(tmp_path / "sequences.json", max_sequences=max_sequences)


# ---------------------------------------------------------------------------
# SequenceStore: CRUD
# ---------------------------------------------------------------------------


class TestSequenceStoreCrud:
    """Tests for SequenceStore create, list, pause, resume, cancel."""

    def test_create_sequence(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        seq = store.create("John Smith", "john@example.com", "email")
        assert seq is not None
        assert seq["id"] == "SEQ-0001"
        assert seq["lead_name"] == "John Smith"
        assert seq["lead_contact"] == "john@example.com"
        assert seq["channel"] == "email"
        assert seq["status"] == "active"
        assert seq["current_step"] == 0

    def test_create_auto_increments_id(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        s1 = store.create("Lead 1", "lead1@test.com", "email")
        s2 = store.create("Lead 2", "lead2@test.com", "telegram")
        assert s1 is not None
        assert s2 is not None
        assert s1["id"] == "SEQ-0001"
        assert s2["id"] == "SEQ-0002"

    def test_create_default_steps(self, tmp_path: Path) -> None:
        """When no steps provided, uses the 3-step default sequence."""
        store = _make_store(tmp_path)
        seq = store.create("Jane Doe", "jane@test.com", "email")
        assert seq is not None
        assert len(seq["steps"]) == 3
        assert seq["steps"][0]["delay_days"] == 1
        assert seq["steps"][0]["message_hint"] == "Quick follow-up"
        assert seq["steps"][1]["delay_days"] == 3
        assert seq["steps"][2]["delay_days"] == 7

    def test_create_custom_steps_from_json(self, tmp_path: Path) -> None:
        """Custom steps parsed from JSON string."""
        store = _make_store(tmp_path)
        custom = json.dumps([
            {"delay_days": 2, "message_hint": "First touch"},
            {"delay_days": 5, "message_hint": "Second touch"},
        ])
        seq = store.create("Custom Lead", "custom@test.com", "whatsapp", steps=custom)
        assert seq is not None
        assert len(seq["steps"]) == 2
        assert seq["steps"][0]["delay_days"] == 2
        assert seq["steps"][1]["message_hint"] == "Second touch"

    def test_create_persists_to_disk(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Persisted", "p@test.com", "email")
        raw = json.loads((tmp_path / "sequences.json").read_text())
        assert len(raw) == 1
        assert raw[0]["lead_name"] == "Persisted"

    def test_list_sequences_all(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("A", "a@test.com", "email")
        store.create("B", "b@test.com", "telegram")
        result = store.list_sequences()
        assert len(result) == 2

    def test_list_sequences_by_status(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Active", "a@test.com", "email")
        store.create("Paused", "p@test.com", "email")
        store.pause("SEQ-0002")
        active = store.list_sequences(status="active")
        paused = store.list_sequences(status="paused")
        assert len(active) == 1
        assert len(paused) == 1
        assert paused[0]["lead_name"] == "Paused"

    def test_pause_sequence(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Lead", "l@test.com", "email")
        result = store.pause("SEQ-0001")
        assert result is True
        seq = store.get("SEQ-0001")
        assert seq is not None
        assert seq["status"] == "paused"

    def test_resume_sequence(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Lead", "l@test.com", "email")
        store.pause("SEQ-0001")
        result = store.resume("SEQ-0001")
        assert result is not None
        assert result["status"] == "active"
        # Reason: next_due_at should be recalculated from now
        assert result["next_due_at"] is not None

    def test_resume_non_paused_returns_none(self, tmp_path: Path) -> None:
        """Resuming an active (non-paused) sequence returns None."""
        store = _make_store(tmp_path)
        store.create("Lead", "l@test.com", "email")
        result = store.resume("SEQ-0001")
        assert result is None

    def test_cancel_sequence(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Lead", "l@test.com", "email")
        result = store.cancel("SEQ-0001")
        assert result is True
        seq = store.get("SEQ-0001")
        assert seq is not None
        assert seq["status"] == "cancelled"


# ---------------------------------------------------------------------------
# SequenceStore: step advancement and due detection
# ---------------------------------------------------------------------------


class TestSequenceStoreAdvancement:
    """Tests for advance_step and get_due."""

    def test_advance_step_marks_sent(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Lead", "l@test.com", "email")
        store.advance_step("SEQ-0001")
        seq = store.get("SEQ-0001")
        assert seq is not None
        assert seq["steps"][0]["sent_at"] is not None
        assert seq["current_step"] == 1

    def test_advance_last_step_completes(self, tmp_path: Path) -> None:
        """Advancing past the last step sets status to completed."""
        store = _make_store(tmp_path)
        custom = json.dumps([{"delay_days": 1, "message_hint": "Only step"}])
        store.create("Lead", "l@test.com", "email", steps=custom)
        store.advance_step("SEQ-0001")
        seq = store.get("SEQ-0001")
        assert seq is not None
        assert seq["status"] == "completed"
        assert seq["next_due_at"] is None

    def test_advance_calculates_next_due(self, tmp_path: Path) -> None:
        """After advancing, next_due_at is based on the next step's delay_days."""
        store = _make_store(tmp_path)
        store.create("Lead", "l@test.com", "email")
        before = datetime.now(timezone.utc)
        store.advance_step("SEQ-0001")
        seq = store.get("SEQ-0001")
        assert seq is not None
        next_due = datetime.fromisoformat(seq["next_due_at"])
        # Next step delay is 3 days
        expected_min = before + timedelta(days=3) - timedelta(seconds=5)
        expected_max = before + timedelta(days=3) + timedelta(seconds=5)
        assert expected_min <= next_due <= expected_max

    def test_get_due_returns_active_past_due(self, tmp_path: Path) -> None:
        """get_due returns sequences that are active and past their next_due_at."""
        store = _make_store(tmp_path)
        store.create("Lead", "l@test.com", "email")
        # Manually set next_due_at to the past
        store._sequences[0]["next_due_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        store._save()
        due = store.get_due()
        assert len(due) == 1
        assert due[0]["id"] == "SEQ-0001"

    def test_get_due_excludes_paused(self, tmp_path: Path) -> None:
        """get_due does not return paused sequences even if past due."""
        store = _make_store(tmp_path)
        store.create("Lead", "l@test.com", "email")
        store._sequences[0]["next_due_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        store.pause("SEQ-0001")
        store._save()
        due = store.get_due()
        assert len(due) == 0

    def test_get_due_excludes_future(self, tmp_path: Path) -> None:
        """get_due does not return sequences due in the future."""
        store = _make_store(tmp_path)
        store.create("Lead", "l@test.com", "email")
        # Default next_due_at is 1 day from now — should not be due
        due = store.get_due()
        assert len(due) == 0


# ---------------------------------------------------------------------------
# SequenceStore: limits
# ---------------------------------------------------------------------------


class TestSequenceStoreLimits:
    """Tests for max_sequences enforcement."""

    def test_max_sequences_enforced(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, max_sequences=2)
        store.create("A", "a@test.com", "email")
        store.create("B", "b@test.com", "email")
        result = store.create("C", "c@test.com", "email")
        assert result is None

    def test_max_sequences_counts_only_active(self, tmp_path: Path) -> None:
        """Completed/cancelled sequences do not count toward the limit."""
        store = _make_store(tmp_path, max_sequences=2)
        store.create("A", "a@test.com", "email")
        store.create("B", "b@test.com", "email")
        store.cancel("SEQ-0001")
        result = store.create("C", "c@test.com", "email")
        assert result is not None

    def test_resume_recalculates_next_due(self, tmp_path: Path) -> None:
        """Resuming a paused sequence recalculates next_due_at from now."""
        store = _make_store(tmp_path)
        store.create("Lead", "l@test.com", "email")
        store.pause("SEQ-0001")
        before = datetime.now(timezone.utc)
        result = store.resume("SEQ-0001")
        assert result is not None
        next_due = datetime.fromisoformat(result["next_due_at"])
        # First step delay is 1 day
        expected_min = before + timedelta(days=1) - timedelta(seconds=5)
        expected_max = before + timedelta(days=1) + timedelta(seconds=5)
        assert expected_min <= next_due <= expected_max


# ---------------------------------------------------------------------------
# SequenceStore: persistence
# ---------------------------------------------------------------------------


class TestSequenceStorePersistence:
    """Tests for ID counter survival across reloads."""

    def test_id_counter_survives_reload(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("First", "first@test.com", "email")
        store.create("Second", "second@test.com", "email")
        store2 = _make_store(tmp_path)
        s3 = store2.create("Third", "third@test.com", "email")
        assert s3 is not None
        assert s3["id"] == "SEQ-0003"


# ---------------------------------------------------------------------------
# SequenceStore: context string
# ---------------------------------------------------------------------------


class TestSequenceStoreContext:
    """Tests for context_string() output."""

    def test_context_string_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.context_string() == "Follow-ups: none"

    def test_context_string_with_sequences(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("A", "a@test.com", "email")
        store.create("B", "b@test.com", "email")
        ctx = store.context_string()
        assert "2 active" in ctx
        assert ctx.startswith("Follow-ups:")

    def test_context_string_due_today(self, tmp_path: Path) -> None:
        """Sequences due today appear in context string."""
        store = _make_store(tmp_path)
        store.create("A", "a@test.com", "email")
        # Set next_due_at to now (past due = still due today)
        store._sequences[0]["next_due_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).isoformat()
        store._save()
        ctx = store.context_string()
        assert "due today" in ctx


# ---------------------------------------------------------------------------
# Tool execute() methods
# ---------------------------------------------------------------------------


class TestSequenceTools:
    """Tests for tool execute() methods — success and error cases."""

    # -- CreateSequenceTool --

    @pytest.mark.asyncio
    async def test_create_tool_success(self, tmp_path: Path) -> None:
        store = SequenceStore(tmp_path / "sequences.json")
        tool = CreateSequenceTool(store)
        result = await tool.execute(
            lead_name="John", lead_contact="john@test.com", channel="email"
        )
        assert "SEQ-0001" in result
        assert "John" in result

    @pytest.mark.asyncio
    async def test_create_tool_invalid_channel(self, tmp_path: Path) -> None:
        store = SequenceStore(tmp_path / "sequences.json")
        tool = CreateSequenceTool(store)
        result = await tool.execute(
            lead_name="John", lead_contact="john@test.com", channel="sms"
        )
        assert "Invalid channel" in result

    @pytest.mark.asyncio
    async def test_create_tool_invalid_steps(self, tmp_path: Path) -> None:
        store = SequenceStore(tmp_path / "sequences.json")
        tool = CreateSequenceTool(store)
        result = await tool.execute(
            lead_name="John",
            lead_contact="john@test.com",
            channel="email",
            steps="not valid json",
        )
        assert "Invalid steps format" in result

    @pytest.mark.asyncio
    async def test_create_tool_steps_missing_fields(self, tmp_path: Path) -> None:
        """Steps with missing required fields should be rejected."""
        store = SequenceStore(tmp_path / "sequences.json")
        tool = CreateSequenceTool(store)
        result = await tool.execute(
            lead_name="John",
            lead_contact="john@test.com",
            channel="email",
            steps='[{"delay_days": 1}]',
        )
        assert "Invalid steps format" in result

    @pytest.mark.asyncio
    async def test_create_tool_max_reached(self, tmp_path: Path) -> None:
        store = SequenceStore(tmp_path / "sequences.json", max_sequences=1)
        tool = CreateSequenceTool(store)
        await tool.execute(
            lead_name="First", lead_contact="first@test.com", channel="email"
        )
        result = await tool.execute(
            lead_name="Second", lead_contact="second@test.com", channel="email"
        )
        assert "Sequence limit reached" in result

    @pytest.mark.asyncio
    async def test_create_tool_default_channel(self, tmp_path: Path) -> None:
        """When no channel provided, uses the configured default."""
        store = SequenceStore(tmp_path / "sequences.json")
        tool = CreateSequenceTool(store, default_channel="telegram")
        result = await tool.execute(lead_name="John", lead_contact="john@test.com")
        assert "telegram" in result

    # -- ListSequencesTool --

    @pytest.mark.asyncio
    async def test_list_tool_empty(self, tmp_path: Path) -> None:
        store = SequenceStore(tmp_path / "sequences.json")
        tool = ListSequencesTool(store)
        result = await tool.execute()
        assert "No sequences found" in result

    @pytest.mark.asyncio
    async def test_list_tool_shows_sequences(self, tmp_path: Path) -> None:
        store = SequenceStore(tmp_path / "sequences.json")
        store.create("Alice", "alice@test.com", "email")
        tool = ListSequencesTool(store)
        result = await tool.execute()
        assert "SEQ-0001" in result
        assert "Alice" in result

    # -- PauseSequenceTool --

    @pytest.mark.asyncio
    async def test_pause_tool_success(self, tmp_path: Path) -> None:
        store = SequenceStore(tmp_path / "sequences.json")
        store.create("Lead", "l@test.com", "email")
        tool = PauseSequenceTool(store)
        result = await tool.execute(sequence_id="SEQ-0001")
        assert "Paused" in result

    @pytest.mark.asyncio
    async def test_pause_tool_not_found(self, tmp_path: Path) -> None:
        store = SequenceStore(tmp_path / "sequences.json")
        tool = PauseSequenceTool(store)
        result = await tool.execute(sequence_id="SEQ-9999")
        assert "not found" in result

    # -- ResumeSequenceTool --

    @pytest.mark.asyncio
    async def test_resume_tool_success(self, tmp_path: Path) -> None:
        store = SequenceStore(tmp_path / "sequences.json")
        store.create("Lead", "l@test.com", "email")
        store.pause("SEQ-0001")
        tool = ResumeSequenceTool(store)
        result = await tool.execute(sequence_id="SEQ-0001")
        assert "Resumed" in result
        assert "Next due" in result

    @pytest.mark.asyncio
    async def test_resume_tool_not_paused(self, tmp_path: Path) -> None:
        store = SequenceStore(tmp_path / "sequences.json")
        store.create("Lead", "l@test.com", "email")
        tool = ResumeSequenceTool(store)
        result = await tool.execute(sequence_id="SEQ-0001")
        assert "not paused" in result

    # -- CancelSequenceTool --

    @pytest.mark.asyncio
    async def test_cancel_tool_success(self, tmp_path: Path) -> None:
        store = SequenceStore(tmp_path / "sequences.json")
        store.create("Lead", "l@test.com", "email")
        tool = CancelSequenceTool(store)
        result = await tool.execute(sequence_id="SEQ-0001")
        assert "Cancelled" in result

    @pytest.mark.asyncio
    async def test_cancel_tool_not_found(self, tmp_path: Path) -> None:
        store = SequenceStore(tmp_path / "sequences.json")
        tool = CancelSequenceTool(store)
        result = await tool.execute(sequence_id="SEQ-9999")
        assert "not found" in result
