"""Response pacing for natural message delivery on chat platforms."""
from __future__ import annotations
import asyncio
import random
from collections.abc import Iterator
from velo.config.schema import PacingConfig


class ResponsePacer:
    """Splits text into chunks with delays for natural delivery.

    Args:
        config: Pacing configuration.
        cancel: Optional event that aborts pacing when set.
    """

    def __init__(self, config: PacingConfig, cancel: asyncio.Event | None = None) -> None:
        self._config = config
        self._cancel = cancel

    def pace(self, text: str) -> Iterator[tuple[str, float]]:
        """Yield (chunk, delay_seconds) pairs for natural delivery.

        Args:
            text: Full response text to pace.

        Yields:
            tuple[str, float]: (text_chunk, delay_before_next_chunk)
        """
        if not text:
            return
        if self._config.mode == "off":
            yield (text, 0.0)
            return

        chunk_size = max(1, self._config.chars_per_chunk)
        min_s = self._config.min_delay_ms / 1000.0
        max_s = self._config.max_delay_ms / 1000.0
        pos = 0

        while pos < len(text):
            if self._cancel and self._cancel.is_set():
                remainder = text[pos:]
                if remainder:
                    yield (remainder, 0.0)
                return

            end = min(pos + chunk_size, len(text))
            if end < len(text):
                space_idx = text.rfind(" ", pos + chunk_size // 2, end + 20)
                if space_idx > pos:
                    end = space_idx + 1

            chunk = text[pos:end]
            pos = end

            if pos >= len(text):
                yield (chunk, 0.0)
            else:
                ratio = len(chunk) / chunk_size
                delay = min_s + (max_s - min_s) * min(ratio, 1.0)
                delay *= random.uniform(0.8, 1.2)
                delay = max(min_s, min(max_s, delay))
                yield (chunk, delay)
