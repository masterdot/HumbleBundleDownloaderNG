*[English](CONCEPT.md) | [Deutsch](CONCEPT.de.md)*

# Konzept: HumbleBundleDownloaderNG

## 1. Ziel & Scope

Ein Python-CLI-Tool, das sich bei humblebundle.com authentifiziert, die komplette Spiele-/Ebook-Bibliothek des Accounts ermittelt und alle Dateien lokal herunterlädt. Zwei Download-Strategien werden unterstützt:

- **Direkt-Download** über eine verwaltete Warteschlange (Queue mit Nebenläufigkeit, Resume, Integritätsprüfung).
- **BitTorrent** als Alternative, sofern für eine Datei verfügbar.

Das Tool spricht ausschließlich die JSON-API von Humble Bundle an (nicht die gerenderte HTML-Bibliotheksseite `/home/library`), da die API stabiler und einfacher zu parsen ist.

## 2. Auth

**Primärer Weg: geführtes Playwright-Login.**

`hbdl auth login` öffnet ein echtes, sichtbares Chromium-Fenster (Playwright) und navigiert zur Humble-Bundle-Login-Seite. Der Nutzer gibt dort selbst seine Zugangsdaten ein und löst Captcha/2FA manuell — das Tool greift an dieser Stelle nicht ein. Sobald die Weiterleitung auf `/home` erkannt wird, liest das Tool den Session-Cookie `_simpleauth_sess` automatisch aus dem Browserkontext aus und speichert ihn lokal (verschlüsselt oder zumindest mit restriktiven Dateirechten, `chmod 600`).

**Warum kein vollautomatisches Login mit Username/Passwort im Tool:** Humble Bundle sichert `/processlogin` mit reCAPTCHA ab. Ein Tool könnte das nur über bezahlte Captcha-Solver-Dienste umgehen — das widerspricht klar der Absicht des Anbieters und ist nicht vertretbar. Der Playwright-Ansatz vermeidet dieses Problem vollständig, da der Mensch die Interaktion mit Captcha/2FA übernimmt, während das Tool nur das Ergebnis (den Cookie) übernimmt.

**Fallback für Headless-/Server-Betrieb** (kein lokales Display verfügbar): manuelle Cookie-Übergabe via
- `--cookie-file PATH` (Netscape-`cookies.txt`-Format, kompatibel mit Browser-Export-Extensions),
- `--cookie VALUE` (roher `_simpleauth_sess`-Wert),
- Env-Var `HBDL_COOKIE` / `HBDL_COOKIE_FILE`,
- oder `cookie_file`-Eintrag in der Config-Datei.

Jeder API-Request muss zusätzlich zum Cookie den Header `X-Requested-By: hb_android_app` mitschicken, sonst wird er von Humble Bundle abgelehnt.

Beim Start führt `auth.py` einen günstigen Validierungs-Call (`GET /api/v1/user/order`) aus und bricht bei 401/403 sofort mit klarer Fehlermeldung ab ("Cookie ungültig/abgelaufen — `hbdl auth login` erneut ausführen"), statt tief im Discovery-Lauf zu scheitern.

## 3. Architektur / Modulaufbau

`src/`-Layout mit `pyproject.toml`, installierbar per `pipx`/`uv tool`:

```
HumbleBundleDownloaderNG/
├── pyproject.toml
├── CONCEPT.md
├── README.md
├── src/
│   └── hbdl/
│       ├── __init__.py
│       ├── __main__.py          # `python -m hbdl`
│       ├── cli.py               # typer-Kommandobaum
│       ├── config.py            # Config-Datei + Env-Var-Auflösung, XDG-Pfade
│       ├── auth.py              # Playwright-Login, Cookie-Fallbacks, HttpClient
│       ├── api.py               # Wrapper für Order-Liste / Order-Details
│       ├── models.py            # DownloadItem, Order, Subproduct Dataclasses
│       ├── catalog.py           # Discovery: Orders -> flache DownloadItem-Liste
│       ├── downloader/
│       │   ├── __init__.py
│       │   ├── direct.py        # HTTP-Download-Queue/Worker-Pool
│       │   ├── torrent.py       # .torrent-Fetch (v1: nur speichern)
│       │   └── strategy.py      # Direct-vs-Torrent-Entscheidung pro Item
│       ├── state.py             # lokale SQLite-Manifest für Idempotenz
│       └── progress.py          # tqdm-basiertes Reporting
└── tests/
    ├── test_catalog.py
    ├── test_direct_downloader.py
    └── fixtures/                # sanitisierte, aufgezeichnete JSON-Responses
```

