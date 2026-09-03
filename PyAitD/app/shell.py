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
    default_settings, load_settings, save_settings, settings_path,
    settings_payload, validate_settings,
)
from PyAitD.engine.script.effects import ChooseCharacter, GameMode, InputMode, OpenStartupMenu, ShowTitle
from PyAitD.engine.script.game import enter_floor_start, init_game
from PyAitD.engine.script.life import Trace
from PyAitD.engine.data.pak import PakError
from PyAitD.engine.nav.navmesh import (
    TARGET_SNAP_CELLS, agent_extent, approach_cell, nearest_walkable,
)
from PyAitD.engine.nav.picking import (
    pick_actor, pick_floor_any_room, snap_accept, viewed_floor_y, visible_accept,
)
from PyAitD.engine.script.save import (
    SaveError, read_slot, restore_game, save_dir, slot_path, snapshot_game, write_slot,
)
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
from PyAitD.app.ui import (
    Command, DOUBLE_PRESS_TICKS, InputBuffer, ModalSession, UIPainter, configure_input,
    event_to_input,
    hit_test_settings_notice, render_cursor, render_hit_feedback, render_play_hud,
    render_settings_notice, reset_input,
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
CUT_DEAD_ZONE_PX = 6   # after a camera cut the pointer must move this far on
                       # an axis before the hold re-resolves; smaller motion is
                       # the hand settling, not a gesture


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
    # _save_session_settings and apply_render_overrides.
    return ModalSession(
        settings=settings, settings_path=path, settings_error=error,
        disk_render=settings.render,
        save_directory=save_dir() if save_directory is None else save_directory,
    )


def configure_session_input(session, input_buffer):
    try:
        configure_input(input_buffer, session.settings)
    except ValueError as exc:
        session.settings = default_settings()
        session.settings_error = (
            f"Could not load settings from {session.settings_path}: {exc}"
        )
        configure_input(input_buffer, session.settings)


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


def continue_available(session):
    # M4a2 save/load replaces this with a real check of the save slots.
    return False


def open_startup_menu(game, session):
    game.close_modal()
    game.open_modal(OpenStartupMenu())
    session.booted_via_menu = True
    session.reset_for(game.active_modal)


def _credits_entry(game):
    # AITD1.cpp:159 Lire(CVars[TEXTE_CREDITS] + 1, ...)
    return game.cvars[game.profile.cvar_index("TEXTE_CREDITS")] + 1


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


def inventory_hud_available(game):
    return (
        game.mode is GameMode.PLAY
        and game.active_modal is None
        and game.input_mode is InputMode.MOUSE
        and game.num_camera != -1
        and game.current_camera_target_actor != -1
        and bool(game.status_screen_allowed)
        and bool(game.inventory_count[game.current_inventory])
    )


def _hit_actor_ids(game):
    return {
        actor_idx for actor_idx, actor in enumerate(game.actors)
        if actor.hit_by != -1
    }


def _hit_feedback_rects(game, draw_list, actor_ids):
    """Presentation rectangles for latched hit actors still visible in PLAY."""
    if game.mode is not GameMode.PLAY or game.active_modal is not None:
        return ()
    rects = []
    for actor_idx, box in draw_list:
        if box is None or actor_idx not in actor_ids:
            continue
        x0, y0, x1, y1 = box
        rects.append(pygame.Rect(x0, y0, x1 - x0 + 1, y1 - y0 + 1))
    return tuple(rects)


def _pointer_actor_targets(game, draw_list, hero_idx):
    """Live, body-bearing world actors under the pointer, never the hero."""
    return [
        (idx, box) for idx, box in draw_list
        if idx != hero_idx
        and game.actors[idx].index_in_world >= 0
        and game.actors[idx].body_num != -1
    ]


def expand_actor_targets(targets, *, pad=2, minimum=12):
    """Return forgiving logical rectangles without changing visible bounds."""
    logical_frame = pygame.Rect(0, 0, 320, 200)
    expanded = []
    for actor_idx, box in targets:
        if box is None:
            continue
        x0, y0, x1, y1 = box
        target = pygame.Rect(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        target.inflate_ip(2 * pad, 2 * pad)
        target.inflate_ip(
            max(0, minimum - target.width),
            max(0, minimum - target.height),
        )
        target.clamp_ip(logical_frame)
        expanded.append((actor_idx, target))
    return expanded


def resolve_play_click(game, floor, logical_pos, draw_list):
    """Resolve inventory, attack, target, push, walk, or blocked plus its payload.

    One resolver behind both the cursor and the click, so hover feedback cannot
    advertise something different from what clicking does. kind is "inventory"
    (the HUD button), "attack" (a combat target with a usable in-hand weapon),
    "target" (an interactable object), "push" (a hold-required scripted
    actor), "walk" (a floor point we can head for), or "blocked" (nothing to
    do, payload None).
    """
    from PyAitD.engine.script.interaction import (
        can_strike, hold_action_approach, is_combat_target,
        is_hold_action_target,
    )
    from PyAitD.app.ui import PlayLayout
    from PyAitD.engine.space.world import room_delta

    if (logical_pos is None or game.active_modal is not None
            or game.input_mode is not InputMode.MOUSE or game.num_camera == -1):
        return ("blocked", None)
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1:
        return ("blocked", None)
    if (inventory_hud_available(game)
            and PlayLayout.INVENTORY_HIT.collidepoint(logical_pos)):
        return ("inventory", None)

    hero = game.actors[hero_idx]
    agent = agent_extent(hero)
    targets = _pointer_actor_targets(game, draw_list, hero_idx)
    actor_idx = pick_actor(logical_pos, targets)
    if actor_idx is None:
        actor_idx = pick_actor(logical_pos, expand_actor_targets(targets))
    if actor_idx is not None and is_combat_target(game, actor_idx):
        if not can_strike(game):
            # an empty hand or a hero already mid-swing is blocked, never a
            # fall-through to a floor walk: the click was aimed at the enemy
            return ("blocked", None)
        return ("attack", actor_idx)
    if actor_idx is not None:
        if not _is_interactable(game, actor_idx):
            if not is_hold_action_target(game, actor_idx):
                return ("blocked", None)
            payload = hold_action_approach(game, floor, hero_idx, actor_idx)
            return ("push", payload) if payload is not None else ("blocked", None)
        target = game.actors[actor_idx]
        dest_x, dest_z = target.room_x, target.room_z
        # An object's own cell is essentially never walkable (the hard col
        # standing for it, plus the agent inflation), so heading for its centre
        # means find_path always fails and the hero grinds into the wall
        # forever. Stand next to it instead, on the side we are coming from.
        mesh = game.nav_meshes.mesh_for(floor, target.room, agent)
        if mesh is not None:
            # The mesh is in the TARGET's room frame, so the approach bias has
            # to be too -- each room has its own origin. Re-frame the hero the
            # way gere_dec re-frames a moving actor: room_delta with FITD's
            # asymmetric signs (x minus, z plus).
            from_x, from_z = hero.room_x, hero.room_z
            if hero.room != target.room:
                dx, _dy, dz = room_delta(game, hero.room, target.room)
                from_x, from_z = from_x - dx, from_z + dz
            # Two stages, because the visibility filter is a preference and
            # never a veto: prefer an approach cell the camera can see, but a
            # camera that can see none must not make the object unreachable.
            # If both searches come up empty the destination stays the
            # object's own centre -- the fall-through this branch has always
            # had, and never `blocked`: refusing here made every object click
            # in a room whose cells the filter rejected unusable.
            spot = approach_cell(
                mesh, dest_x, dest_z, from_x, from_z,
                accept=visible_accept(
                    floor, hero.room, game.num_camera, target.room,
                    viewed_floor_y(floor, hero.room, target.room, hero.world_y), agent,
                ),
            )
            if spot is None:
                spot = approach_cell(mesh, dest_x, dest_z, from_x, from_z)
            if spot is not None:
                dest_x, dest_z = spot
        return (
            "target",
            (dest_x, dest_z, target.room, target.index_in_world),
        )

    picked = pick_floor_any_room(
        logical_pos, floor, hero.room, game.num_camera, hero.world_y, agent=agent,
    )
    if picked is None:
        return ("blocked", None)
    dest_x, dest_z, dest_room = picked
    mesh = game.nav_meshes.mesh_for(floor, dest_room, agent)
    # A mesh with no walkable cell at all is the spec's degraded mode (case 1):
    # keep the click and let direct steering handle it. A blocked cell inside a
    # real mesh snaps, and only an unsnappable one is refused.
    if mesh is not None and mesh.walkable.any():
        snapped = nearest_walkable(
            mesh, dest_x, dest_z,
            accept=snap_accept(
                floor, hero.room, game.num_camera, dest_room,
                viewed_floor_y(floor, hero.room, dest_room, hero.world_y),
                logical_pos, agent,
            ),
        )
        if snapped is None:
            return ("blocked", None)
        dest_x, dest_z = snapped
    return ("walk", (dest_x, dest_z, dest_room, -1))


def route_play_click(
        game, session, floor, logical_pos, draw_list, input_buffer=None,
):
    """Route one resolved PLAY click; HUD and world share the resolver."""
    from PyAitD.engine.script.interaction import apply_click_intent, attack_in_hand

    _stamp_press(game, input_buffer)
    kind, payload = resolve_play_click(game, floor, logical_pos, draw_list)
    if kind == "inventory":
        if input_buffer is not None:
            # a press resolving to anything but walk/target spends the hold
            # (spec Non-goals: no resuming a follow after a strike without a
            # fresh press) -- generalised past attack to cover every
            # press-only kind, inventory included
            input_buffer.follow_spent = True
        route_command(
            game, session, Command.OPEN_INVENTORY, input_buffer,
        )
        return
    if kind == "attack":
        # attack_in_hand only validates, stops and faces. The strike itself is
        # published by the fixed-tick input snapshot, so the accepted target is
        # latched into the application-owned buffer here and nowhere else.
        if input_buffer is not None:
            # spends the hold regardless of whether the target was accepted:
            # the press still resolved to "attack", not walk/target
            input_buffer.follow_spent = True
        if attack_in_hand(game, payload) and input_buffer is not None:
            input_buffer.mouse_attack_target = payload
            input_buffer.mouse_attack_ticks = 0
        return
    intent = game.nav_intent
    if intent is not None and intent.requires_hold:
        return
    if kind == "blocked":
        return
    dest_x, dest_z, room, object_idx = payload
    apply_click_intent(
        game, dest_x, dest_z, room, target_object_idx=object_idx,
        requires_hold=(kind == "push"),
        run=input_buffer is not None and input_buffer.pointer_run,
    )
    if input_buffer is not None:
        # a walk or target press opens a held pointer follow (follow_pointer
        # compares later resolutions against this); a push is latched and
        # never re-resolved, so it leaves no latch behind and spends the
        # hold -- its requires_hold intent can die mid-hold (arrival,
        # give-up), and the still-held button must not resume the follow
        input_buffer.follow_last = payload if kind != "push" else None
        input_buffer.follow_pos = logical_pos if kind != "push" else None
        input_buffer.follow_camera = game.num_camera if kind != "push" else None
        input_buffer.follow_settle_origin = None
        input_buffer.follow_spent = kind == "push"


def _stamp_press(game, input_buffer):
    """Decide whether this press is the second half of a double press.

    Timed on game.timer, so the window stops counting while a modal has the
    game paused, and against the mouse's own DOUBLE_PRESS_TICKS rather than
    the keyboard's much shorter double-tap window -- see the constant for why
    the two gestures do not share a number. Every PLAY press is stamped, not
    just the walks: two presses are two presses whatever each one turned out
    to resolve to.
    """
    if input_buffer is None:
        return
    previous = input_buffer.last_press_tick
    input_buffer.pointer_run = (
        previous is not None and game.timer - previous < DOUBLE_PRESS_TICKS
    )
    input_buffer.last_press_tick = game.timer


def follow_pointer(game, session, floor, logical_pos, draw_list, input_buffer):
    """Held pointer follow: re-aim the hero at whatever the held pointer
    resolves to, once per frame in which it moved
    (docs/superpowers/specs/2026-08-26-held-pointer-follow-design.md).

    The movement gate is what makes a camera cut survivable. A pixel means a
    different world point under every camera -- in the attic's five, the same
    pixel is up to 10,000 units apart -- so re-resolving a still pointer at a
    cut sends the hero somewhere nobody pointed at, and where the new camera
    cannot pick that pixel at all it resolves `blocked` and stops the hero
    dead until the hand moves. Neither is a gesture the player made. Gating on
    input_buffer.follow_pos costs nothing elsewhere: with the camera unchanged
    a still pointer re-resolves to the same payload anyway.

    A pointer that DID move is not automatically safe either: the same hand
    settling after a cut nudges the pointer a pixel or two without the player
    aiming anywhere. input_buffer.follow_camera records the slot follow_pos
    was resolved under, so a mismatch against game.num_camera means a cut just
    happened. From there, input_buffer.follow_settle_origin pins the pointer
    position at the moment the cut was noticed, and motion within
    CUT_DEAD_ZONE_PX of it on either axis (Chebyshev) is treated as settling,
    not a gesture: the destination holds and neither follow_pos nor
    follow_camera advance. Only once the pointer clears the zone does
    follow_settle_origin reset to None and resolution proceed against the new
    camera.

    The resolution is compared against input_buffer.follow_last, never the
    live intent: the engine clears an intent when the follower arrives or
    gives up, and _push_into_target re-aims a target intent at the object
    itself, so an unchanged resolution must never be re-issued within one
    hold. That one rule is both the arrival one-shot latch and the "a dead
    click is not retried until the pointer moves" rule. A transition frame
    (num_camera == -1) is skipped rather than resolved: the resolver reports
    blocked there, which would stop the hero for a tick at every room change.
    """
    from PyAitD.engine.script.interaction import apply_click_intent, cancel_nav_intent

    if (game.active_modal is not None or game.mode is not GameMode.PLAY
            or game.input_mode is not InputMode.MOUSE or session.cutscene
            or game.num_camera == -1
            or not input_buffer.pointer_held or not input_buffer.focused
            or input_buffer.mouse_attack_target is not None
            # a press that resolved to attack/inventory/push spends the
            # hold: no follow starts from it even after the underlying latch
            # (mouse_attack_target, a push's requires_hold intent) dies
            # mid-hold -- only release-and-a-fresh-press clears this
            or input_buffer.follow_spent):
        return
    intent = game.nav_intent
    if intent is not None and intent.requires_hold:
        return  # a latched push ignores pointer motion until release
    if logical_pos == input_buffer.follow_pos:
        return  # a still pointer means what it meant last frame
    if (input_buffer.follow_camera is not None
            and input_buffer.follow_camera != game.num_camera):
        # a cut: the pixel now means something else, but the hand has not
        # said so. Keep the destination until the pointer leaves the dead
        # zone around where it was when the cut landed.
        if input_buffer.follow_settle_origin is None:
            input_buffer.follow_settle_origin = (
                input_buffer.follow_pos
                if input_buffer.follow_pos is not None else logical_pos
            )
        ox, oy = input_buffer.follow_settle_origin
        if (abs(logical_pos[0] - ox) <= CUT_DEAD_ZONE_PX
                and abs(logical_pos[1] - oy) <= CUT_DEAD_ZONE_PX):
            return
    # Every path that advances follow_camera closes the dead zone with it,
    # the branch above and the fall-through alike: the camera can cut BACK to
    # the slot the follow was resolved under while the zone is still open,
    # and a settle origin left behind then draws the cursor's dashed ring for
    # the rest of the hold.
    input_buffer.follow_settle_origin = None
    input_buffer.follow_pos = logical_pos
    input_buffer.follow_camera = game.num_camera
    kind, payload = resolve_play_click(game, floor, logical_pos, draw_list)
    if kind in ("walk", "target"):
        if payload == input_buffer.follow_last:
            return
        dest_x, dest_z, room, object_idx = payload
        # the run belongs to the hold, not to the destination: aiming
        # somewhere else without releasing keeps the hero running
        apply_click_intent(
            game, dest_x, dest_z, room, target_object_idx=object_idx,
            run=input_buffer.pointer_run,
        )
        input_buffer.follow_last = payload
    elif kind == "blocked":
        if intent is not None:
            cancel_nav_intent(game)
        input_buffer.follow_last = None
    # inventory, attack and push need a fresh press: nothing to follow


def _cancel_pointer_invalidation(game, event, input_buffer):
    """Button-up and focus loss end the hold, and every intent is hold-bound."""
    invalidated = (
        event.type == pygame.MOUSEBUTTONUP and event.button == 1
    ) or event.type == pygame.WINDOWFOCUSLOST
    if not invalidated:
        return False
    return _cancel_follow(game, input_buffer)


def _drop_destination(game, input_buffer):
    """Forget where this hold was heading and which pixel said so, and drop
    the intent that was carrying it. True when an intent was live.

    The whole of what ending a *destination* means; what ending the *hold*
    additionally means is the two lines in _cancel_follow below. Keeping them
    apart is what stops the next per-hold buffer field from being cleared in
    one path and silently forgotten in the other. The buffer is optional only
    for callers that own no buffer.
    """
    from PyAitD.engine.script.interaction import cancel_nav_intent
    if input_buffer is not None:
        input_buffer.follow_last = None
        input_buffer.follow_pos = None
        input_buffer.follow_camera = None
        input_buffer.follow_settle_origin = None
    if game.nav_intent is None:
        return False
    cancel_nav_intent(game)
    return True


def _cancel_follow(game, input_buffer):
    """End the hold itself: the destination, plus everything that belonged to
    the press that opened it.

    Clearing follow_spent here is what makes "released and pressed again"
    work: _cancel_pointer_invalidation runs this on MOUSEBUTTONUP and on
    focus loss, so a spent hold cannot outlive the release that ends it. The
    run goes the same way, while last_press_tick survives -- it is what the
    *next* press is measured against.
    """
    if input_buffer is not None:
        input_buffer.follow_spent = False
        input_buffer.pointer_run = False
    return _drop_destination(game, input_buffer)


def _rebase_follow(game, input_buffer):
    """Drop a destination the new floor cannot mean, keeping the hold alive.

    A floor change invalidates the intent -- its `room` indexes the floor that
    was just unloaded -- but the button never came up, so ending the hold here
    would stop the hero dead on the stairs and demand a fresh press. The
    cleared follow_pos is the one case where a still pointer is re-resolved:
    the old destination is gone, so there is nothing left to hold on to.
    """
    return _drop_destination(game, input_buffer)


def _play_cursor_state(game, floor, hover, draw_list, input_buffer):
    """(kind, payload) the cursor should show for `hover`: a latched push
    stays "push" whatever the pointer drifts over; otherwise the resolver."""
    intent = getattr(game, "nav_intent", None)
    if (input_buffer.pointer_held and intent is not None
            and intent.requires_hold):
        return "push", None
    return resolve_play_click(game, floor, hover, draw_list)


def _play_cursor_kind(game, floor, hover, draw_list, input_buffer):
    return _play_cursor_state(game, floor, hover, draw_list, input_buffer)[0]


def _marker_for(game, floor, payload):
    """Project a (dest_x, dest_z, room, object_idx) payload to the logical
    frame under the camera on screen, or None."""
    from PyAitD.engine.nav.picking import project_room_point, viewed_floor_y
    if payload is None or game.num_camera == -1:
        return None
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1:
        return None
    hero = game.actors[hero_idx]
    dest_x, dest_z, room, _object_idx = payload
    y = viewed_floor_y(floor, hero.room, room, hero.world_y)
    return project_room_point(floor, hero.room, game.num_camera, room, dest_x, y, dest_z)


def _intent_marker(game, floor):
    """Where the live intent is heading, on screen, or None."""
    intent = getattr(game, "nav_intent", None)
    if intent is None:
        return None
    return _marker_for(game, floor, (intent.dest_x, intent.dest_z, intent.room, -1))


def _render_play_cursor(game, floor, hover, draw_list, input_buffer, painter):
    """The PLAY cursor with its feedback: the live destination, a preview of
    where a press would head while nothing is held, the press ring, and the
    dashed ring while a cut's dead zone is open."""
    kind, payload = _play_cursor_state(game, floor, hover, draw_list, input_buffer)
    destination = _intent_marker(game, floor)
    preview = None
    if (not input_buffer.pointer_held and destination is None
            and kind in ("walk", "target")):
        preview = _marker_for(game, floor, payload)
    render_cursor(
        painter, hover, kind,
        held=input_buffer.pointer_held,
        settling=input_buffer.follow_settle_origin is not None,
        destination=destination,
        preview=preview,
    )


def _is_interactable(game, actor_idx):
    from PyAitD.engine.script.game import AF_FOUNDABLE
    actor = game.actors[actor_idx]
    if actor.index_in_world < 0:
        return False
    if actor.object_type & AF_FOUNDABLE:
        return True
    return game.world_objects[actor.index_in_world].found_life != -1


def _inventory_view(game, session):
    from PyAitD.engine.script.interaction import inventory_actions, inventory_items
    object_ids = inventory_items(game)
    selected = object_ids[min(session.inventory.object_cursor, len(object_ids) - 1)]
    return object_ids, inventory_actions(game, selected)


def _game_over_ready(session, effect):
    # LM_GAME_OVER's accessibility gate: input acceptance (_route_game_over_command,
    # route_mouse) and the "Click to restart" overlay (render_active_mode) must
    # agree on the same wall-clock wait, so the overlay never invites a click
    # that the router would still swallow.
    return session.elapsed_ms >= effect.delay_units * 1000 // 60


def _route_game_over_command(game, session, modal_command):
    # LM_GAME_OVER's accessibility gate: ignore ACCEPT/CANCEL (and, via the
    # caller's OPEN_INVENTORY-as-ACCEPT translation, OPEN_INVENTORY too) until
    # the wall-clock wait has elapsed, so a startled keypress cannot restart
    # the session before the player has even registered dying.
    ready = _game_over_ready(session, game.active_modal)
    if ready and modal_command in (Command.ACCEPT, Command.CANCEL):
        game.restart_requested = True
    return True


# The only render.RenderOptions fields the CONFIG menu can actually change
# (SystemMenuPage.GRAPHICS's Scale/Shading/Filter/AA/Smoothing rows, via
# GRAPHICS_CYCLES, and SystemMenuPage.REALISM's Lighting/Shadows/Realism/
# Integration/Motion/Occlusion rows, via REALISM_CYCLES, both in
# ui.reduce_system_menu).
# `texture_dir` has no menu row at all, so it is never in this set and a save
# can never pick it up from the in-memory, possibly CLI-set,
# session.settings.render.
_MENU_RENDER_FIELDS = ("scale", "shading", "background_filter", "lighting", "msaa", "realism", "smoothing", "shadows", "integration", "motion", "occlusion", "atmosphere")


def _persisted_render(session):
    """The render payload `_save_session_settings` actually writes: the
    on-disk baseline (`session.disk_render`, captured before any CLI
    override was applied) with only the fields the player explicitly
    changed via a CONFIG menu cycle this session (`session.render_touched`)
    overlaid on top.

    Without this, saving *any* setting (even one unrelated to rendering,
    like Sticky Action) would write session.settings.render wholesale --
    and that field already carries whatever apply_render_overrides baked in
    from argv at boot, CLI-only texture_dir included. apply_render_overrides'
    docstring promises those overrides are session-only; this is what keeps
    that promise true past the first save.
    """
    overrides = {
        field_name: getattr(session.settings.render, field_name)
        for field_name in session.render_touched
    }
    return replace(session.disk_render, **overrides)


def _save_session_settings(session):
    if not session.settings_dirty:
        return True
    if session.settings_path is None:
        session.settings_dirty = False
        return True
    settings_to_save = replace(session.settings, render=_persisted_render(session))
    error = save_settings(settings_to_save, session.settings_path)
    if error is not None:
        session.settings_error = error
        return False
    session.settings_dirty = False
    return True


def _available_slots(session):
    """The slot kinds a LOAD page may offer: a missing file disables its
    row, a present one enables it (a corrupt file still loads-then-fails
    through the visible error route)."""
    if session.save_directory is None:
        return frozenset()
    return frozenset(
        kind for kind in ("manual", "quick")
        if slot_path(session.save_directory, kind).exists()
    )


def _write_save(game, session, kind):
    """Snapshot and write one slot; failures surface as the dismissible
    runtime notice and never touch the live game."""
    if session.save_directory is None:
        session.runtime_error = "Could not save: no save directory is configured"
        return
    settings_to_save = replace(session.settings, render=_persisted_render(session))
    payload = snapshot_game(game, settings_payload(settings_to_save))
    error = write_slot(slot_path(session.save_directory, kind), payload)
    if error is not None:
        session.runtime_error = error


def _manual_save(game, session, kind):
    # Allowed only at a stable system-menu boundary: while a LIFE
    # continuation or a platform effect is queued the world is mid-script,
    # and a snapshot of it would restore into that mid-script state.
    if game.life_stack or game.immediate_effects:
        session.runtime_error = "Could not save: a script is still running"
        return
    _write_save(game, session, kind)


def _request_quick_save(session):
    # Quick Save closes the menu (the result carries close=True) and defers
    # the write to the first stable end-of-PLAY-tick boundary; run() owns
    # the commit so the snapshot can never land mid-tick.
    session.quick_save_requested = True


def _commit_quick_save(game, session):
    session.quick_save_requested = False
    _write_save(game, session, "quick")


def _request_load(game, session, kind):
    """Read and validate the slot; a good payload stages the atomic
    replacement run() performs on this same frame. A bad one leaves the
    live game untouched and raises the dismissible notice."""
    if session.save_directory is None:
        session.runtime_error = "Could not load: no save directory is configured"
        return
    payload, error = read_slot(
        slot_path(session.save_directory, kind), game._data_dir, game.profile,
    )
    if error is not None:
        session.runtime_error = error
        return
    session.pending_load = payload


def _load_branch(game, renderer, session, input_buffer=None):
    """The atomic load replacement: rebuild the game from the staged payload
    and hand run() every loop local that referenced the old game, exactly
    like _restart_branch. A failure consumes the payload, raises the notice,
    and leaves the menu (and everything else) untouched."""
    if session.pending_load is None:
        return None
    payload = session.pending_load
    session.pending_load = None
    _take_over_play_input(game, session, input_buffer)
    trace = game.trace
    try:
        new_game, settings_dict = restore_game(game._data_dir, game.profile, payload)
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
    input_buffer = InputBuffer()
    configure_session_input(session, input_buffer)
    accumulator = 0
    draw_list = []
    hover = None
    game.num_camera = game.new_num_camera
    game.flag_init_view = 0
    new_resolver = _resolver_for(game.assets, texture_dir)
    scene_frame, draw_list = _scene_frame(game, floor, renderer, new_resolver)
    last = pygame.time.get_ticks()
    return (
        game, floor, session, input_buffer, accumulator,
        draw_list, hover, scene_frame, last, 0, new_resolver,
    )


def _apply_system_result(game, session, input_buffer, result, renderer=None):
    if result is None:
        return True
    if result.settings is not None:
        old_render, new_render = session.settings.render, result.settings.render
        render_changed = new_render != old_render
        if render_changed:
            # Only a menu render-field cycle can produce a render diff here
            # (see _MENU_RENDER_FIELDS): record exactly which field(s)
            # changed so a later save persists only those, not whatever
            # else happens to be sitting in session.settings.render.
            touched = set(session.render_touched)
            touched.update(
                field_name for field_name in _MENU_RENDER_FIELDS
                if getattr(old_render, field_name) != getattr(new_render, field_name)
            )
            session.render_touched = frozenset(touched)
        session.settings = result.settings
        session.settings_dirty = True
        configure_input(input_buffer, session.settings)
        if render_changed and renderer is not None:
            renderer.set_options(session.settings.render)
    saved = _save_session_settings(session) if result.save else True
    if result.quit and not saved:
        return True
    if result.save_slot is not None:
        _manual_save(game, session, result.save_slot)
    if result.quick_save:
        _request_quick_save(session)
    if result.load_slot is not None:
        _request_load(game, session, result.load_slot)
    if result.close:
        reset_input(input_buffer)
        game.close_modal()
    if result.quit:
        reset_input(input_buffer)
        return False
    return True


def _capture_keydown(event, game, session, input_buffer):
    from PyAitD.engine.script.effects import OpenSystemMenu
    from PyAitD.app.ui import canonical_key_name, capture_system_key
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
    return True, _apply_system_result(game, session, input_buffer, result)


def _take_over_play_input(game, session, input_buffer) -> None:
    """Atomically drop transient PLAY input before a modal takes control."""
    if input_buffer is not None:
        reset_input(input_buffer)
    from PyAitD.engine.script.interaction import cancel_nav_intent
    cancel_nav_intent(game)
    # route_hover owns presenter-only hover and deliberately does not own the
    # modal lifecycle: ModalSession.reset_for remains at the open/render seams.
    route_hover(game, session, None)


def route_command(game, session, command, input_buffer=None, renderer=None):
    from PyAitD.engine.script.effects import (
        GameMode, GameOver, OpenInventory, OpenSystemMenu, ReadText, ShowFound,
        ShowPicture,
    )
    from PyAitD.engine.script.interaction import (
        apply_found_result, apply_inventory_result, apply_reading_result,
    )
    from PyAitD.app.ui import (
        Command, ReadingResult, reading_pages, reduce_found, reduce_inventory,
        reduce_reading, reduce_system_menu,
    )
    if session.cutscene:
        # PlayWorld(allowSystemMenu=0): every command is a skip, never a
        # route into PLAY's own commands (CANCEL opening the system menu,
        # OPEN_INVENTORY, TOGGLE_INPUT_MODE) -- mainLoop.cpp:71-89. Checked
        # first so that claim holds for every command, TOGGLE_INPUT_MODE
        # included -- defence-in-depth only: shell.run's event-pump swallow
        # already marks skip_cutscene and `continue`s for every KEYDOWN
        # while session.cutscene, so no Command -- this one included -- can
        # actually reach route_command while a cutscene is active; this
        # branch exists for callers that invoke route_command directly
        # (tests, and any future caller bypassing the pump).
        session.skip_cutscene = True
        return True

    if command is Command.TOGGLE_INPUT_MODE:
        from PyAitD.engine.script.interaction import cancel_nav_intent, sync_player_track_mode
        game.input_mode = (
            InputMode.KEYBOARD if game.input_mode is InputMode.MOUSE else InputMode.MOUSE
        )
        cancel_nav_intent(game)
        sync_player_track_mode(game)
        if input_buffer is not None:
            reset_input(input_buffer)
        return True

    if game.mode is GameMode.PLAY:
        if command is Command.CANCEL:
            game.open_modal(OpenSystemMenu())
            _take_over_play_input(game, session, input_buffer)
            session.reset_for(game.active_modal)
            return True
        if command is Command.OPEN_INVENTORY and game.status_screen_allowed:
            if game.inventory_count[game.current_inventory]:
                game.open_modal(OpenInventory())
                _take_over_play_input(game, session, input_buffer)
                session.reset_for(game.active_modal)
        return True

    modal_command = Command.ACCEPT if command is Command.OPEN_INVENTORY else command
    if isinstance(game.active_modal, OpenSystemMenu):
        # the presenter resets where the menu is opened (the PLAY CANCEL
        # branch above), not per dispatch: a staged page/cursor/capture must
        # survive every routed command until the menu closes
        route_hover(game, session, None)
        result = reduce_system_menu(
            session.system_menu, modal_command, session.settings,
            _available_slots(session),
        )
        return _apply_system_result(game, session, input_buffer, result, renderer=renderer)

    session.reset_for(game.active_modal)
    # A keyboard command makes the owning keyboard cursor authoritative until
    # a later MOUSEMOTION establishes a new preview.
    route_hover(game, session, None)
    if isinstance(game.active_modal, ShowTitle):
        from PyAitD.app.startup import credits_page_count, reduce_title
        page_count = credits_page_count(game.assets, _credits_entry(game))
        if reduce_title(session.title, modal_command, page_count=page_count) is not None:
            open_startup_menu(game, session)
        return True
    if isinstance(game.active_modal, OpenStartupMenu):
        from PyAitD.app.startup import reduce_startup_menu
        result = reduce_startup_menu(session.startup, modal_command, continue_enabled=continue_available(session))
        return _apply_startup_result(game, session, input_buffer, result)
    if isinstance(game.active_modal, ChooseCharacter):
        from PyAitD.app.ui import reduce_character_select
        result = reduce_character_select(session.character, modal_command)
        if result is not None:
            if result.hero is not None:
                session.pending_hero = result.hero
            if result.quit:
                if session.booted_via_menu:
                    open_startup_menu(game, session)
                    return True
                return False
        return True
    if isinstance(game.active_modal, ShowFound):
        result = reduce_found(
            session.found, modal_command,
            forced_refuse=game.active_modal.forced_refuse,
        )
        if result is not None:
            apply_found_result(game, result)
        return True
    if isinstance(game.active_modal, OpenInventory):
        object_ids, action_ids = _inventory_view(game, session)
        result = reduce_inventory(
            session.inventory, modal_command,
            object_ids=object_ids, action_ids=action_ids,
        )
        if result is not None:
            apply_inventory_result(game, result)
        return True
    if isinstance(game.active_modal, ReadText):
        page_count = len(reading_pages(game.active_modal, game.assets))
        result = reduce_reading(session.reading, modal_command, page_count=page_count)
        if result is not None:
            apply_reading_result(game, result)
        return True
    if isinstance(game.active_modal, ShowPicture):
        if modal_command in (Command.ACCEPT, Command.CANCEL):
            apply_reading_result(game, ReadingResult(True))
        return True
    if isinstance(game.active_modal, GameOver):
        return _route_game_over_command(game, session, modal_command)
    raise RuntimeError(f"unroutable modal {type(game.active_modal).__name__}")


def _apply_startup_result(game, session, input_buffer, result):
    if result is None:
        return True
    if result.new_game:
        game.close_modal()
        game.open_modal(ChooseCharacter())
        session.reset_for(game.active_modal)
        if input_buffer is not None:
            reset_input(input_buffer)
        return True
    if result.quit:
        if input_buffer is not None:
            reset_input(input_buffer)
        return False
    return True   # continue_game cannot be produced while continue_available is False


def route_mouse(game, session, logical_pos, input_buffer=None, renderer=None):
    from PyAitD.engine.script.effects import (
        ChooseCharacter, CutsceneFinished, GameOver, OpenInventory, OpenSystemMenu,
        ReadText, ShowFound, ShowPicture,
    )
    from PyAitD.engine.script.interaction import (
        apply_found_result, apply_inventory_result, apply_reading_result,
    )
    from PyAitD.app.ui import (
        CharacterPhase, ReadingResult, hit_test_character, hit_test_found,
        hit_test_inventory, hit_test_reading, hit_test_system_menu,
        reading_pages, reduce_system_menu, turn_page,
    )
    from PyAitD.app.ui import SystemMenuPage, pick_system_key
    if logical_pos is None or game.active_modal is None:
        return True
    effect = game.active_modal
    if isinstance(effect, CutsceneFinished):
        # defence-in-depth only: whenever active_modal is CutsceneFinished,
        # session.cutscene is still True (only _cutscene_end_branch clears
        # it), so shell.run's event-pump swallow already intercepts every
        # left click before it can reach route_mouse -- this branch exists
        # for callers that invoke route_mouse directly (tests, and any
        # future caller bypassing the pump).
        session.skip_cutscene = True
        return True
    if isinstance(effect, OpenSystemMenu):
        # same presenter lifetime as route_command: reset at open, never per
        # click, so a staged page/cursor/capture survives mouse routing
        hit = hit_test_system_menu(logical_pos, session.system_menu)
        if hit is None:
            return True
        if session.system_menu.page is SystemMenuPage.KEY_PICK:
            result = pick_system_key(session.system_menu, session.settings, hit)
            return _apply_system_result(game, session, input_buffer, result, renderer=renderer)
        old_page = session.system_menu.page
        session.system_menu.cursor = hit
        result = reduce_system_menu(
            session.system_menu, Command.ACCEPT, session.settings,
            _available_slots(session),
        )
        if session.system_menu.page is not old_page:
            session.system_menu.hover = None
        return _apply_system_result(game, session, input_buffer, result, renderer=renderer)
    session.reset_for(effect)
    if isinstance(effect, ShowTitle):
        from PyAitD.app.startup import credits_page_count, hit_test_title, reduce_title
        if hit_test_title(logical_pos):
            page_count = credits_page_count(game.assets, _credits_entry(game))
            if reduce_title(session.title, Command.ACCEPT, page_count=page_count) is not None:
                open_startup_menu(game, session)
        return True
    if isinstance(effect, OpenStartupMenu):
        from PyAitD.app.startup import hit_test_startup, reduce_startup_menu
        enabled = continue_available(session)
        hit = hit_test_startup(logical_pos, continue_enabled=enabled)
        if hit is None:
            return True
        session.startup.cursor = hit
        result = reduce_startup_menu(session.startup, Command.ACCEPT, continue_enabled=enabled)
        return _apply_startup_result(game, session, input_buffer, result)
    if isinstance(effect, ChooseCharacter):
        hit = hit_test_character(logical_pos, session.character)
        if hit is None:
            return True
        if session.character.phase is CharacterPhase.PORTRAITS:
            session.character.choice = hit
            session.character.phase = CharacterPhase.STORY
        else:
            # the story page is a whole-frame confirm; the hero comes from the
            # selected portrait, not the click position -- the same mapping
            # reduce_character_select uses (choice 0 left Emily -> hero 1,
            # choice 1 right Carnby -> hero 0)
            session.pending_hero = 1 if session.character.choice == 0 else 0
        return True
    if isinstance(effect, ShowFound):
        result = hit_test_found(logical_pos)
        if result is not None:
            apply_found_result(game, result)
        return True
    if isinstance(effect, OpenInventory):
        object_ids, action_ids = _inventory_view(game, session)
        old_subview = session.inventory.choosing_action
        result = hit_test_inventory(
            logical_pos, session.inventory, object_ids, action_ids,
        )
        if session.inventory.choosing_action is not old_subview:
            session.inventory.hover = None
        if result is not None:
            apply_inventory_result(game, result)
        return True
    if isinstance(effect, ReadText):
        page_count = len(reading_pages(effect, game.assets))
        result = hit_test_reading(
            logical_pos, session.reading.page, page_count,
        )
        if result is None:
            return True
        if result.page_delta:
            turn_page(session.reading, result.page_delta, page_count)
            session.reading.hover = None
            return True
        apply_reading_result(game, result)
        return True
    if isinstance(effect, ShowPicture):
        apply_reading_result(game, ReadingResult(True))
        return True
    if isinstance(effect, GameOver):
        # the whole 320x200 logical frame is the target: no hit rectangle, no
        # precision requirement -- any left click once the wait has elapsed
        ready = _game_over_ready(session, effect)
        if ready:
            game.restart_requested = True
        return True
    raise RuntimeError(f"unroutable modal {type(effect).__name__}")


def route_hover(game, session, logical_pos):
    """Update only the active modal presenter's mouse preview."""
    from PyAitD.engine.script.effects import (
        ChooseCharacter, OpenInventory, OpenSystemMenu, ReadText, ShowFound,
    )
    from PyAitD.app.ui import (
        hit_test_character, hit_test_found, hit_test_inventory, hit_test_reading,
        hit_test_system_menu, reading_pages,
    )

    effect = game.active_modal
    if effect is None:
        return
    if isinstance(effect, ShowFound):
        session.found.hover = hit_test_found(logical_pos) if logical_pos is not None else None
    elif isinstance(effect, OpenInventory):
        if logical_pos is None:
            session.inventory.hover = None
        else:
            object_ids, action_ids = _inventory_view(game, session)
            session.inventory.hover = hit_test_inventory(
                logical_pos, session.inventory, object_ids, action_ids, preview=True,
            )
    elif isinstance(effect, ReadText):
        session.reading.hover = (
            hit_test_reading(
                logical_pos, session.reading.page, len(reading_pages(effect, game.assets)),
            ) if logical_pos is not None else None
        )
    elif isinstance(effect, ChooseCharacter):
        session.character.hover = (
            hit_test_character(logical_pos, session.character)
            if logical_pos is not None else None
        )
    elif isinstance(effect, OpenSystemMenu):
        session.system_menu.hover = (
            hit_test_system_menu(logical_pos, session.system_menu)
            if logical_pos is not None else None
        )
    elif isinstance(effect, OpenStartupMenu):
        from PyAitD.app.startup import hit_test_startup
        session.startup.hover = (
            hit_test_startup(logical_pos, continue_enabled=continue_available(session))
            if logical_pos is not None else None
        )


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
                           _available_slots(session))
    elif isinstance(effect, ChooseCharacter):
        # the selector owns the whole frame; the staged PLAY scene is never shown
        render_character_select(painter, session.character, game.assets, resolver)
    elif isinstance(effect, ShowTitle):
        from PyAitD.app.startup import render_title
        render_title(painter, session.title, game.assets, resolver or AssetResolver(game.assets, None),
                      session.elapsed_ms, _credits_entry(game))
    elif isinstance(effect, OpenStartupMenu):
        from PyAitD.app.startup import render_startup_menu
        render_startup_menu(painter, session.startup, game.assets, continue_enabled=continue_available(session))
    elif isinstance(effect, ShowFound):
        world = game.world_objects[effect.object_idx]
        render_found(painter, effect, session.found, game.assets,
                     game.assets.system_text(world.found_name))
    elif isinstance(effect, OpenInventory):
        object_ids, action_ids = _inventory_view(game, session)
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
        render_game_over(painter, renderer.scene_thumbnail(), _game_over_ready(session, effect))
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
    new_game = init_game(data_dir, old_game.profile, hero=hero)
    new_game.input_mode = input_mode
    new_game.trace = trace
    from PyAitD.engine.script.interaction import sync_player_track_mode
    sync_player_track_mode(new_game)
    enter_floor_start(new_game, floor_start)
    new_game.floor_start = floor_start
    return new_game


def _boot_hero(game, renderer, session, input_buffer, hero, *, cutscene):
    """Build the replace tuple run() adopts: a fresh game for `hero`, staged
    on profile.intro_start (cutscene, allowSystemMenu=0, AITD1.cpp:352-361)
    or on the attic init_game already stages (profile.game_start). Shared by
    _hero_branch (character confirmation) and _cutscene_end_branch (the
    startGame(0, 0, 1) hand-over once the opening ends)."""
    from PyAitD.engine.script.game import start_game
    _take_over_play_input(game, session, input_buffer)
    try:
        new_game = init_game(game._data_dir, game.profile, hero=hero)
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
    input_buffer = InputBuffer()
    configure_session_input(new_session, input_buffer)
    # Staged by start_game: num_camera == -1, new_num_camera == 0. This
    # stages camera 0 exactly as FITD's InitView does after startGame -- the
    # same line init_game's own staging (game_start) relies on below.
    new_game.num_camera = new_game.new_num_camera
    new_game.flag_init_view = 0
    new_resolver = _resolver_for(new_game.assets, session.settings.render.texture_dir)
    scene_frame, draw_list = _scene_frame(new_game, new_floor, renderer, new_resolver)
    return (
        new_game, new_floor, new_session, input_buffer, 0,
        draw_list, None, scene_frame, pygame.time.get_ticks(), 0, new_resolver,
    )


def _hero_branch(game, renderer, session, input_buffer=None):
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
    return _boot_hero(game, renderer, session, input_buffer, session.pending_hero, cutscene=cutscene)


def _cutscene_end_branch(game, renderer, session, input_buffer=None):
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
    return _boot_hero(game, renderer, session, input_buffer, hero, cutscene=False)


def _restart_branch(game, renderer, session, input_buffer=None):
    # The atomic replace-game-and-floor step run() inlines each frame: a
    # successful restart hands back every loop local that referenced the old
    # game, so a single tuple assignment plus `continue` is enough to resume
    # the loop on the new session without a stray tick or a stale present.
    # Same resolver-reuse note as _hero_branch above.
    if not game.restart_requested:
        return None
    _take_over_play_input(game, session, input_buffer)
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
    input_buffer = InputBuffer()
    configure_session_input(session, input_buffer)
    accumulator = 0
    draw_list = []
    hover = None
    game.num_camera = game.new_num_camera
    game.flag_init_view = 0
    new_resolver = _resolver_for(game.assets, texture_dir)
    scene_frame, draw_list = _scene_frame(game, floor, renderer, new_resolver)
    last = pygame.time.get_ticks()
    return (
        game, floor, session, input_buffer, accumulator,
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
    input_buffer = InputBuffer()
    configure_session_input(session, input_buffer)
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
        actor_idx: last + HIT_FEEDBACK_MS for actor_idx in _hit_actor_ids(game)
    }
    while running:
        for event in pygame.event.get():
            # raw key capture owns KEYDOWN while the system menu is binding:
            # the event never reaches event_to_input, mouse routing, or the
            # menu reducer; KEYUP and focus events keep the ordinary path
            captured, capture_running = _capture_keydown(
                event, game, session, input_buffer,
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
            running = event_to_input(event, input_buffer, logical_pos) and running
            if (mirror_sink is not None
                    and event.type in (pygame.KEYDOWN, pygame.KEYUP)
                    and not bool(getattr(event, "repeat", False))
                    and game.mode is GameMode.PLAY
                    and game.active_modal is None
                    and game.input_mode is InputMode.KEYBOARD):
                control = input_buffer.bindings.get(event.key)
                if control is not None and control.name in MIRROR_KEYCODES:
                    if event.type == pygame.KEYDOWN:
                        mirror_sink.key_down(control.name)
                    else:
                        mirror_sink.key_up(control.name)
            _cancel_pointer_invalidation(game, event, input_buffer)
            if event.type == pygame.MOUSEMOTION:
                hover = input_buffer.pointer_pos
                if game.active_modal is not None:
                    route_hover(game, session, hover)
            elif event.type == pygame.WINDOWFOCUSLOST:
                hover = None
                if game.active_modal is not None:
                    route_hover(game, session, None)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                logical = input_buffer.pointer_pos
                if game.active_modal is None and game.mode is GameMode.PLAY:
                    # keyboard mode swallows play clicks (resolve_play_click
                    # returns "blocked"); the cursor is hidden there too and
                    # the HUD names the mode, so nothing advertises a click
                    # that does nothing
                    route_play_click(
                        game, session, floor, logical, draw_list, input_buffer,
                    )
                else:
                    running = route_mouse(
                        game, session, logical, input_buffer, renderer=renderer,
                    ) and running
        now = pygame.time.get_ticks()
        elapsed = min(now - last, 250)
        last = now
        was_play = game.mode is GameMode.PLAY
        if input_buffer.commands:
            command = input_buffer.commands.popleft()
            if session.cutscene:
                # defence-in-depth: unreachable in practice, since the
                # cutscene swallow above `continue`s on every KEYDOWN while
                # session.cutscene is True -- event_to_input, the only place
                # that appends to input_buffer.commands, never runs, so
                # commands cannot exist here while a cutscene is active. Kept
                # so this drain still does the right thing if that invariant
                # is ever weakened (e.g. a caller feeding input_buffer.commands
                # directly, as some tests do).
                pass
            elif ((session.settings_error is not None
                   or session.runtime_error is not None)
                    and command in (Command.ACCEPT, Command.OPEN_INVENTORY)):
                # same first refusal as the Dismiss click: ACCEPT and
                # OPEN_INVENTORY dismiss the notice instead of reaching the mode
                session.settings_error = None
                session.runtime_error = None
            else:
                running = route_command(
                    game, session, command, input_buffer, renderer=renderer,
                ) and running
        replaced = _hero_branch(game, renderer, session, input_buffer)
        if replaced is None:
            replaced = _cutscene_end_branch(game, renderer, session, input_buffer)
        if replaced is None:
            replaced = _restart_branch(game, renderer, session, input_buffer)
        if replaced is None:
            replaced = _load_branch(game, renderer, session, input_buffer)
        if replaced is not None:
            (
                new_game, new_floor, new_session, new_input_buffer,
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
            game, floor, session, input_buffer = (
                new_game, new_floor, new_session, new_input_buffer,
            )
            accumulator, draw_list, hover, scene_frame, last = (
                new_accumulator, new_draw_list, new_hover, new_scene_frame, new_last,
            )
            hit_feedback_deadlines = {
                actor_idx: last + HIT_FEEDBACK_MS
                for actor_idx in _hit_actor_ids(game)
            }
            continue
        if game.mode is GameMode.PLAY:
            accumulator += elapsed
            ticked = False
            while accumulator >= TICK_MS and game.mode is GameMode.PLAY:
                motion_prev = motion_snapshot(game)
                play_tick(game, floor, input_buffer)
                ticked = True
                for actor_idx in _hit_actor_ids(game):
                    hit_feedback_deadlines[actor_idx] = now + HIT_FEEDBACK_MS
                if game.mode is not GameMode.PLAY:
                    _take_over_play_input(game, session, input_buffer)
                accumulator -= TICK_MS
                if floor.number != game.current_floor:
                    floor = game.load_floor(game.current_floor)
                    # the intent's room indexes the old floor; the hold
                    # survives and the next frame re-resolves the held
                    # pointer against the new one, still hand or not
                    _rebase_follow(game, input_buffer)
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
                game, session, floor, input_buffer.pointer_pos, draw_list, input_buffer,
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
            # cross the boundary inside play_tick.  Command/pointer routes use
            # the same idempotent seam immediately when they open their modal.
            _take_over_play_input(game, session, input_buffer)
        hit_feedback_deadlines = {
            actor_idx: deadline
            for actor_idx, deadline in hit_feedback_deadlines.items()
            if deadline > now
        }
        painter = render_active_mode(game, session, renderer, resolver)
        render_hit_feedback(
            painter,
            _hit_feedback_rects(game, draw_list, hit_feedback_deadlines),
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
            _render_play_cursor(game, floor, hover, draw_list, input_buffer, painter)
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
    try:
        # The debug starts bypass the character selector, so --hero is the only
        # way to reach Emily's copy of a fixture; a normal boot still opens the
        # selector below and replaces this staging game with the chosen hero's.
        game = init_game(args.data, profile, hero=args.hero)
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
    # _save_session_settings / _persisted_render.
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
