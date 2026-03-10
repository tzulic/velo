# Plugin Catalog

This catalog lists all plugins available in the nanobot library.
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

## Not Yet Available

These plugins are planned for a future release.

| Plugin | Description |
|--------|-------------|
| `rate-limiter` | Per-user or global request throttling with configurable windows |
| `auto-translate` | Detect incoming message language and translate responses |

---

## Vertical Plugins

Vertical plugins target specific domains and are typically paired with a matching
agent template.

*(Vertical plugin entries are added as templates are released.)*
