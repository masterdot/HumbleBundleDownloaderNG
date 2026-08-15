from datetime import datetime, timezone
from pathlib import Path

from hbdl.models import DownloadItem, sanitize_path_component


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
        file_size=100,
        md5="d41d8cd98f00b204e9800998ecf8427e",
        sha1="da39a3ee5e6b4b0d3255bfef95601890afd80709",
        torrent_url=None,
    )
    defaults.update(overrides)
    return DownloadItem(**defaults)


def test_sanitize_path_component_strips_unsafe_chars():
    assert sanitize_path_component("Half-Life 2: Episode One") == "Half-Life 2_ Episode One"
    assert sanitize_path_component("") == "_"


def test_identity_key_is_stable_and_ignores_url():
    a = _item(url="https://dl.humble.com/game.exe?ttl=1")
    b = _item(url="https://dl.humble.com/game.exe?ttl=999")
    assert a.identity_key == b.identity_key


def test_identity_key_differs_per_variant():
    a = _item(variant_name="Installer")
    b = _item(variant_name="Portable")
    assert a.identity_key != b.identity_key


def test_dest_path_builds_expected_layout():
    item = _item(human_name="My Bundle", platform="windows", filename="game.exe")
    path = item.dest_path(Path("/tmp/lib"))
    assert path == Path("/tmp/lib/My Bundle/windows/game.exe")


def test_preferred_hash_prefers_sha1():
    item = _item(md5="m", sha1="s")
    assert item.preferred_hash == ("sha1", "s")

    item2 = _item(md5="m", sha1=None)
    assert item2.preferred_hash == ("md5", "m")

    item3 = _item(md5=None, sha1=None)
    assert item3.preferred_hash is None
