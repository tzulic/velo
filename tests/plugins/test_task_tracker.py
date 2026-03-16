"""Tests for the task-tracker plugin."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Add the plugin directory to the path so we can import it directly.
# The plugin is loaded via importlib at runtime, not installed as a package.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "library" / "plugins" / "horizontal" / "task-tracker"),
)

# ruff: noqa: E402
from __init__ import (  # type: ignore[import]
    CreateTaskTool,
    DeleteTaskTool,
    ListTasksTool,
    TaskStore,
    UpdateTaskTool,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path, max_tasks: int = 5, show_done_days: int = 7) -> TaskStore:
    """Create a TaskStore backed by a temp file.

    Args:
        tmp_path: Pytest tmp_path fixture directory.
        max_tasks: Maximum tasks allowed. Default 5 (small for limit tests).
        show_done_days: Days to retain done/cancelled tasks. Default 7.

    Returns:
        A fresh TaskStore instance.
    """
    return TaskStore(tmp_path / "tasks.json", max_tasks=max_tasks, show_done_days=show_done_days)


# ---------------------------------------------------------------------------
# TaskStore: CRUD
# ---------------------------------------------------------------------------


class TestTaskStoreCrud:
    """Tests for TaskStore create, read, update, delete."""

    def test_create_task(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        task = store.create("Call dentist", priority="high")
        assert task is not None
        assert task["id"] == "TSK-0001"
        assert task["title"] == "Call dentist"
        assert task["priority"] == "high"
        assert task["status"] == "pending"

    def test_create_auto_increments_id(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        t1 = store.create("Task 1")
        t2 = store.create("Task 2")
        assert t1 is not None
        assert t2 is not None
        assert t1["id"] == "TSK-0001"
        assert t2["id"] == "TSK-0002"

    def test_create_persists_to_disk(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Persisted task")
        raw = json.loads((tmp_path / "tasks.json").read_text())
        assert len(raw) == 1
        assert raw[0]["title"] == "Persisted task"

    def test_update_task(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Original")
        updated = store.update("TSK-0001", status="in_progress", title="Updated")
        assert updated is not None
        assert updated["status"] == "in_progress"
        assert updated["title"] == "Updated"

    def test_update_nonexistent_returns_none(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        result = store.update("TSK-9999", title="Nope")
        assert result is None

    def test_delete_task(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("To delete")
        assert store.delete("TSK-0001") is True
        assert store.get("TSK-0001") is None

    def test_delete_nonexistent_returns_false(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.delete("TSK-9999") is False

    def test_get_existing_task(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Find me")
        task = store.get("TSK-0001")
        assert task is not None
        assert task["title"] == "Find me"

    def test_get_nonexistent_returns_none(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.get("TSK-9999") is None


# ---------------------------------------------------------------------------
# TaskStore: filtering / listing
# ---------------------------------------------------------------------------


class TestTaskStoreList:
    """Tests for TaskStore list_tasks filtering."""

    def test_list_excludes_done_by_default(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Active")
        store.create("Done")
        store.update("TSK-0002", status="done")
        tasks = store.list_tasks(include_done=False)
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Active"

    def test_list_includes_done_when_requested(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Active")
        store.create("Done")
        store.update("TSK-0002", status="done")
        tasks = store.list_tasks(include_done=True)
        assert len(tasks) == 2

    def test_list_filter_by_status(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Pending")
        store.create("Done")
        store.update("TSK-0002", status="done")
        tasks = store.list_tasks(status="done")
        assert len(tasks) == 1
        assert tasks[0]["status"] == "done"

    def test_list_filter_by_priority(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Low", priority="low")
        store.create("High", priority="high")
        tasks = store.list_tasks(priority="high")
        assert len(tasks) == 1
        assert tasks[0]["priority"] == "high"

    def test_list_cancelled_excluded_by_default(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Active")
        store.create("Cancelled")
        store.update("TSK-0002", status="cancelled")
        tasks = store.list_tasks()
        assert len(tasks) == 1


# ---------------------------------------------------------------------------
# TaskStore: limits and cleanup
# ---------------------------------------------------------------------------


class TestTaskStoreLimitsAndCleanup:
    """Tests for max_tasks enforcement and auto-cleanup."""

    def test_max_tasks_enforced(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, max_tasks=5)
        for i in range(5):
            store.create(f"Task {i}")
        result = store.create("Too many")
        assert result is None

    def test_max_tasks_counts_only_active(self, tmp_path: Path) -> None:
        """Completed tasks do not count toward the max_tasks limit."""
        store = _make_store(tmp_path, max_tasks=2)
        store.create("First")
        store.create("Second")
        store.update("TSK-0001", status="done")
        # Now only 1 active — should be able to create another
        result = store.create("Third")
        assert result is not None

    def test_auto_cleanup_removes_old_done(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Old done")
        store.update("TSK-0001", status="done")
        # Manually backdate the updated_at so it falls outside the window
        store._tasks[0]["updated_at"] = (
            datetime.now(timezone.utc) - timedelta(days=10)
        ).isoformat()
        store._save()
        # Reload — constructor runs _cleanup_old_done
        store2 = _make_store(tmp_path)
        assert len(store2._tasks) == 0

    def test_auto_cleanup_keeps_recent_done(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path, show_done_days=7)
        store.create("Recent done")
        store.update("TSK-0001", status="done")
        # updated_at is just now — should survive cleanup
        store2 = _make_store(tmp_path, show_done_days=7)
        assert len(store2._tasks) == 1

    def test_id_counter_survives_reload(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("First")
        store.create("Second")
        store2 = _make_store(tmp_path)
        t3 = store2.create("Third")
        assert t3 is not None
        assert t3["id"] == "TSK-0003"


# ---------------------------------------------------------------------------
# TaskStore: summary and context
# ---------------------------------------------------------------------------


class TestTaskStoreSummaryAndContext:
    """Tests for get_summary() and context_string()."""

    def test_overdue_detection(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        store.create("Overdue", due_date=yesterday)
        summary = store.get_summary()
        assert summary["overdue"] == 1

    def test_due_today_detection(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        store.create("Due today", due_date=today)
        summary = store.get_summary()
        assert summary["due_today"] == 1

    def test_context_string_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.context_string() == "Tasks: none"

    def test_context_string_with_active(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("High prio", priority="high")
        ctx = store.context_string()
        assert "1 active" in ctx
        assert "1 high" in ctx

    def test_context_string_excludes_done(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create("Done task")
        store.update("TSK-0001", status="done")
        assert store.context_string() == "Tasks: none"

    def test_context_string_with_overdue(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        store.create("Late", due_date=yesterday)
        ctx = store.context_string()
        assert "overdue" in ctx


# ---------------------------------------------------------------------------
# Tool execute() methods
# ---------------------------------------------------------------------------


class TestTaskTools:
    """Tests for tool execute() methods — success and error cases."""

    # -- CreateTaskTool --

    @pytest.mark.asyncio
    async def test_create_tool_success(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json")
        tool = CreateTaskTool(store)
        result = await tool.execute(title="Test task", priority="high")
        assert "TSK-0001" in result
        assert "high" in result

    @pytest.mark.asyncio
    async def test_create_tool_invalid_priority(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json")
        tool = CreateTaskTool(store)
        result = await tool.execute(title="Bad", priority="urgent")
        assert "Invalid priority" in result

    @pytest.mark.asyncio
    async def test_create_tool_max_reached(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json", max_tasks=1)
        tool = CreateTaskTool(store)
        await tool.execute(title="First")
        result = await tool.execute(title="Second")
        assert "Task limit reached" in result

    @pytest.mark.asyncio
    async def test_create_tool_default_priority(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json")
        tool = CreateTaskTool(store)
        result = await tool.execute(title="Default prio task")
        assert "medium" in result

    # -- UpdateTaskTool --

    @pytest.mark.asyncio
    async def test_update_tool_success(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json")
        store.create("Original")
        tool = UpdateTaskTool(store)
        result = await tool.execute(task_id="TSK-0001", status="done")
        assert "TSK-0001" in result
        assert "done" in result

    @pytest.mark.asyncio
    async def test_update_tool_not_found(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json")
        tool = UpdateTaskTool(store)
        result = await tool.execute(task_id="TSK-9999", status="done")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_update_tool_invalid_status(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json")
        tool = UpdateTaskTool(store)
        result = await tool.execute(task_id="TSK-0001", status="yolo")
        assert "Invalid status" in result

    @pytest.mark.asyncio
    async def test_update_tool_invalid_priority(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json")
        tool = UpdateTaskTool(store)
        result = await tool.execute(task_id="TSK-0001", priority="asap")
        assert "Invalid priority" in result

    # -- ListTasksTool --

    @pytest.mark.asyncio
    async def test_list_tool_empty(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json")
        tool = ListTasksTool(store)
        result = await tool.execute()
        assert "No tasks found" in result

    @pytest.mark.asyncio
    async def test_list_tool_shows_tasks(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json")
        store.create("Buy milk")
        tool = ListTasksTool(store)
        result = await tool.execute()
        assert "TSK-0001" in result
        assert "Buy milk" in result

    @pytest.mark.asyncio
    async def test_list_tool_overdue_prefix(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        store.create("Overdue task", due_date=yesterday)
        tool = ListTasksTool(store)
        result = await tool.execute()
        assert "[OVERDUE]" in result

    # -- DeleteTaskTool --

    @pytest.mark.asyncio
    async def test_delete_tool_success(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json")
        store.create("Delete me")
        tool = DeleteTaskTool(store)
        result = await tool.execute(task_id="TSK-0001")
        assert "Deleted" in result
        assert store.get("TSK-0001") is None

    @pytest.mark.asyncio
    async def test_delete_tool_not_found(self, tmp_path: Path) -> None:
        store = TaskStore(tmp_path / "tasks.json")
        tool = DeleteTaskTool(store)
        result = await tool.execute(task_id="TSK-9999")
        assert "not found" in result
