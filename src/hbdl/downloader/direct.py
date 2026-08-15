"""Direct HTTP download queue: resumable, retried, hash-verified, idempotent.

See CONCEPT.md section 6.
"""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import requests

from hbdl.api import Client
from hbdl.catalog import refresh_item_url
from hbdl.downloader.common import BLOCK_STATUS_CODES, CircuitBreaker
from hbdl.downloader.strategy import select_strategy
from hbdl.downloader.torrent import download_torrent_file
from hbdl.models import DownloadItem
from hbdl.progress import ProgressReporter
from hbdl.state import STATUS_FAILED, STATUS_VERIFIED, StateStore

CHUNK_SIZE = 1024 * 1024  # 1 MiB
MAX_ATTEMPTS = 5
URL_STALE_AFTER = timedelta(minutes=10)


@dataclass(slots=True)
class DownloadResult:
    item: DownloadItem
    ok: bool
    skipped: bool = False
    error: str | None = None


@dataclass(slots=True)
class DownloadReport:
    results: list[DownloadResult] = field(default_factory=list)
    circuit_breaker_tripped: bool = False

    @property
    def succeeded(self) -> list[DownloadResult]:
        return [r for r in self.results if r.ok and not r.skipped]

    @property
    def skipped(self) -> list[DownloadResult]:
        return [r for r in self.results if r.skipped]

    @property
    def failed(self) -> list[DownloadResult]:
        return [r for r in self.results if not r.ok]


def _hash_file(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _fresh_url(client: Client, item: DownloadItem) -> DownloadItem:
    if datetime.now(timezone.utc) - item.url_fetched_at > URL_STALE_AFTER:
        return refresh_item_url(client, item)
    return item


def _download_one(
    client: Client,
    http: requests.Session,
    item: DownloadItem,
    dest_root: Path,
    store: StateStore,
    progress: ProgressReporter | None,
    breaker: CircuitBreaker | None = None,
) -> DownloadResult:
    dest_path = item.dest_path(dest_root)
    part_path = dest_path.with_suffix(dest_path.suffix + ".part")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if store.is_verified(item.identity_key) and dest_path.exists() and dest_path.stat().st_size == item.file_size:
        if progress:
            progress.advance(item.file_size)
        return DownloadResult(item=item, ok=True, skipped=True)

    if breaker and breaker.tripped.is_set():
        return DownloadResult(item=item, ok=False, error="uebersprungen: Circuit Breaker ausgeloest (zu viele 403/429)")

    current_item = item
    last_error: str | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if breaker and breaker.tripped.is_set():
            last_error = "Circuit Breaker ausgeloest waehrend Retry-Wartezeit"
            break
        try:
            current_item = _fresh_url(client, current_item)
            existing = part_path.stat().st_size if part_path.exists() else 0
            headers = {"Range": f"bytes={existing}-"} if existing else {}
            with http.get(current_item.url, headers=headers, stream=True, timeout=60) as resp:
                if resp.status_code in BLOCK_STATUS_CODES:
                    if breaker:
                        breaker.record_block()
                    if resp.status_code == 403:
                        # signature likely expired mid-run: force a refresh and retry once
                        current_item = refresh_item_url(client, current_item)
                    else:
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            time.sleep(min(int(retry_after), 60))
                    raise requests.HTTPError(f"blocked (status={resp.status_code})")
                if existing and resp.status_code != 206:
                    part_path.unlink(missing_ok=True)
                    existing = 0
                resp.raise_for_status()

                mode = "ab" if existing and resp.status_code == 206 else "wb"
                with part_path.open(mode) as fh:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        if progress:
                            progress.advance(len(chunk))

            hash_info = current_item.preferred_hash
            if hash_info:
                algo, expected = hash_info
                actual = _hash_file(part_path, algo)
                if actual.lower() != expected.lower():
                    part_path.unlink(missing_ok=True)
                    raise ValueError(f"hash mismatch: expected {algo}={expected}, got {actual}")

            part_path.replace(dest_path)
            store.upsert(
                item.identity_key,
                status=STATUS_VERIFIED,
                dest_path=str(dest_path),
                file_size=item.file_size,
                hash_algo=hash_info[0] if hash_info else None,
                hash_value=hash_info[1] if hash_info else None,
                last_attempt_at=datetime.now(timezone.utc).isoformat(),
                last_error=None,
            )
            return DownloadResult(item=item, ok=True)

        except (requests.RequestException, ValueError, OSError) as exc:
            last_error = str(exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(0.5 * (2 ** (attempt - 1)), 16))
                continue

    store.upsert(
        item.identity_key,
        status=STATUS_FAILED,
        dest_path=str(dest_path),
        last_attempt_at=datetime.now(timezone.utc).isoformat(),
        last_error=last_error,
    )
    return DownloadResult(item=item, ok=False, error=last_error)


def download_all(
    client: Client,
    items: list[DownloadItem],
    dest_root: Path,
    store: StateStore,
    workers: int = 3,
    show_progress: bool = True,
    on_result: Callable[[DownloadResult], None] | None = None,
    circuit_breaker_threshold: int = 5,
    strategy: str = "direct",
) -> DownloadReport:
    """Downloads `items`. Each item's strategy is resolved individually via
    `select_strategy` (CONCEPT.md section 8) -- torrent items only fetch the
    small .torrent file (v1, see downloader/torrent.py) and are excluded from
    the byte-progress total, which tracks direct-download bytes only."""
    http = client.http_session
    report = DownloadReport()
    breaker = CircuitBreaker(threshold=circuit_breaker_threshold)

    resolved = [(item, select_strategy(item, strategy)) for item in items]
    direct_items = [item for item, kind in resolved if kind == "direct"]
    torrent_items = [item for item, kind in resolved if kind == "torrent"]
    total_bytes = sum(i.file_size for i in direct_items)

    progress_ctx = ProgressReporter(total_bytes, disable=not show_progress)
    with progress_ctx as progress, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_download_one, client, http, item, dest_root, store, progress, breaker): item
            for item in direct_items
        }
        futures.update(
            {
                pool.submit(download_torrent_file, http, item, dest_root, store, breaker): item
                for item in torrent_items
            }
        )
        for future in as_completed(futures):
            result = future.result()
            report.results.append(result)
            if on_result:
                on_result(result)

    report.circuit_breaker_tripped = breaker.tripped.is_set()
    return report


