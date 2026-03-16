# Phase 2: Personal Assistant — Task Tracker + Himalaya Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent task tracker plugin and a himalaya email skill to Velo's personal assistant capabilities.

**Architecture:** Task tracker is a horizontal plugin (register-only) with 4 tools, a context provider, and JSON persistence. Himalaya is a SKILL.md file with setup references. Both are independent — no shared code.

**Tech Stack:** Python 3.11+, pytest, JSON file I/O

**Spec:** `docs/superpowers/specs/2026-03-16-personal-assistant-phase2-design.md`

---

## Chunk 1: Task Tracker Plugin

### Task 1: Create TaskStore + plugin.json manifest

**Files:**
- Create: `library/plugins/horizontal/task-tracker/__init__.py`
- Create: `library/plugins/horizontal/task-tracker/plugin.json`
- Test: `tests/plugins/test_task_tracker.py`

- [ ] **Step 1: Write failing tests for TaskStore**

Create `tests/plugins/test_task_tracker.py`:

```python
"""Tests for the task-tracker plugin."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


class TestTaskStore:
    """Tests for TaskStore load/save/query."""

    def _make_store(self, tmp_path: Path):
        # Import here so test fails if module doesn't exist
        from task_tracker import TaskStore
        return TaskStore(tmp_path / "tasks.json", max_tasks=5, show_done_days=7)

    def test_create_task(self, tmp_path):
        store = self._make_store(tmp_path)
        task = store.create("Call dentist", priority="high")
        assert task["id"] == "TSK-0001"
        assert task["title"] == "Call dentist"
        assert task["priority"] == "high"
        assert task["status"] == "pending"

    def test_create_auto_increments_id(self, tmp_path):
        store = self._make_store(tmp_path)
        t1 = store.create("Task 1")
        t2 = store.create("Task 2")
        assert t1["id"] == "TSK-0001"
        assert t2["id"] == "TSK-0002"

    def test_create_persists_to_disk(self, tmp_path):
        store = self._make_store(tmp_path)
        store.create("Persisted task")
        raw = json.loads((tmp_path / "tasks.json").read_text())
        assert len(raw) == 1
        assert raw[0]["title"] == "Persisted task"

    def test_update_task(self, tmp_path):
        store = self._make_store(tmp_path)
        store.create("Original")
        updated = store.update("TSK-0001", status="in_progress", title="Updated")
        assert updated["status"] == "in_progress"
        assert updated["title"] == "Updated"

    def test_update_nonexistent_returns_none(self, tmp_path):
        store = self._make_store(tmp_path)
        result = store.update("TSK-9999", title="Nope")
        assert result is None

    def test_delete_task(self, tmp_path):
        store = self._make_store(tmp_path)
        store.create("To delete")
        assert store.delete("TSK-0001") is True
        assert store.get("TSK-0001") is None

    def test_delete_nonexistent_returns_false(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.delete("TSK-9999") is False

    def test_list_excludes_done_by_default(self, tmp_path):
        store = self._make_store(tmp_path)
        store.create("Active")
        store.create("Done")
        store.update("TSK-0002", status="done")
        tasks = store.list_tasks(include_done=False)
        assert len(tasks) == 1
        assert tasks[0]["title"] == "Active"

    def test_list_includes_done_when_requested(self, tmp_path):
        store = self._make_store(tmp_path)
        store.create("Active")
        store.create("Done")
        store.update("TSK-0002", status="done")
        tasks = store.list_tasks(include_done=True)
        assert len(tasks) == 2

    def test_list_filter_by_status(self, tmp_path):
        store = self._make_store(tmp_path)
        store.create("Pending")
        store.create("Done")
        store.update("TSK-0002", status="done")
        tasks = store.list_tasks(status="done")
        assert len(tasks) == 1
        assert tasks[0]["status"] == "done"

    def test_list_filter_by_priority(self, tmp_path):
        store = self._make_store(tmp_path)
        store.create("Low", priority="low")
        store.create("High", priority="high")
        tasks = store.list_tasks(priority="high")
        assert len(tasks) == 1
        assert tasks[0]["priority"] == "high"

    def test_max_tasks_enforced(self, tmp_path):
        store = self._make_store(tmp_path)  # max_tasks=5
        for i in range(5):
            store.create(f"Task {i}")
        result = store.create("Too many")
        assert result is None

    def test_auto_cleanup_removes_old_done(self, tmp_path):
        store = self._make_store(tmp_path)
        store.create("Old done")
        store.update("TSK-0001", status="done")
        # Manually backdate the updated_at
        store._tasks[0]["updated_at"] = (
            datetime.now(timezone.utc) - timedelta(days=10)
        ).isoformat()
        store._save()
        # Reload triggers cleanup
        store2 = self._make_store(tmp_path)
        assert len(store2._tasks) == 0

    def test_overdue_detection(self, tmp_path):
        store = self._make_store(tmp_path)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        store.create("Overdue", due_date=yesterday)
        summary = store.get_summary()
        assert summary["overdue"] == 1

    def test_context_string(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.context_string() == "Tasks: none"
        store.create("High prio", priority="high")
        ctx = store.context_string()
        assert "1 active" in ctx
        assert "1 high" in ctx
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/plugins/test_task_tracker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'task_tracker'`

