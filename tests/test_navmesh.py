# SPDX-License-Identifier: GPL-2.0-only
import subprocess
import sys

from PyAitD.floor import Floor
from PyAitD.navmesh import COVER_SCALE, build_cover_grid, cover_polys
from PyAitD.world import is_in_poly

_PURITY_PROBE = """
import sys, PyAitD.navmesh
leaked = {"PyAitD.ui", "PyAitD.render", "pygame", "moderngl", "OpenGL"} & sys.modules.keys()
sys.exit(", ".join(sorted(leaked)) or None)
"""


def test_navmesh_does_not_import_the_presentation_layer():
    out = subprocess.run([sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True)
    assert out.returncode == 0, (
        f"PyAitD.navmesh pulled in {out.stderr.strip()} — the mesh must stay "
        f"importable without the presentation layer so it can build headless"
    )


def test_cover_grid_shape_and_union_are_pinned(data_dir):
    mesh = build_cover_grid(Floor(data_dir, 0), 0)
    assert (mesh.x0, mesh.z0, mesh.step) == (-7540, -4970, 100)
    assert mesh.shape == (151, 141)
    assert int(mesh.walkable.sum()) == 13976


def test_cover_grid_matches_fitd_is_in_poly_cell_for_cell(data_dir):
    # The mesh must never disagree with the predicate the engine itself uses
    # for camera switching (playworld._camera_switch). A generic even-odd fill
    # disagrees on 64 of these cells; vectorising test_cross_product does not.
    floor = Floor(data_dir, 0)
    mesh = build_cover_grid(floor, 0)
    polys = cover_polys(floor, 0)
    mismatches = []
    for i in range(mesh.shape[0]):
        for j in range(mesh.shape[1]):
            x, z = mesh.center_of(i, j)
            cx, cz = x // COVER_SCALE, z // COVER_SCALE
            if bool(mesh.walkable[i, j]) != is_in_poly(cx, cx, cz, cz, polys):
                mismatches.append((i, j))
    assert mismatches == []


def test_room_without_cover_zones_has_no_mesh(data_dir):
    # floor 4 room 1 has camera_indices == [] — no camera views it
    assert build_cover_grid(Floor(data_dir, 4), 1) is None
