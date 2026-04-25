# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
input/pressure.py — maps a normalised pressure value [0,1] to a
stroke thickness [min_thickness, max_thickness] using a cubic Bézier
curve defined by four control points from config.yaml.

Algorithm: de Casteljau's algorithm evaluating B(t) for the y-component,
then interpolating over the configured thickness range.
"""

from __future__ import annotations

from typing import List, Tuple


def _de_casteljau(points: List[Tuple[float, float]], t: float) -> Tuple[float, float]:
    """Evaluate a Bézier curve at parameter t using de Casteljau's algorithm."""
    pts = list(points)
    while len(pts) > 1:
        pts = [
            (
                (1 - t) * pts[i][0] + t * pts[i + 1][0],
                (1 - t) * pts[i][1] + t * pts[i + 1][1],
            )
            for i in range(len(pts) - 1)
        ]
    return pts[0]


def _find_t_for_x(
    control_points: List[Tuple[float, float]],
    target_x: float,
    iterations: int = 8,
) -> float:
    """
    Binary search for the t parameter that gives B_x(t) ≈ target_x.
    Assumes the curve is monotonically increasing in x.
    """
    lo, hi = 0.0, 1.0
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        bx, _ = _de_casteljau(control_points, mid)
        if bx < target_x:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def pressure_to_thickness(
    pressure: float,
    control_points: List[Tuple[float, float]],
    min_thickness: float,
    max_thickness: float,
) -> float:
    """
    Map pressure ∈ [0,1] → thickness ∈ [min_thickness, max_thickness]
    via the Bézier curve defined by control_points.
    """
    pressure = max(0.0, min(1.0, pressure))
    t = _find_t_for_x(control_points, pressure)
    _, curve_y = _de_casteljau(control_points, t)
    curve_y = max(0.0, min(1.0, curve_y))
    return min_thickness + curve_y * (max_thickness - min_thickness)
