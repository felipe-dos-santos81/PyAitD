# SPDX-License-Identifier: GPL-2.0-only
"""Mode and modal dispatch: actions from the keyboard queue, clicks and hovers, and the held pointer, into engine calls and presenter reducers. The shell's pump calls in; nothing here draws."""
from dataclasses import replace

import pygame

from PyAitD.app.config import save_settings, settings_payload
from PyAitD.app.controls.actions import Action
from PyAitD.app.controls.pointer import (
    CANCEL, OPEN_INVENTORY, Attack, Issue, end_hold, hold_decision,
    press_decision, rebase,
    drop_destination as pointer_drop_destination,
)
from PyAitD.app.controls.snapshot import configure, reset
from PyAitD.engine.nav.navmesh import agent_extent, approach_cell, nearest_walkable
from PyAitD.engine.nav.picking import (
    pick_actor, pick_floor_any_room, snap_accept, steer_point, viewed_floor_y,
    visible_accept,
)
from PyAitD.engine.script.effects import (
    ChooseCharacter, GameMode, InputMode, OpenStartupMenu, ShowTitle,
)
from PyAitD.engine.script.playworld import arm_mouse_attack, clear_mouse_attack
from PyAitD.engine.script.save import read_slot, slot_path, snapshot_game, write_slot


def continue_available(session):
    # M4a2 save/load replaces this with a real check of the save slots.
    return False


def open_startup_menu(game, session):
    game.close_modal()
    game.open_modal(OpenStartupMenu())
    session.booted_via_menu = True
    session.reset_for(game.active_modal)


def credits_entry(game):
    # AITD1.cpp:159 Lire(CVars[TEXTE_CREDITS] + 1, ...)
    return game.cvars[game.profile.cvar_index("TEXTE_CREDITS")] + 1


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


def pointer_actor_targets(game, draw_list, hero_idx):
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
    targets = pointer_actor_targets(game, draw_list, hero_idx)
    actor_idx = pick_actor(logical_pos, targets)
    if actor_idx is None:
        actor_idx = pick_actor(logical_pos, expand_actor_targets(targets))
    if actor_idx is not None and is_combat_target(game, actor_idx):
        if not can_strike(game):
            # an empty hand or a hero already mid-swing is blocked, never a
            # fall-through to a floor walk: the click was aimed at the enemy
            return ("blocked", None)
        return ("attack", actor_idx)
    if actor_idx is not None and not is_interactable(game, actor_idx):
        if is_hold_action_target(game, actor_idx):
            payload = hold_action_approach(game, floor, hero_idx, actor_idx)
            if payload is not None:
                return ("push", payload)
        # Nothing to do with this actor, so it must not intercept the click.
        # A draw-list entry is a screen *rectangle* around the skinned model:
        # refusing here refused the floor around the object too, and 86 of
        # 4000 pixels sampled at the opening camera were dead for exactly
        # this reason -- two pieces of inert scenery between them. The pixel
        # falls through to the floor below and means what it would mean if
        # the actor were not there. Combat keeps its own refusal above: an
        # empty hand on an enemy was aimed at the enemy.
        actor_idx = None
    if actor_idx is not None:
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
        return steer(game, floor, logical_pos, hero)
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
            return steer(game, floor, logical_pos, hero)
        dest_x, dest_z = snapped
    return ("walk", (dest_x, dest_z, dest_room, -1))


def steer(game, floor, logical_pos, hero):
    """The floor-side answer when a pixel names no reachable place.

    Walking is always possible: a pixel over a wall, a ceiling, the sky or a
    cell nothing walkable snaps to still names a *direction*, so the click
    heads far along the bearing from the hero through it and lets the
    engine's own collision stop him. Only the actor-side refusals -- an empty
    hand on an enemy, a mid-swing, an object with nothing to do -- still
    resolve `blocked`, because there the click was aimed at a thing and
    walking into it is not what it meant.

    Falls back to `blocked` when the hero's own feet are off screen: with
    nothing to take a bearing from there is no direction to walk in.
    """
    here = (hero.room_x + hero.step_x, hero.room_z + hero.step_z)
    steered = steer_point(
        logical_pos, floor, hero.room, game.num_camera, hero.world_y, here,
    )
    if steered is None:
        return ("blocked", None)
    return ("steer", (steered[0], steered[1], hero.room, -1))


