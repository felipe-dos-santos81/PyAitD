# SPDX-License-Identifier: GPL-2.0-only
"""evalVar port (FITD evalVar.cpp:148, AITD1 path). Owner = life owner actor."""
from PyAitD.engine.script.life import read_s16
from PyAitD.engine.space.realvalue import eval_chrono
from PyAitD.engine.space.world import adjust_zv_between_rooms


def _world_idx(game, slot):
    return -1 if slot == -1 else game.actors[slot].index_in_world


def calc_dist(x1, y1, z1, x2, y2, z2):
    return abs(x1 - x2) + abs(y1 - y2) + abs(z1 - z2)


_GET_POS_REL_TABLE = (4, 1, 8, 2, 4, 1, 8, 0)


def get_pos_rel(game, actor1, actor2):
    # FITD evalVar.cpp:22-95 port
    beta1 = actor1.beta
    counter = 3
    if 0x80 <= beta1 < 0x180:
        counter = 2
    if 0x180 <= beta1 < 0x280:
        counter = 1
    if 0x280 <= beta1 < 0x380:
        counter = 0
    zv = list(actor2.zv)
    if actor1.room != actor2.room:
        _adjust_zv(game, zv, actor2.room, actor1.room)
    center_x = int((zv[0] + zv[1]) / 2)
    center_z = int((zv[4] + zv[5]) / 2)
    if actor1.zv[5] >= center_z and actor1.zv[4] <= center_z:
        if actor1.zv[1] < center_x:
            counter += 1
        else:
            if actor1.zv[0] <= center_x:
                return 0
            counter += 3
    else:
        if actor1.zv[1] >= center_x or actor1.zv[0] <= center_x:
            if actor1.zv[5] < center_z:
                counter += 2
            else:
                if actor1.zv[4] <= center_z:
                    return 0
        else:
            return 0
    return _GET_POS_REL_TABLE[counter]


def _adjust_zv(game, zv, from_room, to_room):
    # FITD AdjustZV (main.cpp:3222), in place
    zv[:] = adjust_zv_between_rooms(game, zv, from_room, to_room)


def _other_object_property(game, vm, tag, widx, world):
    raw_tag = tag & 0x7FFF
    code = raw_tag - 1
    if world.obj_index != -1:
        return _prop(game, game.actors[world.obj_index], code, vm)
    if code == 0x1E:
        return world.room
    if code == 0x25:
        return world.stage
    raise ValueError(
        f"evalVar: raw tag 0x{raw_tag:04X} on out-of-floor object {widx}; "
        "FITD asserts for this property"
    )


def _prop(game, a, code, vm):
    if code == 0x00:
        return _world_idx(game, a.col[0])
    if code == 0x01:
        return a.hard_dec
    if code == 0x02:
        return a.hard_col
    if code == 0x03:
        return _world_idx(game, a.hit)
    if code == 0x04:
        return _world_idx(game, a.hit_by)
    if code == 0x05:
        return a.anim
    if code == 0x06:
        return a.flag_end_anim
    if code == 0x07:
        return a.frame
    if code == 0x08:
        return a.end_frame
    if code == 0x09:
        return a.body_num
    if code == 0x0A:
        return a.mark
    if code == 0x0B:
        return a.track_number
    if code == 0x0C:
        return int(eval_chrono(a.chrono, game.timer) / 60)
    if code == 0x0D:
        return int(eval_chrono(a.room_chrono, game.timer) / 60)
    if code == 0x0E:
        widx = read_s16(vm)
        w = game.world_objects[widx]
        if w.obj_index == -1:
            return 32000
        b = game.actors[w.obj_index]
        return calc_dist(a.world_x, a.world_y, a.world_z, b.world_x, b.world_y, b.world_z)
    if code == 0x0F:
        return _world_idx(game, a.col_by)
    if code == 0x10:
        widx = eval_var(vm)  # nested!
        return 1 if game.world_objects[widx].found_flag & 0x8000 else 0
    if code == 0x11:
        return game.action
    if code == 0x12:
        widx = read_s16(vm)
        w = game.world_objects[widx]
        if w.obj_index == -1:
            return 0
        return get_pos_rel(game, a, game.actors[w.obj_index])
    if code == 0x13:
        j = game.local_joyd
        if j & 4:
            return 4
        if j & 8:
            return 8
        if j & 1:
            return 1
        if j & 2:
            return 2
        return 0
    if code == 0x14:
        return game.local_click
    if code == 0x15:
        t = a.col[0] if a.col[0] != -1 else a.col_by
        return _world_idx(game, t) if t != -1 else -1
    if code == 0x16:
        return a.alpha
    if code == 0x17:
        return a.beta
    if code == 0x18:
        return a.gamma
    if code == 0x19:
        return game.in_hand_table[game.current_inventory]
    if code == 0x1A:
        return a.hit_force
    if code == 0x1B:
        # FITD: *(u16*)(((NumCamera+6)*2)+cameraPtr) — cameraIdxTable[NumCamera]
        return game.camera_param(game.num_camera)
    if code == 0x1C:
        n = read_s16(vm)
        return game.rng.randrange(n)
    if code == 0x1D:
        return a.falling
    if code == 0x1E:
        return a.room
    if code == 0x1F:
        return a.life
    if code == 0x20:
        widx = read_s16(vm)
        return 1 if game.world_objects[widx].found_flag & 0xC000 else 0
    if code == 0x21:
        return a.room_y
    if code == 0x22:
        read_s16(vm)
        read_s16(vm)
        return 0  # M3a stub: TEST_ZV_END_ANIM (M3c)
    if code == 0x23:
        return game.current_music
    if code == 0x24:
        return game.cvars[read_s16(vm)]
    if code == 0x25:
        return a.stage
    if code == 0x26:
        widx = read_s16(vm)
        return 1 if game.world_objects[widx].found_flag & 0x1000 else 0
    raise ValueError(f"evalVar: unknown property code {code} (FITD asserts here)")


def eval_var(vm):
    tag = read_s16(vm)
    game = vm.game
    if tag == -1:
        return read_s16(vm)
    if tag == 0:
        return game.vars[read_s16(vm)]
    if tag & 0x8000:
        widx = read_s16(vm)
        if not 0 <= widx < len(game.world_objects):
            raise ValueError(
                f"evalVar: world object index {widx} out of range 0..{len(game.world_objects) - 1} "
                f"(life owner actor {vm.owner_idx}, byte {vm.pc - 4})"
            )
        w = game.world_objects[widx]
        return _other_object_property(game, vm, tag, widx, w)
    return _prop(game, vm.owner, tag - 1, vm)
