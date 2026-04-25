# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
ui/options_dialog.py — Adwaita preferences window for live config editing.

Opened via the ⚙ button in the status bar. Changes take effect immediately
by writing directly to the live Config object — no restart required.

Pages:
  Typing      — injection strategy, delay, press Enter, clear/quit after inject
  Recognition — engine selection, MyScript credentials, timeout, layout factors
  Appearance  — default brush colour, glow on/off, glow radius
  Input       — pressure curve preset, min/max thickness, touch enabled
  Erase       — scribble-to-erase parameters
  Save        — write all settings back to config.yaml (comments not preserved)

The window is non-modal so the user can draw while it is open.
"""

from __future__ import annotations

import logging

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Adw, Gdk

from core.config import Config

log = logging.getLogger(__name__)

_STRATEGIES = ["auto", "wl_paste", "ydotool", "clipboard_only"]
_STRATEGY_LABELS = [
    "Auto (recommended)",
    "wl_paste — clipboard + Ctrl+V  (fixes QWERTZ y↔z, not for terminals)",
    "ydotool — direct keystrokes  (works in terminals, y↔z on QWERTZ)",
    "Clipboard only — copy, no paste",
]

_ENGINES = ["google", "myscript"]
_ENGINE_LABELS = [
    "Google Handwriting API  (no key required)",
    "MyScript Cloud API  (requires application key + HMAC key)",
]

_PRESSURE_PRESETS = [
    ("Soft",      [(0.0, 0.0), (0.10, 0.50), (0.50, 0.90), (1.0, 1.0)]),
    ("Medium",    [(0.0, 0.0), (0.30, 0.10), (0.70, 0.90), (1.0, 1.0)]),
    ("Firm",      [(0.0, 0.0), (0.50, 0.10), (0.85, 0.70), (1.0, 1.0)]),
    ("Very Firm", [(0.0, 0.0), (0.65, 0.05), (0.95, 0.70), (1.0, 1.0)]),
]
_PRESSURE_LABELS = [name for name, _ in _PRESSURE_PRESETS]
_PRESSURE_CURVES = [curve for _, curve in _PRESSURE_PRESETS]


class OptionsDialog(Adw.PreferencesWindow):
    def __init__(self, cfg: Config, parent: Gtk.Window) -> None:
        super().__init__()
        self.cfg = cfg
        self.set_title("Katip Options")
        self.set_transient_for(parent)
        self.set_modal(False)
        self.set_default_size(620, 560)
        self.set_search_enabled(True)

        self.add(self._build_typing_page())
        self.add(self._build_recognition_page())
        self.add(self._build_appearance_page())
        self.add(self._build_input_page())
        self.add(self._build_erase_page())
        self.add(self._build_save_page())

    # ------------------------------------------------------------------ #
    # Pages
    # ------------------------------------------------------------------ #

    def _build_typing_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Typing", icon_name="input-keyboard-symbolic")

        group = Adw.PreferencesGroup(title="Text Injection")
        page.add(group)

        # Strategy
        strategy_row = Adw.ComboRow(title="Injection strategy")
        strategy_row.set_subtitle(
            "How recognised text is sent to the target window"
        )
        model = Gtk.StringList.new(_STRATEGY_LABELS)
        strategy_row.set_model(model)
        current = self.cfg.typing.strategy
        idx = _STRATEGIES.index(current) if current in _STRATEGIES else 0
        strategy_row.set_selected(idx)
        strategy_row.connect("notify::selected", self._on_strategy_changed)
        group.add(strategy_row)

        # Enabled
        enabled_row = Adw.SwitchRow(
            title="Inject text after recognition",
            subtitle="Disable to only show text in the result panel",
        )
        enabled_row.set_active(self.cfg.typing.enabled)
        enabled_row.connect("notify::active", lambda r, _: setattr(self.cfg.typing, "enabled", r.get_active()))
        group.add(enabled_row)

        # Focus release delay
        delay_row = Adw.SpinRow.new_with_range(50, 2000, 50)
        delay_row.set_title("Focus release delay (ms)")
        delay_row.set_subtitle("Wait before typing — increase if leading characters are lost")
        delay_row.set_value(self.cfg.typing.focus_release_delay_ms)
        delay_row.connect("notify::value", lambda r, _: setattr(
            self.cfg.typing, "focus_release_delay_ms", int(r.get_value())
        ))
        group.add(delay_row)

        group2 = Adw.PreferencesGroup(title="After Injection")
        page.add(group2)

        # Press enter
        enter_row = Adw.SwitchRow(
            title="Press Enter after typing",
            subtitle="Useful for search bars and terminals",
        )
        enter_row.set_active(self.cfg.typing.press_enter)
        enter_row.connect("notify::active", lambda r, _: setattr(self.cfg.typing, "press_enter", r.get_active()))
        group2.add(enter_row)

        # Clear canvas
        clear_row = Adw.SwitchRow(
            title="Clear canvas after injection",
            subtitle="Erase strokes once text has been typed",
        )
        clear_row.set_active(self.cfg.typing.clear_canvas_after_inject)
        clear_row.connect("notify::active", lambda r, _: setattr(
            self.cfg.typing, "clear_canvas_after_inject", r.get_active()
        ))
        group2.add(clear_row)

        # Quit after inject
        quit_row = Adw.SwitchRow(
            title="Quit after injection",
            subtitle="Close Katip once text has been typed",
        )
        quit_row.set_active(self.cfg.typing.quit_after_inject)
        quit_row.connect("notify::active", lambda r, _: setattr(
            self.cfg.typing, "quit_after_inject", r.get_active()
        ))
        group2.add(quit_row)

        return page

    def _build_recognition_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Recognition", icon_name="system-search-symbolic")

        # ── Engine ──────────────────────────────────────────────────────── #
        engine_group = Adw.PreferencesGroup(title="Engine")
        page.add(engine_group)

        engine_row = Adw.ComboRow(title="Recognition engine")
        engine_row.set_model(Gtk.StringList.new(_ENGINE_LABELS))
        current_engine = self.cfg.recognition.engine
        engine_idx = _ENGINES.index(current_engine) if current_engine in _ENGINES else 0
        engine_row.set_selected(engine_idx)
        engine_group.add(engine_row)

        # ── MyScript credentials ─────────────────────────────────────────── #
        ms_group = Adw.PreferencesGroup(
            title="MyScript Credentials",
            description="Get your free keys at developer.myscript.com",
        )
        ms_group.set_visible(current_engine == "myscript")
        page.add(ms_group)

        app_key_row = Adw.PasswordEntryRow(title="Application Key")
        app_key_row.set_text(self.cfg.myscript.application_key)
        app_key_row.connect("notify::text", lambda r, _: setattr(
            self.cfg.myscript, "application_key", r.get_text()
        ))
        ms_group.add(app_key_row)

        hmac_row = Adw.PasswordEntryRow(title="HMAC Key")
        hmac_row.set_text(self.cfg.myscript.hmac_key)
        hmac_row.connect("notify::text", lambda r, _: setattr(
            self.cfg.myscript, "hmac_key", r.get_text()
        ))
        ms_group.add(hmac_row)

        engine_row.connect(
            "notify::selected",
            lambda r, _: self._on_engine_changed(r, ms_group),
        )

        # ── Timing ──────────────────────────────────────────────────────── #
        group = Adw.PreferencesGroup(title="Timing")
        page.add(group)

        timeout_row = Adw.SpinRow.new_with_range(0.5, 10.0, 0.5)
        timeout_row.set_title("Recognition timeout (s)")
        timeout_row.set_subtitle("Seconds of inactivity before OCR fires")
        timeout_row.set_digits(1)
        timeout_row.set_value(self.cfg.recognition.timeout_seconds)
        timeout_row.connect("notify::value", lambda r, _: setattr(
            self.cfg.recognition, "timeout_seconds", r.get_value()
        ))
        group.add(timeout_row)

        # ── Layout ──────────────────────────────────────────────────────── #
        group2 = Adw.PreferencesGroup(title="Layout")
        page.add(group2)

        merge_row = Adw.SpinRow.new_with_range(0.1, 2.0, 0.1)
        merge_row.set_title("Line merge factor")
        merge_row.set_subtitle("Vertical gap threshold for grouping strokes into lines")
        merge_row.set_digits(1)
        merge_row.set_value(self.cfg.recognition.line_merge_factor)
        merge_row.connect("notify::value", lambda r, _: setattr(
            self.cfg.recognition, "line_merge_factor", r.get_value()
        ))
        group2.add(merge_row)

        gap_row = Adw.SpinRow.new_with_range(0.1, 3.0, 0.1)
        gap_row.set_title("Word gap factor")
        gap_row.set_subtitle("Horizontal gap threshold for inserting spaces between words")
        gap_row.set_digits(1)
        gap_row.set_value(self.cfg.recognition.word_gap_factor)
        gap_row.connect("notify::value", lambda r, _: setattr(
            self.cfg.recognition, "word_gap_factor", r.get_value()
        ))
        group2.add(gap_row)

        return page

    def _build_appearance_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Appearance", icon_name="applications-graphics-symbolic")

        group = Adw.PreferencesGroup(title="Brush & Glow")
        page.add(group)

        # Default brush color
        color_row = Adw.ActionRow(
            title="Default brush colour",
            subtitle="Used when the app starts",
        )
        color_btn = Gtk.ColorButton()
        color_btn.set_valign(Gtk.Align.CENTER)
        rgba = Gdk.RGBA()
        rgba.parse(self.cfg.annotation.default_color)
        color_btn.set_rgba(rgba)
        color_btn.connect("color-set", self._on_default_color_set)
        color_row.add_suffix(color_btn)
        color_row.set_activatable_widget(color_btn)
        group.add(color_row)

        # Glow enabled
        glow_row = Adw.SwitchRow(
            title="Glow effect",
            subtitle="Soft halo behind each stroke",
        )
        glow_row.set_active(self.cfg.annotation.glow_enabled)
        glow_row.connect("notify::active", lambda r, _: setattr(
            self.cfg.annotation, "glow_enabled", r.get_active()
        ))
        group.add(glow_row)

        # Glow radius
        radius_row = Adw.SpinRow.new_with_range(1.0, 30.0, 1.0)
        radius_row.set_title("Glow radius (px)")
        radius_row.set_value(self.cfg.annotation.glow_radius)
        radius_row.connect("notify::value", lambda r, _: setattr(
            self.cfg.annotation, "glow_radius", r.get_value()
        ))
        group.add(radius_row)

        return page

    def _build_input_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Input", icon_name="input-tablet-symbolic")

        group = Adw.PreferencesGroup(title="Pressure Curve")
        page.add(group)

        curve_row = Adw.ComboRow(title="Pressure sensitivity")
        curve_row.set_subtitle(
            "How quickly the stroke thickens as you press harder"
        )
        curve_row.set_model(Gtk.StringList.new(_PRESSURE_LABELS))
        # Select the preset that matches the current curve (or Custom if none match)
        current = [list(p) for p in self.cfg.input.pressure_curve]
        selected_idx = 0
        for i, curve in enumerate(_PRESSURE_CURVES):
            if [list(p) for p in curve] == current:
                selected_idx = i
                break
        curve_row.set_selected(selected_idx)
        curve_row.connect("notify::selected", self._on_pressure_preset_changed)
        group.add(curve_row)

        group2 = Adw.PreferencesGroup(title="Stroke Thickness")
        page.add(group2)

        min_row = Adw.SpinRow.new_with_range(0.5, 10.0, 0.5)
        min_row.set_title("Minimum thickness (px)")
        min_row.set_subtitle("Stroke width at zero pressure")
        min_row.set_digits(1)
        min_row.set_value(self.cfg.input.min_thickness)
        min_row.connect("notify::value", lambda r, _: setattr(
            self.cfg.input, "min_thickness", r.get_value()
        ))
        group2.add(min_row)

        max_row = Adw.SpinRow.new_with_range(1.0, 40.0, 0.5)
        max_row.set_title("Maximum thickness (px)")
        max_row.set_subtitle("Stroke width at full pressure")
        max_row.set_digits(1)
        max_row.set_value(self.cfg.input.max_thickness)
        max_row.connect("notify::value", lambda r, _: setattr(
            self.cfg.input, "max_thickness", r.get_value()
        ))
        group2.add(max_row)

        group3 = Adw.PreferencesGroup(title="Touch")
        page.add(group3)

        touch_row = Adw.SwitchRow(
            title="Touch / finger input",
            subtitle="Allow drawing with finger when no stylus is detected",
        )
        touch_row.set_active(self.cfg.input.touch_enabled)
        touch_row.connect("notify::active", lambda r, _: setattr(
            self.cfg.input, "touch_enabled", r.get_active()
        ))
        group3.add(touch_row)

        return page

    def _build_erase_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Erase", icon_name="edit-clear-symbolic")

        group = Adw.PreferencesGroup(
            title="Scribble-to-Erase",
            description="Draw a rapid back-and-forth horizontal stroke over ink to erase it",
        )
        page.add(group)

        enabled_row = Adw.SwitchRow(title="Enable scribble-to-erase")
        enabled_row.set_active(self.cfg.erase.enabled)
        enabled_row.connect("notify::active", lambda r, _: setattr(
            self.cfg.erase, "enabled", r.get_active()
        ))
        group.add(enabled_row)

        reversals_row = Adw.SpinRow.new_with_range(2, 20, 1)
        reversals_row.set_title("Minimum direction reversals")
        reversals_row.set_subtitle("Increase to avoid accidental erasure")
        reversals_row.set_value(self.cfg.erase.min_reversals)
        reversals_row.connect("notify::value", lambda r, _: setattr(
            self.cfg.erase, "min_reversals", int(r.get_value())
        ))
        group.add(reversals_row)

        width_row = Adw.SpinRow.new_with_range(10.0, 300.0, 10.0)
        width_row.set_title("Minimum scribble width (px)")
        width_row.set_subtitle("Increase to require a wider gesture")
        width_row.set_value(self.cfg.erase.min_width)
        width_row.connect("notify::value", lambda r, _: setattr(
            self.cfg.erase, "min_width", r.get_value()
        ))
        group.add(width_row)

        hit_row = Adw.SpinRow.new_with_range(2.0, 60.0, 1.0)
        hit_row.set_title("Hit radius (px)")
        hit_row.set_subtitle("How close the scribble must come to a stroke to erase it")
        hit_row.set_value(self.cfg.erase.hit_threshold)
        hit_row.connect("notify::value", lambda r, _: setattr(
            self.cfg.erase, "hit_threshold", r.get_value()
        ))
        group.add(hit_row)

        return page

    def _build_save_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Save", icon_name="document-save-symbolic")

        group = Adw.PreferencesGroup(
            title="Save Settings",
            description=(
                "Changes take effect immediately. "
                "Save writes them to config.yaml so they persist across restarts."
            ),
        )
        page.add(group)

        save_row = Adw.ActionRow(
            title="Save to config.yaml",
            subtitle="Overwrites the file — comments will be removed",
        )
        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        save_btn.set_valign(Gtk.Align.CENTER)
        save_btn.set_tooltip_text("Write current settings to config.yaml")
        save_btn.connect("clicked", self._on_save)
        save_row.add_suffix(save_btn)
        save_row.set_activatable_widget(save_btn)
        group.add(save_row)

        return page

    # ------------------------------------------------------------------ #
    # Callbacks
    # ------------------------------------------------------------------ #

    def _on_engine_changed(self, row: Adw.ComboRow, ms_group: Adw.PreferencesGroup) -> None:
        idx = row.get_selected()
        if 0 <= idx < len(_ENGINES):
            self.cfg.recognition.engine = _ENGINES[idx]
            ms_group.set_visible(_ENGINES[idx] == "myscript")
            log.info("Recognition engine changed to %s", self.cfg.recognition.engine)

    def _on_pressure_preset_changed(self, row: Adw.ComboRow, _param) -> None:
        idx = row.get_selected()
        if 0 <= idx < len(_PRESSURE_CURVES):
            self.cfg.input.pressure_curve = list(_PRESSURE_CURVES[idx])
            log.info("Pressure curve set to %s", _PRESSURE_LABELS[idx])

    def _on_strategy_changed(self, row: Adw.ComboRow, _param) -> None:
        idx = row.get_selected()
        if 0 <= idx < len(_STRATEGIES):
            self.cfg.typing.strategy = _STRATEGIES[idx]
            log.info("Typing strategy changed to %s", self.cfg.typing.strategy)

    def _on_default_color_set(self, btn: Gtk.ColorButton) -> None:
        rgba = btn.get_rgba()
        r, g, b = int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255)
        self.cfg.annotation.default_color = f"#{r:02X}{g:02X}{b:02X}"
        log.debug("Default color changed to %s", self.cfg.annotation.default_color)

    def _on_save(self, _btn) -> None:
        try:
            self.cfg.save()
            toast = Adw.Toast.new("Settings saved to config.yaml")
            toast.set_timeout(3)
            self.add_toast(toast)
        except Exception as e:
            log.exception("Failed to save config")
            toast = Adw.Toast.new(f"Save failed: {e}")
            toast.set_timeout(5)
            self.add_toast(toast)
