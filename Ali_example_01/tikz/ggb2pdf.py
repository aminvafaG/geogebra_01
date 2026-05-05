#!/usr/bin/env python3
"""
ggb2pdf.py - Build a vector PDF directly from a GeoGebra .ggb file.

Approach
--------
Rather than re-deriving every rotation analytically inside .tex (which is
brittle), this script reads the FINAL 3-D coordinates of every point that
GeoGebra has already stored in the .ggb (in geogebra.xml), then constructs
each visible object (circle through 3 points, axis-circle, segment, vector,
arc) in Python and emits a self-contained TikZ source.  The result is
guaranteed to match the geometry GeoGebra actually computed.

USAGE
-----
    python ggb2pdf.py [path/to/file.ggb] [-o out.pdf] [--open]
"""
from __future__ import annotations
import argparse
import math
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# 3-D vector helpers
# ---------------------------------------------------------------------------
def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def scale(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])
def norm(a): return math.sqrt(a[0]**2 + a[1]**2 + a[2]**2)
def normalize(a):
    n = norm(a)
    return scale(a, 1 / n) if n > 1e-15 else (0.0, 0.0, 0.0)


def rotate_axis(P, axis, angle_deg):
    """Rodrigues rotation: rotate point P around axis (through origin) by angle."""
    n = normalize(axis)
    t = math.radians(angle_deg)
    c, s = math.cos(t), math.sin(t)
    cp = cross(n, P)
    nd = dot(n, P)
    return (P[0] * c + cp[0] * s + n[0] * nd * (1 - c),
            P[1] * c + cp[1] * s + n[1] * nd * (1 - c),
            P[2] * c + cp[2] * s + n[2] * nd * (1 - c))


# ---------------------------------------------------------------------------
# .ggb XML parsing
# ---------------------------------------------------------------------------
def parse_ggb_xml(ggb_path: Path) -> ET.Element:
    with zipfile.ZipFile(ggb_path) as zf:
        with zf.open("geogebra.xml") as f:
            return ET.fromstring(f.read().decode("utf-8"))


def extract_points(root):
    pts = {}
    for el in root.iter("element"):
        t = el.get("type")
        label = el.get("label")
        c = el.find("coords")
        if c is None:
            continue
        if t == "point3d":
            x = float(c.get("x")); y = float(c.get("y"))
            z = float(c.get("z", "0")); w = float(c.get("w", "1"))
            if abs(w) > 1e-12:
                pts[label] = (x / w, y / w, z / w)
        elif t == "point":
            # 2-D point: (x, y, z) with z as homogeneous
            x = float(c.get("x")); y = float(c.get("y"))
            zh = float(c.get("z", "1"))
            if abs(zh) > 1e-12:
                pts[label] = (x / zh, y / zh, 0.0)
    return pts


def extract_booleans(root):
    out = {}
    for el in root.iter("element"):
        if el.get("type") == "boolean":
            v = el.find("value")
            if v is not None:
                out[el.get("label")] = (v.get("val") == "true")
    return out


def extract_styles(root):
    """Read per-object render style from <element>: line thickness,
    typeHidden flag (0=Invisible, 1=Unchanged, 2=Dashed), and the object's
    color + alpha (where alpha is the surface fill opacity for conics).

    Returns label -> dict with keys:
        thickness  : int (1..)
        typeHidden : 0 | 1 | 2
        type       : 0 (solid) | 10 (dashed) | ... pgf line dash style
        rgb        : (r, g, b) ints in 0..255
        alpha      : float in 0..1
    """
    out = {}
    for el in root.iter("element"):
        if el.get("type") not in ("conic3d", "conicpart", "segment3d",
                                   "vector3d", "ray3d", "line3d", "quadric"):
            continue
        ls = el.find("lineStyle")
        col = el.find("objColor")
        if ls is None or col is None:
            continue
        try:
            out[el.get("label")] = {
                "thickness":  int(ls.get("thickness", "5")),
                "typeHidden": int(ls.get("typeHidden", "0")),
                "type":       int(ls.get("type", "0")),
                "rgb":        (int(col.get("r", "0")),
                               int(col.get("g", "0")),
                               int(col.get("b", "0"))),
                "alpha":      float(col.get("alpha", "0")),
            }
        except (TypeError, ValueError):
            continue
    return out


# GGB thickness -> TikZ pt: empirical mapping.
# thickness  1   2   3   4   5   6   7
#   pt      0.3 0.5 0.7 0.9 1.1 1.3 1.5
def thickness_to_pt(t):
    return max(0.3, 0.2 + 0.18 * t)


def rgb_color(rgb):
    """Format an RGB triple as a TikZ xcolor expression."""
    r, g, b = rgb
    return f"{{rgb,255:red,{r};green,{g};blue,{b}}}"


# typeHidden constants (mirror GGB's hidden-line-style radio buttons)
HIDDEN_INVISIBLE = 0
HIDDEN_UNCHANGED = 1
HIDDEN_DASHED    = 2


def extract_line_dirs(root):
    """Return label -> 3-D unit direction for every <line3d>/<ray3d>.

    Important: GeoGebra stores a line's direction with a specific sign.
    Although the line is geometrically bidirectional, the right-hand-rule
    rotation around the line uses the stored direction.  So when a
    construction does `Rotate[obj, angle, MyLine]` we MUST use this exact
    stored direction to get the same orientation GeoGebra computed.
    """
    out = {}
    for el in root.iter("element"):
        if el.get("type") not in ("line3d", "ray3d"):
            continue
        c = el.find("coords")
        if c is None:
            continue
        try:
            vx = float(c.get("vx", "0"))
            vy = float(c.get("vy", "0"))
            vz = float(c.get("vz", "0"))
        except (TypeError, ValueError):
            continue
        n = math.sqrt(vx * vx + vy * vy + vz * vz)
        if n > 1e-12:
            out[el.get("label")] = (vx / n, vy / n, vz / n)
    return out


