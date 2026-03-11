"""AgentCard builder for the A2A server."""

import socket
from pathlib import Path
from typing import TYPE_CHECKING

from a2a.types import AgentCapabilities, AgentCard, AgentSkill

if TYPE_CHECKING:
    from velo.config.schema import A2AConfig


def build_agent_card(a2a_config: "A2AConfig", workspace: Path) -> AgentCard:
    """Build an AgentCard from A2A config and available skills.

    Args:
        a2a_config: A2AConfig instance with server settings.
        workspace: Path to the nanobot workspace.

    Returns:
        AgentCard instance for A2A discovery.
    """
    from velo.agent.skills import SkillsLoader

    loader = SkillsLoader(workspace)
    skill_entries = loader.list_skills(filter_unavailable=True)

    skills = []
    for s in skill_entries:
        meta = loader.get_skill_metadata(s["name"]) or {}
        description = meta.get("description", "") or f"Skill: {s['name']}"
        skills.append(
            AgentSkill(
                id=s["name"],
                name=s["name"],
                description=description,
            )
        )

    if not skills:
        skills = [
            AgentSkill(
                id="general",
                name="General AI Assistant",
                description=(
                    "General-purpose AI assistant capable of answering questions, "
                    "writing, research, and task automation."
                ),
            )
        ]

    name = a2a_config.agent_name or socket.gethostname()
    description = a2a_config.agent_description or "nanobot personal AI assistant"
    url = f"http://0.0.0.0:{a2a_config.port}/"

    return AgentCard(
        name=name,
        description=description,
        url=url,
        version="1.0",
        capabilities=AgentCapabilities(streaming=False),
        defaultInputModes=["text/plain"],
        defaultOutputModes=["text/plain"],
        skills=skills,
    )
