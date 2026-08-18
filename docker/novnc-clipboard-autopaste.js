// Auto-forwards local Cmd/Ctrl+V into the remote VNC session, so login
// credentials can be pasted directly. See CONCEPT_WEB.md's M13/Nachtrag-2/3
// clipboard entries for the full history -- this iteration works because of
// a fix in docker/Dockerfile: stock noVNC's `UI` object is only ever
// `export default UI` from app/ui.js, imported into the *module scope* of
// the inline <script type="module"> in vnc.html -- it was never actually
// `window.UI`, so every earlier version's `if (!window.UI...) return;`
// guard silently returned true on every keypress and none of this script's
// logic ever ran (no permission prompt, no error, keydown just fell
// through to noVNC's own default canvas handler, which is why a stale
// value from the remote-side clipboard got typed instead). Dockerfile now
// patches hbdl-vnc.html to add `window.UI = UI;` right after the import, so
// `UI` is genuinely global here -- confirmed working manually via the sync
// button below before wiring the shortcut back up.
//
// Loaded after app/ui.js (which sets UI.rfb once connected) by a patched
// clone of noVNC's own vnc.html -- see docker/Dockerfile. The stock
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

  // Sends `text` to the remote clipboard via noVNC's own sidebar mechanism
  // (UI.clipboardSend() -> rfb.clipboardPasteFrom()) instead of calling
  // rfb.clipboardPasteFrom() directly, so the sidebar textarea and the
  // remote clipboard never disagree with each other.
  function sendToRemoteClipboard(text) {
    var textarea = document.getElementById("noVNC_clipboard_text");
    if (!textarea) return;
    textarea.value = text;
    window.UI.clipboardSend();
  }

  document.addEventListener(
    "keydown",
    function (e) {
      if (!isPasteShortcut(e)) return;
      if (!window.UI || !window.UI.rfb) return;
      if (!navigator.clipboard || !navigator.clipboard.readText) return;

      e.preventDefault();
      e.stopPropagation();

      var rfb = window.UI.rfb;

      navigator.clipboard
        .readText()
        .then(function (text) {
          if (text) {
            sendToRemoteClipboard(text);
          }
          // Small delay: give the ClientCutText message a moment to reach
          // the server before the simulated keystroke asks the remote app
          // to act on it -- clipboardSend() only updates the remote
          // clipboard/selection, it doesn't itself trigger a paste.
          setTimeout(function () {
            simulateRemoteCtrlV(rfb);
          }, 50);
        })
        .catch(function (err) {
          console.warn("hbdl clipboard: readText() failed, falling back to remote Ctrl+V:", err && err.name, err && err.message);
          simulateRemoteCtrlV(rfb);
        });
    },
    true // capture phase: run before noVNC's own canvas keydown handler
  );

  // Manual fallback: same sync, triggered by a visible button instead of a
  // keypress -- useful the first time, before the browser has granted the
  // clipboard-read permission (or if it's denied outright), and as a way to
  // sync the remote clipboard without also emitting a paste keystroke.
  function syncClipboard() {
    if (!window.UI || !window.UI.rfb) {
      console.warn("hbdl clipboard sync: not connected yet (window.UI.rfb missing)");
      return;
    }
    if (!navigator.clipboard || !navigator.clipboard.readText) {
      console.warn("hbdl clipboard sync: navigator.clipboard.readText unavailable");
      return;
    }

    window.UI.openClipboardPanel();
    var textarea = document.getElementById("noVNC_clipboard_text");
    if (!textarea) {
      console.warn("hbdl clipboard sync: #noVNC_clipboard_text not found");
      return;
    }
    textarea.focus();

    navigator.clipboard
      .readText()
      .then(function (text) {
        sendToRemoteClipboard(text);
        console.log("hbdl clipboard sync: sent", text.length, "chars to remote clipboard");
      })
      .catch(function (err) {
        console.warn("hbdl clipboard sync failed:", err && err.name, err && err.message);
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var button = document.createElement("button");
    button.textContent = "📋 Zwischenablage synchronisieren";
    button.style.position = "fixed";
    button.style.top = "8px";
    button.style.right = "8px";
    button.style.zIndex = "10000";
    button.style.padding = "6px 10px";
    button.style.cursor = "pointer";
    button.addEventListener("click", syncClipboard);
    document.body.appendChild(button);
  });

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
