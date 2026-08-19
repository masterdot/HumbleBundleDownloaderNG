"""DE/EN translation catalog. Flat dict keyed by dotted namespace so both
languages for a given string live next to each other -- keeps them from
drifting apart the way two separate per-language files would.

A handful of entries embed static, developer-authored HTML (e.g. `<code>`,
`<strong>`, links with a hardcoded href) rather than splitting a sentence
into several catalog keys around each tag -- word order differs enough
between German and English that stitching fragments back together gets
unnatural fast. Templates render those with `{{ t("...") | safe }}`. Never
route user-supplied data through `t()` + `| safe`.

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
    "cli.auth.check_ok": {
        "de": "OK - {count} Bestellungen gefunden.",
        "en": "OK - {count} orders found.",
    },
    "cli.config.unknown_key": {
        "de": "Unbekannter Schluessel '{key}', erlaubt: {allowed}.",
        "en": "Unknown key '{key}', allowed: {allowed}.",
    },
    "cli.config.set_saved": {
        "de": "{key} = {value} gespeichert ({path}).",
        "en": "{key} = {value} saved ({path}).",
    },
    "cli.config.unknown_lang": {
        "de": "Unbekannte Sprache '{value}', erlaubt: {allowed}.",
        "en": "Unknown language '{value}', allowed: {allowed}.",
    },
    "cli.list.found_count": {
        "de": "\n{count} Dateien gefunden.",
        "en": "\n{count} files found.",
    },
    "cli.sync.no_items": {
        "de": "Keine Dateien zu verarbeiten (Bibliothek leer oder Filter zu eng).",
        "en": "No files to process (library empty or filter too narrow).",
    },
    "cli.sync.total_summary": {
        "de": "{count} Dateien, {gib:.2f} GiB gesamt.",
        "en": "{count} files, {gib:.2f} GiB total.",
    },
    "cli.sync.verify_summary": {
        "de": "{succeeded} verifiziert, {failed} fehlgeschlagen/fehlend.",
        "en": "{succeeded} verified, {failed} failed/missing.",
    },
    "cli.sync.download_summary": {
        "de": "{succeeded} heruntergeladen, {skipped} uebersprungen (bereits vorhanden).",
        "en": "{succeeded} downloaded, {skipped} skipped (already present).",
    },
    "cli.sync.circuit_breaker": {
        "de": (
            "Circuit Breaker ausgeloest: zu viele 403/429-Antworten. Lauf abgebrochen -- "
            "pruefe, ob der Cookie noch gueltig ist (`hbdl auth check`), bevor du erneut startest."
        ),
        "en": (
            "Circuit breaker tripped: too many 403/429 responses. Run aborted -- check "
            "whether the cookie is still valid (`hbdl auth check`) before starting again."
        ),
    },
    "cli.sync.warnings_heading": {
        "de": "{count} mit Warnung (Datei behalten):",
        "en": "{count} with a warning (file kept):",
    },
    "cli.sync.failed_heading": {
        "de": "{count} fehlgeschlagen:",
        "en": "{count} failed:",
    },
    "cli.web.missing_deps": {
        "de": "Web-Abhaengigkeiten fehlen. Installiere sie mit `pip install hbdl[web]`.",
        "en": "Web dependencies are missing. Install them with `pip install hbdl[web]`.",
    },
    # Shared across dashboard.html and settings.html.
    "shared.dest_label": {"de": "Bibliotheks-Zielordner", "en": "Library destination folder"},
    # error.* -- shared between the web settings form and the CLI (both hit
    # the identical validation cases against config.STRATEGIES/LANGUAGES).
    "error.unknown_strategy": {
        "de": "Unbekannte Strategie '{value}', erlaubt: {allowed}.",
        "en": "Unknown strategy '{value}', allowed: {allowed}.",
    },
    "error.workers_min": {
        "de": "workers muss mindestens 1 sein.",
        "en": "workers must be at least 1.",
    },
    "error.workers_not_integer": {
        "de": "workers muss eine ganze Zahl sein.",
        "en": "workers must be an integer.",
    },
    # error.auth.* -- AuthError.key values (see auth.py). str(exc) stays
    # German (used for logs); these are what the display layer shows instead.
    "error.auth.playwright_missing": {
        "de": (
            "playwright ist nicht installiert. `pip install hbdl[dev]` bzw. "
            "`playwright install chromium` ausfuehren."
        ),
        "en": "playwright is not installed. Run `pip install hbdl[dev]` or `playwright install chromium`.",
    },
    "error.auth.login_window_closed": {
        "de": (
            "Login-Fenster wurde geschlossen oder die Anmeldung wurde nicht "
            "innerhalb von 5 Minuten abgeschlossen."
        ),
        "en": "Login window was closed, or the login wasn't completed within 5 minutes.",
    },
    "error.auth.cookie_not_found_after_login": {
        "de": "Login schien erfolgreich, aber der Cookie '{cookie_name}' wurde nicht gefunden.",
        "en": "Login appeared to succeed, but the '{cookie_name}' cookie wasn't found.",
    },
    "error.auth.cookie_not_in_file": {
        "de": "Kein '{cookie_name}'-Cookie in {path} gefunden.",
        "en": "No '{cookie_name}' cookie found in {path}.",
    },
    "error.auth.no_login_found": {
        "de": (
            "Kein Login gefunden. Fuehre `hbdl auth login` aus, oder uebergib "
            "--cookie / --cookie-file / setze HBDL_COOKIE."
        ),
        "en": "No login found. Run `hbdl auth login`, or pass --cookie / --cookie-file / set HBDL_COOKIE.",
    },
    "error.auth.cookie_invalid": {
        "de": "Cookie ungueltig oder abgelaufen -- `hbdl auth login` erneut ausfuehren.",
        "en": "Cookie invalid or expired -- run `hbdl auth login` again.",
    },
    # library.status.* -- shared by _status_badge.html (deduped out of
    # _column_file.html / _flat_list.html, which used to carry an identical
    # if/elif block each).
    "library.status.downloaded": {"de": "heruntergeladen", "en": "downloaded"},
    "library.status.failed": {"de": "fehlgeschlagen", "en": "failed"},
    "library.status.running": {"de": "laeuft", "en": "running"},
    "library.status.open": {"de": "offen", "en": "open"},
    "library.no_files": {"de": "Keine Dateien.", "en": "No files."},
    "library.no_contents": {"de": "Keine Inhalte.", "en": "No content."},
    "library.no_results": {"de": "Keine Treffer.", "en": "No results."},
    "library.file_count": {"de": "{n} Dateien", "en": "{n} files"},
    "library.search_heading": {
        "de": 'Suche: "{query}" ({count} Treffer)',
        "en": 'Search: "{query}" ({count} results)',
    },
    "library.filter_heading": {
        "de": "Filter: {label} ({count} Treffer)",
        "en": "Filter: {label} ({count} results)",
    },
    "library.no_bundles_cached": {
        "de": 'Keine Bundles im Cache -- fuehre `hbdl sync`/`hbdl list` aus oder "Aktualisieren".',
        "en": 'No bundles cached yet -- run `hbdl sync`/`hbdl list`, or "Refresh".',
    },
    "library.back_to_columns": {"de": "Zurueck zur Spaltenansicht", "en": "Back to column view"},
    "library.title": {"de": "Bibliothek - hbdl", "en": "Library - hbdl"},
    "library.search_placeholder": {
        "de": "Suche ueber die gesamte Bibliothek...",
        "en": "Search the entire library...",
    },
    "library.empty_catalog_message": {
        "de": (
            "Noch kein Katalog-Cache vorhanden. Fuehre <code>hbdl list</code> oder "
            "<code>hbdl sync</code> (auch mit <code>--dry-run</code>) einmal aus, um die "
            'Bibliothek zu ermitteln -- oder <button class="filter-btn" type="button" '
            'hx-post="/library/refresh" hx-target="#library-main" hx-swap="innerHTML">'
            "jetzt aktualisieren</button>."
        ),
        "en": (
            "No catalog cache yet. Run <code>hbdl list</code> or <code>hbdl sync</code> "
            "(optionally with <code>--dry-run</code>) once to discover the library -- or "
            '<button class="filter-btn" type="button" hx-post="/library/refresh" '
            'hx-target="#library-main" hx-swap="innerHTML">refresh now</button>.'
        ),
    },
    "filter.ebooks_aria": {"de": "Ebook-Formate", "en": "Ebook formats"},
    "filter.ebooks_label": {"de": "Ebooks:", "en": "Ebooks:"},
    "filter.no_ebooks_cached": {"de": "(keine Ebooks im Cache)", "en": "(no ebooks cached)"},
    "filter.games_aria": {"de": "Spiele-Systeme", "en": "Game platforms"},
    "filter.games_label": {"de": "Spiele/Software:", "en": "Games/software:"},
    "filter.no_games_cached": {
        "de": "(keine Spiele/Software im Cache)",
        "en": "(no games/software cached)",
    },
    "filter.all": {"de": "Alle", "en": "All"},
    "login.status_ok": {"de": "Login vorhanden", "en": "Logged in"},
    "login.status_none": {"de": "Kein Login", "en": "No login"},
    "login.last_attempt_failed": {
        "de": "Letzter Versuch fehlgeschlagen: {error}",
        "en": "Last attempt failed: {error}",
    },
    "login.embedded_heading": {
        "de": "Login im eingebetteten Browserfenster",
        "en": "Login in the embedded browser window",
    },
    "login.embedded_hint": {
        "de": (
            "Startet einen Browser im Container -- komplett in der GUI, kein "
            "Terminal noetig. Copy-Paste in das Fenster funktioniert direkt."
        ),
        "en": (
            "Starts a browser inside the container -- entirely in the GUI, no "
            "terminal needed. Copy-paste into the window works directly."
        ),
    },
    "login.cli_alt_summary": {
        "de": "Alternative: Login lokal per Kommandozeile",
        "en": "Alternative: log in locally via the command line",
    },
    "login.cli_alt_hint": {
        "de": (
            "Falls du lieber ein natives Browserfenster auf diesem Rechner nutzt "
            "(eigener Passwort-Manager, Authenticator-App): oeffnet ein echtes "
            "Browserfenster ausserhalb des Containers."
        ),
        "en": (
            "If you'd rather use a native browser window on this machine (your "
            "own password manager, authenticator app): opens a real browser "
            "window outside the container."
        ),
    },
    "login.cli_alt_reload_hint": {
        "de": "Danach diese Seite neu laden -- der Login wird automatisch erkannt.",
        "en": "Then reload this page -- the login is detected automatically.",
    },
    "login.cookie_alt_summary": {
        "de": "Alternative: Session-Cookie manuell einfuegen",
        "en": "Alternative: paste the session cookie manually",
    },
    "login.cookie_label": {
        "de": "Session-Cookie (_simpleauth_sess, aus dem eigenen Browser)",
        "en": "Session cookie (_simpleauth_sess, from your own browser)",
    },
    "login.cookie_placeholder": {"de": "Cookie-Wert", "en": "Cookie value"},
    "login.cookie_save_button": {"de": "Cookie speichern", "en": "Save cookie"},
    "login.vnc_starting_hint": {
        "de": (
            "Browser startet im Container -- melde dich im eingebetteten Fenster an "
            "(inkl. Captcha/2FA falls noetig). Kann ein paar Sekunden dauern, bis das "
            "Bild erscheint."
        ),
        "en": (
            "Browser is starting inside the container -- log in via the embedded "
            "window (including captcha/2FA if needed). May take a few seconds for "
            "the picture to appear."
        ),
    },
    "login.vnc_iframe_title": {"de": "Login-Browser", "en": "Login browser"},
    "login.vnc_instructions": {
        "de": (
            "Melde dich im Fenster oben an. Copy-Paste (Cmd/Strg+V) funktioniert direkt "
            "im Fenster -- klicke zuerst in das Zielfeld (z.B. E-Mail), dann normal "
            "einfuegen."
        ),
        "en": (
            "Log in via the window above. Copy-paste (Cmd/Ctrl+V) works directly "
            "inside the window -- click into the target field first (e.g. email), "
            "then paste normally."
        ),
    },
    "login.vnc_start_button": {"de": "Login im Browser starten", "en": "Start login in browser"},
    "settings.tab_config": {"de": "Konfiguration & Login", "en": "Configuration & Login"},
    "settings.tab_about": {"de": "Über & Spenden", "en": "About & Donate"},
    "settings.title": {"de": "Einstellungen - hbdl", "en": "Settings - hbdl"},
    "settings.config_heading": {"de": "Konfiguration", "en": "Configuration"},
    "settings.saved_badge": {"de": "gespeichert", "en": "saved"},
    "settings.workers_label": {
        "de": "Parallele Downloads (workers)",
        "en": "Parallel downloads (workers)",
    },
    "settings.strategy_label": {"de": "Download-Strategie", "en": "Download strategy"},
    "settings.cookie_file_label": {
        "de": "Cookie-Datei (optional, Netscape cookies.txt)",
        "en": "Cookie file (optional, Netscape cookies.txt)",
    },
    "settings.save_button": {"de": "Speichern", "en": "Save"},
    "sse.item_error_badge": {"de": "Fehler", "en": "Error"},
    "job.discovering": {"de": "Ermittle Bibliothek...", "en": "Discovering library..."},
    "job.running": {"de": "Laeuft ({n} Dateien)", "en": "Running ({n} files)"},
    "job.paused": {"de": "Pausiert ({n} Dateien)", "en": "Paused ({n} files)"},
    "job.stopped": {"de": "Gestoppt", "en": "Stopped"},
    "job.done": {"de": "Fertig", "en": "Done"},
    "job.error": {"de": "Fehler: {error}", "en": "Error: {error}"},
    "job.ready": {"de": "Bereit", "en": "Ready"},
    "job.pause_button": {"de": "Pause", "en": "Pause"},
    "job.stop_button": {"de": "Stop", "en": "Stop"},
    "job.resume_button": {"de": "Fortsetzen", "en": "Resume"},
    "job.restart_button": {"de": "Erneut starten", "en": "Restart"},
    "job.start_button": {"de": "Start", "en": "Start"},
    "dashboard.title": {"de": "Dashboard - hbdl", "en": "Dashboard - hbdl"},
    "dashboard.config_dir_label": {"de": "Config-Verzeichnis", "en": "Config directory"},
    "dashboard.data_dir_label": {"de": "Daten-Verzeichnis", "en": "Data directory"},
    "dashboard.login_session_label": {"de": "Login-Session", "en": "Login session"},
    "dashboard.session_present_badge": {"de": "vorhanden", "en": "present"},
    "dashboard.session_missing_badge": {"de": "kein Login gefunden", "en": "no login found"},
    "dashboard.see_settings_prefix": {"de": "-- siehe", "en": "-- see"},
    "dashboard.sync_job_heading": {"de": "Sync-Job", "en": "Sync job"},
    "dashboard.progress_label": {"de": "Fortschritt:", "en": "Progress:"},
    "about.title": {"de": "Über & Spenden - hbdl", "en": "About & Donate - hbdl"},
    "about.heading": {"de": "Über hbdl", "en": "About hbdl"},
    "about.origin_heading": {"de": "Entstehungsgeschichte", "en": "Origin story"},
    "about.origin_text": {
        "de": (
            "Dieses Projekt ist aus einem alten Pascal-Downloader entstanden. Ich wollte den "
            "Download meiner Humble-Bundle-Bibliothek schon lange komfortabler haben -- da "
            "sammelt sich sehr schnell sehr viel an. Durch meine Programmiererfahrung und mit "
            "KI-Unterstützung lässt sich mittlerweile auch als Einzelperson umsetzen, was "
            "frueher fuer ein Ein-Personen-Projekt zu groß und zu aufwaendig gewesen waere."
        ),
        "en": (
            "This project grew out of an old Pascal downloader. I'd wanted a more "
            "comfortable way to download my Humble Bundle library for a long time -- it "
            "piles up fast. Between my programming background and AI assistance, a solo "
            "developer can now pull off what used to be too big and too much effort for a "
            "one-person project."
        ),
    },
    "about.contribute_heading": {"de": "Mitmachen", "en": "Contributing"},
    "about.contribute_text": {
        "de": (
            "Fehler gefunden oder eine Funktion vermisst? Bitte im Issue-Tracker auf GitHub "
            "melden -- Bug-Reports und Feature-Wuensche sind beide willkommen:"
        ),
        "en": (
            "Found a bug or missing a feature? Please report it in the GitHub issue "
            "tracker -- both bug reports and feature requests are welcome:"
        ),
    },
    "about.outlook_heading": {
        "de": "Ausblick: wohin soll das Projekt?",
        "en": "Outlook: where is this heading?",
    },
    "about.outlook_intro": {
        "de": (
            "hbdl soll langfristig das zentrale Element einer kleinen, selbstgehosteten "
            "Medienbibliothek werden -- mit Anbindung an spezialisierte Apps fuer die "
            "jeweiligen Inhalte:"
        ),
        "en": (
            "In the long run, hbdl is meant to become the central piece of a small, "
            "self-hosted media library -- feeding into specialized apps for each kind of "
            "content:"
        ),
    },
    "about.outlook_audiobookshelf": {"de": "für Hörbücher", "en": "for audiobooks"},
    "about.outlook_calibreweb": {"de": "für Ebooks", "en": "for ebooks"},
    "about.outlook_jellyfin": {"de": "(oder ähnlich) für MP3/FLAC", "en": "(or similar) for MP3/FLAC"},
    "about.outlook_games": {
        "de": (
            "Fuer <strong>Spiele</strong> wird noch nach einer guten Loesung gesucht -- evtl. "
            '<a href="https://github.com/rommapp/romm" target="_blank" rel="noopener">RomM</a>. '
            "Gesucht ist im Grunde eine WebGUI, die plattformuebergreifende Spiele "
            "(Windows/Linux/macOS/Android) sauber nebeneinander darstellen kann, idealerweise "
            "mit ordentlich gescrapten Metadaten/Assets. Vorschlaege sind willkommen -- gerne "
            "als Issue."
        ),
        "en": (
            "For <strong>games</strong>, a good solution is still being sought -- maybe "
            '<a href="https://github.com/rommapp/romm" target="_blank" rel="noopener">RomM</a>. '
            "What's needed is basically a web GUI that can cleanly display cross-platform "
            "games (Windows/Linux/macOS/Android) side by side, ideally with well-scraped "
            "metadata/assets. Suggestions are welcome -- feel free to open an issue."
        ),
    },
    "about.donate_heading": {"de": "Spenden", "en": "Donate"},
    "about.donate_text": {
        "de": "Wenn dir hbdl nuetzlich ist, kannst du das Projekt ueber GitHub Sponsors unterstuetzen:",
        "en": "If hbdl is useful to you, you can support the project via GitHub Sponsors:",
    },
}
