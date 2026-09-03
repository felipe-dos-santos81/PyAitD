# SPDX-License-Identifier: GPL-2.0-only
"""Build the navmesh for every camera-visible room on every floor, and
census the floor pick over every camera slot of every room of every floor.

Reports walkable counts. Near-empty cave rooms are a KNOWN boundary (type-3
climbable walls tile their cover area and nothing consumes hard_col == 255
yet), so they are reported, not failed on.

The census is the gate the occlusion filter has to pass: a camera slot with
pickable floor before the filter and none after is a camera the player cannot
walk under at all. It runs over all eight floors -- floor 0, the attic, is
the ONE floor whose cameras sit inside the room they film, so a floor-0-only
census says nothing about the other seven. Exit status is nonzero if the
SHIPPED pick leaves any slot dark; the "forced on" column is what
picking.OCCLUDE_BY_DEFAULT would cost today.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PyAitD.engine.script.game import init_game
from PyAitD.engine.nav.navmesh import agent_extent, build_room_mesh
from PyAitD.engine.nav.picking import OCCLUDE_BY_DEFAULT, pick_floor_any_room
from PyAitD.games.aitd1.profile import AITD1

DEFAULT_DATA = (
    pathlib.Path(__file__).resolve().parent.parent
    / "data" / "aitd1" / "Alone in the Dark 1.app" / "Contents" / "Resources" / "game" / "INDARK"
)


CENSUS_STRIDE = 10   # every floor, every room, every slot: coarse enough to
                     # run in under a minute, fine enough that the reviewer's
                     # own stride-10 numbers reproduce exactly


def sampled_pixels(stride):
    return [(x, y) for y in range(199, 40, -stride) for x in range(2, 320, stride)]


def slot_census(floor, floor_y, agent, stride=CENSUS_STRIDE, occlude=None, rooms=None):
    """{(room, camera slot): (baseline, kept)} sampled-pixel counts.

    `baseline` is the pre-occlusion pick (occlude=False), `kept` the pick
    under `occlude` -- None meaning "whatever pick_floor_any_room ships as
    its default", which is the form the shell calls and therefore the form
    the census gate has to measure. A slot with baseline > 0 and kept == 0 is
    a camera the player cannot walk under at all: see dead_slots.
    """
    pixels = sampled_pixels(stride)
    kwargs = {} if occlude is None else {"occlude": occlude}
    rows = {}
    for room_idx in (range(len(floor.rooms)) if rooms is None else rooms):
        for slot in range(len(floor.rooms[room_idx].camera_indices)):
            baseline = kept = 0
            for pixel in pixels:
                # the pick under test runs first and a kept pixel counts for
                # both columns: occlusion only ever REMOVES picks (pinned by
                # test_occlusion_only_removes_picks_and_removes_some), so a
                # kept pixel was a baseline pixel. That makes the whole census
                # one pick per pixel wherever nothing is refused.
                if pick_floor_any_room(
                        pixel, floor, room_idx, slot, floor_y, agent=agent,
                        **kwargs) is not None:
                    baseline += 1
                    kept += 1
                elif pick_floor_any_room(
                        pixel, floor, room_idx, slot, floor_y, occlude=False) is not None:
                    baseline += 1
            rows[(room_idx, slot)] = (baseline, kept)
    return rows


def dead_slots(rows):
    """The camera slots a filter kills outright: floor to pick before it,
    none after. [(room, slot, baseline pixels), ...]"""
    return [
        (room_idx, slot, baseline)
        for (room_idx, slot), (baseline, kept) in sorted(rows.items())
        if baseline and not kept
    ]


def count_occluded(floor, hero_room, floor_y, agent, stride=5):
    """Per camera slot of hero_room: how many sampled pixels the pre-occlusion
    pick accepted as floor and the OCCLUDING pick refuses -- the wall and
    furniture pixels that would stop falling through onto the floor behind
    them. occlude=True is forced: this measures what the filter is worth, not
    what ships (picking.OCCLUDE_BY_DEFAULT is off -- see the census below)."""
    rows = slot_census(floor, floor_y, agent, stride, occlude=True, rooms=[hero_room])
    return {
        slot: baseline - kept
        for (_room, slot), (baseline, kept) in sorted(rows.items())
    }


def main(argv):
    data = pathlib.Path(argv[0]) if argv else DEFAULT_DATA
    game = init_game(data, AITD1)
    agent = agent_extent(game.actors[game.current_camera_target_actor])
    built = skipped = empty = slots = refused_pixels = 0
    shipped_dead, forced_dead = [], []
    for number in range(8):
        floor = game.load_floor(number)
        for room_idx, room in enumerate(floor.rooms):
            mesh = build_room_mesh(floor, room_idx, agent)
            if mesh is None:
                skipped += 1
                print(f"floor {number} room {room_idx:2d}: no camera views it — skipped")
                continue
            built += 1
            count = int(mesh.walkable.sum())
            note = ""
            if count == 0:
                empty += 1
                note = "  <- EMPTY (known: climbable-wall floor)"
            print(f"floor {number} room {room_idx:2d}: {mesh.shape} "
                  f"walkable {count}{note}")
        if number == 0:
            hero = game.actors[game.current_camera_target_actor]
            for slot, refused in count_occluded(floor, hero.room, hero.world_y, agent).items():
                print(f"floor 0 camera slot {slot}: {refused} wall/furniture pixels would stop picking the floor behind them")
        rows = slot_census(floor, 0, agent, occlude=True)
        forced = dead_slots(rows)
        with_floor = sum(1 for baseline, _kept in rows.values() if baseline)
        refused = sum(baseline - kept for baseline, kept in rows.values())
        shipped_dead += dead_slots(slot_census(floor, 0, agent))
        slots += with_floor
        forced_dead += [(number, *row) for row in forced]
        refused_pixels += refused
        print(f"floor {number}: {with_floor} camera slots with pickable floor, "
              f"{len(forced)} would go dark with occlusion forced on, "
              f"{refused} sampled pixels refused")
    print(f"\nbuilt {built} meshes, {skipped} rooms without cameras, {empty} empty")
    print(f"\ncamera slots with any pickable floor: {slots}")
    print(f"slots with NO pickable pixel under the shipped pick: {len(shipped_dead)}")
    print(f"slots that would have none with occlusion forced on: {len(forced_dead)}"
          f"  ({refused_pixels} sampled pixels refused in total)")
    for number, room_idx, slot, baseline in forced_dead:
        print(f"  would go dark: floor {number} room {room_idx} slot {slot} "
              f"({baseline} baseline pixels)")
    verdict = ("every camera slot keeps clickable floor" if not shipped_dead
               else f"{len(shipped_dead)} CAMERA SLOTS HAVE NO CLICKABLE FLOOR")
    print(f"\npicking.OCCLUDE_BY_DEFAULT is "
          f"{'on' if OCCLUDE_BY_DEFAULT else 'off'} and {verdict}; "
          "see the constant for why the filter is where it is.")
    return 0 if not shipped_dead else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
