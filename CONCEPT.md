*[English](CONCEPT.md) | [Deutsch](CONCEPT.de.md)*

# Concept: HumbleBundleDownloaderNG

## 1. Goal & Scope

A Python CLI tool that authenticates against humblebundle.com, discovers the
account's complete game/ebook library, and downloads every file locally. Two
download strategies are supported:

- **Direct download** via a managed queue (concurrency, resume, integrity
  verification).
- **BitTorrent** as an alternative, where available for a given file.

The tool talks exclusively to Humble Bundle's JSON API (not the rendered
`/home/library` HTML page), since the API is more stable and easier to parse.

## 2. Auth

**Primary path: guided Playwright login.**

`hbdl auth login` opens a real, visible Chromium window (Playwright) and
navigates to the Humble Bundle login page. The user enters their own
credentials there and solves captcha/2FA manually — the tool never touches
this step. Once the redirect to `/home` is detected, the tool automatically
reads the `_simpleauth_sess` session cookie out of the browser context and
saves it locally (encrypted, or at least with restrictive file permissions,
`chmod 600`).

**Why no fully automated username/password login in the tool:** Humble
Bundle protects `/processlogin` with reCAPTCHA. A tool could only get around
that via paid captcha-solving services — that clearly conflicts with the
provider's intent and isn't defensible. The Playwright approach avoids this
problem entirely, since the human handles the captcha/2FA interaction while
the tool only picks up the result (the cookie).

**Fallback for headless/server operation** (no local display available):
manual cookie handoff via
- `--cookie-file PATH` (Netscape `cookies.txt` format, compatible with
  browser export extensions),
- `--cookie VALUE` (raw `_simpleauth_sess` value),
- env vars `HBDL_COOKIE` / `HBDL_COOKIE_FILE`,
- or a `cookie_file` entry in the config file.

Every API request must additionally carry the `X-Requested-By:
hb_android_app` header alongside the cookie, or Humble Bundle rejects it.

At startup, `auth.py` runs a cheap validation call (`GET
/api/v1/user/order`) and aborts immediately on 401/403 with a clear error
message ("cookie invalid/expired — run `hbdl auth login` again"), instead of
failing deep inside a discovery run.

## 3. Architecture / Module Layout

`src/`-layout with `pyproject.toml`, installable via `pipx`/`uv tool`:

```
HumbleBundleDownloaderNG/
├── pyproject.toml
├── CONCEPT.md
├── README.md
├── src/
│   └── hbdl/
│       ├── __init__.py
│       ├── __main__.py          # `python -m hbdl`
│       ├── cli.py               # typer command tree
│       ├── config.py            # config file + env var resolution, XDG paths
│       ├── auth.py              # Playwright login, cookie fallbacks, HttpClient
│       ├── api.py               # wrapper for order list / order details
│       ├── models.py            # DownloadItem, Order, Subproduct dataclasses
│       ├── catalog.py           # discovery: orders -> flat DownloadItem list
│       ├── downloader/
│       │   ├── __init__.py
│       │   ├── direct.py        # HTTP download queue/worker pool
│       │   ├── torrent.py       # .torrent fetch (v1: save only)
│       │   └── strategy.py      # direct-vs-torrent decision per item
│       ├── state.py             # local SQLite manifest for idempotency
│       └── progress.py          # tqdm-based reporting
└── tests/
    ├── test_catalog.py
    ├── test_direct_downloader.py
    └── fixtures/                # sanitized, recorded JSON responses
```

Data storage (via `platformdirs`, cross-platform):
- Config: `~/.config/hbdl/config.toml`
- Saved auth cookie: `~/.config/hbdl/session.json` (restrictive permissions)
- State/manifest: `~/.local/share/hbdl/state.sqlite`
- Downloaded files: user-configurable `--dest`, default `./HumbleLibrary`

Entry point: `pyproject.toml` → `[project.scripts] hbdl = "hbdl.cli:main"`.

## 4. Data Model

```python
@dataclass(slots=True)
class DownloadItem:
    gamekey: str
    human_name: str          # bundle/product name, used for folder naming
    subproduct_name: str     # e.g. "Half-Life 2"
    platform: str            # "windows" | "mac" | "linux" | "ebook" | "android" | ...
    variant_name: str        # download_struct[].name, e.g. "Installer" / "MOBI"
    filename: str
    url: str                 # signed web URL (TTL-limited)
    url_fetched_at: datetime # for TTL staleness checks
    file_size: int
    md5: str | None
    sha1: str | None
    torrent_url: str | None  # None if there's no BitTorrent option
    dest_path: Path          # computed once
```

