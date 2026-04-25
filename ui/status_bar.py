# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
ui/status_bar.py — Adwaita status bar at the bottom of the overlay.

Displays: mode indicator · language selector · engine selector · countdown
          · Annotate toggle · brush colour picker (with palette icon) · ⚙ options button

The options button opens ui/options_dialog.py via a callback set by overlay_window.
"""

from __future__ import annotations

import logging

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from core.config import Config
from core.state_machine import StateMachine, State

log = logging.getLogger(__name__)

_STATE_LABELS = {
    State.IDLE:        ("● Idle", "accent"),
    State.DRAWING:     ("✏ Drawing", "success"),
    State.COUNTDOWN:   ("⏱ Countdown", "warning"),
    State.RECOGNIZING: ("🔍 Recognizing…", "warning"),
    State.ANNOTATING:  ("🖌 Annotation", "error"),
}


class StatusBar(Adw.Bin):
    def __init__(self, cfg: Config, sm: StateMachine) -> None:
        super().__init__()
        self.cfg = cfg
        self.sm = sm

        self._countdown_value: float = cfg.recognition.timeout_seconds
        self._countdown_source: int | None = None
        self._on_mode_toggle_cb = None
        self._on_options_cb = None

        self._build_ui()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        bar = Gtk.Box(spacing=16)
        bar.add_css_class("toolbar")
        bar.set_margin_start(12)
        bar.set_margin_end(12)
        bar.set_margin_top(4)
        bar.set_margin_bottom(4)

        # Mode label
        self._mode_label = Gtk.Label(label="● Idle")
        self._mode_label.add_css_class("caption")
        bar.append(self._mode_label)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        bar.append(sep)

        # Language selector
        lang_box = Gtk.Box(spacing=4)
        lang_box.append(Gtk.Label(label="Lang:"))
        self._lang_combo = Gtk.DropDown.new_from_strings(
            self.cfg.recognition.languages
        )
        active_idx = 0
        try:
            active_idx = self.cfg.recognition.languages.index(
                self.cfg.recognition.active_language
            )
        except ValueError:
            pass
        self._lang_combo.set_selected(active_idx)
        self._lang_combo.connect("notify::selected", self._on_lang_changed)
        lang_box.append(self._lang_combo)
        bar.append(lang_box)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        bar.append(sep2)

        # Engine selector
        engine_box = Gtk.Box(spacing=4)
        engine_box.append(Gtk.Label(label="Engine:"))
        self._engine_combo = Gtk.DropDown.new_from_strings(["Google", "MyScript"])
        active_engine = getattr(self.cfg.recognition, "engine", "google")
        self._engine_combo.set_selected(0 if active_engine == "google" else 1)
        self._engine_combo.connect("notify::selected", self._on_engine_changed)
        engine_box.append(self._engine_combo)
        bar.append(engine_box)

        sep3e = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        bar.append(sep3e)

        # Countdown label
        self._countdown_label = Gtk.Label(label="")
        self._countdown_label.add_css_class("caption")
        bar.append(self._countdown_label)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)

        # Annotation mode toggle button
        self._annotate_btn = Gtk.ToggleButton(label="🖌 Annotate")
        self._annotate_btn.set_tooltip_text("Toggle Annotation mode (Shift+A)")
        self._annotate_btn.add_css_class("flat")
        self._annotate_btn.connect("toggled", self._on_annotate_toggled)
        bar.append(self._annotate_btn)

        sep3 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        bar.append(sep3)

        # Color swatch button with palette icon
        color_box = Gtk.Box(spacing=4)
        color_icon = Gtk.Image.new_from_icon_name("applications-graphics-symbolic")
        color_box.append(color_icon)
        self._color_btn = Gtk.ColorButton()
        self._color_btn.set_tooltip_text("Brush color")
        color_box.append(self._color_btn)
        bar.append(color_box)

        sep4 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        bar.append(sep4)

        # Options button
        self._options_btn = Gtk.Button(icon_name="preferences-system-symbolic")
        self._options_btn.set_tooltip_text("Options (settings)")
        self._options_btn.add_css_class("flat")
        self._options_btn.connect("clicked", self._on_options_clicked)
        bar.append(self._options_btn)

        self.set_child(bar)

    # ------------------------------------------------------------------ #
    def on_state_changed(self, old: State, new: State) -> None:
        GLib.idle_add(self._sync_ui, new)

        if new == State.COUNTDOWN:
            self._start_countdown()
        else:
            self._stop_countdown()

    def _sync_ui(self, state: State) -> bool:
        label, css_class = _STATE_LABELS.get(state, ("?", ""))
        self._mode_label.set_label(label)
        # Remove old accent classes
        for cls in ("accent", "success", "warning", "error"):
            self._mode_label.remove_css_class(cls)
        if css_class:
            self._mode_label.add_css_class(css_class)
        # Keep toggle button in sync — block its signal to avoid feedback loop
        self._annotate_btn.handler_block_by_func(self._on_annotate_toggled)
        self._annotate_btn.set_active(state == State.ANNOTATING)
        self._annotate_btn.handler_unblock_by_func(self._on_annotate_toggled)
        return GLib.SOURCE_REMOVE

    # ------------------------------------------------------------------ #
    def _start_countdown(self) -> None:
        self._countdown_value = self.cfg.recognition.timeout_seconds
        self._update_countdown_label()
        if self._countdown_source is not None:
            GLib.source_remove(self._countdown_source)
        self._countdown_source = GLib.timeout_add(100, self._tick_countdown)

    def _stop_countdown(self) -> None:
        if self._countdown_source is not None:
            GLib.source_remove(self._countdown_source)
            self._countdown_source = None
        self._countdown_label.set_label("")

    def _tick_countdown(self) -> bool:
        self._countdown_value -= 0.1
        self._update_countdown_label()
        if self._countdown_value <= 0:
            self._countdown_source = None
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _update_countdown_label(self) -> None:
        val = max(self._countdown_value, 0.0)
        self._countdown_label.set_label(f"OCR in {val:.1f}s")

    # ------------------------------------------------------------------ #
    def _on_lang_changed(self, combo, _param) -> None:
        idx = combo.get_selected()
        langs = self.cfg.recognition.languages
        if 0 <= idx < len(langs):
            self.cfg.recognition.active_language = langs[idx]
            log.info("Language changed to %s", langs[idx])

    def _on_engine_changed(self, combo, _param) -> None:
        engine = "google" if combo.get_selected() == 0 else "myscript"
        self.cfg.recognition.engine = engine
        log.info("Recognition engine changed to %s", engine)

    def _on_annotate_toggled(self, btn: Gtk.ToggleButton) -> None:
        if self._on_mode_toggle_cb:
            self._on_mode_toggle_cb()

    def _on_options_clicked(self, _btn) -> None:
        if self._on_options_cb:
            self._on_options_cb()

    def set_mode_toggle_callback(self, cb) -> None:
        """Wire up an external callback for the annotate button."""
        self._on_mode_toggle_cb = cb

    def set_options_callback(self, cb) -> None:
        """Wire up an external callback for the options button."""
        self._on_options_cb = cb

    @property
    def color_button(self) -> Gtk.ColorButton:
        return self._color_btn
