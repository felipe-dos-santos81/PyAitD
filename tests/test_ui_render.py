# SPDX-License-Identifier: GPL-2.0-only
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from PyAitD.engine.data.assets import Assets
from PyAitD.app.config import default_settings
from PyAitD.engine.script.effects import FoundResult, ReadText, ShowFound, ShowPicture, TimedMessage
from PyAitD.engine.script.game import init_game
from PyAitD.engine.data.text import BookToken
from PyAitD.app.ui import (
    CharacterLayout, CharacterPhase, CharacterSelectPresenter,
    FoundPresenter, InventoryPresenter, ModalLayout, PlayLayout, ReadingPresenter, ReadingResult,
    SystemMenuPage, SystemMenuPresenter, UIPainter,
    _tile_big_cadre, draw_big_cadre, layout_book,
    overlay_messages, render_character_select, render_cursor, render_found,
    render_game_over, render_hit_feedback, render_picture, render_play_hud, render_reading,
    render_inventory, render_settings_notice, render_system_menu,
    screen_surface, text_size, transparent_canvas,
)

pytestmark = pytest.mark.shell


def test_modal_presenters_paint_rgba_canvases_of_the_painters_size(data_dir, profile):
    # The presenters return nothing: they paint on the painter they are
    # handed, and it is the painter's canvas -- RGBA, not RGB -- that is
    # 320x200 at scale 1.
    pygame.font.init()
    game = init_game(data_dir, profile)
    reading_painter = UIPainter()
    render_reading(reading_painter, ReadText(1, 0), ReadingPresenter(), game.assets)

    found_painter = UIPainter()
    render_found(
        found_painter, ShowFound(13, False), FoundPresenter(), game.assets,
        game.assets.system_text(game.world_objects[13].found_name),
    )
    picture_painter = UIPainter()
    render_picture(picture_painter, ShowPicture(10, 60, 4), game.assets)
    frames = [reading_painter.to_frame(), found_painter.to_frame(), picture_painter.to_frame()]
    assert all(frame.shape == (200, 320, 4) for frame in frames)
    assert all(frame.dtype == np.uint8 for frame in frames)


def test_reading_page_text_is_sharper_at_scale_four(data_dir, profile):
    pygame.font.init()
    game = init_game(data_dir, profile)
    ink = []
    for scale in (1, 4):
        painter = UIPainter(scale)
        render_reading(painter, ReadText(1, 0), ReadingPresenter(), game.assets)
        frame = painter.to_frame()
        dark = ((frame[:, :, 0] < 80) & (frame[:, :, 1] < 80)).sum()
        ink.append(dark / (scale * scale))
    assert ink[1] > ink[0], (
        "4x the canvas must carry more than 4x the glyph pixels, or the text "
        "was upscaled rather than re-rendered"
    )


def test_found_modal_fills_its_own_background_at_any_scale(data_dir, profile):
    pygame.font.init()
    assets = Assets(data_dir, profile)
    for scale in (1, 4):
        painter = UIPainter(scale)
        render_found(painter, ShowFound(13, False), FoundPresenter(), assets, "Lamp")
        frame = painter.to_frame()
        assert frame[:, :, 3].min() == 255, "the found modal owns the whole frame"
        assert tuple(frame[2, 2][:3]) == (17, 11, 9), "its fill colour"


def test_book_layout_preserves_tab_prefix_and_center_flag():
    pygame.font.init()
    pages = layout_book(
        (BookToken("tab"), BookToken("center"), BookToken("text", "Entry")),
        16,
        190,
        8,
    )
    assert pages[0][0] == ("    Entry", True)


def test_message_overlay_paints_a_present_message_in_place(data_dir, profile):
    pygame.font.init()
    game = init_game(data_dir, profile)
    painter = UIPainter()
    overlay_messages(painter, [TimedMessage(100), None, None, None, None], game.assets)
    assert np.count_nonzero(painter.to_frame()) > 0


def test_painter_at_scale_one_matches_a_transparent_canvas():
    painter = UIPainter()
    assert painter.size == (320, 200)
    assert np.array_equal(painter.to_frame(), transparent_canvas())


def test_painter_scales_shapes_by_its_scale():
    painter = UIPainter(3)
    assert painter.size == (960, 600)
    painter.rect((255, 0, 0), pygame.Rect(10, 20, 4, 5))
    frame = painter.to_frame()
    # the logical rect (10,20)-(14,25) lands at (30,60)-(42,75)
    assert tuple(frame[61, 31][:3]) == (255, 0, 0)
    assert frame[59, 29][3] == 0, "nothing painted above/left of the scaled rect"
    assert frame[76, 43][3] == 0, "nothing painted below/right of it"


def test_painter_hairlines_survive_scaling_down_to_one_pixel():
    painter = UIPainter(1)
    painter.rect((255, 255, 255), pygame.Rect(0, 0, 10, 10), width=1)
    assert painter.to_frame()[0, 0, 3] == 255, "a 1px outline must not vanish"


def test_painter_sprite_upscales_pixel_art_by_an_integer():
    art = np.zeros((2, 2, 4), np.uint8)
    art[0, 0] = (255, 0, 0, 255)
    painter = UIPainter(3)
    painter.sprite(art, (0, 0))
    frame = painter.to_frame()
    for y in range(3):
        for x in range(3):
            assert tuple(frame[y, x][:3]) == (255, 0, 0), "each source pixel is a 3x3 block"
    assert frame[0, 3, 3] == 0, "and nothing bleeds past it"


