# Phase 2: Personal Assistant — Task Tracker Plugin + Himalaya Email Skill

> Phase 2 of 3. Adds a persistent task tracker plugin and a provider-agnostic email skill to the Velo personal assistant template.

---

## Context

Phase 1 (Plugin Engine v2) upgraded the plugin infrastructure. Phase 2 adds two personal assistant capabilities:

1. **Task Tracker Plugin** — persistent, independent task management with tools and context provider
2. **Himalaya Email Skill** — CLI email client for any IMAP/SMTP provider (Gmail, Outlook, ProtonMail, self-hosted)

### Why These Two

Research into Hermes Agent, OpenClaw, and the 2026 personal assistant market shows that Velo's existing skills + heartbeat + Honcho already cover calendar, briefings, and memory on par with competitors. The two gaps are:

- **No local task persistence** — Velo relies on gws-tasks (Google Tasks API), which is slow, requires Google auth, and doesn't work offline. Hermes has an in-memory TodoStore; we need persistent JSON-backed tasks.
- **No non-Google email** — Velo only supports Gmail via gws CLI. Customers using Outlook, ProtonMail, or any other IMAP provider have no email integration.

---

## 1. Task Tracker Plugin

### 1.1 Overview

| Aspect | Detail |
|--------|--------|
| **Location** | `library/plugins/horizontal/task-tracker/` |
| **Category** | Horizontal (works with any template) |
| **Lifecycle** | `register()` only (no `activate()` needed — no background services) |
| **Storage** | `workspace/tasks.json` (atomic writes) |
| **Dependencies** | None |

### 1.2 Tools (4)

#### `create_task`

```
create_task(title: str, description: str = "", priority: str = "medium", due_date: str = "")
```

- Creates a task with auto-generated ID (`TSK-0001`, `TSK-0002`, ...)
- Priority: `high`, `medium`, `low`
- Due date: optional ISO date string (e.g., `"2026-03-18"`)
- Returns: created task object as formatted string

#### `update_task`

```
update_task(task_id: str, status: str = "", title: str = "", description: str = "", priority: str = "", due_date: str = "")
```

- Updates any provided field by task ID
- Statuses: `pending`, `in_progress`, `done`, `cancelled`
- Returns: updated task object

#### `list_tasks`

```
list_tasks(status: str = "", priority: str = "", include_done: bool = False)
```

- Filters by status and/or priority
- `include_done=False` hides completed/cancelled by default
- Marks overdue tasks with `[OVERDUE]` prefix
- Returns: formatted task list

#### `delete_task`

```
delete_task(task_id: str)
```

- Removes task permanently from storage
- Returns: confirmation string

### 1.3 Context Provider

Injected into every system prompt — one line, always visible:

```
Tasks: 5 active (2 high, 1 due today, 1 overdue)
```

When no tasks exist: `Tasks: none`

This lets the agent proactively mention tasks without the user asking.

### 1.4 Storage Format

`workspace/tasks.json`:

```json
[
  {
    "id": "TSK-0001",
    "title": "Call the dentist",
    "description": "",
    "status": "pending",
    "priority": "medium",
    "due_date": "2026-03-18",
    "created_at": "2026-03-16T14:00:00Z",
    "updated_at": "2026-03-16T14:00:00Z"
  }
]
```

Writes use atomic temp-file + rename pattern (same as `velo/utils/helpers.py:atomic_write`).

### 1.5 Plugin Manifest (`plugin.json`)

```json
{
  "id": "task-tracker",
  "name": "Task Tracker",
  "version": "1.0.0",
  "description": "Persistent personal task management with priorities and due dates.",
  "category": "horizontal",
  "tags": ["productivity", "tasks", "reminders"],
  "config_schema": {
    "max_tasks": {
      "type": "integer",
      "default": 200,
      "label": "Maximum number of tasks",
      "advanced": true
    },
    "show_done_days": {
      "type": "integer",
      "default": 7,
      "label": "Days to keep completed tasks before auto-cleanup",
      "advanced": true
    }
  },
  "requires": {
    "channels": [],
    "env": [],
    "plugins": []
  },
  "hooks": [],
  "tools": ["create_task", "update_task", "list_tasks", "delete_task"],
  "services": false,
  "context_provider": true,
  "used_by_templates": ["personal-productivity"],
  "ui_hints": {
    "icon": "check-square",
    "color": "blue"
  }
}
```

