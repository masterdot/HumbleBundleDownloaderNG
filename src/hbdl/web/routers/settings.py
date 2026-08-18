"""M9 scope: settings form backed by the same config.Config.save() the CLI's
`hbdl config set` uses -- single source of truth, no duplicated serialization.
M13: the login area (VNC iframe start/poll, cookie-paste) embedded on this
same page -- see web/routers/auth_web.py for its own routes/context."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request

from hbdl import config, i18n
from hbdl.downloader.strategy import STRATEGIES
from hbdl.web.login_state import LoginState
from hbdl.web.routers.auth_web import _login_context

router = APIRouter()


def _context(cfg: config.Config, login_state: LoginState, error: str | None = None, saved: bool = False) -> dict:
    return {
        "dest": str(cfg.dest),
        "workers": cfg.workers,
        "strategy": cfg.strategy,
        "cookie_file": str(cfg.cookie_file) if cfg.cookie_file else "",
        "strategies": STRATEGIES,
        "error": error,
        "saved": saved,
        **_login_context(login_state),
    }


@router.get("/settings")
def settings_form(request: Request):
    templates = request.app.state.templates
    cfg = config.Config.load()
    return templates.TemplateResponse(request, "settings.html", _context(cfg, request.app.state.login_state))


@router.get("/settings/about")
def settings_about(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "about.html", {})


@router.post("/settings")
def settings_save(
    request: Request,
    dest: str = Form(...),
    workers: int = Form(...),
    strategy: str = Form(...),
    cookie_file: str = Form(""),
):
    templates = request.app.state.templates
    login_state: LoginState = request.app.state.login_state

    if strategy not in STRATEGIES:
        cfg = config.Config.load()
        error = i18n.t("error.unknown_strategy", value=strategy, allowed=", ".join(STRATEGIES))
        return templates.TemplateResponse(
            request, "settings.html", _context(cfg, login_state, error=error), status_code=422
        )

    if workers < 1:
        cfg = config.Config.load()
        return templates.TemplateResponse(
            request,
            "settings.html",
            _context(cfg, login_state, error=i18n.t("error.workers_min")),
            status_code=422,
        )

    cfg = config.Config.load()
    cfg.dest = Path(dest).expanduser()
    cfg.workers = workers
    cfg.strategy = strategy
    cfg.cookie_file = Path(cookie_file).expanduser() if cookie_file.strip() else None
    cfg.save()

    return templates.TemplateResponse(request, "settings.html", _context(cfg, login_state, saved=True))
