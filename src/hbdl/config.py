"""Config/state/cache directory resolution and config.toml loading.

See CONCEPT.md section 3 (data storage locations).
"""

from __future__ import annotations

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


@dataclass(slots=True)
class Config:
    dest: Path = DEFAULT_DEST
    workers: int = DEFAULT_WORKERS
    strategy: str = DEFAULT_STRATEGY
    cookie_file: Path | None = None

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> "Config":
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
        if "cookie_file" in data:
            cfg.cookie_file = Path(data["cookie_file"]).expanduser()
        return cfg


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
