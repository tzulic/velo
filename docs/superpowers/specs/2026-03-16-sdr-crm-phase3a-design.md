# Phase 3A: SDR + CRM — Follow-Up Sequencer, Contact Manager, CRM Sync

> Phase 3A of 3. Adds SDR follow-up automation, contact management, and CRM sync capabilities to Velo's business vertical plugins.

---

## Context

Phase 1 (Plugin Engine v2) upgraded the infrastructure. Phase 2 added personal assistant plugins. Phase 3A adds the highest-ROI business vertical: SDR/sales automation.

The ai-sdr template already exists at `~/Volos/library/templates/ai-sdr/` with a `lead-scorer` plugin at `~/Volos/library/plugins/vertical/sdr/lead-scorer/`. Both are in the Volos library (separate from the velo repo). This spec adds the missing pieces to make it a complete SDR solution: automated follow-ups, contact database, and CRM synchronization.

### Why SDR First

From demand research: B2B companies spend $50-150K/yr per human SDR. AI SDR agents at $2-5K/month deliver 70-80% cost savings. The key capability is "replies to every new lead in under 5 seconds" — which Velo already does via messaging channels. What's missing is persistence: tracking leads, following up systematically, and syncing to CRM.

### Competitive Landscape

Neither Hermes Agent nor OpenClaw has any SDR/CRM plugins. Commercial AI SDR tools (11x, Salesforge, Outreach) charge $499-2000/mo. Velo + Volos can offer this at the managed service tier (€59-149/mo).

---

## 1. Follow-Up Sequencer Plugin

### 1.1 Overview

| Aspect | Detail |
|--------|--------|
| **Location** | `library/plugins/vertical/sdr/follow-up-sequencer/` |
| **Category** | Vertical (SDR) |
| **Lifecycle** | `register()` + `activate()` (needs background service) |
| **Storage** | `workspace/sequences.json` (atomic writes) |
| **Dependencies** | None (uses `process_direct` for sending via RuntimeAware) |

### 1.2 Tools (5)

#### `create_sequence`

```
create_sequence(lead_name: str, lead_contact: str, channel: str = "", steps: str = "")
```

- Creates a follow-up sequence for a lead
- `channel`: delivery channel — `email`, `telegram`, `whatsapp` (defaults to config `default_channel`)
- `steps`: JSON string of steps array, e.g. `[{"delay_days": 1, "message_hint": "Follow up on call"}, {"delay_days": 3, "message_hint": "Share case study"}]`
- If `steps` not provided, uses a default 3-step sequence (1 day, 3 days, 7 days)
- Auto-generates ID (`SEQ-0001`)
- Returns: created sequence summary

#### `list_sequences`

```
list_sequences(status: str = "")
```

- Lists all sequences, optionally filtered by status (`active`, `paused`, `completed`, `cancelled`)
- Shows: lead name, current step, next due date, status
- Returns: formatted list

#### `pause_sequence`

```
pause_sequence(sequence_id: str)
```

- Pauses an active sequence
- Returns: confirmation or "not found"

#### `resume_sequence`

```
resume_sequence(sequence_id: str)
```

- Resumes a paused sequence, recalculating `next_due_at` from now
- Returns: confirmation with next due date, or "not found" / "not paused"

#### `cancel_sequence`

```
cancel_sequence(sequence_id: str)
```

- Permanently cancels a sequence
- Returns: confirmation or "not found"

#### Error Handling

- **Invalid sequence ID:** Return `"Sequence {id} not found."`
- **Max sequences reached:** Return `"Sequence limit reached ({max}). Complete or cancel existing sequences."`
- **Invalid channel:** Return `"Invalid channel '{channel}'. Valid: email, telegram, whatsapp"`
- **Invalid steps JSON:** Return `"Invalid steps format. Provide a JSON array of {delay_days, message_hint} objects."`

### 1.3 Background Service

`SequenceRunner` — a `RuntimeAware` service that checks for due follow-ups:

- **Timer:** `asyncio.create_task` with sleep loop, same pattern as `HeartbeatService`
- Runs every `check_interval_minutes` (default: 5)
- For each active sequence: check if `next_due_at <= now`
- If due: compose a follow-up prompt and send via `process_direct`
- **Session key:** Uses `"sequencer:{sequence_id}"` — isolated from user conversations, avoids contention
- The prompt includes: lead name, step number, message hint
- The agent generates the actual message (not pre-written templates) — personalized via Honcho context
- After sending: mark step as sent, advance `current_step`, calculate `next_due_at`
- When all steps completed: set status to `completed`

### 1.4 Hook: `agent_end`

