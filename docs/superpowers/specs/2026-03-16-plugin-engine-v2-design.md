# Plugin Engine v2 — Phase 1 Design Spec

> Phase 1 of 3. Upgrades Velo's plugin infrastructure to support the library expansion in Phases 2 (personal assistant plugins) and 3 (business vertical plugins).

---

## Context

Velo's plugin system currently has 6 hooks, no manifests, no config validation, and a single-phase lifecycle (`setup()`). This is insufficient for the next wave of plugins that need to observe message flow, cancel outgoing messages, track sessions, receive webhooks, and validate config before runtime.

This spec brings Velo's plugin engine to production parity with OpenClaw's plugin system, adapted for Velo's Python stack and Volos's managed service model.

### What This Enables

- **Phase 2 plugins** (email triage, smart calendar, task manager, proactive engine) need `session_start`, `session_end`, `message_received`, `before_prompt_build` hooks
- **Phase 3 plugins** (SDR follow-up, CRM sync, compliance, marketing ops) need `message_sending` with cancel, `before_message_write` for PII redaction, HTTP routes for webhooks
- **Volos agent** can validate plugin config without loading code, discover plugins via machine-readable manifests, and report clear errors to customers

### References

- OpenClaw plugin system: `~/openclaw/src/plugins/` (TypeScript, 25 hooks, manifest-based)
- Velo current plugin system: `velo/plugins/` (Python, 6 hooks, convention-based)
- Demand research: `~/Volos/ai-agent-demand-research.md`

---

## 1. Hook System Expansion (6 → 20)

### 1.1 Execution Strategies

Three strategies replace the current two:

| Strategy | Behavior | Current Equivalent |
|----------|----------|--------------------|
| `fire_and_forget` | All callbacks run in parallel via `asyncio.gather`. Errors logged, never propagate. | Same as today |
| `modifying` | Sequential by priority (lower priority number runs first). Each callback transforms the value. Return `None` = pass through unchanged. Return a dict containing `{"__block": True}` to short-circuit (for `before_tool_call`) or `{"cancel": True}` (for `message_sending`). | Same as today, with cancel/block extension |
| `claiming` | Sequential by priority. First callback to return a truthy result wins; remaining callbacks skipped. | **New** |

### 1.2 The 20 Hooks

#### Agent Lifecycle (5)

| Hook | Strategy | Signature | Purpose |
|------|----------|-----------|---------|
| `before_model_resolve` | modifying | `(model: str, provider: str) → dict \| None` | Override model/provider per turn. Return `{"model": "...", "provider": "..."}` or `None` to pass through. |
| `before_prompt_build` | modifying | `() → dict \| None` | Inject context before prompt assembly. Return `{"prepend_context": "...", "append_context": "..."}` or `None`. |
| `after_prompt_build` | modifying | `(value: str, **kwargs) → str` | Modify assembled system prompt. **Existing hook, unchanged.** |
| `agent_end` | fire_and_forget | `(messages: list, duration_ms: int, **kwargs) → None` | Post-turn analytics, CRM sync, memory capture. |
| `before_reset` | fire_and_forget | `(session_key: str, **kwargs) → None` | Capture state before `/new` clears session. |

#### Message Flow (4)

| Hook | Strategy | Signature | Purpose |
|------|----------|-----------|---------|
| `message_received` | fire_and_forget | `(content: str, channel: str, chat_id: str, metadata: dict, **kwargs) → None` | Log inbound, detect lead intent, trigger qualification. |
| `inbound_claim` | claiming | `(content: str, channel: str, chat_id: str, **kwargs) → dict \| None` | Route/intercept messages before agent. Return `{"handled": True}` to claim, `None` to pass. |
| `message_sending` | modifying | `(value: str, channel: str, chat_id: str, **kwargs) → dict \| str \| None` | Modify or cancel outgoing messages. Return `{"content": "...", "cancel": False}`, `{"cancel": True}`, modified string, or `None` to pass through. **Replaces `before_response`.** |
| `message_sent` | fire_and_forget | `(content: str, channel: str, chat_id: str, **kwargs) → None` | Confirm delivery, log to CRM. |

#### Tool Execution (3)

