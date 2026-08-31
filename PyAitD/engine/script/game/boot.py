# SPDX-License-Identifier: GPL-2.0-only
"""Boot and floor transitions: startGame/initGame/ChangeSalle/floor starts."""
from PyAitD.engine.script.game.state import FloorStart, Game
from PyAitD.engine.script.game.objects import spawn_stage_actors


def change_salle(game, room):
    # ChangeSalle port (M3a subset): current_room = room; num_camera = -1; flag_init_view = 2
    game.current_room = room
    game.num_camera = -1
    game.flag_init_view = 2


def relocate_actor(game, actor_idx, stage, room, x, y, z):
    # setStage coordinate block (life.cpp:306): rebase zv onto the new
    # actual position, move the actor, and zero its per-frame step deltas.
    actor = game.actors[actor_idx]
    actual_x = actor.room_x + actor.step_x
    actual_y = actor.room_y + actor.step_y
    actual_z = actor.room_z + actor.step_z
    actor.zv[0] += x - actual_x
    actor.zv[1] += x - actual_x
    actor.zv[2] += y - actual_y
    actor.zv[3] += y - actual_y
    actor.zv[4] += z - actual_z
    actor.zv[5] += z - actual_z
    actor.stage, actor.room = stage, room
    actor.room_x = actor.world_x = x
    actor.room_y = actor.world_y = y
    actor.room_z = actor.world_z = z
    actor.step_x = actor.step_y = actor.step_z = 0


def enter_floor_start(game, floor_start):
    # the ONE implementation of "immediately be on a floor": used by the
    # debug combat venue, integration tests, the headless proof tool, and
    # restart. No Floor I/O here — the caller owns loading the Floor.
    relocate_actor(
        game, game.current_camera_target_actor,
        floor_start.stage, floor_start.room,
        floor_start.x, floor_start.y, floor_start.z,
    )
    game.current_floor = game.new_num_etage = floor_start.stage
    game.flag_change_etage = 0
    change_salle(game, floor_start.room)
    game.new_num_salle = floor_start.room
    game.new_num_camera = floor_start.camera_slot
    game.flag_init_view = 2
    spawn_stage_actors(game)
    game.flag_genere_aff_list = 0
    game.num_camera = -1


def start_game(game, stage, room):
    # startGame (main.cpp:4134) minus PlayWorld: initVars resets the camera
    # and world targets (main.cpp:1235-1236), LoadEtage(stage), NumCamera=-1,
    # ChangeSalle(room), NewNumCamera=0, FlagInitView=2. The hero is NOT
    # relocated: world data decides which objects live on `stage`. A staged
    # start has no restart point (floor_start) until a script sets one.
    game.current_camera_target_actor = -1
    game.current_world_target = -1
    game.current_floor = game.new_num_etage = stage
    game.flag_change_etage = 0
    change_salle(game, room)
    game.new_num_salle = room
    game.new_num_camera = 0
    game.flag_init_view = 2
    spawn_stage_actors(game)
    game.flag_genere_aff_list = 0
    game.num_camera = -1
    game.floor_start = None


def game_step_tick(game):
    game.timer += 1


def init_game(data_dir, profile, hero=0):
    from PyAitD.engine.script.interaction import sync_player_track_mode  # interaction imports game
    game = Game(data_dir, profile, hero=hero)
    # profile.game_start (games/base.py): the floor/room the playable start
    # boots onto directly -- NOT via start_game, which resets camera/world
    # targets and clears floor_start (see games/base.py's docstring). AITD1's
    # value is (0, 0), matching the hardcode this replaces; a second game
    # with a different attic floor would need only its own profile value.
    game.current_floor, floor_room = profile.game_start
    spawn_stage_actors(game)
    # object data spawns the hero in track mode 1 (tank); the default input mode
    # is the mouse, and mode 1 would eat the follower's mirrored joyd as keyboard
    sync_player_track_mode(game)
    change_salle(game, floor_room)
    game.new_num_camera = 0
    game.flag_init_view = 2
    hero = game.actors[game.current_camera_target_actor]
    game.floor_start = FloorStart(hero.stage, hero.room, hero.room_x, hero.room_y, hero.room_z, 0)
    return game
