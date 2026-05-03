# Vector PDF for `Final_Helal_1404_BSe_BMo.ggb`

GeoGebra Classic 5 cannot export the 3-D Graphics view as vector PDF — every
in-app exporter (PDF, EPS, PSTricks, PGF/TikZ, Asymptote) either rasterises the
3-D scene or silently writes only the 2-D Graphics panel. This folder gives
you a vector-quality PDF anyway, by rebuilding the scene in TikZ from the
slider values stored inside the `.ggb`.

## Files

| File | Purpose |
|---|---|
| `helal.tex` | Hand-written tikz-3dplot source. Renders only objects that have `show object="true"` in the GGB 3-D view. |
| `ggb2pdf.py` | Reads the current `.ggb`, pulls slider + view angles, runs `xelatex` with overrides, drops the PDF next to the `.ggb`. |
| `rebuild.bat` | Double-click wrapper for `ggb2pdf.py --open`. |
| `animate.ps1` | Sweep one parameter to render an animation. |

## Workflow ("in-app feel")

1. Edit the model in GeoGebra Classic 5, move sliders, **save** the `.ggb`.
2. Double-click `rebuild.bat` (or run `python ggb2pdf.py`).
3. The fresh `Final_Helal_1404_BSe_BMo.pdf` opens automatically.

The script reads these from the `.ggb` automatically:

- sliders: `Arz`, `Oola`, `Taghvim`, `BoadSeva`, `ArzGhamar`, `TaghvimGhamar`
- camera: `xAngle`, `zAngle` (translated to tikz-3dplot's `theta`, `phi`)

If you want to override anything by hand:

```powershell
xelatex "\def\Arz{45}\def\Oola{200}\input{helal.tex}"
```

### Camera not matching the GGB view?

The script translates GGB's `xAngle` / `zAngle` into tikz-3dplot's
`theta` / `phi` using an empirically-derived offset. If your model uses
a different default rotation than the calibration file, override directly:

```powershell
python ggb2pdf.py --theta 75 --phi 8         # match a specific view
python ggb2pdf.py --scan                      # render 16 phi values to compare
```

`--scan` writes 16 PDFs to `tikz/scan/scan_NNN.pdf` (one per phi value
from 0° to 338° in 22° steps). Open them, find the layout that matches
your GeoGebra view, then re-run with `--phi <that value>`.

## Animations

```powershell
.\animate.ps1                                  # default: Oola 0..350
.\animate.ps1 -Param Taghvim -From 0 -To 360 -Step 15
.\animate.ps1 -Param ArzGhamar -From -5 -To 5 -Step 0.5 -Fps 12
```

The script writes one PDF per frame plus 150-dpi PNG previews to `frames/`,
then assembles a `.gif` if ImageMagick (`magick.exe`) is on `PATH`.

## Requirements

- TeX Live (XeLaTeX). Tested with TeX Live 2025 on Windows.
- Python 3.x (for `ggb2pdf.py`).
- A Persian-capable font; defaults to **Tahoma** (Windows system font).
- Optional: `pdftoppm` (in Poppler / TeX Live) for preview PNGs;
  `magick` (ImageMagick) for animation gifs.

## Why this exists

GeoGebra's Asymptote exporter on this 3-D file produces a single 2-D circle
(the equator projected) plus the slider widgets — no 3-D structure
whatsoever. Without an in-app vector exporter, the only options are this
pipeline or hand-converting in another tool entirely (Mathematica,
MetaPost, Cinderella). This pipeline was the cheapest route that keeps you
authoring inside GeoGebra.
