# Materials v2 proof

Date: 2026-08-29
Spec: `docs/superpowers/specs/2026-08-29-actor-realism-roadmap-design.md` (sub-project H)

**This document's "Manual attestation" table is a checklist for a human
with real game data and a real window; every row started `pending` and no
claim about the rendered PNGs should be inferred from this file until a
human fills them in.** Everything under "Automated gates" was actually
run, in this environment, on this branch, and the output shown is the real
output of that run. The `make proof-graphics` section below is not a
manual attestation: it is what the renders measurably show, taken from the
PNGs and from numbers computed over them, and it says so where a claim is
a judgement of appearance rather than a measurement.

## What changed

`bump`, `sss` and `emissive` stopped being labels. A material's `detail`
noise is now a height field as well as a colour multiply: the fragment
shader takes Mikkelsen's unparametrized bump from the screen-space
gradient of that height against the camera-space position, so relief
catches the key instead of tinting the surface, and fades to nothing as one
noise cell shrinks toward half a pixel. `sss` warms the terminator — the
band where the half-Lambert wrap is 0.5 — by `SSS_TINT` and vanishes on
both the lit and the unlit side. `emissive` replaces a fragment's colour
with its raw palette entry, which is what ramp 14's flames needed. Blinn-
Phong's lobe gained its `(gloss + 8) / 8pi` normalisation, so a polished
surface no longer reads dimmer than a rough one. Underneath all of that,
the 23 palette ramps any body actually uses were hand-reviewed one at a
time, and this task retuned every number those terms read: the whole
`specular` column (which had been chosen by eye against the *un*normalised
lobe), the `detail_scale` of the three classes whose relief could never be
resolved at any viewing distance, and the global strength of the grain
colour multiply, which now shares the height field's own noise sample.
`realism=classic` is unmoved and byte-compared against
`tests/golden/scene_lit_classic.npy`.

## Automated gates

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_materials.py tests/test_render_gl.py tests/test_bootstrap_materials.py tests/test_layering.py -q
154 passed in 5.92s
```

```
$ make test
1431 passed, 2 skipped, 1 xfailed, 26 warnings in 52.18s
```

1429 before this task + the two new pure tests = 1431; 26 warnings, none
new.

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k "golden or classic or fixed"
5 passed, 83 deselected in 0.36s
```

Those five are the identity net, unmodified by this task:
`test_classic_realism_matches_the_pre_materials_golden` (the committed
`scene_lit_classic.npy`, byte-compared), `test_classic_ignores_the_material_table`,
`test_fixed_lighting_is_unchanged_by_the_scene_light`,
`test_fixed_lighting_casts_no_shadow`,
`test_fixed_lighting_ignores_the_shadows_option`. A retune of
`CLASS_PRESETS` *cannot* move `classic` — every material term is written
`1 + strength * ...` or `mix(x, y, strength)` with `PRESETS["classic"]` all
zeros — so these passing is a check that nothing structural leaked, not
evidence about the numbers.

The two tests this task added, both pure (`tests/test_materials.py`):

- `test_every_class_keeps_its_parameters_in_range_after_the_retune` —
  `Material.__post_init__` only guards `bump`/`sss`/`emissive` and the
  positive `detail_scale`. The retune moved every `specular` value at
  once; this pins the remaining eight fields to 0..1 so a fat-fingered
  `1.5` cannot ship.
- `test_only_emissive_emits` — `emissive` replaces a fragment's whole
  colour, so a stray non-zero anywhere in the table would take a body out
  of the lighting entirely.