- [ ] **Step 3: Create plugin.json manifest**

Create `library/plugins/horizontal/task-tracker/plugin.json` with the exact content from spec Section 1.5.

- [ ] **Step 4: Implement `__init__.py`**

Create `library/plugins/horizontal/task-tracker/__init__.py`:

```python
"""Task tracker plugin — persistent personal task management.

Tools registered:
    create_task — create a new task with title, priority, due date
    update_task — update task status, title, description, priority, due date
    list_tasks — list tasks with optional filters
    delete_task — permanently remove a task

Context provider:
    One-line summary: "Tasks: N active (X high, Y due today, Z overdue)"

Config keys:
    max_tasks (int): Maximum tasks allowed. Default 200.
    show_done_days (int): Days to keep done/cancelled tasks. Default 7.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from velo.agent.tools.base import Tool
from velo.plugins.types import PluginContext
from velo.utils.helpers import atomic_write

logger = logging.getLogger(__name__)

VALID_STATUSES = {"pending", "in_progress", "done", "cancelled"}
VALID_PRIORITIES = {"high", "medium", "low"}
DONE_STATUSES = {"done", "cancelled"}


class TaskStore:
    """JSON-backed task storage with query and summary capabilities.

    Args:
        path: Path to tasks.json file.
        max_tasks: Maximum number of tasks allowed.
        show_done_days: Days to keep completed/cancelled tasks.
    """

    def __init__(self, path: Path, max_tasks: int = 200, show_done_days: int = 7) -> None:
        self._path = path
        self._max_tasks = max_tasks
        self._show_done_days = show_done_days
        self._tasks: list[dict[str, Any]] = []
        self._next_id = 1
        self._load()
        self._cleanup_old_done()

    def _load(self) -> None:
        """Load tasks from disk."""
        if self._path.is_file():
            try:
                self._tasks = json.loads(self._path.read_text(encoding="utf-8"))
                if self._tasks:
                    max_num = max(int(t["id"].split("-")[1]) for t in self._tasks)
                    self._next_id = max_num + 1
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.warning("task_tracker.load_failed: %s", self._path)
                self._tasks = []

    def _save(self) -> None:
        """Write tasks to disk atomically."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self._path, json.dumps(self._tasks, indent=2, ensure_ascii=False))

    def _cleanup_old_done(self) -> None:
        """Remove done/cancelled tasks older than show_done_days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._show_done_days)
        before = len(self._tasks)
        self._tasks = [
            t for t in self._tasks
            if t["status"] not in DONE_STATUSES
            or datetime.fromisoformat(t["updated_at"]) > cutoff
        ]
        if len(self._tasks) < before:
            self._save()

    def _now_iso(self) -> str:
        """Return current UTC time as ISO string."""
        return datetime.now(timezone.utc).isoformat()

    def create(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        due_date: str = "",
    ) -> dict[str, Any] | None:
        """Create a new task. Returns None if at max capacity."""
        active = [t for t in self._tasks if t["status"] not in DONE_STATUSES]
        if len(active) >= self._max_tasks:
            return None
        now = self._now_iso()
        task = {
            "id": f"TSK-{self._next_id:04d}",
            "title": title,
            "description": description,
            "status": "pending",
            "priority": priority,
            "due_date": due_date,
            "created_at": now,
            "updated_at": now,
        }
        self._next_id += 1
        self._tasks.append(task)
        self._save()
        return task

    def update(self, task_id: str, **fields: Any) -> dict[str, Any] | None:
        """Update a task by ID. Returns None if not found."""
        for task in self._tasks:
            if task["id"] == task_id:
                for key, value in fields.items():
                    if value and key in task:
                        task[key] = value
                task["updated_at"] = self._now_iso()
                self._save()
                return task
        return None

    def delete(self, task_id: str) -> bool:
        """Delete a task by ID. Returns True if found and deleted."""
        for i, task in enumerate(self._tasks):
            if task["id"] == task_id:
                self._tasks.pop(i)
                self._save()
                return True
        return False

    def get(self, task_id: str) -> dict[str, Any] | None:
        """Get a single task by ID."""
        for task in self._tasks:
            if task["id"] == task_id:
                return task
        return None

    def list_tasks(
        self,
        status: str = "",
        priority: str = "",
        include_done: bool = False,
    ) -> list[dict[str, Any]]:
        """List tasks with optional filters."""
        result = self._tasks
        if status:
            result = [t for t in result if t["status"] == status]
        elif not include_done:
            result = [t for t in result if t["status"] not in DONE_STATUSES]
        if priority:
            result = [t for t in result if t["priority"] == priority]
        return result

    def get_summary(self) -> dict[str, int]:
        """Get task counts for context provider."""
        active = [t for t in self._tasks if t["status"] not in DONE_STATUSES]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {
            "active": len(active),
            "high": sum(1 for t in active if t["priority"] == "high"),
            "due_today": sum(1 for t in active if t.get("due_date") == today),
            "overdue": sum(
                1 for t in active
                if t.get("due_date") and t["due_date"] < today
            ),
        }

    def context_string(self) -> str:
        """One-line context for system prompt injection."""
        s = self.get_summary()
        if s["active"] == 0:
            return "Tasks: none"
        parts = [f"{s['active']} active"]
        if s["high"]:
            parts.append(f"{s['high']} high")
        if s["due_today"]:
            parts.append(f"{s['due_today']} due today")
        if s["overdue"]:
            parts.append(f"{s['overdue']} overdue")
        return f"Tasks: {', '.join(parts)}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class CreateTaskTool(Tool):
    """Tool: create a new task."""

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "create_task"

    @property
    def description(self) -> str:
        return "Create a new personal task with a title, optional priority (high/medium/low), and optional due date (YYYY-MM-DD)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "description": {"type": "string", "default": "", "description": "Optional details"},
                "priority": {"type": "string", "enum": ["high", "medium", "low"], "default": "medium"},
                "due_date": {"type": "string", "default": "", "description": "Due date in YYYY-MM-DD format"},
            },
            "required": ["title"],
        }

    async def execute(self, **kwargs: Any) -> str:
        title = str(kwargs.get("title", ""))
        priority = str(kwargs.get("priority", "medium"))
        if priority and priority not in VALID_PRIORITIES:
            return f"Invalid priority '{priority}'. Valid: high, medium, low"
        task = self._store.create(
            title=title,
            description=str(kwargs.get("description", "")),
            priority=priority,
            due_date=str(kwargs.get("due_date", "")),
        )
        if task is None:
            return f"Task limit reached ({self._store._max_tasks}). Delete or complete existing tasks first."
        return f"Created: {task['id']} — {task['title']} [{task['priority']}]"


class UpdateTaskTool(Tool):
    """Tool: update an existing task."""

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "update_task"

    @property
    def description(self) -> str:
        return "Update a task's status, title, description, priority, or due date. Use task ID (e.g. TSK-0001)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID (e.g. TSK-0001)"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "done", "cancelled"], "default": ""},
                "title": {"type": "string", "default": ""},
                "description": {"type": "string", "default": ""},
                "priority": {"type": "string", "enum": ["high", "medium", "low"], "default": ""},
                "due_date": {"type": "string", "default": ""},
            },
            "required": ["task_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        task_id = str(kwargs.get("task_id", ""))
        status = str(kwargs.get("status", ""))
        priority = str(kwargs.get("priority", ""))
        if status and status not in VALID_STATUSES:
            return f"Invalid status '{status}'. Valid: pending, in_progress, done, cancelled"
        if priority and priority not in VALID_PRIORITIES:
            return f"Invalid priority '{priority}'. Valid: high, medium, low"
        fields = {k: v for k, v in kwargs.items() if k != "task_id" and v}
        task = self._store.update(task_id, **fields)
        if task is None:
            return f"Task {task_id} not found."
        return f"Updated: {task['id']} — {task['title']} [{task['status']}, {task['priority']}]"


class ListTasksTool(Tool):
    """Tool: list tasks with optional filters."""

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "list_tasks"

    @property
    def description(self) -> str:
        return "List personal tasks. Optionally filter by status or priority. Hides completed tasks by default."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string", "default": "", "description": "Filter by status"},
                "priority": {"type": "string", "default": "", "description": "Filter by priority"},
                "include_done": {"type": "boolean", "default": False, "description": "Show completed/cancelled tasks"},
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        tasks = self._store.list_tasks(
            status=str(kwargs.get("status", "")),
            priority=str(kwargs.get("priority", "")),
            include_done=bool(kwargs.get("include_done", False)),
        )
        if not tasks:
            return "No tasks found."
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = [f"Found {len(tasks)} task(s):\n"]
        for t in tasks:
            overdue = t.get("due_date") and t["due_date"] < today and t["status"] not in DONE_STATUSES
            prefix = "[OVERDUE] " if overdue else ""
            due = f" (due {t['due_date']})" if t.get("due_date") else ""
            lines.append(f"  {prefix}{t['id']} — {t['title']} [{t['status']}, {t['priority']}]{due}")
        return "\n".join(lines)


class DeleteTaskTool(Tool):
    """Tool: permanently remove a task."""

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "delete_task"

    @property
    def description(self) -> str:
        return "Permanently delete a task by its ID."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to delete (e.g. TSK-0001)"},
            },
            "required": ["task_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        task_id = str(kwargs.get("task_id", ""))
        if self._store.delete(task_id):
            return f"Deleted task {task_id}."
        return f"Task {task_id} not found."


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def register(ctx: PluginContext) -> None:
    """Plugin entry point — register task tools and context provider.

    Args:
        ctx: Plugin context with config and workspace.
    """
    max_tasks = int(ctx.config.get("max_tasks", 200))
    show_done_days = int(ctx.config.get("show_done_days", 7))

    store = TaskStore(
        path=ctx.workspace / "tasks.json",
        max_tasks=max_tasks,
        show_done_days=show_done_days,
    )

    ctx.register_tool(CreateTaskTool(store))
    ctx.register_tool(UpdateTaskTool(store))
    ctx.register_tool(ListTasksTool(store))
    ctx.register_tool(DeleteTaskTool(store))
    ctx.add_context_provider(store.context_string)

    logger.debug("task_tracker.register: max_tasks=%d, show_done_days=%d", max_tasks, show_done_days)
```