Since the API doesn't provide a stable content hash independent of the URL,
`(gamekey, subproduct_name, platform, variant_name, filename)` serves as the
stable identity key for local state — not the URL, since that changes on
every fetch (TTL).

Folder structure: `{dest}/{human_name}/{platform}/{filename}`, with
sanitization of filesystem-hostile characters.

## 5. Discovery Flow

1. `GET /api/v1/user/order` → list of all `gamekey`s.
2. For each gamekey (concurrent, but throttled — see §10): `GET
   /api/v1/order/{gamekey}` → full order details.
3. Flatten each order's `subproducts[].downloads[].download_struct[]` into a
   single list of `DownloadItem`s.

`hbdl list` and `hbdl sync --dry-run` just print/serialize this list without
downloading anything — useful for testing the tool against the real account
before any bytes get written.

## 6. Direct Download (Queue)

- **Concurrency**: `concurrent.futures.ThreadPoolExecutor` (no asyncio
  needed — I/O-bound, but a manageable worker count, see §10).
- **Resume**: HTTP `Range` requests against a `.part` sidecar file; if the
  server returns `200` instead of `206` (range not supported / file
  changed), restart from scratch.
- **Retry/backoff**: exponential backoff (capped, max ~5 attempts) on
  connection errors/timeouts/5xx; `429` respects `Retry-After`.
- **Integrity check**: after completion, compare a streamed hash (sha1
  preferred, else md5) against the API value; on mismatch, delete + retry a
  limited number of times, then report as a hard failure in the run
  summary.
- **Idempotency**: SQLite state per identity key (status
  `pending`/`downloading`/`verified`/`failed`); on a repeat `hbdl sync`,
  already-`verified` files are skipped (including an on-disk stat check, in
  case they were deleted externally).
- **TTL handling**: signed URLs are time-limited. If `url_fetched_at` is
  older than a conservative threshold (~10 min, since the exact TTL isn't
  documented) or a download attempt returns 403/an expired signature, the
  order-detail route for exactly that gamekey is refetched and the URL
  replaced before retrying.
- **Progress**: a `tqdm` overall bar (bytes across all files) plus optional
  per-file bars in verbose mode.

## 7. BitTorrent Path

**v1 (this design, to be built first):** if `torrent_url` is set, the tool
only downloads the `.torrent` file itself (small, via the same direct-
download path) to `{dest}/{...}/{filename}.torrent` and tells the user to
open it with their own torrent client. No download of the actual content
via BitTorrent in v1.

Rationale: no new heavy dependencies, works on every platform immediately,
fully covers the core wish ("offer BitTorrent as an alternative") without
pulling in complexity that isn't needed.

**Later, optional expansion stages (not part of v1):**
- *v1.5*: hand off to a locally installed client (Transmission/qBittorrent)
  via its CLI/RPC, so the `.torrent` gets added automatically instead of
  opened manually.
- *v2*: `libtorrent` Python bindings as an optional extra (`hbdl[torrent]`)
  for a fully self-contained download workflow without an external client —
  with the caveat that `libtorrent` is a compiled C++ extension with real
  platform-packaging issues (not available as a wheel for every Python
  version/OS/architecture, especially Apple Silicon), which is why this is
  deliberately optional and pushed to later.

Not every file has a BitTorrent option (ebooks/audio in particular are
usually HTTP-only; torrents mostly show up for large game installers) — the
strategy choice therefore needs to be checked per file, not as a global
mode switch.

## 8. Strategy Choice

`--strategy {auto,direct,torrent}` (default: `auto`).

- `auto`: prefers torrent when `torrent_url` is present (v1: save the
  `.torrent`); otherwise direct download. This makes `auto` sensible even in
  v1, without the user needing to think about it.
- `direct`: forces a direct download for every file, even if a torrent
  option exists (useful on a metered/filtered network).
- `torrent`: forces torrent behavior for every file that has a
  `torrent_url`; files without a torrent option automatically fall back to
  direct (no abort).

