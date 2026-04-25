# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
ui/result_popup.py — Adwaita toast + expandable result panel.

When OCR completes the engine calls show_result(text).  This module:
  1. Shows an Adw.Toast at the bottom of the window ("Recognition complete").
  2. Appends the recognised text to a scrollable history panel that can be
     toggled with the chevron button in the status bar.
  3. Provides a "Copy" button per result entry (writes to the clipboard).

Architecture note
-----------------
ResultPanel is an Adw.Bin that wraps a Gtk.Revealer so it can slide in/out
without reflowing the canvas.  It is appended to the main Gtk.Box between
the canvas and the status bar, hidden by default.
"""

from __future__ import annotations

import logging
import time
from typing import List

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Adw, Gdk, GLib

log = logging.getLogger(__name__)


@staticmethod
def _copy_to_clipboard(text: str) -> None:
    display = Gdk.Display.get_default()
    if display is None:
        return
    clipboard = display.get_clipboard()
    clipboard.set(text)
    log.debug("Copied to clipboard: %r", text[:60])


class ResultEntry(Gtk.Box):
    """Single recognised-text entry row with timestamp and copy button."""

    def __init__(self, text: str, language: str) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(4)
        self.set_margin_bottom(4)

        # Timestamp + language badge
        stamp = time.strftime("%H:%M:%S")
        meta = Gtk.Label(label=f"{stamp} [{language}]")
        meta.add_css_class("caption")
        meta.add_css_class("dim-label")
        meta.set_xalign(0.0)
        self.append(meta)

        # Text label (expands)
        label = Gtk.Label(label=text or "(empty)")
        label.set_hexpand(True)
        label.set_wrap(True)
        label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        label.set_xalign(0.0)
        label.add_css_class("monospace")
        self.append(label)

        # Copy button
        copy_btn = Gtk.Button(icon_name="edit-copy-symbolic")
        copy_btn.set_tooltip_text("Copy to clipboard")
        copy_btn.add_css_class("flat")
        copy_btn.connect("clicked", lambda _: _copy_to_clipboard(text))
        self.append(copy_btn)


class ResultPanel(Adw.Bin):
    """
    Sliding panel that accumulates OCR results.

    Attach to the main window box with::

        window_box.append(self.result_panel)
        window_box.append(self.status_bar)

    Then call result_panel.show_result(text, lang) from the OCR callback.
    """

    MAX_ENTRIES = 50  # older entries are pruned

    def __init__(self, toast_overlay: Adw.ToastOverlay) -> None:
        super().__init__()
        self._toast_overlay = toast_overlay
        self._entries: List[ResultEntry] = []

        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        revealer.set_transition_duration(200)
        self._revealer = revealer

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(80)
        scroll.set_max_content_height(220)

        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.add_css_class("boxed-list")
        scroll.set_child(self._list_box)

        revealer.set_child(scroll)
        self.set_child(revealer)

    # ------------------------------------------------------------------ #
    def show_result(self, text: str, language: str = "eng") -> None:
        """Called (on the main thread) when OCR produces a result."""
        GLib.idle_add(self._append_result, text, language)

    def _append_result(self, text: str, language: str) -> bool:
        entry = ResultEntry(text, language)
        row = Gtk.ListBoxRow()
        row.set_child(entry)
        self._list_box.append(row)
        self._entries.append(entry)

        # Prune oldest if over limit
        while len(self._entries) > self.MAX_ENTRIES:
            oldest = self._entries.pop(0)
            # find and remove its row
            r = oldest.get_parent()
            if r:
                self._list_box.remove(r)

        # Show panel and toast
        self._revealer.set_reveal_child(True)
        toast = Adw.Toast.new(f"Recognised: {text[:40]}{'…' if len(text) > 40 else ''}")
        toast.set_timeout(3)
        self._toast_overlay.add_toast(toast)

        log.info("OCR result displayed: %r", text[:80])
        return GLib.SOURCE_REMOVE

    def toggle_visibility(self) -> None:
        current = self._revealer.get_reveal_child()
        self._revealer.set_reveal_child(not current)

    def clear(self) -> None:
        for entry in self._entries:
            row = entry.get_parent()
            if row:
                self._list_box.remove(row)
        self._entries.clear()
        self._revealer.set_reveal_child(False)
