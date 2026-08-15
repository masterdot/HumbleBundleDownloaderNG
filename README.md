# HumbleBundleDownloaderNG

A new version of a humblebundle batch downloader.

See [CONCEPT.md](CONCEPT.md) for the full design (architecture, data model,
milestones). This README covers day-to-day usage of what's implemented so far.

## Status

Implemented (Milestone M1 — auth & discovery, read-only):

- `hbdl auth login` — guided login
- `hbdl auth check` — validates the current session
- `hbdl list` — lists every file in your library without downloading anything

Not yet implemented: actual downloading (`hbdl sync`), see CONCEPT.md milestones
M2+.

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

## Development

```bash
.venv/bin/python -m pytest
```

Tests run entirely offline against recorded/sanitized fixture JSON in
`tests/fixtures/` — no live Humble Bundle account is required.
