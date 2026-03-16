# Phase 3B: Support Resolution + Marketing Ops Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add resolution guard plugin (policy enforcement + audit trail for agent actions) and campaign reporter plugin (structured marketing reports with trend tracking) to complete the business vertical plugin library.

**Architecture:** Resolution guard hooks `before_tool_call` to enforce policies on MCP actions (refund limits, approval requirements, blocked actions) and logs everything to an audit trail. Campaign reporter stores structured reports with metric comparison and scheduled generation. Both follow established patterns (TaskStore for storage, HeartbeatService for scheduling).

**Tech Stack:** Python 3.11+, pytest, asyncio, JSON file I/O

**Spec:** `docs/superpowers/specs/2026-03-16-support-marketing-phase3b-design.md`

**Reference implementations:**
- Task tracker: `library/plugins/horizontal/task-tracker/__init__.py` (Store + Tool pattern)
- Follow-up sequencer: `library/plugins/vertical/sdr/follow-up-sequencer/__init__.py` (RuntimeAware service)

---

## Chunk 1: Resolution Guard Plugin

### Task 1: AuditStore + guard hook + 2 tools + manifest + tests

**Files:**
- Create: `library/plugins/horizontal/resolution-guard/__init__.py`
- Create: `library/plugins/horizontal/resolution-guard/plugin.json`
- Test: `tests/plugins/test_resolution_guard.py`

- [ ] **Step 1: Create `plugin.json` manifest**

Use the exact manifest from spec Section 1.6.

- [ ] **Step 2: Write failing tests**

Create `tests/plugins/test_resolution_guard.py` with importlib loading (same pattern as contact-manager):

```python
import importlib.util
from pathlib import Path

_plugin_path = (
    Path(__file__).resolve().parents[2]
    / "library" / "plugins" / "horizontal" / "resolution-guard" / "__init__.py"
)
_spec = importlib.util.spec_from_file_location("resolution_guard", _plugin_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

AuditStore = _mod.AuditStore
GetAuditLogTool = _mod.GetAuditLogTool
GetResolutionStatsTool = _mod.GetResolutionStatsTool
```

**TestAuditStore** (~8 tests):
- `test_log_allowed_action` — logs with outcome "allowed"
- `test_log_blocked_action` — logs with outcome "blocked" and reason
- `test_get_log_with_limit`
- `test_get_log_filter_by_action`
- `test_get_stats_counts` — total, blocked, refund amounts
- `test_get_stats_empty`
- `test_cap_enforcement` — oldest entries removed at max_audit_entries
- `test_persists_to_disk`

**TestGuardHook** (~10 tests):
- `test_passthrough_untracked_tool` — tool not matching patterns passes through unchanged
- `test_track_matching_tool` — tool matching pattern gets logged
- `test_block_blocked_action` — returns `{"__block": True, "reason": ...}`
- `test_block_approval_required` — returns block with approval message
- `test_block_amount_over_limit` — refund amount exceeds max
- `test_allow_amount_under_limit` — refund amount within limit
- `test_amount_check_various_keys` — checks "amount", "refund_amount"
- `test_blocked_action_logged` — blocked actions appear in audit log
- `test_approval_action_logged` — approval-required logged with reason
- `test_pattern_matching_case_insensitive`

**TestGuardTools** (~4 tests):
- `test_audit_log_tool_success`
- `test_audit_log_tool_empty`
- `test_stats_tool_with_data`
- `test_stats_tool_empty`

**TestContextString** (~2 tests):
- `test_context_with_actions`
- `test_context_empty`

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/plugins/test_resolution_guard.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 4: Implement `__init__.py`**

Structure:
- `AuditStore` class — JSON load/save, append entries, cap enforcement (FIFO), query by type/date, stats calculation
- `_guard_hook(value, tool_name, **kwargs)` — the `before_tool_call` callback. Checks track_patterns → blocked_actions → require_approval → amount limits. Logs every matched action (allowed or blocked). Returns value unchanged or `{"__block": True, "reason": "..."}`.
- `GetAuditLogTool` — queries AuditStore with limit and optional action_type filter
- `GetResolutionStatsTool` — returns stats for last N days (total, blocked, refund total, common types)
- `register(ctx)` — registers hook (`before_tool_call`, priority=50 to run before other hooks), tools, context provider
- Context provider: single-pass count of today's actions