| Hook | Strategy | Signature | Purpose |
|------|----------|-----------|---------|
| `before_tool_call` | modifying | `(value: dict, tool_name: str, **kwargs) → dict \| None` | Modify tool params. Return `None` to pass through. To block, return `{"__block": True}`. **Existing hook, kwarg renamed from `name` to `tool_name` to match call site.** |
| `after_tool_call` | modifying | `(value: str, tool_name: str, **kwargs) → str` | Modify tool result. **Existing hook, kwarg renamed from `name` to `tool_name` to match call site.** |
| `before_message_write` | modifying | `(value: dict, **kwargs) → dict \| None` | Modify or block (`None`) message before JSONL persistence. For PII redaction, debug filtering. |

#### Session (4)

| Hook | Strategy | Signature | Purpose |
|------|----------|-----------|---------|
| `session_start` | fire_and_forget | `(session_key: str, channel: str, chat_id: str, **kwargs) → None` | Initialize per-customer state, start SLA timer. **Trigger:** first message with a session key not seen before (lazy session creation in SessionManager). |
| `session_end` | fire_and_forget | `(session_key: str, message_count: int, duration_ms: int, **kwargs) → None` | Write summary to CRM, trigger CSAT, compute SLA metrics. **Triggers:** (1) `/new` or `/reset` command, (2) idle timeout (configurable, default 30 min no messages), (3) gateway shutdown. SessionManager needs new idle-timeout detection logic. |
| `subagent_spawned` | fire_and_forget | `(child_session_key: str, parent_session_key: str, **kwargs) → None` | Track escalation subagents. |
| `subagent_ended` | fire_and_forget | `(child_session_key: str, outcome: str, error: str \| None, **kwargs) → None` | Cleanup, route results back. |

#### Gateway (2)

| Hook | Strategy | Signature | Purpose |
|------|----------|-----------|---------|
| `on_startup` | fire_and_forget | `(**kwargs) → None` | **Existing, unchanged.** |
| `on_shutdown` | fire_and_forget | `(**kwargs) → None` | **Existing, unchanged.** |

### 1.3 Migration: `before_response` → `message_sending`

`before_response` is removed. All existing plugins using it migrate to `message_sending`:

**Before:**
```python
ctx.on("before_response", lambda value, **kw: cooldown_msg if throttled else value)
```

**After:**
```python
ctx.on("message_sending", lambda value, **kw: {"cancel": True} if throttled else value)
```

The key difference: `message_sending` can cancel (return `{"cancel": True}`) while `before_response` could only modify.

### 1.4 Implementation

**`velo/plugins/types.py`:**
- Add `"claiming"` to `HookType` literal
- Replace `HOOKS` dict with all 20 entries
- All hooks accept `**kwargs` for forward compatibility

**`velo/plugins/manager.py`:**
- Add `claim()` method:
  ```python
  async def claim(self, hook: str, **kwargs) -> Any:
      """First-claim-wins dispatch. Returns the first truthy result."""
      for entry in self._hooks.get(hook, []):
          try:
              result = await self._call(entry.callback, **kwargs)
              if result:
                  return result
          except Exception:
              logger.exception("plugin.claim_failed: {}", hook)
      return None
  ```
- Update `pipe()` to handle dict returns for `message_sending`:
  ```python
  # If callback returns a dict with "cancel", short-circuit
  if isinstance(result, dict) and result.get("cancel"):
      return result  # Caller checks for cancel
  ```

**Integration points (where hooks are fired):**

