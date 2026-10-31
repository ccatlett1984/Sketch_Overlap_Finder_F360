# SketchOverlapFinder - Fusion 360 add-in
# Copyright (C) 2026 ccatlett1984
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, version 3. It is distributed WITHOUT ANY WARRANTY; see
# the LICENSE file or <https://www.gnu.org/licenses/agpl-3.0.html>.
# SPDX-License-Identifier: AGPL-3.0-only

"""Run with:  python tests/test_overlap_core.py   (no Fusion needed)"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
import overlap_core as c  # noqa: E402

TOL = 0.001          # 0.01 mm in cm
ANG = math.radians(0.01)


def run(prims):
    return c.find_overlaps(prims, TOL, ANG)


def one(prims, kind, inner=None):
    f = run(prims)
    assert len(f) == 1, f
    assert f[0].kind == kind, f[0]
    if inner is not None:
        assert f[0].inner == inner, f[0]
    return f[0]


def test_line_duplicate_same_and_reversed():
    one([c.make_line((0, 0), (5, 0)), c.make_line((0, 0), (5, 0))], c.DUPLICATE)
    one([c.make_line((0, 0), (5, 5)), c.make_line((5, 5), (0, 0))], c.DUPLICATE)


def test_line_duplicate_within_tolerance():
    one([c.make_line((0, 0), (5, 0)), c.make_line((0.0005, 0.0004), (5, -0.0003))], c.DUPLICATE)


def test_line_contained():
    f = one([c.make_line((0, 0), (10, 0)), c.make_line((2, 0), (4, 0))], c.CONTAINED, inner=1)
    assert abs(f.length - 2) < 1e-9
    one([c.make_line((3, 0), (4, 0)), c.make_line((0, 0), (10, 0))], c.CONTAINED, inner=0)
    # sharing one endpoint still counts as contained
    one([c.make_line((0, 0), (10, 0)), c.make_line((0, 0), (4, 0))], c.CONTAINED, inner=1)


def test_line_partial():
    f = one([c.make_line((0, 0), (6, 6)), c.make_line((4, 4), (9, 9))], c.PARTIAL)
    assert abs(f.length - 2 * math.sqrt(2)) < 1e-9
    (_, p0, p1), = f.regions
    assert c._close(p0, (4, 4), 1e-9) and c._close(p1, (6, 6), 1e-9)


def test_line_negatives():
    assert run([c.make_line((0, 0), (5, 0)), c.make_line((5, 0), (9, 0))]) == []      # end to end
    assert run([c.make_line((0, 0), (5, 0)), c.make_line((6, 0), (9, 0))]) == []      # collinear gap
    assert run([c.make_line((0, 0), (5, 0)), c.make_line((0, 0.01), (5, 0.01))]) == []  # parallel offset
    assert run([c.make_line((0, 0), (5, 0)), c.make_line((0, 0), (5, 0.5))]) == []    # angled
    assert run([c.make_line((0, 0), (5, 0)), c.make_line((2, -1), (2, 1))]) == []     # crossing


def test_vertical_lines_and_sweep():
    one([c.make_line((3, 0), (3, 10)), c.make_line((3, 2), (3, 20))], c.PARTIAL)


def test_both_reference_skipped():
    p = [c.make_line((0, 0), (5, 0), is_ref=True), c.make_line((0, 0), (5, 0), is_ref=True)]
    assert run(p) == []


def test_circles():
    one([c.make_circle((1, 1), 2), c.make_circle((1, 1), 2)], c.DUPLICATE)
    assert run([c.make_circle((1, 1), 2), c.make_circle((1, 1), 2.1)]) == []
    assert run([c.make_circle((1, 1), 2), c.make_circle((1.5, 1), 2)]) == []


def test_arc_in_circle():
    one([c.make_circle((0, 0), 1), c.make_arc((0, 0), 1, 1.0, 1.0)], c.CONTAINED, inner=1)


def test_arcs_partial_and_wrap():
    f = one([c.make_arc((0, 0), 1, 0.0, math.pi), c.make_arc((0, 0), 1, math.pi / 2, math.pi)], c.PARTIAL)
    assert abs(f.length - math.pi / 2) < 1e-9
    # interval crossing angle 0
    f = one([c.make_arc((0, 0), 1, 5.5, 1.5), c.make_arc((0, 0), 1, 0.2, 1.0)], c.PARTIAL)
    assert abs(f.length - (5.5 + 1.5 - 2 * math.pi - 0.2)) < 1e-9
    # end to end arcs do not overlap
    assert run([c.make_arc((0, 0), 1, 0.0, 1.0), c.make_arc((0, 0), 1, 1.0, 1.0)]) == []


def test_arc_from_points_both_directions():
    a = c.arc_from_points((0, 0), 1, (1, 0), (0, 1), (-1, 0))      # CCW upper half
    b = c.arc_from_points((0, 0), 1, (-1, 0), (0, 1), (1, 0))      # same arc, reversed
    assert abs(a.data[3] - math.pi) < 1e-9 and abs(b.data[3] - math.pi) < 1e-9
    one([a, b], c.DUPLICATE)
    lower = c.arc_from_points((0, 0), 1, (1, 0), (0, -1), (-1, 0))
    assert run([a, lower]) == []


def test_sampled_duplicates():
    pts = [(x * 0.5, math.sin(x)) for x in range(10)]
    one([c.make_sampled(pts), c.make_sampled(list(reversed(pts)))], c.DUPLICATE)
    other = [(x, y + 0.1) for x, y in pts]
    assert run([c.make_sampled(pts), c.make_sampled(other)]) == []


def test_line_vs_arc_never_overlap():
    assert run([c.make_line((-1, 1), (1, 1)), c.make_circle((0, 0), 1)]) == []


def test_plan_removals():
    prims = [
        c.make_line((0, 0), (5, 0)),
        c.make_line((0, 0), (5, 0)),
        c.make_line((0, 0), (5, 0)),             # triple duplicate
        c.make_line((0, 3), (10, 3)),
        c.make_line((2, 3), (4, 3)),             # contained
        c.make_line((0, 6), (5, 6), is_ref=True),
        c.make_line((0, 6), (5, 6)),             # dup of a projected line
        c.make_line((0, 9), (5, 9), is_constr=True),
        c.make_line((0, 9), (5, 9)),             # dup of construction line
    ]
    f = run(prims)
    scores = [0] * len(prims)
    scores[0] = 3                                 # most constrained of the triple
    removed = c.plan_removals(f, prims, scores, True, False)
    assert 0 not in removed and {1, 2} <= removed
    assert 6 in removed and 5 not in removed     # never remove the reference curve
    assert 7 in removed and 8 not in removed     # construction copy goes first
    assert 4 not in removed                       # contained not requested
    removed = c.plan_removals(f, prims, scores, False, True)
    assert removed == {4}


def test_many_random_no_crash():
    import random
    random.seed(1)
    prims = []
    for _ in range(3000):
        x, y = random.uniform(0, 100), random.uniform(0, 100)
        prims.append(c.make_line((x, y), (x + random.uniform(-3, 3), y + random.uniform(-3, 3))))
    prims.append(c.make_line(prims[0].data[0], prims[0].data[1]))
    f = run(prims)
    assert any(x.kind == c.DUPLICATE for x in f)


if __name__ == '__main__':
    names = [n for n in dir() if n.startswith('test_')]
    for n in names:
        globals()[n]()
        print('ok  ', n)
    print(f'{len(names)} tests passed')
