"""Tests for skill auto-creation nudge."""

from pathlib import Path

from velo.agent.skill_nudge import SkillNudge


class TestSkillNudge:
    def test_below_threshold_no_nudge(self, tmp_path: Path):
        nudge = SkillNudge(workspace=tmp_path, min_tool_calls=5)
        assert not nudge.should_nudge(4)

    def test_at_threshold_nudges(self, tmp_path: Path):
        nudge = SkillNudge(workspace=tmp_path, min_tool_calls=5)
        assert nudge.should_nudge(5)

    def test_above_threshold_nudges(self, tmp_path: Path):
        nudge = SkillNudge(workspace=tmp_path, min_tool_calls=5)
        assert nudge.should_nudge(10)

    def test_once_per_session(self, tmp_path: Path):
        nudge = SkillNudge(workspace=tmp_path, min_tool_calls=5)
        assert nudge.should_nudge(5)
        nudge.mark_nudged()
        assert not nudge.should_nudge(10)

    def test_get_nudge_text_mentions_skill_manage(self, tmp_path: Path):
        nudge = SkillNudge(workspace=tmp_path)
        text = nudge.get_nudge_text()
        assert "skill_manage" in text

    def test_reset_between_sessions(self, tmp_path: Path):
        nudge = SkillNudge(workspace=tmp_path, min_tool_calls=5)
        nudge.mark_nudged()
        nudge.reset()
        assert nudge.should_nudge(5)
