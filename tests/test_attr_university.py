#!/usr/bin/env python3
"""National Taiwan University (application/attractions/national_taiwan_university.py).

Builds the campus on flat ground (y66) into a DictSink, without writing a world save, and
checks the parts that matter most and break most easily:
  · Royal Palm Boulevard: asphalt along the OSM center line, a palm on every mapped palm
    (gray trunk, green crownshaft, 20–23 m to the top of the fronds), and the palms stand
    beside the road, not on it
  · The Main Library: built on its OSM outline, the entrance hall's great arched window
    faces the boulevard, the clock tower is the highest point, and nothing of it stands
    outside the outline
  · The main gate is low (about 3 m, as published), and Fu Bell hangs at its OSM node
  · Both viewpoints can be stood on, the default one faces the library, and the signs at
    each end take you to the other
  · build() only uses ground heights that plan() looked up, building twice gives the same
    result, not a block is written in a keep-out zone, every block id and state is known
    to 26.2 (checked only if the game is installed), and no yellow concrete is used

Usage: ./.venv/bin/python tests/test_attr_university.py
"""
import math
import os
import re
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application import attractions as AT
from mrt.application import signage as SG
from mrt.application.attractions import kit
from mrt.application.attractions import national_taiwan_university as NTU
from mrt.domain import geometry as shapes
from mrt.ports.block_sink import DictSink

G = 66
AID = "national_taiwan_university"
ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


class StrictGround:
    """Flat ground that raises if queried after plan(): cli clears the terrain cache after
    plan_all."""

    def __init__(self):
        self.locked = False

    def __call__(self, x, z):
        if self.locked:
            raise RuntimeError("build() queried ground that plan() did not look up: (%d, %d)" % (x, z))
        return G


def make(keep=None):
    items = [i for i in AT.load_items() if i["id"] == AID]
    a = AT.for_world([], items=items)[0]
    ground = StrictGround()
    t0 = time.time()
    a.plan(kit.Site(ground, keep))
    t1 = time.time()
    a.keep = keep
    ground.locked = True
    w = DictSink()
    err = None
    try:
        AT.build(a, w, keep)
    except Exception as e:                      # noqa: BLE001 -- the test prints the error
        err = e
    return a, w, t1 - t0, time.time() - t1, err


def base(b):
    return b.split("[")[0]


def solid(b):
    return base(b) not in ("minecraft:air", "minecraft:cave_air")


print("National Taiwan University")
a, w, dt_plan, dt, err = make()
chk("build() raised no error (%s)" % err, err is None)
chk("plan in %.1f s and build in %.1f s, %d blocks (each must stay well under a minute)"
    % (dt_plan, dt, len(w.blocks)), dt_plan < 60 and dt < 60)
chk("The campus stands at the ground level of the site (y%d)" % a.G, a.G == G)

cols = {}
for (x, y, z), b in w.blocks.items():
    if solid(b):
        cols.setdefault((x, z), []).append((y, b))


def top(x, z):
    c = cols.get((x, z))
    return max(y for y, _ in c) if c else None


def at(x, y, z):
    return w.blocks.get((x, y, z), "minecraft:air")


# ---- Royal Palm Boulevard ----
line = max(a.boulevard, key=len)
mid = [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) for p, q in zip(line, line[1:])]
road = [at(int(math.floor(x)), G, int(math.floor(z))) for x, z in mid]
chk("Asphalt all along the boulevard's center line (%d of %d points)"
    % (sum(b == NTU.ROAD for b in road), len(road)), all(b == NTU.ROAD for b in road))
trunks, tops, shafts, on_road = 0, [], 0, 0
for x, z in a.palms:
    bx, bz = int(math.floor(x)), int(math.floor(z))
    if at(bx, G + 5, bz) == NTU.PALM_TRUNK:
        trunks += 1
    if NTU.PALM_SHAFT in {b for _, b in cols.get((bx, bz), [])}:
        shafts += 1
    tops.append(top(bx, bz) - G)
    if at(bx, G, bz) == NTU.ROAD:
        on_road += 1
chk("A trunk and crownshaft on every palm (%d trunks, %d crownshafts, %d palms; %d of them "
    "mapped as trees)" % (trunks, shafts, len(a.palms),
                          sum(1 for f in a.features if "Roystonea" in f["tags"].get("species", ""))),
    trunks == shafts == len(a.palms) >= 172)
