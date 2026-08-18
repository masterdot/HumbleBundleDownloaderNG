*[English](CONCEPT_WEB.md) | [Deutsch](CONCEPT_WEB.de.md)*

# Concept: hbdl Web UI + Docker Operation

Extends `CONCEPT.md` (the CLI core concept, still valid unchanged) with the
web interface and Docker operation. A separate document so `CONCEPT.md`'s
scope (§1: pure CLI tool) doesn't get diluted. Numbering continues from
`CONCEPT.md` §12's milestones (M8+).

## 1. Goal & Fundamental Decisions

- Docker container with a web interface, driving the same downloader as the
  CLI.
- Destination folder ("library") freely selectable via volume mount, no
  image rebuild needed.
- No Humble Bundle data whatsoever inside the container itself — config,
  session, manifest, downloaded files all live exclusively in volumes.
- CLI usage stays fully functional throughout the whole restructuring, even
  as a plain `pip install hbdl` without web extras.
- Frontend: lean, server-rendered (htmx/Alpine.js), no Node build.
- Library browser: multi-level Finder-style columns (bundle → subproduct →
  file), derived directly from the existing `DownloadItem` fields, no new
  hierarchy layer.
- Auth in Docker: Playwright login inside the container via Xvfb +
  VNC/noVNC, embedded in the web interface; cookie paste stays the faster
  fallback.
- Pause = "after the current file" (don't start new downloads, let running
  ones finish), no interference with the byte-streaming loop.
- Staged rollout: stage 1 (M8–M11), stage 2 (M12), stage 3 (M13–M14), with
  checkpoints in between.

Architecture details (folder structure, config/state schema, job control,
auth/VNC subsystem, web UI routes, Docker/volumes) are in the original
implementation plan; expanded here as needed once individual parts are
built.

## 2. Milestones

- **M8** — Web scaffold: `web/app.py`, `hbdl web serve`, `[web]` extra,
  Docker `cli`/`web` stages, `XDG_*`/`HBDL_DEST` volume story verified
  end-to-end. ✅ done
- **M9** — Config wiring: close the `Config.load()` gap, `Config.save()`,
  `hbdl config show/set`, settings page (form only, no auth UI yet). ✅ done
- **M10** — Catalog cache + library browser: `catalog_items` table,
  `sync_catalog_cache`, query helpers, 3-column router, live search, filter
  buttons. ✅ done
- **M11** — Job manager + SSE progress (start only, no pause yet). ✅ done
- **M12** — Pause/stop + `STATUS_DOWNLOADING`. ✅ done
- **M13** — Docker VNC login (Xvfb/x11vnc/noVNC, captcha spike first). 🔶
  Infrastructure done and technically verified; the real login attempt
  (captcha spike) is still outstanding.
- **M14** — i18n: DE/EN language switching for the CLI + web UI,
  bilingual core docs (README, CONCEPT.md, CONCEPT_WEB.md). ✅ done
- **M15** — Compose hardening (WAL, lock file), README Docker section.

## Decision Log

### 2026-08-17 – M8 done: web scaffold

- **FastAPI instead of Flask**, sync `def` routes (FastAPI distributes them
  across a thread pool automatically). Rationale: fits the existing
  synchronous/thread-pool architecture (`CONCEPT.md` §11), gets
  OpenAPI/Pydantic for free, `StreamingResponse` for SSE without an extra
  dependency.
- **`hbdl web serve`** imports `hbdl.web` only inside the command function
  (`try/except ImportError` → hint to `pip install hbdl[web]`), so `pip
  install hbdl` without extras stays free of FastAPI/uvicorn/jinja2 — the
  same pattern as the existing optional Playwright import in
  `auth.guided_login`.
- **Gotcha found**: the installed Starlette version expects
  `Jinja2Templates.TemplateResponse(request, name, context)` (request
  first) instead of the older `TemplateResponse(name, context)` ordering.
  The wrong order produces a misleading `TypeError: cannot use 'tuple' as a
  dict key` deep inside Jinja2's template cache, not an obvious signature
  error. Applies to every future route using `TemplateResponse`.
- **`XDG_CONFIG_HOME`/`XDG_DATA_HOME` verified** (not just assumed):
  confirmed locally via `platformdirs`, and additionally tested end-to-end
  in a running `hbdl:web` Docker container with mounted volumes (`/config`,
  `/data`, `/library` correctly resolved via `XDG_CONFIG_HOME`,
  `XDG_DATA_HOME`, the new `HBDL_DEST` env var).
- **`config.resolve_dest(cli_value)`** is new (precedence: CLI flag >
  `HBDL_DEST` env > `config.toml` > `DEFAULT_DEST`), wired into `cli.py
  sync`. Closes the `Path.cwd()` trap of `DEFAULT_DEST`, which would be
  meaningless in a container. Implementation detail: `resolve_dest` passes
  `CONFIG_FILE` explicitly to `Config.load(path=CONFIG_FILE)` instead of
  relying on `Config.load()`'s own default parameter — default parameters
  are bound once at function-definition time, so a
  `monkeypatch.setattr(config, "CONFIG_FILE", ...)` in tests wouldn't
  otherwise reach them.
