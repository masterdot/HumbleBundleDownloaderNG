"""Background sync-job control for the web dashboard. M11 built start + live
progress; M12 (this) adds pause/resume/stop on top of the pause_gate/
stop_event params download_all() already accepted since M11's refactor, plus
STATUS_DOWNLOADING writes (downloader/direct.py) so the UI can show
in-progress files. One JobManager per running web process
(app.state.job_manager) -- not process-safe across multiple web workers or
against a concurrent CLI `hbdl sync`, see CONCEPT_WEB.md's "run at most one
sync at a time" operational note.

Pause vs. stop (see CONCEPT_WEB.md's Job-Steuerung section for the full
rationale): pause parks the *same* download_all() call via pause_gate --
resume is instant, no re-discovery. Stop clears download_all()'s work queue
via stop_event -- the job thread ends, JobState.STOPPED; starting again is a
fresh build_catalog()+download_all() run that naturally continues via the
existing .part/Range-resume + STATUS_VERIFIED-skip idempotency."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

from hbdl import auth, config
from hbdl.api import Client
from hbdl.catalog import build_catalog, sync_catalog_cache
from hbdl.downloader.direct import DownloadResult, download_all
from hbdl.state import open_store
from hbdl.web.events import EventBus


class JobState(str, Enum):
    IDLE = "idle"
    DISCOVERING = "discovering"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    DONE = "done"
    ERROR = "error"


_ACTIVE_STATES = (JobState.DISCOVERING, JobState.RUNNING, JobState.PAUSED)


@dataclass(slots=True)
class JobSnapshot:
    state: JobState = JobState.IDLE
    total_items: int = 0
    completed_items: int = 0
    failed_items: int = 0
    bytes_total: int = 0
    bytes_done: int = 0
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class _EventProgressSink:
    """download_all()'s progress_factory hook: publishes running byte totals
    to the EventBus instead of driving a tqdm bar. See progress.ProgressSink
    for the structural interface this needs to satisfy."""

    def __init__(self, manager: "JobManager") -> None:
        self._manager = manager

    def advance(self, n: int) -> None:
        with self._manager._lock:
            self._manager._snapshot.bytes_done += n
            done = self._manager._snapshot.bytes_done
            total = self._manager._snapshot.bytes_total
        self._manager.events.publish({"type": "bytes", "done": done, "total": total})

    def close(self) -> None:
        pass

    def __enter__(self) -> "_EventProgressSink":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._snapshot = JobSnapshot()
        self._pause_gate = threading.Event()
        self._pause_gate.set()
        self._stop_event = threading.Event()
        self.events = EventBus()

    def snapshot(self) -> JobSnapshot:
        with self._lock:
            return replace(self._snapshot)

    def is_running(self) -> bool:
        """True while a job exists and hasn't reached a terminal state --
        including PAUSED, which still occupies the single job slot."""
        with self._lock:
            return self._snapshot.state in _ACTIVE_STATES

    def start(self) -> None:
        with self._lock:
            if self._snapshot.state in _ACTIVE_STATES:
                raise RuntimeError("Ein Sync-Job laeuft bereits.")
            self._snapshot = JobSnapshot(state=JobState.DISCOVERING, started_at=_now())
            self._pause_gate = threading.Event()
            self._pause_gate.set()
            self._stop_event = threading.Event()
        self._publish_state()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        with self._lock:
            if self._snapshot.state != JobState.RUNNING:
                raise RuntimeError("Kein laufender Job zum Pausieren.")
            self._snapshot.state = JobState.PAUSED
        self._pause_gate.clear()
        self._publish_state()

    def resume(self) -> None:
        with self._lock:
            if self._snapshot.state != JobState.PAUSED:
                raise RuntimeError("Kein pausierter Job zum Fortsetzen.")
            self._snapshot.state = JobState.RUNNING
        self._pause_gate.set()
        self._publish_state()

    def stop(self) -> None:
        with self._lock:
            if self._snapshot.state not in _ACTIVE_STATES:
                raise RuntimeError("Kein laufender Job zum Stoppen.")
        self._stop_event.set()
        self._pause_gate.set()  # unblock an in-progress pause-park immediately

    def _run(self) -> None:
        try:
            session = auth.resolve_session()
            client = Client(session)
            items = build_catalog(client)
            cfg = config.Config.load()

            with open_store() as store:
                sync_catalog_cache(store, items)

                total_bytes = sum(i.file_size for i in items)
                with self._lock:
                    self._snapshot.state = JobState.RUNNING
                    self._snapshot.total_items = len(items)
                    self._snapshot.bytes_total = total_bytes
                self._publish_state()

                dest = config.resolve_dest(None)
                dest.mkdir(parents=True, exist_ok=True)

                download_all(
                    client,
                    items,
                    dest,
                    store,
                    workers=cfg.workers,
                    show_progress=False,
                    strategy=cfg.strategy,
                    on_result=self._on_result,
                    progress_factory=lambda _total: _EventProgressSink(self),
                    pause_gate=self._pause_gate,
                    stop_event=self._stop_event,
                )

            with self._lock:
                self._snapshot.state = JobState.STOPPED if self._stop_event.is_set() else JobState.DONE
                self._snapshot.finished_at = _now()
            self._publish_state()
        except Exception as exc:  # noqa: BLE001 -- surfaced to the UI, not swallowed
            with self._lock:
                self._snapshot.state = JobState.ERROR
                self._snapshot.error = str(exc)
                self._snapshot.finished_at = _now()
            self._publish_state()

    def _on_result(self, result: DownloadResult) -> None:
        with self._lock:
            self._snapshot.completed_items += 1
            if not result.ok:
                self._snapshot.failed_items += 1
        self.events.publish(
            {
                "type": "item_done",
                "human_name": result.item.human_name,
                "filename": result.item.filename,
                "ok": result.ok,
                "error": result.error,
            }
        )

    def _publish_state(self) -> None:
        with self._lock:
            snap = replace(self._snapshot)
        self.events.publish(
            {
                "type": "state",
                "state": snap.state.value,
                "total_items": snap.total_items,
                "error": snap.error,
            }
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
