# SPDX-License-Identifier: GPL-2.0-only
"""Unwrap actor bodies into a texture atlas for an external painter.

A stage of `make export-textures`, tools-side only: it imports xatlas and
libigl from the `tools` extra, which PyAitD/ may never import
(tests/test_layering.py pins that). It writes, per body:

- `bodies/body<NNN>.uv.json` -- the sidecar the runtime reads: atlas size
  and (M, 3, 2) per-corner UVs in the *runtime's own* triangulation order,
  plus a hash of that triangulation so a stale sidecar is detectable.
  xatlas splits vertices at chart seams (body 1: 67 -> 198), which is why
  the UVs are per corner and why the runtime never sees the vertex remap.
- `bodies/body<NNN>-guide.png` -- what a painter works from: charts filled
  with the body's own palette colours, darkened by an ambient-occlusion
  layer, with a dark wireframe overlay tracing every triangle edge, at the
  atlas's own size.

The painter produces `bodies/body<NNN>.png` (albedo, same layout).
`make check-textures` validates the result."""
import argparse
import dataclasses
import json
import pathlib
import sys

import numpy as np

from PyAitD.engine.data.assets import Assets
from PyAitD.games import load_profile
from PyAitD.render.geometry import pose_geometry
from PyAitD.render.texture_export import (
    body_guide_rel_path, body_texture_rel_path, body_uv_rel_path, draw_polyline, sha256_tris,
)
# Run as a script (`python tools/export_actor_uvs.py`), sys.path[0] is
# tools/, not the repo root, so the sibling tools.export_textures module
# export_bodies() imports lazily is only reachable through the package when
# the root is added explicitly (same idiom as tools/check_textures.py).
if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

SIDECAR_SCHEMA = 1
# Requested atlas resolution. xatlas treats this as a hint and grows the
# atlas when the charts do not fit (512 produced 605 for body 12), so the
# real size is always read back from the atlas, never assumed.
ATLAS_RESOLUTION = 512
# Gutter in texels between charts, so a mip level cannot bleed one chart's
# paint into its neighbour.
ATLAS_PADDING = 4
AO_SAMPLES = 64
# Dark, desaturated -- reads against both light and dark palette colours,
# so a chart boundary never disappears into its own fill.
WIREFRAME_RGB = (32, 32, 32)


@dataclasses.dataclass(frozen=True)
class UvBake:
    uvs: np.ndarray      # (M, 3, 2) float32, per corner, runtime triangle order
    width: int
    height: int
    tris_sha256: str
    chart_count: int


def rest_geometry(body):
    """The assembled rest pose and its triangulation -- the exact arrays the
    runtime builds, so the UVs land in the runtime's own corner order."""
    return pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))


def unwrap_body(body):
    """xatlas unwrap of `body`'s rest pose, as per-corner UVs.

    xatlas returns (vmapping, indices, uvs) where the vertices have been
    split at chart seams; `vmapping[indices] == tris` exactly (verified on
    real bodies 1, 12 and 30), so `uvs[indices]` is the per-corner payload
    in the original triangle order."""
    import xatlas
    geo = rest_geometry(body)
    vertices = np.ascontiguousarray(geo.vertices, dtype=np.float32)
    tris = np.ascontiguousarray(geo.tris, dtype=np.uint32)
    atlas = xatlas.Atlas()
    atlas.add_mesh(vertices, tris)
    options = xatlas.PackOptions()
    options.resolution = ATLAS_RESOLUTION
    options.padding = ATLAS_PADDING
    atlas.generate(pack_options=options)
    vmapping, indices, uvs = atlas[0]
    if not np.array_equal(vmapping[indices], tris):
        # The per-corner sidecar is only meaningful if xatlas kept the
        # triangle order. It does; this guards against a future xatlas
        # changing that silently rather than letting it corrupt every paint.
        raise RuntimeError(
            "xatlas did not preserve triangle order; the per-corner UV "
            "sidecar cannot be built against this unwrap")
    corner_uvs = np.ascontiguousarray(uvs[indices], dtype=np.float32)
    return UvBake(
        uvs=corner_uvs,
        width=int(atlas.width),
        height=int(atlas.height),
        tris_sha256=sha256_tris(geo.tris),
        chart_count=int(atlas.chart_count),
    )


def sidecar_payload(bake):
    return {
        "schema": SIDECAR_SCHEMA,
        "size": [bake.width, bake.height],
        "chart_count": bake.chart_count,
        "tris_sha256": bake.tris_sha256,
        "uvs": bake.uvs.round(6).tolist(),
    }


HEROES = (0, 1)


def body_numbers(data_dir, profile, heroes=HEROES):
    """Every body number the hero archives actually expose, sorted.

    Bodies live in per-hero archives (`Assets(..., hero=h).num_bodies`),
    and real archives carry entries that are not bodies at all, so each is
    probed and the failures skipped -- the same loop
    `tools/bootstrap_materials.py:load_game` already uses.

    Note the same number can name a *different* body in each hero's
    archive, while the texture directory keys paints by number alone
    (`bodies/body<NNN>.png`). That ambiguity is inherited, not introduced:
    the existing per-body material override
    (`asset_resolver.texture_body_material_path`) keys the same way. The
    proof document records it as a known limitation."""
    seen = set()
    for hero in heroes:
        assets = Assets(data_dir, profile, hero=hero)
        for num in range(assets.num_bodies):
            try:
                assets.body(num)
            except (ValueError, KeyError, IndexError):
                continue   # an entry that is not a body
            seen.add(num)
    return sorted(seen)


