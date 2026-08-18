"""Direct HTTP download queue: resumable, retried, hash-verified, idempotent.

See CONCEPT.md section 6.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
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
from hbdl.progress import ProgressReporter, ProgressSink
from hbdl.state import STATUS_DOWNLOADING, STATUS_FAILED, STATUS_VERIFIED, StateStore

CHUNK_SIZE = 1024 * 1024  # 1 MiB
MAX_ATTEMPTS = 5
URL_STALE_AFTER = timedelta(minutes=10)


@dataclass(slots=True)
class DownloadResult:
    item: DownloadItem
    ok: bool
    skipped: bool = False
    error: str | None = None
    warning: str | None = None


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

    @property
    def warnings(self) -> list[DownloadResult]:
        return [r for r in self.results if r.warning]


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

    record = store.get(item.identity_key)
    # Compare against the size recorded at actual download time, not the live
    # item.file_size: the API's cached size can go stale (see comment below on
    # Content-Length), which would otherwise make an already-good file look
    # "changed" and get re-downloaded on every single run.
    if (
        record is not None
        and record.status == STATUS_VERIFIED
        and dest_path.exists()
        and dest_path.stat().st_size == record.file_size
    ):
        if progress:
            progress.advance(dest_path.stat().st_size)
        return DownloadResult(item=item, ok=True, skipped=True)

    if breaker and breaker.tripped.is_set():
        return DownloadResult(item=item, ok=False, error="uebersprungen: Circuit Breaker ausgeloest (zu viele 403/429)")

    # Purely informational for the web UI (M12, CONCEPT_WEB.md) -- lets it show
    # "currently downloading X" via a plain query, no other control-flow
    # depends on this row existing. Superseded by the VERIFIED/FAILED upsert
    # below once this attempt concludes either way.
    store.upsert(
        item.identity_key,
        status=STATUS_DOWNLOADING,
        dest_path=str(dest_path),
        last_attempt_at=datetime.now(timezone.utc).isoformat(),
    )

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
                content_length = resp.headers.get("Content-Length")
                expected_total = existing + int(content_length) if content_length and content_length.isdigit() else None

                mode = "ab" if existing and resp.status_code == 206 else "wb"
                with part_path.open(mode) as fh:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        if progress:
                            progress.advance(len(chunk))

            actual_size = part_path.stat().st_size
            # The API's cached file_size/hash can go stale when Humble Bundle
            # replaces a file (patched game build, corrected ebook) without
            # updating download_struct metadata -- confirmed via HEAD requests
            # during testing (server Content-Length differed from the API's
            # file_size for the same URL). The response's OWN Content-Length is
            # the only authoritative signal that this specific transfer is
            # complete; a mismatch against *that* means real truncation/corruption.
            if expected_total is not None and actual_size != expected_total:
                part_path.unlink(missing_ok=True)
                raise ValueError(f"unvollstaendige Uebertragung: erwartet {expected_total} Bytes, erhalten {actual_size}")

            warning: str | None = None
            hash_info = current_item.preferred_hash
            if hash_info:
                algo, expected = hash_info
                actual = _hash_file(part_path, algo)
                if actual.lower() != expected.lower():
                    # Transfer completed correctly per the server's own Content-Length
                    # (checked above); the mismatch is against Humble's stale metadata,
                    # not a corrupted download. Keep the file instead of discarding a
                    # good transfer and retrying into the same mismatch every time.
                    warning = f"Hash-Mismatch ({algo}) gegen ggf. veraltete API-Metadaten -- Datei vollstaendig uebertragen, behalten"

            part_path.replace(dest_path)
            store.upsert(
                item.identity_key,
                status=STATUS_VERIFIED,
                dest_path=str(dest_path),
                file_size=actual_size,  # actual bytes on disk, not the possibly-stale item.file_size
                hash_algo=hash_info[0] if hash_info else None,
                hash_value=hash_info[1] if hash_info else None,
                last_attempt_at=datetime.now(timezone.utc).isoformat(),
                last_error=warning,
            )
            return DownloadResult(item=item, ok=True, warning=warning)

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
    pause_gate: threading.Event | None = None,
    stop_event: threading.Event | None = None,
    progress_factory: Callable[[int], ProgressSink] | None = None,
) -> DownloadReport:
    """Downloads `items`. Each item's strategy is resolved individually via
    `select_strategy` (CONCEPT.md section 8) -- torrent items only fetch the
    small .torrent file (v1, see downloader/torrent.py) and are excluded from
    the byte-progress total, which tracks direct-download bytes only.

    `pause_gate`/`stop_event` (both optional, default to "always go"/"never
    stop" so the CLI's existing call site is unaffected) let a caller like the
    web JobManager (see CONCEPT_WEB.md M11/M12) pause between files -- no new
    submissions once `pause_gate` is cleared, already-in-flight downloads
    finish normally -- or stop the run early -- no new submissions, but
    in-flight downloads are still waited for and their results collected, not
    abandoned. Submission is bounded/incremental (a queue, not "submit every
    future up front") specifically so "stop submitting new work" is
    expressible at all; the per-chunk byte-streaming loop inside
    `_download_one` is untouched by this."""
    if pause_gate is None:
        pause_gate = threading.Event()
        pause_gate.set()
    if stop_event is None:
        stop_event = threading.Event()

    http = client.http_session
    report = DownloadReport()
    breaker = CircuitBreaker(threshold=circuit_breaker_threshold)

    resolved = [(item, select_strategy(item, strategy)) for item in items]
    direct_items = [item for item, kind in resolved if kind == "direct"]
    total_bytes = sum(i.file_size for i in direct_items)

    progress_ctx = (
        progress_factory(total_bytes)
        if progress_factory is not None
        else ProgressReporter(total_bytes, disable=not show_progress)
    )
    with progress_ctx as progress, ThreadPoolExecutor(max_workers=workers) as pool:
        pending = deque(resolved)
        in_flight: dict[Future, DownloadItem] = {}

        def submit_next() -> None:
            item, kind = pending.popleft()
            if kind == "direct":
                future = pool.submit(_download_one, client, http, item, dest_root, store, progress, breaker)
            else:
                future = pool.submit(download_torrent_file, http, item, dest_root, store, breaker)
            in_flight[future] = item

        while pending or in_flight:
            if stop_event.is_set():
                pending.clear()  # no more new starts; still drain in_flight below
            else:
                while pending and len(in_flight) < workers and pause_gate.is_set():
                    submit_next()

            if not in_flight:
                if not pending:
                    break
                pause_gate.wait(timeout=0.5)  # parked: paused with nothing running
                continue

            done, _ = wait(list(in_flight.keys()), timeout=0.5, return_when=FIRST_COMPLETED)
            for future in done:
                result = future.result()
                report.results.append(result)
                if on_result:
                    on_result(result)
                del in_flight[future]

    report.circuit_breaker_tripped = breaker.tripped.is_set()
    return report


def verify_only(items: list[DownloadItem], dest_root: Path, store: StateStore) -> DownloadReport:
    """Re-hashes existing files against the manifest/API hash without any network
    downloads (CONCEPT.md section 10, `--verify-only`). Files not yet present on
    disk are reported as failed (nothing to verify), not silently skipped. A hash
    mismatch with a matching file size is a warning, not a failure -- see the
    comment in `_download_one` for why (stale checksums on old, patched bundles)."""
    report = DownloadReport()
    for item in items:
        dest_path = item.dest_path(dest_root)
        hash_info = item.preferred_hash

        if not dest_path.exists():
            report.results.append(DownloadResult(item=item, ok=False, error="Datei fehlt auf der Platte"))
            continue

        actual_size = dest_path.stat().st_size
        warning: str | None = None
        if hash_info:
            algo, expected = hash_info
            actual = _hash_file(dest_path, algo)
            if actual.lower() != expected.lower():
                if actual_size != item.file_size:
                    store.upsert(
                        item.identity_key,
                        status=STATUS_FAILED,
                        dest_path=str(dest_path),
                        last_attempt_at=datetime.now(timezone.utc).isoformat(),
                        last_error=f"hash mismatch: expected {algo}={expected}, got {actual}",
                    )
                    report.results.append(
                        DownloadResult(item=item, ok=False, error=f"Hash-Mismatch ({algo}) und Groesse falsch")
                    )
                    continue
                warning = f"Hash-Mismatch ({algo}), Datei aber vollstaendig (Groesse passt)"

        # Store the size actually on disk, not the possibly-stale item.file_size
        # from the API -- see the comment in `_download_one` on why that field
        # can go stale, and why comparing against it would break future skips.
        store.upsert(
            item.identity_key,
            status=STATUS_VERIFIED,
            dest_path=str(dest_path),
            file_size=actual_size,
            hash_algo=hash_info[0] if hash_info else None,
            hash_value=hash_info[1] if hash_info else None,
            last_attempt_at=datetime.now(timezone.utc).isoformat(),
            last_error=warning,
        )
        report.results.append(DownloadResult(item=item, ok=True, warning=warning))

    return report
