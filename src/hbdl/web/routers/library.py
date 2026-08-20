"""M10 scope: Finder-style cascading column browser (Bundle -> Subprodukt ->
Datei), live search, and quick-filter buttons -- all backed by the local
catalog_items cache (state.py, catalog.sync_catalog_cache), no live API calls
on page load. See CONCEPT_WEB.md.

Job control (start/pause/stop a real sync) lands in M11/M12; `/library/refresh`
here is a synchronous, one-off "run discovery now and update the cache" action
-- it blocks the request for the duration of build_catalog(), which is
acceptable for a personal library but not the general download job UI.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request

from hbdl import auth, config, i18n
from hbdl.api import Client
from hbdl.catalog import build_catalog, refresh_item_url, sync_catalog_cache
from hbdl.downloader.direct import download_all
from hbdl.models import DownloadItem
from hbdl.state import STATUS_FAILED, BundleSummary, FileRow, StateStore, SubproductSummary, open_store
from hbdl.web.deps import get_store

router = APIRouter(prefix="/library")


def _fmt_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"  # pragma: no cover (personal libraries won't hit this)


def _bundle_rows(bundles: list[BundleSummary]) -> list[dict]:
    return [
        {
            "gamekey": b.gamekey,
            "human_name": b.human_name,
            "item_count": b.item_count,
            "size_label": _fmt_size(b.total_size),
        }
        for b in bundles
    ]


def _subproduct_rows(subs: list[SubproductSummary]) -> list[dict]:
    return [
        {
            "subproduct_name": s.subproduct_name,
            "item_count": s.item_count,
            "size_label": _fmt_size(s.total_size),
        }
        for s in subs
    ]


def _file_rows(files: list[FileRow]) -> list[dict]:
    return [
        {
            "identity_key": f.identity_key,
            "human_name": f.human_name,
            "subproduct_name": f.subproduct_name,
            "platform": f.platform,
            "variant_name": f.variant_name,
            "filename": f.filename,
            "size_label": _fmt_size(f.file_size),
            "has_torrent": f.has_torrent,
            "status": f.status,  # None (never attempted) is handled in the templates
        }
        for f in files
    ]


def _filter_context(store: StateStore) -> dict:
    return {
        "ebook_formats": store.distinct_ebook_formats(),
        "game_platforms": store.distinct_game_platforms(),
    }


@router.get("")
def library_page(request: Request, store: StateStore = Depends(get_store)):
    templates = request.app.state.templates
    context = {
        "bundles": _bundle_rows(store.list_bundles()),
        "empty_catalog": store.catalog_is_empty(),
        **_filter_context(store),
    }
    return templates.TemplateResponse(request, "library.html", context)


@router.get("/columns/root")
def columns_root(request: Request, store: StateStore = Depends(get_store)):
    templates = request.app.state.templates
    context = {"bundles": _bundle_rows(store.list_bundles())}
    return templates.TemplateResponse(request, "_columns_root.html", context)


@router.get("/columns/subproducts")
def columns_subproducts(request: Request, gamekey: str, store: StateStore = Depends(get_store)):
    templates = request.app.state.templates
    context = {"gamekey": gamekey, "subproducts": _subproduct_rows(store.list_subproducts(gamekey))}
    return templates.TemplateResponse(request, "_column_subproduct.html", context)


@router.get("/columns/files")
def columns_files(request: Request, gamekey: str, subproduct: str, store: StateStore = Depends(get_store)):
    templates = request.app.state.templates
    context = {"files": _file_rows(store.list_files(gamekey, subproduct))}
    return templates.TemplateResponse(request, "_column_file.html", context)


@router.get("/search")
def search(request: Request, q: str = "", store: StateStore = Depends(get_store)):
    templates = request.app.state.templates
    q = q.strip()
    if not q:
        context = {"bundles": _bundle_rows(store.list_bundles())}
        return templates.TemplateResponse(request, "_columns_root.html", context)
    files = store.search_files(q)
    heading = i18n.t("library.search_heading", query=q, count=len(files))
    context = {"files": _file_rows(files), "heading": heading}
    return templates.TemplateResponse(request, "_flat_list.html", context)


@router.get("/filter")
def filter_files(
    request: Request,
    platform: str = "",
    variant: str = "",
    store: StateStore = Depends(get_store),
):
    templates = request.app.state.templates
    files = store.filter_files(platform=platform or None, variant_name=variant or None)
    label = platform or variant or i18n.t("filter.all")
    heading = i18n.t("library.filter_heading", label=label, count=len(files))
    context = {"files": _file_rows(files), "heading": heading}
    return templates.TemplateResponse(request, "_flat_list.html", context)


@router.post("/refresh")
def refresh(request: Request, store: StateStore = Depends(get_store)):
    templates = request.app.state.templates
    try:
        session = auth.resolve_session()
    except auth.AuthError as exc:
        error = i18n.t(exc.key, **exc.key_kwargs) if exc.key else str(exc)
        return templates.TemplateResponse(request, "_auth_error.html", {"error": error})

    client = Client(session)
    items = build_catalog(client)
    sync_catalog_cache(store, items)

    context = {"bundles": _bundle_rows(store.list_bundles())}
    return templates.TemplateResponse(request, "_columns_root.html", context)


def _placeholder_item(row: FileRow) -> DownloadItem:
    """A `DownloadItem` carrying only the identity-defining fields (gamekey +
    the four other components of `identity_key`) from a cached `FileRow` --
    just enough for `refresh_item_url` to find the real, current item in a
    freshly refetched order. Its own url/md5/sha1 are throwaway placeholders,
    overwritten by whatever `refresh_item_url` returns."""
    return DownloadItem(
        gamekey=row.gamekey,
        human_name=row.human_name,
        subproduct_name=row.subproduct_name,
        platform=row.platform,
        variant_name=row.variant_name,
        filename=row.filename,
        url="",
        url_fetched_at=datetime.fromtimestamp(0, tz=timezone.utc),
        file_size=row.file_size,
        md5=None,
        sha1=None,
        torrent_url=None,
    )


def _run_single_download(client: Client, row: FileRow) -> None:
    """Runs in its own background thread (started by download_file() below,
    outlives the request) -- its own open_store() rather than the
    request-scoped `get_store` dependency, which FastAPI closes as soon as
    the request handler returns. Safe to run alongside a JobManager bulk
    sync: StateStore serializes all access via its own lock (state.py).

    Always forces strategy="direct", ignoring the account's configured bulk-
    sync strategy: a manual "download this one file now" click means get the
    actual content now, not (for a torrent-eligible item under strategy
    auto/torrent) just the small .torrent metadata file -- which is also
    written under a *different* DB key (`identity_key + "::torrent"`, see
    downloader/torrent.py), so the button's own status badge would never
    leave "offen" even though something did technically happen. Found live
    against a real account file during M17 verification, not a hypothetical."""
    dest = config.resolve_dest(None)
    with open_store() as store:
        try:
            fresh_item = refresh_item_url(client, _placeholder_item(row))
        except Exception as exc:  # noqa: BLE001 -- surfaced via the status badge, not swallowed
            store.upsert(
                row.identity_key,
                status=STATUS_FAILED,
                dest_path=str(_placeholder_item(row).dest_path(dest)),
                last_attempt_at=datetime.now(timezone.utc).isoformat(),
                last_error=str(exc),
            )
            return
        dest.mkdir(parents=True, exist_ok=True)
        download_all(client, [fresh_item], dest, store, workers=1, show_progress=False, strategy="direct")


@router.post("/files/download")
def download_file(request: Request, identity_key: str = Form(...), store: StateStore = Depends(get_store)):
    """Manual single-file download, triggered from the library browser's
    per-row button (_file_action.html) -- separate from JobManager's
    whole-library sync job (web/jobs.py), which is a "one job at a time"
    singleton this deliberately doesn't touch. See _run_single_download()
    for why this needs its own StateStore/background thread."""
    templates = request.app.state.templates
    row = store.get_file(identity_key)
    if row is None:
        return templates.TemplateResponse(request, "_file_action.html", {"identity_key": identity_key, "status": None})

    try:
        session = auth.resolve_session()
    except auth.AuthError:
        # Deliberately no inline error surface here (see the plan/CONCEPT_WEB.md
        # note) -- just re-render the unchanged current status. The user can
        # check the login status on the settings page separately.
        return templates.TemplateResponse(
            request, "_file_action.html", {"identity_key": identity_key, "status": row.status}
        )

    client = Client(session)
    threading.Thread(target=_run_single_download, args=(client, row), daemon=True).start()

    return templates.TemplateResponse(
        request, "_file_action.html", {"identity_key": identity_key, "status": "downloading"}
    )


@router.get("/files/status")
def file_status(request: Request, identity_key: str, store: StateStore = Depends(get_store)):
    """Poll target for _file_action.html's "downloading" state (hx-trigger
    every 2s) -- re-renders the same fragment from the current DB status;
    polling stops naturally once the response no longer carries the
    downloading branch's hx-trigger."""
    templates = request.app.state.templates
    record = store.get(identity_key)
    status = record.status if record else None
    return templates.TemplateResponse(request, "_file_action.html", {"identity_key": identity_key, "status": status})
