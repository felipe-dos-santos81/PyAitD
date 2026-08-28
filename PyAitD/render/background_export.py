# SPDX-License-Identifier: GPL-2.0-only
"""Export the original camera backgrounds for external (AI) regeneration.

Pure numpy: no pygame, no moderngl. PNG encoding lives in
tools/export_backgrounds.py. See docs/ai-background-regeneration.md. Guide
overlay PNGs are drawn from `.json` layout sidecars (layout_geometry /
screen_layout via layout_segments), which are written alongside them.
"""
import hashlib

import numpy as np

from PyAitD.engine.formats import parse_cover_zones
from PyAitD.engine.navmesh import COVER_SCALE
from PyAitD.render.scene import CameraView
from PyAitD.engine.world import CameraState

W, H = 320, 200


def draw_polyline(img, points, rgb, closed=False):
    """Draw 1px Bresenham segments through `points` ((x, y) floats, rounded)
    into `img` (H, W, 3) in place, clipping every pixel to the image."""
    pts = [(int(round(x)), int(round(y))) for x, y in points]
    if not pts:
        return
    if closed and len(pts) > 1:
        pts = pts + [pts[0]]
    if len(pts) == 1:
        pts = pts + [pts[0]]
    h, w = img.shape[:2]
    color = np.array(rgb, dtype=np.uint8)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        x, y = x0, y0
        while True:
            if 0 <= x < w and 0 <= y < h:
                img[y, x] = color
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy


def nearest_upscale(img, scale):
    """Integer nearest-neighbour upscale; always returns a fresh C-contiguous array."""
    out = np.repeat(np.repeat(img, scale, axis=0), scale, axis=1)
    return np.ascontiguousarray(out)


def sha256_rgb(pixels):
    """Hex digest over the raw (H, W, 3) uint8 bytes in row-major order --
    independent of the PNG encoder that later wrote or read them."""
    return hashlib.sha256(np.ascontiguousarray(pixels, dtype=np.uint8).tobytes()).hexdigest()


MANIFEST_SCHEMA = 3
SUPPORTED_SCHEMAS = (1, 2, 3)   # 1: cameras only; 2: cameras + screens; 3: cameras + screens + alt_cameras
LEGEND = {"red": "masks", "blue": "collision", "green": "walkable"}


def background_rel_path(floor_number, cam_idx):
    # Must stay identical to asset_resolver.override_background_path's tail:
    # the export directory is used directly as --overrides DIR.
    return f"backgrounds/floor{floor_number:02d}/camera{cam_idx:03d}.png"


def guide_rel_path(floor_number, cam_idx):
    return f"guides/floor{floor_number:02d}/camera{cam_idx:03d}.png"


def layout_rel_path(floor_number, cam_idx):
    return f"guides/floor{floor_number:02d}/camera{cam_idx:03d}.json"


def alt_background_rel_path(floor_number, cam_idx):
    return f"alt_backgrounds/floor{floor_number:02d}/camera{cam_idx:03d}.png"


def manifest_record(floor, cam_idx, pixels):
    """One manifest entry. `pixels` is the exported (H, W, 3) array, or None
    when Floor.camera_image raised KeyError (image missing from CAMERAnn.PAK)."""
    rec = {
        "floor": floor.number,
        "camera": cam_idx,
        "source": None,
        "guide": None,
        "layout": None,
        "size": None,
        "viewed_rooms": [],
        "masks": 0,
        "sha256": None,
    }
    # Populate camera metadata only if camera exists (valid index)
    if cam_idx < len(floor.cameras):
        cam = floor.cameras[cam_idx]
        rec["viewed_rooms"] = [vr.viewed_room_idx for vr in cam.viewed_rooms]
        rec["masks"] = len(floor.mask_draws(cam_idx))
    # Populate image-derived fields only if pixels available
    if pixels is not None:
        rec["source"] = background_rel_path(floor.number, cam_idx)
        rec["guide"] = guide_rel_path(floor.number, cam_idx)
        rec["layout"] = layout_rel_path(floor.number, cam_idx)
        rec["size"] = [int(pixels.shape[1]), int(pixels.shape[0])]
        rec["sha256"] = sha256_rgb(pixels)
    return rec