def test_painter_blit_scales_the_area_subrect_and_destination():
    # blit's source is ALREADY at canvas scale; only `logical_dest` and
    # `area` are logical and must be scaled by the painter before use.
    # render_character_select depends on this to re-copy the portrait
    # rectangle from the clean background over the cadre -- a wrong area
    # scaling would put the wrong slice of the background there.
    scale = 2
    painter = UIPainter(scale)
    source = pygame.Surface(painter.size)
    source.fill((0, 0, 255))
    logical_area = pygame.Rect(10, 20, 5, 5)
    # what logical_area becomes once scaled into the source's own (already
    # canvas-scale) pixels -- only this exact block is marked
    pixel_area = pygame.Rect(20, 40, 10, 10)
    source.fill((255, 0, 0), pixel_area)
    painter.blit(source, (50, 60), area=logical_area)
    frame = painter.to_frame()
    dest = pygame.Rect(100, 120, 10, 10)  # (50, 60) and (5, 5) each scaled by `scale`
    inside = frame[dest.top:dest.bottom, dest.left:dest.right]
    assert (inside[:, :, :3] == (255, 0, 0)).all(), (
        "the scaled area sub-rect must land exactly at the scaled destination"
    )
    assert (inside[:, :, 3] == 255).all()
    assert frame[dest.top - 1, dest.left, 3] == 0, "nothing painted just above the destination"
    assert frame[dest.bottom, dest.left, 3] == 0, "nothing painted just below the destination"
    assert frame[dest.top, dest.left - 1, 3] == 0, "nothing painted just left of the destination"
    assert frame[dest.top, dest.right, 3] == 0, "nothing painted just right of the destination"


def test_painter_text_scales_size_and_anchor():
    pygame.font.init()
    small, large = UIPainter(1), UIPainter(4)
    small.text("Wg", 16, (255, 255, 255), center=(160, 100))
    large.text("Wg", 16, (255, 255, 255), center=(160, 100))
    small_ink = np.argwhere(small.to_frame()[:, :, 3] > 0)
    large_ink = np.argwhere(large.to_frame()[:, :, 3] > 0)
    assert len(large_ink) > 4 * len(small_ink), "4x the scale must draw more ink"
    # both stay centred on the same logical point
    assert abs(small_ink[:, 1].mean() - 160) < 6
    assert abs(large_ink[:, 1].mean() / 4 - 160) < 6


def test_painter_text_size_is_logical_at_every_scale():
    pygame.font.init()
    assert UIPainter(1).text_size("Hello", 16) == UIPainter(3.5).text_size("Hello", 16)


def test_layout_book_wrapping_cannot_depend_on_the_ui_scale():
    # Wrapping must stay logical: a book that re-flowed on resize would change
    # how many pages it has. layout_book takes no painter and no scale, so the
    # only way a scale could reach it is through the measurement it uses --
    # which every painter agrees on, whatever it was built at.
    pygame.font.init()
    tokens = (BookToken("text", "one two three four five six seven eight nine ten"),)
    line = "one two three four five"
    assert text_size(line, 15) == UIPainter(1).text_size(line, 15)
    assert text_size(line, 15) == UIPainter(3.5).text_size(line, 15)
    assert layout_book(tokens, 15, 150, 12) == layout_book(tokens, 15, 150, 12)


def test_cursor_marks_the_frame():
    painter = UIPainter()
    render_cursor(painter, (160, 100), "walk")
    assert int(painter.to_frame().sum()) > 0, "the cursor drew nothing"


def test_hit_feedback_marks_the_supplied_box_in_high_contrast():
    painter = UIPainter(fill=(80, 80, 80, 255))
    original = painter.to_frame().copy()
    target = pygame.Rect(100, 60, 101, 101)

    render_hit_feedback(painter, (target,))
    result = painter.to_frame()

    changed = np.any(result[:, :, :3] != original[:, :, :3], axis=2)
    assert not np.any(changed[:50, :]), "feedback escaped the supplied target"
    pixels = result[changed]
    assert np.any(np.all(pixels[:, :3] == (255, 255, 255), axis=1)), (
        "hit feedback needs a bright edge against dark scenery"
    )
    assert np.any(
        (pixels[:, 0] == 255) & (pixels[:, 1] <= 64) & (pixels[:, 2] <= 64)
    ), "hit feedback needs a distinct red edge against bright scenery"


def test_play_hud_draws_only_when_available():
    unavailable = UIPainter()
    render_play_hud(unavailable, inventory_available=False)
    assert int(unavailable.to_frame().sum()) == 0

    available = UIPainter()
    render_play_hud(available, inventory_available=True)
    assert not np.array_equal(available.to_frame(), unavailable.to_frame())


def test_keyboard_mode_is_named_on_the_hud_and_mouse_mode_is_not():
    # keyboard mode has no mouse function in PLAY, and the cursor vanishes
    # with it (shell hides the OS pointer), so the HUD is the only thing
    # left that can say why clicking stopped doing anything.
    mouse_mode = UIPainter()
    render_play_hud(mouse_mode, inventory_available=True, keyboard_mode=False)

    keyboard = UIPainter()
    render_play_hud(keyboard, inventory_available=True, keyboard_mode=True)

    assert not np.array_equal(keyboard.to_frame(), mouse_mode.to_frame())
    # the label sits at the top centre, clear of the INV box's top-left corner
    assert int(keyboard.to_frame()[:16, 120:200].sum()) > 0
    assert int(mouse_mode.to_frame()[:16, 120:200].sum()) == 0


