# SPDX-License-Identifier: GPL-2.0-only
"""AITD1 M3b play loop: one event pump, fixed-step PLAY ticks, modal mode
routing, one presentation per frame — freeze-proof replacement for FITD's
nested blocking modal loops (mainLoop.cpp:41-281)."""
import argparse
from dataclasses import replace
import os
import pathlib
import sys

import pygame

from PyAitD.render.asset_resolver import AssetResolver
from PyAitD.app.config import (
    default_settings, load_settings, settings_path, validate_settings,
)
from PyAitD.engine.content import PackError, load_pack
from PyAitD.engine.script.effects import ChooseCharacter, GameMode, InputMode, OpenStartupMenu, ShowTitle
from PyAitD.engine.script.game import enter_floor_start, init_game
from PyAitD.engine.script.life import Trace
from PyAitD.engine.data.pak import PakError
from PyAitD.engine.script.save import SaveError, restore_game, save_dir
# imported by name, not module-qualified: run() reads play_tick as a module
# global, which is the patch point tests/test_play_loop.py relies on
from PyAitD.engine.script.playworld import TICK_MS, play_tick
from PyAitD.render.render import Renderer
from PyAitD.render.render_options import (
    ATMOSPHERE_MODES, BACKGROUND_FILTERS, LIGHTING_MODES, MSAA_LEVELS, REALISM_MODES, SHADING_MODES,
    INTEGRATION_LEVELS, LEGACY_INTEGRATION, MOTION_MODES, OCCLUSION_MODES,
    SHADOW_MODES, SMOOTHING_LEVELS, validate_render_options,
)
from PyAitD.games import load_profile
from PyAitD.games.aitd1.mirror import MIRROR_KEYCODES
from PyAitD.render.motion import snapshot as motion_snapshot
from PyAitD.render.scene import build_frame
from PyAitD.app.controls.actions import Action
from PyAitD.app.controls.cursor import cursor_state, hit_actor_ids, hit_feedback_rects, intent_marker, marker_for
from PyAitD.app.controls.pointer import CUT_DEAD_ZONE_PX, DOUBLE_PRESS_RESUME_PX, DOUBLE_PRESS_TICKS, settling  # re-exported: tests read these through app.shell
from PyAitD.app.controls.snapshot import ControlsState, build_play_input, configure, feed_event
from PyAitD.app.controls.modals import hit_test_settings_notice
from PyAitD.app.controls.router import (
    MENU_RENDER_FIELDS as _MENU_RENDER_FIELDS,  # re-exported: tests read these through app.shell
    apply_system_result, available_slots, cancel_pointer_invalidation, continue_available,
    credits_entry, follow_pointer, game_over_ready, inventory_hud_available, inventory_view,
    rebase_follow, resolve_play_click, route_command, route_hover,  # resolve_play_click re-exported: tests read these through app.shell
    route_mouse, route_play_click, take_over_play_input, write_save,
)
from PyAitD.app.ui import (
    ModalSession, UIPainter,
    render_cursor, render_hit_feedback, render_play_hud,
    render_settings_notice,
)

DEFAULT_DATA = (
    pathlib.Path(__file__).resolve().parent.parent
    / "data"
    / "aitd1"
    / "Alone in the Dark 1.app"
    / "Contents"
    / "Resources"
    / "game"
    / "INDARK"
)
HIT_FEEDBACK_MS = 250


def _integration_level(text):
    """An --integration level, or one of the two words the option used to
    take. "off" and "on" keep parsing so a shell alias or script written
    before the levels does not start failing at the argument parser."""
    value = LEGACY_INTEGRATION.get(text, text)
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = None
    if level not in INTEGRATION_LEVELS:
        raise argparse.ArgumentTypeError(
            "integration must be one of "
            f"{', '.join(str(v) for v in INTEGRATION_LEVELS)}, off or on")
    return level