def alt_manifest_record(floor, cam_idx, pixels, itd_entry):
    rec = manifest_record(floor, cam_idx, pixels)
    # reuse base fields (source/guide/layout/size/sha256/viewed_rooms/masks)
    # but source points to alt tree
    if pixels is not None:
        rec["source"] = alt_background_rel_path(floor.number, cam_idx)
        # guide/layout stay shared (point at base guides/)
    rec["itd_entry"] = int(itd_entry)
    rec["variant"] = "killed_sorcerer"
    return rec


def export_manifest(records, data_dir, guide_scale, screens=(), alt_cameras=()):
    return {
        "schema": MANIFEST_SCHEMA,
        "data_dir": str(data_dir),
        "guide_scale": int(guide_scale),
        "legend": dict(LEGEND),
        "cameras": list(records),
        "alt_cameras": list(alt_cameras),
        "screens": list(screens),
    }


GUIDE_FOOTER = 12
COLOR_MASK = (255, 0, 0)
COLOR_COLLISION = (0, 128, 255)
COLOR_WALKABLE = (0, 200, 0)
_SWATCH_W, _SWATCH_STRIDE = 40, 48
_CULLED = -9999.0


def cover_zones_for(floor, cam_idx, viewed_idx):
    """Cover polygons ((x, z) in cover units) of `viewed_idx` as seen from
    `cam_idx`. Real Floors go through parse_cover_zones exactly as
    navmesh.cover_polys does; a floor object exposing `cover_zones` (test
    stubs) is asked directly."""
    if hasattr(floor, "cover_zones"):
        return floor.cover_zones(cam_idx, viewed_idx)
    return parse_cover_zones(floor.camera_raw, floor.camera_data_offsets[cam_idx], viewed_idx)


def _draw_legend_footer(img, h):
    """Draw the legend swatch footer (red/blue/green for masks/collision/walkable)
    on the bottom of `img` starting at row `h`."""
    for k, color in enumerate((COLOR_MASK, COLOR_COLLISION, COLOR_WALKABLE)):
        x0 = k * _SWATCH_STRIDE
        img[h:, x0:x0 + _SWATCH_W] = color


def _projected_or_none(view, world_pts):
    """Project `world_pts`; a depth-culled vertex becomes None, the rest
    [x, y] floats in 320x200 logical pixels (unrounded, so drawing from the
    layout is pixel-identical to drawing from the projection)."""
    proj = view.project(world_pts)
    return [None if p[2] <= _CULLED else [float(p[0]), float(p[1])] for p in proj]


_BOX_EDGES = (
    (0, 1), (1, 2), (2, 3), (3, 0),   # bottom rectangle (y2, the floor edge)
    (4, 5), (5, 6), (6, 7), (7, 4),   # top rectangle (y1)
    (0, 4), (1, 5), (2, 6), (3, 7),   # verticals
)


def _box_corners(z):
    return [
        (z.x1, z.y2, z.z1), (z.x2, z.y2, z.z1), (z.x2, z.y2, z.z2), (z.x1, z.y2, z.z2),
        (z.x1, z.y1, z.z1), (z.x2, z.y1, z.z1), (z.x2, z.y1, z.z2), (z.x1, z.y1, z.z2),
    ]


LAYOUT_SCHEMA = 1