def extract_camera(root):
    cs = root.find(".//euclidianView3D/coordSystem")
    if cs is None:
        return 25.0, -60.0, False
    xa = float(cs.get("xAngle", 25))
    za = float(cs.get("zAngle", -60))
    show_axes = False
    for ax in root.iterfind(".//euclidianView3D/axis"):
        if ax.get("id") == "0" and ax.get("show") == "true":
            show_axes = True
            break
    return xa, za, show_axes


def extract_sphere_radius(pts):
    """The main sphere passes through N, S, W, E. Use one of those."""
    for label in ("N", "S", "W", "E"):
        if label in pts:
            return norm(pts[label])
    return 5.0


# ---------------------------------------------------------------------------
# Camera / visibility math
# ---------------------------------------------------------------------------
def view_dir(theta_deg, phi_deg):
    """Eye direction unit vector in tikz-3dplot's main_coords convention.

    With \\tdplotsetmaincoords{theta}{phi}, the eye sits at:
        D = (sin theta * sin phi, -sin theta * cos phi, cos theta)
    """
    th = math.radians(theta_deg)
    ph = math.radians(phi_deg)
    return (math.sin(th) * math.sin(ph),
            -math.sin(th) * math.cos(ph),
            math.cos(th))


def split_visibility(C, u, v, r, D, t_start_deg=0.0, t_end_deg=360.0):
    """For circle P(t) = C + r*(u cos t + v sin t) (t in degrees),
    return list of (a, b, visible) intervals covering [t_start, t_end].
    Visibility test: P(t) . D > 0."""
    Av = dot(u, D)
    Bv = dot(v, D)
    Cv = dot(C, D)
    L = math.hypot(Av, Bv)

    def vis_at(t_deg):
        t = math.radians(t_deg)
        return (Cv + r * (Av * math.cos(t) + Bv * math.sin(t))) > 0

    if L < 1e-12:
        return [(t_start_deg, t_end_deg, Cv > 0)]
    arg = -Cv / (r * L)
    if arg <= -1:
        return [(t_start_deg, t_end_deg, True)]
    if arg >= 1:
        return [(t_start_deg, t_end_deg, False)]

    alpha = math.degrees(math.atan2(Bv, Av))
    dalpha = math.degrees(math.acos(arg))
    boundaries = []
    for k in range(-3, 4):
        for s in (-1, 1):
            b = alpha + s * dalpha + 360 * k
            if t_start_deg + 1e-6 < b < t_end_deg - 1e-6:
                boundaries.append(b)
    boundaries = sorted(set(round(b, 6) for b in boundaries))

    pts_t = [t_start_deg] + boundaries + [t_end_deg]
    out = []
    for i in range(len(pts_t) - 1):
        a, b = pts_t[i], pts_t[i + 1]
        if b - a < 1e-6:
            continue
        out.append((a, b, vis_at((a + b) / 2)))
    # merge adjacent same-visibility
    merged = []
    for iv in out:
        if merged and merged[-1][2] == iv[2]:
            merged[-1] = (merged[-1][0], iv[1], iv[2])
        else:
            merged.append(iv)
    return merged


# ---------------------------------------------------------------------------
# Circle constructions (return dict with C, u, v, r, n)
# ---------------------------------------------------------------------------
def circle_from_3pts(P1, P2, P3):
    v1 = sub(P2, P1)
    v2 = sub(P3, P1)
    nv = cross(v1, v2)
    if norm(nv) < 1e-12:
        return None
    n = normalize(nv)
    a = norm(sub(P2, P3)); b = norm(sub(P3, P1)); c = norm(sub(P1, P2))
    a2, b2, c2 = a * a, b * b, c * c
    w1 = a2 * (b2 + c2 - a2)
    w2 = b2 * (a2 + c2 - b2)
    w3 = c2 * (a2 + b2 - c2)
    sw = w1 + w2 + w3
    if abs(sw) < 1e-12:
        return None
    C = ((w1 * P1[0] + w2 * P2[0] + w3 * P3[0]) / sw,
         (w1 * P1[1] + w2 * P2[1] + w3 * P3[1]) / sw,
         (w1 * P1[2] + w2 * P2[2] + w3 * P3[2]) / sw)
    r = norm(sub(P1, C))
    u = normalize(sub(P1, C))
    v = cross(n, u)
    return dict(C=C, u=u, v=v, r=r, n=n)


def circle_axis_through(axis_dir, P_through):
    """Circle around an axis (through origin, dir = axis_dir) passing through P_through."""
    n = normalize(axis_dir)
    proj = dot(P_through, n)
    C = scale(n, proj)
    radial = sub(P_through, C)
    r = norm(radial)
    if r < 1e-12:
        return None
    u = normalize(radial)
    v = cross(n, u)
    return dict(C=C, u=u, v=v, r=r, n=n)


def circle_great(normal):
    """Great circle of radius R centered at origin, in plane perp to normal.
    R is filled in by caller as `r=R`."""
    n = normalize(normal)
    # pick u perp to n
    if abs(n[2]) < 0.99:
        u = normalize(cross(n, (0, 0, 1)))
    else:
        u = normalize(cross(n, (1, 0, 0)))
    v = cross(n, u)
    return dict(C=(0.0, 0.0, 0.0), u=u, v=v, r=None, n=n)


