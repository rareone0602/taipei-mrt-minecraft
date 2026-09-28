#!/usr/bin/env python3
"""The Chiang Kai-shek Memorial Hall grounds and the Sun Yat-sen Memorial Hall
(application/attractions/cks_memorial.py, sun_yat_sen.py, palace_kit.py): built into a
DictSink (flat ground at y66) and read back from the blocks to check a few published
figures.

  · Memorial hall: highest point 70 m above the ground, an octagonal roof, a square hall
    body, 14 m of half steps at the front (28 steps), a 16 m main door, and a statue in
    the hall (about 6 m seated)
  · Liberty Square paifang: five archways, about 30 m high
  · National Theater and Concert Hall: yellow tiles, red columns, main ridge at 37 m; the
    Concert Hall (xieshan) has gable pediments and the Theater (hip) does not
  · Sun Yat-sen Memorial Hall: 30 m high, the corner tips higher than mid-eave, 14 columns
    per side, the portico highest
  · Teleport points are standable, the default viewpoint faces the building, the plaque's
    first line is the attraction's Chinese name and its English line fits; the keep-out
    zone still blocks writes
  · palace_kit: fine angles, the main ridge of a hip roof with tuishan runs along u,
    octagonal hip ridges, the roof shell fills steep steps

Usage: ./.venv/bin/python tests/test_attr_palaces.py
"""
import math
import os
import re
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.application import attractions as AT
from mrt.application import signage as SG
from mrt.application.attractions import kit
from mrt.application.attractions import palace_kit as PK
from mrt.application.attractions.cks_memorial import CksMemorial, GATE_PILLARS
from mrt.application.attractions.sun_yat_sen import SunYatSenMemorial
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True
GY = 66


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def base(b):
    return b.split("[")[0]


def build(aid, keep=None):
    items = [i for i in AT.load_items() if i["id"] == aid]
    a = AT.for_world([], items=items)[0]
    a.plan(kit.Site(lambda x, z: GY))
    w = DictSink()
    t = time.time()
    dropped = AT.build(a, w, keep)
    return a, w, time.time() - t, dropped


BLOCK_RE = re.compile(r"^minecraft:([a-z0-9_]+)(\[[a-z_]+=[a-z0-9_]+(,[a-z_]+=[a-z0-9_]+)*\])?$")
JAR = os.path.expanduser("~/Library/Application Support/minecraft/versions/26.2/26.2.jar")


def jar_blocks():
    """Block ids in the installed 26.2 jar (blockstates/*.json); None if the game is not
    installed (only the format is checked then)."""
    if not os.path.exists(JAR):
        return None
    with zipfile.ZipFile(JAR) as z:
        return {n.rsplit("/", 1)[1][:-5] for n in z.namelist()
                if n.startswith("assets/minecraft/blockstates/") and n.endswith(".json")}


KNOWN = jar_blocks()


def check_ids(w, label):
    names = set(w.blocks.values())
    bad = [n for n in names if not BLOCK_RE.match(n)]
    chk("%s: block strings are well formed (%d kinds%s)" % (label, len(names), "" if not bad else "; malformed: %s" % bad[:3]),
        not bad)
    if KNOWN is not None:
        unknown = sorted({BLOCK_RE.match(n).group(1) for n in names if BLOCK_RE.match(n)} - KNOWN)
        chk("%s: every block is in the 26.2 jar%s" % (label, "" if not unknown else " (missing: %s)" % unknown),
            not unknown)


def get_fn(w):
    return lambda x, y, z: w.get(x, y, z)


def column_top(w, x, z, y0=GY, y1=GY + 90):
    top = None
    for y in range(y0, y1):
        if base(w.get(x, y, z)) != "minecraft:air":
            top = y
    return top


# ---------------------------------------------------------------- palace_kit
print("palace_kit")
ring = [(0, 0), (100 * math.cos(math.radians(1.65)), 100 * math.sin(math.radians(1.65))),
        (100 * math.cos(math.radians(1.65)) - 50 * math.sin(math.radians(1.65)),
         100 * math.sin(math.radians(1.65)) + 50 * math.cos(math.radians(1.65))),
        (-50 * math.sin(math.radians(1.65)), 50 * math.cos(math.radians(1.65)))]
chk("fine_angle: a rectangle 1.65° off measures %.2f°" % math.degrees(PK.fine_angle(ring)),
    abs(math.degrees(PK.fine_angle(ring)) - 1.65) < 0.01)