Datenablage (via `platformdirs`, plattformübergreifend):
- Config: `~/.config/hbdl/config.toml`
- Gespeicherter Auth-Cookie: `~/.config/hbdl/session.json` (restriktive Rechte)
- State/Manifest: `~/.local/share/hbdl/state.sqlite`
- Heruntergeladene Dateien: benutzerdefiniertes `--dest`, Default `./HumbleLibrary`

Entry Point: `pyproject.toml` → `[project.scripts] hbdl = "hbdl.cli:main"`.

## 4. Datenmodell

```python
@dataclass(slots=True)
class DownloadItem:
    gamekey: str
    human_name: str          # Bundle-/Produktname, für Ordnerbenennung
    subproduct_name: str     # z.B. "Half-Life 2"
    platform: str            # "windows" | "mac" | "linux" | "ebook" | "android" | ...
    variant_name: str        # download_struct[].name, z.B. "Installer" / "MOBI"
    filename: str
    url: str                 # signierte Web-URL (TTL-begrenzt)
    url_fetched_at: datetime # für TTL-Staleness-Checks
    file_size: int
    md5: str | None
    sha1: str | None
    torrent_url: str | None  # None, falls keine BitTorrent-Option
    dest_path: Path          # einmalig berechnet
```

Da die API keinen stabilen Content-Hash unabhängig von der URL liefert, dient `(gamekey, subproduct_name, platform, variant_name, filename)` als stabiler Identity-Key für den lokalen State — nicht die URL, da diese bei jedem Fetch wechselt (TTL).

Ordnerstruktur: `{dest}/{human_name}/{platform}/{filename}`, mit Sanitisierung von Dateisystem-kritischen Zeichen.

## 5. Discovery-Flow

1. `GET /api/v1/user/order` → Liste aller `gamekey`s.
2. Für jeden Gamekey (nebenläufig, aber gedrosselt — siehe §10): `GET /api/v1/order/{gamekey}` → vollständige Order-Details.
3. `subproducts[].downloads[].download_struct[]` jeder Order zu einer flachen Liste von `DownloadItem`s zusammenfassen.

`hbdl list` bzw. `hbdl sync --dry-run` geben diese Liste nur aus/serialisieren sie, ohne etwas herunterzuladen — nützlich, um das Tool gegen den echten Account zu testen, bevor Bytes geschrieben werden.

## 6. Direkter Download (Queue)

- **Nebenläufigkeit**: `concurrent.futures.ThreadPoolExecutor` (kein asyncio nötig — I/O-lastig, aber überschaubare Worker-Zahl, siehe §10).
- **Resume**: HTTP-`Range`-Requests gegen eine `.part`-Sidecar-Datei; liefert der Server `200` statt `206` (Range nicht unterstützt / Datei geändert), Neustart von vorn.
- **Retry/Backoff**: exponentielles Backoff (capped, max. ~5 Versuche) bei Verbindungsfehlern/Timeouts/5xx; `429` respektiert `Retry-After`.
- **Integritätsprüfung**: nach Abschluss Stream-Hash (bevorzugt sha1, sonst md5) gegen API-Wert vergleichen; bei Mismatch löschen + begrenzt retryen, danach als harter Fehler in der Laufzusammenfassung melden.
- **Idempotenz**: SQLite-State pro Identity-Key (Status `pending`/`downloading`/`verified`/`failed`); bei erneutem `hbdl sync` werden bereits `verified`-Dateien übersprungen (inkl. Stat-Check auf Disk, falls extern gelöscht).
- **TTL-Handling**: signierte URLs sind zeitlich begrenzt. Ist `url_fetched_at` älter als ein konservativer Schwellwert (~10 min, da die exakte TTL nicht dokumentiert ist) oder liefert ein Download-Versuch 403/abgelaufene Signatur, wird die Order-Detail-Route für genau diesen Gamekey neu geladen und die URL ersetzt, bevor erneut versucht wird.
- **Progress**: `tqdm`-Gesamtbalken (Bytes über alle Dateien) plus optionale Pro-Datei-Balken im Verbose-Modus.

