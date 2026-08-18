#!/usr/bin/env bash
# Logs in via a REAL native browser window on this machine (not the VNC-
# embedded one) -- full OS clipboard, autofill, password manager, and 2FA-app
# support, none of the copy-paste friction the VNC path has. Writes the
# resulting session into the same host folder the Docker container's /config
# volume points at (see docker-compose.yml), so the web UI picks it up
# automatically -- no cookie-copying, no VNC needed at all.
#
# Requirements: this repo checked out with a local venv that has hbdl[dev]
# installed and `playwright install chromium` already run (see README).
#
# Usage: ./docker/login-locally.sh
set -euo pipefail
cd "$(dirname "$0")/.."

HBDL_BIN="hbdl"
if [ -x ".venv/bin/hbdl" ]; then
  HBDL_BIN=".venv/bin/hbdl"
fi

export XDG_CONFIG_HOME="$(pwd)/hbdl-config"

echo "Oeffne ein Browserfenster fuer den Login -- melde dich dort normal an"
echo "(inkl. Captcha/2FA falls noetig), dann schliesst sich das Fenster automatisch."
echo ""

"$HBDL_BIN" auth login

echo ""
echo "Fertig. Die Web-Oberflaeche zeigt den Login jetzt als 'vorhanden' an"
echo "(Einstellungen-Seite neu laden, falls sie schon offen war)."
