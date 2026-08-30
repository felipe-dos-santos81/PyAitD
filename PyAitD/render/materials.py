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
PARAMETER_COUNT = 12  # 10 Material fields + two padding floats: three RGBA texels per index
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
    bump: float = 0.0    # 0..1: how much the detail height field perturbs the normal
    sss: float = 0.0     # 0..1: warm terminator, the cheap stand-in for subsurface
    emissive: float = 0.0  # 0..1: the surface renders its palette colour whatever the light does

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
        # The shader multiplies each of these by a preset strength and by a
        # noise or wrap term; outside 0..1 they stop being a fraction of
        # anything and the classic-identity argument (strength 0 collapses
        # the term) no longer bounds what a bad table can do.
        for name in ("bump", "sss", "emissive"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within 0..1, got {value!r}")

    def parameters(self):
        return np.array([self.roughness, self.specular, self.metallic, self.rim,
                         self.detail, self.detail_scale, float(self.detail_kind), 0.0,
                         self.bump, self.sss, self.emissive, 0.0], dtype=np.float32)


# Retuned by eye against the docs/graphics-proof fixtures at scale 4 (the
# shipped default). The reasoning, the measurements and what each number
# was traded against are in docs/materials-v2-proof.md; the three rules
# the table now obeys are:
#
# - `specular` is a fraction of the key reflected, not a peak brightness.
#   Every value here was divided by its own (gloss + 8) / 8pi, the lobe
#   normalisation task 3 added under a column that had been chosen by eye
#   against the unnormalised lobe. That factor spans 0.48 (cloth) to 41
#   (glass), so the old column was not one mis-scaling but eight.
# - `detail_scale` is what decides whether relief exists at all. One
#   sampled cell -- detail_scale over the kind's stretch, 4x for streak
#   and 6x for brushed -- has to stay above about four pixels or the
#   fade zeroes the perturbation and no `bump` can revive it. At scale 4 a
#   hero-sized body is ~4.9 FITD units per pixel, so the floor is
#   4 * 4.9 * stretch -- about 20, 78 and 118. cloth (12 -> 48),
#   hair (8 -> 80) and metal (25 -> 120) were all under it.
# - relief and the grain colour multiply share one noise sample, so
#   `detail` moves both: `bump` is the relief's own share and
#   PRESETS["enhanced"].detail is the colour's.
CLASS_PRESETS = {
    "matte":    Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, DETAIL_NONE),
    "skin":     Material(0.7, 0.16, 0.0, 0.25, 0.15, 40.0, DETAIL_GRAIN, bump=0.3, sss=1.0),
    "cloth":    Material(0.9, 0.10, 0.0, 0.35, 0.14, 48.0, DETAIL_WEAVE, bump=0.8),
    "leather":  Material(0.5, 0.12, 0.0, 0.3, 0.2, 30.0, DETAIL_GRAIN, bump=0.7),
    "hair":     Material(0.6, 0.19, 0.0, 0.4, 0.3, 80.0, DETAIL_STREAK, bump=0.3),
    "wood":     Material(0.6, 0.13, 0.0, 0.1, 0.35, 60.0, DETAIL_STREAK, bump=0.6),
    "stone":    Material(0.85, 0.09, 0.0, 0.05, 0.3, 50.0, DETAIL_GRAIN, bump=0.9),
    # bump 0.08, not the plan's 0.5, and the ceiling is measured rather
    # than chosen: brushed relief and a tight highlight are in direct
    # conflict. On `test_metal_is_brighter_than_matte_under_enhanced`'s
    # centre pixel the margin over matte falls 62 -> 52 -> 40 -> 30 -> 2 as
    # bump goes 0.0 -> 0.05 -> 0.08 -> 0.10 -> 0.20, and the test's bound is
    # 30. The highlight is scattered, not spent -- the region's peak stays
    # at 31 throughout -- but past 0.08 it stops landing anywhere
    # predictable. Roughness went 0.25 -> 0.4 to widen the lobe from 3.5 to
    # 6 degrees, which is the cheap stand-in for the anisotropy the spec
    # dropped.
    "metal":    Material(0.4, 0.15, 0.8, 0.2, 0.2, 120.0, DETAIL_BRUSHED, bump=0.08),
    "glass":    Material(0.1, 0.022, 0.0, 0.6, 0.0, 1.0, DETAIL_NONE),
    # Not a label only: emissive renders its palette colour whatever the
    # light does, which is what ramp 14's flames need.
    "emissive": Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, DETAIL_NONE, emissive=1.0),
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
        """(256, 12) float32: what the GL backend uploads as a 256x3 RGBA texture."""
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
    bump: float = 0.0
    sss: float = 0.0
    emissive: float = 0.0


# `detail` is the grain colour multiply's global share and nothing else --
# the relief has its own `bump`. It is 0.5 rather than 1.0 because the two
# now read the same noise sample: every bump's lit face was also its bright
# face, which doubled the apparent contrast and made a fine weave read as a
# hatch pattern. The colour term is also the one with no distance fade, so
# it is what aliases as a body recedes.
PRESETS = {
    "classic": RealismPreset(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    "enhanced": RealismPreset(spec=1.0, rim=0.6, ao=0.7, contact=1.0, detail=0.5,
                              hemisphere=1.0, bump=1.0, sss=1.0, emissive=1.0),
}
