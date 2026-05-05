# Pipeline guide: how `ggb2pdf.py` + `helal.tex` turn a `.ggb` into a vector PDF

This document explains, in depth:

1. What the rendering pipeline does, end‑to‑end.
2. How every visible 3‑D object is constructed in code.
3. How to edit `ggb2pdf.py` (and the generated `helal.tex`) to fix mismatches
   between what GeoGebra shows in its 3‑D Graphics view and what the PDF
   contains.

If something looks wrong in the PDF, the fix is almost always in
[`ggb2pdf.py`](ggb2pdf.py). `helal.tex` is **regenerated on every run**, so
hand‑editing it is only useful for one‑off experiments — your changes will
be overwritten the next time you run the script.

---

## 1. High‑level flow

```
   Final_Helal_1404_BSe_BMo.ggb        (GeoGebra ZIP — your source of truth)
              │
              │  zipfile + ElementTree
              ▼
   geogebra.xml                        (every point's final 3‑D coords are
              │                         already stored here by GeoGebra)
              │  build_scene()
              ▼
   helal.tex                           (auto‑generated TikZ scene)
              │
              │  xelatex
              ▼
   helal.pdf  →  Final_Helal_1404_BSe_BMo.pdf
```

The crucial design choice: **we do not re‑derive coordinates from sliders
in TeX.** GeoGebra has already done all the rotations and stored the
result in `<element type="point3d">… <coords x=… y=… z=…/></element>`.
`ggb2pdf.py` reads those numbers verbatim and feeds them into TikZ. This
is why moving a slider in GeoGebra and re‑saving works seamlessly: the
updated coordinates flow straight through.

---

## 2. Files in this directory

| File | Role | Edited by |
|---|---|---|
| `ggb2pdf.py` | Generator. Reads .ggb, computes geometry, emits `helal.tex`, runs `xelatex`. | **You.** This is where every fix lives. |
| `helal.tex` | Output. Regenerated on every run — do not hand‑edit for permanent changes. | Auto. |
| `rebuild.bat` | Double‑click wrapper for `python ggb2pdf.py --open`. | Rare. |
| `PIPELINE.md` | This document. | You. |
| `README.md` | Short user‑facing intro. | You. |
| `helal.pdf` | The compiled vector PDF (intermediate; gets copied next to the .ggb). | Auto. |

---

## 3. Anatomy of `ggb2pdf.py`

Read top‑to‑bottom, the script has these sections:

### 3.1 Vector helpers — `add`, `sub`, `scale`, `dot`, `cross`, `norm`, `normalize`, `rotate_axis`

Plain 3‑D math on tuples. `rotate_axis(P, axis, deg)` is Rodrigues'
formula — used for `List_Borj` (zodiac dots) and a few other rotations
that GeoGebra doesn't pre‑compute as named points.

### 3.2 GGB XML parsers

- `parse_ggb_xml(path)` — opens the .ggb (a zip), pulls `geogebra.xml`,
  returns its root element.
- `extract_points(root)` — iterates every `<element type="point3d">` and
  `<element type="point">` and returns `{label: (x, y, z)}`. The `point`
  case is for 2‑D points like `A` (origin) where GGB stores homogeneous
  coords with `z` as the homogenizer.
- `extract_booleans(root)` — reads the checkbox elements (`e`, `q`,
  `r`, …) so the script can honor them.
- `extract_line_dirs(root)` — reads the unit direction vector of every
  `<line3d>` and `<ray3d>` element, returned as `{label: (vx, vy, vz)}`.
  This is **load-bearing for any `Rotate[obj, angle, MyLine]`
  construction**: the rotation handedness depends on which way the line
  points, and the antipodal point on the sphere is *not* a safe
  substitute (see §7.5).
- `extract_camera(root)` — reads `xAngle`, `zAngle` and whether axes are
  shown.
- `extract_sphere_radius(pts)` — reads `R` from the actual distance
  `|N|` (or `|S|`, `|W|`, `|E|`).

### 3.3 Camera and visibility

- `view_dir(theta, phi)` returns the eye direction in tikz‑3dplot's
  convention:

  ```
  D = (sin θ sin φ,  −sin θ cos φ,  cos θ)
  ```

  A 3‑D point `P` is on the front (visible) hemisphere iff `P · D > 0`.

