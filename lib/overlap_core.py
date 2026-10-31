# SketchOverlapFinder - Fusion 360 add-in
# Copyright (C) 2026 ccatlett1984
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, version 3. It is distributed WITHOUT ANY WARRANTY; see
# the LICENSE file or <https://www.gnu.org/licenses/agpl-3.0.html>.
# SPDX-License-Identifier: AGPL-3.0-only

"""
Pure-Python geometry core for SketchOverlapFinder.

No Fusion imports here, so it can be unit tested outside Fusion 360.
All coordinates are 2D sketch-space values in Fusion internal units (cm).

Supported:
  * line / line   : duplicate, fully contained, partial collinear overlap
  * arc / circle  : duplicate, fully contained, partial overlap on the same circle
  * other curves  : (splines, ellipses, conics) exact duplicates only, by sampling
"""

import math
from dataclasses import dataclass, field

TWO_PI = 2.0 * math.pi

DUPLICATE = 'duplicate'
CONTAINED = 'contained'
PARTIAL = 'partial'


@dataclass
class Prim:
    kind: str                 # 'line' | 'arc' | 'sampled'
    data: tuple
    bbox: tuple               # (minx, miny, maxx, maxy)
    is_ref: bool = False
    is_constr: bool = False


@dataclass
class Finding:
    a: int                    # index into prims
    b: int
    kind: str                 # DUPLICATE | CONTAINED | PARTIAL
    length: float             # overlapping length
    inner: int = -1           # for CONTAINED: index of the fully covered curve
    regions: list = field(default_factory=list)
    # regions: ('line', p0, p1) | ('arc', center, r, start, sweep) | ('poly', [pts])


# --------------------------------------------------------------------------- builders

def make_line(p0, p1, is_ref=False, is_constr=False):
    bbox = (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))
    return Prim('line', (tuple(p0), tuple(p1)), bbox, is_ref, is_constr)


def make_arc(center, r, start, sweep, is_ref=False, is_constr=False):
    """Counter-clockwise arc from `start` (radians) through `sweep` (0, 2pi]."""
    cx, cy = center
    bbox = (cx - r, cy - r, cx + r, cy + r)
    sweep = min(sweep, TWO_PI)
    return Prim('arc', ((cx, cy), r, start % TWO_PI, sweep), bbox, is_ref, is_constr)


def make_circle(center, r, is_ref=False, is_constr=False):
    return make_arc(center, r, 0.0, TWO_PI, is_ref, is_constr)


def _ang(center, p):
    return math.atan2(p[1] - center[1], p[0] - center[0]) % TWO_PI


def _ccw(a, b):
    """CCW angular distance from a to b, in [0, 2pi)."""
    return (b - a) % TWO_PI


def arc_from_points(center, r, p_start, p_mid, p_end, is_ref=False, is_constr=False):
    """Build an arc from start/mid/end points regardless of its direction."""
    a_s, a_m, a_e = _ang(center, p_start), _ang(center, p_mid), _ang(center, p_end)
    if _ccw(a_s, a_m) <= _ccw(a_s, a_e):
        start, sweep = a_s, _ccw(a_s, a_e)
    else:
        start, sweep = a_e, _ccw(a_e, a_s)
    if sweep <= 0.0:
        sweep = TWO_PI
    return make_arc(center, r, start, sweep, is_ref, is_constr)


def make_sampled(points, is_ref=False, is_constr=False):
    pts = [tuple(p) for p in points]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return Prim('sampled', tuple(pts), (min(xs), min(ys), max(xs), max(ys)), is_ref, is_constr)


# --------------------------------------------------------------------------- helpers

def _dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _close(p, q, tol):
    return _dist(p, q) <= tol


