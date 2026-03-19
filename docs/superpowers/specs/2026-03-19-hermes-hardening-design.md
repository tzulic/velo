# Hermes Agent Hardening Patterns for Velo

**Date:** 2026-03-19
**Status:** Approved
**Context:** Patterns from hermes-agent adapted for Velo's managed service context (non-technical users, no human admin backstop, Volos meta agent manages instances autonomously).

---

## Overview

Nine targeted improvements to Velo's agent loop, cron system, subagent system, and session management. Sourced from battle-tested patterns in hermes-agent, adapted to Velo's architecture and Volos's managed service constraints.

Many of these patterns already partially exist in Velo. This spec focuses on the delta — what needs to change, not what needs to be built from scratch.

### Phasing

| Phase | Focus | Items |
|-------|-------|-------|
| 1 | Safety | Cron security scanning, cron recursion guard, error retry flow |
| 2 | Resilience | Streaming fallback, prompt-too-long compression, OAuth 401 handling |
| 3 | User Experience | Cron delivery targets, subagent progress relay, /retry command |

---

## Phase 1: Safety

### 1. Cron Security Scanning

**Existing infrastructure:** `velo/agent/security/__init__.py` already has regex-based `THREAT_PATTERNS`, invisible Unicode detection, and a `scan_content()` function covering prompt injection, exfiltration, SSH backdoors, credential theft, and eval/exec detection.

**What's new:** Extend the existing security module with 5 additional threat patterns not currently covered:

1. **Destructive filesystem** — `rm -rf /`, `mkfs`, `dd if=`
2. **Process manipulation** — kill/pkill targeting system processes
3. **Network reconnaissance** — nmap, netcat listeners
4. **Privilege escalation** — chmod 777, setuid
5. **Crypto mining** — xmrig, minerd, stratum references
6. **Sudoers modification** — visudo, /etc/sudoers

**Integration:** Call the existing `scan_content()` from the cron tool's `create` and `update` actions, before the job is persisted. This is the same pattern already used for memory writes and skill content.

**No new module.** All patterns live in `velo/agent/security/__init__.py`.

---

### 2. Cron Recursion Guard Enhancement

**Existing infrastructure:** `velo/agent/tools/cron.py` already implements a recursion guard via `_in_cron_context` ContextVar. Currently blocks ALL cron creation from within cron context (line 85-86).

**What's new:** Loosen the existing guard to allow one-shot (`repeat="once"`) jobs while continuing to block repeating jobs.

**Modified logic in existing guard:**
```python
if self._in_cron_context.get():
    if repeat != "once":
        return "Error: cron jobs cannot schedule repeating cron jobs. One-shot ('once') jobs are allowed."
```

**Scope:** ~5 lines changed in `velo/agent/tools/cron.py`. No new files.

---

### 3. Error Retry Flow — Invert to Fallback-First

**Existing infrastructure:**
- `velo/providers/errors.py` — `classify_error()` already categorizes errors into `rate_limit`, `server_error`, `timeout`, `context_overflow`, `auth_error`, `bad_request`, `budget_exceeded`, `unknown`
- `velo/agent/llm_helpers.py` — `chat_with_retry()` already does 3 retries with jittered exponential backoff
- `velo/agent/loop.py` — `_try_activate_fallback()` already swaps to fallback provider
- `velo/agent/provider_health.py` — circuit breaker with exponential backoff cooldowns

**What's new (2 changes):**

1. **Invert retry order:** Currently Velo retries the primary provider with backoff first, then falls back. Change to: try fallback provider first on retryable errors, then backoff retry on original if fallback also fails. This reduces user-perceived latency.

2. **User-facing error messages:** Add a mapping from error classifications to natural language messages. Currently line 764 of `loop.py` returns raw LLM error text. Replace with structured messages like "I'm having trouble connecting right now. Let me try again in a moment."

**Also:** Add `"overloaded"` / 529 to the existing `RETRYABLE_ERRORS` set if not already present.

**No new module.** Changes in `velo/agent/loop.py` (`_run_agent_loop_inner`) and a small error message mapping dict.

---

## Phase 2: Resilience

### 4. Provider-Level Streaming Fallback

**Existing infrastructure:** The base `LLMProvider.chat_stream()` in `velo/providers/base.py` already has a default implementation that falls back to `chat()` and yields a single `StreamChunk`. Providers using the default get this for free.

