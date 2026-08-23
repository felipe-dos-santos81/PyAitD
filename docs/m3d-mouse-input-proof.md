# M3d mouse-input proof

**The manual section below is outstanding.** This document was written by an
agent with no display and no way to launch or play the game. Everything under
"Automated evidence" was actually run, in this environment, on this branch,
and the output shown is the real output of that run — not a transcription of
expected behavior. Everything under "Manual verification (not yet done)" is a
checklist for a human at a real display; none of it has been performed, and
no claim about how the game feels or plays should be inferred from this file
until that checklist is completed and this section is updated with real
observations.

## Automated evidence

### Cursor rendering (`render_cursor`)

`PyAitD/ui.py:render_cursor(frame, logical_pos, kind)` draws a walk/target/
blocked cursor onto a copy of the frame and never mutates its input. Covered
by `tests/test_ui_render.py`:

- `test_cursor_marks_the_frame_without_mutating_the_input`
- `test_cursor_kinds_differ`
- `test_cursor_outside_the_surface_is_a_no_op`

Command and real output:

```
$ SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_render.py -q
......                                                                   [100%]
6 passed in 0.12s
```

### Full test suite

```
$ SDL_VIDEODRIVER=dummy .venv/bin/pytest -q
.............................................................s.......... [ 23%]
........................................................................ [ 47%]
........................................................................ [ 70%]
........................................................................ [ 94%]
.................                                                        [100%]
304 passed, 1 skipped in 1.73s
```

(304 = the 301-passed/1-skipped baseline recorded at the start of this task,
plus the 3 new `render_cursor` tests.)

### `make prove` (M3a parse-all + headless boot)

```
$ make prove
.venv/bin/python -m pytest tests/test_prove_m3a.py -q
....                                                                     [100%]
4 passed in 0.17s
```

### `make prove-mouse` (navmesh coverage proof harness)

`tools/prove_mouse.py` builds the walkable navmesh for every room on every
floor (0-7) that at least one camera views, and reports the walkable cell
count per room. Real output, this run:

```
$ make prove-mouse
.venv/bin/python tools/prove_mouse.py "Alone in the Dark 1.app/Contents/Resources/game/INDARK"
floor 0 room  0: (151, 141) walkable 11120
floor 1 room  0: (34, 68) walkable 648
floor 1 room  1: (81, 25) walkable 1161
floor 1 room  2: (55, 46) walkable 970
floor 1 room  3: (30, 46) walkable 430
floor 1 room  4: (54, 59) walkable 1007
floor 1 room  5: (45, 46) walkable 975
floor 1 room  6: (11, 42) walkable 129
floor 1 room  7: (58, 112) walkable 3350
floor 2 room  0: (77, 120) walkable 3021
floor 2 room  1: (31, 205) walkable 4421
floor 2 room  2: (64, 103) walkable 2692
floor 2 room  3: (41, 50) walkable 751
floor 2 room  4: (92, 52) walkable 695
floor 2 room  5: (31, 30) walkable 332
floor 2 room  6: (39, 30) walkable 456
floor 2 room  7: (41, 41) walkable 716
floor 2 room  8: (40, 30) walkable 502
floor 2 room  9: (34, 11) walkable 352
floor 2 room 10: (41, 51) walkable 942
floor 3 room  0: (58, 26) walkable 1003
floor 3 room  1: (98, 50) walkable 3817
floor 3 room  2: (48, 87) walkable 2642
floor 3 room  3: (55, 99) walkable 3656
floor 3 room  4: (60, 76) walkable 1590
floor 3 room  5: (70, 75) walkable 2640
floor 3 room  6: no camera views it — skipped
floor 3 room  7: (24, 25) walkable 112
floor 3 room  8: (57, 78) walkable 1680
floor 3 room  9: (24, 54) walkable 276
floor 3 room 10: (25, 29) walkable 105
floor 3 room 11: (49, 49) walkable 1051
floor 3 room 12: (56, 100) walkable 2585
floor 3 room 13: (51, 45) walkable 1028
floor 3 room 14: no camera views it — skipped
floor 3 room 15: no camera views it — skipped
floor 4 room  0: (152, 101) walkable 9079
floor 4 room  1: no camera views it — skipped
floor 5 room  0: (58, 152) walkable 3757
floor 5 room  1: (117, 108) walkable 291
floor 5 room  2: (34, 118) walkable 64
floor 5 room  3: (45, 144) walkable 0  <- EMPTY (known: climbable-wall floor)
floor 5 room  4: (164, 157) walkable 292
floor 5 room  5: (137, 157) walkable 717
floor 5 room  6: (135, 197) walkable 2218
floor 5 room  7: (182, 135) walkable 10746
floor 5 room  8: (154, 184) walkable 8978
floor 5 room  9: (87, 188) walkable 732
floor 5 room 10: (164, 309) walkable 36500
floor 5 room 11: (81, 75) walkable 2282
floor 6 room  0: (178, 146) walkable 6928
floor 6 room  1: (137, 161) walkable 2495
floor 6 room  2: (170, 129) walkable 6000
floor 6 room  3: (118, 149) walkable 1406
floor 6 room  4: (197, 108) walkable 5227
floor 6 room  5: (147, 128) walkable 6381
floor 6 room  6: (281, 243) walkable 23446
floor 7 room  0: (77, 64) walkable 1796
floor 7 room  1: (184, 177) walkable 18257
floor 7 room  2: (21, 22) walkable 173

built 56 meshes, 4 rooms without cameras, 1 empty
```

Exit code: `0`.

Reading this output:

- 56 rooms built a mesh; the 4 rooms with no camera (floor 3 rooms 6, 14, 15
  and floor 4 room 1) were skipped, as expected — that is a fixed, structural
  property of the camera data, not something this task changes.
- Exactly one room reported EMPTY: floor 5 room 3. The plan carried forward
  from the spec expected EMPTY meshes on **both** floors 5 and 6 (type-3
  climbable-wall cover tiling their area with no `hard_col == 255` consumer
  yet). The actual run only produced one EMPTY room, on floor 5; every floor
  6 room built a non-trivial walkable count. This is reported as observed,
  not adjusted to match the earlier expectation — the harness's job is to
  report what it finds without failing on it, which it does either way.
  Floor 5 room 3's `walkable 0` is consistent with the documented boundary:
  the harness completes with exit code 0 and does not treat it as an error.

## Manual verification (not yet done)

None of the following has been performed. They require a human at a real
display running `make run` (mouse is the default input mode):

- [ ] Walk across the attic (floor 0) by left-clicking the floor; confirm the
      hero paths there without keyboard input.
- [ ] Left-click a foundable object (e.g. the oil lamp) and confirm the
      Take/Leave prompt names *that* object, not a different one.
- [ ] Press Tab to switch to the keyboard scheme and confirm arrow/WASD tank
      movement behaves exactly as before this change (unchanged pivot-then-
      walk keyboard feel).
- [ ] Press Tab again to switch back to mouse and confirm control returns
      cleanly (no stuck input, no stray nav intent).
- [ ] Observe and record the actual felt difference, if any, between mouse
      turn-while-walking and the old keyboard pivot-then-walk — this requires
      subjective human judgment during play and cannot be inferred from any
      automated test in this repository.
- [ ] Confirm the hover cursor changes shape/color over walkable floor,
      blocked floor, and an interactable object, and that it never appears
      while a modal (Found/Inventory/Reading/Picture) is open.
- [ ] Click across a room boundary (cross-room hop) and confirm the hero
      arrives in the correct neighbouring room.
