#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
GNOME Transparent Overlay — main entry point.
Initialises GLib, loads config, and launches the Adwaita application.
"""

import sys
import signal
import logging

__version__ = "0.2.3-alpha"

from utils.logging_setup import setup_logging
setup_logging()

# Delete stale __pycache__ on startup so edited .py files always take effect.
# Python normally uses .pyc if it's newer than the .py — stale caches from
# a previous session can silently run old code after updates.
import shutil, pathlib
for cache_dir in pathlib.Path(__file__).parent.rglob("__pycache__"):
    shutil.rmtree(cache_dir, ignore_errors=True)

from core.config import Config
from core.app import OverlayApplication

log = logging.getLogger("main")


def main() -> int:
    # Allow Ctrl-C to terminate the GLib main loop cleanly
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Load config.yaml from the same directory as main.py,
    # so the app works regardless of which directory it is launched from.
    cfg = Config.load(pathlib.Path(__file__).parent / "config.yaml")
    app = OverlayApplication(cfg)
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