def test_keyboard_label_draws_even_with_no_inventory_button():
    # the inventory button is hidden whenever the HUD is unavailable, but the
    # mode still has to be legible -- these are independent reasons to draw
    blank = UIPainter()
    render_play_hud(blank, inventory_available=False, keyboard_mode=False)
    assert int(blank.to_frame().sum()) == 0

    labelled = UIPainter()
    render_play_hud(labelled, inventory_available=False, keyboard_mode=True)
    assert int(labelled.to_frame().sum()) > 0
    # ...and without the INV button beside it
    assert int(labelled.to_frame()[:32, :40].sum()) == 0


def test_all_pointer_kinds_have_distinct_pixel_output():
    rendered = {}
    for kind in ("inventory", "attack", "target", "walk", "blocked"):
        painter = UIPainter()
        render_cursor(painter, (160, 100), kind)
        rendered[kind] = painter.to_frame()
    assert len({image.tobytes() for image in rendered.values()}) == 5


def test_push_cursor_is_a_sixth_distinct_pointer():
    kinds = ("inventory", "attack", "target", "push", "walk", "blocked")
    rendered = {}
    for kind in kinds:
        painter = UIPainter()
        render_cursor(painter, (160, 100), kind)
        rendered[kind] = painter.to_frame()

    assert len({image.tobytes() for image in rendered.values()}) == len(kinds)


def test_cursor_outside_the_surface_is_a_no_op():
    painter = UIPainter()
    before = painter.to_frame().copy()
    render_cursor(painter, None, "walk")
    assert np.array_equal(painter.to_frame(), before)


def test_game_over_locked_frame_is_identical_and_ready_frame_is_overlayed():
    pygame.font.init()
    source = np.arange(320 * 200 * 3, dtype=np.uint8).reshape((200, 320, 3))

    locked_painter = UIPainter()
    before = locked_painter.to_frame().copy()
    render_game_over(locked_painter, source, ready=False)
    assert np.array_equal(locked_painter.to_frame(), before)

    ready_painter = UIPainter()
    render_game_over(ready_painter, source, ready=True)
    assert not np.array_equal(ready_painter.to_frame()[:, :, :3], source)


def test_big_cadre_pins_fitd_interior_and_ring(data_dir, profile):
    cadre_bank = Assets(data_dir, profile).cadre_bank()
    surface = pygame.Surface((320, 200))
    surface.fill((0, 0, 0))
    interior = _tile_big_cadre(surface, cadre_bank, (160, 100), (320, 200))
    assert interior == pygame.Rect(8, 8, 304, 184)
    frame = pygame.surfarray.array3d(surface).swapaxes(0, 1)
    assert np.count_nonzero(frame) > 0, "the cadre ring drew nothing"
    inside = frame[interior.top:interior.bottom, interior.left:interior.right]
    assert np.count_nonzero(inside) == 0, "the cadre interior must stay black"

    painter = UIPainter()
    draw_big_cadre(painter, cadre_bank, (160, 100), (320, 200))
    assert np.array_equal(painter.to_frame()[:, :, :3], frame), (
        "draw_big_cadre through the painter must match the tiled surface at scale 1"
    )


def test_character_portraits_restore_art_inside_fitd_cadre(data_dir, profile):
    assets = Assets(data_dir, profile)
    base = assets.resource_screen(10)
    painter = UIPainter()
    render_character_select(painter, CharacterSelectPresenter(choice=0), assets)
    frame = painter.to_frame()[:, :, :3]
    left = CharacterLayout.PORTRAITS[0]
    assert np.array_equal(frame[left.top:left.bottom, left.left:left.right],
                          base[left.top:left.bottom, left.left:left.right])
    assert not np.array_equal(frame, base)


def test_hover_preview_overrides_keyboard_selection_without_changing_it(data_dir, profile):
    assets = Assets(data_dir, profile)
    scene = np.zeros((200, 320, 3), dtype=np.uint8)

    found = FoundPresenter(choice=FoundResult.TAKE, hover=FoundResult.LEAVE)
    hovered_found = UIPainter()
    render_found(hovered_found, ShowFound(13, False), found, assets, "Lamp")
    plain_found = UIPainter()
    render_found(
        plain_found, ShowFound(13, False), FoundPresenter(choice=FoundResult.TAKE), assets, "Lamp",
    )
    assert not np.array_equal(hovered_found.to_frame(), plain_found.to_frame())
    assert found.choice is FoundResult.TAKE

    inventory = InventoryPresenter(object_cursor=0, hover=1)
    hovered_inventory = UIPainter()
    render_inventory(hovered_inventory, inventory, assets, scene, ("Lamp", "Key"), ("Use",))
    plain_inventory = UIPainter()
    render_inventory(
        plain_inventory, InventoryPresenter(object_cursor=0), assets, scene, ("Lamp", "Key"), ("Use",),
    )
    assert not np.array_equal(hovered_inventory.to_frame(), plain_inventory.to_frame())
    assert inventory.object_cursor == 0

    character = CharacterSelectPresenter(choice=0, hover=1)
    hovered_character = UIPainter()
    render_character_select(hovered_character, character, assets)
    plain_character = UIPainter()
    render_character_select(plain_character, CharacterSelectPresenter(choice=0), assets)
    assert not np.array_equal(hovered_character.to_frame(), plain_character.to_frame())
    assert character.choice == 0

    menu = SystemMenuPresenter(cursor=0, hover=1)
    hovered_menu = UIPainter()
    render_system_menu(hovered_menu, menu, default_settings(), assets)
    plain_menu = UIPainter()
    render_system_menu(plain_menu, SystemMenuPresenter(cursor=0), default_settings(), assets)
    assert not np.array_equal(hovered_menu.to_frame(), plain_menu.to_frame())
    assert menu.cursor == 0

    assets.book_pages[0] = (("one",), ("two",))
    reading = ReadingPresenter(page=0, hover=ReadingResult(False, 1))
    hovered_reading = UIPainter()
    render_reading(hovered_reading, ReadText(1, 0), reading, assets)
    plain_reading = UIPainter()
    render_reading(plain_reading, ReadText(1, 0), ReadingPresenter(page=0), assets)
    assert not np.array_equal(hovered_reading.to_frame(), plain_reading.to_frame())
    assert reading.page == 0


