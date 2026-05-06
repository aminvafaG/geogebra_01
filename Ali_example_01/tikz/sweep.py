#!/usr/bin/env python3
"""
sweep.py - Vary one slider in a .ggb across a range, regenerating geometry
and a PDF for each value.

USAGE
-----
    python sweep.py FILE.ggb SLIDER START:STEP:STOP [-o OUT_DIR] [--unit deg|rad]

EXAMPLE
-------
    python sweep.py ../Final_Helal_1404_BSe_BMo.ggb Arz 0:10:90 -o sweep_Arz/

For each value v in the matlab-style range, the script:
  1. Re-evaluates the .ggb construction with SLIDER = v (the dependent
     points/lines are recomputed in Python from the <command> tree).
  2. Writes a new .ggb (zip) with the updated cached coordinates.
  3. Extracts the modified geogebra.xml alongside it.
  4. Invokes ggb2pdf.py to render a vector PDF.

Implementation notes
--------------------
The interpreter only covers the GGB primitives used by this specific
construction (17 commands, 37 distinct (name, input-type) signatures).
Unknown commands fall back to the cached value already in the .ggb, which
is fine for objects that don't depend on the swept slider.

Only the cached coordinates that ggb2pdf.py reads back are updated:
  - <element type="point3d">'s <coords x y z w>
  - <element type="point">'s   <coords x y z>
  - <element type="line3d|ray3d">'s <coords ox oy oz ow vx vy vz vw>

Conic / segment / vector cached coords are left as-is (ggb2pdf.py
recomputes them from the points it reads).
"""
from __future__ import annotations
import argparse
import io
import math
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

try:
    from PIL import Image as _PILImage
    _PILLOW = True
except ImportError:
    _PILLOW = False


# ============================================================================
# Geometry types
# ============================================================================
class Point3D:
    __slots__ = ("x", "y", "z")
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z
    def tup(self): return (self.x, self.y, self.z)


class Point2D:
    __slots__ = ("x", "y")
    def __init__(self, x, y): self.x, self.y = x, y
    def tup3(self): return (self.x, self.y, 0.0)


class Vector3D:
    __slots__ = ("x", "y", "z")
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z
    def tup(self): return (self.x, self.y, self.z)


class Line3D:
    """Line through point P with direction d (not necessarily unit)."""
    __slots__ = ("P", "d")
    def __init__(self, P, d): self.P = P; self.d = d


class Ray3D(Line3D): pass


class Plane3D:
    """{ X : n . X = c }."""
    __slots__ = ("n", "c")
    def __init__(self, n, c): self.n = n; self.c = c


class Sphere:
    __slots__ = ("C", "r")
    def __init__(self, C, r): self.C = C; self.r = r


class Circle3D:
    """Circle in 3D: center C, plane normal n (unit), radius r."""
    __slots__ = ("C", "n", "r")
    def __init__(self, C, n, r): self.C = C; self.n = n; self.r = r


class Segment3D:
    __slots__ = ("A", "B")
    def __init__(self, A, B): self.A = A; self.B = B


class Number:
    __slots__ = ("v",)
    def __init__(self, v): self.v = float(v)


# ============================================================================
# Vector helpers (operate on 3-tuples)
# ============================================================================
def T(p):
    """Coerce a Point3D / Point2D / Vector3D / 3-tuple to (x, y, z)."""
    if isinstance(p, Point3D) or isinstance(p, Vector3D):
        return (p.x, p.y, p.z)
    if isinstance(p, Point2D):
        return (p.x, p.y, 0.0)
    return (p[0], p[1], p[2])

def add(a, b): a, b = T(a), T(b); return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
def sub(a, b): a, b = T(a), T(b); return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def scl(a, s): a = T(a); return (a[0]*s, a[1]*s, a[2]*s)
def dot(a, b): a, b = T(a), T(b); return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]
def crs(a, b):
    a, b = T(a), T(b)
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def nrm(a): a = T(a); return math.sqrt(a[0]**2 + a[1]**2 + a[2]**2)
def unit(a):
    n = nrm(a)
    return scl(a, 1.0/n) if n > 1e-15 else (0.0, 0.0, 0.0)


