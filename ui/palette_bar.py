# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
ui/palette_bar.py — floating palette of color swatches.

Rendered as a slim horizontal strip of circular buttons, one per color
in utils.color.PALETTE plus a custom-color picker at the end.

The active color is highlighted with a ring; clicking any swatch
immediately updates the canvas brush and records the color for new
strokes (without touching historical strokes).

The palette bar is appended inside the main overlay box and is only
visible in ANNOTATING state.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib

from core.state_machine import StateMachine, State
from utils.color import PALETTE, hex_to_rgba, rgba_to_hex

log = logging.getLogger(__name__)

_SWATCH_SIZE = 24
_SWATCH_CSS = """
.swatch {{
    min-width:  {sz}px;
    min-height: {sz}px;
    max-width:  {sz}px;
    max-height: {sz}px;
    border-radius: {r}px;
    padding: 0;
    background-color: {color};
    border: 2px solid transparent;
    transition: border-color 120ms;
}}
.swatch:hover {{
    border-color: alpha(white, 0.6);
}}
.swatch-active {{
    border-color: white;
    box-shadow: 0 0 0 2px rgba(0,0,0,0.4);
}}
""".format(sz=_SWATCH_SIZE, r=_SWATCH_SIZE // 2, color="{color}")


class PaletteBar(Gtk.Box):
    """
    Horizontal strip of color swatches.

    Parameters
    ----------
    sm:              StateMachine — used to show/hide the bar by state.
    on_color_change: Callable[[str], None] — receives hex color on selection.
    """

    def __init__(
        self,
        sm: StateMachine,
        on_color_change: Callable[[str], None],
    ) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6,
        )
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_top(6)
        self.set_margin_bottom(6)

        self._sm = sm
        self._on_color_change = on_color_change
        self._active_hex: str = PALETTE[0]
        self._swatch_buttons: dict[str, Gtk.Button] = {}

        self._build_swatches()
        self._build_custom_picker()

        # Only show in ANNOTATING state
        sm.add_listener(self._on_state_changed)
        self.set_visible(sm.state == State.ANNOTATING)

    # ------------------------------------------------------------------ #
    def _build_swatches(self) -> None:
        for hex_color in PALETTE:
            btn = Gtk.Button()
            btn.set_tooltip_text(hex_color)

            # Inline CSS per button via a provider
            css = Gtk.CssProvider()
            css.load_from_data(
                f".swatch {{ background-color: {hex_color}; }}".encode()
            )
            btn.add_css_class("swatch")
            btn.get_style_context().add_provider(
                css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

            btn.connect("clicked", self._on_swatch_clicked, hex_color)
            self._swatch_buttons[hex_color] = btn
            self.append(btn)

        self._mark_active(self._active_hex)

    def _build_custom_picker(self) -> None:
        picker = Gtk.ColorButton()
        picker.set_tooltip_text("Custom color…")
        picker.set_size_request(_SWATCH_SIZE, _SWATCH_SIZE)
        picker.connect("color-set", self._on_custom_color)
        self.append(picker)

    # ------------------------------------------------------------------ #
    def _on_swatch_clicked(self, _btn: Gtk.Button, hex_color: str) -> None:
        self._select_color(hex_color)

    def _on_custom_color(self, btn: Gtk.ColorButton) -> None:
        rgba = btn.get_rgba()
        hex_color = rgba_to_hex(rgba.red, rgba.green, rgba.blue)
        self._select_color(hex_color)

    def _select_color(self, hex_color: str) -> None:
        self._mark_active(hex_color)
        self._active_hex = hex_color
        self._on_color_change(hex_color)
        log.debug("Palette: selected %s", hex_color)

    def cycle_next(self) -> None:
        """Advance to the next palette color. Wraps around. Called by Tab key."""
        keys = list(self._swatch_buttons.keys())
        if not keys:
            return
        try:
            idx = keys.index(self._active_hex)
        except ValueError:
            idx = -1
        next_hex = keys[(idx + 1) % len(keys)]
        self._select_color(next_hex)
        log.debug("Palette: cycled to %s", next_hex)

    def _mark_active(self, hex_color: str) -> None:
        for hx, btn in self._swatch_buttons.items():
            if hx == hex_color:
                btn.add_css_class("swatch-active")
            else:
                btn.remove_css_class("swatch-active")

    # ------------------------------------------------------------------ #
    def _on_state_changed(self, _old: State, new: State) -> None:
        GLib.idle_add(self.set_visible, new == State.ANNOTATING)
