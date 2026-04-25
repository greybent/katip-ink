# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
core/app.py — Adwaita application, global shortcuts, lifecycle.
"""

from __future__ import annotations

import logging

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio

from core.config import Config
from core.state_machine import StateMachine, State
from ui.overlay_window import OverlayWindow

log = logging.getLogger(__name__)


class OverlayApplication(Adw.Application):
    def __init__(self, cfg: Config) -> None:
        super().__init__(
            application_id="org.gnome.overlay.HandwritingOverlay",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.cfg = cfg
        self.sm = StateMachine()
        self._window: OverlayWindow | None = None

        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)

    # ------------------------------------------------------------------ #
    def _on_activate(self, _app) -> None:
        self._window = OverlayWindow(self, self.cfg, self.sm)
        self._window.present()
        self._register_shortcuts()
        log.info("Application activated")

    def _on_shutdown(self, _app) -> None:
        log.info("Application shutting down")

    # ------------------------------------------------------------------ #
    def _register_shortcuts(self) -> None:
        sc = self.cfg.shortcuts

        # Toggle Recognition ↔ Annotation
        toggle_action = Gio.SimpleAction.new("toggle-mode", None)
        toggle_action.connect("activate", self._on_toggle_mode)
        self.add_action(toggle_action)
        self.set_accels_for_action("app.toggle-mode", [sc.toggle_mode])

        # Clear canvas
        clear_action = Gio.SimpleAction.new("clear-canvas", None)
        clear_action.connect("activate", self._on_clear_canvas)
        self.add_action(clear_action)
        self.set_accels_for_action("app.clear-canvas", [sc.clear_canvas])

        # Quit
        quit_action = Gio.SimpleAction.new("quit-app", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit-app", [sc.quit])

        log.debug(
            "Shortcuts registered: toggle=%s clear=%s quit=%s",
            sc.toggle_mode, sc.clear_canvas, sc.quit,
        )

    # ------------------------------------------------------------------ #
    def _on_toggle_mode(self, _action, _param) -> None:
        sm = self.sm
        if sm.state == State.ANNOTATING:
            sm.transition(State.IDLE)
            log.info("Switched to Recognition mode")
        else:
            sm.transition(State.ANNOTATING)
            log.info("Switched to Annotation mode")

    def _on_clear_canvas(self, _action, _param) -> None:
        if self._window:
            self._window.canvas.clear()
            log.info("Canvas cleared")
