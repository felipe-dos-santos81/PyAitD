# SPDX-License-Identifier: GPL-2.0-only
"""Content packs: TOML-authored enemies (later objects, scenarios, players)
run by a fixed vocabulary of Python behaviours over the same primitives the
LIFE opcodes call. Spec: docs/superpowers/specs/2026-09-03-content-packs-
foundation-and-enemies-design.md."""
from PyAitD.engine.content.schema import BEHAVIOUR_LIFE, PackError