def parse_args(argv):
    p = argparse.ArgumentParser(prog="PyAitD", description="AITD1 play viewer (M3b: interaction loop)")
    p.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA, help="game data dir")
    p.add_argument("--floor", type=int, default=None, help="floor number (default: character select on floor 0)")
    p.add_argument("--trace", type=pathlib.Path, default=None, help="write per-opcode LIFE trace to FILE")
    p.add_argument(
        "--hero", type=int, choices=(0, 1), default=0,
        help="hero for the debug starts, 0=Carnby 1=Emily (a normal boot uses "
             "the character selector instead)",
    )
    starts = p.add_mutually_exclusive_group()
    starts.add_argument(
        "--combat-venue", action="store_true",
        help="start at the supported floor-5 combat venue",
    )
    starts.add_argument(
        "--mouse-combat-fixture", action="store_true",
        help="start with the deterministic object-38 mouse combat proof fixture",
    )
    p.add_argument(
        "--render-scale", type=int, default=None,
        help="internal resolution multiple of 320x200 (1-8)",
    )
    p.add_argument(
        "--shading", choices=SHADING_MODES, default=None, help="actor shading mode",
    )
    p.add_argument(
        "--background-filter", choices=BACKGROUND_FILTERS, default=None,
        help="background upscale filter",
    )
    p.add_argument(
        "--lighting", choices=LIGHTING_MODES, default=None,
        help="fixed rig, or a light estimated from each camera's background",
    )
    p.add_argument(
        "--msaa", type=int, choices=MSAA_LEVELS, default=None,
        help="multisample anti-aliasing samples (0 disables)",
    )
    p.add_argument(
        "--realism", choices=REALISM_MODES, default=None,
        help="classic (today's look) or enhanced (per-material specular, rim, occlusion and grain)",
    )
    p.add_argument(
        "--smoothing", type=int, choices=SMOOTHING_LEVELS, default=None,
        help="GPU mesh smoothing level: 0 draws the flat 1992 mesh, 1-3 round it with 4/16/64 sub-triangles",
    )
    p.add_argument(
        "--shadows", choices=SHADOW_MODES, default=None,
        help="hard: the flat projected silhouette; soft: a contact-hardening penumbra, "
             "one gathered pass, and bodies shadowing themselves and each other",
    )
    p.add_argument(
        "--integration", type=_integration_level, default=None,
        metavar="{0,1,2,3}",
        help="how much of the plate's tone, grain and softness the actors take on: "
             "0 draws them straight over it, 1-3 composite at half, full and one-and-a-half strength")
    p.add_argument(
        "--motion", choices=MOTION_MODES, default=None,
        help="tick: one pose per 50 Hz tick; smooth: blend between ticks "
             "at the display rate (rendering only, up to one tick behind)",
    )
    p.add_argument(
        "--occlusion", choices=OCCLUSION_MODES, default=None,
        help="screen-space ambient occlusion on actors (session only)",
    )
    p.add_argument(
        "--atmosphere", choices=ATMOSPHERE_MODES, default=None,
        help="depth-driven haze and depth-graded softness and grain on actors (session only)",
    )
    p.add_argument(
        "--textures", type=pathlib.Path, default=None, help="asset texture directory",
    )
    p.add_argument(
        "--content", type=pathlib.Path, default=None,
        help="content pack directory (holds pack.toml); session only, never persisted",
    )
    p.add_argument(
        "--save-dir", type=pathlib.Path, default=None,
        help="save slot directory (default: beside the settings file)",
    )
    p.add_argument(
        "--skip-intro", action="store_true",
        help="development convenience, not FITD behaviour: boot the attic "
             "directly after character select (skips the floor-7 opening)",
    )
    p.add_argument(
        "--mirror", action="store_true",
        help="forward consumed PLAY keyboard input to the live-mirror helper "
             "(set up by tools/compare_original.py)",
    )
    return p.parse_args(argv)


# (argparse dest, settings-payload key) for every override copied straight
# through. All but --render-scale share a name with their payload key; the
# Nth render option is one line here rather than a fourth `if` block.
_RENDER_OVERRIDES = (
    ("render_scale", "scale"),
    ("shading", "shading"),
    ("background_filter", "background_filter"),
    ("lighting", "lighting"),
    ("msaa", "msaa"),
    ("realism", "realism"),
    ("smoothing", "smoothing"),
    ("shadows", "shadows"),
    ("integration", "integration"),
    ("motion", "motion"),
    ("occlusion", "occlusion"),
    ("atmosphere", "atmosphere"),
)


def apply_render_overrides(settings, args):
    """Session-only CLI overrides for settings.render: pure, never persisted.

    Built via validate_render_options so an out-of-range --render-scale is
    clamped the same way a settings-file value would be, rather than being
    rejected or passed through unclamped.
    """
    payload = settings.render.to_payload()
    for arg_name, key in _RENDER_OVERRIDES:
        value = getattr(args, arg_name)
        if value is not None:
            payload[key] = value
    if args.textures is not None:
        # The one override whose value is transformed rather than copied.
        payload["texture_dir"] = str(args.textures)
    render, _error = validate_render_options(payload)
    return replace(settings, render=render)


def load_runtime_session(path, save_directory=None):
    # JSON-only boot step: no pygame initialization here -- pygame key names
    # are validated later by configure_session_input, once the Renderer owns
    # the initialized pygame runtime.
    settings, error = load_settings(path)
    # Captured before main() applies any --render-* / --textures CLI flags
    # to session.settings: this is the on-disk baseline a later save must
    # not let a session-only CLI override clobber. See
    # save_session_settings and apply_render_overrides.
    return ModalSession(
        settings=settings, settings_path=path, settings_error=error,
        disk_render=settings.render,
        save_directory=save_dir() if save_directory is None else save_directory,
    )


def configure_session_input(session, controls):
    try:
        configure(controls, session.settings)
    except ValueError as exc:
        session.settings = default_settings()
        session.settings_error = (
            f"Could not load settings from {session.settings_path}: {exc}"
        )
        configure(controls, session.settings)


