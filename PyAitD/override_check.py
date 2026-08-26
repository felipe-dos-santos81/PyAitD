# SPDX-License-Identifier: GPL-2.0-only
"""Check an override directory the way the game will load it.

Pure: loads through AssetResolver so whatever it accepts, the game
accepts, and vice versa. PNG decoding is asset_resolver.load_png_rgb.
"""
from dataclasses import dataclass
from pathlib import Path

from PyAitD.asset_resolver import AssetResolver, load_png_rgb, override_background_path
from PyAitD.background_export import sha256_rgb

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


def summarize(findings, cov):
    lines = []
    for f in findings:
        if f.kind != "missing":
            lines.append(f"{f.kind:<7} floor {f.floor:02d} camera {f.camera:03d}  {f.path}: {f.detail}")
    if cov is None:
        lines.append("coverage: no manifest")
        return "\n".join(lines)
    aspect_by_floor = {}
    for f in findings:
        if f.kind == "aspect":
            aspect_by_floor[f.floor] = aspect_by_floor.get(f.floor, 0) + 1
    total = {k: 0 for k in _ORDER}
    for number in sorted(cov):
        row = dict(cov[number], aspect=aspect_by_floor.get(number, 0))
        for k in _ORDER:
            total[k] += row[k]
        lines.append(f"floor {number:02d}: " + " / ".join(f"{k} {row[k]}" for k in _ORDER))
    lines.append("total: " + " / ".join(f"{k} {total[k]}" for k in _ORDER))
    return "\n".join(lines)
