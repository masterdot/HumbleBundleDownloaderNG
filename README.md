# HumbleBundleDownloaderNG

A new version of a humblebundle batch downloader.

See [CONCEPT.md](CONCEPT.md) for the full design (architecture, data model,
milestones). This README covers day-to-day usage of what's implemented so far.

## Status

Implemented:

- **M1 — auth & discovery** (read-only): `hbdl auth login`, `hbdl auth check`,
  `hbdl list`.
- **M2 — direct download queue**: `hbdl sync` downloads every file via
  resumable, hash-verified HTTP downloads, tracked in a local SQLite manifest
  so reruns skip already-verified files.
- **M3 — robustness hardening**: a circuit breaker aborts the whole run after
  repeated 403/429 responses instead of quietly hammering a throttled/expired
  account, and `hbdl sync --verify-only` re-hashes already-downloaded files
  against the manifest without any network downloads.

Not yet implemented: BitTorrent support (M4) — `--strategy` currently only
accepts `direct`. See CONCEPT.md for the full milestone list.

## Setup

```bash
uv venv .venv
uv pip install -e ".[dev]" --python .venv/bin/python
.venv/bin/playwright install chromium   # one-time, needed for `auth login`
```

## Usage

Log in once (opens a real browser window — you complete the login, including
any captcha/2FA, yourself; hbdl only reads out the resulting session cookie
afterwards):

```bash
hbdl auth login
```

Verify the session works:

```bash
hbdl auth check
```

List everything in your library (dry run, no downloads):

```bash
hbdl list
hbdl list --format json > library.json
```

If you're on a headless machine without a display, skip `auth login` and pass
a cookie directly instead (see CONCEPT.md section 2 for the Netscape
`cookies.txt` format):

```bash
hbdl list --cookie-file cookies.txt
hbdl list --cookie "$HBDL_COOKIE"
```

Download everything:

```bash
hbdl sync --dest ~/HumbleLibrary
```

Re-running `hbdl sync` is safe and cheap — already-downloaded, hash-verified
files are skipped (tracked in a local SQLite manifest, not by trusting the
filesystem alone). Filter by platform, or preview without writing anything:

```bash
hbdl sync --platform windows,ebook
hbdl sync --dry-run
```

Re-check integrity of what's already on disk without downloading anything:

```bash
hbdl sync --verify-only
```

## Development

```bash
.venv/bin/python -m pytest
```

Tests run entirely offline against recorded/sanitized fixture JSON in
`tests/fixtures/` — no live Humble Bundle account is required.
