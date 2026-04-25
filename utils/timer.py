# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
utils/timer.py — cancellable, restartable GLib timer wrapper.

Wraps GLib.timeout_add / GLib.source_remove into a clean object so
callers don't have to track source IDs manually.

Usage
-----
    timer = GLibTimer(interval_ms=3000, callback=my_func)
    timer.start()    # or restart() to reset a running timer
    timer.cancel()
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from gi.repository import GLib

log = logging.getLogger(__name__)


class GLibTimer:
    """Single-shot or repeating GLib timer with clean cancel/restart API."""

    def __init__(
        self,
        interval_ms: int,
        callback: Callable[[], None],
        *,
        repeat: bool = False,
    ) -> None:
        self._interval = interval_ms
        self._callback = callback
        self._repeat = repeat
        self._source_id: Optional[int] = None

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Start the timer. No-op if already running."""
        if self._source_id is not None:
            return
        self._source_id = GLib.timeout_add(self._interval, self._fire)

    def restart(self) -> None:
        """Cancel any running timer and start fresh."""
        self.cancel()
        self.start()

    def cancel(self) -> None:
        """Cancel the timer if it is running."""
        if self._source_id is not None:
            GLib.source_remove(self._source_id)
            self._source_id = None
            log.debug("Timer cancelled (interval=%dms)", self._interval)

    @property
    def running(self) -> bool:
        return self._source_id is not None

    # ------------------------------------------------------------------ #
    def _fire(self) -> bool:
        if not self._repeat:
            self._source_id = None
        try:
            self._callback()
        except Exception:
            log.exception("GLibTimer callback raised an exception")
        return GLib.SOURCE_CONTINUE if self._repeat else GLib.SOURCE_REMOVE