def verify_only(items: list[DownloadItem], dest_root: Path, store: StateStore) -> DownloadReport:
    """Re-hashes existing files against the manifest/API hash without any network
    downloads (CONCEPT.md section 10, `--verify-only`). Files not yet present on
    disk are reported as failed (nothing to verify), not silently skipped."""
    report = DownloadReport()
    for item in items:
        dest_path = item.dest_path(dest_root)
        hash_info = item.preferred_hash

        if not dest_path.exists():
            report.results.append(DownloadResult(item=item, ok=False, error="Datei fehlt auf der Platte"))
            continue

        if hash_info:
            algo, expected = hash_info
            actual = _hash_file(dest_path, algo)
            if actual.lower() != expected.lower():
                store.upsert(
                    item.identity_key,
                    status=STATUS_FAILED,
                    dest_path=str(dest_path),
                    last_attempt_at=datetime.now(timezone.utc).isoformat(),
                    last_error=f"hash mismatch: expected {algo}={expected}, got {actual}",
                )
                report.results.append(
                    DownloadResult(item=item, ok=False, error=f"Hash-Mismatch ({algo})")
                )
                continue

        store.upsert(
            item.identity_key,
            status=STATUS_VERIFIED,
            dest_path=str(dest_path),
            file_size=item.file_size,
            hash_algo=hash_info[0] if hash_info else None,
            hash_value=hash_info[1] if hash_info else None,
            last_attempt_at=datetime.now(timezone.utc).isoformat(),
            last_error=None,
        )
        report.results.append(DownloadResult(item=item, ok=True))

    return report
