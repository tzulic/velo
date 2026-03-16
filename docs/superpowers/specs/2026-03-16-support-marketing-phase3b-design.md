# Phase 3B: Support Resolution + Marketing Ops

> Phase 3B of 3. Adds policy-enforced resolution guard for customer service and structured campaign reporting for marketing ops.

---

## Context

Phase 3A added SDR plugins (follow-up sequencer, contact manager, CRM sync). Phase 3B completes the business vertical plugin library with support resolution and marketing operations.

### Why These Two

From demand research:
- **Support:** "The #1 Reddit complaint is 'it's just a glorified chatbot.'" The existing support plugins (ticket-tracker, sla-monitor, csat-survey, escalation-manager) track issues but can't resolve them. The resolution guard adds policy enforcement and audit trails for when the agent takes consequential actions via Composio MCP tools (1000+ integrations).
- **Marketing:** Agencies spend $10-100K/mo on content/ads. The most valuable capability is "what changed, why, and what to do next" — not just dashboards. A structured report store enables trend tracking and period comparison.

### Design Decisions

**Resolution guard is NOT a Stripe/Shopify wrapper.** The agent already has access to any Composio MCP tool. The plugin adds what's missing: guardrails (policy enforcement via `before_tool_call` hook) and accountability (audit trail). This is what Ada and Sierra do — the agent can act, but within defined limits.

**Campaign reporter stores data, doesn't collect it.** The agent collects metrics from whatever sources are connected (GA4, ad platforms, web search). The plugin provides structured storage, trend comparison, and scheduled report generation.

---

## 1. Resolution Guard Plugin

### 1.1 Overview

| Aspect | Detail |
|--------|--------|
| **Location** | `library/plugins/horizontal/resolution-guard/` |
| **Category** | Horizontal (works with any template — support, SDR, any agent taking consequential actions) |
| **Lifecycle** | `register()` only (no background services) |
| **Storage** | `workspace/resolution_audit.json` (atomic writes) |
| **Dependencies** | None |

### 1.2 Hook: `before_tool_call`

Intercepts tool calls matching configurable patterns and enforces policies:

```python
async def _guard(value: dict, tool_name: str, **kwargs) -> dict | None:
    # 1. Check if tool name matches any tracked pattern
    if not any(p in tool_name.lower() for p in track_patterns):
        return value  # Not a resolution action, pass through

    # 2. Check blocked actions
    if tool_name in blocked_actions:
        return {"__block": True}

    # 3. Check approval-required actions
    if tool_name in require_approval:
        return {"__block": True}

    # 4. Check amount limits (for refund-like actions)
    amount = value.get("amount") or value.get("refund_amount") or 0
    if isinstance(amount, (int, float)) and amount > max_refund:
        return {"__block": True}

    # 5. Allowed — log to audit trail and pass through
    audit_log.append({"tool": tool_name, "params": value, "timestamp": now, "outcome": "allowed"})
    return value
```

When blocked, the agent sees the block and should escalate to a human (via escalation-manager if available) or explain the policy to the customer.

### 1.3 Tools (2)

#### `get_audit_log`

```
get_audit_log(limit: int = 20, action_type: str = "")
```

- Returns recent resolution actions from the audit trail
- Filterable by action type (tool name pattern)
- Shows: timestamp, tool name, outcome (allowed/blocked), key params
- Returns: formatted list

#### `get_resolution_stats`

```
get_resolution_stats(days: int = 7)
```

- Returns stats for the last N days
- Total actions, blocked count, most common action types, total refund amount
- Returns: formatted summary

#### Error Handling

- `get_audit_log` with no entries: return "No resolution actions recorded yet."
- Invalid `days` in `get_resolution_stats`: default to 7

### 1.4 Context Provider

```
Resolutions: 5 actions today (2 refunds totaling $150, 1 blocked)
```

When no actions: `Resolutions: none today`

