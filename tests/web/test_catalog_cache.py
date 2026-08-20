"""M10: catalog_items cache table -- sync_catalog_cache() population and the
StateStore query helpers backing the library browser (bundle/subproduct/file
columns, search, quick filters). Pure SQL, no HTTP involved."""

from __future__ import annotations

from datetime import datetime, timezone

from hbdl.catalog import sync_catalog_cache
from hbdl.models import DownloadItem
from hbdl.state import StateStore


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
        torrent_url=None,
    )
    defaults.update(overrides)
    return DownloadItem(**defaults)


def _seeded_store(tmp_path) -> StateStore:
    store = StateStore(tmp_path / "state.sqlite")
    items = [
        _item(gamekey="bundle1", human_name="Cosplay Bundle", subproduct_name="Foam Armor",
              platform="ebook", variant_name="PDF", filename="foam.pdf", file_size=100),
        _item(gamekey="bundle1", human_name="Cosplay Bundle", subproduct_name="Foam Armor",
              platform="ebook", variant_name="EPUB", filename="foam.epub", file_size=110),
        _item(gamekey="bundle1", human_name="Cosplay Bundle", subproduct_name="Sewing 101",
              platform="ebook", variant_name="MOBI", filename="sewing.mobi", file_size=90),
        _item(gamekey="bundle2", human_name="Indie Game Bundle", subproduct_name="Braid",
              platform="windows", variant_name="Installer", filename="braid_win.exe", file_size=500_000,
              torrent_url="https://dl.humble.com/braid.torrent"),
        _item(gamekey="bundle2", human_name="Indie Game Bundle", subproduct_name="Braid",
              platform="mac", variant_name="Installer", filename="braid_mac.dmg", file_size=520_000),
    ]
    sync_catalog_cache(store, items)
    return store


def test_sync_catalog_cache_populates_and_replaces(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    assert store.catalog_is_empty()

    sync_catalog_cache(store, [_item()])
    assert not store.catalog_is_empty()

    # A second sync with a *different* item set fully replaces the cache
    # (no stale rows from refunded/delisted content lingering).
    sync_catalog_cache(store, [_item(filename="other.exe", gamekey="xyz")])
    bundles = store.list_bundles()
    assert len(bundles) == 1
    assert bundles[0].gamekey == "xyz"


def test_list_bundles_grouped_with_counts_and_sizes(tmp_path):
    store = _seeded_store(tmp_path)

    bundles = store.list_bundles()

    assert {b.human_name for b in bundles} == {"Cosplay Bundle", "Indie Game Bundle"}
    cosplay = next(b for b in bundles if b.gamekey == "bundle1")
    assert cosplay.item_count == 3
    assert cosplay.total_size == 100 + 110 + 90


def test_list_bundles_search_filters_by_human_name(tmp_path):
    store = _seeded_store(tmp_path)

    result = store.list_bundles(search="Indie")

    assert [b.gamekey for b in result] == ["bundle2"]


def test_list_subproducts_grouped_within_bundle(tmp_path):
    store = _seeded_store(tmp_path)

    subproducts = store.list_subproducts("bundle1")

    names = {s.subproduct_name for s in subproducts}
    assert names == {"Foam Armor", "Sewing 101"}
    foam = next(s for s in subproducts if s.subproduct_name == "Foam Armor")
    assert foam.item_count == 2


def test_list_files_for_subproduct_includes_status_via_left_join(tmp_path):
    store = _seeded_store(tmp_path)
    an_item = _item(gamekey="bundle2", human_name="Indie Game Bundle", subproduct_name="Braid",
                     platform="windows", variant_name="Installer", filename="braid_win.exe")
    store.upsert(an_item.identity_key, status="verified", dest_path="/lib/braid_win.exe", file_size=500_000)

    files = store.list_files("bundle2", "Braid")

    assert len(files) == 2
    win_file = next(f for f in files if f.platform == "windows")
    mac_file = next(f for f in files if f.platform == "mac")
    assert win_file.status == "verified"
    assert mac_file.status is None  # never attempted -> no downloads row
    assert win_file.has_torrent is True
    assert mac_file.has_torrent is False


def test_get_file_returns_single_row_by_identity_key(tmp_path):
    store = _seeded_store(tmp_path)
    an_item = _item(gamekey="bundle1", human_name="Cosplay Bundle", subproduct_name="Foam Armor",
                     platform="ebook", variant_name="PDF", filename="foam.pdf")

    found = store.get_file(an_item.identity_key)

    assert found is not None
    assert found.filename == "foam.pdf"
    assert found.gamekey == "bundle1"


def test_get_file_returns_none_for_unknown_identity_key(tmp_path):
    store = _seeded_store(tmp_path)

    assert store.get_file("does-not-exist") is None


def test_search_files_matches_human_name_subproduct_and_filename(tmp_path):
    store = _seeded_store(tmp_path)

    by_bundle = store.search_files("Cosplay")
    by_subproduct = store.search_files("Sewing")
    by_filename = store.search_files("braid_mac")

    assert len(by_bundle) == 3
    assert {f.filename for f in by_subproduct} == {"sewing.mobi"}
    assert {f.filename for f in by_filename} == {"braid_mac.dmg"}


def test_filter_files_by_platform_and_variant(tmp_path):
    store = _seeded_store(tmp_path)

    windows_only = store.filter_files(platform="windows")
    epub_only = store.filter_files(variant_name="EPUB")

    assert {f.filename for f in windows_only} == {"braid_win.exe"}
    assert {f.filename for f in epub_only} == {"foam.epub"}


def test_distinct_ebook_formats_and_game_platforms(tmp_path):
    store = _seeded_store(tmp_path)

    assert store.distinct_ebook_formats() == ["EPUB", "MOBI", "PDF"]
    assert store.distinct_game_platforms() == ["mac", "windows"]
    assert "ebook" not in store.distinct_game_platforms()
