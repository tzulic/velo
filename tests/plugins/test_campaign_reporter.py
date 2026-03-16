"""Tests for the campaign-reporter plugin."""

import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Load plugin via importlib (not installed as a package)
# ---------------------------------------------------------------------------

_plugin_path = (
    Path(__file__).resolve().parents[2]
    / "library"
    / "plugins"
    / "vertical"
    / "marketing"
    / "campaign-reporter"
    / "__init__.py"
)
_spec = importlib.util.spec_from_file_location("campaign_reporter", _plugin_path)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

ReportStore = _mod.ReportStore
SaveReportTool = _mod.SaveReportTool
GetReportTool = _mod.GetReportTool
ComparePeriodsTool = _mod.ComparePeriodsTool
ListReportsTool = _mod.ListReportsTool
ReportScheduler = _mod.ReportScheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path, max_reports: int = 10) -> Any:
    """Create a ReportStore backed by a temp file.

    Args:
        tmp_path: Pytest tmp_path fixture directory.
        max_reports: Maximum reports to store. Default 10 (small for cap tests).

    Returns:
        A fresh ReportStore instance.
    """
    return ReportStore(tmp_path / "marketing_reports.json", max_reports=max_reports)


def _save_report(
    store: Any,
    period: str,
    metrics: dict[str, Any] | None = None,
    summary: str = "",
) -> dict[str, Any]:
    """Helper to save a report with default metrics.

    Args:
        store: ReportStore instance.
        period: Period label.
        metrics: Metrics dict. Defaults to {"sessions": 100}.
        summary: Optional summary.

    Returns:
        The saved report dict.
    """
    if metrics is None:
        metrics = {"sessions": 100}
    return store.save(period=period, metrics_dict=metrics, summary=summary)


# ---------------------------------------------------------------------------
# ReportStore: save + auto-increment
# ---------------------------------------------------------------------------


