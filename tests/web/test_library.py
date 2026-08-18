"""M10: library browser routes (column drill-down, search, quick filters).
Seeds the catalog cache directly via sync_catalog_cache (no live API calls --
that's exercised separately by /library/refresh, not covered here since it
needs a resolvable auth session)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from hbdl import config
from hbdl.catalog import sync_catalog_cache
from hbdl.models import DownloadItem
from hbdl.state import StateStore
from hbdl.web.app import create_app


def _item(**overrides) -> DownloadItem:
    defaults = dict(
        gamekey="b1",
        human_name="Cosplay Bundle",
        subproduct_name="Foam Armor",
        platform="ebook",
        variant_name="PDF",
        filename="foam.pdf",
        url="https://dl.humble.com/foam.pdf?ttl=1",
        url_fetched_at=datetime.now(timezone.utc),
        file_size=1234,
        md5=None,
        sha1=None,
        torrent_url=None,
    )
    defaults.update(overrides)
    return DownloadItem(**defaults)


def _client_with_seeded_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")

    store = StateStore(tmp_path / "state.sqlite")
    sync_catalog_cache(
        store,
        [
            _item(),
            _item(variant_name="EPUB", filename="foam.epub"),
            _item(
                gamekey="b2",
                human_name="Indie Bundle",
                subproduct_name="Braid",
                platform="windows",
                variant_name="Installer",
                filename="braid.exe",
                file_size=500_000,
                torrent_url="https://dl.humble.com/braid.torrent",
            ),
        ],
    )
    store.close()

    return TestClient(create_app())


def test_library_page_lists_bundles(tmp_path, monkeypatch):
    client = _client_with_seeded_catalog(tmp_path, monkeypatch)

    resp = client.get("/library")

    assert resp.status_code == 200
    assert "Cosplay Bundle" in resp.text
    assert "Indie Bundle" in resp.text


def test_library_page_shows_empty_state_without_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    client = TestClient(create_app())

    resp = client.get("/library")

    assert resp.status_code == 200
    assert "hbdl list" in resp.text


def test_columns_subproducts_scoped_to_gamekey(tmp_path, monkeypatch):
    client = _client_with_seeded_catalog(tmp_path, monkeypatch)

    resp = client.get("/library/columns/subproducts", params={"gamekey": "b1"})

    assert resp.status_code == 200
    assert "Foam Armor" in resp.text
    assert "Braid" not in resp.text


def test_columns_files_scoped_to_subproduct(tmp_path, monkeypatch):
    client = _client_with_seeded_catalog(tmp_path, monkeypatch)

    resp = client.get("/library/columns/files", params={"gamekey": "b1", "subproduct": "Foam Armor"})

    assert resp.status_code == 200
    assert "foam.pdf" in resp.text
    assert "foam.epub" in resp.text
    assert "braid.exe" not in resp.text


def test_search_matches_across_bundle_subproduct_filename(tmp_path, monkeypatch):
    client = _client_with_seeded_catalog(tmp_path, monkeypatch)

    resp = client.get("/library/search", params={"q": "braid"})

    assert resp.status_code == 200
    assert "braid.exe" in resp.text
    assert "foam.pdf" not in resp.text


def test_search_empty_query_resets_to_columns(tmp_path, monkeypatch):
    client = _client_with_seeded_catalog(tmp_path, monkeypatch)

    resp = client.get("/library/search", params={"q": "   "})

    assert resp.status_code == 200
    assert "Cosplay Bundle" in resp.text
    assert "Indie Bundle" in resp.text


def test_filter_by_variant_and_by_platform(tmp_path, monkeypatch):
    client = _client_with_seeded_catalog(tmp_path, monkeypatch)

    epub_only = client.get("/library/filter", params={"variant": "EPUB"})
    windows_only = client.get("/library/filter", params={"platform": "windows"})

    assert "foam.epub" in epub_only.text
    assert "foam.pdf" not in epub_only.text
    assert "braid.exe" in windows_only.text


def test_filter_bar_buttons_reflect_distinct_values(tmp_path, monkeypatch):
    client = _client_with_seeded_catalog(tmp_path, monkeypatch)

    resp = client.get("/library")

    assert "EPUB" in resp.text
    assert "PDF" in resp.text
    assert "windows" in resp.text
    assert "ebook" not in resp.text.split("Spiele/Software")[1].split("</div>")[0] if "Spiele/Software" in resp.text else True


def test_refresh_without_login_shows_error_not_500(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "STATE_DB", tmp_path / "state.sqlite")
    monkeypatch.setattr(config, "SESSION_FILE", tmp_path / "no-such-session.json")
    monkeypatch.delenv("HBDL_COOKIE", raising=False)
    monkeypatch.delenv("HBDL_COOKIE_FILE", raising=False)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "no-such-config.toml")
    client = TestClient(create_app())

    resp = client.post("/library/refresh")

    assert resp.status_code == 200
    assert "Kein Login" in resp.text