def layout_geometry(floor, cam_idx):
    """The structures the guide draws, as a JSON-able dict in 320x200 pixel
    space: mask polygons (closed), each hard-collision box's 8 projected
    corners in _box_corners order, and the projected cover polygons
    (closed). A depth-culled vertex is None. Room-space coordinates are
    passed to CameraView as-is: the room's world offset is already folded
    into CameraState.from_camera, exactly as in scene.build_frame."""
    masks = []
    for mask in floor.mask_draws(cam_idx):
        for poly in mask.polygons:
            pts = np.asarray(poly, dtype=float).reshape(-1, 2)
            masks.append([[float(x), float(y)] for x, y in pts])
    collision, walkable = [], []
    camera = floor.cameras[cam_idx]
    for viewed_idx, vr in enumerate(camera.viewed_rooms):
        room = floor.rooms[vr.viewed_room_idx]
        view = CameraView(CameraState.from_camera(camera, room.world_x, room.world_y, room.world_z).angles())
        for box in room.hard_cols:
            collision.append(_projected_or_none(view, _box_corners(box)))
        for poly in cover_zones_for(floor, cam_idx, viewed_idx):
            pts = [(x * COVER_SCALE, 0, z * COVER_SCALE) for x, z in poly]
            if len(pts) < 2:
                continue
            walkable.append(_projected_or_none(view, pts))
    return {"schema": LAYOUT_SCHEMA, "size": [W, H],
            "masks": masks, "collision": collision, "walkable": walkable}


def _ring_edges(n):
    return [(k, (k + 1) % n) for k in range(n)]


def _edges_of(pts, edges):
    out = []
    for i, j in edges:
        a, b = pts[i], pts[j]
        if a is None or b is None:
            continue
        out.append(((a[0], a[1]), (b[0], b[1])))
    return out


def layout_segments(layout):
    """Every segment a guide draws for `layout`, in 320x200 pixel space:
    masks and walkable polygons closed, collision boxes along _BOX_EDGES,
    blit rects around their inclusive corners. Edges touching a None
    vertex are skipped. Shared by guide_overlay/screen_guide (scaled) and
    tools/plate_check.guide_lines (unscaled)."""
    segs = []
    for poly in layout.get("masks", ()):
        segs.extend(_edges_of(poly, _ring_edges(len(poly))))
    for corners in layout.get("collision", ()):
        segs.extend(_edges_of(corners, _BOX_EDGES))
    for poly in layout.get("walkable", ()):
        segs.extend(_edges_of(poly, _ring_edges(len(poly))))
    for x, y, rw, rh in layout.get("blit", ()):
        rect = [(x, y), (x + rw - 1, y), (x + rw - 1, y + rh - 1), (x, y + rh - 1)]
        segs.extend(_edges_of(rect, _ring_edges(4)))
    return segs


def _draw_segments(img, segs, rgb, scale):
    for a, b in segs:
        draw_polyline(img, [(a[0] * scale, a[1] * scale), (b[0] * scale, b[1] * scale)], rgb)


def guide_overlay(floor, cam_idx, scale, layout=None):
    """The original background upscaled x`scale` (nearest neighbour) with
    mask polygons (red), hard-collision boxes (blue) and cover polygons
    (green) drawn over it, plus a GUIDE_FOOTER-px legend strip. `layout`
    is layout_geometry(floor, cam_idx), computed here when not given."""
    if layout is None:
        layout = layout_geometry(floor, cam_idx)
    base = nearest_upscale(floor.camera_image(cam_idx), scale)
    h, w = base.shape[:2]
    img = np.zeros((h + GUIDE_FOOTER, w, 3), np.uint8)
    img[:h] = base
    _draw_segments(img, layout_segments({"masks": layout["masks"]}), COLOR_MASK, scale)
    _draw_segments(img, layout_segments({"collision": layout["collision"]}), COLOR_COLLISION, scale)
    _draw_segments(img, layout_segments({"walkable": layout["walkable"]}), COLOR_WALKABLE, scale)
    _draw_legend_footer(img, h)
    return img


