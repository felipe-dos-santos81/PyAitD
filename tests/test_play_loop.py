# SPDX-License-Identifier: GPL-2.0-only
from types import SimpleNamespace

import numpy as np

from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.life import life_gate
from PyAitD.navmesh import agent_extent
from PyAitD.picking import project_floor_point


def test_life_gate(data_dir):
    game = init_game(data_dir, hero=0)
    a = game.actors[0]
    a.life, a.life_mode = -1, -1
    assert not life_gate(a)
    a.life, a.life_mode = 3, 0
    assert life_gate(a)
    a.life, a.life_mode = 3, -1
    assert not life_gate(a)
    a.life, a.life_mode = -1, 0
    assert not life_gate(a)


def test_apply_play_input_mapping(data_dir):
    from PyAitD.effects import InputMode
    from PyAitD.playworld import apply_play_input
    from PyAitD.ui import InputBuffer
    game = init_game(data_dir)
    # this asserts the keyboard mapping specifically; mouse is the default
    # input_mode (task 9: playworld — wire the follower into the input
    # snapshot), so it must be selected explicitly to exercise this path.
    game.input_mode = InputMode.KEYBOARD
    state = InputBuffer(held_joyd=9, action_held=True)
    apply_play_input(game, state)
    assert game.local_joyd == 9
    assert game.local_click == 1
    assert game.action == 0x2000


def test_run_coalesces_catch_up_ticks_into_one_present_per_frame(monkeypatch, tmp_path):
    import PyAitD.__main__ as main
    from PyAitD.effects import GameMode, InputMode

    calls = []
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    event_batches = iter(
        [[], [SimpleNamespace(type=main.pygame.QUIT)]]
    )
    times = iter([0, 100, 100])

    monkeypatch.setattr(
        main, "Floor",
        lambda *args: SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])]),
    )
    monkeypatch.setattr(
        main, "Renderer",
        lambda: SimpleNamespace(
            present=lambda image: calls.append("present"), close=lambda: None,
        ),
    )
    monkeypatch.setattr(
        main, "play_tick", lambda *args: calls.append("tick") or True
    )
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: frame)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None)
    )

    game = SimpleNamespace(
        _data_dir=tmp_path, current_floor=0, trace=None, mode=GameMode.PLAY,
        num_camera=-1, new_num_camera=0, flag_init_view=0, current_room=0,
        actors=[], active_modal=None, input_mode=InputMode.MOUSE,
    )
    assert main.run(game) == 0
    assert calls == ["tick"] * 5 + ["present", "present"]


def test_run_skips_scene_recompute_and_caption_on_transition_frames(monkeypatch, tmp_path):
    # M3a draw_ready gate: a floor/room-change tick leaves num_camera == -1
    # with current_room stale until the next tick's change_salle, so the loop
    # must reuse the previous frame instead of recomputing the scene or
    # indexing floor.rooms[current_room] (IndexError / wrong camera).
    import PyAitD.__main__ as main
    from PyAitD.effects import GameMode, InputMode

    scene_calls = []
    presented = []
    frame = np.zeros((200, 320, 3), dtype=np.uint8)

    def scene_frame(*args):
        scene_calls.append(1)
        return frame, []

    def tick(game, floor, input_buffer):
        game.num_camera = -1  # floor-change tick: change_salle pending
        return False

    event_batches = iter(
        [[], [SimpleNamespace(type=main.pygame.QUIT)]]
    )
    times = iter([0, 100, 100])

    monkeypatch.setattr(
        main, "Floor", lambda *args: SimpleNamespace(number=0, rooms=[]),
    )
    monkeypatch.setattr(
        main, "Renderer",
        lambda: SimpleNamespace(present=presented.append, close=lambda: None),
    )
    monkeypatch.setattr(main, "play_tick", tick)
    monkeypatch.setattr(main, "_scene_frame", scene_frame)
    monkeypatch.setattr(main, "render_active_mode", lambda *args: frame)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None)
    )

    game = SimpleNamespace(
        _data_dir=tmp_path, current_floor=0, trace=None, mode=GameMode.PLAY,
        num_camera=0, new_num_camera=0, flag_init_view=0, current_room=0,
        actors=[], active_modal=None, input_mode=InputMode.MOUSE,
    )
    assert main.run(game) == 0
    assert len(scene_calls) == 1  # only the pre-loop frame, reused after
    assert len(presented) == 2


