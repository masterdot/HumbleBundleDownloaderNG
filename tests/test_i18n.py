"""M14: catalog completeness and lookup behavior for hbdl.i18n."""

from __future__ import annotations

from hbdl import i18n
from hbdl.i18n.strings import CATALOG


def test_every_catalog_entry_has_de_and_en():
    missing = {
        key: sorted({"de", "en"} - set(entry))
        for key, entry in CATALOG.items()
        if not {"de", "en"} <= set(entry)
    }
    assert missing == {}


def test_t_returns_requested_language(monkeypatch):
    monkeypatch.setattr(i18n, "_lang", "en")
    assert i18n.t("nav.library") == "Library"

    monkeypatch.setattr(i18n, "_lang", "de")
    assert i18n.t("nav.library") == "Bibliothek"


def test_t_interpolates_kwargs(monkeypatch):
    monkeypatch.setitem(CATALOG, "test.greeting", {"de": "Hallo {name}", "en": "Hello {name}"})
    monkeypatch.setattr(i18n, "_lang", "en")

    assert i18n.t("test.greeting", name="World") == "Hello World"


def test_set_lang_and_get_lang_round_trip(monkeypatch):
    monkeypatch.setattr(i18n, "_lang", "de")
    i18n.set_lang("en")
    assert i18n.get_lang() == "en"
