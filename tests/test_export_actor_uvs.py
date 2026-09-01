# SPDX-License-Identifier: GPL-2.0-only
"""tools/export_actor_uvs.py: the actor UV bake.

Tools-side: xatlas and igl live in the `tools` extra, so every test here
skips cleanly when the extra is not installed."""
import json

import numpy as np
import pytest

pytestmark = pytest.mark.tools

xatlas = pytest.importorskip("xatlas")
# export_bodies also needs igl.embree (ambient_occlusion); importorskip only
# xatlas here would mean a half-installed tools extra errors instead of
# skipping this module, contradicting the module docstring above.
pytest.importorskip("igl.embree")


def _stub_body():
    """Two triangles sharing an edge, one root group — enough for a real
    unwrap without game data."""
    from types import SimpleNamespace
    from PyAitD.engine.data.formats import Primitive
    group = SimpleNamespace(start=0, num_vertices=4, num_group=0, org_group=-1,
                            base_vertices=0)
    return SimpleNamespace(
        vertices=[(0, 0, 0), (100, 0, 0), (0, 100, 0), (100, 100, 0)],
        groups=[group], group_order=[0], flags=2,
        primitives=[Primitive(1, 0, 10, [0, 1, 3, 2])],
    )


def _point_body():
    """A body with a vertex but no triangle primitive -- the shape real
    bodies 85, 142, 156, 158 and 160 in aitd1 turned out to have: a valid
    Body with vertices and one Point primitive (type 2), nothing for xatlas
    to unwrap."""
    from types import SimpleNamespace
    from PyAitD.engine.data.formats import Primitive
    group = SimpleNamespace(start=0, num_vertices=1, num_group=0, org_group=-1,
                            base_vertices=0)
    return SimpleNamespace(
        vertices=[(0, 0, 0)], groups=[group], group_order=[0], flags=2,
        primitives=[Primitive(2, 0, 5, [0])],
    )


def test_unwrap_produces_per_corner_uvs_aligned_with_the_triangulation():
    from PyAitD.render.geometry import pose_geometry
    from tools.export_actor_uvs import unwrap_body
    body = _stub_body()
    geo = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))
    bake = unwrap_body(body)
    # one UV triple per source triangle, in the source triangle's order
    assert bake.uvs.shape == (len(geo.tris), 3, 2)
    assert bake.uvs.dtype == np.float32
    assert bake.uvs.min() >= 0.0 and bake.uvs.max() <= 1.0
    assert bake.width > 0 and bake.height > 0
    assert bake.chart_count >= 1


def test_unwrap_hash_tracks_the_triangulation_not_the_pose():
    from PyAitD.render.geometry import pose_geometry
    from PyAitD.render.texture_export import sha256_tris
    from tools.export_actor_uvs import unwrap_body
    body = _stub_body()
    geo = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))
    assert unwrap_body(body).tris_sha256 == sha256_tris(geo.tris)


def test_sha256_tris_changes_when_the_triangulation_changes():
    from PyAitD.render.texture_export import sha256_tris
    a = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int32)
    b = np.array([[0, 1, 2], [1, 2, 3]], dtype=np.int32)
    assert sha256_tris(a) == sha256_tris(a.copy())
    assert sha256_tris(a) != sha256_tris(b)


def test_sidecar_payload_round_trips_through_json():
    from tools.export_actor_uvs import sidecar_payload, unwrap_body
    payload = sidecar_payload(unwrap_body(_stub_body()))
    reloaded = json.loads(json.dumps(payload))
    assert reloaded["schema"] == 1
    assert reloaded["size"] == [payload["size"][0], payload["size"][1]]
    assert len(reloaded["uvs"]) == len(payload["uvs"])
    assert len(reloaded["uvs"][0]) == 3 and len(reloaded["uvs"][0][0]) == 2
    assert isinstance(reloaded["tris_sha256"], str) and len(reloaded["tris_sha256"]) == 64


def test_body_paths_are_the_names_the_resolver_opens():
    from PyAitD.render.texture_export import (
        body_guide_rel_path, body_texture_rel_path, body_uv_rel_path,
    )
    assert body_uv_rel_path(7) == "bodies/body007.uv.json"
    assert body_texture_rel_path(7) == "bodies/body007.png"
    assert body_guide_rel_path(7) == "bodies/body007-guide.png"