class _FakeAssets:
    def __init__(self, real_assets, anim):
        self._real = real_assets
        self._anim = anim

    def body(self, index):
        return self._real.body(index)

    def anim(self, index):
        return self._anim

    def life(self, index):
        return self._real.life(index)

    def track(self, index):
        return self._real.track(index)


def test_gere_anim_walk_step(data_dir):
    # GereAnim movement port: walk anim with a 20-tick keyframe stepping
    # (0, 0, 4); each keyframe commit moves the actor +4 in X (beta 0x300:
    # walkStep outputs crossed, animMoveZ = cos*step, animMoveX = -sin*step).
    # First tick is bp=0 (inter), so the first commit lands on tick 21.
    from PyAitD.actors import gere_anim
    from PyAitD.formats import Animation, Frame

    game = init_game(data_dir, hero=0)
    actor = game.actors[game.current_camera_target_actor]
    actor.beta = 0x300
    actor.anim = 0
    actor.anim_type = 1  # repeat: no one-shot re-arm at end of anim
    actor.new_anim = -1
    actor.num_of_frames = 1
    game.assets = _FakeAssets(
        game.assets, Animation(num_frames=1, num_groups=0, frames=[Frame(20, (0, 0, 4), [], [])])
    )
    for speed in (1, 2, 3, 4, 5, -1, 0):
        actor.speed = speed
        actor.room_x = 0
        actor.room_z = 0
        for _ in range(21):
            game.timer += 1
            gere_anim(game, game.current_camera_target_actor)
        assert actor.room_x == 4
        assert actor.room_z == 0


def test_gere_anim_one_shot_rearm(data_dir):
    # FITD anim.cpp:654-660: one-shot (non-repeat) anim wrap with no pending
    # anim clears ANIM_UNINTERRUPTABLE and restarts the anim as ANIM_REPEAT
    from PyAitD.actors import gere_anim
    from PyAitD.formats import Animation, Frame

    game = init_game(data_dir, hero=0)
    actor = game.actors[game.current_camera_target_actor]
    actor.anim = 0
    actor.anim_type = 2  # not repeat (bit 0 clear) + uninterruptable
    actor.anim_info = 0  # same anim
    actor.new_anim = -1
    actor.num_of_frames = 1
    game.assets = _FakeAssets(
        game.assets, Animation(num_frames=1, num_groups=0, frames=[Frame(20, (0, 0, 0), [], [])])
    )
    for _ in range(21):
        game.timer += 1
        gere_anim(game, game.current_camera_target_actor)
    assert actor.flag_end_anim == 1
    assert actor.anim_type == 1
    assert actor.anim_info == -1
    assert actor.new_anim == -1


def test_depth_sort_far_first():
    # FITD sortActorList: farther actors draw first (painter's algorithm)
    from PyAitD.actors import sort_actor_indices
    from PyAitD.game import Actor, Game
    game = Game.__new__(Game)
    game.actors = [Actor(index_in_world=-1) for _ in range(4)]
    game.current_room = 0
    game.actors[1] = Actor(index_in_world=1, body_num=1, zv=[100, 200, 0, 100, 100, 200])
    game.actors[2] = Actor(index_in_world=2, body_num=1, zv=[150, 250, 0, 100, 300, 400])
    # actor 2 is farther from the camera -> must draw FIRST (painter's algorithm)
    assert sort_actor_indices(game, 0, 0, 0) == [2, 1]


