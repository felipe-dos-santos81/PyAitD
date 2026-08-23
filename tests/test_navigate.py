# SPDX-License-Identifier: GPL-2.0-only
import subprocess
import sys

from PyAitD.effects import NavIntent
from PyAitD.game import Actor
from PyAitD.navigate import ARRIVE_DISTANCE, decide
from PyAitD.tracks import cap_objet

_PURITY_PROBE = """
import sys, PyAitD.navigate
leaked = {"PyAitD.ui", "PyAitD.render", "pygame", "moderngl", "OpenGL"} & sys.modules.keys()
sys.exit(", ".join(sorted(leaked)) or None)
"""


def test_navigate_does_not_import_the_presentation_layer():
    out = subprocess.run([sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True)
    assert out.returncode == 0, f"PyAitD.navigate pulled in {out.stderr.strip()}"


class _Game:
    def __init__(self, intent):
        self.nav_intent = intent
        self.timer = 0


def _actor(x, z, beta=0, room=0):
    actor = Actor()
    actor.room_x, actor.room_z, actor.room = x, z, room
    actor.world_x, actor.world_z = x, z
    actor.beta = beta
    return actor


def test_no_intent_means_no_decision():
    assert decide(_Game(None), _actor(0, 0), None) is None


def test_far_from_the_destination_the_follower_advances():
    game = _Game(NavIntent(dest_x=5000, dest_z=0, room=0, waypoints=[(5000, 0)]))
    decision = decide(game, _actor(0, 0), None)
    assert decision.advance is True
    assert decision.arrived is False
    assert decision.joyd & 1, "forward bit must be mirrored while advancing"
    assert (decision.target_x, decision.target_z) == (5000, 0)


def test_reaching_the_final_waypoint_reports_arrival():
    game = _Game(NavIntent(dest_x=10, dest_z=10, room=0, waypoints=[(10, 10)]))
    decision = decide(game, _actor(0, 0), None)
    assert decision.arrived is True
    assert decision.advance is False
    assert decision.joyd == 0, "an arrived follower presses nothing"


def test_intermediate_waypoints_are_consumed_in_order():
    intent = NavIntent(dest_x=9000, dest_z=0, room=0, waypoints=[(10, 0), (9000, 0)])
    game = _Game(intent)
    decision = decide(game, _actor(0, 0), None)
    # first waypoint is already within reach, so it pops and we steer to the next
    assert (decision.target_x, decision.target_z) == (9000, 0)
    assert intent.waypoints == [(9000, 0)]
    assert decision.arrived is False


def test_turn_bits_mirror_the_engine_turn_direction():
    # Pin the actual contract, not just "the two decisions differ" (which would still
    # pass if the polarity were inverted end-to-end). The targets sit to the side of a
    # beta=0 actor's facing ray (the +Z axis - see the dead-ahead/dead-behind test below
    # for why an on-axis target can't be used here), so cap_objet must return a real
    # +1/-1 turn sign for each, and decide() must mirror that sign through
    # gere_manual_rot's bit->direction mapping: cap_objet +1 -> direction +1 -> bit 4,
    # cap_objet -1 -> direction -1 -> bit 8.
    actor_a = _actor(0, 0, beta=0)
    target_a = (9000, 0)
    sign_a = cap_objet(actor_a.room_x, actor_a.room_z, actor_a.beta, *target_a)
    decision_a = decide(_Game(NavIntent(*target_a, 0, waypoints=[target_a])), actor_a, None)

    actor_b = _actor(0, 0, beta=0)
    target_b = (-9000, 0)
    sign_b = cap_objet(actor_b.room_x, actor_b.room_z, actor_b.beta, *target_b)
    decision_b = decide(_Game(NavIntent(*target_b, 0, waypoints=[target_b])), actor_b, None)

    # fixture sanity: the two targets must actually require opposite turns, or the rest
    # of this test would be vacuous
    assert (sign_a, sign_b) == (-1, 1)

    assert decision_a.joyd & 0xC == 8, "cap_objet -1 must set bit 8, and only bit 8"
    assert decision_b.joyd & 0xC == 4, "cap_objet +1 must set bit 4, and only bit 4"
    # literal bit pin so this test can't quietly agree with whatever decide() returns
    assert decision_a.joyd == 0b1001, "forward (bit 1) + turn-right (bit 8)"
    assert decision_b.joyd == 0b0101, "forward (bit 1) + turn-left (bit 4)"


def test_dead_ahead_and_dead_behind_targets_need_no_turn():
    # cap_objet brackets the turn decision by evaluating at beta-4 and beta+4. When the
    # target sits exactly on the beta=0 facing axis - dead ahead or dead behind - that
    # bracket can't favor either side (dead-ahead resolves via the exact-beta recompute
    # branch to 0; dead-behind is a genuine 180-degree tie, (1 + -1 + 1) >> 1 == 0), so
    # cap_objet legitimately returns 0 and decide() must not set a turn bit. This is real
    # engine behaviour, not a gap in the implementation: a follower walking straight at
    # (or straight away from) its own facing direction should keep walking straight, not
    # stall or oscillate hunting for a turn that doesn't exist.
    ahead = decide(_Game(NavIntent(0, 9000, 0, waypoints=[(0, 9000)])), _actor(0, 0, beta=0), None)
    behind = decide(_Game(NavIntent(0, -9000, 0, waypoints=[(0, -9000)])), _actor(0, 0, beta=0), None)
    for decision in (ahead, behind):
        assert decision.joyd & 1, "must still advance"
        assert decision.joyd & 0xC == 0, "on-axis target must not set a turn bit"


def test_arrival_threshold_is_the_engine_track_threshold():
    assert ARRIVE_DISTANCE == 400


def test_a_destination_in_another_room_steers_to_the_room_link():
    # the follower must not path straight at coordinates that belong to a
    # different room's origin; it aims for the link zone first
    class _LinkGame(_Game):
        def __init__(self, intent):
            super().__init__(intent)
            self.link_asked = None

    intent = NavIntent(dest_x=500, dest_z=500, room=3, waypoints=None)
    game = _LinkGame(intent)
    actor = _actor(0, 0, room=0)

    import PyAitD.navigate as navigate_module

    class _Zone:
        x1, x2, y1, y2, z1, z2, type, parameter = 100, 300, 0, 0, 700, 900, 4, 3

    original = navigate_module.get_room_link
    navigate_module.get_room_link = lambda g, a, b: (
        setattr(g, "link_asked", (a, b)) or _Zone()
    )
    try:
        decision = navigate_module.decide(game, actor, None)
    finally:
        navigate_module.get_room_link = original

    assert game.link_asked == (0, 3)
    assert (decision.target_x, decision.target_z) == (200, 800)  # zone centre
    assert intent.path_room == 0, "waypoints belong to the room we started in"


def test_entering_the_target_room_repaths_to_the_real_destination():
    intent = NavIntent(dest_x=500, dest_z=500, room=3, waypoints=[(9, 9)])
    intent.path_room = 0
    game = _Game(intent)
    actor = _actor(0, 0, room=3)          # gere_dec moved us into room 3
    decision = decide(game, actor, None)
    assert intent.path_room == 3
    assert (decision.target_x, decision.target_z) == (500, 500)