### 1.6 Implementation Structure

```
library/plugins/horizontal/task-tracker/
├── __init__.py    — register() + 4 Tool classes + context provider + TaskStore
└── plugin.json    — manifest
```

Single file (`__init__.py`) since total code is ~250 lines. The `TaskStore` class handles JSON load/save/query. Four tool classes inherit from `Tool` ABC. Context provider reads from `TaskStore`.

### 1.7 Auto-Cleanup

On `register()`, tasks with status `done` or `cancelled` older than `show_done_days` are removed from storage. This prevents unbounded growth.

---

## 2. Himalaya Email Skill

### 2.1 Overview

| Aspect | Detail |
|--------|--------|
| **Location** | `velo/skills/himalaya/` |
| **Type** | Skill (SKILL.md), not a plugin |
| **Binary** | `himalaya` — standalone Rust binary, no runtime deps |
| **Protocols** | IMAP + SMTP (any provider) |
| **Config** | `~/.config/himalaya/config.toml` |

### 2.2 Skill Files

```
velo/skills/himalaya/
├── SKILL.md                  — When to use, common commands, output parsing
└── references/
    └── setup.md              — Installation + provider configs (Gmail, Outlook, generic)
```

### 2.3 SKILL.md — Key Commands

| Action | Command |
|--------|---------|
| List inbox (10 most recent) | `himalaya envelope list --folder INBOX --page-size 10` |
| List unread only | `himalaya envelope list --folder INBOX not flag Seen` |
| Search by sender | `himalaya envelope list --folder INBOX from:boss@company.com` |
| Read message | `himalaya message read <id>` |
| Reply | `himalaya message reply <id>` (opens `$EDITOR` — pipe body via stdin for non-interactive) |
| Reply-all | `himalaya message reply <id> --all` |
| Forward | `himalaya message forward <id>` |
| Send new | Compose via MML template piped to `himalaya message send` |
| Move to folder | `himalaya envelope move <id> INBOX Archive` |
| List folders | `himalaya folder list` |
| JSON output | Add `--output json` to any command |
| Download attachments | `himalaya attachment download <id>` |

**Non-interactive sending** (for agent use):

```bash
himalaya message send <<'EOF'
From: user@example.com
To: recipient@example.com
Subject: Meeting follow-up

Hi, just following up on our meeting earlier today.
EOF
```

### 2.4 references/setup.md — Installation & Provider Configs

**Installation on Linux VPS:**

```bash
curl -sSL https://raw.githubusercontent.com/pimalaya/himalaya/master/install.sh | sudo sh
```

Verify: `himalaya --version` (should show v1.2.0+)

**Config location:** `~/.config/himalaya/config.toml`

**Gmail (App Password — simplest):**

Requires: IMAP enabled, 2-step auth enabled, App Password generated at myaccount.google.com/apppasswords

```toml
[accounts.default]
email = "user@gmail.com"

folder.aliases.inbox = "INBOX"
folder.aliases.sent = "[Gmail]/Sent Mail"
folder.aliases.drafts = "[Gmail]/Drafts"
folder.aliases.trash = "[Gmail]/Trash"

backend.type = "imap"
backend.host = "imap.gmail.com"
backend.port = 993
backend.login = "user@gmail.com"
backend.auth.type = "password"
backend.auth.cmd = "cat /root/.velo/secrets/email_password"

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.gmail.com"
message.send.backend.port = 465
message.send.backend.login = "user@gmail.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "cat /root/.velo/secrets/email_password"
```

**Outlook:**