After each conversation turn, check if the agent made a follow-up commitment:
- The hook receives `messages` (full conversation list) and `duration_ms`
- Extract the last assistant message from `messages` list (last entry with `role == "assistant"`)
- Scan that message for phrases like "I'll follow up", "let me check back", "I'll send you"
- If detected: log a suggestion. The agent's context provider already shows active sequences, so the agent will naturally see the prompt to create one.
- **Contact matching:** Not attempted in the hook — this is a lightweight detection, not CRM sync. The agent uses its own judgment to connect the conversation to a contact.

This is advisory only — the agent decides whether to act on it.

### 1.5 Context Provider

```
Follow-ups: 5 active, 1 due today, 2 due this week
```

When no sequences: `Follow-ups: none`

### 1.6 Data Model

`workspace/sequences.json`:

```json
[
  {
    "id": "SEQ-0001",
    "lead_name": "John Smith",
    "lead_contact": "john@company.com",
    "channel": "email",
    "status": "active",
    "steps": [
      {"delay_days": 1, "message_hint": "Quick follow-up on our call", "sent_at": null},
      {"delay_days": 3, "message_hint": "Share case study", "sent_at": null},
      {"delay_days": 7, "message_hint": "Check if still interested", "sent_at": null}
    ],
    "current_step": 0,
    "created_at": "2026-03-16T10:00:00Z",
    "next_due_at": "2026-03-17T10:00:00Z"
  }
]
```

### 1.7 Plugin Manifest

```json
{
  "id": "follow-up-sequencer",
  "name": "Follow-Up Sequencer",
  "version": "1.0.0",
  "description": "Signal-driven follow-up automation for SDR outreach. Creates multi-step follow-up sequences with configurable delays and channels.",
  "category": "vertical",
  "tags": ["sdr", "sales", "follow-up", "outreach"],
  "config_schema": {
    "check_interval_minutes": {
      "type": "integer",
      "default": 5,
      "label": "Minutes between follow-up checks",
      "advanced": true
    },
    "max_sequences": {
      "type": "integer",
      "default": 50,
      "label": "Maximum active sequences"
    },
    "default_channel": {
      "type": "string",
      "default": "email",
      "enum": ["email", "telegram", "whatsapp"],
      "label": "Default delivery channel for follow-ups"
    }
  },
  "requires": {
    "channels": [],
    "env": [],
    "plugins": []
  },
  "hooks": ["agent_end"],
  "tools": ["create_sequence", "list_sequences", "pause_sequence", "resume_sequence", "cancel_sequence"],
  "services": true,
  "context_provider": true,
  "used_by_templates": ["ai-sdr"],
  "ui_hints": {
    "icon": "send",
    "color": "green"
  }
}
```

### 1.8 Implementation Structure

```
library/plugins/vertical/sdr/follow-up-sequencer/
├── __init__.py    — register() + activate() + SequenceStore + 4 tools + SequenceRunner + hook + context provider
└── plugin.json    — manifest
```

Single file. The `SequenceRunner` class implements `ServiceLike` + `RuntimeAware`. Tools operate on `SequenceStore` (same pattern as TaskStore in task-tracker).

---

## 2. Contact Manager Plugin

### 2.1 Overview

| Aspect | Detail |
|--------|--------|
| **Location** | `library/plugins/horizontal/contact-manager/` |
| **Category** | Horizontal (works with any template) |
| **Lifecycle** | `register()` only (no background services) |
| **Storage** | `workspace/contacts.json` (atomic writes) |
| **Dependencies** | None |

### 2.2 Tools (6)

#### `add_contact`

```
add_contact(name: str, email: str = "", company: str = "", role: str = "", phone: str = "", industry: str = "", company_size: str = "", source: str = "", tags: str = "", notes: str = "")
```

- Creates a contact with auto-generated ID (`CON-0001`)
- `tags`: comma-separated string (e.g., `"hot,enterprise"`)
- If `auto_dedupe_on_add` is enabled, checks for existing contact with same email before adding
- If duplicate found: returns warning with existing contact ID instead of creating
- Returns: created contact summary

#### `update_contact`

```
update_contact(contact_id: str, name: str = "", email: str = "", company: str = "", role: str = "", phone: str = "", tags: str = "", notes: str = "")
```

- Updates any provided field
- Returns: updated contact or "not found"

#### `find_contacts`

```
find_contacts(query: str = "", company: str = "", tag: str = "")
```

- Searches by name/email (case-insensitive substring match) AND/OR company AND/OR tag
- Returns: formatted list of matching contacts

#### `enrich_contact`

```
enrich_contact(contact_id: str)
```

