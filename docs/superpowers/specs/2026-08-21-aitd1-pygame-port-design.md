# Alone in the Dark 1 — PyGame Port: Design

Date: 2026-08-21
Status: Approved (design); M1 spec is this document's actionable scope
Reference implementation: FITD (Free in the Dark), `/Users/felipe.dos.santos/code/theirs/FITD`, GPLv2

## Goal

A windowed, single-player, Apple Silicon port of Alone in the Dark 1 (AITD1) in Python,
driven entirely by the original game data files. Definition of done: the full game is
playable start to end — all floors, LIFE scripts, inventory, save/load, menus, audio.

Fidelity target: **modernized**. GL rendering, upscaled visuals, modern input. Not a
pixel-perfect DOS reproduction.

## Non-goals

- AITD2/AITD3/Jack in the Dark/Timegate support.
- Editor tooling, mod support, networking.
- Mobile/Windows/Linux portability work (Apple Silicon arm64 is the only target;
  portable code where free, but no extra effort).

## Context discovered

- The original AITD1 data ships inside `Alone in the Dark 1.app` at
  `Contents/Resources/game/INDARK/` (and `JACK/`). FITD-compatible `.PAK` files:
  `ETAGE##.PAK` (floors/rooms), `CAMERA##.PAK`, `LISTBODY.PAK`, `LISTANIM.PAK`,
  `LISTLIFE.PAK`, `LISTTRAK.PAK`, `ITD_RESS.PAK` (UI/images/font/text),
  `VARS.ITD`, `OBJETS.ITD`, `DEFINES.ITD`, `PRIORITY.ITD`, `LISTMUS.PAK`, `LISTSAMP.PAK`.
- FITD parses these formats directly; it is the authoritative format reference.
  Key FITD sources: `pak.cpp` (archives), `hqr.cpp` (body/anim parsing, cache),
  `room.cpp` (ETAGE/camera structures), `life.cpp` + `life.h` (~100-opcode script VM),
  `track.cpp` (movement/collision tracks), `rendererBGFX.cpp` (render model).
- Rendering model of the original: fixed-camera pre-rendered 2D backgrounds
  (320x200 palette-indexed images) with 3D polygon actors drawn over them.
  Camera switching is zone-driven.
- PAK format: u32 offset table at file start; per-entry: u32 additionalDescriptorSize,
  then pakInfo {u32 discSize, u32 uncompressedSize, u8 compressionFlag, u8 info5,
  u16 nameOffset}, then entry data. compressionFlag: 0=raw, 1=RLE "explode" (needs
  porting from FITD `unpack.cpp`), 4=zlib (stdlib).
- Body format: flags, ZV bounds, scratch buffer, vertices (s16 triplets), animation
  groups (rotation hierarchy), primitives (poly/line/point/sphere + textured variants;
  vertex indices stored *6).
- Anim format: frames with timestamp, root translation step, per-group rotation deltas
  (two variants: with/without optim data; detected from buffer size).
- Room (ETAGE) format: per-room offset table; room def = offsets to camera-cover zones,
  hard collision, world position, camera index table. Cameras hold viewed-room tables
  and zone polys.
- FITD is GPLv2. This project reads the same formats and derives behavior from it,
  so it ships under GPLv2.

## Technology stack

| Concern | Choice | Why |
|---|---|---|
| Window/input/audio | pygame-ce | SDL2 backend, arm64 wheels, active maintenance |
| Rendering | ModernGL over pygame GL context | Clean API, depth buffer, meshes + textured quads, works on macOS (GL 4.1) |
| Math/buffer handling | numpy | Transforms, vertex buffers, image decoding |
| zlib entries | stdlib `zlib` | Free |
| Tests | stdlib `unittest` | No framework needed |
| Python | 3.12 | Installed; arm64 |

Original game data is read in place from the `.app` bundle; path configurable via
`--data`, default `Alone in the Dark 1.app/Contents/Resources/game/INDARK`.

## Architecture

Package `maitd/`, one concern per module, dependencies flow one direction:

```
pak -> formats -> cache      (pure I/O + parsing; no game state)
        |
game <-> world <- life       (state: vars, actors, rooms, script VM)
        |
render / ui / audio          (output only)
        ^
__main__ (fixed 50 Hz loop: input -> life/world tick -> render)
```

### Modules