- `split_visibility(C, u, v, r, D, t_start, t_end)` is the heart of the
  hidden‑line algorithm. For a circle parameterized as

  ```
  P(t) = C + r·(u cos t + v sin t)
  ```

  visibility reduces to `cos(t − α) > −(C·D)/(r·L)` where
  `L = √((u·D)² + (v·D)²)` and `α = atan2(v·D, u·D)`. The function
  returns a list of `(t_start, t_end, visible_bool)` intervals covering
  the input range. Adjacent intervals with the same visibility are
  merged.

### 3.4 Circle constructors

- `circle_from_3pts(P1, P2, P3)` — circumscribed circle of a triangle
  (uses barycentric weights for the circumcenter). This is what
  `Circle[A, B, C]` in GeoGebra means.
- `circle_axis_through(axis_dir, point)` — circle around an axis
  through the origin, passing through `point`. Used for things like
  `Circle[Line_moaddel, Ghamar]`.
- `circle_great(normal)` — great circle perpendicular to `normal`,
  centered at origin. Caller fills in `r = R`. Used for
  `IntersectPath[plane, sphere]` — i.e. `C_Mentaghe`.
- `arc_through_2pts(center, P1, P2)` — minor arc from `P1` to `P2`
  centered at `center`. Returns `t_start = 0`, `t_end = end_angle` so
  it can be fed straight into `emit_circle`.

Each constructor returns a dict with **C, u, v, r, n** where `(u, v, n)`
is a right‑handed orthonormal frame and `t = 0` is at the in‑plane
direction of `u`. This uniformity is what lets `emit_circle` handle
every kind of circle/arc the same way.

### 3.5 TikZ emitters

- `emit_circle(out, circle, D, color_solid, color_dashed, …)` — splits
  the circle by visibility and writes one `\draw … plot[domain=…]` per
  interval. Front intervals draw on the main layer with
  `color_solid`; back intervals draw on the `back` pgflayer with
  `color_dashed,dashed,opacity=…`.
- `emit_segment(out, P1, P2, D, color, lw, …)` — straight line, split
  at the sphere silhouette plane (`P · D = 0`) so the back portion is
  dashed.
- `emit_vector(out, P1, P2, color, lw)` — TikZ arrow. Vectors are not
  split (they extend outside the sphere anyway).
- `emit_point(out, P, color, sz, D)` — circle dot, drawn on the
  `front` or `back` pgflayer based on `P · D`.
- `emit_label`, `emit_label_text` — Persian (`\RL{…}`) and plain text
  labels with the white halo background.

### 3.6 `build_scene(ggb_path, theta, phi, …)`

This is the orchestration function. Each visible object is one block of
code that:
1. checks any `bools.get("…")` condition (the GGB checkbox),
2. constructs the object via one of the circle/arc/segment helpers,
3. calls the matching `emit_*` function with the chosen color and line
   weight.

The order of emission matters — `back` pgflayer items appear behind
`main`, which appears behind `front`. So:

- Sphere shading goes first (back layer, screen‑coords).
- Hidden arcs of every circle go on `back`.
- Visible arcs go on `main`.
- Segments and vectors go on `main`.
- Points go on `front` or `back` depending on visibility.
- Labels go on `main` (last, so they sit on top of everything).

### 3.7 `main()` / CLI

Standard argparse. The defaults read theta/phi from the .ggb; flags
`--theta`, `--phi`, `--axes`, `--no-axes`, `--tex-only`, `--keep`,
`--open` exist for overrides and debugging. With `--tex-only` the script
stops after writing `helal.tex`, which is useful when you want to
inspect or hand‑edit the TikZ.

---

## 4. The data the .ggb gives you

Inside `geogebra.xml`, the relevant nodes are:

