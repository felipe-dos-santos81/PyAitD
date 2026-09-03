# SPDX-License-Identifier: GPL-2.0-only
"""tools/prove_mouse.py: the attic occlusion census the mouse-fidelity proof
document cites -- per camera slot, how many sampled pixels the pre-occlusion
pick accepted as floor and the occluding pick refuses -- and the whole-game
census gate: no camera slot may lose ALL its clickable floor."""
import pytest

pytestmark = pytest.mark.tools

GATE_STRIDE = 16   # coarse: the gate compares the two picks over the SAME
                   # sample, so a wider stride costs sensitivity, never
                   # correctness, and this keeps the whole-game sweep inside
                   # what `make test` can carry


def _fixtures(data_dir, profile):
    import importlib
    from PyAitD.engine.script.game import init_game
    from PyAitD.engine.nav.navmesh import agent_extent
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    return importlib.import_module("tools.prove_mouse"), game, agent_extent(hero)


def test_prove_mouse_counts_occluded_pixels_per_camera(data_dir, profile):
    from PyAitD.engine.data.floor import Floor
    prove_mouse, game, agent = _fixtures(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    floor = Floor(data_dir, 0, profile)
    counts = prove_mouse.count_occluded(floor, hero.room, hero.world_y, agent)
    assert set(counts) == set(range(len(floor.rooms[hero.room].camera_indices)))
    assert all(count >= 0 for count in counts.values())
    assert sum(counts.values()) > 0


def test_no_camera_slot_on_any_floor_loses_all_its_clickable_floor(data_dir, profile):
    """THE gate. A camera slot with pickable floor before the occlusion
    filter and none after is a camera under which the player cannot walk at
    all: no pixel names a destination -- clicks can only steer a bearing, and
    because visible_accept shares the filter, every object click in that room
    goes with it.

    It runs over ALL EIGHT floors on purpose. Floor 0, the attic, is the one
    floor whose cameras sit INSIDE the room they film; every other floor puts
    them behind or above the perimeter wall. A census of floor 0 alone stayed
    green while 87 of the game's 274 camera slots were completely dark --
    which is exactly how that shipped.

    The pick is called the way the shell calls it, with no `occlude=`, so
    this measures what SHIPS. Turning picking.OCCLUDE_BY_DEFAULT on without
    fixing the occluder data fails here.
    """
    prove_mouse, game, agent = _fixtures(data_dir, profile)
    dark = []
    for number in range(8):
        floor = game.load_floor(number)
        rows = prove_mouse.slot_census(floor, 0, agent, stride=GATE_STRIDE)
        dark += [(number, *row) for row in prove_mouse.dead_slots(rows)]
    assert dark == [], (
        f"{len(dark)} camera slots have pickable floor that the shipped pick "
        f"refuses entirely: {dark}"
    )