Key detail: the guard function receives `value` (the tool params dict) and `tool_name`. It pattern-matches `tool_name` against `track_patterns` list using substring matching (case-insensitive). Amount is extracted from `value.get("amount")` or `value.get("refund_amount")`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/plugins/test_resolution_guard.py -v`
Expected: All PASS (~24 tests)

- [ ] **Step 6: Commit**

```bash
git add library/plugins/horizontal/resolution-guard/ tests/plugins/test_resolution_guard.py
git commit -m "feat(plugins): add resolution-guard with policy enforcement and audit trail"
```

---

## Chunk 2: Campaign Reporter Plugin

### Task 2: ReportStore + 4 tools + scheduler + manifest + tests

**Files:**
- Create: `library/plugins/vertical/marketing/campaign-reporter/__init__.py`
- Create: `library/plugins/vertical/marketing/campaign-reporter/plugin.json`
- Test: `tests/plugins/test_campaign_reporter.py`

- [ ] **Step 1: Create directory + `plugin.json` manifest**

```bash
mkdir -p library/plugins/vertical/marketing/campaign-reporter
```

Use the exact manifest from spec Section 2.6 (includes timezone field added after review).

- [ ] **Step 2: Write failing tests**

Create `tests/plugins/test_campaign_reporter.py`:

**TestReportStore** (~12 tests):
- `test_save_report` — auto-ID RPT-0001, stores metrics + summary
- `test_save_auto_increments_id`
- `test_save_persists_to_disk`
- `test_get_by_period`
- `test_get_by_id`
- `test_get_not_found`
- `test_list_reports_newest_first`
- `test_list_with_limit`
- `test_compare_periods_full_overlap` — all metrics shared, shows deltas + percentages
- `test_compare_periods_partial_overlap` — metrics only in A show "removed", only in B show "new"
- `test_compare_period_not_found`
- `test_max_reports_fifo` — oldest removed, IDs keep incrementing
- `test_invalid_metrics_json` — non-JSON string rejected

**TestReportTools** (~6 tests):
- `test_save_tool_success`
- `test_save_tool_invalid_metrics`
- `test_get_tool_by_period`
- `test_compare_tool_success`
- `test_compare_tool_not_found`
- `test_list_tool_empty`

**TestContext** (~2 tests):
- `test_context_with_reports`
- `test_context_empty`

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/plugins/test_campaign_reporter.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 4: Implement `__init__.py`**

Structure:
- `ReportStore` class — JSON load/save, create report, get by period/ID, compare periods, list, FIFO cap, context string
- `compare()` method: union all metric keys from both periods. Shared keys get delta + percentage. Keys only in A marked "(removed)". Keys only in B marked "(new)".
- 4 Tool classes: `SaveReportTool`, `GetReportTool`, `ComparePeriodsTool`, `ListReportsTool`
- `ReportScheduler` — RuntimeAware service (same pattern as follow-up-sequencer's SequenceRunner):
  - `set_runtime(refs)`: store `process_direct`
  - `start()`: create asyncio task
  - `stop()`: cancel task
  - `_run()`: calculate next fire time from schedule_day + schedule_time + timezone, sleep until then, send prompt via `process_direct` with session_key `"reporter:weekly"`
- Module-level `_scheduler_instance`
- `register(ctx)`: tools + context provider, create scheduler
- `activate(ctx)`: register scheduler as service

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/plugins/test_campaign_reporter.py -v`
Expected: All PASS (~20 tests)

- [ ] **Step 6: Commit**

```bash
git add library/plugins/vertical/marketing/campaign-reporter/ tests/plugins/test_campaign_reporter.py
git commit -m "feat(plugins): add campaign-reporter with structured reports and trend comparison"
```

---

## Chunk 3: Competitor Monitor Skill + Template Update + Verification

### Task 3: Create competitor-monitor skill

**Files:**
- Create: `velo/skills/competitor-monitor/SKILL.md`
- Create: `velo/skills/competitor-monitor/references/monitoring-playbook.md`

- [ ] **Step 1: Create directory**

```bash
mkdir -p velo/skills/competitor-monitor/references
```

- [ ] **Step 2: Write SKILL.md**

Content from spec Section 3.3:
- Frontmatter (name, description, no special requirements)
- What to monitor (pricing, blog, job postings, social, tech stack)
- How to store (append to workspace/competitor-notes.md)
- When to alert (significant changes only)
- Integration with heartbeat tasks

- [ ] **Step 3: Write references/monitoring-playbook.md**

Organized by competitor type:
- SaaS: pricing page, changelog, blog, careers, reviews
- E-commerce: catalog, pricing, promotions, shipping
- Agency: case studies, team, services, clients

Each with example web search queries.

- [ ] **Step 4: Verify YAML**

```bash
python -c "import yaml; yaml.safe_load(open('velo/skills/competitor-monitor/SKILL.md').read().split('---')[1]); print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add velo/skills/competitor-monitor/
git commit -m "feat(skills): add competitor-monitor skill with monitoring playbook"
```

---

### Task 4: Update customer-support template + verify

- [ ] **Step 1: Update template manifest**

`~/Volos/library/templates/customer-support/manifest.json` (Volos repo) — add resolution-guard to recommended plugins.

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest tests/plugins/ -v
```

Expected: All pass (~300+ tests including new resolution-guard and campaign-reporter)

- [ ] **Step 3: Run linter**

```bash
uv run ruff check library/plugins/horizontal/resolution-guard/ library/plugins/vertical/marketing/campaign-reporter/
uv run ruff format library/plugins/horizontal/resolution-guard/ library/plugins/vertical/marketing/campaign-reporter/
```

- [ ] **Step 4: Final commit if fixes needed**

---

## Notes for Executor

**Resolution guard hook priority:** Register with `priority=50` (lower than default 100) so the guard runs BEFORE other `before_tool_call` hooks. This ensures policy is checked first.

**Guard amount extraction:** The hook checks multiple common param keys for amount values: `value.get("amount")`, `value.get("refund_amount")`, `value.get("total")`. Convert to float before comparing against limit.

**Campaign reporter schedule:** Use `zoneinfo.ZoneInfo` for timezone-aware scheduling. Calculate next fire time: find next occurrence of schedule_day at schedule_time in the configured timezone. Sleep until then. After firing, recalculate for next week.

**Audit log FIFO:** When `len(entries) > max_audit_entries`, slice to keep only the last `max_audit_entries` entries and save.

**Plugin import pattern:** Use importlib.util in tests (not sys.path) to avoid collisions between plugin test files.

---

## Summary

| Task | What It Delivers |
|------|-----------------|
| 1 | Resolution guard — AuditStore + guard hook + 2 tools + context (~24 tests) |
| 2 | Campaign reporter — ReportStore + 4 tools + scheduler + context (~20 tests) |
| 3 | Competitor monitor skill — SKILL.md + monitoring playbook |
| 4 | Template update + full verification |
