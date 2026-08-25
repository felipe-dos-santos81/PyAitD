# Makefile for PyAitD — Alone in the Dark 1 engine reimplementation
# Targets: env → run → test → proof suites → clean
SERVICE = PyAitD

# Variables
VENV_DIR = .venv
PYTHON = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip
floor ?=
data ?= Alone in the Dark 1.app/Contents/Resources/game/INDARK

.PHONY: help install run run-combat run-mouse-combat test prove prove-m3b prove-shell prove-mouse prove-mouse-only prove-mouse-accessibility prove-combat clean

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

run: install ## Run the game through character selection (use floor=0 for the attic debug bypass)
	$(PYTHON) -m PyAitD $(if $(floor),--floor "$(floor)") --data "$(data)" $(if $(trace),--trace $(trace))

run-combat: install ## Run the supported floor-5 combat venue
	$(PYTHON) -m PyAitD --combat-venue --data "$(data)" $(if $(trace),--trace $(trace))

run-mouse-combat: install ## Run the deterministic object-38 mouse combat proof fixture
	$(PYTHON) -m PyAitD --mouse-combat-fixture --data "$(data)" $(if $(trace),--trace $(trace))

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
