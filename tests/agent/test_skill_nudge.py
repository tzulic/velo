"""Tests for skill auto-creation nudge."""

from velo.agent.skill_nudge import SkillNudge


class TestSkillNudge:
    def test_below_threshold_no_nudge(self):
        nudge = SkillNudge(min_tool_calls=5)
        assert not nudge.should_nudge(4)

    def test_at_threshold_nudges(self):
        nudge = SkillNudge(min_tool_calls=5)
        assert nudge.should_nudge(5)

    def test_above_threshold_nudges(self):
        nudge = SkillNudge(min_tool_calls=5)
        assert nudge.should_nudge(10)

    def test_once_per_session(self):
        nudge = SkillNudge(min_tool_calls=5)
        assert nudge.should_nudge(5)
        nudge.mark_nudged()
        assert not nudge.should_nudge(10)

    def test_get_nudge_text_mentions_skill_manage(self):
        nudge = SkillNudge()
        text = nudge.get_nudge_text()
        assert "skill_manage" in text

    def test_reset_between_sessions(self):
        nudge = SkillNudge(min_tool_calls=5)
        nudge.mark_nudged()
        nudge.reset()
        assert nudge.should_nudge(5)


class TestSkillNudgeTwoPhase:
    def test_inject_not_armed(self):
        nudge = SkillNudge(min_tool_calls=5)
        assert not nudge.should_inject()

    def test_two_phase_flow(self):
        nudge = SkillNudge(min_tool_calls=5)
        nudge.mark_nudged()
        assert nudge.should_inject()
        nudge.mark_injected()
        assert not nudge.should_inject()

    def test_reset_clears_both_phases(self):
        nudge = SkillNudge(min_tool_calls=5)
        nudge.mark_nudged()
        nudge.mark_injected()
        nudge.reset()
        assert not nudge.should_inject()
        assert nudge.should_nudge(5)