def replacement_session(session):
    # Hero confirmation and death restart both replace the game: only the
    # application-session fields (settings and their persistence state) carry
    # over; every modal presenter starts fresh.
    return ModalSession(
        settings=session.settings,
        settings_path=session.settings_path,
        settings_error=session.settings_error,
        settings_dirty=session.settings_dirty,
        disk_render=session.disk_render,
        render_touched=session.render_touched,
        booted_via_menu=session.booted_via_menu,
        skip_intro=session.skip_intro,
        save_directory=session.save_directory,
    )


def _scene_frame(game, floor, renderer, resolver, blend=None):
    # mainLoop.cpp:270 AllRedraw through the scene layer: build_frame keeps
    # the logical draw_list; the renderer draws the enhanced frame (its
    # 320x200 thumbnail, if a presenter or the software path needs one, is
    # computed lazily by renderer.scene_thumbnail() instead of eagerly here
    # -- see the finding-1 note on Renderer.compose_scene). `resolver` is
    # required, not defaulted: a silent `AssetResolver(game.assets)`
    # fallback here would drop the override directory with no error, the same
    # silent-degradation failure mode `_resolver_for` exists to avoid below.
    # shadows is read off renderer.options rather than threaded through as
    # a parameter: renderer.options is the authoritative post-set_options
    # value (see render.py's Renderer.options / set_options and this
    # module's _apply_render_options), so the frame this builds and the
    # backend that draws it can never disagree about which shadow mode is
    # active.
    frame, draw_list = build_frame(game, floor, resolver, blend, shadows=renderer.options.shadows)
    return renderer.compose_scene(frame), draw_list


def _motion_blend(session, motion_prev, accumulator):
    """build_frame's blend argument for this frame, or None.

    Smooth motion only, with a snapshot taken before this game's most
    recent tick; alpha is the accumulator's leftover fraction of the
    next tick, clamped so a stalled frame holds the tick pose instead
    of extrapolating past it."""
    if motion_prev is None or session.settings.render.motion != "smooth":
        return None
    return motion_prev, min(accumulator / TICK_MS, 1.0)


def _resolver_for(assets, texture_dir):
    # A hero swap or restart replaces `game` (and so `game.assets`): the old
    # resolver's cache is keyed off the old assets object and must not be
    # reused, but the texture directory it was configured with still
    # applies to the new game. `texture_dir` is the public
    # `session.settings.render.texture_dir` value -- never read off another
    # resolver's private state.
    return AssetResolver(assets, texture_dir)


def _render_play_cursor(game, floor, hover, draw_list, controls, painter):
    """The PLAY cursor with its feedback: the live destination, a preview of
    where a press would head while nothing is held, the press ring, and the
    dashed ring while a cut's dead zone is open."""
    kind, payload = cursor_state(game, floor, hover, draw_list, controls.pointer)
    destination = intent_marker(game, floor)
    preview = None
    if not controls.pointer.held and destination is None and kind in ("walk", "target"):
        preview = marker_for(game, floor, payload)
    render_cursor(
        painter, hover, kind, held=controls.pointer.held,
        settling=settling(controls.pointer),
        destination=destination, preview=preview,
    )


def _commit_quick_save(game, session):
    session.quick_save_requested = False
    write_save(game, session, "quick")


def _load_branch(game, renderer, session, controls=None):
    """The atomic load replacement: rebuild the game from the staged payload
    and hand run() every loop local that referenced the old game, exactly
    like _restart_branch. A failure consumes the payload, raises the notice,
    and leaves the menu (and everything else) untouched."""
    if session.pending_load is None:
        return None
    payload = session.pending_load
    session.pending_load = None
    take_over_play_input(game, session, controls)
    trace = game.trace
    try:
        new_game, settings_dict = restore_game(game._data_dir, game.profile, payload, pack=game.pack)
        settings, _render_error = validate_settings(settings_dict)
        new_floor = new_game.load_floor(new_game.current_floor)
    except (PakError, SaveError, ValueError) as exc:
        session.runtime_error = f"Could not load save: {exc}"
        return None
    texture_dir = session.settings.render.texture_dir
    game = new_game
    game.trace = trace
    floor = new_floor
    session = replacement_session(session)
    session.settings = settings
    controls = ControlsState()
    configure_session_input(session, controls)
    accumulator = 0
    draw_list = []
    hover = None
    game.num_camera = game.new_num_camera
    game.flag_init_view = 0
    new_resolver = _resolver_for(game.assets, texture_dir)
    scene_frame, draw_list = _scene_frame(game, floor, renderer, new_resolver)
    last = pygame.time.get_ticks()
    return (
        game, floor, session, controls, accumulator,
        draw_list, hover, scene_frame, last, 0, new_resolver,
    )


def _capture_keydown(event, game, session, controls):
    from PyAitD.engine.script.effects import OpenSystemMenu
    from PyAitD.app.controls.bindings import canonical_key_name
    from PyAitD.app.controls.modals import capture_system_key
    if (not isinstance(game.active_modal, OpenSystemMenu)
            or session.system_menu.capture is None
            or event.type != pygame.KEYDOWN):
        return False, True
    if bool(getattr(event, "repeat", False)):
        return True, True
    try:
        name = canonical_key_name(event.key)
        result = capture_system_key(session.system_menu, session.settings, name)
    except ValueError as exc:
        session.settings_error = f"Could not bind pygame key {event.key}: {exc}"
        return True, True
    return True, apply_system_result(game, session, controls, result)


