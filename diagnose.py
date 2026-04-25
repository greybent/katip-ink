#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
diagnose.py — run this from a terminal while the overlay is NOT running.
It tests every injection step in isolation and prints a clear pass/fail.

Usage:
    python3 diagnose.py

Open a text editor first so there is a window to receive keystrokes.
"""

import os
import shutil
import subprocess
import sys
import time

SEP = "─" * 60

def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")

def ok(msg):   print(f"  ✓  {msg}")
def fail(msg): print(f"  ✗  {msg}")
def info(msg): print(f"     {msg}")

# ── 1. Tool availability ──────────────────────────────────────────────────────
section("1. Tool availability")

tools = {
    "ydotool":  shutil.which("ydotool"),
    "xdotool":  shutil.which("xdotool"),
    "wl-copy":  shutil.which("wl-copy"),
    "wtype":    shutil.which("wtype"),
}
for name, path in tools.items():
    if path:
        ok(f"{name}  →  {path}")
    else:
        fail(f"{name}  NOT FOUND")

# ── 2. ydotoold socket ────────────────────────────────────────────────────────
section("2. ydotoold daemon socket")

socket_path = os.environ.get("YDOTOOL_SOCKET", "/tmp/.ydotool_socket")
info(f"Socket path: {socket_path}")

try:
    import stat as _stat
    s = os.stat(socket_path)
    if _stat.S_ISSOCK(s.st_mode):
        ok("ydotoold socket exists and is a socket")
    else:
        fail("Path exists but is NOT a socket")
except FileNotFoundError:
    fail("Socket not found — daemon is not running")
    info("Fix: sudo systemctl start ydotool")
    info("  or: sudo ydotoold &")

# ── 3. Wayland environment ────────────────────────────────────────────────────
section("3. Wayland / display environment")

wayland = os.environ.get("WAYLAND_DISPLAY")
display  = os.environ.get("DISPLAY")
xdg_rt   = os.environ.get("XDG_RUNTIME_DIR")

info(f"WAYLAND_DISPLAY = {wayland!r}")
info(f"DISPLAY         = {display!r}")
info(f"XDG_RUNTIME_DIR = {xdg_rt!r}")

if wayland:
    ok("Running on Wayland")
elif display:
    info("Running on X11 (xdotool will work, ydotool may work)")
else:
    fail("Neither WAYLAND_DISPLAY nor DISPLAY set — no compositor?")

# ── 4. wl-copy clipboard write ────────────────────────────────────────────────
section("4. wl-copy clipboard write")

if tools["wl-copy"]:
    test_text = "DIAGNOSE_TEST_wl_copy"
    try:
        proc = subprocess.Popen(
            ["wl-copy", "--", test_text],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        time.sleep(0.3)
        # Read back with wl-paste
        if shutil.which("wl-paste"):
            r = subprocess.run(["wl-paste", "--no-newline"],
                               capture_output=True, text=True, timeout=3)
            if r.stdout == test_text:
                ok("wl-copy wrote and wl-paste read back correctly")
            else:
                fail(f"wl-paste returned {r.stdout!r}, expected {test_text!r}")
        else:
            ok("wl-copy ran without error (wl-paste not available for readback)")
        proc.terminate()
    except Exception as e:
        fail(f"wl-copy exception: {e}")
else:
    info("wl-copy not installed — skipping")
    info("Install: sudo apt install wl-clipboard")

# ── 5. ydotool type ───────────────────────────────────────────────────────────
section("5. ydotool type  (focus a text editor NOW — text will appear in 3s)")

if tools["ydotool"]:
    info("Waiting 3 seconds — click into a text editor...")
    time.sleep(3)
    test = "ydotool_test_123"
    r = subprocess.run(
        ["ydotool", "type", "--next-delay", "12", "--", test],
        capture_output=True, text=True, timeout=15
    )
    if r.returncode == 0:
        ok(f"ydotool type returned 0 — check your text editor for: {test!r}")
    else:
        fail(f"ydotool type failed (rc={r.returncode})")
        info(f"stderr: {r.stderr.strip()}")
        info(f"stdout: {r.stdout.strip()}")
else:
    fail("ydotool not installed")
    info("Install: sudo apt install ydotool")

# ── 6. ydotool key Enter ──────────────────────────────────────────────────────
section("6. ydotool key Enter  (should press Enter in text editor)")

if tools["ydotool"]:
    time.sleep(0.5)
    r1 = subprocess.run(["ydotool", "key", "KEY_RETURN"],
                        capture_output=True, text=True, timeout=5)
    if r1.returncode == 0:
        ok("ydotool key KEY_RETURN succeeded")
    else:
        info(f"KEY_RETURN failed (rc={r1.returncode}): {r1.stderr.strip()}")
        info("Trying numeric keycode 28...")
        r2 = subprocess.run(["ydotool", "key", "28"],
                            capture_output=True, text=True, timeout=5)
        if r2.returncode == 0:
            ok("ydotool key 28 succeeded")
        else:
            fail(f"Both KEY_RETURN and 28 failed: {r2.stderr.strip()}")
            info("Your ydotool version may use a different syntax.")
            info("Try manually: ydotool key --help")
else:
    info("ydotool not installed — skipping")

# ── 7. xdotool type ───────────────────────────────────────────────────────────
section("7. xdotool type  (XWayland only)")

if tools["xdotool"]:
    if not display:
        info("No DISPLAY set — xdotool will not work on pure Wayland")
    else:
        time.sleep(1)
        test = "xdotool_test_456"
        r = subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay", "12", "--", test],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            ok(f"xdotool type returned 0 — check your text editor for: {test!r}")
        else:
            fail(f"xdotool type failed (rc={r.returncode}): {r.stderr.strip()}")
else:
    info("xdotool not installed — skipping")

# ── 8. wl_paste strategy (wl-copy + Ctrl+V) ─────────────────────────────────
section("8. wl_paste: wl-copy + wtype Ctrl+V  (focus a text editor — pastes in 3s)")

if tools["wl-copy"] and tools["wtype"]:
    test_text = "wl_paste_test Hello"
    info(f"Writing {test_text!r} to clipboard with wl-copy...")
    try:
        proc = subprocess.Popen(
            ["wl-copy", "--", test_text],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        time.sleep(0.1)
        info("Waiting 3 seconds — click into a text editor...")
        time.sleep(3)
        r = subprocess.run(["wtype", "-M", "ctrl", "-k", "v"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            ok("wtype ctrl+v returned 0 — check editor for: " + repr(test_text))
            info("(This is the preferred strategy — layout-independent)")
        else:
            fail(f"wtype ctrl+v failed (rc={r.returncode}): {r.stderr.strip()}")
            info("Possible cause: no window had focus when Ctrl+V was sent.")
            info("Increase focus_release_delay_ms in config.yaml (try 400)")
        proc.terminate()
    except Exception as e:
        fail(f"wl_paste test exception: {e}")
else:
    info("wl-copy or wtype not installed — skipping")
    info("Install: sudo apt install wl-clipboard wtype")

# ── 9. Keyboard layout detection ──────────────────────────────────────────────
section("9. Keyboard layout")

try:
    r = subprocess.run(["localectl", "status"], capture_output=True, text=True, timeout=3)
    for line in r.stdout.splitlines():
        if "Layout" in line or "layout" in line:
            info(line.strip())
            if any(layout in line for layout in ["de", "at", "ch", "qwertz"]):
                info("QWERTZ layout detected — ydotool type will mangle y/z and special chars")
                info("wl_paste strategy bypasses this problem completely")
except Exception:
    pass

try:
    r2 = subprocess.run(["setxkbmap", "-query"], capture_output=True, text=True, timeout=3)
    for line in r2.stdout.splitlines():
        if "layout" in line:
            info(f"setxkbmap: {line.strip()}")
except Exception:
    pass

# ── Summary ───────────────────────────────────────────────────────────────────
section("Summary & Recommendation")

if tools["wl-copy"] and tools["wtype"]:
    ok("wl_paste strategy available — RECOMMENDED for GNOME")
    info("Set in config.yaml:  strategy: wl_paste  (or leave as auto)")
    info("This is layout-independent: works correctly on QWERTZ/AZERTY/etc.")
elif tools["ydotool"] and os.path.exists(socket_path):
    info("ydotool available but may mangle text on non-US layouts")
    info("Install wl-clipboard + wtype for reliable injection:")
    info("  sudo apt install wl-clipboard wtype")
elif tools["xdotool"] and display:
    ok("xdotool available — set  strategy: xdotool  in config.yaml (XWayland only)")
elif tools["wl-copy"]:
    info("Only clipboard available — text will be copied, paste manually with Ctrl+V")
else:
    fail("No injection tools available")
    info("Install: sudo apt install wl-clipboard wtype")

print()
