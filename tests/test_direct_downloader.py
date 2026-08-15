import hashlib
from datetime import datetime, timezone
from pathlib import Path

import responses

from hbdl.api import Client
from hbdl.auth import BASE_URL, Session
from hbdl.downloader.direct import download_all
from hbdl.models import DownloadItem
from hbdl.state import STATUS_FAILED, STATUS_VERIFIED, StateStore

CONTENT = b"hello world" * 1000
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


@responses.activate
def test_download_all_writes_file_and_marks_verified(tmp_path):
    responses.get("https://dl.humble.com/book.pdf", body=CONTENT, status=200)

    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    item = _item()

    report = download_all(client, [item], tmp_path / "dest", store, workers=1, show_progress=False)

    assert len(report.succeeded) == 1
    assert not report.failed
    written = (tmp_path / "dest" / "Example Bundle" / "ebook" / "book.pdf").read_bytes()
    assert written == CONTENT
    assert store.get(item.identity_key).status == STATUS_VERIFIED
    store.close()


@responses.activate
def test_download_all_skips_already_verified(tmp_path):
    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    item = _item()
    dest_path = item.dest_path(tmp_path / "dest")
    dest_path.parent.mkdir(parents=True)
    dest_path.write_bytes(CONTENT)
    store.upsert(item.identity_key, status=STATUS_VERIFIED, dest_path=str(dest_path), file_size=len(CONTENT))

    # no responses.get registered -> would raise ConnectionError if a request were attempted
    report = download_all(client, [item], tmp_path / "dest", store, workers=1, show_progress=False)

    assert len(report.skipped) == 1
    assert not report.failed
    store.close()


@responses.activate
def test_download_all_marks_failed_on_hash_mismatch_with_wrong_size(tmp_path):
    responses.get("https://dl.humble.com/book.pdf", body=b"wrong content", status=200)

    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    item = _item()

    from hbdl.downloader import direct as direct_mod
    direct_mod.MAX_ATTEMPTS = 1  # avoid slow retries in test
    try:
        report = download_all(client, [item], tmp_path / "dest", store, workers=1, show_progress=False)
    finally:
        direct_mod.MAX_ATTEMPTS = 5

    assert len(report.failed) == 1
    assert store.get(item.identity_key).status == STATUS_FAILED
    assert not (tmp_path / "dest" / "Example Bundle" / "ebook" / "book.pdf").exists()
    store.close()


@responses.activate
def test_download_all_keeps_file_on_hash_mismatch_with_correct_size(tmp_path):
    # Same length as CONTENT but different bytes -> matching size, wrong hash.
    # This mirrors real Humble Bundle data: old bundles whose game builds were
    # patched after release without the stored checksum being updated.
    wrong_content = b"WRONG-BYTES" * 1000
    assert len(wrong_content) == len(CONTENT)
    responses.get("https://dl.humble.com/book.pdf", body=wrong_content, status=200)

    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    item = _item()

    report = download_all(client, [item], tmp_path / "dest", store, workers=1, show_progress=False)

    assert len(report.succeeded) == 1
    assert not report.failed
    assert len(report.warnings) == 1
    assert "Hash-Mismatch" in report.warnings[0].warning

    written = (tmp_path / "dest" / "Example Bundle" / "ebook" / "book.pdf").read_bytes()
    assert written == wrong_content  # kept, not deleted
    assert store.get(item.identity_key).status == STATUS_VERIFIED
    store.close()
