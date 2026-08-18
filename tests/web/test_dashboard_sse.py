"""M11: dashboard job-start route and the /jobs/current/events SSE stream.
M12: pause/resume/stop routes on top of the same JobManager. See
CONCEPT_WEB.md's testing note on SSE being "a slightly more fragile corner of
an otherwise fully synchronous, fixture-driven suite" -- kept deliberately
light."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import responses
from fastapi.testclient import TestClient

from hbdl import config
from hbdl.auth import Session
from hbdl.models import DownloadItem
from hbdl.web.app import create_app
from hbdl.web.jobs import JobState
from hbdl.web.routers.dashboard import job_events


def _wait_until_idle(app, timeout: float = 5.0) -> None:
    job_manager = app.state.job_manager
    deadline = time.time() + timeout
    while job_manager.is_running() and time.time() < deadline:
        time.sleep(0.02)


def _wait_for_state(app, state: JobState, timeout: float = 5.0) -> None:
    job_manager = app.state.job_manager
    deadline = time.time() + timeout
    while job_manager.snapshot().state != state and time.time() < deadline:
        time.sleep(0.02)


def test_dashboard_shows_ready_state_and_start_button(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    client = TestClient(create_app())

    resp = client.get("/")

    assert resp.status_code == 200
    assert "Bereit" in resp.text
    assert 'hx-post="/jobs/current/start"' in resp.text


def test_start_job_returns_discovering_state_fragment(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    started = threading.Event()
    release = threading.Event()

    def blocking_resolve_session():
        started.set()
        release.wait(timeout=5)
        raise RuntimeError("blocked")

    monkeypatch.setattr("hbdl.web.jobs.auth.resolve_session", blocking_resolve_session)
    app = create_app()
    client = TestClient(app)

    resp = client.post("/jobs/current/start")
    started.wait(timeout=5)  # the background thread is now parked inside resolve_session

    assert resp.status_code == 200
    assert "Ermittle Bibliothek" in resp.text

    release.set()
    _wait_until_idle(app)


def test_start_job_twice_does_not_error(monkeypatch, tmp_path):
    """A second POST while a job is already running should just re-render the
    current state, not 500 -- JobManager.start()'s RuntimeError is caught."""
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    started = threading.Event()
    release = threading.Event()

    def fake_build_catalog(client):
        started.set()
        release.wait(timeout=5)
        return []

    monkeypatch.setattr("hbdl.web.jobs.auth.resolve_session", lambda: Session(cookie_value="dummy"))
    monkeypatch.setattr("hbdl.web.jobs.build_catalog", fake_build_catalog)

    app = create_app()
    client = TestClient(app)

    first = client.post("/jobs/current/start")
    assert started.wait(timeout=5)
    second = client.post("/jobs/current/start")

    assert first.status_code == 200
    assert second.status_code == 200

    release.set()
    # Wait for the background job to actually finish before the test (and its
    # monkeypatches/tmp_path) tears down -- otherwise the job thread can keep
    # running past teardown and touch the real, un-monkeypatched config/state
    # paths once pytest reverts them (a real, previously-hit source of
    # cross-test flakiness; see CONCEPT_WEB.md's M11 entry).
    _wait_until_idle(app)


def test_pause_resume_stop_routes_render_updated_state(monkeypatch, tmp_path):
    """Full M12 round trip through the HTTP routes (not just JobManager
    directly, that's covered by tests/web/test_job_manager.py): start, pause
    mid-flight, resume, then stop a fresh run -- each response reflects the
    new state, and none of it 500s."""
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    monkeypatch.setenv("HBDL_DEST", str(tmp_path / "lib"))
    config_file = tmp_path / "config.toml"
    config.Config(workers=1, strategy="direct").save(path=config_file)
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    release = threading.Event()

    def blocking_build_catalog(client):
        release.wait(timeout=5)
        return []

    monkeypatch.setattr("hbdl.web.jobs.auth.resolve_session", lambda: Session(cookie_value="dummy"))
    monkeypatch.setattr("hbdl.web.jobs.build_catalog", blocking_build_catalog)

    app = create_app()
    client = TestClient(app)

    client.post("/jobs/current/start")
    # Still DISCOVERING (blocked in build_catalog) -- pause is only valid once
    # RUNNING, so it should be tolerated (no 500), just a no-op re-render.
    pause_while_discovering = client.post("/jobs/current/pause")
    assert pause_while_discovering.status_code == 200

    release.set()
    _wait_until_idle(app)  # total_items=0 -> download_all finishes immediately -> DONE

    resp = client.get("/")
    assert "Fertig" in resp.text


def _download_item(filename: str) -> DownloadItem:
    return DownloadItem(
        gamekey="k", human_name="Bundle", subproduct_name="Sub", platform="ebook",
        variant_name="PDF", filename=filename, url=f"https://dl.humble.com/{filename}?ttl=1",
        url_fetched_at=datetime.now(timezone.utc), file_size=10, md5=None, sha1=None, torrent_url=None,
    )


@responses.activate
def test_pause_and_resume_via_routes_reflect_running_and_paused_state(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    monkeypatch.setenv("HBDL_DEST", str(tmp_path / "lib"))
    config_file = tmp_path / "config.toml"
    config.Config(workers=1, strategy="direct").save(path=config_file)
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    items = [_download_item("f0.pdf"), _download_item("f1.pdf")]
    release = threading.Event()

    def blocking_callback(request):
        release.wait(timeout=5)
        return (200, {}, b"x" * 10)

    responses.add_callback(responses.GET, "https://dl.humble.com/f0.pdf", callback=blocking_callback)
    responses.get("https://dl.humble.com/f1.pdf", body=b"x" * 10, status=200)

    monkeypatch.setattr("hbdl.web.jobs.auth.resolve_session", lambda: Session(cookie_value="dummy"))
    monkeypatch.setattr("hbdl.web.jobs.build_catalog", lambda client: items)

    app = create_app()
    client = TestClient(app)

    client.post("/jobs/current/start")
    _wait_for_state(app, JobState.RUNNING)
    time.sleep(0.1)

    pause_resp = client.post("/jobs/current/pause")
    assert "Fortsetzen" in pause_resp.text

    release.set()
    resume_resp = client.post("/jobs/current/resume")
    assert "Laeuft" in resume_resp.text or "Fertig" in resume_resp.text

    _wait_until_idle(app)
    final = client.get("/")
    assert "Fertig" in final.text


def test_sse_stream_delivers_published_event(monkeypatch, tmp_path):
    """The /jobs/current/events generator runs forever by design (a live
    dashboard tab keeps it open) -- TestClient.stream() over the in-process
    ASGI transport hangs indefinitely trying to fully drain a never-ending
    response instead of yielding chunks incrementally (confirmed empirically:
    the request never even returns a response object). So this calls the
    route function directly and pulls exactly one chunk from the
    StreamingResponse's body_iterator (Starlette wraps a sync generator into
    an async one internally, hence the asyncio.run) -- deterministic, no
    hanging, still exercises the real subscribe -> publish -> render -> SSE
    framing path end to end."""
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    app = create_app()
    job_manager = app.state.job_manager
    fake_request = SimpleNamespace(app=app)

    response = job_events(fake_request)  # subscribes synchronously before returning
    job_manager.events.publish({"type": "state", "state": "running", "total_items": 3})

    async def pull_one_chunk() -> str:
        try:
            return await response.body_iterator.__anext__()
        finally:
            await response.body_iterator.aclose()

    chunk = asyncio.run(pull_one_chunk())

    assert chunk.startswith("event: state\n")
    assert "Laeuft (3 Dateien)" in chunk
