#!/usr/bin/env python3
"""Taipei 101 and Shin Kong Life Tower (application/attractions/taipei101.py, shin_kong.py).

Builds each once on flat ground (y66) into a DictSink, without writing a world save:
  · Taipei 101: spire = ground floor + 508; eight modules (each module top has an
    overhang, and the half-width steps back by 4 m between modules); the ground-level plan
    is about 54 m square and the waist about 44 m; the 89F observatory slab is at +382 and
    standable; the damper is a gold sphere; the lobby and observatory signs teleport to
    each other (function paths as in kit.sight_fn)
  · Shin Kong: antenna top = ground floor + 244; the corners step back story by story as
    in OSM (nothing above 187 m at the 44-story corner); the main outline is almost fully
    covered; the north vestibule has doors; the lobby is standable
  · Both: nothing is written in keep-out zones; the plaque's first line is the
    attraction's Chinese name and fits; no sign's first line starts with `出口`; no yellow
    concrete (reserved for the platform warning strip); every block id is in the 26.2 jar
    (checked only if the jar is found)

Usage: ./.venv/bin/python tests/test_attr_skyscrapers.py
"""
import math
import os
import re
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt import config
from mrt.application import attractions as AT
from mrt.application import signage as SG
from mrt.application.attractions import kit
from mrt.application.attractions import shin_kong as SK
from mrt.application.attractions import taipei101 as T1
from mrt.domain import geometry as shapes
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def solid(b):
    return b is not None and b.split("[")[0] not in ("minecraft:air", "minecraft:cave_air")


def build(aid, keep=None):
    items = [it for it in AT.load_items() if it["id"] == aid]
    a = AT.for_world([], items=items)[0]
    AT.plan_all([a], lambda x, z: 66, keep, say=lambda *_: None)
    w = DictSink()
    t0 = time.time()
    dropped = AT.build(a, w, keep)
    return a, w, time.time() - t0, dropped


def jar_blocks():
    jar = os.path.expanduser("~/Library/Application Support/minecraft/versions/26.2/26.2.jar")
    if not os.path.exists(jar):
        return None
    out = set()
    for n in zipfile.ZipFile(jar).namelist():
        m = re.match(r"assets/minecraft/blockstates/([a-z0-9_]+)\.json$", n)
        if m:
            out.add("minecraft:" + m.group(1))
    return out


JAR = jar_blocks()


def common(a, w):
    names = {b.split("[")[0] for b in w.blocks.values()}
    chk("No yellow concrete (reserved for the platform warning strip)",
        "minecraft:yellow_concrete" not in names)
    if JAR is not None:
        bad = sorted(n for n in names if n not in JAR)
        chk("Every block id is in the 26.2 jar (%d kinds)%s"
            % (len(names), (", missing: %s" % bad) if bad else ""),
            not bad)
    firsts = [v[0] for v in w.signs.values()]
    chk('No sign\'s first line starts with "出口" (%d signs)' % len(firsts),
        not any(f.startswith("出口") for f in firsts))
    front, back = AT.plaque_lines(a)
    # The fourth line on the back (the OSM credit) is the framework's.
    mine = front[:3] + back[:3]
    chk('Plaque: first line is "%s", and the attraction\'s text fits (%s)'
        % (a.name_zh, [SG.line_width(t) for t in mine]),
        front[0]["text"] == a.name_zh and all(SG.line_width(t) <= SG.SIGN_W for t in mine)
        and "…" not in "".join(str(t if isinstance(t, str) else t["text"]) for t in mine))
    en = SG.fit(a.plaque_en())
    chk("English line %r fits the sign and is on the back of the plaque" % en,
        bool(a.plaque_en()) and "…" not in en and en in back)
    sp = a.spots()
    chk("The first teleport point is the default viewpoint (empty key)", sp and sp[0].key == "")
    for s in sp[1:]:
        st = walk.standable(w.get, s.x, s.y, s.z)
        chk("Teleport point %s (%d,%d,%d) is standable (feet %s, below %s)" % (
            s.key, s.x, s.y, s.z, w.get(s.x, s.y, s.z), w.get(s.x, s.y - 1, s.z)), st)