def test_depth_sort_y_bands():
    # different y bands: compare translateY - 2000 - y (no XZ overlap logic)
    from PyAitD.actors import sort_actor_indices
    from PyAitD.game import Actor, Game
    game = Game.__new__(Game)
    game.actors = [Actor(index_in_world=-1) for _ in range(4)]
    game.current_room = 0
    game.actors[1] = Actor(index_in_world=1, body_num=1, zv=[0, 10, 0, 10, 0, 10])
    game.actors[2] = Actor(index_in_world=2, body_num=1, zv=[0, 10, 5000, 5010, 0, 10])
    order = sort_actor_indices(game, 0, 0, 0)
    assert len(order) == 2


from PyAitD.__main__ import _is_interactable, resolve_play_click, route_play_click


def _state_for(floor, room_idx, cam_slot):
    # test scaffolding: route_play_click's floor path goes through
    # pick_floor, which builds its own camera state internally, so this
    # has no production caller — it exists only to reproduce a click's
    # screen coordinates for project_floor_point in the test below.
    from PyAitD.world import CameraState
    room = floor.rooms[room_idx]
    camera = floor.cameras[room.camera_indices[cam_slot]]
    return CameraState.from_camera(
        camera, room.world_x, room.world_y, room.world_z,
    ).angles()


