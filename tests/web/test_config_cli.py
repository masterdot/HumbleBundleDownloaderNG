"""M9: `hbdl config show`/`hbdl config set` via Typer's CliRunner, isolated from
the real user config.toml through a monkeypatched CONFIG_FILE (same isolation
approach as test_config.py, just exercised through the CLI layer)."""

from __future__ import annotations

from typer.testing import CliRunner

from hbdl import cli, config

runner = CliRunner()


def test_config_show_reports_defaults_when_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    result = runner.invoke(cli.app, ["config", "show"])

    assert result.exit_code == 0
    assert "workers      = 3" in result.stdout
    assert "strategy     = auto" in result.stdout


def test_config_set_dest_then_show_reflects_it(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    new_dest = str(tmp_path / "MyLibrary")

    set_result = runner.invoke(cli.app, ["config", "set", "dest", new_dest])
    assert set_result.exit_code == 0

    show_result = runner.invoke(cli.app, ["config", "show"])
    assert new_dest in show_result.stdout


def test_config_set_workers_validates_integer(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    result = runner.invoke(cli.app, ["config", "set", "workers", "not-a-number"])

    assert result.exit_code == 1


def test_config_set_strategy_rejects_unknown_value(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    result = runner.invoke(cli.app, ["config", "set", "strategy", "bogus"])

    assert result.exit_code == 1


def test_config_set_lang_then_show_reflects_it(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    set_result = runner.invoke(cli.app, ["config", "set", "lang", "en"])
    assert set_result.exit_code == 0

    show_result = runner.invoke(cli.app, ["config", "show"])
    assert "lang         = en" in show_result.stdout


def test_config_set_lang_rejects_unknown_value(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    result = runner.invoke(cli.app, ["config", "set", "lang", "fr"])

    assert result.exit_code == 1


def test_config_set_rejects_unknown_key(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    result = runner.invoke(cli.app, ["config", "set", "not_a_real_key", "value"])

    assert result.exit_code == 1


def test_config_set_preserves_other_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    runner.invoke(cli.app, ["config", "set", "workers", "8"])

    result = runner.invoke(cli.app, ["config", "set", "strategy", "direct"])
    assert result.exit_code == 0

    show_result = runner.invoke(cli.app, ["config", "show"])
    assert "workers      = 8" in show_result.stdout
    assert "strategy     = direct" in show_result.stdout


def test_sync_dest_option_uses_config_toml_when_not_passed_on_cli(monkeypatch, tmp_path):
    """Sanity check for the M9 Config.load() wiring: `hbdl sync` without --dest
    should pick up config.toml's dest rather than the cwd-relative built-in
    default -- verified indirectly via config.resolve_dest, which `sync` calls."""
    monkeypatch.delenv("HBDL_DEST", raising=False)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    configured_dest = tmp_path / "ConfiguredLibrary"
    runner.invoke(cli.app, ["config", "set", "dest", str(configured_dest)])

    assert config.resolve_dest(None) == configured_dest
