# Velo vs Hermes Agent Comparison & LiteLLM Migration Plan

> Full comparison of Velo and Hermes Agent architectures, plus migration plan from LiteLLM to native provider SDKs (Anthropic, OpenAI, Mistral, xAI).

---

## Migration Status: COMPLETE (2026-03-14)

All phases implemented and verified. LiteLLM fully removed, replaced by 4 native SDK providers.

### What Was Delivered

| Phase | Status | Provider | Lines | Tests |
|-------|--------|----------|-------|-------|
| Phase 1 | DONE | `AnthropicProvider` — native `AsyncAnthropic` SDK | ~370 | 29 tests |
| Phase 2 | DONE | `OpenAIProvider` — one class, 13 OpenAI-compat backends | ~310 | 16 tests |
| Phase 3 | DONE | `MistralProvider` — native `mistralai.client.Mistral` SDK | ~290 | 10 tests |
| Phase 4 | DONE | `GeminiProvider` — native `google-genai` SDK | ~360 | 14 tests |
| Phase 5 | DONE | Registry refactor + factory update + cleanup | — | 104 registry/existing tests updated |

**Full test suite: 662 passed, 0 failed**

### Files Changed

| File | Action |
|------|--------|
| `velo/providers/anthropic_provider.py` | NEW — prompt caching, extended thinking (adaptive/budget), streaming |
| `velo/providers/openai_provider.py` | NEW — replaces LiteLLM + CustomProvider for all OpenAI-compat APIs |
| `velo/providers/mistral_provider.py` | NEW — 9-char tool ID normalization, EU server default |
| `velo/providers/gemini_provider.py` | NEW — system_instruction, role "model", synthetic tool_call_ids |
| `velo/providers/registry.py` | REWRITTEN — added `provider_type`, removed `litellm_prefix`/`skip_prefixes`/`env_extras`/`env_key`, added xAI |
| `velo/providers/__init__.py` | UPDATED — exports new providers, removed LiteLLM |
| `velo/cli/commands.py` | UPDATED — `_make_provider()` dispatches by `provider_type` instead of LiteLLM fallback |
| `velo/config/schema.py` | UPDATED — `get_api_base()` resolves defaults for ALL providers, added `xai` config field |
| `pyproject.toml` | UPDATED — added `anthropic>=0.52.0`, `mistralai>=2.0.0`, `google-genai>=1.0.0`; removed `litellm` |
| `velo/providers/litellm_provider.py` | DELETED |
| `velo/providers/custom_provider.py` | DELETED |
| `tests/providers/test_anthropic_provider.py` | NEW |
| `tests/providers/test_openai_provider.py` | NEW |
| `tests/providers/test_mistral_provider.py` | NEW |
| `tests/providers/test_gemini_provider.py` | NEW |
| `tests/providers/test_registry.py` | REWRITTEN — updated for new schema |
| `tests/test_commands.py` | UPDATED — removed LiteLLM test and import |

### Key Design Decisions

1. **OpenAI Chat Completions API** (not Responses API) for cross-provider compatibility
2. **One `OpenAIProvider` class** handles 13 backends via `_BACKEND_DEFAULTS` dict — no per-backend subclasses
3. **Prompt caching** on Anthropic: `cache_control: {"type": "ephemeral"}` on last system block + last tool definition
4. **Extended thinking**: adaptive for Claude 4.6, budget-based for older Claude models
5. **xAI added** as new first-class provider (OpenAI-compatible at `api.x.ai/v1`)
6. **`provider_type`** on `ProviderSpec` drives factory dispatch — clean, extensible pattern

---

## Table of Contents

