# NOTE: Table indices below were corrected after review against AITD1.cpp:30-119.
# The table has 87 entries (0..86); dead = 27 LM_CAMERA, 57 LM_STOP_BETA, 61 LM_DO_NORMAL_ZV, 69 LM_SPEED.
# Control flow: SWITCH=25, CASE=26, MULTI_CASE=29. VAR/INC/DEC/ADD/SUB = 19-23 (real handlers).
# GiveDistance2D is Manhattan with 0x7D00 saturation, not euclidean.
# The plan doc (2026-08-22-m3a-life-vm-core-world.md) is authoritative where it disagrees with this doc.
# FITD LIFE VM — Complete Opcode Semantics (AITD1)

Sources (all line numbers from `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib`):
- `life.cpp` — `processLife()` dispatch (453–2520)
- `life.h` — `enumLifeMacro` enum (4–133)
- `AITD1.cpp` — `AITD1KnownCVars` (9–28), `AITD1LifeMacroTable` (30–119)
- `evalVar.cpp` — `evalVar()` AITD1 path (148–550), `evalVar2()` (552–1005, JACK+)
- `common.h` — `enumCVars` (24–87), `TYPE_MASK`/`ANIM_*` (110–115)
- `main.cpp` — `getCVarsIdx` (36–56), CVars sizing (4168–4217)
- `mainLoop.cpp` — life execution gate (155–230)
- `vars.cpp` — `readNextArgument` (172+)

Byte order: all life data read as little-endian s16 via raw `*(s16*)ptr` (or `READ_LE_S16`).

---

## 1. processLife loop structure

```c
void processLife(int lifeNum, bool callFoundLife)      // life.cpp:453
{
    int exitLife = 0;
    int var_6;
    int switchVal = 0;

    currentLifeActorIdx = currentProcessedActorIdx;     // save "life owner" actor
    currentLifeActorPtr = currentProcessedActorPtr;
    currentLifeNum = lifeNum;
    currentLifePtr = HQR_Get(listLife, lifeNum);        // raw script buffer

    while (!exitLife)
    {
        s16 currentOpcode;

        var_6 = -1;                                     // reset "switched actor" marker
        currentOpcode = *(s16*)(currentLifePtr);        // fetch
        currentLifePtr += 2;

        if (currentOpcode & 0x8000)                     // high bit = actor switch
        {
            var_6 = *(s16*)(currentLifePtr);            // world-object index arg
            currentLifePtr += 2;

            currentProcessedActorIdx = ListWorldObjets[var_6].objIndex;

            if (currentProcessedActorIdx != -1)         // object live in floor
            {
                currentProcessedActorPtr = &ListObjets[currentProcessedActorIdx];
                goto processOpcode;                     // normal dispatch on switched actor
            }
            else                                        // object not in floor:
            {                                           // reduced sub-dispatch (object-table ops only)
                opcodeLocated = AITD1LifeMacroTable[currentOpcode & 0x7FFF];
                switch (opcodeLocated)
                {
                    // ONLY: LM_BODY, LM_BODY_RESET, LM_TYPE,
                    //       LM_ANIM_ONCE, LM_ANIM_REPEAT, LM_ANIM_ALL_ONCE, LM_ANIM_RESET,
                    //       LM_MOVE, LM_ANGLE, LM_STAGE, LM_TEST_COL,
                    //       LM_LIFE, LM_LIFE_MODE,
                    //       LM_FOUND_NAME, LM_FOUND_BODY, LM_FOUND_FLAG, LM_FOUND_WEIGHT,
                    //       LM_START_CHRONO  (no-op here)
                    // everything else: printf + assert(0)  (life.cpp:712)
                }
            }
        }
        else
        {
        processOpcode:
            opcodeLocated = AITD1LifeMacroTable[currentOpcode & 0x7FFF];   // opcode 0..87 → enum
            switch (opcodeLocated) { /* full handlers, see table below */ }
        }

        if (var_6 != -1)                                // actor was switched this iteration:
        {
            currentProcessedActorIdx = currentLifeActorIdx;   // restore owner actor
            currentProcessedActorPtr = currentLifeActorPtr;
        }
    }

    currentLifeNum = -1;
}
```

