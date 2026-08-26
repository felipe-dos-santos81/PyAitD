# SPDX-License-Identifier: GPL-2.0-only
"""Per-game profiles. May import engine only.

Resolved lazily so that importing a light module under games/ (mouse_contract,
say) does not build the AITD1 opcode table and pull numpy in behind it."""
import importlib
from types import MappingProxyType

PROFILES = MappingProxyType({"aitd1": ("PyAitD.games.aitd1.profile", "AITD1")})


def load_profile(name):
    module, attr = PROFILES[name]
    return getattr(importlib.import_module(module), attr)