### 1.5 Storage Format

`workspace/resolution_audit.json`:

```json
[
  {
    "id": "RES-0001",
    "tool_name": "stripe_create_refund",
    "params": {"amount": 4999, "charge_id": "ch_xxx"},
    "outcome": "allowed",
    "timestamp": "2026-03-16T14:30:00Z"
  },
  {
    "id": "RES-0002",
    "tool_name": "shopify_cancel_order",
    "params": {"order_id": "12345"},
    "outcome": "blocked",
    "reason": "Action requires human approval",
    "timestamp": "2026-03-16T14:35:00Z"
  }
]
```

Capped at `max_audit_entries` (default 1000). Oldest entries removed when cap reached.

### 1.6 Plugin Manifest

```json
{
  "id": "resolution-guard",
  "name": "Resolution Guard",
  "version": "1.0.0",
  "description": "Policy enforcement and audit trail for consequential agent actions. Intercepts MCP tool calls, enforces limits, and logs all resolution actions.",
  "category": "horizontal",
  "tags": ["support", "policy", "audit", "guardrails"],
  "config_schema": {
    "track_patterns": {
      "type": "array",
      "default": ["refund", "cancel", "delete", "update_order", "modify_subscription"],
      "label": "Tool name patterns to track",
      "help": "Any tool whose name contains one of these patterns will be policy-checked and audited"
    },
    "max_refund_amount": {
      "type": "integer",
      "default": 100,
      "label": "Maximum refund amount without human approval (in cents)"
    },
    "require_approval_actions": {
      "type": "array",
      "default": ["cancel_subscription", "delete_account"],
      "label": "Actions that always require human approval"
    },
    "blocked_actions": {
      "type": "array",
      "default": [],
      "label": "Actions the agent must never take",
      "advanced": true
    },
    "max_audit_entries": {
      "type": "integer",
      "default": 1000,
      "label": "Maximum audit log entries",
      "advanced": true
    }
  },
  "requires": {
    "channels": [],
    "env": [],
    "plugins": []
  },
  "hooks": ["before_tool_call"],
  "tools": ["get_audit_log", "get_resolution_stats"],
  "services": false,
  "context_provider": true,
  "used_by_templates": ["customer-support"],
  "ui_hints": {
    "icon": "shield",
    "color": "red"
  }
}
```

### 1.7 Implementation Structure

```
library/plugins/horizontal/resolution-guard/
├── __init__.py    — register() + AuditStore + guard hook + 2 tools + context provider
└── plugin.json    — manifest
```

Single file, register-only. The guard hook and tools both operate on the same `AuditStore` instance.

---

## 2. Campaign Reporter Plugin

### 2.1 Overview

| Aspect | Detail |
|--------|--------|
| **Location** | `library/plugins/vertical/marketing/campaign-reporter/` |
| **Category** | Vertical (Marketing) |
| **Lifecycle** | `register()` + `activate()` (needs scheduled service) |
| **Storage** | `workspace/marketing_reports.json` (atomic writes) |
| **Dependencies** | None |

### 2.2 Tools (4)

#### `save_report`

```
save_report(period: str, metrics: str, summary: str = "")
```

- `period`: report period label (e.g., "2026-W12", "2026-03", "2026-03-16")
- `metrics`: JSON string of key-value pairs (e.g., `{"sessions": 1200, "conversions": 45}`)
- `summary`: optional narrative ("Traffic up 15% from LinkedIn campaign")
- Auto-generates ID (`RPT-0001`)
- Returns: confirmation with ID

#### `get_report`

```
get_report(period: str = "", report_id: str = "")
```

- Retrieve by period label or report ID
- Returns: formatted report with all metrics and summary

#### `compare_periods`

```
compare_periods(period_a: str, period_b: str)
```