# ================================================================ Taipei 101
print("Taipei 101")
a, w, dt, _ = build("taipei101")
g0 = a.g0
ys = [k[1] for k in w.blocks]
chk("One build takes %.1f s (called once per region, so it must stay well under a minute)" % dt, dt < 30)
chk("Ground floor slab at y%d (flat ground at y66)" % g0, g0 == 66)
chk("Highest point y%d = ground floor + %d (spire 508 m)" % (max(ys), max(ys) - g0), max(ys) == g0 + 508)
chk("top_y() matches the actual highest point", a.top_y() == max(ys))
cx, cz = a.fr.world(0, 0)
ymax = max(ys)
tip = [k for k in w.blocks if k[1] == ymax]
chk("The spire is at the tower's centre (%s, centre %.1f,%.1f)" % (tip, cx, cz),
    all(abs(x + .5 - cx) <= 1 and abs(z + .5 - cz) <= 1 for x, _, z in tip))
chk("The spire is near OSM's spire position (way/615183623, about 4782,1374)",
    abs(cx - 4782.2) < 1.5 and abs(cz - 1373.8) < 1.5)


def south_extent(yy, du=10.0):
    """Return how far south (local +v) the tower has blocks.

    Measured 10 m east of the centerline, because the ruyi and the coins project at the
    middle."""
    best = None
    for k in range(0, 120):
        d = k * 0.5
        x, z = a.fr.cell(du, d)
        if solid(w.blocks.get((x, g0 + yy, z))):
            best = d
    return best


prof = {yy: south_extent(yy) for yy in range(120, 400)}
# The top of each module: a local maximum of the profile that steps back 3 m or more within four
# rows above (three rows of sloped glass sit between modules).
drops = [yy for yy in range(122, 393) if None not in (prof[yy - 1], prof[yy], prof[yy + 1], prof[yy + 4])
         and prof[yy] > prof[yy + 1] and prof[yy] >= prof[yy - 1] and prof[yy] - prof[yy + 4] >= 3]
chk("Eight modules: one setback at each module top from 27F up and one more at 91F, 8 in all (at %s)"
    % drops,
    len(drops) == 8)
flare = [prof[d] - prof[d - 25] for d in drops[:7]]
chk("Each module flares outward: its top is 2–4 m wider than 25 rows below (%s)" % flare,
    all(2 <= f <= 4.5 for f in flare))
base0 = T1.tower_mass(a.F, 0)
e0 = float(a.F.S[base0].max())
e40 = south_extent(40)
waist = south_extent(123)
chk("Half-width of the ground-level plan %.1f m (OSM tower "
    "outline 54 m square; the middle bay projects 1 m more)" % e0,
    27 <= e0 <= 28.6)
chk("The base tapers inward: half-width %.1f m at 40 m" % e40, 25 <= e40 <= e0)
chk("Half-width of the waist (bottom of the first module) %.1f m (about 45.9 m square)" % waist,
    21 <= waist <= 23.5)
top_floor = [k for k in w.blocks if k[1] == g0 + T1.OBS_ROW]
chk("The 89F slab is at ground floor +%d (382 m)" % T1.OBS_ROW,
    T1.OBS_ROW == 382 and len(top_floor) > 1500)
sp = {s.key: s for s in a.spots()}
chk("Teleport points: default, lobby, top", sorted(sp) == ["", "lobby", "top"])
chk("top is on 89F (feet at +383)", sp["top"].y == g0 + 383)
gold = [k for k, v in w.blocks.items() if v == "minecraft:gold_block" and 378 <= k[1] - g0 <= 388]
chk("Damper: a gold steel sphere on 89F (%d blocks; 5.5 m across is about 87 blocks)" % len(gold),
    60 <= len(gold) <= 120)
cmds = {tuple(v): w.sign_meta[k]["command"] for k, v in w.signs.items()}
ns = config.DATAPACK_NS
lob = [c for l, c in cmds.items() if l[0].startswith("89 樓觀景台")]
back = [c for l, c in cmds.items() if l[0].startswith("回 1 樓")]
chk("The lobby sign teleports to 89F: %s" % lob,
    lob == ["function %s:%s" % (ns, kit.sight_fn("taipei101", "top"))])
chk("The observatory sign teleports back to the lobby: %s" % back,
    back == ["function %s:%s" % (ns, kit.sight_fn("taipei101", "lobby"))])
lsign = [k for k, v in w.signs.items() if v[0].startswith("89 樓觀景台")][0]
tsign = [k for k, v in w.signs.items() if v[0].startswith("回 1 樓")][0]
chk("The lobby sign is on the ground floor (y%d), the observatory sign on 89F (y%d)"
    % (lsign[1], tsign[1]),
    lsign[1] == g0 + 1 and tsign[1] == g0 + 383)
chk("The signs are pale oak with glow ink",
    all(w.sign_meta[k]["wood"] == "pale_oak" and w.sign_meta[k]["glow"]
                            for k in (lsign, tsign)))
