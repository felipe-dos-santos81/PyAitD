# Makefile for PyAitD — Alone in the Dark 1 engine reimplementation
# Targets: env → run → test → proof suites → clean
SERVICE = PyAitD

# Variables
VENV_DIR = .venv
PYTHON = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip
floor ?=
data ?= data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK
out ?= data/aitd1/overrides
overrides ?= data/aitd1/overrides

.PHONY: help install install-ai run run-combat run-mouse-combat test prove prove-m3b prove-shell prove-mouse prove-mouse-only prove-mouse-accessibility prove-combat prove-graphics export-backgrounds check-overrides regenerate-backgrounds clean

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

install-ai: install ## Add the optional google-genai dependency for make regenerate-backgrounds
	$(PIP) install -e ".[dev,ai]"

clean: ## Remove venv and all temporary/generated files
	rm -rf $(VENV_DIR)
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "Cleanup complete."

# ── Run ──────────────────────────────────────────────────────────────────────

run: install ## Run the game through character selection (floor=0 for the attic debug bypass, overrides=DIR for regenerated backgrounds)
	$(PYTHON) -m PyAitD $(if $(floor),--floor "$(floor)") --data "$(data)" $(if $(trace),--trace $(trace)) $(if $(overrides),--overrides "$(overrides)")

run-combat: install ## Run the supported floor-5 combat venue (hero=0 Carnby, hero=1 Emily)
	$(PYTHON) -m PyAitD --combat-venue --data "$(data)" $(if $(hero),--hero "$(hero)") $(if $(trace),--trace $(trace))

run-mouse-combat: install ## Run the deterministic object-38 mouse combat proof fixture (hero=0 Carnby, hero=1 Emily)
	$(PYTHON) -m PyAitD --mouse-combat-fixture --data "$(data)" $(if $(hero),--hero "$(hero)") $(if $(trace),--trace $(trace))

# ── Development ──────────────────────────────────────────────────────────────

test: install ## Run the pytest unit test suite
	$(PYTHON) -m pytest tests/ -q

prove: install ## M3a proof: parse-all LIFE/TRACK/tables + headless 60-tick boot
	$(PYTHON) -m pytest tests/test_prove_m3a.py -q

prove-m3b: install ## M3b proof: focused interaction suite headless (continuation, inventory, contacts, zones, opcodes, modes, attic)
	SDL_VIDEODRIVER=dummy $(PYTHON) -m pytest \
		tests/test_life_continuation.py \
		tests/test_interaction.py \
		tests/test_actor_contacts.py \
		tests/test_gere_dec.py \
		tests/test_life_interaction_ops.py \
		tests/test_runtime_modes.py \
		tests/test_m3b_attic.py -q

prove-shell: install ## M4a1 proof: shell, configuration, mouse contract, and real-loop journeys
	SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy $(PYTHON) -m pytest \
		tests/test_config.py tests/test_assets.py tests/test_effects.py \
		tests/test_ui_input.py tests/test_ui_reducers.py tests/test_ui_mouse.py \
		tests/test_ui_render.py tests/test_runtime_modes.py tests/test_main.py \
		tests/test_mouse_only.py tests/test_shell_journeys.py -q

prove-mouse: install ## M3d proof: build the navmesh for every camera-visible room, every floor (usage: make prove-mouse data="path/to/INDARK")
	$(PYTHON) tools/prove_mouse.py "$(data)"

prove-mouse-only: install ## M3e proof: one-button contract + real-data attic, combat, restart, and held-push journeys
	SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy $(PYTHON) -m pytest tests/test_mouse_only.py -q

prove-mouse-accessibility: install ## Mouse accessibility proof: focused input, UI, loop, shell, and real-data journeys
	SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy $(PYTHON) -m pytest \
		tests/test_ui_input.py tests/test_ui_reducers.py tests/test_ui_mouse.py \
		tests/test_ui_render.py tests/test_play_loop.py tests/test_runtime_modes.py \
		tests/test_main.py tests/test_mouse_only.py tests/test_shell_journeys.py -q

prove-combat: install ## M3c proof: venue, real enemy damage, player arms, game over (pytest gate)
	$(PYTHON) tools/prove_combat.py "$(data)"

prove-graphics: install ## Enhanced graphics proof: render attic + combat fixtures at scale 4 per shading mode to docs/graphics-proof/
	$(PYTHON) tools/prove_graphics.py "$(data)"

export-backgrounds: install ## Export every camera background + guide + manifest for external AI regeneration (out=data/aitd1/overrides, floors=0-7, scale=4, force=1)
	$(PYTHON) tools/export_backgrounds.py "$(data)" --out "$(out)" --floors "$(or $(floors),0-7)" --guide-scale "$(or $(scale),4)" $(if $(force),--force)

check-overrides: install ## Check an override dir the way the game loads it (overrides=data/aitd1/overrides, floors=0-7); proof=1 renders original|override side-by-sides to docs/graphics-proof/overrides/
	$(PYTHON) tools/check_overrides.py "$(data)" "$(overrides)" --floors "$(or $(floors),0-7)" $(if $(proof),--proof)

regenerate-backgrounds: install ## Regenerate data/aitd1/overrides backgrounds with Gemini into data/aitd1/overrides-ai (in=, out_ai=, floors=0-7, style=, force=1, dry=1, text_model=, image_model=); needs GEMINI_API_KEY and `make install-ai`
	$(PYTHON) tools/regenerate_backgrounds.py "$(or $(in),data/aitd1/overrides)" --out "$(or $(out_ai),data/aitd1/overrides-ai)" --floors "$(or $(floors),0-7)" $(if $(style),--style "$(style)") $(if $(force),--force) $(if $(dry),--dry-run) $(if $(text_model),--text-model "$(text_model)") $(if $(image_model),--image-model "$(image_model)")