def arc_through_2pts(center, P1, P2):
    """Arc with center, going CCW from P1 to P2 (looking along plane normal)."""
    a1 = sub(P1, center)
    a2 = sub(P2, center)
    r = norm(a1)
    nv = cross(a1, a2)
    if norm(nv) < 1e-12:
        return None
    n = normalize(nv)
    u = normalize(a1)
    v = cross(n, u)
    cos_t = dot(a2, u) / r
    sin_t = dot(a2, v) / r
    end_angle = math.degrees(math.atan2(sin_t, cos_t))
    if end_angle < 0:
        end_angle += 360.0
    return dict(C=center, u=u, v=v, r=r, n=n, t_start=0.0, t_end=end_angle)


# ---------------------------------------------------------------------------
# TikZ emitters
# ---------------------------------------------------------------------------
def fmt(x):
    return f"{x:.5f}"


def _circle_path(C, u, v, r, a, b, ns):
    """TikZ parametric `plot` clause for a circle arc segment in 3-D."""
    return (f"plot[domain={a:.4f}:{b:.4f},samples={ns},smooth,variable=\\t] "
            f"({{{fmt(C[0])}+{fmt(r)}*({fmt(u[0])}*cos(\\t)+{fmt(v[0])}*sin(\\t))}},"
            f"{{{fmt(C[1])}+{fmt(r)}*({fmt(u[1])}*cos(\\t)+{fmt(v[1])}*sin(\\t))}},"
            f"{{{fmt(C[2])}+{fmt(r)}*({fmt(u[2])}*cos(\\t)+{fmt(v[2])}*sin(\\t))}})")


def emit_circle(out, circle, D, color, lw=1.0,
                t_start=0.0, t_end=360.0, samples_full=80,
                hidden_style=HIDDEN_DASHED,
                hidden_opacity=0.55,
                fill_alpha=0.0,
                fill_layer="midback"):
    """Emit a 3-D circle/arc.

    Parameters mirror GGB's per-object style:
      - color       : TikZ color expression (e.g. \"red\" or rgb_color(rgb))
      - lw          : stroke width in pt (use thickness_to_pt(thickness))
      - hidden_style: HIDDEN_INVISIBLE / HIDDEN_UNCHANGED / HIDDEN_DASHED
      - fill_alpha  : 0..1, the conic's surface alpha. >0 paints a filled
                      disk in screen coords using the same parametric path.
      - fill_layer  : pgflayer for the filled disk ('main' draws it on top
                      of back arcs but below front-arc strokes).
    """
    if circle is None:
        return
    C, u, v, r = circle["C"], circle["u"], circle["v"], circle["r"]

    # ------- Disk fill (only for full circles, alpha > 0) -------
    # We close the parametric path with `--cycle` so TikZ fills the
    # projected ellipse. Disk fills go on `fill_layer` (midback) so they
    # sit BETWEEN the back-arc strokes and the front-arc strokes.
    # GGB caps the apparent fill at ~85% even when alpha=1.0, so we cap
    # likewise (matches "even at 100% it's still a bit transparent").
    if fill_alpha > 0.0 and abs((t_end - t_start) - 360.0) < 1e-3:
        ns = max(48, samples_full)
        path = _circle_path(C, u, v, r, 0.0, 360.0, ns)
        eff_alpha = min(0.85, fill_alpha)
        if fill_layer != "main":
            out.append(rf"\begin{{pgfonlayer}}{{{fill_layer}}}")
        out.append(rf"\fill[color={color},opacity={eff_alpha:.3f}] {path} -- cycle;")
        if fill_layer != "main":
            out.append(r"\end{pgfonlayer}")

    # ------- Outline (front + hidden parts per typeHidden) -------
    intervals = split_visibility(C, u, v, r, D, t_start, t_end)
    for (a, b, vis) in intervals:
        span = b - a
        if span < 0.05:
            continue
        ns = max(8, int(samples_full * span / 360))
        path = _circle_path(C, u, v, r, a, b, ns)
        if vis:
            out.append(rf"\draw[color={color},line width={lw}pt] {path};")
        else:
            if hidden_style == HIDDEN_INVISIBLE:
                continue
            elif hidden_style == HIDDEN_UNCHANGED:
                # Same stroke as the front, but on the back layer so any
                # opaque object in front (e.g. inner sphere) still wins.
                out.append(r"\begin{pgfonlayer}{back}")
                out.append(rf"\draw[color={color},line width={lw}pt] {path};")
                out.append(r"\end{pgfonlayer}")
            else:  # HIDDEN_DASHED
                out.append(r"\begin{pgfonlayer}{back}")
                lw_dashed = max(0.3, lw * 0.75)
                out.append(rf"\draw[color={color},line width={lw_dashed:.2f}pt,"
                           rf"dashed,opacity={hidden_opacity}] {path};")
                out.append(r"\end{pgfonlayer}")


