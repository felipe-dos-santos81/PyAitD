# SPDX-License-Identifier: GPL-2.0-only
"""Check a texture directory the way the game will load it.

Pure: loads through AssetResolver so whatever it accepts, the game
accepts, and vice versa. PNG decoding is asset_resolver.load_png_rgb.
"""
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from PyAitD.render.asset_resolver import (
    AssetResolver, load_png_rgb, texture_alt_background_path, texture_background_path, texture_body_material_path,
    texture_screen_path,
)
from PyAitD.render.texture_export import SCREEN_ENTRIES, sha256_rgb

ERROR_KINDS = ("invalid", "aspect")
_ASPECT = 320 / 200
_ASPECT_TOL = 0.01
_ORDER = ("regenerated", "original", "missing", "invalid", "aspect")


@dataclass(frozen=True)
class Finding:
    floor: int
    camera: int
    path: Path
    kind: str      # missing | invalid | aspect | size
    detail: str


def has_errors(findings):
    return any(f.kind in ERROR_KINDS for f in findings)


def _each_camera(texture_dir, floors, load_png):
    """Yield (floor, cam_idx, path, resolver) for every camera of every floor;
    one resolver per floor keeps AssetResolver's cache and failures intact."""
    for floor in floors:
        resolver = AssetResolver(None, texture_dir, load_png=load_png)
        for cam_idx in range(len(floor.cameras)):
            yield floor, cam_idx, texture_background_path(texture_dir, floor.number, cam_idx), resolver


def check_textures(texture_dir, floors, manifest=None, *, load_png=load_png_rgb):
    """At most one Finding per camera. `manifest` is accepted for symmetry
    with coverage() and unused here."""
    findings = []
    for floor, cam_idx, path, resolver in _each_camera(texture_dir, floors, load_png):
        if not path.is_file():
            findings.append(Finding(floor.number, cam_idx, path, "missing", "original will be used"))
            continue
        asset = resolver.background(floor, cam_idx)
        if not asset.is_override:
            findings.append(Finding(floor.number, cam_idx, path, "invalid", resolver.failures.get(path, "rejected")))
            continue
        h, w = asset.pixels.shape[:2]
        if abs(w / h - _ASPECT) > _ASPECT * _ASPECT_TOL:
            findings.append(Finding(floor.number, cam_idx, path, "aspect",
                                    f"{w}x{h} is not 16:10 within 1% -- the game would stretch it"))
            continue
        if w < 320 or h < 200 or w % 320 or h % 200:
            findings.append(Finding(floor.number, cam_idx, path, "size",
                                    f"{w}x{h} is not an integer multiple of 320x200"))
    return findings


def coverage(texture_dir, floors, manifest, *, load_png=load_png_rgb):
    """Per-floor counts. An override whose pixels hash to the manifest's
    sha256 is an untouched export ('original'); any other loadable override
    is 'regenerated'."""
    expected = {(c["floor"], c["camera"]): c["sha256"] for c in manifest["cameras"]}
    out = {}
    for floor, cam_idx, path, resolver in _each_camera(texture_dir, floors, load_png):
        counts = out.setdefault(floor.number, {"regenerated": 0, "original": 0, "missing": 0, "invalid": 0})
        if not path.is_file():
            counts["missing"] += 1
            continue
        asset = resolver.background(floor, cam_idx)
        if not asset.is_override:
            counts["invalid"] += 1
        elif sha256_rgb(asset.pixels) == expected.get((floor.number, cam_idx)):
            counts["original"] += 1
        else:
            counts["regenerated"] += 1
    return out


# Hard-coded fallback for the 5 road alts (AITD1.h:15-19) to keep render/ pure
# (no games import). Must stay in sync with games/aitd1/profile.py.
_DEFAULT_ALT_KEYS = [(7, 0), (7, 1), (6, 0), (6, 5), (6, 8)]


