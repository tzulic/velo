"""Agent core module."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from velo.agent.context import ContextBuilder
    from velo.agent.loop import AgentLoop
    from velo.agent.memory import MemoryStore
    from velo.agent.skills import SkillsLoader

__all__ = ["AgentLoop", "ContextBuilder", "MemoryStore", "SkillsLoader"]


def __getattr__(name: str) -> object:
    """Lazy imports to avoid circular dependency with config.schema."""
    if name == "AgentLoop":
        from velo.agent.loop import AgentLoop

        return AgentLoop
    if name == "ContextBuilder":
        from velo.agent.context import ContextBuilder

        return ContextBuilder
    if name == "MemoryStore":
        from velo.agent.memory import MemoryStore

        return MemoryStore
    if name == "SkillsLoader":
        from velo.agent.skills import SkillsLoader

        return SkillsLoader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