- **Docker**: multi-stage `Dockerfile` with a `cli` and a `web` target (the
  VNC stack only follows in M13, to keep the image lean until then). Both
  targets build and run, verified (`docker build --target cli|web`,
  container test run with all three volumes).
- Small observation, no action needed: `starlette.testclient` reports a
  deprecation warning in favor of `httpx2` — still functional for now, may
  be worth revisiting in a later stage if `httpx2` becomes established.

### 2026-08-17 – M9 done: config wiring + settings page

- **`Config.load()` gap closed**: `hbdl list`/`hbdl sync` now actually read
  `workers` from `config.toml` (previously only `cookie_file` was read, see
  the discrepancy against `CONCEPT.md` §9); `sync` additionally reads
  `strategy`. Precedence everywhere: CLI flag > `config.toml` > built-in
  default.
- **`hbdl config show`/`hbdl config set KEY VALUE`** is new (planned in
  `CONCEPT.md` §9, never built) — uses the same `Config.save()` as the web
  settings page (`POST /settings`), a single serialization source for CLI
  and web.
- **Serious bug found and fixed before it hit production**: both
  `Config.load(path: Path = CONFIG_FILE)` and the new `Config.save(path:
  Path = CONFIG_FILE)` had `CONFIG_FILE` bound as a parameter *default* —
  Python binds default values once at function-definition time, not on
  every call. Every call without an explicit `path=` (e.g.
  `config.Config.load()` in `cli.py`/`settings.py`) therefore ignored a
  later `monkeypatch.setattr(config, "CONFIG_FILE", ...)` entirely and
  read/wrote **the real, production config.toml on the dev machine** —
  which actually happened during this milestone's test runs (the real
  `~/Library/Application Support/hbdl/config.toml` got overwritten with
  test values, then cleaned up). Fix: `path: Path | None = None` as the
  parameter, resolved against the current module-global `CONFIG_FILE`
  **inside the function body** (there it's a normal name lookup, re-
  evaluated on every call, not a frozen default). Harmless in production
  (there `CONFIG_FILE` is set correctly once at process start via
  `XDG_CONFIG_HOME`, no runtime rebinding happens), but a real test-
  isolation and potential footgun risk for any future call site. **To
  check for later stages**: `state.py`'s `StateStore.__init__(path: Path =
  config.STATE_DB)` and `auth.py`'s
  `_save_session`/`_load_saved_session` (`path: Path = config.SESSION_FILE`)
  have the same default-binding style — not touched so far, since every
  existing call site always passes the path explicitly (no bare-call
  pattern like `Config.load()` had), but keep it in mind for future
  changes.
- Settings page (`GET/POST /settings`) validates `strategy` against
  `STRATEGIES` and `workers >= 1` server-side, returns 422 with an error
  message on failure instead of saving something broken.

### 2026-08-17 – M10 done: catalog cache + library browser

- **`catalog_items` table** in `state.sqlite` (additive, same DB as
  `downloads`). `catalog.sync_catalog_cache(store, items)` replaces the
  cache entirely on every run (DELETE + bulk INSERT in one transaction)
  instead of just merging — so returned/removed bundles disappear from the
  browser too, instead of lingering as ghosts. Called from both `hbdl
  list` **and** `hbdl sync` (before any `--platform` filtering, so the
  cache always reflects the full library, not just what this particular
  sync run happened to download) — deliberately not on every login
  automatically, to avoid triggering surprise API calls.
- **Second, more serious find of the same bug class as M9** (frozen
  parameter defaults): `state.py`'s `StateStore.__init__`/`open_store` and
  `auth.py`'s `_save_session`/`_load_saved_session` had exactly the same
  pattern (`path: Path = config.STATE_DB` and `config.SESSION_FILE`
  respectively). This time genuinely security-relevant, not just a test-
  isolation annoyance: the new `web/deps.py::get_store()` dependency calls
  `open_store()` **without** a path (the first "bare call" of that
  function anywhere in the codebase) — without the fix, this would have
  opened/written the real, production `state.sqlite` on the dev machine on
  every request, and a test for `/library/refresh`'s "no login" error
  handling would even have read the dev machine's real, private session-
  cookie file via `auth.resolve_session()` → `_load_saved_session()`. Both
  fixed with the same pattern as in M9 (`path: Path | None = None`,
  module-global lookup inside the function body). **Lesson for the rest of
  the project**: any function with a `path: Path = config.SOMETHING`
  parameter default is suspect as soon as it's ever called *without* an
  explicit `path=` somewhere — check before the next bare call at such a
  site.
- **Column browser** (bundle → subproduct → file) without a new data-model
  layer: the 3 levels come directly from the existing `DownloadItem`
  fields (`gamekey`/`human_name` → `subproduct_name` →
  `platform`+`variant_name`+`filename`). htmx fragments per drill-down
  level (`#col2-onward`/`#col3-onward` get fully replaced on every click on
  a parent column, so switching bundles automatically resets downstream
  columns), row selection via an inline `hx-on:click` handler (no Alpine
  needed for this single feature, even though Alpine is already vendored
  as an asset).
