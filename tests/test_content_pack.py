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


# ── the directory reader ─────────────────────────────────────────────────────

PACK_TOML = 'name = "t"\nversion = "1"\ngame = "aitd1"\n'
PROWLER_TOML = """
id = "prowler"
kind = "pursuer"
body = 24
stage = 0
room = 0
position = [-5600, 0, 1000]
hit_points = 3
[anims]
stand = 22
walk = 23
attack = 25
hurt = 21
death = 24
[attack]
frame = 1
group = 22
radius = 400
force = 1
range = 2000
"""


def _write_pack(root, enemies=(), manifest=PACK_TOML):
    root.mkdir(parents=True, exist_ok=True)
    (root / "pack.toml").write_text(manifest)
    if enemies:
        (root / "enemies").mkdir(exist_ok=True)
    for name, text in enemies:
        (root / "enemies" / name).write_text(text)
    return root


def test_read_pack_reads_the_manifest_and_every_enemy_in_name_order(tmp_path):
    from PyAitD.engine.content.pack import Pack, read_pack
    root = _write_pack(tmp_path / "p", [
        ("b.toml", PROWLER_TOML.replace('"prowler"', '"second"')),
        ("a.toml", PROWLER_TOML),
    ])
    pack = read_pack(root)
    assert isinstance(pack, Pack)
    assert (pack.name, pack.version, pack.game, pack.path) == ("t", "1", "aitd1", root)
    assert [e.id for e in pack.enemies] == ["prowler", "second"]
    assert [e.file for e in pack.enemies] == ["enemies/a.toml", "enemies/b.toml"]
    assert pack.identity() == {"name": "t", "version": "1", "digest": pack.digest}


def test_an_empty_pack_is_a_manifest_alone(tmp_path):
    from PyAitD.engine.content.pack import read_pack
    pack = read_pack(_write_pack(tmp_path / "p"))
    assert pack.enemies == ()


def test_read_pack_errors_name_the_file_and_key(tmp_path):
    from PyAitD.engine.content.pack import read_pack
    with pytest.raises(PackError, match=r"^pack\.toml: root: not found in "):
        read_pack(tmp_path / "missing")
    with pytest.raises(PackError, match=r"^pack\.toml: root: cannot parse: "):
        read_pack(_write_pack(tmp_path / "p1", manifest="name = \n"))
    with pytest.raises(PackError, match=r"^pack\.toml: root: expected exactly the keys \['game', 'name', 'version'\], got \['name'\]"):
        read_pack(_write_pack(tmp_path / "p2", manifest='name = "t"\n'))
    with pytest.raises(PackError, match=r"^pack\.toml: version: expected a non-empty string, got 1"):
        read_pack(_write_pack(tmp_path / "p3", manifest='name = "t"\nversion = 1\ngame = "aitd1"\n'))
    with pytest.raises(PackError, match=r"^enemies/x\.toml: root: cannot parse: "):
        read_pack(_write_pack(tmp_path / "p4", [("x.toml", "id = \n")]))
    with pytest.raises(PackError, match=r"^enemies/x\.toml: hit_points: missing"):
        read_pack(_write_pack(tmp_path / "p5", [("x.toml", PROWLER_TOML.replace("hit_points = 3\n", ""))]))
    with pytest.raises(PackError, match=r"^enemies/b\.toml: id: 'prowler' is already used by enemies/a\.toml"):
        read_pack(_write_pack(tmp_path / "p6", [("a.toml", PROWLER_TOML), ("b.toml", PROWLER_TOML)]))