chk("Palms 17–20 m to the top of the crown, as the species grows (%d–%d m)" % (min(tops), max(tops)),
    17 <= min(tops) and max(tops) <= 20)
chk("No palm stands on the road (%d do)" % on_road, on_road == 0)

# ---- The Main Library ----
lib = a.feature(NTU.LIBRARY)
cells = shapes.poly_cells(max(lib["outer"], key=len))
lib_top = max((top(x, z) or G) for x, z in cells)
covered = sum(1 for x, z in cells if (top(x, z) or G) >= G + 3) / len(cells)
chk("The library covers its outline (%.0f%% of cells have something 3 m up)" % (covered * 100),
    covered >= 0.8)
near = set()
for x, z in cells:
    for dx in (-3, -2, -1, 0, 1, 2, 3):
        for dz in (-3, -2, -1, 0, 1, 2, 3):
            near.add((x + dx, z + dz))
lx0 = min(x for x, _ in cells)
tall_out = [(x, z) for (x, z) in cols if x >= lx0 - 8 and (x, z) not in near
            and (top(x, z) or G) >= G + 12 and not any(b in (NTU.PALM_TRUNK, NTU.PALM_LEAF, NTU.PALM_SHAFT)
                                                       for _, b in cols[(x, z)])
            and abs(z - a.lib_origin[1]) < 90]
chk("Nothing of the library stands more than 3 blocks outside its outline (%d columns)" % len(tall_out),
    not tall_out)
tower = a.feature(NTU.TOWER)
cc = shapes.poly_cells(max(tower["outer"], key=len))
tower_top = max(top(x, z) for x, z in cc)
rest = max((top(x, z) or G) for x, z in cells - cc)
chk("The bell tower is the library's highest point, about twice the north wing's 18 m "
    "(%d m; the rest reaches %d m)" % (tower_top - G, rest - G),
    tower_top == lib_top and 34 <= tower_top - G <= 40)
court = [(x, z) for x, z in zip(a.fa.X[a.court].tolist(), a.fa.Z[a.court].tolist())]
sunk = sum(1 for x, z in court if at(x, G - NTU.SUNK, z) != "minecraft:air"
           and not solid(at(x, G - NTU.SUNK + 1, z)))
chk("The northern courtyard is sunk one story (%d of %d cells floored at y%d)"
    % (sunk, len(court), G - NTU.SUNK), court and sunk >= 0.8 * len(court))
fr = a.lib_fr
glass = 0
for (x, y, z), b in w.blocks.items():
    if b == NTU.GLASS and y >= G + 8:
        u, v = fr.local(x, z)
        if 5 < u < 15 and abs(v) <= 5:
            glass += 1
chk("The entrance hall's great window faces the boulevard (%d glass blocks)" % glass, glass >= 40)

# ---- The gate and Fu Bell ----
gate = a.feature(NTU.GATE)
gc = shapes.poly_cells(max(gate["outer"], key=len))
gtop = max(max(y for y, b in cols[(x, z)] if base(b) != "minecraft:iron_bars")
           for x, z in gc if (x, z) in cols) - G
chk("The main gate's guardhouse is low, like a blockhouse (%d m to its coping; published: "
    "about 3 m)" % gtop, 3 <= gtop <= 6)
frame = [k for k, b in w.blocks.items() if base(b) == NTU.IRON and abs(k[0] - int(a.bell["point"][0])) <= 2]
chk("Fu Bell's frame stands over 5 m (%d m)" % (max(k[1] for k in frame) - G if frame else 0),
    frame and max(k[1] for k in frame) - G > 5)
bx, bz = (int(math.floor(c)) for c in a.bell["point"])
bells = [k for k, b in w.blocks.items() if base(b) == "minecraft:bell"]
chk("Fu Bell hangs at its OSM node (%s)" % bells,
    len(bells) == 1 and abs(bells[0][0] - bx) <= 1 and abs(bells[0][2] - bz) <= 1)

# ---- Viewpoints and signs ----
sp = a.spots()
chk("Two viewpoints: the default one and the gate end (%s)" % [s.key for s in sp],
    [s.key for s in sp] == ["", "gate"])
