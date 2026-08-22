# SPDX-License-Identifier: GPL-2.0-only
"""M1 proof: walk every floor, parse rooms/cameras, decode every camera image."""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from maitd.floor import Floor  # noqa: E402
from maitd.pak import Pak, PakError, find_pak  # noqa: E402


def main():
    data = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else (
        pathlib.Path(__file__).resolve().parent.parent
        / "Alone in the Dark 1.app"
        / "Contents"
        / "Resources"
        / "game"
        / "INDARK"
    )
    failures = 0
    for number in range(0, 20):
        try:
            find_pak(data, f"ETAGE{number:02d}")
        except PakError:
            break
        floor = Floor(data, number)
        images = Pak(find_pak(data, f"CAMERA{number:02d}"))
        bad = 0
        for cam in range(images.count):
            img = floor.camera_image(cam)
            if img.std() < 1.0:  # decoded garbage is near-uniform
                bad += 1
        print(
            f"floor {number:2d}: rooms={len(floor.rooms):2d} "
            f"cameras={len(floor.cameras):2d} images={images.count:2d} blank={bad}"
        )
        failures += bad
        if any(not r.camera_indices for r in floor.rooms):
            print(f"floor {number}: room with no cameras (legit in original data)")
    from maitd.assets import Assets
    assets = Assets(data)
    for i in range(assets.num_bodies):
        body = assets.body(i)
        assert len(body.vertices) > 0
        for prim in body.primitives:
            assert all(p < len(body.vertices) for p in prim.points)
    for i in range(assets.num_anims):
        anim = assets.anim(i)
        assert anim.num_frames > 0
    print(f"OK: parsed {assets.num_bodies} bodies and {assets.num_anims} anims")
    if failures:
        print(f"FAIL: {failures} problems")
        return 1
    print("OK: all floors parsed, all camera images decode non-blank")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
