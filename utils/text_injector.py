# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
utils/text_injector.py — inject recognised text into the focused window.

Strategy priority (auto mode):
  wl_paste       — wl-copy writes text to the clipboard (Unicode,
                   layout-independent), then ydotool sends raw Ctrl+V
                   keycodes (29:1 47:1 47:0 29:0) to paste it.
                   Fixes the QWERTZ y↔z swap because individual characters
                   are never mapped through the keyboard layout.
                   Limitation: terminals use Ctrl+Shift+V, not Ctrl+V.
                   Requires: wl-clipboard + ydotoold daemon.

  ydotool        — ydotool type simulates keystrokes via /dev/uinput.
                   Works in terminals. y↔z swapped on QWERTZ keyboards
                   because ydotool maps characters → keycodes via the
                   active XKB layout, then the compositor maps them back.
                   Requires: ydotoold daemon.

  clipboard_only — wl-copy only; shows a "press Ctrl+V" toast.
                   Always works, no paste performed.

Note: wtype is not used — GNOME Shell does not expose the
      zwp_virtual_keyboard_v1 Wayland protocol.

Socket path: resolved from $YDOTOOL_SOCKET → $XDG_RUNTIME_DIR/.ydotool_socket
             → /run/user/<uid>/.ydotool_socket (in that priority order).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

# ydotoold socket — prefer $XDG_RUNTIME_DIR, fall back to /tmp
_YDOTOOL_SOCKET = os.environ.get(
    "YDOTOOL_SOCKET",
    os.path.join(
        os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
        ".ydotool_socket",
    ),
)


def _ydotool_ok() -> bool:
    if not shutil.which("ydotool"):
        return False
    try:
        import stat
        return stat.S_ISSOCK(os.stat(_YDOTOOL_SOCKET).st_mode)
    except OSError:
        return False


def _wl_copy_ok() -> bool:
    return bool(shutil.which("wl-copy"))


def _best_strategy() -> str:
    if _wl_copy_ok() and _ydotool_ok():
        return "wl_paste"
    if _ydotool_ok():
        return "ydotool"
    if _wl_copy_ok():
        return "clipboard_only"
    return "clipboard_only"


def backend_status() -> dict:
    return {
        "ydotool":        bool(shutil.which("ydotool")),
        "ydotool_daemon": _ydotool_ok(),
        "ydotool_socket": _YDOTOOL_SOCKET,
        "wl_copy":        _wl_copy_ok(),
        "wtype":          bool(shutil.which("wtype")),
        "best_strategy":  _best_strategy(),
    }


def inject_text_async(
    text: str,
    focus_release_delay_ms: int = 150,
    press_enter: bool = False,
    strategy: str = "auto",
    hide_callback: Optional[Callable[[], None]] = None,
    on_done: Optional[Callable[[bool], None]] = None,
) -> None:
    from gi.repository import GLib

    if hide_callback:
        try:
            hide_callback()
        except Exception:
            log.exception("hide_callback raised")

    delay_s = max(focus_release_delay_ms, 100) / 1000.0

    resolved = _best_strategy() if strategy == "auto" else strategy
    log.info("inject_text_async: strategy=%s resolved=%s socket=%s",
             strategy, resolved, _YDOTOOL_SOCKET)

    def _worker():
        time.sleep(delay_s)

        ok = False
        try:
            if resolved == "wl_paste":
                ok = _inject_wl_paste(text, press_enter)
            elif resolved == "ydotool":
                ok = _inject_ydotool(text, press_enter)
            else:
                ok = _inject_clipboard(text)

        except Exception as e:
            print(f"[inject] exception: {e}", file=sys.stderr, flush=True)
            ok = False

        if on_done:
            GLib.idle_add(on_done, ok)

    threading.Thread(target=_worker, daemon=True).start()


# ── Backend implementations ────────────────────────────────────────────────────

def _inject_wl_paste(text: str, press_enter: bool) -> bool:
    """
    Copy text to clipboard with wl-copy (Unicode, layout-independent),
    then paste with ydotool key Ctrl+V (keycodes 29+47).

    This avoids the QWERTZ y↔z swap: ydotool is only used to press Ctrl+V,
    not to type individual characters.

    Note: terminals typically use Ctrl+Shift+V to paste — Ctrl+V will not
    work in GNOME Terminal, Alacritty, Kitty etc.
    """
    env = dict(os.environ, YDOTOOL_SOCKET=_YDOTOOL_SOCKET)

    r = subprocess.run(["wl-copy", "--", text], timeout=10)
    if r.returncode != 0:
        log.warning("wl-copy failed (exit %d)", r.returncode)
        return False

    time.sleep(0.05)
    # 29 = KEY_LEFTCTRL, 47 = KEY_V
    r2 = subprocess.run(
        ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
        env=env, timeout=10,
    )
    ok = r2.returncode == 0

    if ok and press_enter:
        # Wait long enough for the paste to land before Enter fires.
        # 150 ms is generous but avoids submitting an empty field in slow apps.
        time.sleep(0.15)
        subprocess.run(["ydotool", "key", "28:1", "28:0"], env=env, timeout=5)

    return ok


def _inject_ydotool(text: str, press_enter: bool) -> bool:
    """
    Inject via ydotool type (keycodes via uinput, needs ydotoold).
    Note: y and z are swapped on QWERTZ keyboards — use wl_paste instead.
    """
    env = dict(os.environ, YDOTOOL_SOCKET=_YDOTOOL_SOCKET)
    r = subprocess.run(
        ["ydotool", "type", "--next-delay", "12", "--", text],
        env=env, timeout=30,
    )
    if r.returncode != 0:
        return False
    if press_enter:
        time.sleep(0.05)
        r2 = subprocess.run(["ydotool", "key", "KEY_RETURN"], env=env, timeout=5)
        if r2.returncode != 0:
            subprocess.run(["ydotool", "key", "28"], env=env, timeout=5)
    return True


def _inject_clipboard(text: str) -> bool:
    """Copy text to clipboard only (user must Ctrl+V manually)."""
    if not shutil.which("wl-copy"):
        return False
    r = subprocess.run(["wl-copy", "--", text], timeout=10)
    return r.returncode == 0