def _auto_dismiss_picture(game, session):
    from PyAitD.engine.script.effects import ShowPicture
    from PyAitD.engine.script.interaction import apply_reading_result
    from PyAitD.app.ui import ReadingResult
    effect = game.active_modal
    if not isinstance(effect, ShowPicture) or effect.delay_units <= 0:
        return True
    delay_ms = effect.delay_units * 1000 // 60
    if session.elapsed_ms < delay_ms:
        return True
    apply_reading_result(game, ReadingResult(True))
    return True


def render_active_mode(game, session, renderer, resolver=None):
    """`renderer` is the live Renderer, not a pre-computed thumbnail: only
    the two branches below that actually paint a scene thumbnail behind
    their modal (OpenInventory, GameOver) call `renderer.scene_thumbnail()`,
    so every other mode (most frames: no modal at all) never pays for it --
    see the finding-1 note on `Renderer.compose_scene`."""
    from PyAitD.engine.script.effects import (
        ChooseCharacter, CutsceneFinished, GameOver, OpenInventory, OpenSystemMenu,
        ReadText, ShowFound, ShowPicture,
    )
    from PyAitD.app.ui import (
        overlay_messages, render_character_select, render_found,
        render_game_over, render_inventory, render_picture, render_reading,
        render_system_menu,
    )
    painter = UIPainter(renderer.ui_scale())
    effect = game.active_modal
    if effect is None:
        overlay_messages(painter, game.messages, game.assets)
        return painter
    if isinstance(effect, CutsceneFinished):
        # the last PLAY frame stays composed underneath, exactly like
        # render_game_over before its accessibility wait elapses
        return painter
    # This is the modal lifecycle boundary.  It resets a replacement exactly
    # once before any presenter can render, including the system menu.
    session.reset_for(effect)
    # Every branch paints on the one painter and none of them returns a
    # value, so the dispatch ends in a single return: a new modal that forgot
    # its own `return painter` would otherwise hand run() a None to present.
    if isinstance(effect, OpenSystemMenu):
        render_system_menu(painter, session.system_menu, session.settings, game.assets,
                           available_slots(session))
    elif isinstance(effect, ChooseCharacter):
        # the selector owns the whole frame; the staged PLAY scene is never shown
        render_character_select(painter, session.character, game.assets, resolver)
    elif isinstance(effect, ShowTitle):
        from PyAitD.app.startup import render_title
        render_title(painter, session.title, game.assets, resolver or AssetResolver(game.assets, None),
                      session.elapsed_ms, credits_entry(game))
    elif isinstance(effect, OpenStartupMenu):
        from PyAitD.app.startup import render_startup_menu
        render_startup_menu(painter, session.startup, game.assets, continue_enabled=continue_available(session))
    elif isinstance(effect, ShowFound):
        world = game.world_objects[effect.object_idx]
        render_found(painter, effect, session.found, game.assets,
                     game.assets.system_text(world.found_name))
    elif isinstance(effect, OpenInventory):
        object_ids, action_ids = inventory_view(game, session)
        render_inventory(
            painter, session.inventory, game.assets, renderer.scene_thumbnail(),
            tuple(game.assets.system_text(game.world_objects[i].found_name) for i in object_ids),
            tuple(game.assets.system_text(i) for i in action_ids),
        )
    elif isinstance(effect, ReadText):
        render_reading(painter, effect, session.reading, game.assets, resolver)
    elif isinstance(effect, ShowPicture):
        render_picture(painter, effect, game.assets, resolver)
    elif isinstance(effect, GameOver):
        render_game_over(painter, renderer.scene_thumbnail(), game_over_ready(session, effect))
    else:
        raise RuntimeError(f"unrenderable modal {type(effect).__name__}")
    return painter


def restart_session(old_game):
    # Death restarts the current floor (task-10 brief): the title screen and
    # menus now exist (app/startup.py), but a fresh boot through them would
    # discard the run in progress, so restart stays the in-place path that
    # keeps the game playable end-to-end. No Floor I/O here -- the caller
    # (run's atomic restart branch) owns loading the Floor for the
    # reconstructed game.
    hero = old_game.cvars[old_game.profile.cvar_index("CHOOSE_PERSO")]
    input_mode = old_game.input_mode
    trace = old_game.trace
    data_dir = old_game._data_dir
    floor_start = old_game.floor_start
    new_game = init_game(data_dir, old_game.profile, hero=hero, pack=old_game.pack)
    new_game.input_mode = input_mode
    new_game.trace = trace
    from PyAitD.engine.script.interaction import sync_player_track_mode
    sync_player_track_mode(new_game)
    enter_floor_start(new_game, floor_start)
    new_game.floor_start = floor_start
    return new_game


