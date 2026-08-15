"""Primitives shared between the direct and torrent download paths."""

from __future__ import annotations

import threading

BLOCK_STATUS_CODES = (403, 429)


class CircuitBreaker:
    """Aborts the rest of a run after repeated 403/429s (CONCEPT.md section 10):
    better to fail loudly than keep hammering an account/IP that's being throttled."""

    def __init__(self, threshold: int = 5):
        self._threshold = threshold
        self._count = 0
        self._lock = threading.Lock()
        self.tripped = threading.Event()

    def record_block(self) -> None:
        with self._lock:
            self._count += 1
            if self._count >= self._threshold:
                self.tripped.set()