The binding pre-existing gates that this retune had to stay inside:
`test_metal_is_brighter_than_matte_under_enhanced` (see "metal" below —
it set the ceiling on metal's bump), `test_a_streak_material_fades_before_its_cells_go_sub_pixel`
(it bounds `wood.detail_scale` to `(40, 85]`, which is why wood's 60 was
left alone), `test_bump_fades_out_with_distance` and
`test_bump_is_relief_not_tint` (both on stone, which is why stone's
`detail_scale` was left at 50), and
`tests/test_bootstrap_materials.py`'s `REVIEWED_RAMPS`, which pins the
per-index class mapping. This task tuned what a class *looks like*, never
which class an index *is*: `PyAitD/render/materials.json` is untouched.

## The ramp review

The review is Task 4's and is already committed; this section is the
durable record of it, because the survey it was made against is
git-ignored (below). All 23 ramps any body uses, with the class actually
committed to `PyAitD/render/materials.json` immediately before the review
(`git show d878fc7^:PyAitD/render/materials.json`, since `d878fc7` is the
review commit) and the class the review decided:

| Ramp | Before | After | |
|---|---|---|---|
| 0–1 | matte | matte | confirmed |
| 2–3 | metal | metal | confirmed |
| 14 | emissive | emissive | confirmed |
| 15–31 | hair | **skin** | changed |
| 32–47 | skin | skin | confirmed |
| 48–63 | wood | **matte** | changed |
| 64–68 | leather | **stone** | changed |
| 69–74 | skin | **leather** | changed |
| 75–79 | matte | **cloth** | changed |
| 80–95 | matte | matte | confirmed |
| 96–107 | metal | **cloth** | changed |
| 108–111 | metal | **cloth** | changed |
| 112–127 | metal | **skin** | changed |
| 128–143 | wood | **leather** | changed |
| 144–159 | cloth | **skin** | changed |
| 160–175 | cloth | cloth | confirmed |
| 176–191 | hair | **metal** | changed |
| 192–197 | cloth | cloth | confirmed |
| 198–201 | skin | **wood** | changed |
| 202–204 | metal | metal | confirmed |
| 205–207 | cloth | **wood** | changed |
| 208–217 | skin | **cloth** | changed |
| 218–223 | matte | **cloth** | changed |

15 changed across 152 palette indices, 8 confirmed (0–1, 2–3, 14, 32–47,
80–95, 160–175, 192–197, 202–204) — the number the emitted diff below
already gives, now agreeing with this table. An earlier draft of this
table transcribed the survey's `heuristic:` guess into the "Before"
column for ten rows (0–1, 2–3, 14, 69–74, 144–159, 192–197, 198–201,
202–204, 205–207, 208–217) instead of the class that was actually
committed at that point in git; five of those ten (0–1, 2–3, 14, 192–197,
202–204) were consequently marked **changed** when the committed class
never moved. The table above is derived straight from the two commits,
not transcribed from the survey.

**"Confirmed" means two different things in this document, and they are
not the same set.** The table's confirmed/changed column above answers
"did the committed `class` value move between the two commits" — 8 did
not. Two paragraphs below, "ten of the thirteen ramps the review
confirmed" answers a different question: "did the human's final decision
agree with the *heuristic* guess (not the vision guess, and not the
committed value)" — thirteen ramps do (15–31, 32–47, 48–63, 64–68, 75–79,
80–95, 96–107, 108–111, 112–127, 128–143, 160–175, 176–191, 218–223). The
two sets overlap only at 32–47, 80–95 and 160–175, where the committed
value, the vision guess and the heuristic guess all already agreed with
the human. The other ten ramps in the "heuristic-agreed" thirteen needed
an explicit `label` because their *committed* value was still the stale
vision guess, not the heuristic the human actually agreed with — which is
exactly the paragraph below.

**Who decided.** A human, ramp by ramp, over the rendered ramp swatches
and the bodies that use them. The two automated inputs — a heuristic on
the ramp's own colours, and an earlier Gemini vision-labelling pass —
were advisory; where they disagreed with the human the human won, and the
`note` field on each ramp in `PyAitD/render/materials.json` records all
three (`heuristic:`, `vision:`, `label:`) so the disagreement stays
readable.

**No ramp with disagreeing bodies is on record.** Task 4's report names
none, and none of the 23 carries a per-body override — a body that wanted
a different class for an index it shares would need one
(`DIR/bodies/body<NNN>.json`). This task did not re-open the review to
look for a disagreement the reviewer might have resolved silently.

**Ten "confirmed" ramps still had to be written down.** The emitter
resolves `label > vision_class > class`, and ten of the thirteen ramps
the review confirmed had a *stale* `vision_class` from the earlier
Gemini pass sitting under no label — so the committed table was already
emitting the vision guess, not the reviewed value. 15–31, 48–63, 64–68,
75–79, 96–107, 108–111, 112–127, 128–143, 176–191 and 218–223 each got an
explicit label to make the reviewed value the one that ships. The emitted
diff was 15 class-value changes across 152 palette indices.

**Where the labels live.** `data/aitd1/materials-survey/` is git-ignored
(this repo ships no game data, and the survey is derived from it), so the
survey's `label` fields are not the durable record. The durable record is
the `note` string on each of the 23 ramps in
`PyAitD/render/materials.json`, which carries `label: <value>` for every
one of them and is in git. `tests/test_bootstrap_materials.py`'s
`REVIEWED_RAMPS` pins the resulting per-index mapping.

### Glass does not exist in this data