Key structural facts:

- **Opcode = s16, little-endian.** Bit 0x8000 (sign bit of s16) is the *actor-switch* flag, NOT part of opcode. Dispatch index = `opcode & 0x7FFF`. AITD1 opcodes are 0..87; AITD1 table lookup maps opcode number → `enumLifeMacro` name (opcode == enum value for 0..87, but dispatch always goes through the table, never the raw value).
- **Two dispatch paths:**
  - Normal path (`else`, or via `goto processOpcode`): full switch over enum. Handlers use `currentProcessedActorPtr`.
  - Not-in-floor path (`objIndex == -1`): switch limited to world-object-field ops (`ListWorldObjets[var_6].x = ...`). Raw s16 args there (no evalVar). `LM_BODY` there uses `evalVar()` (the one exception).
- **No return stack, no PC save.** `currentLifePtr` is a plain `char*` walking the buffer. Loops/if are bytecode jumps:
  - `LM_GOTO`: `currentLifePtr += readNextArgument("Offset") * 2` — offset in *s16 units*, signed.
  - `LM_IF_*` / `LM_CASE` / `LM_MULTI_CASE`: if condition fails, read jump s16, `currentLifePtr += jump*2`; if condition true, `currentLifePtr += 2` (skip jump word). Jump measured from *after* the jump word itself.
  - `LM_RETURN` / `LM_END`: `exitLife = 1` — same behavior, both terminate script (FITD unifies them).
- **LM_SWITCH/CASE/MULTI_CASE:** `switchVal` is a C local in processLife. `LM_SWITCH` sets `switchVal = evalVar()`. `LM_CASE` compares `readNextArgument()` (raw s16) against switchVal, branch as above. `LM_MULTI_CASE`: reads count s16, then count value s16s, matches if *any* equals switchVal, then same jump-s16 branching.
- **LM_START_CHRONO** (full path): `startChrono(&currentProcessedActorPtr->CHRONO)`. In not-in-floor path: literal no-op.
- **LM_LIFE:** sets `currentProcessedActorPtr->life = newLife`. No call happens inside the VM. The call site is mainLoop: each main-loop iteration, for each actor, if `life != -1 && lifeMode != -1` (AITD1/JACK gate, mainLoop.cpp:166–174) or `lifeMode & 3 && !(lifeMode & 4)` (AITD2+ gate) → `processLife(actor->life, false)`. So "calling a life" = assigning `life`, effective next tick.
- **Re-entry guard / state save:** `currentLifeActorIdx/Ptr` saved at entry (owner), restored after each 0x8000 iteration; `currentLifeNum` set at entry, reset to -1 at exit. `processLife(foundLife, true)` from `main.cpp:236` (FoundObjet path) — `callFoundLife=true` changes only LM_FOUND behavior (see below). Nested re-entry not guarded: a handler that ends up running another processLife (e.g. LM_CALL_INVENTORY → FoundObjet → processLife) would clobber the saved state; FITD relies on call sites being sequential.
- **evalVar targets `currentLifeActorPtr`** (the life owner), never `currentProcessedActorPtr` — 0x8000-switched handlers therefore must read actor fields with raw args or explicit world-obj table ops; `evalVar` still reads owner state.

---

## 2. Opcode table — AITD1LifeMacroTable (88 entries, index = opcode)

Enum value == opcode number for 0..87 (`life.h`). Entries `LM_CAMERA`, `LM_STOP_BETA`, `LM_DO_NORMAL_ZV`, `LM_SPEED` appear in the AITD1 table but have **no dispatch case** in life.cpp → `default: assert(0)` (life.cpp:2496). They are dead in AITD1 data.

### Control flow

