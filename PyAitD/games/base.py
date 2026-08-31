# SPDX-License-Identifier: GPL-2.0-only
"""GameProfile: the per-game constants the engine reads at runtime.

FITD branches on g_gameId in boot (main.cpp), opcode semantics (life.cpp),
getCVarsIdx, and a few format variants. Every seam once hard-coded in
engine/ is now a field here: archive naming and overlay strategy
(floor_archive_name/camera_archive_name/mask_factory), the cadre bank,
VM-control opcode numbering (core_slots; opcode_table itself was already a
field), the player-control indices, the record layouts, and the FITD
gameTypeEnum ordinal (generation). A second game is a new profile instance
plus a PROFILES entry — no engine edits."""
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GameProfile:
    name: str
    lifes_pak: str
    tracks_pak: str
    text_pak: str
    resource_pak: str
    palette_entry: int       # resource_pak entry holding the 768-byte VGA palette
    heroes: tuple            # ((body_archive, anim_archive), ...) indexed by hero
    cvar_names: tuple
    defines_big_endian: bool
    opcode_table: tuple      # index == opcode; every slot callable(vm)
    reduced_dispatch: object # callable(vm, opcode, world_idx): not-in-floor ops
    reduced_allowed: frozenset  # opcodes reduced_dispatch has a case for (life.cpp:522-716)
    debug_venues: Mapping    # CLI venue name -> callable(game)
    generation: int            # FITD gameTypeEnum ordinal (vars.h:5-12): AITD1=0, JACK=1, AITD2=2, AITD3=3, TIMEGATE=4
    floor_archive_name: object # callable(floor_number) -> PAK base name (floor.cpp:26-28)
    camera_archive_name: object # callable(floor_number) -> PAK base name
    mask_factory: object       # callable(camera_raw, offset, viewed_room_record_size) -> Mask records (engine.data.mask.Mask); AITD1 computes (createAITD1Mask), JACK+ loads MASK%02d PAKs (main.cpp:2178-2190)
    cadre_bank: tuple          # (ITD_RESS entry, sprite count) of the cadre sprite bank
    core_slots: Mapping        # semantic VM-control op name -> bytecode slot, per the game's life macro table
    combat_action_text_ids: frozenset  # inventory action text ids that arm combat
    player_stand_anim: int     # hero anim index: stand
    player_push_anim: int      # hero anim index: push
    player_track_modes: tuple  # track_mode values meaning player-controlled, (keyboard, mouse) order
    viewed_room_record_size: int  # viewed-room record stride (floor.cpp:367-375): 0x0C AITD1, 0x10 JACK+
    world_object_has_mark: bool    # OBJETS.ITD records carry a trailing mark s16 (main.cpp:1117-1121)
    # (stage, room) FITD's per-game boot passes to startGame (AITD1.cpp:352-361):
    # the scripted opening with allowSystemMenu=0, or None when the game has
    # none. `intro_start` is consumed by engine.script.game.start_game, exactly the
    # staged-floor primitive FITD's startGame minus PlayWorld is. `game_start`
    # is NOT: running start_game on a booted attic resets
    # current_camera_target_actor/current_world_target to -1 and clears
    # floor_start, leaving an uncontrollable hero with no restart point --
    # start_game is built for a scripted stage, not a controllable one. So
    # `game_start` is instead the floor/room engine.script.game.init_game boots the
    # hand-over onto directly (its own staging, hero left where world data
    # put it), the playable start with allowSystemMenu=1.
    intro_start: tuple | None = None
    game_start: tuple = (0, 0)
    alt_camera_sources: Mapping[tuple[int, int], int] = field(default_factory=dict)
    # (floor, camera) -> ITD_RESS entry that overrides CAMERA{NN} when KILLED_SORCERER==1
    # FitdLib/main.cpp:1253, AITD1.h:15-19. Empty means no alts.

    def cvar_index(self, name):
        return self.cvar_names.index(name)

    def hero_archives(self, hero):
        if not 0 <= hero < len(self.heroes):
            raise ValueError(f"hero must be 0..{len(self.heroes) - 1}, got {hero}")
        return self.heroes[hero]
