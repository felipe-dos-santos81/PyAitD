# SPDX-License-Identifier: GPL-2.0-only
"""Offline gate for regenerated plates: does a candidate keep the original's
structure? Pure numpy; no I/O, no network. Scores are compared at 320x200:
the candidate (1280x800) is box-downsampled 4x, both go to luminance, Sobel
edges are thresholded at EDGE_FRACTION of each image's own 95th percentile
magnitude (floored at EDGE_MIN), and the original's edges are checked for a candidate edge within
2 px -- globally and inside every mask / collision region. Guide colours
along the layout's lines are counted as a leak. See
docs/superpowers/specs/2026-08-27-background-layout-fidelity-design.md."""
import dataclasses

import numpy as np

from PyAitD.render.background_export import draw_polyline, layout_segments

W, H = 320, 200
THRESHOLDS = {"ncc": 0.50, "edge_recall": 0.60, "region_recall": 0.50,
              "leak": 0.02, "leak_frame": 0.005, "plain": 0.02}
MIN_REGION_EDGES = 20        # fewer original edge pixels: the region says nothing
MIN_REGION_AREA = 0.005      # of the frame; smaller regions are dropped
EDGE_FRACTION = 0.25         # of the 95th-percentile Sobel magnitude ...
EDGE_MIN = 40.0              # ... with this floor (Sobel of a ~10-level luminance step): a flat or
                             # gently graded image must not turn its every pixel into an "edge"
EDGE_TOLERANCE = 2           # px: dilation of the candidate's edges
BLUR_SIGMA, BLUR_RADIUS = 3.0, 9
SCORED_KINDS = ("mask", "collision")   # walkable is prompt-only; blit is checked for plainness


@dataclasses.dataclass(frozen=True)
class Region:
    kind: str          # mask | collision | walkable | blit
    polygon: tuple     # ((x, y), ...) in 320x200 px
    bbox_pct: tuple    # (x0, y0, x1, y1), whole percent of frame


@dataclasses.dataclass
class GateResult:
    passed: bool
    scores: dict
    failures: list
    leaked: bool = False


def fmt_bbox(bbox):
    x0, y0, x1, y1 = bbox
    return f"x {x0}–{x1} y {y0}–{y1}"