def test_a_floor_click_becomes_a_walk_intent(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    hero = game.actors[game.current_camera_target_actor]
    screen = project_floor_point(
        _state_for(floor, hero.room, game.num_camera),
        hero.room_x + 1500, hero.world_y, hero.room_z,
    )
    route_play_click(game, floor, (int(screen[0]), int(screen[1])), [])
    assert game.nav_intent is not None
    assert game.nav_intent.target_object_idx == -1


def test_a_click_on_an_actor_becomes_a_target_intent(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    # the actor must be a valid click target (found-able or touch-scripted);
    # not every actor in the draw list is interactable (e.g. plain scenery).
    other_idx = next(
        i for i, a in enumerate(game.actors)
        if a.index_in_world >= 0 and i != game.current_camera_target_actor
        and _is_interactable(game, i)
    )
    draw_list = [(other_idx, (100, 60, 200, 160))]
    route_play_click(game, floor, (150, 100), draw_list)
    assert game.nav_intent is not None
    assert game.nav_intent.target_object_idx == game.actors[other_idx].index_in_world


def test_a_click_on_nothing_leaves_the_intent_alone(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    route_play_click(game, floor, (2, 2), [])
    assert game.nav_intent is None


def _real_draw_list_entry(game, floor, actor_idx):
    """The (actor, screen bbox) pair _scene_frame would produce, without a
    Renderer: the same skin() call, the same picking.actor_bbox."""
    from PyAitD.picking import actor_bbox
    from PyAitD.skel import skin
    from PyAitD.world import CameraState
    room = floor.rooms[game.current_room]
    camera = floor.cameras[room.camera_indices[game.num_camera]]
    state = CameraState.from_camera(
        camera, room.world_x, room.world_y, room.world_z,
    ).angles()
    actor = game.actors[actor_idx]
    body = game.assets.body(actor.body_num)
    result = skin(
        body, [(0, (0, 0, 0))] * len(body.groups),
        (actor.world_x, actor.world_y, actor.world_z), state,
        actor_angles=(actor.alpha, actor.beta, actor.gamma),
    )
    return (actor_idx, actor_bbox(result))


def test_clicking_floor_zero_s_interactable_walks_there_and_dispatches(data_dir):
    # End to end on the only bootable content: floor 0 has exactly one clickable
    # interactable (actor 10 / world object 13, found_life 9), and its own cell
    # is not walkable — the hard col standing for it plus the 266-unit agent
    # inflation cover it. Aiming at the object's centre makes find_path fail
    # every tick, and the hero grinds into the wall forever (measured: still
    # 875 units short after 6000 ticks). The click must snap to a standing spot
    # instead, so the walk actually finishes and the arrival dispatches.
    from PyAitD.effects import GameMode
    from PyAitD.playworld import play_tick
    from PyAitD.ui import InputBuffer

    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    # the draw list is what a click can hit: only actors with a body are in it
    # (actors.sort_actor_indices skips body_num == -1)
    target_idx = next(
        i for i, a in enumerate(game.actors)
        if a.index_in_world >= 0 and a.body_num != -1
        and i != game.current_camera_target_actor and _is_interactable(game, i)
    )
    entry = _real_draw_list_entry(game, floor, target_idx)
    box = entry[1]
    assert box is not None, "the interactable must be on screen to be clickable"
    click = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)

    route_play_click(game, floor, click, [entry])
    intent = game.nav_intent
    assert intent is not None and intent.target_object_idx == game.actors[target_idx].index_in_world
    target = game.actors[target_idx]
    assert (intent.dest_x, intent.dest_z) != (target.room_x, target.room_z), (
        "the destination must be a standing spot beside the object, not its own "
        "cell, which is never walkable"
    )
    mesh = game.nav_meshes.mesh_for(floor, target.room, agent_extent(game.actors[
        game.current_camera_target_actor]))
    assert mesh.is_walkable(intent.dest_x, intent.dest_z)

    buf = InputBuffer()
    dispatched = False
    for _tick in range(2000):
        play_tick(game, floor, buf)
        if game.mode is not GameMode.PLAY:
            dispatched = True   # a foundable target would open its prompt
            break
        if game.action == 0x2000:
            dispatched = True   # a non-foundable target gets the action bit
            break
        if game.nav_intent is None:
            break
    assert dispatched, "the click never reached a dispatch — the hero is grinding"


def _floor_screen_point(game, floor, dx, dz):
    hero = game.actors[game.current_camera_target_actor]
    return project_floor_point(
        _state_for(floor, hero.room, game.num_camera),
        hero.room_x + dx, hero.world_y, hero.room_z + dz,
    )


def test_a_play_click_is_ignored_in_keyboard_mode(data_dir):
    # Tab hands control back to the tank keys; a click that silently does
    # nothing is worse than no click, so the cursor is hidden in that mode too
    # (run() only renders it in mouse mode) and the resolver refuses outright.
    from PyAitD.effects import InputMode
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    screen = _floor_screen_point(game, floor, 1500, 0)
    click = (int(screen[0]), int(screen[1]))
    assert resolve_play_click(game, floor, click, [])[0] != "blocked", "fixture"

    game.input_mode = InputMode.KEYBOARD
    assert resolve_play_click(game, floor, click, [])[0] == "blocked"
    route_play_click(game, floor, click, [])
    assert game.nav_intent is None


def test_the_cursor_and_the_click_come_from_one_resolution(data_dir):
    # The hover cursor used to resolve the floor with pick_floor (the hero's
    # room only) while the click used pick_floor_any_room, so a neighbouring
    # room's floor drew the red "blocked" X and then walked there anyway. Both
    # now go through resolve_play_click, and this pins the agreement: whatever
    # the cursor shows is exactly what clicking does.
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    points = [(x, y) for x in range(10, 320, 23) for y in range(20, 200, 17)]
    seen = set()
    for point in points:
        kind, args = resolve_play_click(game, floor, point, [])
        seen.add(kind)
        game.nav_intent = None
        route_play_click(game, floor, point, [])
        if kind == "blocked":
            assert game.nav_intent is None, f"{point}: cursor said blocked, click walked"
        else:
            assert game.nav_intent is not None, f"{point}: cursor said {kind}, click did nothing"
            assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == args[:2]
    assert {"walk", "blocked"} <= seen, "the sweep must cover both outcomes"


def test_a_walk_click_always_lands_on_a_walkable_cell(data_dir):
    # the cursor promises "walk", so the destination must really be on the mesh
    from PyAitD.navmesh import agent_extent
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    hero = game.actors[game.current_camera_target_actor]
    mesh = game.nav_meshes.mesh_for(floor, hero.room, agent_extent(hero))
    walks = 0
    for x in range(10, 320, 17):
        for y in range(20, 200, 13):
            kind, args = resolve_play_click(game, floor, (x, y), [])
            if kind != "walk":
                continue
            walks += 1
            assert mesh.is_walkable(args[0], args[1]), f"click at {(x, y)} is not walkable"
    assert walks > 20, "the sweep must actually produce walk clicks"
