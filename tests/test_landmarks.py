#!/usr/bin/env python3
"""Unit tests for landmark buildings: extrusion, floor slabs, roofs, degenerate input.

Usage: ./.venv/bin/python tests/test_landmarks.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application.landmarks import *  # noqa: F403
from mrt.domain import geometry as shapes
from mrt.ports.block_sink import DictSink

# ---------- Self-test ----------

# This used to bring its own _FakeWorld; it now uses the DictSink from ports, which is
# the same interface the generator takes.
def _test():
    ok = True
    def chk(name, cond):
        nonlocal ok
        print(("  ok   " if cond else "  FAIL ") + name)
        ok = ok and cond

    print("Building")
    poly = shapes.rect(0, 0, 40, 30)
    b = Building(poly, g0=70, storeys=3, storey_h=5, name="測試")
    w = DictSink()
    b.build(w)
    ys = [y for _, y, _ in w.blocks]
    chk(f"writes {len(w.blocks):,} blocks", len(w.blocks) > 1000)
    chk(f"lowest y={min(ys)} = ground - 3", min(ys) == 67)
    chk(f"top floor slab y={b.top_y()}", b.top_y() == 85)
    chk(f"ridge y={max(ys)} is above the top floor slab", max(ys) > b.top_y())
    peak_rise = max(ys) - b.top_y()
    chk(f"roof rise {peak_rise} m, about min(40,30)/2*slope",
        3 <= peak_rise <= 12)

    # The interior should be empty (walkable).
    mid = w.blocks.get((0, 72, 0))
    chk(f"first-floor interior (0,72,0) = {mid}", mid == AIR)
    corner = w.blocks.get((-20, 72, -15))
    chk(f"outer wall corner (-20,72,-15) = {corner}", corner not in (None, AIR))

    # The floor slab is solid.
    chk("second-floor slab is solid", w.blocks.get((0, 75, 0)) not in (None, AIR))

    bb = b.bbox()
    chk(f"bbox {bb} covers the polygon", bb[0] <= -20 and bb[2] >= 20)

    print("Slab")
    s = Slab(shapes.rect(0, 0, 20, 20), y=50, clear=4,
             wall="minecraft:gray_concrete")
    w2 = DictSink()
    s.build(w2)
    chk(f"writes {len(w2.blocks):,} blocks", len(w2.blocks) > 500)
    chk("floor slab is solid", w2.blocks.get((0, 50, 0)) not in (None, AIR))
    chk("headroom is air", w2.blocks.get((0, 52, 0)) == AIR)
    chk("roof slab is solid", w2.blocks.get((0, 55, 0)) not in (None, AIR))
    chk("surrounding wall is closed", w2.blocks.get((-10, 52, 0)) == "minecraft:gray_concrete")

    print("Degenerate input")
    w3 = DictSink()
    Building([(0, 0), (1, 1)], g0=70).build(w3)
    chk("a two-point polygon neither crashes nor writes anything", len(w3.blocks) == 0)

    print("\nAll passed" if ok else "\nSome tests failed")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_test())
