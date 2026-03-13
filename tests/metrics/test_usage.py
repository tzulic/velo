"""Tests for usage/cost tracking."""

import json
import pytest
from pathlib import Path

from velo.metrics.usage import compute_cost, record_usage, load_usage, print_usage_summary


class TestComputeCost:
    def test_claude_sonnet(self):
        cost = compute_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
        # $3/M input + $15/M output = $18
        assert abs(cost - 18.0) < 0.01

    def test_gpt4o_mini(self):
        cost = compute_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        # $0.15/M + $0.60/M = $0.75
        assert abs(cost - 0.75) < 0.01

    def test_unknown_model_returns_zero(self):
        cost = compute_cost("some-unknown-model", 1_000, 1_000)
        assert cost == 0.0

    def test_zero_tokens(self):
        cost = compute_cost("claude-sonnet-4-6", 0, 0)
        assert cost == 0.0


class TestRecordUsage:
    def test_appends_jsonl(self, tmp_path):
        record_usage(
            workspace=tmp_path,
            run_id="abc123",
            session_key="cli:direct",
            model="claude-sonnet-4-6",
            tokens_in=100,
            tokens_out=50,
            duration_ms=200,
            tool_calls_count=2,
        )
        path = tmp_path / ".velo" / "metrics" / "usage.jsonl"
        assert path.exists()
        records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert len(records) == 1
        r = records[0]
        assert r["run_id"] == "abc123"
        assert r["tokens_in"] == 100
        assert r["tokens_out"] == 50
        assert r["tool_calls"] == 2
        assert r["duration_ms"] == 200

    def test_multiple_records(self, tmp_path):
        for i in range(3):
            record_usage(
                workspace=tmp_path,
                run_id=f"run{i}",
                session_key="cli:x",
                model="gpt-4o-mini",
                tokens_in=10,
                tokens_out=5,
                duration_ms=100,
                tool_calls_count=0,
            )
        records = load_usage(tmp_path)
        assert len(records) == 3

    def test_cost_recorded(self, tmp_path):
        record_usage(
            workspace=tmp_path,
            run_id="r1",
            session_key="tg:123",
            model="claude-sonnet-4-6",
            tokens_in=1_000_000,
            tokens_out=0,
            duration_ms=500,
            tool_calls_count=0,
        )
        records = load_usage(tmp_path)
        # $3/M input = $3.0
        assert abs(records[0]["cost_usd"] - 3.0) < 0.01


class TestLoadUsage:
    def test_empty_when_no_file(self, tmp_path):
        records = load_usage(tmp_path)
        assert records == []

    def test_skips_corrupt_lines(self, tmp_path):
        path = tmp_path / ".velo" / "metrics" / "usage.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text('{"run_id":"ok"}\nnot_json\n{"run_id":"ok2"}\n')
        records = load_usage(tmp_path)
        assert len(records) == 2


class TestPrintSummary:
    def test_no_data_prints_message(self, tmp_path, capsys):
        print_usage_summary(tmp_path)
        out = capsys.readouterr().out
        assert "No usage data" in out

    def test_prints_totals(self, tmp_path, capsys):
        for i in range(2):
            record_usage(
                workspace=tmp_path,
                run_id=f"r{i}",
                session_key="cli:x",
                model="gpt-4o-mini",
                tokens_in=1000,
                tokens_out=500,
                duration_ms=100,
                tool_calls_count=1,
            )
        print_usage_summary(tmp_path)
        out = capsys.readouterr().out
        assert "TOTAL" in out
        assert "2" in out  # 2 runs
