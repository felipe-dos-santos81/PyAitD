# SPDX-License-Identifier: GPL-2.0-only
"""engine.content: pack records, the directory reader, archive checks, and
the world-object attachment (2026-09-03-content-packs-foundation-and-enemies-design.md)."""
import copy

import pytest

from PyAitD.engine.content.schema import (
    BEHAVIOUR_LIFE, PHASES, Anims, Attack, EnemyRecord, PackError, parse_enemy,
)

pytestmark = pytest.mark.engine

PROWLER = {
    "id": "prowler", "kind": "pursuer", "body": 24, "stage": 0, "room": 0,
    "position": [-5600, 0, 1000], "beta": 0, "zv": "max", "life_mode": "room",
    "falls": False, "hit_points": 3,
    "anims": {"stand": 22, "walk": 23, "attack": 25, "hurt": 21, "death": 24},
    "attack": {"frame": 1, "group": 22, "radius": 400, "force": 1, "range": 2000},
}


def _table(**changes):
    table = copy.deepcopy(PROWLER)
    for key, value in changes.items():
        if value is None:
            table.pop(key, None)
        else:
            table[key] = value
    return table


def test_sentinel_and_vocabularies_are_pinned():
    assert BEHAVIOUR_LIFE == -2
    assert PHASES == ("idle", "chase", "attack", "hurt", "dying", "dead")


def test_parse_enemy_builds_a_record_with_compiled_enums():
    record = parse_enemy(PROWLER, "enemies/prowler.toml")
    assert record == EnemyRecord(
        id="prowler", kind="pursuer", body=24, stage=0, room=0,
        position=(-5600, 0, 1000), beta=0, type_zv=0, life_mode=1, falls=False,
        hit_points=3,
        anims=Anims(stand=22, walk=23, attack=25, hurt=21, death=24),
        attack=Attack(frame=1, group=22, radius=400, force=1, range=2000),
        file="enemies/prowler.toml",
    )
    assert record.anims.present() == (("stand", 22), ("walk", 23), ("attack", 25), ("hurt", 21), ("death", 24))


def test_parse_enemy_defaults_beta_zv_life_mode_and_falls():
    record = parse_enemy(_table(beta=None, zv=None, life_mode=None, falls=None), "e.toml")
    assert (record.beta, record.type_zv, record.life_mode, record.falls) == (0, 0, 1, False)


def test_a_sentry_omits_walk_and_a_pursuer_requires_it():
    sentry = _table(kind="sentry", anims={"stand": 22, "attack": 25, "hurt": 21, "death": 24})
    assert parse_enemy(sentry, "e.toml").anims.walk is None
    assert parse_enemy(sentry, "e.toml").anims.present() == (("stand", 22), ("attack", 25), ("hurt", 21), ("death", 24))
    with pytest.raises(PackError, match=r"^e\.toml: anims\.walk: missing"):
        parse_enemy(_table(anims={"stand": 22, "attack": 25, "hurt": 21, "death": 24}), "e.toml")
    with pytest.raises(PackError, match=r"^e\.toml: anims\.walk: a sentry never walks"):
        parse_enemy(_table(kind="sentry"), "e.toml")


@pytest.mark.parametrize("changes, key, message", [
    ({"id": None}, "id", "missing"),
    ({"id": ""}, "id", "expected a non-empty string, got ''"),
    ({"kind": "boss"}, "kind", "'boss' is not one of pursuer, sentry"),
    ({"body": -1}, "body", "-1 is negative"),
    ({"body": 40000}, "body", "40000 is outside -32768..32767"),
    ({"body": "24"}, "body", "expected an integer, got '24'"),
    ({"body": True}, "body", "expected an integer, got True"),
    ({"stage": -1}, "stage", "-1 is negative"),
    ({"room": None}, "room", "missing"),
    ({"position": [1, 2]}, "position", "expected [x, y, z], got [1, 2]"),
    ({"position": [1, 2, 99999]}, "position[2]", "99999 is outside -32768..32767"),
    ({"beta": 1024}, "beta", "1024 is outside 0..1023"),
    ({"zv": "sphere"}, "zv", "'sphere' is not one of max, body, cube, rotated"),
    ({"life_mode": "camera"}, "life_mode", "'camera' is not one of stage, room"),
    ({"falls": 1}, "falls", "expected true or false, got 1"),
    ({"hit_points": 0}, "hit_points", "0 is below 1"),
    ({"anims": None}, "anims", "missing"),
    ({"anims": {"stand": 22, "walk": 23, "attack": 25, "hurt": 21}}, "anims.death", "missing"),
    ({"anims": {"stand": 22, "walk": -3, "attack": 25, "hurt": 21, "death": 24}}, "anims.walk", "-3 is negative"),
    ({"anims": {"stand": 22, "walk": 23, "attack": 25, "hurt": 21, "death": 24, "fly": 1}}, "anims.fly", "unknown key"),
    ({"attack": {"frame": 1, "group": 22, "radius": 400, "force": 1}}, "attack.range", "missing"),
    ({"attack": {"frame": 1, "group": 22, "radius": -1, "force": 1, "range": 2000}}, "attack.radius", "-1 is negative"),
    ({"colour": "red"}, "colour", "unknown key"),
])
def test_parse_enemy_names_file_key_and_value_on_every_failure(changes, key, message):
    with pytest.raises(PackError) as caught:
        parse_enemy(_table(**changes), "enemies/bad.toml")
    assert str(caught.value) == f"enemies/bad.toml: {key}: {message}"
    assert (caught.value.file, caught.value.key, caught.value.message) == ("enemies/bad.toml", key, message)


def test_parse_enemy_rejects_a_non_table():
    with pytest.raises(PackError, match=r"^e\.toml: root: expected a table"):
        parse_enemy(["not", "a", "table"], "e.toml")