fr = kit.Frame(0, 0, 0.0, 50)
h, rm = PK.hip_ridge(fr, 30, 40, 10, 20)
ridge_line = fr.box(19, 0.6)
chk("Hip roof with tuishan: deeper than it is wide, yet the main ridge runs along u (the center line within |u|<=19 is highest)",
    float(h[ridge_line].min()) >= float(h[fr.box(30, 40)].max()) - 1e-6)
chk("Hip roof with tuishan: the ridge mask includes the main ridge and the four hip ridges", bool(rm[ridge_line].all()) and bool(rm[fr.box(0.6, 0.6, du=25, dv=20)].any()))
ho, hips = PK.octagon(fr, 20, 12)
hm = hips & fr.ngon(8, 18) & (np.hypot(fr.U, fr.V) > 4)
angs = np.degrees(np.arctan2(fr.V[hm], fr.U[hm])) % 45
chk("Octagonal pyramidal roof: hip ridges at 22.5° + k·45° (toward the eight vertices)", bool(np.all(np.abs(angs - 22.5) < 8)))
w = DictSink()
p = kit.Painter(w, kit.Frame(0.5, 0.5, 0.0, 6))
hstep = np.where(p.fr.U > 0, 8.0, 2.0)
PK.roof(p, p.fr.box(4, 4), 70, hstep, "minecraft:stone", shell=1)
x, z = p.fr.cell(0.7, 0.0)
col = [y for y in range(70, 80) if w.get(x, y, z) != "minecraft:air"]
chk("Roof shell: the row at a steep step extends down to meet the lower side (%s)" % col, col == list(range(73, 79)))

# ---------------------------------------------------------------- Chiang Kai-shek Memorial Hall
print("\nChiang Kai-shek Memorial Hall")
a, w, dt, _ = build("cks_memorial")
chk("Registry: cks_memorial -> CksMemorial", AT.registry().get("cks_memorial") is CksMemorial)
chk("One build takes %.1f s (called once per region, so it must stay well under a minute)" % dt, dt < 20)
G = a.G
ys = [k[1] for k in w.blocks]
chk("Highest point %d m above the ground (public sources: 70 m)" % (max(ys) - G), max(ys) - G == 70)
fh = a.fh


def local_cells(frame, pred, y):
    """Blocks in one layer that satisfy pred -> array of local coordinates (u, v)."""
    pts = [(x, z) for (x, yy, z), b in w.blocks.items() if yy == y and pred(b)]
    return np.array([frame.local(x, z) for x, z in pts]) if pts else np.zeros((0, 2))


blue = local_cells(fh, lambda b: base(b) in ("minecraft:blue_concrete", "minecraft:blue_glazed_terracotta"), G + 55)
near = blue[np.hypot(blue[:, 0], blue[:, 1]) < 40] if len(blue) else blue
ext = [float((near[:, 0] * math.cos(k * math.pi / 4) + near[:, 1] * math.sin(k * math.pi / 4)).max())
       for k in range(8)] if len(near) else [0]
chk("The upper roof is octagonal: the farthest extent along the eight side normals is %.1f–%.1f m (within 1.5 m)" % (min(ext), max(ext)),
    len(near) > 50 and max(ext) - min(ext) <= 1.5)
wall = local_cells(fh, lambda b: base(b) == "minecraft:smooth_quartz", G + 30)
wall = wall[np.maximum(np.abs(wall[:, 0]), np.abs(wall[:, 1])) < 30]
chk("The hall body is square: half-widths at y+30 are u %.1f, v %.1f (OSM 24.5; the corner piers taper upward)"
    % (np.abs(wall[:, 0]).max(), np.abs(wall[:, 1]).max()),
    abs(np.abs(wall[:, 0]).max() - np.abs(wall[:, 1]).max()) <= 1.0 and 24 <= np.abs(wall[:, 0]).max() <= 27)
# Grand staircase at the front: walking up from the plaza along the line v=12, the standing
# surface rises 0.5 m per step
heights = []
for uu in np.arange(-88.0, -36.0, 0.5):
    x, z = fh.cell(uu, 12.0)
    t = column_top(w, x, z)
    b = w.get(x, t, z)
    heights.append((t - G) + (0.5 if base(b).endswith("_slab") else 1.0) - 1.0)
steps_ = sorted(set(heights))
chk("Grand staircase at the front: standing surface 0 -> 14 m, 0.5 m per step (%d heights)" % len(steps_),
    steps_[0] == 0 and steps_[-1] == 14 and all(abs(b_ - a_ - 0.5) < 1e-6 for a_, b_ in zip(steps_, steps_[1:])))