- `pak.py` — PAK archive reader: offset table, pakInfo header, compression dispatch
  (raw / RLE explode / zlib). Returns `bytes` per entry index.
- `formats.py` — binary parsers producing typed records (dataclasses): body, anim,
  room, camera, zones, indexed image + VGA palette (6-bit -> 8-bit), `.ITD` text/vars.
- `cache.py` — small LRU cache over pak entries (Python-replacement of FITD's HQR
  bookkeeping; file reads are fast, cache only avoids re-parse).
- `life.py` — LIFE script VM: table-driven opcode dispatch (AITD1 opcode table from
  FITD `AITD1LifeMacroTable`), stack-less bytecode interpreter with program counter,
  operates on world/game state via injected interfaces (no file I/O in VM).
- `world.py` — actors, rooms, camera selection by zones, movement tracks, collision
  (hard col + sce zones), world/room coordinate conversion (room offsets * 10).
- `game.py` — session state: VARS, inventory, floor/room loading orchestration,
  game over/restart, save/load (M4).
- `inputmap.py` — pygame events -> game verbs (movement, action, inventory, menu).
- `render/` — ModernGL context on pygame window; background textured quad
  (palette-decoded image -> RGBA texture, upscaled); actor meshes (per-body VBOs,
  per-anim joint transforms computed in numpy); depth buffer; camera matrix from
  room camera params.
- `audio.py` — M4: pygame.mixer sample playback; FM-music path deferred (see risks).
- `ui.py` — M4: menus, text boxes, inventory screens from `ITD_RESS` images.
- `__main__.py` — argparse (`--data`, `--floor` debug), fixed-timestep 50 Hz loop,
  frame cap for render.

### Invariants

- Formats layer is pure and side-effect free; every parser is unit-testable against
  extracted real entries.
- VM never touches disk or rendering; all effects via world/game interfaces.
- Game logic ticks at fixed 50 Hz regardless of render FPS (original timing model).
- All offsets/endianness handled in `pak.py`/`formats.py` only; rest of code sees
  native Python types.

## Milestones

Each milestone gets its own implementation plan; M1 is the scope committed now.

- **M1 — data layer + static room rendering.** `pak.py` (all 3 compression modes),
  `formats.py` for room/camera/image+palette (body/anim parsers included for the
  golden tests but not rendered yet), `cache.py`, ModernGL renderer drawing each
  camera's background image upscaled (linear filtering) in a window; `--floor N`
  debug entry; debug keys cycle room/camera.
  Proof: every room of floor 0 renders its correct background for all its cameras.
- **M2 — actors.** Body meshes + anim skinning in GL, actor spawning from room data,
  zone-driven camera switching, walking + hard collision.
- **M3 — LIFE VM + gameplay.** Full AITD1 opcode set, VARS, inventory, combat,
  death/game-over, floor transitions -> playable start to end.
- **M4 — shell & polish.** Menus, text/dialogs, save/load, samples + music, CRI
  videos, config, packaging.

## Error handling

- Missing/corrupt data files: fail fast with named file and entry index.
- Unknown compression flag / unknown opcode / unknown primitive type: hard error
  with context (mirrors FITD `assert(0)`), never silent skip.
- Renderer resource failures surface as exceptions at init, not mid-frame.

## Testing

- Golden tests: assert exact decoded sizes/fields for a pinned set of real PAK
  entries (body vertex counts, anim frame counts, room counts per floor, image dims).
  Expectations recorded once from real data, then fixed.
- VM tests: synthetic bytecode programs exercising control flow + var ops.
- No mocks for formats; test against actual game data files.

## Assumptions (agreed)

- GPLv2 (FITD-derived).
- Logic tick 50 Hz; render uncapped/vsync.
- Controls: arrows/WASD movement, Enter/Space action, Esc menu; remappable later.
- Data path defaults to the local `.app` bundle; `--data` overrides.
- FM-music emulation deferred to M4; likely approach = offline conversion of original
  tracks to playable audio, or mixer-only samples. Flagged as risk, decided at M4.

## Risks

- RLE "explode" decompression is custom; needs byte-exact port from FITD
  `unpack.cpp` (validate by decoding known entries and comparing sizes).
- macOS OpenGL deprecated but functional (4.1 profile sufficient).
- LIFE VM completeness is the main gameplay risk; AITD1 opcode table exists in FITD
  (`AITD1LifeMacroTable`), mitigating.
- Original data remains owned by user; project reads it, never redistributes it.
