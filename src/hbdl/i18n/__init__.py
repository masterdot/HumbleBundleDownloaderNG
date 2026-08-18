"""Minimal DE/EN translation lookup, shared by the CLI and the web UI.

Language is a single module-global rather than passed around explicitly --
hbdl is a single-user, single-process app (no per-request language
negotiation like a multi-tenant web server would need), so the extra
plumbing would buy nothing. `set_lang()` is called once at process start
(`cli.py::main()` for the CLI, which also covers `hbdl web serve` since it
dispatches through the same entry point) and again by the web UI's language
toggle when the user switches at runtime.
"""

from __future__ import annotations

from hbdl.i18n.strings import CATALOG

_lang = "de"


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang


def get_lang() -> str:
    return _lang


def t(key: str, **kwargs: object) -> str:
    entry = CATALOG[key]
    text = entry.get(_lang, entry["de"])
    return text.format(**kwargs) if kwargs else text


def t_count(key_singular: str, key_plural: str, n: int, **kwargs: object) -> str:
    return t(key_singular if n == 1 else key_plural, n=n, **kwargs)
