"""Tests for API key rotation with health-aware selection."""

from __future__ import annotations

import threading

import pytest

from velo.agent.key_rotator import KeyRotator


class TestKeyRotator:
    def test_current_key_returns_first(self):
        rotator = KeyRotator(["key-a", "key-b", "key-c"])
        assert rotator.current_key() == "key-a"

    def test_rotate_on_failure_returns_next(self):
        rotator = KeyRotator(["key-a", "key-b", "key-c"])
        next_key = rotator.rotate_on_failure("rate_limit")
        assert next_key == "key-b"
        assert rotator.current_key() == "key-b"

    def test_all_keys_exhausted_returns_none(self):
        rotator = KeyRotator(["key-a"])
        result = rotator.rotate_on_failure("rate_limit")
        assert result is None

    def test_success_clears_state(self):
        rotator = KeyRotator(["key-a", "key-b"])
        rotator.rotate_on_failure("rate_limit")
        assert rotator.current_key() == "key-b"
        rotator.record_success()
        assert rotator.current_key() == "key-b"

    def test_healthiest_key_preferred(self):
        rotator = KeyRotator(["key-a", "key-b", "key-c"])
        rotator.rotate_on_failure("rate_limit")  # key-a fails -> key-b
        rotator.rotate_on_failure("rate_limit")  # key-b fails -> key-c
        assert rotator.current_key() == "key-c"

    def test_single_key_no_rotation(self):
        rotator = KeyRotator(["only-key"])
        assert rotator.current_key() == "only-key"
        assert rotator.rotate_on_failure("error") is None
        assert rotator.current_key() == "only-key"

    def test_concurrent_rotation_thread_safe(self):
        rotator = KeyRotator(["key-a", "key-b", "key-c"])
        results: list[str | None] = []
        errors: list[Exception] = []

        def rotate():
            try:
                result = rotator.rotate_on_failure("rate_limit")
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=rotate) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        for r in results:
            assert r is None or r.startswith("key-")
