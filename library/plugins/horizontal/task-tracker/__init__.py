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
        """Create a new task. Returns None if at max capacity.

        Args:
            title: Task title.
            description: Optional details.
            priority: Task priority — high, medium, or low.
            due_date: Optional due date in YYYY-MM-DD format.

        Returns:
            New task dict, or None if max_tasks limit reached.
        """
        active = [t for t in self._tasks if t["status"] not in DONE_STATUSES]
        if len(active) >= self._max_tasks:
            return None
        now = self._now_iso()
        task: dict[str, Any] = {
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
        """Update a task by ID. Returns None if not found.

        Args:
            task_id: Task ID (e.g. TSK-0001).
            **fields: Fields to update (title, description, status, priority, due_date).

        Returns:
            Updated task dict, or None if not found.
        """
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
        """Delete a task by ID. Returns True if found and deleted.

        Args:
            task_id: Task ID (e.g. TSK-0001).

        Returns:
            True if deleted, False if not found.
        """
        for i, task in enumerate(self._tasks):
            if task["id"] == task_id:
                self._tasks.pop(i)
                self._save()
                return True
        return False

    def get(self, task_id: str) -> dict[str, Any] | None:
        """Get a single task by ID.

        Args:
            task_id: Task ID (e.g. TSK-0001).

        Returns:
            Task dict if found, None otherwise.
        """
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
        """List tasks with optional filters.

        Args:
            status: Filter by exact status (overrides include_done filter).
            priority: Filter by exact priority.
            include_done: If True, include done/cancelled tasks when no status filter is set.

        Returns:
            Filtered list of task dicts.
        """
        result = self._tasks
        if status:
            result = [t for t in result if t["status"] == status]
        elif not include_done:
            result = [t for t in result if t["status"] not in DONE_STATUSES]
        if priority:
            result = [t for t in result if t["priority"] == priority]
        return result

    def get_summary(self) -> dict[str, int]:
        """Get task counts for context provider (single-pass).

        Returns:
            Dict with active, high, due_today, and overdue counts.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        active = 0
        high = 0
        due_today = 0
        overdue = 0
        for t in self._tasks:
            if t["status"] in DONE_STATUSES:
                continue
            active += 1
            if t["priority"] == "high":
                high += 1
            due = t.get("due_date", "")
            if due:
                if due == today:
                    due_today += 1
                elif due < today:
                    overdue += 1
        return {"active": active, "high": high, "due_today": due_today, "overdue": overdue}

    def context_string(self) -> str:
        """One-line context for system prompt injection.

        Returns:
            Summary string like "Tasks: 3 active (1 high, 1 overdue)".
        """
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
    """Tool: create a new task.

    Args:
        store: TaskStore instance to write to.
    """

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "create_task"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Create a new personal task with a title, optional priority "
            "(high/medium/low), and optional due date (YYYY-MM-DD)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "description": {
                    "type": "string",
                    "default": "",
                    "description": "Optional details",
                },
                "priority": {
                    "type": "string",
                    "enum": sorted(VALID_PRIORITIES),
                    "default": "medium",
                },
                "due_date": {
                    "type": "string",
                    "default": "",
                    "description": "Due date in YYYY-MM-DD format",
                },
            },
            "required": ["title"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Create a task and return confirmation.

        Args:
            **kwargs: title (str), description (str), priority (str), due_date (str).

        Returns:
            Confirmation string or error message.
        """
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
            return (
                f"Task limit reached ({self._store._max_tasks}). "
                "Delete or complete existing tasks first."
            )
        return f"Created: {task['id']} — {task['title']} [{task['priority']}]"


class UpdateTaskTool(Tool):
    """Tool: update an existing task.

    Args:
        store: TaskStore instance to write to.
    """

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "update_task"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Update a task's status, title, description, priority, or due date. "
            "Use task ID (e.g. TSK-0001)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID (e.g. TSK-0001)",
                },
                "status": {
                    "type": "string",
                    "enum": sorted(VALID_STATUSES),
                    "default": "",
                },
                "title": {"type": "string", "default": ""},
                "description": {"type": "string", "default": ""},
                "priority": {
                    "type": "string",
                    "enum": sorted(VALID_PRIORITIES),
                    "default": "",
                },
                "due_date": {"type": "string", "default": ""},
            },
            "required": ["task_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Update a task and return confirmation.

        Args:
            **kwargs: task_id (str) required; status, title, description,
                      priority, due_date optional.

        Returns:
            Confirmation string or error message.
        """
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
    """Tool: list tasks with optional filters.

    Args:
        store: TaskStore instance to read from.
    """

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "list_tasks"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "List personal tasks. Optionally filter by status or priority. "
            "Hides completed tasks by default."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "default": "",
                    "description": "Filter by status",
                },
                "priority": {
                    "type": "string",
                    "default": "",
                    "description": "Filter by priority",
                },
                "include_done": {
                    "type": "boolean",
                    "default": False,
                    "description": "Show completed/cancelled tasks",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        """List tasks matching the given filters.

        Args:
            **kwargs: status (str), priority (str), include_done (bool).

        Returns:
            Formatted task list or "No tasks found."
        """
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
            overdue = (
                t.get("due_date")
                and t["due_date"] < today
                and t["status"] not in DONE_STATUSES
            )
            prefix = "[OVERDUE] " if overdue else ""
            due = f" (due {t['due_date']})" if t.get("due_date") else ""
            lines.append(
                f"  {prefix}{t['id']} — {t['title']} [{t['status']}, {t['priority']}]{due}"
            )
        return "\n".join(lines)


class DeleteTaskTool(Tool):
    """Tool: permanently remove a task.

    Args:
        store: TaskStore instance to write to.
    """

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "delete_task"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Permanently delete a task by its ID."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID to delete (e.g. TSK-0001)",
                },
            },
            "required": ["task_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Delete a task by ID.

        Args:
            **kwargs: task_id (str) required.

        Returns:
            Confirmation string or error message.
        """
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

    logger.debug(
        "task_tracker.register: max_tasks=%d, show_done_days=%d",
        max_tasks,
        show_done_days,
    )