| op | macro (enum value) | args consumed | description |
|---|---|---|---|
| 4 | LM_IF_EGAL (4) | evalVar, evalVar, jump s16 | `a==b` ? skip jump word : `ptr += jump*2` |
| 5 | LM_IF_DIFFERENT (5) | evalVar, evalVar, jump s16 | `a!=b` ? continue : jump |
| 6 | LM_IF_SUP_EGAL (6) | evalVar, evalVar, jump s16 | `a>=b` ? continue : jump |
| 7 | LM_IF_SUP (7) | evalVar, evalVar, jump s16 | `a>b` ? continue : jump |
| 8 | LM_IF_INF_EGAL (8) | evalVar, evalVar, jump s16 | `a<=b` ? continue : jump |
| 9 | LM_IF_INF (9) | evalVar, evalVar, jump s16 | `a<b` ? continue : jump |
| 10 | LM_GOTO (10) | raw s16 offset | `ptr += offset*2` (s16 units) |
| 11 | LM_RETURN (11) | none | exitLife = 1 |
| 12 | LM_END (12) | none | exitLife = 1 (identical to RETURN) |
| 26 | LM_SWITCH (26) | evalVar | switchVal = value |
| 27 | LM_CASE (27) | raw s16 case, jump s16 | case==switchVal ? skip jump : jump |
| 30 | LM_MULTI_CASE (30) | raw s16 count, count×raw s16, jump s16 | any value==switchVal ? skip jump : jump |

### Actor state / body / anim

