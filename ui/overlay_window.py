# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
ui/overlay_window.py — transparent Wayland overlay window.
"""

from __future__ import annotations

import logging

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Adw, Gdk, GLib

from core.config import Config
from core.state_machine import StateMachine, State
from ui.canvas import StrokeCanvas
from ui.status_bar import StatusBar
from ui.result_popup import ResultPanel
from ui.palette_bar import PaletteBar
from ui.timer_slider import TimerSlider

log = logging.getLogger(__name__)

try:
    import gi as _gi
    _gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
    _HAS_LAYER_SHELL = True
    log.info("gtk4-layer-shell available — using OVERLAY layer")
except (ImportError, ValueError):
    _HAS_LAYER_SHELL = False
    log.warning(
        "gtk4-layer-shell NOT available — falling back to normal window. "
        "Install libgtk4-layer-shell for proper Wayland overlay support."
    )


class OverlayWindow(Adw.ApplicationWindow):
    def __init__(self, app, cfg: Config, sm: StateMachine) -> None:
        super().__init__(application=app)
        self.cfg = cfg
        self.sm = sm

        self._build_ui()
        self._configure_layer_shell()
        self._make_transparent()

        sm.add_listener(self._on_state_changed)
        GLib.idle_add(self._update_input_region)

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        self.set_title("GNOME Handwriting Overlay")
        # Use actual screen dimensions for the default size
        try:
            display = Gdk.Display.get_default()
            monitor = display.get_monitors()[0]
            geo = monitor.get_geometry()
            self.set_default_size(geo.width, geo.height)
        except Exception:
            self.set_default_size(1920, 1080)
        self.set_decorated(False)

        self._toast_overlay = Adw.ToastOverlay()
        self.set_content(self._toast_overlay)

        # Gtk.Overlay lets the canvas fill the full window while the
        # status bar, palette, and result panel float on top of it.
        # The canvas is the main child (fills everything); the UI strips
        # are overlay children pinned to the bottom edge.
        gtk_overlay = Gtk.Overlay()
        self._toast_overlay.set_child(gtk_overlay)

        # Canvas — main child, fills the entire window including the area
        # previously occupied by the status bar
        self.canvas = StrokeCanvas(self.cfg, self.sm)
        self.canvas.set_hexpand(True)
        self.canvas.set_vexpand(True)
        gtk_overlay.set_child(self.canvas)

        # Timer slider — floats on the left edge, always accessible with stylus
        self.timer_slider = TimerSlider(self.cfg)
        gtk_overlay.add_overlay(self.timer_slider)
        gtk_overlay.set_measure_overlay(self.timer_slider, False)

        # Floating bottom strip — status bar + palette + result panel
        # stacked vertically, pinned to the bottom of the window
        bottom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bottom_box.set_valign(Gtk.Align.END)    # pin to bottom
        bottom_box.set_halign(Gtk.Align.FILL)   # full width

        # Semi-transparent background so the bar is readable over ink
        css = Gtk.CssProvider()
        css.load_from_data(b".status-float { background: rgba(0,0,0,0.45); }")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        bottom_box.add_css_class("status-float")

        self.palette_bar = PaletteBar(
            sm=self.sm,
            on_color_change=self.canvas.set_brush_color,
        )
        bottom_box.append(self.palette_bar)

        self.result_panel = ResultPanel(self._toast_overlay)
        bottom_box.append(self.result_panel)

        self.status_bar = StatusBar(self.cfg, self.sm)
        bottom_box.append(self.status_bar)

        gtk_overlay.add_overlay(bottom_box)
        # Allow pointer events to pass through the overlay to the canvas
        # when the user draws above the status bar area
        gtk_overlay.set_measure_overlay(bottom_box, False)
        self._bottom_box = bottom_box  # reference for hide/show toggle
        self._statusbar_visible = True

        # Tell the canvas about the UI strip so stylus taps on buttons
        # don't create strokes on the canvas beneath.
        self.canvas.set_ui_dead_zone_widget(bottom_box)

        self.status_bar.color_button.connect(
            "color-set", self._on_status_bar_color_set
        )

        from recognition.engine import RecognitionEngine
        RecognitionEngine._global_result_callback = self._on_ocr_result

        self.sm.add_listener(self.status_bar.on_state_changed)

        # Wire the annotate button to the same toggle action as Shift+A
        self.status_bar.set_mode_toggle_callback(self._on_toggle_mode_btn)
        # Wire the options button
        self.status_bar.set_options_callback(self._on_options_btn)

        # Enter key on the WINDOW (not canvas) skips the countdown.
        # Using EventControllerKey on the window with CAPTURE phase so it
        # fires before any child widget (DropDown etc.) sees the event.
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed",  self._on_key_pressed)
        key_ctrl.connect("key-released", self._on_key_released)
        self.add_controller(key_ctrl)

        if self.cfg.typing.enabled:
            from utils.text_injector import backend_status
            st = backend_status()
            log.info(
                "Typing backend: %s (ydotool=%s wl_copy=%s wtype=%s)",
                st["best_strategy"], st["ydotool_daemon"], st["wl_copy"], st["wtype"],
            )

    # ------------------------------------------------------------------ #
    # Enter key — skip countdown and fire OCR immediately
    # ------------------------------------------------------------------ #

    def _on_key_pressed(
        self,
        controller,
        keyval: int,
        keycode: int,
        modifier: Gdk.ModifierType,
    ) -> bool:
        # Keep canvas shift_held in sync
        if keyval in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R):
            self.canvas.shift_held = True

        is_enter = keyval in (
            Gdk.KEY_Return,
            Gdk.KEY_KP_Enter,
            Gdk.KEY_ISO_Enter,
        )
        if is_enter and self.sm.state == State.COUNTDOWN:
            log.debug("Enter pressed — firing OCR immediately")
            stylus = self.canvas._stylus
            if stylus._countdown_source is not None:
                GLib.source_remove(stylus._countdown_source)
                stylus._countdown_source = None
            stylus._fire_recognition()
            return True

        # Tab cycles through palette colors (works in any state)
        if keyval == Gdk.KEY_Tab:
            self.palette_bar.cycle_next()
            return True

        # Shift+H toggles the status bar visibility
        # Shift produces uppercase keyval, so check for KEY_H not KEY_h
        if keyval in (Gdk.KEY_H, Gdk.KEY_h) and (modifier & Gdk.ModifierType.SHIFT_MASK):
            self._toggle_statusbar()
            return True

        # Delete or BackSpace removes selected strokes
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            if self.canvas.has_selection:
                self.canvas.delete_selected()
                return True
            return False

        # Escape: clear selection if active, otherwise quit
        if keyval == Gdk.KEY_Escape:
            if self.canvas.has_selection:
                self.canvas.clear_selection()
                return True
            self.get_application().quit()
            return True

        return False

    def _on_key_released(
        self,
        controller,
        keyval: int,
        keycode: int,
        modifier: Gdk.ModifierType,
    ) -> bool:
        if keyval in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R):
            self.canvas.shift_held = False
        return False

    # ------------------------------------------------------------------ #
    # Annotation mode toggle (button in status bar)
    # ------------------------------------------------------------------ #

    def _on_toggle_mode_btn(self) -> None:
        """Called when the Annotate toggle button is clicked."""
        self.get_application()._on_toggle_mode(None, None)

    def _on_options_btn(self) -> None:
        """Open the options/preferences window."""
        from ui.options_dialog import OptionsDialog
        dialog = OptionsDialog(cfg=self.cfg, parent=self)
        dialog.present()

    # ------------------------------------------------------------------ #
    # Status bar toggle
    # ------------------------------------------------------------------ #

    def _toggle_statusbar(self) -> None:
        """Toggle visibility of the status bar and timer slider (Shift+H)."""
        self._statusbar_visible = not self._statusbar_visible
        self._bottom_box.set_visible(self._statusbar_visible)
        self.timer_slider.set_visible(self._statusbar_visible)
        log.debug("Status bar %s", "shown" if self._statusbar_visible else "hidden")

    # ------------------------------------------------------------------ #
    # OCR result → inject
    # ------------------------------------------------------------------ #

    def _on_ocr_result(self, text: str) -> None:
        lang = self.cfg.recognition.active_language
        self.result_panel.show_result(text, lang)

        if not text.strip():
            log.debug("OCR returned empty text — skipping injection")
            return

        if self.cfg.typing.enabled:
            self._inject(text)
        else:
            log.debug("typing.enabled=false — text displayed only")

    def _inject(self, text: str) -> None:
        """
        Hide window, sleep, type via ydotool, quit.
        Mirrors the proven pattern from the reference implementation:
            self.hide()
            time.sleep(0.15)
            subprocess.run(["ydotool", "type", text])
            quit()
        """
        from utils.text_injector import inject_text_async
        tcfg = self.cfg.typing

        def _hide():
            # Hide the window exactly as the reference does
            self.set_visible(False)
            # Drain pending GTK events so the hide is processed before we sleep
            from gi.repository import GLib as _GLib
            ctx = _GLib.main_context_default()
            while ctx.pending():
                ctx.iteration(False)

        inject_text_async(
            text=text,
            focus_release_delay_ms=tcfg.focus_release_delay_ms,
            press_enter=tcfg.press_enter,
            strategy=tcfg.strategy,
            hide_callback=_hide,
            on_done=self._on_inject_done,
        )

    def _on_inject_done(self, success: bool) -> None:
        tcfg = self.cfg.typing

        if tcfg.clear_canvas_after_inject:
            self.canvas.clear()

        if tcfg.quit_after_inject:
            self.get_application().quit()
        else:
            self.set_visible(True)
            if not success:
                toast = Adw.Toast.new("Copied to clipboard — press Ctrl+V to paste")
                toast.set_timeout(8)
                self._toast_overlay.add_toast(toast)

    # ------------------------------------------------------------------ #
    # Color button
    # ------------------------------------------------------------------ #

    def _on_status_bar_color_set(self, btn) -> None:
        rgba = btn.get_rgba()
        from utils.color import rgba_to_hex
        self.canvas.set_brush_color(rgba_to_hex(rgba.red, rgba.green, rgba.blue))

    # ------------------------------------------------------------------ #
    # Layer-shell, transparency, input region
    # ------------------------------------------------------------------ #

    def _configure_layer_shell(self) -> None:
        if not _HAS_LAYER_SHELL:
            return
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        # ON_DEMAND: we claim keyboard focus only while drawing.
        # We switch to NONE before injecting so the compositor
        # immediately hands focus to the underlying window.
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

    def _make_transparent(self) -> None:
        # Scope transparency to this window only via a CSS class,
        # so other windows (e.g. the options dialog) remain opaque.
        self.add_css_class("katip-overlay")
        css = Gtk.CssProvider()
        css.load_from_data(
            b".katip-overlay { background: transparent; } "
            b".katip-overlay box { background: transparent; } "
            b".katip-overlay adw-toast-overlay { background: transparent; }"
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _on_state_changed(self, old: State, new: State) -> None:
        GLib.idle_add(self._update_input_region)

    def _update_input_region(self) -> bool:
        """
        Empty input region (click-through) in IDLE/COUNTDOWN/RECOGNIZING.
        Full input region (capture) in DRAWING/ANNOTATING.

        An empty input region on the overlay surface causes GNOME to route
        all pointer AND keyboard events to whatever window is beneath —
        this is how we hand focus back without hiding the window.
        """
        surface = self.get_surface()
        if surface is None:
            return GLib.SOURCE_REMOVE
        try:
            import cairo
            if not self.sm.is_click_through():
                alloc = self.get_allocation()
                region = cairo.Region(
                    cairo.RectangleInt(0, 0, alloc.width, alloc.height)
                )
            else:
                region = cairo.Region()   # empty = full pass-through

            if hasattr(surface, "set_input_region"):
                surface.set_input_region(region)
            else:
                log.warning(
                    "GdkSurface.set_input_region unavailable — "
                    "upgrade PyGObject >= 3.48 for click-through support."
                )
        except Exception:
            log.exception("Failed to update input region")
        return GLib.SOURCE_REMOVE
