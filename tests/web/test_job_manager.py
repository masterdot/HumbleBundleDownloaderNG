"""M11: the download_all() incremental-submission refactor (pause_gate/
stop_event) and the web JobManager built on top of it. The pause/stop
mechanics are exercised directly against download_all() here -- deterministic
via responses.add_callback() blocking gates rather than sleep-based races --
even though the JobManager/dashboard don't expose pause/stop until M12; this
validates the refactor itself, which M11's scope explicitly introduces."""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import responses

from hbdl import auth, config
from hbdl.api import Client
from hbdl.auth import Session
from hbdl.downloader.direct import download_all
from hbdl.models import DownloadItem
from hbdl.state import StateStore
from hbdl.web.events import EventBus
from hbdl.web.jobs import JobManager, JobState

CONTENT = b"hello world" * 1000
SHA1 = hashlib.sha1(CONTENT).hexdigest()


def _item(**overrides) -> DownloadItem:
    defaults = dict(
        gamekey="abc123",
        human_name="Example Bundle",
        subproduct_name="Example Game",
        platform="ebook",
        variant_name="PDF",
        filename="book.pdf",
        url="https://dl.humble.com/book.pdf?ttl=1",
        url_fetched_at=datetime.now(timezone.utc),
        file_size=len(CONTENT),
        md5=None,
        sha1=SHA1,
        torrent_url=None,
    )
    defaults.update(overrides)
    return DownloadItem(**defaults)


@responses.activate
def test_pause_blocks_new_submissions_but_lets_in_flight_finish(tmp_path):
    items = [
        _item(filename="f0.pdf", url="https://dl.humble.com/f0.pdf?ttl=1"),
        _item(filename="f1.pdf", url="https://dl.humble.com/f1.pdf?ttl=1"),
        _item(filename="f2.pdf", url="https://dl.humble.com/f2.pdf?ttl=1"),
    ]
    release = threading.Event()

    def blocking_callback(request):
        release.wait(timeout=5)
        return (200, {}, CONTENT)

    responses.add_callback(responses.GET, "https://dl.humble.com/f0.pdf", callback=blocking_callback)
    responses.get("https://dl.humble.com/f1.pdf", body=CONTENT, status=200)
    responses.get("https://dl.humble.com/f2.pdf", body=CONTENT, status=200)

    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    pause_gate = threading.Event()
    pause_gate.set()

    result: dict = {}
    thread = threading.Thread(
        target=lambda: result.update(
            report=download_all(
                client, items, tmp_path, store, workers=1, show_progress=False, pause_gate=pause_gate
            )
        )
    )
    thread.start()
    time.sleep(0.2)  # f0 is now blocked inside the callback (workers=1: the only in-flight item)

    pause_gate.clear()
    time.sleep(0.2)  # paused while f0 still in flight -- no new submissions should start

    release.set()  # let f0 finish
    time.sleep(0.3)  # f0 completes; paused, so f1/f2 must NOT start yet

    assert store.get(items[0].identity_key) is not None
    assert store.get(items[1].identity_key) is None
    assert store.get(items[2].identity_key) is None

    pause_gate.set()  # resume
    thread.join(timeout=5)

    report = result["report"]
    assert len(report.succeeded) == 3


@responses.activate
def test_stop_event_drains_in_flight_but_submits_no_more(tmp_path):
    items = [
        _item(filename="f0.pdf", url="https://dl.humble.com/f0.pdf?ttl=1"),
        _item(filename="f1.pdf", url="https://dl.humble.com/f1.pdf?ttl=1"),
    ]
    release = threading.Event()

    def blocking_callback(request):
        release.wait(timeout=5)
        return (200, {}, CONTENT)

    responses.add_callback(responses.GET, "https://dl.humble.com/f0.pdf", callback=blocking_callback)
    responses.get("https://dl.humble.com/f1.pdf", body=CONTENT, status=200)

    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    stop_event = threading.Event()

    result: dict = {}
    thread = threading.Thread(
        target=lambda: result.update(
            report=download_all(
                client, items, tmp_path, store, workers=1, show_progress=False, stop_event=stop_event
            )
        )
    )
    thread.start()
    time.sleep(0.2)  # f0 now blocked in flight

    stop_event.set()
    release.set()  # let the in-flight item finish -- it should still be collected
    thread.join(timeout=5)

    report = result["report"]
    assert len(report.succeeded) == 1
    assert report.succeeded[0].item.filename == "f0.pdf"
    assert store.get(items[1].identity_key) is None  # never submitted after stop


