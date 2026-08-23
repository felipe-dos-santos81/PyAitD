# SPDX-License-Identifier: GPL-2.0-only
"""PlayWorld is the simulation tick, importable without pygame or the Renderer."""
import subprocess
import sys

from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.playworld import play_tick
from PyAitD.ui import InputBuffer

# Runs in a fresh interpreter: pytest (and this module, via InputBuffer) has
# pygame loaded in-process, so sys.modules is only meaningful out-of-process.
# A static import walk cannot substitute — it reports pygame reachable through
# interaction.apply_found_result's deferred `from PyAitD.ui import FoundResult`.
_PURITY_PROBE = """
import sys, PyAitD.playworld
# the layer rule, then the third-party names a direct import would pull in
leaked = {"PyAitD.ui", "PyAitD.render", "pygame", "moderngl", "OpenGL"} & sys.modules.keys()
sys.exit(", ".join(sorted(leaked)) or None)
"""


def test_playworld_does_not_import_the_presentation_layer():
    out = subprocess.run([sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True)
    assert out.returncode == 0, (
        f"PyAitD.playworld pulled in {out.stderr.strip()} — the tick must stay "
        f"importable without the presentation layer so it can run headless"
    )


def test_play_tick_advances_the_world_without_a_display(data_dir):
    # No Renderer, no display, and no SDL_VIDEODRIVER needed. Constructing the
    # InputBuffer still imports pygame: it is a pygame-free dataclass that lives
    # in ui.py, whose module scope evaluates pygame.K_* and pygame.Rect.
    game = init_game(data_dir, hero=0)
    floor = Floor(data_dir, game.current_floor)
    buf = InputBuffer()
    start = game.timer
    for _ in range(60):
        play_tick(game, floor, buf)
    assert game.timer > start
    assert game.flag_game_over == 0


from PyAitD.effects import GameMode, InputMode, NavIntent
from PyAitD.navmesh import agent_extent
from PyAitD.playworld import apply_play_input


def test_keyboard_mode_still_reads_the_input_buffer(data_dir):
    game = init_game(data_dir, hero=0)
    game.input_mode = InputMode.KEYBOARD
    buf = InputBuffer()
    buf.held_joyd = 5
    buf.action_held = True
    apply_play_input(game, buf)
    assert game.local_joyd == 5
    assert game.action == 0x2000
    assert game.nav_decision is None


def test_mouse_mode_ignores_the_keyboard_buffer(data_dir):
    game = init_game(data_dir, hero=0)
    buf = InputBuffer()
    buf.held_joyd = 5
    apply_play_input(game, buf)
    assert game.local_joyd == 0, "mouse mode must not read held keys"


def test_mouse_mode_mirrors_the_follower_joystick(data_dir):
    game = init_game(data_dir, hero=0)
    # apply_play_input is called directly here (not through play_tick), so the
    # Floor that _apply_mouse_input's mesh build needs must be stashed by hand
    # — play_tick normally does this at the top of every tick.
    game.current_floor_data = Floor(data_dir, game.current_floor)
    hero = game.actors[game.current_camera_target_actor]
    game.nav_intent = NavIntent(
        dest_x=hero.room_x, dest_z=hero.room_z + 9000, room=hero.room,
        waypoints=[(hero.room_x, hero.room_z + 9000)],
    )
    apply_play_input(game, InputBuffer())
    assert game.nav_decision is not None
    assert game.local_joyd & 1, "scripts reading evalVar 0x13 must see movement"


def test_hero_walks_to_a_clicked_destination_and_arrives(data_dir):
    from PyAitD.navigate import ARRIVE_DISTANCE
    from PyAitD.realvalue import give_distance_2d

    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    hero = game.actors[game.current_camera_target_actor]
    # Deliberately NOT set here. Object data spawns the hero in track mode 1
    # (tank), and mouse is the default input mode: if init_game does not put the
    # hero into the follower's mode 4, process_track hands the follower's
    # mirrored joyd to _process_track_manual, which reads it as *keyboard*
    # input. The hero then walks a long way in the wrong direction — which is
    # why this test asserts where it ended up, not merely that it moved.
    assert hero.track_mode == 4, "init_game left the hero in tank mode"
    mesh = game.nav_meshes.mesh_for(floor, hero.room, agent_extent(hero))
    goal = mesh.center_of(100, 45)   # walkable, and clear of room 0's two sce_zones
    assert mesh.is_walkable(*goal), "the fixture goal must be on the mesh"
    assert not any(
        zone.x1 <= goal[0] <= zone.x2 and zone.z1 <= goal[1] <= zone.z2
        for zone in floor.rooms[hero.room].sce_zones
    ), "the goal must not be a trigger/transition zone"
    start = (hero.room_x, hero.room_z)
    game.nav_intent = NavIntent(goal[0], goal[1], hero.room)
    buf = InputBuffer()
    joyd_seen = 0
    for tick in range(600):
        # play_tick returns False whenever a LIFE script suspends mid-tick
        # (e.g. a background actor's own message op) — that is a normal
        # "the tick did not finish, call me again" signal, not game-over;
        # test_play_tick_advances_the_world_without_a_display already relies
        # on this by ignoring the return value outright. Treating a bare
        # False as a hard stop aborted this loop after tick 0, before the
        # hero had moved at all — game.mode is the real stop signal.
        play_tick(game, floor, buf)
        if game.mode is not GameMode.PLAY:
            break
        joyd_seen |= game.local_joyd
        # hero.track_mode is owned by the hero's LIFE script (LM_DO_MOVE ->
        # process_track dispatches on it); apply_play_input re-asserts the
        # follower mode every tick, so this must hold all the way through.
        assert hero.track_mode == 4, "the hero fell out of mouse-follow mode"
        if game.nav_intent is None:
            break
    assert game.nav_intent is None, "the hero never reached the destination"
    assert joyd_seen & 1, "scripts reading evalVar 0x13 must have seen movement"
    here = (hero.room_x + hero.step_x, hero.room_z + hero.step_z)
    assert give_distance_2d(*here, *goal) < ARRIVE_DISTANCE, (
        f"stopped at {here}, not at the goal {goal} "
        f"(started at {start})"
    )
    assert hero.room == 0, "the walk must not have left the room"
    assert game.action == 0, "a bare floor walk does not press the action button"
