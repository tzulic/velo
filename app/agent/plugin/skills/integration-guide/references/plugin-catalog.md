# Plugin Catalog

This catalog lists all plugins available in the velo library.
Plugins live under `library/plugins/` and are installed by dropping the plugin
directory into `{workspace}/plugins/`.

---

## Horizontal Plugins

Horizontal plugins add general-purpose capabilities that work across all agent types.

---

### conversation-analytics

**Purpose:** Tracks outgoing messages, tool calls, and escalations. Persists
daily stats to `analytics.json` and exposes a query tool.

**Adds:**
- Tool: `get_analytics` — report for today / yesterday / past week
- Hook: `before_response` (modifying) — counts messages
- Hook: `after_tool_call` (modifying) — counts tool calls by name
- Hook: `on_startup` / `on_shutdown` — load/persist JSON
- Context provider: "Today: N msgs, N tool calls, N escalations"

**Config schema:**
```json
{
  "persist_every_n_messages": 10
}
```

**Deploy sequence:**
```
cp -r library/plugins/horizontal/conversation-analytics {workspace}/plugins/
```

**Used by:** All agent types

---

### scheduled-digest

**Purpose:** Fires a periodic digest prompt at a configured time. The agent
prepares the digest and delivers it via Telegram.

**Adds:**
- Service: `_DigestService` (RuntimeAware) — asyncio scheduler
- Tool: `send_digest_now` — trigger digest immediately
- Context provider: "Next digest: Mon 2026-03-16 08:00 UTC"

**Config schema:**
```json
{
  "frequency": "daily",
  "time": "08:00",
  "timezone": "UTC",
  "owner_telegram_id": "",
  "sections": ["unread emails", "calendar for today", "open tasks"],
  "channel": "telegram"
}
```

**Deploy sequence:**
```
cp -r library/plugins/horizontal/scheduled-digest {workspace}/plugins/
# Set timezone to owner's local timezone (e.g. "Europe/London")
```

**Used by:** Personal assistant, executive assistant templates

---

### knowledge-base

**Purpose:** Indexes local documents and URLs into a SQLite FTS5 database.
Exposes search and add-document tools. Indexes `doc_directory` on startup.

**Adds:**
- Tool: `search_knowledge` — full-text search with BM25 ranking
- Tool: `add_document` — index a file path or URL at runtime
- Hook: `on_startup` — indexes all files in `doc_directory`
- Context provider: "Knowledge base: N documents indexed"

**Config schema:**
```json
{
  "doc_directory": "/path/to/docs",
  "extensions": [".md", ".txt", ".pdf"],
  "chunk_size": 500,
  "chunk_overlap": 50,
  "max_documents": 500
}
```

**Deploy sequence:**
```
cp -r library/plugins/horizontal/knowledge-base {workspace}/plugins/
# Optional: pip install pypdf  (for PDF support)
```

**Used by:** Customer support, documentation assistant, research templates

---

### webhook-receiver

**Purpose:** Starts an aiohttp HTTP server that receives webhook POST requests
from external services (Stripe, Shopify, or any custom service) and injects
them as agent messages via `process_direct`.

**Adds:**
- Service: `_WebhookServer` (RuntimeAware) — aiohttp server
- Tool: `list_webhook_events` — show recent received events
- Signature verification: Stripe (`t=,v1=`), Shopify (base64 HMAC), generic (hex HMAC)

**Config schema:**
```json
{
  "port": 8090,
  "routes": [
    {
      "path": "/webhooks/stripe",
      "service": "stripe",
      "secret_env": "STRIPE_WEBHOOK_SECRET"
    },
    {
      "path": "/webhooks/shopify",
      "service": "shopify",
      "secret_env": "SHOPIFY_CLIENT_SECRET"
    }
  ],
  "max_events_log": 100,
  "reject_invalid_signatures": false
}
```

**Deploy sequence:**
```
cp -r library/plugins/horizontal/webhook-receiver {workspace}/plugins/
# Open the port in Hetzner firewall: ufw allow 8090/tcp
# Register webhook URL in Stripe/Shopify dashboard
```

**Used by:** E-commerce agent, billing automation, event-driven templates

---

### rate-limiter

**Purpose:** Sliding-window throttling for outgoing responses. Enforces a global
message rate limit and an optional per-channel limit. When throttled, the agent
returns a configurable cooldown message instead of the original response.

**Adds:**
- Tool: `get_rate_limit_status` — current global (and per-channel) usage
- Hook: `before_response` (modifying) — blocks response if limit exceeded
- Context provider: "Rate limiter: N/max msgs in last Xs"

