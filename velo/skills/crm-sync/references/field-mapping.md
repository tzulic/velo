# CRM Field Mapping

Maps contact-manager fields to HubSpot and Pipedrive CRM fields.

---

## HubSpot

| Contact Manager Field | HubSpot Property | Notes |
|-----------------------|-----------------|-------|
| `name` | `firstname` + `lastname` | Split on first space. If only one word, use as `firstname`, leave `lastname` empty. |
| `email` | `email` | Required for HubSpot contact creation. |
| `company` | `company` | Plain string — HubSpot stores this on the contact record. |
| `role` | `jobtitle` | |
| `phone` | `phone` | |
| `source` | `hs_lead_status` | Pass the raw source value (e.g. `"inbound"`, `"outbound"`). |
| `tags` (contains `"hot"`) | `lifecyclestage` = `"opportunity"` | Only set if the `hot` tag is present. Other tag-to-stage mappings: `"customer"` tag → `"customer"`. |
| `notes` | HubSpot Note object | Create via `hubspot_create_note`, linked to the contact by `hs_object_id`. |

### Name Splitting Examples

| Contact Manager `name` | HubSpot `firstname` | HubSpot `lastname` |
|------------------------|--------------------|--------------------|
| `"John Smith"` | `"John"` | `"Smith"` |
| `"Mary Jane Watson"` | `"Mary"` | `"Jane Watson"` |
| `"Cher"` | `"Cher"` | `""` |

---

## Pipedrive

| Contact Manager Field | Pipedrive Field | Notes |
|-----------------------|----------------|-------|
| `name` | `name` | Full name — Pipedrive stores it as one field. |
| `email` | `email[0].value` | Pipedrive accepts an array: `[{"value": "...", "primary": true}]`. |
| `company` | `org_id` | Search for existing org first (`pipedrive_search_organizations`). If not found, create it (`pipedrive_create_organization`), then use the returned ID. |
| `role` | Custom field or note | Pipedrive persons do not have a built-in `jobtitle` field. Store in a custom field if configured, otherwise add as a note. |
| `phone` | `phone[0].value` | Same array format as email: `[{"value": "...", "primary": true}]`. |
| `notes` | Pipedrive Note object | Create via `pipedrive_add_note`, linked to person ID (`person_id`). |

### Pipedrive `org_id` Lookup Sequence

1. Call `pipedrive_search_organizations` with `{ "term": "<company name>" }`
2. If results include an exact or close name match → use that `id` as `org_id`
3. If no match → call `pipedrive_create_organization` with `{ "name": "<company name>" }` → use the new `id`

---

## Notes

- **Tag-to-lifecyclestage mapping (HubSpot):** Only `"hot"` is mapped automatically. All other tags are not synced to HubSpot lifecycle — they remain in the local contact record.
- **Fields with no CRM equivalent:** `industry`, `company_size`, `source` (Pipedrive), `enriched` — these are local-only fields. Do not attempt to sync them unless the CRM has a matching custom field configured by the user.
- **`last_contacted_at`:** Not synced automatically. It is updated by the follow-up sequencer when a sequence step is sent.
