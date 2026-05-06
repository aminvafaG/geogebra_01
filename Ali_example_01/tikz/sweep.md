# `sweep.py` — varying a slider in a `.ggb` and regenerating PDFs

Companion tool to [ggb2pdf.py](ggb2pdf.py). Given a GeoGebra file with a slider
(say `Arz`), `sweep.py` produces a fresh `.ggb`, an extracted `geogebra.xml`,
and a vector `.pdf` for every value in a range you specify — all without
opening GeoGebra.

```
python sweep.py FILE.ggb  SLIDER  START:STEP:STOP  [-o OUT_DIR]  [--unit deg|rad]  [--no-pdf]  [--no-jpg]  [--dpi N]
```

Example:

```
python Ali_example_01\tikz\sweep.py Ali_example_01\Final_Helal_1404_BSe_BMo.ggb Oola 0:10:350 -o Ali_example_01\sweep_Oola


This walks `Arz` through `0, 10, 20, …, 90` degrees and emits 10 sets of files
in `../sweep_Arz/`.

---

## 1. The problem this solves

Inside a `.ggb` file (which is just a zip), `geogebra.xml` stores both:

1. The **construction recipe** — `<command name="Rotate">…</command>` nodes
   that say "B' is B rotated around yAxis by Arz", etc. There are 95 of these
   in the sample file.
2. The **cached final values** — every derived element also carries its last
   computed `<coords>` or `<value>`, e.g.

```xml
<element type="point3d" label="B'">
  <coords x="3.151" y="0.0" z="4.337" w="1.0"/>
</element>
```

[ggb2pdf.py](ggb2pdf.py) reads the **cached** coordinates ([extract_points
at lines 66–85](ggb2pdf.py#L66-L85)) — it never executes the construction.

So if you only patch the slider's `<value val="…"/>` and re-run the renderer,
nothing else moves: the dependents still hold the cache from when `Arz` had
its old value. You'd produce identical PDFs for every "different" slider
value.

To make the sweep work, the dependent points must be recomputed. `sweep.py`
does that by walking the construction in Python and re-evaluating each
command with the new slider value.

The relevant scope: in the sample file, `Arz` alone has **72 downstream
objects** computed by **69 commands** spanning 17 distinct command names.

---

## 2. Quick start

```bash
# Sweep Arz from 0 to 90 degrees in 10-degree steps
python sweep.py ../Final_Helal_1404_BSe_BMo.ggb  Arz  0:10:90  -o ../sweep_Arz

# Same, no PDFs (just .ggb + .xml — fast for debugging)
python sweep.py ../Final_Helal_1404_BSe_BMo.ggb  Arz  0:10:90  -o ../out  --no-pdf

# PDF only, skip JPEG
python sweep.py ../Final_Helal_1404_BSe_BMo.ggb  Arz  0:10:90  -o ../out  --no-jpg

# Higher-resolution JPEG (300 DPI)
python sweep.py ../Final_Helal_1404_BSe_BMo.ggb  Arz  0:10:90  -o ../out  --dpi 300