| op | macro | args | description |
|---|---|---|---|
| 0 | LM_DO_MOVE (0) | none | `processTrack()` — advance track move one step |
| 1 | LM_ANIM_ONCE (1) | raw s16 anim, raw s16 flags | `InitAnim(anim, 0, flags)`; anim==-1 → ANIM=-1,newAnim=-2 |
| 2 | LM_ANIM_ALL_ONCE (2) | raw s16 anim, raw s16 flags | `InitAnim(anim, 2, flags)` |
| 3 | LM_BODY (3) | evalVar | set body: world obj `.body`, actor `bodyNum`, `SetInterAnimObjet(frame, anim, body)` (non-animated → FlagInitView=1) |
| 13 | LM_ANIM_REPEAT (13) | raw s16 anim | `InitAnim(anim, 1, -1)` |
| 14 | LM_ANIM_MOVE (14) | 7×raw s16 (stand, walk, run, stop, backward, turnRight, turnLeft) | `animMove(...)` — picks anim by `speed`/`direction` |
| 15 | LM_MOVE (15) | raw s16 trackMode, raw s16 trackNumber | `InitDeplacement(mode, number)` |
| 16 | LM_HIT (16) | raw s16 anim, raw s16 startFrame, raw s16 groupNumber, raw s16 hitBoxSize, evalVar hitForce, raw s16 nextAnim | `hit(...)` — sets animActionType=... via hit() (melee action) |
| 25 | LM_LIFE_MODE (25) | raw s16 | set `lifeMode` if different (AITD1 compares full value) |
| 31 | LM_FOUND (31) | raw s16 objectId | AITD1: `FoundObjet(id, 1)`; else `FoundObjet(id, callFoundLife?2:1)` |
| 32 | LM_LIFE (32) | raw s16 newLife | `actor->life = newLife` (life switch next tick) |
| 33 | LM_DELETE (33) | raw s16 objectId (AITD1; AITD3+ evalVar) | `deleteObject(id)`; if foundBody != -1: AITD1 `foundFlag &= ~0x8000`, then `foundFlag |= 0x4000` |
| 34 | LM_TAKE (34) | raw s16 objectId (AITD1; TIMEGATE: evalVar+3 raw) | `take(id)` — pick up object |
| 35 | LM_IN_HAND (35) | raw s16 (AITD1; JACK+... evalVar) | `inHandTable[currentInventory] = value` |
| 36 | LM_READ (36) | raw s16 a, raw s16 b, +1 raw s16 SKIPPED (AITD1 extra word) | fade, `readBook(b+1, a)`, FlagInitView=2 |
| 37 | LM_ANIM_SAMPLE (37) | evalVar sampleId, raw s16 anim, raw s16 frame | if END_FRAME!=0 && ANIM==anim && frame==frame → `playSound(sampleId)` |
| 38 | LM_SPECIAL (38) | raw s16 type | 0: `InitSpecialObjet(0,...)` evaporate at actor pos+zv; 1: flow from `HIT_BY` actor hotPoint; 4: cigar smoke (only 0/1/4 switch cases) |
| 39 | LM_DO_REAL_ZV (39) | none | `doRealZv(actor)` — recompute ZV from body |
| 40 | LM_SAMPLE (40) | evalVar sampleId (AITD1; TIMEGATE evalVar+raw; JACK evalVar) | `playSound(sampleId)` |
| 41 | LM_TYPE (41) | raw s16 | mask `AF_MASK` on `objectType`: `objectType = (objectType & ~AF_MASK) + (arg & AF_MASK)` (not-in-floor path: `TYPE_MASK` on flags) |
| 42 | LM_GAME_OVER (42) | none | fadeMusic + spin 120 chrono ticks, `FlagGameOver=1`, exitLife=1 |
| 43 | LM_MANUAL_ROT (43) | none | `GereManualRot(AITD1?240:90)` |
| 44 | LM_RND_FREQ (44) | 1 raw s16 (ignored) | skip 2 bytes, nothing else |
| 45 | LM_MUSIC (45) | raw s16 musicIdx | `playMusic(idx)` |
| 46 | LM_SET_BETA (46) | raw s16 beta, raw s16 speed | init/update rotate interpolation towards beta |
| 47 | LM_DO_ROT_ZV (47) | none | `getZvRot(body, zv, alpha,beta,gamma)` + room offset |
| 48 | LM_STAGE (48) | 5×raw s16 (stage, room, x, y, z) | `setStage(...)`; camera target → FlagChangeEtage/FlagChangeSalle, else world coords adjusted |
| 49 | LM_FOUND_NAME (49) | raw s16 | world obj `.foundName = v` |
| 50 | LM_FOUND_FLAG (50) | raw s16 | `foundFlag = (foundFlag & 0xE000) | v` |
| 51 | LM_FOUND_LIFE (51) | raw s16 | world obj `.foundLife = v` |
| 52 | LM_CAMERA_TARGET (52) | raw s16 target | set `currentWorldTarget`, switch camera/room; AITD1: only room change flag; else: stage-change handling |
| 53 | LM_DROP (53) | evalVar worldIdx, raw s16 source | `drop(worldIdx, source)` → PutAtObjet |
| 54 | LM_FIRE (54) | AITD1: 6×raw s16 (anim, frame, emitPoint, zvSize, force, nextAnim) | `fire(...)` sets animActionType=4; non-AITD1: 7 args with evalVar anim + extra emitModel |
| 55 | LM_TEST_COL (55) | raw s16 | set/clear `dynFlags & 1` |
| 56 | LM_FOUND_BODY (56) | raw s16 | world obj `.foundBody = v` |
| 57 | LM_SET_ALPHA (57) | raw s16 alpha, raw s16 speed | rotate interpolation towards alpha |
| 58 | LM_STOP_BETA (58) | — | **no handler — assert(0)** |
| 59 | LM_DO_MAX_ZV (59) | none | `getZvMax(body, zv)` + room offset |
| 60 | LM_PUT (60) | 9×raw s16 (idx, x, y, z, room, stage, alpha, beta, gamma) | `put(...)` — place object, foundFlag |= 0x4000, remove from inventory |
| 61 | LM_C_VAR (61) | raw s16 idx, evalVar value | `CVars[idx] = value` (raw index!) |
| 62 | LM_DO_NORMAL_ZV (62) | — | **no handler — assert(0)** |
| 63 | LM_DO_CARRE_ZV (63) | none | `getZvCube(body, zv)` + room offset |
| 64 | LM_SAMPLE_THEN (64) | AITD1: evalVar, evalVar | `playSound(a)`, `nextSample = b`; non-AITD1: raw s16 pair (JACK: evalVar pair) |
| 65 | LM_LIGHT (65) | raw s16 | `lightOff = 2 - (v<<1)`; skipped if AITD1 && CVars[KILLED_SORCERER]!=0 |
| 66 | LM_SHAKING (66) | 1 raw s16 (ignored) | stub: skip 2 bytes |
| 67 | LM_INVENTORY (67) | raw s16 | `statusScreenAllowed = v` |
| 68 | LM_FOUND_WEIGHT (68) | raw s16 | world obj `.positionInTrack = v` (weight) |
| 69 | LM_UP_COOR_Y (69) | none | `InitRealValue(0, -2000, -1, &YHandler)` — jump/rise move |
| 70 | LM_SPEED (70) | — | **no handler — assert(0)** |
| 71 | LM_PUT_AT (71) | raw s16 obj1, raw s16 obj2 | `PutAtObjet(obj1, obj2)` |
| 72 | LM_DEF_ZV (72) | 6×raw s16 | zv = room + step + args (x1,x2,y1,y2,z1,z2) |
| 73 | LM_HIT_OBJECT (73) | raw s16 flags, raw s16 force | animActionType=8, animActionParam=flags, hitForce=force, hotPointID=-1 |
| 74 | LM_GET_HARD_CLIP (74) | none | `getHardClip()` — room collision box → global hardClip |
| 75 | LM_ANGLE (75) | 3×raw s16 (alpha, beta, gamma) | set angles directly |
| 76 | LM_REP_SAMPLE (76) | AITD1: evalVar, +1 raw s16 skipped | stub: nothing played, args consumed |
| 77 | LM_THROW (77) | 7×raw s16 (anim, frame, arg4, objToThrow, rotated, force, nextAnim) | `throwObj(...)` — animActionType=6; foundFlag |= 0x1000 |
| 78 | LM_WATER (78) | 1 raw s16 (ignored) | stub: skip 2 bytes |
| 79 | LM_PICTURE (79) | raw s16 pictureIndex, raw s16 delay, raw s16 sampleId (AITD1; TIMEGATE adds evalVar+raw) | blocking: LoadPak+blit+playSound, wait delay/key/Click; FlagInitView=1 |
| 80 | LM_STOP_SAMPLE (80) | none (TIMEGATE: 1 raw) | stub: nothing |
| 81 | LM_NEXT_MUSIC (81) | raw s16 idx | currentMusic==-1 ? playMusic(idx) : nextMusic=idx |
| 82 | LM_FADE_MUSIC (82) | raw s16 idx | currentMusic!=-1 ? fade + nextMusic=idx : playMusic(idx) |
| 83 | LM_STOP_HIT_OBJECT (83) | none | if animActionType==8 → clear action |
| 84 | LM_COPY_ANGLE (84) | raw s16 object | copy alpha/beta/gamma from world obj or its live actor |
| 85 | LM_END_SEQUENCE (85) | none | stub: printf only |
| 86 | LM_SAMPLE_THEN_REPEAT (86) | evalVar, evalVar | `playSound(a)`, `nextSample = b | 0x4000` |
| 87 | LM_WAIT_GAME_OVER (87) | none | wait for key/JoyD/Click transitions, FlagGameOver=1, exit=1. **Bug**: second wait is `while (!key && !JoyD && Click)` — Click NOT negated → busy-loop-until-click semantics broken vs original |

