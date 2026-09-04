# SPDX-License-Identifier: GPL-2.0-only
"""The pointer's gesture state and its transitions, pure over PointerState.

Nothing here reads pygame or the game: the pump feeds press/move/release,
and (Task 5) the router asks press_decision/hold_decision what the gesture
means, handing in a resolver for "what is under this pixel".
"""
from dataclasses import dataclass

# How long after a press a second one still reads as a double press, in game
# ticks (50Hz, so 25 is half a second). Deliberately NOT the keyboard's
# tracks.DOUBLE_TAP_TICKS, though the two gestures mean the same thing: a
# double tap on a held movement key is a fast repeat, while a double click is
# one motion of one finger that every desktop times at around half a second
# -- macOS defaults to 500ms. Sharing the keyboard's 10 ticks put the window
# under 180ms, which is quicker than most people can click twice, so the
# gesture almost never fired.
#
# The unit is still game ticks rather than wall-clock milliseconds, because
# the tick clock stops while a modal has the game paused: a press before the
# inventory and one after it are never a double press, however long the
# player spent in there.
DOUBLE_PRESS_TICKS = 25
# how far the pointer may drift between the two halves of a double press and
# still resume the first half's destination
DOUBLE_PRESS_RESUME_PX = 6
# after a camera cut the pointer must move this far on either axis before a
# held follow re-resolves against the new camera
CUT_DEAD_ZONE_PX = 6


@dataclass
class PointerState:
    held: bool = False
    touch: bool = False
    pos: tuple | None = None
    # Held pointer follow: the last (dest_x, dest_z, room, object_idx) issued
    # as an intent during this hold; re-issued only when the resolution
    # differs, which is also the one-shot latch after an arrival.
    follow_last: tuple | None = None
    # The logical pixel follow_last was resolved at: re-resolve only when the
    # pointer has moved off it. None means "resolve on the next frame
    # regardless" -- what a floor change leaves behind.
    follow_pos: tuple | None = None
    # The camera slot follow_pos was resolved under; a mismatch means a cut.
    follow_camera: int | None = None
    # Where the pointer was when a cut was noticed: motion within
    # CUT_DEAD_ZONE_PX of it is settling, not a gesture.
    settle_origin: tuple | None = None
    # True once this hold's press resolved to attack/inventory/push: no
    # follow resumes on this hold, even after the underlying latch dies.
    spent: bool = False
    # A press within DOUBLE_PRESS_TICKS of the previous one runs.
    run: bool = False
    last_press_tick: int | None = None
    # What the hold that just ended was heading for and the pixel that said
    # so, so the second press of a double press resumes it.
    resume_last: tuple | None = None
    resume_pos: tuple | None = None


def reset_pointer(state):
    state.held = False
    state.touch = False
    state.pos = None
    state.follow_last = None
    state.follow_pos = None
    state.follow_camera = None
    state.settle_origin = None
    state.spent = False
    state.run = False
    state.last_press_tick = None
    state.resume_last = None
    state.resume_pos = None


def press(state, pos, touch=False):
    state.held = True
    state.touch = touch
    state.pos = pos


def move(state, pos, touch=False):
    state.touch = touch
    state.pos = pos


def release(state):
    state.held = False
    state.touch = False
    state.pos = None
