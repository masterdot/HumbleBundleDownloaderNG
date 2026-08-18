"""M8: smoke tests for the FastAPI scaffold. Uses TestClient (httpx-backed,
see the `dev` extra) rather than a real server, following the offline-only
convention of the rest of the test suite -- no network, no real platformdirs
paths (isolated via monkeypatched HBDL_DEST/config env vars)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from hbdl import config
from hbdl.web.app import create_app


def test_healthz():
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_dashboard_renders_and_reflects_hbdl_dest(monkeypatch, tmp_path):
    dest = tmp_path / "MyLibrary"
    monkeypatch.setenv("HBDL_DEST", str(dest))

    client = TestClient(create_app())
    resp = client.get("/")

    assert resp.status_code == 200
    assert str(dest) in resp.text


def test_static_assets_served():
    client = TestClient(create_app())
    resp = client.get("/static/app.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_footer_present_on_every_page_with_repo_and_donate_links():
    client = TestClient(create_app())

    for path in ("/", "/library", "/settings"):
        resp = client.get(path)
        assert "masterdot" in resp.text
        assert "https://github.com/masterdot/HumbleBundleDownloaderNG" in resp.text
        assert "https://github.com/sponsors/masterdot/" in resp.text


def test_about_page_renders_with_project_links():
    client = TestClient(create_app())

    resp = client.get("/settings/about")

    assert resp.status_code == 200
    assert "https://github.com/masterdot/HumbleBundleDownloaderNG/issues" in resp.text
    assert "https://github.com/sponsors/masterdot/" in resp.text


def test_settings_and_about_pages_link_to_each_other_via_tabs():
    client = TestClient(create_app())

    settings_resp = client.get("/settings")
    about_resp = client.get("/settings/about")

    assert 'href="/settings/about"' in settings_resp.text
    assert 'href="/settings"' in about_resp.text


def test_settings_get_shows_current_config(monkeypatch, tmp_path):
    config_file = tmp_path / "config.toml"
    config.Config(dest=tmp_path / "lib", workers=4, strategy="direct").save(path=config_file)
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    client = TestClient(create_app())
    resp = client.get("/settings")

    assert resp.status_code == 200
    assert str(tmp_path / "lib") in resp.text
    assert 'value="4"' in resp.text


def test_settings_post_persists_and_reflects_new_values(monkeypatch, tmp_path):
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)
    new_dest = str(tmp_path / "NewLibrary")

    client = TestClient(create_app())
    resp = client.post(
        "/settings",
        data={"dest": new_dest, "workers": "6", "strategy": "torrent", "cookie_file": ""},
    )

    assert resp.status_code == 200
    assert "gespeichert" in resp.text
    reloaded = config.Config.load(path=config_file)
    assert str(reloaded.dest) == new_dest
    assert reloaded.workers == 6
    assert reloaded.strategy == "torrent"


def test_settings_post_rejects_unknown_strategy(monkeypatch, tmp_path):
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    client = TestClient(create_app())
    resp = client.post(
        "/settings",
        data={"dest": str(tmp_path), "workers": "3", "strategy": "bogus", "cookie_file": ""},
    )

    assert resp.status_code == 422
    assert not config_file.exists()
