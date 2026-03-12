"""Tests for trajectory saving feature."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from velo.agent.loop import AgentLoop
from velo.bus.queue import MessageBus


def _make_loop_with_trajectories(workspace: Path) -> AgentLoop:
    """Create a minimal AgentLoop with trajectory saving enabled."""
    from unittest.mock import AsyncMock

    bus = MessageBus()
    provider = AsyncMock()
    provider.get_default_model = lambda: "test-model"
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        save_trajectories=True,
    )


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Provide a temporary workspace directory."""
    return tmp_path


class TestTrajectorySaving:
    """Tests for _save_trajectory."""

    def test_trajectory_file_created(self, tmp_workspace: Path) -> None:
        """Saving a trajectory creates the JSONL file."""
        loop = _make_loop_with_trajectories(tmp_workspace)
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        loop._save_trajectory(messages, "cli:direct", completed=True)

        path = tmp_workspace / "trajectories" / "trajectory_samples.jsonl"
        assert path.exists()

    def test_trajectory_jsonl_format(self, tmp_workspace: Path) -> None:
        """Each trajectory record is valid JSON with expected fields."""
        loop = _make_loop_with_trajectories(tmp_workspace)
        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]
        loop._save_trajectory(messages, "cli:direct", completed=True)

        path = tmp_workspace / "trajectories" / "trajectory_samples.jsonl"
        with open(path, encoding="utf-8") as f:
            line = f.readline().strip()
        record = json.loads(line)

        assert "conversations" in record
        assert "timestamp" in record
        assert "model" in record
        assert record["completed"] is True
        assert record["session_key"] == "cli:direct"

    def test_trajectory_sharegpt_format(self, tmp_workspace: Path) -> None:
        """Conversations use ShareGPT format (human/gpt role pairs)."""
        loop = _make_loop_with_trajectories(tmp_workspace)
        messages = [
            {"role": "user", "content": "Say hello"},
            {"role": "assistant", "content": "Hello!"},
        ]
        loop._save_trajectory(messages, "cli:direct", completed=True)

        path = tmp_workspace / "trajectories" / "trajectory_samples.jsonl"
        with open(path, encoding="utf-8") as f:
            record = json.loads(f.readline())

        convos = record["conversations"]
        assert len(convos) == 2
        assert convos[0] == {"from": "human", "value": "Say hello"}
        assert convos[1] == {"from": "gpt", "value": "Hello!"}

    def test_failed_trajectories_go_to_separate_file(self, tmp_workspace: Path) -> None:
        """Failed trajectories are written to failed_trajectories.jsonl."""
        loop = _make_loop_with_trajectories(tmp_workspace)
        messages = [{"role": "user", "content": "This failed"}]
        loop._save_trajectory(messages, "cli:direct", completed=False)

        failed_path = tmp_workspace / "trajectories" / "failed_trajectories.jsonl"
        samples_path = tmp_workspace / "trajectories" / "trajectory_samples.jsonl"

        assert failed_path.exists()
        assert not samples_path.exists()

        with open(failed_path, encoding="utf-8") as f:
            record = json.loads(f.readline())
        assert record["completed"] is False

    def test_trajectory_appends_multiple_turns(self, tmp_workspace: Path) -> None:
        """Multiple calls append to the same file, not overwrite."""
        loop = _make_loop_with_trajectories(tmp_workspace)
        for i in range(3):
            loop._save_trajectory(
                [{"role": "user", "content": f"msg {i}"}],
                "cli:direct",
                completed=True,
            )

        path = tmp_workspace / "trajectories" / "trajectory_samples.jsonl"
        with open(path, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 3

    def test_no_file_when_disabled(self, tmp_workspace: Path) -> None:
        """No file is created when save_trajectories=False (default)."""
        from unittest.mock import AsyncMock

        bus = MessageBus()
        provider = AsyncMock()
        provider.get_default_model = lambda: "test-model"
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_workspace)
        # save_trajectories defaults to False
        loop._save_trajectory(
            [{"role": "user", "content": "hello"}], "cli:direct", completed=True
        )

        assert not (tmp_workspace / "trajectories").exists()

    def test_tool_messages_excluded_from_trajectory(self, tmp_workspace: Path) -> None:
        """Tool-role messages are not included in the trajectory (only user/assistant)."""
        loop = _make_loop_with_trajectories(tmp_workspace)
        messages = [
            {"role": "user", "content": "run ls"},
            {"role": "assistant", "content": None, "tool_calls": [...]},
            {"role": "tool", "content": "file.txt"},
            {"role": "assistant", "content": "Done!"},
        ]
        loop._save_trajectory(messages, "cli:direct", completed=True)

        path = tmp_workspace / "trajectories" / "trajectory_samples.jsonl"
        with open(path, encoding="utf-8") as f:
            record = json.loads(f.readline())

        # Only user + assistant roles in ShareGPT format; tool messages excluded
        froms = [c["from"] for c in record["conversations"]]
        assert "tool" not in froms
        assert set(froms).issubset({"human", "gpt"})