x, z = fh.cell(-80.0, 0.0)
chk("The imperial way (the middle of the stairs) is white", base(w.get(x, column_top(w, x, z), z)).startswith("minecraft:smooth_quartz"))
x, z = fh.cell(-22.0, 0.0)
door = []
for y in range(G + 15, G + 40):
    if w.get(x, y, z) != "minecraft:air":
        break
    door.append(y - G)
chk("Main door: the doorway runs from platform level %d to %d (%d m high; public sources: 16 m)" % (door[0], door[-1], len(door)),
    door[0] == 15 and len(door) == 16 and base(w.get(x, G + 14, z)) != "minecraft:air")
bronze = [k for k, b in w.blocks.items() if base(b) in ("minecraft:waxed_copper_block", "minecraft:waxed_exposed_copper")
          and fh.local(k[0], k[2])[0] > 5]
by = [k[1] for k in bronze]
chk("Statue in the hall: %d bronze blocks, %d m high seated (public sources: 6.3 m), on a 3 m pedestal"
    % (len(bronze), max(by) - min(by) + 1), len(bronze) > 50 and 5 <= max(by) - min(by) + 1 <= 7
    and min(by) == G + 18)
lamps = [k for k, b in w.blocks.items() if base(b) == "minecraft:sea_lantern"
         and max(abs(fh.local(k[0], k[2])[0]), abs(fh.local(k[0], k[2])[1])) < 21]
chk("The hall is lit (%d lamps)" % len(lamps), len(lamps) >= 20)

# Paifang
fg = a.fg
runs, cur = 0, False
for uu in np.arange(-GATE_PILLARS[2], GATE_PILLARS[2], 0.25):
    x, z = fg.cell(uu, 0.0)
    open_ = w.get(x, G + 5, z) == "minecraft:air"
    if open_ and not cur:
        runs += 1
    cur = open_
chk("Liberty Square paifang: %d archways counted across its width at y+5 (five bays)" % runs, runs == 5)
gate_top = max(k[1] for k in w.blocks if abs(fg.local(k[0], k[2])[0]) < 45 and abs(fg.local(k[0], k[2])[1]) < 12)
chk("The paifang is %d m high (public sources: 30 m)" % (gate_top - G), 29 <= gate_top - G <= 31)
roof_eaves = set()
for sgn in (-1, 1):
    for uu in (0.0, 15.4, 28.0, GATE_PILLARS[0], GATE_PILLARS[1], GATE_PILLARS[2] + 0.6):
        x, z = fg.cell(sgn * uu, 0.0)
        roof_eaves.add((sgn * uu, column_top(w, x, z)))
chk("The paifang's eleven roofs: the central roof is highest, falling away to both sides (%s)" % sorted(roof_eaves),
    max(roof_eaves, key=lambda t: t[1])[0] == 0.0)

# National Theater and Concert Hall


def hall_stats(frame):
    tops, blocks = [], set()
    for (x, y, z), b in w.blocks.items():
        u, v = frame.local(x, z)
        if abs(u) <= 52 and abs(v) <= 58:
            blocks.add(base(b))
            if abs(u) < 3 and abs(v) < 2:
                tops.append(y)
    return max(tops) - G, blocks


ht, bt = hall_stats(a.ft)
hc, bc_ = hall_stats(a.fc)
chk("National Theater: main ridge %d m (OSM 37 m), yellow tiles, red columns" % ht,
    36 <= ht <= 38 and "minecraft:honeycomb_block" in bt and "minecraft:red_concrete" in bt)
chk("National Concert Hall: main ridge %d m, yellow tiles, red columns" % hc,
    36 <= hc <= 38 and "minecraft:honeycomb_block" in bc_ and "minecraft:red_concrete" in bc_)
chk("The Concert Hall is xieshan (blue gable pediments) and the Theater is hip (none)",
    "minecraft:blue_glazed_terracotta" in bc_ and "minecraft:blue_glazed_terracotta" not in bt)

# Teleport points, plaque
sp = a.spots()
g = get_fn(w)
chk("Teleport points %s; the first is the default viewpoint" % [s.key for s in sp], sp and sp[0].key == "" and len(sp) >= 2)
for s in sp:
    chk("Teleport point %r (%d,%d,%d) is standable" % (s.key, s.x, s.y, s.z), walk.standable(g, s.x, s.y, s.z))
s0 = sp[0]
want = kit.yaw_of(a.hall_c[0] - s0.x - 0.5, a.hall_c[1] - s0.z - 0.5)
chk("The default viewpoint faces the memorial hall (off by %.1f°)" % abs((s0.yaw - want + 180) % 360 - 180),
    abs((s0.yaw - want + 180) % 360 - 180) < 3)