## 7. BitTorrent-Pfad

**v1 (dieser Entwurf, umzusetzen zuerst):** Ist `torrent_url` gesetzt, lädt das Tool nur die `.torrent`-Datei selbst (klein, über denselben Direct-Download-Pfad) nach `{dest}/{...}/{filename}.torrent` herunter und informiert den Nutzer, diese mit dem eigenen Torrent-Client zu öffnen. Kein Download des eigentlichen Inhalts über BitTorrent in v1.

Begründung: keine neuen schweren Abhängigkeiten, funktioniert auf jeder Plattform sofort, deckt den Kernwunsch ("BitTorrent als Alternative anbieten") vollständig ab, ohne Komplexität vorzuziehen, die nicht gebraucht wird.

**Spätere, optionale Ausbaustufen (nicht Teil von v1):**
- *v1.5*: Handoff an einen lokal installierten Client (Transmission/qBittorrent) über dessen CLI/RPC, damit der `.torrent` automatisch hinzugefügt wird statt manuell geöffnet zu werden.
- *v2*: `libtorrent`-Python-Bindings als optionales Extra (`hbdl[torrent]`) für einen vollständig eigenständigen Download-Workflow ohne externen Client — mit dem Hinweis, dass `libtorrent` eine kompilierte C++-Extension mit realer Plattform-Packaging-Problematik ist (nicht für jede Python-Version/OS/Architektur als Wheel verfügbar, insbesondere Apple Silicon), weshalb dies bewusst optional und zeitlich hinten angestellt ist.

Nicht jede Datei hat eine BitTorrent-Option (v.a. Ebooks/Audio sind meist HTTP-only, Torrents kommen vor allem bei großen Spiele-Installern vor) — die Strategie-Wahl ist daher pro Datei zu prüfen, kein globaler Modus-Schalter.

## 8. Strategie-Wahl

`--strategy {auto,direct,torrent}` (Default: `auto`).

- `auto`: bevorzugt Torrent, wenn `torrent_url` vorhanden ist (v1: `.torrent` speichern); sonst Direct-Download. Damit ist `auto` auch in v1 sinnvoll, ohne dass der Nutzer nachdenken muss.
- `direct`: erzwingt für alle Dateien Direct-Download, auch wenn eine Torrent-Option existiert (sinnvoll bei getaktetem/gefiltertem Netz).
- `torrent`: erzwingt für alle Dateien mit `torrent_url` das Torrent-Verhalten; Dateien ohne Torrent-Option fallen automatisch auf Direct zurück (kein Abbruch).

Konfigurierbarer Default in `config.toml` (`default_strategy = "auto"`), per CLI-Flag überschreibbar.

## 9. CLI-Oberfläche

Vorschlag mit `typer`:

```
hbdl auth login                    # geführtes Playwright-Login, speichert Cookie
hbdl auth check                    # validiert gespeicherten/übergebenen Cookie
hbdl list [--format table|json]    # nur Discovery, kein Download (Dry Run)
hbdl sync                          # Hauptkommando: Discovery + Download
  --dest PATH                      # Default ./HumbleLibrary oder Config-Default
  --cookie-file PATH
  --cookie VALUE
  --strategy {auto,direct,torrent} # Default auto
  --workers N                      # Default 3
  --platform windows,linux,ebook   # optionaler Filter
  --product "Namens-Substring"     # optionaler Filter
  --dry-run                        # nur Plan ausgeben, keine Writes
  --verify-only                    # bestehende Dateien gegen Manifest neu hashen
hbdl config show / set KEY VALUE
```

`hbdl sync` ist das eine Kommando, das die meisten Nutzer brauchen; die anderen dienen der Diagnostizierbarkeit und kontrolliertem Testen.

## 10. Fehlerbehandlung & Rate-Limiting

Humble Bundle ist ein reales, bezahltes Konto eines Drittanbieters — Zurückhaltung ist eine harte Design-Vorgabe, kein Nice-to-have:

