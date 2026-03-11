---
name: memory
description: Two-layer memory system with grep-based recall.
always: true
---

# Memory

## Structure

Two files store facts; a third is the event log:

- `memory/MEMORY.md` — **Agent notes**: env facts, project context, tool quirks, conventions.
  Always loaded into context with a usage indicator (`[42% — 3,360/8,000 chars]`).
- `memory/USER.md` — **User profile**: who the user is — name, role, timezone, preferences,
  communication style. Also loaded into context with its own usage indicator.
- `memory/HISTORY.md` — Append-only event log. **NOT** loaded into context. Search with grep.
  Each entry starts with `[YYYY-MM-DD HH:MM]`.

**Auto-consolidation populates both MEMORY.md and USER.md** — no manual management needed.
When the session grows large, an LLM call extracts agent notes into MEMORY.md and user profile
facts into USER.md separately.

## Search Past Events

Choose the search method based on file size:

- Small `memory/HISTORY.md`: use `read_file`, then search in-memory
- Large or long-lived `memory/HISTORY.md`: use the `exec` tool for targeted search

Examples:
- **Linux/macOS:** `grep -i "keyword" memory/HISTORY.md`
- **Windows:** `findstr /i "keyword" memory\HISTORY.md`
- **Cross-platform Python:** `python -c "from pathlib import Path; text = Path('memory/HISTORY.md').read_text(encoding='utf-8'); print('\n'.join([l for l in text.splitlines() if 'keyword' in l.lower()][-20:]))"`

Prefer targeted command-line search for large history files.

## When to Update MEMORY.md or USER.md

Write important facts immediately using `edit_file` or `write_file`:

- `memory/MEMORY.md` — env facts, project structure, API patterns, tool quirks, conventions
- `memory/USER.md` — user name, role, timezone, preferences, communication style

Example: "I prefer dark mode" → goes in USER.md. "The API uses OAuth2" → goes in MEMORY.md.

## Auto-consolidation

Old conversations are automatically summarized when the session grows large:
- Key events appended to `HISTORY.md`
- Agent notes merged into `MEMORY.md`
- User profile facts merged into `USER.md`

Usage indicators in the context header (`[X% — N/8,000 chars]`) show when files are filling up.
The consolidation LLM will compress aggressively when either file exceeds 80% capacity.
