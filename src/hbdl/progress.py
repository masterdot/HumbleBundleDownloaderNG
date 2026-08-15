"""tqdm-based progress reporting shared across download workers.

See CONCEPT.md section 6 (Progress: ein Gesamtbalken ueber alle Dateien).
"""

from __future__ import annotations

import threading

from tqdm import tqdm


class ProgressReporter:
    """Thread-safe wrapper around a single overall tqdm bar (bytes across all files)."""

    def __init__(self, total_bytes: int, disable: bool = False):
        self._lock = threading.Lock()
        self._bar = tqdm(
            total=total_bytes,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            disable=disable,
        )

    def advance(self, n: int) -> None:
        with self._lock:
            self._bar.update(n)

    def set_description(self, text: str) -> None:
        with self._lock:
            self._bar.set_description(text, refresh=False)

    def close(self) -> None:
        self._bar.close()

    def __enter__(self) -> "ProgressReporter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
