"""Tests for the resolution-guard plugin."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Load the plugin module via importlib (not installed as a package)
# ---------------------------------------------------------------------------

_plugin_path = (
    Path(__file__).resolve().parents[2]
    / "library"
    / "plugins"
    / "horizontal"
    / "resolution-guard"
    / "__init__.py"
)
_spec = importlib.util.spec_from_file_location("resolution_guard", _plugin_path)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

AuditStore = _mod.AuditStore
GetAuditLogTool = _mod.GetAuditLogTool
GetResolutionStatsTool = _mod.GetResolutionStatsTool
_make_guard = _mod._make_guard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path, max_audit_entries: int = 100) -> Any:
    """Create an AuditStore backed by a temp file.

    Args:
        tmp_path: Pytest tmp_path fixture directory.
        max_audit_entries: Cap for FIFO eviction. Default 100 (small for limit tests).

    Returns:
        A fresh AuditStore instance.
    """
    return AuditStore(tmp_path / "resolution_audit.json", max_audit_entries=max_audit_entries)


async def _run_guard(
    store: Any,
    tool_name: str,
    params: dict[str, Any],
    track_patterns: list[str] | None = None,
    blocked_actions: list[str] | None = None,
    require_approval: list[str] | None = None,
    max_refund: int = 0,
) -> Any:
    """Helper to create and call a guard with given config.

    Args:
        store: AuditStore instance.
        tool_name: Tool name to simulate.
        params: Params dict to pass as value.
        track_patterns: Patterns to track. Default ["refund"].
        blocked_actions: Permanently blocked tool names. Default [].
        require_approval: Approval-required tool names. Default [].
        max_refund: Max refund amount. Default 0 (disabled).

    Returns:
        Guard return value.
    """
    guard = _make_guard(
        store=store,
        track_patterns=track_patterns if track_patterns is not None else ["refund"],
        blocked_actions=blocked_actions or [],
        require_approval=require_approval or [],
        max_refund=max_refund,
    )
    return await guard(params, tool_name=tool_name)


# ---------------------------------------------------------------------------
# AuditStore: log_action and get_log
# ---------------------------------------------------------------------------


class TestAuditStoreLog:
    """Tests for AuditStore log_action and get_log."""

    def test_log_allowed_entry(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("stripe_refund", {"amount": 500}, "allowed")
        entries = store.get_log()
        assert len(entries) == 1
        assert entries[0]["outcome"] == "allowed"
        assert entries[0]["tool_name"] == "stripe_refund"
        assert entries[0]["id"] == "RES-0001"

    def test_log_blocked_entry_with_reason(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("cancel_order", {}, "blocked", "Requires human approval")
        entries = store.get_log()
        assert entries[0]["outcome"] == "blocked"
        assert entries[0]["reason"] == "Requires human approval"

    def test_get_log_respects_limit(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        for i in range(10):
            store.log_action(f"tool_{i}", {}, "allowed")
        entries = store.get_log(limit=3)
        assert len(entries) == 3

    def test_get_log_filter_by_action_type(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("stripe_refund", {}, "allowed")
        store.log_action("cancel_order", {}, "blocked")
        entries = store.get_log(action_type="refund")
        assert len(entries) == 1
        assert entries[0]["tool_name"] == "stripe_refund"

    def test_get_log_filter_case_insensitive(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("Stripe_REFUND", {}, "allowed")
        entries = store.get_log(action_type="refund")
        assert len(entries) == 1

    def test_get_log_returns_newest_first(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("first", {}, "allowed")
        store.log_action("second", {}, "allowed")
        entries = store.get_log()
        assert entries[0]["tool_name"] == "second"
        assert entries[1]["tool_name"] == "first"

    def test_log_persists_to_disk(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("refund_tool", {"amount": 200}, "allowed")
        raw = json.loads((tmp_path / "resolution_audit.json").read_text())
        assert len(raw) == 1
        assert raw[0]["tool_name"] == "refund_tool"

    def test_log_empty_returns_empty_list(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.get_log() == []


# ---------------------------------------------------------------------------
# AuditStore: FIFO cap
# ---------------------------------------------------------------------------


class TestAuditStoreCap:
    """Tests for FIFO cap enforcement."""

    def test_cap_evicts_oldest_entries(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, max_audit_entries=3)
        store.log_action("first", {}, "allowed")
        store.log_action("second", {}, "allowed")
        store.log_action("third", {}, "allowed")
        store.log_action("fourth", {}, "allowed")
        # Should only have the 3 most recent
        assert len(store._log) == 3
        tool_names = [e["tool_name"] for e in store._log]
        assert "first" not in tool_names
        assert "fourth" in tool_names

    def test_id_increments_beyond_cap(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, max_audit_entries=2)
        store.log_action("a", {}, "allowed")
        store.log_action("b", {}, "allowed")
        store.log_action("c", {}, "allowed")
        # Third entry's ID should still be RES-0003 even though first was evicted
        latest = store._log[-1]
        assert latest["id"] == "RES-0003"


# ---------------------------------------------------------------------------
# AuditStore: stats
# ---------------------------------------------------------------------------


class TestAuditStoreStats:
    """Tests for get_stats() and get_today_summary()."""

    def test_stats_counts_total_and_blocked(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("refund_a", {"amount": 500}, "allowed")
        store.log_action("cancel_b", {}, "blocked")
        stats = store.get_stats(days=1)
        assert stats["total"] == 2
        assert stats["blocked"] == 1

    def test_stats_sums_refund_total(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("refund_a", {"amount": 500}, "allowed")
        store.log_action("refund_b", {"amount": 300}, "allowed")
        stats = store.get_stats(days=1)
        assert stats["refund_total"] == 800.0

    def test_stats_refund_amount_key_variants(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("refund_a", {"refund_amount": 200}, "allowed")
        store.log_action("refund_b", {"total": 100}, "allowed")
        stats = store.get_stats(days=1)
        assert stats["refund_total"] == 300.0

    def test_stats_excludes_old_entries(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("old_tool", {}, "allowed")
        # Manually backdate the entry timestamp
        store._log[0]["timestamp"] = (
            datetime.now(timezone.utc) - timedelta(days=10)
        ).isoformat()
        store._save()
        stats = store.get_stats(days=7)
        assert stats["total"] == 0

    def test_stats_most_common_sorted(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("refund_a", {}, "allowed")
        store.log_action("refund_a", {}, "allowed")
        store.log_action("cancel_b", {}, "blocked")
        stats = store.get_stats(days=1)
        assert stats["most_common"][0][0] == "refund_a"
        assert stats["most_common"][0][1] == 2

    def test_stats_empty_store(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        stats = store.get_stats(days=7)
        assert stats["total"] == 0
        assert stats["blocked"] == 0
        assert stats["refund_total"] == 0.0
        assert stats["most_common"] == []

    def test_stats_invalid_days_defaults_to_7(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("refund_a", {}, "allowed")
        # days=0 should default to 7 — entry within 7 days should be counted
        stats = store.get_stats(days=0)
        assert stats["total"] == 1


# ---------------------------------------------------------------------------
# AuditStore: persistence across reload
# ---------------------------------------------------------------------------


class TestAuditStorePersistence:
    """Tests for loading state from disk."""

    def test_id_counter_survives_reload(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("first", {}, "allowed")
        store.log_action("second", {}, "allowed")
        store2 = _make_store(tmp_path)
        store2.log_action("third", {}, "allowed")
        assert store2._log[-1]["id"] == "RES-0003"

    def test_entries_survive_reload(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("refund_x", {"amount": 999}, "allowed")
        store2 = _make_store(tmp_path)
        entries = store2.get_log()
        assert len(entries) == 1
        assert entries[0]["tool_name"] == "refund_x"


# ---------------------------------------------------------------------------
# Guard hook
# ---------------------------------------------------------------------------


class TestGuardHook:
    """Tests for the _make_guard before_tool_call hook."""

    @pytest.mark.asyncio
    async def test_passthrough_untracked_tool(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        params = {"customer_id": "cust_123"}
        result = await _run_guard(store, "get_customer_info", params, track_patterns=["refund"])
        assert result == params
        assert store.get_log() == []  # Nothing logged for untracked tools

    @pytest.mark.asyncio
    async def test_track_matching_tool_allowed(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        params = {"amount": 50}
        result = await _run_guard(
            store, "stripe_refund", params, track_patterns=["refund"], max_refund=100
        )
        assert result == params
        entries = store.get_log()
        assert len(entries) == 1
        assert entries[0]["outcome"] == "allowed"

    @pytest.mark.asyncio
    async def test_block_blocked_action(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = await _run_guard(
            store,
            "delete_account",
            {},
            track_patterns=["delete"],
            blocked_actions=["delete_account"],
        )
        assert result.get("__block") is True
        assert "blocked by policy" in result["reason"]
        entries = store.get_log()
        assert entries[0]["outcome"] == "blocked"

    @pytest.mark.asyncio
    async def test_block_approval_required_action(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = await _run_guard(
            store,
            "cancel_subscription",
            {},
            track_patterns=["cancel"],
            require_approval=["cancel_subscription"],
        )
        assert result.get("__block") is True
        assert "human approval" in result["reason"]
        entries = store.get_log()
        assert entries[0]["outcome"] == "blocked"

    @pytest.mark.asyncio
    async def test_block_amount_over_limit(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = await _run_guard(
            store, "stripe_refund", {"amount": 5000}, track_patterns=["refund"], max_refund=100
        )
        assert result.get("__block") is True
        assert "policy limit" in result["reason"]
        entries = store.get_log()
        assert entries[0]["outcome"] == "blocked"

    @pytest.mark.asyncio
    async def test_allow_amount_under_limit(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        params = {"amount": 50}
        result = await _run_guard(
            store, "stripe_refund", params, track_patterns=["refund"], max_refund=100
        )
        assert result == params
        assert store.get_log()[0]["outcome"] == "allowed"

    @pytest.mark.asyncio
    async def test_allow_when_max_refund_zero(self, tmp_path: Path) -> None:
        """max_refund=0 disables amount checking — any amount should pass."""
        store = _make_store(tmp_path)
        params = {"amount": 999999}
        result = await _run_guard(
            store, "stripe_refund", params, track_patterns=["refund"], max_refund=0
        )
        assert result == params
        assert store.get_log()[0]["outcome"] == "allowed"

    @pytest.mark.asyncio
    async def test_amount_key_refund_amount(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = await _run_guard(
            store,
            "stripe_refund",
            {"refund_amount": 5000},
            track_patterns=["refund"],
            max_refund=100,
        )
        assert result.get("__block") is True

    @pytest.mark.asyncio
    async def test_amount_key_total(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = await _run_guard(
            store,
            "stripe_refund",
            {"total": 5000},
            track_patterns=["refund"],
            max_refund=100,
        )
        assert result.get("__block") is True

    @pytest.mark.asyncio
    async def test_pattern_matching_case_insensitive(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        params = {"amount": 50}
        # "REFUND" in tool name should still match pattern "refund"
        result = await _run_guard(
            store, "STRIPE_REFUND", params, track_patterns=["refund"], max_refund=100
        )
        assert result == params  # allowed
        assert len(store.get_log()) == 1  # was tracked

    @pytest.mark.asyncio
    async def test_blocked_action_logs_reason(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        await _run_guard(
            store,
            "delete_account",
            {},
            track_patterns=["delete"],
            blocked_actions=["delete_account"],
        )
        entries = store.get_log()
        assert "permanently blocked" in entries[0].get("reason", "").lower()

    @pytest.mark.asyncio
    async def test_approval_required_logs_reason(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        await _run_guard(
            store,
            "cancel_subscription",
            {},
            track_patterns=["cancel"],
            require_approval=["cancel_subscription"],
        )
        entries = store.get_log()
        assert "approval" in entries[0].get("reason", "").lower()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class TestGetAuditLogTool:
    """Tests for GetAuditLogTool.execute()."""

    @pytest.mark.asyncio
    async def test_audit_log_with_data(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("stripe_refund", {"amount": 500}, "allowed")
        tool = GetAuditLogTool(store)
        result = await tool.execute()
        assert "stripe_refund" in result
        assert "allowed" in result
        assert "RES-" not in result or "RES-" in result  # entries shown

    @pytest.mark.asyncio
    async def test_audit_log_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        tool = GetAuditLogTool(store)
        result = await tool.execute()
        assert "No resolution actions recorded yet" in result

    @pytest.mark.asyncio
    async def test_audit_log_filter_action_type(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("stripe_refund", {}, "allowed")
        store.log_action("cancel_order", {}, "blocked")
        tool = GetAuditLogTool(store)
        result = await tool.execute(action_type="refund")
        assert "stripe_refund" in result
        assert "cancel_order" not in result

    @pytest.mark.asyncio
    async def test_audit_log_shows_amount(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("stripe_refund", {"amount": 4999}, "allowed")
        tool = GetAuditLogTool(store)
        result = await tool.execute()
        assert "4999" in result


class TestGetResolutionStatsTool:
    """Tests for GetResolutionStatsTool.execute()."""

    @pytest.mark.asyncio
    async def test_stats_with_data(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("stripe_refund", {"amount": 5000}, "allowed")
        store.log_action("cancel_order", {}, "blocked")
        tool = GetResolutionStatsTool(store)
        result = await tool.execute(days=1)
        assert "Total actions" in result
        assert "2" in result
        assert "Blocked" in result
        assert "1" in result

    @pytest.mark.asyncio
    async def test_stats_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        tool = GetResolutionStatsTool(store)
        result = await tool.execute()
        assert "0" in result
        assert "Total actions" in result

    @pytest.mark.asyncio
    async def test_stats_default_days(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        tool = GetResolutionStatsTool(store)
        result = await tool.execute()  # No days arg — should default to 7
        assert "last 7 day(s)" in result


# ---------------------------------------------------------------------------
# Context provider
# ---------------------------------------------------------------------------


class TestContextProvider:
    """Tests for AuditStore.context_string()."""

    def test_context_with_no_actions(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.context_string() == "Resolutions: none today"

    def test_context_with_actions_today(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("stripe_refund", {"amount": 5000}, "allowed")
        store.log_action("cancel_order", {}, "blocked")
        ctx = store.context_string()
        assert ctx.startswith("Resolutions:")
        assert "2 actions today" in ctx
        assert "blocked" in ctx

    def test_context_refund_totaling(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.log_action("stripe_refund", {"amount": 10000}, "allowed")
        ctx = store.context_string()
        assert "refunds totaling" in ctx
        assert "$100" in ctx

    def test_context_excludes_old_entries(self, tmp_path: Path) -> None:
        """Actions from previous days should not appear in today's context."""
        store = _make_store(tmp_path)
        store.log_action("stripe_refund", {"amount": 500}, "allowed")
        # Backdate the entry to yesterday
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        store._log[0]["timestamp"] = yesterday + "T12:00:00+00:00"
        assert store.context_string() == "Resolutions: none today"
