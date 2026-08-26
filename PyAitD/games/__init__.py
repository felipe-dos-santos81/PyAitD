# SPDX-License-Identifier: GPL-2.0-only
"""Per-game profiles. May import engine only."""
from PyAitD.games.aitd1.profile import AITD1

PROFILES = {"aitd1": AITD1}


def load_profile(name):
    return PROFILES[name]
