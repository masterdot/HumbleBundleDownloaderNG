import hashlib
from datetime import datetime, timezone
from pathlib import Path

import responses

from hbdl.api import Client
from hbdl.auth import BASE_URL, Session
from hbdl.downloader import direct as direct_mod
from hbdl.downloader.direct import CircuitBreaker, download_all, verify_only
from hbdl.models import DownloadItem
from hbdl.state import STATUS_VERIFIED, StateStore

CONTENT = b"payload" * 500
SHA1 = hashlib.sha1(CONTENT).hexdigest()


def _item(**overrides) -> DownloadItem:
    defaults = dict(
        gamekey="abc123",
        human_name="Example Bundle",
        subproduct_name="Example Game",
        platform="ebook",
        variant_name="PDF",
        filename="book.pdf",
        url="https://dl.humble.com/book.pdf?ttl=1",
        url_fetched_at=datetime.now(timezone.utc),
        file_size=len(CONTENT),
        md5=None,
        sha1=SHA1,
        torrent_url=None,
    )
    defaults.update(overrides)
    return DownloadItem(**defaults)


def test_circuit_breaker_trips_after_threshold():
    breaker = CircuitBreaker(threshold=3)
    assert not breaker.tripped.is_set()
    breaker.record_block()
    breaker.record_block()
    assert not breaker.tripped.is_set()
    breaker.record_block()
    assert breaker.tripped.is_set()


@responses.activate
def test_download_all_trips_breaker_on_repeated_429(tmp_path):
    for _ in range(6):
        responses.get("https://dl.humble.com/book.pdf", status=429)

    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    item = _item()

    orig_max_attempts = direct_mod.MAX_ATTEMPTS
    direct_mod.MAX_ATTEMPTS = 2  # keep test fast
    try:
        report = download_all(
            client, [item], tmp_path / "dest", store, workers=1, show_progress=False, circuit_breaker_threshold=1
        )
    finally:
        direct_mod.MAX_ATTEMPTS = orig_max_attempts

    assert report.circuit_breaker_tripped is True
    assert len(report.failed) == 1
    store.close()


def test_verify_only_marks_missing_file_as_failed(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    item = _item()

    report = verify_only([item], tmp_path / "dest", store)

    assert len(report.failed) == 1
    assert "fehlt" in report.failed[0].error
    store.close()


def test_verify_only_marks_matching_file_as_verified(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    item = _item()
    dest_path = item.dest_path(tmp_path / "dest")
    dest_path.parent.mkdir(parents=True)
    dest_path.write_bytes(CONTENT)

    report = verify_only([item], tmp_path / "dest", store)

    assert len(report.succeeded) == 1
    assert store.get(item.identity_key).status == STATUS_VERIFIED
    store.close()


def test_verify_only_marks_hash_mismatch_as_failed(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    item = _item()
    dest_path = item.dest_path(tmp_path / "dest")
    dest_path.parent.mkdir(parents=True)
    dest_path.write_bytes(b"not the right content at all")

    report = verify_only([item], tmp_path / "dest", store)

    assert len(report.failed) == 1


def test_verify_only_warns_but_keeps_file_on_hash_mismatch_with_correct_size(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    item = _item()
    dest_path = item.dest_path(tmp_path / "dest")
    dest_path.parent.mkdir(parents=True)
    wrong_but_same_size = b"OTHER!!" * 500
    assert len(wrong_but_same_size) == len(CONTENT)
    dest_path.write_bytes(wrong_but_same_size)

    report = verify_only([item], tmp_path / "dest", store)

    assert len(report.succeeded) == 1
    assert not report.failed
    assert len(report.warnings) == 1
    assert store.get(item.identity_key).status == STATUS_VERIFIED
    assert dest_path.read_bytes() == wrong_but_same_size  # untouched
    store.close()