def route_play_click(
        game, session, floor, logical_pos, draw_list, controls=None,
):
    """Route one resolved PLAY click; HUD and world share the resolver."""
    from PyAitD.engine.script.interaction import apply_click_intent, attack_in_hand

    if controls is None:
        # callers that own no controls: resolve and act once, nothing to latch
        kind, payload = resolve_play_click(game, floor, logical_pos, draw_list)
        if kind == "inventory":
            route_command(game, session, Action.INVENTORY_CONFIRM, None)
        elif kind == "attack":
            if attack_in_hand(game, payload):
                arm_mouse_attack(game, payload)
        elif kind not in ("blocked",) and not (game.nav_intent is not None and game.nav_intent.requires_hold):
            dest_x, dest_z, room, object_idx = payload
            apply_click_intent(game, dest_x, dest_z, room, target_object_idx=object_idx,
                               requires_hold=(kind == "push"), run=False, steering=(kind == "steer"))
        return
    intent = game.nav_intent
    decision = press_decision(
        controls.pointer, tick=game.timer, pos=logical_pos, camera=game.num_camera,
        resolve=lambda pos: resolve_play_click(game, floor, pos, draw_list),
        latched_push=intent is not None and intent.requires_hold,
    )
    if decision is OPEN_INVENTORY:
        route_command(game, session, Action.INVENTORY_CONFIRM, controls)
    elif isinstance(decision, Attack):
        # attack_in_hand only validates, stops and faces. The strike itself is
        # published by the fixed-tick input snapshot from the game-owned latch.
        if attack_in_hand(game, decision.target):
            arm_mouse_attack(game, decision.target)
    elif isinstance(decision, Issue):
        dest_x, dest_z, room, object_idx = decision.payload
        apply_click_intent(
            game, dest_x, dest_z, room, target_object_idx=object_idx,
            requires_hold=(decision.kind == "push"), run=decision.run,
            steering=(decision.kind == "steer"),
        )


def follow_pointer(game, session, floor, logical_pos, draw_list, controls):
    """Held pointer follow: re-aim the hero at whatever the held pointer
    resolves to, once per frame in which it moved
    (docs/superpowers/specs/2026-08-26-held-pointer-follow-design.md)."""
    from PyAitD.engine.script.interaction import apply_click_intent, cancel_nav_intent
    if (game.active_modal is not None or game.mode is not GameMode.PLAY
            or game.input_mode is not InputMode.MOUSE or session.cutscene
            # a transition frame is skipped rather than resolved: the
            # resolver reports blocked there, which would stop the hero for
            # a tick at every room change
            or game.num_camera == -1
            or not controls.pointer.held or not controls.focused
            or game.mouse_attack_target is not None):
        return
    intent = game.nav_intent
    decision = hold_decision(
        controls.pointer, pos=logical_pos, camera=game.num_camera,
        resolve=lambda pos: resolve_play_click(game, floor, pos, draw_list),
        latched_push=intent is not None and intent.requires_hold,
        intent_alive=intent is not None,
    )
    if isinstance(decision, Issue):
        dest_x, dest_z, room, object_idx = decision.payload
        apply_click_intent(
            game, dest_x, dest_z, room, target_object_idx=object_idx,
            run=decision.run, steering=(decision.kind == "steer"),
        )
    elif decision is CANCEL:
        cancel_nav_intent(game)


def cancel_pointer_invalidation(game, event, controls):
    """Button-up and focus loss end the hold, and every intent is hold-bound."""
    invalidated = (
        event.type == pygame.MOUSEBUTTONUP and event.button == 1
    ) or event.type == pygame.WINDOWFOCUSLOST
    if not invalidated:
        return False
    if event.type == pygame.WINDOWFOCUSLOST:
        clear_mouse_attack(game)
    return cancel_follow(game, controls)


def drop_destination(game, controls):
    """Forget where this hold was heading and drop the intent that was
    carrying it; True when an intent was live. The whole of what ending a
    *destination* means -- what ending the *hold* additionally means is the
    extra clearing in cancel_follow below. Keeping them apart is what stops
    the next per-hold field being cleared in one path and forgotten in the
    other. `controls` is optional only for callers that own no controls state."""
    from PyAitD.engine.script.interaction import cancel_nav_intent
    if controls is not None:
        pointer_drop_destination(controls.pointer)
    if game.nav_intent is None:
        return False
    cancel_nav_intent(game)
    return True


def cancel_follow(game, controls):
    """End the hold itself: the destination, plus everything that belonged
    to the press that opened it."""
    if controls is not None:
        steered = game.nav_intent is not None and game.nav_intent.steering
        end_hold(controls.pointer, steering=steered)
    return drop_destination(game, controls)


