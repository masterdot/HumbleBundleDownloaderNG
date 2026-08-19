"""M9 scope: settings form backed by the same config.Config.save() the CLI's
`hbdl config set` uses -- single source of truth, no duplicated serialization.
M13: the login area (VNC iframe start/poll, cookie-paste) embedded on this
same page -- see web/routers/auth_web.py for its own routes/context."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

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
        "current_lang": cfg.lang,
        "languages": config.LANGUAGES,
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
    lang: str = Form(...),
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

    if lang not in config.LANGUAGES:
        cfg = config.Config.load()
        error = i18n.t("cli.config.unknown_lang", value=lang, allowed=", ".join(config.LANGUAGES))
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
    cfg.lang = lang
    cfg.cookie_file = Path(cookie_file).expanduser() if cookie_file.strip() else None
    cfg.save()
    i18n.set_lang(lang)

    return templates.TemplateResponse(request, "settings.html", _context(cfg, login_state, saved=True))


@router.post("/settings/lang")
def settings_set_lang(request: Request, lang: str = Form(...)):
    """Quick DE/EN toggle in the topbar -- separate from the full settings
    form above so switching language doesn't require visiting /settings.
    Full page reload (no hx-* attributes on the form), since a partial
    htmx swap would leave the rest of the page's copy in the old language."""
    if lang in config.LANGUAGES:
        cfg = config.Config.load()
        cfg.lang = lang
        cfg.save()
        i18n.set_lang(lang)
    referer = request.headers.get("referer", "/")
    return RedirectResponse(referer, status_code=303)