# Pass radians instead of degrees
python sweep.py ../Final_Helal_1404_BSe_BMo.ggb  Arz  0:0.1:1.5  -o ../out  --unit rad
```

For each value `v` in the range, the script writes three files into the
output directory, with names like `Arz_010_00.ggb / .xml / .pdf`. The tag
encodes the value (`010_00` = 10.00, `m015_50` = -15.50).

---

## 3. CLI reference

| Argument           | Meaning |
|--------------------|---------|
| `ggb` (positional) | Path to the source `.ggb`. |
| `slider` (positional) | Label of the element to sweep (e.g. `Arz`, `Oola`, `ArzGhamar`). Must be a free angle/numeric element in the file. |
| `range` (positional) | Matlab-style `START:STEP:STOP` (or `START:STOP`, step defaulting to 1). Both endpoints inclusive. |
| `-o, --out DIR`    | Output directory. Default: `<ggb-parent>/<slider>_sweep`. |
| `--unit deg\|rad`  | Unit of the range values. Default `deg`. GGB stores angle sliders internally as radians; `--unit deg` converts on input. |
| `--no-pdf`         | Skip the [ggb2pdf.py](ggb2pdf.py) step; emit `.ggb` + `.xml` only. |
| `--no-jpg`         | Skip JPEG generation (PDF is still produced unless `--no-pdf` is set). |
| `--dpi N`          | Rasterisation resolution for JPEG output. Default `150`. Higher values give sharper images at the cost of larger files (e.g. `--dpi 300`). |

**JPEG dependency.** JPEG output requires Pillow and `pdftoppm` (which ships with TeX Live, already on this machine). Install Pillow once with:
```
pip install Pillow
```
If Pillow is absent the script continues and prints a skip message; all other outputs are still produced.

Exit codes: `0` on full success; `2` on missing input or unknown slider
label. Per-value PDF failures are reported and skipped — they don't abort
the sweep.

---

## 4. Output layout

```
sweep_Arz/
├── Arz_000_00.ggb     # repackaged GeoGebra file at Arz = 0°
├── Arz_000_00.xml     # the modified geogebra.xml extracted from it
├── Arz_000_00.pdf     # rendered vector PDF
├── Arz_000_00.jpg     # rasterised JPEG (150 DPI default)
├── Arz_010_00.ggb
├── …
└── Arz_090_00.jpg
```

The `.xml` is just a copy of `geogebra.xml` from inside the corresponding
`.ggb` — provided for convenience so you can diff or inspect without
unzipping.

---

## 5. How it works — the four phases

```
                  +---------------------+
   FILE.ggb  -->  | 1. parse XML        |
                  | 2. seed scene from  |  scene = { label: typed_value }
                  |    cached <coords>  |
                  +---------------------+
                            |
                            v   override scene[SLIDER] = v
                  +---------------------+
                  | 3. walk             |  for each <command>:
                  |    <construction>   |    args = resolve(<input>)
                  |    in document      |    out  = CMD[name](*args)
                  |    order            |    scene[<output>] = out
                  +---------------------+
                            |
                            v
                  +---------------------+
                  | 4. write back       |  update <coords>/<value>
                  |    repack into ggb  |  for point3d, point,
                  |    run ggb2pdf.py   |  line3d, ray3d, angle, numeric
                  +---------------------+
                            |
                            v
                    Arz_<v>.ggb / .xml / .pdf
```

### Phase 1 — Parse

Standard `xml.etree.ElementTree` over the bytes of `geogebra.xml`. Nothing
unusual.

### Phase 2 — Seed the scene

The interpreter keeps a single `dict` named `scene`, mapping each element's
`label` to a typed Python object — `Point3D`, `Line3D`, `Plane3D`,
`Circle3D`, `Sphere`, `Segment3D`, `Ray3D`, `Vector3D`, `Number`.

Before evaluating any commands, every `<element>` in the construction is
seeded from its cached `<coords>` / `<value>` ([parse_initial_value at
lines ~321–360](sweep.py)). This matters for two reasons:

- **Free objects** (sliders, free points like `B = Point[zAxis]`) have no
  command we can evaluate — we *must* take the cached value.
- **Off-chain derived objects** (anything not downstream of the swept
  slider) don't need recomputing; the cache is correct. Seeding them
  upfront means the interpreter can fall back gracefully when it doesn't
  recognize a command.

After seeding, the slider's value is overwritten with the requested sweep
value (in radians).

### Phase 3 — Walk the construction

The `<construction>` block lists `<element>`, `<command>`, and
`<expression>` nodes interleaved in topological (dependency) order —
GeoGebra always writes producers before consumers. So we just iterate
children in document order. `<expression>` nodes (e.g.
`<expression label="cross" exp="u ⊗ v" type="vector"/>`) are evaluated
through the inline evaluator and their result stored under the declared
label. For each `<command>`:

1. **Resolve inputs.** Each `<input a0="X" a1="Y" …/>` attribute value can
   be either a bare identifier (`B'`, `Line_moaddel`) or an inline
   expression (`(-Taghvim)`, `(1.2 * Sp)`, `Mirror[Ghamar, A]`,
   `23.5°`, `2`). Identifiers go straight to a `scene[…]` lookup; anything
   else is handed to the inline evaluator (§7).
2. **Dispatch** on the command name to the corresponding implementation
   (`CMD["Rotate"]`, `CMD["Circle"]`, etc. — see §6).
3. **Distribute outputs.** Most commands produce one value; a few
   (`Intersect[circle, circle]`, `Intersect[line, sphere]`) produce two.
   Outputs are stored back into `scene` under their declared labels.

