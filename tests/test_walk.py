#!/usr/bin/env python3
"""Unit tests for the walking reachability rules.

The focus of this test is **slabs**. The project's stairs alternate full blocks and
bottom slabs, rising 0.5 m per meter. If the reachability check does not recognize
slabs, a whole stair is read as half solid and half hanging in the air, and the
verification tools report a pile of breaks that do not exist, or worse, pass a stair
that really is broken. So the test uses stairs built by the generator itself, not
hand-made fake data.

Usage: ./.venv/bin/python tests/test_walk.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application.landmarks import ShaftStair
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def floor_world(x0, x1, z0, z1, y, block="minecraft:smooth_stone"):
    """Lay a floor with 4 blocks of headroom above it."""
    d = DictSink()
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            d.set(x, y, z, block)
            for dy in range(1, 5):
                d.set(x, y + dy, z, "minecraft:air")
    return d


print("Block classification")
chk("air is passable", walk.is_passable("minecraft:air"))
chk("rails are passable (you stand on the cell below)", walk.is_passable("minecraft:rail"))
chk("signs are passable", walk.is_passable("minecraft:oak_sign[rotation=4]"))
chk("iron bars block the way", not walk.is_passable("minecraft:iron_bars"))
chk("a slab without states defaults to a bottom slab",
    walk.is_bottom_slab("minecraft:smooth_stone_slab"))
chk("a top slab is not a bottom slab",
    not walk.is_bottom_slab("minecraft:smooth_stone_slab[type=top]"))
chk("a double slab is not a bottom slab",
    not walk.is_bottom_slab("minecraft:smooth_stone_slab[type=double]"))

print("Flat ground")
d = floor_world(0, 9, 0, 9, 60)
g = d.get
chk("you can stand one cell above the floor", walk.standable(g, 3, 61, 3))
chk("you cannot stand in the floor cell (the feet are inside the block)",
    not walk.standable(g, 3, 60, 3))
chk("you cannot stand in mid-air", not walk.standable(g, 3, 63, 3))
dist, _ = walk.flood(g, [(0, 61, 0)], bounds=(0, 55, 0, 9, 70, 9))
chk(f"the whole 10x10 floor is reachable ({len(dist)} cells)", len(dist) == 100)
chk("the step count equals the Manhattan distance", dist[(9, 61, 9)] == 18)

print("Insufficient headroom")
d2 = floor_world(0, 9, 0, 9, 60)
for x in range(0, 10):
    d2.set(x, 62, 5, "minecraft:stone")        # A beam that leaves only 1 block of headroom
dist, _ = walk.flood(d2.get, [(0, 61, 0)], bounds=(0, 55, 0, 9, 70, 9))
chk(f"a beam with 1 block of headroom blocks the way ({len(dist)} cells reached)", len(dist) == 50)
chk("the far side of the beam is unreachable", (0, 61, 9) not in dist)

print("Walls")
d3 = floor_world(0, 9, 0, 9, 60)
for x in range(0, 10):
    for dy in (1, 2, 3):
        d3.set(x, 60 + dy, 5, "minecraft:stone")
comps = walk.components(d3.get, [(0, 61, 0), (0, 61, 9)],
                        bounds=(0, 55, 0, 9, 70, 9))
chk(f"a full wall splits the floor in two (components: {len(comps)})", len(comps) == 2)

print("Drops")
d4 = floor_world(0, 4, 0, 9, 60)
for x in range(5, 10):                          # The right half is 1 block lower
    for z in range(0, 10):
        d4.set(x, 59, z, "minecraft:smooth_stone")
        for dy in range(1, 5):
            d4.set(x, 59 + dy, z, "minecraft:air")
dist, _ = walk.flood(d4.get, [(0, 61, 0)], bounds=(0, 50, 0, 9, 70, 9))
chk("a 1-block drop can be crossed", (9, 60, 9) in dist)

d5 = floor_world(0, 4, 0, 9, 60)
for x in range(5, 10):                          # The right half is 3 blocks lower
    for z in range(0, 10):
        d5.set(x, 57, z, "minecraft:smooth_stone")
        for dy in range(1, 5):
            d5.set(x, 57 + dy, z, "minecraft:air")
dist, _ = walk.flood(d5.get, [(0, 61, 0)], bounds=(0, 50, 0, 9, 70, 9))
chk("a 3-block drop cannot be crossed (jumping down without climbing back does not count)",
    (9, 58, 9) not in dist)

print("Switchback stair shaft (a real stair built by landmarks.ShaftStair)")
G0, YTO = 66, 44                                # 22 m deep, like a Tamsui-Xinyi Line concourse
d6 = DictSink()
st = ShaftStair(0, 0, 1, 0, G0, YTO)
st.build(d6)
g6 = d6.get
x0, z0, x1, z1 = st.bbox()
b = (x0, YTO - 4, z0, x1, G0 + 6, z1)
top = walk.nearest_standable(g6, 0, G0 + 1, 0, radius=3, dy=2)
chk(f"you can stand on the ground at the shaft top {top}", top is not None)
dist, came = walk.flood(g6, [top], bounds=b)
bottom = [c for c in dist if c[1] <= YTO]
chk(f"walks from the ground at y={G0} to the shaft bottom at y={YTO} "
    f"({len(bottom)} cells at the bottom)",
    len(bottom) > 0)
if bottom:
    deep = min(dist, key=lambda c: c[1])
    chk(f"deepest point reached y={deep[1]} (target {YTO})", deep[1] <= YTO)
    chk(f"the path is {dist[deep]} steps, longer than the straight-line distance",
        dist[deep] > (G0 - YTO))
    # The reverse direction must also work; the symmetric rules already guarantee it, so this
    # is a safeguard
    back, _ = walk.flood(g6, [deep], bounds=b)
    chk("you can walk back from the shaft bottom to the ground", top in back)

print("\nAll passed" if ok else "\nSome tests failed")
raise SystemExit(0 if ok else 1)
