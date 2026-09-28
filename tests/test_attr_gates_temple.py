#!/usr/bin/env python3
"""The four gates of the Taipei Prefecture city wall (city_gates.py) and Bangka Longshan
Temple (longshan_temple.py).

No world save is written: each is built once into a DictSink on a flat Site (y66), and
the test checks:
  · City gates: the location is on the OSM gate outline (the catalog center points of the
    East, South and Little South Gates are not trusted); the gate platform fills the
    outline; the passage can be walked from outside the city to inside (by walk's rules)
    without cutting through the top of the platform; there is a roof of reasonable height;
    the name board and the plaque; the viewpoint is standable, faces the gate and lies
    outside the grading area
  · North Gate: red walls, red tiles, the two square and one round windows on the north
    (outer) face
  · The three palace-style gates: green glazed tiles, red columns, white crenellations;
    the red brick balustrade at the back of the Little South Gate
  · Longshan Temple: the double-eaved main hall (two layers of tiles, lower and upper
    eaves) is higher than the front hall, the courtyard is open, the courtyard can be
    reached from the forecourt through the front hall's doors, both pools hold water, and
    both viewpoints are standable
  · Shared: no ground lookups after plan (cli discards the terrain distance field after
    plan_all); no yellow concrete (reserved for the platform warning strip); stairs face
    the four cardinal directions; no sign's first line starts with `出口`; the plaque's
    fact lines, Chinese and English, fit without truncation

Usage: ./.venv/bin/python tests/test_attr_gates_temple.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application import attractions as AT
from mrt.application.attractions import city_gates as CG
from mrt.application.attractions import kit
from mrt.domain import geometry as shapes
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


GROUND = 66
ITEMS = {it["id"]: it for it in AT.load_items()}


def build(aid):
    """As in cli: the ground function may not be called after plan (cli discards the terrain
    distance field), so grading in build can use only the values looked up during plan
    and kept in Site's cache."""
    a = AT.for_world([], items=[ITEMS[aid]])[0]
    w = DictSink()
    state = {"planning": True}

    def ground(x, z):
        if not state["planning"]:
            raise RuntimeError("Ground looked up after plan at (%d, %d)" % (x, z))
        return GROUND
    a.plan(kit.Site(ground))
    state["planning"] = False
    AT.build(a, w)
    return a, w


def column_top(w, x, z):
    ys = [k[1] for k, b in w.blocks.items() if k[0] == x and k[2] == z and not b.endswith(":air")]
    return max(ys) if ys else None


def common(a, w):
    blocks = w.blocks.values()
    chk("No yellow concrete (reserved for the platform warning strip)", not any("yellow_concrete" in b for b in blocks))
    bad = [b for b in blocks if "_stairs[" in b and not any("facing=%s" % f in b for f in
                                                            ("north", "south", "east", "west"))]
    chk("Every stair faces a cardinal direction", not bad)
    firsts = [lines[0] for lines in w.signs.values() if lines]
    chk("No sign's first line starts with 出口 (%d signs)" % len(firsts), not any(t.startswith("出口") for t in firsts))
    sp = a.spots()
    chk("The first viewpoint's key is the empty string", bool(sp) and sp[0].key == "")
    for s in sp:
        chk("Viewpoint %r (%d,%d,%d) is standable" % (s.key, s.x, s.y, s.z), walk.standable(w.get, s.x, s.y, s.z))
    s0 = sp[0]
    near = [k for k, lines in w.signs.items()
            if abs(k[0] - s0.x) <= 4 and abs(k[2] - s0.z) <= 4 and lines and lines[0] == a.name_zh]
    chk("The plaque beside the viewpoint reads %s" % a.name_zh, bool(near))


def facing_err(a, s):
    """Deviation (degrees) of a viewpoint's direction from looking at the outline's
    center."""
    cells = set()
    for r in [a.outline()]:
        cells |= shapes.poly_cells(r)
    cx = sum(c[0] for c in cells) / len(cells)
    cz = sum(c[1] for c in cells) / len(cells)
    want = math.degrees(math.atan2(-(cx + 0.5 - (s.x + 0.5)), cz + 0.5 - (s.z + 0.5)))
    return abs((s.yaw - want + 180) % 360 - 180)


print("City gate locations: always from the OSM gate outline")
expect = {"beimen": (-631.3, -162.2), "dongmen": (23.5, 799.6),
          "nanmen": (-242.9, 1232.3), "xiaonanmen": (-943.5, 1037.4)}