- Default `--workers 3` sowohl für Order-Detail-Fetches während der Discovery als auch für Downloads.
- Die Discovery-Phase (potenziell Dutzende Order-Detail-Calls) läuft über denselben gedrosselten Worker-Pool, nicht ungebremst parallel — das ist das API-Hammering-verdächtigste Traffic-Muster.
- Globale Retry/Backoff-Policy im gemeinsamen `HttpClient`: exponentielles Backoff mit Jitter, begrenzte Versuche (~5), `Retry-After` bei 429 respektieren, Circuit-Breaker-artiger Abbruch des gesamten Laufs bei wiederholten 429/403 (lieber laut scheitern als kaputt weiterhämmern).
- Einzelne Datei-Fehler (404, Hash-Mismatch nach Retries) brechen nicht den ganzen Lauf ab — werden gesammelt, am Ende als Zusammenfassung ausgegeben ("312 erfolgreich, 2 fehlgeschlagen: ..."); erneutes `hbdl sync` holt dank Idempotenz nur die fehlenden/fehlgeschlagenen Dateien nach.
- Kein verstecktes Hintergrund-Scheduling — reines, manuell gestartetes CLI-Tool, kein Daemon.

## 11. Vorgeschlagene Abhängigkeiten

- `requests` (statt `httpx`) — kein Async-Bedarf durch Thread-Pool-Modell; `requests.adapters.HTTPAdapter` + `urllib3.Retry` liefert Retry/Backoff nahezu geschenkt.
- `typer` für die CLI (auf `click` aufbauend, typgetriebene Kommandos, gute `--help`-Ausgabe).
- `playwright` für den geführten Login (inkl. `playwright install chromium` als einmaliger Setup-Schritt).
- `tqdm` für Progress-Balken.
- `platformdirs` für plattformübergreifende Config-/State-Pfade.
- `tenacity` (optional) für deklarative Retry/Backoff-Policies statt Handrolling.
- stdlib `http.cookiejar.MozillaCookieJar` für Netscape-Cookie-Datei-Parsing (Fallback-Pfad).
- stdlib `sqlite3` für das State-Manifest.
- Optionales Extra `hbdl[torrent]` → `libtorrent` (nur v2).
- Dev/Test: `pytest`, `pytest-mock`, `responses` (HTTP-Mocking für `requests`) — Tests laufen offline gegen Fixture-JSON, nie gegen die echte API.

## 12. Build-Meilensteine

1. **M1 — Auth + Discovery** (read-only, am sichersten zuerst gegen den echten Account zu testen): `auth.py` (Playwright-Login), `api.py`, `catalog.py`, `models.py`, `hbdl auth login/check`, `hbdl list`. Ergebnis: vollständige `DownloadItem`-Liste, keine Dateischreibvorgänge.
2. **M2 — Direct-Download-Queue**: `downloader/direct.py`, `state.py`, `progress.py`, `hbdl sync --strategy direct`. Retry/Backoff, resumierbare Range-Requests, Hash-Verifikation, idempotente Wiederholungsläufe. Kernnutzen des Tools.
3. **M3 — TTL-/Robustheits-Härtung**: URL-Refresh bei Ablauf, Circuit-Breaker bei wiederholten 429/403, Fehlerzusammenfassung, `--verify-only` und `--dry-run`.
4. **M4 — BitTorrent v1 (Save-only)**: `downloader/torrent.py`, `--strategy torrent/auto`-Verdrahtung in `strategy.py`.
5. **M5 (optional, später) — Client-Handoff**: Transmission/qBittorrent-CLI-Integration.
6. **M6 — Politur**: Config-Datei-Support, Filter (`--platform`, `--product`), Packaging (`pyproject.toml` final, `[torrent]`-Extra-Grundgerüst), README-Nutzungsdoku.
7. **M7 (optional, später) — `libtorrent`-v2**, nur falls M4/M5 für den Bedarf nicht ausreichen.

Jeder Meilenstein sollte primär gegen aufgezeichnete, sanitisierte Fixture-JSONs testbar sein — echte Cookie-Tests gegen den Live-Account sollten die Ausnahme bleiben, nicht die Regel.
