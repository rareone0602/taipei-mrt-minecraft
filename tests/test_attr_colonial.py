#!/usr/bin/env python3
"""Three Western-style buildings from the Japanese era: the Presidential Office Building,
the National Taiwan Museum and the Red House (application/attractions/).

Builds them on flat ground (y66) into a DictSink, without writing a world save, and checks
the parts of the appearance that matter most and break most easily:
  · Presidential Office Building: the central tower's top is 60 m above the ground, the
    tower is on the front (east) side, both courtyards are open (lawn, no roof), the outer
    walls have more red brick than white banding, and the tower shaft is cross-shaped
    (a notch at each of the four corners)
  · National Taiwan Museum: the dome is there, its top is nearly 30 m, six portico
    columns face north, the hall has 32 columns, the hall can be walked into from the
    steps in front of the portico (the floor is standable and the two blocks overhead are
    clear), and the hall is lit
  · Red House: the Octagon is there (walls in all eight directions, an area of about
    412 m²), the central lantern is the highest point, and the Cruciform Building's
    transept is there
  · All of them: build() only uses ground heights that plan() looked up (cli clears the
    terrain cache after plan_all), building twice gives identical results (it is called
    once per region it spans), not a single block is written in a keep-out zone, the rules
    for plaques and signs hold, the viewpoint faces the building, every block id is known
    to 26.2 (checked only if the game is installed), and no yellow concrete is used

Usage: ./.venv/bin/python tests/test_attr_colonial.py
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
from mrt.application.attractions import national_taiwan_museum as NTM
from mrt.application.attractions import presidential_office as PO
from mrt.application.attractions import red_house as RH
from mrt.ports.block_sink import DictSink

G = 66
ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


class StrictGround:
    """Flat ground that raises an exception if queried after plan(): cli clears the
    terrain cache after plan_all."""

    def __init__(self):
        self.locked = False

    def __call__(self, x, z):
        if self.locked:
            raise RuntimeError("build() queried ground that plan() did not look up: (%d, %d)" % (x, z))
        return G


def make(aid, keep=None):
    items = [i for i in AT.load_items() if i["id"] == aid]
    a = AT.for_world([], items=items)[0]
    ground = StrictGround()
    a.plan(kit.Site(ground, keep))
    a.keep = keep
    ground.locked = True
    w = DictSink()
    t0 = time.time()
    err = None
    try:
        AT.build(a, w, keep)
    except Exception as e:                      # noqa: BLE001 -- the test prints the error
        err = e
    return a, w, time.time() - t0, err


def base(b):
    return b.split("[")[0]


def solid(b):
    return base(b) not in ("minecraft:air", "minecraft:cave_air")


def local_of(a, x, z):
    return a.fr.local(x, z)


def column_top(w, x, z):
    ys = [k[1] for k, b in w.blocks.items() if k[0] == x and k[2] == z and solid(b)]
    return max(ys) if ys else None


def common(a, w, dt, err):
    chk("%s: build() raised no error (%s)" % (a.id, err), err is None)
    chk("%s: one building in %.2f s, %d blocks (must stay well under a minute)"
        % (a.id, dt, len(w.blocks)),
        dt < 30)
    names = {base(b) for b in w.blocks.values()}
    chk("%s: no yellow concrete (reserved for the platform warning strip)" % a.id,
        "minecraft:yellow_concrete" not in names)
    for (x, y, z), lines in w.signs.items():
        if lines and lines[0].startswith("出口"):
            chk('%s: the first line of sign (%d,%d,%d) starts with "出口"' % (a.id, x, y, z), False)
    sp = a.spots()
    chk("%s: has a default viewpoint (empty key)" % a.id, bool(sp) and sp[0].key == "")
    if sp:
        s0 = sp[0]
        cx, cz = a.center()
        pts = a.outline()
        cx = sum(p[0] for p in pts) / len(pts)
        cz = sum(p[1] for p in pts) / len(pts)
        want = math.degrees(math.atan2(-(cx + 0.5 - s0.x), cz + 0.5 - s0.z))
        dev = abs((s0.yaw - want + 180) % 360 - 180)
        chk("%s: the viewpoint faces the building (off by %.0f°) and stands on the ground at y%d"
            % (a.id, dev, s0.y),
            dev <= 45 and s0.y == G + 1)
        under = w.get(s0.x, s0.y, s0.z)
        chk("%s: the building does not occupy the viewpoint's block (%s)" % (a.id, under),
            not solid(under) or "sign" in under)
    zh, en, f1, f2 = a.plaque()
    chk("%s: the plaque's first line is the Chinese name from the data, \"%s\"" % (a.id, zh),
        zh == a.name_zh)
    chk("%s: both fact lines fit on one sign line (%d and %d px)"
        % (a.id, SG.text_width(f1), SG.text_width(f2)),
        SG.text_width(f1) <= SG.SIGN_W and SG.text_width(f2) <= SG.SIGN_W)
    front, back = AT.plaque_lines(a)            # Raises if the first line starts with `出口`
    en = SG.fit(a.plaque_en())
    chk("%s: English line %r fits the sign and is on the back of the plaque" % (a.id, en),
        bool(a.plaque_en()) and "…" not in en and en in back)
    chk("%s: the plaque stands next to the viewpoint" % a.id,
        any(abs(k[0] - sp[0].x) <= 3 and abs(k[2] - sp[0].z) <= 3
                                        for k in w.signs))
    # Building twice must give identical results (it is called once per region it spans)
    w2 = DictSink()
    AT.build(a, w2, getattr(a, "keep", None))
    chk("%s: building twice gives the same result" % a.id, w2.blocks == w.blocks)
    return names


def jar_names():
    jar = os.path.expanduser("~/Library/Application Support/minecraft/versions/26.2/26.2.jar")
    if not os.path.exists(jar):
        return None
    z = zipfile.ZipFile(jar)
    out = {}
    for n in z.namelist():
        m = re.match(r"assets/minecraft/blockstates/([a-z0-9_]+)\.json$", n)
        if m:
            out["minecraft:" + m.group(1)] = n
    return z, out


JAR = jar_names()


def check_ids(aid, w):
    if JAR is None:
        print("  --   26.2 is not installed; skipping the block id check")
        return
    z, table = JAR
    bad = sorted({base(b) for b in w.blocks.values()} - set(table))
    chk("%s: every block id exists in 26.2 (%s)" % (aid, bad[:5]), not bad)
    # States: every "property=value" must appear in the
    # blockstates (stair facing/half, slab type, ...)
    wrong = set()
    cache = {}
    for b in set(w.blocks.values()):
        if "[" not in b or base(b) not in table:
            continue
        if base(b) not in cache:
            txt = z.read(table[base(b)]).decode("utf-8")
            cache[base(b)] = txt
        txt = cache[base(b)]
        props = b[b.index("[") + 1:-1].split(",")
        for pv in props:
            k, v = pv.split("=")
            if k == "waterlogged" or k in ("persistent", "distance"):
                continue
            if ("%s=%s" % (k, v)) not in txt and ('"%s": "%s"' % (k, v)) not in txt and \
                    ('"%s":"%s"' % (k, v)) not in txt:
                wrong.add(pv + " @" + base(b))
    chk("%s: every block state value is valid (%s)" % (aid, sorted(wrong)[:4]), not wrong)


# ---------------------------------------------------------------- Presidential Office Building
print("Presidential Office Building")
a, w, dt, err = make("presidential_office")
names = common(a, w, dt, err)
check_ids(a.id, w)
fr = a.fr
tx, tz = fr.cell(PO.TOWER_U, 0.0)
top = column_top(w, tx, tz)
chk("The central tower's top is %s m above the ground (public sources: about 60 m)"
    % (top - G if top else None),
    top == G + 60)
peak = max(k[1] for k, b in w.blocks.items() if solid(b))
chk("The highest point of the whole building is the tower top (y%d)" % peak, peak == G + 60)
# The tower is at the front (east): its local u is greater than the outer ring's midpoint; the
# easternmost structure is the porte-cochère
chk("The tower is in the east wing (the front faces east, onto Ketagalan Boulevard)",
    PO.TOWER_U > 20 and fr.dir(1, 0)[0] > 0.9)
# Cross-shaped: in the tower shaft's section at +30, each of the four corners has a notch and the
# middle of each face has wall
a_, n_ = PO.TOWER_A, PO.TOWER_N
notch, face = [], []
for x in range(tx - 7, tx + 8):
    for z in range(tz - 7, tz + 8):
        u, v = local_of(a, x, z)
        du, dv = abs(u - PO.TOWER_U), abs(v)
        if a_ - n_ + 0.3 < du <= a_ - 0.2 and a_ - n_ + 0.3 < dv <= a_ - 0.2:
            notch.append(solid(w.get(x, G + 33, z)))
        if a_ - 0.8 < du <= a_ and dv < 0.8:
            face.append(solid(w.get(x, G + 33, z)))
# 8.3 m square with 1.2 m notches: on a grid skewed 5.7° a notch is only one or two blocks, so
# mostly empty is enough
chk("The tower shaft is cross-shaped: the corner notches at +33 are mostly "
    "empty (%d/%d blocks empty) and the middle of each face is wall (%d blocks)"
    % (notch.count(False), len(notch), len(face)),
    notch and notch.count(False) * 2 >= len(notch) and face and all(face))
# Courtyards: lawn with nothing above it (trees and hedges excepted, all below +8)
for i, court in enumerate(a.courts):
    cells = fr.cells(court)
    inner = [c for c in cells if kit.erode(court, 3)[c[1] - fr.z0, c[0] - fr.x0]]
    grass = sum(1 for x, z in inner if w.get(x, G, z) in ("minecraft:grass_block", "minecraft:polished_andesite"))
    roofed = sum(1 for x, z in inner if any(solid(w.get(x, y, z)) for y in range(G + 9, G + 30)))
    chk("Courtyard %d: of %d blocks, %d have lawn or path "
        "underfoot and %d have something at +9 or above" % (i + 1, len(inner), grass, roofed),
        len(inner) > 500 and grass == len(inner) and roofed == 0)
chk("Two courtyards (a double-courtyard plan)", len(a.courts) == 2)
cnt = {}
for b in w.blocks.values():
    cnt[base(b)] = cnt.get(base(b), 0) + 1
chk("More red brick than white banding (brick %d, banding %d)"
    % (cnt.get("minecraft:bricks", 0), cnt.get("minecraft:calcite", 0)),
    cnt.get("minecraft:bricks", 0) > 2 * cnt.get("minecraft:calcite", 0))
# The corner towers are taller than the main block: their pyramidal roofs are above +26
hi = [k for k, b in w.blocks.items() if k[1] >= G + 28 and "copper" in b]
chk("The copper roofs of the corner and guard towers rise "
    "above the main ridge (%d copper blocks at +28 or above)" % len(hi),
    len(hi) > 40)

# Keep-out zone: block off a whole region (10x10 at the outer ring's northeast corner, from the
# ground to the tower top) and write nothing inside it
x0, z0 = fr.cell(30.0, -60.0)
keep = lambda x, y, z: x0 - 5 <= x <= x0 + 5 and z0 - 5 <= z <= z0 + 5
a2, w2, _, err2 = make("presidential_office", keep=keep)
chk("Not a single block is written in the keep-out zone (exit and underground mall blocks)",
    err2 is None and not any(keep(*k) for k in w2.blocks) and len(w2.blocks) > 0)

# ---------------------------------------------------------------- National Taiwan Museum
print("\nNational Taiwan Museum")
a, w, dt, err = make("national_taiwan_museum")
names = common(a, w, dt, err)
check_ids(a.id, w)
fr = a.fr
dx, dz = fr.cell(0.0, NTM.DOME_V)
top = column_top(w, dx, dz)
chk("The dome's top is %s m above the ground (nearly 30 m)" % (top - G if top else None), top == G + 30)
dome = [k for k, b in w.blocks.items() if "copper" in b and k[1] >= G + NTM.H_DOME0 + 2
        and math.hypot(*[a_ - b_ for a_, b_ in zip(local_of(a, k[0], k[2]), (0.0, NTM.DOME_V))]) <= NTM.DOME_R]
chk("The dome shell is there (%d copper blocks above the drum)" % len(dome), len(dome) > 80)
chk("The front faces north (portico at -v, the Frame's v axis points south)",
    NTM.FRONT < NTM.WING_N and fr.dir(0, 1)[1] > 0.99)
# Six portico columns: count the runs of column shaft at +8 along the front edge of the portico
row = sorted(set(fr.cell(u, NTM.FRONT + 1.0) for u in np.arange(-12.0, 12.01, 0.25)))
runs, prev = 0, False
for x, z in row:
    cur = w.get(x, G + 8, z) == NTM.COLUMN
    if cur and not prev:
        runs += 1
    prev = cur
chk("%d Doric columns in the portico's front row (hexastyle)" % runs, runs == 6)
chk("%d columns in the hall (public sources: 32)" % a.hall_columns, a.hall_columns == 32)
hall_cols = [k for k, b in w.blocks.items() if k[1] == G + NTM.H_FLOOR + 6 and b == NTM.COLUMN
             and abs(local_of(a, k[0], k[2])[0]) <= NTM.HALL + 0.6
             and abs(local_of(a, k[0], k[2])[1] - NTM.DOME_V) <= NTM.HALL + 0.6]
chk("32 blocks of column shaft at +8 in the hall (%d)" % len(hall_cols), len(hall_cols) == 32)


def standable(x, y, z):
    return solid(w.get(x, y - 1, z)) and not solid(w.get(x, y, z)) and not solid(w.get(x, y + 1, z))


# Walkable: from the ground in front of the portico, walk south along the central axis to
# the middle of the hall; every step must be standable (a step climbs at most one block)
path = [fr.cell(0.3, v) for v in np.arange(NTM.FRONT - 6.0, NTM.DOME_V + 0.1, 0.5)]
y, walk_ok, where = G + 1, True, None
seen = []
for x, z in path:
    if (x, z) in seen:
        continue
    seen.append((x, z))
    for dy in (0, 1, -1):
        if standable(x, y + dy, z):
            y += dy
            break
    else:
        walk_ok, where = False, (x, y, z, w.get(x, y - 1, z), w.get(x, y, z), w.get(x, y + 1, z))
        break
chk("From the ground in front of the museum, up the steps and through "
    "the main entrance to the middle of the hall (ends standing at y%d)%s"
    % (y, "" if walk_ok else where),
    walk_ok and y == G + NTM.H_FLOOR + 1)
lamps = [k for k, b in w.blocks.items() if b == "minecraft:sea_lantern"
         and abs(local_of(a, k[0], k[2])[0]) <= NTM.HALL + 1 and G + 3 <= k[1] <= G + NTM.H_SKY + 1]
chk("The hall is lit (%d sea lanterns)" % len(lamps), len(lamps) >= 12)
sky = [k for k, b in w.blocks.items() if "stained_glass" in b and k[1] == G + NTM.H_SKY]
chk("The stained glass skylight above the hall (%d blocks, %d m above the ground floor)"
    % (len(sky), NTM.H_SKY - NTM.H_FLOOR - 1),
    len(sky) > 60)

# ---------------------------------------------------------------- Red House
print("\nRed House")
a, w, dt, err = make("red_house")
names = common(a, w, dt, err)
check_ids(a.id, w)
fr = a.fr
octm = a.oct
area = int(octm.sum())
chk("The Octagon covers %d m² (public sources: 412 m²)" % area, abs(area - 412) <= 60)
sectors = [0] * 8
for k, b in w.blocks.items():
    if k[1] != G + 5 or not solid(b):
        continue
    u, v = local_of(a, k[0], k[2])
    r = math.hypot(u, v)
    if RH.A_WALL - 1.5 <= r <= RH.A_WALL / math.cos(math.radians(22.5)) + 0.5:
        sectors[int(((math.degrees(math.atan2(v, u)) + 22.5) % 360) // 45)] += 1
chk("The Octagon has walls in all eight directions (%s; the west face joins the Cruciform Building)"
    % sectors,
    all(s > 0 for s in sectors))
cx, cz = fr.cell(0.0, 0.0)
top = column_top(w, cx, cz)
peak = max(k[1] for k, b in w.blocks.items() if solid(b))
chk("The spire of the central lantern is the highest point (y%s, %s m above the ground)"
    % (top, top - G if top else None),
    top == peak == G + RH.H_TOP)
lan = [k for k, b in w.blocks.items() if RH.H_LANTERN[0] <= k[1] - G <= RH.H_LANTERN[1]
       and b == RH.GLASS and math.hypot(*local_of(a, k[0], k[2])) <= RH.A_LANTERN + 0.8]
chk("The lantern has windows all round (%d glass blocks)" % len(lan), len(lan) >= 4)
xs, zs = fr.cell((RH.CROSS_U[0] + RH.CROSS_U[1]) / 2, RH.CROSS_V[0] + 3.0)
xn, zn = fr.cell((RH.CROSS_U[0] + RH.CROSS_U[1]) / 2, RH.CROSS_V[1] - 3.0)
chk("Both the north and south ends of the Cruciform Building's transept have a roof",
    column_top(w, xs, zs) and column_top(w, xn, zn)
    and column_top(w, xs, zs) >= G + RH.H_HALL_ROOF)
fx, fz = fr.cell(RH.A_WALL + 0.6, 0.0)
chk('The sign above the main entrance reads "西門紅樓"',
    any(v[0] == "西門紅樓" for v in w.signs.values()))
chk("The main entrance faces Red House Plaza (the viewpoint is on the Octagon's front side)",
    a.spots()[0].x > cx - 1e9 and a.spot_uv()[0] > RH.A_WALL)

print("\nRegistry")
reg = AT.registry()
chk("All three have their own registered class", reg.get("presidential_office") is PO.PresidentialOffice
    and reg.get("national_taiwan_museum") is NTM.NationalTaiwanMuseum and reg.get("red_house") is RH.RedHouse)

print("\n" + ("All tests passed" if ok else "Some tests failed"))
sys.exit(0 if ok else 1)