- **Filter buttons** in two rows, as requested by the user: "Ebooks"
  (formats, from `distinct_ebook_formats()` = `variant_name` where
  `platform='ebook'`) and "Games/software" (platforms, from
  `distinct_game_platforms()` = `platform != 'ebook'`), computed
  dynamically from the actual catalog contents, not hardcoded.
- **htmx 2.0.4 + Alpine.js 3.x + the htmx-sse extension** vendored into
  `web/static/` (no Node build, fits the lean-frontend decision) — the SSE
  extension is already pulled in now but only actually wired up in M11.
- `/library/refresh` (POST) triggers a synchronous, blocking
  `build_catalog()`+`sync_catalog_cache()` run — deliberately simple for
  v1, the "Refresh" button; a non-blocking job with progress display is
  the subject of M11.

### 2026-08-17 – M11 done: job manager + SSE progress (start)

- **`download_all()` core rebuilt** onto incremental futures dispatch
  (`deque` + a bounded `in_flight` set instead of "submit all futures at
  once"), with new optional `pause_gate`/`stop_event` parameters (default:
  always open/never set, existing CLI call stays unchanged/compatible) as
  well as `progress_factory` (an injectable progress sink instead of the
  hardwired `ProgressReporter`, new `progress.ProgressSink` protocol). The
  byte-streaming loop in `_download_one` stays completely untouched, as
  required by the plan. Pause parks the run (`pause_gate.wait()`, running
  downloads finish, no new ones start); stop drains the queue (no new
  starts), but lets already-running downloads finish and collects their
  results instead of silently discarding them. Both already backed by
  targeted, deterministic tests (`responses.add_callback` as a gate instead
  of sleep-based racing), even though pause/stop only become reachable from
  the UI in M12.
- **`web/jobs.py::JobManager`**: one job at a time, runs in a background
  thread (`build_catalog` → `sync_catalog_cache` → `download_all`), status
  `IDLE/DISCOVERING/RUNNING/DONE/ERROR`. Errors (e.g. `AuthError` with no
  login) are caught and mirrored as `ERROR` status with a message in the
  snapshot/event, not swallowed. **No pause/resume/stop methods on
  `JobManager` itself yet** — deliberately not built while nothing calls
  them (arrives with M12 together with the dashboard buttons).
- **`web/events.py::EventBus`**: simple in-process pub/sub (a
  `queue.Queue` per subscriber), the publisher is the `JobManager`, the
  subscriber is the SSE route.
- **Hand-rolled SSE framing** (`event: TYPE\ndata: ...\n\n`, multi-line
  payloads correctly prefixed with one `data: ` per line) instead of an
  SSE library — fits the original decision against `sse-starlette` (see
  the M8 entry on FastAPI/SSE). The htmx-sse extension handles the
  frontend wiring purely declaratively (`sse-connect`/`sse-swap`), no
  custom JS needed.
- **Important test-infrastructure find**: `TestClient.stream()` over this
  Starlette version's in-process ASGI transport hangs completely on a
  deliberately never-ending generator (like the SSE endpoint) — the
  request doesn't even return a response object, because the transport
  apparently tries to buffer the *entire* response before returning
  anything. Empirically verified (a debug script that never got past
  "opening stream..."). Fix: call the route function directly and pull
  exactly one chunk from `StreamingResponse.body_iterator` — despite being
  a sync generator in `dashboard.py`, it's internally an *async* generator
  (Starlette auto-wraps sync generators via thread-pool iteration), hence
  `asyncio.run(...)` with `__anext__()`/`aclose()` instead of a plain
  `next()`. Deterministic, no hanging, still exercises the real path
  subscribe → publish → render → SSE framing.
- **Second find in the same "forgotten isolation" category as M9/M10, this
  time in our own tests rather than production code**: two new tests
  (`test_job_manager_rejects_concurrent_start`, plus a web dashboard test)
  let the background thread keep running after `release.set()` without
  waiting for `is_running() == False` before the test function (and with
  it `monkeypatch`/`tmp_path`) ended. Since these tests hadn't isolated
  `config.STATE_DB` at all, the still-running job thread actually opened
  the real, production `state.sqlite` on the dev machine (an empty
  `catalog_items` table got created there, no real data was lost —
  `downloads` with its real 1334 rows stayed untouched). After the fix
  (isolate STATE_DB **and** actively wait for job completion before the
  test ends), five consecutive full test runs verified with no change to
  the real `state.sqlite`'s file timestamp. **Recurring lesson across
  M9–M11**: for every new test that starts a background thread against
  `hbdl` code, ALWAYS (a) explicitly isolate
  `config.STATE_DB`/`config.CONFIG_FILE`/target paths AND (b) actively
  wait for the thread to finish before the test function returns — not
  just signal it to continue and optimistically move on.
- Verified end-to-end in the real `hbdl:web` Docker container: the
  dashboard shows a "Ready" button, starting without a login runs through
  `DISCOVERING` and lands cleanly (no 500) at `ERROR` with "no login
  found".

### 2026-08-17 – M12 done: pause/stop + STATUS_DOWNLOADING

