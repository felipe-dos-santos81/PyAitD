# SPDX-License-Identifier: GPL-2.0-only
"""PlayWorld simulation tick (FITD mainLoop.cpp:41-281 order).

Imports no pygame, ModernGL or Renderer, so one 50 Hz logic step can be
advanced without a window. Callers still reach `ui.py` for an InputBuffer;
freeing that needs InputBuffer moved out of the presentation layer.
"""
from PyAitD.engine.script.effects import GameMode, LifeFrame
from PyAitD.engine.script.game import change_salle, game_step_tick
from PyAitD.engine.script.interaction import (
    advance_messages, dispatch_nav_arrival, drain_immediate_effects, execute_found_life,
    run_life,
)
from PyAitD.engine.script.life import life_gate
from PyAitD.engine.script.playworld.input import apply_play_input
from PyAitD.engine.script.playworld.passes import (
    _anim_pass, _camera_switch, _genere_active_list, _handoff_game_over,
)

TICK_MS = 20  # 50 Hz logic tick
NATIVE_ACTION = 0x2000  # mainLoop.cpp:87-101 held-action input
# Melee animation 41 reaches its strike frame well inside this; the budget
# only exists so a LIFE that never returns the hero to idle cannot leave the
# mouse holding a virtual button for the rest of the session.
MOUSE_ATTACK_TICK_BUDGET = 100


def play_tick(game, floor, input_buffer):
    # mainLoop.cpp:41-281 PlayWorld, one 50Hz iteration, PLAY mode only.
    # Rendering stays outside this fixed-step function so catch-up ticks
    # cannot block input behind repeated GPU work.
    if game.mode is not GameMode.PLAY:
        return False
    if game.flag_game_over and not _handoff_game_over(game):
        # A LIFE frame suspended on a modal is resumed by interaction.resume_life
        # when that modal closes, outside this function: the real death sequence
        # (LISTLIFE 554) is LM_PICTURE immediately followed by LM_GAME_OVER, so
        # the flag is raised long after the raising tick's LIFE loop finished.
        # FITD never sees a pending flag -- its LM_PICTURE blocks inside
        # processLife, so LM_GAME_OVER lands in the same pass mainLoop.cpp:185
        # checks. Consume it before this tick re-runs that LIFE, which would
        # suspend on the picture again and strand the flag forever.
        return False
    game.current_floor_data = floor   # the mesh cache needs the loaded Floor
    apply_play_input(game, input_buffer)
    if not dispatch_nav_arrival(game):
        return False
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
    if not _handoff_game_over(game):
        return False
    if game.flag_change_etage:
        # LoadEtage M3a subset (floor.cpp:7): floor data swap happens in run().
        # LoadEtage raises FlagChangeSalle (floor.cpp:40) and mainLoop consumes
        # it in the same iteration (mainLoop.cpp:189-199), so the room change
        # lands here rather than a tick later.
        game.current_floor = game.new_num_etage
        game.flag_change_etage = 0
        change_salle(game, game.new_num_salle)
        game.flag_change_salle = 0
        # FITD then `continue`s past GenereActiveList, so its next iteration
        # runs the anim pass over the previous floor's actors and only
        # regenerates at the end of it (mainLoop.cpp:249) -- C++ tolerates the
        # out-of-range roomDataTable read that produces, Python raises
        # IndexError. Raise the port's existing spawn request instead, so the
        # one spawn gate regenerates the list here, before any pass indexes the
        # new floor's rooms.
        game.flag_genere_aff_list = 1
        _genere_active_list(game)
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
    _genere_active_list(game)
    advance_messages(game)
    return True
