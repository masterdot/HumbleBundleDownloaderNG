"""Data model for a single downloadable file in a user's Humble Bundle library.

See CONCEPT.md section 4 for the design rationale (identity key, TTL field).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_UNSAFE_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_path_component(name: str) -> str:
    """Strip characters that are unsafe as a file/dir name on common filesystems."""
    cleaned = _UNSAFE_PATH_CHARS.sub("_", name).strip().strip(".")
    return cleaned or "_"


@dataclass(slots=True)
class DownloadItem:
    gamekey: str
    human_name: str
    subproduct_name: str
    platform: str
    variant_name: str
    filename: str
    url: str
    url_fetched_at: datetime
    file_size: int
    md5: str | None
    sha1: str | None
    torrent_url: str | None

    @property
    def identity_key(self) -> str:
        """Stable key across reruns; NOT based on `url`, which is TTL-signed and changes per fetch."""
        parts = (self.gamekey, self.subproduct_name, self.platform, self.variant_name, self.filename)
        return "|".join(sanitize_path_component(p) for p in parts)

    def dest_path(self, root: Path) -> Path:
        return (
            root
            / sanitize_path_component(self.human_name)
            / sanitize_path_component(self.platform)
            / sanitize_path_component(self.filename)
        )

    @property
    def preferred_hash(self) -> tuple[str, str] | None:
        """Returns (algo, hexdigest), preferring sha1 over md5 as noted in CONCEPT.md."""
        if self.sha1:
            return ("sha1", self.sha1)
        if self.md5:
            return ("md5", self.md5)
        return None