- [ ] **Step 5: Fix test imports**

The tests import `from task_tracker import TaskStore` but the plugin isn't a proper Python package (it's loaded by the plugin manager via importlib). Update tests to import the `TaskStore` by adding the library path or importing directly:

```python
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "library" / "plugins" / "horizontal" / "task-tracker"))
from __init__ import TaskStore  # noqa: E402
```

Or alternatively, write tests that use the PluginManager to load the plugin (following the pattern in `tests/plugins/test_lifecycle.py`). Choose whichever works — the key is that tests exercise `TaskStore` directly.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/plugins/test_task_tracker.py -v`
Expected: All 16 tests PASS

- [ ] **Step 7: Commit**

```bash
git add library/plugins/horizontal/task-tracker/ tests/plugins/test_task_tracker.py
git commit -m "feat(plugins): add task-tracker plugin with 4 tools, context provider, JSON persistence"
```

---

### Task 2: Add tool execution tests

**Files:**
- Extend: `tests/plugins/test_task_tracker.py`

- [ ] **Step 1: Add tool execution tests**

Append to `tests/plugins/test_task_tracker.py`:

```python
class TestTaskTools:
    """Test the tool execute() methods directly."""

    def _make_store(self, tmp_path: Path):
        from __init__ import TaskStore
        return TaskStore(tmp_path / "tasks.json", max_tasks=5, show_done_days=7)

    @pytest.mark.asyncio
    async def test_create_tool(self, tmp_path):
        from __init__ import CreateTaskTool, TaskStore
        store = TaskStore(tmp_path / "tasks.json")
        tool = CreateTaskTool(store)
        result = await tool.execute(title="Test task", priority="high")
        assert "TSK-0001" in result
        assert "high" in result

    @pytest.mark.asyncio
    async def test_create_tool_invalid_priority(self, tmp_path):
        from __init__ import CreateTaskTool, TaskStore
        store = TaskStore(tmp_path / "tasks.json")
        tool = CreateTaskTool(store)
        result = await tool.execute(title="Bad", priority="urgent")
        assert "Invalid priority" in result

    @pytest.mark.asyncio
    async def test_update_tool_not_found(self, tmp_path):
        from __init__ import UpdateTaskTool, TaskStore
        store = TaskStore(tmp_path / "tasks.json")
        tool = UpdateTaskTool(store)
        result = await tool.execute(task_id="TSK-9999", status="done")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_update_tool_invalid_status(self, tmp_path):
        from __init__ import UpdateTaskTool, TaskStore
        store = TaskStore(tmp_path / "tasks.json")
        tool = UpdateTaskTool(store)
        result = await tool.execute(task_id="TSK-0001", status="yolo")
        assert "Invalid status" in result

    @pytest.mark.asyncio
    async def test_list_tool_empty(self, tmp_path):
        from __init__ import ListTasksTool, TaskStore
        store = TaskStore(tmp_path / "tasks.json")
        tool = ListTasksTool(store)
        result = await tool.execute()
        assert "No tasks found" in result

    @pytest.mark.asyncio
    async def test_delete_tool_not_found(self, tmp_path):
        from __init__ import DeleteTaskTool, TaskStore
        store = TaskStore(tmp_path / "tasks.json")
        tool = DeleteTaskTool(store)
        result = await tool.execute(task_id="TSK-9999")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_create_tool_max_reached(self, tmp_path):
        from __init__ import CreateTaskTool, TaskStore
        store = TaskStore(tmp_path / "tasks.json", max_tasks=1)
        tool = CreateTaskTool(store)
        await tool.execute(title="First")
        result = await tool.execute(title="Second")
        assert "Task limit reached" in result
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/plugins/test_task_tracker.py -v`
Expected: All PASS (23 tests total)

- [ ] **Step 3: Commit**

```bash
git add tests/plugins/test_task_tracker.py
git commit -m "test(plugins): add tool execution tests for task-tracker"
```

---

## Chunk 2: Himalaya Email Skill

### Task 3: Create himalaya SKILL.md and setup reference

**Files:**
- Create: `velo/skills/himalaya/SKILL.md`
- Create: `velo/skills/himalaya/references/setup.md`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p velo/skills/himalaya/references
```

