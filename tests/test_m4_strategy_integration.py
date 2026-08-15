import hashlib
from datetime import datetime, timezone

import responses

from hbdl.api import Client
from hbdl.auth import Session
from hbdl.downloader.direct import download_all
from hbdl.downloader.torrent import torrent_dest_path
from hbdl.models import DownloadItem
from hbdl.state import StateStore

DIRECT_CONTENT = b"ebook bytes" * 100
DIRECT_SHA1 = hashlib.sha1(DIRECT_CONTENT).hexdigest()
TORRENT_BYTES = b"fake torrent metadata"


def _direct_item() -> DownloadItem:
    return DownloadItem(
        gamekey="abc123",
        human_name="Example Bundle",
        subproduct_name="Example Game",
        platform="ebook",
        variant_name="PDF",
        filename="book.pdf",
        url="https://dl.humble.com/book.pdf?ttl=1",
        url_fetched_at=datetime.now(timezone.utc),
        file_size=len(DIRECT_CONTENT),
        md5=None,
        sha1=DIRECT_SHA1,
        torrent_url=None,
    )


def _torrent_item() -> DownloadItem:
    return DownloadItem(
        gamekey="abc123",
        human_name="Example Bundle",
        subproduct_name="Example Game",
        platform="windows",
        variant_name="Installer",
        filename="game.exe",
        url="https://dl.humble.com/game.exe?ttl=1",
        url_fetched_at=datetime.now(timezone.utc),
        file_size=5_000_000_000,  # deliberately huge; must NOT be fetched directly under auto
        md5=None,
        sha1=None,
        torrent_url="https://dl.humble.com/torrents/game.exe.torrent",
    )


@responses.activate
def test_auto_strategy_routes_ebook_direct_and_game_to_torrent(tmp_path):
    responses.get("https://dl.humble.com/book.pdf", body=DIRECT_CONTENT, status=200)
    responses.get("https://dl.humble.com/torrents/game.exe.torrent", body=TORRENT_BYTES, status=200)
    # deliberately no responses.get for https://dl.humble.com/game.exe -- if
    # auto strategy tried a direct download of the huge game file, this test
    # would fail with a ConnectionError instead of silently passing.

    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    ebook, game = _direct_item(), _torrent_item()

    report = download_all(
        client, [ebook, game], tmp_path / "dest", store, workers=1, show_progress=False, strategy="auto"
    )

    assert len(report.succeeded) == 2
    assert not report.failed
    assert (tmp_path / "dest" / "Example Bundle" / "ebook" / "book.pdf").read_bytes() == DIRECT_CONTENT
    assert torrent_dest_path(game, tmp_path / "dest").read_bytes() == TORRENT_BYTES
    store.close()


@responses.activate
def test_direct_strategy_ignores_torrent_option(tmp_path):
    responses.get("https://dl.humble.com/torrents/game.exe.torrent", status=200, body=b"")
    responses.get(
        "https://dl.humble.com/game.exe",
        status=200,
        body=b"x" * 10,
        headers={"Content-Length": "10"},
    )

    client = Client(Session(cookie_value="dummy"))
    store = StateStore(tmp_path / "state.sqlite")
    game = _torrent_item()
    game.file_size = 10  # keep it small for a real byte-for-byte direct download in this test
    game.sha1 = hashlib.sha1(b"x" * 10).hexdigest()

    report = download_all(
        client, [game], tmp_path / "dest", store, workers=1, show_progress=False, strategy="direct"
    )

    assert len(report.succeeded) == 1
    assert (tmp_path / "dest" / "Example Bundle" / "windows" / "game.exe").exists()
    assert not torrent_dest_path(game, tmp_path / "dest").exists()
    store.close()
