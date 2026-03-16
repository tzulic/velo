# Velo Technical Reference

Version: 0.1.4 | Package: `velo-ai` | Python: 3.11+

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Message Flow: End to End](#3-message-flow-end-to-end)
4. [Agent System](#4-agent-system)
   - 4.1 [Agent Loop](#41-agent-loop)
   - 4.2 [Context Builder](#42-context-builder)
   - 4.3 [Memory System](#43-memory-system)
   - 4.4 [Session Management](#44-session-management)
   - 4.5 [Subagent System](#45-subagent-system)
   - 4.6 [Budget Control](#46-budget-control)
   - 4.7 [Context Trimming and Compression](#47-context-trimming-and-compression)
5. [Provider System](#5-provider-system)
   - 5.1 [Base Interface](#51-base-interface)
   - 5.2 [Provider Registry](#52-provider-registry)
   - 5.3 [Native SDK Providers](#53-native-sdk-providers)
   - 5.4 [Provider Health and Fallback](#54-provider-health-and-fallback)
   - 5.5 [How to Add a Provider](#55-how-to-add-a-provider)
6. [Channel System](#6-channel-system)
   - 6.1 [Base Channel](#61-base-channel)
   - 6.2 [Available Channels](#62-available-channels)
   - 6.3 [Access Control](#63-access-control)
7. [Tool System](#7-tool-system)
   - 7.1 [Tool Base Class](#71-tool-base-class)
   - 7.2 [Tool Registry](#72-tool-registry)
   - 7.3 [Deferred Tools](#73-deferred-tools)
   - 7.4 [Built-in Tools](#74-built-in-tools)
   - 7.5 [MCP Tool Integration](#75-mcp-tool-integration)
8. [Skills System](#8-skills-system)
   - 8.1 [Skill Format](#81-skill-format)
   - 8.2 [Built-in Skills](#82-built-in-skills)
   - 8.3 [Skill Self-Improvement](#83-skill-self-improvement)
9. [Configuration](#9-configuration)
   - 9.1 [Schema Structure](#91-schema-structure)
   - 9.2 [File Location and Loading](#92-file-location-and-loading)
   - 9.3 [Key Configuration Values](#93-key-configuration-values)
10. [Security Model](#10-security-model)
    - 10.1 [Memory Write Protection](#101-memory-write-protection)
    - 10.2 [Command Guard](#102-command-guard)
    - 10.3 [External Content Isolation](#103-external-content-isolation)
    - 10.4 [Skill Security Guard](#104-skill-security-guard)
    - 10.5 [Group Chat Restrictions](#105-group-chat-restrictions)
11. [Honcho Integration](#11-honcho-integration)
    - 11.1 [What Honcho Does](#111-what-honcho-does)
    - 11.2 [Dual-Peer Architecture](#112-dual-peer-architecture)
    - 11.3 [Context Injection](#113-context-injection)
    - 11.4 [Configuration](#114-configuration)
12. [Plugin System](#12-plugin-system)
    - 12.1 [Plugin Discovery](#121-plugin-discovery)
    - 12.2 [The Setup Function](#122-the-setup-function)
    - 12.3 [Available Hooks](#123-available-hooks)
    - 12.4 [Built-in Plugins](#124-built-in-plugins)
13. [A2A Protocol](#13-a2a-protocol)
14. [Cron Service](#14-cron-service)
15. [Heartbeat Service](#15-heartbeat-service)
16. [CLI Reference](#16-cli-reference)
17. [Workspace Layout](#17-workspace-layout)
18. [Docker and Deployment](#18-docker-and-deployment)
19. [Dependencies](#19-dependencies)
20. [Design Decisions and Rationale](#20-design-decisions-and-rationale)

---

## 1. Executive Summary

Velo is an open-source personal AI assistant framework. It is the software that Volos (the managed service) deploys for each customer. Velo provides a conversation agent backed by configurable LLM providers, connected to external services through a set of chat channel integrations, and extended through a skills and plugin architecture.

**What Velo is:**
- A long-running async Python process (the "gateway") that listens on multiple chat channels simultaneously
- A stateful agent loop that maintains per-session conversation history, persistent memory, and a skills library
- A multi-provider LLM backend that speaks natively to Anthropic, OpenAI, Mistral, Gemini, and a dozen more APIs without routing through a third-party abstraction layer
- A self-extensible system: the agent can create, edit, and activate skills during a conversation

**What Velo is not:**
- A web API server (it has an internal FastAPI/Starlette app only for the A2A protocol and the dashboard channel)
- A per-user VPS (Volos runs many users on shared infrastructure)
- A RAG pipeline (memory is managed through LLM-assisted consolidation, not vector search)

**Repository:** `github.com/tzulic/velo`
**Package name on PyPI:** `velo-ai`
**Entry point:** `velo` CLI (installed by the package)

---

## 2. Architecture Overview

Velo's runtime is organized into five cooperating layers:

```
┌─────────────────────────────────────────────────────────────────┐
│  Channels  (Telegram, WhatsApp, Discord, Slack, Email, …)       │
│  Each channel is a long-running async task                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ InboundMessage
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  MessageBus  (velo/bus/queue.py)                                 │
│  asyncio.Queue: inbound → agent, outbound ← agent               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  AgentLoop  (velo/agent/loop.py)                                 │
│  - Session management (per channel:chat_id)                     │
│  - Context building (ContextBuilder)                            │
│  - Tool-use loop (up to max_tool_iterations per turn)           │
│  - Memory consolidation (MemoryStore)                           │
│  - Subagent spawning (SubagentManager)                          │
│  - Provider health / fallback                                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ LLMProvider.chat() / chat_stream()
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Providers  (velo/providers/)                                    │
│  Anthropic | OpenAI | Mistral | Gemini | Azure | CLI | …        │
│  Native SDKs. No LiteLLM.                                       │
└─────────────────────────────────────────────────────────────────┘
```

**Supporting subsystems:**
- **Plugin manager** (`velo/plugins/`) — extends the agent with tools, context providers, hooks, services, and channels
- **Skills loader** (`velo/agent/skills.py`) — reads SKILL.md files from workspace and built-in directories; injects summaries into the system prompt
- **Honcho adapter** (`velo/agent/honcho/`) — syncs conversation turns to Honcho for cross-session user modeling
- **Cron service** (`velo/cron/`) — scheduled tasks that feed back into the agent as inbound messages
- **Heartbeat service** (`velo/heartbeat/`) — periodic agent wake-up to check for proactive tasks
- **A2A server** (`velo/a2a/`) — agent-to-agent delegation over HTTP

---

## 3. Message Flow: End to End

This section traces the lifecycle of a single user message from arrival to delivered response.

### 3.1 Inbound path

1. A channel (e.g. Telegram) receives a message from its upstream API.
2. The channel calls `BaseChannel._handle_message()`, which:
   - Checks the sender against the `allow_from` list. Denied senders are silently dropped with a warning log.
   - Wraps the message in an `InboundMessage` dataclass (channel, sender_id, chat_id, content, media, timestamp).
   - Computes `session_key = channel:chat_id` (or uses `session_key_override` for thread-scoped sessions like Slack threads).
   - Calls `await bus.publish_inbound(msg)`, placing the message on `asyncio.Queue`.

### 3.2 Agent loop consumption

3. `AgentLoop.run()` is a long-running coroutine that calls `await bus.consume_inbound()` in a loop.
4. On each message:
   a. A per-session asyncio lock is acquired (prevents concurrent processing for the same session).
   b. `SessionManager.get_or_create(session_key)` retrieves or creates the `Session` object.
   c. If Honcho is active, `honcho.set_current_session(key)` marks which session is being processed; then `honcho.sync_messages()` batches any unsynced turns to the Honcho API, and `honcho.prefetch_context()` fires a background task to get fresh user context for the *next* turn.
   d. `ContextBuilder.build_messages()` assembles the full message list:
      - System prompt (identity + bootstrap files + MEMORY.md + USER.md + plugin context + skills summary)
      - Session history (unconsolidated messages, aligned to a user turn)
      - Runtime context block (current time, channel, chat_id, Honcho user context)
      - Current user message

### 3.3 Tool-use loop

5. The assembled messages are sent to the LLM provider via `chat_with_retry()`.
6. If the response contains tool calls, the loop:
   a. Fires the `before_tool_call` plugin hook.
   b. Executes each tool via `ToolRegistry.execute()`.
   c. Appends the assistant message and tool results to the message list.
   d. Fires the `after_tool_call` plugin hook.
   e. Returns to step 5 for the next iteration.
7. The loop exits when the LLM returns text-only (no tool calls), the `max_tool_iterations` limit is reached, or the iteration budget is exhausted.

### 3.4 Response delivery

8. If streaming is enabled (`send_progress=True`), text chunks are forwarded to the outbound bus as they arrive; the final response is also published.
9. If not streaming, the final response is published as a single `OutboundMessage`.
10. The channel manager's outbound consumer picks up the message and delivers it to the right channel and chat ID.
11. The user message and assistant response are persisted to the session (JSONL or SQLite backend).
12. If `memory_window` messages have accumulated since the last consolidation, `MemoryStore.consolidate()` is called asynchronously using a separate LLM call to update MEMORY.md, HISTORY.md, and USER.md.

---

## 4. Agent System

### 4.1 Agent Loop

**File:** `velo/agent/loop.py`

`AgentLoop` is the central orchestrator. It is created once per gateway or CLI session and runs for the lifetime of the process.

**Constructor parameters (key ones):**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bus` | `MessageBus` | required | Shared message bus |
| `provider` | `LLMProvider` | required | Primary LLM provider |
| `workspace` | `Path` | required | Agent workspace directory |
| `model` | `str` | `"anthropic/claude-opus-4-5"` | LLM model identifier |
| `max_iterations` | `int` | `40` | Max tool-use iterations per turn |
| `memory_window` | `int` | `100` | Messages before consolidation triggers |
| `memory_char_limit` | `int` | `8000` | Soft char limit for MEMORY.md |
| `user_char_limit` | `int` | `4000` | Soft char limit for USER.md |
| `reasoning_effort` | `str\|None` | `None` | Enables LLM extended thinking (`low/medium/high/xhigh`) |
| `fallback_provider` | `LLMProvider\|None` | `None` | Backup provider on primary exhaustion |
| `subagent_model` | `str\|None` | `None` | Cheaper model for background subagents |
| `mcp_servers` | `dict` | `{}` | MCP server configurations |
| `save_trajectories` | `bool` | `False` | Write JSONL turn records to `workspace/trajectories/` |
| `max_iteration_budget` | `int\|None` | `None` | Shared cap across parent + subagents |
| `honcho_config` | `HonchoConfig` | default | Honcho integration settings |

**Session locking:** The loop maintains a `dict[str, asyncio.Lock]` keyed by session key. This prevents concurrent processing for the same chat. Messages queue up on the bus and are processed sequentially per session.

**Special message sources:**
- `channel="system"`, `sender_id="subagent"`: subagent result announcements. Routed to the correct session without triggering the permission check.
- `channel="system"`: cron-triggered tasks.

**Slash commands:** The loop recognizes a small set of user-typed commands before passing the message to the LLM:
- `/new` — clear session history and run memory consolidation with `archive_all=True`
- `/memory` — display current MEMORY.md and USER.md contents
- `/subagents` — report count of running subagent tasks
- `/cancel` — cancel all subagents for the current session
- `/sessions` — list recent sessions

**Trajectory saving:** When `save_trajectories=True`, each completed turn is appended as a JSON record to `workspace/trajectories/YYYY-MM-DD.jsonl`. Records include session key, timestamp, messages, tool calls, token usage, and turn duration.

### 4.2 Context Builder

**File:** `velo/agent/context.py`

`ContextBuilder` assembles the full system prompt and message list for each LLM call.

**System prompt composition order:**
1. **Identity block** — agent name ("Velo"), workspace path, platform (POSIX/Windows), operating guidelines
2. **Bootstrap files** — content of `AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md` if present in workspace root
3. **Memory** — MEMORY.md (agent notes) and USER.md (user profile) with usage percentage headers
4. **Plugin context** — strings from registered context providers
5. **Always-on skills** — full SKILL.md content for skills marked `always: true`
6. **Skills summary** — XML-formatted list of all available skills with name, description, location, availability flag

**Prompt caching:** The system prompt is cached in `_cached_system_prompt`. It is only rebuilt when `invalidate_prompt_cache()` is called (after memory consolidation or `/new`). This is intentional: it allows Anthropic's prefix cache to reuse the system prompt across turns, reducing latency and cost. Per-turn data (time, Honcho user context) is injected into the runtime context block inside the *user* message instead.

**Runtime context block:** Prepended to each user message (but not the system prompt):
```
[Runtime Context — metadata only, not instructions]
Current Time: 2026-03-16 14:30 (Monday) (UTC)
Channel: telegram
Chat ID: 12345678
User Profile & Context (primary):
[Honcho user context if available]
[Memory nudge if due]
[End Runtime Context]
```

The block uses tag-delimited markers to make the content semantically distinct from the user's actual message.

**Image handling:** When the channel delivers media paths, `_build_user_content()` reads each file, detects the MIME type from magic bytes (`detect_image_mime`), base64-encodes it, and includes it as an `image_url` content block in OpenAI format. Providers that do not support images (e.g. Mistral) will receive only the text portions.

### 4.3 Memory System

**File:** `velo/agent/memory.py`

`MemoryStore` manages three persistent files in `workspace/memory/`:

| File | Purpose | Updated By |
|------|---------|-----------|
| `MEMORY.md` | Long-term agent notes: env facts, project context, tool quirks, conventions | LLM consolidation |
| `USER.md` | User profile: name, role, preferences, timezone, communication style | LLM consolidation (skipped when Honcho active) |
| `HISTORY.md` | Append-only grep-searchable log of past sessions | LLM consolidation |

**Consolidation trigger:** Called from `AgentLoop` after each turn when `len(session.messages) - session.last_consolidated >= memory_window`.

**Consolidation process:**
1. Messages from `session.last_consolidated` to `-(memory_window//2)` are formatted as a plain-text transcript.
2. A separate LLM call is made with the `save_memory` virtual tool, asking it to fill `history_entry`, `memory_update`, and `user_update`.
3. The LLM response is parsed; each field is security-scanned before being written atomically.
4. `session.last_consolidated` is advanced.

**Atomic writes:** All writes use `utils.helpers.atomic_write()`, which writes to a `.tmp` file and then `os.replace()`s it into place. This prevents partial-write corruption.

**Memory size management:** When MEMORY.md or USER.md approaches 80% of their configured limits, the consolidation prompt includes a compression hint instructing the LLM to merge duplicates and remove outdated facts.

### 4.4 Session Management

**File:** `velo/session/manager.py`

`SessionManager` provides get-or-create semantics for `Session` objects keyed by `channel:chat_id`.

**Session struct:**
```python
@dataclass
class Session:
    key: str               # "telegram:12345"
    messages: list[dict]   # Full message history (append-only)
    last_consolidated: int # Index of last consolidated message
    last_heartbeat_text: str | None
    last_heartbeat_at: datetime | None
```

**Storage backends:**

*JSONL (default):* Each session is a `{key}.jsonl` file in `workspace/sessions/`. The first line is a JSON metadata record (`_type: "metadata"`). Subsequent lines are message objects. On corrupt lines, the file is backed up and rewritten clean.

*SQLite:* A single `workspace/sessions/sessions.db` file with an FTS5 virtual table for full-text search. Used when `session_backend = "sqlite"` in config. Supports `session_search` tool functionality. Migrates JSONL files automatically on first access.

**History slicing:** `Session.get_history()` returns only the unconsolidated portion of `messages`, aligned to the first `user` role message (to avoid orphaned `tool_result` blocks at the head).

**Session migration:** On startup, sessions previously stored in the legacy path (`~/.velo/sessions/`) are migrated to the workspace-local `sessions/` directory on first access.

### 4.5 Subagent System

**File:** `velo/agent/subagent.py`

Subagents are independent agent loops that run as background asyncio tasks. The primary agent uses the `spawn` tool to delegate work.

**Constraints:**
- `MAX_SPAWN_DEPTH = 1`: subagents cannot spawn other subagents
- `MAX_CHILDREN_PER_SESSION = 5`: maximum concurrent subagents per session

**Subagent tool set:** Read/write/edit/list files, shell exec, web search, web fetch, browser. Notably absent: `message` tool and `spawn` tool.

**Result delivery:** When a subagent completes, it injects an `InboundMessage` with `channel="system"` and `sender_id="subagent"` into the bus. The main agent loop processes this and summarizes the result for the user.

**Budget sharing:** If `max_iteration_budget` is set, the `IterationBudget` object is shared between the parent agent and all its subagents. Subagents check `budget.consume()` at the start of each iteration and stop early if the budget is exhausted.

**Event-driven heartbeat:** On subagent completion, if `on_complete_callback` is set, the subagent notifies the heartbeat service (`push_event()`), which can trigger an immediate heartbeat tick to deliver the result to the user.

### 4.6 Budget Control

**File:** `velo/agent/budget.py`

`IterationBudget` is a shared async counter for limiting LLM call iterations.

- `consume()` returns `False` (and the caller should stop) when `used >= total`
- `warning_message()` returns a text warning injected into the context at 70% and 90% usage, nudging the LLM to wrap up
- Protected by an `asyncio.Lock` so concurrent subagent tasks do not race

### 4.7 Context Trimming and Compression

**Files:** `velo/agent/llm_helpers.py`, `velo/agent/context_compressor.py`

Two complementary mechanisms prevent context overflow:

**Proactive trim** (`trim_to_budget`): When estimated tokens exceed 90% of the context window, the oldest middle messages are removed (while preserving the system message and the trailing user turn). Orphaned tool call/result pairs are removed together to avoid provider 400 errors.

**Context compression** (`compress_context`): When estimated tokens exceed 50% of the context window, the middle messages are summarized by a separate LLM call. The summary is injected as a `[Context Summary]` user message, replacing the middle segment. Thresholds:
- `PROACTIVE_TRIM_THRESHOLD = 0.90` → trim oldest messages
- `COMPRESSION_THRESHOLD = 0.50` → LLM-summarize the middle

Both operations preserve:
1. System message (index 0)
2. Protected head (first 3 messages for compression)
3. Protected tail (last 4 messages for compression; last user turn for trimming)

---

## 5. Provider System

LiteLLM has been fully removed from Velo. Every provider uses its vendor's native Python SDK directly.

### 5.1 Base Interface

**File:** `velo/providers/base.py`

All providers implement `LLMProvider`:

```python
class LLMProvider(ABC):
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse: ...

    async def chat_stream(self, ...) -> AsyncIterator[StreamChunk]: ...

    def get_default_model(self) -> str: ...
```

The message format passed to all providers is OpenAI's format (role/content/tool_calls). Each provider converts this to its own API format internally.

**`LLMResponse` fields:**

| Field | Type | Description |
|-------|------|-------------|
| `content` | `str \| None` | Text response |
| `tool_calls` | `list[ToolCallRequest]` | Requested tool calls |
| `finish_reason` | `str` | `"stop"`, `"tool_calls"`, `"length"`, `"error"` |
| `usage` | `dict[str, int]` | Token counts |
| `reasoning_content` | `str \| None` | Extended thinking output (Kimi, DeepSeek-R1, Claude thinking) |
| `thinking_blocks` | `list[dict] \| None` | Anthropic-format thinking blocks (preserved in history) |
| `error_code` | `str \| None` | Classified error code on failure |

### 5.2 Provider Registry

**File:** `velo/providers/registry.py`

The registry is a tuple of `ProviderSpec` dataclasses that serves as the single source of truth for all provider metadata. Adding a new provider requires only adding an entry here plus a field in `ProvidersConfig`.

**`ProviderSpec` fields:**

| Field | Description |
|-------|-------------|
| `name` | Config field name (e.g. `"dashscope"`) |
| `keywords` | Model-name keywords for auto-detection |
| `provider_type` | Which SDK class to instantiate: `"anthropic"`, `"openai"`, `"mistral"`, `"gemini"`, `"azure"`, `"codex"`, `"cli"`, `"custom"` |
| `is_gateway` | Routes any model; detected by api_key prefix or api_base URL |
| `is_local` | Local deployment (vLLM, Ollama) |
| `detect_by_key_prefix` | e.g. `"sk-or-"` for OpenRouter |
| `detect_by_base_keyword` | Substring match in api_base URL |
| `default_api_base` | Default endpoint URL |
| `strip_model_prefix` | Strip `provider/` prefix before sending to API |
| `model_overrides` | Per-model parameter overrides |
| `is_oauth` | Uses OAuth flow instead of API key |
| `supports_prompt_caching` | Enables cache_control injection |

**Provider matching logic** (in `Config._match_provider()`):
1. If `agents.defaults.provider != "auto"`, use that provider directly.
2. Try explicit provider prefix in model name (e.g. `"anthropic/claude-..."` → anthropic).
3. Try keyword matching against model name.
4. Fall back to first available provider with an API key.

### 5.3 Native SDK Providers

**Anthropic** (`velo/providers/anthropic_provider.py`):
- Converts OpenAI-format messages to Anthropic format (separate `system` block, `tool_result` as user messages, `tool_use` blocks)
- Injects `cache_control: {"type": "ephemeral"}` on the last system block and last tool definition (Anthropic prompt caching)
- Supports OAuth tokens (prefix `sk-ant-oat`) with `claude-code-20250219` and `oauth-2025-04-20` beta headers
- Extended thinking: Claude 4.6 models use `thinking: {type: "adaptive"}` + `output_config: {effort: ...}`; older models use `thinking: {type: "enabled", budget_tokens: N}`
- Enforces role alternation by merging consecutive same-role messages

**OpenAI** (`velo/providers/openai_provider.py`):
- Handles all OpenAI-compatible APIs (OpenAI, DeepSeek, Groq, xAI, OpenRouter, AiHubMix, SiliconFlow, VolcEngine, Zhipu, DashScope, Moonshot, MiniMax, vLLM, custom)
- Passes `extra_headers` for providers that require custom headers (e.g. AiHubMix APP-Code)
- Uses `json_repair` library to handle malformed JSON in tool call arguments

**Mistral** (`velo/providers/mistral_provider.py`):
- Uses `mistralai` SDK
- Converts OpenAI tool format to Mistral's format
- Tool IDs are 9-char alphanumeric (Mistral's constraint)

**Gemini** (`velo/providers/gemini_provider.py`):
- Uses `google-genai` SDK
- Converts message history to Gemini's `Content` object format

**Azure OpenAI** (`velo/providers/azure_openai_provider.py`):
- Direct Azure endpoint calls with `api-version=2024-10-21`
- Requires both `api_key` and `api_base` (deployment URL)

**Claude CLI** (`velo/providers/cli_provider.py`):
- Invokes the `claude` binary as a subprocess
- Uses the user's Claude Max subscription (no API key)
- Supports `bypassPermissions` mode for agentic tasks

**OpenAI Codex** (`velo/providers/openai_codex_provider.py`):
- OAuth-based access to ChatGPT's backend API
- Requires `oauth-cli-kit` for token management

### 5.4 Provider Health and Fallback

**File:** `velo/agent/provider_health.py`

`ProviderHealth` tracks availability with exponential backoff:
- First failure: 60s cooldown
- Second failure: 300s (5 min)
- Third failure: 1500s (25 min)
- Fourth+: 3600s (1 hour)

The agent loop checks health before calling the primary provider. If unavailable and a `fallback_provider` is configured, the fallback is used instead. A probe window (2 minutes before cooldown expires) allows testing whether the primary has recovered.

**Retry logic** (`chat_with_retry` in `velo/agent/llm_helpers.py`): Up to 3 attempts with exponential backoff (1s × 2^attempt) for retryable errors. Retryable error codes: `rate_limit`, `server_error`, `timeout`.

### 5.5 How to Add a Provider

1. Add a `ProviderSpec` to the `PROVIDERS` tuple in `velo/providers/registry.py`
2. Add a corresponding `ProviderConfig` field to `ProvidersConfig` in `velo/config/schema.py`
3. If it uses a novel SDK (not OpenAI-compatible), implement an `LLMProvider` subclass
4. If it uses an OpenAI-compatible API, set `provider_type="openai"` and it will use `OpenAIProvider` automatically

---

## 6. Channel System

### 6.1 Base Channel

**File:** `velo/channels/base.py`

All channels extend `BaseChannel` and implement three methods:
- `start()` — long-running coroutine that listens for messages
- `stop()` — clean shutdown
- `send(msg: OutboundMessage)` — deliver a response

`_handle_message()` is the common entry point that performs permission checking and bus publication.

### 6.2 Available Channels

| Channel | File | Transport |
|---------|------|-----------|
| Telegram | `channels/telegram.py` | python-telegram-bot webhooks/polling |
| WhatsApp | `channels/whatsapp.py` | WebSocket bridge to Node.js (baileys) |
| Discord | `channels/discord.py` | Discord Gateway WebSocket |
| Slack | `channels/slack.py` | Slack Socket Mode |
| Feishu/Lark | `channels/feishu.py` | Feishu WebSocket long connection |
| DingTalk | `channels/dingtalk.py` | DingTalk Stream mode |
| Matrix | `channels/matrix.py` | matrix-nio (E2EE supported) |
| Email | `channels/email.py` | IMAP polling + SMTP send |
| QQ | `channels/qq.py` | qq-botpy SDK |
| Mochat | `channels/mochat.py` | Socket.IO |
| Dashboard | `channels/dashboard.py` | Supabase Realtime (agent-to-agent room) |
| CLI | (built into `cli/commands.py`) | Direct stdin/stdout |

**WhatsApp bridge:** Requires a Node.js companion process. The `velo channels login` command builds and starts the bridge for QR-code pairing.

**Matrix:** E2EE is optional but enabled by default. Requires the `matrix` optional dependency group (`pip install velo-ai[matrix]`).

**Dashboard channel:** Uses Supabase Realtime as a message bus for multi-agent rooms. Supports agent-to-agent conversations with a configurable `max_agent_turns` limit per round.

### 6.3 Access Control

Every channel has an `allow_from` list in its configuration. The behavior is:
- Empty list: deny all (with a warning log)
- `["*"]`: allow all
- `["12345", "67890"]`: allowlist by sender ID (format varies by channel — user ID for Telegram/Discord, phone number for WhatsApp, etc.)

For channels with group/channel support (Slack, Discord, Matrix), a separate `group_policy` controls whether the agent responds to group messages at all: `"open"` (all messages), `"mention"` (only when @-mentioned), `"allowlist"` (specific channel IDs).

---

## 7. Tool System

### 7.1 Tool Base Class

**File:** `velo/agent/tools/base.py`

All tools extend `Tool`:

```python
class Tool(ABC):
    @property
    def name(self) -> str: ...        # Function name for LLM
    @property
    def description(self) -> str: ... # Description for LLM
    @property
    def parameters(self) -> dict: ... # JSON Schema
    async def execute(self, **kwargs) -> str: ...
```

`to_schema()` returns the OpenAI function-calling format used by all providers. Parameter validation and type-casting (`cast_params`, `validate_params`) run before every `execute()` call.

### 7.2 Tool Registry

**File:** `velo/agent/tools/registry.py`

`ToolRegistry` maintains two dictionaries:
- `_tools`: active tools, included in every LLM call's tool list
- `_deferred`: inactive tools, available on-demand via `search_tools`

`execute()` validates parameters, calls `tool.execute()`, applies `sanitize_tool_result()` to the output, and appends a `[Analyze the error above and try a different approach.]` hint to error responses.

### 7.3 Deferred Tools

The deferred pool reduces the number of tool definitions sent to the LLM on every turn. MCP tools and Composio actions default to deferred registration.

**`search_tools` tool:** The agent calls `search_tools(query)` to find relevant deferred tools. The registry uses BM25 scoring against tool names and descriptions, with substring fallback. Matching tools are moved from `_deferred` to `_tools` and become available on the next LLM call.

A `get_deferred_summary()` is included in the system prompt listing deferred tool groups: `github (12 tools), composio:gmail (5 tools)`.

### 7.4 Built-in Tools

| Tool name | File | Description |
|-----------|------|-------------|
| `web_search` | `tools/web.py` | Web search via Parallel.ai |
| `web_fetch` | `tools/web.py` | Fetch and extract URL content via Parallel.ai |
| `browse` | `tools/browse.py` | Full browser automation via Patchright (Playwright fork) |
| `read_file` | `tools/filesystem.py` | Read a file |
| `write_file` | `tools/filesystem.py` | Write a file |
| `edit_file` | `tools/filesystem.py` | Exact string replacement in a file |
| `list_dir` | `tools/filesystem.py` | List directory contents |
| `exec` | `tools/shell.py` | Run a shell command |
| `message` | `tools/message.py` | Send a message to a specific channel/chat |
| `spawn` | `tools/spawn.py` | Spawn a background subagent |
| `cron` | `tools/cron.py` | Schedule/manage cron jobs |
| `skill_manage` | `tools/skill_manage.py` | Create/edit/delete skills |
| `search_tools` | `tools/search.py` | Activate deferred tools |
| `session_search` | `tools/session_search.py` | Full-text search across session history (SQLite backend only) |
| `clarify` | `tools/clarify.py` | Ask a clarifying question (CLI only) |
| `a2a_call` | `tools/a2a_call.py` | Delegate a task to an A2A peer agent |

**Honcho tools** (`velo/agent/honcho/tools.py`): Registered when Honcho is active.
- `honcho_search` — semantic search across session history
- `honcho_profile` — get user's peer card
- `honcho_add_note` — record a structured conclusion about the user
- `honcho_dialectic` — ask Honcho about the user or AI via dialectic reasoning

**Filesystem safety:** `ReadFileTool`, `WriteFileTool`, `EditFileTool`, and `ListDirTool` accept an optional `allowed_dir` parameter. When set (via `restrict_to_workspace=True`), all paths are resolved and checked to be descendants of `allowed_dir`. Attempts to escape are blocked.

**Shell safety:** `ExecTool` runs `command_guard.check_command()` before executing. With `extended_safety=True` (default), 20 additional patterns beyond the original 9 are checked. Environment variables passed to the subprocess are controlled by `env_passthrough` and a minimal safe set.

### 7.5 MCP Tool Integration

**File:** `velo/agent/tools/mcp.py`

Velo connects to MCP servers configured in `tools.mcp_servers`. Both stdio (subprocess) and HTTP/SSE transports are supported.

MCP tools are registered with the prefix `mcp_{server_name}_{tool_name}`. By default (`defer_tools=true`), all MCP tools start in the deferred pool and are activated by `search_tools`.

Each MCP tool call runs with a configurable `tool_timeout` (default 30 seconds).

---

## 8. Skills System

### 8.1 Skill Format

**File:** `velo/agent/skills.py`

Skills are directories under `workspace/skills/{skill-name}/` or `velo/skills/{skill-name}/` (built-in), each containing a `SKILL.md` file.

The SKILL.md format:

```markdown
---
name: github
description: "Interact with GitHub using the gh CLI."
metadata: {"velo":{"emoji":"🐙","requires":{"bins":["gh"]},"always":false}}
---

# Skill Content

Markdown documentation the agent reads to learn how to use this skill.
```

**Frontmatter fields:**
- `name`: Skill identifier
- `description`: Short description shown in the skills summary
- `metadata` (JSON-encoded `velo` key):
  - `requires.bins`: CLI binaries that must be in `$PATH`
  - `requires.env`: Environment variables that must be set
  - `always`: If `true`, skill is always loaded into the system prompt
  - `emoji`: Display emoji (cosmetic)
  - `install`: Install instructions for missing requirements

**Skill loading flow:**
1. `build_skills_summary()` generates an XML list for the system prompt
2. When the agent needs a skill, it calls `read_file` on the SKILL.md path
3. Skills with `always=true` are loaded directly into the system prompt

**Priority:** Workspace skills override built-in skills of the same name.

### 8.2 Built-in Skills

| Skill | Requires | Description |
|-------|----------|-------------|
| `github` | `gh` CLI | GitHub CLI usage (issues, PRs, CI runs) |
| `cron` | — | Scheduling recurring tasks |
| `memory` | — | Memory management guidelines |
| `summarize` | — | Document summarization patterns |
| `tmux` | `tmux` | Terminal session management |
| `weather` | — | Weather query patterns |
| `skill-creator` | — | Guidelines for creating new skills |
| `clawhub` | — | ClaWHub community skill registry |

### 8.3 Skill Self-Improvement

After completing a complex task (5+ tool calls), the system prompt instructs the agent to consider saving reusable procedures as skills via `skill_manage`. This creates workspace-local skills that persist across sessions. The `skill_manage` tool writes content to `workspace/skills/{name}/SKILL.md` after passing it through the skill security guard.

---

## 9. Configuration

### 9.1 Schema Structure

**File:** `velo/config/schema.py`

The root config object is `Config`, a Pydantic `BaseSettings` subclass. All nested models accept both camelCase and snake_case keys (via `alias_generator=to_camel`).

```
Config
├── agents.defaults        AgentDefaults
│   ├── workspace          str  (~/.velo/workspace)
│   ├── model              str  (anthropic/claude-opus-4-5)
│   ├── provider           str  (auto)
│   ├── max_tokens         int  (8192)
│   ├── temperature        float (0.1)
│   ├── max_tool_iterations int  (40)
│   ├── memory_window      int  (100)
│   ├── reasoning_effort   str | None
│   ├── session_backend    "jsonl" | "sqlite"
│   ├── subagent_model     str | None
│   ├── fallback_model     str | None
│   └── save_trajectories  bool
├── channels               ChannelsConfig
│   ├── send_progress      bool
│   ├── send_tool_hints    bool
│   ├── telegram           TelegramConfig
│   ├── whatsapp           WhatsAppConfig
│   ├── discord            DiscordConfig
│   ├── slack              SlackConfig
│   ├── feishu             FeishuConfig
│   ├── dingtalk           DingTalkConfig
│   ├── matrix             MatrixConfig
│   ├── email              EmailConfig
│   ├── qq                 QQConfig
│   ├── mochat             MochatConfig
│   └── dashboard          DashboardConfig
├── providers              ProvidersConfig
│   ├── anthropic          ProviderConfig
│   ├── openai             ProviderConfig
│   ├── openrouter         ProviderConfig
│   ├── deepseek           ProviderConfig
│   ├── gemini             ProviderConfig
│   ├── mistral            ProviderConfig
│   ├── xai                ProviderConfig
│   ├── groq               ProviderConfig
│   ├── dashscope          ProviderConfig
│   ├── moonshot           ProviderConfig
│   ├── zhipu              ProviderConfig
│   ├── minimax            ProviderConfig
│   ├── aihubmix           ProviderConfig
│   ├── siliconflow        ProviderConfig
│   ├── volcengine         ProviderConfig
│   ├── vllm               ProviderConfig
│   ├── azure_openai       ProviderConfig
│   ├── openai_codex       ProviderConfig
│   ├── github_copilot     ProviderConfig
│   ├── claude_cli         CliProviderConfig
│   └── custom             ProviderConfig
├── tools                  ToolsConfig
│   ├── web.search.api_key str  (Parallel.ai key)
│   ├── web.proxy          str | None
│   ├── exec.timeout       int  (60)
│   ├── exec.extended_safety bool (true)
│   ├── exec.env_passthrough list[str]
│   ├── restrict_to_workspace bool (false)
│   └── mcp_servers        dict[str, MCPServerConfig]
├── gateway                GatewayConfig
│   ├── host               str  (0.0.0.0)
│   ├── port               int  (18790)
│   └── heartbeat          HeartbeatConfig
├── a2a                    A2AConfig
├── honcho                 HonchoConfig
└── plugins                dict[str, Any]
```

### 9.2 File Location and Loading

**Default config path:** `~/.velo/config.json`

Config can be overridden per invocation with `--config /path/to/config.json`. When running multiple Velo instances, each gets its own config file; `set_config_path()` tracks the active path globally.

Format is JSON with camelCase keys. Example minimal config:

```json
{
  "agents": {
    "defaults": {
      "model": "claude-sonnet-4-6"
    }
  },
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-..."
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "...",
      "allowFrom": ["123456789"]
    }
  },
  "tools": {
    "web": {
      "search": {
        "apiKey": "..."
      }
    }
  }
}
```

**Environment variable overrides:** All config values can be overridden via environment variables with prefix `VELO_` and `__` as nested delimiter. For example: `VELO_AGENTS__DEFAULTS__MODEL=claude-haiku-4-5`.

### 9.3 Key Configuration Values

**`agents.defaults.provider`:** Normally `"auto"`, which selects the provider based on the model name. Set to a specific provider name (e.g. `"openrouter"`) to force a particular provider regardless of model name.

**`agents.defaults.reasoning_effort`:** Enables extended thinking. Values: `low`, `medium`, `high`, `xhigh`. On Claude 4.6+ this maps to adaptive thinking effort levels; on older models it maps to budget_tokens.

**`channels.send_progress`:** When `true`, streams text chunks to the user channel as they arrive from the LLM.

**`channels.send_tool_hints`:** When `true`, sends brief tool-call hints to the user channel (e.g. "reading file...").

**`tools.restrict_to_workspace`:** When `true`, all file operations and shell commands are confined to the workspace directory.

---

## 10. Security Model

### 10.1 Memory Write Protection

**File:** `velo/agent/security/__init__.py`

Every write to `MEMORY.md`, `USER.md`, and `SKILL.md` passes through `scan_content()`. This function checks for:

- **Invisible characters:** Unicode zero-width and directional override characters (U+200B, U+202A–U+202E, etc.)
- **Prompt injection:** "ignore previous instructions", "you are now", "system prompt override", etc.
- **Deception patterns:** "do not tell the user", role hijack attempts
- **Exfiltration patterns:** curl/wget with credential variables, cat of sensitive files
- **Backdoors:** authorized_keys references
- **Code execution:** shebangs, `eval()`, `exec()` in markdown context

If any pattern matches, the write is blocked and logged. This is a defense against indirect prompt injection from web content that the agent processes and might try to save.

### 10.2 Command Guard

**File:** `velo/agent/security/command_guard.py`

`check_command()` blocks catastrophic shell commands before they reach the OS:

- Recursive delete of `/`, `~`, or `.`
- Filesystem formatting (`mkfs`, `format C:`)
- Direct disk writes (`dd if=... of=/dev/sd`)
- Fork bombs
- Reverse shells (`bash -i >& /dev/tcp/`, `nc -e`)
- Privilege escalation (`sudo`, `su`, `chroot`)
- System power control (`shutdown`, `reboot`)
- Credential leakage (`cat config.json`, `printenv`, `cat .env`)

The guard uses **context classification** to avoid false positives: a command that merely contains `rm -rf /` inside an `echo` statement or single quotes is not blocked.

### 10.3 External Content Isolation

**File:** `velo/agent/security/external_content.py`

`wrap_external_content()` wraps all content from web fetches, emails, and external sources with boundary markers:

```
<<<EXTERNAL_UNTRUSTED_CONTENT id="a3f9b2c1">>>
[content]
<<<END_EXTERNAL_UNTRUSTED_CONTENT id="a3f9b2c1">>>
```

The unique ID per wrapping makes the boundaries harder to spoof. The same threat patterns from `THREAT_PATTERNS` are scanned; detections are logged as warnings but do not block delivery (defense-in-depth, not denial, since legitimate content may contain pattern-matching phrases).

### 10.4 Skill Security Guard

**File:** `velo/agent/security/skill_guard.py`

`scan_skill()` provides a more comprehensive scan for skill content with 30+ patterns across 10 categories: exfiltration, prompt injection, destructive commands, persistence mechanisms (crontab, dotfiles, systemd), network (reverse shells, tunnel services), obfuscation (base64 decode pipe, hex encoding), supply chain (curl-pipe-bash, npm/pip installs), privilege escalation, agent config modification, and hardcoded secrets.

**Trust levels and policy:**

| Trust level | Safe | Caution | Dangerous |
|-------------|------|---------|-----------|
| `builtin` | allow | allow | allow |
| `volos-curated` | allow | allow | allow |
| `community` | allow | block | block |
| `agent-created` | allow | block | block |

Community and agent-created skills with any high-severity finding are blocked.

### 10.5 Group Chat Restrictions

In group chat sessions (`session.metadata["is_group"] = True`), the tool registry filters out:
`exec`, `write_file`, `edit_file`, `skill_manage`, `cron`, and `spawn`.

This prevents multi-user group conversations from triggering side-effecting operations.

---

## 11. Honcho Integration

### 11.1 What Honcho Does

Honcho (honcho.dev, by Plastic Labs) is a user-modeling platform. It stores conversation history, builds user representations ("peer cards"), and provides:
- **Free context:** Formatted user context string, injected every turn
- **Semantic search:** Across all past sessions for this user
- **Dialectic queries:** "What does this user prefer?" answered by Honcho's reasoning layer

In Volos deployments, Honcho is the primary user-context layer. Local `MEMORY.md`/`USER.md` remain as agent-notes (operational facts), while Honcho manages user identity, preferences, and cross-session continuity.

### 11.2 Dual-Peer Architecture

Each Honcho session contains two peers:
- `"user"` peer: represents the human
- `"{ai_peer}"` peer (default: `"velo"`): represents the AI assistant

Both peers observe each other (`observe_others=True`), enabling theory-of-mind modeling. On first session creation, `SOUL.md` content from the workspace is seeded as an observation on the AI peer to establish the assistant's identity.

### 11.3 Context Injection

Honcho context is injected into the **runtime context block** (inside the user message), not the system prompt. This is deliberate: the system prompt stays stable across turns, preserving Anthropic's prefix cache. Per-turn Honcho context changes without invalidating the cached system prefix.

**Context prefetch:** After processing each turn, the adapter fires a background task (`prefetch_context()`) that fetches fresh user context and peer card for the *next* turn. This hides the ~200ms Honcho API latency.

**Peer card sync:** When `sync_peer_card_to_user_md=true`, the user peer card is written to `workspace/memory/USER.md` on change (hash-based dedup). This gives offline visibility into what Honcho knows about the user.

**Recall modes:**
- `hybrid` (default): context auto-injected + Honcho tools available
- `context`: only auto-injection, no tools
- `tools`: only tools, no auto-injection

### 11.4 Configuration

**File:** `velo/agent/honcho/config.py`

```json
{
  "honcho": {
    "enabled": true,
    "apiKey": "...",
    "apiBase": "https://api.honcho.dev",
    "workspaceId": "default",
    "aiPeer": "velo",
    "writeFrequency": "async",
    "recallMode": "hybrid",
    "contextTokens": null,
    "dialecticReasoningLevel": "low",
    "dialecticMaxChars": 600,
    "observePeers": true,
    "seedIdentity": true,
    "syncPeerCardToUserMd": true
  }
}
```

`write_frequency` controls when messages are synced to Honcho:
- `"async"` (default): fire-and-forget background task
- `"turn"`: await sync before responding
- `"session"`: batch at end of session

---

## 12. Plugin System

### 12.1 Plugin Discovery

**File:** `velo/plugins/manager.py`

Plugins are Python packages (directories with `__init__.py`) found in two locations:
1. `velo/plugins/builtin/` — shipped with Velo
2. `{workspace}/plugins/` — workspace-local (dropped by Volos via provisioning)

A plugin can be disabled by setting `plugins.{name}.enabled = false` in config.

### 12.2 The Setup Function

Each plugin must export a `setup(ctx: PluginContext)` function:

```python
def setup(ctx: PluginContext) -> None:
    # Register tools
    ctx.register_tool(MyTool(), deferred=False)

    # Add to system prompt
    ctx.add_context_provider(lambda: "Extra context string")

    # Register a background service
    ctx.register_service(MyService())

    # Register a custom channel
    ctx.register_channel(MyChannel(config, bus))

    # Register hooks
    ctx.on("before_tool_call", my_hook)
```

`PluginContext` receives the plugin's config dict (the section under `plugins.{name}` minus `enabled`) and the workspace path.

### 12.3 Available Hooks

| Hook | Type | Signature | Called when |
|------|------|-----------|-------------|
| `on_startup` | fire-and-forget | `()` | After all plugins loaded |
| `on_shutdown` | fire-and-forget | `()` | On process shutdown |
| `after_prompt_build` | modifying | `(value: str)` | After system prompt built; return modified prompt |
| `before_tool_call` | modifying | `(value: dict, tool_name: str, tool_args: dict)` | Before each tool execution |
| `after_tool_call` | modifying | `(value: str, tool_name: str, result: str)` | After tool execution; return modified result |
| `before_response` | modifying | `(value: str)` | Before response sent to user |

**Fire-and-forget hooks** (`on_startup`, `on_shutdown`): all callbacks run concurrently; exceptions are logged and ignored.

**Modifying hooks** (`after_prompt_build`, etc.): callbacks run sequentially; each receives the output of the previous one. Exceptions skip the failing callback and pass the value through unchanged.

### 12.4 Built-in Plugins

**Composio** (`plugins/builtin/composio/`): Bridges Composio actions as Velo tools. Registers all enabled Composio apps as deferred tools with the `composio_` prefix.

**Heartbeat** (`plugins/builtin/heartbeat/`): Exposes the heartbeat service to plugins.

---

## 13. A2A Protocol

**Files:** `velo/a2a/`

Velo implements the A2A (Agent-to-Agent) protocol for delegation between agents.

**Server side:** When `a2a.enabled=true`, an ASGI server (Starlette + uvicorn) starts on `a2a.port` (default 18791). It exposes:
- `/.well-known/agent.json` — public AgentCard with skills list
- A2A protocol endpoints for task submission and streaming

Bearer token auth protects all non-discovery endpoints when `a2a.api_key` is set.

**Client side:** The `a2a_call` tool delegates a task to a configured peer:
```json
{
  "a2a": {
    "peers": [
      {"name": "research-agent", "url": "http://192.168.1.2:18791", "apiKey": "..."}
    ]
  }
}
```

The `VeloAgentExecutor` (`velo/a2a/executor.py`) wraps `agent_loop.process_direct()` to satisfy the A2A protocol's task execution interface.

---

## 14. Cron Service

**Files:** `velo/cron/`

The cron service persists scheduled jobs to `~/.velo/cron/jobs.json`. The agent schedules jobs using the `cron` tool, specifying a cron expression, message, target channel, and chat ID.

When a job fires, the gateway's `on_cron_job` callback calls `agent.process_direct()` with a system-injected reminder message. If the agent uses the `message` tool during execution, delivery is assumed handled. Otherwise, if `deliver=true` on the job, the response is sent directly to the configured channel/chat.

The `CronTool.set_cron_context()` method prevents the agent from scheduling new cron jobs while processing an existing one (re-entrancy guard).

---

## 15. Heartbeat Service

**File:** `velo/heartbeat/service.py`

The heartbeat service wakes the agent periodically (default: every 30 minutes) to check for proactive tasks.

**Phase 1 (decision):** The service reads `workspace/HEARTBEAT.md`. If the file exists, the LLM is called with a virtual `heartbeat` tool. It returns either `action=skip` or `action=run` with a task description.

**Phase 2 (execution):** On `run`, the `on_execute` callback passes the task to the agent loop. The gateway's implementation routes to the most recently used non-CLI session.

**Anti-spam features:**
- **Deduplication:** Identical responses within 24 hours are suppressed
- **Quiet hours:** Configurable time window where `on_notify` is skipped (execution still runs and state is recorded)
- **Event-driven wake:** Subagent completion can push an event via `push_event()`, triggering an immediate tick without waiting for the interval

Dedup state persists to the `"heartbeat"` session so it survives process restarts.

---

## 16. CLI Reference

**File:** `velo/cli/commands.py`

The `velo` binary (installed as a console script) provides:

```
velo onboard                     Initialize config and workspace
velo agent                       Start interactive chat (REPL)
velo agent -m "message"          Send single message and exit
velo agent --session cli:name    Use named session
velo agent --workspace /path     Override workspace directory
velo agent --config /path        Override config file
velo agent --no-markdown         Disable Markdown rendering
velo agent --logs                Show runtime logs
velo gateway                     Start the full gateway (all channels, cron, heartbeat)
velo gateway --port 18790        Override port
velo status                      Show config, workspace, and API key status
velo channels status             Show channel enable/config status
velo channels login              QR-code WhatsApp pairing
velo provider login openai-codex OAuth login for OpenAI Codex
```

**Interactive mode input:** Uses `prompt_toolkit` with persistent file history (`~/.velo/cli_history`). The prompt reads with bracketed paste mode (handles multi-line pastes). Terminal state is saved and restored on exit.

**Slash commands in chat:** `/new`, `/memory`, `/subagents`, `/cancel`, `/sessions` (processed by the agent loop, not the CLI).

---

## 17. Workspace Layout

The workspace (`~/.velo/workspace/` by default) holds all runtime data for a single Velo instance:

```
workspace/
├── AGENTS.md          # Bootstrap: agent rules (loaded into system prompt)
├── SOUL.md            # Bootstrap: agent identity/persona
├── USER.md            # Bootstrap: initial user context
├── TOOLS.md           # Bootstrap: custom tool documentation
├── HEARTBEAT.md       # Proactive task list (read by heartbeat service)
│
├── memory/
│   ├── MEMORY.md      # Agent notes (env facts, projects, conventions)
│   ├── USER.md        # User profile (consolidated or synced from Honcho)
│   └── HISTORY.md     # Grep-searchable history log
│
├── sessions/
│   ├── telegram_12345.jsonl   # JSONL session files (or sessions.db for SQLite)
│   └── sessions.db            # SQLite session store (if enabled)
│
├── skills/
│   └── {skill-name}/
│       └── SKILL.md   # User/agent-created skills
│
├── plugins/
│   └── {plugin-name}/
│       └── __init__.py # Workspace-local plugins
│
└── trajectories/
    └── YYYY-MM-DD.jsonl # Turn records (if save_trajectories=true)
```

Bootstrap files (`AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`) are loaded from the workspace root. `velo onboard` syncs default templates from `velo/templates/` if they do not exist.

---

## 18. Docker and Deployment

### 18.1 Dockerfile

The image is based on `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`. Build steps:

1. Install Node.js 20 (for the WhatsApp bridge)
2. Install Python dependencies via `uv pip install`
3. Build the WhatsApp bridge (`npm install && npm run build`)
4. Copy Velo source to `/opt/velo-src` for agent exploration
5. Expose port 18790 (gateway)

The entry point is `velo` with default command `status`.

### 18.2 docker-compose.yml

```yaml
services:
  velo-gateway:
    command: ["gateway"]
    restart: unless-stopped
    ports:
      - 18790:18790
    volumes:
      - ~/.velo:/root/.velo    # Config and workspace
    deploy:
      resources:
        limits: {cpus: '1', memory: 1G}
        reservations: {cpus: '0.25', memory: 256M}
```

The `velo-cli` service profile (`--profile cli`) provides an interactive container.

### 18.3 Volos Deployment Notes

In Volos managed deployments:
- The gateway config is provisioned by the Volos backend and mounted at `/root/.velo/`
- Workspace-local plugins are dropped via SSH
- Honcho `workspace_id` is set per-customer for tenant isolation
- The A2A port (18791) may be exposed for agent-to-agent communication
- The gateway port (18790) is proxied through Volos infrastructure; it is not publicly exposed directly

---

## 19. Dependencies

Key runtime dependencies (from `pyproject.toml`):

| Package | Version | Purpose |
|---------|---------|---------|
| `anthropic` | ≥0.52.0 | Anthropic API SDK |
| `openai` | ≥2.8.0 | OpenAI-compatible APIs |
| `mistralai` | ≥2.0.0 | Mistral AI SDK |
| `google-genai` | ≥1.0.0 | Gemini SDK |
| `honcho-ai` | ≥2.0.1 | Honcho user modeling |
| `parallel-web` | ≥0.4.1 | Parallel.ai web search/fetch |
| `patchright` | ≥1.58.0 | Browser automation (Playwright fork) |
| `mcp` | ≥1.26.0 | MCP client |
| `a2a-sdk[http-server]` | ≥0.3.0 | A2A protocol |
| `rank-bm25` | ≥0.2.2 | BM25 search for deferred tools |
| `json-repair` | ≥0.57.0 | Malformed JSON repair from LLM outputs |
| `python-telegram-bot[socks]` | ≥22.6 | Telegram channel |
| `lark-oapi` | ≥1.5.0 | Feishu/Lark channel |
| `dingtalk-stream` | ≥0.24.0 | DingTalk channel |
| `slack-sdk` | ≥3.39.0 | Slack channel |
| `qq-botpy` | ≥1.2.0 | QQ channel |
| `websockets` | ≥14.0 | WhatsApp bridge WebSocket |
| `realtime` | ≥2.7.0 | Supabase Realtime (dashboard channel) |
| `composio` | ≥0.11.0 | Composio integration |
| `croniter` | ≥6.0.0 | Cron expression parsing |
| `oauth-cli-kit` | ≥0.1.3 | OAuth token management (Codex) |
| `typer` | ≥0.20.0 | CLI framework |
| `prompt-toolkit` | ≥3.0.50 | Interactive CLI input |
| `rich` | ≥14.0.0 | Terminal rendering |
| `loguru` | ≥0.7.3 | Structured logging |

Optional dependency group `matrix`: `matrix-nio[e2e]`, `mistune`, `nh3` (for Matrix E2EE).

---

## 20. Design Decisions and Rationale

### No LiteLLM

LiteLLM was removed and replaced with native SDK providers. The reasons:
- Native SDKs expose provider-specific features (Anthropic prompt caching, extended thinking, Gemini's content structure) that LiteLLM either does not expose or exposes with a delay
- Anthropic's `cache_control` injection requires fine-grained control over message structure that LiteLLM abstracts away
- The abstraction layer added complexity without sufficient benefit for the features Velo needed

### Message format: OpenAI-compatible internally

All providers receive OpenAI-format messages and convert internally. This means:
- The agent loop and context builder only need to know one message format
- Tool results are `role: "tool"` with `tool_call_id`
- Provider-specific conversions are isolated in each provider class

### Deferred tools

Sending 50+ tool definitions to the LLM on every turn increases context size and cost. The deferred pool keeps MCP tools and Composio actions out of the active tool list until the agent explicitly searches for them. This matters most with Anthropic models where tool definitions count toward context usage.

### Prompt caching strategy

The system prompt (identity + bootstrap + memory + skills) is cached in `ContextBuilder._cached_system_prompt` and only rebuilds when invalidated. Per-turn data (time, Honcho context) is injected into the user message's runtime context block. This separation ensures the stable portion of the prompt benefits from Anthropic's prefix cache.

### Two-layer memory (MEMORY.md + Honcho)

`MEMORY.md` stores agent-operational facts: environment configuration, project structure, tool quirks, and conventions discovered during sessions. Honcho stores user-identity facts: who the person is, their preferences, communication style, and cross-session patterns. The two layers serve different audiences — agent-efficiency vs. user-personalization — and have different appropriate backends (local file vs. cloud ML platform).

When Honcho is active, `MemoryStore.consolidate()` skips writing `USER.md` to avoid conflicts with Honcho's peer card syncing.

### Subagent depth limit

`MAX_SPAWN_DEPTH = 1` prevents recursive subagent spawning. Unlimited recursion would be both expensive (each subagent runs its own LLM loop) and difficult to reason about. One level of background parallelism covers the practical use cases (run a slow task while continuing to chat).

### Session locking

Per-session asyncio locks prevent concurrent message processing for the same chat. Without locking, two rapid messages in the same chat could both read the same session state, both process, and write conflicting results. The lock ensures message processing is serialized per session while allowing parallel processing across different sessions.

### Security scan on write, not on read

The threat-pattern scanner runs at write time (when saving to MEMORY.md, USER.md, or SKILL.md), not at read time. This is because the threat is indirect prompt injection: malicious content from the web gets processed by the agent and might be saved to a file that is loaded into the system prompt on every future turn. Blocking at write time stops the contamination before it becomes persistent.
