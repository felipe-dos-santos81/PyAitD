# SPDX-License-Identifier: GPL-2.0-only
"""Pack directory reader: pack.toml + enemies/*.toml, the identity digest,
and the archive-dependent checks (body/anim counts for every hero, floor
rooms). `read_pack` needs no game data; `load_pack` needs it."""
import hashlib
import pathlib
import tomllib
from dataclasses import dataclass

from PyAitD.engine.content.schema import PackError, parse_enemy
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.data.pak import Pak, PakError, find_pak

PACK_FILE = "pack.toml"
PACK_KEYS = ("game", "name", "version")


@dataclass(frozen=True)
class Pack:
    name: str
    version: str
    game: str
    enemies: tuple
    digest: str
    path: pathlib.Path

    def identity(self):
        """What a save records to refuse loading against another pack."""
        return {"name": self.name, "version": self.version, "digest": self.digest}


def _toml_files(root):
    return sorted(p for p in root.rglob("*.toml") if p.is_file())


def pack_digest(root):
    """SHA-256 over every TOML file's relative path and bytes, in sorted
    path order: a renamed, added or edited file changes it."""
    root = pathlib.Path(root)
    digest = hashlib.sha256()
    for path in _toml_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_toml(path, rel):
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PackError(rel, "root", f"cannot parse: {exc}") from None


def read_pack(path):
    """Read a pack directory into a Pack. Raises PackError; touches no game data."""
    root = pathlib.Path(path)
    manifest = root / PACK_FILE
    if not manifest.is_file():
        raise PackError(PACK_FILE, "root", f"not found in {root}")
    table = _load_toml(manifest, PACK_FILE)
    if sorted(table) != list(PACK_KEYS):
        raise PackError(PACK_FILE, "root", f"expected exactly the keys {list(PACK_KEYS)}, got {sorted(table)}")
    for key in PACK_KEYS:
        if type(table[key]) is not str or not table[key]:
            raise PackError(PACK_FILE, key, f"expected a non-empty string, got {table[key]!r}")
    enemies = []
    owner = {}
    folder = root / "enemies"
    for file in sorted(folder.glob("*.toml")) if folder.is_dir() else ():
        rel = file.relative_to(root).as_posix()
        record = parse_enemy(_load_toml(file, rel), rel)
        if record.id in owner:
            raise PackError(rel, "id", f"{record.id!r} is already used by {owner[record.id]}")
        owner[record.id] = rel
        enemies.append(record)
    return Pack(table["name"], table["version"], table["game"], tuple(enemies), pack_digest(root), root)


def _pak_count(data_dir, name):
    return Pak(str(find_pak(data_dir, name))).count


def check_archives(pack, data_dir, profile):
    """Every body and anim must exist in *both* hero archives (Carnby's and
    Emily's paks differ in count, and a character switch must not fail
    later), and every stage/room must exist in the floor archive."""
    if pack.game != profile.name:
        raise PackError(PACK_FILE, "game", f"{pack.game!r} is not {profile.name!r}")
    archives = []
    for hero in range(len(profile.heroes)):
        body_pak, anim_pak = profile.hero_archives(hero)
        archives.append((body_pak, _pak_count(data_dir, body_pak), anim_pak, _pak_count(data_dir, anim_pak)))
    rooms = {}
    for record in pack.enemies:
        for body_pak, num_bodies, anim_pak, num_anims in archives:
            if record.body >= num_bodies:
                raise PackError(record.file, "body", f"{record.body} is not below {num_bodies} ({body_pak})")
            for key, anim in record.anims.present():
                if anim >= num_anims:
                    raise PackError(record.file, f"anims.{key}", f"{anim} is not below {num_anims} ({anim_pak})")
        if record.stage not in rooms:
            try:
                rooms[record.stage] = len(Floor(data_dir, record.stage, profile).rooms)
            except PakError as exc:
                raise PackError(record.file, "stage", f"{record.stage}: {exc}") from None
        if record.room >= rooms[record.stage]:
            raise PackError(record.file, "room", f"{record.room} is not below {rooms[record.stage]} on stage {record.stage}")


def load_pack(path, data_dir, profile):
    """read_pack + check_archives: the only entry point the app uses."""
    pack = read_pack(path)
    check_archives(pack, data_dir, profile)
    return pack
