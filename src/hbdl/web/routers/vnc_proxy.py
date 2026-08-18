"""Same-origin reverse proxy for noVNC (M13 Nachtrag, see CONCEPT_WEB.md).

Serves noVNC's static assets and relays its WebSocket (RFB) connection
through this same FastAPI app on port 8000, instead of the separate port
6080 websockify was previously exposed on directly. This puts the embedded
VNC iframe on the same origin as the rest of the UI -- the earlier
cross-origin setup is what silently blocked the Clipboard API from working
inside the login window. See CONCEPT_WEB.md's dated entry for the full
diagnosis and the three failed cross-origin workarounds that preceded this.

websockify keeps listening on 127.0.0.1:6080 inside the container; that port
is no longer published to the host (docker-compose.yml) -- only this proxy
is reachable from outside.

The WebSocket relay below is the one deliberate async exception in this
otherwise fully-synchronous codebase (CONCEPT.md section 11 explains why
`requests` is used over `httpx` elsewhere) -- WebSocket proxying is
inherently an async concern in Starlette, kept scoped to this single route.
"""

from __future__ import annotations

import asyncio

import requests
import websockets
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from websockets.exceptions import ConnectionClosed

router = APIRouter(prefix="/vnc")

_UPSTREAM_HTTP = "http://127.0.0.1:6080"
_UPSTREAM_WS = "ws://127.0.0.1:6080/websockify"

# Hop-by-hop headers that must not be copied through a proxy (RFC 7230 6.1) --
# in particular content-length/content-encoding, which can go stale once
# `requests` has already transparently decoded the upstream response body.
_EXCLUDED_RESPONSE_HEADERS = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "content-encoding",
    "content-length",
}


@router.api_route("/{path:path}", methods=["GET"])
def proxy_http(path: str, request: Request) -> Response:
    url = f"{_UPSTREAM_HTTP}/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    upstream = requests.get(url, timeout=10)
    headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in _EXCLUDED_RESPONSE_HEADERS
    }
    return Response(content=upstream.content, status_code=upstream.status_code, headers=headers)


@router.websocket("/websockify")
async def proxy_websocket(websocket: WebSocket) -> None:
    # noVNC connects with no Sec-WebSocket-Protocol (confirmed by reading
    # app/ui.js's `new RFB(...)` call, which passes no wsProtocols option) --
    # nothing to negotiate on either leg of the relay.
    await websocket.accept()

    async with websockets.connect(_UPSTREAM_WS) as upstream:

        async def client_to_upstream() -> None:
            try:
                while True:
                    message = await websocket.receive_bytes()
                    await upstream.send(message)
            except (WebSocketDisconnect, ConnectionClosed):
                pass

        async def upstream_to_client() -> None:
            try:
                async for message in upstream:
                    await websocket.send_bytes(message)
            except (WebSocketDisconnect, ConnectionClosed):
                pass

        tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