# ============================================================================
# Built-in axes (GGB constants)
# ============================================================================
def builtin(name):
    if name == "xAxis": return Line3D((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    if name == "yAxis": return Line3D((0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    if name == "zAxis": return Line3D((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
    return None


# ============================================================================
# GGB command implementations
# ============================================================================
# All commands return a typed object (Point3D / Line3D / Plane3D / ...).
# Variant dispatch is by isinstance() inside each function.

def cmd_Point(arg):
    """Point[zAxis] etc. — a free point ON an axis. We don't know where the
    user dragged it, so the caller seeds this from the element's cached
    <coords>. Returning None signals 'use cache'."""
    return None


def cmd_Sphere(C, on):
    """Sphere through `on`, centered at C."""
    r = nrm(sub(on, C))
    return Sphere(T(C), r)


def cmd_Plane(obj):
    """Plane[conic] -> the conic's supporting plane.

    For our circles we keep `n` (plane normal) and a point `C` (center) so
    the plane equation is n · X = n · C.
    """
    if isinstance(obj, Circle3D):
        return Plane3D(unit(obj.n), dot(obj.n, obj.C))
    raise TypeError(f"Plane: unsupported input {type(obj).__name__}")


def cmd_OrthogonalLine(P, plane):
    """Line through P perpendicular to plane."""
    return Line3D(T(P), unit(plane.n))


def cmd_OrthogonalPlane(P, line):
    """Plane through P perpendicular to line."""
    n = unit(line.d)
    return Plane3D(n, dot(n, T(P)))


def cmd_Line(A, B):
    """Line through two points (or two-point variants)."""
    a, b = T(A), T(B)
    return Line3D(a, sub(b, a))


def cmd_Ray(A, B):
    a, b = T(A), T(B)
    return Ray3D(a, sub(b, a))


def cmd_Segment(A, B):
    return Segment3D(T(A), T(B))


def cmd_Vector(A, B):
    """Vector[A, B] = B - A."""
    d = sub(B, A)
    return Vector3D(*d)


def cmd_Mirror(obj, center):
    """Point reflection of obj through center point."""
    cx = T(center)
    if isinstance(obj, (Point3D, Point2D)):
        p = T(obj)
        return Point3D(2*cx[0]-p[0], 2*cx[1]-p[1], 2*cx[2]-p[2])
    if isinstance(obj, Circle3D):
        # Reflect center; flip normal sign (so traversal sense is mirrored).
        c = T(obj.C)
        Cnew = (2*cx[0]-c[0], 2*cx[1]-c[1], 2*cx[2]-c[2])
        return Circle3D(Cnew, scl(obj.n, -1.0), obj.r)
    raise TypeError(f"Mirror: unsupported input {type(obj).__name__}")


def cmd_Rotate(obj, angle, axis):
    """Rotate point or circle around axis (line or point) by angle (radians)."""
    if isinstance(angle, Number):
        a = angle.v
    else:
        a = float(angle)
    # Axis: either a Line3D, a built-in axis name (already resolved), or
    # something else (we treat it as a Line3D).
    if isinstance(axis, Line3D):
        ax_pt = axis.P
        ax_dir = unit(axis.d)
    else:
        raise TypeError(f"Rotate: axis must be Line3D, got {type(axis).__name__}")

    def rot_point(P):
        # Translate so axis passes through origin.
        Q = sub(P, ax_pt)
        n = ax_dir
        c, s = math.cos(a), math.sin(a)
        cp = crs(n, Q)
        nd = dot(n, Q)
        Rq = (Q[0]*c + cp[0]*s + n[0]*nd*(1-c),
              Q[1]*c + cp[1]*s + n[1]*nd*(1-c),
              Q[2]*c + cp[2]*s + n[2]*nd*(1-c))
        return add(Rq, ax_pt)

    if isinstance(obj, (Point3D, Point2D)):
        x, y, z = rot_point(T(obj))
        return Point3D(x, y, z)
    if isinstance(obj, Circle3D):
        Cnew = rot_point(T(obj.C))
        # Rotate the normal too. Translation cancels for direction vectors:
        n = obj.n
        c, s = math.cos(a), math.sin(a)
        cp = crs(ax_dir, n)
        nd = dot(ax_dir, n)
        nnew = (n[0]*c + cp[0]*s + ax_dir[0]*nd*(1-c),
                n[1]*c + cp[1]*s + ax_dir[1]*nd*(1-c),
                n[2]*c + cp[2]*s + ax_dir[2]*nd*(1-c))
        return Circle3D(Cnew, nnew, obj.r)
    raise TypeError(f"Rotate: unsupported input {type(obj).__name__}")


def _circle_from_3pts(P1, P2, P3):
    """Return Circle3D through the three points (None if collinear)."""
    p1, p2, p3 = T(P1), T(P2), T(P3)
    v1 = sub(p2, p1); v2 = sub(p3, p1)
    nv = crs(v1, v2)
    if nrm(nv) < 1e-12:
        return None
    n = unit(nv)
    a = nrm(sub(p2, p3)); b = nrm(sub(p3, p1)); c = nrm(sub(p1, p2))
    a2, b2, c2 = a*a, b*b, c*c
    w1 = a2*(b2 + c2 - a2)
    w2 = b2*(a2 + c2 - b2)
    w3 = c2*(a2 + b2 - c2)
    sw = w1 + w2 + w3
    if abs(sw) < 1e-12:
        return None
    C = ((w1*p1[0]+w2*p2[0]+w3*p3[0])/sw,
         (w1*p1[1]+w2*p2[1]+w3*p3[1])/sw,
         (w1*p1[2]+w2*p2[2]+w3*p3[2])/sw)
    r = nrm(sub(p1, C))
    return Circle3D(C, n, r)


def cmd_Circle(*args):
    """Circle has 3 variants in this file:
        Circle[P1, P2, P3]                — 3 points
        Circle[line, point]               — axis line + point on the circle
        Circle[P1, P2, literal]           — same as 3 points (3rd is inline)
    """
    if len(args) == 3 and all(isinstance(a, (Point3D, Point2D)) for a in args):
        return _circle_from_3pts(*args)
    if len(args) == 2 and isinstance(args[0], Line3D) and isinstance(args[1], (Point3D, Point2D)):
        line, P = args
        ax = unit(line.d)
        # Project P onto the axis; that's the center.
        rel = sub(P, line.P)
        t = dot(rel, ax)
        C = add(line.P, scl(ax, t))
        r = nrm(sub(P, C))
        return Circle3D(C, ax, r)
    raise TypeError(f"Circle: bad args {[type(a).__name__ for a in args]}")


def cmd_CircleArc(C, A, B):
    """Circle arc with center C, from A to B (CCW around plane normal)."""
    # We just return the underlying circle (ggb2pdf.py recomputes arcs).
    return _circle_from_3pts(C, A, B)  # close enough for our writeback needs


def cmd_CircumcircleArc(A, B, C):
    return _circle_from_3pts(A, B, C)


def _intersect_line_plane(line, plane):
    """Return parametric t and the resulting point, or None."""
    n = plane.n
    d = line.d
    nd = dot(n, d)
    if abs(nd) < 1e-15:
        return None
    t = (plane.c - dot(n, line.P)) / nd
    return add(line.P, scl(d, t))


def _intersect_circle_circle(c1, c2, idx):
    """Two circles in 3D, possibly in different planes. We need their
    intersection; for our use case (zodiac construction) the two circles
    *do* intersect at two points. Idx ∈ {1, 2} chooses which.

    Implementation: find the line of intersection of the two circles' planes,
    then intersect with circle 1.
    """
    n1, n2 = unit(c1.n), unit(c2.n)
    d = crs(n1, n2)
    if nrm(d) < 1e-12:
        # Coplanar circles
        return _intersect_coplanar_circles(c1, c2, idx)
    # Find a point on both planes.
    # Solve: n1 . X = n1 . C1, n2 . X = n2 . C2, X . d = 0
    # Use 3x3 linear system.
    a11, a12, a13 = n1[0], n1[1], n1[2]
    a21, a22, a23 = n2[0], n2[1], n2[2]
    a31, a32, a33 = d[0],  d[1],  d[2]
    b1 = dot(n1, c1.C); b2 = dot(n2, c2.C); b3 = 0.0
    M = [[a11, a12, a13, b1],
         [a21, a22, a23, b2],
         [a31, a32, a33, b3]]
    P0 = _solve3(M)
    if P0 is None:
        return None
    # Intersect line {P0 + s*d} with circle c1: project onto c1's plane
    # and solve |P0 + s*d - C1|^2 = r1^2.
    e = sub(P0, c1.C)
    A = dot(d, d)
    B = 2*dot(d, e)
    Cv = dot(e, e) - c1.r*c1.r
    disc = B*B - 4*A*Cv
    if disc < 0:
        return None
    sq = math.sqrt(disc)
    s1 = (-B - sq)/(2*A); s2 = (-B + sq)/(2*A)
    # GGB's idx=1 corresponds to the larger-s root in our parametrization
    # (empirical, matched against Intersect[C_ofogh, C_Mentaghe, 1]->Ghareb).
    s = s2 if idx == 1 else s1
    P = add(P0, scl(d, s))
    return Point3D(*P)


def _intersect_coplanar_circles(c1, c2, idx):
    """Two coplanar circles in 3D, intersected in 2D by reducing to the
    common plane."""
    # Build 2D basis in c1's plane, write c2's center in those coords.
    n = unit(c1.n)
    if abs(n[2]) < 0.99:
        u = unit(crs(n, (0, 0, 1)))
    else:
        u = unit(crs(n, (1, 0, 0)))
    v = crs(n, u)
    def to2d(P): rel = sub(P, c1.C); return (dot(rel, u), dot(rel, v))
    cx, cy = to2d(c2.C)
    d = math.hypot(cx, cy)
    if d < 1e-12 or d > c1.r + c2.r + 1e-9 or d < abs(c1.r - c2.r) - 1e-9:
        return None
    # Standard two-circle intersection in 2D
    aa = (c1.r*c1.r - c2.r*c2.r + d*d) / (2*d)
    h2 = c1.r*c1.r - aa*aa
    if h2 < 0:
        h2 = 0
    h = math.sqrt(h2)
    # Midpoint along center line
    ux, uy = cx/d, cy/d
    px, py = ux*aa, uy*aa
    # Perpendicular offset (+/- h)
    nx, ny = -uy*h, ux*h
    if idx == 1:
        x2, y2 = px + nx, py + ny
    else:
        x2, y2 = px - nx, py - ny
    P = add(c1.C, add(scl(u, x2), scl(v, y2)))
    return Point3D(*P)


def _intersect_line_sphere(line, sph, want_two=False):
    """Intersect a line with a sphere. Returns a list of Point3D."""
    e = sub(line.P, sph.C)
    A = dot(line.d, line.d)
    B = 2*dot(line.d, e)
    C = dot(e, e) - sph.r*sph.r
    disc = B*B - 4*A*C
    if disc < 0:
        return []
    sq = math.sqrt(disc)
    s1 = (-B - sq)/(2*A); s2 = (-B + sq)/(2*A)
    P1 = Point3D(*add(line.P, scl(line.d, s1)))
    P2 = Point3D(*add(line.P, scl(line.d, s2)))
    return [P1, P2]


def _intersect_segment_sphere(seg, sph):
    """Pick the segment intersection inside [0,1] parametric range."""
    line = Line3D(seg.A, sub(seg.B, seg.A))
    e = sub(line.P, sph.C)
    A = dot(line.d, line.d)
    B = 2*dot(line.d, e)
    C = dot(e, e) - sph.r*sph.r
    disc = B*B - 4*A*C
    if disc < 0:
        return None
    sq = math.sqrt(disc)
    for s in ((-B - sq)/(2*A), (-B + sq)/(2*A)):
        if -1e-9 <= s <= 1 + 1e-9:
            return Point3D(*add(line.P, scl(line.d, s)))
    return None


def _intersect_ray_sphere(ray, sph):
    """Pick the ray intersection with t >= 0 (closest first)."""
    e = sub(ray.P, sph.C)
    A = dot(ray.d, ray.d)
    B = 2*dot(ray.d, e)
    C = dot(e, e) - sph.r*sph.r
    disc = B*B - 4*A*C
    if disc < 0:
        return None
    sq = math.sqrt(disc)
    s1 = (-B - sq)/(2*A); s2 = (-B + sq)/(2*A)
    for s in sorted([s1, s2]):
        if s >= -1e-9:
            return Point3D(*add(ray.P, scl(ray.d, s)))
    return None


def _intersect_plane_sphere(plane, sph):
    """Plane ∩ sphere -> Circle3D (or None)."""
    n = unit(plane.n)
    # Distance from sphere center to plane:
    sd = dot(n, T(sph.C)) - plane.c
    if abs(sd) > sph.r:
        return None
    C = sub(sph.C, scl(n, sd))
    r = math.sqrt(max(0.0, sph.r*sph.r - sd*sd))
    return Circle3D(C, n, r)


def cmd_Intersect(*args):
    """All Intersect variants in this file:
        Intersect[conic, conic, idx]
        Intersect[conic, conic]            (returns 2 points)
        Intersect[line, quadric]           (returns 2 points)
        Intersect[line, plane]             (1 point)
        Intersect[segment, quadric]        (1 point)
        Intersect[ray, quadric]            (1 point)
    """
    a = args[0]; b = args[1]
    idx = None
    if len(args) >= 3 and isinstance(args[2], Number):
        idx = int(args[2].v)
    elif len(args) >= 3:
        try: idx = int(args[2])
        except (TypeError, ValueError): idx = None

    if isinstance(a, Circle3D) and isinstance(b, Circle3D):
        if idx is None:
            # Two-output form: caller will assign both, in idx 1, 2 order.
            P1 = _intersect_circle_circle(a, b, 1)
            P2 = _intersect_circle_circle(a, b, 2)
            return (P1, P2)
        return _intersect_circle_circle(a, b, idx)
    # Ray3D is a Line3D subclass — check it FIRST so the ray-specific
    # root selection (smallest s ≥ 0) wins over the generic line variant.
    if isinstance(a, Ray3D) and isinstance(b, Sphere):
        return _intersect_ray_sphere(a, b)
    if isinstance(a, Line3D) and isinstance(b, Sphere):
        pts = _intersect_line_sphere(a, b)
        return tuple(pts) if len(pts) == 2 else (None, None)
    if isinstance(a, Line3D) and isinstance(b, Plane3D):
        P = _intersect_line_plane(a, b)
        return Point3D(*P) if P is not None else None
    if isinstance(a, Segment3D) and isinstance(b, Sphere):
        return _intersect_segment_sphere(a, b)
    if isinstance(a, Plane3D) and isinstance(b, Sphere):
        return _intersect_plane_sphere(a, b)
    raise TypeError(f"Intersect: unhandled types ({type(a).__name__}, {type(b).__name__})")


def cmd_IntersectPath(plane, q):
    """IntersectPath[plane, sphere] -> Circle3D."""
    if isinstance(plane, Plane3D) and isinstance(q, Sphere):
        return _intersect_plane_sphere(plane, q)
    raise TypeError(f"IntersectPath: unhandled ({type(plane).__name__}, {type(q).__name__})")


def cmd_Distance(A, B):
    return Number(nrm(sub(A, B)))


def cmd_Angle(*args):
    """Angle[v1, v2] or Angle[A, vertex, B]."""
    if len(args) == 2 and all(isinstance(a, Vector3D) for a in args):
        u, v = T(args[0]), T(args[1])
        nu, nv = nrm(u), nrm(v)
        if nu < 1e-15 or nv < 1e-15:
            return Number(0.0)
        cosA = max(-1.0, min(1.0, dot(u, v)/(nu*nv)))
        return Number(math.acos(cosA))
    if len(args) == 3:
        A, V, B = T(args[0]), T(args[1]), T(args[2])
        u, v = sub(A, V), sub(B, V)
        nu, nv = nrm(u), nrm(v)
        if nu < 1e-15 or nv < 1e-15:
            return Number(0.0)
        cosA = max(-1.0, min(1.0, dot(u, v)/(nu*nv)))
        return Number(math.acos(cosA))
    raise TypeError(f"Angle: bad args")


def cmd_Sequence(*args):
    """Sequence[expr, var, lo, hi, step] - we don't need this for ggb2pdf
    output (the script computes zodiac dots itself), so return None."""
    return None


def cmd_If(*args):
    """If[cond, then] or If[cond, then, else].

    `cond` may be a Python bool (from a comparison) or a Number (treated as
    truthy when nonzero). Anything else falls back to None (preserve cache).
    """
    if not args:
        return None
    cond = args[0]
    if isinstance(cond, bool):
        c = cond
    elif isinstance(cond, Number):
        c = (cond.v != 0.0)
    else:
        return None
    if c:
        return args[1] if len(args) > 1 else None
    return args[2] if len(args) > 2 else None


CMD = {
    "Point": cmd_Point,
    "Sphere": cmd_Sphere,
    "Plane": cmd_Plane,
    "OrthogonalLine": cmd_OrthogonalLine,
    "OrthogonalPlane": cmd_OrthogonalPlane,
    "Line": cmd_Line,
    "Ray": cmd_Ray,
    "Segment": cmd_Segment,
    "Vector": cmd_Vector,
    "Mirror": cmd_Mirror,
    "Rotate": cmd_Rotate,
    "Circle": cmd_Circle,
    "CircleArc": cmd_CircleArc,
    "CircumcircleArc": cmd_CircumcircleArc,
    "Intersect": cmd_Intersect,
    "IntersectPath": cmd_IntersectPath,
    "Distance": cmd_Distance,
    "Angle": cmd_Angle,
    "Sequence": cmd_Sequence,
    "If": cmd_If,
}


def _solve3(M):
    """Solve a 3x4 augmented system; return tuple or None if singular."""
    # Plain Gaussian elimination with partial pivoting.
    A = [row[:] for row in M]
    for i in range(3):
        # Pivot
        pi = max(range(i, 3), key=lambda r: abs(A[r][i]))
        if abs(A[pi][i]) < 1e-15:
            return None
        A[i], A[pi] = A[pi], A[i]
        for r in range(i+1, 3):
            f = A[r][i] / A[i][i]
            for c in range(i, 4):
                A[r][c] -= f * A[i][c]
    x = [0.0, 0.0, 0.0]
    for i in (2, 1, 0):
        s = A[i][3] - sum(A[i][c]*x[c] for c in range(i+1, 3))
        x[i] = s / A[i][i]
    return tuple(x)


# ============================================================================
# Inline expression evaluator
# ============================================================================
# GGB inputs may be either bare identifiers or inline expressions like:
#   (-Taghvim)
#   (1.2 * Sp)
#   Mirror[Ghamar, A]
#   Intersect[C_Mentaghe, C_ofoghTaksiryGhamar, 2]
#   23.5°
#   1
#   yAxis
#   (-9°)
#   (-(k°))
# Identifiers may contain letters, digits, underscores, single quotes,
# and braces (e.g. W'_{1}).

ID_RE = re.compile(r"^[^\W\d][\w'{}]*$")  # unicode letters allowed (e.g. θ_signed, α, β)


def _split_top(s, seps):
    """Split s at top-level (not inside [] or ()) occurrences of any sep
    in `seps`. Returns list of substrings, preserving the seps as separate
    items so callers can fold left-associatively."""
    out, buf = [], []
    depth = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in "([":
            depth += 1; buf.append(ch)
        elif ch in ")]":
            depth -= 1; buf.append(ch)
        elif depth == 0 and ch in seps:
            # Reject leading '-' (unary): only when nothing non-whitespace
            # has been emitted into the current buf yet. The previous check
            # only inspected buf[-1], which mis-fired on `360 - X` (the
            # trailing space made it look like a unary minus).
            if ch == '-' and "".join(buf).strip() == '':
                buf.append(ch)
            else:
                out.append("".join(buf)); out.append(ch); buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out


def _split_args(argstr):
    """Split a comma-separated argument list at top-level commas."""
    out, buf = [], []
    depth = 0
    for ch in argstr:
        if ch in "([": depth += 1; buf.append(ch)
        elif ch in ")]": depth -= 1; buf.append(ch)
        elif ch == ',' and depth == 0:
            out.append("".join(buf).strip()); buf = []
        else:
            buf.append(ch)
    if buf: out.append("".join(buf).strip())
    return out


def _strip_outer(s):
    s = s.strip()
    while s.startswith('(') and s.endswith(')'):
        depth = 0
        ok = True
        for i, ch in enumerate(s):
            if ch == '(': depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    ok = False
                    break
        if not ok:
            break
        s = s[1:-1].strip()
    return s


def eval_inline(expr, scene):
    """Evaluate a GGB inline expression string against the current scene."""
    expr = _strip_outer(expr)
    if not expr:
        return None

    # Built-in axes
    bi = builtin(expr)
    if bi is not None:
        return bi

    # Identifier (possibly with primes/braces)
    if ID_RE.match(expr):
        if expr in scene:
            return scene[expr]
        # Unknown identifier (free var like 'k' inside a Sequence body) -> 0
        return Number(0.0)

    # Function call: Name[args]   (also tolerate Name(args) just in case)
    m = re.match(r"^([A-Za-z][A-Za-z0-9_]*)\[(.*)\]$", expr)
    if m:
        # Make sure the closing `]` matches the opening one — otherwise
        # `Distance[X] ≥ Distance[Y]` would mis-parse as one Distance call
        # because `(.*)` is greedy.
        depth = 0
        ok = False
        for i, ch in enumerate(expr):
            if ch == '[': depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    ok = (i == len(expr) - 1)
                    break
        if not ok:
            m = None
    if not m:
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*)\((.*)\)$", expr)
        if m:
            # Make sure the closing paren matches the opening one (rule
            # out (a)(b) collisions).
            depth = 0
            ok = False
            for i, ch in enumerate(expr):
                if ch == '(': depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        ok = (i == len(expr) - 1)
                        break
            if not ok:
                m = None
    if m:
        fname, argstr = m.group(1), m.group(2)
        args = [eval_inline(a, scene) for a in _split_args(argstr)]
        if fname in CMD:
            return CMD[fname](*args)
        raise ValueError(f"unknown function {fname}")

    # Bare degree symbol — value of one degree in radians (π/180).
    # Lets `BoadMoaddal / °` evaluate as radians → degrees (BoadMoaddal_rad
    # divided by π/180 yields the value in degrees).
    if expr == '°':
        return Number(math.pi / 180.0)

    # Plain number
    try:
        return Number(float(expr))
    except ValueError:
        pass

    # Unary minus
    if expr.startswith('-'):
        v = eval_inline(expr[1:], scene)
        if isinstance(v, Number): return Number(-v.v)
        if isinstance(v, Point3D): return Point3D(-v.x, -v.y, -v.z)
        if isinstance(v, Vector3D): return Vector3D(-v.x, -v.y, -v.z)
        raise ValueError(f"can't negate {type(v).__name__}")

    # Comparison operators (lowest precedence, single comparison only).
    # Returns a Python bool — fed to cmd_If for branch selection.
    parts = _split_top(expr, "<>≤≥≠")
    if len(parts) >= 3:
        a = eval_inline(parts[0], scene)
        op = parts[1]
        b = eval_inline(parts[2], scene)
        return _apply_cmp(op, a, b)

    # Binary +, -, *, /, ⊗ (left-to-right, no precedence beyond what splitting gives)
    # We handle only the cases this construction needs: numeric * point, etc.
    parts = _split_top(expr, "+-")
    if len(parts) > 1:
        # Fold
        acc = eval_inline(parts[0], scene)
        i = 1
        while i < len(parts):
            op = parts[i]; rhs = eval_inline(parts[i+1], scene); i += 2
            acc = _apply_op(op, acc, rhs)
        return acc
    parts = _split_top(expr, "*/⊗")
    if len(parts) > 1:
        acc = eval_inline(parts[0], scene)
        i = 1
        while i < len(parts):
            op = parts[i]; rhs = eval_inline(parts[i+1], scene); i += 2
            acc = _apply_op(op, acc, rhs)
        return acc

    # Number with trailing degree sign (e.g. `23.5°` -> radians). Must come
    # AFTER the operator splits so `BoadMoaddal / °` isn't swallowed here.
    if expr.endswith('°'):
        body = expr[:-1].strip()
        v = eval_inline(body, scene)
        if isinstance(v, Number): return Number(math.radians(v.v))
        if isinstance(v, (int, float)): return Number(math.radians(float(v)))
        raise ValueError(f"can't apply ° to {v!r}")

    raise ValueError(f"can't evaluate inline expression: {expr!r}")


def _apply_cmp(op, a, b):
    """Evaluate a single comparison (<, >, ≤, ≥, ≠, =) on Numbers."""
    def _num(x):
        if isinstance(x, Number): return x.v
        if isinstance(x, (int, float)): return float(x)
        raise TypeError(f"comparison needs Number, got {type(x).__name__}")
    av, bv = _num(a), _num(b)
    if op == '<':  return av <  bv
    if op == '>':  return av >  bv
    if op == '≤':  return av <= bv
    if op == '≥':  return av >= bv
    if op == '=':  return av == bv
    if op == '≠':  return av != bv
    raise ValueError(f"unknown comparison op: {op!r}")


def _apply_op(op, a, b):
    """Apply one of +, -, *, / to mixed Number/Point/Vector operands."""
    def _pair(a, b):
        if isinstance(a, Number) and isinstance(b, Number):
            return ("nn", a.v, b.v)
        if isinstance(a, Number) and isinstance(b, (Point3D, Vector3D, Point2D)):
            return ("np", a.v, T(b))
        if isinstance(b, Number) and isinstance(a, (Point3D, Vector3D, Point2D)):
            return ("pn", T(a), b.v)
        if isinstance(a, (Point3D, Vector3D, Point2D)) and isinstance(b, (Point3D, Vector3D, Point2D)):
            return ("pp", T(a), T(b))
        return (None, a, b)

    kind, x, y = _pair(a, b)
    if kind == "nn":
        return Number({"+": x+y, "-": x-y, "*": x*y, "/": x/y if y else 0.0}[op])
    if kind == "np" and op == "*":
        return Point3D(*scl(y, x))
    if kind == "pn" and op == "*":
        return Point3D(*scl(x, y))
    if kind == "pn" and op == "/":
        return Point3D(*scl(x, 1.0/y if y else 0.0))
    if kind == "pp" and op == "+":
        return Point3D(*add(x, y))
    if kind == "pp" and op == "-":
        return Point3D(*sub(x, y))
    # Vector⊗Vector → cross product (vector). The "pp" kind covers
    # Vector3D ⊗ Vector3D in this construction (e.g. cross = u ⊗ v).
    if kind == "pp" and op == "⊗":
        return Vector3D(*crs(x, y))
    # Vector*Vector → dot product (scalar). GGB uses `*` between two
    # vectors to mean dot — e.g. `(cross * n) < 0` in If conditions.
    if kind == "pp" and op == "*" and isinstance(a, (Vector3D,)) and isinstance(b, (Vector3D,)):
        return Number(dot(x, y))
    raise TypeError(f"can't apply {op} to {type(a).__name__}, {type(b).__name__}")


# ============================================================================
# Construction loader
# ============================================================================
def parse_initial_value(el):
    """Read an <element>'s cached value into a typed object."""
    t = el.get("type")
    if t == "point3d":
        c = el.find("coords")
        if c is None: return None
        x = float(c.get("x")); y = float(c.get("y"))
        z = float(c.get("z", "0")); w = float(c.get("w", "1")) or 1.0
        return Point3D(x/w, y/w, z/w)
    if t == "point":
        c = el.find("coords")
        if c is None: return None
        x = float(c.get("x")); y = float(c.get("y"))
        zh = float(c.get("z", "1")) or 1.0
        return Point2D(x/zh, y/zh)
    if t == "line3d" or t == "ray3d":
        c = el.find("coords")
        if c is None: return None
        ox = float(c.get("ox", "0")); oy = float(c.get("oy", "0")); oz = float(c.get("oz", "0"))
        vx = float(c.get("vx", "0")); vy = float(c.get("vy", "0")); vz = float(c.get("vz", "0"))
        return (Line3D if t == "line3d" else Ray3D)((ox, oy, oz), (vx, vy, vz))
    if t in ("angle", "numeric"):
        v = el.find("value")
        if v is None: return Number(0.0)
        return Number(float(v.get("val", "0")))
    if t == "boolean":
        v = el.find("value")
        if v is None: return False
        return v.get("val") == "true"
    if t == "vector3d":
        c = el.find("coords")
        if c is None: return None
        return Vector3D(float(c.get("x", "0")), float(c.get("y", "0")), float(c.get("z", "0")))
    if t == "plane3d":
        c = el.find("coords")
        if c is None: return None
        a = float(c.get("a", "0")); b = float(c.get("b", "0"))
        cc = float(c.get("c", "0")); d = float(c.get("d", "0"))
        return Plane3D((a, b, cc), -d)  # ax+by+cz+d=0  ->  n.X = -d
    # Conics, quadrics, segments — not used as inputs to ggb2pdf.
    return None


def evaluate_construction(root, slider_overrides):
    """Walk <construction> and produce a label -> object dict.

    `slider_overrides` is {label: value}; values are in the SAME UNITS as
    the cached `<value val=...>` (radians for angle sliders).
    """
    scene = {}
    con = root.find("construction")
    if con is None:
        return scene

    # Pre-pass: seed every element from its cached value.
    for el in con:
        if el.tag != "element":
            continue
        lbl = el.get("label")
        v = parse_initial_value(el)
        if v is not None:
            scene[lbl] = v

    # Apply overrides (after seeding, so freshly-set values win over cache).
    for lbl, val in slider_overrides.items():
        if lbl in scene and isinstance(scene[lbl], Number):
            scene[lbl] = Number(val)
        else:
            scene[lbl] = Number(val)

    # Walk in document order; commands recompute outputs. <expression>
    # nodes are also handled so dependent vars (e.g. cross = u ⊗ v) follow
    # the swept slider — without this, anything that consumes `cross`
    # (like sign_{1} via the If condition) would use a stale cache.
    for node in con:
        if node.tag == "expression":
            lbl = node.get("label")
            exp = node.get("exp")
            if not lbl or not exp:
                continue
            try:
                result = eval_inline(exp, scene)
            except Exception:
                continue
            if result is not None:
                scene[lbl] = result
            continue
        if node.tag != "command":
            continue
        name = node.get("name")
        inp = node.find("input")
        out = node.find("output")
        if inp is None or out is None:
            continue
        in_keys = sorted(inp.attrib.keys())
        out_keys = sorted(out.attrib.keys())
        out_labels = [out.attrib[k] for k in out_keys if out.attrib[k]]

        # Resolve inputs (each may be identifier or inline expression).
        try:
            args = []
            for k in in_keys:
                raw = inp.attrib[k]
                if ID_RE.match(raw) and raw in scene:
                    args.append(scene[raw])
                else:
                    bi = builtin(raw)
                    if bi is not None:
                        args.append(bi)
                    else:
                        args.append(eval_inline(raw, scene))
        except Exception as e:
            # Fall back to cache for any output we can't recompute.
            continue

        if name not in CMD:
            continue
        try:
            result = CMD[name](*args)
        except Exception:
            continue

        # Distribute results to output labels.
        if isinstance(result, tuple):
            for lbl, val in zip(out_labels, result):
                if val is not None:
                    scene[lbl] = val
        else:
            if result is not None and out_labels:
                scene[out_labels[0]] = result

    return scene


# ============================================================================
# XML write-back
# ============================================================================
def write_back(root, scene):
    """Update the cached coords of point3d / point / line3d / ray3d
    elements from the freshly-computed scene."""
    for el in root.iter("element"):
        t = el.get("type"); lbl = el.get("label")
        v = scene.get(lbl)
        if v is None: continue
        c = el.find("coords")
        if t == "point3d" and isinstance(v, Point3D) and c is not None:
            c.set("x", f"{v.x:.15g}")
            c.set("y", f"{v.y:.15g}")
            c.set("z", f"{v.z:.15g}")
            c.set("w", "1.0")
        elif t == "point" and isinstance(v, (Point2D, Point3D)) and c is not None:
            xx = v.x; yy = v.y
            c.set("x", f"{xx:.15g}"); c.set("y", f"{yy:.15g}")
            if "z" in c.attrib: c.set("z", "1.0")
        elif t in ("line3d", "ray3d") and isinstance(v, Line3D) and c is not None:
            ox, oy, oz = v.P; vx, vy, vz = v.d
            c.set("ox", f"{ox:.15g}"); c.set("oy", f"{oy:.15g}"); c.set("oz", f"{oz:.15g}")
            if "ow" in c.attrib: c.set("ow", "1.0")
            c.set("vx", f"{vx:.15g}"); c.set("vy", f"{vy:.15g}"); c.set("vz", f"{vz:.15g}")
            if "vw" in c.attrib: c.set("vw", "0.0")
        elif t in ("angle", "numeric") and isinstance(v, Number):
            valuel = el.find("value")
            if valuel is not None:
                valuel.set("val", f"{v.v:.15g}")


# ============================================================================
# .ggb repackaging
# ============================================================================
def write_ggb(src_ggb: Path, new_xml_bytes: bytes, dst_ggb: Path):
    """Copy src_ggb to dst_ggb, replacing geogebra.xml with new_xml_bytes."""
    with zipfile.ZipFile(src_ggb, "r") as zin, \
         zipfile.ZipFile(dst_ggb, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename == "geogebra.xml":
                zout.writestr(item, new_xml_bytes)
            else:
                zout.writestr(item, zin.read(item.filename))


# ============================================================================
# PDF → JPEG rasteriser
# ============================================================================
def pdf_to_jpg(pdf_path: Path, jpg_path: Path, dpi: int = 150) -> bool:
    """Rasterise the first page of *pdf_path* and save it as JPEG.

    Pipeline: pdftoppm (Poppler/TeX Live) converts page → PNG in a temp
    directory; Pillow then reads the PNG and saves a JPEG.

    Returns True on success, False (with a printed message) on any failure.
    Requires Pillow: pip install Pillow
    """
    if not _PILLOW:
        print("  [JPG skipped — Pillow not installed in this environment: "
              "pip install Pillow]")
        return False

    pdftoppm_exe = shutil.which("pdftoppm")
    if pdftoppm_exe is None:
        print("  [JPG skipped — pdftoppm not found on PATH]")
        return False

    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "page"
        res = subprocess.run(
            [pdftoppm_exe, "-png", "-singlefile", "-r", str(dpi),
             str(pdf_path), str(prefix)],
            capture_output=True,
        )
        if res.returncode != 0:
            print(f"  [JPG failed — pdftoppm exited {res.returncode}]")
            return False
        png = Path(tmp) / "page.png"
        if not png.exists():
            print("  [JPG failed — pdftoppm produced no output]")
            return False
        _PILImage.open(png).convert("RGB").save(str(jpg_path), "JPEG", quality=95)
    return True


# ============================================================================
# Combined PDF
# ============================================================================
def merge_pdfs(pdf_paths: list[Path], out_path: Path) -> bool:
    """Concatenate *pdf_paths* (one page each) into a single multi-page PDF
    using pdfunite (ships with Poppler / TeX Live).

    Returns True on success.
    """
    pdfunite_exe = shutil.which("pdfunite")
    if pdfunite_exe is None:
        print("  [combined PDF skipped — pdfunite not found on PATH]")
        return False
    res = subprocess.run(
        [pdfunite_exe] + [str(p) for p in pdf_paths] + [str(out_path)],
        capture_output=True,
    )
    if res.returncode != 0:
        print(f"  [combined PDF failed — pdfunite exited {res.returncode}]")
        return False
    return True


# ============================================================================
# Range parsing
# ============================================================================
def parse_range(spec):
    """Matlab-style 'start:step:stop'. Returns a list of floats."""
    parts = [p.strip() for p in spec.split(':')]
    if len(parts) == 2:
        start, stop = float(parts[0]), float(parts[1]); step = 1.0
    elif len(parts) == 3:
        start, step, stop = float(parts[0]), float(parts[1]), float(parts[2])
    else:
        raise ValueError(f"bad range: {spec!r}")
    if step == 0:
        raise ValueError("step cannot be zero")
    out = []
    v = start
    n = 0
    while (step > 0 and v <= stop + 1e-9) or (step < 0 and v >= stop - 1e-9):
        out.append(v); n += 1
        if n > 100000: raise RuntimeError("range too large")
        v = start + n*step
    return out


# ============================================================================
# CLI
# ============================================================================
def main(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ggb", type=Path)
    ap.add_argument("slider", type=str, help="label of the slider to sweep (e.g. Arz)")
    ap.add_argument("range", type=str, help="matlab-style range: start:step:stop  (e.g. 0:10:90)")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="output directory (default: <slider>_sweep next to .ggb)")
    ap.add_argument("--unit", choices=("deg", "rad"), default="deg",
                    help="unit of the range values (default: deg, since GGB sliders are angles)")
    ap.add_argument("--no-pdf", action="store_true",
                    help="emit .ggb + .xml only; don't run ggb2pdf.py")
    ap.add_argument("--no-jpg", action="store_true",
                    help="skip JPEG generation even when a PDF is produced")
    ap.add_argument("--dpi", type=int, default=150,
                    help="rasterisation DPI for JPEG output (default: 150)")
    ap.add_argument("--no-merge", action="store_true",
                    help="skip the combined multi-page PDF at the end")
    args = ap.parse_args(argv)

    src = args.ggb.resolve()
    if not src.exists():
        print(f"ERROR: not found: {src}", file=sys.stderr); return 2

    out_dir = (args.out or src.parent / f"{args.slider}_sweep").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load
    with zipfile.ZipFile(src) as zf:
        xml_bytes = zf.read("geogebra.xml")
    root = ET.fromstring(xml_bytes.decode("utf-8"))
    # Confirm slider exists
    if not any(e.get("label") == args.slider for e in root.iter("element")):
        print(f"ERROR: no element labelled {args.slider!r} in {src}", file=sys.stderr)
        return 2

    values = parse_range(args.range)
    print(f"Sweeping {args.slider} over {len(values)} values: {values}")
    print(f"Output dir: {out_dir}")

    # Path to ggb2pdf.py (sibling)
    ggb2pdf = Path(__file__).resolve().parent / "ggb2pdf.py"

    fmt_v = "{:+07.2f}" if any(v < 0 for v in values) else "{:06.2f}"
    produced_pdfs: list[Path] = []

    for v in values:
        v_in_radians = math.radians(v) if args.unit == "deg" else v
        # Reload XML each iteration (writeback mutates ElementTree in-place).
        root = ET.fromstring(xml_bytes.decode("utf-8"))
        scene = evaluate_construction(root, {args.slider: v_in_radians})
        write_back(root, scene)

        new_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        tag = fmt_v.format(v).replace('+', 'p').replace('-', 'm').replace('.', '_')
        stem = f"{args.slider}_{tag}"
        ggb_out = out_dir / f"{stem}.ggb"
        xml_out = out_dir / f"{stem}.xml"

        write_ggb(src, new_xml, ggb_out)
        xml_out.write_bytes(new_xml)
        print(f"  {args.slider}={v:>7.3f} {args.unit} -> {ggb_out.name}", end="")

        if not args.no_pdf:
            pdf_out = out_dir / f"{stem}.pdf"
            cmd = [sys.executable, str(ggb2pdf), str(ggb_out), "-o", str(pdf_out)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                print(f"   [PDF FAILED]")
                print(res.stdout[-1500:] or "")
                print(res.stderr[-1500:] or "", file=sys.stderr)
                continue
            produced_pdfs.append(pdf_out)
            print(f", {pdf_out.name}", end="")
            if not args.no_jpg:
                jpg_out = out_dir / f"{stem}.jpg"
                if pdf_to_jpg(pdf_out, jpg_out, args.dpi):
                    print(f", {jpg_out.name}", end="")

        print()

    # Combined multi-page PDF
    if produced_pdfs and not args.no_pdf and not args.no_merge:
        combined = out_dir / f"{args.slider}_combined.pdf"
        print(f"\nMerging {len(produced_pdfs)} pages -> {combined.name} ...", end=" ")
        if merge_pdfs(produced_pdfs, combined):
            print("done")
        else:
            print("failed")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