signs = [v for k, v in w.signs.items() if abs(k[0] - s0.x) <= 3 and abs(k[2] - s0.z) <= 3]
chk("The first line of the plaque beside the viewpoint is 中正紀念堂", any(v and v[0] == "中正紀念堂" for v in signs))
en = SG.fit(a.plaque_en())
chk("The plaque's English line %r fits" % en, bool(a.plaque_en()) and "…" not in en)
chk("No sign in the grounds has a first line starting with 出口", not any(v and v[0].startswith("出口") for v in w.signs.values()))
chk("No yellow concrete (reserved for the platform warning strip)", not any(base(b) == "minecraft:yellow_concrete" for b in w.blocks.values()))
check_ids(w, "Chiang Kai-shek Memorial Hall")
# Keep-out zone: a zone across the stairs still blocks writes
kx, kz = fh.cell(-70.0, 0.0)
_, w2, _, dropped = build("cks_memorial", keep=lambda x, y, z: abs(x - kx) <= 2 and abs(z - kz) <= 2)
chk("Not a single block is written in the keep-out zone (%d writes blocked)" % dropped,
    dropped > 0 and not any(abs(k[0] - kx) <= 2 and abs(k[2] - kz) <= 2 for k in w2.blocks))

# ---------------------------------------------------------------- Sun Yat-sen Memorial Hall
print("\nSun Yat-sen Memorial Hall")
a, w, dt, _ = build("sun_yat_sen_memorial")
chk("Registry: sun_yat_sen_memorial -> SunYatSenMemorial",
    AT.registry().get("sun_yat_sen_memorial") is SunYatSenMemorial)
G = a.G
fr = a.fr
ys = [k[1] for k in w.blocks]
chk("Highest point %d m above the ground (public sources: 29.6–30.4 m)" % (max(ys) - G), max(ys) - G == 30)
en = SG.fit(a.plaque_en())
chk("The plaque's English line %r fits" % en, bool(a.plaque_en()) and "…" not in en)
top = max(w.blocks, key=lambda k: k[1])
tu, tv = fr.local(top[0], top[2])
chk("The highest point is on the main portico (u %.1f, v %.1f)" % (tu, tv), abs(tu) <= 18 and tv > 38)
corner = max(column_top(w, *fr.cell(su * 52.0, sv * 52.0)) for su in (-1, 1) for sv in (-1, 1)) - G
mid = column_top(w, *fr.cell(0.0, -51.0)) - G
chk("The flying eaves turn up at the corners: tips %d m, north mid-eave %d m" % (corner, mid), corner - mid >= 5 and 12 <= mid <= 15)
cols = 0
cur = False
for uu in np.arange(-52.0, 52.0, 0.25):
    x, z = fr.cell(uu, -47.0)
    c_ = base(w.get(x, G + 6, z)) == "minecraft:smooth_stone"
    if c_ and not cur:
        cols += 1
    cur = c_
chk("North colonnade: %d columns (public sources: 14 per side)" % cols, cols == 14)
names = {base(b) for b in w.blocks.values()}
chk("Large yellow roof, ochre-red outer walls, flat central roof",
    {"minecraft:honeycomb_block", "minecraft:red_terracotta", "minecraft:packed_mud"} <= names)
sp = a.spots()
g = get_fn(w)
for s in sp:
    chk("Teleport point %r (%d,%d,%d) is standable" % (s.key, s.x, s.y, s.z), walk.standable(g, s.x, s.y, s.z))
s0 = sp[0]
want = kit.yaw_of(a.c[0] - s0.x - 0.5, a.c[1] - s0.z - 0.5)
chk("The default viewpoint is on the front plaza, facing the memorial hall (off by %.1f°)" % abs((s0.yaw - want + 180) % 360 - 180),
    abs((s0.yaw - want + 180) % 360 - 180) < 3 and fr.local(s0.x, s0.z)[1] > 60)
signs = [v for k, v in w.signs.items() if abs(k[0] - s0.x) <= 3 and abs(k[2] - s0.z) <= 3]
chk("The first line of the plaque beside the viewpoint is 國父紀念館", any(v and v[0] == "國父紀念館" for v in signs))
chk("No yellow concrete", not any(base(b) == "minecraft:yellow_concrete" for b in w.blocks.values()))
check_ids(w, "Sun Yat-sen Memorial Hall")

print("\n" + ("All tests passed" if ok else "Some tests failed"))
sys.exit(0 if ok else 1)