- [ ] **Step 2: Create SKILL.md**

Write `velo/skills/himalaya/SKILL.md` with the full content from spec Sections 2.3 and 2.5. Include:
- YAML frontmatter (name, description, metadata.requires.bins)
- Overview paragraph
- Command reference table
- Non-interactive sending example
- JSON output parsing guidance
- Tips for the agent (always use `--output json` for structured parsing, IDs are per-folder)

- [ ] **Step 3: Create references/setup.md**

Write `velo/skills/himalaya/references/setup.md` with the full content from spec Section 2.4. Include:
- Linux VPS installation command (curl)
- Gmail config template (App Password)
- Outlook config template
- Generic IMAP config template
- Security notes (password stored in /root/.velo/secrets/)
- Verification command

- [ ] **Step 4: Commit**

```bash
git add velo/skills/himalaya/
git commit -m "feat(skills): add himalaya email skill for IMAP/SMTP providers"
```

---

## Chunk 3: Template Update + Final Verification

### Task 4: Update personal-productivity template manifest

**Files:**
- Modify: `library/templates/personal-productivity/manifest.json`

- [ ] **Step 1: Read current manifest**

Read `library/templates/personal-productivity/manifest.json` to see current state.

- [ ] **Step 2: Add task-tracker to plugins.required**

