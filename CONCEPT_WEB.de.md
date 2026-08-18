*[English](CONCEPT_WEB.md) | [Deutsch](CONCEPT_WEB.de.md)*

# Konzept: hbdl Web-UI + Docker-Betrieb

Ergänzt `CONCEPT.md` (das CLI-Kernkonzept, unverändert gültig) um die Web-Oberfläche
und den Docker-Betrieb. Eigenständiges Dokument, damit `CONCEPT.md`s Scope (§1: reines
CLI-Tool) nicht verwässert wird. Nummerierung setzt bei den Meilensteinen aus
`CONCEPT.md` §12 fort (M8+).

## 1. Ziel & Grundsatzentscheidungen

- Docker-Container mit Weboberfläche, steuert denselben Downloader wie die CLI.
- Zielordner ("library") frei per Volume-Mount wählbar, ohne Image-Rebuild.
- Keinerlei Humble-Bundle-Daten im Container selbst — Config, Session, Manifest,
  heruntergeladene Dateien ausschließlich über Volumes.
- CLI-Nutzung bleibt über die gesamte Umstrukturierung hinweg voll funktionsfähig,
  auch als reines `pip install hbdl` ohne Web-Extras.
- Frontend: schlank, serverseitig gerendert (htmx/Alpine.js), kein Node-Build.
- Bibliotheks-Browser: mehrstufige Finder-Spalten (Bundle → Subprodukt → Datei),
  abgeleitet direkt aus den bestehenden `DownloadItem`-Feldern, keine neue Hierarchie-Ebene.
- Auth in Docker: Playwright-Login im Container über Xvfb + VNC/noVNC, eingebettet
  in die Weboberfläche; Cookie-Paste bleibt schnellerer Fallback.
- Pause = "nach aktueller Datei" (keine neuen Downloads starten, laufende fertig
  werden lassen), kein Eingriff in den Byte-Streaming-Loop.
- Umsetzung etappenweise: Etappe 1 (M8–M11), Etappe 2 (M12), Etappe 3 (M13–M14),
  mit Zwischen-Checkpoints.

Details zur Architektur (Ordnerstruktur, Config/State-Schema, Job-Steuerung,
Auth/VNC-Subsystem, Web-UI-Routen, Docker/Volumes) siehe der ursprüngliche
Implementierungsplan; wird hier bei Bedarf vertieft, sobald einzelne Teile umgesetzt sind.

## 2. Meilensteine

- **M8** — Web-Grundgerüst: `web/app.py`, `hbdl web serve`, `[web]`-Extra, Docker
  `cli`/`web`-Stages, `XDG_*`/`HBDL_DEST`-Volume-Story end-to-end verifiziert. ✅ erledigt
- **M9** — Config-Anbindung: `Config.load()`-Lücke schließen, `Config.save()`,
  `hbdl config show/set`, Settings-Seite (nur Formular, noch kein Auth-UI). ✅ erledigt
- **M10** — Katalog-Cache + Bibliotheks-Browser: `catalog_items`-Tabelle,
  `sync_catalog_cache`, Query-Helper, 3-Spalten-Router, Live-Suche, Filter-Buttons. ✅ erledigt
- **M11** — Job-Manager + SSE-Progress (nur Start, noch kein Pause). ✅ erledigt
- **M12** — Pause/Stop + `STATUS_DOWNLOADING`. ✅ erledigt
- **M13** — Docker-VNC-Login (Xvfb/x11vnc/noVNC, Captcha-Spike zuerst). 🔶 Infrastruktur
  fertig und technisch verifiziert, echter Login-Versuch (Captcha-Spike) steht noch aus.
- **M14** — i18n: DE/EN-Sprachumschaltung fuer CLI + Web-UI, zweisprachige
  Kern-Docs (README, CONCEPT.md, CONCEPT_WEB.md). ✅ erledigt
- **M15** — Compose-Härtung (WAL, Lock-Datei), README-Docker-Abschnitt.

## Entscheidungsprotokoll

### 2026-08-17 – M8 abgeschlossen: Web-Grundgerüst

- **FastAPI statt Flask**, sync `def`-Routen (FastAPI verteilt sie automatisch auf
  einen Threadpool). Begründung: passt zur bestehenden synchronen/Thread-Pool-
  Architektur (`CONCEPT.md` §11), liefert OpenAPI/Pydantic "for free", `StreamingResponse`
  für SSE ohne Zusatz-Dependency.
- **`hbdl web serve`** importiert `hbdl.web` erst innerhalb der Kommando-Funktion
  (`try/except ImportError` → Hinweis auf `pip install hbdl[web]`), damit
  `pip install hbdl` ohne Extras weiterhin frei von FastAPI/uvicorn/jinja2 bleibt
  — gleiches Muster wie der bestehende optionale Playwright-Import in `auth.guided_login`.
- **Stolperfalle entdeckt**: die installierte Starlette-Version erwartet
  `Jinja2Templates.TemplateResponse(request, name, context)` (Request zuerst) statt
  der älteren `TemplateResponse(name, context)`-Reihenfolge. Falsche Reihenfolge führt zu
  einem irreführenden `TypeError: cannot use 'tuple' as a dict key` tief in Jinja2s
  Template-Cache, nicht zu einem offensichtlichen Signatur-Fehler. Gilt für alle
  künftigen Routen mit `TemplateResponse`.