def emit_segment(out, P1, P2, D, color, lw,
                 hidden_style=HIDDEN_DASHED, hidden_opacity=0.4):
    """Emit a 3-D line segment with proper hidden-line handling.

    The segment is split at the sphere silhouette plane (`P · D = 0`).
    The portion on the front hemisphere is drawn solid; the back portion
    follows `hidden_style` exactly like `emit_circle`.
    """
    d1 = dot(P1, D)
    d2 = dot(P2, D)

    def emit_part(A, B, vis):
        coords = (f"({fmt(A[0])},{fmt(A[1])},{fmt(A[2])}) -- "
                  f"({fmt(B[0])},{fmt(B[1])},{fmt(B[2])})")
        if vis:
            out.append(rf"\draw[color={color},line width={lw}pt] {coords};")
        else:
            if hidden_style == HIDDEN_INVISIBLE:
                return
            if hidden_style == HIDDEN_UNCHANGED:
                out.append(r"\begin{pgfonlayer}{back}")
                out.append(rf"\draw[color={color},line width={lw}pt] {coords};")
                out.append(r"\end{pgfonlayer}")
            else:  # HIDDEN_DASHED
                lw_d = max(0.3, lw * 0.75)
                out.append(r"\begin{pgfonlayer}{back}")
                out.append(rf"\draw[color={color},line width={lw_d:.2f}pt,"
                           rf"dashed,opacity={hidden_opacity}] {coords};")
                out.append(r"\end{pgfonlayer}")

    if d1 >= 0 and d2 >= 0:
        emit_part(P1, P2, True)
    elif d1 <= 0 and d2 <= 0:
        emit_part(P1, P2, False)
    else:
        s = d1 / (d1 - d2)
        Pmid = (P1[0] + s * (P2[0] - P1[0]),
                P1[1] + s * (P2[1] - P1[1]),
                P1[2] + s * (P2[2] - P1[2]))
        if d1 > 0:
            emit_part(P1, Pmid, True)
            emit_part(Pmid, P2, False)
        else:
            emit_part(P1, Pmid, False)
            emit_part(Pmid, P2, True)


def emit_vector(out, P1, P2, color, lw):
    out.append(rf"\draw[->,>=Latex,line width={lw}pt,color={color}] "
               f"({fmt(P1[0])},{fmt(P1[1])},{fmt(P1[2])}) -- "
               f"({fmt(P2[0])},{fmt(P2[1])},{fmt(P2[2])});")


def emit_point(out, P, color, sz, D):
    visible = dot(P, D) > 0
    layer = "front" if visible else "back"
    op = "1" if visible else "0.55"
    out.append(f"\\begin{{pgfonlayer}}{{{layer}}}")
    out.append(f"\\fill[{color},opacity={op}] ({fmt(P[0])},{fmt(P[1])},{fmt(P[2])}) circle ({sz}pt);")
    out.append("\\end{pgfonlayer}")


def emit_label(out, P, persian_text, anchor="above", offset="3pt"):
    out.append(f"\\node[{anchor}={offset},font=\\fa\\footnotesize,inner sep=0.5pt,"
               f"fill=white,fill opacity=0.55,text opacity=1,rounded corners=1pt] "
               f"at ({fmt(P[0])},{fmt(P[1])},{fmt(P[2])}) {{\\RL{{{persian_text}}}}};")


def emit_label_text(out, P, text, anchor="above", offset="2pt", font="\\tiny"):
    out.append(f"\\node[{anchor}={offset},font={font}] "
               f"at ({fmt(P[0])},{fmt(P[1])},{fmt(P[2])}) {{{text}}};")


# ---------------------------------------------------------------------------
# Main scene generation
# ---------------------------------------------------------------------------
LABEL_DECOR = {  # label, anchor, offset, persian text
    "N":  ("above left",  "1pt",  "شمال"),
    "S":  ("below right", "1pt",  "جنوب"),
    "W":  ("left",        "4pt",  "غرب"),
    "E":  ("right",       "4pt",  "شرق"),
    "Np": ("above right", "1pt",  "ق ش"),
    "Sp": ("below left",  "1pt",  "ق ج"),
    "NpM":("above left",  "8pt",  "ق م"),
    "NPM'":("below right","8pt",  "ق م"),
    "Hamal":("above right","2pt", "حمل"),
    "Mizan":("below left", "2pt", "میزان"),
    "Shams":("above",      "4pt", "شمس"),
    "MozeGhamar":("left",  "4pt", "مو قمر"),
    "Ghamar":("right",     "3pt", "قمر"),
    "Ghamar'":     ("right",      "3pt", "ن قمر"),
    "Shams'":      ("above",      "4pt", "ن شمس"),
    "GhamarMoaddal": ("below",    "3pt", "قمر معدل"),
    "GhamarMoaddal'": ("above",   "3pt", "ن قمر معدل"),
}

POINT_STYLE = {  # label -> (color, size_pt, draw_label_in_3d)
    "N":  ("red",      "2",   True),
    "S":  ("red",      "2",   True),
    "W":  ("red",      "2",   True),
    "E":  ("orange",   "2",   True),
    "Np": ("blue",     "2",   True),
    "Sp": ("blue",     "2",   True),
    "NpM":("violet",   "1.6", True),
    "NPM'":("violet",  "1.6", True),
    "Hamal":("red",    "1.8", True),
    "Mizan":("red",    "1.8", True),
    "Shams":("orange", "2.4", True),
    "Ghareb":("black", "1.6", False),
    "MozeGhamar":("red", "2", True),
    "Ghamar":("orange","2.4", True),
    "MagharebGhamr":("violet","1.6", False),
    "Zenith":("red",   "2",   False),
    "Nadir":("gray",   "1.8", False),
    "G":  ("gray!60!black", "1", False),
    "K":  ("gray!60!black", "1", False),
    "M":  ("gray!60!black", "1", False),
    # Conditional points (rendered only when their boolean is true) ---
    "Ghamar'":        ("orange",         "2.4", True),   # cond f_1
    "Shams'":         ("orange",         "2.4", True),   # cond s
    "GhamarMoaddal":  ("white",          "2.0", True),   # cond b_1
    "GhamarMoaddal'": ("white",          "2.0", True),   # cond e_1
    "Ghareb'":        ("gray!60!black",  "1.4", False),  # cond j
    "H":              ("blue!50!black",  "1.6", False),  # cond r (z-axis point)
    "I":              ("blue!50!black",  "1.6", False),  # cond r (z-axis point)
    "L":              ("orange",         "2.4", False),  # cond r (moon image on inner sphere)
    "J":              ("red",            "2.4", False),  # cond r (apparent moon position)
}