@pytest.mark.parametrize("body_num", [1, 12, 30])
def test_unwrap_on_real_bodies_keeps_the_corner_order(data_dir, profile, body_num):
    """The whole per-corner design rests on xatlas preserving face order:
    vmapping[indices] == faces exactly. Pinned on real data."""
    from PyAitD.engine.data.assets import Assets
    from PyAitD.render.geometry import pose_geometry
    from tools.export_actor_uvs import unwrap_body
    body = Assets(data_dir, profile).body(body_num)
    geo = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))
    bake = unwrap_body(body)
    assert bake.uvs.shape == (len(geo.tris), 3, 2)
    assert bake.uvs.min() >= 0.0 and bake.uvs.max() <= 1.0


def test_bbox_fill_paints_the_triangle_colour_ao_darkens_and_draws_a_wireframe_edge():
    """Pure-function coverage for the guide renderer -- no igl, no game
    data. A single triangle at known pixel corners in an 11x11 atlas, so
    an interior pixel and an edge pixel are both known in advance."""
    from tools.export_actor_uvs import WIREFRAME_RGB, _bbox_fill
    # corners land exactly on atlas pixels (1, 1), (7, 1), (1, 7) for an
    # 11x11 image (xs = round(u * 10), ys = round(v * 10) -- no flip: v=0
    # is row 0, matching the runtime's top-down upload, see
    # test_guide_orientation_matches_the_runtimes_top_down_upload below)
    corner_uvs = np.array([[[0.1, 0.1], [0.7, 0.1], [0.1, 0.7]]], dtype=np.float32)
    corner_values = np.array([[200, 100, 50]], dtype=np.uint8)

    bright = _bbox_fill((11, 11), corner_uvs, corner_values, np.array([1.0], dtype=np.float32))
    dark = _bbox_fill((11, 11), corner_uvs, corner_values, np.array([0.5], dtype=np.float32))

    assert bright.shape == (11, 11, 3)
    # (2, 2) sits inside the bounding box and off every edge: the flat fill
    interior = (2, 2)
    assert tuple(int(c) for c in bright[interior]) == (200, 100, 50)
    # the same pixel is darkened when the corners' mean openness drops
    assert tuple(int(c) for c in dark[interior]) == (100, 50, 25)
    # (1, 4) sits on the top edge (y=1, x in [1, 7]): the wireframe, not
    # the fill, whichever the openness
    edge = (1, 4)
    assert tuple(int(c) for c in bright[edge]) == WIREFRAME_RGB
    assert tuple(int(c) for c in dark[edge]) == WIREFRAME_RGB


def test_guide_orientation_matches_the_runtimes_top_down_upload():
    """Guide<->runtime orientation contract: `_bbox_fill` must place a known
    UV at row `round(v * (H - 1))`, with no flip, because that is the
    convention the runtime's texture upload actually uses --
    `self._ctx.texture((w, h), 3, data)` at
    PyAitD/render/render_gl.py:918 -- a top-down CPU upload (the same
    convention `_bg_tex` uses, documented at render_gl.py:426-431), so at
    sample time v=0 reads row 0, the top. If a future edit reintroduces a
    (1 - v) flip here, this test pins the row it painted and the row it
    deliberately left untouched, so the drift is caught immediately rather
    than only showing up as an upside-down paint in the game."""
    from tools.export_actor_uvs import _bbox_fill
    # All three corners share v=0.2 -- a degenerate, one-pixel-tall bbox --
    # so the fill lands on exactly one row: round(0.2 * 10) = row 2 of an
    # 11x11 atlas (height - 1 = 10). The mirrored row a (1 - v) flip would
    # use instead -- round((1 - 0.2) * 10) = row 8 -- must stay untouched.
    corner_uvs = np.array([[[0.1, 0.2], [0.9, 0.2], [0.1, 0.2]]], dtype=np.float32)
    corner_values = np.array([[200, 100, 50]], dtype=np.uint8)

    img = _bbox_fill((11, 11), corner_uvs, corner_values, np.array([1.0], dtype=np.float32))

    painted_row, flipped_row, col = 2, 8, 5
    assert tuple(int(c) for c in img[painted_row, col]) != (0, 0, 0)
    assert tuple(int(c) for c in img[flipped_row, col]) == (0, 0, 0)


