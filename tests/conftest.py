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
def gl_ctx():
    moderngl = pytest.importorskip("moderngl")
    try:
        ctx = moderngl.create_standalone_context(require=330)
    except Exception as exc:  # no GL on this host/CI
        pytest.skip(f"no standalone GL 3.3 context: {exc}")
    yield ctx
    ctx.release()
