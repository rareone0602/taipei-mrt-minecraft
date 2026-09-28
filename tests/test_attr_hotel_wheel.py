#!/usr/bin/env python3
"""The Grand Hotel and the Miramar Ferris Wheel (application/attractions/grand_hotel.py,
miramar_wheel.py).

Only the blocks written into DictSink count; the numbers the modules compute for
themselves are not trusted:
  The Grand Hotel
    · On flat ground: the highest point (top of the ridge-end ornaments) is 87 m above
      the ground floor slab; the main body covers the OSM main-block outline and the
      portico is on the south face
    · The main ridge runs along the outline's long axis (21°); the golden tiles and red
      columns are there
    · On a slope: under the upper terrace the fill runs from the ground up to the slab
      with no unsupported cells; where the slope is cut, the terrace is clear above
    · The viewpoints are standable (forecourt plaza, 13th-floor gallery); the default
      viewpoint is south of the block and faces it
  The Miramar Ferris Wheel
    · The gondola roof is 100 m above the ground and the axle is on the OSM point
    · The front and rear rims each form a closed ring (26-connected, present at every
      degree of a sweep)
    · Gondola count: exactly 48 gondola interiors that are hollow in the middle with
      wool above and below
    · The wheel plane runs east-west (matching the mall's long side); the teleport
      point in the top gondola is standable, with gondola above and below
    · The mall covers the OSM outline

Usage: ./.venv/bin/python tests/test_attr_hotel_wheel.py
"""
import math
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.application import attractions as AT
from mrt.application import signage as SG
from mrt.application.attractions import kit
from mrt.domain import geometry as shapes
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def make(aid, ground):
    items = [it for it in AT.load_items() if it["id"] == aid]
    a = AT.for_world([], items=items)[0]
    AT.plan_all([a], ground, None, say=lambda *_: None)
    w = DictSink()
    AT.build(a, w)
    return a, w, items[0]


def base(b):
    return b.split("[")[0]


def solid(b):
    return base(b) != "minecraft:air"


# ================================================================ The Grand Hotel
print("Grand Hotel: flat ground")
a, w, item = make("grand_hotel", lambda x, z: 66)
chk("Has its own class (not OsmMassing)", type(a).__name__ == "GrandHotel")
g0 = a.g0
ys = [k[1] for k, v in w.blocks.items() if solid(v)]
chk("Highest point is %d m above the ground floor slab (public figure 87 m)" % (max(ys) - g0),
    max(ys) - g0 == 87)
main = next(f for f in item["features"] if f["osm"] == "way/25202548")
ring_ = max(main["outer"], key=len)
cells = shapes.poly_cells(ring_)
cover = sum(1 for x, z in cells if any(solid(w.get(x, y, z)) for y in range(g0 + 1, g0 + 30))) / len(cells)
chk("Main body covers the OSM main-block outline (%.0f%% of cells have a wall, column or slab)"
    % (cover * 100),
    cover >= 0.9)
# The gold name board of the portico should be south of the main block's centroid (the hotel faces
# the Keelung River)
cx = sum(x for x, z in cells) / len(cells)
cz = sum(z for x, z in cells) / len(cells)
plaque = [k for k, v in w.blocks.items() if v == "minecraft:gold_block" and g0 + 9 <= k[1] <= g0 + 13]
pz = sum(k[2] for k in plaque) / max(1, len(plaque))
chk("Gold name board of the portico is on the south face (%.0f m south of the centroid)" % (pz - cz),
    plaque and pz - cz > 20)
# Main ridge: the direction of the highest layer of gold ridge blocks
top_ridge = max(k[1] for k, v in w.blocks.items() if v == "minecraft:gold_block" and k[1] < g0 + 86)
rid = [(k[0], k[2]) for k, v in w.blocks.items() if v == "minecraft:gold_block" and k[1] == top_ridge]
xs, zs = np.array([p[0] for p in rid], float), np.array([p[1] for p in rid], float)
ev = np.linalg.eigh(np.cov(np.vstack([xs, zs])))[1][:, -1]
ang = math.degrees(math.atan2(ev[1], ev[0])) % 180
chk("Main ridge runs along the long axis: %.0f° (outline axis about 21°), %.0f m long"
    % (ang, xs.max() - xs.min()),
    abs(ang - 21) < 6 and xs.max() - xs.min() > 40)
names = {base(v) for v in w.blocks.values()}
chk("Golden tiles, red columns and blue-green dougong brackets are all there",
    {"minecraft:raw_gold_block", "minecraft:red_concrete",
     "minecraft:dark_prismarine", "minecraft:prismarine_bricks"} <= names)
