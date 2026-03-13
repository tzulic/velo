"""Tests for disk-backed delivery queue."""

import asyncio
import json
import pytest

from velo.bus.delivery_queue import DeliveryQueue


@pytest.fixture
def queue(tmp_path):
    return DeliveryQueue(base_dir=tmp_path)


class TestDeliveryQueue:
    @pytest.mark.asyncio
    async def test_successful_delivery_deletes_file(self, queue):
        """On success the pending file should be deleted."""
        delivered = []

        async def publish(msg):
            delivered.append(msg)

        await queue.send({"content": "hello"}, publish)
        assert delivered == [{"content": "hello"}]
        # No pending files should remain
        pending = list(queue.pending_dir.glob("*.json"))
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_failed_delivery_keeps_pending_file(self, queue):
        """On failure the pending file should remain with updated retry metadata."""

        async def publish(msg):
            raise ConnectionError("network error")

        await queue.send({"content": "retry me"}, publish)
        pending = list(queue.pending_dir.glob("*.json"))
        assert len(pending) == 1
        data = json.loads(pending[0].read_text())
        assert data["retry_count"] == 1
        assert data["next_retry_at"] is not None

    @pytest.mark.asyncio
    async def test_permanent_failure_moves_to_failed(self, queue):
        """Permanent failure patterns should move the message to failed/."""

        async def publish(msg):
            raise Exception("bot was blocked by the user")

        await queue.send({"content": "blocked"}, publish)
        pending = list(queue.pending_dir.glob("*.json"))
        failed = list(queue.failed_dir.glob("*.json"))
        assert len(pending) == 0
        assert len(failed) == 1

    @pytest.mark.asyncio
    async def test_permanent_failure_chat_not_found(self, queue):
        """'chat not found' should also be treated as permanent."""

        async def publish(msg):
            raise Exception("Bad Request: chat not found")

        await queue.send({"content": "gone"}, publish)
        failed = list(queue.failed_dir.glob("*.json"))
        assert len(failed) == 1

    @pytest.mark.asyncio
    async def test_drain_delivers_eligible_messages(self, queue, tmp_path):
        """drain_pending should retry eligible messages."""
        delivered = []

        # Write a pending message with a past retry time
        msg_id = "test-abc"
        record = {
            "id": msg_id,
            "message": {"content": "retry"},
            "created_at": "2026-01-01T00:00:00+00:00",
            "retry_count": 1,
            "next_retry_at": "2026-01-01T00:00:00+00:00",  # in the past
            "last_error": "timeout",
        }
        pending_file = queue.pending_dir / f"{msg_id}.json"
        pending_file.write_text(json.dumps(record), encoding="utf-8")

        async def publish(msg):
            delivered.append(msg)

        count = await queue.drain_pending(publish)
        assert count == 1
        assert delivered == [{"content": "retry"}]

    @pytest.mark.asyncio
    async def test_drain_skips_future_retry(self, queue):
        """Messages with a future next_retry_at should not be retried."""
        from datetime import datetime, timedelta, timezone

        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        record = {
            "id": "skip-me",
            "message": {"content": "not yet"},
            "created_at": "2026-01-01T00:00:00+00:00",
            "retry_count": 1,
            "next_retry_at": future,
            "last_error": "timeout",
        }
        (queue.pending_dir / "skip-me.json").write_text(json.dumps(record), encoding="utf-8")

        delivered = []

        async def publish(msg):
            delivered.append(msg)

        await queue.drain_pending(publish)
        assert len(delivered) == 0

    def test_is_permanent_patterns(self, queue):
        assert queue._is_permanent("bot was blocked by the user") is True
        assert queue._is_permanent("Bad Request: chat not found") is True
        assert queue._is_permanent("user is deactivated") is True
        assert queue._is_permanent("network timeout") is False
        assert queue._is_permanent("server error 500") is False
