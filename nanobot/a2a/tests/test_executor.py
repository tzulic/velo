"""Tests for NanobotAgentExecutor.

Requires a2a-sdk to be installed.  Tests are skipped automatically when the
package is absent so the CI suite remains green in non-A2A environments.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytest.importorskip("a2a", reason="a2a-sdk not installed — skipping executor tests")


def _make_context(task_id: str = "task-1", context_id: str = "ctx-1", text: str = "Hello") -> MagicMock:
    ctx = MagicMock()
    ctx.task_id = task_id
    ctx.context_id = context_id
    ctx.get_user_input.return_value = text
    return ctx


def _make_event_queue() -> MagicMock:
    return MagicMock()


class TestNanobotAgentExecutor:
    """Tests for NanobotAgentExecutor."""

    @pytest.mark.asyncio
    @patch("nanobot.a2a.executor.TaskUpdater")
    @patch("nanobot.a2a.executor.TaskState")
    @patch("nanobot.a2a.executor.Part")
    @patch("nanobot.a2a.executor.TextPart")
    async def test_execute_success(self, mock_text_part, mock_part, mock_state, mock_updater_cls):
        """Successful execution marks task as completed."""
        from nanobot.a2a.executor import NanobotAgentExecutor

        loop = MagicMock()
        loop.process_direct = AsyncMock(return_value="Done!")
        executor = NanobotAgentExecutor(loop)

        updater = MagicMock()
        updater.new_agent_message.return_value = MagicMock()
        mock_updater_cls.return_value = updater

        ctx = _make_context(text="Do a thing")
        await executor.execute(ctx, _make_event_queue())

        updater.submit.assert_called_once()
        updater.start_work.assert_called_once()
        loop.process_direct.assert_called_once()
        updater.update_status.assert_called_once()
        call_args = updater.update_status.call_args
        assert call_args.args[0] == mock_state.completed

    @pytest.mark.asyncio
    @patch("nanobot.a2a.executor.TaskUpdater")
    @patch("nanobot.a2a.executor.TaskState")
    @patch("nanobot.a2a.executor.Part")
    @patch("nanobot.a2a.executor.TextPart")
    async def test_execute_failure_marks_failed(
        self, mock_text_part, mock_part, mock_state, mock_updater_cls
    ):
        """When process_direct raises, task is marked as failed."""
        from nanobot.a2a.executor import NanobotAgentExecutor

        loop = MagicMock()
        loop.process_direct = AsyncMock(side_effect=RuntimeError("boom"))
        executor = NanobotAgentExecutor(loop)

        updater = MagicMock()
        updater.new_agent_message.return_value = MagicMock()
        mock_updater_cls.return_value = updater

        await executor.execute(_make_context(), _make_event_queue())

        call_args = updater.update_status.call_args
        assert call_args.args[0] == mock_state.failed

    @pytest.mark.asyncio
    @patch("nanobot.a2a.executor.TaskUpdater")
    @patch("nanobot.a2a.executor.TaskState")
    async def test_cancel_marks_canceled(self, mock_state, mock_updater_cls):
        """cancel() marks task as canceled."""
        from nanobot.a2a.executor import NanobotAgentExecutor

        updater = MagicMock()
        mock_updater_cls.return_value = updater

        executor = NanobotAgentExecutor(MagicMock())
        await executor.cancel(_make_context(), _make_event_queue())

        updater.update_status.assert_called_once_with(mock_state.canceled)

    @pytest.mark.asyncio
    @patch("nanobot.a2a.executor.TaskUpdater")
    @patch("nanobot.a2a.executor.TaskState")
    @patch("nanobot.a2a.executor.Part")
    @patch("nanobot.a2a.executor.TextPart")
    async def test_session_key_is_scoped_to_task(
        self, mock_text_part, mock_part, mock_state, mock_updater_cls
    ):
        """Session key contains the A2A task ID."""
        from nanobot.a2a.executor import NanobotAgentExecutor

        loop = MagicMock()
        loop.process_direct = AsyncMock(return_value="ok")
        executor = NanobotAgentExecutor(loop)
        mock_updater_cls.return_value = MagicMock()

        await executor.execute(_make_context(task_id="abc-123"), _make_event_queue())

        _, kwargs = loop.process_direct.call_args
        assert "abc-123" in kwargs["session_key"]
        assert kwargs["channel"] == "a2a"
