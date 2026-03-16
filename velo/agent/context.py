"""Context builder for assembling agent prompts."""

from __future__ import annotations

import base64
import mimetypes
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from velo.agent.memory import MemoryStore
from velo.agent.skills import SkillsLoader
from velo.utils.helpers import detect_image_mime

if TYPE_CHECKING:
    from velo.agent.honcho.adapter import HonchoAdapter
    from velo.plugins.manager import PluginManager


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"
    _RUNTIME_END_TAG = "[End Runtime Context]"

    def __init__(
        self,
        workspace: Path,
        plugin_manager: PluginManager | None = None,
        memory_limit: int = 8000,
        user_limit: int = 4000,
    ):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
        self._plugin_manager = plugin_manager
        self._memory_limit = memory_limit
        self._user_limit = user_limit
        self._honcho: HonchoAdapter | None = None
        # Prompt caching: reuse the same system prompt across turns until invalidated.
        self._cached_system_prompt: str | None = None
        self._cached_deferred_hint: str | None = None

    def set_honcho(self, adapter: HonchoAdapter) -> None:
        """Set the Honcho adapter for context injection.

        Args:
            adapter: HonchoAdapter instance to use for user context.
        """
        self._honcho = adapter

    def invalidate_prompt_cache(self) -> None:
        """Clear the cached system prompt so the next call rebuilds it.

        Call after memory consolidation, /new, or any event that changes
        identity/bootstrap/memory content.
        """
        self._cached_system_prompt = None
        self._cached_deferred_hint = None

    async def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        deferred_tools_hint: str | None = None,
    ) -> str:
        """Build the system prompt from identity, bootstrap files, memory, skills, and plugins.

        Honcho user context is NOT included here (it changes every turn and would
        invalidate Anthropic's prefix cache). Instead, Honcho context is injected
        into the runtime context block in ``build_messages()``.

        Args:
            skill_names: Optional list of skill names to include.
            deferred_tools_hint: Optional summary of deferred tools available via search_tools.
        """
        # Return cached prompt if available and the deferred tools hint hasn't changed.
        if (
            self._cached_system_prompt is not None
            and deferred_tools_hint == self._cached_deferred_hint
        ):
            return self._cached_system_prompt

        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        memory = self.memory.get_memory_context(self._memory_limit, self._user_limit)
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        # Honcho context deliberately excluded — see docstring.

        # Plugin context providers inject after memory
        if self._plugin_manager:
            plugin_ctx = await self._plugin_manager.get_context_additions()
            if plugin_ctx:
                parts.append(f"# Plugin Context\n\n{plugin_ctx}")

        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

        if deferred_tools_hint:
            parts.append(
                f"# Available Tools (via search_tools)\n\n"
                "The following capabilities are available on demand. "
                f"Use the `search_tools` tool to activate them:\n{deferred_tools_hint}"
            )

        prompt = "\n\n---\n\n".join(parts)

        # Pipe through after_prompt_build hook
        if self._plugin_manager:
            prompt = await self._plugin_manager.pipe("after_prompt_build", value=prompt)

        self._cached_system_prompt = prompt
        self._cached_deferred_hint = deferred_tools_hint
        return prompt

    def _get_identity(self) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        platform_policy = ""
        if system == "Windows":
            platform_policy = """## Platform Policy (Windows)
- You are running on Windows. Do not assume GNU tools like `grep`, `sed`, or `awk` exist.
- Prefer Windows-native commands or file tools when they are more reliable.
- If terminal output is garbled, retry with UTF-8 output enabled.
"""
        else:
            platform_policy = """## Platform Policy (POSIX)
- You are running on a POSIX system. Prefer UTF-8 and standard shell tools.
- Use file tools when they are simpler or more reliable than shell commands.
"""

        return f"""# Velo 💨

You are Velo, a personal AI assistant for the Volos ecosystem.

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Agent notes: {workspace_path}/memory/MEMORY.md (env, projects, conventions — always loaded)
- User profile: {workspace_path}/memory/USER.md (who the user is — auto-updated at consolidation)
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable). Each entry starts with [YYYY-MM-DD HH:MM].
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

{platform_policy}

## Velo Guidelines
- State intent before tool calls, but NEVER predict or claim results before receiving them.
- Before modifying a file, read it first. Do not assume files or directories exist.
- After writing or editing a file, re-read it if accuracy matters.
- If a tool call fails, analyze the error before retrying with a different approach.
- Ask for clarification when the request is ambiguous.

Reply directly with text for conversations. Only use the 'message' tool to send to a specific chat channel."""

    @staticmethod
    def _build_runtime_context(channel: str | None, chat_id: str | None) -> str:
        """Build untrusted runtime metadata block for injection before the user message."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = time.strftime("%Z") or "UTC"
        lines = [f"Current Time: {now} ({tz})"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)

    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []

        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    async def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        deferred_tools_hint: str | None = None,
        memory_nudge: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call.

        Args:
            history: Prior conversation messages.
            current_message: The user's current message text.
            skill_names: Optional list of skill names to include in the prompt.
            media: Optional list of image file paths to include.
            channel: Channel identifier for runtime context.
            chat_id: Chat ID for runtime context.
            deferred_tools_hint: Optional summary of deferred tools for the system prompt.
            memory_nudge: Optional reminder appended to runtime context (stripped from session).
        """
        runtime_ctx = self._build_runtime_context(channel, chat_id)
        # Inject Honcho user context into runtime block (per-turn, not in system prompt)
        # so the system prompt stays stable for Anthropic's prefix cache.
        if self._honcho:
            honcho_ctx = self._honcho.get_prefetched_context()
            if honcho_ctx:
                runtime_ctx += f"\nUser Profile & Context (primary):\n{honcho_ctx}"
        # Reason: nudge is appended to runtime_ctx so _save_turn strips it from session storage.
        if memory_nudge:
            runtime_ctx += f"\n{memory_nudge}"
        runtime_ctx += f"\n{self._RUNTIME_END_TAG}"
        user_content = self._build_user_content(current_message, media)

        # Merge runtime context and user content into a single user message
        # to avoid consecutive same-role messages that some providers reject.
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}] + user_content

        return [
            {
                "role": "system",
                "content": await self.build_system_prompt(skill_names, deferred_tools_hint),
            },
            *history,
            {"role": "user", "content": merged},
        ]

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            # Detect real MIME type from magic bytes; fallback to filename guess
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(raw).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        if not images:
            return text
        return images + [{"type": "text", "text": text}]

    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str,
    ) -> list[dict[str, Any]]:
        """Add a tool result to the message list."""
        messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result}
        )
        return messages

    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
        if thinking_blocks:
            msg["thinking_blocks"] = thinking_blocks
        messages.append(msg)
        return messages
