"""Local SQLite manifest tracking download status per DownloadItem.identity_key.

See CONCEPT.md section 6 (Idempotenz ueber Wiederholungslaeufe hinweg).
"""

from __future__ import annotations

import sqlite3
import threading
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

CREATE TABLE IF NOT EXISTS catalog_items (
    identity_key TEXT PRIMARY KEY,
    gamekey TEXT NOT NULL,
    human_name TEXT NOT NULL,
    subproduct_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    variant_name TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    has_torrent INTEGER NOT NULL DEFAULT 0,
    md5 TEXT,
    sha1 TEXT,
    last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_catalog_gamekey ON catalog_items(gamekey);
CREATE INDEX IF NOT EXISTS idx_catalog_human_name ON catalog_items(human_name);
CREATE INDEX IF NOT EXISTS idx_catalog_subproduct ON catalog_items(gamekey, subproduct_name);
CREATE INDEX IF NOT EXISTS idx_catalog_platform ON catalog_items(platform);
CREATE INDEX IF NOT EXISTS idx_catalog_variant ON catalog_items(variant_name);
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


@dataclass(slots=True)
class CatalogItemRecord:
    """One denormalized DownloadItem, cached for the library browser (bundle/
    subproduct/file metadata) so it can be queried locally without hitting the
    live Humble Bundle API on every page load. See catalog.sync_catalog_cache."""

    identity_key: str
    gamekey: str
    human_name: str
    subproduct_name: str
    platform: str
    variant_name: str
    filename: str
    file_size: int
    has_torrent: bool
    md5: str | None
    sha1: str | None
    last_seen_at: str


@dataclass(slots=True)
class BundleSummary:
    gamekey: str
    human_name: str
    item_count: int
    total_size: int


@dataclass(slots=True)
class SubproductSummary:
    subproduct_name: str
    item_count: int
    total_size: int


@dataclass(slots=True)
class FileRow:
    identity_key: str
    gamekey: str
    human_name: str
    subproduct_name: str
    platform: str
    variant_name: str
    filename: str
    file_size: int
    has_torrent: bool
    status: str | None  # None = never attempted (no `downloads` row yet)


class StateStore:
    def __init__(self, path: Path | None = None):
        # `path`'s default is resolved here, not via a `path: Path =
        # config.STATE_DB` parameter default -- see the identical comment on
        # Config.load() in config.py for why: parameter defaults are bound
        # once at class-definition time and would be immune to
        # monkeypatching config.STATE_DB in tests (or any other legitimate
        # runtime rebind).
        if path is None:
            path = config.STATE_DB
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        # check_same_thread=False only disables Python's own same-thread
        # guard -- it does NOT make concurrent *simultaneous* access from
        # multiple threads on one connection safe (download_all's worker pool
        # shares one StateStore across `workers` threads). Without this lock,
        # concurrent upsert()s intermittently raised
        # "sqlite3.OperationalError: bad parameter or other API misuse" --
        # caught via a flaky test once STATUS_DOWNLOADING added a second
        # upsert() per item (M12, see CONCEPT_WEB.md). Every method touching
        # self._conn must hold this for its full duration, cursor reads
        # (fetchall) included -- a cursor is only valid while its connection
        # isn't being used by another thread.
        self._db_lock = threading.Lock()
        with self._db_lock:
            # executescript (not execute): _SCHEMA now holds multiple statements
            # (downloads + catalog_items tables, several indexes).
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get(self, identity_key: str) -> Record | None:
        with self._db_lock:
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
        with self._db_lock:
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

    def reconcile_stale_downloading(self) -> int:
        """Resets any `downloading` rows left over from a process that died
        mid-transfer (container restart, kill -9) back to `pending`. Purely
        cosmetic -- the .part file + Range-resume logic doesn't need this, it
        only stops the UI from showing a phantom "downloading" row for a file
        nothing is actually working on. Called once at web app startup (see
        web/app.py). Returns the number of rows reset."""
        with self._db_lock:
            cur = self._conn.execute(
                "UPDATE downloads SET status = ? WHERE status = ?", (STATUS_PENDING, STATUS_DOWNLOADING)
            )
            self._conn.commit()
            return cur.rowcount

    # -- Catalog cache (library browser backing) ---------------------------
    # See catalog.sync_catalog_cache for the population side; these are the
    # read helpers behind the 3-column bundle/subproduct/file browser, live
    # search, and quick-filter buttons in web/routers/library.py.

    def replace_catalog_items(self, records: list[CatalogItemRecord]) -> None:
        """Wholesale-replaces the catalog cache (single transaction: DELETE
        then bulk INSERT) so bundles/items no longer in the account (refunds,
        delisted content) don't linger as stale rows after a fresh sync."""
        with self._db_lock:
            self._conn.execute("DELETE FROM catalog_items")
            self._conn.executemany(
                """
                INSERT INTO catalog_items
                    (identity_key, gamekey, human_name, subproduct_name, platform,
                     variant_name, filename, file_size, has_torrent, md5, sha1, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r.identity_key,
                        r.gamekey,
                        r.human_name,
                        r.subproduct_name,
                        r.platform,
                        r.variant_name,
                        r.filename,
                        r.file_size,
                        int(r.has_torrent),
                        r.md5,
                        r.sha1,
                        r.last_seen_at,
                    )
                    for r in records
                ],
            )
            self._conn.commit()

    def catalog_is_empty(self) -> bool:
        with self._db_lock:
            cur = self._conn.execute("SELECT 1 FROM catalog_items LIMIT 1")
            return cur.fetchone() is None

    def list_bundles(self, search: str | None = None) -> list[BundleSummary]:
        sql = "SELECT gamekey, human_name, COUNT(*), SUM(file_size) FROM catalog_items"
        params: list[str] = []
        if search:
            sql += " WHERE human_name LIKE ?"
            params.append(f"%{search}%")
        sql += " GROUP BY gamekey, human_name ORDER BY human_name COLLATE NOCASE"
        with self._db_lock:
            cur = self._conn.execute(sql, params)
            return [BundleSummary(*row) for row in cur.fetchall()]

    def list_subproducts(self, gamekey: str, search: str | None = None) -> list[SubproductSummary]:
        sql = "SELECT subproduct_name, COUNT(*), SUM(file_size) FROM catalog_items WHERE gamekey = ?"
        params: list[str] = [gamekey]
        if search:
            sql += " AND subproduct_name LIKE ?"
            params.append(f"%{search}%")
        sql += " GROUP BY subproduct_name ORDER BY subproduct_name COLLATE NOCASE"
        with self._db_lock:
            cur = self._conn.execute(sql, params)
            return [SubproductSummary(*row) for row in cur.fetchall()]

    _FILE_ROW_SELECT = (
        "SELECT ci.identity_key, ci.gamekey, ci.human_name, ci.subproduct_name, ci.platform, "
        "ci.variant_name, ci.filename, ci.file_size, ci.has_torrent, d.status "
        "FROM catalog_items ci LEFT JOIN downloads d ON d.identity_key = ci.identity_key"
    )

    @staticmethod
    def _row_to_file(row) -> FileRow:
        return FileRow(
            identity_key=row[0],
            gamekey=row[1],
            human_name=row[2],
            subproduct_name=row[3],
            platform=row[4],
            variant_name=row[5],
            filename=row[6],
            file_size=row[7],
            has_torrent=bool(row[8]),
            status=row[9],
        )

    def get_file(self, identity_key: str) -> FileRow | None:
        sql = self._FILE_ROW_SELECT + " WHERE ci.identity_key = ?"
        with self._db_lock:
            cur = self._conn.execute(sql, (identity_key,))
            row = cur.fetchone()
        return self._row_to_file(row) if row else None

    def list_files(self, gamekey: str, subproduct_name: str) -> list[FileRow]:
        sql = (
            self._FILE_ROW_SELECT
            + " WHERE ci.gamekey = ? AND ci.subproduct_name = ?"
            + " ORDER BY ci.platform, ci.variant_name, ci.filename"
        )
        with self._db_lock:
            cur = self._conn.execute(sql, (gamekey, subproduct_name))
            return [self._row_to_file(row) for row in cur.fetchall()]

    def search_files(self, query: str, limit: int = 200) -> list[FileRow]:
        needle = f"%{query}%"
        sql = (
            self._FILE_ROW_SELECT
            + " WHERE ci.human_name LIKE ? OR ci.subproduct_name LIKE ? OR ci.filename LIKE ?"
            + " ORDER BY ci.human_name COLLATE NOCASE, ci.subproduct_name COLLATE NOCASE LIMIT ?"
        )
        with self._db_lock:
            cur = self._conn.execute(sql, (needle, needle, needle, limit))
            return [self._row_to_file(row) for row in cur.fetchall()]

    def filter_files(
        self, platform: str | None = None, variant_name: str | None = None, limit: int = 200
    ) -> list[FileRow]:
        sql = self._FILE_ROW_SELECT + " WHERE 1=1"
        params: list = []
        if platform:
            sql += " AND ci.platform = ?"
            params.append(platform)
        if variant_name:
            sql += " AND ci.variant_name = ?"
            params.append(variant_name)
        sql += " ORDER BY ci.human_name COLLATE NOCASE, ci.subproduct_name COLLATE NOCASE LIMIT ?"
        params.append(limit)
        with self._db_lock:
            cur = self._conn.execute(sql, params)
            return [self._row_to_file(row) for row in cur.fetchall()]

    def distinct_platforms(self) -> list[str]:
        with self._db_lock:
            cur = self._conn.execute("SELECT DISTINCT platform FROM catalog_items ORDER BY platform")
            return [row[0] for row in cur.fetchall()]

    def distinct_variant_names(self) -> list[str]:
        with self._db_lock:
            cur = self._conn.execute("SELECT DISTINCT variant_name FROM catalog_items ORDER BY variant_name")
            return [row[0] for row in cur.fetchall()]

    def distinct_ebook_formats(self) -> list[str]:
        """variant_name values for platform='ebook' items -- drives the
        "Ebooks (Formate)" quick-filter row."""
        with self._db_lock:
            cur = self._conn.execute(
                "SELECT DISTINCT variant_name FROM catalog_items WHERE platform = 'ebook' ORDER BY variant_name"
            )
            return [row[0] for row in cur.fetchall()]

    def distinct_game_platforms(self) -> list[str]:
        """platform values excluding 'ebook' -- drives the "Spiele (Systeme)"
        quick-filter row."""
        with self._db_lock:
            cur = self._conn.execute(
                "SELECT DISTINCT platform FROM catalog_items WHERE platform != 'ebook' ORDER BY platform"
            )
            return [row[0] for row in cur.fetchall()]


@contextmanager
def open_store(path: Path | None = None) -> Iterator[StateStore]:
    store = StateStore(path)
    try:
        yield store
    finally:
        store.close()
