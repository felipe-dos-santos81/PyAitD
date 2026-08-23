# SPDX-License-Identifier: GPL-2.0-only
from types import SimpleNamespace

import numpy as np

from maitd.game import init_game
from maitd.life import life_gate


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
    from maitd.playworld import apply_play_input
    from maitd.ui import InputBuffer
    game = init_game(data_dir)
    state = InputBuffer(held_joyd=9, action_held=True)
    apply_play_input(game, state)
    assert game.local_joyd == 9
    assert game.local_click == 1
    assert game.action == 0x2000


def test_run_coalesces_catch_up_ticks_into_one_present_per_frame(monkeypatch, tmp_path):
    import maitd.__main__ as main
    from maitd.effects import GameMode

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
    monkeypatch.setattr(main, "_scene_frame", lambda *args: frame)
    monkeypatch.setattr(main, "render_active_mode", lambda *args: frame)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None)
    )

    game = SimpleNamespace(
        _data_dir=tmp_path, current_floor=0, trace=None, mode=GameMode.PLAY,
        num_camera=-1, new_num_camera=0, flag_init_view=0, current_room=0,
        actors=[],
    )
    assert main.run(game) == 0
    assert calls == ["tick"] * 5 + ["present", "present"]


def test_run_skips_scene_recompute_and_caption_on_transition_frames(monkeypatch, tmp_path):
    # M3a draw_ready gate: a floor/room-change tick leaves num_camera == -1
    # with current_room stale until the next tick's change_salle, so the loop
    # must reuse the previous frame instead of recomputing the scene or
    # indexing floor.rooms[current_room] (IndexError / wrong camera).
    import maitd.__main__ as main
    from maitd.effects import GameMode

    scene_calls = []
    presented = []
    frame = np.zeros((200, 320, 3), dtype=np.uint8)

    def scene_frame(*args):
        scene_calls.append(1)
        return frame

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
        actors=[],
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
    from maitd.actors import gere_anim
    from maitd.formats import Animation, Frame

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
    from maitd.actors import gere_anim
    from maitd.formats import Animation, Frame

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
    from maitd.actors import sort_actor_indices
    from maitd.game import Actor, Game
    game = Game.__new__(Game)
    game.actors = [Actor(index_in_world=-1) for _ in range(4)]
    game.current_room = 0
    game.actors[1] = Actor(index_in_world=1, body_num=1, zv=[100, 200, 0, 100, 100, 200])
    game.actors[2] = Actor(index_in_world=2, body_num=1, zv=[150, 250, 0, 100, 300, 400])
    # actor 2 is farther from the camera -> must draw FIRST (painter's algorithm)
    assert sort_actor_indices(game, 0, 0, 0) == [2, 1]


def test_depth_sort_y_bands():
    # different y bands: compare translateY - 2000 - y (no XZ overlap logic)
    from maitd.actors import sort_actor_indices
    from maitd.game import Actor, Game
    game = Game.__new__(Game)
    game.actors = [Actor(index_in_world=-1) for _ in range(4)]
    game.current_room = 0
    game.actors[1] = Actor(index_in_world=1, body_num=1, zv=[0, 10, 0, 10, 0, 10])
    game.actors[2] = Actor(index_in_world=2, body_num=1, zv=[0, 10, 5000, 5010, 0, 10])
    order = sort_actor_indices(game, 0, 0, 0)
    assert len(order) == 2