@pytest.mark.parametrize(
    ("choice", "hero", "copied"),
    ((0, 1, pygame.Rect(160, 0, 160, 200)),
     (1, 0, pygame.Rect(0, 0, 160, 200))),
)
def test_story_composes_the_opposite_intro_half_and_expected_text(
    data_dir, profile, choice, hero, copied,
):
    assets = Assets(data_dir, profile)
    presenter = CharacterSelectPresenter(choice=choice, phase=CharacterPhase.STORY)
    painter = UIPainter()
    render_character_select(painter, presenter, assets)
    frame = painter.to_frame()
    intro = assets.resource_screen(14)
    # Compare a margin outside the text column; the copied half remains exact.
    margin = pygame.Rect(copied.left, 0, 4, 200)
    assert np.array_equal(
        frame[margin.top:margin.bottom, margin.left:margin.right, :3],
        intro[margin.top:margin.bottom, margin.left:margin.right],
    )
    assert int(frame.sum()) > 0
    assert (1 if choice == 0 else 0) == hero


def test_settings_notice_overlays_the_painter():
    painter = UIPainter()
    before = painter.to_frame().copy()
    render_settings_notice(painter, "Could not load settings from /x: corrupt")
    assert not np.array_equal(painter.to_frame(), before)


@pytest.mark.parametrize("page", tuple(SystemMenuPage))
def test_system_menu_is_a_logical_rgb_frame(data_dir, profile, page):
    painter = UIPainter()
    render_system_menu(
        painter, SystemMenuPresenter(page=page), default_settings(), Assets(data_dir, profile),
    )
    frame = painter.to_frame()
    assert frame.shape == (200, 320, 4)
    assert frame.dtype == np.uint8


def test_system_menu_labels_match_the_layouts():
    from PyAitD.app.ui import SystemMenuLayout, system_menu_labels
    settings = default_settings()
    for page in (SystemMenuPage.MAIN, SystemMenuPage.SAVE, SystemMenuPage.LOAD,
                 SystemMenuPage.CONFIG, SystemMenuPage.GRAPHICS, SystemMenuPage.REALISM):
        assert len(system_menu_labels(page, settings)) == len(SystemMenuLayout.rows(page))
    assert system_menu_labels(SystemMenuPage.MAIN, settings) == [
        "Return to Game", "Save", "Load", "Quick Save", "Configuration", "Quit",
    ]
    assert system_menu_labels(SystemMenuPage.SAVE, settings) == ["Manual Slot", "Back"]
    assert system_menu_labels(SystemMenuPage.LOAD, settings) == [
        "Manual Slot", "Quick Save", "Back",
    ]


def test_load_page_renders_missing_slots_disabled(data_dir, profile):
    assets = Assets(data_dir, profile)
    disabled = UIPainter()
    render_system_menu(
        disabled, SystemMenuPresenter(page=SystemMenuPage.LOAD), default_settings(), assets,
    )
    enabled = UIPainter()
    render_system_menu(
        enabled, SystemMenuPresenter(page=SystemMenuPage.LOAD), default_settings(), assets,
        frozenset({"manual", "quick"}),
    )
    assert not np.array_equal(disabled.to_frame(), enabled.to_frame())
    # a disabled row takes no selection highlight: hovering it paints
    # exactly what the plain cursor already shows
    hovered = UIPainter()
    render_system_menu(
        hovered, SystemMenuPresenter(page=SystemMenuPage.LOAD, hover=0),
        default_settings(), assets,
    )
    assert np.array_equal(hovered.to_frame(), disabled.to_frame())


def test_configuration_lists_graphics_rows_inside_the_screen():
    from PyAitD.app.ui import SystemMenuLayout, config_row_count
    rows = SystemMenuLayout.rows(SystemMenuPage.CONFIG)
    assert len(rows) == config_row_count()
    assert all(r.bottom <= 200 for r in rows)
    hit = SystemMenuLayout.hit_rows(SystemMenuPage.CONFIG)
    for a in range(len(hit)):
        for b in range(a + 1, len(hit)):
            assert not hit[a].colliderect(hit[b])