def ambient_occlusion(body):
    """(N,) float32 per-vertex openness of the rest pose, 1 = open.

    `igl.embree` is a submodule that is not imported by `import igl`, so it
    is imported explicitly here."""
    import igl.embree
    geo = rest_geometry(body)
    v = np.ascontiguousarray(geo.vertices, dtype=np.float64)
    f = np.ascontiguousarray(geo.tris, dtype=np.int64)
    n = np.ascontiguousarray(geo.normals, dtype=np.float64)
    occlusion = igl.embree.ambient_occlusion(v, f, v, n, AO_SAMPLES)
    return (1.0 - np.asarray(occlusion, dtype=np.float32)).clip(0.0, 1.0)


def _barycentric_fill(size, corner_uvs, corner_values, ao_values):
    """Rasterise each triangle's chart into an (H, W, 3) uint8 image.

    Flat-fills each triangle's bounding box with its own palette colour
    scaled by the mean openness of its corners -- enough for a painter to
    read shape and cavity without pulling in a rasteriser dependency -- then
    draws every triangle's three edges over the fill in a dark wireframe, so
    chart boundaries (otherwise invisible: two charts can sit right next to
    each other in the same fill colour) stay legible."""
    width, height = size
    img = np.zeros((height, width, 3), dtype=np.uint8)
    xs = np.clip((corner_uvs[:, :, 0] * (width - 1)).round().astype(np.int32), 0, width - 1)
    ys = np.clip(((1.0 - corner_uvs[:, :, 1]) * (height - 1)).round().astype(np.int32), 0, height - 1)
    for tri in range(len(corner_uvs)):
        x0, x1 = int(xs[tri].min()), int(xs[tri].max())
        y0, y1 = int(ys[tri].min()), int(ys[tri].max())
        shade = float(ao_values[tri])
        img[y0:y1 + 1, x0:x1 + 1] = np.clip(
            corner_values[tri].astype(np.float32) * shade, 0, 255).astype(np.uint8)
    # A second pass, after every fill, so no triangle's wireframe edge is
    # ever painted over by a neighbour's bounding-box fill.
    for tri in range(len(corner_uvs)):
        points = list(zip(xs[tri].tolist(), ys[tri].tolist()))
        draw_polyline(img, points, WIREFRAME_RGB, closed=True)
    return img


def guide_image(body, bake, palette, ao):
    """The painter's guide: every triangle's chart filled with that
    triangle's own palette colour, darkened by its corners' mean
    occlusion."""
    geo = rest_geometry(body)
    tri_rgb = np.asarray(palette, dtype=np.uint8)[np.asarray(geo.tri_colors, dtype=np.int32)]
    tri_ao = np.asarray(ao, dtype=np.float32)[np.asarray(geo.tris, dtype=np.int32)].mean(axis=1)
    return _barycentric_fill((bake.width, bake.height), bake.uvs, tri_rgb, tri_ao)


def export_bodies(data_dir, profile, out_dir, *, save=None):
    """Bake every body the hero archives expose. Returns one manifest record
    per body, in body-number order."""
    from PyAitD.engine.data.floor import Floor
    from tools.export_textures import save_png
    save = save_png if save is None else save
    # Hero 0's archive is the one the guide's palette colours come from; a
    # number present only in hero 1's archive falls back to that archive.
    by_hero = {h: Assets(data_dir, profile, hero=h) for h in HEROES}
    palette = Floor(data_dir, 0, profile).palette
    out_dir = pathlib.Path(out_dir)
    records = []
    for num in body_numbers(data_dir, profile):
        body = None
        for hero in HEROES:
            try:
                body = by_hero[hero].body(num)
                break
            except (ValueError, KeyError, IndexError):
                continue
        if body is None:
            continue
        # A handful of real bodies (85, 142, 156, 158, 160 in aitd1) are
        # point/sprite entries with vertices but no triangle primitives --
        # a valid Body, but nothing for xatlas to unwrap or a painter to
        # paint, so they are skipped like any other entry with nothing to
        # bake.
        if len(rest_geometry(body).tris) == 0:
            continue
        bake = unwrap_body(body)
        uv_path = out_dir / body_uv_rel_path(num)
        uv_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = uv_path.with_suffix(uv_path.suffix + ".tmp")
        tmp.write_text(json.dumps(sidecar_payload(bake)), encoding="utf-8")
        tmp.replace(uv_path)
        ao = ambient_occlusion(body)
        save(out_dir / body_guide_rel_path(num), guide_image(body, bake, palette, ao))
        records.append({
            "body": num,
            "uv": body_uv_rel_path(num),
            "guide": body_guide_rel_path(num),
            "texture": body_texture_rel_path(num),
            "size": [bake.width, bake.height],
            "charts": bake.chart_count,
            "tris_sha256": bake.tris_sha256,
        })
    return records


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("data", type=pathlib.Path, help="game data directory (e.g. .../INDARK)")
    p.add_argument("--out", type=pathlib.Path, required=True, help="texture directory to write into")
    p.add_argument("--game", default="aitd1", help="game id (default aitd1)")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not args.data.is_dir():
        print(f"error: game data directory not found: {args.data}", file=sys.stderr)
        return 2
    records = export_bodies(args.data, load_profile(args.game), args.out)
    for rec in records:
        print(f"{rec['uv']}  {rec['size'][0]}x{rec['size'][1]}  {rec['charts']} charts")
    print(f"{len(records)} bodies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