def _each_alt_camera(texture_dir, floors, load_png, *, manifest=None):
    """Yield (floor, cam_idx, path, resolver) for every alt camera.

    Alt keys come from manifest["alt_cameras"] when the manifest carries them
    (schema 3), else from the default 5 road alts when there is no manifest.
    An old schema manifest without alt_cameras yields nothing. Only alts
    whose floor is in `floors` are yielded."""
    if manifest is None:
        alt_tuples = list(_DEFAULT_ALT_KEYS)
    elif "alt_cameras" in manifest:
        alt_tuples = [(c["floor"], c["camera"]) for c in manifest.get("alt_cameras", [])]
    else:
        alt_tuples = []
    # dedup + sort for deterministic order
    alt_tuples = sorted(set(alt_tuples))
    if not alt_tuples:
        return
    floor_by_number = {f.number: f for f in floors}
    resolvers = {}
    for floor_num, cam_idx in alt_tuples:
        floor = floor_by_number.get(floor_num)
        if floor is None:
            continue
        if floor_num not in resolvers:
            resolvers[floor_num] = AssetResolver(None, texture_dir, load_png=load_png)
        resolver = resolvers[floor_num]
        path = texture_alt_background_path(texture_dir, floor_num, cam_idx)
        yield floor, cam_idx, path, resolver


def check_alt_backgrounds(texture_dir, floors, manifest=None, *, load_png=load_png_rgb):
    """At most one Finding per alt camera. Reuses _require_rgb/8192/aspect logic via AssetResolver."""
    findings = []
    for floor, cam_idx, path, resolver in _each_alt_camera(texture_dir, floors, load_png, manifest=manifest):
        if not path.is_file():
            findings.append(Finding(floor.number, cam_idx, path, "missing", "original will be used"))
            continue
        asset = resolver.background(floor, cam_idx, killed_sorcerer=True)
        # An invalid alt (corrupt, oversized, non-RGB) lands in failures and falls back to base;
        # detect it via the alt path's failure entry.
        if path in resolver.failures:
            findings.append(Finding(floor.number, cam_idx, path, "invalid", resolver.failures.get(path, "rejected")))
            continue
        if not asset.is_override:
            findings.append(Finding(floor.number, cam_idx, path, "invalid", resolver.failures.get(path, "rejected")))
            continue
        h, w = asset.pixels.shape[:2]
        if abs(w / h - _ASPECT) > _ASPECT * _ASPECT_TOL:
            findings.append(Finding(floor.number, cam_idx, path, "aspect",
                                    f"{w}x{h} is not 16:10 within 1% -- the game would stretch it"))
            continue
        if w < 320 or h < 200 or w % 320 or h % 200:
            findings.append(Finding(floor.number, cam_idx, path, "size",
                                    f"{w}x{h} is not an integer multiple of 320x200"))
    return findings


def alt_coverage(texture_dir, floors, manifest, *, load_png=load_png_rgb):
    """Counts for alt cameras. An override whose sha matches the manifest is 'original'."""
    expected = {(c["floor"], c["camera"]): c["sha256"] for c in manifest.get("alt_cameras", [])} if manifest else {}
    counts = {"regenerated": 0, "original": 0, "missing": 0, "invalid": 0}
    for floor, cam_idx, path, resolver in _each_alt_camera(texture_dir, floors, load_png, manifest=manifest):
        if not path.is_file():
            counts["missing"] += 1
            continue
        asset = resolver.background(floor, cam_idx, killed_sorcerer=True)
        if path in resolver.failures:
            counts["invalid"] += 1
            continue
        if not asset.is_override:
            counts["invalid"] += 1
            continue
        if sha256_rgb(asset.pixels) == expected.get((floor.number, cam_idx)):
            counts["original"] += 1
        else:
            counts["regenerated"] += 1
    return counts


def _each_screen(texture_dir, assets, load_png):
    resolver = AssetResolver(assets, texture_dir, load_png=load_png)
    for entry in SCREEN_ENTRIES:
        yield entry, texture_screen_path(texture_dir, entry), resolver


def check_screens(texture_dir, assets, *, load_png=load_png_rgb):
    """At most one Finding per screen; `floor` is -1, `camera` is the entry."""
    findings = []
    for entry, path, resolver in _each_screen(texture_dir, assets, load_png):
        if not path.is_file():
            findings.append(Finding(-1, entry, path, "missing", "original will be used"))
            continue
        asset = resolver.resource_screen(entry)
        if not asset.is_override:
            findings.append(Finding(-1, entry, path, "invalid", resolver.failures.get(path, "rejected")))
            continue
        h, w = asset.pixels.shape[:2]
        if abs(w / h - _ASPECT) > _ASPECT * _ASPECT_TOL:
            findings.append(Finding(-1, entry, path, "aspect",
                                    f"{w}x{h} is not 16:10 within 1% -- the game would stretch it"))
            continue
        if w < 320 or h < 200 or w % 320 or h % 200:
            findings.append(Finding(-1, entry, path, "size",
                                    f"{w}x{h} is not an integer multiple of 320x200"))
    return findings


