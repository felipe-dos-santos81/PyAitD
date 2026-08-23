# SPDX-License-Identifier: GPL-2.0-only
"""AITD1 M3b play loop: one event pump, fixed-step PLAY ticks, modal mode
routing, one presentation per frame — freeze-proof replacement for FITD's
nested blocking modal loops (mainLoop.cpp:41-281)."""
import argparse
import pathlib
import sys

import pygame

from maitd.actors import anim_player_for, sort_actor_indices
from maitd.effects import GameMode
from maitd.floor import Floor
from maitd.game import init_game, spawn_stage_actors
from maitd.life import Trace
from maitd.pak import PakError
# imported by name, not module-qualified: run() reads play_tick as a module
# global, which is the patch point tests/test_play_loop.py relies on
from maitd.playworld import TICK_MS, play_tick
from maitd.render import Renderer
from maitd.skel import skin
from maitd.ui import Command, InputBuffer, ModalSession, event_to_input
from maitd.world import CameraState

DEFAULT_DATA = (
    pathlib.Path(__file__).resolve().parent.parent
    / "Alone in the Dark 1.app"
    / "Contents"
    / "Resources"
    / "game"
    / "INDARK"
)


def parse_args(argv):
    p = argparse.ArgumentParser(prog="maitd", description="AITD1 play viewer (M3b: interaction loop)")
    p.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA, help="game data dir")
    p.add_argument("--floor", type=int, default=0, help="floor number (default 0)")
    p.add_argument("--trace", type=pathlib.Path, default=None, help="write per-opcode LIFE trace to FILE")
    return p.parse_args(argv)


def _scene_frame(game, floor, renderer):
    # mainLoop.cpp:270 AllRedraw: M2 render pipeline, every live actor skinned
    # through the current camera (num_camera is room-relative, FITD InitView).
    room = floor.rooms[game.current_room]
    cam_idx = room.camera_indices[game.num_camera]
    cam = floor.cameras[cam_idx]
    state = CameraState.from_camera(
        cam, room.world_x, room.world_y, room.world_z,
    ).angles()
    results = []
    actor_rooms = []
    actor_zvs = []
    draw_order = sort_actor_indices(game, state.x, state.y, state.z)
    for index in draw_order:
        actor = game.actors[index]
        body = game.assets.body(actor.body_num)
        if actor.anim == -1:
            states = [(0, (0, 0, 0))] * len(body.groups)
        else:
            states = anim_player_for(game, index).group_states()
        results.append(skin(
            body,
            states,
            (
                actor.world_x + actor.step_x,
                actor.world_y + actor.step_y,
                actor.world_z + actor.step_z,
            ),
            state,
            actor_angles=(actor.alpha, actor.beta, actor.gamma),
        ))
        actor_rooms.append(actor.room)
        actor_zvs.append(actor.zv)
    return renderer.compose_scene(
        floor.camera_image(cam_idx), results, floor.masks(cam_idx), floor.palette,
        actor_rooms, actor_zvs,
    )


def _inventory_view(game, session):
    from maitd.interaction import inventory_actions, inventory_items
    object_ids = inventory_items(game)
    selected = object_ids[min(session.inventory.object_cursor, len(object_ids) - 1)]
    return object_ids, inventory_actions(game, selected)


def route_command(game, session, command):
    from maitd.effects import GameMode, OpenInventory, ReadText, ShowFound, ShowPicture
    from maitd.interaction import (
        apply_found_result, apply_inventory_result, apply_reading_result,
    )
    from maitd.ui import (
        Command, ReadingResult, reading_pages, reduce_found, reduce_inventory,
        reduce_reading,
    )
    if game.mode is GameMode.PLAY:
        if command is Command.OPEN_INVENTORY and game.status_screen_allowed:
            if game.inventory_count[game.current_inventory]:
                game.open_modal(OpenInventory())
                session.reset_for(game.active_modal)
        return True

    session.reset_for(game.active_modal)
    modal_command = Command.ACCEPT if command is Command.OPEN_INVENTORY else command
    if isinstance(game.active_modal, ShowFound):
        result = reduce_found(
            session.found, modal_command,
            forced_refuse=game.active_modal.forced_refuse,
        )
        if result is not None:
            apply_found_result(game, result)
        return True
    if isinstance(game.active_modal, OpenInventory):
        object_ids, action_ids = _inventory_view(game, session)
        result = reduce_inventory(
            session.inventory, modal_command,
            object_ids=object_ids, action_ids=action_ids,
        )
        if result is not None:
            apply_inventory_result(game, result)
        return True
    if isinstance(game.active_modal, ReadText):
        page_count = len(reading_pages(game.active_modal, game.assets))
        result = reduce_reading(session.reading, modal_command, page_count=page_count)
        if result is not None:
            apply_reading_result(game, result)
        return True
    if isinstance(game.active_modal, ShowPicture):
        if modal_command in (Command.ACCEPT, Command.CANCEL):
            apply_reading_result(game, ReadingResult(True))
        return True
    raise RuntimeError(f"unroutable modal {type(game.active_modal).__name__}")