- **`JobManager`** extended with `pause()`/`resume()`/`stop()`, built on
  the `pause_gate`/`stop_event` parameters of `download_all()` already
  added in M11. New `PAUSED`/`STOPPED` states in the `JobState` enum.
  Pause is only valid from `RUNNING`, resume only from `PAUSED`, stop from
  any active state (`DISCOVERING`/`RUNNING`/`PAUSED`) — invalid
  transitions raise `RuntimeError`, caught by the routes (no 500 on a
  click that collides with the job's actual progress, e.g. "Pause" right
  after the job already finished).
- **`STATUS_DOWNLOADING`** is now written in `_download_one` (before the
  retry loop) — purely informational for the UI, no control-flow change.
  New `StateStore.reconcile_stale_downloading()`, called once at
  `create_app()` startup, resets orphaned `downloading` rows (container
  crash mid-transfer) cosmetically back to `pending`.
- **Serious, actually reproduced side finding**: `StateStore`, despite
  `check_same_thread=False`, didn't allow truly *concurrent* access from
  multiple threads to the same SQLite connection — `check_same_thread=False`
  only disables Python's own same-thread check, it doesn't make the
  connection thread-safe for real parallelism. `download_all()`'s worker
  pool has always passed the same `store` to multiple simultaneous worker
  threads; so this was a latent bug in existing code, not newly introduced
  by M12. But it only got triggered reliably enough to surface in a flaky
  test by the new `STATUS_DOWNLOADING` extra write (two `upsert()` calls
  per file instead of one, both potentially concurrent with other items)
  (`sqlite3.OperationalError: bad parameter or other API misuse`, about 1
  in 10 runs). Verified via a reproduction script (60 repetitions), then
  fixed: a `threading.Lock` around **every** access to `self._conn` in
  `StateStore` (including `fetchall()` on cursor results, which are only
  valid as long as no other thread is using the same connection). After
  the fix, 60/60 repetitions and ten full test-suite runs clean.
  **Practical relevance beyond tests**: this would have occasionally
  caused failed downloads via SQLite errors in real web operation with
  `workers > 1` (the default is 3), not just a test problem — a good find
  before the VNC login stage enables real downloads via the web UI.
- Verified end-to-end in the real Docker container: `/jobs/current/pause`,
  `/resume`, `/stop` respond cleanly (200, no 500) even when no job is
  running.

### 2026-08-18 – M13 (part 1): VNC login infrastructure built and verified

- **`web/login_state.py::LoginState`**: its own, deliberately simple state
  machine kept separate from the `JobManager` (`idle/running/success/error`,
  no progress/queue concept needed) — a one-off, short-lived operation
  (log in once, collect the cookie), not a download job. `guided_login()`
  itself needed **zero code changes**: it already starts a visible
  Chromium (`headless=False`) that renders to the process's `DISPLAY` —
  Xvfb's `:99` inside the container.
- **`auth.save_manual_cookie()`** is new (a thin public wrapper around
  `_save_session`) for the cookie-paste fallback in
  `web/routers/auth_web.py` — both paths (VNC login and pasting a cookie)
  land on the same settings page, `_login_area.html` shows a start button,
  the embedded VNC iframe, success, or error depending on `LoginState`
  status, via htmx polling (`hx-trigger="every 2s"`) while `running`.
- **Docker `web` stage extended**: `xvfb x11vnc novnc websockify
  supervisor` via apt, `playwright install --with-deps chromium`,
  `docker/supervisord.conf` brings up 4 programs (`xvfb` → `x11vnc` →
  `novnc`/websockify on :6080 → `hbdl-web` with `DISPLAY=:99`). Image size
  **2.67GB** (ARM64/Apple Silicon build) — at the upper end of the
  1-1.5GB estimate named in the plan, but within the expected range; the
  `cli`/`web` split remains the answer for anyone who doesn't need this.
- **`docker-compose.yml`**: port 6080 is bound only to `127.0.0.1` (x11vnc
  runs with `-nopw`, i.e. no VNC password — must never be exposed beyond
  the host), documented with a comment directly in the compose file.
- **End-to-end technically verified in the real container** (not just
  assumed): both `/healthz` and `http://localhost:6080/vnc.html` are
  reachable, `POST /auth/login/start` returns the VNC iframe fragment, and
  a real Chromium process is actually running in the container afterward
  (confirmed via a `/proc` scan, `ps` is missing in the slim image) — the
  full chain Playwright → Xvfb → x11vnc → noVNC → browser iframe works
  mechanically.
- **Still open, deliberately not something I can verify myself**: whether
  the real login against the real Humble Bundle site (including
  captcha/2FA) is actually usable through the embedded VNC view, and
  whether Humble Bundle's bot/automation detection blocks this path.
  That's exactly the spike the plan calls for before the rest of
  M13/M14 — needs real credentials and visual/interactive checking that
  only the user can do. Automated tests deliberately only cover the mocked
  `LoginState`/routes part (`tests/web/test_auth_web.py`), not the real
  Xvfb/VNC/captcha chain — exactly as explicitly planned originally.

### 2026-08-18 – Bug fix: VNC iframe kept reloading from the status poll

