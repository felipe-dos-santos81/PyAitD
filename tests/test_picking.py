# SPDX-License-Identifier: GPL-2.0-only
import subprocess
import sys

from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.navmesh import COVER_SCALE, cover_polys
from PyAitD.picking import pick_floor, project_floor_point
from PyAitD.world import CameraState

_PURITY_PROBE = """
import sys, PyAitD.picking
leaked = {"PyAitD.ui", "PyAitD.render", "pygame", "moderngl", "OpenGL"} & sys.modules.keys()
sys.exit(", ".join(sorted(leaked)) or None)
"""


def test_picking_does_not_import_the_presentation_layer():
    out = subprocess.run([sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True)
    assert out.returncode == 0, (
        f"PyAitD.picking pulled in {out.stderr.strip()} — picking is pure math "
        f"and must not need a window; __main__ passes it logical coordinates"
    )


def _state(floor, room_idx, cam_idx):
    room = floor.rooms[room_idx]
    camera = floor.cameras[room.camera_indices[cam_idx]]
    return CameraState.from_camera(
        camera, room.world_x, room.world_y, room.world_z,
    ).angles()


def test_pick_floor_round_trips_projected_points(data_dir):
    # For every camera of the opening room, projecting a floor point and
    # picking it back must land within a cell of where it started. The floor
    # is per-camera, not just aggregate: a camera that puts any point on
    # screen must round-trip at least one of them, so a regression narrowed
    # to one camera angle (e.g. a _quad_of corner-selection bug) cannot hide
    # behind other cameras' successes.
    floor = Floor(data_dir, 0)
    game = init_game(data_dir)
    floor_y = game.actors[game.current_camera_target_actor].world_y
    checked = 0
    for cam_slot in range(len(floor.rooms[0].camera_indices)):
        state = _state(floor, 0, cam_slot)
        candidates = 0
        camera_checked = 0
        for poly in cover_polys(floor, 0):
            xs = [p[0] * COVER_SCALE for p in poly]
            zs = [p[1] * COVER_SCALE for p in poly]
            cx, cz = sum(xs) // len(xs), sum(zs) // len(zs)
            screen = project_floor_point(state, cx, floor_y, cz)
            if screen is None:
                continue
            candidates += 1
            picked = pick_floor(screen, floor, 0, cam_slot, floor_y)
            if picked is None:
                continue
            assert abs(picked[0] - cx) <= 100 and abs(picked[1] - cz) <= 100, (
                f"camera {cam_slot}: {picked} should round-trip to {(cx, cz)}"
            )
            camera_checked += 1
        # A camera that never projects a point onto screen has nothing to
        # prove here (that's project_floor_point's culling, not a picking
        # failure). But a camera that *did* put points on screen must
        # round-trip at least one of them, or the fit is broken for it.
        assert candidates == 0 or camera_checked > 0, (
            f"camera {cam_slot}: {candidates} point(s) projected onto screen "
            f"but none round-tripped — the fit is broken for this camera"
        )
        checked += camera_checked
    assert checked > 0, "no floor point round-tripped — the fit never ran"


def test_pick_floor_outside_every_cover_polygon_is_none(data_dir):
    floor = Floor(data_dir, 0)
    # top-left corner of the 320x200 logical surface is ceiling, never floor
    assert pick_floor((2, 2), floor, 0, 0, 0) is None