- **`XDG_CONFIG_HOME`/`XDG_DATA_HOME` verifiziert** (nicht nur angenommen): lokal via
  `platformdirs` bestätigt, zusätzlich end-to-end im laufenden `hbdl:web`-Docker-Container
  mit gemounteten Volumes getestet (`/config`, `/data`, `/library` korrekt aufgelöst über
  `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, neue `HBDL_DEST`-Env-Var).
- **`config.resolve_dest(cli_value)`** neu (Präzedenz: CLI-Flag > `HBDL_DEST`-Env >
  `config.toml` > `DEFAULT_DEST`), in `cli.py sync` verdrahtet. Schließt die
  `Path.cwd()`-Falle von `DEFAULT_DEST`, die im Container bedeutungslos wäre.
  Implementierungsdetail: `resolve_dest` übergibt `CONFIG_FILE` explizit an
  `Config.load(path=CONFIG_FILE)`, statt sich auf `Config.load()`s eigenen
  Default-Parameter zu verlassen — Default-Parameter werden einmalig bei der
  Funktionsdefinition gebunden, ein `monkeypatch.setattr(config, "CONFIG_FILE", ...)`
  in Tests würde sie sonst nicht erreichen.
- **Docker**: Multi-Stage-`Dockerfile` mit `cli`- und `web`-Target (VNC-Stack folgt erst
  in M13, um das Image bis dahin schlank zu halten). Beide Targets bauen und laufen
  verifiziert durch (`docker build --target cli|web`, Container-Testlauf mit allen drei
  Volumes).
- Kleine Beobachtung, kein Handlungsbedarf: `starlette.testclient` meldet eine
  Deprecation-Warnung zugunsten von `httpx2` — aktuell noch funktionsfähig, in einer
  späteren Etappe ggf. nachziehen, falls `httpx2` sich etabliert.

### 2026-08-17 – M9 abgeschlossen: Config-Anbindung + Settings-Seite

- **`Config.load()`-Lücke geschlossen**: `hbdl list`/`hbdl sync` lesen `workers`
  jetzt tatsächlich aus `config.toml` (vorher nur `cookie_file` je gelesen, siehe
  `CONCEPT.md`-Diskrepanz zu §9); `sync` zusätzlich `strategy`. Präzedenz überall:
  CLI-Flag > `config.toml` > eingebauter Default.
- **`hbdl config show`/`hbdl config set KEY VALUE`** neu (in `CONCEPT.md` §9 vorgesehen,
  nie gebaut) — nutzt dieselbe `Config.save()` wie die Web-Settings-Seite (`POST
  /settings`), eine einzige Serialisierungs-Quelle für CLI und Web.
- **Ernsthafter Bug gefunden und behoben, bevor er in Produktion gegangen wäre**: sowohl
  `Config.load(path: Path = CONFIG_FILE)` als auch das neue `Config.save(path: Path =
  CONFIG_FILE)` hatten `CONFIG_FILE` als Parameter-*Default* gebunden — Python bindet
  Default-Werte einmalig bei der Funktionsdefinition, nicht bei jedem Aufruf. Jeder
  Aufruf ohne explizites `path=` (z. B. `config.Config.load()` in `cli.py`/`settings.py`)
  ignorierte deshalb ein späteres `monkeypatch.setattr(config, "CONFIG_FILE", ...)`
  komplett und schrieb/las **die echte, produktive config.toml auf der Entwicklungs-
  maschine** — während der Testläufe für diesen Meilenstein tatsächlich passiert
  (die reale `~/Library/Application Support/hbdl/config.toml` wurde mit Testwerten
  überschrieben, danach bereinigt). Fix: `path: Path | None = None` als Parameter,
  Auflösung auf den aktuellen Modul-Global `CONFIG_FILE` **im Funktionskörper** (dort
  ist es ein normaler, bei jedem Aufruf neu ausgewerteter Namens-Lookup, kein
  eingefrorener Default). Gilt für Produktionsbetrieb unkritisch (dort wird `CONFIG_FILE`
  einmalig beim Prozessstart über `XDG_CONFIG_HOME` korrekt gesetzt, es gibt kein
  Rebinding zur Laufzeit), war aber ein reales Test-Isolations- und potenzielles
  Footgun-Risiko für jeden künftigen Callsite. **Zu prüfen für spätere Etappen**:
  `state.py`s `StateStore.__init__(path: Path = config.STATE_DB)` und `auth.py`s
  `_save_session`/`_load_saved_session` (`path: Path = config.SESSION_FILE`) haben
  denselben Default-Bindungsstil — bisher nicht angefasst, da alle bestehenden
  Aufrufstellen den Pfad ohnehin immer explizit übergeben (kein bare-call-Muster wie
  bei `Config.load()`), aber bei künftigen Änderungen im Hinterkopf behalten.
- Settings-Seite (`GET/POST /settings`) validiert `strategy` gegen `STRATEGIES` und
  `workers >= 1` serverseitig, gibt bei Fehlern 422 mit Fehlermeldung zurück statt
  fehlerhaft zu speichern.

### 2026-08-17 – M10 abgeschlossen: Katalog-Cache + Bibliotheks-Browser

- **`catalog_items`-Tabelle** in `state.sqlite` (additiv, gleiche DB wie `downloads`).
  `catalog.sync_catalog_cache(store, items)` ersetzt den Cache bei jedem Lauf komplett
  (DELETE + Bulk-INSERT in einer Transaktion) statt nur zu mergen -- damit verschwinden
  zurückgegebene/entfernte Bundles auch aus dem Browser, statt als Leichen liegen zu
  bleiben. Aufgerufen aus `hbdl list` **und** `hbdl sync` (vor einer eventuellen
  `--platform`-Filterung, damit der Cache immer die volle Bibliothek zeigt, nicht nur
  das, was dieser eine Sync-Lauf gerade heruntergeladen hat) -- bewusst nicht bei jedem
  Login automatisch, um keine überraschenden API-Aufrufe auszulösen.
- **Zweiter, gravierenderer Fund derselben Bug-Klasse aus M9** (eingefrorene
  Parameter-Defaults): `state.py`s `StateStore.__init__`/`open_store` und `auth.py`s
  `_save_session`/`_load_saved_session` hatten exakt dasselbe Muster
  (`path: Path = config.STATE_DB` bzw. `config.SESSION_FILE`). Diesmal real
  sicherheitsrelevant, nicht nur ein Test-Isolations-Ärgernis: die neue
  `web/deps.py::get_store()`-Dependency ruft `open_store()` **ohne** Pfad auf (der
  erste "bare call" dieser Funktion im gesamten Code) -- ohne Fix hätte das bei jedem
  Request die echte, produktive `state.sqlite` auf der Entwicklungsmaschine
  geöffnet/beschrieben, und ein Test für die "Kein Login"-Fehlerbehandlung von
  `/library/refresh` hätte über `auth.resolve_session()` → `_load_saved_session()`
  sogar die echte, private Session-Cookie-Datei der Entwicklungsmaschine gelesen.
  Beide mit demselben Muster wie in M9 behoben (`path: Path | None = None`,
  Modul-Global-Lookup im Funktionskörper). **Lehre für den Rest des Projekts**: jede
  Funktion mit `path: Path = config.IRGENDWAS`-Parameter-Default ist verdächtig,
  sobald sie irgendwo *ohne* explizites `path=` aufgerufen wird -- vor dem naechsten
  bare call an so einer Stelle erst pruefen.
- **Spalten-Browser** (Bundle → Subprodukt → Datei) ohne neue Datenmodell-Ebene: die
  3 Stufen kommen direkt aus den vorhandenen `DownloadItem`-Feldern
  (`gamekey`/`human_name` → `subproduct_name` → `platform`+`variant_name`+`filename`).
  htmx-Fragmente pro Drilldown-Stufe (`#col2-onward`/`#col3-onward` werden bei jedem
  Klick auf eine übergeordnete Spalte komplett ersetzt, damit ein Wechsel des Bundles
  automatisch nachgelagerte Spalten zurücksetzt), Zeilen-Selektion per
  `hx-on:click`-Inline-Handler (kein Alpine noetig fuer dieses einzelne Feature, auch
  wenn Alpine als Asset schon vendored ist).
- **Filter-Buttons** zweizeilig, wie vom Nutzer gewünscht: "Ebooks" (Formate, aus
  `distinct_ebook_formats()` = `variant_name` bei `platform='ebook'`) und
  "Spiele/Software" (Systeme, aus `distinct_game_platforms()` = `platform != 'ebook'`),
  dynamisch aus dem tatsächlichen Katalog-Inhalt berechnet, nicht hartkodiert.