1. [Velo vs Hermes — Full Comparison](#velo-vs-hermes--full-comparison)
   - [What Hermes Does Better](#what-hermes-does-better)
   - [What Hermes Does Differently](#what-hermes-does-differently-not-necessarily-better)
   - [What Velo Does Better](#what-velo-does-better-than-hermes)
   - [Top Recommendations for Velo](#top-recommendations-for-velo-priority-order)
2. [Current State](#current-state)
3. [Why Drop LiteLLM](#why-drop-litellm)
3. [Target Architecture](#target-architecture)
4. [Provider-by-Provider Breakdown](#provider-by-provider-breakdown)
   - [AnthropicProvider](#1-anthropicprovider--native-sdk)
   - [OpenAIProvider](#2-openaiprovider--openai--openrouter--deepseek--groq)
   - [MistralProvider](#3-mistralprovider--eu-data-sovereignty)
   - [XAIProvider](#4-xaiprovider--xaigrok)
5. [Hermes Agent Reference Patterns](#hermes-agent-reference-patterns)
6. [Mistral SDK Deep Dive](#mistral-sdk-deep-dive)
7. [Migration Plan](#migration-plan)
8. [Estimated Effort](#estimated-effort)

---

## Velo vs Hermes — Full Comparison

Both are personal AI agent frameworks with similar DNA (multi-channel, tool-based, skill system, MCP support). Hermes is by Nous Research, more mature, and community-driven. Here's what stands out.

### What Hermes Does Better

#### 1. Context Compression (Big Win)

Hermes auto-detects when approaching the context window limit and uses an auxiliary LLM (Gemini Flash) to summarize early messages, then chains into a new session via `parent_session_id`. Velo has no equivalent — long conversations just hit the limit.

**Implementation:** `agent/context_compressor.py`
- Triggered at configurable threshold (default 50% of context window)
- Auxiliary LLM (cheap/fast model) summarizes early messages
- Creates child session with summarized context
- Agent loop continues transparently
- Preserves prompt cache (system prompt unchanged)

→ **Steal this.** Add a `context_compressor.py` that triggers at ~50% context usage, summarizes old turns, and continues seamlessly.

#### 2. Session Search (FTS5 Full-Text Search)

Hermes stores all sessions in SQLite with FTS5 full-text search. The agent can recall past conversations with a `session_search` tool — ranked results, LLM-summarized. Velo uses flat JSONL files and relies on `HISTORY.md` grep.

**Implementation:** `hermes_state.py` + `tools/session_search_tool.py`
- SQLite `messages_fts` virtual table (FTS5)
- `session_search` tool available to the agent
- LLM summarization of matching sessions
- Results injected as current-turn user message (not system prompt — preserves cache)

→ **Steal this.** Velo already has a `sqlite` session backend option — add FTS5 indexing and a `session_search` tool.

#### 3. Sandboxed Code Execution

Hermes has `execute_code` — a sandboxed Python REPL with RPC access to other tools but no direct filesystem access. Great for data analysis, calculations, quick scripting without risk.

**Implementation:** `tools/code_execution_tool.py`
- Child process with stripped env vars (security)
- RPC access to available tools (no direct FS)
- Import generation from enabled tools
- Works with delegate_tool for parallel execution

→ **Worth adding.** Especially for Volos customers who want their agent to do data work.

#### 4. Terminal Backend Abstraction

Hermes supports 6 terminal backends through a unified interface:

| Backend | Use Case |
|---|---|
| `local` | Direct shell execution |
| `docker` | Containerized isolation (5GB memory, 50GB disk default) |
| `ssh` | Remote server execution |
| `modal` | Serverless GPU cloud (FaaS) |
| `daytona` | Cloud dev environments with persistence |
| `singularity` | HPC containerization |

All backends support: sudo, resource limits, filesystem persistence, volume mounts. Velo only has local `exec`.

→ **Relevant for Volos.** You're already SSH-ing into customer servers. A proper backend abstraction would clean up the agent→server execution model.

#### 5. Tool Approval / Safety System

Hermes has `tools/approval.py` with regex-based dangerous command detection, per-session approval, and symlink resolution to prevent path traversal:

- Detects: `rm -rf`, `chmod 777`, `curl | bash`, `echo >> ~/.bashrc`, etc.
- Per-session approval flow (user approves dangerous commands interactively)
- `os.path.realpath()` symlink resolution to prevent path traversal
- Sudo password support via `sudo -S` with `shlex.quote()` for injection protection

Velo has `deny_patterns` in config but it's simpler.

→ **Upgrade Velo's safety.** Especially important for a managed service where customers run agents on shared infra.

#### 6. Skin Engine / CLI Theming

Hermes has a data-driven skin system (`hermes_cli/skin_engine.py`):

- 4 built-in themes: default (gold/kawaii), ares (crimson/war-god), mono (grayscale), slate (blue)
- Users drop custom YAML skins into `~/.hermes/skins/`
- Controls: banner colors, spinner faces/verbs/wings, tool prefix, agent name, response label, prompt symbol
- Pure cosmetic, but polished

→ **Nice-to-have**, not urgent for Volos (web-first).

#### 7. TTS/STT Built-in

Hermes has text-to-speech and speech-to-text:

| Feature | Providers |
|---|---|
| TTS | Edge (free), ElevenLabs, OpenAI |
| STT | faster-whisper (local), OpenAI |

Velo only has voice transcription via Groq on Telegram.

→ **Low priority** unless Volos moves to voice interfaces.

#### 8. Image Generation

Hermes integrates FAL.ai for prompt-based image generation (`tools/image_generation_tool.py`). Velo has nothing here.

→ **Skill candidate** — easy to add as a Velo skill rather than a core tool.

#### 9. Honcho (Cross-Session User Modeling)

Hermes integrates Honcho AI (`tools/honcho_tools.py`) for building persistent user profiles across sessions — separate from MEMORY.md:

- `honcho_context` — Retrieve user context from prior sessions
- `honcho_profile` — Build/update user profile from observations
- `honcho_search` — Search user history by topic
- `honcho_conclude` — Summarize findings about user

Tracks preferences, communication style, workflow habits over time.

→ **Interesting for Volos.** Your agents serve the same customer repeatedly — building a richer user model over time could differentiate.

#### 10. Anthropic Prompt Caching

Hermes explicitly sets `cache_control` directives on system prompts for Anthropic models (`agent/prompt_caching.py`). This saves ~75% on input tokens for multi-turn conversations. Velo has basic cache control support but doesn't leverage it fully through LiteLLM.

→ **Direct SDK migration unlocks this properly.** See Phase 1 below.

---

### What Hermes Does Differently (Not Necessarily Better)

| Aspect | Velo | Hermes |
|---|---|---|
| **Agent loop** | Async (asyncio-native) | Synchronous (blocking) |
| **LLM client** | LiteLLM (multi-provider) | OpenAI SDK + Anthropic SDK (direct) |
| **Message bus** | Event bus with queue + delivery | Direct callback dispatch |
| **Plugin system** | Full lifecycle hooks (setup→shutdown) | Self-registering tools at import |
| **Tool registry** | Active + deferred (BM25 search) | All tools loaded, toolset filtering |
| **Config format** | JSON (`config.json`) | YAML (`config.yaml`) |
| **CLI framework** | Typer | Fire + prompt_toolkit |
| **Logging** | Loguru | Standard logging |
| **A2A protocol** | Built-in | Not present |
| **Composio** | Built-in plugin | Not present (MCP-only approach) |
| **Code size** | Smaller, modular files (<500 lines) | Monolithic (5K+ line files) |
| **Session storage** | JSONL (default) + SQLite | SQLite with FTS5 |
| **Memory limits** | 8000 chars (memory) + 4000 chars (user) | 2200 chars (memory) + 1375 chars (user) |
| **Channel count** | 10 (Telegram, Discord, WhatsApp, Slack, Feishu, DingTalk, QQ, Email, Matrix, Mochat) | 7 (Telegram, Discord, WhatsApp, Slack, Signal, Email, Home Assistant) |
| **Skill count** | Smaller curated set | 257 bundled + optional |
| **Test coverage** | Feature-level tests | ~3,000 tests in `tests/` |

---

### What Velo Does Better Than Hermes

#### 1. Async-Native Architecture

Velo is fully async (`asyncio`-native throughout). Hermes's synchronous agent loop is a bottleneck for concurrent users in gateway mode — it runs LLM calls in background threads and uses `threading.Thread` workarounds for interrupt handling.

#### 2. Deferred Tools with BM25 Search

Velo's `search_tools` + deferred tool pool is more context-efficient than Hermes loading all tool schemas into every LLM call. Tools only enter the context window when activated by keyword search.

**Implementation:** `velo/agent/tools/registry.py`
- `search_deferred(query, limit)` — BM25 search on deferred tool descriptions
- `activate(name)` — Move tool from deferred to active pool
- Deferred tools don't consume LLM context until needed

Hermes loads everything and uses `toolsets` to filter — still sends all enabled tool schemas.

#### 3. Plugin System with Lifecycle Hooks

Velo has proper lifecycle hooks:
- `after_config_load` — modify config after loading
- `after_prompt_build` — inject context into system prompt
- `on_turn_start` — pre-processing before each turn
- `on_tool_use` — intercept/modify tool calls
- `setup()` → `set_runtime()` → `start()` → `stop()` → `shutdown()`

Hermes uses self-registration at import time, which is simpler but less extensible.

#### 4. A2A Protocol (Agent-to-Agent)

`velo/a2a/` implements agent-to-agent communication:
- Card discovery (public agent metadata)
- Message sending (authenticated)
- Multi-agent workflows

Hermes doesn't have A2A.

#### 5. Composio Integration (100+ Integrations)

`velo/plugins/builtin/composio/` provides native integration with Composio:
- All tools registered as deferred (activated on demand)
- Routes through `COMPOSIO_BASE_URL` for proxy/call counting
- Supports: Gmail, Slack, GitHub, Notion, Stripe, HubSpot, etc.

Hermes relies entirely on MCP servers for external integrations — no Composio equivalent.

#### 6. Code Organization

Velo keeps files under 500 lines with clear module boundaries. Hermes has monolithic files:
- `run_agent.py` — 5,848 lines
- `cli.py` — 5,931 lines
- `gateway/run.py` — 4,403 lines
- `tools/browser_tool.py` — 73KB

#### 7. Memory Injection Scanning

Both scan for prompt injection, but Velo's scanning is in the core memory module (`velo/agent/memory.py`), applied consistently. Hermes duplicates scanning logic across `prompt_builder.py` and `memory_tool.py`.

#### 8. More Chat Channels

Velo supports 10 channels vs Hermes's 7. Unique to Velo: Feishu/Lark, DingTalk, QQ, Matrix, Mochat. Unique to Hermes: Signal, Home Assistant.

---

### Top Recommendations for Velo (Priority Order)

| Priority | Feature | Source | Effort | Impact |
|---|---|---|---|---|
| **1** | Context compression | Hermes `context_compressor.py` | Medium | High — prevents context overflow |
| **2** | FTS5 session search | Hermes `session_search_tool.py` | Medium | High — agent recalls past conversations |
| **3** | Anthropic prompt caching | Hermes `prompt_caching.py` | Low | High — ~75% input token cost savings |
| **4** | Enhanced command safety | Hermes `approval.py` | Low-Medium | High — critical for managed service |
| **5** | Sandboxed code execution | Hermes `code_execution_tool.py` | Medium | Medium — data work for customers |
| **6** | Terminal backend abstraction | Hermes `environments/` | Medium | Medium — cleaner server management |
| **7** | Cross-session user modeling | Hermes `honcho_tools.py` | Medium | Medium — richer personalization |
| **8** | Image generation | Hermes `image_generation_tool.py` | Low | Low — add as skill |
| **9** | TTS/STT | Hermes `tts_tool.py` | Low | Low — only if voice needed |

---

## Current State

Velo's architecture makes this migration **clean**. LiteLLM is isolated to a single file.

### Files That Touch LiteLLM

| File | Role | LiteLLM Dependency |
|---|---|---|
| `velo/providers/litellm_provider.py` (496 lines) | **Only** file that imports `litellm` | `litellm.acompletion`, config globals |
| `velo/providers/registry.py` (467 lines) | Provider registry with LiteLLM prefix routing | Model prefix strings only |
| `velo/cli/commands.py` | Provider instantiation | None (uses abstract interface) |
| `velo/config/schema.py` | Provider configuration | None (provider names only) |

### Files With Zero LiteLLM Dependency

- `velo/agent/loop.py` — uses abstract `LLMProvider` interface
- `velo/agent/llm_helpers.py` — uses abstract `LLMProvider` interface
- `velo/metrics/usage.py` — no LiteLLM dependency
- All tools, channels, plugins, skills — no LiteLLM dependency

### Existing Direct SDK Providers (Already Bypassing LiteLLM)

| Provider | SDK | File |
|---|---|---|
| `CustomProvider` | `AsyncOpenAI` | `velo/providers/custom_provider.py` |
| `AzureOpenAIProvider` | Raw `httpx` | `velo/providers/azure_provider.py` |
| `CliProvider` | `claude` subprocess | `velo/providers/cli_provider.py` |
| `OpenAICodexProvider` | `oauth_cli_kit` + `httpx` | `velo/providers/codex_provider.py` |

### Base Abstractions (Unchanged by Migration)

```python
# velo/providers/base.py

class LLMProvider(ABC):
    async def chat(self, **kwargs) -> LLMResponse: ...
    async def chat_stream(self, **kwargs) -> AsyncIterator[StreamChunk]: ...

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCallRequest] | None
    finish_reason: str
    usage: dict[str, int]
    reasoning_content: str | None
    thinking_blocks: list | None
    error_code: str | None

@dataclass
class StreamChunk:
    delta: str | None
    tool_calls: list[ToolCallRequest] | None
    finish_reason: str | None
    usage: dict[str, int] | None
    reasoning_content: str | None

@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: str  # JSON string
```

### LiteLLM API Surface Actually Used

```python
import litellm
from litellm import acompletion

# Configuration (litellm_provider.py lines 57-69)
litellm.suppress_debug_info = True
litellm.drop_params = True
litellm.REPEATED_STREAMING_CHUNK_LIMIT = 100
litellm.api_base = api_base
os.environ[spec.env_key] = api_key

# Non-streaming (line 258)
response = await acompletion(**kwargs)

# Streaming (line 360)
response = await acompletion(**kwargs)  # with stream=True
async for chunk in response:
    # chunk.choices[0].delta.content
    # chunk.choices[0].delta.tool_calls
    # chunk.choices[0].finish_reason
```

### LiteLLM-Specific Behaviors to Replace

| Behavior | LiteLLM | Direct SDK Replacement |
|---|---|---|
| Model prefix routing | `anthropic/claude-3` → routes to Anthropic | Provider class selection at config time |
| `drop_params = True` | Silently drops unsupported params | Per-provider kwarg builders |
| Tool call ID normalization | Handled by LiteLLM for some providers | Normalize in each provider |
| Empty content handling | LiteLLM sometimes strips | `_sanitize_empty_content()` already exists |
| Prompt caching injection | Manual `cache_control` on messages | Native SDK cache control |

---

## Why Drop LiteLLM

| Issue | Impact |
|---|---|
| **Black box** | Hides provider-specific features (prompt caching, extended thinking, adaptive reasoning) |
| **Version churn** | LiteLLM updates frequently, sometimes breaks provider mappings |
| **Dependency bloat** | Pulls in 50+ transitive deps you don't need |
| **No control over retries/errors** | `litellm.drop_params = True` silently swallows problems |
| **Token counting** | You already do your own — LiteLLM's is redundant |
| **Model prefix routing** | Fragile string-prefix system (`anthropic/`, `openrouter/`) that breaks with new models |
| **Prompt caching blocked** | Can't use Anthropic's native `cache_control` properly through LiteLLM |
| **Extended thinking blocked** | Can't use `thinking: {"type": "adaptive"}` natively |
| **EU compliance story** | Can't leverage Mistral's EU data residency as a selling point without direct SDK |

---

## Target Architecture

```
velo/providers/
├── base.py                  # LLMProvider, LLMResponse, StreamChunk (UNCHANGED)
├── errors.py                # Error classification (UNCHANGED)
├── registry.py              # Provider registry (SIMPLIFIED — no prefix routing)
├── anthropic_provider.py    # NEW — anthropic SDK
├── openai_provider.py       # NEW — openai SDK (+ OpenRouter, DeepSeek, Groq, vLLM)
├── mistral_provider.py      # NEW — mistralai SDK
├── xai_provider.py          # NEW — openai SDK pointed at xAI (or subclass of openai_provider)
├── azure_provider.py        # EXISTING (keep as-is)
├── cli_provider.py          # EXISTING (keep as-is)
├── codex_provider.py        # EXISTING (keep as-is)
└── litellm_provider.py      # DELETED
```

### Provider → SDK Mapping

| Provider Name | SDK Package | Base URL | Notes |
|---|---|---|---|
| `anthropic` | `anthropic` | `api.anthropic.com` | Native Messages API |
| `openai` | `openai` | `api.openai.com` | Chat Completions API |
| `openrouter` | `openai` | `openrouter.ai/api/v1` | OpenAI-compatible + custom headers |
| `deepseek` | `openai` | `api.deepseek.com` | OpenAI-compatible |
| `groq` | `openai` | `api.groq.com/openai/v1` | OpenAI-compatible |
| `mistral` | `mistralai` | `api.mistral.ai` | Native Mistral SDK |
| `xai` | `openai` | `api.x.ai/v1` | OpenAI-compatible |
| `vllm` | `openai` | User-configured | OpenAI-compatible |
| `aihubmix` | `openai` | User-configured | OpenAI-compatible + `APP-Code` header |
| `siliconflow` | `openai` | User-configured | OpenAI-compatible |
| `azure_openai` | `httpx` | Azure endpoint | Existing provider (unchanged) |
| `claude_cli` | subprocess | N/A | Existing provider (unchanged) |
| `openai_codex` | `httpx` | Codex endpoint | Existing provider (unchanged) |

---

## Provider-by-Provider Breakdown

### 1. AnthropicProvider — Native SDK

```python
from anthropic import AsyncAnthropic

class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, api_base: str | None = None):
        self.client = AsyncAnthropic(
            api_key=api_key,
            base_url=api_base,
            timeout=httpx.Timeout(timeout=900.0, connect=10.0),
            default_headers={"anthropic-beta": "interleaved-thinking-2025-05-14"},
        )
```

#### What You Gain

- **Prompt caching** — `cache_control: {"type": "ephemeral"}` on system prompt + last tool def. ~75% input token savings on multi-turn conversations
- **Extended thinking** — `thinking: {"type": "adaptive"}` + `output_config: {"effort": "medium"}` for Claude 4.6 models
- **Native streaming** — `async with client.messages.stream()` with proper event types
- **Direct error types** — `anthropic.RateLimitError`, `anthropic.AuthenticationError`, etc.

#### Message Format Conversion

| OpenAI Format | Anthropic Format |
|---|---|
| `{"role": "system", "content": "..."}` in messages array | Separate `system=` parameter on API call |
| `{"role": "assistant", "tool_calls": [{...}]}` | `{"role": "assistant", "content": [{"type": "tool_use", ...}]}` |
| `{"role": "tool", "tool_call_id": "...", "content": "..."}` | `{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "...", "content": "..."}]}` |
| Consecutive same-role messages allowed | Must alternate `user`/`assistant` — merge consecutive same-role |

#### Tool Schema Conversion

```python
# OpenAI format (what Velo tools produce)
{
    "type": "function",
    "function": {
        "name": "exec",
        "description": "Execute a shell command",
        "parameters": {"type": "object", "properties": {...}}
    }
}

# Anthropic format (what the API expects)
{
    "name": "exec",
    "description": "Execute a shell command",
    "input_schema": {"type": "object", "properties": {...}}
}
```

#### Tool Choice Mapping

| OpenAI | Anthropic |
|---|---|
| `"auto"` | `{"type": "auto"}` |
| `"required"` | `{"type": "any"}` |
| `"none"` | Omit `tool_choice` |
| `{"function": {"name": "X"}}` | `{"type": "tool", "name": "X"}` |

#### Response Normalization

```python
def _normalize_response(self, response) -> LLMResponse:
    text_parts = []
    reasoning_parts = []
    tool_calls = []

    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "thinking":
            reasoning_parts.append(block.thinking)
        elif block.type == "tool_use":
            tool_calls.append(ToolCallRequest(
                id=block.id,
                name=block.name,
                arguments=json.dumps(block.input),  # dict → JSON string
            ))

    stop_reason_map = {
        "end_turn": "stop",
        "tool_use": "tool_calls",
        "max_tokens": "length",
    }

    return LLMResponse(
        content="\n".join(text_parts) or None,
        tool_calls=tool_calls or None,
        finish_reason=stop_reason_map.get(response.stop_reason, "stop"),
        usage={"prompt_tokens": response.usage.input_tokens, "completion_tokens": response.usage.output_tokens},
        reasoning_content="\n\n".join(reasoning_parts) or None,
        thinking_blocks=[...],
    )
```

#### Prompt Caching Implementation

Based on Hermes's `prompt_caching.py` — 4 cache breakpoints max:

```python
def _apply_cache_control(self, system: str, tools: list[dict], messages: list[dict]):
    """Inject cache_control markers for Anthropic prompt caching."""

    # Cache the system prompt (stable across all turns)
    # → system = [{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]

    # Cache the last tool definition (stable across most turns)
    if tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}

    # Cache last 2 user messages (rolling window)
    user_indices = [i for i, m in enumerate(messages) if m["role"] == "user"]
    for idx in user_indices[-2:]:
        messages[idx]["cache_control"] = {"type": "ephemeral"}
```

#### Extended Thinking Configuration

```python
def _build_thinking_params(self, model: str, reasoning_effort: str | None) -> dict:
    """Map reasoning_effort to Anthropic thinking config."""
    if not reasoning_effort:
        return {}

    effort = reasoning_effort.lower()

    if self._supports_adaptive(model):  # Claude 4.6 models
        return {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": {
                "xhigh": "max", "high": "high",
                "medium": "medium", "low": "low",
            }.get(effort, "medium")},
        }
    else:  # Older Claude models
        budgets = {"xhigh": 32000, "high": 16000, "medium": 8000, "low": 4000}
        return {
            "thinking": {"type": "enabled", "budget_tokens": budgets.get(effort, 8000)},
            "temperature": 1,  # Required when thinking is enabled
        }
```

---

### 2. OpenAIProvider — OpenAI + OpenRouter + DeepSeek + Groq

```python
from openai import AsyncOpenAI

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, api_base: str, extra_headers: dict | None = None):
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers=extra_headers,
        )
```

#### One Provider, Many Backends

| Backend | `api_base` | `extra_headers` |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | None |
| OpenRouter | `https://openrouter.ai/api/v1` | `{"HTTP-Referer": "https://volos.dev", "X-OpenRouter-Title": "Velo Agent"}` |
| DeepSeek | `https://api.deepseek.com` | None |
| Groq | `https://api.groq.com/openai/v1` | None |
| xAI | `https://api.x.ai/v1` | None |
| vLLM | User-configured | None |
| AiHubMix | User-configured | `{"APP-Code": "..."}` |
| SiliconFlow | User-configured | None |

#### What You Gain

- Direct control over `parallel_tool_calls`, `reasoning_effort`, streaming options
- OpenRouter prompt caching via `prompt_cache_key` header
- No model prefix strings — model name passed as-is
- Proper error types from `openai` SDK

#### API Call Pattern

```python
async def chat(self, **kwargs) -> LLMResponse:
    response = await self.client.chat.completions.create(
        model=kwargs["model"],
        messages=kwargs["messages"],
        tools=kwargs.get("tools"),
        tool_choice=kwargs.get("tool_choice", "auto"),
        temperature=kwargs.get("temperature", 0.3),
        max_tokens=kwargs.get("max_tokens"),
        parallel_tool_calls=kwargs.get("parallel_tool_calls", True),
    )
    return self._normalize_response(response)

async def chat_stream(self, **kwargs) -> AsyncIterator[StreamChunk]:
    kwargs["stream"] = True
    response = await self.client.chat.completions.create(**kwargs)
    async for chunk in response:
        delta = chunk.choices[0].delta
        yield StreamChunk(
            delta=delta.content,
            tool_calls=self._accumulate_tool_deltas(delta.tool_calls),
            finish_reason=chunk.choices[0].finish_reason,
            usage=getattr(chunk, "usage", None),
        )
```

#### Reasoning Content Extraction (Multi-Provider)

```python
def _extract_reasoning(self, message) -> str | None:
    """Handle reasoning fields across OpenAI-compatible providers."""
    parts = []
    # OpenRouter unified format
    if hasattr(message, "reasoning") and message.reasoning:
        parts.append(message.reasoning)
    # Some providers use different field names
    if hasattr(message, "reasoning_content") and message.reasoning_content:
        parts.append(message.reasoning_content)
    # OpenRouter metadata array
    if hasattr(message, "reasoning_details") and isinstance(message.reasoning_details, list):
        for detail in message.reasoning_details:
            text = detail.get("summary") or detail.get("content") or detail.get("text")
            if text:
                parts.append(text)
    return "\n\n".join(parts) if parts else None
```

---

### 3. MistralProvider — EU Data Sovereignty

```python
from mistralai import Mistral

class MistralProvider(LLMProvider):
    def __init__(self, api_key: str, server: str = "eu"):
        self.client = Mistral(api_key=api_key, server=server)
```

#### EU Value Proposition for Volos

- **All data hosted in EU by default** — French HQ, no US CLOUD Act exposure
- **GDPR architectural compliance** — not just contractual
- **No training on API data** — inputs/outputs never used for model training
- **DPA available** — `https://legal.mistral.ai/terms/data-processing-addendum`
- Massive EU infrastructure investment (1.2B EUR Swedish data centers, 40MW French cluster)

#### Available Models for Agent Use

| Model | API ID | Input $/1M | Output $/1M | Context | Best For |
|---|---|---|---|---|---|
| Mistral Large 3 | `mistral-large-latest` | $0.50 | $1.50 | 262K | Primary agent (flagship) |
| Magistral Medium | `magistral-medium-latest` | $2.00 | $5.00 | 40K | Chain-of-thought reasoning |
| Magistral Small | `magistral-small-latest` | $0.50 | $1.50 | 40K | Reasoning (lighter) |
| Mistral Medium 3.1 | `mistral-medium-latest` | $0.40 | $2.00 | 131K | Balanced |
| Mistral Small 3.2 | `mistral-small-latest` | $0.10 | $0.30 | 131K | High-volume, best value |
| Codestral | `codestral-latest` | $0.30 | $0.90 | 256K | Code generation |
| Devstral 2 | `devstral-2` | $0.40 | $0.90 | 262K | Coding/agentic |
| Devstral Small 2 | `devstral-small-2` | $0.10 | $0.30 | 256K | Lightweight coding |

**Cost comparison:** Mistral Large at $0.50/$1.50 is 4x cheaper input than GPT-4.1.

#### SDK Differences from OpenAI

| Aspect | OpenAI SDK | Mistral SDK |
|---|---|---|
| **Client class** | `OpenAI(api_key=...)` | `Mistral(api_key=...)` |
| **Chat complete** | `client.chat.completions.create()` | `client.chat.complete()` |
| **Async complete** | Same method on `AsyncOpenAI` | `client.chat.complete_async()` |
| **Streaming** | `stream=True` param on same method | Separate `client.chat.stream()` method |
| **Async streaming** | Same method on `AsyncOpenAI` | `client.chat.stream_async()` |
| **Stream chunk access** | `chunk.choices[0].delta.content` | `chunk.data.choices[0].delta.content` (extra `.data`) |
| **`tool_choice="required"`** | `"required"` | `"any"` (Mistral-native) or `"required"` (compat) |
| **`seed` param** | `seed` | `random_seed` |
| **Tool call ID format** | `"call_abc123..."` | Short alphanumeric `"D681PevKs"` |
| **`safe_prompt`** | Not available | Mistral-specific boolean |
| **`prediction`** | Not available | Predicted outputs for faster inference |
| **`prompt_mode`** | Not available | `"reasoning"` for Magistral models |
| **Error base class** | `openai.APIError` | `errors.MistralError` |
| **HTTP client** | `httpx` | `httpx` |
| **Stream termination** | `data: [DONE]` | `data: [DONE]` (same) |
| **Usage in response** | `response.usage.prompt_tokens` | `response.usage.prompt_tokens` (same) |

#### API Call Pattern

```python
async def chat(self, **kwargs) -> LLMResponse:
    response = await self.client.chat.complete_async(
        model=kwargs["model"],
        messages=kwargs["messages"],
        tools=kwargs.get("tools"),
        tool_choice=self._map_tool_choice(kwargs.get("tool_choice")),
        temperature=kwargs.get("temperature", 0.3),
        max_tokens=kwargs.get("max_tokens"),
        random_seed=kwargs.get("seed"),  # Note: random_seed not seed
    )
    return self._normalize_response(response)

async def chat_stream(self, **kwargs) -> AsyncIterator[StreamChunk]:
    response = await self.client.chat.stream_async(
        model=kwargs["model"],
        messages=kwargs["messages"],
        tools=kwargs.get("tools"),
        tool_choice=self._map_tool_choice(kwargs.get("tool_choice")),
        temperature=kwargs.get("temperature", 0.3),
        max_tokens=kwargs.get("max_tokens"),
    )
    async for chunk in response:
        delta = chunk.data.choices[0].delta  # Note: .data wrapper
        yield StreamChunk(
            delta=delta.content,
            tool_calls=self._accumulate_tool_deltas(delta.tool_calls),
            finish_reason=chunk.data.choices[0].finish_reason,
            usage=getattr(chunk.data, "usage", None),
        )

def _map_tool_choice(self, choice: str | None) -> str | None:
    if choice == "required":
        return "any"  # Mistral's equivalent
    return choice
```

#### Tool Calling Flow

Tool definitions use the same OpenAI format — no conversion needed:

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "exec",
            "description": "Execute a shell command",
            "parameters": {"type": "object", "properties": {...}, "required": [...]}
        }
    }
]
```

Tool result messages also use the same format:

```python
{"role": "tool", "name": "exec", "content": "...", "tool_call_id": "D681PevKs"}
```

#### Server Selection

```python
# EU (default) — all data stays in EU
client = Mistral(api_key="...", server="eu")

# Explicit URL
client = Mistral(api_key="...", server_url="https://api.mistral.ai")

# Azure deployment
from mistralai import MistralAzure
client = MistralAzure(azure_api_key="...", azure_endpoint="https://...")

# GCP deployment
from mistralai import MistralGoogleCloud
client = MistralGoogleCloud(project_id="...", region="europe-west4")
```

---

### 4. XAIProvider — xAI/Grok

xAI's API is fully OpenAI-compatible. Two options:

**Option A: Config entry in OpenAIProvider (recommended)**

```python
# In registry.py — just a different base URL
"xai": ProviderSpec(
    cls=OpenAIProvider,
    env_key="XAI_API_KEY",
    api_base="https://api.x.ai/v1",
)
```

**Option B: Thin subclass**

```python
class XAIProvider(OpenAIProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key=api_key, api_base="https://api.x.ai/v1")
```

No format differences to handle — standard OpenAI Chat Completions API.

---

## Hermes Agent Reference Patterns

Hermes has been running without LiteLLM for a long time. Here's what they do that's worth stealing.

### Anthropic Adapter Pattern

Hermes keeps all Anthropic-specific logic in a single file (`agent/anthropic_adapter.py`, 624 lines):

```python
# Public API
def build_anthropic_client(api_key, base_url=None) -> Anthropic
def build_anthropic_kwargs(model, messages, tools, max_tokens, reasoning_config) -> dict
def normalize_anthropic_response(response) -> (SimpleNamespace, str)
```

**Key insight:** Separate the format conversion from the provider class. Makes it testable independently.

### Prompt Caching (Anthropic-Specific)

```python
def apply_anthropic_cache_control(api_messages):
    """4 cache_control breakpoints max (Anthropic limit).
    - System prompt (stable across all turns)
    - Last 3 non-system messages (rolling window)
    """
    marker = {"type": "ephemeral"}  # 5-minute TTL, 1.25x write cost

    # Mark system message
    if messages[0].get("role") == "system":
        messages[0]["cache_control"] = marker

    # Mark last 3 non-system messages
    non_sys = [i for i, m in enumerate(messages) if m["role"] != "system"]
    for idx in non_sys[-3:]:
        messages[idx]["cache_control"] = marker
```

**Cost savings:** ~75% reduction on input tokens for multi-turn conversations.

### Credential Refresh on 401

```python
# On API error:
if "authentication" in str(error).lower() or "401" in str(error):
    if provider == "anthropic":
        refreshed = refresh_anthropic_oauth_token()
    elif provider == "nous":
        refreshed = refresh_nous_credentials()
    if refreshed:
        response = retry_api_call(**kwargs)
```

### Three API Modes

```python
# Hermes detects API mode at init time
if provider == "anthropic":
    api_mode = "anthropic_messages"
elif provider == "openai-codex":
    api_mode = "codex_responses"
else:
    api_mode = "chat_completions"

# Then dispatches
if api_mode == "anthropic_messages":
    response = anthropic_client.messages.create(**anthropic_kwargs)
elif api_mode == "codex_responses":
    response = run_codex_stream(codex_kwargs)
else:
    response = openai_client.chat.completions.create(**openai_kwargs)
```

### Interruptible API Calls

```python
def _interruptible_api_call(self, api_kwargs):
    """Run API call in background thread, detect user interrupts."""
    result = {"response": None}

    def _call():
        result["response"] = self.client.chat.completions.create(**api_kwargs)

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    while t.is_alive():
        t.join(timeout=0.3)
        if self._interrupt_requested:
            self.client.close()  # Force-close HTTP connection
            self.client = rebuild_client()  # Rebuild for next call
            raise InterruptedError()
```

### Multi-Format Reasoning Extraction

```python
def _extract_reasoning(self, message):
    """Handle reasoning fields across providers."""
    parts = []
    # Standard field
    if hasattr(message, "reasoning") and message.reasoning:
        parts.append(message.reasoning)
    # Alternative name
    if hasattr(message, "reasoning_content") and message.reasoning_content:
        parts.append(message.reasoning_content)
    # OpenRouter metadata array
    if hasattr(message, "reasoning_details") and isinstance(message.reasoning_details, list):
        for detail in message.reasoning_details:
            text = detail.get("summary") or detail.get("content") or detail.get("text")
            if text:
                parts.append(text)
    return "\n\n".join(parts) if parts else None
```

### Frozen Memory Snapshot for Cache Stability

Hermes takes a snapshot of MEMORY.md/USER.md at session start and injects it into the system prompt. Memory tool responses show live disk state, but the system prompt never changes mid-session — preserving Anthropic prompt cache validity.

Velo should adopt this pattern when using prompt caching.

---

## Mistral SDK Deep Dive

### Package Details

- **Package:** `mistralai` on PyPI
- **Latest version:** `2.0.1` (March 2026)
- **Python:** `>=3.10`
- **HTTP client:** Built on `httpx`
- **Install:** `uv add mistralai`

### Complete API Surface

```python
from mistralai import Mistral

client = Mistral(api_key="...")

# Chat (sync)
response = client.chat.complete(model="...", messages=[...])

# Chat (async)
response = await client.chat.complete_async(model="...", messages=[...])

# Stream (sync)
for chunk in client.chat.stream(model="...", messages=[...]):
    print(chunk.data.choices[0].delta.content)

# Stream (async)
async for chunk in client.chat.stream_async(model="...", messages=[...]):
    print(chunk.data.choices[0].delta.content)

# Embeddings
response = client.embeddings.create(model="mistral-embed", inputs=["..."])

# File upload
response = client.files.upload(file=open("doc.pdf", "rb"))

# Agents (Mistral-hosted agents)
response = client.agents.complete(agent_id="...", messages=[...])
```

### Supported `complete()` / `stream()` Parameters

```python
client.chat.complete(
    model="mistral-large-latest",       # Required
    messages=[...],                       # Required
    tools=[...],                          # Optional — OpenAI format
    tool_choice="auto",                   # "auto" | "any" | "none" | "required" | specific
    parallel_tool_calls=True,             # Boolean, default True
    temperature=0.3,                      # 0.0-2.0
    max_tokens=4096,                      # Max output tokens
    top_p=1.0,                            # Nucleus sampling
    random_seed=42,                       # NOT "seed" — Mistral-specific name
    safe_prompt=False,                    # Mistral safety prompt injection
    response_format={"type": "text"},     # "text" | "json_object" | "json_schema"
    n=1,                                  # Number of completions
    frequency_penalty=0.0,                # -2.0 to 2.0
    presence_penalty=0.0,                 # -2.0 to 2.0
    prediction={"type": "content", "content": "..."},  # Predicted output
    prompt_mode="reasoning",              # For Magistral models
)
```

### Streaming Chunk Format (Raw SSE)

```
data: {"id":"abc123","object":"chat.completion.chunk","created":1726290938,
       "model":"mistral-large-latest",
       "choices":[{"index":0,"delta":{"content":" weather"},
                   "finish_reason":null}]}

data: {"id":"abc123","object":"chat.completion.chunk","created":1726290938,
       "model":"mistral-large-latest",
       "choices":[{"index":0,"delta":{"content":""},
                   "finish_reason":"stop"}],
       "usage":{"prompt_tokens":238,"total_tokens":890,"completion_tokens":652}}

data: [DONE]
```

Almost identical to OpenAI at the HTTP level. The SDK wraps chunks with an extra `.data` accessor.

### Error Handling

```python
from mistralai import errors

try:
    response = await client.chat.complete_async(...)
except errors.HTTPValidationError as e:  # 422
    print(e.detail)
except errors.SDKError as e:             # Base error class
    print(e.status_code, e.body)
```

### Built-in Retry Configuration

```python
from mistralai import Mistral
from mistralai.utils import RetryConfig, BackoffStrategy

client = Mistral(
    api_key="...",
    retry_config=RetryConfig(
        strategy="backoff",
        backoff=BackoffStrategy(
            initial_interval=500,      # ms
            max_interval=60000,        # ms
            exponent=1.5,
            max_elapsed_time=300000,   # ms (5 min)
        ),
        retry_connection_errors=True,
    ),
)
```

### Context Manager Support

```python
async with Mistral(api_key="...") as client:
    response = await client.chat.complete_async(...)
# Client properly closed
```

---

## Migration Plan (Completed 2026-03-14)

### Phase 1: AnthropicProvider (Highest Value) -- DONE

**Steps (all completed):**
1. [x] Created `velo/providers/anthropic_provider.py` (~370 lines)
2. [x] Message format conversion (OpenAI → Anthropic Messages API) with system extraction, tool_calls→tool_use, tool results
3. [x] Tool schema conversion (`parameters` → `input_schema`)
4. [x] Response normalization (Anthropic Message → `LLMResponse`)
5. [x] Prompt caching (`cache_control: {"type": "ephemeral"}` on last system block + last tool)
6. [x] Extended thinking (adaptive for Claude 4.6, budget-based for older models)
7. [x] Role alternation enforcement (merge consecutive same-role messages)
8. [x] Streaming via `messages.stream()` with thinking/tool_use accumulation
9. [x] Typed error handling (`RateLimitError`, `AuthenticationError`, etc.)
10. [x] Tests: 29 unit tests covering all conversion, caching, thinking, and prefix stripping

### Phase 2: OpenAIProvider (Broadest Coverage) -- DONE

**Steps (all completed):**
1. [x] Created `velo/providers/openai_provider.py` (~310 lines)
2. [x] One class handles 13 backends via `_BACKEND_DEFAULTS` dict
3. [x] OpenRouter-specific headers (`HTTP-Referer`, `X-OpenRouter-Title`)
4. [x] Reasoning content extraction (DeepSeek `reasoning_content`, OpenRouter `reasoning`/`reasoning_details`)
5. [x] Model overrides (e.g. `kimi-k2.5` → `temperature: 1.0`)
6. [x] Streaming with tool call accumulation
7. [x] Replaces both `LiteLLMProvider` and `CustomProvider`
8. [x] Tests: 16 unit tests covering backends, prefixes, reasoning, overrides

### Phase 3: MistralProvider (EU Differentiator) -- DONE

**Steps (all completed):**
1. [x] Added `mistralai>=2.0.0` to `pyproject.toml`
2. [x] Created `velo/providers/mistral_provider.py` (~290 lines)
3. [x] Handles `.data` wrapper on streaming chunks
4. [x] Maps `tool_choice="required"` → `"any"`
5. [x] 9-char alphanumeric tool_call_id normalization (Mistral's requirement)
6. [x] `server="eu"` default for EU data residency
7. [x] Import from `mistralai.client` (not top-level `mistralai`)
8. [x] Tests: 10 unit tests covering tool choice, IDs, prefix stripping

### Phase 4: GeminiProvider (New Addition) -- DONE

**Steps (all completed):**
1. [x] Added `google-genai>=1.0.0` to `pyproject.toml`
2. [x] Created `velo/providers/gemini_provider.py` (~360 lines)
3. [x] Message conversion: system→`system_instruction`, role "model" (not "assistant"), function_call/function_response parts
4. [x] Tool schema conversion to `FunctionDeclaration` with `automatic_function_calling` disabled
5. [x] Synthetic tool_call_id generation (sha1 hash of name+args)
6. [x] Role alternation merging for Gemini Content objects
7. [x] Streaming via `generate_content_stream()`
8. [x] Tests: 14 unit tests covering conversion, tools, IDs

### Phase 5: Registry Refactor + Factory Update + Cleanup -- DONE

**Steps (all completed):**
1. [x] Rewrote `registry.py` — added `provider_type` field, removed `litellm_prefix`/`skip_prefixes`/`env_extras`/`env_key`
2. [x] Added xAI as new provider (`provider_type="openai"`, `default_api_base="https://api.x.ai/v1"`)
3. [x] Added `default_api_base` for DeepSeek, Groq, Zhipu, DashScope, Moonshot, MiniMax
4. [x] Updated `_make_provider()` factory — dispatches by `provider_type` instead of LiteLLM fallback
5. [x] Fixed `get_api_base()` — resolves default URLs for ALL providers (not just gateways)
6. [x] Added `xai: ProviderConfig` to `ProvidersConfig` in schema.py
7. [x] Updated `__init__.py` exports
8. [x] Updated `pyproject.toml` — removed `litellm>=1.81.5,<2.0.0`
9. [x] Deleted `litellm_provider.py` and `custom_provider.py`
10. [x] Updated `test_commands.py` and `test_registry.py` for new schema
11. [x] Full test suite: **662 passed, 0 failed**

---

## Estimated Effort (Actual)

| Phase | New Files | Deleted Files | Lines Written | Tests Added |
|---|---|---|---|---|
| Phase 1 (Anthropic) | `anthropic_provider.py` | — | ~370 | 29 |
| Phase 2 (OpenAI) | `openai_provider.py` | — | ~310 | 16 |
| Phase 3 (Mistral) | `mistral_provider.py` | — | ~290 | 10 |
| Phase 4 (Gemini) | `gemini_provider.py` | — | ~360 | 14 |
| Phase 5 (Cleanup) | — | `litellm_provider.py`, `custom_provider.py` | ~260 (registry) | 104 (updated) |

### Key Principle (Validated)

The `LLMProvider` abstraction boundary is clean. **Everything above the provider layer (agent loop, tools, channels, plugins, skills) stayed completely untouched.** This was a provider-layer-only change. Zero changes needed outside the providers/ directory and the factory function.
