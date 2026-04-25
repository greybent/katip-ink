# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
tests/test_pressure.py — unit tests for input.pressure.
"""

import pytest
from input.pressure import pressure_to_thickness, _de_casteljau


DEFAULT_CURVE = [(0.0, 0.0), (0.3, 0.1), (0.7, 0.9), (1.0, 1.0)]
MIN_T = 2.0
MAX_T = 10.0


class TestPressureToThickness:
    def test_zero_pressure_returns_min(self):
        t = pressure_to_thickness(0.0, DEFAULT_CURVE, MIN_T, MAX_T)
        assert abs(t - MIN_T) < 0.05

    def test_full_pressure_returns_max(self):
        t = pressure_to_thickness(1.0, DEFAULT_CURVE, MIN_T, MAX_T)
        assert abs(t - MAX_T) < 0.05

    def test_midpoint_is_within_range(self):
        t = pressure_to_thickness(0.5, DEFAULT_CURVE, MIN_T, MAX_T)
        assert MIN_T <= t <= MAX_T

    def test_monotonically_increasing(self):
        pressures = [i / 10 for i in range(11)]
        thicknesses = [
            pressure_to_thickness(p, DEFAULT_CURVE, MIN_T, MAX_T)
            for p in pressures
        ]
        for i in range(len(thicknesses) - 1):
            assert thicknesses[i] <= thicknesses[i + 1] + 0.01

    def test_out_of_range_pressure_clamped(self):
        t_neg = pressure_to_thickness(-0.5, DEFAULT_CURVE, MIN_T, MAX_T)
        t_over = pressure_to_thickness(1.5, DEFAULT_CURVE, MIN_T, MAX_T)
        assert abs(t_neg - MIN_T) < 0.1
        assert abs(t_over - MAX_T) < 0.1

    def test_linear_curve(self):
        linear = [(0.0, 0.0), (0.33, 0.33), (0.66, 0.66), (1.0, 1.0)]
        t = pressure_to_thickness(0.5, linear, 0.0, 1.0)
        assert abs(t - 0.5) < 0.05


class TestDeCasteljau:
    def test_t0_returns_first_point(self):
        pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (2.0, 1.0)]
        x, y = _de_casteljau(pts, 0.0)
        assert abs(x - 0.0) < 1e-9
        assert abs(y - 0.0) < 1e-9

    def test_t1_returns_last_point(self):
        pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (2.0, 1.0)]
        x, y = _de_casteljau(pts, 1.0)
        assert abs(x - 2.0) < 1e-9
        assert abs(y - 1.0) < 1e-9