- **htmx 2.0.4 + Alpine.js 3.x + htmx-sse-Extension** vendored nach `web/static/`
  (kein Node-Build, passt zum schlanken-Frontend-Entscheid) -- SSE-Extension bereits
  jetzt mitgeholt, wird aber erst in M11 tatsächlich eingebunden.
- `/library/refresh` (POST) stößt einen synchronen, blockierenden `build_catalog()`+
  `sync_catalog_cache()`-Lauf an -- bewusst einfach für v1, die "Aktualisieren"-Button;
  ein nicht-blockierender Job mit Fortschrittsanzeige ist Gegenstand von M11.

### 2026-08-17 – M11 abgeschlossen: Job-Manager + SSE-Progress (Start)

- **`download_all()`-Kern umgebaut** auf schrittweise Futures-Vergabe (`deque` +
  begrenzte `in_flight`-Menge statt "alle Futures sofort einreichen"), mit neuen
  optionalen Parametern `pause_gate`/`stop_event` (Default: immer offen/nie gesetzt,
  bestehender CLI-Aufruf unverändert kompatibel) sowie `progress_factory` (injizierbarer
  Fortschritts-Sink statt fest verdrahtetem `ProgressReporter`, neues `progress.ProgressSink`-
  Protocol). Der Byte-Streaming-Loop in `_download_one` bleibt komplett unangetastet, wie
  im Plan gefordert. Pause parkt den Lauf (`pause_gate.wait()`, laufende Downloads werden
  fertig, keine neuen gestartet); Stop leert die Warteschlange (keine neuen Starts mehr),
  lässt aber bereits laufende Downloads noch fertig werden und sammelt deren Ergebnisse
  ein, statt sie stillschweigend zu verwerfen. Beides jetzt schon mit gezielten,
  deterministischen Tests abgesichert (`responses.add_callback` als Sperre statt
  Sleep-basiertem Racing), obwohl Pause/Stop erst in M12 über die UI ansteuerbar werden.
- **`web/jobs.py::JobManager`**: ein Job gleichzeitig, läuft in einem Hintergrund-Thread
  (`build_catalog` → `sync_catalog_cache` → `download_all`), Status
  `IDLE/DISCOVERING/RUNNING/DONE/ERROR`. Fehler (z. B. `AuthError` ohne Login) werden
  abgefangen und als `ERROR`-Status mit Meldung im Snapshot/Event gespiegelt, nicht
  verschluckt. **Noch keine Pause/Resume/Stop-Methoden** auf `JobManager` selbst -- bewusst
  nicht gebaut, solange nichts sie aufruft (kommt mit M12 zusammen mit den Dashboard-Buttons).
- **`web/events.py::EventBus`**: einfaches In-Process-Pub/Sub (`queue.Queue` pro
  Subscriber), Publisher ist der `JobManager`, Subscriber die SSE-Route.
- **SSE-Framing von Hand** (`event: TYP\ndata: ...\n\n`, mehrzeilige Payloads korrekt
  mit einem `data: `-Prefix pro Zeile) statt einer SSE-Bibliothek -- passt zur
  ursprünglichen Entscheidung gegen `sse-starlette` (siehe M8-Eintrag zu FastAPI/SSE).
  htmx-sse-Extension übernimmt das Verdrahten im Frontend rein deklarativ
  (`sse-connect`/`sse-swap`), keine eigene JS-Logik nötig.
- **Wichtiger Test-Infrastruktur-Fund**: `TestClient.stream()` über den In-Process-
  ASGI-Transport dieser Starlette-Version hängt sich bei einem absichtlich nie
  endenden Generator (wie dem SSE-Endpoint) komplett auf -- die Anfrage liefert nicht
  einmal ein Response-Objekt zurück, weil der Transport offenbar versucht, die
  *gesamte* Antwort zu puffern, bevor er etwas zurückgibt. Empirisch verifiziert
  (Debug-Skript, das nie über "opening stream..." hinauskam). Fix: die Route-Funktion
  direkt aufrufen und genau einen Chunk aus `StreamingResponse.body_iterator` ziehen
  -- der ist trotz synchronem Generator in `dashboard.py` intern ein *async* Generator
  (Starlette wrapped sync Generatoren automatisch via Threadpool-Iteration), daher
  `asyncio.run(...)` mit `__anext__()`/`aclose()` statt normalem `next()`. Deterministisch,
  kein Hängen, testet trotzdem den echten Pfad subscribe → publish → render → SSE-Framing.
- **Zweiter Fund derselben "vergessene Isolation"-Kategorie wie in M9/M10, diesmal in
  eigenen Tests statt in Produktionscode**: zwei neue Tests (`test_job_manager_rejects_
  concurrent_start`, sowie ein Web-Dashboard-Test) ließen den Hintergrund-Thread nach
  `release.set()` weiterlaufen, ohne auf `is_running() == False` zu warten, bevor die
  Testfunktion (und damit `monkeypatch`/`tmp_path`) endet. Da diese Tests `config.STATE_DB`
  gar nicht erst isoliert hatten, öffnete der noch laufende Job-Thread tatsächlich die
  echte, produktive `state.sqlite` auf der Entwicklungsmaschine (leere `catalog_items`-
  Tabelle dort angelegt, keine echten Daten verloren -- `downloads` mit den echten 1334
  Zeilen blieb unberührt). Nach Fix (STATE_DB isolieren **und** vor Testende aktiv auf
  Job-Abschluss warten) fünf aufeinanderfolgende volle Testläufe ohne Aenderung am
  Datei-Zeitstempel der echten `state.sqlite` verifiziert. **Wiederkehrende Lehre über
  M9-M11 hinweg**: bei jedem neuen Test, der einen Hintergrund-Thread gegen `hbdl`-Code
  startet, IMMER (a) `config.STATE_DB`/`config.CONFIG_FILE`/Ziel-Pfade explizit isolieren
  UND (b) aktiv auf den Thread-Abschluss warten, bevor die Testfunktion zurückkehrt --
  nicht nur das Signal zum Weiterlaufen geben und optimistisch weitermachen.
- End-to-End im echten `hbdl:web`-Docker-Container verifiziert: Dashboard zeigt
  "Bereit"-Button, Start ohne Login läuft durch `DISCOVERING` und landet sauber (kein
  500) bei `ERROR` mit "Kein Login gefunden".

### 2026-08-17 – M12 abgeschlossen: Pause/Stop + STATUS_DOWNLOADING

- **`JobManager`** um `pause()`/`resume()`/`stop()` erweitert, auf den bereits in M11
  gebauten `pause_gate`/`stop_event`-Parametern von `download_all()`. Neue Zustände
  `PAUSED`/`STOPPED` im `JobState`-Enum. Pause nur aus `RUNNING` gültig, Resume nur aus
  `PAUSED`, Stop aus jedem aktiven Zustand (`DISCOVERING`/`RUNNING`/`PAUSED`) --
  ungültige Übergänge werfen `RuntimeError`, von den Routen abgefangen (kein 500 bei
  einem Klick, der mit dem tatsächlichen Job-Fortschritt kollidiert, z. B. "Pause"
  kurz nachdem der Job schon fertig wurde).