def route_mouse(game, session, logical_pos):
    from maitd.effects import OpenInventory, ReadText, ShowFound, ShowPicture
    from maitd.interaction import (
        apply_found_result, apply_inventory_result, apply_reading_result,
    )
    from maitd.ui import (
        ReadingResult, hit_test_found, hit_test_inventory, hit_test_reading,
        reading_pages, turn_page,
    )
    if logical_pos is None or game.active_modal is None:
        return True
    effect = game.active_modal
    session.reset_for(effect)
    if isinstance(effect, ShowFound):
        result = hit_test_found(logical_pos)
        if result is not None:
            apply_found_result(game, result)
        return True
    if isinstance(effect, OpenInventory):
        object_ids, action_ids = _inventory_view(game, session)
        result = hit_test_inventory(
            logical_pos, session.inventory, object_ids, action_ids,
        )
        if result is not None:
            apply_inventory_result(game, result)
        return True
    if isinstance(effect, ReadText):
        page_count = len(reading_pages(effect, game.assets))
        result = hit_test_reading(
            logical_pos, session.reading.page, page_count,
        )
        if result is None:
            return True
        if result.page_delta:
            turn_page(session.reading, result.page_delta, page_count)
            return True
        apply_reading_result(game, result)
        return True
    if isinstance(effect, ShowPicture):
        apply_reading_result(game, ReadingResult(True))
        return True
    raise RuntimeError(f"unroutable modal {type(effect).__name__}")


def _auto_dismiss_picture(game, session):
    from maitd.effects import ShowPicture
    from maitd.interaction import apply_reading_result
    from maitd.ui import ReadingResult
    effect = game.active_modal
    if not isinstance(effect, ShowPicture) or effect.delay_units <= 0:
        return True
    delay_ms = effect.delay_units * 1000 // 60
    if session.reading.elapsed_ms < delay_ms:
        return True
    apply_reading_result(game, ReadingResult(True))
    return True


def render_active_mode(game, session, scene_frame):
    from maitd.effects import OpenInventory, ReadText, ShowFound, ShowPicture
    from maitd.ui import (
        overlay_messages, render_found, render_inventory, render_picture,
        render_reading,
    )
    effect = game.active_modal
    if effect is None:
        return overlay_messages(scene_frame, game.messages, game.assets)
    session.reset_for(effect)
    if isinstance(effect, ShowFound):
        world = game.world_objects[effect.object_idx]
        return render_found(effect, session.found, game.assets, game.assets.system_text(world.found_name))
    if isinstance(effect, OpenInventory):
        object_ids, action_ids = _inventory_view(game, session)
        return render_inventory(
            session.inventory, game.assets, scene_frame,
            tuple(game.assets.system_text(game.world_objects[i].found_name) for i in object_ids),
            tuple(game.assets.system_text(i) for i in action_ids),
        )
    if isinstance(effect, ReadText):
        return render_reading(effect, session.reading, game.assets)
    if isinstance(effect, ShowPicture):
        return render_picture(effect, game.assets)
    raise RuntimeError(f"unrenderable modal {type(effect).__name__}")


def run(game, trace_path=None):
    # M3b play loop: one event pump, fixed-step PLAY ticks, one present/frame
    try:
        floor = Floor(game._data_dir, game.current_floor)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    game.trace = Trace(trace_path) if trace_path else None
    renderer = Renderer()
    clock = pygame.time.Clock()
    input_buffer = InputBuffer()
    session = ModalSession()
    running = True
    last = pygame.time.get_ticks()
    accumulator = 0
    if game.num_camera == -1:
        game.num_camera = game.new_num_camera
        game.flag_init_view = 0
    scene_frame = _scene_frame(game, floor, renderer)
    while running:
        for event in pygame.event.get():
            running = event_to_input(event, input_buffer) and running
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                logical = renderer.window_to_logical(event.pos)
                running = route_mouse(game, session, logical) and running
        now = pygame.time.get_ticks()
        elapsed = min(now - last, 250)
        last = now
        was_play = game.mode is GameMode.PLAY
        if input_buffer.commands:
            command = input_buffer.commands.popleft()
            if game.mode is GameMode.PLAY and command is Command.CANCEL:
                running = False
            else:
                route_command(game, session, command)
        if game.mode is GameMode.PLAY:
            accumulator += elapsed
            while accumulator >= TICK_MS and game.mode is GameMode.PLAY:
                play_tick(game, floor, input_buffer)
                accumulator -= TICK_MS
                if floor.number != game.current_floor:
                    floor = Floor(game._data_dir, game.current_floor)
            if game.num_camera != -1:
                scene_frame = _scene_frame(game, floor, renderer)
        else:
            accumulator = 0
            session.reading.elapsed_ms += elapsed
            _auto_dismiss_picture(game, session)
        if was_play and game.mode is not GameMode.PLAY:
            # FITD flushes input on modal entry: leftover edges queued by the
            # same pump (route_command or a found-contact in play_tick) must
            # not reach the new modal, where OPEN_INVENTORY maps to ACCEPT.
            # Already-modal frames keep theirs: freshly queued, must route.
            input_buffer.commands.clear()
        renderer.present(render_active_mode(game, session, scene_frame))
        if game.num_camera != -1:
            # M3a draw_ready gate: transition frames (change_salle/floor
            # pending, num_camera == -1, current_room stale) reuse the
            # previous frame instead of re-indexing rooms/cameras.
            room = floor.rooms[game.current_room]
            cam_idx = room.camera_indices[game.num_camera]
            live = sum(1 for actor in game.actors if actor.index_in_world >= 0)
            pygame.display.set_caption(
                f"maitd — floor {floor.number} room {game.current_room} "
                f"camera {cam_idx} actors {live}"
            )
        clock.tick(60)
    if game.trace is not None:
        game.trace.close()
    renderer.close()
    return 0


def main(argv=None):
    args = parse_args(argv)
    try:
        game = init_game(args.data)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.floor != game.current_floor:
        game.current_floor = args.floor
        spawn_stage_actors(game)
        game.num_camera = -1
        game.flag_init_view = 2
    return run(game, args.trace)


if __name__ == "__main__":
    raise SystemExit(main())
