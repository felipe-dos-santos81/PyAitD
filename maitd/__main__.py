# SPDX-License-Identifier: GPL-2.0-only
"""AITD1 M3b play loop: one event pump, fixed-step PLAY ticks, modal mode
routing, one presentation per frame — freeze-proof replacement for FITD's
nested blocking modal loops (mainLoop.cpp:41-281)."""
import argparse
import pathlib
import sys

import pygame

from maitd.actors import anim_player_for, gere_anim, sort_actor_indices
from maitd.effects import GameMode
from maitd.floor import Floor
from maitd.formats import parse_cover_zones
from maitd.game import (
    AF_ANIMATED,
    AF_TRIGGER,
    change_salle,
    game_step_tick,
    init_game,
    spawn_stage_actors,
)
from maitd.life import Trace, life_gate
from maitd.mask import create_aitd1_mask
from maitd.pak import PakError
from maitd.render import Renderer
from maitd.skel import skin
from maitd.ui import Command, InputBuffer, ModalSession, event_to_input
from maitd.world import CameraState, find_best_camera, is_in_poly

DEFAULT_DATA = (
    pathlib.Path(__file__).resolve().parent.parent
    / "Alone in the Dark 1.app"
    / "Contents"
    / "Resources"
    / "game"
    / "INDARK"
)

TICK_MS = 20  # 50 Hz logic tick


def parse_args(argv):
    p = argparse.ArgumentParser(prog="maitd", description="AITD1 play viewer (M3b: interaction loop)")
    p.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA, help="game data dir")
    p.add_argument("--floor", type=int, default=0, help="floor number (default 0)")
    p.add_argument("--trace", type=pathlib.Path, default=None, help="write per-opcode LIFE trace to FILE")
    return p.parse_args(argv)


def apply_play_input(game, input_buffer):
    game.local_joyd = input_buffer.held_joyd if input_buffer.focused else 0
    game.local_click = 1 if input_buffer.focused and input_buffer.action_held else 0
    game.local_key = 0
    game.action = 0x2000 if game.local_click else 0


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
    translate_x = (cam.x - room.world_x) * 10
    translate_y = (room.world_y - cam.y) * 10
    translate_z = (room.world_z - cam.z) * 10
    draw_order = sort_actor_indices(game, translate_x, translate_y, translate_z)
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
    masks = create_aitd1_mask(
        floor.camera_raw, floor.camera_data_offsets[cam_idx],
    )
    return renderer.compose_scene(
        floor.camera_image(cam_idx), results, masks, floor.palette,
        actor_rooms, actor_zvs,
    )


def _anim_pass(game):
    from maitd.interaction import gere_dec
    for index, actor in enumerate(game.actors):
        if actor.index_in_world < 0:
            continue
        flags = actor.object_type
        if flags & AF_ANIMATED:
            gere_anim(game, index)
            if game.mode is not GameMode.PLAY:
                return False
        if flags & AF_TRIGGER:
            gere_dec(game, index)
    return game.mode is GameMode.PLAY


def _camera_switch(game, floor):
    # main.cpp:3654 GereSwitchCamera port: hero out of the current camera's
    # cover zones -> findBestCamera among the hero-room's cameras.
    if game.current_camera_target_actor == -1:
        return
    actor = game.actors[game.current_camera_target_actor]
    room = floor.rooms[actor.room]
    room_cameras = [floor.cameras[i] for i in room.camera_indices]
    zv = actor.zv
    x1, x2 = int(zv[0] / 10), int(zv[1] / 10)
    z1, z2 = int(zv[4] / 10), int(zv[5] / 10)
    if game.num_camera != -1:
        cam_idx = room.camera_indices[game.num_camera]
        cam = floor.cameras[cam_idx]
        viewed = [vr.viewed_room_idx for vr in cam.viewed_rooms]
        if actor.room in viewed:
            vi = viewed.index(actor.room)
            off = floor.camera_data_offsets[cam_idx]
            if is_in_poly(x1, x2, z1, z2, parse_cover_zones(floor.camera_raw, off, vi)):
                return
    zones_by_camera = []
    for cam_idx in room.camera_indices:
        cam = floor.cameras[cam_idx]
        viewed = [vr.viewed_room_idx for vr in cam.viewed_rooms]
        if actor.room in viewed:
            vi = viewed.index(actor.room)
            off = floor.camera_data_offsets[cam_idx]
            zones_by_camera.append(parse_cover_zones(floor.camera_raw, off, vi))
        else:
            zones_by_camera.append([])
    new_camera = find_best_camera(x1, x2, z1, z2, actor.beta, room_cameras, zones_by_camera)
    if new_camera != -1 and game.num_camera != new_camera:
        game.new_num_camera = new_camera
        game.flag_init_view = 1