def test_guide_image_matches_the_atlas_size_and_darkens_with_lower_ao():
    from PyAitD.render.geometry import pose_geometry
    from tools.export_actor_uvs import guide_image, unwrap_body
    body = _stub_body()
    geo = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))
    bake = unwrap_body(body)
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[10] = (200, 100, 50)   # matches _stub_body's Primitive color index
    bright_ao = np.ones(len(geo.vertices), dtype=np.float32)
    dark_ao = np.full(len(geo.vertices), 0.5, dtype=np.float32)

    bright = guide_image(body, bake, palette, bright_ao)
    dark = guide_image(body, bake, palette, dark_ao)

    assert bright.shape == (bake.height, bake.width, 3)
    # the stub's own palette colour is painted somewhere in the chart
    assert (bright == (200, 100, 50)).all(axis=-1).any()
    # lower corner openness darkens the whole image (the wireframe pixels
    # are the same dark grey in both, so only the fill can move the sum)
    assert int(dark.astype(np.int32).sum()) < int(bright.astype(np.int32).sum())


def test_export_bodies_writes_the_sidecar_and_guide_and_skips_bodies_with_no_triangles(tmp_path, monkeypatch):
    """export_bodies against fakes standing in for the archives: one body
    with triangles (baked, one record, both files written) and one without
    (85/142/156/158/160 in the real aitd1 archives -- skipped, not raised)."""
    from types import SimpleNamespace
    import tools.export_actor_uvs as export_actor_uvs
    # export_bodies always runs `from tools.export_textures import
    # save_png`, even when a `save` is already supplied below. If that is
    # the *first* import of tools/export_textures.py in the whole pytest
    # session, it happens while Floor is patched a few lines down --
    # tools/export_textures.py binds its own module-level `Floor` at
    # import time (`from PyAitD.engine.data.floor import Floor`), so it
    # would permanently capture the fake. monkeypatch only restores the
    # attribute it patched on PyAitD.engine.data.floor, not that separate
    # copy, so every later load_floor in the session would return the fake
    # SimpleNamespace instead of a real Floor. Importing the real module
    # here, before any patching, forces it to bind the genuine class.
    import tools.export_textures  # noqa: F401
    from PyAitD.engine.data.floor import Floor as real_floor

    mesh_body = _stub_body()
    point_body = _point_body()

    class _FakeAssets:
        def __init__(self, data_dir, profile, hero=0):
            self._bodies = {0: mesh_body, 1: point_body} if hero == 0 else {}
            self.num_bodies = len(self._bodies)

        def body(self, num):
            if num not in self._bodies:
                raise KeyError(num)
            return self._bodies[num]

    monkeypatch.setattr(export_actor_uvs, "Assets", _FakeAssets)
    monkeypatch.setattr(
        "PyAitD.engine.data.floor.Floor",
        lambda data_dir, number, profile: SimpleNamespace(palette=np.zeros((256, 3), dtype=np.uint8)),
    )
    saved = {}

    def fake_save(path, rgb):
        saved[str(path)] = rgb

    records = export_actor_uvs.export_bodies("ignored", "ignored", tmp_path, save=fake_save)

    assert [r["body"] for r in records] == [0]   # the point body never gets a record
    uv_path = tmp_path / export_actor_uvs.body_uv_rel_path(0)
    assert uv_path.is_file()
    payload = json.loads(uv_path.read_text())
    assert payload["schema"] == 1
    assert len(payload["uvs"]) == 2   # the stub body's two triangles
    guide_path = str(tmp_path / export_actor_uvs.body_guide_rel_path(0))
    assert guide_path in saved
    assert saved[guide_path].shape == (records[0]["size"][1], records[0]["size"][0], 3)
    # the point body wrote nothing at all
    assert not (tmp_path / export_actor_uvs.body_uv_rel_path(1)).exists()
    assert str(tmp_path / export_actor_uvs.body_guide_rel_path(1)) not in saved

    # Cheap guard against the exact leak shape this test used to have:
    # once the Floor patch above is lifted, tools.export_textures must
    # still resolve Floor to the genuine class, not a stale copy of the
    # fake it never should have captured.
    monkeypatch.undo()
    import tools.export_textures as export_textures
    assert export_textures.Floor is real_floor