def _boot_hero(game, renderer, session, controls, hero, *, cutscene):
    """Build the replace tuple run() adopts: a fresh game for `hero`, staged
    on profile.intro_start (cutscene, allowSystemMenu=0, AITD1.cpp:352-361)
    or on the attic init_game already stages (profile.game_start). Shared by
    _hero_branch (character confirmation) and _cutscene_end_branch (the
    startGame(0, 0, 1) hand-over once the opening ends)."""
    from PyAitD.engine.script.game import start_game
    take_over_play_input(game, session, controls)
    try:
        new_game = init_game(game._data_dir, game.profile, hero=hero, pack=game.pack)
        if cutscene:
            start_game(new_game, *game.profile.intro_start)
            new_game.allow_system_menu = False
        new_floor = new_game.load_floor(new_game.current_floor)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return (None, None, None, None, 0, [], None, None, None, 2, None)
    new_game.trace = game.trace
    new_game.input_mode = game.input_mode
    new_session = replacement_session(session)
    new_session.cutscene = cutscene
    controls = ControlsState()
    configure_session_input(new_session, controls)
    # Staged by start_game: num_camera == -1, new_num_camera == 0. This
    # stages camera 0 exactly as FITD's InitView does after startGame -- the
    # same line init_game's own staging (game_start) relies on below.
    new_game.num_camera = new_game.new_num_camera
    new_game.flag_init_view = 0
    new_resolver = _resolver_for(new_game.assets, session.settings.render.texture_dir)
    scene_frame, draw_list = _scene_frame(new_game, new_floor, renderer, new_resolver)
    return (
        new_game, new_floor, new_session, controls, 0,
        draw_list, None, scene_frame, pygame.time.get_ticks(), 0, new_resolver,
    )


def _hero_branch(game, renderer, session, controls=None):
    # Atomic hero replacement: confirming a character rebuilds game, floor,
    # session, and input buffer in one tuple, so run() resumes on the new
    # game with a single assignment plus `continue` -- no PLAY tick and no
    # stale present can slip through for the staging game. The resolver this
    # branch builds for its own _scene_frame call is returned too, so run()
    # can adopt it for later frames instead of building a second one over
    # the same new_game.assets.
    if session.pending_hero is None:
        return None
    # startAITD1: ChoosePerso() then startGame(7, 1, 0), the scripted opening
    # (AITD1.cpp:356) -- unless the game has none, or --skip-intro asked
    # to boot the attic directly (development convenience, not FITD).
    cutscene = game.profile.intro_start is not None and not session.skip_intro
    return _boot_hero(game, renderer, session, controls, session.pending_hero, cutscene=cutscene)


def _cutscene_end_branch(game, renderer, session, controls=None):
    # PlayWorld(allowSystemMenu=0) returns on FlagGameOver or any key/click
    # (mainLoop.cpp:71-89, CutsceneFinished / session.skip_cutscene); then
    # startAITD1 calls startGame(0, 0, 1), the attic (AITD1.cpp:361), with
    # the same hero that was staged for the opening.
    from PyAitD.engine.script.effects import CutsceneFinished
    if not session.cutscene:
        return None
    if not (session.skip_cutscene or isinstance(game.active_modal, CutsceneFinished)):
        return None
    hero = game.cvars[game.profile.cvar_index("CHOOSE_PERSO")]
    return _boot_hero(game, renderer, session, controls, hero, cutscene=False)


def _restart_branch(game, renderer, session, controls=None):
    # The atomic replace-game-and-floor step run() inlines each frame: a
    # successful restart hands back every loop local that referenced the old
    # game, so a single tuple assignment plus `continue` is enough to resume
    # the loop on the new session without a stray tick or a stale present.
    # Same resolver-reuse note as _hero_branch above.
    if not game.restart_requested:
        return None
    take_over_play_input(game, session, controls)
    try:
        new_game = restart_session(game)
        new_floor = new_game.load_floor(new_game.current_floor)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return (None, None, None, None, 0, [], None, None, None, 2, None)
    texture_dir = session.settings.render.texture_dir
    game = new_game
    floor = new_floor
    session = replacement_session(session)
    controls = ControlsState()
    configure_session_input(session, controls)
    accumulator = 0
    draw_list = []
    hover = None
    game.num_camera = game.new_num_camera
    game.flag_init_view = 0
    new_resolver = _resolver_for(game.assets, texture_dir)
    scene_frame, draw_list = _scene_frame(game, floor, renderer, new_resolver)
    last = pygame.time.get_ticks()
    return (
        game, floor, session, controls, accumulator,
        draw_list, hover, scene_frame, last, 0, new_resolver,
    )


