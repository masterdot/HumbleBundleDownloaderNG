import json
from pathlib import Path

import responses

from hbdl.api import Client
from hbdl.auth import BASE_URL, Session
from hbdl.catalog import build_catalog

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text())


@responses.activate
def test_build_catalog_flattens_order_into_items():
    responses.get(f"{BASE_URL}/api/v1/order/abc123", json=_load("order_detail_abc123.json"))

    client = Client(Session(cookie_value="dummy"))
    items = build_catalog(client, workers=1, gamekeys=["abc123"])

    assert len(items) == 2
    windows_item = next(i for i in items if i.platform == "windows")
    assert windows_item.filename == "examplegame-installer.exe"
    assert windows_item.torrent_url is not None
    assert windows_item.file_size == 104857600

    ebook_item = next(i for i in items if i.platform == "ebook")
    assert ebook_item.torrent_url is None


@responses.activate
def test_build_catalog_uses_list_gamekeys_when_none_given():
    responses.get(f"{BASE_URL}/api/v1/user/order", json=_load("order_list.json"))
    responses.get(f"{BASE_URL}/api/v1/order/abc123", json=_load("order_detail_abc123.json"))

    client = Client(Session(cookie_value="dummy"))
    items = build_catalog(client, workers=1)

    assert len(items) == 2