for s in sp:
    feet, head, below = at(s.x, s.y, s.z), at(s.x, s.y + 1, s.z), at(s.x, s.y - 1, s.z)
    chk("Viewpoint %r can be stood on (feet %s, head %s, below %s)" % (s.key, feet, head, below),
        not solid(feet) and not solid(head) and solid(below))
xs = [p[0] for p in cells]
zs = [p[1] for p in cells]
cx, cz = sum(xs) / len(xs), sum(zs) / len(zs)
s0 = sp[0]
want = math.degrees(math.atan2(-(cx + 0.5 - s0.x), cz + 0.5 - s0.z))
dev = abs((s0.yaw - want + 180) % 360 - 180)
chk("The default viewpoint faces the library (off by %.0f°)" % dev, dev <= 45)
for (x, y, z), lines in w.signs.items():
    chk("No sign's first line starts with 出口 (%s)" % lines[0], not lines[0].startswith("出口"))
front, back = AT.plaque_lines(a)
chk("The plaque stands next to the default viewpoint and names the university",
    any(abs(k[0] - s0.x) <= 3 and abs(k[2] - s0.z) <= 3 and v[0] == a.name_zh for k, v in w.signs.items()))
en = SG.fit(a.plaque_en())
chk("English line %r fits the sign and is on the back of the plaque" % en, en in back)
chk("Both fact lines fit on one sign line (%d and %d px)"
    % (SG.text_width(a.plaque()[2]), SG.text_width(a.plaque()[3])),
    all(SG.text_width(t) <= SG.SIGN_W for t in a.plaque()[2:]))
chk("A sign at each end of the boulevard: %d signs within 3 blocks of the two viewpoints"
    % sum(1 for k in w.signs for s in sp if abs(k[0] - s.x) <= 3 and abs(k[2] - s.z) <= 3),
    sum(1 for k in w.signs for s in sp if abs(k[0] - s.x) <= 3 and abs(k[2] - s.z) <= 3) >= 3)
chk("The gate end's function path is sight/%s_gate" % AID, kit.sight_fn(AID, "gate") == "sight/%s_gate" % AID)

# ---- Framework rules ----
w2 = DictSink()
AT.build(a, w2, None)
chk("Building twice gives the same result", w2.blocks == w.blocks)
names = {base(b) for b in w.blocks.values()}
chk("No yellow concrete (reserved for the platform warning strip)", "minecraft:yellow_concrete" not in names)
# A keep-out strip across the boulevard and the library front: nothing may be written in it.
kx = int(a.lib_origin[0]) - 2


def keep(x, y, z):
    return kx <= x <= kx + 4 or 1900 <= x <= 1903


k_a, k_w, _, _, k_err = make(keep)
hit = [k for k in k_w.blocks if keep(*k)]
chk("Nothing is written in a keep-out zone (%d blocks; %s)" % (len(hit), k_err), not hit and k_err is None)

jar = os.path.expanduser("~/Library/Application Support/minecraft/versions/26.2/26.2.jar")
if os.path.exists(jar):
    z = zipfile.ZipFile(jar)
    table = {}
    for n in z.namelist():
        m = re.match(r"assets/minecraft/blockstates/([a-z0-9_]+)\.json$", n)
        if m:
            table["minecraft:" + m.group(1)] = n
    bad = sorted(names - set(table))
    chk("Every block id exists in 26.2 (%s)" % bad[:5], not bad)
    wrong = set()
    for b in set(w.blocks.values()):
        if "[" not in b or base(b) not in table:
            continue
        txt = z.read(table[base(b)]).decode("utf-8")
        for pv in b[b.index("[") + 1:-1].split(","):
            k, v = pv.split("=")
            if k in ("waterlogged", "persistent", "distance"):
                continue
            if ("%s=%s" % (k, v)) not in txt and ('"%s": "%s"' % (k, v)) not in txt:
                wrong.add(pv + " @" + base(b))
    chk("Every block state value is valid (%s)" % sorted(wrong)[:4], not wrong)
else:
    print("  --   26.2 is not installed; skipping the block id check")

print("\n" + ("All tests passed" if ok else "Some tests failed"))
sys.exit(0 if ok else 1)