| XML | What you get |
|---|---|
| `<element type="point3d" label="X"><coords x=… y=… z=… w=…/></element>` | A 3‑D point. Real coords are `(x/w, y/w, z/w)`. `extract_points` does this. |
| `<element type="point" label="X"><coords x=… y=… z=…/></element>` | A 2‑D point (e.g. `A` at origin). `z` is the homogeneous denominator. |
| `<element type="boolean" label="e"><value val="true"/></element>` | A checkbox in the GGB UI. |
| `<element type="angle" label="Arz"><value val="0.628…"/></element>` | A slider (radians). |
| `<element type="quadric" label="a">` | A sphere/ellipsoid. We only render the main sphere, as a flat ball‑shaded disk in screen coords. |
| `<element type="conic3d" label="…">` | A circle. We rebuild it from the construction inputs (3 points, axis+point, etc.). |
| `<element type="conicpart" label="…">` | An arc. Same idea, plus a start/end. |
| `<element type="segment3d">` / `vector3d` | Line segments and arrows. We use the endpoints from `pts`. |
| `<euclidianView3D><coordSystem xAngle=… zAngle=…/>` | The camera. |

**Key point:** for any "point" the .ggb gives you the final coords. For
any "circle", `geogebra.xml` records the *command* that produced it
(e.g. `<command name="Circle"><input a0="E" a1="S" a2="W"/>…`) but the
matrix it stores afterwards is in *plane‑local* coordinates, which is
hard to interpret. We sidestep that by reconstructing each circle from
its inputs (which are point labels we have full coords for).

---

## 5. How each visible object is rendered

This is the lookup table you need when something is wrong. Each row maps
a GGB object to the lines in `ggb2pdf.py` that draw it.

