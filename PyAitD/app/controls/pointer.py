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


def settling(state):
    return state.settle_origin is not None


@dataclass(frozen=True)
class Nothing:
    pass


@dataclass(frozen=True)
class Cancel:
    pass


@dataclass(frozen=True)
class OpenInventory:
    pass


@dataclass(frozen=True)
class Attack:
    target: int


@dataclass(frozen=True)
class Issue:
    kind: str          # walk | steer | target | push
    payload: tuple     # (dest_x, dest_z, room, object_idx)
    run: bool


NOTHING = Nothing()
CANCEL = Cancel()
OPEN_INVENTORY = OpenInventory()


def _resume_destination(state, pos):
    """The destination this press should reuse, or None to pick afresh.

    The second press of a double press is the same finger on the same spot
    saying "faster", so it resumes what the first press committed to instead
    of resolving again -- a pixel of drift between the two halves of one
    gesture must not choose a different cell. Only a double press (run)
    within DOUBLE_PRESS_RESUME_PX of the first press's pixel resumes.
    """
    if not state.run:
        return None
    last, at = state.resume_last, state.resume_pos
    if last is None or at is None:
        return None
    if (abs(pos[0] - at[0]) > DOUBLE_PRESS_RESUME_PX
            or abs(pos[1] - at[1]) > DOUBLE_PRESS_RESUME_PX):
        return None
    return last


def press_decision(state, *, tick, pos, camera, resolve, latched_push):
    """What a PLAY press means. Every press is stamped against the previous
    one (timed on game ticks, so the window stops while a modal has the game
    paused); then the pixel is resolved and the hold opened or spent."""
    previous = state.last_press_tick
    state.run = previous is not None and tick - previous < DOUBLE_PRESS_TICKS
    state.last_press_tick = tick
    kind, payload = resolve(pos)
    if kind == "inventory":
        # a press resolving to anything but walk/target spends the hold: no
        # resuming a follow after it without a fresh press
        state.spent = True
        return OPEN_INVENTORY
    if kind == "attack":
        # spends the hold whether or not the target is accepted
        state.spent = True
        return Attack(payload)
    if latched_push or kind == "blocked":
        return NOTHING
    if kind != "push":
        resumed = _resume_destination(state, pos)
        if resumed is not None:
            payload = resumed
    is_push = kind == "push"
    # a walk or target press opens a held follow; a push is latched and never
    # re-resolved, so it leaves no latch behind and spends the hold
    state.follow_last = None if is_push else payload
    state.follow_pos = None if is_push else pos
    state.follow_camera = None if is_push else camera
    state.settle_origin = None
    state.spent = is_push
    return Issue(kind, payload, state.run)


def hold_decision(state, *, pos, camera, resolve, latched_push, intent_alive):
    """What a held pointer means this frame: re-aim at whatever it resolves
    to, once per frame in which it moved, surviving camera cuts.

    A pixel means a different world point under every camera, so a still
    pointer is never re-resolved at a cut, and after one the hand must leave
    a CUT_DEAD_ZONE_PX zone around where it was before resolution proceeds
    against the new camera. The resolution is compared against follow_last,
    never the live intent: an unchanged resolution is never re-issued within
    one hold, which is both the arrival one-shot latch and the "a dead click
    is not retried until the pointer moves" rule.
    """
    if not state.held or state.spent or latched_push:
        return NOTHING
    if pos == state.follow_pos:
        return NOTHING
    if state.follow_camera is not None and state.follow_camera != camera:
        if state.settle_origin is None:
            state.settle_origin = state.follow_pos if state.follow_pos is not None else pos
        ox, oy = state.settle_origin
        if abs(pos[0] - ox) <= CUT_DEAD_ZONE_PX and abs(pos[1] - oy) <= CUT_DEAD_ZONE_PX:
            return NOTHING
    # every path that advances follow_camera closes the dead zone with it
    state.settle_origin = None
    state.follow_pos = pos
    state.follow_camera = camera
    kind, payload = resolve(pos)
    if kind in ("walk", "target", "steer"):
        if payload == state.follow_last:
            return NOTHING
        state.follow_last = payload
        # the run belongs to the hold, not to the destination
        return Issue(kind, payload, state.run)
    if kind == "blocked":
        state.follow_last = None
        return CANCEL if intent_alive else NOTHING
    return NOTHING   # inventory, attack and push need a fresh press


def drop_destination(state):
    state.follow_last = None
    state.follow_pos = None
    state.follow_camera = None
    state.settle_origin = None


def end_hold(state, *, steering):
    """Button-up or focus loss: the destination plus everything that belonged
    to the press that opened it. The run goes; last_press_tick survives, it
    is what the next press is measured against. A bearing is never stashed
    for resume: it was taken from where the hero stood at the press."""
    state.spent = False
    state.run = False
    state.resume_last = None if steering else state.follow_last
    state.resume_pos = state.follow_pos
    drop_destination(state)


def rebase(state):
    """A floor change: the destination and the stash index a floor that was
    just unloaded, but the button never came up, so the hold survives."""
    state.resume_last = None
    state.resume_pos = None
    drop_destination(state)