- Compares metrics between two saved reports
- Returns: delta for each metric with percentage change
- Example output:
  ```
  Comparing 2026-W11 vs 2026-W12:
    Sessions: 1200 → 1400 (+16.7%)
    Conversions: 45 → 52 (+15.6%)
    Ad spend: $500 → $480 (-4.0%)
  ```

#### `list_reports`

```
list_reports(limit: int = 10)
```

- Lists recent reports, newest first
- Shows: period, date saved, metric count, summary preview
- Returns: formatted list

#### Error Handling

- **Invalid metrics JSON:** `"Invalid metrics format. Provide a JSON object with numeric values."`
- **Period not found in compare:** `"No report found for period '{period}'."`
- **Report not found:** `"Report {id} not found."`
- **Max reports reached:** oldest report removed automatically (FIFO)

### 2.3 Background Service

`ReportScheduler` — RuntimeAware service:
- Runs weekly on configured day/time
- Sends prompt via `process_direct`: "Generate this week's marketing report. Check connected analytics sources, compile key metrics, and save with `save_report`."
- The agent collects data from whatever is available (Composio MCPs, web search, manual input)
- Uses session key `"reporter:weekly"` — isolated from user conversations
- Timer: asyncio task with sleep loop (same pattern as heartbeat, follow-up-sequencer)

### 2.4 Context Provider

```
Marketing: 12 reports saved, latest: 2026-W11 (sessions: 1400, conversions: 52)
```

When no reports: `Marketing: no reports yet`

### 2.5 Data Model

`workspace/marketing_reports.json`:

```json
[
  {
    "id": "RPT-0001",
    "period": "2026-W12",
    "metrics": {
      "sessions": 1200,
      "conversions": 45,
      "ad_spend": 500,
      "leads_generated": 12
    },
    "summary": "LinkedIn campaign drove 40% of traffic. Google Ads CPC up 10%.",
    "created_at": "2026-03-16T09:00:00Z"
  }
]
```

### 2.6 Plugin Manifest

```json
{
  "id": "campaign-reporter",
  "name": "Campaign Reporter",
  "version": "1.0.0",
  "description": "Structured marketing report storage with trend tracking and period comparison. Generates scheduled weekly reports.",
  "category": "vertical",
  "tags": ["marketing", "analytics", "reporting", "campaigns"],
  "config_schema": {
    "schedule_day": {
      "type": "string",
      "default": "monday",
      "enum": ["monday", "tuesday", "wednesday", "thursday", "friday"],
      "label": "Day to generate weekly report"
    },
    "schedule_time": {
      "type": "string",
      "default": "09:00",
      "label": "Time to generate report (HH:MM)"
    },
    "max_reports": {
      "type": "integer",
      "default": 200,
      "label": "Maximum reports stored",
      "advanced": true
    }
  },
  "requires": {
    "channels": [],
    "env": [],
    "plugins": []
  },
  "hooks": [],
  "tools": ["save_report", "get_report", "compare_periods", "list_reports"],
  "services": true,
  "context_provider": true,
  "used_by_templates": [],
  "ui_hints": {
    "icon": "bar-chart",
    "color": "teal"
  }
}
```

### 2.7 Implementation Structure

```
library/plugins/vertical/marketing/campaign-reporter/
├── __init__.py    — register() + activate() + ReportStore + 4 tools + ReportScheduler + context
└── plugin.json    — manifest
```

Single file. `ReportScheduler` follows the same RuntimeAware + module-level instance pattern as follow-up-sequencer.

---

## 3. Competitor Monitor Skill

### 3.1 Overview

| Aspect | Detail |
|--------|--------|
| **Location** | `velo/skills/competitor-monitor/` |
| **Type** | Skill (SKILL.md), not a plugin |
| **Dependencies** | Web search (builtin) |

### 3.2 Skill Files

```
velo/skills/competitor-monitor/
├── SKILL.md                          — When/how to monitor, formatting guide
└── references/
    └── monitoring-playbook.md        — Detailed checklist by competitor type
```