def run(game, trace_path=None, session=None, resolver=None, mirror_sink=None):
    # M3b play loop: one event pump, fixed-step PLAY ticks, one present/frame
    try:
        floor = game.load_floor(game.current_floor)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    game.trace = Trace(trace_path) if trace_path else None
    if session is None:
        session = ModalSession()
    renderer = Renderer(session.settings.render)
    if renderer.fallback_notice and session.settings_error is None:
        session.settings_error = renderer.fallback_notice
    resolver = resolver or AssetResolver(game.assets, session.settings.render.texture_dir)
    clock = pygame.time.Clock()
    controls = ControlsState()
    configure_session_input(session, controls)
    running = True
    exit_status = 0
    last = pygame.time.get_ticks()
    accumulator = 0
    motion_prev = None
    if game.num_camera == -1:
        game.num_camera = game.new_num_camera
        game.flag_init_view = 0
    draw_list = []
    hover = None
    # Unconditional: this is what makes the very first present() well-defined.
    # The GL backend's texture (render_gl.py) and the software backend's
    # cached thumbnail both start undrawn, and present() has no "never drawn"
    # guard -- compose_scene must run at least once before the loop's first
    # present(), even on a frame where game.num_camera stays -1 below.
    scene_frame, draw_list = _scene_frame(game, floor, renderer, resolver)
    hit_feedback_deadlines = {
        actor_idx: last + HIT_FEEDBACK_MS for actor_idx in hit_actor_ids(game)
    }
    while running:
        for event in pygame.event.get():
            # raw key capture owns KEYDOWN while the system menu is binding:
            # the event never reaches feed_event, mouse routing, or the
            # menu reducer; KEYUP and focus events keep the ordinary path
            captured, capture_running = _capture_keydown(
                event, game, session, controls,
            )
            if captured:
                running = capture_running and running
                continue
            logical_pos = None
            if event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
                logical_pos = renderer.window_to_logical(event.pos)
            if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                    and (session.settings_error is not None
                         or session.runtime_error is not None)
                    and logical_pos is not None
                    and hit_test_settings_notice(logical_pos)):
                # the notice's Dismiss gets first refusal over every other
                # route -- including the cutscene skip below -- so a click on
                # it during the opening clears only the error, never the
                # mode/effect underneath and never the cutscene itself.
                session.settings_error = None
                session.runtime_error = None
                continue
            if session.cutscene and (
                event.type == pygame.KEYDOWN
                or (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1)
                or event.type == pygame.FINGERDOWN
            ):
                # PlayWorld(allowSystemMenu=0) breaks on 0x1C/0x17 or any
                # click (mainLoop.cpp:69-92). ponytail: FITD's 0x1B (Escape)
                # instead calls processSystemMenu() unconditionally first
                # (mainLoop.cpp:55-61), before any allowSystemMenu test, so
                # Escape opens the system menu *during* the intro rather than
                # skipping it; this port deliberately swallows every key,
                # Escape included, as a skip instead (the spec's chosen
                # simplification -- no system menu during the opening). A
                # faithful upgrade would special-case KEYDOWN Escape here to
                # open OpenSystemMenu instead of setting skip_cutscene.
                # QUIT and focus events fall through to their normal handling
                # below; everything else just skips.
                session.skip_cutscene = True
                continue
            running = feed_event(controls, event, logical_pos) and running
            if (mirror_sink is not None
                    and event.type in (pygame.KEYDOWN, pygame.KEYUP)
                    and not bool(getattr(event, "repeat", False))
                    and game.mode is GameMode.PLAY
                    and game.active_modal is None
                    and game.input_mode is InputMode.KEYBOARD):
                control = controls.keyboard.table.get(event.key)
                if control is not None and control.name in MIRROR_KEYCODES:
                    if event.type == pygame.KEYDOWN:
                        mirror_sink.key_down(control.name)
                    else:
                        mirror_sink.key_up(control.name)
            cancel_pointer_invalidation(game, event, controls)
            if event.type == pygame.MOUSEMOTION:
                hover = controls.pointer.pos
                if game.active_modal is not None:
                    route_hover(game, session, hover)
            elif event.type == pygame.WINDOWFOCUSLOST:
                hover = None
                if game.active_modal is not None:
                    route_hover(game, session, None)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                logical = controls.pointer.pos
                if game.active_modal is None and game.mode is GameMode.PLAY:
                    # keyboard mode swallows play clicks (resolve_play_click
                    # returns "blocked"); the cursor is hidden there too and
                    # the HUD names the mode, so nothing advertises a click
                    # that does nothing
                    route_play_click(
                        game, session, floor, logical, draw_list, controls,
                    )
                else:
                    running = route_mouse(
                        game, session, logical, controls, renderer=renderer,
                    ) and running
        now = pygame.time.get_ticks()
        elapsed = min(now - last, 250)
        last = now
        was_play = game.mode is GameMode.PLAY
        if controls.keyboard.queue:
            command = controls.keyboard.queue.popleft()
            if session.cutscene:
                # defence-in-depth: unreachable in practice, since the
                # cutscene swallow above `continue`s on every KEYDOWN while
                # session.cutscene is True -- feed_event, the only place
                # that appends to controls.keyboard.queue, never runs, so
                # commands cannot exist here while a cutscene is active. Kept
                # so this drain still does the right thing if that invariant
                # is ever weakened (e.g. a caller feeding controls.keyboard.queue
                # directly, as some tests do).
                pass
            elif ((session.settings_error is not None
                   or session.runtime_error is not None)
                    and command in (Action.ACTION, Action.INVENTORY_CONFIRM)):
                # same first refusal as the Dismiss click: ACTION and
                # INVENTORY_CONFIRM dismiss the notice instead of reaching the mode
                session.settings_error = None
                session.runtime_error = None
            else:
                running = route_command(
                    game, session, command, controls, renderer=renderer,
                ) and running
        replaced = _hero_branch(game, renderer, session, controls)
        if replaced is None:
            replaced = _cutscene_end_branch(game, renderer, session, controls)
        if replaced is None:
            replaced = _restart_branch(game, renderer, session, controls)
        if replaced is None:
            replaced = _load_branch(game, renderer, session, controls)
        if replaced is not None:
            (
                new_game, new_floor, new_session, new_controls,
                new_accumulator, new_draw_list, new_hover, new_scene_frame,
                new_last, exit_status, new_resolver,
            ) = replaced
            if exit_status:
                running = False
                break
            # The branch above already built the one resolver this
            # replacement needs (for the scene_frame it produced); adopt the
            # same object here instead of building a second one over the same
            # new_game.assets, so later frames keep its override-PNG cache.
            resolver = new_resolver
            # a hero swap, restart, cutscene hand-over or load must never
            # blend from the old game's snapshot
            motion_prev = None
            game, floor, session, controls = (
                new_game, new_floor, new_session, new_controls,
            )
            accumulator, draw_list, hover, scene_frame, last = (
                new_accumulator, new_draw_list, new_hover, new_scene_frame, new_last,
            )
            hit_feedback_deadlines = {
                actor_idx: last + HIT_FEEDBACK_MS
                for actor_idx in hit_actor_ids(game)
            }
            continue
        if game.mode is GameMode.PLAY:
            accumulator += elapsed
            ticked = False
            while accumulator >= TICK_MS and game.mode is GameMode.PLAY:
                motion_prev = motion_snapshot(game)
                play_tick(game, floor, build_play_input(controls))
                ticked = True
                for actor_idx in hit_actor_ids(game):
                    hit_feedback_deadlines[actor_idx] = now + HIT_FEEDBACK_MS
                if game.mode is not GameMode.PLAY:
                    take_over_play_input(game, session, controls)
                accumulator -= TICK_MS
                if floor.number != game.current_floor:
                    floor = game.load_floor(game.current_floor)
                    # the intent's room indexes the old floor; the hold
                    # survives and the next frame re-resolves the held
                    # pointer against the new one, still hand or not
                    rebase_follow(game, controls)
            if (ticked and session.quick_save_requested
                    and game.mode is GameMode.PLAY
                    and not game.life_stack and not game.immediate_effects):
                # the deferred Quick Save commits at the first stable
                # end-of-tick boundary: a tick really ran after the request,
                # PLAY is still active, no LIFE continuation, no platform
                # effects queued
                _commit_quick_save(game, session)
            if game.num_camera != -1:
                scene_frame, draw_list = _scene_frame(
                    game, floor, renderer, resolver,
                    _motion_blend(session, motion_prev, accumulator),
                )
            # after the ticks and the scene refresh, so a moved pointer
            # resolves against the frame it is actually over. A camera cut
            # with a still pointer changes nothing here: follow_pointer's
            # movement gate leaves the destination alone until the hand moves
            follow_pointer(
                game, session, floor, controls.pointer.pos, draw_list, controls,
            )
        else:
            accumulator = 0
            # not PLAY this frame: the accumulator restarts, so the old
            # snapshot must not survive to blend against on the resume
            # frame (it would pop the actor backward by up to one tick)
            motion_prev = None
            session.elapsed_ms += elapsed
            _auto_dismiss_picture(game, session)
            if isinstance(game.active_modal, ShowTitle):
                from PyAitD.app.startup import advance_title
                advance_title(session.title, session.elapsed_ms)
        if was_play and game.mode is not GameMode.PLAY:
            # Simulation-raised effects (found, reading, picture, game over)
            # cross the boundary inside play_tick.  Action/pointer routes use
            # the same idempotent seam immediately when they open their modal.
            take_over_play_input(game, session, controls)
        hit_feedback_deadlines = {
            actor_idx: deadline
            for actor_idx, deadline in hit_feedback_deadlines.items()
            if deadline > now
        }
        painter = render_active_mode(game, session, renderer, resolver)
        render_hit_feedback(
            painter,
            hit_feedback_rects(game, draw_list, hit_feedback_deadlines),
        )
        available = inventory_hud_available(game) and not session.cutscene
        # At most one visible cursor, and none at all where the mouse does
        # nothing. The software cursor draws only for PLAY + mouse + no modal.
        # PLAY + keyboard has no mouse function whatsoever -- resolve_play_click
        # returns "blocked" before it picks anything, and route_hover only runs
        # for modals -- so the OS pointer is hidden there too rather than
        # inviting clicks that cannot land. Every other state (modals with
        # buttons, menus, cutscenes) keeps it. Toggled per frame.
        software_cursor = (game.mode is GameMode.PLAY
                           and game.active_modal is None
                           and game.input_mode is InputMode.MOUSE
                           and not session.cutscene)
        play_keyboard = (game.mode is GameMode.PLAY
                         and game.active_modal is None
                         and game.input_mode is InputMode.KEYBOARD
                         and not session.cutscene)
        render_play_hud(
            painter, inventory_available=available,
            keyboard_mode=play_keyboard,
        )
        # the settings notice is mode-independent: after the HUD and before
        # the software cursor, so its Dismiss target is visually topmost.
        # Persistence errors share the surface and its one large Dismiss
        # target (a settings error wins the slot: it names the boot file).
        render_settings_notice(painter, session.settings_error or session.runtime_error)
        pygame.mouse.set_visible(not software_cursor and not play_keyboard)
        if software_cursor:
            _render_play_cursor(game, floor, hover, draw_list, controls, painter)
        renderer.present(painter)
        if game.num_camera != -1:
            # M3a draw_ready gate: transition frames (change_salle/floor
            # pending, num_camera == -1, current_room stale) reuse the
            # previous frame instead of re-indexing rooms/cameras.
            room = floor.rooms[game.current_room]
            cam_idx = room.camera_indices[game.num_camera]
            live = sum(1 for actor in game.actors if actor.index_in_world >= 0)
            pygame.display.set_caption(
                f"PyAitD — floor {floor.number} room {game.current_room} "
                f"camera {cam_idx} actors {live}"
            )
        clock.tick(60)
    if game.trace is not None:
        game.trace.close()
    pygame.mouse.set_visible(True)
    renderer.close()
    return exit_status


