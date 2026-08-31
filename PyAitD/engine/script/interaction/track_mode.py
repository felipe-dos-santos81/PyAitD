# SPDX-License-Identifier: GPL-2.0-only
"""Player track-mode sync between input modes."""
from PyAitD.engine.script.effects import InputMode


def player_track_mode(input_mode, modes):
    """The track mode that means 'the player drives this actor', per input mode.

    `modes` is the profile's player_track_modes, (keyboard, mouse) order.
    """
    return modes[1] if input_mode is InputMode.MOUSE else modes[0]


def sync_player_track_mode(game):
    """Keep the hero's manual-control mode in step with the input mode.

    Mouse mode is useless unless the hero is actually in mode 4: mode 1 would
    consume the follower's mirrored joyd as if it were the keyboard, which is
    the autopilot-driving-a-tank approach the spec rejected. Object data spawns
    the hero in mode 1 (game.spawn_stage_actors -> tracks.init_deplacement), so
    init_game and every input snapshot re-assert this.

    The translation is deliberately conditional, between the profile's two
    player track modes only: a script that parks the hero on a scripted track
    (mode 2/3) or freezes it (mode 0) keeps what it asked for, so cutscenes
    are unaffected. It is re-asserted rather than set once because
    LM_INIT_DEPLACEMENT can put the hero back in mode 1 at any time, and a
    one-shot at init would silently lose the mouse there.
    """
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1:
        return
    hero = game.actors[hero_idx]
    modes = game.profile.player_track_modes
    wanted = player_track_mode(game.input_mode, modes)
    if hero.track_mode in modes and hero.track_mode != wanted:
        hero.track_mode = wanted
