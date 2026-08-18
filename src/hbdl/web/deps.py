"""FastAPI dependency providers. Kept intentionally minimal -- only what's
actually used today (get_store); avoid speculative providers for subsystems
that don't exist yet (job manager lands in M11, see CONCEPT_WEB.md)."""

from __future__ import annotations

from typing import Iterator

from hbdl.state import StateStore, open_store


def get_store() -> Iterator[StateStore]:
    with open_store() as store:
        yield store
