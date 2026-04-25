# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
ui/canvas.py — Cairo-backed drawing surface with Shift+drag selection.

Stroke rendering uses per-segment variable width: each consecutive point
pair is drawn as a separate Cairo line with a line width derived from the
local (averaged) pressure of its two endpoints.  LINE_CAP_ROUND fills the
joints between adjacent segments seamlessly.  Laplacian smoothing is applied
to both x/y coordinates and pressure before rendering, so thickness
transitions are as gradual as positional transitions.

_render_highlight is the only path that still uses the single-width bezier
approach (_build_path + _avg_thickness), since selection indicators do not
need pressure variation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib

import cairo

from core.config import Config
from core.state_machine import StateMachine, State
from input.stylus_handler import StylusHandler
from input.pressure import pressure_to_thickness

log = logging.getLogger(__name__)

RGBAColor = Tuple[float, float, float, float]

# Minimum squared distance (px²) between consecutive stroke points.
# Filters sub-pixel ADC jitter from high-frequency evdev input which
# would otherwise create tiny zigzags in the rendered bezier path.
_MIN_POINT_DIST_SQ: float = 4.0  # 2 px minimum distance


def hex_to_rgba(hex_color: str, alpha: float = 1.0) -> RGBAColor:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    return (r, g, b, alpha)


@dataclass
class Stroke:
    color: RGBAColor
    points: List[Tuple[float, float, float]] = field(default_factory=list)

    def add_point(self, x: float, y: float, pressure: float) -> None:
        self.points.append((x, y, pressure))

    def is_valid(self) -> bool:
        return len(self.points) >= 2

    def bbox(self) -> Tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))


@dataclass
class TextLabel:
    """A text annotation placed at a canvas position."""
    text:  str
    x:     float
    y:     float
    color: RGBAColor
    size:  float = 18.0  # font size in px

    def bbox(self) -> Tuple[float, float, float, float]:
        # Approximate bbox: width ~= 0.6 * size * len, height ~= size
        w = self.size * len(self.text) * 0.6
        h = self.size * 1.2
        return (self.x, self.y - h, self.x + w, self.y)


