"""Discovery flow: order list -> order details -> flat list of DownloadItem.

See CONCEPT.md section 5.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from hbdl.api import Client
from hbdl.models import DownloadItem


def _order_to_items(order: dict) -> list[DownloadItem]:
    items: list[DownloadItem] = []
    gamekey = order.get("gamekey", "")
    human_name = order.get("product", {}).get("human_name") or order.get("human_name") or gamekey
    fetched_at = datetime.now(timezone.utc)

    for subproduct in order.get("subproducts", []):
        subproduct_name = subproduct.get("human_name", "unknown")
        for download in subproduct.get("downloads", []):
            platform = download.get("platform", "unknown")
            for variant in download.get("download_struct", []):
                url_block = variant.get("url") or {}
                web_url = url_block.get("web")
                if not web_url:
                    continue
                filename = web_url.split("?", 1)[0].rsplit("/", 1)[-1]
                items.append(
                    DownloadItem(
                        gamekey=gamekey,
                        human_name=human_name,
                        subproduct_name=subproduct_name,
                        platform=platform,
                        variant_name=variant.get("name", "unknown"),
                        filename=filename,
                        url=web_url,
                        url_fetched_at=fetched_at,
                        file_size=int(variant.get("file_size") or 0),
                        md5=variant.get("md5"),
                        sha1=variant.get("sha1"),
                        torrent_url=url_block.get("bittorrent"),
                    )
                )
    return items


def build_catalog(client: Client, workers: int = 3, gamekeys: list[str] | None = None) -> list[DownloadItem]:
    """Fetch all orders (throttled via a bounded thread pool, per CONCEPT.md
    section 10 rate-limiting guidance) and flatten them into DownloadItems."""
    keys = gamekeys if gamekeys is not None else client.list_gamekeys()
    items: list[DownloadItem] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(client.order_detail, key): key for key in keys}
        for future in as_completed(futures):
            order = future.result()
            items.extend(_order_to_items(order))
    return items


def refresh_item_url(client: Client, item: DownloadItem) -> DownloadItem:
    """Re-fetch a single order and return a fresh copy of the matching item,
    used when a signed URL has expired (CONCEPT.md section 6, TTL handling)."""
    order = client.order_detail(item.gamekey)
    for fresh in _order_to_items(order):
        if fresh.identity_key == item.identity_key:
            return fresh
    raise LookupError(f"Item {item.identity_key} not found in refreshed order {item.gamekey}")
