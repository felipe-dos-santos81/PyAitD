# SPDX-License-Identifier: GPL-2.0-only
"""Content packs: TOML-authored enemies (later objects, scenarios, players)
run by a fixed vocabulary of Python behaviours over the same primitives the
LIFE opcodes call. Spec: docs/superpowers/specs/2026-09-03-content-packs-
foundation-and-enemies-design.md."""
from PyAitD.engine.content.enemies import enter_phase, step_enemy
from PyAitD.engine.content.pack import PACK_FILE, Pack, check_archives, check_references, load_pack, pack_digest, read_pack
from PyAitD.engine.content.runner import run_behaviour
from PyAitD.engine.content.schema import (
    BEHAVIOUR_LIFE, PackError, PickupRecord, SceneryRecord, TriggerRecord, parse_enemy, parse_object,
)
from PyAitD.engine.content.world import (
    CONTENT_TEXT_BASE, ContentAttachment, allocate_texts, attach, compile_record, initial_state,
)
