from datetime import datetime, timezone

import responses

from hbdl.api import Client
from hbdl.auth import Session
from hbdl.downloader.common import CircuitBreaker
from hbdl.downloader.torrent import download_torrent_file, torrent_dest_path
from hbdl.models import DownloadItem
from hbdl.state import STATUS_VERIFIED, StateStore

TORRENT_BYTES = b"d8:announce...fake torrent bytese"


def _item(**overrides) -> DownloadItem:
    defaults = dict(
        gamekey="abc123",
        human_name="Example Bundle",
        subproduct_name="Example Game",
        platform="windows",
        variant_name="Installer",
        filename="game.exe",
        url="https://dl.humble.com/game.exe?ttl=1",
        url_fetched_at=datetime.now(timezone.utc),
        file_size=1000,
        md5=None,
        sha1=None,
        torrent_url="https://dl.humble.com/torrents/game.exe.torrent",
    )
    defaults.update(overrides)
    return DownloadItem(**defaults)


@responses.activate
def test_download_torrent_file_saves_bytes(tmp_path):
    responses.get("https://dl.humble.com/torrents/game.exe.torrent", body=TORRENT_BYTES, status=200)

    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    item = _item()

    result = download_torrent_file(client.http_session, item, tmp_path / "dest", store)

    assert result.ok is True
    dest = torrent_dest_path(item, tmp_path / "dest")
    assert dest.read_bytes() == TORRENT_BYTES
    assert store.get(f"{item.identity_key}::torrent").status == STATUS_VERIFIED
    store.close()


def test_download_torrent_file_without_url_fails_cleanly(tmp_path):
    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    item = _item(torrent_url=None)

    result = download_torrent_file(client.http_session, item, tmp_path / "dest", store)

    assert result.ok is False
    store.close()


@responses.activate
def test_download_torrent_file_skips_when_already_verified(tmp_path):
    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    item = _item()
    dest = torrent_dest_path(item, tmp_path / "dest")
    dest.parent.mkdir(parents=True)
    dest.write_bytes(TORRENT_BYTES)
    store.upsert(f"{item.identity_key}::torrent", status=STATUS_VERIFIED, dest_path=str(dest))

    # no responses.get registered -> would raise ConnectionError if requested
    result = download_torrent_file(client.http_session, item, tmp_path / "dest", store)

    assert result.ok is True
    assert result.skipped is True
    store.close()


@responses.activate
def test_download_torrent_file_trips_breaker_on_429(tmp_path):
    for _ in range(3):
        responses.get("https://dl.humble.com/torrents/game.exe.torrent", status=429)

    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    item = _item()
    breaker = CircuitBreaker(threshold=1)

    result = download_torrent_file(client.http_session, item, tmp_path / "dest", store, breaker=breaker)

    assert result.ok is False
    assert breaker.tripped.is_set()
    store.close()
