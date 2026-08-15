from datetime import datetime, timezone

import pytest

from hbdl.downloader.strategy import select_strategy
from hbdl.models import DownloadItem


def _item(torrent_url: str | None) -> DownloadItem:
    return DownloadItem(
        gamekey="abc123",
        human_name="Example Bundle",
        subproduct_name="Example Game",
        platform="windows",
        variant_name="Installer",
        filename="game.exe",
        url="https://dl.humble.com/game.exe?ttl=1",
        url_fetched_at=datetime.now(timezone.utc),
        file_size=100,
        md5=None,
        sha1=None,
        torrent_url=torrent_url,
    )


def test_direct_strategy_always_direct_even_with_torrent():
    item = _item(torrent_url="https://dl.humble.com/x.torrent")
    assert select_strategy(item, "direct") == "direct"


@pytest.mark.parametrize("requested", ["auto", "torrent"])
def test_auto_and_torrent_prefer_torrent_when_available(requested):
    item = _item(torrent_url="https://dl.humble.com/x.torrent")
    assert select_strategy(item, requested) == "torrent"


@pytest.mark.parametrize("requested", ["auto", "torrent"])
def test_auto_and_torrent_fall_back_to_direct_without_torrent_url(requested):
    item = _item(torrent_url=None)
    assert select_strategy(item, requested) == "direct"


def test_unknown_strategy_raises():
    item = _item(torrent_url=None)
    with pytest.raises(ValueError):
        select_strategy(item, "carrier-pigeon")
