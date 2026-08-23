# SPDX-License-Identifier: GPL-2.0-only
"""Mouse follower: turns a NavIntent into one tick of steering.

Runs inside playworld.apply_play_input, so the decision is made once per tick
and consumed twice — once as mirrored joystick bits (LIFE scripts read the
joystick through evalVar 0x13 and must not see a dead stick while the player
is walking), and once by tracks._process_track_mouse, which applies it through
the same _turn_toward the engine's follow mode uses.
"""
from PyAitD.effects import NavDecision
from PyAitD.navmesh import find_path
from PyAitD.realvalue import give_distance_2d
from PyAitD.tracks import cap_objet

ARRIVE_DISTANCE = 400    # tracks.DISTANCE_TO_POINT_TRESSHOLD [sic], same units
WAYPOINT_DISTANCE = 400  # how close counts as reaching an intermediate hop


def _repath(game, actor, mesh):
    intent = game.nav_intent
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


def decide(game, actor, mesh):
    """One tick of follower output, or None when there is nothing to follow."""
    intent = game.nav_intent
    if intent is None:
        return None
    if intent.waypoints is None:
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
    if len(intent.waypoints) == 1 and distance < ARRIVE_DISTANCE:
        return NavDecision(0, target_x, target_z, advance=False, arrived=True)
    joyd = 1  # forward
    modificator = cap_objet(here_x, here_z, actor.beta, target_x, target_z)
    if modificator > 0:
        joyd |= 4   # gere_manual_rot: bit 4 -> direction +1
    elif modificator < 0:
        joyd |= 8   # bit 8 -> direction -1
    return NavDecision(joyd, target_x, target_z, advance=True, arrived=False)
