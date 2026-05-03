#!/usr/bin/env python3
"""
ggb2pdf.py - Build a vector PDF of the celestial-sphere model directly from a
GeoGebra .ggb file, by reading the current slider values out of the embedded
geogebra.xml and feeding them to helal.tex via xelatex command-line overrides.

USAGE
-----
    python ggb2pdf.py [path/to/Final_Helal_1404_BSe_BMo.ggb] [-o output.pdf] [--open]

If no .ggb path is given, the script searches the parent directory for one.
With --open the resulting PDF is launched in the default viewer.

WORKFLOW
--------
    1. Edit the model in GeoGebra Classic 5, move sliders, save .ggb.
    2. Run this script (double-click a .bat wrapper, run from terminal,
       or set up an editor "build" command).
    3. Get a fresh vector PDF named after the .ggb (or whatever -o specified).
"""
from __future__ import annotations
import argparse
import math
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# Map: GGB element label  ->  (\def macro name in helal.tex,  unit in tex)
#   GGB stores angle values in radians; tex expects degrees.
SLIDER_MAP = {
    "Arz":           "Arz",
    "Oola":          "Oola",
    "Taghvim":       "Taghvim",
    "BoadSeva":      "BoadSeva",
    "ArzGhamar":     "ArzGhamar",
    "TaghvimGhamar": "TaghvimGhamar",  # not yet read by tex but kept for parity
}

# GGB view -> tex camera map.
#   GGB stores xAngle in degrees (elevation above horizontal plane) and zAngle
#   in degrees (cumulative azimuth, often large from many user drags).
#   Empirically derived against this .ggb's snapshot:
#       theta_tikz = 90 - xAngle        (matches: small xAngle ⇒ near-horizontal view)
#       phi_tikz   = (270 - zAngle) mod 360
#   The (270 - zAngle) offset is because GGB measures zAngle CCW from a
#   different reference axis than tikz-3dplot's phi (which is CCW from +x).
#   Override on the command line with --theta / --phi if your model uses a
#   different default view convention.
def view_from_ggb(xml: str) -> tuple[float, float] | None:
    m = re.search(r'<euclidianView3D>.*?<coordSystem[^/]*xAngle="([\-0-9.eE]+)"'
                  r'\s+zAngle="([\-0-9.eE]+)"', xml, re.S)
    if not m:
        return None
    x_ang = float(m.group(1))
    z_ang = float(m.group(2)) % 360.0
    theta = 90.0 - x_ang
    phi   = (270.0 - z_ang) % 360.0
    return theta, phi


def read_slider_values(xml: str) -> dict[str, float]:
    """Pull <element type='angle' label='X'><value val='RAD'/></element>"""
    out: dict[str, float] = {}
    pat = re.compile(
        r'<element[^>]*type="angle"[^>]*label="([^"]+)"[^>]*>'
        r'.*?<value\s+val="([\-0-9.eE]+)"',
        re.S,
    )
    for m in pat.finditer(xml):
        label, val_rad = m.group(1), float(m.group(2))
        out[label] = math.degrees(val_rad)
    return out


def build_overrides(ggb_path: Path) -> tuple[str, dict[str, float]]:
    with zipfile.ZipFile(ggb_path) as zf:
        with zf.open("geogebra.xml") as f:
            xml = f.read().decode("utf-8")
    sliders_deg = read_slider_values(xml)

    parts: list[str] = []
    used: dict[str, float] = {}
    for ggb_label, tex_macro in SLIDER_MAP.items():
        if ggb_label in sliders_deg:
            v = sliders_deg[ggb_label]
            parts.append(rf"\def\{tex_macro}{{{v:.4f}}}")
            used[ggb_label] = v

    view = view_from_ggb(xml)
    if view is not None:
        theta, phi = view
        parts.append(rf"\def\mTheta{{{theta:.3f}}}")
        parts.append(rf"\def\mPhi{{{phi:.3f}}}")
        used["xAngle->mTheta"] = theta
        used["zAngle->mPhi"]   = phi

    return "".join(parts), used


def find_ggb_default() -> Path | None:
    here = Path(__file__).resolve().parent
    for cand in (here.parent, here):
        for p in cand.glob("*.ggb"):
            return p
    return None


