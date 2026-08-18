"""M13 Nachtrag: same-origin reverse proxy for noVNC (web/routers/vnc_proxy.py).
Runs against a plain local HTTP server and a local websockets echo server --
no real websockify/noVNC involved, see CONCEPT_WEB.md for why that layer
stays out of automated tests."""

from __future__ import annotations

import asyncio
import http.server
import threading

import pytest
import websockets
from fastapi.testclient import TestClient

from hbdl.web.app import create_app
from hbdl.web.routers import vnc_proxy


class _EchoPathHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(f"path={self.path}".encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def http_upstream(monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _EchoPathHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    monkeypatch.setattr(vnc_proxy, "_UPSTREAM_HTTP", f"http://127.0.0.1:{port}")
    yield
    server.shutdown()
    thread.join(timeout=5)


def test_http_proxy_passes_through_path_and_query(http_upstream):
    client = TestClient(create_app())

    resp = client.get("/vnc/hbdl-vnc.html?path=websockify&autoconnect=true")

    assert resp.status_code == 200
    assert resp.text == "path=/hbdl-vnc.html?path=websockify&autoconnect=true"


@pytest.fixture
def ws_upstream(monkeypatch):
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    state: dict = {}

    async def echo(websocket):
        async for message in websocket:
            await websocket.send(message)

    def run():
        asyncio.set_event_loop(loop)

        async def start():
            server = await websockets.serve(echo, "127.0.0.1", 0)
            state["server"] = server
            state["port"] = server.sockets[0].getsockname()[1]
            ready.set()

        loop.run_until_complete(start())
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(timeout=5)
    monkeypatch.setattr(vnc_proxy, "_UPSTREAM_WS", f"ws://127.0.0.1:{state['port']}")

    yield

    async def stop():
        state["server"].close()
        await state["server"].wait_closed()

    asyncio.run_coroutine_threadsafe(stop(), loop).result(timeout=5)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)


def test_websocket_proxy_relays_frames_in_both_directions(ws_upstream):
    client = TestClient(create_app())

    with client.websocket_connect("/vnc/websockify") as ws:
        ws.send_bytes(b"hello-vnc")
        assert ws.receive_bytes() == b"hello-vnc"

        ws.send_bytes(b"second-frame")
        assert ws.receive_bytes() == b"second-frame"