def test_pack_digest_covers_every_toml_by_relative_path_and_is_order_free(tmp_path):
    from PyAitD.engine.content.pack import pack_digest
    a = _write_pack(tmp_path / "a", [("x.toml", PROWLER_TOML), ("y.toml", PROWLER_TOML.replace('"prowler"', '"y"'))])
    b = _write_pack(tmp_path / "b", [("y.toml", PROWLER_TOML.replace('"prowler"', '"y"')), ("x.toml", PROWLER_TOML)])
    assert pack_digest(a) == pack_digest(b)
    (a / "enemies" / "x.toml").write_text(PROWLER_TOML.replace("range = 2000", "range = 2001"))
    assert pack_digest(a) != pack_digest(b)
    (b / "enemies" / "x.toml").rename(b / "enemies" / "z.toml")
    assert pack_digest(a) != pack_digest(b)


def test_the_example_pack_reads(example_pack_dir):
    from PyAitD.engine.content.pack import read_pack
    pack = read_pack(example_pack_dir)
    assert (pack.name, pack.version, pack.game) == ("example", "1", "aitd1")
    assert [(e.id, e.kind) for e in pack.enemies] == [("prowler", "pursuer"), ("watcher", "sentry")]
    prowler, watcher = pack.enemies
    assert (prowler.body, prowler.position, prowler.hit_points) == (24, (-5600, 0, 1000), 3)
    assert (prowler.anims, prowler.attack) == (
        Anims(stand=22, walk=23, attack=25, hurt=21, death=24),
        Attack(frame=1, group=22, radius=400, force=1, range=2000),
    )
    assert (watcher.position, watcher.beta, watcher.anims.walk, watcher.attack.range) == ((2500, 0, 3500), 512, None, 1500)


# ── archive checks (need game data) ──────────────────────────────────────────


def test_load_pack_accepts_the_example_pack_against_real_data(data_dir, profile, example_pack_dir):
    from PyAitD.engine.content.pack import load_pack
    pack = load_pack(example_pack_dir, data_dir, profile)
    assert [e.id for e in pack.enemies] == ["prowler", "watcher"]


def test_check_archives_names_the_offending_key_exactly(tmp_path, data_dir, profile):
    from PyAitD.engine.content.pack import load_pack
    cases = [
        ("body = 24", "body = 272", "body", "272 is not below 272 (LISTBODY)"),
        ("walk = 23", "walk = 305", "anims.walk", "305 is not below 305 (LISTANIM)"),
        ("stage = 0", "stage = 40", "stage", "40: PAK not found"),
        ("room = 0", "room = 99", "room", "99 is not below 1 on stage 0"),
    ]
    for i, (old, new, key, message) in enumerate(cases):
        root = _write_pack(tmp_path / f"p{i}", [("x.toml", PROWLER_TOML.replace(old, new))])
        with pytest.raises(PackError) as caught:
            load_pack(root, data_dir, profile)
        assert (caught.value.file, caught.value.key) == ("enemies/x.toml", key)
        assert caught.value.message.startswith(message), caught.value.message


def test_check_archives_refuses_another_game(tmp_path, data_dir, profile):
    from PyAitD.engine.content.pack import load_pack
    root = _write_pack(tmp_path / "p", manifest=PACK_TOML.replace('"aitd1"', '"aitd2"'))
    with pytest.raises(PackError, match=r"^pack\.toml: game: 'aitd2' is not 'aitd1'"):
        load_pack(root, data_dir, profile)


def test_check_archives_validates_against_both_hero_archives(tmp_path, data_dir, profile, monkeypatch):
    # Carnby's and Emily's paks are validated in turn; a record that fits the
    # first must still fail if it does not fit the second.
    from PyAitD.engine.content import pack as pack_module
    counts = {"LISTBODY": 300, "LISTBOD2": 25, "LISTANIM": 400, "LISTANI2": 400}
    monkeypatch.setattr(pack_module, "_pak_count", lambda data_dir, name: counts[name])
    root = _write_pack(tmp_path / "p", [("x.toml", PROWLER_TOML.replace("body = 24", "body = 30"))])
    with pytest.raises(PackError, match=r"^enemies/x\.toml: body: 30 is not below 25 \(LISTBOD2\)"):
        pack_module.load_pack(root, data_dir, profile)
