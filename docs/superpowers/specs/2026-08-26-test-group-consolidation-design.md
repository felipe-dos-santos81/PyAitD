# Test group consolidation — design

Date: 2026-08-26. Status: approved design.

## Goal

Replace nine hand-maintained `prove-*` Make targets with a small set of
capability-named `test-*` targets driven by pytest markers, so that a test's
group travels with the test instead of living in a Makefile recipe. Keep every
existing `prove-*` name working as an alias, and keep the milestone evidence
those names represent honest.

## What is wrong today

Measured on the tree at `4024b10`:

| Problem | Evidence |
|---|---|
| Two targets are near-duplicates | `prove-shell` ∩ `prove-mouse-accessibility` = 8 shared files, of 12 and 9 |
| One is a strict subset of both | `prove-mouse-only` runs only `tests/test_mouse_only.py` |
| Env vars are inconsistent | `test` sets neither SDL var; `prove-m3b` and `prove-intro` set `SDL_VIDEODRIVER` only; three targets set video + audio |
| Grouping lives in the Makefile | `prove-shell` names 12 file paths in its recipe; adding a test to the group means editing the Makefile |
| Coverage is narrow | only **15 of 72** test files appear in any `prove-*` target; a new file joins no group and nothing notices |
| Two kinds share one prefix | five targets are pytest subsets; `prove-mouse`, `prove-combat`, `prove-graphics` run tools that emit artifacts and need GL and game data; `prove-intro` does both |

`AGENTS.md` states that any test touching rendering or pygame needs
`SDL_VIDEODRIVER=dummy`. `make test` sets it for nothing and passes only
because some test files call `os.environ.setdefault` themselves. That is a
latent inconsistency this design closes.

## Why markers, and why not package imports

Package imports cannot be the axis. Only 15 of 72 files import a single
`PyAitD` package; the largest cluster (20 files) imports `engine` and `games`
together, and 6 import all four. A file's marker is therefore a judgment
about what the test asserts, not a mechanical derivation — and that judgment
is the main cost of this work.

## Marker taxonomy

Exactly one **subject** marker per test file, declared as a module-level
`pytestmark` immediately after the imports:

| marker | covers |
|---|---|
| `engine` | simulation, LIFE VM, formats, actors, animation, tracks, collision, navmesh, picking, and the AITD1 opcode handlers |
| `render` | `FrameDescription` → pixels: scene description, geometry, both backends, asset resolution, override export and check |
| `shell` | `app/`: window, event pump, settings schema and persistence, CLI, UI screens and modals |
| `tools` | standalone scripts under `tools/` |
| `meta` | the repo's own rules rather than its behaviour: `test_layering.py`'s package-import scan and this milestone's group-enforcement test |

`meta` exists because a test that asserts a *convention* has no layer whose
behaviour it exercises; without it, `test_layering.py` would have to be
mislabelled as one of the other four.

Plus one optional cross-cutting marker:

- `journey` — the test drives the real `run()` event pump, or runs a long
  real-data simulation. Orthogonal to subject: a journey file also carries
  its subject marker.

**Tie-break rule**, binding for the assignment pass: mark by the layer whose
behaviour the test asserts, not by what it imports. A test that drives `run()`
and asserts routing is `shell`; one that drives `run()` and asserts world or
actor state is `engine`.

Markers are registered in `pyproject.toml` under
`[tool.pytest.ini_options] markers`, and `--strict-markers` is added to
`addopts` so an unregistered or misspelled marker fails the run instead of
silently selecting nothing.

## Targets

Pytest gates, all sharing one headless environment:

```make
HEADLESS = SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy
```

| target | runs |
|---|---|
| `test` | the whole suite, headless |
| `test-engine` | `-m engine` |
| `test-render` | `-m render` |
| `test-shell` | `-m shell` |
| `test-tools` | `-m tools` |
| `test-meta` | `-m meta` |
| `test-journey` | `-m journey` |

Artifact proofs, renamed so the prefix says they need GL and game data:

| target | was |
|---|---|
| `proof-mouse` | `prove-mouse` |
| `proof-combat` | `prove-combat` |
| `proof-graphics` | `prove-graphics` |
| `proof-intro` | `prove-intro` (keeps its pytest gate + tool pair) |

Every `prove-*` name survives as an alias delegating to the new target, so
the eight proof documents that cite them keep working unedited:
`prove`, `prove-m3b`, `prove-shell`, `prove-mouse-only`,
`prove-mouse-accessibility`, `prove-mouse`, `prove-combat`, `prove-graphics`,
`prove-intro`.

Alias marker expressions are restricted to a single marker or `or`-joined
single markers, so the pinning test can evaluate them by parsing `pytestmark`
without a subprocess.

## Enforcement

New `tests/test_test_groups.py`, marked `meta`:

1. **Exhaustive and disjoint.** Every `tests/test_*.py` carries exactly one
   subject marker; the five subjects' file sets union to the full set and
   pairwise intersect to empty. `conftest.py`, `purity.py` and `stub_floor.py`
   are excluded by name — they define no tests.
2. **Registered.** Every marker used appears in `pyproject.toml`'s `markers`
   list, and vice versa — no dead registrations.
3. **Alias coverage is a superset of history.** Each legacy alias's historical
   file list is frozen as literal data in this test, with a comment stating it
   is historical and must not be edited to make a failure go away. The test
   asserts the alias's marker expression selects every file it historically
   ran. This is what keeps the proof documents' evidence claims true.

The pinning in (3) only covers the 15 files currently named by a gate. The
other 57 files' subject markers are checked by nothing but review — that is a
known and accepted limitation of this design, recorded here so nobody assumes
otherwise.

## Testing

- The three enforcement properties above.
- Suite-invariance: the marker pass must leave the collected test count and
  every outcome unchanged. `889 passed`-equivalent before and after is the
  acceptance check; the count is re-measured at implementation time rather
  than pinned here, because unrelated work may land first.
- `make test-engine`, `test-render`, `test-shell`, `test-tools`, `test-meta`
  together collect the same set as `make test`.
- Each renamed `proof-*` target and each `prove-*` alias runs and exits zero
  on a machine with GL and game data.

## Files

| file | change |
|---|---|
| `tests/test_*.py` (72) | one `pytestmark` line each |
| `tests/test_test_groups.py` | new: the three enforcement properties |
| `pyproject.toml` | register markers; add `--strict-markers` |
| `Makefile` | `HEADLESS` variable; six `test-*` targets; four `proof-*` targets; nine `prove-*` aliases; `.PHONY` updated |
| `AGENTS.md` | the Commands table gains the `test-*` group targets and the `proof-*` rename; states the marker rule and the tie-break |
| `CONTEXT.md` | a short section naming the marker taxonomy and pointing at the enforcement test |

Proof documents are deliberately not edited: the aliases hold, so their cited
commands stay valid.

## Non-goals

- No test file is moved, renamed, split, or rewritten. This changes grouping
  only.
- No new coverage. Files that no gate ran before still are not run by any
  gate other than `make test`; they simply now belong to a named group.
- No CI configuration is introduced.
- `prove-*` aliases are not deprecated or warned about in this milestone.
