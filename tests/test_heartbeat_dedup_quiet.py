"""Tests for heartbeat deduplication and quiet hours."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from velo.heartbeat.service import HeartbeatService
from velo.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from velo.session.manager import SessionManager


class _RunProvider(LLMProvider):
    """Always returns 'run' action."""

    async def chat(self, *args, **kwargs) -> LLMResponse:
        return LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check tasks"},
                )
            ],
        )

    def get_default_model(self) -> str:
        return "test"


# ── Deduplication ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_identical_heartbeat_suppressed_within_24h(tmp_path):
    """Identical heartbeat response within 24h should NOT call on_notify."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] task", encoding="utf-8")

    notify_calls: list[str] = []

    async def on_execute(tasks: str) -> str:
        return "same response"

    async def on_notify(response: str) -> None:
        notify_calls.append(response)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=_RunProvider(),
        model="test",
        on_execute=on_execute,
        on_notify=on_notify,
    )

    # First tick — should deliver
    await service._tick()
    assert len(notify_calls) == 1

    # Second tick with same response — should be suppressed
    await service._tick()
    assert len(notify_calls) == 1  # still 1


@pytest.mark.asyncio
async def test_different_heartbeat_delivered(tmp_path):
    """Different heartbeat response should always be delivered."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] task", encoding="utf-8")

    responses = ["response A", "response B"]
    idx = 0
    notify_calls: list[str] = []

    async def on_execute(tasks: str) -> str:
        nonlocal idx
        r = responses[idx % len(responses)]
        idx += 1
        return r

    async def on_notify(response: str) -> None:
        notify_calls.append(response)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=_RunProvider(),
        model="test",
        on_execute=on_execute,
        on_notify=on_notify,
    )

    await service._tick()
    await service._tick()
    assert len(notify_calls) == 2


@pytest.mark.asyncio
async def test_duplicate_after_24h_delivered(tmp_path):
    """Identical response older than 24h should be re-delivered."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] task", encoding="utf-8")

    notify_calls: list[str] = []

    async def on_execute(tasks: str) -> str:
        return "same"

    async def on_notify(response: str) -> None:
        notify_calls.append(response)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=_RunProvider(),
        model="test",
        on_execute=on_execute,
        on_notify=on_notify,
    )

    # Simulate last delivery was > 24h ago
    await service._tick()
    service._last_heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=25)
    assert len(notify_calls) == 1

    await service._tick()
    assert len(notify_calls) == 2


# ── Quiet Hours ────────────────────────────────────────────────────────────────


