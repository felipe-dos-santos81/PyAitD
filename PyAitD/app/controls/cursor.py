# SPDX-License-Identifier: GPL-2.0-only
"""What the PLAY cursor should show: the resolver's kind for the hovered
pixel, the live destination and the press preview, projected on screen.
Drawing is app.ui.render_cursor."""
import pygame

from PyAitD.engine.script.effects import GameMode
from PyAitD.app.controls.router import resolve_play_click


def hit_actor_ids(game):
    return {
        actor_idx for actor_idx, actor in enumerate(game.actors)
        if actor.hit_by != -1
    }


def hit_feedback_rects(game, draw_list, actor_ids):
    """Presentation rectangles for latched hit actors still visible in PLAY."""
    if game.mode is not GameMode.PLAY or game.active_modal is not None:
        return ()
    rects = []
    for actor_idx, box in draw_list:
        if box is None or actor_idx not in actor_ids:
            continue
        x0, y0, x1, y1 = box
        rects.append(pygame.Rect(x0, y0, x1 - x0 + 1, y1 - y0 + 1))
    return tuple(rects)


def cursor_state(game, floor, hover, draw_list, pointer):
    """(kind, payload) the cursor should show for `hover`: a latched push
    stays "push" whatever the pointer drifts over; otherwise the resolver."""
    intent = getattr(game, "nav_intent", None)
    if (pointer.held and intent is not None
            and intent.requires_hold):
        return "push", None
    return resolve_play_click(game, floor, hover, draw_list)


def cursor_kind(game, floor, hover, draw_list, pointer):
    return cursor_state(game, floor, hover, draw_list, pointer)[0]


def marker_for(game, floor, payload):
    """Project a (dest_x, dest_z, room, object_idx) payload to the logical
    frame under the camera on screen, or None."""
    from PyAitD.engine.nav.picking import project_room_point, viewed_floor_y
    if payload is None or game.num_camera == -1:
        return None
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1:
        return None
    hero = game.actors[hero_idx]
    dest_x, dest_z, room, _object_idx = payload
    y = viewed_floor_y(floor, hero.room, room, hero.world_y)
    return project_room_point(floor, hero.room, game.num_camera, room, dest_x, y, dest_z)


def intent_marker(game, floor):
    """Where the live intent is heading, on screen, or None.

    A steer has no destination to mark: its `dest` is a bearing 12000 units
    out, so a diamond there would sit near the horizon pointing at nothing the
    hero is trying to reach.
    """
    intent = getattr(game, "nav_intent", None)
    if intent is None or intent.steering:
        return None
    return marker_for(game, floor, (intent.dest_x, intent.dest_z, intent.room, -1))
