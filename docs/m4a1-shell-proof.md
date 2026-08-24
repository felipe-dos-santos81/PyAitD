# M4a1 Shell and Configuration Proof

Date: 2026-08-24
Spec: `docs/superpowers/specs/2026-08-24-m4a1-shell-design.md`
Plan: `docs/superpowers/plans/2026-08-24-m4a1-shell-and-configuration.md`

## Automated evidence

Run 2026-08-24 on macOS 26.6.2 (arm64) with the real game data
(`Alone in the Dark 1.app/Contents/Resources/game/INDARK`).

- `make prove-shell`: PASS — `165 passed in 6.90s` (`tests/test_config.py`,
  `tests/test_assets.py`, `tests/test_effects.py`, `tests/test_ui_input.py`,
  `tests/test_ui_reducers.py`, `tests/test_ui_mouse.py`, `tests/test_ui_render.py`,
  `tests/test_runtime_modes.py`, `tests/test_main.py`, `tests/test_mouse_only.py`,
  `tests/test_shell_journeys.py`; run under
  `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`).
- `make test` (`.venv/bin/pytest -q`): PASS — `559 passed, 1 skipped, 1 xfailed
  in 13.81s`.
- `make prove`: PASS — `4 passed in 0.22s` (`tests/test_prove_m3a.py`).

`tests/test_shell_journeys.py` drives the real `run()` event pump with
synthetic pygame events and the real shell render dispatch
(`render_active_mode` is not patched):

| Journey | Result | Observation |
|---|---|---|
| One-click Emily / Carnby | PASS | Portrait click → story click → exactly one atomic replacement; hero CVar and LISTBOD2/LISTANI2 vs LISTBODY/LISTANIM match; inventory empty at replacement; no PLAY tick before replacement |
| Keyboard back/start | PASS | RIGHT/ACCEPT enter Carnby's story, CANCEL returns, LEFT/OPEN_INVENTORY ×2 start Emily; each event advances exactly one presenter state |
| Menu/remap/sticky/save/reload | PASS | Escape opens the paused menu; Configuration → Sticky Action → capture UP ← `q`; Back saves once (schema 1, UP `['q']`, sticky true); Return resumes; Tab + Space + q yields exactly one `(joyd=1, click=1, action=0x2000)` tick, next tick `click==0`; a fresh `load_runtime_session` + `configure_session_input` compiles the same behavior |
| Capture replay | PASS | During ACTION capture, Return becomes the binding (stealing it from INVENTORY_CONFIRM, leaving `i`) and never reaches the reducer |
| Transition replay | PASS | Held movement/Action before opening and before closing the menu: the first resumed PLAY tick is `(0, 0, 0)` with empty held/sticky buffer state |
| Corrupt boot / forced save failure | PASS | Corrupt JSON boots to defaults with a notice naming the path; Dismiss click and ACCEPT dismissal clear only the notice — character select and menu modes/presenters unchanged; the Back boundary saved exactly once |
| Death restart | PASS | Dirty/live remap, sticky flag, settings path, and visible error survive `_restart_branch`; input transient state does not |
| Process-level reload | PASS | Two independent `load_runtime_session` calls around a real `save_settings` read bytes off disk, not a reused object |

## Windowed one-button/keyboard evidence — PENDING

Not yet performed. These items require a real window and physical input and
must be run by the operator before merge; a failed item is an implementation
failure to fix and rerun, not a waived checkbox. Run with the real game data
via plain `make run` (now boots through character selection) and
`make run floor=0` for the attic debug bypass.

| Route | Result | Observation |
|---|---|---|
| Plain `make run` enters selection before any PLAY frame | PENDING | — |
| Emily and Carnby each select/start once by mouse and once by keyboard | PENDING | — |
| Story starts by single click; Esc returns to portraits | PENDING | — |
| PLAY Escape opens the paused menu; Return, Configuration, and Quit work by mouse and keyboard | PENDING | — |
| Sticky Action works with one-finger sequential Space then direction | PENDING | — |
| Remapped key works immediately and after a full process restart | PENDING | — |
| Corrupt-load and forced/unwritable-save messages name the settings path and dismiss by mouse/keyboard without changing mode | PENDING | — |
| No held movement, activation, or sticky pulse replays after menu entry/exit | PENDING | — |
| Exactly one visible cursor appears in every shell/menu/PLAY mode; window close remains reachable | PENDING | — |

## Scope ruling

M4a1 proves the shell boundary only: character selection, the system menu,
remappable controls, sticky Action, settings persistence, and the settings
notice overlay. M4a2 (save/load rows in the stable three-row MAIN menu),
M4b (audio/sequences/title flow), and M4c (ending closure) are out of scope.