- Identifies missing fields on the contact (no phone, no company, no role)
- Returns a formatted prompt suggesting what to search for:
  ```
  Contact CON-0001 (John Smith) is missing: company, role, phone.
  Suggested searches:
  - "John Smith LinkedIn" for role and company
  - "john@acme.com" for company website
  Use web_search to find this information, then update_contact to save it.
  ```
- Does NOT perform the search itself — the agent uses its existing web_search tool, or LinkedIn via Composio (`linkedin_get_profile`, `linkedin_search_people`) if connected
- Marks the contact as `enriched: true` after the agent updates it

#### `delete_contact`

```
delete_contact(contact_id: str)
```

- Removes a contact permanently
- Returns: confirmation or "not found"

#### `dedupe_contacts`

```
dedupe_contacts()
```

- Scans all contacts for potential duplicates
- Matching rules: exact email match OR (same first name + same company, case-insensitive)
- Returns groups of potential duplicates for agent review:
  ```
  Found 2 duplicate groups:

  Group 1 (email match):
    CON-0003: John Smith (john@acme.com)
    CON-0015: J. Smith (john@acme.com)

  Group 2 (name+company match):
    CON-0007: Sarah Connor (sarah@sky.net, Skynet)
    CON-0022: Sarah O'Connor (s.connor@sky.net, Skynet)

  Use update_contact to merge and delete_contact to remove duplicates.
  ```
- Does NOT auto-merge — agent decides

#### Error Handling

- **Duplicate on add:** `"Contact with email '{email}' already exists: {id} — {name}. Use update_contact to modify."`
- **Not found:** `"Contact {id} not found."`
- **Max contacts:** `"Contact limit reached ({max}). Remove unused contacts first."`

### 2.3 Context Provider

```
Contacts: 47 total (12 hot, 8 need enrichment)
```

When empty: `Contacts: none`

"Need enrichment" = contacts where `enriched` is false and email or company is missing.

### 2.4 Data Model

`workspace/contacts.json`:

```json
[
  {
    "id": "CON-0001",
    "name": "John Smith",
    "email": "john@acme.com",
    "company": "Acme Corp",
    "role": "CTO",
    "phone": "+1-555-0123",
    "industry": "Technology",
    "company_size": "50-200",
    "source": "inbound",
    "tags": ["hot", "enterprise"],
    "enriched": true,
    "notes": "Met at conference, interested in AI automation",
    "last_contacted_at": "",
    "created_at": "2026-03-16T10:00:00Z",
    "updated_at": "2026-03-16T10:00:00Z"
  }
]
```

### 2.5 Plugin Manifest

```json
{
  "id": "contact-manager",
  "name": "Contact Manager",
  "version": "1.0.0",
  "description": "Local contact database with enrichment prompts and duplicate detection.",
  "category": "horizontal",
  "tags": ["contacts", "crm", "enrichment", "dedup"],
  "config_schema": {
    "max_contacts": {
      "type": "integer",
      "default": 500,
      "label": "Maximum contacts",
      "advanced": true
    },
    "auto_dedupe_on_add": {
      "type": "boolean",
      "default": true,
      "label": "Check for duplicates when adding contacts"
    }
  },
  "requires": {
    "channels": [],
    "env": [],
    "plugins": []
  },
  "hooks": [],
  "tools": ["add_contact", "update_contact", "delete_contact", "find_contacts", "enrich_contact", "dedupe_contacts"],
  "services": false,
  "context_provider": true,
  "used_by_templates": ["ai-sdr", "customer-support"],
  "ui_hints": {
    "icon": "users",
    "color": "purple"
  }
}
```

### 2.6 Implementation Structure

```
library/plugins/horizontal/contact-manager/
├── __init__.py    — register() + ContactStore + 5 tools + context provider
└── plugin.json    — manifest
```

Single file. Same patterns as task-tracker (TaskStore → ContactStore).

---

## 3. CRM Sync Skill

### 3.1 Overview

| Aspect | Detail |
|--------|--------|
| **Location** | `velo/skills/crm-sync/` |
| **Type** | Skill (SKILL.md), not a plugin |
| **Dependencies** | CRM connected via Composio (HubSpot, Pipedrive, or Salesforce) |

### 3.2 Skill Files

```
velo/skills/crm-sync/
├── SKILL.md                    — When/how to sync, decision guide
└── references/
    └── field-mapping.md        — HubSpot + Pipedrive field mapping tables
```

### 3.3 SKILL.md Content

**Frontmatter:**

