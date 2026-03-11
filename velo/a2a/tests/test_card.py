"""Tests for the A2A AgentCard builder.

Requires a2a-sdk to be installed.  Tests are skipped automatically when the
package is absent so the CI suite remains green in non-A2A environments.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

a2a_available = pytest.importorskip(
    "a2a", reason="a2a-sdk not installed — skipping A2A card tests"
)


def _make_a2a_config(
    agent_name: str = "",
    agent_description: str = "",
    port: int = 18791,
    api_key: str = "",
) -> MagicMock:
    cfg = MagicMock()
    cfg.agent_name = agent_name
    cfg.agent_description = agent_description
    cfg.port = port
    cfg.api_key = api_key
    return cfg


class TestBuildAgentCard:
    """Tests for build_agent_card()."""

    @patch("velo.a2a.card.AgentCard")
    @patch("velo.a2a.card.AgentCapabilities")
    @patch("velo.a2a.card.AgentSkill")
    @patch("velo.a2a.card.SkillsLoader")
    def test_uses_config_name_and_description(
        self, mock_loader_cls, mock_skill, mock_caps, mock_card
    ):
        """AgentCard uses agent_name and agent_description from config."""
        from velo.a2a.card import build_agent_card

        loader = MagicMock()
        loader.list_skills.return_value = []
        mock_loader_cls.return_value = loader

        cfg = _make_a2a_config(agent_name="ResearchBot", agent_description="Researches stuff")
        build_agent_card(cfg, Path("/fake"))

        call_kwargs = mock_card.call_args.kwargs
        assert call_kwargs["name"] == "ResearchBot"
        assert call_kwargs["description"] == "Researches stuff"

    @patch("velo.a2a.card.AgentCard")
    @patch("velo.a2a.card.AgentCapabilities")
    @patch("velo.a2a.card.AgentSkill")
    @patch("velo.a2a.card.SkillsLoader")
    @patch("socket.gethostname", return_value="myhost")
    def test_defaults_to_hostname(
        self, mock_hostname, mock_loader_cls, mock_skill, mock_caps, mock_card
    ):
        """When agent_name is empty, hostname is used."""
        from velo.a2a.card import build_agent_card

        loader = MagicMock()
        loader.list_skills.return_value = []
        mock_loader_cls.return_value = loader

        build_agent_card(_make_a2a_config(), Path("/fake"))
        assert mock_card.call_args.kwargs["name"] == "myhost"

    @patch("velo.a2a.card.AgentCard")
    @patch("velo.a2a.card.AgentCapabilities")
    @patch("velo.a2a.card.AgentSkill")
    @patch("velo.a2a.card.SkillsLoader")
    def test_builds_skills_from_loader(
        self, mock_loader_cls, mock_skill, mock_caps, mock_card
    ):
        """Skills from SkillsLoader appear in the AgentCard."""
        from velo.a2a.card import build_agent_card

        loader = MagicMock()
        loader.list_skills.return_value = [
            {"name": "weather", "path": "/fake/weather/SKILL.md", "source": "workspace"},
            {"name": "calendar", "path": "/fake/calendar/SKILL.md", "source": "workspace"},
        ]
        loader.get_skill_metadata.return_value = {"description": "Checks weather"}
        mock_loader_cls.return_value = loader

        build_agent_card(_make_a2a_config(), Path("/fake"))
        assert mock_skill.call_count == 2

    @patch("velo.a2a.card.AgentCard")
    @patch("velo.a2a.card.AgentCapabilities")
    @patch("velo.a2a.card.AgentSkill")
    @patch("velo.a2a.card.SkillsLoader")
    def test_fallback_skill_when_no_skills(
        self, mock_loader_cls, mock_skill, mock_caps, mock_card
    ):
        """When no skills are available, one generic skill is added."""
        from velo.a2a.card import build_agent_card

        loader = MagicMock()
        loader.list_skills.return_value = []
        mock_loader_cls.return_value = loader

        build_agent_card(_make_a2a_config(), Path("/fake"))
        assert mock_skill.call_count == 1
        assert mock_skill.call_args.kwargs["id"] == "general"
