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

from fastapi import APIRouter, Depends, Request

from hbdl import auth, i18n
from hbdl.api import Client
from hbdl.catalog import build_catalog, sync_catalog_cache
from hbdl.state import BundleSummary, FileRow, StateStore, SubproductSummary
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