The spec expected the attic window panes and the lantern chimney to
surface as `glass`. **No ramp among the 23 that any body uses reads as
glass, so no `glass` index ships and nothing in either fixture renders
through the `glass` preset.** The survey walks bodies, so anything drawn
into the pre-rendered plate rather than as body geometry is outside its
reach entirely — and the attic window is largely plate: the striping
across its panes is present under `realism=classic` too, unchanged, so no
material produces it. What *is* body geometry there resolves to `cloth`
for the pane polygons and `skin` for the lantern's chimney. Neither reads
as glass, and that is a consequence of the data rather than a defect of
the review: no ramp among the 23 carries the colours a glass ramp would.

`hair` is likewise absent: both ramps that previously resolved to a stale
`hair` vision guess (15–31, 176–191) were reviewed to `skin` and `metal`.
`glass` and `hair` remain in `MATERIAL_CLASSES` and in `CLASS_PRESETS`
because an override directory can still ask for them per body.

The classes that *are* present: `matte`, `skin`, `cloth`, `leather`,
`wood`, `stone`, `metal`, `emissive`.

## `make proof-graphics`

Sixteen PNGs under `docs/graphics-proof/` (git-ignored). The six
`-classic` files are **byte-identical to the ones rendered before this
retune** (`cmp` on all six), which is the visual half of the classic
identity claim.

**The combat fixture shows almost nothing.** Diffing
`combat-smooth-enhanced.png` against its `-classic` twin: 3,611 of
1,024,000 pixels differ, in one 253x27 strip. A per-class probe
(the fixture rendered once per class with that class forced to
`emissive=1.0`, then diffed) finds 3,620 `skin` pixels there and **zero
pixels of every other class**. Everything below is therefore the **attic**
fixture, where 65,546 pixels differ between `enhanced` and `classic`.

Which class each region of the attic frame is was established by
rendering the fixture once per class with that class forced to
`emissive=1.0` and diffing — an exact mask, not an eyeball:

| class | attic px | what it is on screen |
|---|---|---|
| cloth | 23,483 | Carnby's coat and trousers, the window's pane polygons, the rocking horse's rockers, the lantern's collar |
| skin | 18,021 | Carnby's face and hands, the lantern's glass chimney, part of the window frame |
| matte | 14,625 | the wardrobe, the stool |
| metal | 6,586 | the rocking horse's body, Carnby's shoes |
| leather | 2,450 | Carnby's lapel, the wardrobe's top |
| stone | 716 | Carnby's bow tie |
| wood | 0 | — |
| emissive | 0 | — |

**`wood`, `emissive`, `hair` and `glass` are not observable on either
fixture.** Their numbers below were set by rule and by measurement, never
by eye, and this document does not claim otherwise.

Measured over each class's own pixels, before and after the retune (`max`
is the brightest channel value any pixel of that class reaches, `clip` is
how many of them reach 250 or more, `|vs classic|` is the largest
per-channel distance from the `classic` render of the same frame):

| class | before max / clip / \|vs classic\| | after max / clip / \|vs classic\| |
|---|---|---|
| cloth | 120 / 0 / 35 | 117 / 0 / 38 |
| leather | 217 / 0 / 135 | 131 / 0 / **49** |
| matte | 150 / 0 / 61 | 150 / 0 / 61 |
| metal | 255 / **28** / 174 | 244 / **0** / **88** |
| skin | 255 / 9 / 95 | 255 / 8 / 67 |
| stone | 112 / 0 / 31 | 108 / 0 / 26 |

Across the whole frame the enhanced pass still touches essentially the
same pixels (65,601 → 65,546) but its largest excursion from `classic`
fell from 174 levels to 88.

Per class, against the spec's criteria:

- **skin — "smooth with a soft highlight and a warm terminator": met, in
  part by measurement.** Carnby's face reads smooth before and after; the
  only visible change is that the lantern's glass chimney lost the fine
  vertical striations it had, because the grain colour multiply is now at
  half strength. The warm terminator is not judgeable on this fixture —
  the face is small and its palette entries are saturated — and is
  instead pinned by `test_skin_warms_at_the_terminator`, which measures
  R/G on a grey swept-normal quad: 0.218 of excess redness at the
  light/shade boundary against 0.017 and 0.013 on the two sides, and 0
  levels of movement in the red channel. Skin's `specular` moved 0.15 →
  0.16, which is the lobe-normalisation compensation and nothing else.
