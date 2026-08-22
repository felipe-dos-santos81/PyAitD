# SPDX-License-Identifier: GPL-2.0-only
"""Game state: CVars, script vars, world objects, actor table (FITD main.cpp ports)."""
from dataclasses import dataclass, field
from itertools import product

from maitd.assets import Assets
from maitd.cos_table import COS_TABLE
from maitd.floor import Floor
from maitd.formats import parse_defines, parse_objets, parse_vars

NUM_MAX_OBJECT = 128

AF_ANIMATED = 0x0001
AF_DRAWABLE = 0x0004
AF_BOXIFY = 0x0008
AF_SPECIAL = 0x0020
AF_TRIGGER = 0x0040
AF_FOUNDABLE = 0x0080
AF_MASK = AF_ANIMATED + 0x10 + AF_TRIGGER + AF_FOUNDABLE + 0x100 + 0x400

AITD1_CVAR_NAMES = (
    "SAMPLE_PAGE", "BODY_FLAMME", "MAX_WEIGHT_LOADABLE", "TEXTE_CREDITS",
    "SAMPLE_TONNERRE", "INTRO_DETECTIVE", "INTRO_HERITIERE", "WORLD_NUM_PERSO",
    "CHOOSE_PERSO", "SAMPLE_CHOC", "SAMPLE_PLOUF", "REVERSE_OBJECT",
    "KILLED_SORCERER", "LIGHT_OBJECT", "FOG_FLAG", "DEAD_PERSO",
)

FOG_FLAG = AITD1_CVAR_NAMES.index("FOG_FLAG")


@dataclass
class RealValue:
    start_value: int = 0
    end_value: int = 0
    num_steps: int = 0
    memo_ticks: int = 0


@dataclass
class Actor:
    index_in_world: int = -1
    body_num: int = 0
    object_type: int = 0
    dyn_flags: int = 0
    zv: list = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    room_x: int = 0
    room_y: int = 0
    room_z: int = 0
    world_x: int = 0
    world_y: int = 0
    world_z: int = 0
    alpha: int = 0
    beta: int = 0
    gamma: int = 0
    chrono: int = 0
    room_chrono: int = 0
    anim: int = -1
    anim_type: int = 0
    anim_info: int = 0
    new_anim: int = -1
    new_anim_type: int = 0
    new_anim_info: int = 0
    frame: int = 0
    num_of_frames: int = 0
    end_frame: int = 0
    flag_end_anim: int = 0
    track_mode: int = 0
    track_number: int = 0
    mark: int = -1
    position_in_track: int = 0
    step_x: int = 0
    step_y: int = 0
    step_z: int = 0
    y_handler: RealValue = field(default_factory=RealValue)
    falling: int = 0
    rotate: RealValue = field(default_factory=RealValue)
    direction: int = 0
    speed: int = 0
    speed_change: RealValue = field(default_factory=RealValue)
    anim_neg_x: int = 0
    anim_neg_y: int = 0
    anim_neg_z: int = 0
    col: list = field(default_factory=lambda: [-1, -1, -1])
    col_by: int = -1
    hard_dec: int = -1
    hard_col: int = -1
    hit: int = -1
    hit_by: int = -1
    anim_action_type: int = 0
    anim_action_anim: int = -1
    anim_action_frame: int = 0
    anim_action_param: int = 0
    hit_force: int = 0
    hot_point_id: int = -1
    hot_point: list = field(default_factory=lambda: [0, 0, 0])
    stage: int = 0
    room: int = 0
    life: int = -1
    life_mode: int = -1


