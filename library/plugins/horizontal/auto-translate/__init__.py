"""Auto-translate plugin — injects language instruction into the system prompt.

Hooks registered:
    after_prompt_build (modifying) — appends language directive to system prompt.

Config keys:
    default_language (str): Language to use if none is configured at runtime. Default "".
    auto_detect (bool): If true and no language is set, instruct agent to match
        the user's language automatically. Default true.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.plugins.types import PluginContext

logger = logging.getLogger(__name__)

_LANG_FILE = "language.txt"


# ---------------------------------------------------------------------------
# Language store
# ---------------------------------------------------------------------------


class _LanguageStore:
    """Persists the active language setting to a plain-text file.

    Args:
        workspace: Agent workspace directory.
    """

    def __init__(self, workspace: Path) -> None:
        self._path = workspace / _LANG_FILE

    def get(self) -> str:
        """Read the current language setting.

        Returns:
            Language string (e.g. "Spanish") or "" if not set.
        """
        try:
            return self._path.read_text().strip()
        except FileNotFoundError:
            return ""

    def set(self, lang: str) -> None:
        """Write the language setting to disk.

        Args:
            lang: Language name (e.g. "French"). Empty string resets to auto.
        """
        self._path.write_text(lang.strip())
        logger.info("auto_translate.language_set: %s", lang or "(auto)")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class SetLanguageTool(Tool):
    """Tool: set or clear the response language.

    Args:
        store: Language store to write to.
    """

    def __init__(self, store: _LanguageStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "set_language"

    @property
    def description(self) -> str:
        """Tool description."""
        return (
            "Set the language for all agent responses. "
            "Pass an empty string to revert to auto-detect mode."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "description": "Language name (e.g. 'Spanish'). Empty to auto-detect.",
                }
            },
            "required": ["language"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """Set the response language and confirm.

        Args:
            **kwargs: language (str) — target language or "" for auto.

        Returns:
            Confirmation message.
        """
        lang = str(kwargs.get("language", ""))
        self._store.set(lang)
        if lang:
            return f"Language set to: {lang}"
        return "Language reset to auto-detect."


class GetLanguageTool(Tool):
    """Tool: retrieve the current language setting.

    Args:
        store: Language store to read from.
    """

    def __init__(self, store: _LanguageStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        """Tool name."""
        return "get_language"

    @property
    def description(self) -> str:
        """Tool description."""
        return "Get the currently configured response language."

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema — no parameters required."""
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> str:
        """Return the current language setting.

        Args:
            **kwargs: Not used.

        Returns:
            Current language or "(auto-detect)".
        """
        lang = self._store.get()
        return f"Current language: {lang}" if lang else "Current language: auto-detect"


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def setup(ctx: PluginContext) -> None:
    """Plugin entry point — register language injection hook and tools.

    Args:
        ctx: Plugin context with config and workspace.
    """
    default_language: str = ctx.config.get("default_language", "")
    auto_detect: bool = bool(ctx.config.get("auto_detect", True))

    store = _LanguageStore(ctx.workspace)

    # Prime with configured default only when no runtime override exists yet
    if default_language and not store.get():
        store.set(default_language)

    def on_after_prompt_build(value: str, **_: Any) -> str:
        """Inject language instruction into the system prompt.

        Args:
            value: The current system prompt text.

        Returns:
            System prompt with language directive appended.
        """
        lang = store.get() or default_language
        if lang:
            return value + f"\n\nAlways respond in {lang}."
        if auto_detect:
            return value + "\n\nAlways respond in the same language as the user's message."
        return value

    def context_provider() -> str:
        """Return current language setting for agent context.

        Returns:
            One-line language summary.
        """
        lang = store.get() or default_language
        if lang:
            return f"Language: {lang}"
        return "Language: auto (respond in user's language)"

    ctx.on("after_prompt_build", on_after_prompt_build)
    ctx.register_tool(SetLanguageTool(store))
    ctx.register_tool(GetLanguageTool(store))
    ctx.add_context_provider(context_provider)

    logger.debug(
        "auto_translate.setup_completed: default=%s auto_detect=%s",
        default_language or "(none)",
        auto_detect,
    )