```yaml
---
name: crm-sync
description: |
  Sync contacts, conversations, and deal data to CRM (HubSpot, Pipedrive) and
  enrich contacts via LinkedIn. Use when the user asks to sync data, after
  qualifying a lead, or after a follow-up sequence completes.
  Requires CRM and/or LinkedIn connected via Composio.
metadata:
  requires:
    config: ["composio"]
---
```

**When to sync:**
- After qualifying a lead with `score_lead` → push contact + score to CRM
- After a conversation ends with a prospect → push conversation summary as CRM note
- After a follow-up sequence step → log activity in CRM
- When user explicitly asks ("sync to HubSpot", "update CRM")

**How to sync:**
- Check which CRM is connected (ask user if unclear)
- Map contact-manager fields to CRM fields (see `references/field-mapping.md`)
- Use Composio MCP tools for the connected CRM

**LinkedIn enrichment (via Composio):**
- `linkedin_get_profile` — get full profile by URL or name
- `linkedin_search_people` — search by name + company
- Use to enrich contacts: role, company, headline, location
- Composio handles OAuth — user clicks link, authenticates, done

**Error handling:**
- If CRM tool fails, log the error and tell the user
- Never silently drop a sync — always confirm success or report failure
- If no CRM connected, suggest connecting one via Composio

### 3.4 references/field-mapping.md

Maps contact-manager fields to CRM fields:

**HubSpot:**

| Contact Manager | HubSpot Property |
|----------------|-----------------|
| `name` | `firstname` + `lastname` (split on first space) |
| `email` | `email` |
| `company` | `company` |
| `role` | `jobtitle` |
| `phone` | `phone` |
| `source` | `hs_lead_status` |
| `tags` (contains "hot") | `lifecyclestage` = "opportunity" |
| `notes` | Create a note via `hubspot_create_note` |

**Pipedrive:**

| Contact Manager | Pipedrive Field |
|----------------|----------------|
| `name` | `name` |
| `email` | `email[0].value` |
| `company` | `org_id` (find or create org) |
| `role` | Custom field or note |
| `phone` | `phone[0].value` |
| `notes` | Create note via `pipedrive_add_note` |

---

## 4. Template Updates

### 4.1 ai-sdr manifest.json

Update plugins section:

```json
"plugins": {
  "required": ["lead-scorer", "follow-up-sequencer", "contact-manager"],
  "recommended": ["escalation-manager"],
  "optional": ["conversation-analytics", "rate-limiter"]
}
```

Add crm-sync skill:

```json
"skills_to_install": ["crm-sync"]
```

---

## 5. File Changes

### 5.1 New Files

| File | Purpose |
|------|---------|
| `library/plugins/vertical/sdr/follow-up-sequencer/__init__.py` | Plugin: SequenceStore + 5 tools + service + hook + context |
| `library/plugins/vertical/sdr/follow-up-sequencer/plugin.json` | Manifest |
| `library/plugins/horizontal/contact-manager/__init__.py` | Plugin: ContactStore + 6 tools + context |
| `library/plugins/horizontal/contact-manager/plugin.json` | Manifest |
| `velo/skills/crm-sync/SKILL.md` | Skill: sync decision guide |
| `velo/skills/crm-sync/references/field-mapping.md` | CRM field mappings |
| `tests/plugins/test_follow_up_sequencer.py` | Sequence CRUD, due detection, service |
| `tests/plugins/test_contact_manager.py` | Contact CRUD, dedupe, enrichment |

### 5.2 Modified Files

| File | Changes |
|------|---------|
| `library/templates/ai-sdr/manifest.json` | Add follow-up-sequencer + contact-manager to required, crm-sync to skills |

### 5.3 Test Coverage

| Test File | What It Covers |
|-----------|---------------|
| `test_follow_up_sequencer.py` | Sequence CRUD, step advancement, due date calculation, max limit, pause/cancel, context string, default steps |
| `test_contact_manager.py` | Contact CRUD, email dedupe on add, fuzzy name+company dedupe, find by query/company/tag, enrichment prompt, max limit, context string |

---

## 6. Scope Boundaries

### In Scope

- Follow-up sequencer plugin (5 tools, background service, agent_end hook, context provider)
- Contact manager plugin (6 tools, context provider, dedupe, enrichment prompts)
- CRM sync skill (SKILL.md + field mapping reference)
- ai-sdr template manifest update
- Tests for both plugins

### Out of Scope

- External enrichment APIs (Clay, Apollo, ZoomInfo) — but LinkedIn IS available via Composio
- Email deliverability infrastructure
- Sub-spec 3B (support resolution + marketing ops)
- Multi-channel sequence orchestration (email + LinkedIn + phone in one sequence)
- Automated meeting scheduling (Calendly-style)
- Volos agent deployment skills (separate Volos repo)
