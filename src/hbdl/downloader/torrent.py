"""BitTorrent path, v1: fetch and save the .torrent file only.

See CONCEPT.md section 7. `item.torrent_url` (when present) points to a small
.torrent metadata file, not a magnet link and not the game content itself —
this module downloads just that small file so the user can open it with their
own torrent client. Real client handoff (v1.5) and an embedded libtorrent
engine (v2) are explicitly out of scope here.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from hbdl.downloader.common import BLOCK_STATUS_CODES, CircuitBreaker
from hbdl.models import DownloadItem
from hbdl.state import STATUS_FAILED, STATUS_VERIFIED, StateStore

MAX_ATTEMPTS = 3


def torrent_dest_path(item: DownloadItem, dest_root: Path) -> Path:
    base = item.dest_path(dest_root)
    return base.with_name(base.name + ".torrent")


def torrent_identity_key(item: DownloadItem) -> str:
    return f"{item.identity_key}::torrent"


def download_torrent_file(
    http: requests.Session,
    item: DownloadItem,
    dest_root: Path,
    store: StateStore,
    breaker: CircuitBreaker | None = None,
):
    from hbdl.downloader.direct import DownloadResult  # local import avoids a cycle

    if not item.torrent_url:
        return DownloadResult(item=item, ok=False, error="keine Torrent-URL vorhanden")

    dest_path = torrent_dest_path(item, dest_root)
    identity_key = torrent_identity_key(item)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if store.is_verified(identity_key) and dest_path.exists():
        return DownloadResult(item=item, ok=True, skipped=True)

    if breaker and breaker.tripped.is_set():
        return DownloadResult(item=item, ok=False, error="uebersprungen: Circuit Breaker ausgeloest (zu viele 403/429)")

    last_error: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = http.get(item.torrent_url, timeout=30)
            if resp.status_code in BLOCK_STATUS_CODES:
                if breaker:
                    breaker.record_block()
                raise requests.HTTPError(f"blocked (status={resp.status_code})")
            resp.raise_for_status()
            dest_path.write_bytes(resp.content)
            store.upsert(
                identity_key,
                status=STATUS_VERIFIED,
                dest_path=str(dest_path),
                file_size=len(resp.content),
                last_attempt_at=datetime.now(timezone.utc).isoformat(),
                last_error=None,
            )
            return DownloadResult(item=item, ok=True)
        except (requests.RequestException, OSError) as exc:
            last_error = str(exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(0.5 * (2 ** (attempt - 1)), 8))

    store.upsert(
        identity_key,
        status=STATUS_FAILED,
        dest_path=str(dest_path),
        last_attempt_at=datetime.now(timezone.utc).isoformat(),
        last_error=last_error,
    )
    return DownloadResult(item=item, ok=False, error=last_error)