| Hook | Fired from |
|------|-----------|
| `before_model_resolve` | `velo/agent/loop.py` — before provider resolution |
| `before_prompt_build` | `velo/agent/context.py` — before prompt assembly |
| `after_prompt_build` | `velo/agent/context.py` — after prompt assembly (existing) |
| `agent_end` | `velo/agent/loop.py` — after turn completes |
| `before_reset` | `velo/agent/loop.py` — on `/new` or `/reset` command |
| `message_received` | `velo/agent/loop.py` — when inbound message arrives |
| `inbound_claim` | `velo/agent/loop.py` — before dispatching to agent |
| `message_sending` | `velo/agent/loop.py` — before publishing outbound |
| `message_sent` | `velo/bus/delivery_queue.py` — after `DeliveryQueue.send()` succeeds (delivery confirmation exists here, not in MessageBus) |
| `before_tool_call` | `velo/agent/loop.py` — before tool execution (existing) |
| `after_tool_call` | `velo/agent/loop.py` — after tool execution (existing) |
| `before_message_write` | `velo/session/manager.py` — before JSONL append |
| `session_start` | `velo/session/manager.py` — on new session creation |
| `session_end` | `velo/session/manager.py` — on session close/timeout |
| `subagent_spawned` | `velo/agent/subagent.py` — after spawn |
| `subagent_ended` | `velo/agent/subagent.py` — after child completes |
| `on_startup` | `velo/plugins/manager.py` — after all plugins activated (existing) |
| `on_shutdown` | `velo/plugins/manager.py` — before shutdown (existing) |

---

## 2. Plugin Manifest System

### 2.1 Manifest Format

Every plugin has a `plugin.json` next to its `__init__.py`:

```json
{
  "id": "escalation-manager",
  "name": "Escalation Manager",
  "version": "1.0.0",
  "description": "Human handoff tool + automatic phrase detection. Sends alerts via Telegram when escalation is triggered.",
  "category": "horizontal",
  "tags": ["support", "escalation", "alerts"],

  "config_schema": {
    "owner_telegram_id": {
      "type": "string",
      "label": "Telegram Chat ID for alerts",
      "help": "Message @userinfobot on Telegram to find yours",
      "placeholder": "123456789",
      "required": true
    },
    "notification_channel": {
      "type": "string",
      "label": "Notification method",
      "enum": ["telegram", "log"],
      "default": "telegram"
    },
    "trigger_phrases": {
      "type": "array",
      "items": { "type": "string" },
      "label": "Auto-escalation trigger phrases",
      "default": ["speak to a human", "urgent", "refund"],
      "advanced": true
    },
    "max_wait_minutes": {
      "type": "integer",
      "label": "Minutes before follow-up reminder",
      "default": 30,
      "advanced": true
    }
  },

  "requires": {
    "channels": ["telegram"],
    "env": [],
    "plugins": []
  },

  "hooks": ["message_sending"],
  "tools": ["escalate_to_human"],
  "services": false,
  "context_provider": false,

  "used_by_templates": ["customer-support", "booking-agent"],

  "ui_hints": {
    "icon": "alert-triangle",
    "color": "orange"
  }
}
```

### 2.2 Config Schema Field Types

| Field | Type | Purpose |
|-------|------|---------|
| `type` | `string` | JSON type: `string`, `integer`, `number`, `boolean`, `array`, `object` |
| `label` | `string` | Human-readable name for Volos agent to show customer |
| `help` | `string` | Instructions for the customer |
| `placeholder` | `string` | Example value |
| `default` | `any` | Applied when field missing from config |
| `required` | `bool` | Plugin disabled if missing |
| `sensitive` | `bool` | Volos agent uses `request_api_key` not chat |
| `enum` | `list` | Valid values |
| `advanced` | `bool` | Skip unless customer explicitly asks |
| `items` | `dict` | Schema for array items |

### 2.3 Discovery Metadata

| Field | Purpose |
|-------|---------|
| `id` | Canonical plugin identifier |
| `name` | Display name |
| `version` | SemVer string |
| `description` | One-line purpose |
| `category` | `horizontal` or `vertical` |
| `tags` | Free-form tags for search |
| `requires.channels` | Required channels |
| `requires.env` | Required environment variables |
| `requires.plugins` | Plugin dependencies (load order) |
| `hooks` | Hook names this plugin uses |
| `tools` | Tool names this plugin registers |
| `services` | Whether plugin runs a background service |
| `context_provider` | Whether plugin injects system prompt context |
| `used_by_templates` | Template names that include this plugin |
| `ui_hints` | Icon, color for future dashboard |

### 2.4 Implementation

**New file: `velo/plugins/manifest.py`**

