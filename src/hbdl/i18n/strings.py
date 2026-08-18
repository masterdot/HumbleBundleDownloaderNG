"""DE/EN translation catalog. Flat dict keyed by dotted namespace so both
languages for a given string live next to each other -- keeps them from
drifting apart the way two separate per-language files would.

See CONCEPT_WEB.md M14 for the scoping decision behind this mechanism."""

from __future__ import annotations

CATALOG: dict[str, dict[str, str]] = {
    "nav.dashboard": {"de": "Dashboard", "en": "Dashboard"},
    "nav.library": {"de": "Bibliothek", "en": "Library"},
    "nav.settings": {"de": "Einstellungen", "en": "Settings"},
    "footer.github": {"de": "GitHub-Repository", "en": "GitHub repository"},
    "footer.donate": {"de": "Spenden", "en": "Donate"},
    "cli.auth.login_success": {
        "de": "Login erfolgreich, Session gespeichert.",
        "en": "Login successful, session saved.",
    },
}