class Game:
    def __init__(self, data_dir, hero=0):
        self._data_dir = data_dir
        self._rooms_by_floor = {}
        self.assets = Assets(data_dir)
        self.world_objects = parse_objets((data_dir / "OBJETS.ITD").read_bytes())
        self.actors = [Actor() for _ in range(NUM_MAX_OBJECT)]
        self.cvars = parse_defines((data_dir / "DEFINES.ITD").read_bytes())
        self.cvars[8] = hero  # CHOOSE_PERSO (startGame backs up and restores it)
        self.vars = parse_vars((data_dir / "VARS.ITD").read_bytes())
        self.timer = 0
        self._last_time_forward = 0  # FITD lastTimeForward static (track.cpp:151)
        # input snapshot
        self.local_joyd = 0
        self.local_key = 0
        self.local_click = 0
        self.action = 0
        # play loop state (M3a): LIFE trace sink + per-actor anim players
        self.trace = None
        self.anim_players = {}
        # world / camera state
        self.current_floor = 0
        self.current_room = 0
        self.current_stage = 0
        self.num_camera = -1
        self.new_num_camera = 0
        self.current_camera_target_actor = -1
        self.current_world_target = self.cvars[7]
        self.flag_change_etage = 0
        self.new_num_etage = 0
        self.flag_change_salle = 0
        self.new_num_salle = 0
        self.flag_init_view = 2
        self.flag_game_over = 0
        self.flag_genere_aff_list = 1
        self.hard_clip = [32000, -32000, 32000, -32000, 32000, -32000]
        # M3b/M4 stubs (audio, inventory)
        self.in_hand_table = [-1] * 256
        self.current_inventory = 0
        self.status_screen_allowed = 1
        self.current_music = -1
        self.next_music = -1
        self.light_off = 0
        self.last_sample = -1
        self.next_sample = -1
        self.last_priority = -1

    def rooms_of_floor(self, floor_number):
        # roomDataTable port: global room indices, entry per room in the ETAGE pak
        if floor_number not in self._rooms_by_floor:
            self._rooms_by_floor[floor_number] = Floor(self._data_dir, floor_number).rooms
        return self._rooms_by_floor[floor_number]

    def camera_param(self, slot):
        # evalVar 0x1B: *(u16*)(((NumCamera+6)*2)+cameraPtr) — the room def's
        # u16 camera index table starts at byte 12 (roomDefStruct header is
        # 6 u16s); slot -1 reads numCameraInRoom (byte 10).
        room = self.rooms_of_floor(self.current_floor)[self.current_room]
        if slot == -1:
            return len(room.camera_indices)
        return room.camera_indices[slot]


def _cdiv(a, b):
    # C integer division: truncation toward zero
    return a // b if a >= 0 else -((-a) // b)


def joyd_from_keys(up=False, down=False, left=False, right=False):
    # FITD JoyD bit mapping: UP=1, DOWN=2, LEFT=4, RIGHT=8
    joyd = 0
    if up:
        joyd |= 1
    if down:
        joyd |= 2
    if left:
        joyd |= 4
    if right:
        joyd |= 8
    return joyd


def _zv_default():
    return [-100, 100, -2000, 0, -100, 100]


def _zv_max(body_zv):
    # getZvMax: widest square footprint from body ZV (X/Z centered, Y kept)
    x1, x2, y1, y2, z1, z2 = body_zv
    x2 = -x1 + x2
    z2 = -z1 + z2
    if x2 < z2:
        x2 = z2
    x2 = _cdiv(x2, 2)
    return [-x2, x2, y1, y2, -x2, x2]


def _zv_cube(body_zv):
    # getZvCube: cube footprint from body ZV (X/Z centered, Y kept)
    x1, x2, y1, y2, z1, z2 = body_zv
    z2 = x2 = _cdiv(x2 + z2, 2)
    return [-z2, x2, y1, y2, -z2, z2]


def _point_rotate(x, y, z, cx, sx, cy, sy, cz, sz):
    # FITD pointRotate: fixed-point rotation Z then Y then X (>>16 arithmetic, <<1)
    temp_x, temp_y = x, y
    x = (((temp_x * sz - temp_y * cz) >> 16) << 1)
    y = (((temp_x * cz + temp_y * sz) >> 16) << 1)
    temp_x, temp_z = x, z
    x = (((temp_x * sy - temp_z * cy) >> 16) << 1)
    z = (((temp_x * cy + temp_z * sy) >> 16) << 1)
    temp_y, temp_z = y, z
    y = (((temp_y * sx - temp_z * cx) >> 16) << 1)
    z = (((temp_y * cx + temp_z * sx) >> 16) << 1)
    return x, y, z