def screen_coverage(texture_dir, assets, manifest, *, load_png=load_png_rgb):
    expected = {s["entry"]: s["sha256"] for s in manifest.get("screens", [])}
    counts = {"regenerated": 0, "original": 0, "missing": 0, "invalid": 0}
    for entry, path, resolver in _each_screen(texture_dir, assets, load_png):
        if not path.is_file():
            counts["missing"] += 1
            continue
        asset = resolver.resource_screen(entry)
        if not asset.is_override:
            counts["invalid"] += 1
        elif sha256_rgb(asset.pixels) == expected.get(entry):
            counts["original"] += 1
        else:
            counts["regenerated"] += 1
    return counts


def check_bodies(texture_dir):
    """One Finding per file under bodies/ the game would not load -- a
    material remap or a crease it rejects, or a body*.json whose name the
    resolver would never ask for. `floor` is -2 and `camera` is the body
    number, or -1 when the name carries no readable one. Loads through
    AssetResolver so acceptance stays identical to the game's."""
    bodies = Path(texture_dir) / "bodies"
    findings = []
    # One resolver for the whole directory, as the game has: a fresh one per
    # file would re-log every failure and defeat AssetResolver's log-once.
    resolver = AssetResolver(None, texture_dir)
    for path in sorted(bodies.glob("body*.json")):
        if path.stem.endswith(".uv"):
            continue                  # the runtime's UV sidecar (body<NNN>.uv.json), not an override
        # The name must round-trip through the path the game actually asks
        # for. body7.json reads as body 7 but the game only ever opens
        # body007.json, so such a file would silently never load -- a silent
        # no-op is exactly the failure a checker exists to catch, so it is
        # reported rather than skipped.
        num = int(path.stem[4:]) if path.stem[4:].isdigit() else None
        if num is None or path != texture_body_material_path(texture_dir, num):
            wanted = texture_body_material_path(texture_dir, num).name if num is not None else "body<NNN>.json"
            findings.append(Finding(-2, num if num is not None else -1, path, "invalid",
                                    f"the game never loads this name; it opens {wanted}"))
            continue
        # Reads the file once through the shared _validate_body_override, so
        # this one call already covers both keys the file can carry --
        # materials and crease alike -- and its verdict is final.
        resolver.material_table(num)
        if path in resolver.failures:
            findings.append(Finding(-2, num, path, "invalid", resolver.failures[path]))
    return findings


# Bodies are archive-scoped (Assets(..., hero=h)): the same number can name
# a different body per hero, and hero 1's archive carries numbers hero 0's
# does not. Probing both and taking the first hit mirrors
# tools/export_actor_uvs.py:body_numbers/export_bodies -- but this module
# is under PyAitD/ and must not import tools/, so it keeps its own copy of
# the probe rather than sharing that one.
_BODY_HEROES = (0, 1)


