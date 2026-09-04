# SPDX-License-Identifier: GPL-2.0-only
import os
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DATA = REPO_ROOT / "data" / "aitd1" / "Alone in the Dark 1.app" / "Contents" / "Resources" / "game" / "INDARK"


@pytest.fixture
def data_dir():
    path = pathlib.Path(os.environ.get("PYAITD_DATA", DEFAULT_DATA))
    if not path.is_dir():
        pytest.skip(f"game data not found at {path}")
    return path


@pytest.fixture
def profile():
    """The GameProfile under test. AITD1 today; a second game would
    parametrize here. Tests that assert AITD1's *identity* -- its pak names,
    opcode table, CVar list, reduced-opcode set -- import AITD1 directly
    instead (tests/test_game_profile.py). This fixture makes the suite's
    construction idiom uniform; it does NOT make the tests portable, since
    they still assert AITD1-specific golden values."""
    from PyAitD.games.aitd1.profile import AITD1
    return AITD1


@pytest.fixture
def example_pack_dir():
    """The in-repo example content pack (packs/example), used by the
    content-pack tests and by `make run content=packs/example`."""
    return REPO_ROOT / "packs" / "example"


@pytest.fixture
def gl_ctx():
    moderngl = pytest.importorskip("moderngl")
    try:
        ctx = moderngl.create_standalone_context(require=330)
    except Exception as exc:  # no GL on this host/CI
        pytest.skip(f"no standalone GL 3.3 context: {exc}")
    yield ctx
    ctx.release()


def held_pointer(pos=None):
    """A ControlsState with the left button down. Since held pointer follow
    every navigation intent is hold-bound: a test that ticks a walk must hold
    the button, or the next tick cancels the intent (playworld._apply_mouse_input).
    """
    from PyAitD.app.controls.pointer import PointerState
    from PyAitD.app.controls.snapshot import ControlsState
    return ControlsState(pointer=PointerState(held=True, pos=pos), focused=True)


def stub_renderer(scale=1.0):
    """The least a stub needs to survive render_active_mode: the UI scale it
    builds its painter from, and the scene thumbnail the two modals that sit
    over the world ask for. One definition, so a branch that starts reading
    another renderer attribute fails in one place rather than three."""
    import numpy as np
    from types import SimpleNamespace
    return SimpleNamespace(
        ui_scale=lambda: scale,
        scene_thumbnail=lambda: np.zeros((200, 320, 3), np.uint8),
    )


def painter_from_frame(frame):
    """A scale-1 UIPainter seeded with `frame`, the stand-in for a
    monkeypatched `render_active_mode` (task 9: it now returns a painter,
    not a numpy frame). Reproduces exactly what the old run() bridge line
    did -- `UIPainter().sprite(frame, (0, 0))` -- so a test that fakes
    render_active_mode's output still hands run() something the rest of
    the frame (hit feedback, HUD, cursor) can paint on top of."""
    from PyAitD.app.ui import UIPainter
    painter = UIPainter()
    painter.sprite(frame, (0, 0))
    return painter