- **cloth — "weave is relief, not stripes": met.** Before, Carnby's
  trousers carried an unmistakable fine diagonal crosshatch — one weave
  cell was 2.4 px at his distance, which is the aliasing band, and the
  pattern read as printed-on rather than woven. After, the crosshatch is
  gone and the trousers carry soft diagonal drape that changes with the
  light across each facet. The two changes were separated and rendered
  independently, and they do different jobs. Halving the colour multiply
  with `detail_scale` still at 12 removes the hatch but leaves nothing in
  its place — at 2.4 px per cell the fade holds the relief near zero, so
  the trousers go flat. Widening to 48 with the multiply still at full
  strength gives a legible diagonal twill, but colour and relief reinforce
  each other (they read the same noise sample) and it comes out stronger
  than drape. Both together is what gives the drape.
- **wood — "streaked": unobservable.** No wood pixel is in either
  fixture. `wood` was left at `detail_scale` 60 for that reason; the only
  change is the lobe-normalisation compensation on `specular` (0.2 →
  0.13). At scale 4 a hero-sized body puts wood's sampled cell at 0.32
  cells per pixel, so its relief runs at ~81% of full strength rather
  than 100%, and that is measured rather than seen.
- **metal — "brushed with a real highlight": met, with a trade recorded
  below.** Before, the rocking horse carried aliased fine horizontal
  banding (one sampled cell was 0.71 px across its flank) *and* a blown
  white pinprick on its mane where the normalised lobe clipped 28 pixels
  to 255. After, the banding is coherent brushed streaking that follows
  the body, and nothing clips.
- **glass — "rimmed and glossy": unobservable, and permanently so on this
  data.** No ramp is glass. Glass's `specular` was rescaled by its own
  normalisation factor (0.9 → 0.022, a factor of 41) so that the column
  means one thing throughout, and its rim is pinned by
  `test_rim_brightens_the_silhouette_edge_not_the_centre`, which
  monkeypatches its own glass material and so is unaffected by the table.
- **"nothing shimmers when the hero walks away at scale 4": met, by
  measurement — see the next section.**

## Shimmer

Shimmer is not "the surface has texture"; it is texture that changes
between adjacent frames of a body that is only creeping away. Measured
that way: a camera-facing material square walked from z=400 to z=12000 in
steps of 200 at scale 4, with each frame's body patch compared against the
previous frame's patch resampled onto this frame's footprint (both are
camera-facing squares, so the mapping is a pure scale about the image
centre). The number is the worst mean absolute difference that survives
that resample, in 8-bit levels, and the bracketed figure is how many
sampled noise cells one pixel covered at the step where the worst
happened — a step in the aliasing band (above ~0.5) is the one that
matters:

| class | before | after |
|---|---|---|
| metal | **31.7** (at 0.30 cells/px) | **3.8** (at 0.07) |
| hair | 8.6 (at **3.98** cells/px) | 5.2 (at 0.23) |
| leather | 9.7 (at 0.10) | 7.4 (at 0.10) |
| wood | 9.5 (at 0.27) | 6.1 (at 0.27) |
| skin | 5.8 (at 0.11) | 4.3 (at 0.11) |
| cloth | 2.4 (at 0.17) | 2.2 (at 0.03) |
| stone | 16.7 (at 0.20) | 16.5 (at 0.05) |

**What this shows:** metal's worst step fell 8.4x, and after the retune no
class's worst step falls in the aliasing band at all — before, metal's
worst was at 0.30 cells/px and hair's at 3.98, both places where the
sampled noise is at or past what the frame can carry.

**What this does not show, said plainly:** the metric has a floor
proportional to the texture's own contrast, because the resample is
nearest-neighbour and a high-contrast pattern loses more to it than a
faint one. Stone's 16.5 is the largest number in the table and its worst
step is at 0.05 cells per pixel — nowhere near aliasing — so it is
measuring stone's contrast, not stone shimmering. The metric separates
"the pattern is past Nyquist" from "the pattern is not"; it does not rank
two classes that are both comfortably inside it. **Whether anything
shimmers to a human eye in a real window is still a `pending` row below.**

## Retune

`PRESETS["enhanced"]`: `detail` 1.0 → **0.5**. Everything else unchanged
(`spec` 1.0, `rim` 0.6, `ao` 0.7, `contact` 1.0, `hemisphere` 1.0,
`bump` 1.0, `sss` 1.0, `emissive` 1.0).

