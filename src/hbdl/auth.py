"""Authentication: guided Playwright login (primary) + manual cookie fallback.

See CONCEPT.md section 2 for the rationale: Humble Bundle gates /processlogin
behind reCAPTCHA, so we never submit credentials programmatically. Instead we
open a real, visible browser, let the human complete login (incl. captcha/2FA),
and lift the resulting session cookie out of the browser context.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
from dataclasses import dataclass
from pathlib import Path

import requests

from hbdl import config

SESSION_COOKIE_NAME = "_simpleauth_sess"
REQUIRED_HEADER = {"X-Requested-By": "hb_android_app"}
LOGIN_URL = "https://www.humblebundle.com/login"
BASE_URL = "https://www.humblebundle.com"
USER_AGENT = "hbdl/0.1 (+https://github.com/; python-requests)"


class AuthError(RuntimeError):
    """`message` stays German (used for logs and as the str(exc) fallback).
    `key`/`key_kwargs` let a display layer (cli.py, web/routers/library.py)
    look up a translated version via `i18n.t(exc.key, **exc.key_kwargs)`
    instead -- translation happens at the display boundary, not here, so
    this module never needs to import hbdl.i18n or care about the current
    language (see CONCEPT_WEB.md M14)."""

    def __init__(self, message: str, *, key: str | None = None, **key_kwargs: object) -> None:
        super().__init__(message)
        self.key = key
        self.key_kwargs = key_kwargs


@dataclass(slots=True)
class Session:
    cookie_value: str

    def build_http_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(REQUIRED_HEADER)
        s.headers["User-Agent"] = USER_AGENT
        s.cookies.set(SESSION_COOKIE_NAME, self.cookie_value, domain="www.humblebundle.com")
        s.cookies.set(SESSION_COOKIE_NAME, self.cookie_value, domain=".humblebundle.com")
        return s


def _save_session(cookie_value: str, path: Path | None = None) -> None:
    # `path`'s default is resolved here, not via a `path: Path =
    # config.SESSION_FILE` parameter default -- see the identical comment on
    # Config.load() in config.py: parameter defaults are bound once at
    # function-definition time and would be immune to monkeypatching
    # config.SESSION_FILE in tests (this function is called bare, with no
    # path, from guided_login() below).
    if path is None:
        path = config.SESSION_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cookie": cookie_value}), encoding="utf-8")
    os.chmod(path, 0o600)


def save_manual_cookie(cookie_value: str) -> None:
    """Public wrapper around _save_session for the web settings page's
    cookie-paste fallback (CONCEPT_WEB.md M13) -- faster than the VNC-based
    guided login if you already have the cookie from your own browser.
    Kept as a thin wrapper rather than having the web layer reach into the
    `_`-prefixed _save_session directly."""
    _save_session(cookie_value)


def _load_saved_session(path: Path | None = None) -> Session | None:
    if path is None:
        path = config.SESSION_FILE  # see the identical comment in _save_session()
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    cookie = data.get("cookie")
    return Session(cookie_value=cookie) if cookie else None


def _load_cookie_file(path: Path) -> str | None:
    """Parse a Netscape-format cookies.txt and pull out _simpleauth_sess."""
    jar = http.cookiejar.MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    for cookie in jar:
        if cookie.name == SESSION_COOKIE_NAME:
            return cookie.value
    return None


def guided_login(headless: bool = False) -> Session:
    """Open a real browser window, let the user log in manually, and lift the
    session cookie once we land on /home. Never touches the user's password."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise AuthError(
            "playwright ist nicht installiert. `pip install hbdl[dev]` bzw. "
            "`playwright install chromium` ausfuehren.",
            key="error.auth.playwright_missing",
        ) from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL)
        try:
            page.wait_for_url(f"{BASE_URL}/home*", timeout=5 * 60 * 1000)
        except Exception as exc:
            browser.close()
            raise AuthError(
                "Login-Fenster wurde geschlossen oder die Anmeldung wurde nicht "
                "innerhalb von 5 Minuten abgeschlossen.",
                key="error.auth.login_window_closed",
            ) from exc

        cookies = context.cookies("https://www.humblebundle.com")
        browser.close()

    for cookie in cookies:
        if cookie["name"] == SESSION_COOKIE_NAME:
            _save_session(cookie["value"])
            return Session(cookie_value=cookie["value"])

    raise AuthError(
        f"Login schien erfolgreich, aber der Cookie '{SESSION_COOKIE_NAME}' wurde nicht gefunden.",
        key="error.auth.cookie_not_found_after_login",
        cookie_name=SESSION_COOKIE_NAME,
    )


def resolve_session(
    cookie: str | None = None,
    cookie_file: Path | None = None,
) -> Session:
    """Resolution order: --cookie > --cookie-file > env vars > saved Playwright
    session > config file cookie_file. Raises AuthError if nothing is found."""
    if cookie:
        return Session(cookie_value=cookie)

    if cookie_file:
        value = _load_cookie_file(cookie_file)
        if value:
            return Session(cookie_value=value)
        raise AuthError(
            f"Kein '{SESSION_COOKIE_NAME}'-Cookie in {cookie_file} gefunden.",
            key="error.auth.cookie_not_in_file",
            cookie_name=SESSION_COOKIE_NAME,
            path=cookie_file,
        )

    if env_cookie := os.environ.get("HBDL_COOKIE"):
        return Session(cookie_value=env_cookie)

    if env_cookie_file := os.environ.get("HBDL_COOKIE_FILE"):
        value = _load_cookie_file(Path(env_cookie_file))
        if value:
            return Session(cookie_value=value)

    if saved := _load_saved_session():
        return saved

    cfg = config.Config.load()
    if cfg.cookie_file:
        value = _load_cookie_file(cfg.cookie_file)
        if value:
            return Session(cookie_value=value)

    raise AuthError(
        "Kein Login gefunden. Fuehre `hbdl auth login` aus, oder uebergib "
        "--cookie / --cookie-file / setze HBDL_COOKIE.",
        key="error.auth.no_login_found",
    )


def check_session(session: Session) -> dict:
    """Cheap validation call; raises AuthError on 401/403."""
    http_session = session.build_http_session()
    resp = http_session.get(f"{BASE_URL}/api/v1/user/order", timeout=15)
    if resp.status_code in (401, 403):
        raise AuthError(
            "Cookie ungueltig oder abgelaufen -- `hbdl auth login` erneut ausfuehren.",
            key="error.auth.cookie_invalid",
        )
    resp.raise_for_status()
    return {"order_count": len(resp.json())}