doors = [k for k, v in w.blocks.items() if "door" in v and "half=lower" in v]
chk("The ground floor has doors (two each on the south and east: %d)" % len(doors),
    len(doors) == 4 and all(k[1] == g0 + 1 for k in doors))
d0 = sp[""]
dist = math.hypot(d0.x - cx, d0.z - cz)
chk("The default viewpoint is %.0f m from the tower, with "
    "the spire at %.0f° elevation (must fit a 70° view)" % (
    dist, math.degrees(math.atan2(508, dist))), math.degrees(math.atan2(508, dist)) < 69)
mall = shapes.poly_cells(a._ring(T1.MALL))
roof = sum(1 for x, z in mall if any(solid(w.blocks.get((x, g0 + yy, z))) for yy in range(26, 44)))
chk("Mall (OSM outline, %d cells): %.0f%% is built up to about 30 m"
    % (len(mall), 100.0 * roof / len(mall)),
    roof >= 0.9 * len(mall))
common(a, w)

print("\nKeep-out zone")
kx, kz = a.fr.cell(0.0, 20.0)
a2, w2, _, dropped = build("taipei101", keep=lambda x, y, z: (x, z) == (kx, kz))
chk("Not a single block is written in the keep-out column (%d blocks blocked)" % dropped,
    dropped > 0 and not any((x, z) == (kx, kz) for x, _, z in w2.blocks))

# ================================================================ Shin Kong Life Tower
print("\nShin Kong Life Tower")
s, w, dt, _ = build("shin_kong_tower")
g0 = s.g0
ys = [k[1] for k in w.blocks]
chk("One build takes %.1f s" % dt, dt < 30)
chk("Highest point y%d = ground floor + %d (antenna 244.15 m)" % (max(ys), max(ys) - g0),
    max(ys) == g0 + 244)
colmax = {}
for (x, y, z), b in w.blocks.items():
    # The thin overhangs reach out over the corner one step lower.
    if solid(b) and not b.startswith(SK.LEDGE.split("[")[0]):
        if y > colmax.get((x, z), -999):
            colmax[(x, z)] = y
main = shapes.poly_cells(s.part_ring(SK.MAIN))
cov = sum(1 for c in main if colmax.get(c, -999) >= g0 + 3)
chk("Main outline (%d cells): %.0f%% have something more than 3 blocks above the ground"
    % (len(main), 100.0 * cov / len(main)),
    cov >= 0.95 * len(main))
corner = shapes.poly_cells(s.part_ring("way/644774199"))     # The 44-story (187.36 m) corner.
tops = sorted({colmax.get(c, -999) - g0 for c in corner})
chk("Sawtooth corner: the top of the 44-storey corner is at 186–187 (%s)" % tops,
    tops and all(185 <= t <= 187 for t in tops))
corner = shapes.poly_cells(s.part_ring("way/644774198"))     # The 46-story (195.68 m) corner.
tops = sorted({colmax.get(c, -999) - g0 for c in corner})
chk("Sawtooth corner: the top of the 46-storey corner is at 194–195 (%s)" % tops,
    tops and all(193 <= t <= 195 for t in tops))
body = shapes.poly_cells(s.part_ring(SK.TOWER_BODY))
tb = [colmax.get(c, -999) - g0 for c in body]
chk("Tower body (50 storeys, 211.04 m): at least 80 per cent "
    "of the columns in the outline top out above 210 m (%d/%d)" % (
    sum(1 for t in tb if t >= 210), len(tb)), sum(1 for t in tb if t >= 210) >= 0.8 * len(tb))
ymax = max(ys)
top = [v for k, v in w.blocks.items() if k[1] == ymax]
chk("A pyramid and a finial on top (%s)" % top,
    top == ["minecraft:lightning_rod[facing=up,powered=false]"])
pyr = sum(1 for k, v in w.blocks.items() if v == SK.PYRAMID)
chk("Pyramid: %d blocks" % pyr, pyr > 100)
doors = [k for k, v in w.blocks.items() if "door" in v and "half=lower" in v]
chk("The north vestibule has two doors (%s)" % doors,
    len(doors) == 2 and all(k[1] == g0 + 1 for k in doors)
    and all(k[2] < 0 for k in doors))
common(s, w)

print("\nRegistry")
reg = AT.registry()
chk("taipei101 -> Taipei101, shin_kong_tower -> ShinKongTower",
    reg.get("taipei101") is T1.Taipei101 and reg.get("shin_kong_tower") is SK.ShinKongTower)

print("\n" + ("All tests passed" if ok else "Some tests failed"))
sys.exit(0 if ok else 1)
