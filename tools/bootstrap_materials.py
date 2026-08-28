# SPDX-License-Identifier: GPL-2.0-only
"""Bootstrap PyAitD/render/materials.json: classify the 256 palette indices
into material classes from the palette's own ramps and from which bodies use
them, optionally ask a vision model about the uncertain ramps, and emit the
table the game loads.

    survey  palette ramps + body usage + heuristic proposal -> OUT/survey.json, OUT/sheets/
            (an existing survey.json's hand `label`/`vision_class` are carried forward)
    label   (--vision, needs the `agy` CLI) vision_class for ramps under --threshold
    emit    survey.json -> materials.json, precedence: hand `label` > vision_class > heuristic
    check   exit 1 when the committed table differs from a fresh emit of survey.json

Only `label` touches a model, and only through regenerate_backgrounds'
agy_structured. survey.json and sheets/ are git-ignored; the emitted table
is the one committed file. Spec:
docs/superpowers/specs/2026-08-28-actor-surface-and-materials-design.md."""
import argparse
import json
import pathlib
import shutil
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from PyAitD.render.geometry import POLY_TYPES, pose_geometry, vertex_groups  # noqa: E402
from PyAitD.render.materials import DEFAULT_TABLE_PATH, MATERIAL_CLASSES  # noqa: E402
from tools.export_backgrounds import save_png  # noqa: E402

SURVEY_FILE = "survey.json"
DEFAULT_OUT = pathlib.Path("data/aitd1/materials-survey")
RAMP_HUE_TOLERANCE = 0.06   # hue drift (0..1 circle) allowed inside one ramp
GREY_SATURATION = 0.12      # below this an entry has no usable hue
CONFIDENT = 0.8             # ramps at or above this skip the vision pass
HEROES = (0, 1)             # both hero body archives: Carnby's and Emily's
MAGENTA = (255, 0, 255)


# ---- colour ----

