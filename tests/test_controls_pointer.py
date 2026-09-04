# SPDX-License-Identifier: GPL-2.0-only
"""The hold-follow, double-press and cut-settling rules, each as a unit test
over PointerState with a fake resolver -- the shape the mouse bugs so far
("hold does not walk", "the run window swallowed clicks", "an unreachable
pixel refused") should have been reproduced in."""
import pytest

from PyAitD.app.controls.pointer import (
    CANCEL, CUT_DEAD_ZONE_PX, DOUBLE_PRESS_RESUME_PX, DOUBLE_PRESS_TICKS, NOTHING,
    OPEN_INVENTORY, Attack, Issue, PointerState, drop_destination, end_hold,
    hold_decision, press, press_decision, rebase, release,
)

pytestmark = pytest.mark.shell

WALK_A = (1000, 2000, 0, -1)
WALK_B = (1500, 2500, 0, -1)
TARGET = (300, 400, 0, 13)
PUSH = (300, 400, 0, 4)
STEER = (9000, 9000, 0, -1)


def resolver(table):
    """pixel -> (kind, payload); anything unlisted is blocked."""
    return lambda pos: table.get(pos, ("blocked", None))


def _held(pos, **fields):
    state = PointerState(**fields)
    press(state, pos)
    return state


def test_a_walk_press_issues_and_opens_the_follow():
    state = _held((10, 10))
    decision = press_decision(state, tick=100, pos=(10, 10), camera=2,
                              resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    assert decision == Issue("walk", WALK_A, False)
    assert (state.follow_last, state.follow_pos, state.follow_camera) == (WALK_A, (10, 10), 2)
    assert (state.spent, state.run, state.last_press_tick, state.settle_origin) == (False, False, 100, None)


def test_a_blocked_press_does_nothing_but_still_stamps_the_press_clock():
    state = _held((10, 10))
    assert press_decision(state, tick=100, pos=(10, 10), camera=2, resolve=resolver({}), latched_push=False) is NOTHING
    assert (state.last_press_tick, state.follow_last) == (100, None)


def test_inventory_and_attack_presses_spend_the_hold():
    state = _held((10, 10))
    assert press_decision(state, tick=1, pos=(10, 10), camera=0,
                          resolve=resolver({(10, 10): ("inventory", None)}), latched_push=False) is OPEN_INVENTORY
    assert state.spent is True
    state = _held((10, 10))
    assert press_decision(state, tick=1, pos=(10, 10), camera=0,
                          resolve=resolver({(10, 10): ("attack", 7)}), latched_push=False) == Attack(7)
    assert (state.spent, state.follow_last) == (True, None)


def test_a_push_press_latches_without_a_follow_and_spends_the_hold():
    state = _held((10, 10))
    assert press_decision(state, tick=1, pos=(10, 10), camera=0,
                          resolve=resolver({(10, 10): ("push", PUSH)}), latched_push=False) == Issue("push", PUSH, False)
    assert (state.follow_last, state.follow_pos, state.follow_camera, state.spent) == (None, None, None, True)


def test_a_press_while_a_push_is_latched_is_ignored():
    state = _held((10, 10))
    assert press_decision(state, tick=1, pos=(10, 10), camera=0,
                          resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=True) is NOTHING


def test_the_second_press_within_the_window_runs_and_resumes_the_first_destination():
    state = _held((10, 10))
    press_decision(state, tick=100, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    release(state)
    end_hold(state, steering=False)
    assert (state.resume_last, state.resume_pos, state.follow_last) == (WALK_A, (10, 10), None)
    drift = (10 + DOUBLE_PRESS_RESUME_PX, 10)
    press(state, drift)
    # the drifted pixel would resolve elsewhere; the resume wins
    decision = press_decision(state, tick=100 + DOUBLE_PRESS_TICKS - 1, pos=drift, camera=0,
                              resolve=resolver({drift: ("walk", WALK_B)}), latched_push=False)
    assert decision == Issue("walk", WALK_A, True)
    assert state.run is True


def test_a_press_outside_the_window_or_too_far_picks_afresh():
    state = _held((10, 10))
    press_decision(state, tick=100, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    release(state)
    end_hold(state, steering=False)
    far = (10 + DOUBLE_PRESS_RESUME_PX + 1, 10)
    press(state, far)
    assert press_decision(state, tick=101, pos=far, camera=0,
                          resolve=resolver({far: ("walk", WALK_B)}), latched_push=False) == Issue("walk", WALK_B, True)
    release(state)
    end_hold(state, steering=False)
    press(state, (10, 10))
    assert press_decision(state, tick=101 + DOUBLE_PRESS_TICKS, pos=(10, 10), camera=0,
                          resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False) == Issue("walk", WALK_A, False)


def test_a_steer_is_never_stashed_for_resume():
    state = _held((10, 10))
    press_decision(state, tick=1, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("steer", STEER)}), latched_push=False)
    release(state)
    end_hold(state, steering=True)
    assert (state.resume_last, state.resume_pos) == (None, (10, 10))


def test_a_still_pointer_means_what_it_meant_last_frame():
    state = _held((10, 10))
    press_decision(state, tick=1, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    calls = []
    def spy(pos):
        calls.append(pos)
        return ("walk", WALK_B)
    assert hold_decision(state, pos=(10, 10), camera=0, resolve=spy, latched_push=False, intent_alive=True) is NOTHING
    assert calls == []


def test_a_moved_pointer_re_issues_only_when_the_resolution_differs():
    state = _held((10, 10))
    press_decision(state, tick=1, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    same = resolver({(11, 10): ("walk", WALK_A), (40, 40): ("target", TARGET)})
    assert hold_decision(state, pos=(11, 10), camera=0, resolve=same, latched_push=False, intent_alive=True) is NOTHING
    assert state.follow_pos == (11, 10)
    assert hold_decision(state, pos=(40, 40), camera=0, resolve=same, latched_push=False, intent_alive=True) == Issue("target", TARGET, False)
    assert state.follow_last == TARGET


def test_a_blocked_hold_cancels_a_live_intent_once_and_retries_only_after_motion():
    state = _held((10, 10))
    press_decision(state, tick=1, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    assert hold_decision(state, pos=(50, 50), camera=0, resolve=resolver({}), latched_push=False, intent_alive=True) is CANCEL
    assert state.follow_last is None
    assert hold_decision(state, pos=(50, 50), camera=0, resolve=resolver({}), latched_push=False, intent_alive=False) is NOTHING
    assert hold_decision(state, pos=(51, 50), camera=0, resolve=resolver({}), latched_push=False, intent_alive=False) is NOTHING


def test_a_camera_cut_opens_a_dead_zone_the_hand_must_leave():
    state = _held((10, 10))
    press_decision(state, tick=1, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    inside = (10 + CUT_DEAD_ZONE_PX, 10 - CUT_DEAD_ZONE_PX)
    table = resolver({inside: ("walk", WALK_B), (30, 30): ("walk", WALK_B)})
    assert hold_decision(state, pos=inside, camera=3, resolve=table, latched_push=False, intent_alive=True) is NOTHING
    assert (state.settle_origin, state.follow_camera, state.follow_last) == ((10, 10), 0, WALK_A)
    assert hold_decision(state, pos=(30, 30), camera=3, resolve=table, latched_push=False, intent_alive=True) == Issue("walk", WALK_B, False)
    assert (state.settle_origin, state.follow_camera) == (None, 3)


def test_the_hold_keeps_running_while_the_run_belongs_to_it():
    state = PointerState(last_press_tick=90)
    press(state, (10, 10))
    press_decision(state, tick=100, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    assert hold_decision(state, pos=(20, 20), camera=0, resolve=resolver({(20, 20): ("walk", WALK_B)}),
                         latched_push=False, intent_alive=True) == Issue("walk", WALK_B, True)


def test_a_spent_or_released_hold_and_a_latched_push_never_follow():
    spent = _held((10, 10), spent=True)
    assert hold_decision(spent, pos=(20, 20), camera=0, resolve=resolver({(20, 20): ("walk", WALK_A)}), latched_push=False, intent_alive=False) is NOTHING
    released = PointerState(pos=(20, 20))
    assert hold_decision(released, pos=(20, 20), camera=0, resolve=resolver({(20, 20): ("walk", WALK_A)}), latched_push=False, intent_alive=False) is NOTHING
    latched = _held((10, 10))
    assert hold_decision(latched, pos=(20, 20), camera=0, resolve=resolver({(20, 20): ("walk", WALK_A)}), latched_push=True, intent_alive=True) is NOTHING


def test_ending_the_hold_clears_spent_and_run_but_keeps_the_press_clock():
    state = _held((10, 10), spent=True, run=True, last_press_tick=42, follow_last=WALK_A, follow_pos=(10, 10), follow_camera=1, settle_origin=(9, 9))
    end_hold(state, steering=False)
    assert (state.spent, state.run, state.last_press_tick) == (False, False, 42)
    assert (state.follow_last, state.follow_pos, state.follow_camera, state.settle_origin) == (None, None, None, None)
    assert (state.resume_last, state.resume_pos) == (WALK_A, (10, 10))


def test_rebase_drops_the_destination_and_the_stash_but_keeps_the_hold():
    state = _held((10, 10), follow_last=WALK_A, follow_pos=(10, 10), follow_camera=1, resume_last=WALK_B, resume_pos=(3, 3), run=True)
    rebase(state)
    assert (state.held, state.run) == (True, True)
    assert (state.follow_last, state.follow_pos, state.resume_last, state.resume_pos) == (None, None, None, None)
    drop_destination(state)   # idempotent
    assert state.follow_camera is None