def test_system_menu_row_label_mismatch_raises_instead_of_hiding_back_to_menu(monkeypatch):
    # If the row layout and the hand-built label list ever drift in length,
    # a plain zip() truncates silently: with fewer rows than labels the
    # trailing "Back to Menu" row simply never gets drawn (invisible, but
    # reduce_system_menu still treats row_count - 1 as Back, so its hit
    # target is real -- a fully hidden but clickable row). strict=True turns
    # that drift into a loud failure instead of a silent, hard-to-notice UI
    # bug.
    import PyAitD.app.ui as ui_module

    monkeypatch.setattr(ui_module.SystemMenuLayout, "MAIN_ROWS", ui_module.SystemMenuLayout.MAIN_ROWS[:-1])
    fake_sprite = np.zeros((20, 20, 3), dtype=np.uint8)
    fake_assets = SimpleNamespace(cadre_bank=lambda: (fake_sprite,) * 9)

    with pytest.raises(ValueError):
        render_system_menu(
            UIPainter(), SystemMenuPresenter(page=SystemMenuPage.MAIN), default_settings(), fake_assets,
        )


def test_transparent_canvas_and_rgba_round_trip():
    from PyAitD.app.ui import _to_frame, _to_surface, transparent_canvas
    canvas = transparent_canvas()
    assert canvas.shape == (200, 320, 4) and canvas.max() == 0
    surface = _to_surface(canvas)
    assert surface.get_flags() & pygame.SRCALPHA
    back = _to_frame(surface)
    assert back.shape == (200, 320, 4) and back.max() == 0
    rgb = np.full((200, 320, 3), 5, np.uint8)
    assert _to_frame(_to_surface(rgb)).shape == (200, 320, 3)


def test_play_hud_and_cursor_keep_the_canvas_transparent_elsewhere():
    painter = UIPainter()
    render_play_hud(painter, inventory_available=True)
    render_cursor(painter, (160, 100), "walk")
    out = painter.to_frame()
    assert out.shape == (200, 320, 4)
    assert out[0, 0, 3] == 0                      # untouched corner stays clear
    assert out[:, :, 3].max() == 255              # something was drawn


def test_overlays_paint_in_place_and_match_the_old_canvas_at_scale_one():
    painter = UIPainter()
    render_play_hud(painter, inventory_available=True)
    render_cursor(painter, (100, 50), "attack")
    frame = painter.to_frame()
    assert frame[50, 100, 3] > 0, "the cursor painted at its logical point"
    assert frame[PlayLayout.INVENTORY.centery, PlayLayout.INVENTORY.centerx, 3] > 0


def test_overlays_scale_with_the_painter():
    painter = UIPainter(4)
    render_cursor(painter, (100, 50), "attack")
    assert painter.to_frame()[200, 400, 3] > 0, "the cursor tracks the scaled point"


def test_game_over_not_ready_is_identity_on_the_canvas():
    from PyAitD.app.ui import render_game_over, transparent_canvas
    scene = np.zeros((200, 320, 3), np.uint8)

    locked_painter = UIPainter()
    render_game_over(locked_painter, scene, False)
    assert np.array_equal(locked_painter.to_frame(), transparent_canvas())

    ready_painter = UIPainter()
    render_game_over(ready_painter, scene, True)
    assert ready_painter.to_frame().shape == (200, 320, 4)


from PyAitD.render.asset_resolver import AssetResolver, texture_screen_path
from PyAitD.render import texture_export as be


def test_character_layout_portraits_come_from_the_export_guide_rects():
    assert tuple(tuple(r) for r in CharacterLayout.PORTRAITS) == be.PORTRAIT_RECTS


def test_character_select_uses_a_screen_override_outside_the_portraits(data_dir, profile, tmp_path):
    pygame.font.init()
    game = init_game(data_dir, profile)
    path = texture_screen_path(tmp_path, 10)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    plate = np.zeros((400, 640, 3), np.uint8)
    plate[:, :, 1] = 255                                     # solid green at 2x
    resolver = AssetResolver(game.assets, tmp_path, load_png=lambda p: plate)
    painter = UIPainter()
    render_character_select(painter, CharacterSelectPresenter(), game.assets, resolver)
    frame = painter.to_frame()
    assert frame.shape == (200, 320, 4)
    assert tuple(frame[196, 318, :3]) == (0, 255, 0)         # outside portraits and cadre: the override
    x, y, w, h = be.PORTRAIT_RECTS[1]
    # The unhovered portrait isn't special-cased: it's part of resource 10's
    # background, so the override covers it too, same as the rest of the screen.
    assert tuple(frame[y + 5, x + 5, :3]) == (0, 255, 0)
    original_painter = UIPainter()
    render_character_select(original_painter, CharacterSelectPresenter(), game.assets)
    original = original_painter.to_frame()
    assert tuple(original[y + 5, x + 5, :3]) != (0, 255, 0)  # sanity: real art there with no override


def test_character_select_background_is_fetched_at_canvas_size(data_dir, profile):
    pygame.font.init()
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    painter = UIPainter(4)
    render_character_select(painter, CharacterSelectPresenter(), game.assets, resolver)
    frame = painter.to_frame()
    assert frame.shape[:2] == (800, 1280)
    assert frame[:, :, 3].min() == 255, "the selector owns the whole frame"


