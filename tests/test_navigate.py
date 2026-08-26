# SPDX-License-Identifier: GPL-2.0-only
import subprocess
import sys

from PyAitD.engine.effects import NavIntent
from PyAitD.engine.game import Actor
from PyAitD.engine.navigate import (
    ARRIVE_DISTANCE, GIVE_UP_ARRIVE_DISTANCE, STALL_TICKS, decide,
)
from PyAitD.engine.tracks import cap_objet

_PURITY_PROBE = """
import sys, PyAitD.engine.navigate
leaked = {"PyAitD.ui", "PyAitD.render", "pygame", "moderngl", "OpenGL"} & sys.modules.keys()
sys.exit(", ".join(sorted(leaked)) or None)
"""


def test_navigate_does_not_import_the_presentation_layer():
    out = subprocess.run([sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True)
    assert out.returncode == 0, f"PyAitD.engine.navigate pulled in {out.stderr.strip()}"


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


def test_contact_steering_advances_inside_the_ordinary_arrival_radius():
    intent = NavIntent(200, 0, 0, waypoints=[(200, 0)])
    intent.path_room = 0
    game = _Game(intent)
    actor = _actor(0, 0)
    assert decide(game, actor, None).arrived is True
    decision = decide(game, actor, None, stop_at_destination=False)
    assert decision.advance is True
    assert decision.joyd & 1
    for _tick in range(STALL_TICKS):
        decision = decide(game, actor, None, stop_at_destination=False)
    assert decision.arrived is True
    assert decision.advance is False


def test_intermediate_waypoints_are_consumed_in_order():
    intent = NavIntent(dest_x=9000, dest_z=0, room=0, waypoints=[(10, 0), (9000, 0)])
    # Simulates a tick after the initial repath already ran (path_room already
    # matches the actor's room), so decide() must NOT re-path here -- if it
    # did, the hand-set two-waypoint list below would be silently replaced by
    # a fresh single-waypoint fallback and the pop loop this test targets
    # would never run.
    intent.path_room = 0
    game = _Game(intent)
    decision = decide(game, _actor(0, 0), None)
    # first waypoint is already within reach, so it pops and we steer to the next
    assert (decision.target_x, decision.target_z) == (9000, 0)
    assert intent.waypoints == [(9000, 0)]
    assert decision.arrived is False


def test_turn_bits_mirror_the_engine_turn_direction():
    # The mirror has to reproduce the *physical* turn, and the two engine
    # functions read the same numeral with opposite meaning:
    #
    #   tracks._turn_toward (mode 4, mode 2):
    #       init_real_value(beta, beta - angle_modif * step, ...)
    #       -> angle_modif == +1 makes beta DECREASE
    #   tracks.gere_manual_rot (mode 1, LM_MANUAL_ROT):
    #       (4, +1), (8, -1) with init_real_value(beta, beta + direction * 0x100)
    #       -> bit 4 makes beta INCREASE
    #
    # so equivalence needs direction == -angle_modif: cap_objet +1 -> bit 8,
    # cap_objet -1 -> bit 4. That is a sign relationship between two functions,
    # not a coincidence of numerals; matching cap_objet +1 with direction +1
    # "because both are +1" inverts every mirrored turn. evalVar 0x13 reports
    # these bits to scripts and LM_MANUAL_ROT rotates by them, so the polarity
    # is observable, and test_the_mirrored_joyd_turns_beta_the_way_mode_4_does
    # below proves it against the engine rather than against this comment.
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

    assert decision_a.joyd & 0xC == 4, "cap_objet -1 must set bit 4, and only bit 4"
    assert decision_b.joyd & 0xC == 8, "cap_objet +1 must set bit 8, and only bit 8"
    # literal bit pin so this test can't quietly agree with whatever decide() returns
    assert decision_a.joyd == 0b0101, "forward (bit 1) + gere_manual_rot direction +1"
    assert decision_b.joyd == 0b1001, "forward (bit 1) + gere_manual_rot direction -1"


def test_the_mirrored_joyd_turns_beta_the_way_mode_4_does():
    # The contract the bit mapping above exists for, checked against the engine:
    # for the same pose and target, the mode-4 path (_turn_toward, which
    # tracks._process_track_mouse applies) and the mirrored joyd fed through
    # mode 1's gere_manual_rot must drive beta in the same direction. Before the
    # polarity fix these ran exactly opposite (+123 vs -123 over 30 ticks).
    from PyAitD.engine.tracks import _turn_toward, gere_manual_rot

    for target in ((9000, 0), (-9000, 0), (5000, 5000), (-5000, 5000)):
        intent = NavIntent(target[0], target[1], 0, waypoints=[target])
        intent.path_room = 0
        game = _Game(intent)
        follower = _actor(0, 0, beta=0)
        mirrored = _actor(0, 0, beta=0)
        follower.speed = mirrored.speed = 4   # gere_manual_rot halves its step at rest
        for tick in range(1, 31):
            game.timer = tick
            intent.waypoints = [target]
            intent.path_room = 0
            decision = decide(game, follower, None)
            _turn_toward(game, follower, decision.target_x, decision.target_z)
            follower.beta &= 0x3FF
            gere_manual_rot(mirrored, 60, decision.joyd, game.timer)
            mirrored.beta &= 0x3FF
        assert follower.beta != 0, f"the fixture must actually turn for {target}"
        assert follower.beta == mirrored.beta, (
            f"target {target}: mode 4 turned to beta {follower.beta} but the "
            f"mirrored joyd turned to {mirrored.beta} — the bits are inverted"
        )


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

    import PyAitD.engine.navigate as navigate_module

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


def test_reaching_the_room_link_is_not_reaching_the_destination():
    # The cross-room repath produces exactly one waypoint, the room-link
    # midpoint. Without a room check, standing on it looks identical to
    # standing on the destination: the hero would halt in the doorway and
    # dispatch as though it had arrived. The type-0 sce_zone that performs the
    # transition begins past the link slab (measured over all 95 type-4 links:
    # median 50 units beyond, max 850), so the hero must keep walking until
    # gere_dec moves it across.
    intent = NavIntent(dest_x=500, dest_z=500, room=3, waypoints=[(200, 800)])
    intent.path_room = 0
    game = _Game(intent)
    actor = _actor(200, 800, room=0)   # standing exactly on the link midpoint
    decision = decide(game, actor, None)
    assert decision.arrived is False, "the doorway is not the destination"
    assert decision.advance is True and decision.joyd & 1, "keep walking through"


def test_reaching_the_destination_in_its_own_room_does_report_arrival():
    # control for the test above: same pose, same waypoint, but this time the
    # actor is in the intent's room, so the waypoint really is the destination
    intent = NavIntent(dest_x=200, dest_z=800, room=3, waypoints=[(200, 800)])
    intent.path_room = 3
    decision = decide(_Game(intent), _actor(200, 800, room=3), None)
    assert decision.arrived is True


def _grind(target, actor):
    """Run a wedged follower (the actor never moves) until it gives up."""
    intent = NavIntent(dest_x=target[0], dest_z=target[1], room=0, waypoints=[target])
    intent.path_room = 0
    game = _Game(intent)
    for tick in range(STALL_TICKS):
        decision = decide(game, actor, None)
        assert decision.advance is True, f"gave up early, at tick {tick}"
    return decide(game, actor, None)


def test_a_follower_wedged_at_its_destination_counts_it_as_arrival():
    # The mesh models hard cols but not other actors' ZVs, so the last stretch
    # to a clicked object can be blocked by whatever is standing on it. Close
    # enough is arrival: the click dispatches instead of grinding forever.
    target = (GIVE_UP_ARRIVE_DISTANCE - 100, 0)
    decision = _grind(target, _actor(0, 0, beta=0))
    assert decision.arrived is True
    assert decision.abandoned is False
    assert decision.advance is False


def test_a_follower_wedged_far_from_its_destination_abandons_the_click():
    # ... but a hero stuck halfway across the room must not act on the object
    # through the wall it is grinding into: the click is dropped, not dispatched
    decision = _grind((9000, 0), _actor(0, 0, beta=0))
    assert decision.arrived is False
    assert decision.abandoned is True


def test_closing_on_the_target_resets_the_give_up_counter():
    intent = NavIntent(dest_x=9000, dest_z=0, room=0, waypoints=[(9000, 0)])
    intent.path_room = 0
    game = _Game(intent)
    actor = _actor(0, 0, beta=0)
    for step in range(STALL_TICKS * 3):
        decide(game, actor, None)
        actor.room_x += 1          # crawling, but closing
        assert intent.stall_ticks <= 1, "progress must keep resetting the counter"
