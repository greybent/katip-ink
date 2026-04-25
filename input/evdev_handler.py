# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
input/evdev_handler.py — high-frequency stylus input via evdev.

Points are accumulated in a thread-safe queue and flushed to the GTK
main thread in a single GLib.timeout_add callback at ~200Hz. This avoids
the race condition where per-point GLib.idle_add calls arrive out of order
relative to the pen-down/pen-up events.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)

try:
    import evdev
    from evdev import ecodes
    _HAS_EVDEV = True
except ImportError:
    _HAS_EVDEV = False
    log.warning("evdev not installed — pip install evdev")

# Event type tags in the queue
_BEGIN = "B"
_POINT = "P"
_END   = "E"

# Flush interval in ms — 5ms = 200Hz, well above tablet rate
_FLUSH_MS = 5


class EvdevHandler:
    def __init__(
        self,
        cfg,
        on_begin: Callable[[float, float, float], None],
        on_point: Callable[[float, float, float], None],
        on_end:   Callable[[float, float, float], None],
    ) -> None:
        self.cfg      = cfg
        self.on_begin = on_begin
        self.on_point = on_point
        self.on_end   = on_end

        self._device:   Optional["evdev.InputDevice"] = None
        self._thread:   Optional[threading.Thread] = None
        self._running:  bool = False

        # Thread-safe queue: items are (_BEGIN/_POINT/_END, x, y, pressure)
        self._queue: queue.Queue = queue.Queue()
        self._flush_source: Optional[int] = None

        # Current accumulated axis state
        self._x:        int = 0
        self._y:        int = 0
        self._pressure: int = 0
        self._pen_down: bool = False
        self._pen_near: bool = False

        # Device ranges for normalisation
        self._x_max: int = 1
        self._y_max: int = 1
        self._p_max: int = 1

        self.screen_w, self.screen_h = self._get_screen_size()

        self._stylus_handler = None  # set by canvas after init for pen_near sync

        self.available: bool = False
        if _HAS_EVDEV:
            self._device = self._find_tablet()
            self.available = self._device is not None

    # ------------------------------------------------------------------ #
    # Device discovery
    # ------------------------------------------------------------------ #

    def _find_tablet(self) -> Optional["evdev.InputDevice"]:
        try:
            for path in evdev.list_devices():
                try:
                    dev = evdev.InputDevice(path)
                    caps = dev.capabilities()
                    if ecodes.EV_ABS not in caps:
                        continue
                    abs_map = dict(caps[ecodes.EV_ABS])
                    if all(k in abs_map for k in (
                        ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_PRESSURE
                    )):
                        self._x_max = max(abs_map[ecodes.ABS_X].max, 1)
                        self._y_max = max(abs_map[ecodes.ABS_Y].max, 1)
                        self._p_max = max(abs_map[ecodes.ABS_PRESSURE].max, 1)
                        log.info("evdev: found %r at %s (x=%d y=%d p=%d)",
                                 dev.name, path,
                                 self._x_max, self._y_max, self._p_max)
                        return dev
                except (PermissionError, OSError):
                    continue
        except Exception:
            log.exception("evdev: device discovery failed")
        log.warning("evdev: no tablet found — check: sudo usermod -aG input $USER")
        return None

    # ------------------------------------------------------------------ #
    # Start / stop
    # ------------------------------------------------------------------ #

    def start(self) -> bool:
        if not self.available or self._running:
            return False
        self._running = True
        self._thread = threading.Thread(
            target=self._read_loop, daemon=True, name="evdev-tablet"
        )
        try:
            self._thread.start()
        except Exception:
            self._running = False
            log.exception("evdev: failed to start thread")
            return False

        # Flush queue to GTK main thread at fixed interval
        from gi.repository import GLib
        self._flush_source = GLib.timeout_add(_FLUSH_MS, self._flush)
        log.info("evdev: started (flush every %dms)", _FLUSH_MS)
        return True

    def stop(self) -> None:
        self._running = False
        if self._flush_source is not None:
            from gi.repository import GLib
            GLib.source_remove(self._flush_source)
            self._flush_source = None
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # GTK main thread flush — called every _FLUSH_MS ms
    # ------------------------------------------------------------------ #

    def _flush(self) -> bool:
        """
        Drain the queue and call callbacks in order on the GTK main thread.
        All events in the queue were enqueued in hardware order, so flushing
        them sequentially preserves the correct point ordering.
        """
        while not self._queue.empty():
            try:
                tag, x, y, p = self._queue.get_nowait()
            except queue.Empty:
                break
            if   tag == _BEGIN: self.on_begin(x, y, p)
            elif tag == _POINT: self.on_point(x, y, p)
            elif tag == _END:   self.on_end(x, y, p)
        return True  # keep timer running

    # ------------------------------------------------------------------ #
    # Background read loop
    # ------------------------------------------------------------------ #

    def _read_loop(self) -> None:
        dev = self._device
        try:
            for event in dev.read_loop():
                if not self._running:
                    break

                if event.type == ecodes.EV_ABS:
                    if   event.code == ecodes.ABS_X:        self._x        = event.value
                    elif event.code == ecodes.ABS_Y:        self._y        = event.value
                    elif event.code == ecodes.ABS_PRESSURE: self._pressure = event.value

                elif event.type == ecodes.EV_KEY:
                    if event.code == ecodes.BTN_TOOL_PEN:
                        self._pen_near = bool(event.value)
                        # Sync to stylus_handler so drag can filter pen vs finger
                        if self._stylus_handler is not None:
                            self._stylus_handler.evdev_pen_near = self._pen_near
                        if not self._pen_near and self._pen_down:
                            self._pen_down = False
                            self._queue.put((_END, *self._to_normalized()))

                    elif event.code == ecodes.BTN_TOUCH:
                        if event.value == 1 and not self._pen_down:
                            self._pen_down = True
                            self._queue.put((_BEGIN, *self._to_normalized()))
                        elif event.value == 0 and self._pen_down:
                            self._pen_down = False
                            self._queue.put((_END, *self._to_normalized()))

                elif event.type == ecodes.EV_SYN:
                    if event.code == ecodes.SYN_REPORT and self._pen_down:
                        self._queue.put((_POINT, *self._to_normalized()))

        except OSError as e:
            if self._running:
                log.error("evdev: read error: %s", e)
        except Exception:
            log.exception("evdev: unexpected error in read loop")
        finally:
            # Always clear the running flag so start() can be retried after an error
            self._running = False

    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_screen_size():
        try:
            import gi
            gi.require_version("Gdk", "4.0")
            from gi.repository import Gdk
            display = Gdk.Display.get_default()
            monitor = display.get_monitors()[0]
            geo = monitor.get_geometry()
            # Use logical pixels only — we need the aspect ratio to detect
            # portrait vs landscape, not the physical pixel count.
            w = geo.width
            h = geo.height
            log.info("evdev: screen %dx%d (logical px)", w, h)
            return w, h
        except Exception as e:
            log.warning("evdev: screen size query failed (%s), using 1920x1200", e)
            return 1920, 1200

    def refresh_screen_size(self) -> None:
        """Re-query the monitor geometry. Call this on pen-down so that
        _to_normalized() uses the current orientation for axis-swap detection."""
        w, h = self._get_screen_size()
        if (w, h) != (self.screen_w, self.screen_h):
            log.info("evdev: screen size updated %dx%d → %dx%d",
                     self.screen_w, self.screen_h, w, h)
            self.screen_w, self.screen_h = w, h

    def _to_normalized(self):
        """
        Return (nx, ny, pressure) all in [0, 1].

        Coordinates are normalised to the canvas fraction rather than mapped
        to pixel values.  This sidesteps the scale-factor / logical-vs-physical
        pixel ambiguity entirely: the canvas multiplies by its own alloc
        dimensions (which are always in the correct logical-pixel units) to
        get final canvas coordinates.

        Axis-swap logic (only active when tablet and screen orientations differ):

          CCW (portrait-top = landscape-left edge of tablet):
            nx_out = 1 - ny_in   (tablet Y axis → inverted screen X)
            ny_out =     nx_in   (tablet X axis →          screen Y)

          CW (portrait-top = landscape-right edge of tablet):
            nx_out =     ny_in   (tablet Y axis →          screen X)
            ny_out = 1 - nx_in   (tablet X axis → inverted screen Y)
        """
        nx = self._x / self._x_max
        ny = self._y / self._y_max
        np_ = self._pressure / self._p_max

        tablet_is_landscape = self._x_max >= self._y_max
        screen_is_landscape = self.screen_w >= self.screen_h

        if tablet_is_landscape == screen_is_landscape:
            return nx, ny, np_

        rotation = getattr(self.cfg.input, "portrait_rotation", "ccw")
        if rotation == "ccw":
            return 1.0 - ny, nx, np_
        else:  # cw
            return ny, 1.0 - nx, np_
