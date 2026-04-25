# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
tests/test_config.py — unit tests for core.config.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from core.config import Config, WindowConfig, InputConfig, RecognitionConfig


class TestConfigDefaults:
    def test_default_config_loads(self):
        cfg = Config()
        assert isinstance(cfg.window, WindowConfig)
        assert cfg.window.opacity == 0.0
        assert cfg.window.z_layer == "overlay"

    def test_default_recognition_timeout(self):
        cfg = Config()
        assert cfg.recognition.timeout_seconds == 3.0

    def test_default_languages(self):
        cfg = Config()
        assert "en" in cfg.recognition.languages


class TestConfigFromFile:
    def _write_yaml(self, data: dict) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        )
        yaml.dump(data, tmp)
        tmp.flush()
        return Path(tmp.name)

    def test_window_opacity_override(self):
        p = self._write_yaml({"window": {"opacity": 0.15}})
        cfg = Config.load(p)
        assert abs(cfg.window.opacity - 0.15) < 1e-9

    def test_recognition_timeout_override(self):
        p = self._write_yaml({"recognition": {"timeout_seconds": 5.0}})
        cfg = Config.load(p)
        assert cfg.recognition.timeout_seconds == 5.0

    def test_languages_override(self):
        p = self._write_yaml({"recognition": {"languages": ["fr", "de"]}})
        cfg = Config.load(p)
        assert "fr" in cfg.recognition.languages
        assert "de" in cfg.recognition.languages

    def test_unknown_key_ignored(self):
        p = self._write_yaml({"window": {"nonexistent_key": 42}})
        cfg = Config.load(p)
        assert not hasattr(cfg.window, "nonexistent_key")

    def test_missing_file_returns_defaults(self):
        cfg = Config.load("/tmp/nonexistent_config_xyz.yaml")
        assert cfg.recognition.timeout_seconds == 3.0

    def test_empty_file_returns_defaults(self):
        p = self._write_yaml({})
        cfg = Config.load(p)
        assert cfg.annotation.glow_enabled is True


class TestColorUtils:
    def test_hex_to_rgba_basic(self):
        from utils.color import hex_to_rgba
        r, g, b, a = hex_to_rgba("#FF0000")
        assert abs(r - 1.0) < 0.01
        assert abs(g - 0.0) < 0.01
        assert abs(b - 0.0) < 0.01
        assert abs(a - 1.0) < 0.01

    def test_hex_to_rgba_shorthand(self):
        from utils.color import hex_to_rgba
        r, g, b, a = hex_to_rgba("#F00")
        assert abs(r - 1.0) < 0.01

    def test_rgba_to_hex_roundtrip(self):
        from utils.color import hex_to_rgba, rgba_to_hex
        original = "#4488CC"
        r, g, b, a = hex_to_rgba(original)
        result = rgba_to_hex(r, g, b)
        assert result == original

    def test_lighten_increases_lightness(self):
        from utils.color import hex_to_rgba, lighten
        dark = hex_to_rgba("#333333")
        light = lighten(dark, 0.3)
        # light should be brighter (higher average RGB)
        assert sum(light[:3]) > sum(dark[:3])

    def test_with_alpha(self):
        from utils.color import hex_to_rgba, with_alpha
        c = hex_to_rgba("#FF0000", 1.0)
        c2 = with_alpha(c, 0.5)
        assert abs(c2[3] - 0.5) < 0.01
