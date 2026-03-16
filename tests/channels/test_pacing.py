"""Tests for response pacing."""

from __future__ import annotations
import asyncio
from velo.channels.pacing import ResponsePacer
from velo.config.schema import PacingConfig


class TestResponsePacer:
    def test_off_mode_yields_full_text(self):
        config = PacingConfig(mode="off")
        pacer = ResponsePacer(config)
        chunks = list(pacer.pace("Hello world"))
        assert len(chunks) == 1
        assert chunks[0][0] == "Hello world"
        assert chunks[0][1] == 0.0

    def test_natural_mode_splits_text(self):
        config = PacingConfig(mode="natural", chars_per_chunk=10)
        pacer = ResponsePacer(config)
        text = "A" * 50
        chunks = list(pacer.pace(text))
        assert len(chunks) >= 3

    def test_empty_string(self):
        config = PacingConfig(mode="natural")
        pacer = ResponsePacer(config)
        chunks = list(pacer.pace(""))
        assert len(chunks) == 0

    def test_natural_mode_delays_within_range(self):
        config = PacingConfig(mode="natural", min_delay_ms=100, max_delay_ms=500)
        pacer = ResponsePacer(config)
        chunks = list(pacer.pace("A" * 400))
        for _, delay in chunks[:-1]:
            assert 0.08 <= delay <= 0.6  # Allow jitter margin

    def test_cancellation_event(self):
        config = PacingConfig(mode="natural", chars_per_chunk=5)
        cancel = asyncio.Event()
        pacer = ResponsePacer(config, cancel=cancel)
        cancel.set()
        chunks = list(pacer.pace("A" * 100))
        assert len(chunks) <= 2
