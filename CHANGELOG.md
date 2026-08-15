# Changelog

## v0.1.0 — initial implementation

Implements all milestones from [CONCEPT.md](CONCEPT.md):

- **M1 — Auth & discovery**: guided Playwright login (no credentials ever
  touch the tool itself), cookie-file fallback for headless use, and a
  read-only `hbdl list` that flattens the Humble Bundle API's order/subproduct
  structure into a flat list of downloadable files.
- **M2 — Direct download queue**: `hbdl sync` with resumable range requests,
  exponential backoff, hash verification, and a local SQLite manifest for
  idempotent reruns.
- **M3 — Robustness hardening**: a circuit breaker that aborts a run after
  repeated 403/429 responses instead of hammering a throttled or
  expired-cookie account, plus `hbdl sync --verify-only` for a network-free
  integrity re-check.
- **M4 — BitTorrent v1**: `--strategy {auto,direct,torrent}`. v1 only ever
  saves the small `.torrent` metadata file via plain HTTPS — it never opens a
  P2P connection, never talks to trackers/peers, and never invokes a torrent
  client. Real client handoff and an embedded torrent engine are deliberately
  out of scope (see CONCEPT.md section 7).

### Fixes from first real-account test run

The first end-to-end run against a real account (92 orders, ~2700 files, 710
GiB total) surfaced two related bugs, both rooted in the same cause: for
older bundles, Humble Bundle's API can return **stale metadata** — a game
build gets patched, or an ebook edition gets corrected, and the cached
`file_size`/hash in `download_struct` is never updated to match.

- **Hash-mismatch handling was too strict.** `_download_one` used to delete
  and retry (up to 5×) any file whose hash didn't match the API's value, even
  when the transfer itself was perfectly complete — discarding good downloads
  and burning bandwidth retrying into the same mismatch every time. A mismatch
  is now only a hard failure when the transfer was actually incomplete;
  otherwise the file is kept and reported as a warning
  (`DownloadResult.warning`, surfaced separately from real failures in the
  CLI output).
- **Transfer completeness is now checked against the real HTTP response**,
  not the API's cached `file_size`. A HEAD request during debugging confirmed
  the live `Content-Length` from Humble's CDN can differ from the API's
  stored size for the same URL — so that stored size was never a reliable
  truncation signal to begin with. The only trustworthy check for "did this
  transfer complete" is the `Content-Length` of the response actually
  received.
- **The state manifest now stores the size actually written to disk**, not
  the API's `file_size`. Storing the (possibly stale) API value would have
  made the idempotency skip check fail forever on these files, re-downloading
  them on every single `hbdl sync` run.

`verify_only()` mirrors the same warn-instead-of-fail behavior for files
already on disk.
