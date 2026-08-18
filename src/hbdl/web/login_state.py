"""Background state for the guided Playwright login triggered from the
settings page (M13: VNC-based auth in Docker, see CONCEPT_WEB.md). Deliberately
separate from JobManager -- this is a one-shot, short-lived, single-purpose
action (log in once, capture a cookie), not a queue/progress state machine.

guided_login() itself needs zero code changes for this to work: it already
just launches Playwright with headless=False, which renders onto whatever
DISPLAY is set for the process -- inside the Docker image that's Xvfb's :99,
wired up via supervisord (docker/supervisord.conf), exposed to the browser
through noVNC (internally on port 6080, reverse-proxied same-origin under
/vnc -- see web/routers/vnc_proxy.py). This module only needs to run
guided_login() off the request thread, since it blocks for up to 5 minutes
waiting for the human to complete login/captcha/2FA."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum

from hbdl import auth


class LoginStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


@dataclass(slots=True)
class LoginSnapshot:
    status: LoginStatus = LoginStatus.IDLE
    error: str | None = None


class LoginState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = LoginSnapshot()
        self._thread: threading.Thread | None = None

    def snapshot(self) -> LoginSnapshot:
        with self._lock:
            return LoginSnapshot(status=self._snapshot.status, error=self._snapshot.error)

    def start(self) -> None:
        with self._lock:
            if self._snapshot.status == LoginStatus.RUNNING:
                raise RuntimeError("Login laeuft bereits.")
            self._snapshot = LoginSnapshot(status=LoginStatus.RUNNING)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            auth.guided_login(headless=False)
            with self._lock:
                self._snapshot = LoginSnapshot(status=LoginStatus.SUCCESS)
        except auth.AuthError as exc:
            with self._lock:
                self._snapshot = LoginSnapshot(status=LoginStatus.ERROR, error=str(exc))
        except Exception as exc:  # noqa: BLE001 -- surfaced to the UI, not swallowed
            with self._lock:
                self._snapshot = LoginSnapshot(status=LoginStatus.ERROR, error=str(exc))
