*[English](README.md) | [Deutsch](README.de.md)*

# HumbleBundleDownloaderNG

Eine neue Version eines Batch-Downloaders für Humble Bundle.

Das vollständige Konzept (Architektur, Datenmodell, Meilensteine) steht in
[CONCEPT.md](CONCEPT.md), was bereits gebaut und behoben wurde in
[CHANGELOG.md](CHANGELOG.md). Dieses README beschreibt die alltägliche
Nutzung des aktuell Implementierten.

## Verwandte Projekte

Dies ist eine eigenständige Implementierung, kein Fork, baut aber auf Ideen
früherer Humble-Bundle-Downloader auf:

- [jimmckeeth/HumbleBundleDownloader](https://github.com/jimmckeeth/HumbleBundleDownloader) —
  das ursprüngliche Projekt in dieser Werkzeug-Linie.
- [Don-Swanson/HumbleBundleDownloader](https://github.com/Don-Swanson/HumbleBundleDownloader) —
  dessen Nachfolger.

## Status

Implementiert:

- **M1 — Auth & Discovery** (nur lesend): `hbdl auth login`, `hbdl auth check`,
  `hbdl list`.
- **M2 — Direct-Download-Warteschlange**: `hbdl sync` lädt jede Datei über
  resumierbare, hash-verifizierte HTTP-Downloads herunter, nachverfolgt in
  einem lokalen SQLite-Manifest, sodass wiederholte Läufe bereits verifizierte
  Dateien überspringen.
- **M3 — Robustheits-Härtung**: ein Circuit Breaker bricht den gesamten Lauf
  nach wiederholten 403/429-Antworten ab, statt ein gedrosseltes/abgelaufenes
  Konto stillschweigend weiter zu belasten; `hbdl sync --verify-only` hasht
  bereits heruntergeladene Dateien ohne jeden Netzwerk-Download erneut gegen
  das Manifest.
- **M4 — BitTorrent v1**: `--strategy {auto,direct,torrent}`. `auto`/`torrent`
  speichern die `.torrent`-Datei dort, wo der Download sonst landen würde,
  wann immer eine verfügbar ist (selbst im bevorzugten Torrent-Client öffnen)
  und fallen sonst auf einen Direct-Download zurück; `direct` ignoriert die
  Torrent-Option grundsätzlich. Der eigentliche Download des Inhalts über
  BitTorrent (Client-Handoff oder eingebettete Engine) ist für v1 bewusst
  nicht im Scope — siehe CONCEPT.md Abschnitt 7 für die späteren, optionalen
  Ausbaustufen.

Alle Meilensteine aus CONCEPT.md sind jetzt implementiert und wurden gegen
ein echtes Konto (92 Bestellungen, ~2700 Dateien) durchgespielt. Dieser Lauf
hat zwei echte Bugs rund um veraltete API-Metadaten bei älteren Bundles
aufgedeckt und behoben — Details siehe [CHANGELOG.md](CHANGELOG.md).

## Einrichtung

```bash
uv venv .venv
uv pip install -e ".[dev]" --python .venv/bin/python
.venv/bin/playwright install chromium   # einmalig, fuer `auth login` noetig
```

## Nutzung

Einmalig einloggen (öffnet ein echtes Browserfenster — Login inkl. Captcha/2FA
erledigst du selbst; hbdl liest anschließend nur den resultierenden
Session-Cookie aus):

```bash
hbdl auth login
```

Prüfen, ob die Session funktioniert:

```bash
hbdl auth check
```

Alles in der Bibliothek auflisten (Dry Run, kein Download):

```bash
hbdl list
hbdl list --format json > library.json
```

Auf einer Headless-Maschine ohne Display: `auth login` überspringen und
stattdessen direkt einen Cookie übergeben (siehe CONCEPT.md Abschnitt 2 für
das Netscape-`cookies.txt`-Format):

```bash
hbdl list --cookie-file cookies.txt
hbdl list --cookie "$HBDL_COOKIE"
```

Alles herunterladen:

```bash
hbdl sync --dest ~/HumbleLibrary
```

`hbdl sync` erneut auszuführen ist sicher und günstig — bereits
heruntergeladene, hash-verifizierte Dateien werden übersprungen (nachverfolgt
in einem lokalen SQLite-Manifest, nicht nur durch Vertrauen auf das
Dateisystem). Nach Plattform filtern, oder ohne Schreibvorgänge vorab prüfen:

```bash
hbdl sync --platform windows,ebook
hbdl sync --dry-run
```

Integrität des bereits Vorhandenen prüfen, ohne etwas herunterzuladen:

```bash
hbdl sync --verify-only
```

BitTorrent bevorzugen, wo verfügbar (v1: speichert die `.torrent`-Datei für
Dateien mit dieser Option, lädt den Rest direkt), oder einen Modus fest
erzwingen:

```bash
hbdl sync --strategy auto      # Default
hbdl sync --strategy direct    # immer HTTP, ignoriert Torrent-Optionen
hbdl sync --strategy torrent   # .torrent speichern wo verfuegbar, sonst Direct-Fallback
```

## Entwicklung

```bash
.venv/bin/python -m pytest
```

Tests laufen vollständig offline gegen aufgezeichnete/sanitisierte
Fixture-JSONs in `tests/fixtures/` — kein echtes Humble-Bundle-Konto nötig.

## Lizenz

[MIT](LICENSE).