```toml
[accounts.default]
email = "user@outlook.com"

backend.type = "imap"
backend.host = "outlook.office365.com"
backend.port = 993
backend.login = "user@outlook.com"
backend.auth.type = "password"
backend.auth.cmd = "cat /root/.velo/secrets/email_password"

message.send.backend.type = "smtp"
message.send.backend.host = "smtp-mail.outlook.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "user@outlook.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "cat /root/.velo/secrets/email_password"
```

**Generic IMAP (any provider):**

```toml
[accounts.default]
email = "user@example.com"

backend.type = "imap"
backend.host = "mail.example.com"
backend.port = 993
backend.login = "user@example.com"
backend.auth.type = "password"
backend.auth.cmd = "cat /root/.velo/secrets/email_password"

message.send.backend.type = "smtp"
message.send.backend.host = "mail.example.com"
message.send.backend.port = 465
message.send.backend.login = "user@example.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "cat /root/.velo/secrets/email_password"
```

**Security:** Passwords stored in `/root/.velo/secrets/email_password` (readable only by root), retrieved via `backend.auth.cmd`. Never stored in the TOML config directly.

**Verification:** `himalaya envelope list --page-size 1` — if it returns an email envelope, setup works.

### 2.5 SKILL.md Frontmatter

```yaml
---
name: himalaya
description: |
  CLI email client for any IMAP/SMTP provider (Gmail, Outlook, ProtonMail, self-hosted).
  Use when the user asks about email and they don't use Google Workspace, or when
  himalaya is configured as their email provider. Supports list, read, send, reply,
  forward, search, attachments, and folder management.
metadata:
  requires:
    bins: ["himalaya"]
---
```

---

## 3. Template Updates

### 3.1 personal-productivity manifest.json

Add `task-tracker` to the plugins section:

```json
"plugins": {
  "required": ["task-tracker"],
  "recommended": ["business-hours"],
  "optional": []
}
```

Add himalaya as an alternative email integration:

```json
"mcp_servers": {
  "gws": { ... },
  "himalaya": {
    "optional": true,
    "description": "Email via IMAP/SMTP — use instead of gws for non-Google email providers (Outlook, ProtonMail, etc.)",
    "skills": ["himalaya"],
    "setup_guide": "velo/skills/himalaya/references/setup.md"
  }
}
```

### 3.2 HEARTBEAT.md

Add task check to morning briefing:

```
## Task 1: Morning Briefing
...
3. Fetch tasks due today and overdue tasks via `list_tasks` tool
```

The heartbeat already references tasks — now there's an actual plugin providing the data.

---

## 4. File Changes

### 4.1 New Files

| File | Purpose |
|------|---------|
| `library/plugins/horizontal/task-tracker/__init__.py` | Plugin: TaskStore + 4 tools + context provider |
| `library/plugins/horizontal/task-tracker/plugin.json` | Manifest |
| `velo/skills/himalaya/SKILL.md` | Skill: commands, usage, frontmatter |
| `velo/skills/himalaya/references/setup.md` | Setup: install + provider configs |

### 4.2 Modified Files

| File | Changes |
|------|---------|
| `library/templates/personal-productivity/manifest.json` | Add task-tracker to required plugins, himalaya to optional integrations |

### 4.3 Test Files

| File | Purpose |
|------|---------|
| `tests/plugins/test_task_tracker.py` | Task CRUD, context provider, auto-cleanup, overdue detection, edge cases |

---

## 5. Scope Boundaries

### In Scope

- Task tracker plugin (4 tools, context provider, JSON persistence, auto-cleanup)
- Himalaya email skill (SKILL.md + setup reference)
- Template manifest update
- Tests for task tracker plugin

### Out of Scope

- Google Tasks sync (independent, gws-tasks skill still works separately)
- Recurring tasks (YAGNI — add later if needed)
- Task notifications/reminders (heartbeat already handles this via HEARTBEAT.md)
- Himalaya plugin (it's a skill, not a plugin — no code needed beyond SKILL.md)
- Volos agent deployment skill for himalaya (separate Volos-side work)
- Phase 3 business vertical plugins
