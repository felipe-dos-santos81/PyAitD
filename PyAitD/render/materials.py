# SPDX-License-Identifier: GPL-2.0-only
"""Per-palette-index material classes and the realism presets.

The game files say nothing about what a polygon is made of; a body is
vertices and palette-indexed primitives. This module classifies the 256
palette indices into material classes (a committed JSON table, bootstrapped
by tools/bootstrap_materials.py and hand-corrected), turns a class into the
shader's numeric parameters, and holds the two global presets that scale
every new shading term -- `classic` is all zeros so it renders exactly as
before. Pure: no pygame, no GL, no engine imports."""
from dataclasses import dataclass
import functools
import json
from pathlib import Path

import numpy as np

MATERIAL_CLASSES = ("matte", "skin", "cloth", "leather", "hair",
                    "wood", "stone", "metal", "glass", "emissive")
REALISM_MODES = ("classic", "enhanced")
PALETTE_SIZE = 256
PARAMETER_COUNT = 8   # 7 Material fields + one padding float: two RGBA texels per index
DETAIL_NONE, DETAIL_GRAIN, DETAIL_WEAVE, DETAIL_STREAK, DETAIL_BRUSHED = range(5)
DEFAULT_TABLE_PATH = Path(__file__).with_name("materials.json")


@dataclass(frozen=True)
class Material:
    roughness: float     # 0..1: specular exponent and spread
    specular: float      # 0..1: highlight strength
    metallic: float      # 0..1: highlight takes the surface colour, not the key's
    rim: float           # 0..1: fresnel rim strength
    detail: float        # 0..1: procedural grain amount
    detail_scale: float  # FITD units per noise cell; always > 0, the shader divides by it
    detail_kind: int     # DETAIL_NONE .. DETAIL_BRUSHED

    def __post_init__(self):
        # The shader divides v_rest by this, so a zero would make the noise
        # NaN -- and under realism=classic `0.0 * NaN` is NaN too, which is
        # the one way a data change alone could break the byte-for-byte
        # classic identity. Rejected here, in the pure module that owns
        # every other material invariant, rather than clamped in the
        # shader: a clamp would quietly render a nonsense material instead
        # of naming the bad field.
        if not self.detail_scale > 0:
            raise ValueError(f"detail_scale must be > 0, got {self.detail_scale!r}")

    def parameters(self):
        return np.array([self.roughness, self.specular, self.metallic, self.rim,
                         self.detail, self.detail_scale, float(self.detail_kind), 0.0], dtype=np.float32)


# Tuned by eye against the docs/graphics-proof fixtures at scale 4: cloth's
# weave stays faint enough to read as fabric rather than as a pattern, and
# metal's highlight keeps enough of the key's own colour to show on a
# saturated body instead of vanishing into it.
CLASS_PRESETS = {
    "matte":    Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, DETAIL_NONE),
    "skin":     Material(0.7, 0.15, 0.0, 0.25, 0.15, 40.0, DETAIL_GRAIN),
    "cloth":    Material(0.9, 0.05, 0.0, 0.35, 0.08, 12.0, DETAIL_WEAVE),
    "leather":  Material(0.5, 0.35, 0.0, 0.3, 0.2, 30.0, DETAIL_GRAIN),
    "hair":     Material(0.6, 0.3, 0.0, 0.4, 0.3, 8.0, DETAIL_STREAK),
    "wood":     Material(0.6, 0.2, 0.0, 0.1, 0.35, 60.0, DETAIL_STREAK),
    "stone":    Material(0.85, 0.05, 0.0, 0.05, 0.3, 50.0, DETAIL_GRAIN),
    "metal":    Material(0.25, 0.8, 0.8, 0.2, 0.15, 25.0, DETAIL_BRUSHED),
    "glass":    Material(0.1, 0.9, 0.0, 0.6, 0.0, 1.0, DETAIL_NONE),
    # A label only: no emissive term exists in the shader, so it shades as matte.
    "emissive": Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, DETAIL_NONE),
}


def _check_class(name, where):
    if name not in MATERIAL_CLASSES:
        raise ValueError(f"{where}: unknown material class {name!r}")


def _check_index(index, where):
    if not 0 <= index < PALETTE_SIZE:
        raise ValueError(f"{where}: outside 0..{PALETTE_SIZE - 1}")


@dataclass(frozen=True)
class MaterialTable:
    classes: tuple   # PALETTE_SIZE class names, index = palette index

    def __post_init__(self):
        if len(self.classes) != PALETTE_SIZE:
            raise ValueError(f"material table must have {PALETTE_SIZE} entries, got {len(self.classes)}")
        for index, name in enumerate(self.classes):
            _check_class(name, f"index {index}")

    def parameters(self):
        """(256, 8) float32: what the GL backend uploads as a 256x2 RGBA texture."""
        out = np.zeros((PALETTE_SIZE, PARAMETER_COUNT), dtype=np.float32)
        for index, name in enumerate(self.classes):
            out[index] = CLASS_PRESETS[name].parameters()
        return out

    def remapped(self, overrides):
        """A new table with `overrides` ({index: class}) applied on top."""
        classes = list(self.classes)
        for index, name in overrides.items():
            _check_index(index, f"index {index}")
            _check_class(name, f"index {index}")
            classes[index] = name
        return MaterialTable(tuple(classes))


def parse_assignments(data):
    """The explicit {index: class} assignments a table file makes: `ramps`
    in order, then `indices`. Unmentioned indices are absent, which is what
    lets a per-body override leave the default alone everywhere else."""
    if not isinstance(data, dict):
        raise ValueError("material table must be an object")
    out = {}
    for ramp in data.get("ramps", ()):
        lo, hi, name = ramp.get("lo"), ramp.get("hi"), ramp.get("class")
        where = f"ramp {lo}..{hi}"
        if type(lo) is not int or type(hi) is not int:
            raise ValueError(f"{where}: lo and hi must be integers")
        if lo > hi:
            raise ValueError(f"{where}: lo > hi")
        _check_index(lo, where)
        _check_index(hi, where)
        _check_class(name, where)
        for index in range(lo, hi + 1):
            out[index] = name
    for key, name in data.get("indices", {}).items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            raise ValueError(f"index {key!r}: not an integer") from None
        _check_index(index, f"index {index}")
        _check_class(name, f"index {index}")
        out[index] = name
    return out


def parse_table(data):
    return MaterialTable(("matte",) * PALETTE_SIZE).remapped(parse_assignments(data))


def load_table(path):
    return parse_table(json.loads(Path(path).read_text(encoding="utf-8")))


@functools.lru_cache(maxsize=1)
def default_table():
    """The committed PyAitD/render/materials.json. Cached: GLBackend skips
    the parameter upload when an actor hands it the same table object."""
    return load_table(DEFAULT_TABLE_PATH)


@dataclass(frozen=True)
class RealismPreset:
    spec: float
    rim: float
    ao: float
    contact: float
    detail: float
    hemisphere: float


PRESETS = {
    "classic": RealismPreset(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    "enhanced": RealismPreset(spec=1.0, rim=0.6, ao=0.7, contact=1.0, detail=1.0, hemisphere=1.0),
}