```python
@dataclass
class PluginManifest:
    id: str
    name: str
    version: str
    description: str
    category: str
    tags: list[str]
    config_schema: dict[str, Any]
    requires: dict[str, list[str]]
    hooks: list[str]
    tools: list[str]
    services: bool
    context_provider: bool
    used_by_templates: list[str]
    ui_hints: dict[str, str]

def load_manifest(plugin_dir: Path) -> PluginManifest | None:
    """Load and parse plugin.json. Returns None if not found."""

def validate_manifest(manifest: PluginManifest) -> list[str]:
    """Return list of validation errors. Empty = valid."""
```

**`velo/plugins/manager.py` changes:**
- `discover()` reads `plugin.json` manifests. Plugins without a manifest fail to load (no fallback — all plugins must have `plugin.json`).
- `_register_plugin()` validates config against manifest schema before calling `register()`
- `PluginMeta` dataclass gets a `manifest: PluginManifest | None` field

### 2.5 Manifests to Create

All 16 plugins get a `plugin.json`:

**Horizontal (8):** escalation-manager, business-hours, conversation-analytics, scheduled-digest, knowledge-base, webhook-receiver, rate-limiter, auto-translate

**Vertical (6):** lead-scorer, availability-checker, health-checker, ticket-tracker, sla-monitor, csat-survey

**Builtin (2):** heartbeat, composio

---

## 3. Two-Phase Plugin Lifecycle

### 3.1 The Two Phases

| Phase | When | What Goes Here |
|-------|------|----------------|
| `register(ctx)` | During discovery. Synchronous. | Declare tools, hooks, context providers. Validate config. No I/O, no connections, no background tasks. |
| `activate(ctx)` | After all plugins registered. Async-safe. | Start services, open connections, warm caches, run initial data loads. |

### 3.2 Plugin API

```python
def register(ctx: PluginContext) -> None:
    """Required. Declare capabilities. No side effects."""
    api_key = ctx.config.get("api_key", "")
    if not api_key:
        ctx.disable("Missing required config: api_key")
        return

    ctx.register_tool(MyTool(api_key))
    ctx.on("message_sending", my_hook)

def activate(ctx: PluginContext) -> None:
    """Optional. Start services. Called after all plugins registered."""
    ctx.register_service(MyPollingService(ctx.config))
```

### 3.3 PluginContext Additions

```python
class PluginContext:
    # ... existing methods ...

    def disable(self, reason: str) -> None:
        """Gracefully disable this plugin during registration.

        Args:
            reason: Human-readable explanation logged and available to Volos agent.
        """
        self._disabled = True
        self._disable_reason = reason
```

### 3.4 Loading Sequence

```python
async def load_all(self) -> None:
    # Phase 0: Discover
    metas = self.discover()  # Read plugin.json manifests

    # Phase 1: Register
    for meta in metas:
        self._validate_config(meta)   # Check config against manifest schema
        self._register_plugin(meta)   # Call register()
        # If ctx._disabled, log reason and skip this plugin

    # Sort all hooks by priority
    for hook_name in self._hooks:
        self._hooks[hook_name].sort(key=lambda e: e.priority)

    # Phase 2: Activate
    for meta in [m for m in metas if m.enabled]:
        await self._activate_plugin(meta)  # Call activate() if it exists

    # Phase 3: Start services + fire startup hooks
    await self.start_services()
    await self.fire("on_startup")
```

### 3.5 No Backward Compatibility

- `setup()` is not supported. Plugins without `register()` fail with: `"Plugin '{name}' has no register() function"`
- All 16 existing plugins are migrated as part of this spec

### 3.6 Plugin Migration Map

| Plugin | `register()` only | Needs `activate()` |
|--------|:------------------:|:------------------:|
| escalation-manager | x | |
| business-hours | x | |
| conversation-analytics | x | |
| rate-limiter | x | |
| auto-translate | x | |
| lead-scorer | x | |
| ticket-tracker | x | |
| csat-survey | x | |
| composio (builtin) | x | |
| scheduled-digest | | x |
| knowledge-base | | x |
| webhook-receiver | | x |
| health-checker | | x |
| sla-monitor | | x |
| heartbeat (builtin) | | x |

---

## 4. HTTP Route Registration

### 4.1 API

