"""Unit tests for hbdl.config.resolve_dest (M8): precedence CLI flag > HBDL_DEST
env var > config.toml > DEFAULT_DEST. See CONCEPT_WEB.md for why this matters
for Docker (the container's cwd-relative DEFAULT_DEST is meaningless)."""

from __future__ import annotations

from pathlib import Path

from hbdl import config


def test_resolve_dest_prefers_cli_value(monkeypatch, tmp_path):
    monkeypatch.setenv("HBDL_DEST", str(tmp_path / "from-env"))
    cli_value = tmp_path / "from-cli"

    result = config.resolve_dest(cli_value)

    assert result == cli_value


def test_resolve_dest_falls_back_to_env_var(monkeypatch, tmp_path):
    monkeypatch.delenv("HBDL_DEST", raising=False)
    env_dest = tmp_path / "from-env"
    monkeypatch.setenv("HBDL_DEST", str(env_dest))

    result = config.resolve_dest(None)

    assert result == env_dest


def test_resolve_dest_falls_back_to_config_toml(monkeypatch, tmp_path):
    monkeypatch.delenv("HBDL_DEST", raising=False)
    config_file = tmp_path / "config.toml"
    config_dest = tmp_path / "from-config-toml"
    config_file.write_text(f'dest = "{config_dest}"\n', encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    result = config.resolve_dest(None)

    assert result == config_dest


def test_resolve_dest_falls_back_to_default(monkeypatch, tmp_path):
    monkeypatch.delenv("HBDL_DEST", raising=False)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "does-not-exist.toml")

    result = config.resolve_dest(None)

    assert result == config.DEFAULT_DEST


def test_resolve_lang_prefers_cli_value(monkeypatch):
    monkeypatch.setenv("HBDL_LANG", "de")

    result = config.resolve_lang("en")

    assert result == "en"


def test_resolve_lang_falls_back_to_env_var(monkeypatch):
    monkeypatch.setenv("HBDL_LANG", "en")

    result = config.resolve_lang(None)

    assert result == "en"


def test_resolve_lang_falls_back_to_config_toml(monkeypatch, tmp_path):
    monkeypatch.delenv("HBDL_LANG", raising=False)
    config_file = tmp_path / "config.toml"
    config_file.write_text('lang = "en"\n', encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    result = config.resolve_lang(None)

    assert result == "en"


def test_resolve_lang_falls_back_to_default(monkeypatch, tmp_path):
    monkeypatch.delenv("HBDL_LANG", raising=False)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "does-not-exist.toml")

    result = config.resolve_lang(None)

    assert result == config.DEFAULT_LANG


def test_config_save_then_load_round_trips_all_fields(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.Config(
        dest=tmp_path / "library",
        workers=7,
        strategy="torrent",
        lang="en",
        cookie_file=tmp_path / "cookies.txt",
    )

    cfg.save(path=path)
    loaded = config.Config.load(path=path)

    assert loaded.dest == cfg.dest
    assert loaded.workers == 7
    assert loaded.strategy == "torrent"
    assert loaded.lang == "en"
    assert loaded.cookie_file == cfg.cookie_file


def test_config_save_omits_cookie_file_when_none(tmp_path):
    path = tmp_path / "config.toml"
    cfg = config.Config(dest=tmp_path / "library", workers=3, strategy="auto", cookie_file=None)

    cfg.save(path=path)
    loaded = config.Config.load(path=path)

    assert loaded.cookie_file is None


def test_config_save_load_mutate_save_preserves_other_fields(tmp_path):
    """The documented "merge" pattern: load(), mutate one field, save()."""
    path = tmp_path / "config.toml"
    config.Config(dest=tmp_path / "orig", workers=5, strategy="direct").save(path=path)

    cfg = config.Config.load(path=path)
    cfg.workers = 9
    cfg.save(path=path)

    reloaded = config.Config.load(path=path)
    assert reloaded.workers == 9
    assert reloaded.dest == tmp_path / "orig"
    assert reloaded.strategy == "direct"


def test_config_save_escapes_backslashes_in_windows_style_paths(tmp_path):
    path = tmp_path / "config.toml"
    tricky = Path(r"C:\Users\me\My Library")
    cfg = config.Config(dest=tricky, workers=3, strategy="auto")

    cfg.save(path=path)
    loaded = config.Config.load(path=path)

    assert loaded.dest == tricky
