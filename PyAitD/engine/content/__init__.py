# SPDX-License-Identifier: GPL-2.0-only
"""Content packs: TOML-authored enemies (later objects, scenarios, players)
run by a fixed vocabulary of Python behaviours over the same primitives the
LIFE opcodes call. Spec: docs/superpowers/specs/2026-09-03-content-packs-
foundation-and-enemies-design.md."""
from PyAitD.engine.content.pack import PACK_FILE, Pack, check_archives, load_pack, pack_digest, read_pack
from PyAitD.engine.content.schema import BEHAVIOUR_LIFE, PackError
from PyAitD.engine.content.world import ContentAttachment, attach, compile_record