**What's new:** Providers that override `chat_stream()` with native streaming (Anthropic, OpenAI) currently catch errors and emit an error `StreamChunk`. Change these to fall back to `self.chat()` on streaming failure instead of emitting an error chunk.

**Pattern for providers overriding `chat_stream()`:**
```python
async def chat_stream(self, messages, **kwargs):
    try:
        async for chunk in self._native_stream(messages, **kwargs):
            yield chunk
    except Exception as e:
        logger.warning("provider.stream_fallback_triggered", error=str(e))
        response = await self.chat(messages, **kwargs)
        yield StreamChunk(delta="", response=response)
```

**Scope:** Only modify `anthropic_provider.py` and `openai_provider.py`. Mistral and Gemini providers using the base class default are already covered.

**Layering:** Within-provider streaming fallback (this change) is the first defense. Cross-provider fallback in the agent loop is the second.

**Logging:** `provider.stream_fallback_triggered` event with original error.

---

### 5. "Prompt Too Long" — Compress Before Trim

**Existing infrastructure:**
- `velo/agent/context_compressor.py` — `compress_context()` summarizes middle messages (lighter operation)
- `velo/agent/loop.py` lines 664-675 — reactive trim on `context_overflow` error via `trim_to_budget()`
- `velo/providers/errors.py` — `classify_error()` already detects context overflow and returns `context_overflow`

**What's new:** Insert a compression step into the existing `context_overflow` handling path, BEFORE the reactive trim.

**Updated flow:**
```
context_overflow error detected
  -> try compress_context() (summarize middle messages)
  -> retry LLM call
  -> if still context_overflow -> fall through to existing trim_to_budget()
  -> if still fails after trim -> non-retryable, surface to user
```

**Important distinction:** This uses `compress_context()` (lightweight message summarization), NOT `_consolidate_memory()` (heavy operation writing to MEMORY.md/HISTORY.md/USER.md). Memory consolidation should not be triggered by an error path.

**No new files.** Modification to the `context_overflow` handling block in `loop.py`.

---

### 6. OAuth 401 — Clear Error Message (Deferred Full Refresh)

**Original proposal:** Full OAuth token refresh via Anthropic's endpoint.

**Revised after review:** The refresh flow is under-specified — no known public refresh endpoint, refresh token storage mechanism is unclear, and Volos is moving away from BYOK toward fully managed API keys. Full auto-refresh is deferred.

**What's implemented instead:**
1. On 401 with an `sk-ant-oat01-*` token, produce a clear user-facing message: "Your Claude Max session has expired. Please re-authenticate."
2. On 401 with a regular API key, produce: "Authentication failed. Please check your API key configuration."
3. Log `provider.auth_error` with token type (oauth vs api_key) for Volos monitoring.

**Base class addition (simplified):**
```python
class LLMProvider(ABC):
    def get_auth_error_message(self) -> str:
        """Return user-facing message for authentication failures."""
        return "Authentication failed. Please check your configuration."
```

**Anthropic override** checks token prefix and returns the appropriate message.

**Future:** When a public refresh endpoint exists and Volos has a refresh token storage mechanism, upgrade to auto-refresh.

---

## Phase 3: User Experience

### 7. Cron Cross-Channel Delivery

**Existing infrastructure:** `CronPayload` in `velo/cron/types.py` already has `deliver: bool`, `channel: str | None`, and `to: str | None`. The cron tool already stores `channel` and `to` from the originating session at creation time. The `on_cron_job` callback already delivers to the stored channel.

**What's new:** Allow cross-channel override — create a job on Telegram, deliver results to Discord.

**Changes to `CronTool`:**
- Add optional `deliver_channel` and `deliver_chat_id` parameters to the tool schema
- If provided, store in the existing `CronPayload.channel` and `CronPayload.to` fields (overriding the defaults from the originating session)
- At creation time, validate that the target channel is configured and active. Reject with explanation if not.

**No new fields on CronPayload or CronJob.** Uses existing `channel` and `to` fields — they just get set from the tool parameters instead of always from the current session.

---

### 8. Subagent Progress Relay

**New module:** `velo/agent/progress.py`
**Modified:** `velo/agent/subagent.py`

**Staged implementation:**

