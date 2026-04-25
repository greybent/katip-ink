#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
debug_inject.py — paste this into a terminal WHILE the overlay is running,
or run it standalone. It replaces the full inject chain with direct subprocess
calls and prints every step.

Usage (standalone — focus a text editor first):
    python3 debug_inject.py "hello world"
"""
import subprocess, sys, time, os, shutil

text = sys.argv[1] if len(sys.argv) > 1 else "test_injection_123"
print(f"Testing injection of: {text!r}")
print()

# ── 1. Check ydotoold socket ──────────────────────────────────────────────────
socket = os.environ.get("YDOTOOL_SOCKET", "/tmp/.ydotool_socket")
import stat as _stat
try:
    assert _stat.S_ISSOCK(os.stat(socket).st_mode)
    print(f"[OK] ydotoold socket: {socket}")
except Exception as e:
    print(f"[FAIL] ydotoold socket missing: {e}")
    sys.exit(1)

# ── 2. ydotool type ───────────────────────────────────────────────────────────
print(f"\nFocusing your text editor... typing in 2s")
time.sleep(2)

r = subprocess.run(
    ["ydotool", "type", "--next-delay", "12", "--", text],
    capture_output=True, text=True, timeout=15
)
print(f"ydotool type → rc={r.returncode}")
if r.stdout: print(f"  stdout: {r.stdout!r}")
if r.stderr: print(f"  stderr: {r.stderr!r}")

if r.returncode != 0:
    print("\n[FAIL] ydotool type failed. Check daemon permissions.")
    sys.exit(1)
print("[OK] ydotool type succeeded")

# ── 3. ydotool key Return ─────────────────────────────────────────────────────
time.sleep(0.1)
r2 = subprocess.run(
    ["ydotool", "key", "KEY_RETURN"],
    capture_output=True, text=True, timeout=5
)
print(f"\nydotool key KEY_RETURN → rc={r2.returncode}")
if r2.stderr: print(f"  stderr: {r2.stderr!r}")

if r2.returncode != 0:
    r3 = subprocess.run(["ydotool", "key", "28"], capture_output=True, text=True)
    print(f"ydotool key 28 → rc={r3.returncode}")

print("\nDone. Check your text editor.")

# ── Also test: does the overlay's keyboard mode call work? ────────────────────
# Run this block manually to verify GtkLayerShell is present:
#   python3 -c "
#   import gi; gi.require_version('GtkLayerShell','0.1')
#   from gi.repository import GtkLayerShell
#   print('GtkLayerShell OK, version:', GtkLayerShell.get_major_version())
#   "
