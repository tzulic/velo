"""Pattern-triggered memory nudges for high-value user signals."""

from __future__ import annotations

import re

_PREFERENCE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(i prefer|i always|i never|i like|i hate|remember that)\b", re.I),
    re.compile(r"\b(my name is|i work at|i'm a|my timezone|i live in)\b", re.I),
    re.compile(r"\b(don't forget|important:|note:)\b", re.I),
]

# Pre-compiled stripping patterns for code fences and blockquotes.
_RE_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_RE_INLINE_CODE = re.compile(r"`[^`]+`")
_RE_BLOCKQUOTE = re.compile(r"^>.*$", re.MULTILINE)


def should_trigger_memory_nudge(user_message: str) -> bool:
    """Return True if the user's message contains memory-worthy patterns.

    Skips pattern matching inside code fences and quoted text.

    Args:
        user_message: The raw user message text.

    Returns:
        bool: True if patterns suggest persistent info worth saving.
    """
    if not user_message:
        return False
    stripped = _RE_CODE_FENCE.sub("", user_message)
    stripped = _RE_INLINE_CODE.sub("", stripped)
    stripped = _RE_BLOCKQUOTE.sub("", stripped)
    return any(p.search(stripped) for p in _PREFERENCE_PATTERNS)


def get_triggered_nudge() -> str:
    """Return memory nudge text for pattern-triggered saves.

    Returns:
        str: Nudge text to inject into runtime context.
    """
    return (
        "[Memory Hint] The user just shared personal preferences or identity "
        "information. Consider saving important details to memory using "
        "save_memory so you remember this in future conversations."
    )