- **`STATUS_DOWNLOADING`** wird jetzt in `_download_one` geschrieben (vor dem
  Retry-Loop) -- rein informativ für die UI, keine Kontrollfluss-Änderung. Neue
  `StateStore.reconcile_stale_downloading()`, einmalig beim Start von `create_app()`
  aufgerufen, setzt verwaiste `downloading`-Zeilen (Container-Absturz mitten im
  Transfer) kosmetisch auf `pending` zurück.
- **Ernster, real reproduzierter Nebenfund**: `StateStore` erlaubte trotz
  `check_same_thread=False` keinen wirklich *gleichzeitigen* Zugriff mehrerer Threads
  auf dieselbe SQLite-Connection -- `check_same_thread=False` schaltet nur Pythons
  eigene Selbe-Thread-Prüfung ab, macht die Connection aber nicht thread-sicher für
  echte Parallelität. `download_all()`s Worker-Pool übergibt seit jeher denselben
  `store` an mehrere gleichzeitige Worker-Threads; das war also ein latenter Bug im
  bestehenden Code, nicht neu durch M12 eingeführt. Er wurde aber erst durch den neuen
  `STATUS_DOWNLOADING`-Zusatz-Write (zwei `upsert()`-Aufrufe pro Datei statt einem,
  beide potenziell gleichzeitig mit anderen Items) zuverlässig genug getriggert, um in
  einem flakigen Test aufzufallen (`sqlite3.OperationalError: bad parameter or other
  API misuse`, ca. 1 von 10 Läufen). Per Reproduktionsskript (60 Wiederholungen)
  verifiziert, dann behoben: `threading.Lock` um **jeden** Zugriff auf `self._conn` in
  `StateStore` (inklusive `fetchall()` der Cursor-Ergebnisse, die nur gültig sind,
  solange kein anderer Thread dieselbe Connection benutzt). Nach dem Fix 60/60
  Wiederholungen und zehn volle Testsuite-Läufe sauber. **Praktische Relevanz über
  Tests hinaus**: das hätte im echten Web-Betrieb mit `workers > 1` (Standard ist 3)
  gelegentlich zu fehlgeschlagenen Downloads durch SQLite-Fehler geführt, nicht nur zu
  einem Test-Problem -- guter Fund, bevor die VNC-Login-Etappe reale Downloads über die
  Web-UI ermöglicht.
- End-to-End im echten Docker-Container verifiziert: `/jobs/current/pause`,
  `/resume`, `/stop` antworten sauber (200, kein 500) auch wenn kein Job läuft.

### 2026-08-18 – M13 (Teil 1): VNC-Login-Infrastruktur gebaut und verifiziert

- **`web/login_state.py::LoginState`**: eigene, bewusst simple State-Machine getrennt
  vom `JobManager` (`idle/running/success/error`, kein Progress/Queue-Konzept noetig) --
  ein einmaliger, kurzlebiger Vorgang (einmal einloggen, Cookie einsammeln), kein
  Download-Job. `guided_login()` selbst brauchte **keine einzige Code-Aenderung**: es
  startet ohnehin einen sichtbaren Chromium (`headless=False`), der auf das
  Prozess-`DISPLAY` rendert -- im Container Xvfbs `:99`.
- **`auth.save_manual_cookie()`** neu (duenner oeffentlicher Wrapper um `_save_session`)
  fuer den Cookie-Paste-Fallback in `web/routers/auth_web.py` -- beide Wege (VNC-Login
  und Cookie einfuegen) landen auf derselben Settings-Seite, `_login_area.html` zeigt
  je nach `LoginState`-Status Start-Button, eingebettetes VNC-iframe, Erfolg oder
  Fehler, per htmx-Polling (`hx-trigger="every 2s"`) waehrend `running`.
- **Docker `web`-Stage erweitert**: `xvfb x11vnc novnc websockify supervisor` per apt,
  `playwright install --with-deps chromium`, `docker/supervisord.conf` faehrt 4
  Programme hoch (`xvfb` → `x11vnc` → `novnc`/websockify auf :6080 → `hbdl-web` mit
  `DISPLAY=:99`). Image-Groesse **2.67GB** (ARM64/Apple-Silicon-Build) -- am oberen Rand
  der im Plan genannten 1-1.5GB-Schaetzung, aber im erwarteten Rahmen; der `cli`/`web`-
  Split bleibt die Antwort fuer alle, die das nicht brauchen.
- **`docker-compose.yml`**: Port 6080 nur an `127.0.0.1` gebunden (x11vnc laeuft mit
  `-nopw`, also ohne VNC-Passwort -- darf nie ueber den Host hinaus exponiert werden),
  mit Kommentar direkt im Compose-File dokumentiert.
- **End-to-End im echten Container technisch verifiziert** (nicht nur angenommen):
  `/healthz` und `http://localhost:6080/vnc.html` beide erreichbar, `POST
  /auth/login/start` liefert das VNC-iframe-Fragment, und im Container laeuft danach
  tatsaechlich ein echter Chromium-Prozess (per `/proc`-Scan bestaetigt, `ps` fehlt im
  Slim-Image) -- die komplette Kette Playwright → Xvfb → x11vnc → noVNC → Browser-iframe
  funktioniert mechanisch.
- **Noch offen, bewusst nicht von mir pruefbar**: ob der echte Login gegen die
  echte Humble-Bundle-Seite (inkl. Captcha/2FA) durch die eingebettete VNC-Ansicht
  tatsaechlich benutzbar ist und ob Humble Bundles Bot-/Automatisierungserkennung
  diesen Weg blockiert. Das ist genau der im Plan vorgesehene Spike vor dem Rest von
  M13/M14 -- braucht echte Zugangsdaten und visuelle/interaktive Pruefung, die nur der
  Nutzer selbst machen kann. Automatisierte Tests decken bewusst nur den gemockten
  `LoginState`/Routen-Teil ab (`tests/web/test_auth_web.py`), nicht die echte
  Xvfb/VNC/Captcha-Kette -- wie im urspruenglichen Plan explizit vorgesehen.

### 2026-08-18 – Bug-Fix: VNC-iframe wurde vom Status-Polling neu geladen

Vom Nutzer gemeldet: das eingebettete Login-Fenster "laedt sich staendig neu, keine
Eingabe moeglich" -- sah aus wie Verbindungsabbrueche. Ursache: das 2-Sekunden-Polling
fuer den Login-Status (`hx-trigger="every 2s"`) saß auf dem AEUSSEREN `#login-area`-Div
und ersetzte dessen komplettes `outerHTML` bei jedem Tick -- inklusive des VNC-iframes
selbst. Damit wurde die VNC-Verbindung alle zwei Sekunden neu aufgebaut, genau wie
beschrieben. Fix: das Polling sitzt jetzt auf einem kleinen, separaten
`#login-status-poll`-Div NEBEN dem iframe (nicht mehr darum herum), das nur sich selbst
ersetzt (`hx-target="this"`). Erst beim tatsaechlichen Statuswechsel (Erfolg/Fehler)
wird per htmx Out-of-Band-Swap (`hx-swap-oob="true"`) das gesamte `#login-area`
inklusive iframe ausgetauscht -- an dem Punkt ist das iframe ohnehin nicht mehr noetig.
Zwei Regressionstests ergaenzt (`tests/web/test_auth_web.py`), die genau das absichern:
das iframe darf im "running"-Status-Poll nicht erneut auftauchen.