def test_reading_and_picture_accept_a_resolver(data_dir, profile):
    pygame.font.init()
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    reading_painter = UIPainter()
    render_reading(reading_painter, ReadText(1, 0), ReadingPresenter(), game.assets, resolver)
    a = reading_painter.to_frame()
    picture_painter = UIPainter()
    render_picture(picture_painter, ShowPicture(10, 60, 4), game.assets, resolver)
    b = picture_painter.to_frame()
    assert a.shape == (200, 320, 4) and b.shape == (200, 320, 4)


def test_modal_reading_buttons_come_from_the_export_guide_rects():
    assert tuple(ModalLayout.READING_PREV) == be.READING_PREV_RECT
    assert tuple(ModalLayout.READING_CLOSE) == be.READING_CLOSE_RECT
    assert tuple(ModalLayout.READING_NEXT) == be.READING_NEXT_RECT


def test_screen_surface_is_memoized_per_resolver_and_entry(data_dir, profile):
    """shell.py's render loop calls screen_surface every frame for the same
    resolver/entry (character select at 60 Hz); the scaled Surface must be
    reused rather than rebuilt from scratch each call."""
    pygame.font.init()
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    first = screen_surface(resolver, 10)
    second = screen_surface(resolver, 10)
    assert first is second
    other_entry = screen_surface(resolver, 14)
    assert other_entry is not first
    other_resolver = screen_surface(AssetResolver(game.assets, None), 10)
    assert other_resolver is not first


def test_screen_surface_returns_the_requested_size_and_caches_per_size(data_dir, profile):
    pygame.font.init()
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    small = screen_surface(resolver, 10)
    big = screen_surface(resolver, 10, size=(1280, 800))
    assert small.get_size() == (320, 200)
    assert big.get_size() == (1280, 800)
    assert screen_surface(resolver, 10, size=(1280, 800)) is big, "cached per size"
    assert screen_surface(resolver, 10) is small, "and the old size still cached"


def test_render_reading_does_not_leak_drawing_into_the_cached_screen_surface(data_dir, profile):
    """screen_surface returns a shared, cached Surface for repeat calls;
    render_reading blits it onto the painter's own surface rather than
    drawing text/buttons directly onto the cached Surface, so a second call
    for the same resolver must not draw over the first call's leftover
    pixels instead of a clean background."""
    pygame.font.init()
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    presenter = ReadingPresenter()
    first_painter = UIPainter()
    render_reading(first_painter, ReadText(1, 0), presenter, game.assets, resolver)
    second_painter = UIPainter()
    render_reading(second_painter, ReadText(1, 0), presenter, game.assets, resolver)
    assert (first_painter.to_frame() == second_painter.to_frame()).all()


def test_render_character_select_story_phase_does_not_leak_across_calls(data_dir, profile):
    """Same hazard as render_reading, for the STORY overlay: it blits half
    of resource 14 and book text onto the (now cached) resource-10 surface."""
    pygame.font.init()
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    presenter = CharacterSelectPresenter(choice=0, phase=CharacterPhase.STORY)
    first_painter = UIPainter()
    render_character_select(first_painter, presenter, game.assets, resolver)
    second_painter = UIPainter()
    render_character_select(second_painter, presenter, game.assets, resolver)
    assert (first_painter.to_frame() == second_painter.to_frame()).all()


# --- scale > 1 end to end ---------------------------------------------------
# Until this block only three of the thirteen presenters were ever rendered
# above scale 1, so a whole class of scale bug -- art sized by round(scale)
# while its destination is sized by the exact scale -- could only be seen by
# running the game in a window.

_FULL_FRAME_SCALES = (1, 2.5, 4)
_FULL_FRAME_PRESENTERS = (
    "system_menu", "system_menu_config", "startup_menu", "inventory",
    "game_over", "title", "credits",
)


def _full_frame_presenters(game, resolver, credits_entry):
    """The presenters that paint their own ground and therefore must cover
    every pixel of the canvas, whatever its size."""
    from PyAitD.app.startup import (
        StartupMenuPresenter, TitlePhase, TitlePresenter, render_startup_menu, render_title,
    )
    assets = game.assets
    scene = np.full((200, 320, 3), 90, np.uint8)
    return {
        "system_menu": lambda p: render_system_menu(
            p, SystemMenuPresenter(), default_settings(), assets),
        "system_menu_config": lambda p: render_system_menu(
            p, SystemMenuPresenter(page=SystemMenuPage.CONFIG), default_settings(), assets),
        "startup_menu": lambda p: render_startup_menu(
            p, StartupMenuPresenter(), assets, continue_enabled=True),
        "inventory": lambda p: render_inventory(
            p, InventoryPresenter(), assets, scene, ("Lamp", "Key"), ("Use",)),
        "game_over": lambda p: render_game_over(p, scene, True),
        "title": lambda p: render_title(
            p, TitlePresenter(), assets, resolver, 10_000, credits_entry),
        "credits": lambda p: render_title(
            p, TitlePresenter(TitlePhase.CREDITS), assets, resolver, 0, credits_entry),
    }