def rebase_follow(game, controls):
    """Drop a destination the new floor cannot mean, keeping the hold alive:
    a floor change invalidates the intent -- its `room` indexes the floor
    that was just unloaded -- but the button never came up, so ending the
    hold here would stop the hero dead on the stairs and demand a fresh
    press."""
    if controls is not None:
        rebase(controls.pointer)
    return drop_destination(game, controls)


def is_interactable(game, actor_idx):
    from PyAitD.engine.script.game import AF_FOUNDABLE
    actor = game.actors[actor_idx]
    if actor.index_in_world < 0:
        return False
    if actor.object_type & AF_FOUNDABLE:
        return True
    return game.world_objects[actor.index_in_world].found_life != -1


def inventory_view(game, session):
    from PyAitD.engine.script.interaction import inventory_actions, inventory_items
    object_ids = inventory_items(game)
    selected = object_ids[min(session.inventory.object_cursor, len(object_ids) - 1)]
    return object_ids, inventory_actions(game, selected)


def game_over_ready(session, effect):
    # LM_GAME_OVER's accessibility gate: input acceptance (route_game_over_command,
    # route_mouse) and the "Click to restart" overlay (render_active_mode) must
    # agree on the same wall-clock wait, so the overlay never invites a click
    # that the router would still swallow.
    return session.elapsed_ms >= effect.delay_units * 1000 // 60


def route_game_over_command(game, session, modal_command):
    # LM_GAME_OVER's accessibility gate: ignore ACTION/CANCEL (and, via the
    # caller's INVENTORY_CONFIRM-as-ACTION translation, INVENTORY_CONFIRM too)
    # until the wall-clock wait has elapsed, so a startled keypress cannot
    # restart the session before the player has even registered dying.
    ready = game_over_ready(session, game.active_modal)
    if ready and modal_command in (Action.ACTION, Action.CANCEL):
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
MENU_RENDER_FIELDS = ("scale", "shading", "background_filter", "lighting", "msaa", "realism", "smoothing", "shadows", "integration", "motion", "occlusion", "atmosphere")