def _zv_rot(body_zv, alpha, beta, gamma):
    # getZvRot: bounding box of the 8 rotated ZV corners (FITD getZvRot port)
    x1, x2, y1, y2, z1, z2 = body_zv
    if not (alpha or beta or gamma):
        return list(body_zv)
    a = alpha & 0x3FF
    b = beta & 0x3FF
    g = gamma & 0x3FF
    cx = COS_TABLE[a]
    sx = COS_TABLE[(a + 0x100) & 0x3FF]
    cy = COS_TABLE[b]
    sy = COS_TABLE[(b + 0x100) & 0x3FF]
    cz = COS_TABLE[g]
    sz = COS_TABLE[(g + 0x100) & 0x3FF]
    min_x = min_y = min_z = 32000
    max_x = max_y = max_z = -32000
    for px, py, pz in product((x1, x2), (y1, y2), (z1, z2)):
        rx, ry, rz = _point_rotate(px, py, pz, cx, sx, cy, sy, cz, sz)
        min_x = min(min_x, rx)
        max_x = max(max_x, rx)
        min_y = min(min_y, ry)
        max_y = max(max_y, ry)
        min_z = min(min_z, rz)
        max_z = max(max_z, rz)
    return [min_x, max_x, min_y, max_y, min_z, max_z]


def _hard_zv(game, room, hard_zv_idx):
    # type_zv == 4: ZV from room hard col entry (type == 9, parameter == hardZvIdx)
    for col in game.rooms_of_floor(game.current_floor)[room].hard_cols:
        if col.type == 9 and col.parameter == hard_zv_idx:
            return [col.x1, col.x2, col.y1, col.y2, col.z1, col.z2]
    return None


def add_actor(game, world_idx):
    # InitObjet port (object.cpp:3): copies tWorldObject -> tObject slot.
    # Returns the actor slot idx or -1.
    obj = game.world_objects[world_idx]
    slot = next((i for i, a in enumerate(game.actors) if a.index_in_world == -1), -1)
    if slot == -1:
        return -1
    actor = game.actors[slot]

    actor.body_num = obj.body
    actor.object_type = obj.flags & ~AF_SPECIAL
    actor.stage = obj.stage
    actor.room = obj.room
    actor.world_x = actor.room_x = obj.x
    actor.world_y = actor.room_y = obj.y
    actor.world_z = actor.room_z = obj.z

    x, y, z = obj.x, obj.y, obj.z
    if obj.type_zv == 4:
        zv = _hard_zv(game, obj.room, obj.found_name)
        if zv is not None:
            # hard zv: coords are the ZV midpoints (object.cpp:209)
            x = y = z = 0
            actor.world_x = actor.room_x = _cdiv(zv[0], 2) + _cdiv(zv[1], 2)
            actor.world_y = actor.room_y = _cdiv(zv[2], 2) + _cdiv(zv[3], 2)
            actor.world_z = actor.room_z = _cdiv(zv[4], 2) + _cdiv(zv[5], 2)
        else:
            zv = _zv_default()
    elif obj.body == -1:
        zv = _zv_default()
    else:
        body_zv = game.assets.body(obj.body).zv
        if obj.type_zv == 0:
            zv = _zv_max(body_zv)
        elif obj.type_zv == 1:
            zv = list(body_zv)
        elif obj.type_zv == 2:
            zv = _zv_cube(body_zv)
        elif obj.type_zv == 3:
            zv = _zv_rot(body_zv, obj.alpha, obj.beta, obj.gamma)
        else:
            zv = _zv_default()

    if obj.room != game.current_room:
        rooms = game.rooms_of_floor(game.current_floor)
        cur, act = rooms[game.current_room], rooms[obj.room]
        actor.world_x -= (cur.world_x - act.world_x) * 10
        actor.world_y += (cur.world_y - act.world_y) * 10
        actor.world_z += (cur.world_z - act.world_z) * 10

    actor.alpha = obj.alpha
    actor.beta = obj.beta
    actor.gamma = obj.gamma

    actor.dyn_flags = 1

    actor.anim = obj.anim
    actor.frame = obj.frame
    actor.anim_type = obj.anim_type
    actor.anim_info = obj.anim_info

    actor.end_frame = 1
    actor.flag_end_anim = 1
    actor.new_anim = -1
    actor.new_anim_type = 0
    actor.new_anim_info = -1

    actor.step_x = 0
    actor.step_y = 0
    actor.step_z = 0
    actor.anim_neg_x = 0
    actor.anim_neg_y = 0
    actor.anim_neg_z = 0
    actor.speed_change = RealValue()

    actor.col = [-1, -1, -1]
    actor.col_by = -1
    actor.hard_dec = -1
    actor.hard_col = -1

    actor.rotate = RealValue()
    actor.y_handler = RealValue()

    actor.falling = 0
    actor.direction = 0
    actor.speed = 0

    actor.track_mode = 0
    actor.track_number = -1

    actor.anim_action_type = 0
    actor.hit = -1
    actor.hit_by = -1

    if obj.body != -1:
        if obj.anim != -1:
            actor.num_of_frames = game.assets.anim(obj.anim).num_frames
            actor.flag_end_anim = 0
            actor.object_type |= AF_ANIMATED
        elif not (actor.object_type & AF_DRAWABLE):
            actor.object_type &= ~AF_ANIMATED  # do not animate an invisible object

    actor.zv = [zv[0] + x, zv[1] + x, zv[2] + y, zv[3] + y, zv[4] + z, zv[5] + z]

    return slot


