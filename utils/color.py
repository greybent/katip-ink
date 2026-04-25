# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
utils/color.py — color parsing, conversion, and palette helpers.

All internal colors are stored as (r, g, b, a) tuples with components in [0, 1].
"""

from __future__ import annotations

import colorsys
import re
from typing import Tuple

RGBA = Tuple[float, float, float, float]


# ── Parsing ──────────────────────────────────────────────────────────────────

def hex_to_rgba(hex_color: str, alpha: float = 1.0) -> RGBA:
    """Parse a CSS hex color string to an RGBA tuple."""
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"Invalid hex color: {hex_color!r}")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (r, g, b, max(0.0, min(1.0, alpha)))


def rgba_to_hex(r: float, g: float, b: float, _a: float = 1.0) -> str:
    """Convert an RGB tuple (components in [0,1]) to a CSS hex string."""
    return "#{:02X}{:02X}{:02X}".format(
        round(r * 255), round(g * 255), round(b * 255)
    )


# ── Manipulation ─────────────────────────────────────────────────────────────

def lighten(color: RGBA, amount: float = 0.2) -> RGBA:
    """Lighten a color by increasing its lightness in HLS space."""
    r, g, b, a = color
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = min(1.0, l + amount)
    nr, ng, nb = colorsys.hls_to_rgb(h, l, s)
    return (nr, ng, nb, a)


def darken(color: RGBA, amount: float = 0.2) -> RGBA:
    """Darken a color by decreasing its lightness in HLS space."""
    r, g, b, a = color
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, l - amount)
    nr, ng, nb = colorsys.hls_to_rgb(h, l, s)
    return (nr, ng, nb, a)


def with_alpha(color: RGBA, alpha: float) -> RGBA:
    """Return the same color with a new alpha value."""
    return (color[0], color[1], color[2], max(0.0, min(1.0, alpha)))


def blend(a: RGBA, b: RGBA, t: float = 0.5) -> RGBA:
    """Linear interpolation between two RGBA colors. t=0 → a, t=1 → b."""
    t = max(0.0, min(1.0, t))
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(4))  # type: ignore[return-value]


# ── Built-in annotation palette ──────────────────────────────────────────────

PALETTE: list[str] = [
    "#FF4444",  # red
    "#FF8C00",  # orange
    "#FFD700",  # yellow
    "#44DD44",  # green
    "#44AAFF",  # blue
    "#CC44FF",  # violet
    "#FF44AA",  # pink
    "#FFFFFF",  # white
    "#111111",  # near-black
]
