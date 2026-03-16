# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Velo

Velo is an open-source personal AI assistant framework. It runs as a daemon on a VPS, connects to chat platforms (Telegram, Discord, WhatsApp, Slack, etc.), and routes messages through an LLM with tools. Volos is the managed service that deploys and maintains Velo instances.

## Essential Commands

```bash
# Run tests
uv run pytest -v                          # All tests
uv run pytest tests/test_foo.py -v        # Single file
uv run pytest tests/test_foo.py::test_bar # Single test
uv run pytest -k "memory" -v             # Tests matching keyword

# Lint & format
uv run ruff check .
uv run ruff format .

# Run the agent (CLI mode)
velo agent                                # Interactive REPL
velo agent -m "Hello!"                    # Single message

# Run the gateway (daemon mode — connects to chat channels)
velo gateway

# Docker
docker compose run --rm velo-cli onboard
docker compose up -d velo-gateway
```

Python 3.11+. Package manager: `uv`. Config: `pyproject.toml` with Hatch build backend.

## Architecture

**Message flow:** Channel → MessageBus (inbound queue) → AgentLoop → MessageBus (outbound queue) → Channel

```
velo/
├── agent/              # Core: loop, context builder, memory, subagent, security
│   ├── loop.py         # Main event loop — dispatches messages, calls LLM, executes tools
│   ├── context.py      # Builds system prompt + runtime context (cached until invalidated)
│   ├── memory.py       # Three-layer: MEMORY.md (facts), HISTORY.md (log), USER.md (profile)
│   ├── subagent.py     # Background task spawning (max depth 1, max 5 children/session)
│   ├── skills.py       # Discovers + loads SKILL.md files from workspace + builtins
│   ├── honcho/         # Honcho integration (user context, peer cards, dialectic queries)
│   ├── security/       # Pattern scanning, command guard, log scrubbing, skill guard
│   └── tools/          # Built-in tools + ToolRegistry (active vs deferred two-tier)
├── providers/          # LLM providers — native SDKs, no LiteLLM
│   ├── registry.py     # ProviderSpec registry + factory (single source of truth)
│   ├── anthropic_provider.py  # Claude (prompt caching, extended thinking, streaming)
│   ├── openai_provider.py     # One class, 13 OpenAI-compatible backends
│   ├── mistral_provider.py    # Mistral (9-char tool IDs, EU default)
│   └── gemini_provider.py     # Google Gemini (system_instruction, "model" role)
├── channels/           # Chat platform integrations (13 channels)
├── bus/                # Async message bus (inbound/outbound queues)
├── session/            # Session management (JSONL default, SQLite with FTS5 optional)
├── config/             # Pydantic settings schema + loader (~/.velo/config.json)
├── plugins/            # Plugin system (hooks, context providers, services)
├── cli/                # Typer CLI (onboard, agent, gateway, status, etc.)
├── a2a/                # Agent-to-agent protocol
├── skills/             # Built-in skills (github, weather, cron, memory, etc.)
├── templates/          # Bootstrap files for new workspaces (AGENTS.md, SOUL.md, etc.)
├── cron/               # Scheduled tasks
├── heartbeat/          # Proactive wake-up (checks HEARTBEAT.md every 30 min)
├── metrics/            # Usage tracking
└── utils/              # Helpers (atomic_write, safe_filename, etc.)
```

**Other top-level dirs:**
- `app/` — Volos managed service (FastAPI backend, separate from the velo package)
- `bridge/` — Node.js WhatsApp bridge (bundled in Docker image)
- `tests/` — Mirrors velo structure; uses pytest + pytest-asyncio
- `library/` — Templates and integration recipes
- `dist/` — Build artifacts

## Key Design Patterns

### Provider System
All providers inherit from abstract `LLMProvider`. Provider lookup: explicit type → model name keywords → API key prefix → API base URL. Adding a provider = add `ProviderSpec` to registry + field to `ProvidersConfig`. The `OpenAIProvider` handles 13 backends via a `_BACKEND_DEFAULTS` dict — no subclasses.

### Two-Tier Tool Loading
Tools are either **active** (sent to LLM in context) or **deferred** (discoverable via `search_tools` with BM25 ranking). This reduces context bloat. Tools implement the `Tool` ABC with `name`, `description`, `parameters` (JSON Schema), and `execute()`.

### System Prompt Caching
`context.py` caches the system prompt and reuses it across turns. Cache invalidated by: memory consolidation, `/new`, skill changes, Honcho context changes. Honcho context is injected as runtime (never cached) because it changes every turn.

### Per-Session Concurrency
Different sessions run in parallel; messages within the same session serialize via `WeakValueDictionary` locks. Session key = `"{channel}:{chat_id}"`.

### Memory Consolidation
Append-only messages accumulate in sessions. When unconsolidated count >= `memory_window` (default 100), the LLM is asked to summarize into MEMORY.md/HISTORY.md/USER.md via the `save_memory` tool. Writes are atomic (temp file + rename).

### Graceful Degradation
All external integrations (Honcho, MCP, plugins) catch exceptions — failures are logged but never crash the agent loop.

### Skills
Markdown files (SKILL.md) with YAML frontmatter. Loaded from `workspace/skills/` (user) + `velo/skills/` (builtin), workspace overrides builtins. Agent can create/edit skills via `skill_manage` tool (security-scanned before write).

## Testing Patterns

```python
# The make_loop fixture (tests/conftest.py) creates a minimal AgentLoop:
def test_something(make_loop):
    loop = make_loop()  # Uses AsyncMock provider, tmp workspace
    # Override: make_loop(workspace=Path("/custom"))

# Async tests use pytest-asyncio (asyncio_mode = "auto" in pyproject.toml)
async def test_async_thing(make_loop):
    loop = make_loop()
    result = await loop.some_method()

# Test subdirectories mirror velo/ structure:
# tests/agent/, tests/providers/, tests/channels/, tests/plugins/, etc.
```

## Configuration

Config file: `~/.velo/config.json` (or `VELO_CONFIG_FILE` env var). Pydantic schema in `velo/config/schema.py`. Supports both camelCase and snake_case field names. Key sections: `agents`, `providers`, `channels`, `tools`, `skills`, `honcho`, `a2a`.

## Ruff Settings

Line length 100, target Python 3.11, rules: E/F/I/N/W, E501 ignored (line length not enforced by linter).

## Entry Point

CLI: `velo = "velo.cli.commands:app"` (Typer). Gateway port: 18790.