def _init_deplacement(actor, track_mode, track_number):
    # InitDeplacement port (main.cpp:1791)
    actor.track_mode = track_mode
    if track_mode == 2:
        actor.track_number = track_number
        actor.mark = -1
    elif track_mode == 3:
        actor.track_number = track_number
        actor.position_in_track = 0
        actor.mark = -1


def _delete_objet(game, index):
    # DeleteObjet port (main.cpp:1663)
    actor = game.actors[index]
    if actor.index_in_world == -2:  # flow
        actor.index_in_world = -1
        if actor.anim == 4:
            game.cvars[FOG_FLAG] = 0
        return
    if actor.index_in_world >= 0:
        obj = game.world_objects[actor.index_in_world]
        obj.obj_index = -1
        actor.index_in_world = -1
        obj.body = actor.body_num
        obj.anim = actor.anim
        obj.frame = actor.frame
        obj.anim_type = actor.anim_type
        obj.anim_info = actor.anim_info
        obj.flags = actor.object_type & ~AF_BOXIFY
        obj.flags |= AF_SPECIAL * actor.dyn_flags
        obj.life = actor.life
        obj.life_mode = actor.life_mode
        obj.track_mode = actor.track_mode
        if obj.track_mode:
            obj.track_number = actor.track_number
            obj.position_in_track = actor.position_in_track
        obj.x = actor.room_x + actor.step_x
        obj.y = actor.room_y + actor.step_y
        obj.z = actor.room_z + actor.step_z
        obj.alpha = actor.alpha
        obj.beta = actor.beta
        obj.gamma = actor.gamma
        obj.stage = actor.stage
        obj.room = actor.room
        game.flag_genere_aff_list = 1


def delete_object(game, obj_idx):
    # deleteObject port (main.cpp:2372): AITD1 delete opcode
    obj = game.world_objects[obj_idx]
    actor_idx = obj.obj_index
    if actor_idx != -1:
        actor = game.actors[actor_idx]
        actor.room = -1
        actor.stage = -1
        actor.index_in_world = -1
    obj.obj_index = -1
    obj.room = -1
    obj.stage = -1
    # DeleteInventoryObjet: M3b inventory removal skipped