def play_tick(game, floor, input_buffer):
    # mainLoop.cpp:41-281 PlayWorld, one 50Hz iteration, PLAY mode only.
    # Rendering stays outside this fixed-step function so catch-up ticks
    # cannot block input behind repeated GPU work.
    from maitd.effects import LifeFrame
    from maitd.interaction import (
        advance_messages, drain_immediate_effects, execute_found_life, run_life,
    )
    if game.mode is not GameMode.PLAY:
        return False
    apply_play_input(game, input_buffer)
    game_step_tick(game)
    in_hand = game.in_hand_table[game.current_inventory]
    if in_hand != -1 and not execute_found_life(game, in_hand):
        return False
    if not drain_immediate_effects(game) or game.mode is not GameMode.PLAY:
        return False
    for actor in game.actors:
        if actor.index_in_world >= 0:
            actor.col_by = actor.hit_by = actor.hit = actor.hard_dec = actor.hard_col = -1
    if not _anim_pass(game):
        return False
    for index, actor in enumerate(game.actors):
        if actor.index_in_world < 0:
            continue
        if life_gate(actor):
            if not run_life(game, LifeFrame(index, actor.life)):
                drain_immediate_effects(game)
                return False
            if not drain_immediate_effects(game):
                return False
        if game.flag_change_etage:
            break
    if game.flag_change_etage:
        # LoadEtage M3a subset (floor.cpp:7): floor data swap happens in run();
        # FITD LoadEtage sets FlagChangeSalle so the view re-rooms next tick.
        game.current_floor = game.new_num_etage
        game.flag_change_etage = 0
        game.num_camera = -1
        game.flag_change_salle = 1
        return False
    if game.flag_change_salle:
        # mainLoop.cpp:194-199: ChangeSalle + InitView + continue (no draw)
        change_salle(game, game.new_num_salle)
        game.flag_change_salle = 0
        return False
    _camera_switch(game, floor)
    if game.flag_init_view:
        # InitView M3a subset: camera data is loaded on demand at draw
        game.num_camera = game.new_num_camera
        game.flag_init_view = 0
    if game.flag_genere_aff_list:
        spawn_stage_actors(game)
        game.flag_genere_aff_list = 0
    advance_messages(game)
    return True


def route_command(game, session, command, scene_frame):
    from maitd.effects import GameMode, OpenInventory, ReadText, ShowFound, ShowPicture
    from maitd.interaction import (
        apply_found_result, apply_inventory_result, apply_reading_result,
        inventory_actions, inventory_items,
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
        object_ids = inventory_items(game)
        selected = object_ids[min(session.inventory.object_cursor, len(object_ids) - 1)]
        actions = inventory_actions(game, selected)
        result = reduce_inventory(
            session.inventory, modal_command,
            object_ids=object_ids, action_ids=actions,
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


def route_mouse(game, session, logical_pos, scene_frame):
    from maitd.effects import OpenInventory, ReadText, ShowFound, ShowPicture
    from maitd.interaction import (
        apply_found_result, apply_inventory_result, apply_reading_result,
        inventory_actions, inventory_items,
    )
    from maitd.ui import (
        ReadingResult, hit_test_found, hit_test_inventory, hit_test_reading,
        reading_pages,
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
        object_ids = inventory_items(game)
        selected = object_ids[min(session.inventory.object_cursor, len(object_ids) - 1)]
        action_ids = inventory_actions(game, selected)
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
            session.reading.page = min(
                page_count - 1,
                max(0, session.reading.page + result.page_delta),
            )
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
    from maitd.interaction import inventory_actions, inventory_items
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
        object_ids = inventory_items(game)
        selected = object_ids[min(session.inventory.object_cursor, len(object_ids) - 1)]
        action_ids = inventory_actions(game, selected)
        return render_inventory(
            object_ids, action_ids, session.inventory, game.assets, scene_frame,
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
                running = route_mouse(game, session, logical, scene_frame) and running
        now = pygame.time.get_ticks()
        elapsed = min(now - last, 250)
        last = now
        if input_buffer.commands:
            command = input_buffer.commands.popleft()
            if game.mode is GameMode.PLAY and command is Command.CANCEL:
                running = False
            else:
                route_command(game, session, command, scene_frame)
        if game.mode is GameMode.PLAY:
            accumulator += elapsed
            while accumulator >= TICK_MS and game.mode is GameMode.PLAY:
                play_tick(game, floor, input_buffer)
                accumulator -= TICK_MS
                if floor.number != game.current_floor:
                    floor = Floor(game._data_dir, game.current_floor)
            scene_frame = _scene_frame(game, floor, renderer)
        else:
            accumulator = 0
            session.reading.elapsed_ms += elapsed
            _auto_dismiss_picture(game, session)
        renderer.present(render_active_mode(game, session, scene_frame))
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
