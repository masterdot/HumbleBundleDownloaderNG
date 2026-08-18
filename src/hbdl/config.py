"""Config/state/cache directory resolution and config.toml loading.

See CONCEPT.md section 3 (data storage locations).
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import PlatformDirs

_dirs = PlatformDirs(appname="hbdl", appauthor=False)

CONFIG_DIR = Path(_dirs.user_config_dir)
DATA_DIR = Path(_dirs.user_data_dir)
CONFIG_FILE = CONFIG_DIR / "config.toml"
SESSION_FILE = CONFIG_DIR / "session.json"
STATE_DB = DATA_DIR / "state.sqlite"

DEFAULT_DEST = Path.cwd() / "HumbleLibrary"
DEFAULT_WORKERS = 3
DEFAULT_STRATEGY = "auto"
LANGUAGES = ("de", "en")
DEFAULT_LANG = "de"


@dataclass(slots=True)
class Config:
    dest: Path = DEFAULT_DEST
    workers: int = DEFAULT_WORKERS
    strategy: str = DEFAULT_STRATEGY
    lang: str = DEFAULT_LANG
    cookie_file: Path | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        # `path`'s default is resolved here (module-global lookup, re-evaluated
        # on every call) rather than via a `path: Path = CONFIG_FILE` parameter
        # default -- parameter defaults are bound once at class-definition
        # time, which would make this permanently immune to any later
        # `monkeypatch.setattr(config, "CONFIG_FILE", ...)` in tests (and, in
        # principle, to any other legitimate runtime rebind of CONFIG_FILE).
        if path is None:
            path = CONFIG_FILE
        if not path.exists():
            return cls()
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        cfg = cls()
        if "dest" in data:
            cfg.dest = Path(data["dest"]).expanduser()
        if "workers" in data:
            cfg.workers = int(data["workers"])
        if "strategy" in data:
            cfg.strategy = data["strategy"]
        if "lang" in data:
            cfg.lang = data["lang"]
        if "cookie_file" in data:
            cfg.cookie_file = Path(data["cookie_file"]).expanduser()
        return cfg

    def save(self, path: Path | None = None) -> None:
        """Writes this Config out as config.toml, overwriting the file whole.

        Callers that want to change a single field should `Config.load()`
        first, mutate that one attribute, then `save()` -- since `load()`
        already carries over every other previously-saved (or default) field,
        this is the merge: no separate read-modify-write dance needed here.

        Hand-rolled TOML serialization (4 known scalar fields, no nesting)
        rather than a tomli-w dependency -- keeps a CLI-only install light.
        """
        if path is None:
            path = CONFIG_FILE  # see the identical comment in Config.load()
        # Create *this path's* parent, not unconditionally the real CONFIG_DIR
        # via ensure_dirs() -- callers/tests may pass a path outside it (e.g.
        # tmp_path in tests), and save() shouldn't have a side effect on the
        # real machine-wide config directory in that case.
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f'dest = "{_toml_escape(str(self.dest))}"',
            f"workers = {int(self.workers)}",
            f'strategy = "{_toml_escape(self.strategy)}"',
            f'lang = "{_toml_escape(self.lang)}"',
        ]
        if self.cookie_file is not None:
            lines.append(f'cookie_file = "{_toml_escape(str(self.cookie_file))}"')
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def resolve_dest(cli_value: Path | None = None) -> Path:
    """Precedence: CLI flag > HBDL_DEST env > config.toml > DEFAULT_DEST.

    HBDL_DEST mirrors the existing HBDL_COOKIE/HBDL_COOKIE_FILE env-var
    pattern in auth.resolve_session() -- primarily so a Docker container can
    point the library destination at a mounted volume without a rebuild,
    without relying on the (container-meaningless) Path.cwd()-relative
    DEFAULT_DEST.
    """
    if cli_value is not None:
        return cli_value
    if env_dest := os.environ.get("HBDL_DEST"):
        return Path(env_dest).expanduser()
    return Config.load().dest


def resolve_lang(cli_value: str | None = None) -> str:
    """Precedence: CLI flag > HBDL_LANG env > config.toml > DEFAULT_LANG.

    Mirrors resolve_dest() above. `cli.py::main()` calls this once at process
    start and feeds the result into `i18n.set_lang()`.
    """
    if cli_value is not None:
        return cli_value
    if env_lang := os.environ.get("HBDL_LANG"):
        return env_lang
    return Config.load().lang
