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

# CRM Sync

Sync contact-manager data to an external CRM (HubSpot or Pipedrive) and enrich contacts via LinkedIn — all via Composio MCP tools. Composio handles OAuth; the user clicks a link to authenticate their CRM and/or LinkedIn account once.

## When to Sync

Sync to CRM in these four situations:

1. **After qualifying a lead** — `score_lead` returns a result → push the contact and score to CRM immediately
2. **After a conversation with a prospect ends** — push a conversation summary as a CRM note
3. **After a follow-up sequence step is sent** — log the outreach activity in CRM
4. **When the user explicitly asks** — phrases like "sync to HubSpot", "update the CRM", "push this to Pipedrive"

## How to Sync

### Step 1 — Identify the connected CRM

Check which CRM the user has connected via Composio. If it is not clear, ask:

> "Which CRM are you using — HubSpot or Pipedrive?"

### Step 2 — Map fields

Use the field mapping table in `references/field-mapping.md` to translate contact-manager fields to CRM properties before calling any Composio tool.

Key rules:
- Split `name` on the first space to get `firstname` / `lastname` (HubSpot)
- `company` maps to a property in HubSpot but requires finding or creating an org in Pipedrive (`org_id`)
- `notes` are created as a separate note object, not a contact property

### Step 3 — Call Composio MCP tools

**HubSpot:**
- Create/update contact: `hubspot_create_contact` or `hubspot_update_contact`
- Add note: `hubspot_create_note` (link to contact ID)
- Log activity: `hubspot_create_engagement`

**Pipedrive:**
- Create/update person: `pipedrive_create_person` or `pipedrive_update_person`
- Find or create org: `pipedrive_search_organizations` → `pipedrive_create_organization`
- Add note: `pipedrive_add_note`

Always pass the contact ID returned by the CRM tool back to the user as confirmation.

## LinkedIn Enrichment (via Composio)

Use LinkedIn tools to fill in missing contact fields before or after syncing:

| Tool | When to Use |
|------|-------------|
| `linkedin_get_profile` | You have a LinkedIn URL or a full name to look up |
| `linkedin_search_people` | You know name + company but not the profile URL |

After enrichment, update the local contact via `update_contact` to save the new data, then sync the enriched record to CRM.

Fields LinkedIn can provide: `role` (headline/title), `company`, `location`, `industry`.

## Error Handling

- If a Composio CRM tool returns an error, log it and tell the user what failed and why
- Never silently drop a sync — always confirm success or report failure with the error message
- If no CRM is connected, say:
  > "No CRM is connected yet. You can connect HubSpot or Pipedrive via Composio — I can walk you through it."
- If a contact is missing required fields (e.g., no email for HubSpot), ask the user to provide them before syncing or use `enrich_contact` to surface what is missing