def _hull(points):
    """Andrew's monotone chain; the convex hull as a counter-clockwise list."""
    pts = sorted(set((float(x), float(y)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _region(kind, polygon):
    pts = tuple((float(x), float(y)) for x, y in polygon)
    if len(pts) < 3:
        return None
    xs = [min(max(x, 0.0), float(W)) for x, _ in pts]
    ys = [min(max(y, 0.0), float(H)) for _, y in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if (x1 - x0) * (y1 - y0) < MIN_REGION_AREA * W * H:
        return None
    bbox = (int(round(x0 * 100 / W)), int(round(y0 * 100 / H)),
            int(round(x1 * 100 / W)), int(round(y1 * 100 / H)))
    return Region(kind, pts, bbox)


def layout_regions(layout):
    """Prompt/gate regions of a layout sidecar: masks and walkable polygons
    as they are (None vertices dropped), each collision box as the convex
    hull of its live corners, blit rects as rectangles. Regions under
    MIN_REGION_AREA of the frame are dropped."""
    if not layout:
        return []
    out = []
    for poly in layout.get("masks", ()):
        out.append(_region("mask", [p for p in poly if p is not None]))
    for corners in layout.get("collision", ()):
        out.append(_region("collision", _hull([c for c in corners if c is not None])))
    for poly in layout.get("walkable", ()):
        out.append(_region("walkable", [p for p in poly if p is not None]))
    for x, y, rw, rh in layout.get("blit", ()):
        out.append(_region("blit", [(x, y), (x + rw, y), (x + rw, y + rh), (x, y + rh)]))
    return [r for r in out if r is not None]


def polygon_mask(polygon, shape=(H, W)):
    """Even-odd scanline fill; a pixel is inside when its centre is."""
    h, w = shape
    mask = np.zeros((h, w), bool)
    pts = [(float(x), float(y)) for x, y in polygon]
    n = len(pts)
    if n < 3:
        return mask
    for row in range(h):
        y = row + 0.5
        xs = []
        for k in range(n):
            (x0, y0), (x1, y1) = pts[k], pts[(k + 1) % n]
            if (y0 <= y) != (y1 <= y):
                xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
        xs.sort()
        for a, b in zip(xs[0::2], xs[1::2]):
            lo, hi = max(int(np.ceil(a - 0.5)), 0), min(int(np.floor(b - 0.5)) + 1, w)
            if hi > lo:
                mask[row, lo:hi] = True
    return mask


def guide_lines(layout):
    """Boolean 320x200 map of every line a guide would draw for `layout`."""
    img = np.zeros((H, W, 3), np.uint8)
    for a, b in layout_segments(layout):
        draw_polyline(img, [a, b], (255, 255, 255))
    return img[..., 0] > 0


def luminance(rgb):
    rgb = np.asarray(rgb, dtype=np.float32)
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def downsample4(candidate):
    c = np.asarray(candidate, dtype=np.float32)
    h, w = c.shape[:2]
    return c.reshape(h // 4, 4, w // 4, 4, 3).mean(axis=(1, 3))


def sobel_magnitude(lum):
    p = np.pad(lum, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return np.hypot(gx, gy)


def edge_map(lum):
    mag = sobel_magnitude(lum)
    return mag >= max(EDGE_MIN, EDGE_FRACTION * float(np.percentile(mag, 95)))


def dilate(mask, r):
    if r <= 0:
        return mask.copy()
    h, w = mask.shape
    p = np.pad(mask, r)
    out = np.zeros_like(mask)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= p[r + dy:r + dy + h, r + dx:r + dx + w]
    return out


def gaussian_blur(img, sigma=BLUR_SIGMA, radius=BLUR_RADIUS):
    k = np.exp(-0.5 * (np.arange(-radius, radius + 1, dtype=np.float32) / sigma) ** 2)
    k /= k.sum()
    h, w = img.shape
    p = np.pad(img, ((radius, radius), (radius, radius)), mode="edge")
    rows = sum(k[i] * p[:, i:i + w] for i in range(2 * radius + 1))
    return sum(k[i] * rows[i:i + h, :] for i in range(2 * radius + 1))


def ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 0 else 0.0


def _recall(orig_edges, cand_dilated, where=None):
    sel = orig_edges if where is None else (orig_edges & where)
    n = int(sel.sum())
    if n == 0:
        return None, 0
    return float((sel & cand_dilated).sum() / n), n


def guide_band(rgb):
    """Pixels whose colour sits in a guide band: red, blue (COLOR_COLLISION
    is (0, 128, 255)) or green."""
    r, g, b = rgb[..., 0].astype(int), rgb[..., 1].astype(int), rgb[..., 2].astype(int)
    red = (r > 180) & (g < 80) & (b < 80)
    blue = (b > 200) & (g >= 80) & (g <= 180) & (r < 80)
    green = (g > 150) & (r < 80) & (b < 80)
    return red | blue | green


def gate(candidate, original, layout, scale=1.0):
    """Score `candidate` against `original`; see the module docstring.
    `scale` multiplies every threshold; 0 passes everything but still
    reports scores. Failures are worded as corrections for the next
    attempt."""
    candidate = np.asarray(candidate)
    original = np.asarray(original)
    if candidate.shape != (4 * H, 4 * W, 3):
        raise ValueError(f"candidate must be {4 * W}x{4 * H} RGB, got {candidate.shape}")
    if original.shape != (H, W, 3):
        raise ValueError(f"original must be {W}x{H} RGB, got {original.shape}")
    t = {k: v * scale for k, v in THRESHOLDS.items()}
    small = downsample4(candidate)
    lum_c, lum_o = luminance(small), luminance(original)
    edges_o, edges_c = edge_map(lum_o), edge_map(lum_c)
    edges_c2 = dilate(edges_c, EDGE_TOLERANCE)
    scores, failures, leaked = {}, [], False

    scores["ncc"] = ncc(gaussian_blur(lum_c), gaussian_blur(lum_o))
    if scores["ncc"] < t["ncc"]:
        failures.append(f"framing differs (ncc {scores['ncc']:.2f})")
    recall, _ = _recall(edges_o, edges_c2)
    scores["edge_recall"] = 1.0 if recall is None else recall
    if scores["edge_recall"] < t["edge_recall"]:
        failures.append(f"structure differs (edge recall {scores['edge_recall']:.2f})")

    if layout:
        regions = []
        for region in layout_regions(layout):
            where = polygon_mask(region.polygon)
            entry = {"kind": region.kind, "bbox_pct": list(region.bbox_pct)}
            if region.kind in SCORED_KINDS:
                r, n = _recall(edges_o, edges_c2, where)
                entry["recall"] = None if n < MIN_REGION_EDGES else r
                if entry["recall"] is not None and entry["recall"] < t["region_recall"]:
                    failures.append(f"structure missing inside {fmt_bbox(region.bbox_pct)} "
                                    f"(edge recall {entry['recall']:.2f})")
            elif region.kind == "blit":
                entry["plain"] = float((edges_c & where).sum() / max(int(where.sum()), 1))
                if entry["plain"] > t["plain"]:
                    failures.append(f"text or clutter inside plain region {fmt_bbox(region.bbox_pct)} "
                                    f"(edge density {entry['plain']:.3f})")
            else:
                continue
            regions.append(entry)
        scores["regions"] = regions

        band_full = guide_band(candidate)
        band = band_full.reshape(H, 4, W, 4).any(axis=(1, 3))
        lines = dilate(guide_lines(layout), 1)
        n_lines = int(lines.sum())
        scores["leak"] = float((band & lines).sum() / n_lines) if n_lines else 0.0
        scores["leak_frame"] = float(band_full.mean())
        if scores["leak"] > t["leak"]:
            leaked = True
            failures.append(f"guide colour on {scores['leak'] * 100:.0f} % of guide-line pixels: "
                            "do not draw the red, blue or green lines")
        if scores["leak_frame"] > t["leak_frame"]:
            leaked = True
            failures.append(f"guide colours on {scores['leak_frame'] * 100:.1f} % of the frame: "
                            "do not draw the red, blue or green lines")

    if scale == 0:
        failures, leaked = [], False
    return GateResult(not failures, scores, failures, leaked)
