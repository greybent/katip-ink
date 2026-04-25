#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
test_evdev.py — find your tablet device and verify evdev input works.

Run this BEFORE integrating evdev into the overlay:
    sudo python3 test_evdev.py        # needs root to read /dev/input
    # or add yourself to the input group:
    sudo usermod -aG input $USER      # then log out/in
    python3 test_evdev.py

Install evdev first:
    pip install evdev
"""

import sys

try:
    import evdev
except ImportError:
    print("evdev not installed. Run: pip install evdev")
    sys.exit(1)

print("=== Available input devices ===")
devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
for dev in devices:
    caps = dev.capabilities(verbose=True)
    has_abs = evdev.ecodes.EV_ABS in dev.capabilities()
    has_pen = any('TOOL_PEN' in str(c) or 'BTN_TOOL_PEN' in str(c)
                  for cap_list in caps.values() for c in cap_list
                  if isinstance(c, tuple))
    print(f"  {dev.path}: {dev.name!r}  abs={has_abs} pen={has_pen}")

print()
print("=== Tablet/stylus devices ===")
tablet_devs = []
for dev in devices:
    caps = dev.capabilities()
    if evdev.ecodes.EV_ABS in caps:
        abs_axes = [code for code, _ in caps[evdev.ecodes.EV_ABS]]
        if evdev.ecodes.ABS_PRESSURE in abs_axes:
            print(f"  FOUND: {dev.path}: {dev.name!r}")
            info = dev.capabilities()[evdev.ecodes.EV_ABS]
            for code, absinfo in info:
                if code in (evdev.ecodes.ABS_X, evdev.ecodes.ABS_Y,
                            evdev.ecodes.ABS_PRESSURE):
                    name = evdev.ecodes.ABS[code]
                    print(f"    {name}: min={absinfo.min} max={absinfo.max} res={absinfo.resolution}")
            tablet_devs.append(dev)

if not tablet_devs:
    print("  No tablet devices found with ABS_PRESSURE.")
    print("  Make sure your tablet is connected.")
    sys.exit(1)

print()
print(f"Testing first device: {tablet_devs[0].path}")
print("Move the stylus over the tablet — press Ctrl+C to stop")
print()

dev = tablet_devs[0]
x_info = dict(dev.capabilities()[evdev.ecodes.EV_ABS])[evdev.ecodes.ABS_X]
y_info = dict(dev.capabilities()[evdev.ecodes.EV_ABS])[evdev.ecodes.ABS_Y]
p_info = dict(dev.capabilities()[evdev.ecodes.EV_ABS])[evdev.ecodes.ABS_PRESSURE]

count = 0
try:
    for event in dev.read_loop():
        if event.type == evdev.ecodes.EV_ABS:
            if event.code == evdev.ecodes.ABS_X:
                count += 1
                if count % 20 == 0:
                    print(f"  x={event.value} (raw tablet units, max={x_info.max})")
        if count > 200:
            print("  200 X events received — evdev is working correctly!")
            break
except KeyboardInterrupt:
    print(f"\nReceived {count} X events total.")
    if count > 0:
        print("evdev is working. You can proceed with integration.")
    else:
        print("No events received. Check device permissions.")
