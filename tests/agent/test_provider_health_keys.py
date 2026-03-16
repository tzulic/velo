"""Tests for per-key health metrics."""

import pytest
from velo.agent.provider_health import KeyHealth


class TestKeyHealth:
    def test_error_rate_zero_requests(self):
        kh = KeyHealth(key_suffix="abcd")
        assert kh.error_rate() == 0.0

    def test_error_rate_calculation(self):
        kh = KeyHealth(key_suffix="abcd", request_count=10, error_count=3)
        assert kh.error_rate() == pytest.approx(0.3)

    def test_key_suffix_stored(self):
        kh = KeyHealth(key_suffix="wxyz")
        assert kh.key_suffix == "wxyz"

    def test_default_values(self):
        kh = KeyHealth(key_suffix="test")
        assert kh.request_count == 0
        assert kh.error_count == 0
        assert kh.cooldown_until is None
        assert kh.avg_latency_ms == 0.0

    def test_high_error_rate(self):
        kh = KeyHealth(key_suffix="bad", request_count=100, error_count=100)
        assert kh.error_rate() == 1.0
