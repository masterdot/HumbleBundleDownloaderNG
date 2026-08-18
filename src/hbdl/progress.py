"""tqdm-based progress reporting shared across download workers.

See CONCEPT.md section 6 (Progress: ein Gesamtbalken ueber alle Dateien).
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from tqdm import tqdm


@runtime_checkable
class ProgressSink(Protocol):
    """Structural interface download_all() needs from a progress reporter --
    lets a caller (the web JobManager, see CONCEPT_WEB.md M11) inject an
    alternative that publishes SSE events instead of/alongside driving a tqdm
    bar, via download_all()'s progress_factory parameter."""

    def advance(self, n: int) -> None: ...
    def close(self) -> None: ...
    def __enter__(self) -> "ProgressSink": ...
    def __exit__(self, *exc) -> None: ...


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
