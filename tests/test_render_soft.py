# SPDX-License-Identifier: GPL-2.0-only
import numpy as np

from PyAitD.render.asset_resolver import ImageAsset
from PyAitD.render.geometry import BodyGeometry
from PyAitD.engine.data.mask_geometry import MaskDraw
from PyAitD.render.render_soft import SoftwareBackend
from PyAitD.render.scene import ActorDraw, CameraView, FrameDescription
from PyAitD.engine.skel import PrimEntry, RenderResult
from PyAitD.engine.space.world import CameraState
import pytest

pytestmark = pytest.mark.render


def _palette():
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[1], palette[2], palette[3] = (255, 0, 0), (0, 255, 0), (0, 0, 255)
    return palette


def _empty_geometry():
    e = np.zeros((0, 3), dtype=np.float32)
    return BodyGeometry(e, e, np.zeros((0, 3), np.int32), np.zeros(0, np.uint8), np.zeros((0, 2), np.int32),
                        np.zeros(0, np.uint8), (), np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))


def _actor(index, prims, room=0, mask_ids=()):
    return ActorDraw(index, _empty_geometry(), (0.0, 0.0, 0.0), room, (0,) * 6,
                     RenderResult([], prims), mask_ids)


def _frame(actors, masks=(), background=None, palette=None):
    state = CameraState(0, 0, 0, 0, 0, 0, 100, 100, 100).angles()
    if background is None:
        background = np.zeros((200, 320, 3), np.uint8)
    if palette is None:
        palette = _palette()
    return FrameDescription(CameraView(state), ImageAsset(background, False),
                            palette, tuple(actors), tuple(masks))


def test_painter_order_is_the_given_order_across_rooms():
    frame = _frame([_actor(0, [PrimEntry(2, 1, [(20, 10, 1)])], room=0),
                    _actor(1, [PrimEntry(2, 2, [(20, 10, 1)])], room=1),
                    _actor(2, [PrimEntry(2, 3, [(20, 10, 1)])], room=0)])
    out = SoftwareBackend().draw(frame)
    assert out.shape == (200, 320, 3) and tuple(out[10, 20]) == (0, 0, 255)


def test_near_polygon_wins_inside_one_actor_even_if_submitted_last():
    near = PrimEntry(1, 1, [(10, 10, 100), (30, 10, 100), (10, 30, 100)])
    far = PrimEntry(1, 2, [(10, 10, 1000), (30, 10, 1000), (10, 30, 1000)])
    out = SoftwareBackend().draw(_frame([_actor(0, [far, near]), ]))
    assert tuple(out[15, 15]) == (255, 0, 0)
    out = SoftwareBackend().draw(_frame([_actor(0, [near, far]), ]))
    assert tuple(out[15, 15]) == (255, 0, 0)


def test_mask_erases_only_the_actor_it_applies_to():
    mask = MaskDraw(0, (np.array([[20, 10], [21, 10], [21, 11], [20, 11]], np.int16),), (20, 10, 21, 11), 0, ())
    frame = _frame([_actor(0, [PrimEntry(2, 1, [(20, 10, 1)])]),
                    _actor(1, [PrimEntry(2, 2, [(20, 10, 1)])], mask_ids=(0,))], [mask])
    out = SoftwareBackend().draw(frame)
    assert tuple(out[10, 20]) == (255, 0, 0)


def test_background_is_copied_not_aliased():
    background = np.full((200, 320, 3), 9, np.uint8)
    frame = _frame([], background=background)
    out = SoftwareBackend().draw(frame)
    assert out is not background and np.array_equal(out, background)


def test_draw_does_not_mutate_the_frames_background_or_palette():
    background = np.full((200, 320, 3), 9, np.uint8)
    palette = _palette()
    background_before = background.copy()
    palette_before = palette.copy()
    mask = MaskDraw(0, (np.array([[20, 10], [21, 10], [21, 11], [20, 11]], np.int16),), (20, 10, 21, 11), 0, ())
    frame = _frame(
        [_actor(0, [PrimEntry(2, 1, [(20, 10, 1)])]),
         _actor(1, [PrimEntry(2, 2, [(20, 10, 1)])], mask_ids=(0,))],
        [mask], background=background, palette=palette,
    )
    SoftwareBackend().draw(frame)
    assert np.array_equal(background, background_before)
    assert np.array_equal(palette, palette_before)
    assert np.array_equal(frame.background.pixels, background_before)
    assert np.array_equal(frame.palette, palette_before)


