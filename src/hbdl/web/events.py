"""In-process pub/sub used to stream job progress to SSE clients. The
publisher is JobManager (web/jobs.py); the subscriber is the SSE route
(web/routers/dashboard.py, GET /jobs/current/events). Deliberately in-process
only (a plain per-subscriber queue.Queue, no external broker) -- there is
exactly one web process per CONCEPT_WEB.md, no multi-worker fan-out need."""

from __future__ import annotations

import queue
import threading


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue] = []

    def subscribe(self) -> "queue.Queue[dict]":
        q: "queue.Queue[dict]" = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[dict]") -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event: dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put(event)
