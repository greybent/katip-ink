# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
core/config.py — loads and validates config.yaml.

Schema
------
window:
  opacity: float          # 0.0–1.0, background layer opacity
  z_layer: str            # overlay | top | bottom  (wlr-layer-shell layer)

input:
  pressure_curve:         # Bezier control points [[x0,y0],[x1,y1]]
    - [0.0, 0.0]
    - [0.3, 0.1]
    - [0.7, 0.9]
    - [1.0, 1.0]
  min_thickness: float    # px at pressure=0
  max_thickness: float    # px at pressure=1
  touch_enabled: bool

recognition:
  timeout_seconds: float  # countdown before OCR fires  (default 3.0)
  languages:              # BCP-47 language codes
    - en
    - de
  active_language: en

annotation:
  default_color: "#FF4444"
  glow_enabled: bool
  glow_radius: float      # px

typing:
  enabled: bool                   # inject text into focused window after OCR
  focus_release_delay_ms: int     # wait this long before typing (default 150)
  clear_canvas_after_inject: bool # erase strokes after typing (default true)

shortcuts:
  toggle_mode: "<Shift>A"
  clear_canvas: "<Shift>c"
  quit: "<Shift>q"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

import yaml

log = logging.getLogger(__name__)


@dataclass
class WindowConfig:
    opacity: float = 0.0
    z_layer: str = "overlay"


@dataclass
class InputConfig:
    pressure_curve: List[Tuple[float, float]] = field(
        default_factory=lambda: [(0.0, 0.0), (0.5, 0.1), (0.85, 0.7), (1.0, 1.0)]
    )
    min_thickness: float = 1.5
    max_thickness: float = 12.0
    touch_enabled: bool = True
    # Direction of rotation when the screen is in portrait mode and the tablet
    # hardware is natively landscape (wider than tall). evdev reads raw hardware
    # coordinates that bypass the Wayland compositor's input transformation, so
    # the axis swap must be applied manually.
    # "ccw" = 90° counter-clockwise (left edge of landscape goes up) — most common
    # "cw"  = 90° clockwise (right edge of landscape goes up)
    portrait_rotation: str = "ccw"

    def validate(self) -> None:
        """Validate and clamp input config values, logging warnings for bad entries."""
        _DEFAULT_CURVE = [(0.0, 0.0), (0.5, 0.1), (0.85, 0.7), (1.0, 1.0)]
        curve = self.pressure_curve
        if len(curve) != 4:
            log.warning(
                "pressure_curve must have exactly 4 control points (got %d) — using default",
                len(curve),
            )
            self.pressure_curve = _DEFAULT_CURVE
            return
        xs = [p[0] for p in curve]
        if xs != sorted(xs) or len(set(xs)) != len(xs):
            log.warning(
                "pressure_curve x values must be strictly monotonically increasing "
                "(got %s) — using default. Non-monotonic curves cause incorrect "
                "pressure mapping.",
                xs,
            )
            self.pressure_curve = _DEFAULT_CURVE


@dataclass
class RecognitionConfig:
    timeout_seconds: float = 3.0
    # Recognition engine: "google" (default) or "myscript"
    engine: str = "google"
    # Language codes for Google Handwriting API (BCP-47 short codes)
    # en, de, fr, es, it, pt, nl, ru, zh-CN, ja, ar, ...
    languages: List[str] = field(default_factory=lambda: ["en", "de"])
    active_language: str = "en"
    # Multi-line: vertical gap (as fraction of median stroke height) that
    # still merges two strokes into the same line. Increase if tall letters
    # get split across lines; decrease if lines bleed into each other.
    line_merge_factor: float = 0.6
    # Word boundary: horizontal gap (as fraction of median stroke width)
    # that signals a new word. Increase to require bigger gaps before
    # inserting a space; decrease to insert spaces more aggressively.
    word_gap_factor: float = 0.8


@dataclass
class AnnotationConfig:
    default_color: str = "#FF4444"
    glow_enabled: bool = True
    glow_radius: float = 6.0
    # Colour of the glow halo. "auto" uses the stroke colour (default behaviour).
    # Set to any CSS hex value e.g. "#FFFFFF" for a white glow on all strokes.
    glow_color: str = "auto"


@dataclass
class TypingConfig:
    # Inject recognised text directly into the previously focused window
    enabled: bool = True
    # ms to wait after the overlay releases focus before sending keystrokes.
    # Increase to 300+ if the target app misses leading characters.
    focus_release_delay_ms: int = 150
    # Press Enter as a separate key event after the text is typed.
    # More reliable than appending \n — use for search bars, terminals, address bars.
    press_enter: bool = False
    # Clear all canvas strokes after injection (or clipboard copy)
    clear_canvas_after_inject: bool = True
    # Injection strategy: auto | wl_paste | ydotool | clipboard_only
    # auto resolves to: wl_paste (if wl-copy + ydotoold available) > ydotool > clipboard_only
    # wl_paste  — layout-independent, fixes QWERTZ y↔z; doesn't work in terminals
    # ydotool   — works in terminals; has y↔z swap on QWERTZ keyboards
    # auto = pick the best available method automatically (recommended)
    strategy: str = "auto"
    # Quit the application after text is successfully injected (or clipboard set)
    quit_after_inject: bool = True


