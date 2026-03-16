"""API key rotation with health-aware selection."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from loguru import logger

_COOLDOWN_S = 60


@dataclass
class _KeyState:
    """Internal state tracking for a single API key.

    Args:
        key: The API key string.
        error_count: Number of errors recorded for this key.
        request_count: Total requests (successes + errors) for this key.
        cooldown_until: If set, the key is unavailable until this datetime.
    """

    key: str
    error_count: int = 0
    request_count: int = 0
    cooldown_until: datetime | None = None

    @property
    def key_suffix(self) -> str:
        """Return the last 4 characters of the key for safe logging."""
        return self.key[-4:] if len(self.key) >= 4 else "****"

    def is_available(self) -> bool:
        """Return True if this key is not in cooldown.

        Returns:
            bool: True if available, False if still in cooldown window.
        """
        if self.cooldown_until is None:
            return True
        return datetime.now(timezone.utc) >= self.cooldown_until

    def error_rate(self) -> float:
        """Compute the error rate as a fraction of total requests.

        Returns:
            float: Error rate between 0.0 and 1.0; 0.0 if no requests yet.
        """
        if self.request_count == 0:
            return 0.0
        return self.error_count / self.request_count


class KeyRotator:
    """Health-aware API key rotation.

    Cycles through a list of API keys, preferring keys with lower error rates.
    Thread-safe via an internal lock.

    Args:
        keys: List of API keys to rotate through.

    Example:
        rotator = KeyRotator(["key-a", "key-b", "key-c"])
        key = rotator.current_key()
        # On failure:
        next_key = rotator.rotate_on_failure("rate_limit")
        # On success:
        rotator.record_success()
    """

    def __init__(self, keys: list[str]) -> None:
        self._states = [_KeyState(key=k) for k in keys]
        self._current_idx = 0
        self._lock = threading.Lock()

    def current_key(self) -> str:
        """Return the currently active API key.

        Returns:
            str: The current API key.
        """
        with self._lock:
            return self._states[self._current_idx].key

    def rotate_on_failure(self, reason: str) -> str | None:
        """Record a failure for the current key and rotate to the healthiest available key.

        Puts the failed key into cooldown and selects the candidate with the lowest
        error rate. Returns None if no other keys are available.

        Args:
            reason: Human-readable failure reason (e.g. "rate_limit", "auth_error").

        Returns:
            str | None: The new key after rotation, or None if all keys are exhausted.
        """
        with self._lock:
            current = self._states[self._current_idx]
            current.error_count += 1
            current.request_count += 1
            current.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=_COOLDOWN_S)
            logger.warning(
                "provider.key_rotated: ...{} failed ({})",
                current.key_suffix,
                reason,
            )
            return self._select_healthiest()

    def record_success(self) -> None:
        """Record a successful request for the current key and clear any cooldown.

        Increments the request count and removes the cooldown timer so the key
        can be considered available again after a prior failure.
        """
        with self._lock:
            state = self._states[self._current_idx]
            state.request_count += 1
            if state.cooldown_until is not None:
                state.cooldown_until = None

    def _select_healthiest(self) -> str | None:
        """Select the available key with the lowest error rate (excluding current).

        Called internally while the lock is already held.

        Returns:
            str | None: The selected key, or None if no candidates are available.
        """
        candidates = []
        for i, state in enumerate(self._states):
            if i == self._current_idx:
                continue
            if state.is_available():
                candidates.append((i, state.error_rate()))

        if not candidates:
            return None

        # Sort ascending by error rate — healthiest key first
        candidates.sort(key=lambda x: x[1])
        best_idx = candidates[0][0]
        self._current_idx = best_idx
        selected = self._states[best_idx]
        logger.info(
            "provider.key_selected: ...{} (error_rate={:.1%})",
            selected.key_suffix,
            selected.error_rate(),
        )
        return selected.key
