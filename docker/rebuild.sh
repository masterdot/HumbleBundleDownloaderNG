#!/usr/bin/env bash
# Rebuilds and restarts the hbdl-web container, then prunes the now-unused
# image layers the previous build left behind.
#
# Why this exists: `docker compose up -d --build` replaces the running
# image but does NOT clean up the old one -- it just becomes dangling.
# Repeated rebuilds during development pile these up fast (this genuinely
# filled the host disk to ~150MB free during hbdl's own Docker/VNC work, see
# CONCEPT_WEB.md). `docker image prune -f` (no -a) only removes dangling,
# unnamed layers -- it never touches other tagged images from unrelated
# projects on the same machine.
#
# Usage: ./docker/rebuild.sh
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose build
docker compose up -d
docker image prune -f