### 2026-08-18 – Footer + Über/Spenden-Seite

Auf Nutzerwunsch: Footer auf jeder Seite (Copyright, Link zum Repository, Spenden-Link
zu GitHub Sponsors). Neue `/settings/about`-Seite (als zweiter "Tab" neben den
bestehenden Einstellungen, `_settings_tabs.html` verlinkt zwischen beiden) mit
Entstehungsgeschichte, Einladung zum Mitmachen ueber GitHub Issues, und einem Ausblick
auf geplante Integrationen (Audiobookshelf, Calibre-Web, Jellyfin, noch offene
Spiele-Loesung).

### 2026-08-18 – VNC-Clipboard-Autopaste + Docker-Disk-Zwischenfall

- **Clipboard-Fix, Versuch 1 (falsch)**: eigener Klon von noVNCs `vnc.html`
  (`hbdl-vnc.html`, Original bleibt unangetastet) mit einem zusaetzlichen Script, das
  auf ein natives `paste`-Event auf `document` gelauscht hat, in der Annahme, noVNC
  faengt Tastatureingaben ueber ein verstecktes `<textarea id="noVNC_keyboardinput">`
  ein. Vom Nutzer getestet: **funktionierte nicht**, Klemmbrett blieb leer.
- **Ursache gefunden**: `core/rfb.js` haengt die eigentliche Desktop-Tastatureingabe an
  ein `<canvas>`-Element (`this._keyboard = new Keyboard(this._canvas)`), nicht an das
  Textarea -- das ist nur fuer den separaten mobilen virtuellen-Tastatur-Button
  zustaendig. Ein `<canvas>` feuert grundsaetzlich **kein** `paste`-Event, egal wie es
  fokussiert ist -- mein Handler kam nie zum Zug.
- **Clipboard-Fix, Versuch 2 (funktioniert)**: statt auf `paste` zu lauschen, faengt
  das Script jetzt den Cmd/Strg+V-**Keydown** ab (den bekommt der Canvas normal, so
  liest auch noVNC selbst normale Tastatureingaben), liest das lokale Klemmbrett aktiv
  per `navigator.clipboard.readText()` aus (erlaubt, weil der Aufruf innerhalb einer
  echten Nutzer-Tastendruck-Geste passiert), schickt den Text per
  `RFB.clipboardPasteFrom()` an die Remote-Seite, und simuliert danach -- mit kurzer
  Verzoegerung, damit die Klemmbrett-Nachricht zuerst ankommt -- per `RFB.sendKey()`
  (oeffentliche, von noVNC selbst genutzte API) ein echtes Strg+V auf der Remote-Seite,
  damit die entfernte App den frisch gesetzten Inhalt auch tatsaechlich einfuegt. Der
  urspruengliche Keydown wird unterdrueckt (`preventDefault`/`stopPropagation` in der
  Capture-Phase, vor noVNCs eigenem Canvas-Handler), damit kein doppeltes Einfuegen
  passiert. Faellt bei fehlender Clipboard-Berechtigung auf ein einfaches
  durchgereichtes Remote-Strg+V zurueck, statt die Tastenkombination stillschweigend
  zu verschlucken. Rueckrichtung (Remote → lokal) weiterhin best-effort ueber
  `navigator.clipboard.writeText()`, Sidebar-Textarea bleibt als Fallback.
- **Clipboard-Fix, Versuch 3 (jetzt primärer Weg)**: Versuch 2 schlug beim Nutzer
  weiterhin fehl -- vermuteter (und plausibler) Grund: `navigator.clipboard.readText()`
  aus einem Cross-Origin-iframe heraus (VNC-Ansicht laeuft auf Port 6080, Elternseite
  auf 8000 -- unterschiedliche Origins) wird von Browsern haeufig ohne sichtbaren
  Hinweis schlicht verweigert. Statt weiter an der Clipboard-API zu drehen: komplett
  vermieden. Auf der Settings-Seite steht jetzt ein normales `<input>` neben dem
  iframe -- Einfuegen dort ist ein ganz normaler, berechtigungsfreier Browser-Paste
  (same-origin Textfeld). Der Inhalt wird per `postMessage()` (keine Berechtigung
  noetig) an das iframe geschickt, dort von `novnc-clipboard-autopaste.js`
  entgegengenommen (Origin-Check gegen Port 8000) und wie zuvor per
  `RFB.clipboardPasteFrom()` + simuliertem `RFB.sendKey()`-Strg+V in die Session
  injiziert. Versuch 2 (Keydown+Clipboard-API) bleibt als zusaetzlicher Best-Effort-Pfad
  bestehen, falls er in manchen Browsern doch funktioniert -- die Einfuege-Box ist aber
  jetzt der dokumentierte, verlaessliche Weg.
- **Clipboard-Fix, Versuch 3, ebenfalls nicht ausreichend**: Nutzer-Feedback nach
  Versuch 3 -- funktioniert weiterhin nicht zuverlaessig, Kontextmenu im Remote-
  Chromium teils kaputt, "sportlich" mit Fokus/Copy-Paste. Klare Ansage des Nutzers:
  komfortable, zuverlaessige Loesung gewuenscht, keine Cookie-Kopiererei, OTP/2FA per
  VNC-Copy-Paste ist ein echtes Problem (zeitkritisch). Frage: Login per CLI moeglich,
  Token danach "ziehen"?
- **Kurswechsel: CLI-Login lokal wird primaerer, empfohlener Weg.** Antwort: ja, und
  die Grundlage existierte bereits fast vollstaendig -- `hbdl auth login` (unveraendert,
  schon seit M1) oeffnet ein **echtes natives** Browserfenster auf dem Host-Rechner,
  nicht im Container. Normales OS-Copy-Paste, Passwort-Manager, Authenticator-Apps --
  keine VNC-Einschraenkungen ueberhaupt. Der einzige fehlende Baustein: dieselbe
  `session.json` muss dort landen, wo der Container sie erwartet. Da
  `docker-compose.yml`s `/config`-Volume bereits auf `./hbdl-config` im Host-
  Projektordner zeigt, reicht `XDG_CONFIG_HOME="$(pwd)/hbdl-config" hbdl auth login`
  lokal ausgefuehrt -- kein Kopieren, kein Cookie-Handling, der Container sieht die
  Datei automatisch ueber das geteilte Volume. Verifiziert: lokal geschriebene
  Test-Session wurde vom laufenden Container sofort korrekt gelesen.
  Neues `docker/login-locally.sh` kapselt das (findet `.venv/bin/hbdl` automatisch,
  setzt `XDG_CONFIG_HOME` korrekt).
