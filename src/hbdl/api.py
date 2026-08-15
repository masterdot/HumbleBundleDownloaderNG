"""Thin wrapper around the two Humble Bundle JSON endpoints we need.

See CONCEPT.md section 5 (Discovery-Flow) for the endpoint contract.
"""

from __future__ import annotations

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from hbdl.auth import BASE_URL, Session

_RETRYABLE = (requests.ConnectionError, requests.Timeout)


class ApiError(RuntimeError):
    pass


def _retrying():
    return retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=0.5, max=16),
        reraise=True,
    )


class Client:
    def __init__(self, session: Session, timeout: float = 30.0):
        self._http = session.build_http_session()
        self._timeout = timeout

    @_retrying()
    def _get(self, path: str) -> requests.Response:
        resp = self._http.get(f"{BASE_URL}{path}", timeout=self._timeout)
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            raise ApiError(f"Rate-limited (429), Retry-After={retry_after}")
        resp.raise_for_status()
        return resp

    def list_gamekeys(self) -> list[str]:
        resp = self._get("/api/v1/user/order")
        return [entry["gamekey"] for entry in resp.json()]

    def order_detail(self, gamekey: str) -> dict:
        resp = self._get(f"/api/v1/order/{gamekey}")
        return resp.json()