@dataclass
class EraseConfig:
    # Enable scribble-to-erase gesture (rapid back-and-forth horizontal stroke)
    enabled: bool = True
    # Minimum number of direction reversals to recognise a scribble gesture.
    # Increase to require more back-and-forth before erasing.
    min_reversals: int = 6
    # Minimum horizontal span (px) of the scribble gesture.
    # Increase to avoid accidental erasure from small wiggles.
    min_width: float = 60.0
    # Hit distance (px): how close a scribble point must come to a stroke
    # point to count as a hit. Increase for a larger erase radius.
    hit_threshold: float = 15.0

    def validate(self) -> None:
        """Clamp erase config values to safe ranges, logging warnings for bad entries."""
        if self.min_reversals < 1:
            log.warning(
                "erase.min_reversals must be >= 1 (got %d) — clamped to 1",
                self.min_reversals,
            )
            self.min_reversals = 1
        if self.min_width <= 0:
            log.warning(
                "erase.min_width must be > 0 (got %g) — clamped to 1.0",
                self.min_width,
            )
            self.min_width = 1.0
        if self.hit_threshold <= 0:
            log.warning(
                "erase.hit_threshold must be > 0 (got %g) — clamped to 1.0",
                self.hit_threshold,
            )
            self.hit_threshold = 1.0


@dataclass
class MyScriptConfig:
    # Credentials from https://developer.myscript.com/
    application_key: str = ""
    hmac_key: str = ""


@dataclass
class ShortcutsConfig:
    toggle_mode: str = "<Shift>A"
    clear_canvas: str = "<Shift>c"
    quit: str = "<Shift>q"


@dataclass
class Config:
    window: WindowConfig = field(default_factory=WindowConfig)
    input: InputConfig = field(default_factory=InputConfig)
    recognition: RecognitionConfig = field(default_factory=RecognitionConfig)
    annotation: AnnotationConfig = field(default_factory=AnnotationConfig)
    typing: TypingConfig = field(default_factory=TypingConfig)
    erase: EraseConfig = field(default_factory=EraseConfig)
    shortcuts: ShortcutsConfig = field(default_factory=ShortcutsConfig)
    myscript: MyScriptConfig = field(default_factory=MyScriptConfig)

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> "Config":
        p = Path(path)
        if not p.exists():
            log.warning("config.yaml not found — using defaults")
            return cls()

        with p.open() as fh:
            raw: dict = yaml.safe_load(fh) or {}

        def _sub(section_cls, key):
            data = raw.get(key, {})
            obj = section_cls()
            for f_name, f_val in data.items():
                if hasattr(obj, f_name):
                    setattr(obj, f_name, f_val)
                else:
                    log.warning("Unknown config key %s.%s — ignored", key, f_name)
            if hasattr(obj, "validate"):
                obj.validate()
            return obj

        cfg = cls(
            window=_sub(WindowConfig, "window"),
            input=_sub(InputConfig, "input"),
            recognition=_sub(RecognitionConfig, "recognition"),
            annotation=_sub(AnnotationConfig, "annotation"),
            typing=_sub(TypingConfig, "typing"),
            erase=_sub(EraseConfig, "erase"),
            shortcuts=_sub(ShortcutsConfig, "shortcuts"),
            myscript=_sub(MyScriptConfig, "myscript"),
        )
        cfg._path = p.resolve()
        log.info("Config loaded from %s", p.resolve())
        return cfg

    def save(self) -> None:
        """Write current settings back to the file this config was loaded from."""
        import yaml
        path = getattr(self, "_path", None)
        if path is None:
            log.warning("Config.save(): no path set — cannot save")
            return
        data = {
            "window": {
                "opacity": self.window.opacity,
                "z_layer": self.window.z_layer,
            },
            "input": {
                "pressure_curve": [list(p) for p in self.input.pressure_curve],
                "min_thickness": self.input.min_thickness,
                "max_thickness": self.input.max_thickness,
                "touch_enabled": self.input.touch_enabled,
                "portrait_rotation": self.input.portrait_rotation,
            },
            "recognition": {
                "timeout_seconds": self.recognition.timeout_seconds,
                "engine": self.recognition.engine,
                "languages": self.recognition.languages,
                "active_language": self.recognition.active_language,
                "line_merge_factor": self.recognition.line_merge_factor,
                "word_gap_factor": self.recognition.word_gap_factor,
            },
            "annotation": {
                "default_color": self.annotation.default_color,
                "glow_enabled": self.annotation.glow_enabled,
                "glow_radius": self.annotation.glow_radius,
                "glow_color": self.annotation.glow_color,
            },
            "typing": {
                "enabled": self.typing.enabled,
                "strategy": self.typing.strategy,
                "focus_release_delay_ms": self.typing.focus_release_delay_ms,
                "press_enter": self.typing.press_enter,
                "clear_canvas_after_inject": self.typing.clear_canvas_after_inject,
                "quit_after_inject": self.typing.quit_after_inject,
            },
            "erase": {
                "enabled": self.erase.enabled,
                "min_reversals": self.erase.min_reversals,
                "min_width": self.erase.min_width,
                "hit_threshold": self.erase.hit_threshold,
            },
            "shortcuts": {
                "toggle_mode": self.shortcuts.toggle_mode,
                "clear_canvas": self.shortcuts.clear_canvas,
                "quit": self.shortcuts.quit,
            },
            "myscript": {
                "application_key": self.myscript.application_key,
                "hmac_key": self.myscript.hmac_key,
            },
        }
        with open(path, "w") as fh:
            yaml.dump(data, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
        log.info("Config saved to %s", path)