- **Echter Bug dabei gefunden und behoben**: `_login_context()` liess einen
  fehlgeschlagenen VNC-Versuch **dauerhaft** als Fehlerstatus haengen, selbst nachdem
  spaeter (z.B. per CLI-Login oder Cookie-Paste) ein gueltiger Login zustande kam --
  die Datei auf der Platte wurde nur bei Status `IDLE` ueberhaupt geprueft. Fix: die
  on-disk-Session ist jetzt in jedem Nicht-"running"-Zustand die Quelle der Wahrheit,
  nicht der zuletzt im Speicher gehaltene Status. Regressionstest ergaenzt
  (`test_a_session_file_appearing_after_a_failed_attempt_overrides_the_stale_error`).
- **UI umgebaut**: "Login lokal per Kommandozeile" ist jetzt die klar hervorgehobene
  Empfehlung oben auf der Login-Karte. VNC-Login und Cookie-Paste sind beide in
  `<details>`-Elemente verschoben ("Alternative: ..."), eingeklappt per Default (VNC
  bleibt aufgeklappt waehrend ein Versuch laeuft). Die VNC-Infrastruktur (M13) bleibt
  bestehen -- fuer Faelle ohne jeden lokalen Zugriff auf den Docker-Host -- ist aber
  nicht mehr der beworbene Standardweg.
- **Echter Zwischenfall waehrend der Arbeit**: die Mac-Festplatte lief durch die vielen
  Rebuilds in dieser Session auf ca. 150MB frei (von 228GB) leer, was Docker/Colima
  mit I/O-Fehlern zum Absturz brachte -- erst nur beim Schreiben (Build schlug fehl),
  spaeter war die Colima-VM selbst so weit im I/O-Fehler-Zustand haengengeblieben, dass
  sogar `colima ssh` sofort fehlschlug (vermutlich Dateisystem-Beschaedigung durch
  Schreibversuche waehrend die Platte voll war). Kein Datenverlust (alle
  Humble-Bundle-Daten liegen in Volumes ausserhalb der VM), aber `colima restart` war
  noetig, um die VM wieder in einen sauberen Zustand zu bringen -- danach sofort
  wieder 12-19GB frei auf Host und VM.
- **`docker/rebuild.sh`** neu: `docker compose build && docker compose up -d &&
  docker image prune -f` in einem Schritt, damit alte Image-Layer nach jedem Rebuild
  automatisch aufgeraeumt werden (nur dangling/unbenannte Layer, ruehrt andere
  getaggte Images auf derselben Maschine nicht an). In `docker-compose.yml` als
  empfohlener Rebuild-Weg dokumentiert. **Lehre**: bei einem Projekt mit so vielen
  Docker-Rebuild-Iterationen wie diesem haette dieses Skript von Anfang an existieren
  sollen, nicht erst nachdem die Platte tatsaechlich vollgelaufen ist.

### 2026-08-18 – VNC richtig repariert: Same-Origin-Reverse-Proxy statt CLI-Login-Empfehlung

- **Klare Nutzeransage nach den drei Clipboard-Versuchen**: ausschliesslich GUI-Bedienung,
  keinerlei Konsolenbefehle fuer den Endnutzer -- explizite Kritik an der bisherigen
  spontanen Bug-Fix-Bug-Fix-Schleife, Aufforderung zu einem einmal gruendlich
  durchdachten Loesungsentwurf statt eines weiteren Rateversuchs. Zwei ehrliche Optionen
  zur Wahl gestellt: (a) kleiner lokaler Helferprozess (einmaliges Setup, danach GUI-only)
  vs. (b) VNC sauber reparieren, vollstaendig im Container, ganz ohne Host-Zusatzschritt.
  Nutzerentscheidung: **(b), VNC richtig reparieren.**
- **Eigentliche Ursache aller drei bisherigen Fehlschlaege identifiziert**: nicht die
  Clipboard-Mechanik selbst, sondern dass das VNC-iframe (`hbdl-vnc.html`) auf Port 6080
  lief, die restliche Oberflaeche auf 8000 -- zwei verschiedene Origins. Browser
  verweigern `navigator.clipboard`-Zugriff aus einem Cross-Origin-iframe meist ohne
  sichtbaren Hinweis; das erklaert, warum Versuch 2 (Keydown+Clipboard-API) beim Nutzer
  nie funktionierte, obwohl der Mechanismus grundsaetzlich richtig war.
- **Fix: kompletter Same-Origin-Reverse-Proxy** statt der separaten Port-6080-Origin.
  Neuer Router `web/routers/vnc_proxy.py`: `GET /vnc/{path:path}` reicht noVNCs statische
  Assets (`hbdl-vnc.html`, `app/*.js`, `core/*.js` etc.) synchron per `requests` an
  `http://127.0.0.1:6080/...` durch (Hop-by-Hop-Header wie `content-length` werden dabei
  bewusst nicht durchgereicht, da `requests` die Antwort schon entpackt hat). `WS
  /vnc/websockify` ist ein WebSocket-Relay (neue `websockets`-Abhaengigkeit, `[web]`-Extra)
  -- die einzige bewusste Async-Ausnahme im sonst rein synchronen Code (vgl. CONCEPT.md
  §11), sauber auf diese eine Route begrenzt.
- **noVNCs eigener `path`-Verbindungsparameter verifiziert** (durch Lesen von
  `app/ui.js` im laufenden Container, nicht blind angenommen): ist `host` leer (Default),
  baut noVNC die WebSocket-URL relativ zur aktuellen Dokument-URL
  (`new URL(path, location.href)`). Bei `hbdl-vnc.html` unter `/vnc/` reicht daher
  `?path=websockify` (ohne `vnc/`-Praefix) -- loest relativ zum `/vnc/`-Verzeichnis korrekt
  zu `/vnc/websockify` auf, passend zur neuen Proxy-Route. Bestaetigt zugleich, dass noVNC
  ohne explizit gesetztes `wsProtocols`-Handshake verbindet -- der WS-Proxy muss kein
  Sub-Protokoll aushandeln.
- **`novnc-clipboard-autopaste.js` vereinfacht**: die `postMessage`-Einfuege-Box (Versuch
  3) und die separate Paste-Box im Login-Template entfallen wieder -- zurueck zu einer
  bereinigten Version von Versuch 2 (Keydown+Clipboard-API), die jetzt Same-Origin laeuft
  und damit tatsaechlich Clipboard-Berechtigung bekommen sollte. Weniger uebereinandergelegte
  Mechanismen = auch ein moeglicher Kandidat dafuer, warum zuvor das Kontextmenu im
  eingebetteten Fenster kaputt war.
- **UI wieder umgebaut**: VNC-Login ist wieder der primaere, direkt sichtbare Weg (keine
  `<details>` mehr noetig, da jetzt der verlaessliche Pfad). "Login lokal per
  Kommandozeile" (`docker/login-locally.sh`) bleibt als `<details>`-Alternative fuer alle,
  die lieber ein natives Host-Browserfenster nutzen -- ist aber nicht mehr die Empfehlung.
  Cookie-Paste bleibt als dritte, niedrigschwellige `<details>`-Alternative bestehen.
