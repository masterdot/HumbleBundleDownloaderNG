"""M13: VNC-based guided login (start/poll) plus the manual cookie-paste
fallback -- both rendered on the settings page (_login_area.html). See
web/login_state.py for the guided-login side."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request

from hbdl import auth, config
from hbdl.web.login_state import LoginState, LoginStatus

router = APIRouter(prefix="/auth")


def _login_context(login_state: LoginState) -> dict:
    snap = login_state.snapshot()
    if snap.status == LoginStatus.RUNNING:
        return {"login_status": "running", "login_error": None}
    # Whenever no login is actively in progress, a session on disk always
    # means "success" -- regardless of what this LoginState instance's own
    # last attempt recorded. Without the SESSION_FILE.exists() check, a
    # failed *previous* attempt (VNC timeout, wrong captcha, whatever)
    # permanently pinned the UI on "failed" even after a valid session showed
    # up some other way afterwards (CLI login on the host, cookie-paste, a
    # session.json dropped in by hand) -- confirmed hitting this in practice.
    # See CONCEPT_WEB.md's M13 clipboard/login entries.
    if snap.status == LoginStatus.SUCCESS or config.SESSION_FILE.exists():
        return {"login_status": "success", "login_error": None}
    if snap.status == LoginStatus.ERROR:
        return {"login_status": "error", "login_error": snap.error}
    return {"login_status": "idle", "login_error": None}


@router.post("/login/start")
def login_start(request: Request):
    templates = request.app.state.templates
    login_state: LoginState = request.app.state.login_state
    try:
        login_state.start()
    except RuntimeError:
        pass
    # The "Login im Browser starten" button lives inside #vnc-login-inner
    # (see _login_area.html's collapsible VNC section) and swaps only that,
    # not the whole #login-area -- so the response has to match that scope.
    return templates.TemplateResponse(request, "_vnc_login_inner.html", _login_context(login_state))


@router.get("/login/status")
def login_status(request: Request):
    templates = request.app.state.templates
    login_state: LoginState = request.app.state.login_state
    # _login_status_response.html: while still "running", re-arm only the
    # small poll div (leaves the VNC iframe alone -- swapping the whole
    # #login-area every 2s tore the iframe down and reconnected it every poll
    # tick, which looked like constant refresh/disconnects and made the
    # embedded login page unusable). Once terminal, it out-of-band-replaces
    # #login-area via the oob=True flag below.
    context = {**_login_context(login_state), "oob": True}
    return templates.TemplateResponse(request, "_login_status_response.html", context)


@router.post("/cookie")
def save_manual_cookie(request: Request, cookie: str = Form(...)):
    templates = request.app.state.templates
    login_state: LoginState = request.app.state.login_state
    value = cookie.strip()
    if value:
        auth.save_manual_cookie(value)
    return templates.TemplateResponse(request, "_login_area.html", _login_context(login_state))