If anything fails — unknown command, unparseable inline, type mismatch —
the failure is caught and that command is silently skipped, leaving the
cached value intact. This conservative design means an unsupported edge
case in one branch of the construction doesn't corrupt the rest.

### Phase 4 — Write back and repack

Only the cached coordinates that [ggb2pdf.py](ggb2pdf.py) actually reads
are rewritten:

| GGB element type      | What gets updated |
|-----------------------|-------------------|
| `point3d`             | `<coords x y z w>` |
| `point`               | `<coords x y z>`   |
| `line3d`, `ray3d`     | `<coords ox oy oz ow vx vy vz vw>` |
| `angle`, `numeric`    | `<value val>`      |

Conics, quadrics, segments, planes, vectors are **not** rewritten in the
XML. The renderer reconstructs them from points anyway, so updating their
caches would be wasted work — and harmless to leave stale.

The whole zip is then repacked: every file inside the `.ggb`
(`geogebra_thumbnail.png`, `geogebra_javascript.js`, etc.) is copied
verbatim except `geogebra.xml`, which is replaced with the modified
version.

Finally, [ggb2pdf.py](ggb2pdf.py) is invoked as a subprocess, passing it
the new `.ggb` and the desired output path.

---

## 6. The command interpreter

The interpreter covers exactly the GGB primitives that appear in the
sample construction. Each implementation lives as a `cmd_*` function and
is registered in the `CMD` dispatch table.

| GGB command         | Variants supported                                                              | Returns      |
|---------------------|---------------------------------------------------------------------------------|--------------|
| `Point[axis]`       | n/a — free, value comes from cache                                              | `None`       |
| `Sphere[C, on]`     | center + point-on-surface                                                       | `Sphere`     |
| `Plane[conic]`      | the conic's supporting plane                                                    | `Plane3D`    |
| `OrthogonalLine[P, plane]` | line through `P` perpendicular to `plane`                                | `Line3D`     |
| `OrthogonalPlane[P, line]` | plane through `P` perpendicular to `line`                                | `Plane3D`    |
| `Line[A, B]`        | through two points                                                              | `Line3D`     |
| `Ray[A, B]`         | from `A` through `B`                                                            | `Ray3D`      |
| `Segment[A, B]`     | endpoints                                                                       | `Segment3D`  |
| `Vector[A, B]`      | `B - A`                                                                         | `Vector3D`   |
| `Mirror[obj, P]`    | point reflection (point or circle through a point)                              | same as `obj`|
| `Rotate[obj, angle, axis]` | point or circle rotated around axis line by angle (radians)              | same as `obj`|
| `Circle[P1, P2, P3]`       | circle through three points                                              | `Circle3D`   |
| `Circle[line, P]`   | small/great circle around `line` passing through `P`                            | `Circle3D`   |
| `CircleArc[C, A, B]`       | center-arc — returned as the underlying circle (the renderer redraws arcs) | `Circle3D`   |
| `CircumcircleArc[A, B, C]` | arc through three points — same simplification                          | `Circle3D`   |
| `Intersect[circle, circle, idx]` | one of the two intersections; `idx ∈ {1, 2}`                          | `Point3D`    |
| `Intersect[circle, circle]`     | both intersections (two outputs)                                       | `(Point3D, Point3D)` |
| `Intersect[line, sphere]`       | both line-sphere hits (two outputs)                                    | `(Point3D, Point3D)` |
| `Intersect[line, plane]`        | one point                                                              | `Point3D`    |
| `Intersect[segment, sphere]`    | the hit inside `[0, 1]`                                                | `Point3D`    |
| `Intersect[ray, sphere]`        | the smallest `t ≥ 0` hit                                               | `Point3D`    |
| `Intersect[plane, sphere]`      | the cutting circle                                                     | `Circle3D`   |
| `IntersectPath[plane, sphere]`  | same as above (GGB uses a different name)                              | `Circle3D`   |
| `Distance[A, B]`    | euclidean distance                                                              | `Number`     |
| `Angle[v1, v2]` / `Angle[A, V, B]` | angle in radians between two vectors / at a vertex                  | `Number`     |
| `Sequence[…]`       | not needed by the renderer — returns `None`                                     | `None`       |
| `If[cond, then]` / `If[cond, then, else]` | picks a branch from a Python `bool` (or truthy `Number`); returns the chosen branch as-is | same as branch |

