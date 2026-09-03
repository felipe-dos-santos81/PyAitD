# SPDX-License-Identifier: GPL-2.0-only
"""The behaviour branch of the tick: what run_life is to a LIFE actor."""
from PyAitD.engine.content.enemies import step_enemy


def run_behaviour(game, slot):
    """Step the behaviour of the BEHAVIOUR_LIFE actor in `slot`. Never
    raises on game state: an actor with no record (only a corrupt save
    could produce one, and validate_snapshot refuses those) is left alone."""
    actor = game.actors[slot]
    content = game.content
    record = None if content is None else content.record_for(actor.index_in_world)
    if record is None:
        return
    state = game.content_state[actor.index_in_world]
    step_enemy(game, slot, record, state)
    if game.trace is not None:
        game.trace.log_behaviour(game, slot, state["phase"])
