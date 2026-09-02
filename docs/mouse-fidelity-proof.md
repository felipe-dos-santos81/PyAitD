# Mouse fidelity proof

Spec: `docs/superpowers/specs/2026-09-02-mouse-fidelity-design.md`
Plan: `docs/superpowers/plans/2026-09-02-mouse-fidelity.md`

## Automated gates

| Gate | Command | Result |
|---|---|---|
| Picking: ray-box, visibility, viewed-room depth, occlusion subset, snap budget | `make test-engine` | green — `539 passed, 1 skipped, 1140 deselected, 1 xfailed in 12.86s` (2026-09-02, `fc93f1c`) |
| Follow: cut dead zone, release and floor change clear it, arrival while settling | `make test-shell` | green — `476 passed, 1205 deselected, 26 warnings in 15.03s` (2026-09-02, `fc93f1c`) |
| Cursor: marker, preview, ring, dashed ring, defaults | `make test-shell` | green — `476 passed, 1205 deselected, 26 warnings in 15.03s` (2026-09-02, `fc93f1c`) |
| Contract unchanged | `make test-shell` | green — `476 passed, 1205 deselected, 26 warnings in 15.03s` (2026-09-02, `fc93f1c`) |
| Attic occlusion census | `make proof-mouse` | see below |

Full suite, `make test` (2026-09-02, `fc93f1c`):

```
1679 passed, 1 skipped, 1 xfailed, 26 warnings in 74.89s (0:01:14)
```

### Attic occlusion census (`make proof-mouse`)

```
floor 0 camera slot 0: 225 wall/furniture pixels no longer pick the floor behind them
floor 0 camera slot 1: 165 wall/furniture pixels no longer pick the floor behind them
floor 0 camera slot 2: 188 wall/furniture pixels no longer pick the floor behind them
floor 0 camera slot 3: 225 wall/furniture pixels no longer pick the floor behind them
floor 0 camera slot 4: 103 wall/furniture pixels no longer pick the floor behind them
```

## Windowed attestation

Run `make run --skip-intro` and play the attic. Fill in one row per hero.

| Hero | Wall pixel refuses (X cursor, hero stands) | Snap shows marker within the pointer's neighbourhood | Cut with still hand keeps heading | One-pixel jitter after cut does not redirect | Ring while held, dashed while settling | Attested by / date |
|---|---|---|---|---|---|---|
| Carnby | pending | pending | pending | pending | pending | |
| Emily | pending | pending | pending | pending | pending | |
