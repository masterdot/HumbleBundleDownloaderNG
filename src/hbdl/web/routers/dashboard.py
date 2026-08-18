"""M8: status page proving the config/data/library volume story works
end-to-end. M11: job control (start) + a live SSE progress stream on top of
it -- see web/jobs.py::JobManager (the state machine + background thread) and
web/events.py::EventBus (the pub/sub this streams from). M12: pause/resume/
stop routes on top of the same JobManager methods."""

from __future__ import annotations

import queue

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from hbdl import config
from hbdl.web.jobs import JobManager, JobSnapshot

router = APIRouter()


def _state_context(snap: JobSnapshot) -> dict:
    return {"state": snap.state.value, "total_items": snap.total_items, "error": snap.error}


@router.get("/")
def index(request: Request):
    templates = request.app.state.templates
    job_manager: JobManager = request.app.state.job_manager
    context = {
        "config_dir": str(config.CONFIG_DIR),
        "data_dir": str(config.DATA_DIR),
        "dest": str(config.resolve_dest()),
        "session_exists": config.SESSION_FILE.exists(),
        **_state_context(job_manager.snapshot()),
    }
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


def _control_and_render(request: Request, action: str):
    """Shared body for the start/pause/resume/stop routes: call the
    JobManager method, tolerate it refusing (wrong state for that action --
    e.g. a stale "Pause" click after the job already finished), and always
    re-render the current (possibly unchanged) state so the caller never gets
    a 500 for a harmless race between a button click and the job's own
    progress."""
    templates = request.app.state.templates
    job_manager: JobManager = request.app.state.job_manager
    try:
        getattr(job_manager, action)()
    except RuntimeError:
        pass
    return templates.TemplateResponse(request, "_sse_state.html", _state_context(job_manager.snapshot()))


@router.post("/jobs/current/start")
def start_job(request: Request):
    return _control_and_render(request, "start")


@router.post("/jobs/current/pause")
def pause_job(request: Request):
    return _control_and_render(request, "pause")


@router.post("/jobs/current/resume")
def resume_job(request: Request):
    return _control_and_render(request, "resume")


@router.post("/jobs/current/stop")
def stop_job(request: Request):
    return _control_and_render(request, "stop")


def _render_event(templates, request: Request, event: dict) -> str:
    if event["type"] == "state":
        return templates.get_template("_sse_state.html").render(
            request=request,
            state=event.get("state"),
            total_items=event.get("total_items", 0),
            error=event.get("error"),
        )
    if event["type"] == "item_done":
        return templates.get_template("_sse_item.html").render(
            request=request,
            human_name=event.get("human_name"),
            filename=event.get("filename"),
            ok=event.get("ok"),
            error=event.get("error"),
        )
    if event["type"] == "bytes":
        return templates.get_template("_sse_bytes.html").render(
            request=request, done=event.get("done", 0), total=event.get("total", 0)
        )
    return ""  # pragma: no cover -- unknown event types are dropped, not fatal


def _sse_frame(event_name: str, html: str) -> str:
    # SSE framing: multi-line payloads need one "data: " prefix per line.
    data_lines = "\n".join(f"data: {line}" for line in html.splitlines()) or "data: "
    return f"event: {event_name}\n{data_lines}\n\n"


@router.get("/jobs/current/events")
def job_events(request: Request):
    templates = request.app.state.templates
    job_manager: JobManager = request.app.state.job_manager
    subscription = job_manager.events.subscribe()

    def stream():
        try:
            while True:
                try:
                    event = subscription.get(timeout=15)
                except queue.Empty:
                    yield ": heartbeat\n\n"  # keep idle connections/proxies alive
                    continue
                yield _sse_frame(event["type"], _render_event(templates, request, event))
        finally:
            job_manager.events.unsubscribe(subscription)

    return StreamingResponse(stream(), media_type="text/event-stream")
