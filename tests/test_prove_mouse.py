# SPDX-License-Identifier: GPL-2.0-only
"""tools/prove_mouse.py: the attic occlusion census the mouse-fidelity proof
document cites -- per camera slot, how many sampled pixels the pre-occlusion
pick accepted as floor and the occluded pick now refuses."""
import pytest

pytestmark = pytest.mark.tools


def test_prove_mouse_counts_occluded_pixels_per_camera(data_dir, profile):
    import importlib
    prove_mouse = importlib.import_module("tools.prove_mouse")
    from PyAitD.engine.data.floor import Floor
    from PyAitD.engine.script.game import init_game
    from PyAitD.engine.nav.navmesh import agent_extent
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, 0, profile)
    hero = game.actors[game.current_camera_target_actor]
    counts = prove_mouse.count_occluded(floor, hero.room, hero.world_y, agent_extent(hero))
    assert set(counts) == set(range(len(floor.rooms[hero.room].camera_indices)))
    assert all(count >= 0 for count in counts.values())
    assert sum(counts.values()) > 0
