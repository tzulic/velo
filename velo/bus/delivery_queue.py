"""Disk-backed delivery queue for reliable outbound message delivery.

Writes each outbound message to disk before attempting delivery.
On success the file is deleted. On failure the message is retried
with exponential backoff. Permanently-failing messages (e.g. blocked
users) are moved to a failed/ subdirectory without further retries.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

# Retry backoff schedule (seconds): 5, 25, 120, 600, 600
_BACKOFF_SCHEDULE = [5, 25, 120, 600, 600]

# Substrings that indicate a permanent delivery failure
_PERMANENT_FAILURE_PATTERNS = [
    "bot was blocked",
    "chat not found",
    "user is deactivated",
    "have no rights to send",
    "PEER_ID_INVALID",
]


class DeliveryQueue:
    """Disk-backed outbound message queue with retry and backoff.

    Args:
        base_dir (Path): Directory for pending and failed message files.
    """

    def __init__(self, base_dir: Path) -> None:
        self.pending_dir = base_dir / "outbound"
        self.failed_dir = base_dir / "outbound" / "failed"
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send(
        self,
        message: dict[str, Any],
        publish_fn: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """Write message to disk, attempt delivery, handle failures.

        Args:
            message (dict): Message payload (channel, chat_id, content, …).
            publish_fn (Callable): Async function that performs actual delivery.
        """
        msg_file = self._write_pending(message)
        try:
            await publish_fn(message)
            msg_file.unlink(missing_ok=True)
            logger.debug("delivery_queue.delivered: {}", msg_file.name)
        except Exception as e:
            error_str = str(e)
            if self._is_permanent(error_str):
                self._move_to_failed(msg_file, error_str)
                logger.warning(
                    "delivery_queue.permanent_failure: {} — {}", msg_file.name, error_str[:120]
                )
            else:
                self._increment_retry(msg_file, error_str)
                logger.warning(
                    "delivery_queue.retry_scheduled: {} — {}", msg_file.name, error_str[:120]
                )

    async def drain_pending(
        self,
        publish_fn: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
        budget_s: float = 60.0,
    ) -> int:
        """Retry eligible pending messages on startup.

        Args:
            publish_fn (Callable): Async function for delivery.
            budget_s (float): Maximum seconds to spend retrying.

        Returns:
            int: Number of messages successfully delivered.
        """
        import asyncio
        import time

        deadline = time.monotonic() + budget_s
        delivered = 0
        now = datetime.now(timezone.utc)

        for msg_file in sorted(self.pending_dir.glob("*.json")):
            if time.monotonic() > deadline:
                break
            try:
                data = json.loads(msg_file.read_text(encoding="utf-8"))
                next_retry_str = data.get("next_retry_at")
                if next_retry_str:
                    next_retry = datetime.fromisoformat(next_retry_str)
                    if next_retry > now:
                        continue
                message = data.get("message", {})
                await asyncio.wait_for(publish_fn(message), timeout=10.0)
                msg_file.unlink(missing_ok=True)
                delivered += 1
            except Exception as e:
                error_str = str(e)
                if self._is_permanent(error_str):
                    self._move_to_failed(msg_file, error_str)
                else:
                    self._increment_retry(msg_file, error_str)

        if delivered:
            logger.info("delivery_queue.drained: delivered {} pending messages", delivered)
        return delivered

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_pending(self, message: dict[str, Any]) -> Path:
        """Write a message to the pending directory.

        Args:
            message (dict): Message payload.

        Returns:
            Path: Path to the written file.
        """
        msg_id = str(uuid.uuid4())
        path = self.pending_dir / f"{msg_id}.json"
        record = {
            "id": msg_id,
            "message": message,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "retry_count": 0,
            "next_retry_at": None,
            "last_error": None,
        }
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return path

    def _increment_retry(self, msg_file: Path, error: str) -> None:
        """Update retry metadata on a failed delivery attempt.

        Args:
            msg_file (Path): Path to the pending message file.
            error (str): Error message from the failed delivery.
        """
        try:
            data = json.loads(msg_file.read_text(encoding="utf-8"))
            retry_count = data.get("retry_count", 0) + 1
            idx = min(retry_count - 1, len(_BACKOFF_SCHEDULE) - 1)
            backoff_s = _BACKOFF_SCHEDULE[idx]
            next_retry = datetime.now(timezone.utc) + timedelta(seconds=backoff_s)
            data["retry_count"] = retry_count
            data["next_retry_at"] = next_retry.isoformat()
            data["last_error"] = error[:500]
            msg_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("delivery_queue.retry_update_failed: {}", e)

    def _move_to_failed(self, msg_file: Path, error: str) -> None:
        """Move a message to the failed directory.

        Args:
            msg_file (Path): Path to the pending message file.
            error (str): Error message explaining the permanent failure.
        """
        try:
            data = json.loads(msg_file.read_text(encoding="utf-8"))
            data["permanent_failure"] = error[:500]
            data["failed_at"] = datetime.now(timezone.utc).isoformat()
            dest = self.failed_dir / msg_file.name
            dest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            msg_file.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("delivery_queue.move_failed: {}", e)

    @staticmethod
    def _is_permanent(error: str) -> bool:
        """Return True if the error indicates a permanent delivery failure.

        Args:
            error (str): Error string to check.

        Returns:
            bool: True if retrying would be pointless.
        """
        lower = error.lower()
        return any(pattern.lower() in lower for pattern in _PERMANENT_FAILURE_PATTERNS)
