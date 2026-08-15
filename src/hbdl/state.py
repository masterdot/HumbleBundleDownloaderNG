"""Local SQLite manifest tracking download status per DownloadItem.identity_key.

See CONCEPT.md section 6 (Idempotenz ueber Wiederholungslaeufe hinweg).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from hbdl import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    identity_key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    dest_path TEXT NOT NULL,
    file_size INTEGER,
    hash_algo TEXT,
    hash_value TEXT,
    last_attempt_at TEXT,
    last_error TEXT
);
"""

STATUS_PENDING = "pending"
STATUS_DOWNLOADING = "downloading"
STATUS_VERIFIED = "verified"
STATUS_FAILED = "failed"


@dataclass(slots=True)
class Record:
    identity_key: str
    status: str
    dest_path: str
    file_size: int | None
    hash_algo: str | None
    hash_value: str | None
    last_attempt_at: str | None
    last_error: str | None


class StateStore:
    def __init__(self, path: Path = config.STATE_DB):
        config.ensure_dirs()
        self._path = path
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get(self, identity_key: str) -> Record | None:
        cur = self._conn.execute(
            "SELECT identity_key, status, dest_path, file_size, hash_algo, hash_value, "
            "last_attempt_at, last_error FROM downloads WHERE identity_key = ?",
            (identity_key,),
        )
        row = cur.fetchone()
        return Record(*row) if row else None

    def upsert(
        self,
        identity_key: str,
        status: str,
        dest_path: str,
        file_size: int | None = None,
        hash_algo: str | None = None,
        hash_value: str | None = None,
        last_attempt_at: str | None = None,
        last_error: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO downloads
                (identity_key, status, dest_path, file_size, hash_algo, hash_value, last_attempt_at, last_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(identity_key) DO UPDATE SET
                status=excluded.status,
                dest_path=excluded.dest_path,
                file_size=COALESCE(excluded.file_size, downloads.file_size),
                hash_algo=COALESCE(excluded.hash_algo, downloads.hash_algo),
                hash_value=COALESCE(excluded.hash_value, downloads.hash_value),
                last_attempt_at=COALESCE(excluded.last_attempt_at, downloads.last_attempt_at),
                last_error=excluded.last_error
            """,
            (identity_key, status, dest_path, file_size, hash_algo, hash_value, last_attempt_at, last_error),
        )
        self._conn.commit()

    def is_verified(self, identity_key: str) -> bool:
        record = self.get(identity_key)
        return record is not None and record.status == STATUS_VERIFIED


@contextmanager
def open_store(path: Path = config.STATE_DB) -> Iterator[StateStore]:
    store = StateStore(path)
    try:
        yield store
    finally:
        store.close()