chk("No yellow concrete (reserved for the platform warning strip)",
    "minecraft:yellow_concrete" not in names)
sp = a.spots()
chk("Two viewpoints: the default and the 13th-floor gallery", [s.key for s in sp] == ["", "terrace"])
for s in sp:
    chk("Viewpoint %r (%d,%d,%d) is standable" % (s.key, s.x, s.y, s.z),
        walk.standable(w.get, s.x, s.y, s.z))
s0 = sp[0]
chk("Default viewpoint is south of the block (%d m)" % (s0.z - cz), s0.z - cz > 60)
want = kit.yaw_of(cx - s0.x, cz - s0.z)
chk("Default viewpoint faces the block (off by %.0f°)" % abs((s0.yaw - want + 180) % 360 - 180),
    abs((s0.yaw - want + 180) % 360 - 180) < 20)
front, back = AT.plaque_lines(a)
chk('First line of the plaque is "圓山大飯店"', kit.sight_fn(a.id) == "sight/grand_hotel"
    and a.plaque()[0] == "圓山大飯店")
en = SG.fit(a.plaque_en())
chk("English line %r fits the sign and is on the back of the plaque" % en,
    bool(a.plaque_en()) and "…" not in en and en in back)

print("\nGrand Hotel: on a slope (rising 0.12 m per metre northwards, plus an east-west undulation)")


def slope(x, z):
    return int(round(80 - 0.12 * (z + 3590) + 3 * math.sin(x / 23.0)))


a, w, item = make("grand_hotel", slope)
g0 = a.g0
fr = a.fr
up = (a.kind == 1) & (np.abs(a.Lv - g0) < 1e-6)
holes = low = high = 0
for i, j in zip(*np.nonzero(up)):
    x, z = int(fr.X[i, j]), int(fr.Z[i, j])
    gy = slope(x, z)
    if gy < g0:
        low += 1
        if any(not solid(w.get(x, y, z)) for y in range(gy + 1, g0 + 1)):
            holes += 1
    elif gy > g0:
        high += 1
chk("Upper terrace straddles the slope: %d cells to fill, %d cells to cut" % (low, high),
    low > 200 and high > 200)
chk("Filled cells have no gaps from the ground to the slab (%d cells with holes)" % holes, holes == 0)
cut_bad = 0
for i, j in zip(*np.nonzero(up)):
    x, z = int(fr.X[i, j]), int(fr.Z[i, j])
    gy = slope(x, z)
    if gy > g0 + 1 and a.body[i, j] == 0:
        if w.get(x, g0 + 1, z) != "minecraft:air" and base(w.get(x, g0 + 1, z)) != "minecraft:diorite_wall":
            cut_bad += 1
chk("Terrace over the cut is cleared above (%d cells not cleared)" % cut_bad, cut_bad == 0)
floor = sum(1 for i, j in zip(*np.nonzero(a.body)) if solid(w.get(int(fr.X[i, j]), g0, int(fr.Z[i, j]))))
chk("Ground floor slab of the main block is complete (%d / %d)" % (floor, int(a.body.sum())),
    floor == int(a.body.sum()))
ys = [k[1] for k, v in w.blocks.items() if solid(v)]
chk("On the slope the height is still 87 m (%d)" % (max(ys) - g0), max(ys) - g0 == 87)
for s in a.spots():
    chk("Viewpoint %r on the slope is standable" % s.key, walk.standable(w.get, s.x, s.y, s.z))

# ================================================================ The Miramar Ferris Wheel
print("\nMiramar Ferris Wheel: flat ground")
a, w, item = make("miramar_wheel", lambda x, z: 66)
chk("Has its own class (not OsmMassing)", type(a).__name__ == "MiramarWheel")
g0 = a.g0
ys = [k[1] for k, v in w.blocks.items() if solid(v)]
chk("Highest point is %d m above the ground (public figure 100 m)" % (max(ys) - g0), max(ys) - g0 == 100)
node = next(f for f in item["features"] if f.get("point"))
hx, hz = node["point"]
axle = [k for k, v in w.blocks.items() if v == "minecraft:light_gray_concrete" and k[1] > g0 + 60]
ax = sum(k[0] for k in axle) / len(axle) + 0.5
az = sum(k[2] for k in axle) / len(axle) + 0.5
hub_y = int(round(sum(k[1] for k in axle) / len(axle)))
chk("Axle is on the OSM point (off by %.1f m), %d m up" % (math.hypot(ax - hx, az - hz), hub_y - g0),
    math.hypot(ax - hx, az - hz) <= 1.5 and 60 <= hub_y - g0 <= 70)