def put_at_objet(game, obj_idx, obj_idx_to_put_at):
    # PutAtObjet port (main.cpp:3948)
    obj = game.world_objects[obj_idx]
    put_at = game.world_objects[obj_idx_to_put_at]
    if put_at.obj_index != -1:
        src = game.actors[put_at.obj_index]
        x, y, z = src.room_x, src.room_y, src.room_z
        room, stage = src.room, src.stage
        alpha, beta, gamma = src.alpha, src.beta, src.gamma
    else:
        x, y, z = put_at.x, put_at.y, put_at.z
        room, stage = put_at.room, put_at.stage
        alpha, beta, gamma = put_at.alpha, put_at.beta, put_at.gamma
    if obj.obj_index == -1:
        obj.x, obj.y, obj.z = x, y, z
        obj.room, obj.stage = room, stage
        obj.alpha, obj.beta, obj.gamma = alpha, beta, gamma
        obj.found_flag |= 0x4000
        obj.flags |= 0x80
    else:
        a = game.actors[obj.obj_index]
        a.room_x, a.room_y, a.room_z = x, y, z
        a.room, a.stage = room, stage
        a.alpha, a.beta, a.gamma = alpha, beta, gamma
        game.world_objects[a.index_in_world].found_flag |= 0x4000
        game.world_objects[a.index_in_world].flags |= 0x80
    # DeleteInventoryObjet: M3b inventory removal skipped


def spawn_stage_actors(game):
    # GenereActiveList port (main.cpp:1990-2130)
    for i, actor in enumerate(game.actors):
        if actor.index_in_world == -1:
            continue
        if actor.stage == game.current_floor:
            if actor.life != -1:
                if actor.life_mode == 0:
                    continue  # STAGE: keep
                if actor.life_mode == 1 and actor.room == game.current_room:
                    continue  # ROOM: keep
                # ponytail: life_mode 2 keeps (FITD: isInViewList with the
                # selected camera) — needs camera state, M4+
                if actor.life_mode == 2:
                    continue
                # default (incl life_mode == -1): delete
            else:
                # ponytail: life == -1 keeps (FITD: isInViewList), M4+
                continue
        _delete_objet(game, i)

    for i, obj in enumerate(game.world_objects):
        if obj.obj_index != -1:
            if game.current_world_target == i:
                game.current_camera_target_actor = obj.obj_index
            continue
        if obj.stage != game.current_floor:
            continue
        if obj.life != -1:
            if obj.life_mode == -1:
                continue
            if obj.life_mode == 1 and obj.room != game.current_room:
                continue
            # ponytail: life_mode 2 passes unconditionally (FITD: isInViewList), M4+
        # ponytail: life == -1 passes unconditionally (FITD: isInViewList), M4+

        obj.obj_index = add_actor(game, i)
        if obj.obj_index != -1:
            actor = game.actors[obj.obj_index]
            if game.current_world_target == i:
                game.current_camera_target_actor = obj.obj_index
            actor.dyn_flags = (obj.flags & 0x20) // 0x20  # recheck
            actor.life = obj.life
            actor.life_mode = obj.life_mode
            actor.index_in_world = i
            _init_deplacement(actor, obj.track_mode, obj.track_number)
            actor.position_in_track = obj.position_in_track
            game.flag_genere_aff_list = 1


def change_salle(game, room):
    # ChangeSalle port (M3a subset): current_room = room; num_camera = -1; flag_init_view = 2
    game.current_room = room
    game.num_camera = -1
    game.flag_init_view = 2


def game_step_tick(game):
    game.timer += 1


def init_game(data_dir, hero=0):
    game = Game(data_dir, hero=hero)
    spawn_stage_actors(game)
    change_salle(game, 0)
    game.new_num_camera = 0
    game.flag_init_view = 2
    return game