# Which booleans guard which conditional points (for visibility filtering)
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


def build_scene(ggb_path, theta_deg, phi_deg, show_axes_override=None):
    root = parse_ggb_xml(ggb_path)
    pts = extract_points(root)
    bools = extract_booleans(root)
    line_dirs = extract_line_dirs(root)
    styles = extract_styles(root)
    cam_x, cam_z, cam_axes = extract_camera(root)

    R = extract_sphere_radius(pts)
    D = view_dir(theta_deg, phi_deg)

    # Helper that pulls a GGB-stored style and produces emit-ready params.
    # If a label has no entry, falls back to a sensible default.
    DEFAULT_STYLE = {"thickness": 5, "typeHidden": HIDDEN_DASHED, "type": 0,
                     "rgb": (0, 0, 0), "alpha": 0.0}

    def style(label):
        s = styles.get(label, DEFAULT_STYLE)
        return {
            "color":        rgb_color(s["rgb"]),
            "lw":           thickness_to_pt(s["thickness"]),
            "hidden_style": s["typeHidden"],
            "fill_alpha":   s["alpha"],
            "thickness":    s["thickness"],
        }

    def draw_circle(label, circle, **overrides):
        """Look up GGB style for `label` and emit the circle with it."""
        if circle is None:
            return
        s = style(label)
        s.update(overrides)
        emit_circle(out, circle, D,
                    color=s["color"], lw=s["lw"],
                    hidden_style=s["hidden_style"],
                    fill_alpha=s["fill_alpha"],
                    t_start=s.get("t_start", 0.0),
                    t_end=s.get("t_end", 360.0),
                    samples_full=s.get("samples_full", 80))

    def draw_segment(label, P1, P2):
        s = style(label)
        emit_segment(out, P1, P2, D,
                     color=s["color"], lw=s["lw"],
                     hidden_style=s["hidden_style"])

    show_axes = cam_axes if show_axes_override is None else show_axes_override

    out = []
    out.append(r"% ---- generated by ggb2pdf.py ----")
    out.append(r"% sphere radius R = " + fmt(R))
    out.append(r"% camera theta=" + f"{theta_deg:.3f}, phi={phi_deg:.3f}")
    out.append("")

    # ------- Sphere ball shading (back layer, in screen coords) -------
    out.append(r"\begin{pgfonlayer}{back}")
    out.append(r"\begin{scope}[tdplot_screen_coords]")
    out.append(rf"\shade[ball color=gray!40,opacity=0.40] (0,0) circle ({fmt(R)});")
    out.append(r"\end{scope}")
    out.append(r"\end{pgfonlayer}")
    out.append("")

    # ------- Helper points referenced as coordinates -------
    out.append(r"% --- 3D coordinate aliases (so labels can use \node at (Foo)) ---")
    for label, P in pts.items():
        # Use safe TeX-friendly names: replace ' and _ etc.
        if any(ch in label for ch in (" ", "&")):
            continue
        safe = label.replace("'", "p").replace("_", "X")
        if safe == label or safe.replace("p", "").replace("X", "").replace("{", "").replace("}", "").isalnum():
            out.append(rf"\coordinate ({safe}) at ({fmt(P[0])},{fmt(P[1])},{fmt(P[2])});")
    out.append("")

    # ------- Circles (visible ones with conditional booleans honored) -------
    # Every block below pulls its color, line thickness, hidden-line style
    # (Invisible / Unchanged / Dashed) and surface alpha from the .ggb's
    # <lineStyle> and <objColor>.  Editing those properties in GeoGebra
    # propagates to the PDF on the next run.
    out.append(r"% --- 3D circles ---")

    # C_ofogh: horizon, through E, S, W (alpha=1.0 -> filled disk)
    if all(k in pts for k in ("E", "S", "W")):
        draw_circle("C_ofogh", circle_from_3pts(pts["E"], pts["S"], pts["W"]))

    # C_Moaddel: through B', W, E (B' = rotation of B around y by Arz)
    if "B'" in pts and "W" in pts and "E" in pts:
        draw_circle("C_Moaddel", circle_from_3pts(pts["B'"], pts["W"], pts["E"]))

    # C_Mentaghe: great circle perpendicular to NpM through origin
    if "NpM" in pts:
        c = circle_great(pts["NpM"]); c["r"] = R
        draw_circle("C_Mentaghe", c)

    # C_nesf: meridian through S, B, N
    if all(k in pts for k in ("S", "N", "B")):
        draw_circle("C_nesf", circle_from_3pts(pts["S"], pts["B"], pts["N"]))

    # C_yomiGhamar: small circle around Line_moaddel through Ghamar
    if "Np" in pts and "Ghamar" in pts:
        draw_circle("C_yomiGhamar",
                    circle_axis_through(pts["Np"], pts["Ghamar"]))

    # C_ofoghTaksiryGhamar - bool 'e'
    if bools.get("e", True) and "MagharebGhamr" in pts and "Ghamar" in pts:
        ghm_neg = scale(pts["Ghamar"], -1.0)
        draw_circle("C_ofoghTaksiryGhamar",
                    circle_from_3pts(pts["MagharebGhamr"], pts["Ghamar"], ghm_neg))

    # C_BodeMoaddal9 = Rotate[C_ofogh, -9°, Line_moaddel] - bool 'l'
    # Rotate around Line_moaddel's stored direction (NOT pts["Np"], which
    # is antiparallel and would flip the rotation handedness).
    if bools.get("l", False) and "Line_moaddel" in line_dirs and "E" in pts:
        ax = line_dirs["Line_moaddel"]
        E2 = rotate_axis(pts["E"], ax, -9.0)
        S2 = rotate_axis(pts["S"], ax, -9.0)
        W2 = rotate_axis(pts["W"], ax, -9.0)
        draw_circle("C_BodeMoaddal9", circle_from_3pts(E2, S2, W2))

    # C_boadSeva9: Circle[NpM, Ghareb', NPM']  - bool 'j'
    if bools.get("j", False) and all(k in pts for k in ("NpM", "NPM'", "Ghareb'")):
        draw_circle("C_boadSeva9",
                    circle_from_3pts(pts["NpM"], pts["Ghareb'"], pts["NPM'"]))

    # C_ArzGhamar - bool 'm'
    if bools.get("m", False) and all(k in pts for k in ("NpM", "NPM'", "MozeGhamar")):
        draw_circle("C_ArzGhamar",
                    circle_from_3pts(pts["NpM"], pts["NPM'"], pts["MozeGhamar"]))

    # C_Arzghamrmanfi6 = Circle[Line_mentaghe, Hamal'] - bool 'o'
    # SMALL circle around NpM-axis through Hamal' (the +6° lunar-latitude
    # parallel relative to the ecliptic).
    if bools.get("o", False) and "NpM" in pts and "Hamal'" in pts:
        draw_circle("C_Arzghamrmanfi6",
                    circle_axis_through(pts["NpM"], pts["Hamal'"]))
        # C_Arzghamr6 = Mirror[C_Arzghamrmanfi6, A]: -6° parallel
        draw_circle("C_Arzghamr6",
                    circle_axis_through(pts["NpM"], scale(pts["Hamal'"], -1.0)))

    # C_vasatAssama - bool 'd_1'
    if bools.get("d_1", False) and all(k in pts for k in ("NpM", "Zenith", "Nadir")):
        draw_circle("C_vasatAssama",
                    circle_from_3pts(pts["Zenith"], pts["NpM"], pts["Nadir"]))

    # c_1 (apparent latitude): Circle[NpM, NPM', J] - bool 'w'
    if bools.get("w", False) and all(k in pts for k in ("NpM", "NPM'", "J")):
        draw_circle("c_1", circle_from_3pts(pts["NpM"], pts["NPM'"], pts["J"]))

    # C_ertefa5 (altitude=5°): Circle[Line_Ofogh, W'_1] - bool 'h_1'
    if bools.get("h_1", False) and "W'_{1}" in pts:
        draw_circle("C_ertefa5",
                    circle_axis_through((0.0, 0.0, 1.0), pts["W'_{1}"]))

    # C_ertefa8 (altitude=8°): Circle[Line_Ofogh, W'] - bool 'g_1'
    if bools.get("g_1", False) and "W'" in pts:
        draw_circle("C_ertefa8",
                    circle_axis_through((0.0, 0.0, 1.0), pts["W'"]))

    # C_ErtefaGhamar = Circle[Ghamar, Zenith, Nadir] - bool 'a_1'
    if bools.get("a_1", False) and all(k in pts for k in ("Ghamar", "Zenith", "Nadir")):
        draw_circle("C_ErtefaGhamar",
                    circle_from_3pts(pts["Ghamar"], pts["Zenith"], pts["Nadir"]))

    # Arc_ArzGhamar - bool 'q'
    if bools.get("q", True) and "Ghamar" in pts and "MozeGhamar" in pts:
        arc = arc_through_2pts((0.0, 0.0, 0.0), pts["Ghamar"], pts["MozeGhamar"])
        if arc:
            s = style("Arc_ArzGhamar")
            emit_circle(out, arc, D,
                        color=s["color"], lw=s["lw"],
                        hidden_style=s["hidden_style"],
                        fill_alpha=0.0,  # arcs aren't filled
                        t_start=arc["t_start"], t_end=arc["t_end"],
                        samples_full=24)

    # ------- Segments (drawn from GGB-stored color/thickness/typeHidden) -------
    out.append(r"% --- segments ---")
    O = (0.0, 0.0, 0.0)
    # j_1 = Segment[W, A]
    if "W" in pts:
        draw_segment("j_1", pts["W"], O)
    # i_1 = Segment[MagharebGhamr, A] (cond 'e')
    if "MagharebGhamr" in pts and bools.get("e", True):
        draw_segment("i_1", pts["MagharebGhamr"], O)
    # h = Segment[A, Ghamar] (cond 'r')
    if bools.get("r", False) and "Ghamar" in pts:
        draw_segment("h", O, pts["Ghamar"])
    # k = Segment[H, J] (cond 'r')
    if bools.get("r", False) and "H" in pts and "J" in pts:
        draw_segment("k", pts["H"], pts["J"])
    # k_1: Ghamar -> G,  l_1: K -> G
    # Compute G, K, M from intersections (independent of helper pts that may be hidden)
    if all(k in pts for k in ("Np", "Ghamar")):
        # G = projection of Ghamar onto Line_moaddel (axis Np)
        n = normalize(pts["Np"])
        G = scale(n, dot(pts["Ghamar"], n))
        # K, M = intersections of C_ofogh (z=0 plane) with C_yomiGhamar
        # C_yomiGhamar: axis n, through Ghamar
        # On z=0 plane, the points have z=0 and lie on circle of radius rYG around C
        # rYG^2 = R^2 - (Ghamar . n)^2
        proj = dot(pts["Ghamar"], n)
        rYG = math.sqrt(max(R * R - proj * proj, 0.0))
        # Local basis for the small circle
        u = normalize(sub(pts["Ghamar"], G))
        v = cross(n, u)
        # Solve C_z + rYG*(u_z cos t + v_z sin t) = 0
        # G + rYG*(u cos t + v sin t) has z = G_z + rYG*(u_z cos t + v_z sin t)
        Gz = G[2]; uz = u[2]; vz = v[2]
        Lz = math.hypot(uz, vz)
        if Lz > 1e-12 and abs(-Gz / (rYG * Lz)) <= 1:
            alpha = math.degrees(math.atan2(vz, uz))
            dalpha = math.degrees(math.acos(-Gz / (rYG * Lz)))
            t_K = math.radians(alpha - dalpha)
            t_M = math.radians(alpha + dalpha)
            def at(tr):
                return (G[0] + rYG * (u[0] * math.cos(tr) + v[0] * math.sin(tr)),
                        G[1] + rYG * (u[1] * math.cos(tr) + v[1] * math.sin(tr)),
                        G[2] + rYG * (u[2] * math.cos(tr) + v[2] * math.sin(tr)))
            K_pt = at(t_K)
            M_pt = at(t_M)
            # Use the existing K, M from XML if present (they should match)
            K_pt = pts.get("K", K_pt)
            M_pt = pts.get("M", M_pt)
            # k_1 = Segment[Ghamar, G],  l_1 = Segment[K, G]
            draw_segment("k_1", pts["Ghamar"], G)
            draw_segment("l_1", K_pt, G)
            # Stash for points
            pts["G"] = G
            pts["K"] = K_pt
            pts["M"] = M_pt

    # ------- Vectors (style from GGB) -------
    out.append(r"% --- vectors ---")
    def draw_vector(label, P1, P2):
        s = style(label)
        emit_vector(out, P1, P2, color=s["color"], lw=s["lw"])
    # u_1: B -> 1.2 B  (z-axis upward arrow)
    if "B" in pts:
        draw_vector("u_1", pts["B"], scale(pts["B"], 1.2))
    # v_1: Np -> 1.2 Np
    if "Np" in pts:
        draw_vector("v_1", pts["Np"], scale(pts["Np"], 1.2))
    # w_1: Sp -> 1.2 Sp
    if "Sp" in pts:
        draw_vector("w_1", pts["Sp"], scale(pts["Sp"], 1.2))

    # ------- Axis lines (only if GGB shows them) -------
    if show_axes:
        out.append(r"% --- axes ---")
        L = R * 0.35
        out.append(rf"\draw[->,thin,gray] (0,0,0) -- ({fmt(L)},0,0) "
                   rf"node[anchor=west,font=\tiny,gray]{{$x$}};")
        out.append(rf"\draw[->,thin,gray] (0,0,0) -- (0,{fmt(L)},0) "
                   rf"node[anchor=south,font=\tiny,gray]{{$y$}};")
        out.append(rf"\draw[->,thin,gray] (0,0,0) -- (0,0,{fmt(L)}) "
                   rf"node[anchor=south,font=\tiny,gray]{{$z$}};")

    # ------- List_Borj (zodiac dots): Rotate[Hamal, -k°, Line_mentaghe] for k=30..330 step 30 -------
    if "Hamal" in pts and "NpM" in pts:
        for k in range(30, 360, 30):
            P = rotate_axis(pts["Hamal"], pts["NpM"], -float(k))
            emit_point(out, P, "yellow!70!orange", "1.2", D)

    # ------- Inner concentric spheres b, d (bool 'r' = "موضع مرئی") -------
    # Colors and alphas are taken from the .ggb's stored object color so
    # editing them in GeoGebra propagates here. They go on the `midback`
    # pgflayer: above outer-sphere shading and back-arcs, below front
    # arcs and points.
    if bools.get("r", False):
        for label, pt_label in (("d", "I"), ("b", "H")):  # outermost first
            if pt_label not in pts or label not in styles:
                continue
            radius = norm(pts[pt_label])
            sty = styles[label]
            col = rgb_color(sty["rgb"])
            alpha = min(0.85, sty["alpha"])
            out.append(r"\begin{pgfonlayer}{midback}")
            out.append(r"\begin{scope}[tdplot_screen_coords]")
            out.append(rf"\shade[ball color={col},opacity={alpha:.3f}] "
                       rf"(0,0) circle ({fmt(radius)});")
            out.append(r"\end{scope}")
            out.append(r"\end{pgfonlayer}")
        out.append("")

    # ------- Points -------
    out.append(r"% --- points ---")
    for label, (color, sz, _) in POINT_STYLE.items():
        if label not in pts:
            continue
        # If the point is gated by a boolean, only render it when the
        # boolean is true.  Default for unknown booleans is False so we
        # don't accidentally draw a hidden point.
        guard = POINT_BOOL.get(label)
        if guard is not None and not bools.get(guard, False):
            continue
        emit_point(out, pts[label], color, sz, D)

    # ------- Persian labels -------
    out.append(r"% --- labels ---")
    for label, (anchor, offset, txt) in LABEL_DECOR.items():
        if label not in pts:
            continue
        guard = POINT_BOOL.get(label)
        if guard is not None and not bools.get(guard, False):
            continue
        emit_label(out, pts[label], txt, anchor=anchor, offset=offset)
    # G, K, M small text labels (always visible when present)
    for lbl in ("G", "K", "M"):
        if lbl in pts:
            P = pts[lbl]
            anchor = {"G": "above right", "K": "below", "M": "above"}[lbl]
            emit_label_text(out, P, f"${lbl}$", anchor=anchor, offset="1pt")
    # H, I, L, J letter labels (only when bool 'r' is true)
    if bools.get("r", False):
        for lbl, anchor in (("H", "left"), ("I", "left"),
                            ("L", "above right"), ("J", "below right")):
            if lbl in pts:
                emit_label_text(out, pts[lbl], f"${lbl}$",
                                anchor=anchor, offset="2pt")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# .tex template
