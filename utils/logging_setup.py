# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
utils/logging_setup.py — configure structured logging for the application.

Call setup_logging() once from main.py before anything else.
Log levels can be overridden per-module via the LOG_LEVELS env var:

    LOG_LEVELS="input.stylus_handler=DEBUG,recognition.engine=INFO" python3 main.py
"""

from __future__ import annotations

import logging
import os
import sys


def setup_logging(default_level: int = logging.INFO) -> None:
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(default_level)
    root.addHandler(handler)

    # Per-module overrides from environment
    overrides = os.environ.get("LOG_LEVELS", "")
    for part in overrides.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        module, level_str = part.split("=", 1)
        level = getattr(logging, level_str.upper(), None)
        if level is not None:
            logging.getLogger(module.strip()).setLevel(level)
            logging.getLogger(__name__).debug(
                "Log level override: %s → %s", module.strip(), level_str.upper()
            )