**Config schema:**
```json
{
  "window_seconds": 60,
  "max_messages": 60,
  "per_channel_max": 0,
  "cooldown_response": "Rate limit reached. Please wait a moment."
}
```

Notes: `per_channel_max=0` disables per-channel limiting (global only).

**Deploy sequence:**
```
cp -r library/plugins/horizontal/rate-limiter {workspace}/plugins/
```

**Used by:** Multi-tenant agents, high-traffic bots, abuse-prevention setups

---

### auto-translate

**Purpose:** Injects a language directive into the system prompt so the agent
always responds in a configured language. Supports runtime switching via tools
and auto-detect mode (agent matches the user's language).

**Adds:**
- Tool: `set_language` — change or clear the active language at runtime
- Tool: `get_language` — read the current language setting
- Hook: `after_prompt_build` (modifying) — appends language directive to system prompt
- Context provider: "Language: Spanish" or "Language: auto"
- Persistence: `language.txt` in workspace

**Config schema:**
```json
{
  "default_language": "",
  "auto_detect": true
}
```

**Deploy sequence:**
```
cp -r library/plugins/horizontal/auto-translate {workspace}/plugins/
```

**Used by:** Multilingual support bots, international e-commerce agents

---

## Vertical Plugins

Vertical plugins target specific domains and are typically paired with a matching
agent template.

---

### support / ticket-tracker

**Purpose:** Full ticket lifecycle management with JSON persistence. Provides
CRUD operations for support tickets and auto-enriches TKT-XXXX references in
responses with live status. Foundation for the support suite.

**Adds:**
- Tool: `create_ticket` — open a new ticket (title, description, priority)
- Tool: `update_ticket` — change status, title, description, or priority
- Tool: `get_ticket` — fetch a single ticket by ID
- Tool: `list_tickets` — filter by status or priority
- Hook: `before_response` (modifying) — replaces TKT-XXXX refs with live status
- Hook: `on_startup` / `on_shutdown` — load/save `tickets.json`
- Context provider: "Open tickets: N (P0: X, P1: Y)"
- Persistence: `tickets.json` in workspace

**Config schema:**
```json
{
  "auto_link_responses": true
}
```

**Deploy sequence:**
```
cp -r library/plugins/vertical/support/ticket-tracker {workspace}/plugins/
```

**Used by:** Customer support template, help-desk agents

---

### support / sla-monitor

**Purpose:** Background SLA breach detection. Reads `tickets.json` produced by
ticket-tracker and sends an alert via `process_direct` when tickets breach or
approach their deadline. No shared module — direct file read.

**Adds:**
- Service: `_SLAMonitor` (RuntimeAware) — asyncio polling loop
- Tool: `get_sla_report` — formatted SLA status table for all open tickets
- Context provider: "SLA monitor: checking every 30m, warning at 2h before breach"

**Config schema:**
```json
{
  "check_interval_minutes": 30,
  "warning_hours": 2,
  "sla_rules": {"P0": 4, "P1": 8, "P2": 24, "P3": 72}
}
```

**Deploy sequence:**
```
cp -r library/plugins/vertical/support/ticket-tracker {workspace}/plugins/
cp -r library/plugins/vertical/support/sla-monitor {workspace}/plugins/
```

**Used by:** Customer support template (deploy alongside ticket-tracker)

---

### support / csat-survey

**Purpose:** Post-resolution satisfaction surveys. Detects when `update_ticket`
sets status to `resolved` and appends a survey invitation. Persists responses
and exposes a summary report.

**Adds:**
- Tool: `record_csat` — save score (1–5) and comment for a ticket
- Tool: `get_csat_report` — avg score, response count, score distribution
- Hook: `after_tool_call` (modifying) — appends survey prompt on ticket resolution
- Hook: `on_startup` / `on_shutdown` — load/save `csat.json`
- Context provider: "CSAT: 4.2/5 avg (17 surveys)"
- Persistence: `csat.json` in workspace

**Config schema:**
```json
{
  "survey_message": "How satisfied were you with this resolution? Please rate 1-5 and use record_csat to log your response.",
  "min_surveys_for_report": 3
}
```

**Deploy sequence:**
```
cp -r library/plugins/vertical/support/ticket-tracker {workspace}/plugins/
cp -r library/plugins/vertical/support/csat-survey {workspace}/plugins/
```

**Used by:** Customer support template (deploy alongside ticket-tracker)
