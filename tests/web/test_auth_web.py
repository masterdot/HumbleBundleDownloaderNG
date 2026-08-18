"""M13: VNC-based guided login (start/poll) and the cookie-paste fallback.
auth.guided_login is mocked entirely -- it launches a real Playwright/Xvfb
browser, which doesn't run in CI/dev sandboxes; see CONCEPT_WEB.md's note that
the actual Xvfb/x11vnc/noVNC/supervisord layer and real captcha behavior are
explicitly out of scope for automated tests."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from hbdl import auth, config
from hbdl.web.app import create_app
from hbdl.web.login_state import LoginState, LoginStatus


def _wait_for_status(login_state: LoginState, status: LoginStatus, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while login_state.snapshot().status != status and time.time() < deadline:
        time.sleep(0.02)


def test_login_state_start_success(monkeypatch):
    monkeypatch.setattr("hbdl.web.login_state.auth.guided_login", lambda headless=False: None)
    state = LoginState()

    state.start()
    _wait_for_status(state, LoginStatus.SUCCESS)

    assert state.snapshot().status == LoginStatus.SUCCESS


def test_login_state_start_captures_auth_error(monkeypatch):
    def raise_auth_error(headless=False):
        raise auth.AuthError("Login-Fenster nicht abgeschlossen")

    monkeypatch.setattr("hbdl.web.login_state.auth.guided_login", raise_auth_error)
    state = LoginState()

    state.start()
    _wait_for_status(state, LoginStatus.ERROR)

    snap = state.snapshot()
    assert snap.status == LoginStatus.ERROR
    assert "Login-Fenster" in snap.error


def test_login_state_rejects_concurrent_start(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_login(headless=False):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr("hbdl.web.login_state.auth.guided_login", blocking_login)
    state = LoginState()

    state.start()
    assert started.wait(timeout=5)

    with pytest.raises(RuntimeError):
        state.start()

    release.set()
    _wait_for_status(state, LoginStatus.SUCCESS)


def test_settings_page_shows_login_start_button_when_idle(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSION_FILE", tmp_path / "no-session.json")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "no-config.toml")
    client = TestClient(create_app())

    resp = client.get("/settings")

    assert resp.status_code == 200
    assert "Login im Browser starten" in resp.text


def test_settings_page_shows_success_when_session_file_exists(monkeypatch, tmp_path):
    session_file = tmp_path / "session.json"
    session_file.write_text('{"cookie": "abc"}', encoding="utf-8")
    monkeypatch.setattr(config, "SESSION_FILE", session_file)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "no-config.toml")
    client = TestClient(create_app())

    resp = client.get("/settings")

    assert "Login vorhanden" in resp.text


def test_login_start_route_returns_vnc_iframe_fragment(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSION_FILE", tmp_path / "no-session.json")
    started = threading.Event()
    release = threading.Event()

    def blocking_login(headless=False):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr("hbdl.web.login_state.auth.guided_login", blocking_login)
    app = create_app()
    client = TestClient(app)

    resp = client.post("/auth/login/start")
    started.wait(timeout=5)

    assert resp.status_code == 200
    assert "vnc-frame" in resp.text
    # hbdl-vnc.html, not noVNC's stock vnc.html -- the clipboard-autopaste
    # clone, see docker/novnc-clipboard-autopaste.js. Served same-origin
    # through the /vnc reverse proxy (web/routers/vnc_proxy.py), not the old
    # separate :6080 origin -- see CONCEPT_WEB.md's same-origin fix entry.
    assert '/vnc/hbdl-vnc.html?path=websockify' in resp.text

    release.set()
    _wait_for_status(app.state.login_state, LoginStatus.SUCCESS)


def test_login_start_twice_does_not_error(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSION_FILE", tmp_path / "no-session.json")
    started = threading.Event()
    release = threading.Event()

    def blocking_login(headless=False):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr("hbdl.web.login_state.auth.guided_login", blocking_login)
    app = create_app()
    client = TestClient(app)

    first = client.post("/auth/login/start")
    started.wait(timeout=5)
    second = client.post("/auth/login/start")

    assert first.status_code == 200
    assert second.status_code == 200

    release.set()
    _wait_for_status(app.state.login_state, LoginStatus.SUCCESS)


def test_login_status_route_reflects_error(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSION_FILE", tmp_path / "no-session.json")

    def raise_auth_error(headless=False):
        raise auth.AuthError("Kein Cookie gefunden")

    monkeypatch.setattr("hbdl.web.login_state.auth.guided_login", raise_auth_error)
    app = create_app()
    client = TestClient(app)

    client.post("/auth/login/start")
    _wait_for_status(app.state.login_state, LoginStatus.ERROR)

    resp = client.get("/auth/login/status")
    assert "Kein Cookie gefunden" in resp.text


def test_a_session_file_appearing_after_a_failed_attempt_overrides_the_stale_error(monkeypatch, tmp_path):
    """Regression test for a real bug: a failed VNC login attempt used to
    permanently pin the UI on "failed", even after a valid session showed up
    some other way afterwards (CLI login on the host sharing the same config
    volume, cookie-paste, a session.json dropped in by hand). The on-disk
    session file must win over a stale in-memory error once no login is
    actively running."""
    session_file = tmp_path / "session.json"
    monkeypatch.setattr(config, "SESSION_FILE", session_file)

    def raise_auth_error(headless=False):
        raise auth.AuthError("Login-Fenster wurde geschlossen")

    monkeypatch.setattr("hbdl.web.login_state.auth.guided_login", raise_auth_error)
    app = create_app()
    client = TestClient(app)

    client.post("/auth/login/start")
    _wait_for_status(app.state.login_state, LoginStatus.ERROR)
    assert "Login-Fenster wurde geschlossen" in client.get("/settings").text

    # A session shows up some other way (e.g. `hbdl auth login` run locally,
    # writing into the same shared config volume) -- the LoginState itself
    # never re-ran, it's still recording the earlier ERROR.
    session_file.write_text('{"cookie": "abc"}', encoding="utf-8")

    resp = client.get("/settings")
    assert "Login vorhanden" in resp.text
    assert "Login-Fenster wurde geschlossen" not in resp.text


def test_login_status_while_running_does_not_recreate_the_vnc_iframe(monkeypatch, tmp_path):
    """Regression test for a real bug: polling used to swap the *entire*
    #login-area (including the iframe) every 2s, tearing down and
    reconnecting the VNC session on every poll tick -- looked like constant
    refresh/disconnects and made the embedded login page unusable for typing.
    The status-poll response while still running must only re-arm the small
    poll div, never touch/recreate the iframe."""
    monkeypatch.setattr(config, "SESSION_FILE", tmp_path / "no-session.json")
    started = threading.Event()
    release = threading.Event()

    def blocking_login(headless=False):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr("hbdl.web.login_state.auth.guided_login", blocking_login)
    app = create_app()
    client = TestClient(app)

    client.post("/auth/login/start")
    started.wait(timeout=5)

    resp = client.get("/auth/login/status")

    assert "vnc-frame" not in resp.text
    assert 'id="login-status-poll"' in resp.text
    assert 'hx-trigger="every 2s"' in resp.text

    release.set()
    _wait_for_status(app.state.login_state, LoginStatus.SUCCESS)


def test_login_status_on_success_replaces_login_area_out_of_band(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSION_FILE", tmp_path / "no-session.json")
    monkeypatch.setattr("hbdl.web.login_state.auth.guided_login", lambda headless=False: None)
    app = create_app()
    client = TestClient(app)

    client.post("/auth/login/start")
    _wait_for_status(app.state.login_state, LoginStatus.SUCCESS)

    resp = client.get("/auth/login/status")

    assert 'hx-swap-oob="true"' in resp.text
    assert "Login vorhanden" in resp.text
    assert "vnc-frame" not in resp.text


def test_cookie_paste_saves_session_and_settings_reflects_it(monkeypatch, tmp_path):
    session_file = tmp_path / "session.json"
    monkeypatch.setattr(config, "SESSION_FILE", session_file)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "no-config.toml")
    client = TestClient(create_app())

    resp = client.post("/auth/cookie", data={"cookie": "  raw-cookie-value  "})

    assert resp.status_code == 200
    assert "Login vorhanden" in resp.text
    assert session_file.exists()
    assert "raw-cookie-value" in session_file.read_text(encoding="utf-8")


def test_cookie_paste_with_blank_value_does_not_save(monkeypatch, tmp_path):
    session_file = tmp_path / "session.json"
    monkeypatch.setattr(config, "SESSION_FILE", session_file)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "no-config.toml")
    client = TestClient(create_app())

    resp = client.post("/auth/cookie", data={"cookie": "   "})

    assert resp.status_code == 200
    assert not session_file.exists()