def rgb_to_hsl(rgb):
    """(N,3) uint8 -> (hue, saturation, lightness) float arrays in 0..1."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    r, g, b = c[:, 0], c[:, 1], c[:, 2]
    hi, lo = c.max(axis=1), c.min(axis=1)
    light = (hi + lo) / 2.0
    delta = hi - lo
    sat = np.where(delta > 0, delta / (1.0 - np.abs(2.0 * light - 1.0) + 1e-9), 0.0)
    hue = np.zeros_like(light)
    m = delta > 0
    rm, gm, bm = (hi == r) & m, (hi == g) & m & (hi != r), (hi == b) & m & (hi != r) & (hi != g)
    hue[rm] = ((g - b)[rm] / delta[rm]) % 6.0
    hue[gm] = (b - r)[gm] / delta[gm] + 2.0
    hue[bm] = (r - g)[bm] / delta[bm] + 4.0
    return hue / 6.0, sat, light


def _hue_distance(a, b):
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def split_ramps(palette):
    """Runs of indices whose lightness is monotone and whose hue stays
    near the run's first saturated entry. Every index lands in exactly one
    ramp; an entry that fits nowhere is a ramp of its own."""
    hue, sat, light = rgb_to_hsl(palette)
    ramps = []
    start = 0
    direction = 0
    while start < len(palette):
        end = start
        anchor = hue[start] if sat[start] >= GREY_SATURATION else None
        direction = 0
        while end + 1 < len(palette):
            nxt = end + 1
            step = np.sign(light[nxt] - light[end])
            if step == 0:
                break
            if direction == 0:
                direction = step
            elif step != direction:
                break
            if sat[nxt] >= GREY_SATURATION:
                if anchor is None:
                    anchor = hue[nxt]
                elif _hue_distance(hue[nxt], anchor) > RAMP_HUE_TOLERANCE:
                    break
            elif anchor is not None and sat[end] >= GREY_SATURATION:
                break   # a coloured ramp does not continue into grey
            end = nxt
        ramps.append((start, end))
        start = end + 1
    return ramps


# ---- usage ----

def body_usage(bodies):
    """{palette index: {"bodies": [...], "triangles": n, "groups": [...]}}
    over every polygon primitive of every body; lines and points are not
    surfaces and are skipped."""
    out = {}
    for key in sorted(bodies):
        body = bodies[key]
        groups = vertex_groups(body)
        for prim in body.primitives:
            if prim.type not in POLY_TYPES or len(prim.points) < 3:
                continue
            entry = out.setdefault(prim.color, {"bodies": [], "triangles": 0, "groups": set()})
            if key not in entry["bodies"]:
                entry["bodies"].append(key)
            entry["triangles"] += len(prim.points) - 2
            entry["groups"].update(int(groups[p]) for p in prim.points if 0 <= p < len(groups))
    for entry in out.values():
        entry["groups"] = sorted(entry["groups"])
    return out


def _ramp_usage(lo, hi, usage):
    bodies, triangles, groups = [], 0, set()
    for index in range(lo, hi + 1):
        entry = usage.get(index)
        if entry is None:
            continue
        bodies += [b for b in entry["bodies"] if b not in bodies]
        triangles += entry["triangles"]
        groups.update(entry["groups"])
    return {"bodies": sorted(bodies), "triangles": triangles, "groups": sorted(groups)}


def propose(lo, hi, palette, usage, bodies=None):
    """(class, confidence, reason) for one ramp. `bodies` (the survey's
    dict) lets the rule read group counts; without it every body counts as
    one-group scenery."""
    used = _ramp_usage(lo, hi, usage)
    if not used["bodies"]:
        return "matte", 0.9, "unused by any body"
    hue, sat, light = rgb_to_hsl(palette[lo:hi + 1])
    h, s, l, n = float(np.median(hue)), float(sat.mean()), float(light.mean()), hi - lo + 1
    group_counts = [len(bodies[b].groups) if bodies and b in bodies else 1 for b in used["bodies"]]
    many_groups = bool(group_counts) and min(group_counts) >= 8
    scenery = bool(group_counts) and max(group_counts) <= 1
    if s < GREY_SATURATION:
        if n >= 8:
            return "metal", 0.5, f"long grey ramp ({n} steps)"
        return "stone", 0.4, f"short grey ramp ({n} steps)"
    if 0.02 <= h <= 0.11 and 0.2 <= s <= 0.75 and l > 0.35:
        conf = 0.7 + (0.1 if many_groups else 0.0)
        return "skin", conf, "peach hue" + ("; used only by bodies with >= 8 groups" if many_groups else "")
    if 0.03 <= h <= 0.13 and s > 0.3 and l <= 0.4:
        if scenery:
            return "wood", 0.5, "dark saturated brown on one-group scenery"
        return "leather", 0.5, "dark saturated brown on articulated bodies"
    if n <= 2 and l > 0.8:
        return "emissive", 0.5, "very short, very bright ramp"
    if 0.25 <= h <= 0.75:
        return "cloth", 0.5, "green/blue hue"
    if many_groups:
        return "cloth", 0.3, "unclassified hue on articulated bodies"
    return "matte", 0.3, "unclassified hue on scenery"


# What a re-survey must not destroy: everything a human or a model put on a
# ramp. `label` in particular has no other home -- the documented fix for a
# misclassification is to hand-label a ramp in survey.json and re-run `make
# bootstrap-materials`, which runs the survey stage first.
CARRIED_FIELDS = ("label", "vision_class", "vision_reason")


def survey(palette, bodies, previous=None):
    """The ramp table for `palette`: boundaries, heuristic proposal and body
    usage, all re-derived. `previous` is an earlier survey whose human and
    model fields (CARRIED_FIELDS) are carried onto the ramp with the same
    (lo, hi). Ramp boundaries are deterministic from the palette, so in
    practice every ramp matches; one whose boundaries moved is a different
    ramp and inherits nothing rather than a stale label."""
    usage = body_usage(bodies)
    carried = {(r.get("lo"), r.get("hi")): r for r in (previous or {}).get("ramps", ())}
    ramps = []
    for lo, hi in split_ramps(palette):
        name, confidence, reason = propose(lo, hi, palette, usage, bodies)
        ramp = {"lo": lo, "hi": hi, "class": name, "confidence": round(confidence, 2),
                "reason": reason, "usage": _ramp_usage(lo, hi, usage)}
        old = carried.get((lo, hi), {})
        ramp.update({k: old[k] for k in CARRIED_FIELDS if k in old})
        ramps.append(ramp)
    return {"ramps": ramps}


# ---- sheets ----

def contact_sheet(body, palette, highlight=None):
    """A flat 320x200 render of the body in rest pose on a black plate
    through SoftwareBackend; `highlight=(lo, hi)` paints that ramp magenta."""
    from PyAitD.render.asset_resolver import ImageAsset
    from PyAitD.render.render_soft import SoftwareBackend
    from PyAitD.render.scene import ActorDraw, CameraView, FrameDescription
    from PyAitD.engine.skel import skin
    from PyAitD.engine.world import CameraState
    pal = np.array(palette, dtype=np.uint8, copy=True)
    if highlight is not None:
        pal[highlight[0]:highlight[1] + 1] = MAGENTA
    states = [(0, (0, 0, 0))] * len(body.groups)
    rest = np.array(body.vertices, dtype=np.float64).reshape(-1, 3)
    extent = float(np.abs(rest).max()) if len(rest) else 100.0
    depth = max(0.0, extent * 320.0 / 90.0 - 1000.0)
    y_mid = float((rest[:, 1].min() + rest[:, 1].max()) / 2.0) if len(rest) else 0.0
    position = (0.0, -y_mid, depth)
    state = CameraState(0, 0, 0, 0, 0, 0, 1000, 320, 320).angles()
    logical = skin(body, states, position, state, actor_angles=(0, 0, 0))
    actor = ActorDraw(0, pose_geometry(body, states, (0, 0, 0)), position, 0, tuple(body.zv), logical, ())
    frame = FrameDescription(CameraView(state), ImageAsset(np.zeros((200, 320, 3), np.uint8), False),
                             pal, (actor,), ())
    return SoftwareBackend().draw(frame)


def write_sheets(out_dir, data, palette, bodies):
    sheets = pathlib.Path(out_dir) / "sheets"
    for key, body in bodies.items():
        hero, num = key.split(":")
        save_png(sheets / f"body{hero}-{int(num):03d}.png", contact_sheet(body, palette))
    for ramp in data["ramps"]:
        used = ramp["usage"]["bodies"]
        if not used:
            continue
        top = max(used, key=lambda k: sum(1 for p in bodies[k].primitives if p.color in range(ramp["lo"], ramp["hi"] + 1)))
        hero, num = top.split(":")
        ramp["sheet"] = f"sheets/body{hero}-{int(num):03d}.png"
        ramp["highlight"] = f"sheets/ramp{ramp['lo']:03d}-{ramp['hi']:03d}.png"
        save_png(sheets / f"ramp{ramp['lo']:03d}-{ramp['hi']:03d}.png",
                 contact_sheet(bodies[top], palette, highlight=(ramp["lo"], ramp["hi"])))


# ---- emit ----

def resolve_class(ramp):
    return ramp.get("label") or ramp.get("vision_class") or ramp["class"]


def emit_table(data):
    """The committed table: one row per ramp that says something.

    A ramp that no body uses and that nothing classified as anything but
    `matte` resolves to exactly what parse_table's implicit `matte` default
    already gives it, so emitting it would add a row saying nothing to a file
    a human is meant to read and hand-edit. Note segments with nothing in
    them are dropped for the same reason. `matte` on a ramp bodies *do* use
    is a real answer about a real surface and keeps its row."""
    ramps = []
    for ramp in data["ramps"]:
        used = ramp["usage"]
        name = resolve_class(ramp)
        if not used["bodies"] and name == "matte":
            continue
        note = []
        if used["bodies"]:
            note.append(f"bodies {', '.join(used['bodies'][:6])}" + (" ..." if len(used["bodies"]) > 6 else ""))
        if used["groups"]:
            note.append(f"groups {', '.join(str(g) for g in used['groups'][:8])}")
        note.append(f"heuristic: {ramp['class']} ({ramp.get('confidence', 0)})")
        if ramp.get("vision_class"):
            note.append(f"vision: {ramp['vision_class']}")
        if ramp.get("label"):
            note.append(f"label: {ramp['label']}")
        ramps.append({"lo": ramp["lo"], "hi": ramp["hi"], "class": name, "note": "; ".join(note)})
    return {"ramps": ramps, "indices": {}}


# ---- data loading ----

def load_game(data_dir):
    """(palette, bodies) from real game data: the floor-0 palette and every
    body of both hero archives, keyed '<hero>:<num>'."""
    from PyAitD.engine.assets import Assets
    from PyAitD.engine.floor import Floor
    from PyAitD.games.aitd1.profile import AITD1
    palette = Floor(data_dir, 0, AITD1).palette
    bodies = {}
    for hero in HEROES:
        assets = Assets(data_dir, AITD1, hero=hero)
        for num in range(assets.num_bodies):
            try:
                bodies[f"{hero}:{num}"] = assets.body(num)
            except (ValueError, KeyError, IndexError):
                continue   # an entry that is not a body (real archives carry a few)
    return palette, bodies


def _read_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _write_json(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


# ---- CLI ----

def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("data", type=pathlib.Path, help="game data directory (e.g. .../INDARK); unused by emit/check")
    p.add_argument("stage", choices=("survey", "label", "emit", "check"))
    p.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT, help="survey directory")
    p.add_argument("--table", type=pathlib.Path, default=DEFAULT_TABLE_PATH, help="materials.json to emit/check")
    p.add_argument("--model", default="gemini-3.1-pro", help="vision model for the label stage")
    p.add_argument("--threshold", type=float, default=CONFIDENT, help="label ramps below this confidence")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    survey_path = args.out / SURVEY_FILE
    if args.stage == "survey":
        if not args.data.is_dir():
            print(f"error: game data directory not found: {args.data}", file=sys.stderr)
            return 2
        palette, bodies = load_game(args.data)
        previous = _read_json(survey_path) if survey_path.is_file() else None
        data = survey(palette, bodies, previous)
        write_sheets(args.out, data, palette, bodies)
        _write_json(survey_path, data)
        print(f"{survey_path}: {len(data['ramps'])} ramps over {len(bodies)} bodies")
        return 0
    if not survey_path.is_file():
        print(f"error: no {survey_path}; run the survey stage first", file=sys.stderr)
        return 2
    data = _read_json(survey_path)
    if args.stage == "label":
        return label_stage(data, args, survey_path)
    table = emit_table(data)
    if args.stage == "emit":
        _write_json(args.table, table)
        print(f"{args.table}: {len(table['ramps'])} ramps")
        return 0
    committed = _read_json(args.table) if args.table.is_file() else None
    if committed != table:
        print(f"{args.table} differs from a fresh emit of {survey_path}", file=sys.stderr)
        return 1
    print(f"{args.table} is up to date")
    return 0


LABEL_SCHEMA = {
    "type": "object",
    "required": ["class", "reason"],
    "properties": {"class": {"type": "string", "enum": list(MATERIAL_CLASSES)},
                   "reason": {"type": "string"}},
    "additionalProperties": False,
}


def label_instructions(sheet, highlight):
    return (f"Look at the image at {sheet}. It is a flat-shaded render of a low-polygon character or "
            f"object from the 1992 game Alone in the Dark, on a black background. Then look at {highlight}: "
            "the same render with one of its colour ramps painted magenta. Name the real-world material the "
            "magenta surfaces most plausibly represent on this model. Choose exactly one of: "
            + ", ".join(MATERIAL_CLASSES) + ". Use 'matte' when nothing fits. Give a one-sentence reason.")


def ask_vision(model, out_dir):
    """An `ask(sheet, highlight)` over agy, resolving the survey's relative
    sheet paths against `out_dir`."""
    from tools.regenerate_backgrounds import agy_structured
    out_dir = pathlib.Path(out_dir)

    def ask(sheet, highlight):
        return agy_structured(model, label_instructions(
            (out_dir / sheet).resolve(), (out_dir / highlight).resolve()), LABEL_SCHEMA)
    return ask


def label_ramps(data, ask, threshold):
    """Fill `vision_class`/`vision_reason` on every ramp below `threshold`
    that has sheets and no hand `label`. Returns how many were asked."""
    count = 0
    for ramp in data["ramps"]:
        if ramp.get("label") or ramp.get("confidence", 0.0) >= threshold:
            continue
        if not ramp.get("sheet") or not ramp.get("highlight"):
            continue
        answer = ask(ramp["sheet"], ramp["highlight"])
        name = answer.get("class")
        if name not in MATERIAL_CLASSES:
            raise ValueError(f"ramp {ramp['lo']}..{ramp['hi']}: vision model answered {name!r}, "
                             f"not one of {', '.join(MATERIAL_CLASSES)}")
        ramp["vision_class"] = name
        ramp["vision_reason"] = str(answer.get("reason", ""))
        count += 1
    return count


def label_stage(data, args, survey_path):
    if shutil.which("agy") is None:
        print("error: the `agy` CLI is not on PATH; the label stage needs it (survey.json untouched)",
              file=sys.stderr)
        return 2
    asked = label_ramps(data, ask_vision(args.model, args.out), args.threshold)
    _write_json(survey_path, data)
    print(f"{survey_path}: {asked} ramps labelled by {args.model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