```python
def register(ctx: PluginContext) -> None:
    ctx.register_http_route(
        method="POST",
        path="/webhooks/stripe",
        handler=handle_stripe_webhook,
        metadata={"auth": "signature", "service": "stripe"},
    )
```

### 4.2 Request/Response Types

```python
@dataclass
class HttpRequest:
    method: str
    path: str
    body: bytes
    headers: dict[str, str]
    query_params: dict[str, str]

@dataclass
class HttpResponse:
    status: int = 200
    body: str | bytes = ""
    headers: dict[str, str] = field(default_factory=dict)
```

### 4.3 Design Rules

- All plugin routes prefixed with `/plugins/` (e.g., `/plugins/webhooks/stripe`)
- Route collisions detected at registration time — second plugin fails with clear error
- No auth middleware — plugins handle their own signature verification
- Handlers are async functions: `async def handler(request: HttpRequest) -> HttpResponse`
- Gateway mounts routes during activation phase

### 4.4 Implementation

**New file: `velo/plugins/http.py`**
- `HttpRequest`, `HttpResponse` dataclasses
- `RouteTable` class: stores registered routes, detects collisions, dispatches requests
- `PluginHttpServer` class: lightweight aiohttp server that serves plugin routes

**`velo/plugins/types.py`:**
- Add `register_http_route()` to `PluginContext`
- Add `_collect_http_routes()` internal method

**`velo/plugins/manager.py`:**
- Collect routes from all plugins after registration
- Start `PluginHttpServer` during activation phase (if any routes registered)

**Gateway HTTP server (new infrastructure):**

The Velo gateway (`velo/cli/commands.py:gateway()`) currently runs only an asyncio event loop with a MessageBus — it has no HTTP server. This spec adds a lightweight aiohttp server specifically for plugin routes:

- **New class:** `PluginHttpServer` in `velo/plugins/http.py`
- **Port:** Reuses the gateway port (default 18790) — the HTTP server binds to it
- **Lifecycle:** Started during plugin activation phase (after all routes collected), stopped during shutdown
- **Scope:** Only serves `/plugins/*` paths. Not a general-purpose web framework.
- **Library:** Uses `aiohttp` (already a dependency via several channels). No new dependencies.
- **If no routes registered:** Server is not started (zero overhead for deployments without webhook plugins)

### 4.5 webhook-receiver Migration

The existing `webhook-receiver` plugin migrates from standalone aiohttp server to `register_http_route()`. Its `_WebhookServer` service class is replaced by route registrations in `register()`. Signature verification logic stays in the handler functions.

---

## 5. Config Schema Validation

### 5.1 Validation Flow

```
Discovery → read plugin.json → parse config_schema
    → read plugin config from config.json
    → validate against schema
    → if errors: disable plugin with clear message
    → if valid: apply defaults, pass to register(ctx)
```

### 5.2 Validation Rules

| Situation | Result |
|-----------|--------|
| Required field missing | Plugin disabled: `"escalation-manager: missing required config 'owner_telegram_id'"` |
| Wrong type | Plugin disabled: `"rate-limiter: 'max_messages' must be integer, got string"` |
| Unknown field | Ignored (forward-compatible) |
| Missing optional with default | Default applied silently |
| Invalid enum value | Plugin disabled with list of valid options |
| No config section, has required fields | Plugin disabled with list of required fields |
| No config section, no required fields | All defaults applied, plugin loads fine |

### 5.3 Implementation

**New file: `velo/plugins/validation.py`**

```python
def validate_config(
    config: dict[str, Any],
    schema: dict[str, Any],
    plugin_name: str,
) -> tuple[dict[str, Any], list[str]]:
    """Validate plugin config against manifest schema.

    Args:
        config: Raw config dict from config.json plugins section.
        schema: config_schema dict from plugin.json manifest.
        plugin_name: For error messages.

    Returns:
        Tuple of (validated config with defaults applied, list of error strings).
        Empty error list = valid.
    """
```

No external dependencies. The schema format is simple enough (type, required, default, enum) to validate with ~80 lines of Python.

---

## 6. File Changes

### 6.1 New Files

