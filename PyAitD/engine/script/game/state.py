# SPDX-License-Identifier: GPL-2.0-only
"""Game state: CVars, script vars, world objects, actor table (FITD main.cpp ports)."""
import random
from collections import deque
from dataclasses import dataclass, field

from PyAitD.engine.data.assets import Assets
from PyAitD.engine.script.effects import GameMode, ImmediateEffect, InputMode, MODAL_MODE
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.data.formats import parse_defines, parse_objets, parse_vars
from PyAitD.engine.nav.navmesh import MeshCache

NUM_MAX_OBJECT = 128

AF_ANIMATED = 0x0001
AF_DRAWABLE = 0x0004
AF_BOXIFY = 0x0008
AF_MOVABLE = 0x0010
AF_SPECIAL = 0x0020
AF_TRIGGER = 0x0040
AF_FOUNDABLE = 0x0080
AF_FALLABLE = 0x0100
AF_MASK = AF_ANIMATED + AF_MOVABLE + AF_TRIGGER + AF_FOUNDABLE + AF_FALLABLE + 0x400


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


@dataclass(frozen=True)
class FloorStart:
    # a restart boundary: the coordinates for "immediately be on a floor"
    stage: int
    room: int
    x: int
    y: int
    z: int
    camera_slot: int


class Game:
    def __init__(self, data_dir, profile, hero=0):
        self.profile = profile
        self._data_dir = data_dir
        self._rooms_by_floor = {}
        self.assets = Assets(data_dir, profile, hero=hero)
        self.world_objects = parse_objets((data_dir / "OBJETS.ITD").read_bytes())
        self.actors = [Actor() for _ in range(NUM_MAX_OBJECT)]
        self.cvars = parse_defines((data_dir / "DEFINES.ITD").read_bytes(), big_endian=profile.defines_big_endian)
        self.cvars[profile.cvar_index("CHOOSE_PERSO")] = hero  # startGame backs up and restores it
        self.vars = parse_vars((data_dir / "VARS.ITD").read_bytes())
        self.timer = 0
        self._last_time_forward = 0  # FITD lastTimeForward static (track.cpp:151)
        # the one gameplay RNG (evalVar 0x1C): owned here so a save can
        # snapshot it and a restored game draws the identical stream
        self.rng = random.Random()
        # input snapshot
        self.local_joyd = 0
        self.local_key = 0
        self.local_click = 0
        self.action = 0
        # play loop state (M3a): LIFE trace sink + per-actor anim players
        self.trace = None
        self.anim_players = {}
        # restart boundary: current "immediately be on a floor" target (M3c)
        self.floor_start = None
        self.restart_requested = False
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
        # M3b effect / mode / inventory state
        self.active_modal = None
        self.life_stack = []
        self.immediate_effects = deque()
        self.inventory_table = [[-1] * 30 for _ in range(2)]
        self.inventory_count = [0, 0]
        self.in_hand_table = [-1, -1]
        self.current_inventory = 0
        self.messages = [None] * 5
        self.status_screen_allowed = 1
        # startGame's allowSystemMenu (main.cpp:4134): False for the scripted
        # opening, where FlagGameOver ends the sequence (CutsceneFinished)
        # instead of killing the player, and any input ends it early.
        self.allow_system_menu = True
        # mouse navigation state (see docs/superpowers/specs/2026-08-23-...)
        self.input_mode = InputMode.MOUSE
        self.nav_intent = None
        self.nav_decision = None
        self.nav_arrived_target = -1
        self.nav_meshes = MeshCache()
        self.current_floor_data = None
        # M3b/M4 stubs (audio)
        self.current_music = -1
        self.next_music = -1
        self.light_off = 0
        self.last_sample = -1
        self.next_sample = -1
        self.last_priority = -1

    @property
    def hero(self):
        # a read view, not state: FITD keeps the chosen character in the
        # CHOOSE_PERSO CVar (startGame backs it up and restores it)
        return self.cvars[self.profile.cvar_index("CHOOSE_PERSO")]

    def load_floor(self, number):
        """The Floor loader for callers outside Game: threads self.profile so
        they need neither the profile nor self._data_dir. Uncached by design
        -- callers hold their own floor and reload only when current_floor
        changes, and a cache would retain every visited floor's decoded
        camera images for the process's lifetime. Game's own internals
        (rooms_of_floor) construct Floor directly, so a test stubbing
        load_floor cannot starve them."""
        return Floor(self._data_dir, number, self.profile)

    def rooms_of_floor(self, floor_number):
        # roomDataTable port: global room indices, entry per room in the ETAGE pak
        if floor_number not in self._rooms_by_floor:
            self._rooms_by_floor[floor_number] = Floor(self._data_dir, floor_number, self.profile).rooms
        return self._rooms_by_floor[floor_number]

    def camera_param(self, slot):
        # evalVar 0x1B: *(u16*)(((NumCamera+6)*2)+cameraPtr) — the room def's
        # u16 camera index table starts at byte 12 (roomDefStruct header is
        # 6 u16s); slot -1 reads numCameraInRoom (byte 10).
        room = self.rooms_of_floor(self.current_floor)[self.current_room]
        if slot == -1:
            return len(room.camera_indices)
        return room.camera_indices[slot]

    def open_modal(self, effect):
        if self.active_modal is not None:
            raise RuntimeError(
                f"cannot open {type(effect).__name__} while "
                f"{type(self.active_modal).__name__} is active"
            )
        self.active_modal = effect

    @property
    def mode(self):
        if self.active_modal is None:
            return GameMode.PLAY
        return MODAL_MODE[type(self.active_modal)]

    def close_modal(self):
        self.active_modal = None

    def emit(self, effect):
        if isinstance(effect, ImmediateEffect):
            self.immediate_effects.append(effect)
            return
        self.open_modal(effect)
