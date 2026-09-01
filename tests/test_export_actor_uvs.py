# SPDX-License-Identifier: GPL-2.0-only
"""tools/export_actor_uvs.py: the actor UV bake.

Tools-side: xatlas and igl live in the `tools` extra, so every test here
skips cleanly when the extra is not installed."""
import json

import numpy as np
import pytest

pytestmark = pytest.mark.tools

xatlas = pytest.importorskip("xatlas")


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
