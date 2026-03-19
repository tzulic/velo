"""Tests for subagent progress tracking."""

from velo.agent.progress import ProgressTracker


def test_tracker_accumulates_events():
    """Expected use: multiple tool calls are recorded and counted."""
    tracker = ProgressTracker()
    tracker.record_tool("web_search", {"query": "weather today"})
    tracker.record_tool("read_file", {"path": "/tmp/data.txt"})
    assert tracker.count == 2


def test_tracker_summary_natural_language():
    """Expected use: summary groups repeated tools with counts."""
    tracker = ProgressTracker()
    tracker.record_tool("web_search", {"query": "weather"})
    tracker.record_tool("web_search", {"query": "news"})
    tracker.record_tool("read_file", {"path": "/tmp/x"})
    summary = tracker.summary()
    assert "web search (2x)" in summary
    assert "read file" in summary
    assert len(summary) < 200


def test_tracker_empty_summary():
    """Edge case: no events produces empty string."""
    tracker = ProgressTracker()
    assert tracker.summary() == ""


def test_tracker_single_tool():
    """Edge case: single tool has no count suffix."""
    tracker = ProgressTracker()
    tracker.record_tool("exec", {"command": "ls"})
    summary = tracker.summary()
    assert "exec" in summary
    assert "(2x)" not in summary