class TestReportStoreSave:
    """Tests for ReportStore save() and ID auto-increment."""

    def test_save_assigns_id(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        report = _save_report(store, "2026-W01")
        assert report["id"] == "RPT-0001"

    def test_save_auto_increments_id(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        r1 = _save_report(store, "2026-W01")
        r2 = _save_report(store, "2026-W02")
        assert r1["id"] == "RPT-0001"
        assert r2["id"] == "RPT-0002"

    def test_save_stores_period_and_metrics(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        metrics = {"sessions": 1200, "conversions": 45}
        report = store.save(period="2026-W12", metrics_dict=metrics, summary="Good week")
        assert report["period"] == "2026-W12"
        assert report["metrics"] == metrics
        assert report["summary"] == "Good week"

    def test_save_persists_to_disk(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _save_report(store, "2026-W01", {"sessions": 500})
        raw = json.loads((tmp_path / "marketing_reports.json").read_text())
        assert len(raw) == 1
        assert raw[0]["period"] == "2026-W01"

    def test_id_counter_survives_reload(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _save_report(store, "2026-W01")
        _save_report(store, "2026-W02")
        store2 = _make_store(tmp_path)
        r3 = _save_report(store2, "2026-W03")
        assert r3["id"] == "RPT-0003"


# ---------------------------------------------------------------------------
# ReportStore: get
# ---------------------------------------------------------------------------


class TestReportStoreGet:
    """Tests for ReportStore get() by period and ID."""

    def test_get_by_period(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _save_report(store, "2026-W11")
        report = store.get(period="2026-W11")
        assert report is not None
        assert report["period"] == "2026-W11"

    def test_get_by_id(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _save_report(store, "2026-W11")
        report = store.get(report_id="RPT-0001")
        assert report is not None
        assert report["id"] == "RPT-0001"

    def test_get_period_not_found_returns_none(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.get(period="2026-W99") is None

    def test_get_id_not_found_returns_none(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.get(report_id="RPT-9999") is None

    def test_get_returns_most_recent_for_duplicate_period(self, tmp_path: Path) -> None:
        """When two reports share a period, get() returns the most recent one."""
        store = _make_store(tmp_path)
        store.save("2026-W11", {"sessions": 100})
        store.save("2026-W11", {"sessions": 200})
        report = store.get(period="2026-W11")
        assert report is not None
        assert report["metrics"]["sessions"] == 200


# ---------------------------------------------------------------------------
# ReportStore: list
# ---------------------------------------------------------------------------


class TestReportStoreList:
    """Tests for ReportStore list_reports()."""

    def test_list_returns_newest_first(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _save_report(store, "2026-W01")
        _save_report(store, "2026-W02")
        _save_report(store, "2026-W03")
        reports = store.list_reports()
        assert reports[0]["period"] == "2026-W03"
        assert reports[-1]["period"] == "2026-W01"

    def test_list_respects_limit(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        for i in range(5):
            _save_report(store, f"2026-W{i:02d}")
        reports = store.list_reports(limit=2)
        assert len(reports) == 2

    def test_list_empty_returns_empty_list(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.list_reports() == []


# ---------------------------------------------------------------------------
# ReportStore: compare
# ---------------------------------------------------------------------------


class TestReportStoreCompare:
    """Tests for ReportStore compare() — deltas and partial overlap."""

    def test_compare_full_overlap(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.save("2026-W11", {"sessions": 1200, "conversions": 45})
        store.save("2026-W12", {"sessions": 1400, "conversions": 52})
        result = store.compare("2026-W11", "2026-W12")
        assert "Comparing 2026-W11 vs 2026-W12" in result
        assert "1200" in result
        assert "1400" in result
        # Should contain percentage
        assert "%" in result

    def test_compare_positive_delta(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.save("2026-W11", {"sessions": 1000})
        store.save("2026-W12", {"sessions": 1100})
        result = store.compare("2026-W11", "2026-W12")
        assert "+10.0%" in result

    def test_compare_negative_delta(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.save("2026-W11", {"ad_spend": 500})
        store.save("2026-W12", {"ad_spend": 480})
        result = store.compare("2026-W11", "2026-W12")
        assert "-4.0%" in result

    def test_compare_partial_overlap_removed_key(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.save("2026-W11", {"sessions": 1200, "old_metric": 99})
        store.save("2026-W12", {"sessions": 1400})
        result = store.compare("2026-W11", "2026-W12")
        assert "(removed)" in result

    def test_compare_partial_overlap_new_key(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.save("2026-W11", {"sessions": 1200})
        store.save("2026-W12", {"sessions": 1400, "new_metric": 7})
        result = store.compare("2026-W11", "2026-W12")
        assert "(new)" in result

    def test_compare_period_a_not_found(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.save("2026-W12", {"sessions": 100})
        result = store.compare("2026-W11", "2026-W12")
        assert "No report found for period '2026-W11'" in result

    def test_compare_period_b_not_found(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.save("2026-W11", {"sessions": 100})
        result = store.compare("2026-W11", "2026-W12")
        assert "No report found for period '2026-W12'" in result

    def test_compare_zero_baseline_no_percentage(self, tmp_path: Path) -> None:
        """When baseline value is 0, percentage is skipped to avoid division by zero."""
        store = _make_store(tmp_path)
        store.save("2026-W11", {"leads": 0})
        store.save("2026-W12", {"leads": 5})
        result = store.compare("2026-W11", "2026-W12")
        # Should not raise; should show delta without percentage
        assert "0 → 5" in result


# ---------------------------------------------------------------------------
# ReportStore: max_reports FIFO
# ---------------------------------------------------------------------------


class TestReportStoreMaxReports:
    """Tests for FIFO eviction when max_reports is reached."""

    def test_max_reports_evicts_oldest(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, max_reports=3)
        _save_report(store, "2026-W01")  # RPT-0001 — will be evicted
        _save_report(store, "2026-W02")  # RPT-0002
        _save_report(store, "2026-W03")  # RPT-0003
        _save_report(store, "2026-W04")  # RPT-0004 — oldest evicted
        assert len(store._reports) == 3
        assert store.get(report_id="RPT-0001") is None
        assert store.get(report_id="RPT-0004") is not None

    def test_max_reports_ids_keep_incrementing_after_eviction(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, max_reports=2)
        _save_report(store, "2026-W01")
        _save_report(store, "2026-W02")
        r3 = _save_report(store, "2026-W03")
        # ID should still be RPT-0003, not reset
        assert r3["id"] == "RPT-0003"


# ---------------------------------------------------------------------------
# ReportStore: context_string
# ---------------------------------------------------------------------------


class TestReportStoreContext:
    """Tests for context_string()."""

    def test_context_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.context_string() == "Marketing: no reports yet"

    def test_context_with_reports(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.save("2026-W11", {"sessions": 1400, "conversions": 52})
        ctx = store.context_string()
        assert "Marketing:" in ctx
        assert "2026-W11" in ctx
        assert "sessions" in ctx

    def test_context_shows_count(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        for i in range(3):
            _save_report(store, f"2026-W{i:02d}")
        ctx = store.context_string()
        assert "3 reports" in ctx


# ---------------------------------------------------------------------------
# Tool: SaveReportTool
# ---------------------------------------------------------------------------


class TestSaveReportTool:
    """Tests for SaveReportTool.execute()."""

    @pytest.mark.asyncio
    async def test_save_success(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        tool = SaveReportTool(store)
        result = await tool.execute(
            period="2026-W12",
            metrics='{"sessions": 1200, "conversions": 45}',
            summary="Good week",
        )
        assert "RPT-0001" in result
        assert "2026-W12" in result

    @pytest.mark.asyncio
    async def test_save_invalid_json_metrics(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        tool = SaveReportTool(store)
        result = await tool.execute(period="2026-W12", metrics="not json")
        assert "Invalid metrics format" in result

    @pytest.mark.asyncio
    async def test_save_metrics_not_a_dict(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        tool = SaveReportTool(store)
        result = await tool.execute(period="2026-W12", metrics="[1, 2, 3]")
        assert "Invalid metrics format" in result

    @pytest.mark.asyncio
    async def test_save_shows_metric_count(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        tool = SaveReportTool(store)
        result = await tool.execute(
            period="2026-W12",
            metrics='{"a": 1, "b": 2, "c": 3}',
        )
        assert "3 metric" in result


# ---------------------------------------------------------------------------
# Tool: GetReportTool
# ---------------------------------------------------------------------------


class TestGetReportTool:
    """Tests for GetReportTool.execute()."""

    @pytest.mark.asyncio
    async def test_get_by_period_success(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.save("2026-W11", {"sessions": 1000})
        tool = GetReportTool(store)
        result = await tool.execute(period="2026-W11")
        assert "2026-W11" in result
        assert "sessions" in result

    @pytest.mark.asyncio
    async def test_get_by_id_success(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.save("2026-W11", {"sessions": 1000})
        tool = GetReportTool(store)
        result = await tool.execute(report_id="RPT-0001")
        assert "RPT-0001" in result

    @pytest.mark.asyncio
    async def test_get_period_not_found(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        tool = GetReportTool(store)
        result = await tool.execute(period="2026-W99")
        assert "No report found" in result

    @pytest.mark.asyncio
    async def test_get_id_not_found(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        tool = GetReportTool(store)
        result = await tool.execute(report_id="RPT-9999")
        assert "not found" in result


# ---------------------------------------------------------------------------
# Tool: ComparePeriodsTool
# ---------------------------------------------------------------------------


class TestComparePeriodsTool:
    """Tests for ComparePeriodsTool.execute()."""

    @pytest.mark.asyncio
    async def test_compare_success(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.save("2026-W11", {"sessions": 1200})
        store.save("2026-W12", {"sessions": 1400})
        tool = ComparePeriodsTool(store)
        result = await tool.execute(period_a="2026-W11", period_b="2026-W12")
        assert "Comparing 2026-W11 vs 2026-W12" in result
        assert "1200" in result
        assert "1400" in result

    @pytest.mark.asyncio
    async def test_compare_not_found(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        tool = ComparePeriodsTool(store)
        result = await tool.execute(period_a="2026-W11", period_b="2026-W12")
        assert "No report found" in result


# ---------------------------------------------------------------------------
# Tool: ListReportsTool
# ---------------------------------------------------------------------------


class TestListReportsTool:
    """Tests for ListReportsTool.execute()."""

    @pytest.mark.asyncio
    async def test_list_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        tool = ListReportsTool(store)
        result = await tool.execute()
        assert "No reports" in result

    @pytest.mark.asyncio
    async def test_list_shows_reports(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.save("2026-W11", {"sessions": 1000}, summary="Good week")
        tool = ListReportsTool(store)
        result = await tool.execute()
        assert "RPT-0001" in result
        assert "2026-W11" in result

    @pytest.mark.asyncio
    async def test_list_newest_first(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        _save_report(store, "2026-W01")
        _save_report(store, "2026-W03")
        tool = ListReportsTool(store)
        result = await tool.execute()
        # W03 should appear before W01 in the output
        idx_w03 = result.index("2026-W03")
        idx_w01 = result.index("2026-W01")
        assert idx_w03 < idx_w01

    @pytest.mark.asyncio
    async def test_list_respects_limit(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        for i in range(5):
            _save_report(store, f"2026-W{i:02d}")
        tool = ListReportsTool(store)
        result = await tool.execute(limit=2)
        assert "2 report" in result


# ---------------------------------------------------------------------------
# ReportScheduler: instantiation and runtime binding
# ---------------------------------------------------------------------------


class TestReportScheduler:
    """Tests for ReportScheduler instantiation and set_runtime."""

    def test_scheduler_creates_without_error(self) -> None:
        scheduler = ReportScheduler(
            schedule_day="monday", schedule_time="09:00", tz_name="UTC"
        )
        assert scheduler is not None

    def test_scheduler_set_runtime_stores_process_direct(self) -> None:
        """set_runtime should store the process_direct callback."""
        from unittest.mock import MagicMock

        scheduler = ReportScheduler()
        mock_process = AsyncMock()
        refs = MagicMock()
        refs.process_direct = mock_process
        scheduler.set_runtime(refs)
        assert scheduler._process_direct is mock_process

    def test_scheduler_stop_cancels_task(self) -> None:
        """stop() should cancel the internal asyncio task without raising."""
        from unittest.mock import MagicMock

        scheduler = ReportScheduler()
        mock_task = MagicMock()
        scheduler._task = mock_task
        scheduler.stop()
        mock_task.cancel.assert_called_once()
