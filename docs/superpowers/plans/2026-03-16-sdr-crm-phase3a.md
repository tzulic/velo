# Phase 3A: SDR + CRM Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add follow-up sequencer plugin, contact manager plugin, and CRM sync skill to complete the SDR vertical.

**Architecture:** Two plugins following the same pattern as task-tracker (JSON store + Tool classes + context provider). Follow-up sequencer adds a RuntimeAware background service (like heartbeat plugin). CRM sync is a SKILL.md file with field mapping references. Both plugins use `register()` + optional `activate()`.

**Tech Stack:** Python 3.11+, pytest, asyncio, JSON file I/O

**Spec:** `docs/superpowers/specs/2026-03-16-sdr-crm-phase3a-design.md`

**Reference implementations:**
- Task tracker plugin: `library/plugins/horizontal/task-tracker/__init__.py` (Store + Tool pattern)
- Heartbeat plugin: `velo/plugins/builtin/heartbeat/__init__.py` (RuntimeAware service pattern)

---

## Chunk 1: Contact Manager Plugin

### Task 1: ContactStore + 6 tools + manifest + tests

**Files:**
- Create: `library/plugins/horizontal/contact-manager/__init__.py`
- Create: `library/plugins/horizontal/contact-manager/plugin.json`
- Test: `tests/plugins/test_contact_manager.py`

- [ ] **Step 1: Create `plugin.json` manifest**

Use the exact manifest from spec Section 2.5.

- [ ] **Step 2: Write failing tests**

Create `tests/plugins/test_contact_manager.py` with test classes covering:

**TestContactStore** (~15 tests):
- `test_add_contact` — creates with auto-ID CON-0001
- `test_add_auto_increments_id`
- `test_add_persists_to_disk`
- `test_add_duplicate_email_blocked` — when auto_dedupe_on_add=True
- `test_add_duplicate_email_allowed` — when auto_dedupe_on_add=False
- `test_update_contact` — update fields by ID
- `test_update_nonexistent_returns_none`
- `test_delete_contact`
- `test_delete_nonexistent_returns_false`
- `test_find_by_name` — case-insensitive substring
- `test_find_by_company`
- `test_find_by_tag`
- `test_find_combined_filters`
- `test_max_contacts_enforced`
- `test_context_string_empty` — "Contacts: none"
- `test_context_string_with_contacts` — includes hot count and needs-enrichment count

**TestDedupe** (~3 tests):
- `test_dedupe_by_email` — exact email match
- `test_dedupe_by_name_company` — same first name + same company
- `test_dedupe_no_duplicates` — returns empty

**TestEnrich** (~2 tests):
- `test_enrich_missing_fields` — returns prompt with missing fields
- `test_enrich_already_enriched` — returns "already enriched"

**TestContactTools** (~8 tests):
- `test_add_tool_success`
- `test_add_tool_duplicate_blocked`
- `test_update_tool_not_found`
- `test_find_tool_results`
- `test_find_tool_empty`
- `test_delete_tool_success`
- `test_delete_tool_not_found`
- `test_enrich_tool_missing_fields`

Import pattern (same as task-tracker tests):
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "library" / "plugins" / "horizontal" / "contact-manager"))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/plugins/test_contact_manager.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 4: Implement `__init__.py`**

Follow the task-tracker pattern exactly:
- `ContactStore` class (same structure as `TaskStore`) with: `_load()`, `_save()`, `add()`, `update()`, `delete()`, `get()`, `find()`, `enrich()`, `dedupe()`, `get_summary()`, `context_string()`
- 6 Tool classes: `AddContactTool`, `UpdateContactTool`, `DeleteContactTool`, `FindContactsTool`, `EnrichContactTool`, `DedupeContactsTool`
- `register(ctx)` entry point — registers all tools + context provider
- Tags stored as `list[str]` internally, parsed from comma-separated input
- Dedupe: exact email match OR (same first name case-insensitive + same company case-insensitive)
- Enrich: check which fields are empty, return formatted prompt suggesting searches