- **`docker-compose.yml`**: Port 6080 wird nicht mehr nach aussen published (websockify
  laeuft weiterhin intern im Container auf 6080, ist von aussen aber gar nicht mehr
  erreichbar) -- kleiner Sicherheitsgewinn nebenbei, da der ungeschuetzte `-nopw`-VNC-Port
  vorher zumindest auf `127.0.0.1` erreichbar war.
- Neue Tests `tests/web/test_vnc_proxy.py`: HTTP-Proxy gegen einen lokalen
  `http.server`-Test-Server (Pfad/Query korrekt durchgereicht), WS-Proxy gegen einen
  lokalen `websockets`-Echo-Server (Frames unveraendert in beide Richtungen). Bestehender
  `test_auth_web.py`-Test auf die neue `/vnc/hbdl-vnc.html?path=websockify`-URL angepasst.
  Weiterhin bewusst ausserhalb automatisierter Tests: echtes Captcha-/Login-Verhalten und
  tatsaechliches Clipboard-Verhalten in einem echten Browser -- bleibt manuelle
  Verifikation durch den Nutzer, jetzt aber mit einer soliden technischen Begruendung,
  warum es eher funktionieren sollte, statt eines weiteren Rateversuchs.

### 2026-08-18 – M14 abgeschlossen: i18n (DE/EN) fuer CLI + Web-UI, zweisprachige Docs

- **Hintergrund**: die Web-UI soll spaeter als editierbarer Claude-Design-Canvas
  nachgebaut werden, um sie visuell zu ueberarbeiten, bevor die neue Version die
  aktuelle Implementierung ersetzt (eigener, spaeterer Schritt). Damit diese
  Ueberarbeitung nicht auf einer rein deutschen UI aufsetzt und die
  Uebersetzungsarbeit nicht doppelt anfaellt, wurde die Sprachumschaltung vorher
  eingebaut. Sprache ist eine globale App-Einstellung (persistiert in
  `config.toml`, kein Session-Cookie) -- explizite Scope-Entscheidung des Nutzers,
  ebenso dass die CLI mituebersetzt wird (nicht nur die Web-UI).
- **Neues Paket `src/hbdl/i18n/`**: `strings.py` traegt einen flachen
  `CATALOG: dict[str, dict[str, str]]` mit dotted keys, DE/EN je Eintrag
  nebeneinander (verhindert Drift zwischen den Sprachen). `__init__.py` bietet
  `t(key, **kwargs)` (Modul-globale Sprache, `str.format`-Interpolation),
  `t_count()`, `set_lang()`/`get_lang()`. Sprache ist bewusst ein einzelner
  Modul-Global statt durchgereichtem State -- hbdl ist Single-User/-Prozess, es
  gibt kein Multi-Tenant-Szenario mit Accept-Language-Verhandlung pro Request,
  das die zusaetzliche Plumbing rechtfertigen wuerde.
- **`t()`s `key`-Parameter ist positional-only** (`def t(key, /, **kwargs)`):
  ein frueher Versuch, `i18n.t("cli.config.set_saved", key=key, ...)`
  aufzurufen, kollidierte mit `t()`s eigenem `key`-Parameter
  (`TypeError: t() got multiple values for argument 'key'`), da Katalogeintraege
  selbst `{key}` als Platzhaltername verwenden wollten. Positional-only behebt
  das grundsaetzlich, statt an jeder betroffenen Stelle den Platzhalternamen zu
  aendern.
- **Web-Wiring**: `create_app()` registriert `t`/`lang` als Jinja-Globals
  (`app.state.templates.env.globals`), sodass jedes Template `{{ t("key") }}`
  nutzen kann, ohne dass jeder Router-Handler es einzeln in den Context packen
  muss. `base.html`s `<html lang="de">` wurde zu `<html lang="{{ lang() }}">`.
- **Alle 18 Jinja2-Templates** migriert. Die vier identischen
  Status-Badge-Bloecke (heruntergeladen/fehlgeschlagen/laeuft/offen) aus
  `_column_file.html` und `_flat_list.html` wurden dabei in eine gemeinsame
  Partial `_status_badge.html` zusammengefasst (`{% with status = f.status %}
  {% include "_status_badge.html" %}{% endwith %}`).
- **HTML in Katalogeintraegen, bewusst mit `| safe` gerendert**: ein paar
  Eintraege (z.B. `about.outlook_games`, `library.empty_catalog_message`)
  enthalten statisches, selbst verfasstes HTML (`<code>`, `<strong>`, Links mit
  fest codiertem href) statt den Satz an jeder Tag-Grenze in mehrere
  Katalog-Keys aufzuspalten -- die Wortstellung unterscheidet sich zwischen
  Deutsch und Englisch genug, dass wieder zusammengesetzte Fragmente schnell
  unnatuerlich klingen. Ausdruecklich niemals nutzerkontrollierte Daten ueber
  `t()` + `| safe` ausgeben.
- **Rohe `HTMLResponse` in `library.py`s `/refresh` durch echte Template-Response
  ersetzt** (`_auth_error.html`): die alte Fassung baute die AuthError-Message
  ungeeescaped in einen f-String -- kleiner nebenbei behobener Bug, da Jinja
  jetzt automatisch escaped.
- **CLI-Wiring**: Typer generiert `help=`-Texte einmalig beim Modul-Import,
  bevor `Config.load()` je gelaufen ist -- dynamische `--help`-Uebersetzung ist
  mit Typers Decorator-Architektur nicht sauber machbar. Entscheidung:
  `help=`-Texte bleiben bewusst statisch-englisch (als Referenzdokumentation),
  aber alle Laufzeit-Ausgaben (`typer.echo`/`typer.secho`) laufen ueber `t()`.
  `cli.py::main()` ruft `i18n.set_lang(config.resolve_lang())` ganz am Anfang
  auf, bevor `app()` dispatcht -- deckt damit auch `hbdl web serve` ab, da es
  ueber denselben Einstiegspunkt laeuft.
- **`AuthError` um optionales `key`/`key_kwargs` erweitert**, die bestehende
  deutsche `message` bleibt als `str(exc)`-Fallback fuer Logs/Tests unveraendert
  erhalten. Anzeige-Stellen (`cli.py`s vier `except auth.AuthError`-Bloecke,
  `library.py`s `/refresh`) nutzen `i18n.t(exc.key, **exc.key_kwargs) if exc.key
  else str(exc)`. Uebersetzt wird bewusst an der Anzeige-Grenze, nicht an der
  Raise-Stelle -- haelt `auth.py` frei von jedem i18n-Import/Sprach-Zustand.
- **`config.py`**: neues `Config.lang`-Feld (Default `"de"`, bestehende Nutzer
  sehen also keine Aenderung, bis sie aktiv umschalten), `LANGUAGES = ("de",
  "en")`, `resolve_lang(cli_value=None)` exakt analog zu `resolve_dest()`
  (Praezedenz: CLI-Flag > `HBDL_LANG`-Env > `config.toml` > Default). `hbdl
  config set lang en` funktioniert ueber denselben `CONFIG_KEYS`/`config_set`-
  Mechanismus wie `strategy`.
