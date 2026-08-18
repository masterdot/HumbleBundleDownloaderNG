"""FastAPI application factory for `hbdl web serve`.

See CONCEPT_WEB.md section 1 for the overall web-layer architecture. Kept as
a separate optional subpackage (imported lazily from cli.py) so `pip install
hbdl` without the `web` extra never pulls in FastAPI/uvicorn/jinja2.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from hbdl import i18n
from hbdl.state import open_store
from hbdl.web.jobs import JobManager
from hbdl.web.login_state import LoginState
from hbdl.web.routers import auth_web, dashboard, library, settings, vnc_proxy

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="hbdl")
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.templates.env.globals["t"] = i18n.t
    app.state.templates.env.globals["lang"] = i18n.get_lang
    # One JobManager per process (see CONCEPT_WEB.md M11) -- created fresh per
    # create_app() call, which is also what keeps tests (each building their
    # own app via TestClient(create_app())) isolated from one another.
    app.state.job_manager = JobManager()
    # One LoginState per process (M13) -- same reasoning as job_manager above.
    app.state.login_state = LoginState()
    # One-time cleanup of any `downloading` rows orphaned by a previous
    # process dying mid-transfer (M12, CONCEPT_WEB.md) -- cosmetic only.
    with open_store() as store:
        store.reconcile_stale_downloading()
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(dashboard.router)
    app.include_router(settings.router)
    app.include_router(library.router)
    app.include_router(auth_web.router)
    app.include_router(vnc_proxy.router)
    return app