def test_draws_a_line_primitive():
    # a horizontal line from (10,50) to (30,50) must colour the midpoint
    line = PrimEntry(0, 1, [(10, 50, 100), (30, 50, 100)])
    out = SoftwareBackend().draw(_frame([_actor(0, [line])]))
    assert tuple(out[50, 20]) == (255, 0, 0)


def test_draws_a_sphere_primitive_at_its_centre():
    sphere = PrimEntry(3, 2, [(50, 60, 100)], 5)
    out = SoftwareBackend().draw(_frame([_actor(0, [sphere])]))
    assert tuple(out[60, 50]) == (0, 255, 0)


def test_draws_a_zixel_point_primitive_as_a_single_pixel():
    # type 7 is a 1px point, same footprint as type 2 (proven by the
    # painter-order test above, which uses type 2 to hit out[10, 20]).
    zixel = PrimEntry(7, 3, [(40, 40, 100)])
    out = SoftwareBackend().draw(_frame([_actor(0, [zixel])]))
    assert tuple(out[40, 40]) == (0, 0, 255)


def test_draws_a_big_point_primitive_as_a_two_pixel_block():
    # type 6 is BigPoint (formats._PRIM_POINT_LIKE); type 4 never occurs --
    # formats.py's loader raises ValueError for it, so it must not appear
    # in this test suite as if it were real body data.
    big_point = PrimEntry(6, 1, [(60, 70, 100)])
    out = SoftwareBackend().draw(_frame([_actor(0, [big_point])]))
    assert tuple(out[70, 60]) == (255, 0, 0)
    assert tuple(out[71, 61]) == (255, 0, 0)


def test_draws_poly_family_types_8_9_10_as_filled_polygons_not_scattered_points():
    # formats.py groups (1, 8, 9, 10) as one poly family, all parsed as
    # N-point polygons; geometry.POLY_TYPES treats them identically in the
    # float path. The software backend must match: 8/9/10 must not fall
    # through to the point/rect default branch.
    for poly_type in (8, 9, 10):
        tri = PrimEntry(poly_type, 1, [(10, 10, 100), (30, 10, 100), (10, 30, 100)])
        out = SoftwareBackend().draw(_frame([_actor(0, [tri])]))
        assert tuple(out[15, 15]) == (255, 0, 0), f"type {poly_type} did not fill the triangle interior"


def test_degenerate_polygon_is_dropped_not_drawn_as_scattered_points():
    # A poly-family primitive with fewer than 3 points is silently dropped
    # by render.py's _ActorLayer (its triangle-fan loop emits nothing for
    # < 3 points); the software backend must match, not fall through to
    # the point/rect default branch and paint stray pixels.
    degenerate = PrimEntry(1, 1, [(60, 70, 100), (61, 70, 100)])
    out = SoftwareBackend().draw(_frame([_actor(0, [degenerate])]))
    assert tuple(out[70, 60]) == (0, 0, 0)
    assert tuple(out[70, 61]) == (0, 0, 0)


def test_mismatched_background_resolution_is_nearest_resized_to_320x200():
    # An override background at a different resolution (e.g. a hi-res asset
    # meant for the GL path) must still come out at the classic 320x200.
    background = np.zeros((400, 640, 3), np.uint8)
    background[200:, :] = (9, 9, 9)  # bottom half distinct from top half
    background_before = background.copy()
    frame = _frame([], background=background)
    out = SoftwareBackend().draw(frame)
    assert out.shape == (200, 320, 3)
    assert tuple(out[0, 0]) == (0, 0, 0)
    assert tuple(out[199, 0]) == (9, 9, 9)
    assert np.array_equal(background, background_before)  # draw() did not mutate the source


def test_thumbnail_starts_blank_and_then_reflects_the_last_draw():
    backend = SoftwareBackend()
    blank = backend.thumbnail()
    assert blank.shape == (200, 320, 3) and np.all(blank == 0)
    background = np.full((200, 320, 3), 7, np.uint8)
    out = backend.draw(_frame([], background=background))
    assert np.array_equal(backend.thumbnail(), out)


def test_thumbnail_is_a_copy_mutating_the_returned_frame_cannot_corrupt_it():
    backend = SoftwareBackend()
    background = np.full((200, 320, 3), 7, np.uint8)
    out = backend.draw(_frame([], background=background))
    out[:] = 0  # a caller mutating the array draw() handed back
    assert not np.all(backend.thumbnail() == 0)
    assert np.array_equal(backend.thumbnail(), np.full((200, 320, 3), 7, np.uint8))