def check_body_textures(texture_dir, data_dir, profile):
    """One Finding per painted body the game could not use.

    A body with no PNG is not a finding -- missing is the steady state, the
    same rule the background override follows. A body that HAS a paint is
    checked hard: the sidecar must exist and parse, its hash must match the
    body's current triangulation (a re-export invalidates stale paints
    loudly), every UV must be inside [0, 1], and the PNG must decode at the
    sidecar's atlas size. `floor` is -3 and `camera` is the body number."""
    from PyAitD.engine.data.assets import Assets
    from PyAitD.render.geometry import pose_geometry
    from PyAitD.render.texture_export import (
        body_texture_rel_path, body_uv_rel_path, sha256_tris,
    )
    texture_dir = Path(texture_dir)
    findings = []
    pngs = sorted((texture_dir / "bodies").glob("body*.png"))
    if not pngs:
        return findings          # nothing painted -- don't even open the archives
    by_hero = {h: Assets(data_dir, profile, hero=h) for h in _BODY_HEROES}
    for png in pngs:
        stem = png.stem
        if stem.endswith("-guide"):
            continue                      # the painter's input, not a paint
        if not stem[4:].isdigit():
            findings.append(Finding(-3, -1, png, "invalid",
                                    "the game never loads this name; it opens body<NNN>.png"))
            continue
        num = int(stem[4:])
        if png != texture_dir / body_texture_rel_path(num):
            findings.append(Finding(-3, num, png, "invalid",
                                    f"the game never loads this name; it opens "
                                    f"{Path(body_texture_rel_path(num)).name}"))
            continue
        uv_path = texture_dir / body_uv_rel_path(num)
        if not uv_path.is_file():
            findings.append(Finding(-3, num, png, "invalid",
                                    f"painted but unmapped: {uv_path.name} is missing"))
            continue
        try:
            payload = json.loads(uv_path.read_text(encoding="utf-8"))
            uvs = np.asarray(payload["uvs"], dtype=np.float32)
            width, height = int(payload["size"][0]), int(payload["size"][1])
            digest = str(payload["tris_sha256"])
        except Exception as exc:
            findings.append(Finding(-3, num, uv_path, "invalid", f"unreadable sidecar: {exc}"))
            continue
        body = None
        for hero in _BODY_HEROES:
            try:
                body = by_hero[hero].body(num)
                break
            except (ValueError, KeyError, IndexError):
                continue
        if body is None:
            findings.append(Finding(-3, num, png, "invalid",
                                    f"body {num} is not in either hero archive; the game has no such body"))
            continue
        tris = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups)).tris
        if digest != sha256_tris(tris):
            findings.append(Finding(-3, num, uv_path, "invalid",
                                    "sidecar was baked against a different triangulation; "
                                    "re-export and repaint"))
            continue
        if uvs.shape != (len(tris), 3, 2):
            findings.append(Finding(-3, num, uv_path, "invalid",
                                    f"expected {(len(tris), 3, 2)} per-corner UVs, got {uvs.shape}"))
            continue
        if float(uvs.min()) < 0.0 or float(uvs.max()) > 1.0:
            findings.append(Finding(-3, num, uv_path, "invalid",
                                    f"UVs outside [0, 1]: [{uvs.min():.4f}, {uvs.max():.4f}]"))
            continue
        try:
            pixels = load_png_rgb(png)
        except Exception as exc:
            findings.append(Finding(-3, num, png, "invalid", f"unreadable: {exc}"))
            continue
        if (pixels.shape[1], pixels.shape[0]) != (width, height):
            findings.append(Finding(-3, num, png, "invalid",
                                    f"is {pixels.shape[1]}x{pixels.shape[0]}, "
                                    f"sidecar says {width}x{height}"))
    return findings


def summarize(findings, cov, screen_cov=None, alt_cov=None):
    lines = []
    for f in findings:
        if f.kind != "missing":
            if f.floor == -1:
                lines.append(f"{f.kind:<7} screen ress{f.camera:02d}  {f.path}: {f.detail}")
            elif f.floor == -2:
                # camera is -1 when the filename carries no readable body number
                body = f"{f.camera:03d}" if f.camera >= 0 else "???"
                lines.append(f"{f.kind:<7} body {body}  {f.path}: {f.detail}")
            elif f.floor == -3:
                # camera is -1 when the filename carries no readable body number
                body = f"{f.camera:03d}" if f.camera >= 0 else "???"
                lines.append(f"{f.kind:<7} body {body} texture  {f.path}: {f.detail}")
            else:
                lines.append(f"{f.kind:<7} floor {f.floor:02d} camera {f.camera:03d}  {f.path}: {f.detail}")
    if cov is None:
        lines.append("coverage: no manifest")
    else:
        aspect_by_floor = {}
        for f in findings:
            if f.kind == "aspect" and f.floor != -1:
                aspect_by_floor[f.floor] = aspect_by_floor.get(f.floor, 0) + 1
        total = {k: 0 for k in _ORDER}
        for number in sorted(cov):
            row = dict(cov[number], aspect=aspect_by_floor.get(number, 0))
            for k in _ORDER:
                total[k] += row[k]
            lines.append(f"floor {number:02d}: " + " / ".join(f"{k} {row[k]}" for k in _ORDER))
        lines.append("total: " + " / ".join(f"{k} {total[k]}" for k in _ORDER))
    if screen_cov is not None:
        lines.append("screens: " + " / ".join(f"{k} {screen_cov[k]}" for k in ("regenerated", "original", "missing", "invalid")))
    if alt_cov is not None:
        lines.append("alt_backgrounds: " + " / ".join(f"{k} {alt_cov[k]}" for k in ("regenerated", "original", "missing", "invalid")))
    body_findings = sum(1 for f in findings if f.floor == -3)
    lines.append(f"bodies: {body_findings} finding(s)")
    return "\n".join(lines)
