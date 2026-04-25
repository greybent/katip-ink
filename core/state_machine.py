# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
core/state_machine.py — finite-state machine for the overlay.

States
------
IDLE            Window is click-through; no strokes being drawn.
DRAWING         Active stylus/touch contact; strokes accumulating.
COUNTDOWN       Input lifted; 3-second timer running (Recognition mode only).
RECOGNIZING     Async OCR in progress.
ANNOTATING      Annotation mode active; timer suppressed.
"""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Callable, Dict, List, Optional

log = logging.getLogger(__name__)


class State(Enum):
    IDLE = auto()
    DRAWING = auto()
    COUNTDOWN = auto()
    RECOGNIZING = auto()
    ANNOTATING = auto()


# Valid transitions: {from_state: [allowed_to_states]}
TRANSITIONS: Dict[State, List[State]] = {
    State.IDLE:        [State.DRAWING, State.ANNOTATING],
    State.DRAWING:     [State.IDLE, State.COUNTDOWN, State.ANNOTATING],
    State.COUNTDOWN:   [State.DRAWING, State.RECOGNIZING, State.IDLE, State.ANNOTATING],
    State.RECOGNIZING: [State.IDLE, State.ANNOTATING],
    State.ANNOTATING:  [State.IDLE, State.DRAWING],
}


class StateMachine:
    def __init__(self, initial: State = State.IDLE) -> None:
        self._state = initial
        self._listeners: List[Callable[[State, State], None]] = []

    # ------------------------------------------------------------------ #
    @property
    def state(self) -> State:
        return self._state

    def add_listener(self, cb: Callable[[State, State], None]) -> None:
        """Register a callback(old_state, new_state)."""
        self._listeners.append(cb)

    def transition(self, new_state: State) -> bool:
        """
        Attempt a state transition.
        Returns True on success, False if the transition is invalid.
        """
        allowed = TRANSITIONS.get(self._state, [])
        if new_state not in allowed:
            log.warning(
                "Invalid transition %s → %s (allowed: %s)",
                self._state.name, new_state.name, [s.name for s in allowed],
            )
            return False

        old = self._state
        self._state = new_state
        log.debug("State: %s → %s", old.name, new_state.name)

        for cb in self._listeners:
            try:
                cb(old, new_state)
            except Exception:           # noqa: BLE001
                log.exception("State listener raised an exception")
        return True

    # Convenience helpers
    def is_drawing_active(self) -> bool:
        return self._state in (State.DRAWING, State.ANNOTATING)

    def is_click_through(self) -> bool:
        """True when the window should be transparent to pointer events."""
        return self._state in (State.IDLE, State.COUNTDOWN, State.RECOGNIZING)
