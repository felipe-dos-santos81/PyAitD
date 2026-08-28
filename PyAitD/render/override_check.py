# SPDX-License-Identifier: GPL-2.0-only
"""Check an override directory the way the game will load it.

Pure: loads through AssetResolver so whatever it accepts, the game
accepts, and vice versa. PNG decoding is asset_resolver.load_png_rgb.
"""
from dataclasses import dataclass
from pathlib import Path

from PyAitD.render.asset_resolver import (
    AssetResolver, load_png_rgb, override_background_path, override_body_material_path, override_screen_path,
)
from PyAitD.render.background_export import SCREEN_ENTRIES, sha256_rgb

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


def _each_camera(override_dir, floors, load_png):
    """Yield (floor, cam_idx, path, resolver) for every camera of every floor;
    one resolver per floor keeps AssetResolver's cache and failures intact."""
    for floor in floors:
        resolver = AssetResolver(None, override_dir, load_png=load_png)
        for cam_idx in range(len(floor.cameras)):
            yield floor, cam_idx, override_background_path(override_dir, floor.number, cam_idx), resolver


def check_overrides(override_dir, floors, manifest=None, *, load_png=load_png_rgb):
    """At most one Finding per camera. `manifest` is accepted for symmetry
    with coverage() and unused here."""
    findings = []
    for floor, cam_idx, path, resolver in _each_camera(override_dir, floors, load_png):
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


def coverage(override_dir, floors, manifest, *, load_png=load_png_rgb):
    """Per-floor counts. An override whose pixels hash to the manifest's
    sha256 is an untouched export ('original'); any other loadable override
    is 'regenerated'."""
    expected = {(c["floor"], c["camera"]): c["sha256"] for c in manifest["cameras"]}
    out = {}
    for floor, cam_idx, path, resolver in _each_camera(override_dir, floors, load_png):
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


def _each_screen(override_dir, assets, load_png):
    resolver = AssetResolver(assets, override_dir, load_png=load_png)
    for entry in SCREEN_ENTRIES:
        yield entry, override_screen_path(override_dir, entry), resolver


def check_screens(override_dir, assets, *, load_png=load_png_rgb):
    """At most one Finding per screen; `floor` is -1, `camera` is the entry."""
    findings = []
    for entry, path, resolver in _each_screen(override_dir, assets, load_png):
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


def screen_coverage(override_dir, assets, manifest, *, load_png=load_png_rgb):
    expected = {s["entry"]: s["sha256"] for s in manifest.get("screens", [])}
    counts = {"regenerated": 0, "original": 0, "missing": 0, "invalid": 0}
    for entry, path, resolver in _each_screen(override_dir, assets, load_png):
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


def check_body_materials(override_dir):
    """One Finding per file under bodies/ the game would not load: a
    body<NNN>.json the resolver rejects, or a body*.json whose name the
    resolver would never ask for. `floor` is -2 and `camera` is the body
    number, or -1 when the name carries no readable one. Loads through
    AssetResolver so acceptance stays identical to the game's."""
    bodies = Path(override_dir) / "bodies"
    findings = []
    # One resolver for the whole directory, as the game has: a fresh one per
    # file would re-log every failure and defeat AssetResolver's log-once.
    resolver = AssetResolver(None, override_dir)
    for path in sorted(bodies.glob("body*.json")):
        # The name must round-trip through the path the game actually asks
        # for. body7.json reads as body 7 but the game only ever opens
        # body007.json, so such a file would silently never load -- a silent
        # no-op is exactly the failure a checker exists to catch, so it is
        # reported rather than skipped.
        num = int(path.stem[4:]) if path.stem[4:].isdigit() else None
        if num is None or path != override_body_material_path(override_dir, num):
            wanted = override_body_material_path(override_dir, num).name if num is not None else "body<NNN>.json"
            findings.append(Finding(-2, num if num is not None else -1, path, "invalid",
                                    f"the game never loads this name; it opens {wanted}"))
            continue
        resolver.material_table(num)
        if path in resolver.failures:
            findings.append(Finding(-2, num, path, "invalid", resolver.failures[path]))
    return findings


def summarize(findings, cov, screen_cov=None):
    lines = []
    for f in findings:
        if f.kind != "missing":
            if f.floor == -1:
                lines.append(f"{f.kind:<7} screen ress{f.camera:02d}  {f.path}: {f.detail}")
            elif f.floor == -2:
                # camera is -1 when the filename carries no readable body number
                body = f"{f.camera:03d}" if f.camera >= 0 else "???"
                lines.append(f"{f.kind:<7} body {body}  {f.path}: {f.detail}")
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
    return "\n".join(lines)