Anything not in this table is treated as "leave the cache". For your
specific construction this is fine; if you sweep a slider whose chain hits
a command we don't implement, the off-chain output stays at its original
value (which may or may not be correct).

---

## 7. Inline expression evaluator

GGB inlines small expressions into command inputs. Examples seen in the
sample file:

| Inline string                | What it means |
|------------------------------|---------------|
| `Arz`                        | identifier — look up in scene (unicode letters allowed, e.g. `θ_signed`, `α`, `β`) |
| `yAxis` / `xAxis` / `zAxis`  | built-in coordinate axes |
| `23.5°`                      | degrees → radians: `math.radians(23.5)` |
| `BoadMoaddal / °`            | radians → degrees (bare `°` evaluates to `π/180`) |
| `(-Taghvim)`                 | unary negation of a scene value |
| `(1.2 * Sp)`                 | scalar × point → scaled point |
| `u ⊗ v`                      | vector cross product → `Vector3D` |
| `cross * n`                  | vector dot product → `Number` (when both operands are `Vector3D`) |
| `sign_{1} > 0`               | comparison → Python `bool` (also `<`, `≤`, `≥`, `=`, `≠`); fed to `cmd_If` |
| `Mirror[Ghamar, A]`          | nested function call |
| `Intersect[C_Mentaghe, C_ofoghTaksiryGhamar, 2]` | nested call with index |
| `(-9°)`                      | parenthesized negative angle |
| `(-(k°))`                    | dummy variable inside `Sequence` (resolved to 0 since the renderer doesn't need `Sequence` output) |

The evaluator (`eval_inline` in [sweep.py](sweep.py)) handles each form
by:

1. Stripping redundant outer parentheses.
2. Trying built-ins, then identifiers, then function-call syntax (the
   `Name[...]` matcher checks bracket pairing so `Distance[X] ≥ Distance[Y]`
   isn't mis-parsed as one greedy call).
3. Numeric parsing.
4. Splitting on top-level operators in precedence order: comparison
   (`< > ≤ ≥ ≠ =`) → `+ -` → `* / ⊗` (parens/brackets respected),
   folding left-to-right within each level.
5. Falling through to a trailing-`°` handler for atoms like `23.5°`.

`<expression>` nodes in the construction (e.g. `cross = u ⊗ v`,
`aaa = BoadMoaddal / °`) are evaluated alongside `<command>` nodes in
document order, so dependent values follow the swept slider rather than
freezing at their seeded cache.

It is *not* a general-purpose expression evaluator — it covers the forms
this construction uses and refuses anything else. If you hit
`ValueError: can't evaluate inline expression: …` while sweeping a
different file, that's the place to extend.

---

## 8. Type system

Everything in `scene` is one of these tiny classes ([sweep.py
lines ~37–95](sweep.py)):

| Class       | Fields                          | Notes |
|-------------|----------------------------------|-------|
| `Point3D`   | `x, y, z`                        | also coerced from `Point2D` and 3-tuples by the helper `T(...)` |
| `Point2D`   | `x, y`                           | only `A` (the origin) in this file |
| `Vector3D`  | `x, y, z`                        |       |
| `Line3D`    | `P` (3-tuple), `d` (3-tuple)     | `d` is *not* required to be unit; `unit(d)` is taken when needed |
| `Ray3D`     | inherits `Line3D`                | dispatch order in `cmd_Intersect` checks `Ray3D` *before* `Line3D` |
| `Plane3D`   | `n`, `c` with `n · X = c`        |       |
| `Sphere`    | `C`, `r`                         |       |
| `Circle3D`  | `C`, `n` (plane normal), `r`     |       |
| `Segment3D` | `A`, `B`                         |       |
| `Number`    | `v` (float, in radians for angles) |     |

Vector-math helpers `add / sub / scl / dot / crs / nrm / unit` operate on
3-tuples; the helper `T(p)` coerces any of the above to `(x, y, z)` so the
math kernels don't care about Python types.

---

## 9. Empirical conventions ("gotchas")

GeoGebra has internal conventions for *which* of two intersection points
gets called "1" vs "2" and *which* of two output labels is the "first".
Two small empirical adjustments live in the code; if you sweep a different
file and see a point flip to its antipodal partner, look here:

1. **`_intersect_circle_circle` idx mapping.** GGB's `idx=1` corresponds
   to our larger-`s` root, not the smaller. Fixed inside the function:
   ```python
   s = s2 if idx == 1 else s1
   ```
   Calibrated against `Intersect[C_ofogh, C_Mentaghe, 1] -> Ghareb` in the
   sample file.

2. **Ray-vs-line dispatch.** `Ray3D` inherits from `Line3D`, so an
   `isinstance(_, Line3D)` check matches both. `cmd_Intersect` checks
   `Ray3D` first to avoid the line branch returning the wrong root for a
   ray that starts inside a sphere. Calibrated against
   `Intersect[i, a] -> J`.

Validation: sweeping at the file's currently-saved slider value
reproduces every cached `point3d` to ~1e-5 or better. The points routed
through `If[…]` (`MagharebGhamr`, `GhamarMoaddal`, `GhamarMoaddal'`, `F`)
agree to ~1e-5; the rest match within floating-point noise (~1e-14). To
re-check after edits:

```bash
python sweep.py ../Final_Helal_1404_BSe_BMo.ggb  Arz  36:1:36  -o /tmp/check  --no-pdf
# then compare /tmp/check/Arz_036_00.ggb's point3d coords against the original
```

---

## 10. Limitations

- **Single slider per run.** By design. Sweep one variable, vary it
  cleanly. If you need a 2-D parameter sweep, run the script in a shell
  loop — each invocation is independent.
- **Conics/segments/vectors not rewritten in XML.** Harmless for
  [ggb2pdf.py](ggb2pdf.py), but if you load a swept `.ggb` back into
  GeoGebra it'll briefly show stale outlines until GeoGebra recomputes on
  load. Re-saving in GeoGebra refreshes them.
- **`Sequence[…]` outputs are not recomputed.** Returns `None` and the
  dependent objects stay at cached values. (`If[…]` *is* supported — see
  §6/§7 — but its condition must reduce to a comparison the inline
  evaluator can parse.)
- **Booleans aren't recomputed.** They're typically user-toggle state in
  this file (e.g. "show altitude line"); the sweep preserves them. If a
  boolean were dynamically computed from the slider you'd need to extend
  the interpreter.
- **`angle3d` / `vector3d` caches aren't rewritten in XML.** Same
  rationale as conics/segments — the renderer reconstructs from points.
  Notable side-effect: a recomputed `<expression>` like `cross = u ⊗ v`
  flows into downstream commands within the run, but the `.ggb` you save
  still carries the *original* `cross`/`BoadMoaddal` cache, so reopening
  in GeoGebra briefly shows stale values until GeoGebra recomputes.
- **No expression precedence beyond comparison → `+ -` → `* / ⊗`.**
  Within each level, left-to-right. Sufficient for the inlines in this
  file (no chained comparisons, no `a + b*c`-style mixed precedence at
  the same level); extend `eval_inline` if you hit something more
  involved.

---

## 11. Extending it (adding a new GGB command)

If `sweep.py` skips a command because it's unimplemented, you'll see the
downstream object frozen at its cached value. To add the command:

1. Write a function `cmd_NewName(arg1, arg2, …)` that consumes typed
   inputs and returns a typed output. Cross-reference the GGB docs for
   the command's signature.
2. Register it: add `"NewName": cmd_NewName,` to the `CMD` dict.
3. If the new command produces a type the writeback step doesn't yet
   serialize, extend `write_back()` accordingly. Most additions don't
   need this — `Point3D`, `Line3D`, etc. are already covered.
4. If your command returns multiple outputs, return them as a tuple in
   the order GGB lists them in `<output a0=… a1=…/>` (sorted by key).

To debug an unexpected mismatch, the simplest tactic is the
self-consistency check from §9: sweep at the file's *original* slider
value and diff every `point3d`'s `<coords>` against the unmodified `.ggb`.
Any non-zero delta is a bug in the interpreter, not a sweep artifact.

---

## 12. File map

| File                         | Role |
|------------------------------|------|
| [sweep.py](sweep.py)         | This tool — interpreter + writeback + CLI |
| [ggb2pdf.py](ggb2pdf.py)     | Pre-existing renderer — turns one `.ggb` into one PDF |
| [sweep.md](sweep.md)         | This document |
| `../Final_Helal_1404_BSe_BMo.ggb` | The sample GeoGebra file the tool was developed against |