Reported by the user: the embedded login window "keeps reloading, can't
type anything" — looked like connection drops. Root cause: the 2-second
polling for login status (`hx-trigger="every 2s"`) sat on the OUTER
`#login-area` div and replaced its entire `outerHTML` on every tick —
including the VNC iframe itself. That rebuilt the VNC connection every two
seconds, exactly as described. Fix: the polling now sits on a small,
separate `#login-status-poll` div NEXT TO the iframe (no longer wrapping
around it), which only replaces itself (`hx-target="this"`). Only on an
actual status change (success/error) does an htmx out-of-band swap
(`hx-swap-oob="true"`) replace the whole `#login-area` including the
iframe — by that point the iframe isn't needed anymore anyway. Two
regression tests added (`tests/web/test_auth_web.py`) that guard exactly
this: the iframe must not reappear during a "running"-status poll.

### 2026-08-18 – Footer + About/Donate page

At the user's request: a footer on every page (copyright, link to the
repository, donate link to GitHub Sponsors). New `/settings/about` page (as
a second "tab" next to the existing settings, `_settings_tabs.html` links
between the two) with an origin story, an invitation to contribute via
GitHub issues, and an outlook on planned integrations (Audiobookshelf,
Calibre-Web, Jellyfin, still-open games solution).

### 2026-08-18 – VNC clipboard autopaste + Docker disk incident

- **Clipboard fix, attempt 1 (wrong)**: a custom clone of noVNC's
  `vnc.html` (`hbdl-vnc.html`, the original stays untouched) with an
  additional script that listened for a native `paste` event on
  `document`, on the assumption that noVNC catches keyboard input via a
  hidden `<textarea id="noVNC_keyboardinput">`. Tested by the user:
  **didn't work**, the clipboard stayed empty.
- **Root cause found**: `core/rfb.js` attaches the actual desktop keyboard
  input to a `<canvas>` element (`this._keyboard = new
  Keyboard(this._canvas)`), not to the textarea — that one's only
  responsible for the separate mobile virtual-keyboard button. A
  `<canvas>` fundamentally never fires a `paste` event, no matter how it's
  focused — my handler never got a chance to run.