Configurable default in `config.toml` (`default_strategy = "auto"`),
overridable via CLI flag.

## 9. CLI Surface

Proposal using `typer`:

```
hbdl auth login                    # guided Playwright login, saves cookie
hbdl auth check                    # validates the saved/passed cookie
hbdl list [--format table|json]    # discovery only, no download (dry run)
hbdl sync                          # main command: discovery + download
  --dest PATH                      # default ./HumbleLibrary or config default
  --cookie-file PATH
  --cookie VALUE
  --strategy {auto,direct,torrent} # default auto
  --workers N                      # default 3
  --platform windows,linux,ebook   # optional filter
  --product "name substring"       # optional filter
  --dry-run                        # print the plan only, no writes
  --verify-only                    # re-hash existing files against the manifest
hbdl config show / set KEY VALUE
```

`hbdl sync` is the one command most users need; the others exist for
diagnostics and controlled testing.

## 10. Error Handling & Rate Limiting

Humble Bundle is a real, paid third-party account — restraint is a hard
design requirement, not a nice-to-have:

- Default `--workers 3` for both order-detail fetches during discovery and
  downloads.
- The discovery phase (potentially dozens of order-detail calls) runs
  through the same throttled worker pool, not unbounded in parallel — that's
  the most API-hammering-suspicious traffic pattern.
- Global retry/backoff policy in the shared `HttpClient`: exponential
  backoff with jitter, limited attempts (~5), respect `Retry-After` on 429,
  circuit-breaker-style abort of the whole run on repeated 429/403 (better
  to fail loudly than to keep hammering a broken account).
- Individual file failures (404, hash mismatch after retries) don't abort
  the whole run — they're collected and reported as a summary at the end
  ("312 succeeded, 2 failed: ..."); a repeat `hbdl sync` only picks up the
  missing/failed files thanks to idempotency.
- No hidden background scheduling — a plain, manually invoked CLI tool, no
  daemon.

## 11. Proposed Dependencies

- `requests` (instead of `httpx`) — no async need given the thread-pool
  model; `requests.adapters.HTTPAdapter` + `urllib3.Retry` gets
  retry/backoff nearly for free.
- `typer` for the CLI (built on `click`, type-driven commands, good
  `--help` output).
- `playwright` for the guided login (including `playwright install
  chromium` as a one-time setup step).
- `tqdm` for progress bars.
- `platformdirs` for cross-platform config/state paths.
- `tenacity` (optional) for declarative retry/backoff policies instead of
  hand-rolling.
- stdlib `http.cookiejar.MozillaCookieJar` for Netscape cookie file
  parsing (fallback path).
- stdlib `sqlite3` for the state manifest.
- Optional extra `hbdl[torrent]` → `libtorrent` (v2 only).
- Dev/test: `pytest`, `pytest-mock`, `responses` (HTTP mocking for
  `requests`) — tests run offline against fixture JSON, never against the
  real API.

## 12. Build Milestones

1. **M1 — Auth + Discovery** (read-only, safest to test against the real
   account first): `auth.py` (Playwright login), `api.py`, `catalog.py`,
   `models.py`, `hbdl auth login/check`, `hbdl list`. Result: a complete
   `DownloadItem` list, no file writes.
2. **M2 — Direct Download Queue**: `downloader/direct.py`, `state.py`,
   `progress.py`, `hbdl sync --strategy direct`. Retry/backoff, resumable
   range requests, hash verification, idempotent repeat runs. The tool's
   core value.
3. **M3 — TTL/Robustness Hardening**: URL refresh on expiry, circuit
   breaker on repeated 429/403, error summary, `--verify-only` and
   `--dry-run`.
4. **M4 — BitTorrent v1 (Save-only)**: `downloader/torrent.py`,
   `--strategy torrent/auto` wiring in `strategy.py`.
5. **M5 (optional, later) — Client Handoff**: Transmission/qBittorrent CLI
   integration.
6. **M6 — Polish**: config file support, filters (`--platform`,
   `--product`), packaging (`pyproject.toml` final, `[torrent]` extra
   scaffold), README usage docs.
7. **M7 (optional, later) — `libtorrent` v2**, only if M4/M5 don't cover
   the need.

Every milestone should primarily be testable against recorded, sanitized
fixture JSON — real cookie tests against the live account should stay the
exception, not the rule.