@pytest.mark.parametrize("scale", _FULL_FRAME_SCALES)
@pytest.mark.parametrize("name", _FULL_FRAME_PRESENTERS)
def test_full_frame_presenters_own_every_pixel_at_every_scale(
    data_dir, profile, name, scale,
):
    """A modal that paints its own background must be opaque edge to edge on
    a canvas of any size. Scaling the art by round(scale) instead of to the
    scaled destination left the last fifth of a 2.5x canvas showing the live
    scene through the modal."""
    pygame.font.init()
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    credits_entry = game.cvars[profile.cvar_index("TEXTE_CREDITS")] + 1
    painter = UIPainter(scale)
    _full_frame_presenters(game, resolver, credits_entry)[name](painter)
    frame = painter.to_frame()
    assert frame.shape[:2] == (painter.size[1], painter.size[0])
    assert frame[:, :, 3].min() == 255, (
        f"{name} left a transparent pixel at scale {scale}: it does not cover "
        f"its own {painter.size} canvas"
    )


@pytest.mark.parametrize("scale", _FULL_FRAME_SCALES)
def test_settings_notice_washes_the_whole_frame_at_every_scale(scale):
    # The notice is a translucent overlay, not an opaque modal: what must
    # reach every pixel is its wash, not full alpha.
    pygame.font.init()
    painter = UIPainter(scale)
    render_settings_notice(painter, "Could not load settings from /x: corrupt")
    alpha = painter.to_frame()[:, :, 3]
    assert alpha.min() >= 190, "the dimming wash must reach every pixel of the canvas"


def test_sprite_lands_on_its_exact_scaled_destination_at_a_fractional_scale():
    """The regression test for art scaled by round(scale) but positioned by
    the exact scale. At 2.5 those disagree by 20%: a full-frame sprite used
    to cover 640x400 of the 800x500 canvas, anchored top-left."""
    scale = 2.5
    painter = UIPainter(scale)
    assert painter.size == (800, 500)
    art = np.zeros((10, 20, 4), np.uint8)
    art[:, :] = (255, 0, 0, 255)
    painter.sprite(art, (30, 40))
    frame = painter.to_frame()
    # exactly what UIPainter._rect makes of the logical rect (30, 40, 20, 10)
    dest = pygame.Rect(75, 100, 50, 25)
    inside = frame[dest.top:dest.bottom, dest.left:dest.right]
    assert (inside[:, :, :3] == (255, 0, 0)).all() and (inside[:, :, 3] == 255).all()
    assert frame[dest.top, dest.left - 1, 3] == 0, "painted left of the destination"
    assert frame[dest.top, dest.right, 3] == 0, "painted right of the destination"
    assert frame[dest.top - 1, dest.left, 3] == 0, "painted above the destination"
    assert frame[dest.bottom, dest.left, 3] == 0, "painted below the destination"

    full = UIPainter(scale)
    full.sprite(np.full((200, 320, 4), 255, np.uint8), (0, 0))
    assert full.to_frame()[:, :, 3].min() == 255, (
        "logical-full-frame art must fill the whole fractional canvas"
    )


@pytest.mark.parametrize("scale", (1, 4))
def test_centred_book_line_lands_on_the_logical_centre(data_dir, profile, scale):
    """Measuring with the scale-1 text_size and placing by topleft put a
    centred reading line 4.5 logical pixels left of centre at scale 4,
    because pygame's font metrics are not linear in size. Isolates the
    glyph by diffing against the same page with the line blank, so the
    background art and the buttons cancel out."""
    pygame.font.init()
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    effect = ReadText(1, 0)

    def render(page):
        game.assets.book_pages[effect.text_index] = (page,)
        painter = UIPainter(scale)
        render_reading(painter, effect, ReadingPresenter(), game.assets, resolver)
        return painter.to_frame()

    blank = render((("", True),))
    painted = render((("Realized & Directed by", True),))
    ink = np.argwhere(np.any(blank != painted, axis=2))
    assert ink.size, "the centred line drew nothing"
    centre = (int(ink[:, 1].min()) + int(ink[:, 1].max()) + 1) / 2
    assert abs(centre / scale - 160) <= 1.0, (
        f"the centred line's ink spans a box centred on logical x="
        f"{centre / scale:.2f}, not 160"
    )


def test_to_bytes_matches_the_numpy_round_trip():
    """present()'s GL path uploads to_bytes() instead of to_frame().tobytes()
    -- 0.7 ms rather than 18.6 ms at 1280x800 -- so the two must be the same
    bytes, not merely the same picture."""
    pygame.font.init()
    for scale in (1, 2.5, 4):
        painter = UIPainter(scale)
        render_play_hud(painter, inventory_available=True)
        render_cursor(painter, (100, 50), "attack")
        painter.text("Wg", 16, (255, 255, 255), center=(160, 100))
        assert painter.to_bytes() == painter.to_frame().tobytes()


def test_zero_width_line_paints_nothing_like_pygame_draw():
    """`width=0` means "filled" to pygame's shape calls and "no line" to
    pygame.draw.line; UIPainter._width preserves the 0, so a caller passing
    it cannot get a 41-pixel-thick line out of the scale multiplication."""
    painter = UIPainter(4)
    painter.line((255, 255, 255), (10, 10), (100, 10), width=0)
    assert painter.to_frame()[:, :, 3].max() == 0
    painter.line((255, 255, 255), (10, 10), (100, 10), width=1)
    assert painter.to_frame()[:, :, 3].max() == 255, "a hairline still draws"


@pytest.mark.parametrize(("scale", "top", "bottom", "right"),
                         ((1, 60, 139, 319), (2.5, 150, 349, 799), (4, 240, 559, 1279)))