Change:
```json
"required": []
```
To:
```json
"required": ["task-tracker"]
```

- [ ] **Step 3: Add himalaya to mcp_servers**

Add after the existing `search_the_web` entry:
```json
"himalaya": {
  "optional": true,
  "description": "Email via IMAP/SMTP — use instead of gws for non-Google email providers (Outlook, ProtonMail, etc.)",
  "skills": ["himalaya"],
  "setup_guide": "velo/skills/himalaya/references/setup.md"
}
```

- [ ] **Step 4: Commit**

```bash
git add library/templates/personal-productivity/manifest.json
git commit -m "feat(templates): add task-tracker and himalaya to personal-productivity"
```

---

### Task 5: Run full test suite and verify

- [ ] **Step 1: Run all plugin tests**

Run: `uv run pytest tests/plugins/ -v`
Expected: All pass, including new task-tracker tests

- [ ] **Step 2: Run linter**

Run: `uv run ruff check library/plugins/horizontal/task-tracker/ velo/skills/himalaya/`
Run: `uv run ruff format library/plugins/horizontal/task-tracker/`

- [ ] **Step 3: Verify skill loads**

Check that the himalaya SKILL.md frontmatter is valid YAML:
```bash
python -c "import yaml; yaml.safe_load(open('velo/skills/himalaya/SKILL.md').read().split('---')[1]); print('OK')"
```

- [ ] **Step 4: Final commit if any fixes needed**

---

## Summary

| Task | What It Delivers |
|------|-----------------|
| 1 | TaskStore + 4 tools + context provider + manifest + 16 tests |
| 2 | Tool execution tests (error handling, edge cases) |
| 3 | Himalaya SKILL.md + setup reference (Gmail, Outlook, generic) |
| 4 | Template manifest update (task-tracker required, himalaya optional) |
| 5 | Full verification |