### Dispatch cases absent from AITD1 table (present in life.cpp, reachable only via AITD2+/JACK/TIMEGATE tables)

LM_BODY_RESET (104), LM_ANIM_RESET (97), LM_ANIM_HYBRIDE_ONCE (100), LM_ANIM_HYBRIDE_REPEAT (101), LM_FIRE_UP_DOWN (114, AITD3: evalVar+skip12+evalVar), LM_RESET_MOVE_MANUAL (98), LM_CONTINUE_TRACK (96), LM_STAGE_LIFE (95), LM_DEF_ABS_ZV (111), LM_READ_ON_PICTURE (113), LM_PLAY_SEQUENCE (107), LM_DEF_SEQUENCE_SAMPLE (112), LM_PROTECT (110), LM_SET_INVENTORY (106), LM_SET_GROUND (109), LM_2D_ANIM_SAMPLE (108), LM_CALL_INVENTORY (103), LM_MODIF_C_VAR (102), LM_DEL_INVENTORY (105 — enum only, no case anywhere), LM_GET_MATRICE (94 — enum only, no case), LM_DO_ROT_CLUT / LM_START_FADE_IN_MUSIC_LOOP (TIMEGATE asserts).

---

## 3. evalVar — variable encoding (AITD1 path, evalVar.cpp:148)

