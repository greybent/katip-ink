# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
tests/test_state_machine.py — unit tests for core.state_machine.
"""

import pytest
from core.state_machine import StateMachine, State


class TestStateMachine:
    def test_initial_state(self):
        sm = StateMachine()
        assert sm.state == State.IDLE

    def test_valid_transition_idle_to_drawing(self):
        sm = StateMachine()
        assert sm.transition(State.DRAWING) is True
        assert sm.state == State.DRAWING

    def test_valid_transition_drawing_to_countdown(self):
        sm = StateMachine()
        sm.transition(State.DRAWING)
        assert sm.transition(State.COUNTDOWN) is True
        assert sm.state == State.COUNTDOWN

    def test_invalid_transition_returns_false(self):
        sm = StateMachine()
        # Cannot go directly IDLE → COUNTDOWN
        result = sm.transition(State.COUNTDOWN)
        assert result is False
        assert sm.state == State.IDLE  # unchanged

    def test_listener_called_on_transition(self):
        sm = StateMachine()
        events = []
        sm.add_listener(lambda old, new: events.append((old, new)))
        sm.transition(State.DRAWING)
        assert events == [(State.IDLE, State.DRAWING)]

    def test_listener_not_called_on_invalid_transition(self):
        sm = StateMachine()
        events = []
        sm.add_listener(lambda old, new: events.append((old, new)))
        sm.transition(State.COUNTDOWN)  # invalid
        assert events == []

    def test_is_click_through_idle(self):
        sm = StateMachine()
        assert sm.is_click_through() is True

    def test_is_click_through_drawing(self):
        sm = StateMachine()
        sm.transition(State.DRAWING)
        assert sm.is_click_through() is False

    def test_is_drawing_active_annotating(self):
        sm = StateMachine()
        sm.transition(State.ANNOTATING)
        assert sm.is_drawing_active() is True

    def test_full_recognition_flow(self):
        sm = StateMachine()
        assert sm.transition(State.DRAWING)
        assert sm.transition(State.COUNTDOWN)
        assert sm.transition(State.RECOGNIZING)
        assert sm.transition(State.IDLE)
        assert sm.state == State.IDLE

    def test_annotation_toggle(self):
        sm = StateMachine()
        assert sm.transition(State.ANNOTATING)
        assert sm.state == State.ANNOTATING
        assert sm.transition(State.IDLE)
        assert sm.state == State.IDLE
