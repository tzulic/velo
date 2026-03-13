"""LLM usage and cost tracking.

Records per-run token usage and cost estimates to a JSONL file at
~/.velo/metrics/usage.jsonl (or workspace/.velo/metrics/usage.jsonl).
Provides a summary command accessible via `velo usage`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

# Cost per million tokens (USD). Ordered most-specific first to avoid
# shorter prefixes shadowing longer ones (e.g. "gpt-4o" before "gpt-4o-mini").
_COST_TABLE: list[tuple[str, float, float]] = [
    # (substring, input_cost_per_M, output_cost_per_M)
    ("claude-opus", 15.0, 75.0),
    ("claude-sonnet", 3.0, 15.0),
    ("claude-haiku", 0.25, 1.25),
    ("gpt-4o-mini", 0.15, 0.60),  # must be before "gpt-4o"
    ("gpt-4o", 5.0, 15.0),
    ("gpt-4-turbo", 10.0, 30.0),
    ("o1-mini", 3.0, 12.0),       # must be before "o1"
    ("o1", 15.0, 60.0),
]


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate cost in USD for a model run.

    Uses substring matching against known model names, checked in specificity
    order (most specific first). Returns 0.0 for unknown models.

    Args:
        model (str): Model identifier (e.g. "claude-sonnet-4-6").
        tokens_in (int): Number of input tokens.
        tokens_out (int): Number of output tokens.

    Returns:
        float: Estimated cost in USD.
    """
    model_lower = model.lower()
    input_rate = 0.0
    output_rate = 0.0

    for key, in_rate, out_rate in _COST_TABLE:
        if key in model_lower:
            input_rate = in_rate
            output_rate = out_rate
            break

    return (tokens_in * input_rate + tokens_out * output_rate) / 1_000_000


def record_usage(
    workspace: Path,
    run_id: str,
    session_key: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    duration_ms: int,
    tool_calls_count: int,
) -> None:
    """Append one usage record to the JSONL log.

    Args:
        workspace (Path): Workspace directory (metrics stored under .velo/).
        run_id (str): Short run identifier for correlation.
        session_key (str): Session key (channel:chat_id).
        model (str): Model identifier.
        tokens_in (int): Input token count.
        tokens_out (int): Output token count.
        duration_ms (int): Wall-clock time for the run in milliseconds.
        tool_calls_count (int): Number of tool calls made during the run.
    """
    metrics_dir = workspace / ".velo" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    path = metrics_dir / "usage.jsonl"

    cost = compute_cost(model, tokens_in, tokens_out)
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "session_key": session_key,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 6),
        "duration_ms": duration_ms,
        "tool_calls": tool_calls_count,
    }

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("usage.record_failed: {}", e)


def load_usage(workspace: Path) -> list[dict[str, Any]]:
    """Load all usage records from the JSONL log.

    Args:
        workspace (Path): Workspace directory.

    Returns:
        list[dict]: All usage records, oldest first.
    """
    path = workspace / ".velo" / "metrics" / "usage.jsonl"
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def print_usage_summary(workspace: Path) -> None:
    """Print a cost/token summary to stdout.

    Groups records by day and model. Outputs a readable table.

    Args:
        workspace (Path): Workspace directory.
    """
    records = load_usage(workspace)
    if not records:
        print("No usage data recorded yet.")
        return

    # Aggregate by date
    by_date: dict[str, dict[str, Any]] = {}
    total_cost = 0.0
    total_in = 0
    total_out = 0

    for rec in records:
        day = rec.get("ts", "")[:10] or "unknown"
        if day not in by_date:
            by_date[day] = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "runs": 0}
        by_date[day]["tokens_in"] += rec.get("tokens_in", 0)
        by_date[day]["tokens_out"] += rec.get("tokens_out", 0)
        by_date[day]["cost_usd"] += rec.get("cost_usd", 0.0)
        by_date[day]["runs"] += 1
        total_cost += rec.get("cost_usd", 0.0)
        total_in += rec.get("tokens_in", 0)
        total_out += rec.get("tokens_out", 0)

    print(f"\n{'Date':<12} {'Runs':>6} {'Tokens In':>12} {'Tokens Out':>12} {'Cost (USD)':>12}")
    print("-" * 58)
    for day in sorted(by_date):
        d = by_date[day]
        print(
            f"{day:<12} {d['runs']:>6} {d['tokens_in']:>12,} {d['tokens_out']:>12,} "
            f"${d['cost_usd']:>11.4f}"
        )
    print("-" * 58)
    print(
        f"{'TOTAL':<12} {len(records):>6} {total_in:>12,} {total_out:>12,} ${total_cost:>11.4f}"
    )
    print()
