"""Provider health tracking with exponential backoff circuit breaker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from loguru import logger

_MAX_BACKOFF_S = 3600  # 1 hour cap
_BASE_BACKOFF_S = 60  # base: 5^0 * 60 = 60s on first failure
_PROBE_MARGIN_S = 120  # probe 2 min before cooldown expires
_MIN_PROBE_INTERVAL_S = 30

# Singleton dict of per-provider health state
_provider_health: dict[str, ProviderHealth] = {}


@dataclass
class ProviderHealth:
    """Tracks provider availability with exponential backoff cooldowns.

    Error count n produces backoff of min(5^(n-1) * 60s, 3600s):
      n=1 → 60s, n=2 → 300s, n=3 → 1500s, n=4+ → 3600s
    """

    error_count: int = 0
    cooldown_until: datetime | None = None
    last_failure_reason: str = ""
    last_probe_at: datetime | None = field(default=None, repr=False)

    def is_available(self) -> bool:
        """Return True if the provider is not in cooldown.

        Returns:
            bool: True if provider can be called now.
        """
        if self.cooldown_until is None:
            return True
        return datetime.now(timezone.utc) >= self.cooldown_until

    def record_failure(self, reason: str) -> None:
        """Record a provider failure and set exponential backoff cooldown.

        Args:
            reason (str): Failure reason / error code for diagnostics.
        """
        self.error_count += 1
        self.last_failure_reason = reason
        # Backoff: 5^(n-1) * 60s, capped at 3600s
        backoff_s = min(int(5 ** (self.error_count - 1) * _BASE_BACKOFF_S), _MAX_BACKOFF_S)
        self.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=backoff_s)
        logger.warning(
            "provider.health_degraded: error_count={} backoff={}s reason={}",
            self.error_count,
            backoff_s,
            reason,
        )

    def record_success(self) -> None:
        """Clear all failure state on a successful call."""
        if self.error_count > 0:
            logger.info("provider.health_recovered: cleared {} prior errors", self.error_count)
        self.error_count = 0
        self.cooldown_until = None
        self.last_failure_reason = ""

    def seconds_until_available(self) -> float:
        """Return seconds remaining in cooldown (0 if available).

        Returns:
            float: Seconds until provider becomes available again.
        """
        if self.cooldown_until is None:
            return 0.0
        remaining = (self.cooldown_until - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, remaining)

    def should_probe(self) -> bool:
        """Return True if we should send a probe request now.

        Probe when within PROBE_MARGIN_S of cooldown expiry, and at least
        MIN_PROBE_INTERVAL_S has elapsed since the last probe.

        Returns:
            bool: True if a probe attempt is warranted.
        """
        if self.is_available():
            return False
        remaining = self.seconds_until_available()
        if remaining > _PROBE_MARGIN_S:
            return False
        # Check probe interval
        if self.last_probe_at is None:
            return True
        since_probe = (datetime.now(timezone.utc) - self.last_probe_at).total_seconds()
        return since_probe >= _MIN_PROBE_INTERVAL_S

    def mark_probed(self) -> None:
        """Record that a probe was just sent."""
        self.last_probe_at = datetime.now(timezone.utc)


@dataclass
class KeyHealth:
    """Per-API-key health metrics.

    Args:
        key_suffix: Last 4 chars for safe logging (never log full key).
        request_count: Total requests made with this key.
        error_count: Total errors encountered with this key.
        cooldown_until: UTC datetime when this key comes off cooldown, or None.
        avg_latency_ms: Rolling average latency in milliseconds.
    """

    key_suffix: str
    request_count: int = 0
    error_count: int = 0
    cooldown_until: datetime | None = None
    avg_latency_ms: float = 0.0

    def error_rate(self) -> float:
        """Return error rate as fraction (0.0 - 1.0).

        Returns:
            float: Error rate.
        """
        if self.request_count == 0:
            return 0.0
        return self.error_count / self.request_count


def get_provider_health(provider_id: str) -> ProviderHealth:
    """Get (or create) the health state for a provider.

    Args:
        provider_id (str): Unique identifier, e.g. "ClassName:model-name".

    Returns:
        ProviderHealth: The health tracker for this provider.
    """
    if provider_id not in _provider_health:
        _provider_health[provider_id] = ProviderHealth()
    return _provider_health[provider_id]
