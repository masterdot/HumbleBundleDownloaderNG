// Forwards a local Cmd/Ctrl+V paste into the remote VNC session, so login
// credentials can be pasted directly instead of via noVNC's clipboard
// sidebar (open panel -> paste into textarea -> it syncs). See
// CONCEPT_WEB.md's M13 clipboard entries for the full history -- this is the
// fourth iteration, now served same-origin through the /vnc reverse proxy
// (web/routers/vnc_proxy.py) instead of a separate port. The first three
// attempts (bare `paste` listener, this same keydown approach cross-origin,
// a postMessage relay box) are kept there as a record of what didn't work
// and why; same-origin is what actually fixes the root cause (browsers
// silently refuse navigator.clipboard reads from a cross-origin iframe).
//
// Loaded after app/ui.js (which exposes window.UI.rfb once connected) by a
// patched clone of noVNC's own vnc.html -- see docker/Dockerfile. The stock
// vnc.html is left untouched.
(function () {
  // Standard X11 keysyms (X11/keysymdef.h) -- stable, effectively frozen
  // values; hardcoded here since this plain <script> (not a module) can't
  // import noVNC's own core/input/keysym.js constants.
  var XK_Control_L = 0xffe3;
  var XK_v = 0x0076;

  function isPasteShortcut(e) {
    var key = (e.key || "").toLowerCase();
    return key === "v" && (e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey;
  }

  function simulateRemoteCtrlV(rfb) {
    rfb.sendKey(XK_Control_L, "ControlLeft", true);
    rfb.sendKey(XK_v, "KeyV", true);
    rfb.sendKey(XK_v, "KeyV", false);
    rfb.sendKey(XK_Control_L, "ControlLeft", false);
  }

  document.addEventListener(
    "keydown",
    function (e) {
      if (!isPasteShortcut(e)) return;
      if (!window.UI || !window.UI.rfb) return;

      e.preventDefault();
      e.stopPropagation();

      var rfb = window.UI.rfb;

      if (!navigator.clipboard || !navigator.clipboard.readText) {
        // No Clipboard API available -- still forward a plain remote Ctrl+V
        // so the shortcut isn't just swallowed (works if the remote
        // clipboard already has something useful, e.g. set via the sidebar).
        simulateRemoteCtrlV(rfb);
        return;
      }

      navigator.clipboard
        .readText()
        .then(function (text) {
          if (text) {
            rfb.clipboardPasteFrom(text);
          }
          // Small delay: give the ClientCutText message a moment to reach
          // the server before the simulated keystroke asks the remote app
          // to act on it -- clipboardPasteFrom() only updates the remote
          // clipboard/selection, it doesn't itself trigger a paste.
          setTimeout(function () {
            simulateRemoteCtrlV(rfb);
          }, 50);
        })
        .catch(function (err) {
          // Permission denied, empty clipboard, or non-text content --
          // still forward the keystroke as a plain remote Ctrl+V fallback.
          console.warn("hbdl clipboard: readText() failed, falling back to remote Ctrl+V:", err);
          simulateRemoteCtrlV(rfb);
        });
    },
    true // capture phase: run before noVNC's own canvas keydown handler
  );

  // Best-effort remote-to-local direction (e.g. copying a 2FA code shown in
  // the remote browser back out). Not a direct local user gesture (the
  // remote side is what changed), so some browsers may silently refuse it
  // under their permissions policy -- the sidebar textarea
  // (#noVNC_clipboard_text) still receives the same update as a fallback.
  document.addEventListener("DOMContentLoaded", function () {
    var hookClipboardReceive = function () {
      if (window.UI && window.UI.rfb) {
        window.UI.rfb.addEventListener("clipboard", function (e) {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(e.detail.text).catch(function () {});
          }
        });
      } else {
        setTimeout(hookClipboardReceive, 500);
      }
    };
    hookClipboardReceive();
  });
})();
