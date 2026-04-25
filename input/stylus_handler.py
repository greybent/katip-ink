# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
input/stylus_handler.py

Key insight from reference apps (rnote, xournalpp, Krita):
They receive every raw tablet motion event by connecting to low-level
motion-notify rather than a gesture controller. In GTK4 the equivalent
is GtkEventControllerMotion, which fires for every pointer motion event
without coalescing — unlike GtkGestureStylus.motion which merges events.

Architecture:
- GtkGestureStylus  : pen-down / pen-up / pressure axis only
- GtkEventControllerMotion : every motion event at full hardware rate
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib

from core.config import Config
from core.state_machine import StateMachine, State

log = logging.getLogger(__name__)

StrokeCallback = Callable[[float, float, float], None]
_FALLBACK_PRESSURE = 0.5


class StylusHandler:
    def __init__(
        self,
        widget: Gtk.Widget,
        cfg: Config,
        sm: StateMachine,
    ) -> None:
        self.cfg = cfg
        self.sm  = sm

        self.on_stroke_begin: Optional[StrokeCallback] = None
        self.on_stroke_point: Optional[StrokeCallback] = None
        self.on_stroke_end:   Optional[StrokeCallback] = None
        self.on_touch_point:  Optional[StrokeCallback] = None  # finger-only fallback

        self._countdown_source: Optional[int] = None
        self._drawing: bool = False
        self._last_pressure: float = _FALLBACK_PRESSURE
        self.evdev_active: bool = False  # set True by canvas when evdev takes over
        self.evdev_pen_near: bool = False  # mirrors evdev._pen_near for drag filtering

        # ── GtkGestureStylus: pen-down, pen-up, pressure ──────────────────
        stylus = Gtk.GestureStylus.new()
        stylus.connect("down", self._on_stylus_down)
        stylus.connect("up",   self._on_stylus_up)
        # motion on the stylus gesture is intentionally NOT connected —
        # we use GtkEventControllerMotion for motion to get every event
        widget.add_controller(stylus)
        self._stylus_gesture = stylus

        # ── GtkEventControllerMotion: raw motion at full hardware rate ────
        # This is what reference apps use — it fires for every input event
        # without any gesture coalescing, giving the full tablet resolution.
        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_raw_motion)
        widget.add_controller(motion)

        # ── Touch / drag fallback ─────────────────────────────────────────
        # Always add the controller; check cfg.input.touch_enabled at event
        # time so the setting can be toggled live without restarting.
        drag = Gtk.GestureDrag.new()
        drag.connect("drag-begin",  self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end",    self._on_drag_end)
        widget.add_controller(drag)
        self._drag_start: tuple[float, float] = (0.0, 0.0)

    # ------------------------------------------------------------------ #
    # Stylus down/up (pressure, state transitions)
    # ------------------------------------------------------------------ #

    def _on_stylus_down(self, gesture, x: float, y: float) -> None:
        self._last_pressure = self._get_pressure(gesture)
        self._drawing = True
        self._begin_stroke(x, y, self._last_pressure)

    def _on_stylus_up(self, gesture, x: float, y: float) -> None:
        self._drawing = False
        self._end_stroke(x, y, 0.0)

    # ------------------------------------------------------------------ #
    # Raw motion — fires for every tablet event, no coalescing
    # ------------------------------------------------------------------ #

    def _on_raw_motion(self, controller, x: float, y: float) -> None:
        if self.evdev_active:
            return  # evdev is handling motion — don't double-add points
        if not self._drawing:
            return
        # Try to get current pressure from the stylus gesture
        try:
            ok, pressure = self._stylus_gesture.get_axis(Gdk.AxisUse.PRESSURE)
            if not (ok and 0.0 <= pressure <= 1.0):
                pressure = self._last_pressure
            else:
                self._last_pressure = pressure
        except Exception:
            pressure = self._last_pressure
        self._add_point(x, y, pressure)

    # ------------------------------------------------------------------ #
    # Touch / drag fallback
    # ------------------------------------------------------------------ #

    def _on_drag_begin(self, gesture, x: float, y: float) -> None:
        if not self.cfg.input.touch_enabled:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        self._drag_start = (x, y)
        self._begin_stroke(x, y, _FALLBACK_PRESSURE)

    def _on_drag_update(self, gesture, dx: float, dy: float) -> None:
        sx, sy = self._drag_start
        x, y = sx + dx, sy + dy
        if not self.sm.is_drawing_active():
            return
        if self.evdev_active:
            # Only pass drag through if the stylus pen is NOT near the surface.
            # If pen is near, the drag is from the stylus — evdev handles that.
            # If pen is not near, the drag must be a finger — allow it.
            if not self.evdev_pen_near and self.on_touch_point:
                self.on_touch_point(x, y, _FALLBACK_PRESSURE)
        elif self.on_stroke_point:
            self.on_stroke_point(x, y, _FALLBACK_PRESSURE)

    def _on_drag_end(self, gesture, dx: float, dy: float) -> None:
        sx, sy = self._drag_start
        self._end_stroke(sx + dx, sy + dy, 0.0)

    # ------------------------------------------------------------------ #
    # Core stroke logic
    # ------------------------------------------------------------------ #

    def _begin_stroke(self, x: float, y: float, pressure: float) -> None:
        self._cancel_countdown()
        sm = self.sm
        if sm.state == State.IDLE:
            sm.transition(State.DRAWING)
        elif sm.state == State.COUNTDOWN:
            sm.transition(State.DRAWING)
        if self.on_stroke_begin:
            self.on_stroke_begin(x, y, pressure)

    def _add_point(self, x: float, y: float, pressure: float) -> None:
        if self.on_stroke_point and self.sm.is_drawing_active():
            self.on_stroke_point(x, y, pressure)

    def _end_stroke(self, x: float, y: float, pressure: float) -> None:
        if self.on_stroke_end:
            self.on_stroke_end(x, y, pressure)
        sm = self.sm
        if sm.state == State.DRAWING:
            sm.transition(State.COUNTDOWN)
            timeout_ms = int(self.cfg.recognition.timeout_seconds * 1000)
            self._countdown_source = GLib.timeout_add(
                timeout_ms, self._fire_recognition
            )

    def _fire_recognition(self) -> bool:
        self._countdown_source = None
        sm = self.sm
        if sm.state != State.COUNTDOWN:
            return GLib.SOURCE_REMOVE
        sm.transition(State.RECOGNIZING)
        from recognition.engine import RecognitionEngine
        RecognitionEngine.run_async(sm, language=self.cfg.recognition.active_language)
        return GLib.SOURCE_REMOVE

    def _cancel_countdown(self) -> None:
        if self._countdown_source is not None:
            GLib.source_remove(self._countdown_source)
            self._countdown_source = None
            if self.sm.state == State.COUNTDOWN:
                self.sm.transition(State.DRAWING)

    @staticmethod
    def _get_pressure(gesture: Gtk.GestureStylus) -> float:
        try:
            ok, val = gesture.get_axis(Gdk.AxisUse.PRESSURE)
            if ok and 0.0 <= val <= 1.0:
                return val
        except Exception:
            pass
        return _FALLBACK_PRESSURE
