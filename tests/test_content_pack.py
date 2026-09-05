# SPDX-License-Identifier: GPL-2.0-only
"""engine.content: pack records, the directory reader, archive checks, and
the world-object attachment (2026-09-03-content-packs-foundation-and-enemies-design.md)."""
import copy

import pytest

from PyAitD.engine.content.schema import (
    BEHAVIOUR_LIFE, PHASES, Anims, Attack, EnemyRecord, PackError, parse_enemy,
)
from PyAitD.engine.content.schema import (
    ALWAYS, Action, Condition, Effect, PickupRecord, Rule, SceneryRecord, TriggerRecord, parse_object,
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


# ── object records ───────────────────────────────────────────────────────────

KEY = {
    "id": "attic_key", "kind": "pickup", "stage": 0, "room": 0,
    "name": "Attic key", "body": 187, "position": [3231, 0, -2248], "beta": 0,
    "zv": "body", "weight": 1,
    "on_take": [{"then": [{"set_flag": "has_key"}, {"message": "A small brass key."}]}],
    "actions": [{"label": "Look", "then": [{"message": "It is warm to the touch."}]}],
}
BARRICADE = {
    "id": "barricade", "kind": "scenery", "stage": 0, "room": 0,
    "body": 8, "position": [3231, 0, -3400], "beta": 0, "zv": "cube", "pushable": False,
}
GATE = {
    "id": "gate", "kind": "trigger", "stage": 0, "room": 0,
    "box": {"x": [2800, 3700], "y": [-500, 500], "z": [-3100, -2700]},
    "on_enter": [
        {"when": {"has_item": "attic_key"},
         "then": [{"delete_object": "barricade"}, {"message": "The barricade gives way."},
                  {"delete_object": "gate"}]},
        {"then": [{"message": "Something heavy blocks the doorway."}]},
    ],
}


def _object(base, **changes):
    table = copy.deepcopy(base)
    for key, value in changes.items():
        if value is None:
            table.pop(key, None)
        else:
            table[key] = value
    return table


def test_parse_object_builds_each_kind():
    key = parse_object(KEY, "objects/attic_key.toml")
    assert key == PickupRecord(
        id="attic_key", kind="pickup", stage=0, room=0, name="Attic key", body=187,
        position=(3231, 0, -2248), beta=0, type_zv=1, weight=1,
        on_take=(Rule(ALWAYS, (Effect("set_flag", "has_key"), Effect("message", "A small brass key."))),),
        actions=(Action("Look", Rule(ALWAYS, (Effect("message", "It is warm to the touch."),))),),
        file="objects/attic_key.toml",
    )
    assert parse_object(BARRICADE, "b.toml") == SceneryRecord(
        id="barricade", kind="scenery", stage=0, room=0, body=8, position=(3231, 0, -3400),
        beta=0, type_zv=2, pushable=False, file="b.toml",
    )
    gate = parse_object(GATE, "g.toml")
    assert gate == TriggerRecord(
        id="gate", kind="trigger", stage=0, room=0, box=(2800, 3700, -500, 500, -3100, -2700),
        on_enter=(
            Rule(Condition(has_item="attic_key"), (
                Effect("delete_object", "barricade"), Effect("message", "The barricade gives way."),
                Effect("delete_object", "gate"))),
            Rule(ALWAYS, (Effect("message", "Something heavy blocks the doorway."),)),
        ),
        file="g.toml",
    )


def test_parse_object_defaults_beta_zv_weight_rules_and_pushable():
    key = parse_object(_object(KEY, beta=None, zv=None, weight=None, on_take=None, actions=None), "k.toml")
    assert (key.beta, key.type_zv, key.weight, key.on_take, key.actions) == (0, 0, 0, (), ())
    assert parse_object(_object(BARRICADE, pushable=None, beta=None, zv=None), "b.toml").pushable is False


def test_records_enumerate_their_rules_in_text_order():
    key, barricade, gate = (parse_object(t, "f") for t in (KEY, BARRICADE, GATE))
    assert [k for k, _ in key.rules()] == ["on_take[0]", "actions[0]"]
    assert key.rules()[1][1] is key.actions[0].rule
    assert barricade.rules() == ()
    assert [k for k, _ in gate.rules()] == ["on_enter[0]", "on_enter[1]"]


@pytest.mark.parametrize("base, changes, key, message", [
    (KEY, {"kind": "door"}, "kind", "'door' is not one of pickup, scenery, trigger"),
    (KEY, {"extra": 1}, "extra", "unknown key"),
    (KEY, {"pushable": True}, "pushable", "unknown key"),
    (KEY, {"name": ""}, "name", "expected a non-empty string, got ''"),
    (KEY, {"stage": None}, "stage", "missing"),
    (KEY, {"weight": -1}, "weight", "-1 is negative"),
    (KEY, {"position": [1, 2]}, "position", "expected [x, y, z], got [1, 2]"),
    (KEY, {"beta": 1024}, "beta", "1024 is outside 0..1023"),
    (KEY, {"on_take": {"then": []}}, "on_take", "expected an array of tables"),
    (KEY, {"on_take": [{"then": []}]}, "on_take[0].then", "expected a non-empty array of effects, got []"),
    (KEY, {"on_take": [{"then": [{"explode": "x"}]}]}, "on_take[0].then[0].explode",
     "unknown effect; expected one of message, set_flag, clear_flag, remove_item, delete_object"),
    (KEY, {"on_take": [{"then": [{"message": "a", "set_flag": "b"}]}]}, "on_take[0].then[0]",
     "expected a table with exactly one key"),
    (KEY, {"on_take": [{"then": [{"message": ""}]}]}, "on_take[0].then[0].message",
     "expected a non-empty string, got ''"),
    (KEY, {"on_take": [{"when": {"near": "x"}, "then": [{"message": "a"}]}]}, "on_take[0].when.near", "unknown key"),
    (KEY, {"on_take": [{"when": {"flag": 3}, "then": [{"message": "a"}]}]}, "on_take[0].when.flag",
     "expected a non-empty string, got 3"),
    (KEY, {"on_take": [{"label": "x", "then": [{"message": "a"}]}]}, "on_take[0].label", "unknown key"),
    (KEY, {"actions": [{"then": [{"message": "a"}]}]}, "actions[0].label", "missing"),
    (KEY, {"actions": [{"label": "a", "then": [{"message": "a"}]}] * 6}, "actions",
     "6 actions is more than the inventory shows (5)"),
    (BARRICADE, {"pushable": "yes"}, "pushable", "expected true or false, got 'yes'"),
    (BARRICADE, {"name": "x"}, "name", "unknown key"),
    (GATE, {"box": {"x": [0, 1], "y": [0, 1]}}, "box", "expected a table with the keys x, y, z"),
    (GATE, {"box": {"x": [0], "y": [0, 1], "z": [0, 1]}}, "box.x", "expected [min, max], got [0]"),
    (GATE, {"box": {"x": [5, 1], "y": [0, 1], "z": [0, 1]}}, "box.x", "min 5 is above max 1"),
    (GATE, {"box": {"x": [0, 40000], "y": [0, 1], "z": [0, 1]}}, "box.x[1]", "40000 is outside -32768..32767"),
    (GATE, {"on_enter": []}, "on_enter", "expected at least one rule"),
    (GATE, {"body": 3}, "body", "unknown key"),
])
def test_parse_object_names_file_key_and_value_on_every_failure(base, changes, key, message):
    with pytest.raises(PackError) as caught:
        parse_object(_object(base, **changes), "o.toml")
    assert (caught.value.file, caught.value.key) == ("o.toml", key)
    assert message in caught.value.message


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


# ── attachment ───────────────────────────────────────────────────────────────


def test_compile_record_is_an_inert_original_record_with_the_sentinel_life():
    from PyAitD.engine.content.world import compile_record
    from PyAitD.engine.data.formats import WorldObject
    record = parse_enemy(PROWLER, "enemies/prowler.toml")
    assert compile_record(record) == WorldObject(
        obj_index=-1, body=24, flags=0x21, type_zv=0,
        found_body=-1, found_name=-1, found_flag=0, found_life=-1,
        x=-5600, y=0, z=1000, alpha=0, beta=0, gamma=0, stage=0, room=0,
        life_mode=1, life=BEHAVIOUR_LIFE, floor_life=-1,
        anim=22, frame=0, anim_type=1, anim_info=-1,
        track_mode=0, track_number=-1, position_in_track=0, mark=0,
    )
    falls = compile_record(parse_enemy(_table(falls=True, zv="cube", life_mode="stage", beta=512), "e.toml"))
    assert (falls.flags, falls.type_zv, falls.life_mode, falls.beta) == (0x121, 2, 0, 512)


def test_init_game_appends_the_pack_after_the_original_records(data_dir, profile, example_pack_dir):
    from PyAitD.engine.content import load_pack
    from PyAitD.engine.script.game import init_game
    pack = load_pack(example_pack_dir, data_dir, profile)
    game = init_game(data_dir, profile, pack=pack)
    assert game.pack is pack
    assert len(game.world_objects) == 294
    assert game.content.first_index == 292
    assert [r.id for r in game.content.records.values()] == ["prowler", "watcher"]
    assert game.content.record_for(292).id == "prowler"
    assert game.content.record_for(9) is None
    assert game.content_state == {292: {"hp": 3, "phase": "idle"}, 293: {"hp": 2, "phase": "idle"}}
    # both spawned into the attic by the ordinary spawn pass, standing
    for idx in (292, 293):
        world = game.world_objects[idx]
        slot = world.obj_index
        assert slot != -1
        actor = game.actors[slot]
        assert (actor.index_in_world, actor.life, actor.life_mode, actor.room) == (idx, BEHAVIOUR_LIFE, 1, 0)
        assert (actor.body_num, actor.anim, actor.anim_type, actor.dyn_flags) == (24, 22, 1, 1)
    prowler = game.actors[game.world_objects[292].obj_index]
    assert (prowler.room_x, prowler.room_y, prowler.room_z) == (-5600, 0, 1000)


def test_attach_is_a_no_op_without_a_pack_and_refuses_a_second_pack(data_dir, profile, example_pack_dir):
    from PyAitD.engine.content import attach, load_pack
    from PyAitD.engine.script.game import init_game
    game = init_game(data_dir, profile)
    assert (game.pack, game.content, game.content_state) == (None, None, {})
    assert attach(game, None) is None
    pack = load_pack(example_pack_dir, data_dir, profile)
    with_pack = init_game(data_dir, profile, pack=pack)
    with pytest.raises(ValueError, match="already attached"):
        attach(with_pack, pack)


def test_an_empty_pack_changes_nothing_but_the_identity(data_dir, profile, tmp_path):
    from PyAitD.engine.content import load_pack
    from PyAitD.engine.script.game import init_game
    empty = load_pack(_write_pack(tmp_path / "empty"), data_dir, profile)
    game = init_game(data_dir, profile, pack=empty)
    assert len(game.world_objects) == 292
    assert (game.content.first_index, game.content.records, game.content_state) == (292, {}, {})


# ── vanilla invariance ───────────────────────────────────────────────────────


def test_an_empty_pack_ticks_identically_to_no_pack(data_dir, profile, tmp_path):
    from PyAitD.engine.content import load_pack
    from PyAitD.engine.data.floor import Floor
    from PyAitD.engine.script.game import init_game
    from PyAitD.engine.script.playworld import IDLE, play_tick
    from PyAitD.engine.script.save import _snapshot_actor
    empty = load_pack(_write_pack(tmp_path / "empty"), data_dir, profile)
    vanilla = init_game(data_dir, profile)
    packed = init_game(data_dir, profile, pack=empty)
    for game in (vanilla, packed):
        game.rng.seed(7)
    floor = Floor(data_dir, 0, profile)
    for tick in range(400):
        play_tick(vanilla, floor, IDLE)
        play_tick(packed, floor, IDLE)
        assert [_snapshot_actor(a) for a in vanilla.actors] == [_snapshot_actor(a) for a in packed.actors], tick
    assert vanilla.timer == packed.timer == 400