Key differences from task-tracker:
- No `show_done_days` cleanup — contacts don't expire
- Has `auto_dedupe_on_add` config (check email before adding)
- Has `enriched` boolean field
- Has `last_contacted_at` field
- Has `tags` list field
- `find()` does case-insensitive substring match on name/email, exact match on company/tag

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/plugins/test_contact_manager.py -v`
Expected: All PASS (~28 tests)

- [ ] **Step 6: Commit**

```bash
git add library/plugins/horizontal/contact-manager/ tests/plugins/test_contact_manager.py
git commit -m "feat(plugins): add contact-manager plugin with 6 tools, dedupe, enrichment"
```

---

## Chunk 2: Follow-Up Sequencer Plugin

### Task 2: SequenceStore + 5 tools + manifest + tests

**Files:**
- Create: `library/plugins/vertical/sdr/follow-up-sequencer/__init__.py`
- Create: `library/plugins/vertical/sdr/follow-up-sequencer/plugin.json`
- Test: `tests/plugins/test_follow_up_sequencer.py`

- [ ] **Step 1: Create `plugin.json` manifest**

Use the exact manifest from spec Section 1.7.

- [ ] **Step 2: Write failing tests**

Create `tests/plugins/test_follow_up_sequencer.py` with:

**TestSequenceStore** (~14 tests):
- `test_create_sequence` — auto-ID SEQ-0001, default 3 steps
- `test_create_custom_steps` — parse JSON steps
- `test_create_auto_increments_id`
- `test_create_persists_to_disk`
- `test_list_all`
- `test_list_filter_by_status`
- `test_pause_sequence` — status changes to paused
- `test_pause_nonexistent_returns_false`
- `test_resume_sequence` — status back to active, next_due_at recalculated
- `test_resume_not_paused_returns_false`
- `test_cancel_sequence` — status changes to cancelled
- `test_max_sequences_enforced`
- `test_advance_step` — marks step sent, advances current_step, calculates next_due_at
- `test_advance_completes_sequence` — last step → status completed
- `test_context_string_empty`
- `test_context_string_with_sequences`
- `test_get_due_sequences` — returns sequences where next_due_at <= now

**TestSequenceTools** (~7 tests):
- `test_create_tool_success`
- `test_create_tool_invalid_channel`
- `test_create_tool_invalid_steps_json`
- `test_create_tool_max_reached`
- `test_list_tool_empty`
- `test_pause_tool_not_found`
- `test_cancel_tool_not_found`

Import pattern:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "library" / "plugins" / "vertical" / "sdr" / "follow-up-sequencer"))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/plugins/test_follow_up_sequencer.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 4: Implement `__init__.py`**

Structure:
- `VALID_CHANNELS = {"email", "telegram", "whatsapp"}`
- `VALID_STATUSES = {"active", "paused", "completed", "cancelled"}`
- `DEFAULT_STEPS` — 3-step sequence (1 day, 3 days, 7 days)
- `SequenceStore` class — JSON load/save/query (same pattern as TaskStore/ContactStore)
  - `create()`, `list_sequences()`, `pause()`, `resume()`, `cancel()`, `get()`, `get_due()`, `advance_step()`, `get_summary()`, `context_string()`
- 5 Tool classes: `CreateSequenceTool`, `ListSequencesTool`, `PauseSequenceTool`, `ResumeSequenceTool`, `CancelSequenceTool`
- `SequenceRunner` class — `ServiceLike` + `RuntimeAware`
  - `set_runtime(refs)`: store `process_direct` reference
  - `start()`: create asyncio task with sleep loop
  - `stop()`: cancel task
  - `_run()`: every N minutes, check `store.get_due()`, for each due sequence compose prompt and call `process_direct`
- Hook callback for `agent_end`: extract last assistant message, scan for follow-up phrases
- `register(ctx)`: register tools + hook + context provider
- `activate(ctx)`: register SequenceRunner service
- Module-level `_runner_instance` variable (same pattern as heartbeat's `_plugin_instance`)

Key implementation detail for `SequenceRunner._run()`:
```python
async def _run(self) -> None:
    while True:
        await asyncio.sleep(self._interval_s)
        try:
            due = self._store.get_due()
            for seq in due:
                step = seq["steps"][seq["current_step"]]
                prompt = (
                    f"[Follow-up Task] Send follow-up #{seq['current_step'] + 1} "
                    f"to {seq['lead_name']} ({seq['lead_contact']}) via {seq['channel']}.\n"
                    f"Message hint: {step['message_hint']}\n"
                    f"Compose and send the message now."
                )
                if self._process_direct:
                    await self._process_direct(
                        prompt,
                        session_key=f"sequencer:{seq['id']}",
                        channel="cli",
                        chat_id="direct",
                    )
                self._store.advance_step(seq["id"])
        except Exception:
            logger.exception("sequencer.tick_failed")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/plugins/test_follow_up_sequencer.py -v`
Expected: All PASS (~21 tests)

- [ ] **Step 6: Commit**

```bash
git add library/plugins/vertical/sdr/follow-up-sequencer/ tests/plugins/test_follow_up_sequencer.py
git commit -m "feat(plugins): add follow-up-sequencer plugin with 5 tools, background service, agent_end hook"
```

---

## Chunk 3: CRM Sync Skill + Template Update + Verification

### Task 3: Create CRM sync skill

**Files:**
- Create: `velo/skills/crm-sync/SKILL.md`
- Create: `velo/skills/crm-sync/references/field-mapping.md`

- [ ] **Step 1: Create directory**

```bash
mkdir -p velo/skills/crm-sync/references
```

- [ ] **Step 2: Write SKILL.md**

Full content from spec Section 3.3:
- YAML frontmatter (name, description, metadata.requires.config)
- When to sync (4 triggers)
- How to sync (Composio MCP tools)
- LinkedIn enrichment section
- Error handling guidance

- [ ] **Step 3: Write references/field-mapping.md**

Full content from spec Section 3.4:
- HubSpot field mapping table
- Pipedrive field mapping table
- Notes on name splitting, tag-to-lifecyclestage mapping

- [ ] **Step 4: Verify YAML frontmatter**

```bash
python -c "import yaml; yaml.safe_load(open('velo/skills/crm-sync/SKILL.md').read().split('---')[1]); print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add velo/skills/crm-sync/
git commit -m "feat(skills): add crm-sync skill with HubSpot/Pipedrive field mappings"
```

---

### Task 4: Update ai-sdr template manifest

**Files:**
- Modify: `library/templates/ai-sdr/manifest.json` (in Volos repo, not velo)

- [ ] **Step 1: Add plugins to required**

Change plugins.required to: `["lead-scorer", "follow-up-sequencer", "contact-manager"]`

- [ ] **Step 2: Add crm-sync to skills**

Add `"crm-sync"` to `skills_to_install` array.

- [ ] **Step 3: Commit** (in Volos repo)

Note: This file is at `~/Volos/library/templates/ai-sdr/manifest.json`, outside the velo repo. Commit separately.

---

### Task 5: Full verification

- [ ] **Step 1: Run all plugin tests**

Run: `uv run pytest tests/plugins/ -v`
Expected: All pass (including new contact-manager and follow-up-sequencer tests)

- [ ] **Step 2: Run linter**

Run: `uv run ruff check library/plugins/horizontal/contact-manager/ library/plugins/vertical/sdr/follow-up-sequencer/ velo/skills/crm-sync/`
Run: `uv run ruff format library/plugins/horizontal/contact-manager/ library/plugins/vertical/sdr/follow-up-sequencer/`

- [ ] **Step 3: Final commit if fixes needed**

---

## Notes for Executor

**Plugin locations:** Library plugins are at `~/Volos/library/plugins/` (NOT inside the velo repo). They are deployed to customer workspaces via SSH. Tests import them via sys.path manipulation.

**Follow-up sequencer service pattern:** Follow the heartbeat plugin pattern exactly:
1. Module-level `_runner_instance: SequenceRunner | None = None`
2. `register()` creates the SequenceRunner, stores in module var
3. `activate()` calls `ctx.register_service(_runner_instance)`
4. SequenceRunner implements `set_runtime(refs)` to get `process_direct`
5. `start()` creates asyncio task, `stop()` cancels it

**agent_end hook:** The hook receives `messages` (list of message dicts) and `duration_ms`. Extract last assistant message: `[m for m in messages if m.get("role") == "assistant"][-1]`. Scan its content for follow-up phrases. This is fire-and-forget — log a debug message, don't modify anything.

**Contact dedupe matching:** For "same first name + same company":
```python
def _first_name(name: str) -> str:
    return name.split()[0].lower() if name else ""
```
Compare `_first_name(a) == _first_name(b) and a_company.lower() == b_company.lower()`.

---

## Summary

| Task | What It Delivers |
|------|-----------------|
| 1 | Contact manager plugin — ContactStore + 6 tools + context + dedupe + enrichment prompts (~28 tests) |
| 2 | Follow-up sequencer plugin — SequenceStore + 5 tools + background service + agent_end hook + context (~21 tests) |
| 3 | CRM sync skill — SKILL.md + field mapping reference |
| 4 | ai-sdr template manifest update (Volos repo) |
| 5 | Full verification |