| File | Purpose |
|------|---------|
| `velo/plugins/manifest.py` | Load and parse `plugin.json` manifests |
| `velo/plugins/validation.py` | Validate config against schema |
| `velo/plugins/http.py` | `HttpRequest`, `HttpResponse`, `RouteTable` |
| `library/plugins/**/plugin.json` (x14) | Manifests for library plugins |
| `velo/plugins/builtin/heartbeat/plugin.json` | Heartbeat manifest |
| `velo/plugins/builtin/composio/plugin.json` | Composio manifest |
| `tests/plugins/test_manifest.py` | Manifest parsing tests |
| `tests/plugins/test_validation.py` | Config validation tests |
| `tests/plugins/test_http.py` | HTTP route tests |
| `tests/plugins/test_hooks.py` | All 20 hooks fire correctly |
| `tests/plugins/test_lifecycle.py` | Two-phase loading tests |
| `tests/plugins/test_migration.py` | All 16 plugins load with new lifecycle |

### 6.2 Modified Files

| File | Changes |
|------|---------|
| `velo/plugins/types.py` | `claiming` hook type, 20 hooks, `HttpRequest`/`HttpResponse`, `register_http_route()`, `ctx.disable()` |
| `velo/plugins/manager.py` | Two-phase loading, manifest discovery, `claim()` method, HTTP route mounting, config validation |
| `velo/plugins/__init__.py` | Update exports |
| `velo/agent/loop.py` | Fire 10 new hooks at appropriate points |
| `velo/agent/context.py` | Fire `before_prompt_build` hook |
| `velo/bus/delivery_queue.py` | Fire `message_sent` hook after successful delivery |
| `velo/session/manager.py` | Fire `session_start`, `session_end`, `before_message_write` hooks. Add idle-timeout detection for `session_end`. |
| `velo/agent/subagent.py` | Fire `subagent_spawned`, `subagent_ended` hooks |
| `velo/cli/commands.py` | Start `PluginHttpServer` in gateway command if routes are registered |
| All 14 library plugins | `setup()` → `register()` + `activate()` |
| 2 builtin plugins | `setup()` → `register()` + `activate()` |

### 6.3 Unchanged

| File | Why |
|------|-----|
| `velo/providers/*` | Provider system is separate |
| `velo/channels/*` | Hooks fired by bus/loop, not channels |
| `velo/config/schema.py` | Plugin validation in plugin system |
| `velo/cli/*` (except `commands.py`) | No CLI changes beyond gateway HTTP server startup |

---

## 7. Testing Strategy

### 7.1 Unit Tests

| Test File | What It Covers |
|-----------|---------------|
| `test_manifest.py` | Parse valid manifest, missing fields, invalid types, partial manifests |
| `test_validation.py` | Required fields, type checking, defaults, enums, unknown fields, edge cases |
| `test_http.py` | Route registration, collision detection, dispatch, path prefixing |
| `test_hooks.py` | All 20 hooks fire with correct args. `fire()` parallel, `pipe()` sequential, `claim()` first-wins. Error isolation. Priority ordering. |
| `test_lifecycle.py` | Two-phase loading: register-only plugins, register+activate plugins, `ctx.disable()`, missing `register()` error |
| `test_migration.py` | Load each of the 16 migrated plugins, verify tools/hooks/services registered correctly |

### 7.2 Integration Tests

| Test | What It Covers |
|------|---------------|
| Full plugin load cycle | Discover → validate config → register → activate → startup hooks |
| Hook chain | Multiple plugins hooking same event, priority ordering, error in one doesn't block others |
| HTTP route end-to-end | Register route → send HTTP request → handler returns response |
| Config validation failure | Bad config → plugin disabled → clear error → other plugins still load |

---

## 8. Scope Boundaries

### In Scope

- 20 hooks with 3 execution strategies
- `plugin.json` manifests for all 16 plugins
- Two-phase lifecycle (`register`/`activate`)
- HTTP route registration on gateway
- Config schema validation
- Migration of all existing plugins
- Tests

### Out of Scope (Future Phases)

- Plugin install CLI / marketplace
- Dashboard UI for plugin management
- Bundle compatibility (Claude/Codex/Cursor formats)
- Plugin versioning / update system
- New plugins (Phase 2 and 3)
- Volos agent skill updates (separate repo, separate PR)
