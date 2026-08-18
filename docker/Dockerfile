# Multi-stage build. `cli` is a minimal image for `docker run --rm hbdl:cli ...`
# / `docker exec` scripting use; `web` extends it with the FastAPI web layer
# plus the VNC-based guided-login stack (Xvfb/x11vnc/noVNC/websockify,
# supervisord, Playwright Chromium -- CONCEPT_WEB.md M13). This makes `web`
# noticeably heavier (~1-1.5GB) -- if you only ever plan to use the
# cookie-paste login fallback and never need the embedded browser, `cli` +
# `hbdl auth login` on the host is the lighter path.
#
# No Humble-Bundle-specific data (session cookie, config.toml, state.sqlite,
# downloaded library files) is ever baked into either stage -- see the
# XDG_CONFIG_HOME / XDG_DATA_HOME / HBDL_DEST env vars in docker-compose.yml.

FROM python:3.12-slim AS cli
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
ENTRYPOINT ["hbdl"]
CMD ["--help"]

FROM cli AS web
RUN pip install --no-cache-dir ".[web]"

# Xvfb (virtual display) + x11vnc (VNC server on that display) + novnc/
# websockify (browser-accessible VNC client, served on :6080) + supervisor
# (runs all of this alongside the FastAPI app as one container process).
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        x11vnc \
        novnc \
        websockify \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

# Playwright manages its own OS-dependency list (fonts, codecs, etc.) rather
# than us hand-listing them -- see CONCEPT.md's rationale for guided_login().
RUN playwright install --with-deps chromium

COPY docker/supervisord.conf /etc/supervisor/conf.d/hbdl.conf

# Clone (not patch in place) noVNC's own vnc.html so the stock file stays
# untouched, and load one small extra script that auto-forwards local paste
# (Cmd+V/Ctrl+V) into the remote VNC session -- see the JS file's own
# comments and CONCEPT_WEB.md for why this doesn't need clipboard
# permissions. Settings' login iframe points at hbdl-vnc.html, not vnc.html.
COPY docker/novnc-clipboard-autopaste.js /usr/share/novnc/hbdl-clipboard-autopaste.js
RUN cp /usr/share/novnc/vnc.html /usr/share/novnc/hbdl-vnc.html \
    && sed -i 's#import UI from "./app/ui.js";#import UI from "./app/ui.js"; window.UI = UI;#' /usr/share/novnc/hbdl-vnc.html \
    && sed -i 's#</body>#<script src="hbdl-clipboard-autopaste.js"></script></body>#' /usr/share/novnc/hbdl-vnc.html

ENV DISPLAY=:99
EXPOSE 8000 6080
ENTRYPOINT ["supervisord", "-c", "/etc/supervisor/conf.d/hbdl.conf"]
