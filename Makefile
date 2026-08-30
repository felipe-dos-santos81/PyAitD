# Makefile for PyAitD — Alone in the Dark 1 engine reimplementation
# Targets: env → run → test → proof suites → clean
SERVICE = PyAitD

# Variables
VENV_DIR = .venv
PYTHON = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip
floor ?=
data ?= data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK
out ?= data/aitd1/textures
textures ?= data/aitd1/textures

# Every pytest target runs headless: AGENTS.md requires SDL_VIDEODRIVER=dummy
# for any test touching rendering or pygame, and SDL_AUDIODRIVER=dummy keeps
# the mixer from opening a device on machines that have one.
HEADLESS = SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy

.PHONY: help install run run-combat run-mouse-combat test test-engine test-render test-shell test-tools test-meta test-journey proof-mouse proof-combat proof-graphics proof-intro prove prove-m3b prove-shell prove-mouse prove-mouse-only prove-mouse-accessibility prove-combat prove-graphics prove-intro prove-persistence export-textures check-textures bootstrap-materials clean

# ── Environment ──────────────────────────────────────────────────────────────

help: ## Print this help message
	@printf '\033[01;32m${SERVICE} — Alone in the Dark 1 engine reimplementation\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [arg=\"val\"...]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

install: ## Create .venv and install the package (editable, with dev deps)
	@if [ ! -d "$(VENV_DIR)" ]; then \
		python3 -m venv $(VENV_DIR); \
		$(PIP) install -U pip; \
		$(PIP) install -e ".[dev]"; \
	fi; \
	echo "Environment setup complete."

clean: ## Remove venv and all temporary/generated files
	rm -rf $(VENV_DIR)
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "Cleanup complete."

# ── Run ──────────────────────────────────────────────────────────────────────

run: install ## Run the game through character selection (floor=0 attic debug bypass, textures=DIR defaults to data/aitd1/textures — pass textures= to play the original backgrounds, trace=FILE)
	$(PYTHON) -m PyAitD $(if $(floor),--floor "$(floor)") --data "$(data)" $(if $(trace),--trace $(trace)) $(if $(textures),--textures "$(textures)")

run-combat: install ## Run the supported floor-5 combat venue (hero=0 Carnby, hero=1 Emily)
	$(PYTHON) -m PyAitD --combat-venue --data "$(data)" $(if $(hero),--hero "$(hero)") $(if $(trace),--trace $(trace))

run-mouse-combat: install ## Run the deterministic object-38 mouse combat proof fixture (hero=0 Carnby, hero=1 Emily)
	$(PYTHON) -m PyAitD --mouse-combat-fixture --data "$(data)" $(if $(hero),--hero "$(hero)") $(if $(trace),--trace $(trace))

# ── Development ──────────────────────────────────────────────────────────────

test: install ## Run the whole pytest suite, headless
	$(HEADLESS) $(PYTHON) -m pytest tests/ -q

test-engine: install ## Engine group: simulation, LIFE VM, formats, actors, anim, tracks, collision, navmesh, picking, opcodes
	$(HEADLESS) $(PYTHON) -m pytest -m engine -q

test-render: install ## Render group: scene, geometry, both backends, asset resolution, texture export and check
	$(HEADLESS) $(PYTHON) -m pytest -m render -q

test-shell: install ## Shell group: event pump, settings, CLI, UI screens and modals
	$(HEADLESS) $(PYTHON) -m pytest -m shell -q

test-tools: install ## Tools group: the standalone scripts under tools/
	$(HEADLESS) $(PYTHON) -m pytest -m tools -q

test-meta: install ## Meta group: the repo's own rules (package layering, test grouping)
	$(HEADLESS) $(PYTHON) -m pytest -m meta -q

test-journey: install ## Journey group: real run() event pump and long real-data simulations
	$(HEADLESS) $(PYTHON) -m pytest -m journey -q

# ── Artifact proofs (need GL and real game data) ─────────────────────────────

proof-mouse: install ## Navmesh proof: build it for every camera-visible room, every floor (data="path/to/INDARK")
	$(PYTHON) tools/prove_mouse.py "$(data)"