# ---------------------------------------------------------------------------
TEX_TEMPLATE = r"""% AUTO-GENERATED by ggb2pdf.py - regenerate with: python ggb2pdf.py
\documentclass[border=4mm,tikz]{standalone}

\usepackage{fontspec}
\newfontfamily{\fa}{Tahoma}
\usepackage{bidi}

\usepackage{tikz-3dplot}
\usetikzlibrary{calc,arrows.meta,decorations.markings,backgrounds,positioning}

% Layer order, back to front:
%   back     : outer-sphere ball shading + dashed/hidden back-arcs of circles
%   midback  : filled conic disks (alpha>0) + inner spheres (b, d)
%   main     : front-arcs, segments, vectors
%   front    : points + labels
\pgfdeclarelayer{back}
\pgfdeclarelayer{midback}
\pgfdeclarelayer{front}
\pgfsetlayers{back,midback,main,front}

\tdplotsetmaincoords{__THETA__}{__PHI__}

\begin{document}
\begin{tikzpicture}[tdplot_main_coords,scale=0.85,>=Latex]
__BODY__
\end{tikzpicture}
\end{document}
"""


def view_from_ggb(xa, za):
    """Map GGB camera (xAngle, zAngle) -> tikz-3dplot (theta, phi).
    Empirically tuned against the sample .ggb."""
    theta = 90.0 - xa
    phi = (270.0 - za) % 360.0
    return theta, phi


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def find_ggb_default():
    here = Path(__file__).resolve().parent
    for cand in (here.parent, here):
        for p in cand.glob("*.ggb"):
            return p
    return None


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ggb", nargs="?", type=Path, help="path to .ggb file")
    ap.add_argument("-o", "--output", type=Path, default=None, help="output PDF")
    ap.add_argument("--theta", type=float, default=None,
                    help="override polar angle (deg from +z); ignores xAngle from .ggb")
    ap.add_argument("--phi", type=float, default=None,
                    help="override azimuth (deg from +x); ignores zAngle from .ggb")
    ap.add_argument("--axes", action="store_true", default=None,
                    help="force-show axes regardless of .ggb")
    ap.add_argument("--no-axes", dest="no_axes", action="store_true",
                    help="force-hide axes")
    ap.add_argument("--open", action="store_true", help="open PDF when done")
    ap.add_argument("--keep", action="store_true", help="keep aux/log files")
    ap.add_argument("--tex-only", action="store_true",
                    help="emit helal.tex and stop (no xelatex)")
    args = ap.parse_args(argv)

    ggb = args.ggb or find_ggb_default()
    if ggb is None or not ggb.exists():
        print("ERROR: no .ggb file found.", file=sys.stderr); return 2
    ggb = ggb.resolve()
    out_pdf = (args.output or ggb.with_suffix(".pdf")).resolve()

    # Camera
    root = parse_ggb_xml(ggb)
    xa, za, show_axes_ggb = extract_camera(root)
    if args.theta is None or args.phi is None:
        theta_def, phi_def = view_from_ggb(xa, za)
    else:
        theta_def, phi_def = 25.0, -60.0
    theta = args.theta if args.theta is not None else theta_def
    phi = args.phi if args.phi is not None else phi_def
    theta = theta + 0
    phi = -phi + 0 
    if args.no_axes:
        show_axes_override = False
    elif args.axes:
        show_axes_override = True
    else:
        show_axes_override = None

    print(f"  source .ggb : {ggb}")
    print(f"  view        : theta={theta:.3f}, phi={phi:.3f}  (from xAngle={xa:.2f}, zAngle={za % 360:.2f})")
    print(f"  show axes   : {show_axes_ggb if show_axes_override is None else show_axes_override}")

    body = build_scene(ggb, theta, phi, show_axes_override)
    tex_src = (TEX_TEMPLATE
               .replace("__THETA__", f"{theta:.3f}")
               .replace("__PHI__", f"{phi:.3f}")
               .replace("__BODY__", body))

    work = Path(__file__).resolve().parent
    tex_path = work / "helal.tex"
    tex_path.write_text(tex_src, encoding="utf-8")
    print(f"  wrote       : {tex_path}")

    if args.tex_only:
        return 0

    cmd = ["xelatex", "-interaction=batchmode", "-halt-on-error", "helal.tex"]
    print(f"  running     : xelatex (in {work})")
    res = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if res.returncode != 0:
        print("xelatex failed:\n" + (res.stdout or "")[-3000:], file=sys.stderr)
        return 1

    src = work / "helal.pdf"
    if not src.exists():
        print(f"ERROR: expected PDF not produced at {src}", file=sys.stderr)
        return 1
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != out_pdf:
        shutil.copyfile(src, out_pdf)
    print(f"  output      : {out_pdf}")

    if not args.keep:
        for ext in (".aux", ".log", ".out", ".fls", ".fdb_latexmk"):
            p = work / ("helal" + ext)
            if p.exists():
                p.unlink()

    if args.open:
        if sys.platform.startswith("win"):
            import os
            os.startfile(str(out_pdf))  # noqa
        elif sys.platform == "darwin":
            subprocess.run(["open", str(out_pdf)])
        else:
            subprocess.run(["xdg-open", str(out_pdf)])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