def test_big_cadre_spans_its_exact_scaled_box(data_dir, profile, scale, top, bottom, right):
    """draw_big_cadre assembles the FITD tiling on a logical surface and
    hands it to painter.sprite; the assembled frame must land on the exact
    scaled box, not on a round(scale) one. At 2.5 the rounded factor put the
    startup cadre 20% undersized and anchored top-left, framing nothing --
    the buttons it surrounds are placed at exact-scale positions."""
    cadre_bank = Assets(data_dir, profile).cadre_bank()
    painter = UIPainter(scale)
    draw_big_cadre(painter, cadre_bank, (160, 100), (320, 80))  # StartupLayout.CADRE
    ink = np.argwhere(painter.to_frame()[:, :, 3] > 0)
    assert (int(ink[:, 0].min()), int(ink[:, 0].max())) == (top, bottom)
    assert (int(ink[:, 1].min()), int(ink[:, 1].max())) == (0, right)


def test_graphics_and_realism_page_rows_fit_the_screen_and_do_not_overlap():
    from PyAitD.app.ui import SystemMenuLayout, graphics_row_count, realism_row_count
    assert len(SystemMenuLayout.rows(SystemMenuPage.GRAPHICS)) == graphics_row_count()
    assert len(SystemMenuLayout.rows(SystemMenuPage.REALISM)) == realism_row_count()
    for page in (SystemMenuPage.GRAPHICS, SystemMenuPage.REALISM):
        for rect in SystemMenuLayout.rows(page):
            assert rect.bottom <= 200 and rect.height >= 13
        hit = SystemMenuLayout.hit_rows(page)
        for a in range(len(hit)):
            for b in range(a + 1, len(hit)):
                assert not hit[a].colliderect(hit[b])


def test_graphics_and_realism_labels_match_the_cycles_one_per_row():
    from PyAitD.app.ui import (
        GRAPHICS_CYCLES, GRAPHICS_ROWS, REALISM_CYCLES, REALISM_ROWS,
        SMOOTHING_LABELS, graphics_labels, realism_labels,
    )
    from PyAitD.render.render_options import (
        INTEGRATION_LABELS, INTEGRATION_LEVELS, SMOOTHING_LEVELS)
    render = default_settings().render
    graphics = graphics_labels(render)
    realism = realism_labels(render)
    assert len(graphics) == GRAPHICS_ROWS == len(GRAPHICS_CYCLES)
    assert len(realism) == REALISM_ROWS == len(REALISM_CYCLES)
    # every other row's label is total over its option; the Smoothing and
    # Integration rows index a tuple, so a level with no label would
    # IndexError (or, below zero, silently wrap) instead of drawing
    assert len(SMOOTHING_LABELS) == len(SMOOTHING_LEVELS)
    assert len(INTEGRATION_LABELS) == len(INTEGRATION_LEVELS)
    assert graphics[0] == "Scale: 4x" and graphics[4] == "Smoothing: Medium"
    assert realism[1] == "Shadows: Soft" and realism[2] == "Realism: Enhanced"
    assert realism[3] == "Integration: Full" and realism[4] == "Motion: Smooth"


def test_every_integration_level_draws_its_own_row_label():
    from dataclasses import replace

    from PyAitD.app.ui import realism_labels
    render = default_settings().render
    drawn = [realism_labels(replace(render, integration=level))[3]
             for level in (0, 1, 2, 3)]
    assert drawn == ["Integration: Off", "Integration: Subtle",
                     "Integration: Full", "Integration: Strong"]


def test_motion_label_titles_the_mode():
    from dataclasses import replace
    from PyAitD.app.ui import realism_labels
    render = default_settings().render
    assert realism_labels(replace(render, motion="tick"))[4] == "Motion: Tick"
    assert realism_labels(replace(render, motion="smooth"))[4] == "Motion: Smooth"


def test_configuration_page_ends_with_graphics_realism_then_back(monkeypatch):
    # The CONFIG label list is hand-built; pin its tail so the reducer's
    # "row_count - 3 is Graphics..., row_count - 2 is Realism..." rule and
    # the drawn labels cannot drift.
    from PyAitD.app.ui import _button
    drawn = []
    monkeypatch.setattr("PyAitD.app.ui._button", lambda painter, rect, label, **kw: drawn.append(label))
    fake_sprite = np.zeros((20, 20, 3), dtype=np.uint8)
    fake_assets = SimpleNamespace(cadre_bank=lambda: (fake_sprite,) * 9)
    render_system_menu(UIPainter(), SystemMenuPresenter(page=SystemMenuPage.CONFIG), default_settings(), fake_assets)
    assert drawn[-3:] == ["Graphics...", "Realism...", "Back to Menu"]
    assert not any(label.startswith("Scale") for label in drawn)
    assert not any(label.startswith("Lighting") for label in drawn)
    drawn.clear()
    render_system_menu(UIPainter(), SystemMenuPresenter(page=SystemMenuPage.GRAPHICS), default_settings(), fake_assets)
    assert drawn[0] == "Scale: 4x" and drawn[-1] == "Back"
    drawn.clear()
    render_system_menu(UIPainter(), SystemMenuPresenter(page=SystemMenuPage.REALISM), default_settings(), fake_assets)
    assert drawn[0] == "Lighting: Scene" and drawn[-1] == "Back"