#### Stage 1 (this spec): Completion summary
When a subagent completes, emit a brief summary of what it did before the main result:
```
Finished background task: searched the web (3 queries), analyzed 2 documents
```
- Derived from tool execution log accumulated during subagent run
- Single message, no channel editing needed
- Pushed to outbound MessageBus for the user's channel

#### Stage 2 (future): Real-time progress
- Batch events (5 events or 10 seconds), edit previous status message in-place
- Requires extending channel abstraction with `edit_message()` capability
- Deferred until channel abstraction supports message editing

**Stage 1 implementation:**
- `ProgressTracker` class accumulates tool events (tool name + brief argument summary) during subagent execution
- On subagent completion, `tracker.summary()` returns a natural language summary
- Subagent's `_run_subagent()` passes the summary to the announcement mechanism

**Thinking events:** Not relayed in Stage 1. Extended thinking reasoning content can contain sensitive internal reasoning. Deferred to Stage 2 with explicit filtering.

---

### 9. /retry Command

**Modified files:** `velo/agent/loop.py`, `velo/session/manager.py`

**Detection:** `/retry` exact command match, intercepted before message reaches the LLM. Consistent with existing `/new`, `/stop`, `/help` command handling in `loop.py`.

**Mechanism:**
1. User sends `/retry`
2. Agent loop intercepts before normal processing
3. Finds the last user message in the session transcript
4. Removes ALL messages from that user message onward (user message + all assistant responses, tool calls, and tool results from that exchange)
5. Requeues the original user message text as a new inbound message
6. Resets `_turn_counts` for the session
7. Processes fresh

**Why "remove back to last user message" instead of "remove last 2":** A single user exchange can produce 5-10+ messages when tools are involved (assistant with tool calls, tool results, final assistant response). Removing only the last 2 would leave orphaned tool messages.

**Edge cases:**
- No previous exchange (first message) — respond "Nothing to retry."
- Previous message was `/retry` — works, removes retried exchange, re-retries original
- Subagent running — cancel it first, then retry
- Last exchange triggered memory consolidation — retry proceeds with current memory state (no rollback of memory writes, which would be destructive)

**Session save:** Uses existing full-rewrite save mechanism (`_save_jsonl` opens with `"w"` mode). No tombstone concept needed.

**Cross-channel:** Works on all channels (operates at session level, not channel level).

---

## Files Changed Summary

| File | Change Type | Phase |
|------|------------|-------|
| `velo/agent/security/__init__.py` | Modified (add patterns) | 1 |
| `velo/agent/tools/cron.py` | Modified (loosen guard, add delivery params) | 1, 3 |
| `velo/agent/loop.py` | Modified (invert retry, error messages, /retry) | 1, 3 |
| `velo/agent/llm_helpers.py` | Modified (retry order) | 1 |
| `velo/providers/base.py` | Modified (auth error message method) | 2 |
| `velo/providers/anthropic_provider.py` | Modified (streaming fallback, auth message) | 2 |
| `velo/providers/openai_provider.py` | Modified (streaming fallback) | 2 |
| `velo/agent/progress.py` | New (Stage 1 only) | 3 |
| `velo/agent/subagent.py` | Modified (progress tracking) | 3 |
| `velo/session/manager.py` | Modified (remove-back-to-user) | 3 |

## What Was Explicitly Skipped

- **Streaming consumer detection** (`_has_stream_consumers()`) — Velo's channel system already knows channel capabilities
- **CLI spinner progress** — Velo is headless (chat platforms), no terminal UI
- **Natural language retry detection** — Start with `/retry` command only, add later if users ask
- **Full OAuth token refresh** — Deferred until refresh endpoint and token storage are specified
- **Real-time subagent progress with message editing** — Deferred to Stage 2 after channel abstraction supports `edit_message()`

## Architect Review Notes

This spec was revised after architect review against the existing codebase. Key corrections:
- Items 1, 2, 3, 7 had significant overlap with existing Velo infrastructure — rewritten to extend existing code rather than duplicate it
- Item 6 descoped from auto-refresh to clear error messaging due to under-specified refresh mechanism
- Item 8 staged into two phases because message editing requires channel abstraction changes
- Item 9 fixed: "remove last 2 messages" corrected to "remove back to last user message" to handle multi-tool exchanges; tombstone concept dropped in favor of existing full-rewrite save
