#!/usr/bin/env python3
"""The shared attraction framework (application/attractions/).

Each attraction's appearance is checked by its own test file (tests/test_attr_*.py); this
file checks what they all share:
  · Frame: inverse rasterization of a rectangle at any angle misses no cell, the area is
    right, and local and world coordinates convert back and forth consistently
  · Roof heightfields: eaves at 0, ridge highest, the xieshan gable pediment, the symmetry
    of the octagonal pyramidal roof, upturns only at the corners
  · Guard: nothing is written in the keep-out zone and the blocked writes are counted; a
    plaque's first line must not start with `出口`; an English fact goes on the back
  · Datapack: each sight function has exactly one tp line, the buttons' trigger values
    follow the station ones, the main menu has an attractions button
  · Registry: every attraction has a class (those without their own module fall back to
    OsmMassing), and ids are unique

Usage: ./.venv/bin/python tests/test_attractions.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.application import attractions as AT
from mrt.application.attractions import kit
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def holes(mask):
    """Number of cells in the mask that are False yet surrounded on four sides (inverse
    rasterization should leave none)."""
    m = mask
    inner = np.zeros_like(m)
    inner[1:-1, 1:-1] = (m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:]) & ~m[1:-1, 1:-1]
    return int(inner.sum())


print("Frame: rotated rectangles")
for deg in (0, 7, 30, 45, 62, 90, 133):
    fr = kit.Frame(100.3, -50.7, math.radians(deg), 40)
    m = fr.box(20, 10)
    area = int(m.sum())
    chk(f"{deg:>3}°: half-length 20, half-width 10 -> {area} cells (area 800), no holes",
        abs(area - 800) <= 40 and holes(m) == 0)
fr = kit.Frame(10, 20, math.radians(30), 30)
x, z = fr.world(5, -3)
u, v = fr.local(int(math.floor(x)), int(math.floor(z)))
chk("Local -> world -> local is within one cell", abs(u - 5) <= 1 and abs(v + 3) <= 1)
chk("The u axis follows angle: (1,0) at 30° is world (cos30, sin30)",
    all(abs(a - b) < 1e-9 for a, b in zip(fr.dir(1, 0), (math.cos(math.radians(30)), math.sin(math.radians(30))))))
fr0 = kit.Frame(0, 0, 0.0, 20)
chk("At angle=0 the v axis is +z (south)", fr0.dir(0, 1) == (0.0, 1.0) and fr0.facing(0, 1) == "south")
fo = kit.Frame(0.5, 0.5, 0.0, 20)
oct_ = fo.ngon(8, 10)
pts = set(zip(fo.U[oct_].round(3).tolist(), fo.V[oct_].round(3).tolist()))
# Cells whose centers fall exactly on an edge count too, so the cell count exceeds the area
# by about half the perimeter (Pick's theorem).
chk("Octagon with apothem 10 (area 331 m2, %d cells), symmetric left-right and top-bottom" % oct_.sum(),
    abs(int(oct_.sum()) - 331) <= 40 and pts == {(-u, -v) for u, v in pts} == {(v, u) for u, v in pts})
chk("ring is the outer ring, and none of it survives erode",
    kit.ring(fr0.box(5, 5)).sum() == 36 and not (kit.erode(fr0.box(5, 5)) & kit.ring(fr0.box(5, 5))).any())

print("\nRoof heightfields")
fr = kit.Frame(0, 0, 0.0, 30)
h = kit.hip(fr, 20, 10, 8, profile=1.5)
box = fr.box(20, 10)
chk("Hip roof: eaves 0, ridge about 8 (cell centers are half a block from the ridge)",
    abs(h[box].min()) < 0.8 and 7.0 < h[box].max() <= 8.0)
ridge = h[fr.box(8, 0.6)]
chk("The hip roof's ridge runs along u (the whole center line is highest)", ridge.min() >= h[box].max() - 1e-9)
hg = kit.hip_gable(fr, 20, 10, 8, gable_in=6)
end_mid = float(hg[fr.box(0.5, 0.5, du=13)].max())
chk("Xieshan: inside the pediment (6 m from the end), the center line reaches the ridge like the long slopes",
    end_mid >= float(h[box].max()) - 1e-9)
chk("Xieshan: the short end slope is higher than the hip roof's (the pediment stands up)", float(hg[fr.box(0.5, 0.5, du=16)].max()) > float(h[fr.box(0.5, 0.5, du=16)].max()))
pl = kit.pyramid(fr, 10, 12, sides=8, profile=1.3)
chk("Octagonal pyramidal roof: about 12 at the center, 0 at the eaves", 10.5 < float(pl.max()) <= 12 and float(pl[fr.ngon(8, 10) & ~fr.ngon(8, 9)].min()) < 1.5)
hl = kit.hip(fr, 20, 10, 8, profile=1.5, lift=2.0)
corner = fr.box(0.6, 0.6, du=19.5, dv=9.5)
side_mid = fr.box(0.6, 0.6, du=0, dv=9.5)
chk("Upturn: the eaves at a corner are nearly 2 m higher than at mid-eave",
    float(hl[corner].max() - h[corner].max()) > 1.2 and float(hl[side_mid].max() - h[side_mid].max()) < 0.2)

print("\nGuard and Painter")
w = DictSink()
g = kit.Guard(w, keep=lambda x, y, z: x == 0)
p = kit.Painter(g, kit.Frame(0.5, 0.5, 0.0, 3))
p.fill(p.fr.box(2, 2), 64, 65, "minecraft:stone")
chk("The keep-out row is not written and everything else is", all(k[0] != 0 for k in w.blocks) and len(w.blocks) > 0 and g.dropped > 0)
w = DictSink()
p = kit.Painter(w, kit.Frame(0, 0, 0.0, 10))
p.heightfield(p.fr.box(3, 3), 70, np.full(p.fr.shape, 2.6), "minecraft:bricks", slab="minecraft:brick_slab")
chk("heightfield: a slab goes on top where the fraction is >= 0.5",
    any(v.startswith("minecraft:brick_slab") for v in w.blocks.values()))


class Fake(kit.Attraction):
    def plaque(self):
        return ["出口 1", "Exit", "", ""]


class WithEnglish(kit.Attraction):
    def plaque(self):
        return [self.name_zh, self.name_en, "1884 年", "清代原貌"]

    def plaque_en(self):
        return ["Built in 1884, in its original Qing form", "Built 1884"]


print("\nPlaques and the datapack")
try:
    AT.plaque_lines(Fake(dict(id="x", name_zh="出口", name_en="x")))
    chk("A plaque whose first line starts with 出口 is rejected", False)
except ValueError:
    chk("A plaque whose first line starts with 出口 is rejected", True)
a = kit.Attraction(dict(id="cks_memorial", name_zh="中正紀念堂", name_en="Chiang Kai-shek Memorial Hall"))
a.station = ("中正紀念堂", "R08;G10", 350.0, "Chiang Kai-shek Memorial Hall")
front, back = AT.plaque_lines(a)
from mrt.application import signage as SG
chk("Plaque: a long English name breaks over two lines, each of which fits (%s)" % [kit_t if isinstance(kit_t, str) else kit_t["text"] for kit_t in front],
    all(SG.line_width(t) <= SG.SIGN_W for t in front) and len(front) == 4)
chk("The plaque's fourth line is the MRT station within walking distance", "中正紀念堂站" in str(front[3]))
chk("Without an English fact, the back starts with the attraction name",
    isinstance(back[0], dict) and back[0]["text"] == "中正紀念堂" and back[3] == "資料 © OpenStreetMap")
_, back_en = AT.plaque_lines(WithEnglish(dict(id="x", name_zh="北門", name_en="North Gate")))
chk("With an English fact, the back holds the Chinese facts, the English line that fits and the source (%s)"
    % back_en, back_en == ["1884 年", "清代原貌", "Built 1884", "資料 © OpenStreetMap"])
chk("sight function paths", kit.sight_fn("taipei101") == "sight/taipei101"
    and kit.sight_fn("taipei101", "top") == "sight/taipei101_top")

from mrt.application import ride_plan as RP
from mrt.domain import network as NW
entries = [dict(id="beimen", name_zh="北門", name_en="North Gate", station=("北門", "G13", 200, "Beimen"),
                facts=["1884 年"], spots=[kit.Spot("", 1, 66, 2, 0.0, -10.0, "北門", "North Gate")._asdict()]),
           dict(id="taipei101", name_zh="台北101", name_en="Taipei 101", station=None, facts=["508 m"],
                spots=[kit.Spot("", 10, 70, 20, 90.0, -30.0, "台北101", "Taipei 101")._asdict(),
                       kit.Spot("top", 12, 452, 22, 0.0, 10.0, "89 樓觀景台", "89F Observatory")._asdict()])]
spec = RP.build_spec({}, [], {}, sights=entries)
fns = spec["functions"]
tp_lines = {k: [ln for ln in v if ln.startswith("tp ")] for k, v in fns.items() if k.startswith("sight/")}
chk("One sight function per teleport point, each with exactly one tp line (%s)" % sorted(tp_lines),
    sorted(tp_lines) == ["sight/beimen", "sight/taipei101", "sight/taipei101_top"]
    and all(len(v) == 1 for v in tp_lines.values()))
chk("The tp line targets the block center: tp @s 1.5 66 2.5 0.0 -10.0", tp_lines["sight/beimen"] == ["tp @s 1.5 66 2.5 0.0 -10.0"])
chk("Attraction button trigger values are 1..2 (starting at 1 with no stations) and point to the default viewpoints",
    spec["triggers"] == {1: "sight/beimen", 2: "sight/taipei101"})
menu = spec["dialogs"][NW.MENU_DIALOG]
chk("The main menu has an attractions button that opens mrt:sights",
    any(a_.get("action", {}).get("dialog") == "mrt:sights" for a_ in menu["actions"]) and "sights" in spec["dialogs"])
chk("The attraction list buttons are trigger mrt.go set n",
    [a_["action"]["command"] for a_ in spec["dialogs"]["sights"]["actions"]] == ["trigger mrt.go set 1", "trigger mrt.go set 2"])
chk("sys/go_dispatch dispatches to the attractions", any("sight/taipei101" in ln for ln in fns["sys/go_dispatch"]))

e = entries[0]
sl = SG.sight_lines(e)
chk("Concourse attraction sign: starts with ★, every line fits, does not start with 出口 (%s)" % [t if isinstance(t, str) else t["text"] for t in sl],
    all(SG.line_width(t) <= SG.SIGN_W for t in sl) and sl[0]["text"].startswith("★")
    and not str(sl[0]["text"]).startswith("出口"))
chk("Clicking the concourse attraction sign runs function mrt:sight/beimen", SG.sight_command(e) == "function mrt:sight/beimen")
dlg = RP.build_spec({}, [], {}, sights=entries)["dialogs"]
chk("With no stations the station dialogs are unaffected (only the main menu and the attraction list)", sorted(dlg) == ["network", "sights"])

print("\nRegistry")
reg = AT.registry()
items = AT.load_items()
chk("data/attractions.json has 15 attractions", len(items) == 15)
chk("Every id uses only characters valid in a datapack path", all(all(c.isalnum() and c.islower() or c.isdigit() or c == "_" for c in it["id"]) for it in items))
objs = AT.for_world([], items=items)
chk("Every attraction has a class to build it (%d with their own, the rest fall back to OsmMassing)" % sum(1 for o in objs if type(o) is not AT.OsmMassing),
    len(objs) == len(items))
chk("Every bbox is reasonable (sides 10–1200 m)",
    all(10 <= o.bbox()[2] - o.bbox()[0] <= 1200 and 10 <= o.bbox()[3] - o.bbox()[1] <= 1200 for o in objs))

print("\n" + ("All tests passed" if ok else "Some tests failed"))
sys.exit(0 if ok else 1)