for aid, (ex, ez) in expect.items():
    a = AT.for_world([], items=[ITEMS[aid]])[0]
    cx, cz = a.center()
    chk("%s center (%.1f, %.1f) is on the OSM gate (error < 1.5 m)" % (aid, cx, cz), math.hypot(cx - ex, cz - ez) < 1.5)
    x0, z0, x1, z1 = a.bbox()
    chk("%s bbox contains the gate outline" % aid, x0 < cx < x1 and z0 < cz < z1)
for aid in expect:
    a = AT.for_world([], items=[ITEMS[aid]])[0]
    f = a.feature(a.osm)
    chk("%s uses the gate way named in the data (%s, historic=city_gate)" % (aid, a.osm),
        f is not None and f.get("main") and f["tags"].get("historic") == "city_gate")

for aid in ("beimen", "dongmen", "nanmen", "xiaonanmen"):
    print("\n%s" % aid)
    a, w = build(aid)
    fr, g0 = a.fr, a.g0
    # The gate platform fills the OSM outline: the layer at the top of the platform is solid
    # (the South Gate's outline includes planters and lawn, so only half is required).
    # Viewed from above as verify_attractions does: the share of columns whose top is more
    # than 3 blocks above the ground.
    cells = shapes.poly_cells(a.outline())
    filled = sum(1 for x, z in cells if not w.get(x, a.hb, z).endswith(":air"))
    need = 0.35 if aid == "nanmen" else 0.9
    chk("Of %d cells in the OSM outline, %.0f%% are solid at the platform top y%d" % (len(cells), 100.0 * filled / len(cells), a.hb),
        filled >= need * len(cells))
    tops = {}
    for (x, y, z), b in w.blocks.items():
        if not b.endswith(":air") and y > tops.get((x, z), -999):
            tops[(x, z)] = y
    cover = sum(1 for c in cells if tops.get(c, -999) >= g0 + 3) / float(len(cells))
    chk("From above, %.0f%% of the columns in the outline top out more than 3 blocks above the ground (verify_attractions wants 50%%)" % (cover * 100), cover >= 0.55)
    # Passage: walk from outside the city to inside along the passage's center line
    outer = fr.cell(0.0, -a.b - 3.0)
    inner = fr.cell(0.0, a.b + 3.0)
    x0, z0, x1, z1 = a.bbox()
    dist, _ = walk.flood(w.get, [(outer[0], g0 + 1, outer[1])],
                         bounds=(x0, g0, z0, x1, g0 + 3, z1),
                         allow=lambda x, y, z: abs(fr.local(x, z)[0]) <= 4.0)
    chk("The passage can be walked: outside %s -> inside %s (keeping within 4 m of its center line)" % (outer, inner),
        (inner[0], g0 + 1, inner[1]) in dist)
    mid = fr.cell(0.0, 0.0)
    chk("Headroom in the middle of the passage is >= 3 blocks",
        all(w.get(mid[0], y, mid[1]).endswith(":air") for y in range(g0 + 1, g0 + 4)))
    chk("The passage does not cut through the platform top (y%d is solid or an upside-down stair)" % a.hb,
        not w.get(mid[0], a.hb, mid[1]).endswith(":air"))
    top = max(k[1] for k in w.blocks)
    chk("Highest point %d m above the ground (12–18)" % (top - g0), 12 <= top - g0 <= 18)
    roof = [b for k, b in w.blocks.items() if k[1] >= g0 + 10 and ("stairs" in b or "slab" in b)]
    chk("The roof is tiled (%d stairs and slabs)" % len(roof), len(roof) > 60)
    plaques = [lines for lines in w.signs.values() if len(lines) > 1 and lines[1] == a.plaque_text] \
        if aid != "beimen" else [lines for lines in w.signs.values() if len(lines) > 1 and lines[1] == "承恩門"]
    chk("Name board sign", bool(plaques))
    s0 = a.spots()[0]
    i, j = s0.z - fr.z0, s0.x - fr.x0
    in_ground = 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] and a.ground[i, j]
    chk("The viewpoint is outside the grading area (no need to guess the ground height)", not in_ground)
    chk("The viewpoint is on the outside of the city (nearer the name board face)",
        fr.local(s0.x, s0.z)[1] < 0)
    chk("The viewpoint faces the outline's center (off by %.0f°)" % facing_err(a, s0), facing_err(a, s0) <= 30)
    common(a, w)
    names = set(b.split("[")[0] for b in w.blocks.values())
    if aid == "beimen":
        chk("North Gate: red walls, orange-red tiles, dark gray ridge",
            {"minecraft:red_terracotta", "minecraft:waxed_cut_copper_stairs",
             "minecraft:polished_deepslate"} <= names)
        # Window openings on the north (outer) face: holes through the red wall in the g0+8
        # row
        holes = 0
        for du in (-3.7, 0.0, 3.7):
            x, z = fr.cell(du, -a.b + 0.3)
            holes += w.get(x, g0 + 8, z).endswith(":air")
        chk("Two square and one round window in the north wall: three openings (%d)" % holes, holes == 3)
    else:
        chk("Palace style: green glazed tiles, red columns, white crenellations, yellow ridges",
            {"minecraft:prismarine_brick_stairs", "minecraft:red_concrete", "minecraft:white_concrete",
             "minecraft:honeycomb_block"} <= names)
        if aid == "xiaonanmen":
            back = [k for k, b in w.blocks.items() if b == "minecraft:bricks" and k[1] == a.hb + 1]
            chk("Little South Gate: the balustrade on the city side is red brick (%d blocks)" % len(back), len(back) > 5)

