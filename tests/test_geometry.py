#!/usr/bin/env python3
"""Unit tests for the geometry tools: polygon fill, outer ring, inset and hip roofs.

Usage: ./.venv/bin/python tests/test_geometry.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.domain.geometry import *  # noqa: F403  The tests keep the original unqualified calls

def _test():
    ok = True
    def chk(name, cond):
        nonlocal ok
        print(("  ok   " if cond else "  FAIL ") + name)
        ok = ok and cond

    print("Polygon fill")
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    c = poly_cells(sq)
    chk(f"10x10 square, area 100 -> {len(c)} cells", len(c) == 100)
    chk("the bottom-left corner is inside; beyond the top-right corner is not",
        (0, 0) in c and (9, 9) in c and (10, 10) not in c)
    chk("the outside is not inside", (10, 5) not in c and (-1, 5) not in c)

    tri = [(0, 0), (10, 0), (0, 10)]
    t = poly_cells(tri)
    chk(f"right triangle, area 50 -> {len(t)} cells", 44 <= len(t) <= 56)
    chk("beyond the hypotenuse is not inside", (9, 9) not in t)

    print("Outer ring and inset")
    r = ring_cells(c)
    chk(f"10x10 outer ring of 36 cells -> {len(r)}", len(r) == 36)
    chk(f"inset 1 -> 8x8 = 64 cells -> {len(inset(c,1))}", len(inset(c, 1)) == 64)
    chk(f"inset 4 leaves the central 2x2 -> {len(inset(c,4))}", len(inset(c, 4)) == 4)
    chk("inset 5 is empty", inset(c, 5) == set())
    chk("insetting to the empty set does not crash", inset(c, 99) == set())

    print("Hip roofs")
    d = depth_map(c)
    chk(f"the centre has the largest distance = 5 -> {d[(5,5)]}", d[(5, 5)] == 5)
    chk("corner distance = 1", d[(0, 0)] == 1)
    rf = hip_roof(c, 100, slope=0.5)
    chk(f"eave 100, centre top {rf[(5,5)][1]}", rf[(5, 5)][1] == 102)
    chk("the eave ring is not raised", rf[(0, 0)][1] == 100)
    rf2 = hip_roof(c, 100, slope=0.5, max_rise=1)
    chk("max_rise takes effect", rf2[(5, 5)][1] == 101)

    print("Centroid and rectangles")
    cx, cz = centroid(sq)
    chk(f"square centroid ({cx:.1f},{cz:.1f})", abs(cx - 5) < 1e-6 and abs(cz - 5) < 1e-6)
    rr = rect(0, 0, 10, 4)
    chk(f"unrotated rectangle bbox {bbox(rr)}", bbox(rr) == (-5.0, -2.0, 5.0, 2.0))
    rr90 = rect(0, 0, 10, 4, math.pi / 2)
    bb = bbox(rr90)
    chk("rotating 90 degrees swaps length and width",
        abs(bb[2] - bb[0] - 4) < 1e-6 and abs(bb[3] - bb[1] - 10) < 1e-6)
    chk(f"unrotated 20x10, area 200 -> {len(poly_cells(rect(0,0,20,10)))} cells",
        len(poly_cells(rect(0, 0, 20, 10))) == 200)
    n = len(poly_cells(rect(0, 0, 20, 10, math.pi / 6)))
    chk(f"rotated 30 degrees, the area is still about 200 -> {n} cells", 180 <= n <= 220)

    print("Degenerate input")
    chk("two points return the empty set", poly_cells([(0, 0), (1, 1)]) == set())
    chk("a zero-area centroid does not crash", centroid([(0, 0), (1, 1), (2, 2)]) is not None)

    print("\nAll passed" if ok else "\nSome tests failed")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_test())
