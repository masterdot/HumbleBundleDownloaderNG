"""Per-item direct-vs-torrent decision. See CONCEPT.md section 8.

Not every file has a torrent option (mostly large game installers do; ebooks
and audio are typically HTTP-only), so the decision is made per DownloadItem,
never as a single global switch.
"""

from __future__ import annotations

from hbdl.models import DownloadItem

STRATEGIES = ("auto", "direct", "torrent")


def select_strategy(item: DownloadItem, requested: str) -> str:
    """Resolve the requested strategy to a concrete per-item choice.

    - "direct": always direct HTTP, even if a torrent option exists.
    - "torrent": torrent if available, otherwise falls back to direct
      (a file without a torrent option must never be silently dropped).
    - "auto": same fallback behaviour as "torrent" — prefer torrent when
      available, direct otherwise.
    """
    if requested not in STRATEGIES:
        raise ValueError(f"unknown strategy: {requested!r} (expected one of {STRATEGIES})")
    if requested == "direct":
        return "direct"
    return "torrent" if item.torrent_url else "direct"
