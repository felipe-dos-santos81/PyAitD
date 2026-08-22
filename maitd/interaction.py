# SPDX-License-Identifier: GPL-2.0-only
from maitd.effects import AfterLife, LifeFrame
from maitd.life import process_life


def _release_temporary_actor(game, actor_idx):
    if actor_idx != -1:
        game.actors[actor_idx].index_in_world = -1


def _complete_after_life(game, frame):
    _release_temporary_actor(game, frame.release_actor_idx)
    if frame.after is AfterLife.FINISH_TAKE:
        _finish_take(game, frame.subject_idx)


def run_life(game, frame):
    pending = process_life(
        game, frame.owner_idx, frame.life_num, pc=frame.pc, after=frame.after,
        subject_idx=frame.subject_idx, release_actor_idx=frame.release_actor_idx,
    )
    if pending is not None:
        game.life_stack.append(pending)
        return False
    _complete_after_life(game, frame)
    return True


def resume_life(game):
    while game.life_stack and game.active_modal is None:
        frame = game.life_stack.pop()
        if not run_life(game, frame):
            return False
    return game.active_modal is None


def execute_found_life(game, object_idx, *, after=AfterLife.NONE):
    if object_idx == -1:
        return True
    world = game.world_objects[object_idx]
    if world.found_life == -1:
        if after is AfterLife.FINISH_TAKE:
            _finish_take(game, object_idx)
        return True
    release_actor_idx = -1
    actor_idx = world.obj_index
    if actor_idx == -1:
        actor_idx = next(
            (i for i in range(len(game.actors) - 1, -1, -1)
             if game.actors[i].index_in_world == -1),
            len(game.actors) - 1,
        )
        actor = game.actors[actor_idx]
        actor.index_in_world = object_idx
        actor.life = actor.body_num = actor.room = actor.life_mode = actor.anim = -1
        actor.object_type = 0
        actor.track_mode = -1
        release_actor_idx = actor_idx
    return run_life(game, LifeFrame(
        actor_idx, world.found_life, after=after, subject_idx=object_idx,
        release_actor_idx=release_actor_idx,
    ))