def run_scan(*, work: Path, tex: Path, base_overrides: str, out_pdf: Path) -> int:
    """Render a contact sheet of 16 views at theta=75, phi sweep 0..337.5.
    Useful when the auto-extracted view doesn't match what GGB shows."""
    print("  scan        : rendering 16 phi values at theta=75 ...")
    frames_dir = work / "scan"
    frames_dir.mkdir(exist_ok=True)
    for i, phi in enumerate(range(0, 360, 22)):
        ovr = re.sub(r"\\def\\m(Theta|Phi)\{[^}]*\}", "", base_overrides)
        ovr += rf"\def\mTheta{{75}}\def\mPhi{{{phi}}}"
        arg = ovr + r"\input{" + tex.name.replace(".tex", "") + "}"
        cmd = ["xelatex", "-interaction=batchmode", "-halt-on-error",
               "-output-directory=" + str(frames_dir),
               "-jobname=" + f"scan_{phi:03d}", arg]
        subprocess.run(cmd, cwd=work, capture_output=True, text=True, check=False)
    print(f"  scan PDFs   : {frames_dir}")
    print(f"  next step   : open the scan_*.pdf files, find the phi value whose")
    print(f"                  layout matches your GGB snapshot, then re-run with")
    print(f"                  --phi <that value>.")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ggb", nargs="?", type=Path, help="path to .ggb (default: search ../)")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="output PDF path (default: alongside the .ggb)")
    ap.add_argument("-t", "--tex", type=Path, default=Path(__file__).with_name("helal.tex"),
                    help="path to helal.tex (default: next to this script)")
    ap.add_argument("--theta", type=float, default=None,
                    help="override polar angle (degrees from +z); if set, ignores xAngle from .ggb")
    ap.add_argument("--phi", type=float, default=None,
                    help="override azimuth (degrees from +x); if set, ignores zAngle from .ggb")
    ap.add_argument("--scan", action="store_true",
                    help="render a 4x4 contact sheet of phi sweeps to help find the right view")
    ap.add_argument("--open", action="store_true", help="open PDF when done")
    ap.add_argument("--keep", action="store_true", help="keep aux/log files")
    args = ap.parse_args(argv)

    ggb = args.ggb or find_ggb_default()
    if ggb is None or not ggb.exists():
        print("ERROR: no .ggb file found. Pass one as the first argument.",
              file=sys.stderr)
        return 2
    ggb = ggb.resolve()
    tex = args.tex.resolve()
    if not tex.exists():
        print(f"ERROR: helal.tex not found at {tex}", file=sys.stderr)
        return 2

    out_pdf = (args.output or ggb.with_suffix(".pdf")).resolve()

    # 1. read slider values from .ggb
    overrides, used = build_overrides(ggb)

    # CLI overrides for theta/phi take precedence over GGB-extracted values.
    if args.theta is not None:
        overrides = re.sub(r"\\def\\mTheta\{[^}]*\}", "", overrides)
        overrides += rf"\def\mTheta{{{args.theta:.3f}}}"
        used["xAngle->mTheta"] = args.theta
    if args.phi is not None:
        overrides = re.sub(r"\\def\\mPhi\{[^}]*\}", "", overrides)
        overrides += rf"\def\mPhi{{{args.phi:.3f}}}"
        used["zAngle->mPhi"] = args.phi

    print(f"  source .ggb : {ggb}")
    print(f"  template    : {tex}")
    print(f"  overrides   :")
    for k, v in used.items():
        print(f"      {k:25s} = {v:10.3f}")

    if args.scan:
        return run_scan(work=tex.parent, tex=tex, base_overrides=overrides,
                        out_pdf=out_pdf)

    # 2. run xelatex with overrides
    work = tex.parent
    arg = overrides + r"\input{" + tex.name.replace(".tex", "") + "}"
    cmd = ["xelatex", "-interaction=batchmode", "-halt-on-error", arg]
    print(f"  running     : xelatex (in {work})")
    res = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if res.returncode != 0:
        print("xelatex failed:\n" + res.stdout[-2000:], file=sys.stderr)
        return 1

    # 3. move resulting PDF to requested location
    src = work / tex.name.replace(".tex", ".pdf")
    if not src.exists():
        print(f"ERROR: expected PDF not produced at {src}", file=sys.stderr)
        return 1
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != out_pdf:
        shutil.copyfile(src, out_pdf)
    print(f"  output      : {out_pdf}")

    # 4. tidy
    if not args.keep:
        for ext in (".aux", ".log", ".out"):
            p = work / tex.name.replace(".tex", ext)
            if p.exists():
                p.unlink()

    if args.open:
        if sys.platform.startswith("win"):
            import os
            os.startfile(str(out_pdf))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(out_pdf)])
        else:
            subprocess.run(["xdg-open", str(out_pdf)])

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