*Traded against:* the visibility of the weave and the wood grain as
*colour*. `detail` is now only the grain colour multiply's share — the
relief has its own `bump` — and the two read the same noise sample, so
every bump's lit face was also its bright face and the apparent contrast
was roughly doubled. The spec asked for the multiply to fall to a
fraction once bump existed. It is also the one term with no distance
fade, so it is what aliases as a body recedes. Rendered at 0.35 (with
cloth's `detail` still at 0.08) Carnby's trousers read flat; 0.5, with
cloth's `detail` raised to 0.14 alongside it, keeps the streak and the
weave legible as colour while letting relief carry the shape.

`CLASS_PRESETS`, every value that moved:

| class | field | from | to | why, and against what |
|---|---|---|---|---|
| skin | specular | 0.15 | 0.16 | lobe normalisation (÷0.955). Nothing else: skin already read smooth. |
| cloth | specular | 0.05 | 0.10 | lobe normalisation (÷0.478). Cloth's lobe is broad, so the normalisation made it *dimmer*; this restores it. |
| cloth | detail | 0.08 | 0.14 | Traded against the colour hatch. The preset's halving would otherwise have taken the weave's colour amplitude from ±0.08 to ±0.04 — the relief is untouched by that halving (`relief = m1.x * m1.y * dn` is scaled by `preset_c.x`, not by `PRESETS["enhanced"].detail`, which only reaches the colour multiply; `PyAitD/render/materials.py:82-84` has this right) — and 0.14 puts the colour back near where it was while giving the relief 1.75x the slope. Rendered at 0.20 as well; that read as ribbing rather than drape. |
| cloth | detail_scale | 12 | 48 | Traded against how fine the fabric reads. At the shipped ~4.9 FITD units/px on Carnby (below), one weave cell was 12/4.9 ≈ 2.4 px — aliasing, and the source of the crosshatch. 48 puts it at 48/4.9 ≈ 9.8 px. 32 was rendered as well and read as finer ribbing rather than drape. |
| leather | specular | 0.35 | 0.12 | lobe normalisation (÷2.865). This is the single largest correction in the column and it is what took leather's brightest pixel from 217 to 131. |
| hair | specular | 0.3 | 0.19 | lobe normalisation (÷1.592). **Unverifiable by eye — no ramp is hair.** |
| hair | detail_scale | 8 | 80 | Rule, not eye. Streak stretches the noise coordinate by 4, so at 8 one pixel covered 1.8 to 10.9 sampled cells at scale 1 and 0.63 to 5.1 at scale 4 — past the fade's half-cell everywhere, at every distance and every scale. Hair shipped relief that could not be resolved anywhere. 80 is the ~20x-stretch floor (below). |
| hair | bump | 0.8 | 0.3 | Traded against hair's now-live relief being far too strong. Streak multiplies the height gradient by 4, so at `detail` 0.3 the old 0.8 would have tilted normals by tens of degrees the moment the cell became resolvable. 0.3 puts hair's relief product (`detail x bump` = 0.09) below wood's (0.21), which is the only streak class with a measured appearance. **Unverifiable by eye.** |
| wood | specular | 0.2 | 0.13 | lobe normalisation (÷1.592). `detail_scale` deliberately left at 60 — see below. |
| stone | specular | 0.05 | 0.09 | lobe normalisation (÷0.543). |
| metal | roughness | 0.25 | 0.4 | Traded against highlight tightness. At 0.25 the lobe is 3.5° wide and lands as a pinprick on low-poly geometry; 0.4 gives 6°. This is the cheap stand-in for the anisotropy the spec dropped — a brushed surface's highlight should stretch along the brush direction, and a broader isotropic lobe is the honest substitute. **The fixtures cannot decide this**: metal's pixels in the attic sit nowhere near the lobe centre, and 0.25/0.3/0.4/0.5 all render within 3 levels of each other over them. |
| metal | specular | 0.8 | 0.15 | Set so the highlight's *peak* is exactly what the pre-normalisation table produced: 0.15 x (128+8)/8pi = 0.81, against the old 0.8. Verified on `test_metal_is_brighter_than_matte_under_enhanced`'s fixture, which reads a margin of 62 over matte at both — the same number the paragraph in that test was written against. |
| metal | detail | 0.15 | 0.2 | Brings the brushed colour streak back to ±0.10 after the preset's halving took it to ±0.075 (it was ±0.15 before). Not further: `detail` also scales the relief, and `detail x bump` is what the highlight ceiling below is really about. |
| metal | detail_scale | 25 | 120 | Rule, not eye. Brushed stretches by 6, so at 25 one sampled cell was 0.86 px at z=150 — metal's relief was byte-identical at bump 0.0 / 0.2 / 0.5 / 0.9, and its aliased banding was the largest shimmer source in the frame. |
| metal | bump | 0.5 | 0.08 | **The one place where a criterion had to be traded away, and the ceiling is measured.** See below. |
| glass | specular | 0.9 | 0.022 | lobe normalisation (÷41.06). **Unobservable — no ramp is glass.** |

Unchanged: `matte` and `emissive` entirely; `leather`'s and `stone`'s
`detail`, `detail_scale` and `bump`; `wood`'s `detail`, `detail_scale`
and `bump`; every `metallic` and every `rim`; `skin`'s `sss`.

### The specular column was eight mis-scalings, not one

Task 3 added Blinn-Phong's `(gloss + 8) / 8pi`, but the whole column had
been chosen by eye against the *un*normalised lobe. The factor is a
per-class constant, so dividing each entry by its own factor reproduces
the pre-Task-3 rendering to within the two decimal places the shipped
table is rounded to (skin's exact quotient is 0.1571, shipped as 0.16;
cloth's is 0.1047, shipped as 0.10) -- not exactly, pixel for pixel -- and
leaves the column meaning "the fraction of the key this surface reflects"
rather than "how bright its peak happens to be":

| class | roughness | gloss | (gloss+8)/8pi | old | new |
|---|---|---|---|---|---|
| skin | 0.7 | 16 | 0.955 | 0.15 | 0.16 |
| cloth | 0.9 | 4 | 0.478 | 0.05 | 0.10 |
| leather | 0.5 | 64 | 2.865 | 0.35 | 0.12 |
| hair | 0.6 | 32 | 1.592 | 0.3 | 0.19 |
| wood | 0.6 | 32 | 1.592 | 0.2 | 0.13 |
| stone | 0.85 | 5.66 | 0.543 | 0.05 | 0.09 |
| metal | 0.25 → 0.4 | 362 → 128 | 14.72 → 5.41 | 0.8 | 0.15 |
| glass | 0.1 | 1024 | 41.06 | 0.9 | 0.022 |

That the compensated column lands so evenly (0.09–0.19 for everything but
metal and glass, whose lobes are far tighter) is a check on the earlier
by-eye work, not a coincidence: the old values were mostly compensating
for the missing normalisation.

### `detail_scale` is the lever, and the rule it now follows

A class is inert once `detail_scale`, divided by its kind's stretch of the
noise coordinate (1 for grain and weave, 4 for streak, 6 for brushed),
puts one sampled cell under half a pixel — the shader's
`1 - smoothstep(0.25, 0.5, fwidth(nc))` zeroes the perturbation there, and
**no value of `bump` can revive it**.

At the shipped default (`scale` 4) a hero-sized body in the attic fixture
is ~4.9 FITD units per pixel. For the fade to be at full strength the
sampled cell has to be at least four pixels, which is
`detail_scale >= 4 x 4.9 x stretch` — about 20 for grain and weave, 78 for
streak, 118 for brushed. Measured against that rule before the retune:
`cloth` 12 (needs 20), `hair` 8 (needs 78) and `metal` 25 (needs 118) were
all short; `skin` 40, `leather` 30 and `stone` 50 already met it, and
`wood` 60 falls just short of 78 at 81% strength.

**`wood` was left at 60 anyway.** Raising it is bounded above at 85 by
`test_a_streak_material_fades_before_its_cells_go_sub_pixel`, which needs
wood's far frame at z=2400 to be byte-identical; 80 would fit with only a
6% margin, and no fixture shows a wood pixel, so there is nothing to
judge the change by. 81% of full strength is not broken, and the honest
move was to leave it.

`stone` (50) and `leather` (30) were left alone for the same kind of
reason: both already meet the rule, `test_bump_fades_out_with_distance`
and `test_bump_is_relief_not_tint` both measure stone at fixed distances
(widening it would move them), and neither class has enough of the attic
frame — 716 px of bow tie and 2,450 px of lapel and wardrobe top — to
judge a change by eye. Leather's `specular` correction alone took its
brightest pixel from 217 to 131, which is the change that mattered there.

### Measured: what each class's relief actually does, after

Max | mean-absolute per-pixel change over the body patch between `bump`
at 0 and `bump` at its tabled value, with the sampled cells per pixel
alongside. At scale 4 (the shipped default):

| class | ds | kind | z=603 | z=3003 | z=6003 | z=12003 |
|---|---|---|---|---|---|---|
| skin | 40 | grain | 26 \| 2.13 \| 0.03 | 26 \| 1.20 \| 0.08 | 24 \| 0.38 \| 0.14 | 25 \| 0.14 \| 0.25 |
| cloth | 48 | weave | 9 \| 0.37 \| 0.03 | 8 \| 0.22 \| 0.07 | 9 \| 0.10 \| 0.11 | 9 \| 0.03 \| 0.21 |
| leather | 30 | grain | 85 \| 4.29 \| 0.04 | 84 \| 2.68 \| 0.10 | 89 \| 0.88 \| 0.18 | 41 \| 0.15 \| 0.34 |
| hair | 80 | streak | 16 \| 1.07 \| 0.06 | 17 \| 0.99 \| 0.16 | 16 \| 0.31 \| 0.27 | 0 \| 0.00 \| 0.51 |
| wood | 60 | streak | 40 \| 3.52 \| 0.08 | 32 \| 1.61 \| 0.21 | 25 \| 0.30 \| 0.36 | 0 \| 0.00 \| 0.68 |
| stone | 50 | grain | 93 \| 10.74 \| 0.03 | 93 \| 5.35 \| 0.06 | 94 \| 1.84 \| 0.11 | 93 \| 0.53 \| 0.20 |
| metal | 120 | brushed | 38 \| 4.68 \| 0.06 | 34 \| 1.39 \| 0.16 | 22 \| 0.30 \| 0.27 | 0 \| 0.00 \| 0.51 |

And at scale 1, the regime the automated tests measure in:

| class | ds | kind | z=153 | z=603 | z=2403 | z=6003 |
|---|---|---|---|---|---|---|
| skin | 40 | grain | 24 \| 2.59 \| 0.09 | 25 \| 2.18 \| 0.13 | 27 \| 1.54 \| 0.27 | 0 \| 0.00 \| 0.55 |
| cloth | 48 | weave | 19 \| 1.75 \| 0.08 | 9 \| 0.37 \| 0.10 | 9 \| 0.41 \| 0.22 | 1 \| 0.01 \| 0.46 |
| leather | 30 | grain | 69 \| 4.61 \| 0.12 | 83 \| 4.42 \| 0.17 | 39 \| 2.07 \| 0.35 | 0 \| 0.00 \| 0.73 |
| hair | 80 | streak | 13 \| 1.44 \| 0.18 | 13 \| 1.06 \| 0.25 | 0 \| 0.00 \| 0.53 | 0 \| 0.00 \| 1.09 |
| wood | 60 | streak | 37 \| 3.40 \| 0.24 | 33 \| 2.40 \| 0.33 | 0 \| 0.00 \| 0.71 | 0 \| 0.00 \| 1.46 |
| stone | 50 | grain | 90 \| 8.37 \| 0.07 | 92 \| 10.89 \| 0.10 | 94 \| 7.54 \| 0.21 | 19 \| 0.29 \| 0.44 |
| metal | 120 | brushed | 39 \| 3.16 \| 0.18 | 31 \| 5.10 \| 0.25 | 0 \| 0.00 \| 0.53 | 0 \| 0.00 \| 1.09 |

Before the retune the same measurement gave `hair` and `metal` a flat
`0 | 0.00` in **every** column at both scales except one (metal moved 255
levels at scale 4, z=603, which was the aliased banding, not relief), and
`cloth` a flat `0` at the distances the earlier table sampled.

**A correction to the measured table this task was handed.** The relief
table in the task brief listed `cloth` as `0 / 1 / 0 / 0` — inert. It is
not: those zeros are an artefact of the fixture. `_facing_square` is a
constant-`z` plane, the weave is `sin(2 pi x) sin(2 pi z)`, and every `z`
that table sampled (150, 600, 2400, 6000) is an exact multiple of half a
12-unit cell, so `sin(2 pi z / 12)` is exactly zero and the whole weave
vanishes. Re-measured three units off (z=153, 603, 2403, 6003) at `scale`
1 -- the automated tests' regime, not the shipped default -- the old
`cloth` (`detail_scale` 12, before this task's retune) moves 10 levels at
z=153 and 3 at z=603. At `scale` 4 the same offset frames move
substantially more: 14 levels at both z=153 and z=603, which is the old
`detail_scale`'s aliasing, not resolvable relief, and is in the same
neighbourhood as this task's own fix report's 13-at-z=603-at-scale-4 (a
separate, independent measurement of the same effect). Every measurement
in the "Measured: what each class's relief actually does" tables below
states which scale it uses. `hair` and `metal` were genuinely inert;
`cloth` was not, and its `detail_scale` was widened for the aliasing the
fixture *did* show, not for the inertness it did not have.

### metal: the criterion that had to be traded

Relief and a tight highlight are in direct opposition, and metal has both.
`test_metal_is_brighter_than_matte_under_enhanced` samples one pixel at
the exact lobe centre and needs it 30 levels above matte. Measured on
that fixture, with metal at roughness 0.4 / specular 0.15 / detail 0.2:

| bump | 0.0 | 0.05 | 0.08 | 0.10 | 0.12 | 0.20 | 0.35 |
|---|---|---|---|---|---|---|---|
| margin over matte | 62 | 52 | **40** | 30 | 22 | 2 | −30 |
| region peak (green) | 31 | 31 | 31 | 31 | 31 | 31 | 31 |
| region mean (green) | 31.0 | 27.6 | 23.7 | 21.3 | 19.2 | 13.3 | 8.3 |

The highlight is **scattered, not spent** — the region's peak is 31 at
every bump — but past 0.08 it stops landing anywhere predictable, and the
bound is 30. Broadening the lobe further buys almost nothing (at
roughness 0.6, bump 0.35 still gives a margin of −2).

`bump = 0.08` is what shipped. On the rocking horse it is a slight
crispening of the brushed streaks over `bump = 0.0` — the streaks are
mostly the colour term either way — and it redistributes
about a quarter of the highlight's energy across the surface — a real
effect, where the old `0.5` was byte-identical to `0.0` at every distance.
But it is far below what the brushed *look* would carry on its own, and
most of the horse's brushed character comes from the colour streak rather
than from relief. **The honest statement is that metal's relief is
capped by its highlight, not chosen for its appearance.** A future task
that wants deeper brushing should widen the test's probe from one pixel to
a region — the claim "metal is brighter than matte" survives that, the
single-pixel measurement does not survive relief — rather than raise the
bump against the current gate.

## Known limitations

- **Derivative bump is per 2x2 quad.** `dFdx`/`dFdy` are constant across a
  quad, so the perturbed normal is too: faintly blocky at scale 1,
  invisible at 4.
- **Distant actors lose their relief by design.** The fade zeroes the
  perturbation once a sampled cell goes under half a pixel. That is what
  stops the shimmer, and it means a body walking away flattens rather than
  keeping its texture. The colour multiply has *no* such fade, so it is
  the term that still aliases past that point — halving it is a mitigation,
  not a fix.
- **`detail_scale` is tuned for one render scale.** The fade is a
  screen-space measure, so a class that is at full relief at `scale` 4 is
  at a quarter of the cells per pixel at `scale` 1 and may be faded there.
  The numbers here were chosen at the shipped default (4); at `scale` 1
  cloth, hair and metal all sit near the knee. `--render-scale` goes to 8,
  which only helps.
- **The review is a human step and always will be.** Nothing in the data
  says what a polygon is made of. `make bootstrap-materials` can survey
  and can ask a vision model, but the committed table's authority is a
  person, and re-running the emitter without labels will silently
  reintroduce the model's guesses — which is exactly what Task 4 found had
  already happened to ten ramps.
- **Detail is shape-free.** The noise has no seams, no planks, no buttons
  and no placement: it is one procedural field per kind, positioned only
  by the body's own rest coordinates. Cloth gets a weave, not a hem.
- **Anisotropy and plate reflections were dropped** as not worth their
  cost at this scale. Metal's broader lobe is the stand-in for the first;
  there is no stand-in for the second.
- **`glass` and `hair` are untested against anything real.** No ramp uses
  them, so their presets are reasoned, not observed.
- **The `smoothstep(0.0, 0.25, |cos|)` ramp width** — how far off its own
  facet a shading normal has to be before the bump comes back to full
  strength — is still a chosen constant that no measurement pins. Nothing
  in the fixtures gave a reason to move it, so it was left.

## Manual attestation

| Check | Status |
|---|---|
| Carnby's trousers and coat read as woven cloth in a real window, not as a printed pattern | pending |
| Carnby's face reads smooth, with a soft highlight and a visibly warm terminator at the light/shade boundary | pending |
| The rocking horse reads as brushed metal with a highlight, not as banded plastic | pending |
| Nothing shimmers, crawls or fizzes on the hero as he walks away at `--render-scale 4` | pending |
| Nothing shimmers on the hero at `--render-scale 1` and at `--render-scale 8` | pending |
| A lit flame body (ramp 14) stays bright when the room's key turns away from it | pending |
| `--realism classic` looks exactly as it did before this branch, in the window as well as in the golden | pending |
| The floor-5 combat venue's monsters read as leather/skin rather than as one flat colour | pending |
| No material change costs a playable frame rate at scale 4 or 8 | pending |