# Rim: white cells at a radius of 27 to 29.5 m around the OSM point (the inner rings and the mall's
# white emblem do not count)
rim = [k for k, v in w.blocks.items() if v == "minecraft:white_concrete" and abs(k[2] + 0.5 - hz) <= 6
       and 27.0 <= math.hypot(k[0] + 0.5 - hx, k[1] - hub_y) <= 29.5]
rx = np.array([k[0] for k in rim], float)
rz = np.array([k[2] for k in rim], float)
chk("Wheel plane runs east-west: rim %.0f m wide east-west, %.0f m thick north-south"
    % (rx.max() - rx.min(), rz.max() - rz.min()),
    rx.max() - rx.min() > 55 and rz.max() - rz.min() <= 7)


def rim_face(sign):
    """Return one rim: the white cells at a radius of 27 to 29.5 on one side of the axle.

    sign selects the side (south or north)."""
    return {(x, y, z) for (x, y, z) in rim if (z + 0.5 - hz) * sign > 0.4}


for sign, nm in ((1, "South"), (-1, "North")):
    face = rim_face(sign)
    start = next(iter(face))
    seen = {start}
    q = deque([start])
    while q:
        x, y, z = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    n = (x + dx, y + dy, z + dz)
                    if n in face and n not in seen:
                        seen.add(n)
                        q.append(n)
    # The rim's circumference is about 178 m: every 3° sector (about 1.5 m) must contain rim
    bins = {int((math.degrees(math.atan2(y - hub_y, x + 0.5 - hx)) % 360) // 3) for x, y, z in face}
    chk("%s rim forms a closed ring: %d cells in one connected "
        "component, all 120 sectors of 3° present (%d missing)"
        % (nm, len(face), 120 - len(bins)), len(seen) == len(face) and len(bins) == 120)
interiors = 0
for (x, y, z), v in w.blocks.items():
    if v != "minecraft:air" or w.get(x, y + 1, z) != "minecraft:air":
        continue
    below, above = w.get(x, y - 1, z), w.get(x, y + 2, z)
    if base(below).endswith(("_wool", "glass")) and base(above).endswith(("_wool", "glass")) \
            and y > g0 + 25:
        interiors += 1
chk("%d gondolas (public figure 48)" % interiors, interiors == 48)
clear = {k for k, v in w.blocks.items() if v in ("minecraft:white_stained_glass", "minecraft:glass")}
chk("Transparent gondolas are there (%d cells of white glass)" % len(clear), len(clear) >= 2 * 16)
sp = a.spots()
chk("Two viewpoints: the default and the top gondola", [s.key for s in sp] == ["", "top"])
for s in sp:
    chk("Viewpoint %r (%d,%d,%d) is standable" % (s.key, s.x, s.y, s.z),
        walk.standable(w.get, s.x, s.y, s.z))
top = sp[1]
chk("Top gondola: gondola floor underfoot, gondola roof overhead (%d m up)" % (top.y - g0),
    base(w.get(top.x, top.y - 1, top.z)).endswith("_wool")
    and base(w.get(top.x, top.y + 2, top.z)).endswith("_wool") and top.y - g0 >= 95)
s0 = sp[0]
want = kit.yaw_of(hx - s0.x, hz - s0.z)
chk("Default viewpoint is %d m south of the wheel and faces it (off by %.0f°)"
    % (s0.z - hz, abs((s0.yaw - want + 180) % 360 - 180)),
    s0.z - hz > 45 and abs((s0.yaw - want + 180) % 360 - 180) < 10)
mall = next(f for f in item["features"] if f["osm"] == "way/155816458")
mc = shapes.poly_cells(max(mall["outer"], key=len))
cover = sum(1 for x, z in mc if solid(w.get(x, g0 + 12, z)) or solid(w.get(x, g0 + 6, z))) / len(mc)
chk("Mall covers the OSM outline (%.0f%%)" % (cover * 100), cover >= 0.95)
names = {base(v) for v in w.blocks.values()}
chk("No yellow concrete (reserved for the platform warning strip)",
    "minecraft:yellow_concrete" not in names)
chk('First line of the plaque is "美麗華摩天輪"', a.plaque()[0] == "美麗華摩天輪")
front, back = AT.plaque_lines(a)
en = SG.fit(a.plaque_en())
chk("English line %r fits the sign and is on the back of the plaque" % en,
    bool(a.plaque_en()) and "…" not in en and en in back)

print("\n" + ("All tests passed" if ok else "Some tests failed"))
sys.exit(0 if ok else 1)
