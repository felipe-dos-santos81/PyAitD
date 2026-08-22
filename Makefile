# Makefile for maitd — Alone in the Dark 1 engine reimplementation
# Targets: env → run → test → prove → clean
SERVICE = maitd

# Variables
VENV_DIR = .venv
PYTHON = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip
floor ?= 0
data ?= "Alone in the Dark 1.app/Contents/Resources/game/INDARK"

.PHONY: help install run test prove clean

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

run: install ## Run the play viewer: walk the actor, cameras switch, masks occlude (usage: make run floor=3 data="path/to/INDARK")
	$(PYTHON) -m maitd --floor "$(floor)" --data $(data)

# ── Development ──────────────────────────────────────────────────────────────

test: install ## Run the pytest unit test suite
	$(PYTHON) -m pytest tests/ -q

prove: install ## M3a proof: parse-all LIFE/TRACK/tables + headless 60-tick boot
	$(PYTHON) -m pytest tests/test_prove_m3a.py -q