proof-combat: install ## Combat proof: venue, real enemy damage, player arms, game over
	$(PYTHON) tools/prove_combat.py "$(data)"

proof-graphics: install ## Graphics proof: attic + combat fixtures at scale 4 per shading mode x realism preset, plus a flat-mesh pair, a hard-shadow pair, an un-composited pair and an over-composited pair, to docs/graphics-proof/
	$(PYTHON) tools/prove_graphics.py "$(data)"

proof-intro: install ## Opening cutscene proof: headless run to CutsceneFinished + one GL render per visited camera to docs/intro-proof/
	$(HEADLESS) $(PYTHON) -m pytest tests/test_intro.py -q && $(PYTHON) tools/prove_intro.py "$(data)"

prove-persistence: install ## M4a2 persistence gate: save schema, slots, restoration, menu pages, loop policy, journeys, mouse contract
	$(HEADLESS) $(PYTHON) -m pytest tests/test_save.py tests/test_game_rng.py tests/test_ui_reducers.py tests/test_ui_mouse.py tests/test_ui_render.py tests/test_runtime_modes.py tests/test_shell_journeys.py tests/test_mouse_only.py tests/test_main.py tests/test_config.py -q

# ── Legacy milestone gate names, kept so the proof docs keep working ─────────
# Each alias runs a superset of the files it historically ran; the superset
# property is pinned by tests/test_test_groups.py.

prove: test-engine ## Alias of test-engine (was the M3a proof)

prove-m3b: install ## Alias (was the M3b interaction proof)
	$(HEADLESS) $(PYTHON) -m pytest -m "engine or shell" -q

prove-shell: install ## Alias (was the M4a1 shell proof)
	$(HEADLESS) $(PYTHON) -m pytest -m "engine or shell" -q

prove-mouse-only: test-shell ## Alias of test-shell (was the M3e one-button proof)

prove-mouse-accessibility: test-shell ## Alias of test-shell (was the mouse accessibility proof)

prove-mouse: proof-mouse ## Alias of proof-mouse

prove-combat: proof-combat ## Alias of proof-combat

prove-graphics: proof-graphics ## Alias of proof-graphics

prove-intro: proof-intro ## Alias of proof-intro

export-textures: install ## Export every camera background + 5 KILLED_SORCERER alts + palette + ITD_RESS screens + guides + layout sidecars + manifest schema 3 for the external texture tool (out=data/aitd1/textures, floors=0-7, scale=4, force=1, screens=0 to skip screens)
	$(PYTHON) tools/export_textures.py "$(data)" --out "$(out)" --floors "$(or $(floors),0-7)" --guide-scale "$(or $(scale),4)" $(if $(force),--force) $(if $(filter 0,$(screens)),--no-screens)

check-textures: install ## Check a texture dir the way the game loads it (textures=data/aitd1/textures, floors=0-7); proof=1 renders original|texture side-by-sides to docs/graphics-proof/textures/ (bases, alts -alt.png, screens)
	$(PYTHON) tools/check_textures.py "$(data)" "$(textures)" --floors "$(or $(floors),0-7)" $(if $(proof),--proof)

bootstrap-materials: install ## Survey palette ramps + body usage into data/aitd1/materials-survey, then emit PyAitD/render/materials.json (survey_out=, vision=1 runs the agy labelling stage in between, model=, threshold=0.8). The survey dir is git-ignored and holds the hand `label`s from the 23-ramp review; without it the emit falls back to vision/heuristic guesses, which tests/test_bootstrap_materials.py's REVIEWED_RAMPS then fails on. See docs/materials-v2-proof.md.
	$(PYTHON) tools/bootstrap_materials.py "$(data)" survey --out "$(or $(survey_out),data/aitd1/materials-survey)"
	$(if $(vision),$(PYTHON) tools/bootstrap_materials.py "$(data)" label --out "$(or $(survey_out),data/aitd1/materials-survey)" $(if $(model),--model "$(model)") $(if $(threshold),--threshold "$(threshold)"))
	$(PYTHON) tools/bootstrap_materials.py "$(data)" emit --out "$(or $(survey_out),data/aitd1/materials-survey)"