# ---- full-screen ITD_RESS resources -------------------------------------
# AITD1.h entry numbers. Entry 11 (GRENOUILLE, copy protection) is never drawn.
SCREEN_ENTRIES = (6, 7, 8, 10, 12, 13, 14)
SCREEN_NAMES = {6: "LETTRE", 7: "LIVRE", 8: "CARNET", 10: "PERSO_CHOICE",
                12: "DEAD_END", 13: "TITRE", 14: "FOND_INTRO"}
# (x, y, w, h) in 320x200 space: the regions app/ui.py draws over. Only the
# rects ui.py actually imports (PORTRAIT_RECTS, the READING_*_RECT trio) are
# pinned against drift this way; STORY_COLUMNS, CREDITS_BOX and READING_BOX
# are reference-only numbers ui.py does not consume, hand-copied from
# AITD1.cpp / ui.render_reading and unchecked against it.
PORTRAIT_RECTS = ((10, 10, 140, 181), (170, 10, 140, 181))       # ui.CharacterLayout.PORTRAITS
STORY_COLUMNS = ((5, 5, 150, 189), (165, 5, 150, 189))           # AITD1.cpp Lire(...,5,5,154,194) / (165,5,314,194)
CREDITS_BOX = (48, 2, 212, 195)                                  # AITD1.cpp:159 Lire(TEXTE_CREDITS, 48,2,260,197)
READING_BOX = (60, 20, 200, 160)                                 # ui.render_reading text area
# ui.ModalLayout.READING_PREV/CLOSE/NEXT: the three page buttons render_reading
# draws on every letter/book/notebook screen (entries 6, 7, 8).
READING_PREV_RECT = (12, 164, 96, 28)
READING_CLOSE_RECT = (114, 164, 96, 28)
READING_NEXT_RECT = (216, 164, 96, 28)
FULL_FRAME = (0, 0, 320, 200)
SCREEN_GUIDES = {
    6: (READING_BOX, READING_PREV_RECT, READING_CLOSE_RECT, READING_NEXT_RECT),
    7: (READING_BOX, CREDITS_BOX, READING_PREV_RECT, READING_CLOSE_RECT, READING_NEXT_RECT),
    8: (READING_BOX, READING_PREV_RECT, READING_CLOSE_RECT, READING_NEXT_RECT),
    10: PORTRAIT_RECTS,
    12: (FULL_FRAME,),
    13: (FULL_FRAME,),
    14: STORY_COLUMNS,
}
COLOR_BLIT = COLOR_COLLISION   # blue: "the engine draws over this"


def screen_rel_path(entry):
    # Must stay identical to asset_resolver.override_screen_path's tail.
    return f"screens/ress{entry:02d}.png"


def screen_guide_rel_path(entry):
    return f"guides/screens/ress{entry:02d}.png"


def screen_layout_rel_path(entry):
    return f"guides/screens/ress{entry:02d}.json"


def screen_layout(entry):
    """The blit rects the engine draws over `entry`, as a JSON-able layout."""
    return {"schema": LAYOUT_SCHEMA, "size": [W, H], "blit": [list(r) for r in SCREEN_GUIDES[entry]]}


def screen_record(entry, pixels):
    return {
        "entry": int(entry),
        "name": SCREEN_NAMES[entry],
        "source": screen_rel_path(entry),
        "guide": screen_guide_rel_path(entry),
        "layout": screen_layout_rel_path(entry),
        "size": [int(pixels.shape[1]), int(pixels.shape[0])],
        "sha256": sha256_rgb(pixels),
        "blits": [list(r) for r in SCREEN_GUIDES[entry]],
    }


def screen_guide(pixels, entry, scale):
    """The screen upscaled x`scale` with every blit rect outlined in blue
    and the same legend footer as guide_overlay."""
    base = nearest_upscale(pixels, scale)
    h, w = base.shape[:2]
    img = np.zeros((h + GUIDE_FOOTER, w, 3), np.uint8)
    img[:h] = base
    _draw_segments(img, layout_segments(screen_layout(entry)), COLOR_BLIT, scale)
    _draw_legend_footer(img, h)
    return img