class StrokeCanvas(Gtk.DrawingArea):
    def __init__(self, cfg: Config, sm: StateMachine) -> None:
        super().__init__()
        self.cfg = cfg
        self.sm  = sm

        self._committed:  List[Stroke] = []
        self._labels:     List[TextLabel] = []   # text annotations
        self._current:    Stroke | None = None
        self._brush_color: RGBAColor = hex_to_rgba(cfg.annotation.default_color)

        # UI dead zone: strokes that begin inside the status bar area are
        # suppressed so the stylus can tap buttons without creating ink.
        # Set by overlay_window via set_ui_dead_zone_widget().
        self._ui_dead_zone_widget = None

        # Dot detection: track pen-down position to detect single taps
        self._dot_origin: Optional[Tuple[float, float]] = None
        _DOT_THRESHOLD = 8  # px — movement beyond this is a stroke not a dot

        # Selection
        self._selected:   Set[int] = set()
        self._sel_origin: Optional[Tuple[float, float]] = None
        self._sel_rect:   Optional[Tuple[float, float, float, float]] = None
        self.shift_held:  bool = False

        # Input
        self._stylus = StylusHandler(self, cfg, sm)
        self._stylus.on_stroke_begin = self._on_stroke_begin
        self._stylus.on_stroke_point = self._on_stroke_point
        self._stylus.on_stroke_end   = self._on_stroke_end
        self._stylus.on_touch_point  = self._on_stroke_point  # finger bypass when evdev active

        # Try high-frequency evdev input — bypasses compositor event throttling
        self._evdev = None
        try:
            from input.evdev_handler import EvdevHandler
            handler = EvdevHandler(
                cfg=cfg,
                on_begin=self._on_evdev_begin,
                on_point=self._on_evdev_point,
                on_end=self._on_evdev_end,
            )
            if handler.available and handler.start():
                self._evdev = handler
                # Disable GTK raw motion — evdev handles motion now
                self._stylus.on_stroke_point = None
                self._stylus.evdev_active = True
                handler._stylus_handler = self._stylus  # for pen_near sync
                log.info("evdev: high-frequency input active")
            else:
                log.info("evdev: not available, using GTK input")
        except Exception as e:
            import traceback
            log.exception("evdev: failed to initialise")
            import sys
            traceback.print_exc(file=sys.stderr)

        sel_drag = Gtk.GestureDrag.new()
        sel_drag.set_button(1)
        sel_drag.connect("drag-begin",  self._on_sel_begin)
        sel_drag.connect("drag-update", self._on_sel_update)
        sel_drag.connect("drag-end",    self._on_sel_end)
        self.add_controller(sel_drag)

        self.set_draw_func(self._draw)
        self.set_focusable(True)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def set_ui_dead_zone_widget(self, widget) -> None:
        """Pass the bottom UI bar widget so strokes starting over it are ignored."""
        self._ui_dead_zone_widget = widget

    def _in_ui_zone(self, canvas_y: float) -> bool:
        """True when canvas_y falls inside the floating status bar at the bottom."""
        if self._ui_dead_zone_widget is None:
            return False
        zone_h = self._ui_dead_zone_widget.get_height()
        if zone_h <= 0:
            return False
        alloc = self.get_allocation()
        return canvas_y >= alloc.height - zone_h

    def set_brush_color(self, hex_color: str) -> None:
        self._brush_color = hex_to_rgba(hex_color)

    def clear(self) -> None:
        self._committed.clear()
        self._labels.clear()
        self._current = None
        self._selected.clear()
        self._sel_rect = None
        from recognition.engine import RecognitionEngine
        RecognitionEngine._active_surface = None
        RecognitionEngine._active_strokes = None
        RecognitionEngine._active_cfg     = None
        self.queue_draw()

    def delete_selected(self) -> bool:
        if not self._selected:
            return False
        self._committed = [s for i, s in enumerate(self._committed)
                           if i not in self._selected]
        self._selected.clear()
        self._sel_rect = None
        self.queue_draw()
        GLib.idle_add(self._snapshot_to_engine)
        return True

    def clear_selection(self) -> None:
        self._selected.clear()
        self._sel_rect = None
        self.queue_draw()

    @property
    def has_selection(self) -> bool:
        return bool(self._selected)

    # ------------------------------------------------------------------ #
    # Selection drag
    # ------------------------------------------------------------------ #

    def _on_sel_begin(self, gesture, x: float, y: float) -> None:
        if not self.shift_held:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._sel_origin = (x, y)
        self._sel_rect   = (x, y, x, y)
        self._selected.clear()
        self.queue_draw()

    def _on_sel_update(self, gesture, dx: float, dy: float) -> None:
        if self._sel_origin is None:
            return
        ox, oy = self._sel_origin
        x2, y2 = ox + dx, oy + dy
        rx1, rx2 = (ox, x2) if ox <= x2 else (x2, ox)
        ry1, ry2 = (oy, y2) if oy <= y2 else (y2, oy)
        self._sel_rect = (rx1, ry1, rx2, ry2)
        self._selected = {
            i for i, s in enumerate(self._committed)
            if _bbox_overlaps(s.bbox(), rx1, ry1, rx2, ry2)
        }
        self.queue_draw()

    def _on_sel_end(self, gesture, dx: float, dy: float) -> None:
        self._sel_origin = None
        self._sel_rect   = None
        self.queue_draw()

    # ------------------------------------------------------------------ #
    # Stroke lifecycle
    # ------------------------------------------------------------------ #

    def _on_stroke_begin(self, x: float, y: float, pressure: float) -> None:
        if self.shift_held:
            return
        if self._in_ui_zone(y):
            return
        self.clear_selection()
        self._dot_origin = (x, y)
        self._current = Stroke(color=self._brush_color)
        self._current.add_point(x, y, pressure)
        self.queue_draw()

    def _on_stroke_point(self, x: float, y: float, pressure: float) -> None:
        if self._current is not None:
            pts = self._current.points
            if pts:
                lx, ly, _ = pts[-1]
                if (x - lx) ** 2 + (y - ly) ** 2 < _MIN_POINT_DIST_SQ:
                    return
            self._current.add_point(x, y, pressure)
            self.queue_draw()

    # Maximum movement (px) for a tap to be treated as a dot, not a stroke
    _DOT_THRESHOLD: float = 8.0

    def _on_stroke_end(self, x: float, y: float, pressure: float) -> None:
        if self._current is None:
            return

        # Dot detection — single tap in ANNOTATING mode opens a text box
        if self.sm.state == State.ANNOTATING and self._dot_origin is not None:
            ox, oy = self._dot_origin
            dist = ((x - ox) ** 2 + (y - oy) ** 2) ** 0.5
            if dist < self._DOT_THRESHOLD:
                self._dot_origin = None
                self._current = None
                self.queue_draw()
                GLib.idle_add(self._show_text_entry, ox, oy)
                return

        self._dot_origin = None
        self._current.add_point(x, y, max(pressure, 0.0))
        if self._current.is_valid():
            if self._is_scribble(self._current):
                if self._erase_hits(self._current) > 0:
                    self._current = None
                    self.queue_draw()
                    GLib.idle_add(self._snapshot_to_engine)
                    return
            self._committed.append(self._current)
        self._current = None
        self.queue_draw()
        GLib.idle_add(self._snapshot_to_engine)

    # ------------------------------------------------------------------ #
    # evdev callbacks — called on the GTK main thread via the queue flush
    # timer (GLib.timeout_add) in EvdevHandler._flush()
    # ------------------------------------------------------------------ #

    def _evdev_to_canvas(self, x: float, y: float):
        """
        Convert normalised evdev coordinates [0,1]×[0,1] to canvas pixels.

        The tablet maps to the *full* screen (including any top panel), but the
        canvas window is positioned below the panel, so alloc.height < screen_h
        by roughly one panel height.  Mapping y → y*alloc.height would shift
        every stroke downward by ~panel_height.  The correct mapping is:

            canvas_x = x * screen_w  −  (screen_w − alloc.width)
            canvas_y = y * screen_h  −  (screen_h − alloc.height)

        This is identical in concept to the original _evdev_y_offset approach
        but now uses logical pixels throughout (no ×scale_factor bug).
        """
        alloc = self.get_allocation()
        sw = self._evdev.screen_w if self._evdev else alloc.width
        sh = self._evdev.screen_h if self._evdev else alloc.height
        cx = x * sw - (sw - alloc.width)
        cy = y * sh - (sh - alloc.height)
        return cx, cy

    def _on_evdev_begin(self, x: float, y: float, pressure: float) -> None:
        if self._evdev is not None:
            self._evdev.refresh_screen_size()
        cx, cy = self._evdev_to_canvas(x, y)
        if self._in_ui_zone(cy):
            return
        self._on_stroke_begin(cx, cy, pressure)

    def _on_evdev_point(self, x: float, y: float, pressure: float) -> None:
        if self._current is not None:
            cx, cy = self._evdev_to_canvas(x, y)
            pts = self._current.points
            if pts:
                lx, ly, _ = pts[-1]
                if (cx - lx) ** 2 + (cy - ly) ** 2 < _MIN_POINT_DIST_SQ:
                    return
            self._current.add_point(cx, cy, pressure)
            self.queue_draw()

    def _on_evdev_end(self, x: float, y: float, pressure: float) -> None:
        cx, cy = self._evdev_to_canvas(x, y)
        self._on_stroke_end(cx, cy, pressure)

    # ------------------------------------------------------------------ #
    # Text entry popover (annotation mode dot tap)
    # ------------------------------------------------------------------ #

    def _show_text_entry(self, x: float, y: float) -> bool:
        """
        Show a small popover with a text entry at canvas position (x, y).
        Enter confirms and renders the text as a Cairo label.
        Escape cancels.
        """
        # Build the popover
        popover = Gtk.Popover()
        popover.set_has_arrow(False)
        popover.set_autohide(True)

        entry = Gtk.Entry()
        entry.set_size_request(220, -1)
        entry.set_placeholder_text("Type annotation…")
        popover.set_child(entry)
        popover.set_parent(self)

        # Position the popover at the tap point
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width  = 1
        rect.height = 1
        popover.set_pointing_to(rect)

        color = self._brush_color

        def _on_activate(_entry):
            text = entry.get_text().strip()
            popover.popdown()
            if text:
                self._labels.append(TextLabel(
                    text=text, x=x, y=y, color=color
                ))
                self.queue_draw()
                GLib.idle_add(self._snapshot_to_engine)

        def _on_closed(_popover):
            # Re-enable shortcuts — focus returns to window
            self.get_root().set_focus(None)

        entry.connect("activate", _on_activate)
        popover.connect("closed", _on_closed)
        popover.popup()
        entry.grab_focus()
        return GLib.SOURCE_REMOVE

    # ------------------------------------------------------------------ #
    # Scribble-to-erase
    # ------------------------------------------------------------------ #

    def _is_scribble(self, stroke: Stroke) -> bool:
        ecfg = self.cfg.erase
        if not ecfg.enabled:
            return False
        pts = stroke.points
        if len(pts) < 8:
            return False
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x_span = max(xs) - min(xs)
        y_span = max(ys) - min(ys)

        # Must be wide enough and predominantly horizontal.
        # Loosened from 0.8 to 1.5 — a natural erasing motion can wander
        # vertically quite a bit without losing its horizontal character.
        if x_span < ecfg.min_width or y_span > x_span * 0.9:
            return False

        # Count direction reversals on smoothed segments rather than raw
        # per-point deltas. Evdev delivers hundreds of points per stroke so
        # consecutive same-direction micro-steps are merged into one segment
        # before counting reversals. This makes detection robust to both
        # noisy high-frequency input and slow deliberate scribbles.
        segments = []
        for i in range(1, len(xs)):
            dx = xs[i] - xs[i-1]
            if abs(dx) < 4:          # ignore small ADC noise (raised from 2→4 px)
                continue
            d = 1 if dx > 0 else -1
            if not segments or segments[-1] != d:
                segments.append(d)

        # Reversals = number of direction changes in the segment list
        reversals = sum(
            1 for i in range(1, len(segments)) if segments[i] != segments[i-1]
        )
        return reversals >= ecfg.min_reversals

    def _erase_hits(self, scribble: Stroke) -> int:
        """
        Erase committed strokes that overlap with the scribble.

        Two-phase approach:
        1. Bounding-box pre-filter — skip strokes whose bbox does not
           overlap the scribble bbox expanded by hit_threshold. This avoids
         the expensive point-level check for strokes nowhere near the scribble.
        2. Point-level hit test — only for strokes that pass the bbox filter.
           Sample every 3rd scribble point against every candidate stroke point.
        """
        thr = self.cfg.erase.hit_threshold
        thr2 = thr ** 2
        s_pts = scribble.points

        # Scribble bounding box expanded by threshold
        s_xs = [p[0] for p in s_pts]
        s_ys = [p[1] for p in s_pts]
        sx1 = min(s_xs) - thr
        sx2 = max(s_xs) + thr
        sy1 = min(s_ys) - thr
        sy2 = max(s_ys) + thr

        def _hits(c: Stroke) -> bool:
            # Phase 1: bounding box overlap check
            bx1, by1, bx2, by2 = c.bbox()
            if bx2 < sx1 or bx1 > sx2 or by2 < sy1 or by1 > sy2:
                return False
            # Phase 2: point proximity check
            for i in range(0, len(s_pts), 3):
                spx, spy = s_pts[i][0], s_pts[i][1]
                for cpx, cpy, _ in c.points:
                    if (spx - cpx)**2 + (spy - cpy)**2 <= thr2:
                        return True
            return False

        before_strokes = len(self._committed)
        self._committed = [s for s in self._committed if not _hits(s)]
        erased = before_strokes - len(self._committed)

        # Also erase text labels whose bbox overlaps the scribble area
        before_labels = len(self._labels)
        def _label_hit(lbl: TextLabel) -> bool:
            bx1, by1, bx2, by2 = lbl.bbox()
            # Expand label bbox by threshold and check against scribble bbox
            if bx2 + thr < sx1 or bx1 - thr > sx2:
                return False
            if by2 + thr < sy1 or by1 - thr > sy2:
                return False
            return True
        self._labels = [lbl for lbl in self._labels if not _label_hit(lbl)]
        erased += before_labels - len(self._labels)

        return erased

    # ------------------------------------------------------------------ #
    # Snapshot for OCR
    # ------------------------------------------------------------------ #

    def _snapshot_to_engine(self) -> bool:
        alloc = self.get_allocation()
        w, h = max(alloc.width, 1), max(alloc.height, 1)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        for stroke in self._committed:
            self._render_stroke(cr, stroke)
        surface.flush()
        from recognition.engine import RecognitionEngine
        RecognitionEngine._active_surface = surface
        RecognitionEngine._active_strokes = list(self._committed)
        RecognitionEngine._active_cfg     = self.cfg
        # Store canvas dimensions for the Google API writing_guide
        self.cfg._canvas_alloc = (w, h)
        return GLib.SOURCE_REMOVE

    # ------------------------------------------------------------------ #
    # Cairo rendering
    # ------------------------------------------------------------------ #

    def _draw(self, area, cr: cairo.Context, w: int, h: int) -> None:
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        for i, stroke in enumerate(self._committed):
            self._render_stroke(cr, stroke)
            if i in self._selected:
                self._render_highlight(cr, stroke)

        for label in self._labels:
            self._render_label(cr, label)

        if self._current is not None:
            self._render_stroke(cr, self._current)

        if self._sel_rect is not None:
            self._render_sel_rect(cr, self._sel_rect)

    def _smooth_pts(self, pts: list) -> list:
        """
        Two passes of Laplacian smoothing on x, y, AND pressure.

        Smoothing pressure alongside coordinates ensures that width transitions
        are as gradual as the position transitions — no abrupt jumps in thickness
        from ADC noise that survived the minimum-distance filter.
        Endpoints are pinned so the stroke starts/ends exactly where the pen touched.
        Runs only at render time; stored points and OCR data are unaffected.
        """
        if len(pts) < 3:
            return pts
        for _ in range(2):
            out = [pts[0]]
            for i in range(1, len(pts) - 1):
                sx = (pts[i-1][0] + pts[i][0] * 2 + pts[i+1][0]) * 0.25
                sy = (pts[i-1][1] + pts[i][1] * 2 + pts[i+1][1]) * 0.25
                sp = (pts[i-1][2] + pts[i][2] * 2 + pts[i+1][2]) * 0.25
                out.append((sx, sy, sp))
            out.append(pts[-1])
            pts = out
        return pts

    def _thickness_at(self, pressure: float, extra: float = 0.0) -> float:
        cfg_i = self.cfg.input
        return pressure_to_thickness(
            pressure, cfg_i.pressure_curve,
            cfg_i.min_thickness, cfg_i.max_thickness,
        ) + extra

    def _avg_thickness(self, pts: list, extra: float = 0.0) -> float:
        """Average-pressure thickness — kept for selection highlight only."""
        cfg_i = self.cfg.input
        avg_p = sum(p[2] for p in pts) / len(pts)
        return pressure_to_thickness(
            avg_p, cfg_i.pressure_curve,
            cfg_i.min_thickness, cfg_i.max_thickness,
        ) + extra

    def _render_segments(
        self, cr, smoothed: list, r, g, b, a, extra: float = 0.0
    ) -> None:
        """
        Draw smoothed points as individual line segments, each with its own
        line width derived from the local (averaged) pressure of its two endpoints.

        LINE_CAP_ROUND is essential: the round end-caps of adjacent segments
        overlap at their shared midpoint, filling the joint seamlessly even when
        neighbouring segments have slightly different widths.  This is the same
        technique used by Procreate, rnote, and Krita for pressure-sensitive ink.
        """
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_antialias(cairo.ANTIALIAS_BEST)
        cr.set_source_rgba(r, g, b, a)
        for i in range(len(smoothed) - 1):
            x0, y0, p0 = smoothed[i]
            x1, y1, p1 = smoothed[i + 1]
            cr.set_line_width(self._thickness_at((p0 + p1) * 0.5, extra))
            cr.move_to(x0, y0)
            cr.line_to(x1, y1)
            cr.stroke()

    def _render_stroke(self, cr, stroke: Stroke) -> None:
        pts = stroke.points
        if len(pts) < 2:
            return
        r, g, b, a = stroke.color
        smoothed = self._smooth_pts(pts)
        if self.cfg.annotation.glow_enabled:
            self._render_glow(cr, stroke, r, g, b, self.cfg.annotation.glow_radius, smoothed)
        self._render_segments(cr, smoothed, r, g, b, a)

    def _render_glow(self, cr, stroke: Stroke, r, g, b, radius, smoothed=None) -> None:
        pts = stroke.points
        if len(pts) < 2:
            return
        if smoothed is None:
            smoothed = self._smooth_pts(pts)
        glow_color = self.cfg.annotation.glow_color
        if glow_color and glow_color.lower() != "auto":
            try:
                h = glow_color.lstrip("#")
                gr, gg, gb = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
            except Exception:
                gr, gg, gb = r, g, b
        else:
            gr, gg, gb = r, g, b
        for pass_i in range(4, 0, -1):
            factor = pass_i / 4
            self._render_segments(cr, smoothed, gr, gg, gb, 0.08 * factor,
                                  extra=radius * factor * 2)

    def _build_path(self, cr, pts: list) -> None:
        """Bezier path through smoothed points — used only for selection highlight."""
        if len(pts) < 2:
            return
        def mid(a, b):
            return ((a[0]+b[0])*0.5, (a[1]+b[1])*0.5)
        sx, sy = mid(pts[0], pts[1])
        cr.move_to(sx, sy)
        for i in range(1, len(pts) - 1):
            cx, cy = pts[i][0], pts[i][1]
            ex, ey = mid(pts[i], pts[i+1])
            cr.curve_to(cx, cy, cx, cy, ex, ey)
        cr.line_to(pts[-1][0], pts[-1][1])

    def _render_sel_rect(self, cr, rect) -> None:
        x1, y1, x2, y2 = rect
        w, h = x2 - x1, y2 - y1
        cr.set_source_rgba(0.3, 0.6, 1.0, 0.08)
        cr.rectangle(x1, y1, w, h)
        cr.fill()
        cr.set_source_rgba(0.4, 0.7, 1.0, 0.9)
        cr.set_line_width(1.5)
        cr.set_dash([6.0, 4.0])
        cr.rectangle(x1, y1, w, h)
        cr.stroke()
        cr.set_dash([])
        if self._selected:
            n = len(self._selected)
            lbl = f"{n} stroke{'s' if n != 1 else ''} — Delete to remove"
            cr.set_font_size(13)
            cr.set_source_rgba(1, 1, 1, 0.9)
            cr.move_to(x1 + 6, y1 - 6)
            cr.show_text(lbl)

    def _render_highlight(self, cr, stroke: Stroke) -> None:
        pts = stroke.points
        if len(pts) < 2:
            return
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_antialias(cairo.ANTIALIAS_BEST)
        cr.set_source_rgba(0.4, 0.7, 1.0, 0.5)
        cr.set_line_width(self._avg_thickness(pts) + 5)
        self._build_path(cr, pts)
        cr.stroke()


    def _render_label(self, cr, label: TextLabel) -> None:
        r, g, b, a = label.color
        cr.set_antialias(cairo.ANTIALIAS_BEST)
        # Subtle glow behind text for readability
        if self.cfg.annotation.glow_enabled:
            glow_color = self.cfg.annotation.glow_color
            if glow_color and glow_color.lower() != "auto":
                try:
                    h = glow_color.lstrip("#")
                    gr, gg, gb = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
                except Exception:
                    gr, gg, gb = r, g, b
            else:
                gr, gg, gb = r, g, b
            cr.set_source_rgba(gr, gg, gb, 0.25)
            cr.set_font_size(label.size + 4)
            cr.move_to(label.x + 1, label.y + 1)
            cr.show_text(label.text)
        # Main text
        cr.set_source_rgba(r, g, b, a)
        cr.set_font_size(label.size)
        cr.move_to(label.x, label.y)
        cr.show_text(label.text)


# ── Module-level helper ───────────────────────────────────────────────────────

def _bbox_overlaps(
    bbox: Tuple[float, float, float, float],
    rx1: float, ry1: float, rx2: float, ry2: float,
) -> bool:
    bx1, by1, bx2, by2 = bbox
    return bx1 <= rx2 and bx2 >= rx1 and by1 <= ry2 and by2 >= ry1