### 3.3 SKILL.md Content

**Frontmatter:**

```yaml
---
name: competitor-monitor
description: |
  Monitor competitor websites, pricing, product launches, and hiring patterns.
  Use when the user asks to track competitors, or as a recurring heartbeat task.
  Uses web search to check for changes — no special integrations needed.
metadata:
  requires:
    bins: ["curl"]
---
```

**What to monitor:**
- Pricing page changes (price increases, new tiers, feature additions)
- Blog posts and product announcements
- Job postings (hiring signals — new roles indicate strategic direction)
- Social media activity (Twitter/LinkedIn posts)
- Technology stack changes (via BuiltWith or similar)

**How to store findings:**
- Append to `workspace/competitor-notes.md` with date and source
- Format: `## [Date] — [Competitor] — [Finding type]\n[Details]\n[Source URL]`

**When to alert:**
- Significant pricing changes
- New product launches or feature announcements
- Major hiring surges (5+ new roles in a week)
- Don't alert on routine blog posts or minor updates

### 3.4 references/monitoring-playbook.md

Detailed monitoring checklist organized by competitor type:

**SaaS competitors:** pricing page, changelog, blog, careers page, G2/Capterra reviews
**E-commerce competitors:** product catalog, pricing, promotions, shipping policies
**Agency competitors:** case studies, team page, service offerings, client logos

Each section includes example web search queries and what to look for.

---

## 4. Template Updates

### 4.1 customer-support manifest.json

Add resolution-guard to recommended plugins:

```json
"plugins": {
  "required": ["escalation-manager"],
  "recommended": ["business-hours", "resolution-guard"],
  "optional": ["webhook-receiver", "csat-survey"]
}
```

---

## 5. File Changes

### 5.1 New Files

| File | Purpose |
|------|---------|
| `library/plugins/horizontal/resolution-guard/__init__.py` | Plugin: AuditStore + guard hook + 2 tools + context |
| `library/plugins/horizontal/resolution-guard/plugin.json` | Manifest |
| `library/plugins/vertical/marketing/campaign-reporter/__init__.py` | Plugin: ReportStore + 4 tools + scheduler + context |
| `library/plugins/vertical/marketing/campaign-reporter/plugin.json` | Manifest |
| `velo/skills/competitor-monitor/SKILL.md` | Skill: monitoring guide |
| `velo/skills/competitor-monitor/references/monitoring-playbook.md` | Reference: detailed checklist |
| `tests/plugins/test_resolution_guard.py` | Guard hook tests, audit log, policy checks |
| `tests/plugins/test_campaign_reporter.py` | Report CRUD, comparison, context string |

### 5.2 Modified Files

| File | Changes |
|------|---------|
| `library/templates/customer-support/manifest.json` | Add resolution-guard to recommended |

### 5.3 Test Coverage

| Test File | What It Covers |
|-----------|---------------|
| `test_resolution_guard.py` | Policy matching (track patterns, blocked, approval-required), amount limits, audit logging, passthrough for non-tracked tools, stats calculation, context string, cap enforcement |
| `test_campaign_reporter.py` | Report CRUD, period comparison (deltas + percentages), invalid metrics, max reports FIFO, context string, list formatting |

---

## 6. Scope Boundaries

### In Scope

- Resolution guard plugin (before_tool_call hook, audit log, policy enforcement, 2 tools, context provider)
- Campaign reporter plugin (4 tools, report storage, trend comparison, scheduled service, context provider)
- Competitor monitor skill (SKILL.md + monitoring playbook reference)
- customer-support template manifest update
- Tests for both plugins

### Out of Scope

- Direct API wrappers for Stripe/Shopify (agent uses Composio MCP tools)
- Real-time analytics dashboards
- A/B test infrastructure
- Marketing template creation (can be created later from campaign-reporter + competitor-monitor)
- Volos agent deployment skills (separate repo)