- **Sprachumschaltung in der Web-UI**: Schnell-Toggle im Topbar (`POST
  /settings/lang`, zwei Submit-Buttons DE/EN, echter Full-Page-Reload statt
  htmx-Fragment-Swap -- sonst blieben Nav/Footer/Seiteninhalt inkonsistent
  uebersetzt), plus ein vollstaendiges `<select name="lang">` im
  Settings-Formular ueber den bestehenden `settings_save()`-Flow.
- **Zweisprachige Kern-Docs**: Konvention `<name>.md` = Englisch (Standard),
  `<name>.de.md` = Deutsch. `README.md` war bereits Englisch, `README.de.md`
  neu ergaenzt. `CONCEPT.md` und `CONCEPT_WEB.md` enthielten bisher die
  deutschen Inhalte -- per `git mv` (bzw. schlichtem `mv`, da `CONCEPT_WEB.md`
  noch untracked war) zu `CONCEPT.de.md`/`CONCEPT_WEB.de.md` verschoben,
  danach frische englische `CONCEPT.md`/`CONCEPT_WEB.md` geschrieben. Alle
  sechs Dateien verlinken sich oben gegenseitig
  (`*[English](README.md) | [Deutsch](README.de.md)*`). LICENSE unangetastet,
  CHANGELOG.md bleibt bewusst englisch-only (Nutzerentscheidung).
- **Wie einen neuen String hinzufuegen**: Eintrag mit `de`/`en`-Wert in
  `src/hbdl/i18n/strings.py`s `CATALOG` ergaenzen (dotted-key-Namespace passend
  zum Kontext, z.B. `settings.*`, `library.status.*`), dann `t("dein.key")` im
  Template oder `i18n.t("dein.key", **kwargs)` im Python-Code aufrufen.
  `tests/test_i18n.py::test_every_catalog_entry_has_de_and_en` verhindert,
  dass ein Eintrag nur in einer Sprache existiert.
- **Wie eine neue Sprache hinzufuegen**: `config.LANGUAGES` erweitern, fuer
  jeden bestehenden `CATALOG`-Eintrag den neuen Sprachcode ergaenzen (der
  Vollstaendigkeits-Test greift nur `"de"`/`"en"` fest ab -- bei mehr als zwei
  Sprachen muesste er entsprechend erweitert werden), sowie das
  DE/EN-Umschalt-UI (Topbar-Formular, Settings-`<select>`) um die neue Option.

### 2026-08-19 – VNC-Clipboard: die eigentliche Root Cause gefunden (`window.UI` existierte nie wirklich)

- **Symptom nach dem Same-Origin-Proxy-Fix**: das Kontextmenue im VNC-Fenster
  funktionierte wieder, aber Cmd/Strg+V fuegte weiterhin einen alten Wert ein
  (einen bereits abgelaufenen OTP-Code) statt des aktuellen
  Zwischenablage-Inhalts -- ohne jeden Berechtigungs-Dialog und ohne
  Konsolenfehler, selbst nachdem ein `console.warn` im `catch`-Block
  ergaenzt worden war.
- **Root Cause**, gefunden durch Lesen von `/usr/share/novnc/hbdl-vnc.html`
  und `app/ui.js` im laufenden Container: das `UI`-Objekt von noVNC ist nur
  `export default UI` aus `app/ui.js`, importiert in den *Modul-Scope* des
  inline `<script type="module">` in `vnc.html`. Es wurde nie tatsaechlich
  `window.UI` zugewiesen -- jede bisherige Version von
  `novnc-clipboard-autopaste.js` (inklusive der aus dem Same-Origin-Fix)
  begann mit `if (!window.UI || !window.UI.rfb) return;`, was bei jedem
  einzelnen Tastendruck lautlos zutraf. Keine der Clipboard-Logiken lief je,
  der Keydown fiel unveraendert durch zu noVNCs eigenem Standard-Canvas-Handler,
  der ein rohes Strg+V an die Remote-X11-Session weiterreichte -- das erklaert
  sowohl den alten Wert (was auch immer zuletzt in der *Remote*-Zwischenablage
  stand) als auch das komplette Fehlen jeglicher Fehlermeldung (der Code-Pfad
  wurde nie erreicht).
- **Diagnose-Ansatz, auf Vorschlag des Nutzers**: statt eines weiteren
  Rate-Versuchs an der Clipboard-Berechtigung wurde das Problem in zwei
  unabhaengig testbare Haelften zerlegt. Zuerst noVNCs eigenen, bereits
  fertigen Zwischenablage-Mechanismus untersucht (`UI.openClipboardPanel()`
  oeffnet eine Sidebar mit `#noVNC_clipboard_text`, dessen natives
  `change`-Event `UI.clipboardSend()` aufruft, das das Textfeld liest und
  `UI.rfb.clipboardPasteFrom()` aufruft). Ein temporaerer Diagnose-Build
  fuegte einen sichtbaren "Zwischenablage synchronisieren"-Button hinzu, der
  genau diesen Pfad ansteuert plus ausfuehrliches Konsolen-Logging, wobei die
  automatische Cmd/Strg+V-Abfangung komplett entfernt wurde, damit ein
  normaler Strg+V sich wie Standard-noVNC verhaelt. Der Button zeigte zum
  ersten Mal einen echten Zwischenablage-Berechtigungs-Dialog -- was zur
  Entdeckung der `window.UI`-Luecke fuehrte, da die Guard-Klausel des Buttons
  getroffen und klar geloggt wurde.
- **Fix**: der bestehende `sed`-Patch-Schritt in `docker/Dockerfile` (der
  `vnc.html` zu `hbdl-vnc.html` klont) bekam eine weitere Ersetzung: `import
  UI from "./app/ui.js";` -> `import UI from "./app/ui.js"; window.UI = UI;`.
  Das ist der gesamte Fix -- `UI` ist jetzt wirklich global, und jede bereits
  vorhandene `window.UI`-Pruefung im JS laeuft tatsaechlich.
- **`novnc-clipboard-autopaste.js` wieder auf einen einzigen Tastendruck
  zurueckgebaut**: mit echtem `window.UI` wurde die automatische
  Cmd/Strg+V-Abfangung wieder eingebaut (`readText()` -> Sync in
  `#noVNC_clipboard_text` -> `UI.clipboardSend()` -> simuliertes Remote-
  Strg+V), vom Nutzer end-to-end bestaetigt. Der manuelle "Zwischenablage
  synchronisieren"-Button bleibt als sichtbarer Fallback fuer den Fall, dass
  der Browser die Clipboard-Read-Berechtigung noch nicht erteilt (oder
  verweigert) hat.
- **Vom Nutzer end-to-end in einem echten Browser bestaetigt**: ein
  einzelnes Cmd/Strg+V im eingebetteten Login-Fenster fuegt jetzt den
  aktuellen Host-Zwischenablage-Inhalt ein.
