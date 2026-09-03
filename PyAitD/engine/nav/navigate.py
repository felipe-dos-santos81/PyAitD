# SPDX-License-Identifier: GPL-2.0-only
"""Mouse follower: turns a NavIntent into one tick of steering.

Runs inside playworld.apply_play_input, so the decision is made once per tick
and consumed twice — once as mirrored joystick bits (LIFE scripts read the
joystick through evalVar 0x13 and must not see a dead stick while the player
is walking), and once by tracks._process_track_mouse, which applies it through
the same _turn_toward the engine's follow mode uses.
"""
from PyAitD.engine.script.effects import NavDecision
from PyAitD.engine.nav.navmesh import find_path
from PyAitD.engine.space.realvalue import give_distance_2d
from PyAitD.engine.actor.tracks import cap_objet, get_room_link
from PyAitD.engine.space.world import cdiv

ARRIVE_DISTANCE = 400    # tracks.DISTANCE_TO_POINT_TRESSHOLD [sic], same units
WAYPOINT_DISTANCE = 400  # how close counts as reaching an intermediate hop
# Give-up guard. The follower steers at the engine's own rotation rate
# (_turn_toward: 256 beta units per 60 ticks), so a turn-around takes ~120 ticks
# during which the hero legitimately walks *away* from its target. Measured over
# 80 randomised floor-0 walks with the guard disabled: walks that completed
# never spent more than 147 ticks without closing on the current steering
# target, while a hero wedged against geometry racked up 1500-2900. 300 is twice
# the worst honest run, and six seconds of grinding is already far too long.
STALL_TICKS = 300
# How close to the destination a give-up still counts as getting there. Past it
# the click is abandoned instead of dispatched, so a hero stuck behind a wall
# cannot reach the object through it. The hero's own half-extent is 266, so this
# is about one body short of the standing spot the click snapped to.
GIVE_UP_ARRIVE_DISTANCE = 2 * ARRIVE_DISTANCE


def _repath(game, actor, mesh):
    intent = game.nav_intent
    intent.path_room = actor.room
    if intent.room != actor.room:
        # One hop: aim for the centre of the zone linking us to the target room,
        # exactly as _process_track_follow does for a followed actor in another
        # room. gere_dec performs the actual transition when we cross it; the
        # room change then re-paths us to the real destination below.
        # cdiv (C truncation toward zero), same as _process_track_follow uses.
        link = get_room_link(game, actor.room, intent.room)
        intent.waypoints = [(
            link.x1 + cdiv(link.x2 - link.x1, 2),
            link.z1 + cdiv(link.z2 - link.z1, 2),
        )]
        return
    start = (actor.room_x + actor.step_x, actor.room_z + actor.step_z)
    goal = (intent.dest_x, intent.dest_z)
    if mesh is not None:
        path = find_path(mesh, start, goal)
        if path:
            intent.waypoints = list(path)
            return
    # degraded mode: no mesh, hero off-mesh, or no route — steer straight at the
    # click and let the engine's own collision slide do what A* would not
    intent.waypoints = [goal]


def decide(game, actor, mesh, *, stop_at_destination=True):
    """One tick of follower output, or None when there is nothing to follow."""
    intent = game.nav_intent
    if intent is None:
        return None
    if intent.waypoints is None or intent.path_room != actor.room:
        _repath(game, actor, mesh)
    here_x = actor.room_x + actor.step_x
    here_z = actor.room_z + actor.step_z
    while len(intent.waypoints) > 1:
        target = intent.waypoints[0]
        if give_distance_2d(here_x, here_z, target[0], target[1]) >= WAYPOINT_DISTANCE:
            break
        intent.waypoints.pop(0)
    target_x, target_z = intent.waypoints[0]
    distance = give_distance_2d(here_x, here_z, target_x, target_z)
    # Only the destination room reports arrival. A cross-room intent's single
    # waypoint is the room-link midpoint, not the destination: the type-0
    # sce_zone that performs the transition starts 50+ units past the link slab
    # (measured over all 95 type-4 links: median 50, max 850), so stopping at
    # the link would halt the hero in the doorway and dispatch as if it had
    # reached the click. gere_dec crosses us over; _repath then aims at the
    # real destination.
    if (stop_at_destination and intent.room == actor.room
            and len(intent.waypoints) == 1 and distance < ARRIVE_DISTANCE):
        return NavDecision(0, target_x, target_z, advance=False, arrived=True)
    if intent.hold_until is not None and game.timer < intent.hold_until:
        # The run commit window. The hero is aimed but not yet moving: a press
        # cannot know whether a second one is coming, so starting the walk
        # immediately makes every double press walk before it runs. Standing
        # still for a few ticks lets the second press arrive and replace this
        # intent with a running one that never took a walking step.
        #
        # Placed after the arrival test so a click the hero is already
        # standing on still dispatches at once (a door, an object, a pickup
        # loses nothing to the window), and before the stall test so the ticks
        # spent waiting are not counted as failing to make progress.
        return NavDecision(0, target_x, target_z, advance=False, arrived=False)
    if _stalled(intent, target_x, target_z, distance):
        # Blocked short of the destination. Count it as arrival only when we got
        # near enough that a player would call it there — the mesh does not
        # model other actors' ZVs, so "wedged against the thing I clicked" is a
        # real arrival, while "wedged halfway across the room" is a dead click.
        close = distance < GIVE_UP_ARRIVE_DISTANCE
        return NavDecision(
            0, target_x, target_z, advance=False, arrived=close, abandoned=not close,
        )
    joyd = 1  # forward
    modificator = cap_objet(here_x, here_z, actor.beta, target_x, target_z)
    # The joyd mirror must reproduce the *physical* turn, and the two engine
    # functions read the same numeral with opposite meaning:
    #   tracks._turn_toward:    init_real_value(beta, beta - angle_modif * step)
    #   tracks.gere_manual_rot: bit 4 -> direction +1, bit 8 -> direction -1,
    #                           init_real_value(beta, beta + direction * 0x100)
    # so equivalence is direction == -angle_modif, i.e. cap_objet > 0 -> bit 8.
    # It is a sign relationship, not a numeral coincidence: do not "correct" it
    # to match +1 with bit 4. tests/test_navigate.py proves both paths drive
    # beta the same way for the same target.
    if modificator > 0:
        joyd |= 8
    elif modificator < 0:
        joyd |= 4
    return NavDecision(
        joyd, target_x, target_z, advance=True, arrived=False, run=intent.run,
    )


def _stalled(intent, target_x, target_z, distance):
    """True once the follower has spent STALL_TICKS not closing on its target.

    Without this the hero grinds into an obstacle forever: the mesh models hard
    cols but not other actors' ZVs, so a destination can be walkable on the mesh
    and still unreachable. The caller turns a give-up into an arrival or into an
    abandoned click depending on how far short of the destination it happened.
    """
    if (target_x, target_z) != intent.stall_target or distance < intent.stall_best:
        intent.stall_target = (target_x, target_z)
        intent.stall_best = distance
        intent.stall_ticks = 0
        return False
    intent.stall_ticks += 1
    return intent.stall_ticks >= STALL_TICKS