def persisted_render(session):
    """The render payload `save_session_settings` actually writes: the
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


def save_session_settings(session):
    if not session.settings_dirty:
        return True
    if session.settings_path is None:
        session.settings_dirty = False
        return True
    settings_to_save = replace(session.settings, render=persisted_render(session))
    error = save_settings(settings_to_save, session.settings_path)
    if error is not None:
        session.settings_error = error
        return False
    session.settings_dirty = False
    return True


def available_slots(session):
    """The slot kinds a LOAD page may offer: a missing file disables its
    row, a present one enables it (a corrupt file still loads-then-fails
    through the visible error route)."""
    if session.save_directory is None:
        return frozenset()
    return frozenset(
        kind for kind in ("manual", "quick")
        if slot_path(session.save_directory, kind).exists()
    )


def write_save(game, session, kind):
    """Snapshot and write one slot; failures surface as the dismissible
    runtime notice and never touch the live game."""
    if session.save_directory is None:
        session.runtime_error = "Could not save: no save directory is configured"
        return
    settings_to_save = replace(session.settings, render=persisted_render(session))
    payload = snapshot_game(game, settings_payload(settings_to_save))
    error = write_slot(slot_path(session.save_directory, kind), payload)
    if error is not None:
        session.runtime_error = error


def manual_save(game, session, kind):
    # Allowed only at a stable system-menu boundary: while a LIFE
    # continuation or a platform effect is queued the world is mid-script,
    # and a snapshot of it would restore into that mid-script state.
    if game.life_stack or game.immediate_effects:
        session.runtime_error = "Could not save: a script is still running"
        return
    write_save(game, session, kind)


def request_quick_save(session):
    # Quick Save closes the menu (the result carries close=True) and defers
    # the write to the first stable end-of-PLAY-tick boundary; run() owns
    # the commit so the snapshot can never land mid-tick.
    session.quick_save_requested = True


def request_load(game, session, kind):
    """Read and validate the slot; a good payload stages the atomic
    replacement run() performs on this same frame. A bad one leaves the
    live game untouched and raises the dismissible notice."""
    if session.save_directory is None:
        session.runtime_error = "Could not load: no save directory is configured"
        return
    payload, error = read_slot(
        slot_path(session.save_directory, kind), game._data_dir, game.profile, pack=game.pack,
    )
    if error is not None:
        session.runtime_error = error
        return
    session.pending_load = payload


def apply_system_result(game, session, controls, result, renderer=None):
    if result is None:
        return True
    if result.settings is not None:
        old_render, new_render = session.settings.render, result.settings.render
        render_changed = new_render != old_render
        if render_changed:
            # Only a menu render-field cycle can produce a render diff here
            # (see MENU_RENDER_FIELDS): record exactly which field(s)
            # changed so a later save persists only those, not whatever
            # else happens to be sitting in session.settings.render.
            touched = set(session.render_touched)
            touched.update(
                field_name for field_name in MENU_RENDER_FIELDS
                if getattr(old_render, field_name) != getattr(new_render, field_name)
            )
            session.render_touched = frozenset(touched)
        session.settings = result.settings
        session.settings_dirty = True
        configure(controls, session.settings)
        if render_changed and renderer is not None:
            renderer.set_options(session.settings.render)
    saved = save_session_settings(session) if result.save else True
    if result.quit and not saved:
        return True
    if result.save_slot is not None:
        manual_save(game, session, result.save_slot)
    if result.quick_save:
        request_quick_save(session)
    if result.load_slot is not None:
        request_load(game, session, result.load_slot)
    if result.close:
        reset(controls, game)
        game.close_modal()
    if result.quit:
        reset(controls, game)
        return False
    return True


def take_over_play_input(game, session, controls) -> None:
    """Atomically drop transient PLAY input before a modal takes control."""
    if controls is not None:
        reset(controls, game)
    from PyAitD.engine.script.interaction import cancel_nav_intent
    cancel_nav_intent(game)
    if controls is None:
        clear_mouse_attack(game)
    # route_hover owns presenter-only hover and deliberately does not own the
    # modal lifecycle: ModalSession.reset_for remains at the open/render seams.
    route_hover(game, session, None)


def route_command(game, session, command, controls=None, renderer=None):
    from PyAitD.engine.script.effects import (
        GameMode, GameOver, OpenInventory, OpenSystemMenu, ReadText, ShowFound,
        ShowPicture,
    )
    from PyAitD.engine.script.interaction import (
        apply_found_result, apply_inventory_result, apply_reading_result,
    )
    from PyAitD.app.ui import ReadingResult, reading_pages
    from PyAitD.app.controls.modals import (
        reduce_found, reduce_inventory, reduce_reading, reduce_system_menu,
    )
    if session.cutscene:
        # PlayWorld(allowSystemMenu=0): every command is a skip, never a
        # route into PLAY's own commands (CANCEL opening the system menu,
        # the inventory-confirm action, TOGGLE_INPUT_MODE) -- mainLoop.cpp:71-89. Checked
        # first so that claim holds for every command, TOGGLE_INPUT_MODE
        # included -- defence-in-depth only: shell.run's event-pump swallow
        # already marks skip_cutscene and `continue`s for every KEYDOWN
        # while session.cutscene, so no command -- this one included -- can
        # actually reach route_command while a cutscene is active; this
        # branch exists for callers that invoke route_command directly
        # (tests, and any future caller bypassing the pump).
        session.skip_cutscene = True
        return True

    if command is Action.TOGGLE_INPUT_MODE:
        from PyAitD.engine.script.interaction import cancel_nav_intent, sync_player_track_mode
        game.input_mode = (
            InputMode.KEYBOARD if game.input_mode is InputMode.MOUSE else InputMode.MOUSE
        )
        cancel_nav_intent(game)
        if controls is None:
            clear_mouse_attack(game)
        sync_player_track_mode(game)
        if controls is not None:
            reset(controls, game)
        return True

    if game.mode is GameMode.PLAY:
        if command is Action.CANCEL:
            game.open_modal(OpenSystemMenu())
            take_over_play_input(game, session, controls)
            session.reset_for(game.active_modal)
            return True
        if command is Action.INVENTORY_CONFIRM and game.status_screen_allowed:
            if game.inventory_count[game.current_inventory]:
                game.open_modal(OpenInventory())
                take_over_play_input(game, session, controls)
                session.reset_for(game.active_modal)
        return True

    modal_command = Action.ACTION if command is Action.INVENTORY_CONFIRM else command
    if isinstance(game.active_modal, OpenSystemMenu):
        # the presenter resets where the menu is opened (the PLAY CANCEL
        # branch above), not per dispatch: a staged page/cursor/capture must
        # survive every routed command until the menu closes
        route_hover(game, session, None)
        result = reduce_system_menu(
            session.system_menu, modal_command, session.settings,
            available_slots(session),
        )
        return apply_system_result(game, session, controls, result, renderer=renderer)

    session.reset_for(game.active_modal)
    # A keyboard command makes the owning keyboard cursor authoritative until
    # a later MOUSEMOTION establishes a new preview.
    route_hover(game, session, None)
    if isinstance(game.active_modal, ShowTitle):
        from PyAitD.app.startup import credits_page_count, reduce_title
        page_count = credits_page_count(game.assets, credits_entry(game))
        if reduce_title(session.title, modal_command, page_count=page_count) is not None:
            open_startup_menu(game, session)
        return True
    if isinstance(game.active_modal, OpenStartupMenu):
        from PyAitD.app.startup import reduce_startup_menu
        result = reduce_startup_menu(session.startup, modal_command, continue_enabled=continue_available(session))
        return apply_startup_result(game, session, controls, result)
    if isinstance(game.active_modal, ChooseCharacter):
        from PyAitD.app.controls.modals import reduce_character_select
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
        object_ids, action_ids = inventory_view(game, session)
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
        if modal_command in (Action.ACTION, Action.CANCEL):
            apply_reading_result(game, ReadingResult(True))
        return True
    if isinstance(game.active_modal, GameOver):
        return route_game_over_command(game, session, modal_command)
    raise RuntimeError(f"unroutable modal {type(game.active_modal).__name__}")


def apply_startup_result(game, session, controls, result):
    if result is None:
        return True
    if result.new_game:
        game.close_modal()
        game.open_modal(ChooseCharacter())
        session.reset_for(game.active_modal)
        if controls is not None:
            reset(controls, game)
        if controls is None:
            clear_mouse_attack(game)
        return True
    if result.quit:
        if controls is not None:
            reset(controls, game)
        if controls is None:
            clear_mouse_attack(game)
        return False
    return True   # continue_game cannot be produced while continue_available is False


def route_mouse(game, session, logical_pos, controls=None, renderer=None):
    from PyAitD.engine.script.effects import (
        ChooseCharacter, CutsceneFinished, GameOver, OpenInventory, OpenSystemMenu,
        ReadText, ShowFound, ShowPicture,
    )
    from PyAitD.engine.script.interaction import (
        apply_found_result, apply_inventory_result, apply_reading_result,
    )
    from PyAitD.app.ui import CharacterPhase, ReadingResult, SystemMenuPage, reading_pages
    from PyAitD.app.controls.modals import (
        hit_test_character, hit_test_found, hit_test_inventory, hit_test_reading,
        hit_test_system_menu, pick_system_key, reduce_system_menu, turn_page,
    )
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
            return apply_system_result(game, session, controls, result, renderer=renderer)
        old_page = session.system_menu.page
        session.system_menu.cursor = hit
        result = reduce_system_menu(
            session.system_menu, Action.ACTION, session.settings,
            available_slots(session),
        )
        if session.system_menu.page is not old_page:
            session.system_menu.hover = None
        return apply_system_result(game, session, controls, result, renderer=renderer)
    session.reset_for(effect)
    if isinstance(effect, ShowTitle):
        from PyAitD.app.startup import credits_page_count, hit_test_title, reduce_title
        if hit_test_title(logical_pos):
            page_count = credits_page_count(game.assets, credits_entry(game))
            if reduce_title(session.title, Action.ACTION, page_count=page_count) is not None:
                open_startup_menu(game, session)
        return True
    if isinstance(effect, OpenStartupMenu):
        from PyAitD.app.startup import hit_test_startup, reduce_startup_menu
        enabled = continue_available(session)
        hit = hit_test_startup(logical_pos, continue_enabled=enabled)
        if hit is None:
            return True
        session.startup.cursor = hit
        result = reduce_startup_menu(session.startup, Action.ACTION, continue_enabled=enabled)
        return apply_startup_result(game, session, controls, result)
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
        object_ids, action_ids = inventory_view(game, session)
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
        ready = game_over_ready(session, effect)
        if ready:
            game.restart_requested = True
        return True
    raise RuntimeError(f"unroutable modal {type(effect).__name__}")


def route_hover(game, session, logical_pos):
    """Update only the active modal presenter's mouse preview."""
    from PyAitD.engine.script.effects import (
        ChooseCharacter, OpenInventory, OpenSystemMenu, ReadText, ShowFound,
    )
    from PyAitD.app.ui import reading_pages
    from PyAitD.app.controls.modals import (
        hit_test_character, hit_test_found, hit_test_inventory, hit_test_reading,
        hit_test_system_menu,
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
            object_ids, action_ids = inventory_view(game, session)
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
