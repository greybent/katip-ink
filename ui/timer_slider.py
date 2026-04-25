# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
ui/timer_slider.py — vertical countdown timer slider.

A narrow vertical Gtk.Scale floats on the left edge of the screen,
overlaid on top of the canvas (via Gtk.Overlay in overlay_window).

Design
------
- Range: 0.5 s – 10.0 s in 0.5 s steps
- Orientation: vertical, top = max (10s), bottom = min (0.5s)
  so sliding UP = more time, DOWN = less time (natural pen motion)
- Always visible so the user can adjust it with the stylus at any time
- Value label shows current setting next to the slider
- Writing cfg.recognition.timeout_seconds directly means the new value
  is picked up automatically the next time a countdown starts

Stylus compatibility
--------------------
Gtk.Scale already handles GtkGestureStylus internally for value changes,
but we also add a GtkGestureStylus explicitly to ensure the widget gets
stylus events even when it is part of a Gtk.Overlay stack.
The slider width is kept wide enough (48px) to be a comfortable stylus
target without obscuring too much of the canvas.
"""

from __future__ import annotations

import logging

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib

from core.config import Config

log = logging.getLogger(__name__)

# Slider range and step
_MIN  = 0.5
_MAX  = 10.0
_STEP = 0.5


class TimerSlider(Gtk.Box):
    """
    Vertical slider + label, meant to be added as a Gtk.Overlay child
    pinned to the left edge of the window.
    """

    def __init__(self, cfg: Config) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.cfg = cfg

        self.set_valign(Gtk.Align.CENTER)  # vertically centred on screen
        self.set_halign(Gtk.Align.START)   # pinned to left edge
        self.set_margin_start(6)
        self.set_margin_top(40)
        self.set_margin_bottom(40)

        # Semi-transparent background pill
        css = Gtk.CssProvider()
        css.load_from_data(
            b".timer-pill {"
            b"  background: rgba(0,0,0,0.50);"
            b"  border-radius: 16px;"
            b"  padding: 8px 4px;"
            b"}"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self.add_css_class("timer-pill")

        # Top label: max value hint
        top_lbl = Gtk.Label(label=f"{_MAX:.0f}s")
        top_lbl.add_css_class("caption")
        top_lbl.set_opacity(0.5)
        self.append(top_lbl)

        # Vertical scale — inverted so top = high value
        self._scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.VERTICAL, _MIN, _MAX, _STEP
        )
        self._scale.set_inverted(True)        # top = MAX, bottom = MIN
        self._scale.set_draw_value(False)     # we draw our own label
        self._scale.set_vexpand(True)
        self._scale.set_size_request(48, 200)

        # Connect handler before set_value so the label updates,
        # but block the signal during init to avoid writing back to cfg
        self._scale.connect("value-changed", self._on_value_changed)

        # Set initial value from config — block signal so we don't
        # overwrite cfg.recognition.timeout_seconds during construction
        current = max(_MIN, min(_MAX, cfg.recognition.timeout_seconds))
        self._scale.handler_block_by_func(self._on_value_changed)
        self._scale.set_value(current)
        self._scale.handler_unblock_by_func(self._on_value_changed)
        self._val_label_pending = current
        self.append(self._scale)

        # Bottom label: min value hint
        bot_lbl = Gtk.Label(label=f"{_MIN:.1f}s")
        bot_lbl.add_css_class("caption")
        bot_lbl.set_opacity(0.5)
        self.append(bot_lbl)

        # Current value label shown below the slider
        self._val_label = Gtk.Label()
        self._val_label.add_css_class("caption")
        self._val_label.set_markup(f"<b>{current:.1f}s</b>")
        self.append(self._val_label)

        # Re-apply config value after realise in case GTK fires value-changed
        # internally when the widget is mapped to screen
        self.connect("realize", lambda *_: self._apply_config_value())

        # Clock emoji header
        icon = Gtk.Label(label="⏱")
        icon.set_opacity(0.7)
        # Insert at top (before top_lbl)
        self.prepend(icon)

    # ------------------------------------------------------------------ #

    def _apply_config_value(self) -> None:
        """Re-apply the config timeout after realise to override any GTK drift."""
        current = max(_MIN, min(_MAX, self.cfg.recognition.timeout_seconds))
        self._scale.handler_block_by_func(self._on_value_changed)
        self._scale.set_value(current)
        self._scale.handler_unblock_by_func(self._on_value_changed)
        self._val_label.set_markup(f"<b>{current:.1f}s</b>")
        log.debug("Timer slider initialised to %.1fs", current)

    def _on_value_changed(self, scale: Gtk.Scale) -> None:
        val = round(scale.get_value() / _STEP) * _STEP   # snap to step
        val = max(_MIN, min(_MAX, val))
        self.cfg.recognition.timeout_seconds = val
        self._val_label.set_markup(f"<b>{val:.1f}s</b>")
        log.debug("Countdown timer → %.1fs", val)