# -- EventBus -----------------------------------------------------------

def test_event_bus_delivers_to_subscribers():
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()

    bus.publish({"type": "state", "state": "running"})

    assert q1.get(timeout=1) == {"type": "state", "state": "running"}
    assert q2.get(timeout=1) == {"type": "state", "state": "running"}


def test_event_bus_unsubscribe_stops_delivery():
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)

    bus.publish({"type": "state", "state": "running"})

    assert q.empty()


# -- JobManager -----------------------------------------------------------

def _wait_until_idle(manager: JobManager, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while manager.is_running() and time.time() < deadline:
        time.sleep(0.02)


@responses.activate
def test_job_manager_runs_to_completion_and_updates_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    monkeypatch.setenv("HBDL_DEST", str(tmp_path / "lib"))

    items = [
        _item(filename="f0.pdf", url="https://dl.humble.com/f0.pdf?ttl=1"),
        _item(filename="f1.pdf", url="https://dl.humble.com/f1.pdf?ttl=1"),
    ]
    responses.get("https://dl.humble.com/f0.pdf", body=CONTENT, status=200)
    responses.get("https://dl.humble.com/f1.pdf", body=CONTENT, status=200)

    monkeypatch.setattr("hbdl.web.jobs.auth.resolve_session", lambda: Session(cookie_value="dummy"))
    monkeypatch.setattr("hbdl.web.jobs.build_catalog", lambda client: items)

    manager = JobManager()
    events_seen = []
    q = manager.events.subscribe()

    manager.start()
    _wait_until_idle(manager)

    snap = manager.snapshot()
    assert snap.state == JobState.DONE
    assert snap.total_items == 2
    assert snap.completed_items == 2
    assert snap.failed_items == 0
    assert snap.bytes_done == snap.bytes_total

    while not q.empty():
        events_seen.append(q.get())
    event_types = {e["type"] for e in events_seen}
    assert "state" in event_types
    assert "item_done" in event_types
    assert "bytes" in event_types


def test_job_manager_rejects_concurrent_start(monkeypatch, tmp_path):
    # fake_build_catalog returns [], but _run() still proceeds to open_store()
    # afterwards -- STATE_DB must be isolated or that touches the real,
    # machine-wide state.sqlite (this bit us once already, see
    # CONCEPT_WEB.md's M11 entry).
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    monkeypatch.setenv("HBDL_DEST", str(tmp_path / "lib"))
    started = threading.Event()
    release = threading.Event()

    def fake_build_catalog(client):
        started.set()
        release.wait(timeout=5)
        return []

    monkeypatch.setattr("hbdl.web.jobs.auth.resolve_session", lambda: Session(cookie_value="dummy"))
    monkeypatch.setattr("hbdl.web.jobs.build_catalog", fake_build_catalog)

    manager = JobManager()
    manager.start()
    assert started.wait(timeout=5)

    with pytest.raises(RuntimeError):
        manager.start()

    release.set()
    _wait_until_idle(manager)


def test_job_manager_captures_error_state_on_auth_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")

    def raise_auth_error():
        raise auth.AuthError("kein Login gefunden")

    monkeypatch.setattr("hbdl.web.jobs.auth.resolve_session", raise_auth_error)

    manager = JobManager()
    manager.start()
    _wait_until_idle(manager)

    snap = manager.snapshot()
    assert snap.state == JobState.ERROR
    assert "kein Login gefunden" in snap.error


# -- JobManager pause/resume/stop (M12) ------------------------------------

def test_pause_raises_if_no_job_running():
    manager = JobManager()
    with pytest.raises(RuntimeError):
        manager.pause()


def test_resume_raises_if_not_paused():
    manager = JobManager()
    with pytest.raises(RuntimeError):
        manager.resume()


def test_stop_raises_if_idle():
    manager = JobManager()
    with pytest.raises(RuntimeError):
        manager.stop()


def _wait_for_state(manager: JobManager, state: JobState, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while manager.snapshot().state != state and time.time() < deadline:
        time.sleep(0.02)


@responses.activate
def test_pause_then_resume_completes_all_items(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    monkeypatch.setenv("HBDL_DEST", str(tmp_path / "lib"))
    config_file = tmp_path / "config.toml"
    config.Config(workers=1, strategy="direct").save(path=config_file)
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    items = [
        _item(filename="f0.pdf", url="https://dl.humble.com/f0.pdf?ttl=1"),
        _item(filename="f1.pdf", url="https://dl.humble.com/f1.pdf?ttl=1"),
        _item(filename="f2.pdf", url="https://dl.humble.com/f2.pdf?ttl=1"),
    ]
    release = threading.Event()

    def blocking_callback(request):
        release.wait(timeout=5)
        return (200, {}, CONTENT)

    responses.add_callback(responses.GET, "https://dl.humble.com/f0.pdf", callback=blocking_callback)
    responses.get("https://dl.humble.com/f1.pdf", body=CONTENT, status=200)
    responses.get("https://dl.humble.com/f2.pdf", body=CONTENT, status=200)

    monkeypatch.setattr("hbdl.web.jobs.auth.resolve_session", lambda: Session(cookie_value="dummy"))
    monkeypatch.setattr("hbdl.web.jobs.build_catalog", lambda client: items)

    manager = JobManager()
    manager.start()
    _wait_for_state(manager, JobState.RUNNING)
    time.sleep(0.1)  # let the loop actually submit f0 (workers=1, so only f0 is in flight)

    manager.pause()
    assert manager.snapshot().state == JobState.PAUSED

    release.set()  # let f0 finish
    time.sleep(0.2)  # paused -- f1/f2 must NOT start even though f0 just completed

    assert manager.snapshot().completed_items == 1

    manager.resume()
    _wait_until_idle(manager)

    snap = manager.snapshot()
    assert snap.state == JobState.DONE
    assert snap.completed_items == 3
    assert snap.failed_items == 0


@responses.activate
def test_stop_ends_job_early_and_marks_stopped(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    monkeypatch.setenv("HBDL_DEST", str(tmp_path / "lib"))
    config_file = tmp_path / "config.toml"
    config.Config(workers=1, strategy="direct").save(path=config_file)
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    items = [
        _item(filename="f0.pdf", url="https://dl.humble.com/f0.pdf?ttl=1"),
        _item(filename="f1.pdf", url="https://dl.humble.com/f1.pdf?ttl=1"),
    ]
    release = threading.Event()

    def blocking_callback(request):
        release.wait(timeout=5)
        return (200, {}, CONTENT)

    responses.add_callback(responses.GET, "https://dl.humble.com/f0.pdf", callback=blocking_callback)
    responses.get("https://dl.humble.com/f1.pdf", body=CONTENT, status=200)

    monkeypatch.setattr("hbdl.web.jobs.auth.resolve_session", lambda: Session(cookie_value="dummy"))
    monkeypatch.setattr("hbdl.web.jobs.build_catalog", lambda client: items)

    manager = JobManager()
    manager.start()
    _wait_for_state(manager, JobState.RUNNING)
    time.sleep(0.1)

    manager.stop()
    release.set()  # let the in-flight f0 finish -- should still be collected
    _wait_until_idle(manager)

    snap = manager.snapshot()
    assert snap.state == JobState.STOPPED
    assert snap.completed_items == 1  # only f0; f1 never submitted after stop