def main(argv=None):
    args = parse_args(argv)
    profile = load_profile("aitd1")
    pack = None
    if args.content is not None:
        try:
            pack = load_pack(args.content, args.data, profile)
        except (PackError, PakError) as exc:
            # a pack is applied whole or not at all: no substitute exists
            # for a missing enemy, unlike a missing texture
            print(f"content pack error: {exc}", file=sys.stderr)
            return 2
    try:
        # The debug starts bypass the character selector, so --hero is the only
        # way to reach Emily's copy of a fixture; a normal boot still opens the
        # selector below and replaces this staging game with the chosen hero's.
        game = init_game(args.data, profile, hero=args.hero, pack=pack)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.floor not in (None, 0):
        print(
            "error: non-zero --floor has no safe room/coordinate mapping; "
            "use --combat-venue or --mouse-combat-fixture",
            file=sys.stderr,
        )
        return 2
    if args.mouse_combat_fixture:
        profile.debug_venues["mouse-combat-fixture"](game)
    elif args.combat_venue:
        profile.debug_venues["combat-venue"](game)
    debug_start = (
        args.floor is not None or args.combat_venue or args.mouse_combat_fixture
    )
    if not debug_start:
        # Normal boot stages floor zero but opens the title screen before
        # run(), following the title -> credits -> menu -> selector flow
        # (startAITD1); PLAY never ticks or presents until _hero_branch
        # replaces the staging game with the confirmed hero's game.
        # Invariant: this is the only modal ever opened before a ModalSession
        # exists (session is constructed below, then handed to run()) -- so
        # ShowTitle's presenter must be reset-clean by construction, since no
        # session.reset_for(effect) call has run yet to clean it. A route_*
        # branch that reads/mutates session.title before reset_for observes
        # this exact effect identity is exactly the bug fixed in 16be7dd
        # (route_mouse dispatched before reset_for while route_command reset
        # first, silently swallowing the title screen's first click).
        game.open_modal(ShowTitle())
    session = load_runtime_session(settings_path(), save_directory=args.save_dir)
    # Session-only: this replaces session.settings in memory, but
    # session.disk_render (captured above, before this call) stays the
    # on-disk baseline -- so even a later save triggered by an unrelated
    # settings change (e.g. toggling Sticky Action in CONFIG) writes back
    # these CLI values' *un*-overridden originals, not argv. See
    # save_session_settings / persisted_render.
    session.settings = apply_render_overrides(session.settings, args)
    session.skip_intro = args.skip_intro
    mirror_sink = None
    if args.mirror:
        fd = os.environ.get("PYAITD_MIRROR_FD")
        pid = os.environ.get("PYAITD_MIRROR_PID")
        if fd is not None and pid is not None:
            from PyAitD.app.mirror import MirrorSink
            stream = os.fdopen(int(fd), "w", encoding="ascii", buffering=1)
            noted = []

            def write_line(line):
                # The helper is a separate process and can die mid-session;
                # a dead pipe must degrade the port, never crash the run
                # loop. Note once on stderr, then no-op.
                if noted:
                    return
                try:
                    stream.write(line + "\n")
                except OSError:
                    noted.append(True)
                    print("note: the mirror helper died; key forwarding "
                          "is disabled for this session", file=sys.stderr)

            mirror_sink = MirrorSink(write_line, int(pid))
    return run(game, args.trace, session=session, mirror_sink=mirror_sink)