class TestQuietHours:
    def _service(self, tmp_path, *, quiet_start, quiet_end, tz="UTC"):
        return HeartbeatService(
            workspace=tmp_path,
            provider=_RunProvider(),
            model="test",
            quiet_start=quiet_start,
            quiet_end=quiet_end,
            quiet_timezone=tz,
        )

    def test_not_in_quiet_hours_when_unconfigured(self, tmp_path):
        svc = HeartbeatService(workspace=tmp_path, provider=_RunProvider(), model="test")
        assert svc._in_quiet_hours() is False

    def test_same_day_window_inside(self, tmp_path):
        """09:00–17:00 window: 12:00 UTC is inside."""
        from unittest.mock import patch
        from datetime import datetime, timezone

        svc = self._service(tmp_path, quiet_start="09:00", quiet_end="17:00")
        fake_now = datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc)
        with patch("velo.heartbeat.service.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert svc._in_quiet_hours() is True

    def test_same_day_window_outside(self, tmp_path):
        """09:00–17:00 window: 08:00 UTC is outside."""
        from unittest.mock import patch

        svc = self._service(tmp_path, quiet_start="09:00", quiet_end="17:00")
        fake_now = datetime(2026, 3, 13, 8, 0, tzinfo=timezone.utc)
        with patch("velo.heartbeat.service.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert svc._in_quiet_hours() is False

    def test_midnight_wrap_inside(self, tmp_path):
        """23:00–07:00 window: 02:00 UTC is inside."""
        from unittest.mock import patch

        svc = self._service(tmp_path, quiet_start="23:00", quiet_end="07:00")
        fake_now = datetime(2026, 3, 13, 2, 0, tzinfo=timezone.utc)
        with patch("velo.heartbeat.service.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert svc._in_quiet_hours() is True

    def test_midnight_wrap_outside(self, tmp_path):
        """23:00–07:00 window: 10:00 UTC is outside."""
        from unittest.mock import patch

        svc = self._service(tmp_path, quiet_start="23:00", quiet_end="07:00")
        fake_now = datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc)
        with patch("velo.heartbeat.service.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            assert svc._in_quiet_hours() is False


@pytest.mark.asyncio
async def test_quiet_hours_suppresses_on_notify(tmp_path):
    """During quiet hours, on_notify should not be called."""
    from unittest.mock import patch

    (tmp_path / "HEARTBEAT.md").write_text("- [ ] task", encoding="utf-8")

    notify_calls: list[str] = []

    async def on_execute(tasks: str) -> str:
        return "important message"

    async def on_notify(response: str) -> None:
        notify_calls.append(response)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=_RunProvider(),
        model="test",
        on_execute=on_execute,
        on_notify=on_notify,
        quiet_start="00:00",
        quiet_end="23:59",  # always quiet
    )

    await service._tick()
    assert len(notify_calls) == 0


# ── Event-Driven Wake ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_push_event_wakes_immediately(tmp_path):
    """push_event should trigger a tick before the next interval."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] task", encoding="utf-8")

    notify_calls: list[str] = []

    async def on_execute(tasks: str) -> str:
        return f"event: {tasks}"

    async def on_notify(response: str) -> None:
        notify_calls.append(response)

    # Very long interval so normal sleep won't trigger
    service = HeartbeatService(
        workspace=tmp_path,
        provider=_RunProvider(),
        model="test",
        on_execute=on_execute,
        on_notify=on_notify,
        interval_s=9999,
    )

    await service.start()
    service.push_event({"type": "subagent_complete", "summary": "done"})

    # Should wake and call notify within a short time
    await asyncio.sleep(0.2)
    service.stop()

    assert len(notify_calls) >= 1


# ── Session persistence ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dedup_state_persisted_to_session(tmp_path):
    """After delivery, last_heartbeat_text/at should be saved to the heartbeat session."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] task", encoding="utf-8")
    sm = SessionManager(tmp_path)

    async def on_execute(_: str) -> str:
        return "persistent response"

    async def on_notify(_: str) -> None:
        pass

    service = HeartbeatService(
        workspace=tmp_path,
        provider=_RunProvider(),
        model="test",
        on_execute=on_execute,
        on_notify=on_notify,
        session_manager=sm,
    )
    await service._tick()

    session = sm.get_or_create("heartbeat")
    assert session.last_heartbeat_text == "persistent response"
    assert session.last_heartbeat_at is not None


@pytest.mark.asyncio
async def test_dedup_state_loaded_on_start(tmp_path):
    """On start(), dedup state is seeded from the persisted heartbeat session."""
    sm = SessionManager(tmp_path)

    # Pre-populate the session with a prior delivery
    prior_text = "prior response"
    prior_at = datetime.now(timezone.utc)
    session = sm.get_or_create("heartbeat")
    session.last_heartbeat_text = prior_text
    session.last_heartbeat_at = prior_at
    sm.save(session)

    notify_calls: list[str] = []

    async def on_execute(_: str) -> str:
        return prior_text  # Same response as what was persisted

    async def on_notify(r: str) -> None:
        notify_calls.append(r)

    (tmp_path / "HEARTBEAT.md").write_text("- [ ] task", encoding="utf-8")
    service = HeartbeatService(
        workspace=tmp_path,
        provider=_RunProvider(),
        model="test",
        on_execute=on_execute,
        on_notify=on_notify,
        session_manager=sm,
    )
    await service.start()
    # Dedup state should be loaded — prior_text within 24h should be suppressed
    await service._tick()
    service.stop()

    assert len(notify_calls) == 0, "Should suppress delivery of already-sent response after restart"