| GGB object | Type | Defining inputs | `ggb2pdf.py` block |
|---|---|---|---|
| `a` | sphere | center=origin, radius=R | sphere ball‑shading scope |
| `C_ofogh` | circle (green) | `Circle[E, S, W]` | `circle_from_3pts(pts["E"], pts["S"], pts["W"])` |
| `C_Moaddel` | circle (blue) | `Circle[B', W, E]` | `circle_from_3pts(pts["B'"], pts["W"], pts["E"])` |
| `C_Mentaghe` | great circle (violet) | `IntersectPath[plane⊥NpM, sphere]` | `circle_great(pts["NpM"])` |
| `C_nesf` | circle (red) | `Circle[S, B, N]` (the meridian) | `circle_from_3pts(pts["S"], pts["B"], pts["N"])` |
| `C_yomiGhamar` | small circle | `Circle[Line_moaddel, Ghamar]` | `circle_axis_through(pts["Np"], pts["Ghamar"])` |
| `C_ofoghTaksiryGhamar` | circle (red) | `Circle[MagharebGhamr, Ghamar, −Ghamar]` | `circle_from_3pts(MagharebGhamr, Ghamar, −Ghamar)`. Conditional on bool **`e`**. |
| `C_BodeMoaddal9` | circle | `Rotate[C_ofogh, −9°, Line_moaddel]` | rotate `E, S, W` around **`line_dirs["Line_moaddel"]`** by −9°, then `circle_from_3pts`. **Must use the line's stored direction, not `pts["Np"]`** — they're antiparallel and rotating around `Np` flips the handedness (see §7.5). Conditional on **`l`**. |
| `C_boadSeva9` | circle | `Circle[NpM, Ghareb′, NPM']` | `circle_from_3pts(NpM, pts["Ghareb'"], NPM')` — uses GGB's stored `Ghareb'` directly rather than recomputing the rotation. Conditional on **`j`**. |
| `C_ArzGhamar` | circle | `Circle[NpM, NPM', MozeGhamar]` | `circle_from_3pts(...)`. Conditional on **`m`**. |
| `C_Arzghamrmanfi6` | small circle | `Circle[Line_mentaghe, Hamal']` (+6° lunar-latitude parallel around the ecliptic) | `circle_axis_through(pts["NpM"], pts["Hamal'"])`. Uses GGB's stored `Hamal'`. Conditional on **`o`**. |
| `C_Arzghamr6` | small circle | `Mirror[C_Arzghamrmanfi6, A]` (−6° lunar-latitude parallel) | `circle_axis_through(pts["NpM"], −pts["Hamal'"])`. Conditional on **`o`**. |
| `C_vasatAssama` | circle | `Circle[Zenith, NpM, Nadir]` | `circle_from_3pts(...)`. Conditional on **`d_1`**. |
| `C_ErtefaGhamar` | great circle | `Circle[Ghamar, Zenith, Nadir]` (موت altitude — passes through zenith, nadir, and the moon) | `circle_from_3pts(Ghamar, Zenith, Nadir)`. Conditional on **`a_1`** ("ارتفاع"). Note: GGB stores this element with `show object="false"`, but the `a_1` checkbox is the canonical visibility gate, so we honor that. |
| `c_1` | circle | `Circle[NpM, NPM', J]` (apparent latitude) | `circle_from_3pts(NpM, NPM', J)`. Conditional on **`w`**. |
| `C_ertefa5` | small circle | `Circle[Line_Ofogh, W'_1]` (altitude 5°) | `circle_axis_through((0,0,1), pts["W'_{1}"])`. Conditional on **`h_1`** ("ارتفاع5"). |
| `C_ertefa8` | small circle | `Circle[Line_Ofogh, W']` (altitude 8°) | `circle_axis_through((0,0,1), pts["W'"])`. Conditional on **`g_1`** ("ارتفاع8"). |
| `b` | inner sphere | `Sphere[A, H]` (radius `\|H\|`) | flat shaded disk in screen coords, back layer. Conditional on **`r`**. |
| `d` | inner sphere | `Sphere[A, I]` (radius `\|I\|`) | flat shaded disk in screen coords, back layer. Conditional on **`r`**. |
| `h` | segment | `Segment[A, Ghamar]` (red) | `emit_segment(O, Ghamar, …)`. Conditional on **`r`**. |
| `k` | segment | `Segment[H, J]` (red) | `emit_segment(H, J, …)`. Conditional on **`r`**. |
| `Arc_ArzGhamar` | arc | `CircleArc[A, Ghamar, MozeGhamar]` | `arc_through_2pts((0,0,0), Ghamar, MozeGhamar)`. Conditional on **`q`**. |
| `j_1` | segment | `Segment[W, A]` | `emit_segment(pts["W"], O, …)` |
| `i_1` | segment | `Segment[MagharebGhamr, A]` | `emit_segment(pts["MagharebGhamr"], O, …)`. Conditional on **`e`**. |
| `k_1` | segment | `Segment[Ghamar, G]` | `emit_segment(pts["Ghamar"], G, …)` |
| `l_1` | segment | `Segment[K, G]` | `emit_segment(K_pt, G, …)` |
| `u_1` | vector (black) | `Vector[B, 1.2·B]` (z‑axis) | `emit_vector(B, 1.2·B, "black")` |
| `v_1` | vector (blue) | `Vector[Np, 1.2·Np]` | `emit_vector(Np, 1.2·Np, "blue")` |
| `w_1` | vector (blue) | `Vector[Sp, 1.2·Sp]` | `emit_vector(Sp, 1.2·Sp, "blue")` |
| `List_Borj` | 11 dots | `Sequence[Rotate[Hamal,(-k)°,Line_mentaghe], k, 30, 330, 30]` | loop calling `rotate_axis(pts["Hamal"], pts["NpM"], -k)` |

Conditional booleans are read once at the top of `build_scene`:

```python
bools = extract_booleans(root)
...
if bools.get("e", True):   # افق تکثیری قمر
    ...
```

So toggling a checkbox in GeoGebra and re‑saving the .ggb will toggle
the corresponding object in the PDF.

---

## 6. The visibility / hidden‑line algorithm in detail

For a circle `P(t) = C + r·(u cos t + v sin t)`, the visibility condition
`P · D > 0` becomes:

```
C·D + r·(Av cos t + Bv sin t) > 0          where Av = u·D, Bv = v·D
⇔  L · cos(t − α) > −(C·D)/r               where L = √(Av² + Bv²),  α = atan2(Bv, Av)
⇔  cos(t − α) > −(C·D)/(r·L) =: arg
```

Three cases:

- **`arg ≤ −1`** → `cos(t−α) > −1` is always true → the entire circle is
  in front. One interval, visible.
- **`arg ≥ 1`** → never visible. One interval, hidden.
- **otherwise** → visible band is `t ∈ [α − Δα, α + Δα]` with
  `Δα = acos(arg)`. The function returns those boundaries clipped to
  `[t_start, t_end]`.

For arcs (`t_start = 0, t_end = end_angle < 360`), the boundaries
outside the arc are just dropped, which is why the same code path
handles both full circles and arcs.

For segments, the silhouette intersection is one parameter:
`s = d1 / (d1 − d2)` along `P(s) = P1 + s(P2 − P1)`. If both endpoints
are on the same side of the silhouette plane, no split happens.

---

## 7. The camera

The mapping from GGB's `(xAngle, zAngle)` to tikz‑3dplot's
`(theta, phi)` is in `view_from_ggb`:

```python
theta = 90 - xAngle
phi   = (270 - zAngle) % 360
```

- **`xAngle`** is the camera elevation above the horizon (degrees). When
  the user tilts the GGB scene up/down, `xAngle` changes. Converting to
  the tikz polar angle `theta` (degrees from `+z`) is straightforward.
- **`zAngle`** is GGB's azimuthal rotation. It accumulates while the
  user spins the scene, so it can be a huge number — we take it mod 360.
  The `270 −` offset is empirical: GGB and tikz‑3dplot pick different
  zero references for azimuth.

If the orientation in the PDF doesn't match GeoGebra:

1. Try `python ggb2pdf.py --phi <value>` with several values 22° apart
   until the cardinal points (N/S/E/W) line up.
2. Once you find the right `phi`, work out the offset relative to the
   .ggb's `zAngle % 360` and adjust the `270` in `view_from_ggb`.

If north/south are swapped or front/back is inverted, the convention in
`view_dir` may be off — try changing the signs:

```python
return (math.sin(th) * math.sin(ph),
        -math.sin(th) * math.cos(ph),
        math.cos(th))
```

Common alternatives if your model uses a different handedness:

```python
# variant A
return ( math.sin(th) * math.cos(ph),  math.sin(th) * math.sin(ph), math.cos(th))
# variant B
return (-math.sin(th) * math.sin(ph),  math.sin(th) * math.cos(ph), math.cos(th))
```

Whichever you change, also re‑check the dashed‑arc split for one
specific circle (e.g. `C_ofogh`) to confirm the *front* half stays
solid.

---

## 8. How to fix common mismatches

### 8.1 "A circle in the PDF is parallel to another, but in GGB they are tilted"

Cause: the circle is being constructed from a wrong rule (e.g. an
axis‑plus‑point rule when GGB actually used three points).

Fix: open the .ggb in GeoGebra, look at the circle's command in the
Algebra view (e.g. `Circle[P, Q, R]` vs `Circle[axis, point]`), then
match the `ggb2pdf.py` line that produces it. The rule‑of‑thumb is:

| GGB command | use this Python helper |
|---|---|
| `Circle[P, Q, R]` (3 points) | `circle_from_3pts(p, q, r)` |
| `Circle[axis, point]` | `circle_axis_through(axis_dir, point)` |
| `IntersectPath[plane⊥V, sphere]` | `circle_great(V)` then `c["r"] = R` |
| `CircleArc[center, P, Q]` | `arc_through_2pts(center, P, Q)` |
| `Rotate[obj, angle, axis]` | apply `rotate_axis(...)` to the inputs of `obj`, **then** rebuild |

### 8.2 "An angle/arc is going the wrong direction"

`arc_through_2pts(center, P1, P2)` always goes counter‑clockwise from
`P1` to `P2` in the plane oriented by `n = (P1 − center) × (P2 −
center)`. If GGB's arc goes the *other* way (the major arc, or the
opposite direction), swap `P1` and `P2`:

```python
arc = arc_through_2pts((0,0,0), pts["MozeGhamar"], pts["Ghamar"])  # was Ghamar, MozeGhamar
```

### 8.3 "A line goes through the sphere where it should be hidden"

Either (a) the visibility split isn't happening because both endpoints
are on the front hemisphere, or (b) the camera direction `D` is wrong
(see §7). To debug, print `dot(P1, D)` and `dot(P2, D)` for the segment
in question:

```python
print(label, P1, dot(P1, D), P2, dot(P2, D))
```

Negative means back‑hemisphere.

### 8.4 "A label collides with another or sits on top of a line"

Edit the `LABEL_DECOR` dictionary in `ggb2pdf.py`. Each entry is
`(anchor, offset, persian_text)`:

```python
"Shams": ("above", "4pt", "شمس"),
```

The `anchor` follows TikZ syntax: `above`, `below`, `left`, `right`,
`above left`, etc. The `offset` is the gap in pt. To move a label
further from its point, increase the offset.

### 8.5 "A point dot is the wrong color or size"

Edit the `POINT_STYLE` dictionary, e.g.:

```python
"Shams": ("orange", "2.4", True),    # color, size in pt, has_persian_label
```

### 8.5b "A conditional point appears even when its checkbox is off"

Conditional points are gated by the `POINT_BOOL` dictionary. Each entry
maps a point label to the GGB boolean that controls its visibility:

```python
POINT_BOOL = {
    "Ghamar'":        "f_1",
    "Shams'":         "s",
    "GhamarMoaddal":  "b_1",
    "GhamarMoaddal'": "e_1",
    "Ghareb'":        "j",
    "H":              "r",
    "I":              "r",
    "L":              "r",
    "J":              "r",
    "MagharebGhamr":  "e",
}
```

If you add a new point that should depend on a checkbox, add the
mapping here. Both the dot and its Persian label (if any in
`LABEL_DECOR`) will be skipped when the boolean is false.

### 8.6 "An object I toggled in GeoGebra still shows / never shows in the PDF"

Find the boolean's label in `geogebra.xml` (the `<element
type="boolean">` block) — a single letter, sometimes with subscript like
`a_1`. Then check the corresponding `bools.get("…", default)` line in
`ggb2pdf.py`. If the line is missing entirely, add a guard around the
emit call:

```python
if bools.get("h_1", False):
    # render C_ertefa5 ...
```

The default in the second argument of `bools.get` controls what happens
if the boolean isn't defined in the .ggb at all.

### 8.7 "An object is missing from the PDF entirely"

Three places to check:

1. Does the GGB element have `show object="true"`? If `false`, we
   intentionally skip it. Toggle it on in GeoGebra and re‑save.
2. Is the element guarded by a `<condition showObject="…"/>`? If yes,
   the boolean must be true (see §8.6).
3. Is there code for it in `build_scene`? If not, add a block. Use the
   table in §5 as a pattern.

### 8.8 "I added a new construction in GeoGebra, how do I render it?"

Steps:

1. Save the .ggb. Inspect `geogebra.xml` and find the
   `<command name="…"><input …/><output a0="MyNewThing"/></command>`
   for your object, plus the `<element type="…" label="MyNewThing">`.
2. Note the GGB command name (`Circle`, `CircleArc`, `Segment`,
   `Vector`, etc.) and its inputs.
3. In `build_scene`, add a block. Example for a new circle through
   three existing points `P, Q, R`:

   ```python
   if bools.get("yourBool", True) and all(k in pts for k in ("P", "Q", "R")):
       c = circle_from_3pts(pts["P"], pts["Q"], pts["R"])
       emit_circle(out, c, D, "teal", "teal",
                   lw_solid=1.0, lw_dashed=0.7)
   ```

4. If the object has labels or point dots, add entries to
   `LABEL_DECOR` and `POINT_STYLE`.
5. Re‑run the script.

### 8.9 "The sphere shading is too dark / opaque / wrong color"

The shading is a single TikZ line emitted near the top of `build_scene`:

```python
out.append(rf"\shade[ball color=gray!40,opacity=0.40] (0,0) circle ({fmt(R)});")
```

Change `gray!40` (xcolor mix), `opacity=0.40`, or replace `ball color`
with a flat `fill=gray!10` for a non‑shaded look.

### 8.10 "The PDF is the wrong size / margin"

The `\documentclass[border=4mm,tikz]{standalone}` line and the
`scale=0.85` on the `tikzpicture` control sizing. Both are in
`TEX_TEMPLATE` near the bottom of `ggb2pdf.py`. Increase `border` for
more whitespace, or change `scale=` to make the figure larger/smaller.

### 8.11 "I want to change a stroke color or line weight project‑wide"

Each `emit_circle(...)` call passes its own colors and `lw_solid` /
`lw_dashed`. To change `C_Moaddel` from blue to green:

```python
emit_circle(out, c, D, "green!50!black", "green!50!black",
            lw_solid=1.1, lw_dashed=0.8)
```

Use any TikZ/xcolor expression: `red`, `blue!70`, `red!50!black`,
`{rgb,255:red,127;green,0;blue,255}`, etc.

### 8.12 "Persian labels are showing as boxes"

`fontspec` requires Tahoma (or another Persian‑capable font) to be on
your system. Edit the `\newfontfamily{\fa}{Tahoma}` line in
`TEX_TEMPLATE` in `ggb2pdf.py` to match a font you have installed:

```python
\newfontfamily{\fa}{IRANSans}     % e.g.
```

---

## 9. Inspecting the generated TikZ

Every line of the generated `helal.tex` corresponds to a single
construction in `ggb2pdf.py`. The blocks are commented:

```latex
% --- 3D circles ---
\begin{pgfonlayer}{back}
\draw[green!35!black,line width=0.8pt,dashed,opacity=0.55]
  plot[domain=0.0000:44.0602,...] (...);
\end{pgfonlayer}
\draw[green!35!black,line width=1.2pt]
  plot[domain=44.0602:224.0602,...] (...);
...
```

If a circle is wrong, find its block in the .tex (search for the
color), then find the same color in `ggb2pdf.py` to identify which
emitter call produced it.

To work iteratively without xelatex re‑running each time:

```powershell
python ggb2pdf.py --tex-only      # only writes helal.tex
xelatex helal.tex                  # compile manually
```

To dump the .ggb's XML for inspection (useful when adding new objects):

```powershell
python -c "import zipfile; print(zipfile.ZipFile('../Final_Helal_1404_BSe_BMo.ggb').open('geogebra.xml').read().decode('utf-8'))" > scene.xml
```

---

## 10. Glossary of GGB labels you'll see in this scene

| GGB label | Meaning (Persian / astronomy) |
|---|---|
| `Arz` | عرض جغرافیایی — observer's geographic latitude |
| `Mayl` | میل کلی — obliquity of ecliptic (≈ 23.5°) |
| `Oola` | اولیة — angular position on ecliptic from a reference |
| `Taghvim` | تقویم — solar position offset |
| `BoadSeva` | بعد سوا — equator distance |
| `ArzGhamar` | عرض قمر — lunar latitude |
| `TaghvimGhamar` | تقویم قمر — lunar offset |
| `C_ofogh` | افق — horizon (z = 0 plane) |
| `C_Moaddel` | معدل النهار — celestial equator |
| `C_Mentaghe` | منطقة البروج — ecliptic |
| `C_nesf` | نصف النهار — meridian |
| `Hamal` | حمل — Aries (vernal equinox) |
| `Mizan` | میزان — Libra (autumnal equinox) |
| `Shams` | شمس — Sun |
| `Ghamar` | قمر — Moon |
| `MozeGhamar` | موضع قمر — Moon's position on ecliptic |
| `Np`, `Sp` | شمالی/جنوبی قطب معدل — celestial poles |
| `NpM`, `NPM'` | قطب منطقه — ecliptic poles |
| `Zenith`, `Nadir` | سمت‑الرأس / سمت‑القدم |
| `Ghareb` | غرب — west (ecliptic↔horizon intersection) |
| `MagharebGhamr` | مغرب قمر — Moon‑setting point |

---

## 11. Quick checklist when something's wrong

1. Open the .ggb in GeoGebra, find the misbehaving object, note its
   construction (`Algebra view → context menu → Object Properties` or
   look at the formula).
2. Open `tikz/_scene_dump.xml` (or extract manually) and find the
   matching `<element>` and the `<command>` that produced it.
3. Map the GGB command name to a helper in §5.
4. Find the corresponding block in `ggb2pdf.py`. Fix the inputs
   (commonly: wrong helper, wrong axis, swapped points).
5. Re‑run `python ggb2pdf.py`.
6. If the orientation is what's wrong (not the geometry), adjust
   `--phi` first; only edit `view_from_ggb` if the offset is wrong for
   *every* re‑render.