print("\nBangka Longshan Temple")
a, w = build("longshan_temple")
fr, g0 = a.fr, a.g0
common(a, w)
mx, mz = fr.cell(0.0, 0.0)
main_top = max(k[1] for k in w.blocks if abs(fr.local(k[0], k[2])[0]) <= a.ha and abs(fr.local(k[0], k[2])[1]) <= a.hb_)
front = a.front_box
fx, fz = fr.cell(0.0, (front[2] + front[3]) / 2)
front_top = max(k[1] for k in w.blocks if front[0] <= fr.local(k[0], k[2])[0] <= front[1]
                and front[2] <= fr.local(k[0], k[2])[1] <= front[3])
chk("The main hall (top y%d) is higher than the front hall (y%d)" % (main_top, front_top), main_top > front_top + 2)
chk("Main hall %d m above the ground (14–19)" % (main_top - g0), 14 <= main_top - g0 <= 19)
# Double eaves: looking in from the front edge of the main hall, the lower and upper eaves
# each have a layer of tiles
ex, ez = fr.cell(0.0, a.hb_ - 2.7)                     # Between the upper wall and the upper eave's overhang
tiles = [k[1] for k, b in w.blocks.items() if ("copper" in b or "resin" in b) and k[0] == ex and k[2] == ez]
eaves = sorted(set(tiles))
chk("Two layers of tiles above the main hall's front edge (double eaves, y %s)" % eaves, len(eaves) >= 2 and max(eaves) - min(eaves) >= 3)
cx_, cz_ = fr.cell(0.0, (a.hb_ + front[2]) / 2 + 2.0)
chk("The courtyard is open to the sky", all(w.get(cx_, y, cz_).endswith(":air") for y in range(g0 + 1, g0 + 25)))
plaza = a.spots()[0]
court = a.spots()[1]
x0, z0, x1, z1 = a.bbox()
dist, _ = walk.flood(w.get, [(plaza.x, plaza.y, plaza.z)], bounds=(x0, g0, z0, x1, g0 + 4, z1))
chk("The courtyard can be reached from the forecourt through the front hall's doors", (court.x, court.y, court.z) in dist)
water = [k for k, b in w.blocks.items() if b.startswith("minecraft:water")]
chk("The waterfall pools on both sides of the forecourt hold water (%d blocks)" % len(water), len(water) > 60)
chk("Bronze dragon columns and carved stone dragon columns are present", {"minecraft:waxed_exposed_chiseled_copper", "minecraft:chiseled_deepslate"}
    <= set(b.split("[")[0] for b in w.blocks.values()))
chk("The courtyard viewpoint's key is courtyard", court.key == "courtyard")
chk("The default viewpoint faces the main hall (off by %.0f°)" % facing_err(a, plaza), facing_err(a, plaza) <= 30)
chk("Plaque lines: the name and English name follow the data", a.plaque()[:2] == [ITEMS["longshan_temple"]["name_zh"],
                                               ITEMS["longshan_temple"]["name_en"]])

print("\nThe plaque's fact lines fit (not truncated with …)")
from mrt.application import signage as SG
for aid in ("beimen", "dongmen", "nanmen", "xiaonanmen", "longshan_temple"):
    a = AT.for_world([], items=[ITEMS[aid]])[0]
    facts = [t for t in a.plaque()[2:] if t]
    chk("%s: %s" % (aid, " / ".join(facts)), len(facts) == 2 and all(SG.text_width(t) <= SG.SIGN_W for t in facts))
    en = SG.fit(a.plaque_en())
    chk("%s: English line %r fits" % (aid, en), bool(a.plaque_en()) and "…" not in en)

print("\n" + ("All tests passed" if ok else "Some tests failed"))
sys.exit(0 if ok else 1)
