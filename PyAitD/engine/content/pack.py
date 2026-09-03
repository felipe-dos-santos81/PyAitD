# SPDX-License-Identifier: GPL-2.0-only
"""Pack directory reader: pack.toml + enemies/*.toml, the identity digest,
and the archive-dependent checks (body/anim counts for every hero, floor
rooms). `read_pack` needs no game data; `load_pack` needs it."""
import hashlib
import pathlib
import tomllib
from dataclasses import dataclass

from PyAitD.engine.content.schema import PackError, parse_enemy

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