def _poly_len(pts):
    return sum(_dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def circ_overlap(s1, w1, s2, w2):
    """Overlapping angular intervals of two CCW arcs. Returns [(start, sweep), ...]."""
    s1 %= TWO_PI
    s2 %= TWO_PI
    w1 = min(w1, TWO_PI)
    w2 = min(w2, TWO_PI)
    out = []
    for k in (-1, 0, 1):
        lo = max(s1, s2 + k * TWO_PI)
        hi = min(s1 + w1, s2 + w2 + k * TWO_PI)
        if hi > lo:
            out.append((lo % TWO_PI, hi - lo))
    return out


# --------------------------------------------------------------------------- pair tests

def _line_line(ia, A, ib, B, tol, sin_ang):
    a0, a1 = A.data
    b0, b1 = B.data
    la = _dist(a0, a1)
    lb = _dist(b0, b1)
    if la <= tol or lb <= tol:
        return None
    ux, uy = (a1[0] - a0[0]) / la, (a1[1] - a0[1]) / la
    vx, vy = (b1[0] - b0[0]) / lb, (b1[1] - b0[1]) / lb

    # parallel?
    if abs(ux * vy - uy * vx) > sin_ang:
        return None

    # collinear? (perpendicular offsets, checked both ways for symmetry)
    def perp(p, o, dx, dy):
        return abs((p[0] - o[0]) * dy - (p[1] - o[1]) * dx)

    if perp(b0, a0, ux, uy) > tol or perp(b1, a0, ux, uy) > tol:
        return None
    if perp(a0, b0, vx, vy) > tol or perp(a1, b0, vx, vy) > tol:
        return None

    t0 = (b0[0] - a0[0]) * ux + (b0[1] - a0[1]) * uy
    t1 = (b1[0] - a0[0]) * ux + (b1[1] - a0[1]) * uy
    lo, hi = min(t0, t1), max(t0, t1)
    o0, o1 = max(0.0, lo), min(la, hi)
    overlap = o1 - o0
    if overlap <= tol:
        return None          # disjoint or just touching end-to-end

    region = ('line', (a0[0] + ux * o0, a0[1] + uy * o0), (a0[0] + ux * o1, a0[1] + uy * o1))

    dup = (_close(a0, b0, tol) and _close(a1, b1, tol)) or \
          (_close(a0, b1, tol) and _close(a1, b0, tol))
    if dup:
        return Finding(ia, ib, DUPLICATE, overlap, regions=[region])
    if lo >= -tol and hi <= la + tol:
        return Finding(ia, ib, CONTAINED, overlap, inner=ib, regions=[region])
    if lo <= tol and hi >= la - tol:
        return Finding(ia, ib, CONTAINED, overlap, inner=ia, regions=[region])
    return Finding(ia, ib, PARTIAL, overlap, regions=[region])


def _arc_arc(ia, A, ib, B, tol):
    c1, r1, s1, w1 = A.data
    c2, r2, s2, w2 = B.data
    if _dist(c1, c2) > tol or abs(r1 - r2) > tol:
        return None
    r = 0.5 * (r1 + r2)
    c = ((c1[0] + c2[0]) * 0.5, (c1[1] + c2[1]) * 0.5)
    ivals = circ_overlap(s1, w1, s2, w2)
    overlap = sum(w for _, w in ivals) * r
    if overlap <= tol:
        return None
    regions = [('arc', c, r, s, w) for s, w in ivals]
    a_covered = w1 * r1 - overlap <= tol
    b_covered = w2 * r2 - overlap <= tol
    if a_covered and b_covered:
        return Finding(ia, ib, DUPLICATE, overlap, regions=regions)
    if a_covered:
        return Finding(ia, ib, CONTAINED, overlap, inner=ia, regions=regions)
    if b_covered:
        return Finding(ia, ib, CONTAINED, overlap, inner=ib, regions=regions)
    return Finding(ia, ib, PARTIAL, overlap, regions=regions)


def _sampled_dup(ia, A, ib, B, tol):
    pa, pb = A.data, B.data
    if len(pa) != len(pb):
        return None
    fwd = all(_close(p, q, tol) for p, q in zip(pa, pb))
    rev = not fwd and all(_close(p, q, tol) for p, q in zip(pa, reversed(pb)))
    if fwd or rev:
        return Finding(ia, ib, DUPLICATE, _poly_len(pa), regions=[('poly', list(pa))])
    return None


def check_pair(ia, A, ib, B, tol, sin_ang):
    if A.kind == 'line' and B.kind == 'line':
        return _line_line(ia, A, ib, B, tol, sin_ang)
    if A.kind == 'arc' and B.kind == 'arc':
        return _arc_arc(ia, A, ib, B, tol)
    if A.kind == 'sampled' and B.kind == 'sampled':
        return _sampled_dup(ia, A, ib, B, tol)
    return None   # line/arc etc. can only touch, never overlap along a length


# --------------------------------------------------------------------------- main entry

def find_overlaps(prims, tol, ang_tol_rad):
    """Return a list of Finding for every overlapping pair (sweep-and-prune on X)."""
    sin_ang = math.sin(max(ang_tol_rad, 0.0))
    order = sorted(range(len(prims)), key=lambda i: prims[i].bbox[0])
    found = []
    for n, i in enumerate(order):
        A = prims[i]
        for j in order[n + 1:]:
            B = prims[j]
            if B.bbox[0] > A.bbox[2] + tol:
                break
            if B.bbox[1] > A.bbox[3] + tol or B.bbox[3] < A.bbox[1] - tol:
                continue
            if A.is_ref and B.is_ref:
                continue        # two projected curves - nothing the user can fix
            ia, ib = (i, j) if i < j else (j, i)
            f = check_pair(ia, prims[ia], ib, prims[ib], tol, sin_ang)
            if f:
                found.append(f)
    rank = {DUPLICATE: 0, CONTAINED: 1, PARTIAL: 2}
    found.sort(key=lambda f: (rank[f.kind], f.a, f.b))
    return found


def plan_removals(findings, prims, scores, remove_duplicates, remove_contained):
    """
    Choose which curves to delete. Never removes projected/reference curves.
    Duplicates: drop the construction one first, then the one with fewer
    constraints/dimensions (`scores`), then the newer one (higher index).
    Contained: drop the covered (inner) curve.
    """
    removed = set()
    for f in findings:
        if f.a in removed or f.b in removed:
            continue
        victim = None
        if f.kind == DUPLICATE and remove_duplicates:
            cands = [x for x in (f.a, f.b) if not prims[x].is_ref]
            if cands:
                victim = min(cands, key=lambda x: (not prims[x].is_constr, scores[x], -x))
        elif f.kind == CONTAINED and remove_contained:
            if not prims[f.inner].is_ref:
                victim = f.inner
        if victim is not None:
            removed.add(victim)
    return removed