`s16` tagged value. `evalVar` reads tag, then maybe payload:

| tag (s16) | meaning | payload |
|---|---|---|
| -1 | immediate constant | next s16 returned as-is |
| 0 | script variable `vars[idx]` | next s16 = idx |
| 1..0x7FFF | actor property (tag-1 = property code) | depends on code |
| 0x8000+ | actor property of *another* object | next s16 = world-object idx, then property code |

0x8000 case: `actorIdx = ListWorldObjets[obj].objIndex`. If -1 (not in floor): only property 0x1F → `ListWorldObjets[obj].room`, 0x26 → `.stage` allowed; else assert. Otherwise use `ListObjets[actorIdx]`.

Property codes (after tag-1, 0-indexed switch), owner = `currentLifeActorPtr`:

| code | returns | extra payload |
|---|---|---|
| 0x00 | `COL[0]` → world index of first collided actor, -1 if none | — |
| 0x01 | `HARD_DEC` | — |
| 0x02 | `HARD_COL` | — |
| 0x03 | `HIT` → world idx or -1 | — |
| 0x04 | `HIT_BY` → world idx or -1 | — |
| 0x05 | `ANIM` | — |
| 0x06 | `flagEndAnim` | — |
| 0x07 | `frame` | — |
| 0x08 | `END_FRAME` | — |
| 0x09 | `bodyNum` | — |
| 0x0A | `MARK` | — |
| 0x0B | `trackNumber` | — |
| 0x0C | `evalChrono(CHRONO)/60` | — |
| 0x0D | `evalChrono(ROOM_CHRONO)/60` | — |
| 0x0E | DIST: Manhattan `calcDist` to object; 32000 if object not in floor | +1 s16 world idx |
| 0x0F | `COL_BY` → world idx or -1 | — |
| 0x10 | found test: `foundFlag & 0x8000 ? 1 : 0` | +1 evalVar (nested!) world idx |
| 0x11 | global `action` | — |
| 0x12 | POSREL: `getPosRel(actor, obj)` 8-direction table | +1 s16 world idx |
| 0x13 | joystick: `localJoyD` → 4/8/1/2 (first set) else 0 | — |
| 0x14 | `localClick` | — |
| 0x15 | COL[0] else COL_BY → world idx or -1 | — |
| 0x16 | `alpha` | — |
| 0x17 | `beta` | — |
| 0x18 | `gamma` | — |
| 0x19 | `inHandTable[currentInventory]` | — |
| 0x1A | `hitForce` | — |
| 0x1B | camera value: `*(u16*)((NumCamera+6)*2 + cameraPtr)` | — |
| 0x1C | `rand() % n` | +1 s16 n |
| 0x1D | `falling` | — |
| 0x1E | `room` | — |
| 0x1F | `life` | — |
| 0x20 | taken test: `foundFlag & 0xC000 ? 1 : 0` | +1 s16 world idx |
| 0x21 | `roomY` (AITD1; in evalVar2 it's currentMusic) | — |
| 0x22 | TEST_ZV_END_ANIM: simulates anim walk, col test | +2 s16 (anim, param) |
| 0x23 | `currentMusic` | — |
| 0x24 | `CVars[idx]` — raw index | +1 s16 |
| 0x25 | `stage` | — |
| 0x26 | thrown test: `foundFlag & 0x1000 ? 1 : 0` | +1 s16 world idx |
| other | printf + assert(0) | — |

(JACK+ adds in evalVar2: 0x25 get_matrix, 0x26 hardMat, 0x27 TEST_PROTECT, 0x2A sample-related; AITD1 not relevant.)

---

## 4. CVars (AITD1)

### Layout
`CVars` = `std::vector<s16>`, AITD1 size **45** (main.cpp:4168). Index = position in `AITD1KnownCVars` (0-based, sentinel -1 ends table). `getCVarsIdx(enumCVars)` linear-scans `currentCVarTable` == `AITD1KnownCVars` (main.cpp:36). Saved verbatim in savegame (save.cpp:187 asserts size 45).

### AITD1KnownCVars (AITD1.cpp:9) — index → enum value

| CVars idx | enum | value | use |
|---|---|---|---|
| 0 | SAMPLE_PAGE | 0 | page-turn sound |
| 1 | BODY_FLAMME | 1 | flame body |
| 2 | MAX_WEIGHT_LOADABLE | 2 | inventory weight cap |
| 3 | TEXTE_CREDITS | 3 | credits text |
| 4 | SAMPLE_TONNERRE | 4 | thunder sample |
| 5 | INTRO_DETECTIVE | 5 | intro text block |
| 6 | INTRO_HERITIERE | 6 | intro text block |
| 7 | WORLD_NUM_PERSO | 7 | current hero world-object number |
| 8 | CHOOSE_PERSO | 8 | 0=detective 1=heiress |
| 9 | SAMPLE_CHOC | 9 | hit sound |
| 10 | SAMPLE_PLOUF | 10 | splash sound |
| 11 | REVERSE_OBJECT | 11 | reversed object idx |
| 12 | KILLED_SORCERER | 12 | sorcerer dead flag |
| 13 | LIGHT_OBJECT | 13 | light world-object idx |
| 14 | FOG_FLAG | 14 | fog on/off |
| 15 | DEAD_PERSO | 15 | hero dead |
| 16..44 | — (unused pad to 45) | — | zero |

enumCVars values for first 16 match idx 1:1 (common.h:71–86). The remaining enum members (JET_SARBACANE, TIR_CANON, ... UNKNOWN_CVAR) are AITD2/JACK-era, not in AITD1 table.

### In-script access
- `evalVar` tag 0x24 → `CVars[<next s16>]` — **raw index**, not enum.
- LM_C_VAR / LM_MODIF_C_VAR: `CVars[raw s16 idx] = evalVar()`.
- Engine-side: `CVars[getCVarsIdx(CHOOSE_PERSO)]` etc. (AITD1.cpp:275-328, main.cpp:933+).

---

## 5. Porting notes (Python VM)

1. Buffer = bytes, PC in **bytes**, little-endian s16. All raw-arg handlers: `value = read_s16(); pc += 2`.
2. evalVar must push-pull a nested cursor — recursion on same buffer (cases 0x10, and any nested evalVar).
3. Jump encoding: `jump*2` bytes relative to after-jump-word. Python: `pc = after_jump_word_pos + jump*2`.
4. Opcode mapping: `table[opcode & 0x7FFF]` with 88 entries; assert-on-missing mirrors C (4 dead entries).
5. 0x8000 path needs a *reduced* handler set operating on `ListWorldObjets` (serialize as world-obj state in Python).
6. Chrono units: `evalChrono/60` (seconds); LM_GAME_OVER waits 120 ticks.
7. LM_READ AITD1 skips an extra s16 after its 2 args — must replicate or scripts desync.
8. `LM_WAIT_GAME_OVER` second loop condition differs from original interpreter (FITD bug) — decide fidelity vs bug-for-bug.
9. Stub (do nothing, consume args): LM_RND_FREQ, LM_SHAKING, LM_WATER, LM_REP_SAMPLE, LM_STOP_SAMPLE, LM_END_SEQUENCE, LM_PROTECT(n/a), LM_SET_INVENTORY(n/a).
