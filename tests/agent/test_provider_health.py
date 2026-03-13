"""Tests for provider health tracking and circuit breaker."""

import pytest
from datetime import datetime, timezone, timedelta

from velo.agent.provider_health import ProviderHealth, get_provider_health, _provider_health


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the provider health registry before each test."""
    _provider_health.clear()
    yield
    _provider_health.clear()


class TestProviderHealth:
    def test_is_available_initially(self):
        h = ProviderHealth()
        assert h.is_available() is True

    def test_record_failure_sets_cooldown(self):
        h = ProviderHealth()
        before = datetime.now(timezone.utc)
        h.record_failure("rate_limit")
        assert h.cooldown_until is not None
        # First failure: 5^0 * 60 = 60s backoff
        assert h.cooldown_until > before + timedelta(seconds=55)
        assert h.cooldown_until < before + timedelta(seconds=65)

    def test_first_failure_60s_backoff(self):
        h = ProviderHealth()
        h.record_failure("r1")
        assert h.error_count == 1
        remaining = h.seconds_until_available()
        assert 55 <= remaining <= 65

    def test_second_failure_300s_backoff(self):
        h = ProviderHealth()
        h.record_failure("r1")
        h.record_failure("r2")
        assert h.error_count == 2
        remaining = h.seconds_until_available()
        assert 295 <= remaining <= 305

    def test_third_failure_1500s_backoff(self):
        h = ProviderHealth()
        h.record_failure("r1")
        h.record_failure("r2")
        h.record_failure("r3")
        assert h.error_count == 3
        remaining = h.seconds_until_available()
        assert 1495 <= remaining <= 1505

    def test_backoff_capped_at_3600s(self):
        h = ProviderHealth()
        for _ in range(5):
            h.record_failure("err")
        remaining = h.seconds_until_available()
        assert remaining <= 3601

    def test_record_success_clears_state(self):
        h = ProviderHealth()
        h.record_failure("err")
        assert h.error_count == 1
        h.record_success()
        assert h.error_count == 0
        assert h.cooldown_until is None
        assert h.last_failure_reason == ""
        assert h.is_available() is True

    def test_is_not_available_during_cooldown(self):
        h = ProviderHealth()
        h.error_count = 1
        h.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=300)
        assert h.is_available() is False

    def test_is_available_after_cooldown_expires(self):
        h = ProviderHealth()
        h.error_count = 1
        h.cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert h.is_available() is True

    def test_should_probe_false_when_available(self):
        h = ProviderHealth()
        assert h.should_probe() is False

    def test_should_probe_false_far_from_expiry(self):
        h = ProviderHealth()
        h.error_count = 1
        h.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=500)
        assert h.should_probe() is False

    def test_should_probe_true_near_expiry(self):
        h = ProviderHealth()
        h.error_count = 1
        # Within probe margin (< 120s remaining)
        h.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=60)
        assert h.should_probe() is True

    def test_should_probe_respects_min_interval(self):
        h = ProviderHealth()
        h.error_count = 1
        h.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=60)
        h.mark_probed()
        # Just probed — should not probe again
        assert h.should_probe() is False

    def test_seconds_until_available_zero_when_available(self):
        h = ProviderHealth()
        assert h.seconds_until_available() == 0.0


class TestGetProviderHealth:
    def test_returns_same_instance(self):
        h1 = get_provider_health("test_provider:model")
        h2 = get_provider_health("test_provider:model")
        assert h1 is h2

    def test_different_providers_are_independent(self):
        h1 = get_provider_health("provA:m1")
        h2 = get_provider_health("provB:m2")
        h1.record_failure("err")
        assert h2.is_available() is True