- **Clipboard fix, attempt 2 (works)**: instead of listening for `paste`,
  the script now intercepts the Cmd/Ctrl+V **keydown** (which the canvas
  normally does receive, that's how noVNC itself reads regular keyboard
  input too), actively reads the local clipboard via
  `navigator.clipboard.readText()` (allowed, because the call happens
  inside a real user keypress gesture), sends the text to the remote side
  via `RFB.clipboardPasteFrom()`, and then — after a short delay so the
  clipboard message arrives first — simulates a real Ctrl+V on the remote
  side via `RFB.sendKey()` (a public API noVNC itself uses), so the remote
  app actually pastes the freshly set content. The original keydown gets
  suppressed (`preventDefault`/`stopPropagation` in the capture phase,
  before noVNC's own canvas handler) so nothing gets pasted twice. Falls
  back to a plain passed-through remote Ctrl+V if clipboard permission is
  missing, instead of silently swallowing the key combo. The reverse
  direction (remote → local) remains best-effort via
  `navigator.clipboard.writeText()`, the sidebar textarea stays as a
  fallback.
- **Clipboard fix, attempt 3 (now the primary path)**: attempt 2 still
  failed for the user — suspected (and plausible) reason:
  `navigator.clipboard.readText()` from a cross-origin iframe (the VNC
  view runs on port 6080, the parent page on 8000 — different origins) is
  frequently and silently refused by browsers. Instead of continuing to
  tweak the clipboard API: avoided it entirely. The settings page now has
  a plain `<input>` next to the iframe — pasting there is a completely
  normal, permission-free browser paste (same-origin text field). The
  content is sent to the iframe via `postMessage()` (no permission
  needed), picked up there by `novnc-clipboard-autopaste.js` (origin-
  checked against port 8000), and injected the same way as before via
  `RFB.clipboardPasteFrom()` + a simulated `RFB.sendKey()` Ctrl+V. Attempt
  2 (keydown + clipboard API) remains as an extra best-effort path in case
  it does work in some browsers — but the paste box is now the documented,
  reliable path.
- **Clipboard fix, attempt 3, also not sufficient**: user feedback after
  attempt 3 — still not reliably working, the context menu in the remote
  Chromium was partly broken, "iffy" focus/copy-paste behavior. Clear
  message from the user: wants a comfortable, reliable solution, no cookie
  copying around, OTP/2FA via VNC copy-paste is a real problem (time-
  sensitive). Question: is a local CLI login possible, then "pulling" the
  token afterward?
- **Course change: local CLI login becomes the primary, recommended
  path.** Answer: yes, and the foundation already existed almost entirely
  — `hbdl auth login` (unchanged, present since M1) opens a **real
  native** browser window on the host machine, not inside the container.
  Normal OS copy-paste, password manager, authenticator apps — no VNC
  limitations at all. The only missing piece: the same `session.json`
  needs to land where the container expects it. Since
  `docker-compose.yml`'s `/config` volume already points at
  `./hbdl-config` in the host project folder, running
  `XDG_CONFIG_HOME="$(pwd)/hbdl-config" hbdl auth login` locally is
  enough — no copying, no cookie handling, the container sees the file
  automatically through the shared volume. Verified: a locally written
  test session was immediately read correctly by the running container.
  New `docker/login-locally.sh` wraps this (finds `.venv/bin/hbdl`
  automatically, sets `XDG_CONFIG_HOME` correctly).
- **Real bug found and fixed along the way**: `_login_context()` let a
  failed VNC attempt stick as an error status **permanently**, even after
  a valid login later came in through a different path (e.g. CLI login or
  cookie paste) — the on-disk file was only ever checked in status `IDLE`.
  Fix: the on-disk session is now the source of truth in every non-
  "running" state, not the last status held in memory. Regression test
  added
  (`test_a_session_file_appearing_after_a_failed_attempt_overrides_the_stale_error`).
- **UI rebuilt**: "Log in locally via the command line" is now the
  clearly highlighted recommendation at the top of the login card. VNC
  login and cookie paste are both moved into `<details>` elements
  ("Alternative: ..."), collapsed by default (VNC stays expanded while an
  attempt is running). The VNC infrastructure (M13) stays in place — for
  cases with no local access to the Docker host at all — but is no longer
  the advertised default path.
- **Real incident during the work**: the Mac's disk ran down to about
  150MB free (out of 228GB) through the many rebuilds in this session,
  which crashed Docker/Colima with I/O errors — first only on writes
  (builds failed), later the Colima VM itself got stuck deep enough in an
  I/O-error state that even `colima ssh` failed immediately (likely
  filesystem damage from write attempts while the disk was full). No data
  loss (all Humble Bundle data lives in volumes outside the VM), but
  `colima restart` was needed to bring the VM back into a clean state —
  immediately back to 12-19GB free on host and VM afterward.
- **`docker/rebuild.sh`** is new: `docker compose build && docker compose
  up -d && docker image prune -f` in one step, so old image layers get
  cleaned up automatically after every rebuild (only dangling/untagged
  layers, doesn't touch other tagged images on the same machine).
  Documented in `docker-compose.yml` as the recommended rebuild path.
  **Lesson**: on a project with as many Docker rebuild iterations as this
  one, this script should have existed from the start, not only after the
  disk actually filled up.

### 2026-08-18 – VNC properly fixed: same-origin reverse proxy instead of a CLI-login recommendation

- **Clear user directive after the three clipboard attempts**:
  GUI-operation only, no console commands whatsoever for the end user —
  explicit criticism of the spontaneous fix-bug-fix-bug loop so far, a
  call for one thoroughly thought-through solution design instead of
  another guess. Two honest options offered: (a) a small local helper
  process (one-time setup, GUI-only afterward) vs. (b) fix VNC properly,
  entirely inside the container, with zero extra host-side step. User's
  decision: **(b), fix VNC properly.**
- **The actual root cause of all three previous failures identified**: not
  the clipboard mechanism itself, but that the VNC iframe (`hbdl-vnc.html`)
  ran on port 6080 while the rest of the UI ran on 8000 — two different
  origins. Browsers usually refuse `navigator.clipboard` access from a
  cross-origin iframe without any visible indication; that explains why
  attempt 2 (keydown + clipboard API) never worked for the user, even
  though the mechanism itself was fundamentally correct.
- **Fix: a complete same-origin reverse proxy** instead of the separate
  port-6080 origin. New router `web/routers/vnc_proxy.py`: `GET
  /vnc/{path:path}` synchronously forwards noVNC's static assets
  (`hbdl-vnc.html`, `app/*.js`, `core/*.js`, etc.) via `requests` to
  `http://127.0.0.1:6080/...` (hop-by-hop headers like `content-length`
  are deliberately not forwarded, since `requests` has already unpacked
  the response). `WS /vnc/websockify` is a WebSocket relay (new
  `websockets` dependency, `[web]` extra) — the one deliberate async
  exception in an otherwise fully synchronous codebase (cf. `CONCEPT.md`
  §11), cleanly confined to this single route.
- **noVNC's own `path` connection parameter verified** (by reading
  `app/ui.js` in the running container, not blindly assumed): if `host` is
  empty (the default), noVNC builds the WebSocket URL relative to the
  current document URL (`new URL(path, location.href)`). With
  `hbdl-vnc.html` served under `/vnc/`, `?path=websockify` (without a
  `vnc/` prefix) is therefore enough — it resolves relative to the `/vnc/`
  directory correctly to `/vnc/websockify`, matching the new proxy route.
  This also confirms noVNC connects without negotiating an explicit
  `wsProtocols` handshake — the WS proxy doesn't need to negotiate a
  sub-protocol.
- **`novnc-clipboard-autopaste.js` simplified**: the `postMessage` paste
  box (attempt 3) and the separate paste box in the login template are
  gone again — back to a cleaned-up version of attempt 2 (keydown +
  clipboard API), which now runs same-origin and should therefore actually
  get clipboard permission. Fewer stacked mechanisms = also a plausible
  candidate for why the context menu in the embedded window was broken
  before.
- **UI rebuilt again**: VNC login is once more the primary, directly
  visible path (no more `<details>` needed, since it's now the reliable
  path). "Log in locally via the command line"
  (`docker/login-locally.sh`) stays as a `<details>` alternative for
  anyone who'd rather use a native host browser window — but is no longer
  the recommendation. Cookie paste stays as a third, low-friction
  `<details>` alternative.
- **`docker-compose.yml`**: port 6080 is no longer published externally
  (websockify still runs internally in the container on 6080, but is no
  longer reachable from outside at all) — a small security win on the
  side, since the unprotected `-nopw` VNC port was previously at least
  reachable on `127.0.0.1`.
- New tests `tests/web/test_vnc_proxy.py`: HTTP proxy against a local
  `http.server` test server (path/query correctly forwarded), WS proxy
  against a local `websockets` echo server (frames unchanged in both
  directions). The existing `test_auth_web.py` test updated to the new
  `/vnc/hbdl-vnc.html?path=websockify` URL. Still deliberately outside
  automated tests: real captcha/login behavior and actual clipboard
  behavior in a real browser — stays manual verification by the user, now
  with a solid technical rationale for why it should work better, instead
  of another guess.

### 2026-08-18 – M14 done: i18n (DE/EN) for CLI + web UI, bilingual docs

- **Background**: the web UI is meant to later be rebuilt as an editable
  Claude Design canvas to overhaul it visually, before the new version
  replaces the current implementation (a separate, later step). So that
  overhaul work wouldn't start from a German-only UI and duplicate the
  translation effort, the language switch was built first. Language is a
  global app setting (persisted in `config.toml`, no session cookie) —
  an explicit scope decision by the user, as was translating the CLI too
  (not just the web UI).
- **New package `src/hbdl/i18n/`**: `strings.py` carries a flat `CATALOG:
  dict[str, dict[str, str]]` with dotted keys, DE/EN side by side per
  entry (prevents drift between the languages). `__init__.py` provides
  `t(key, **kwargs)` (module-global language, `str.format` interpolation),
  `t_count()`, `set_lang()`/`get_lang()`. Language is deliberately a
  single module global rather than threaded-through state — hbdl is
  single-user/single-process, there's no multi-tenant scenario with per-
  request Accept-Language negotiation that would justify the extra
  plumbing.
- **`t()`'s `key` parameter is positional-only** (`def t(key, /,
  **kwargs)`): an early attempt to call
  `i18n.t("cli.config.set_saved", key=key, ...)` collided with `t()`'s
  own `key` parameter (`TypeError: t() got multiple values for argument
  'key'`), since catalog entries themselves wanted to use `{key}` as a
  placeholder name. Positional-only fixes this at the root, instead of
  renaming the placeholder at every affected call site.
- **Web wiring**: `create_app()` registers `t`/`lang` as Jinja globals
  (`app.state.templates.env.globals`), so every template can use `{{
  t("key") }}` without every route handler having to pack it into the
  context individually. `base.html`'s `<html lang="de">` became `<html
  lang="{{ lang() }}">`.
- **All 18 Jinja2 templates** migrated. The four identical status-badge
  blocks (downloaded/failed/running/open) in `_column_file.html` and
  `_flat_list.html` were consolidated into a shared partial
  `_status_badge.html` (`{% with status = f.status %}{% include
  "_status_badge.html" %}{% endwith %}`).
- **HTML in catalog entries, deliberately rendered with `| safe`**: a
  handful of entries (e.g. `about.outlook_games`,
  `library.empty_catalog_message`) embed static, developer-authored HTML
  (`<code>`, `<strong>`, links with a hardcoded href) rather than
  splitting the sentence into several catalog keys around each tag — word
  order differs enough between German and English that stitching
  fragments back together gets unnatural fast. Explicitly: never route
  user-controlled data through `t()` + `| safe`.
- **Raw `HTMLResponse` in `library.py`'s `/refresh` replaced with a real
  template response** (`_auth_error.html`): the old version embedded the
  AuthError message into an f-string unescaped — a small bug fixed on the
  side, since Jinja now escapes it automatically.
- **CLI wiring**: Typer generates `help=` text once at module-import time,
  before `Config.load()` has ever run — dynamic `--help` translation isn't
  cleanly possible with Typer's decorator architecture. Decision: `help=`
  text stays deliberately static English (as reference documentation), but
  every runtime output (`typer.echo`/`typer.secho`) goes through `t()`.
  `cli.py::main()` calls `i18n.set_lang(config.resolve_lang())` right at
  the start, before `app()` dispatches — this also covers `hbdl web
  serve`, since it runs through the same entry point.
- **`AuthError` extended with optional `key`/`key_kwargs`**, the existing
  German `message` stays unchanged as the `str(exc)` fallback for
  logs/tests. Display sites (`cli.py`'s four `except auth.AuthError`
  blocks, `library.py`'s `/refresh`) use `i18n.t(exc.key, **exc.key_kwargs)
  if exc.key else str(exc)`. Translation deliberately happens at the
  display boundary, not at the raise site — keeps `auth.py` free of any
  i18n import/language state.
- **`config.py`**: new `Config.lang` field (default `"de"`, so existing
  users see no change until they actively switch), `LANGUAGES = ("de",
  "en")`, `resolve_lang(cli_value=None)` exactly analogous to
  `resolve_dest()` (precedence: CLI flag > `HBDL_LANG` env > `config.toml`
  > default). `hbdl config set lang en` works through the same
  `CONFIG_KEYS`/`config_set` mechanism as `strategy`.
- **Language switching in the web UI**: a quick toggle in the topbar
  (`POST /settings/lang`, two DE/EN submit buttons, a real full-page
  reload instead of an htmx fragment swap — otherwise nav/footer/page
  content would stay inconsistently translated), plus a full `<select
  name="lang">` in the settings form going through the existing
  `settings_save()` flow.
- **Bilingual core docs**: convention `<name>.md` = English (default),
  `<name>.de.md` = German. `README.md` was already English, `README.de.md`
  newly added. `CONCEPT.md` and `CONCEPT_WEB.md` used to carry the German
  content — moved to `CONCEPT.de.md`/`CONCEPT_WEB.de.md` via `git mv` (or
  a plain `mv`, since `CONCEPT_WEB.md` was still untracked), then fresh
  English `CONCEPT.md`/`CONCEPT_WEB.md` written. All six files cross-link
  each other at the top (`*[English](README.md) | [Deutsch](README.de.md)*`).
  LICENSE untouched, CHANGELOG.md deliberately stays English-only (user's
  decision).
- **How to add a new string**: add an entry with a `de`/`en` value to
  `src/hbdl/i18n/strings.py`'s `CATALOG` (a dotted-key namespace matching
  the context, e.g. `settings.*`, `library.status.*`), then call
  `t("your.key")` in a template or `i18n.t("your.key", **kwargs)` in
  Python code. `tests/test_i18n.py::test_every_catalog_entry_has_de_and_en`
  prevents an entry from existing in only one language.
- **How to add a new language**: extend `config.LANGUAGES`, add the new
  language code to every existing `CATALOG` entry (the completeness test
  currently hardcodes `"de"`/`"en"` — it would need extending for more than
  two languages), and add the new option to the DE/EN switch UI (topbar
  form, settings `<select>`).

### 2026-08-19 – VNC clipboard: the actual root cause found (`window.UI` was never real)

- **Symptom after the same-origin proxy fix**: the browser's context menu
  worked again inside the VNC window, but Cmd/Ctrl+V still pasted a stale
  value (an old, already-expired OTP) instead of the current clipboard
  content — with no permission prompt and no console error at all, even
  after adding a `console.warn` to the `catch` branch.
- **Root cause, found by reading `/usr/share/novnc/hbdl-vnc.html` and
  `app/ui.js` inside the running container**: stock noVNC's `UI` object is
  only ever `export default UI` from `app/ui.js`, imported into the
  *module scope* of the inline `<script type="module">` in `vnc.html`. It
  was never actually assigned to `window.UI` — every version of
  `novnc-clipboard-autopaste.js` so far (including the one from the
  same-origin fix) started with `if (!window.UI || !window.UI.rfb)
  return;`, which was silently true on every single keypress. None of the
  clipboard logic ever ran; the keydown just fell through unmodified to
  noVNC's own default canvas handler, which forwarded a bare Ctrl+V to the
  remote X11 session — explaining the stale value (whatever was last in
  the *remote* clipboard/selection buffer) and the complete absence of any
  error (the code path was never reached at all).
- **Diagnosis approach, at the user's suggestion**: instead of guessing at
  another clipboard-permission fix, split the problem into two
  independently-testable halves. Investigated noVNC's own already-built-in
  clipboard mechanism first (`UI.openClipboardPanel()` reveals a sidebar
  with `#noVNC_clipboard_text`, whose native `change` event calls
  `UI.clipboardSend()`, which reads the textarea and calls
  `UI.rfb.clipboardPasteFrom()`). A temporary diagnostic build added a
  visible "Sync clipboard" button driving that exact path plus verbose
  console logging, with the automatic Cmd/Ctrl+V interception removed
  entirely so a plain Ctrl+V would behave like stock noVNC. The button
  surfaced a real clipboard-permission prompt for the first time — which
  is what led to finding the `window.UI` gap, since the button's own guard
  clause was hit and logged clearly.
- **Fix**: `docker/Dockerfile`'s existing `sed` patch step (which clones
  `vnc.html` to `hbdl-vnc.html`) gained one more substitution: `import UI
  from "./app/ui.js";` → `import UI from "./app/ui.js"; window.UI = UI;`.
  That's the entire fix — `UI` is now genuinely global, and every
  `window.UI`-gated check that already existed in the JS actually runs.
- **`novnc-clipboard-autopaste.js` restored to one shortcut**: with
  `window.UI` real, the automatic Cmd/Ctrl+V interception was wired back
  up (`readText()` → sync into `#noVNC_clipboard_text` → `UI.clipboardSend()`
  → simulated remote Ctrl+V), confirmed end-to-end by the user. The manual
  "Sync clipboard" button stays as a visible fallback for the case where
  the browser hasn't granted (or has denied) the clipboard-read permission
  yet.
- **Confirmed working end-to-end by the user** in a real browser: a single
  Cmd/Ctrl+V in the embedded login window now pastes the current host
  clipboard content.
