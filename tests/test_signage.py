#!/usr/bin/env python3
"""Station signs and line colors (application/signage.py).

Builds a synthetic network, really builds its station boxes and signs
(DictSink), and checks:
  · ride signs: one per berth, in the platform screen door row (door glass above,
    support below), with a standable berth two blocks in front; the click command
    matches network's ride/turn function; the next station on the sign is the
    command's destination; every line fits in 90 px; glow ink and pale wood
  · the arrival side of a terminus says `本站終點` and a click changes platform
  · a Chinese ride sign without an English twin carries the English itself
  · the arrow for the departing train: right to left (←) on an island platform,
    left to right (→) on a side platform
  · line color bands: platform screen door lintels and outer track walls; both
    levels of a stacked station, and each side of a shared station box follows
    its own line
  · concourse: the double-sided signs on gate cabinets (front: to the platforms;
    back: to the exits), the route map ticket machine (opens the route map
    dialog), the direction signs at the two platform stairs of a side-platform
    station, and the signs at the stairs between the levels of a stacked station
  · with all of that in place, every platform's warning strip and every berth can
    still be reached on foot from the unpaid area
  · exit signs: line color and glow on the first line, with the plain text
    exactly as before (verify_exits relies on it)
  · no other sign has a first line starting with `出口`
  · every sign with Chinese also has English, apart from Chinese ride signs that
    have an English twin
  · the same on a 45-degree alignment

Usage: ./.venv/bin/python tests/test_signage.py
"""
import copy
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt import config
from mrt.application import build_exits as BX
from mrt.application import build_line as BL
from mrt.application import signage as SG
from mrt.domain import alignment as AL
from mrt.domain import network as NW
from mrt.domain import stacked as SK
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


G = 66
COLOURS = {"T": "#007EC7", "S": "#FFD900", "BL": "#007EC7", "G": "#1E7B54", "D": "#FF0000"}
NS = config.DATAPACK_NS
CJK = re.compile(r"[\u3400-\u9fff]")
LATIN = re.compile(r"[a-z]")          # Lower case only: station codes such as T02 are not English.


def make_seg(ref, pts, stations, y):
    """stations = [(x or (x, z), code, name, English name)]; each station lands on the nearest sample."""
    samples = AL.resample(pts, ["tunnel"] * len(pts), AL.STEP)
    n = len(samples)
    stn = {}
    for pos, code, name, en in stations:
        px, pz = pos if isinstance(pos, tuple) else (pos, samples[0][1])
        i = min(range(n), key=lambda k: (samples[k][0] - px) ** 2 + (samples[k][1] - pz) ** 2)
        stn[i] = (code, name, en)
    return dict(ref=ref, samples=samples, ys=np.full(n, y), ground=np.full(n, G),
                stn=stn, stn_seq=dict(stn))


def build(segs, net, berths):
    """In the CLI's order: build_station for each station box, then station_signage."""
    w = DictSink()
    of = {}
    for b in berths:
        of.setdefault(b.box.key, []).append(b)
    for li, sg in enumerate(segs):
        for i, (full, name, en) in sg["stn"].items():
            under = AL.structure_for_ground(int(sg["ys"][i]), int(sg["ground"][i])) == "tunnel"
            BL.build_station(w, SK.station_samples(sg, i), sg["ys"], i, under,
                             label=(full, name, en), grounds=sg["ground"], access=False,
                             stacked=sg.get("stacked", {}).get(i))
            SG.station_signage(w, of.get((li, i), ()), net, COLOURS, grounds=sg["ground"])
    return w


def plain(line):
    return line["text"] if isinstance(line, dict) else str(line)


def ride_signs_ok(w, berths, net, tag):
    """One ride sign per berth, with the right position, command, text and style."""
    n = bad = 0
    for b in berths:
        for s in b.slots:
            n += 1
            meta = w.sign_meta.get(s.sign)
            text = w.signs.get(s.sign)
            why = []
            if meta is None:
                why.append("no sign")
            else:
                sx, sy, sz = s.sign
                if "pane" not in w.get(sx, sy + 1, sz):
                    why.append(f"no door glass above ({w.get(sx, sy + 1, sz)})")
                if not walk.is_support(w.get(sx, sy - 1, sz)):
                    why.append("no support below")
                if not walk.standable(w.get, *s.stand):
                    why.append("berth not standable")
                if not (meta["glow"] and meta["wood"] == SG.SIGN_WOOD):
                    why.append("not glow ink on pale wood")
                if s.dest is not None:
                    to = net[(b.line, s.dest.next)]
                    want = f"function {NS}:{NW.ride_fn(b.station.code, to.code)}"
                    if meta["command"] != want:
                        why.append(f"command {meta['command']} != {want}")
                    if s.lang == "zh" and not any(t.endswith(s.dest.next) and "下一站" in t
                                                  for t in text):
                        why.append(f"Chinese sign does not give the next station {s.dest.next}: {text}")
                    if s.lang == "en" and not any(to.en.split(" ")[0] in t for t in text[1:3]):
                        why.append(f"English sign does not give the next station {to.en}: {text}")
                    if not isinstance(meta["lines"][0], dict) or "color" not in meta["lines"][0]:
                        why.append("direction line has no line colour")
                else:
                    want = f"function {NS}:{NW.turn_fn(b.station.code, b.d)}"
                    if meta["command"] != want:
                        why.append(f"terminus command {meta['command']} != {want}")
                    if not ("本站終點" in text[0] or "Terminus" in text[0]):
                        why.append(f"terminus side does not say so: {text}")
                wide = [SG.line_width(t) for t in meta["lines"]]
                if max(wide) > SG.SIGN_W:
                    why.append(f"a line is {max(wide)} px, over {SG.SIGN_W}: {text}")
            if why:
                bad += 1
                print(f"      {b} {s}: {'; '.join(why)}")
    chk(f"{tag}: each of the {n} berths has a ride sign (position, command, text, style)", n > 0 and bad == 0)


def no_exit_first_line(w, tag):
    bad = [t for t in w.signs.values() if t and t[0].startswith("出口")]
    chk(f"{tag}: no sign has a first line starting with 出口", not bad)


def all_fit(w, tag):
    bad = []
    for k, meta in w.sign_meta.items():
        for side in ("lines", "back"):
            for t in (meta.get(side) or ()):
                if SG.line_width(t) > SG.SIGN_W:
                    bad.append((k, t))
    chk(f"{tag}: every line of the {len(w.sign_meta)} signs (backs included) fits in {SG.SIGN_W} px", not bad)
    for b in bad[:4]:
        print("     ", b)


def bilingual(w, berths, tag):
    """Every sign side with Chinese also has English, apart from the Chinese ride
    signs that have an English sign for the same destination on their berth."""
    def dest(s):
        return s.dest.next if s.dest is not None else None
    twinned = {s.sign for b in berths for s in b.slots
               if s.lang == "zh" and any(o.lang == "en" and dest(o) == dest(s) for o in b.slots)}
    bad = []
    for k, meta in w.sign_meta.items():
        for side in ("lines", "back"):
            texts = [plain(t) for t in (meta.get(side) or ())]
            if side == "lines" and k in twinned:
                continue
            if any(CJK.search(t) for t in texts) and not any(LATIN.search(t) for t in texts):
                bad.append(texts)
    chk(f"{tag}: every sign with Chinese also has English ({len(bad)} without)", not bad)
    for t in bad[:4]:
        print("     ", t)


def yellow_reached(w, dist):
    return {(x, y + 1, z) for (x, y, z), blk in w.blocks.items()
            if blk == BL.YELLOW and (x, y + 1, z) in dist}


def signs_with(w, pred):
    return [(k, w.signs[k], m) for k, m in w.sign_meta.items() if pred(w.signs[k], m)]


# ================================================================ Straight underground line
print("Straight underground line: 甲—乙—丙, island platforms")
line = make_seg("T", [(0, 0), (3000, 0)],
                [(500, "T01", "甲", "Jia"), (1500, "T02", "乙", "Yi"),
                 (2500, "T03", "丙", "Bing")], 40)
segs = [line]
net, berths = NW.plan_berths(segs)
w = build(segs, net, berths)
ride_signs_ok(w, berths, net, "Island station")
bidx = NW.berth_index(berths)
b = bidx[("T", "乙", 1)]
s0 = b.slots[0]
t = w.signs[s0.sign]
chk(f"Chinese sign from 乙 to 丙: {t}", t[0] == "← 往 丙" and t[1] == "下一站 丙" and t[2] == "T02 乙"
    and "搭車" in t[3])
chk("Island platform: trains run from right to left (arrow ←)", SG.travel_arrow(b) == "←")
t = w.signs[b.slots[1].sign]
chk(f"English sign from 乙 to 丙: {t}", t[0] == "← To Bing" and t[1] == "Next: Bing" and t[2] == "T02 Yi")
end = bidx[("T", "丙", 1)]
t = w.signs[end.slots[0].sign]
chk(f"Arrival side at 丙: terminus, use the opposite side, trains for 甲 ({t})",
    t[0] == "本站終點" and t[1] == "請至對面月台" and t[2] == "搭往 甲")
chk("A click on the arrival side at 丙 moves to the opposite platform (turn/t03_p)",
    w.sign_meta[end.slots[0].sign]["command"] == f"function {NS}:turn/t03_p")
# A Chinese sign whose berth has no English sign for its destination (the branch
# direction at Qizhang, Daqiaotou, Beitou and Binhai Shalun) carries the English.
lone = copy.copy(b)
lone.slots = [b.slots[0]]
lines, cmd = SG.ride_lines(lone, lone.slots[0], net, COLOURS["T"])
t = [plain(x) for x in lines]
chk(f"A Chinese sign without an English twin gives the next station in English ({t})",
    t == ["← 往 丙", "下一站 丙", "Next: Bing", SG.RIDE_HINT_ZH]
    and cmd == f"function {NS}:{NW.ride_fn('T02', 'T03')}"
    and all(SG.line_width(x) <= SG.SIGN_W for x in lines))
lone = copy.copy(end)
lone.slots = [end.slots[0]]
lines, cmd = SG.ride_lines(lone, lone.slots[0], net, COLOURS["T"], bidx[("T", "丙", -1)])
t = [plain(x) for x in lines]
chk(f"A Chinese terminus sign without an English twin says it in both languages ({t})",
    t[0] == "本站終點 Terminus" and t[1] == "請至對面月台" and t[2] == "Use other side"
    and cmd == f"function {NS}:turn/t03_p" and all(SG.line_width(x) <= SG.SIGN_W for x in lines))
# Lintel and outer wall bands
box = b.box
blk = SG.band_block("T", COLOURS)
chk(f"Bannan Line colour #007EC7 -> {blk}", blk == "minecraft:light_blue_concrete")
mid = (box.lo + box.hi) // 2
hx, hz = box.cell(mid, AL.PLAT_HALF)
chk("The top row of the platform screen doors is a line-coloured lintel", w.get(hx, 40 + 5, hz) == blk)
chk("Under the lintel is still platform screen door (glass or opening)", w.get(hx, 40 + 4, hz) in (BL.PSD, BL.AIR))
wx, wz = box.cell(mid, AL.BOX_HALF - 1)
chk("The outer track wall has two rows of line colour at eye level", w.get(wx, 43, wz) == blk and w.get(wx, 44, wz) == blk)
wx, wz = box.cell(mid, -(AL.BOX_HALF - 1))
chk("So does the wall on the other side", w.get(wx, 43, wz) == blk and w.get(wx, 44, wz) == blk)
ix, iz = box.cell(mid, AL.BOX_HALF - 2)
chk("The bands do not stick into the station (the cell at ±10 is still empty)", w.get(ix, 43, iz) == BL.AIR)
# Concourse
ym = 40 + AL.LEVEL_DY["tunnel"]
gates = signs_with(w, lambda t, m: t[0].startswith("往月台") and abs(m.get("facing", (0, 0))[0] + 1) < 1e-6
                   and m.get("back"))
per_st = {}
for k, t, m in gates:
    per_st.setdefault(round(k[0] / 1000), []).append((k, t, m))
chk(f"Two double-sided signs on the fare gates of every station ({ {k: len(v) for k, v in per_st.items()} })",
    len(per_st) == 3 and all(len(v) == 2 for v in per_st.values()))
k, t, m = next(g for g in gates if 1400 < g[0][0] < 1600)
chk(f"The gate sign stands on a cabinet at eye level ({k}, below it {w.get(k[0], k[1] - 1, k[2])})",
    k[1] == ym + 1 and w.get(k[0], k[1] - 1, k[2]) == BL.GATE)
chk(f"Gate sign front: to the platforms, the line, both directions ({t})",
    "往月台" in t[0] and "T" in t[1] and "甲" in t[2] and "丙" in t[2])
chk(f"Gate sign back faces the paid area: to the exits ({m['back']})", m["back"][0].startswith("往出口") and m["back"][1] == "乙")
chk("Gate sign front faces the unpaid area (toward −u)", m["facing"][0] < -0.99)
maps = signs_with(w, lambda t, m: m.get("dialog"))
chk(f"One route map ticket machine per station ({len(maps)})", len(maps) == 3)
k, t, m = next(g for g in maps if 1400 < g[0][0] < 1600)
chk(f"A click opens the route map dialog ({m['dialog']})", m["dialog"] == f"{NS}:{NW.MENU_DIALOG}")
chk("The ticket machine is in the unpaid area (lo+10 m, before the fare gates)",
    box.samples[box.lo][0] < k[0] < box.samples[box.lo + 14 * 2][0])
chk("The ticket machine's sign stands on a machine", w.get(k[0], k[1] - 1, k[2]) == BL.GATE)
# Reachable on foot
start = (int(round(box.samples[box.lo + 4][0])), ym, int(round(box.samples[box.lo + 4][1])))
chk("The unpaid area is standable", walk.standable(w.get, *start))
dist, _ = walk.flood(w.get, [start])
yel = yellow_reached(w, dist)
n_yel = sum(1 for (x, y, z), bb in w.blocks.items() if bb == BL.YELLOW
            and box.samples[box.lo][0] <= x <= box.samples[box.hi][0])
chk(f"The whole platform warning strip is reachable from the unpaid area ({len([c for c in yel if 1400 < c[0] < 1600])}/{n_yel})",
    len([c for c in yel if 1400 < c[0] < 1600]) == n_yel)
chk("Every berth is reachable", all(s.stand in dist for bb in berths if bb.station.name == "乙"
                                    for s in bb.slots))
no_exit_first_line(w, "Island station")
all_fit(w, "Island station")
bilingual(w, berths, "Island station")
# On a curve, a door-opening sample can round to the sign's cell (the Tamsui-Xinyi
# Line at Taipei Main Station): pretend that column is a door opening, and after
# the sign is placed the two cells above it must be glass again.
b = bidx[("T", "乙", -1)]
sx, sy, sz = b.slots[0].sign
for yy in range(sy, sy + 4):
    w.set(sx, yy, sz, BL.AIR)
SG.ride_signs(w, [b], net, COLOURS)
chk("If the sign's column was a door opening, placing the sign restores the glass (island: two cells above)",
    w.get(sx, sy + 1, sz) == BL.PSD and w.get(sx, sy + 2, sz) == BL.PSD and "sign" in w.get(sx, sy, sz))

# ================================================================ Elevated side platforms
print("\nElevated side-platform station: rail top 20 m above the ground (concourse under the viaduct)")
sky = make_seg("S", [(0, 0), (3000, 0)],
               [(500, "S01", "戊", "Wu"), (1500, "S02", "己", "Ji"),
                (2500, "S03", "庚", "Geng")], G + 20)
net, berths = NW.plan_berths([sky])
w = build([sky], net, berths)
ride_signs_ok(w, berths, net, "Side-platform station")
b = NW.berth_index(berths)[("S", "己", 1)]
chk("Side platform: trains run from left to right (arrow →)", SG.travel_arrow(b) == "→")
t = w.signs[b.slots[0].sign]
chk(f"Chinese sign at a side-platform station: {t}", t[0] == "往 庚 →" and t[1] == "下一站 庚")
box = b.box
blk = SG.band_block("S", COLOURS)
chk(f"The band for the Circular Line yellow #FFD900 is not yellow concrete ({blk})", blk != BL.YELLOW and "yellow" in blk)
mid = (box.lo + box.hi) // 2
hx, hz = box.cell(mid, AL.PLAT_HALF - 1)
chk("Platform screen door lintel at a side-platform station (+4)", w.get(hx, G + 20 + 4, hz) == blk)
kind = SG.concourse_kind(box, sky["ground"])
ym = G + 20 + AL.LEVEL_DY[kind]
stair_signs = [(k, t, m) for k, t, m in signs_with(w, lambda t, m: True)
               if 1400 < k[0] < 1600 and k[1] == ym and not m.get("dialog")]
chk(f"One direction sign at each of the two platform stairs in the concourse ({[t[0] for k, t, m in stair_signs]})",
    len(stair_signs) == 2 and {("庚" in t[0]) for k, t, m in stair_signs} == {True, False})
for k, t, m in stair_signs:
    side = 1 if k[2] > 0 else -1
    want = "庚" if side > 0 else "戊"
    chk(f"  The {'+' if side > 0 else '−'} side stairs point to {want} ({t})", want in t[0] and "下一站" in t[2])
start = (int(round(box.samples[box.lo + 4][0])), ym, int(round(box.samples[box.lo + 4][1])))
chk("The unpaid area of the under-viaduct concourse is standable", walk.standable(w.get, *start))
dist, _ = walk.flood(w.get, [start])
yel = [c for c in yellow_reached(w, dist) if 1400 < c[0] < 1600]
chk(f"Both side platforms are reachable from the unpaid area ({len({c[2] > 0 for c in yel})})",
    {c[2] > 0 for c in yel} == {True, False})
chk("Every berth is reachable", all(s.stand in dist for bb in berths if bb.station.name == "己"
                                    for s in bb.slots))
no_exit_first_line(w, "Side-platform station")
all_fit(w, "Side-platform station")
bilingual(w, berths, "Side-platform station")
b = NW.berth_index(berths)[("S", "己", -1)]
sx, sy, sz = b.slots[0].sign
for yy in range(sy, sy + 3):
    w.set(sx, yy, sz, BL.AIR)
SG.ride_signs(w, [b], net, COLOURS)
chk("Side-platform station: a door-opening column gets its glass back (the cell above the sign)", w.get(sx, sy + 1, sz) == BL.PSD)
# The cell below the sign: glass only if it really is a door opening; platform
# surface (rounded together on an oblique line) is left alone.
box = b.box
slot_cells = {(s.sign[0], s.sign[2]) for bb in berths for s in bb.slots}
yb = G + 20 + 1
row = {box.cell(i, sd * (AL.PLAT_HALF - 1)) for i in range(box.lo + 1, box.hi)
       for sd in (1, -1)} - slot_cells
agree = [(w.get(c[0], yb, c[1]) == BL.AIR) == SG._side_below_is_door(box, c) for c in row]
n_door = sum(1 for c in row if w.get(c[0], yb, c[1]) == BL.AIR)
plat_cells = [box.cell(i, -(AL.PLAT_HALF + 1)) for i in range(box.lo + 2, box.hi - 2)]
chk(f"Side-platform station: the replay agrees with the build on which cells of the door row (+1) are openings"
    f" ({len(row)} cells, {n_door} openings), and platform cells are not openings",
    all(agree) and n_door > 0 and not any(SG._side_below_is_door(box, c) for c in plat_cells))

# ================================================================ Shared stacked station
print("\nShared island stacked station (like Ximen): Bannan Line at z=0, Songshan-Xindian Line at z=17")
# The two lines are only 17 m apart, and the neighboring stations are staggered by
# 200 m so two ordinary station boxes do not overlap (an artifact of the
# synthetic network).
bl = make_seg("BL", [(0, 0), (3000, 0)],
              [(500, "BL10", "龍山寺", "Longshan Temple"), (1500, "BL11", "西門", "Ximen"),
               (2500, "BL12", "台北車站", "Taipei Main Station")], 48)
gl = make_seg("G", [(0, 17), (3000, 17)],
              [((300, 17), "G11", "小南門", "Xiaonanmen"), ((1500, 17), "G12", "西門", "Ximen"),
               ((2700, 17), "G13", "北門", "Beimen")], 48)
bi = next(i for i, v in bl["stn"].items() if v[1] == "西門")
pbi = next(i for i, v in gl["stn"].items() if v[1] == "西門")
j_to = next(i for i, v in bl["stn"].items() if v[1] == "台北車站")
pj_to = next(i for i, v in gl["stn"].items() if v[1] == "北門")
SK.plan_shared(bl, bi, SK.direction_sign(bi, j_to), gl, pbi, SK.direction_sign(pbi, pj_to))
net, berths = NW.plan_berths([bl, gl])
w = build([bl, gl], net, berths)
ride_signs_ok(w, berths, net, "Stacked station, both levels")
bidx = NW.berth_index(berths)
box = bidx[("BL", "西門", 1)].box
mid = (box.lo + box.hi) // 2
c_bl, c_g = SG.band_block("BL", COLOURS), SG.band_block("G", COLOURS)
chk(f"The two lines have different bands ({c_bl} / {c_g})", c_bl != c_g)
ok_levels = True
for dy0 in (0, -SK.LEVEL_H):
    y = 48 + dy0
    for sd, want in ((-box.side, c_bl), (box.side, c_g)):
        hx, hz = box.cell(mid, sd * AL.PLAT_HALF)
        wx, wz = box.cell(mid, sd * (AL.BOX_HALF - 1))
        if not (w.get(hx, y + 5, hz) == want and w.get(wx, y + 3, wz) == want):
            ok_levels = False
            print(f"      dy0={dy0} side {sd}: lintel {w.get(hx, y + 5, hz)}, outer wall {w.get(wx, y + 3, wz)}")
chk("On both levels the Bannan Line side is in Bannan Line colour and the Songshan-Xindian Line side in its colour", ok_levels)
ym = 48 + AL.LEVEL_DY["tunnel"]
gates = [(k, t, m) for k, t, m in signs_with(w, lambda t, m: t[0].startswith("往月台"))
         if 1400 < k[0] < 1600]
chk(f"One sign per line on the fare gates ({[t[1] for k, t, m in gates]})",
    len(gates) == 2 and {t[1] for k, t, m in gates} == {"板南線 BL", "松山新店線 G"})
for k, t, m in gates:
    x, z = k[0], k[2]
    _, off = (x - box.samples[mid][0]), z - box.samples[mid][1]
    want = -box.side if "BL" in t[1] else box.side
    chk(f"  The {t[1]} gate sign is on its own platform's side (offset {off:+.0f})", off * want > 0)
    chk(f"  {t[1]}: {t[2]}", ("頂埔" in t[2] or "龍山寺" in t[2] or "新店" in t[2] or "小南門" in t[2]))
lv = [(k, t) for k, t, m in signs_with(w, lambda t, m: "層月台" in t[0]) if 1400 < k[0] < 1600]
chk(f"Two signs at the stairs between levels: upper to lower and lower to upper ({[t[0] for k, t in lv]})",
    sorted(k[1] for k, t in lv) == [48 + 2 - SK.LEVEL_H, 48 + 2]
    and any("下層" in t[0] and k[1] == 50 for k, t in lv)
    and any("上層" in t[0] and k[1] == 50 - SK.LEVEL_H for k, t in lv))
k_up = next(k for k, t in lv if k[1] == 50)
t_up = next(t for k, t in lv if k[1] == 50)
chk(f"The upper sign lists the lower level's directions ({t_up[2:]})",
    any("龍山寺" in x or "頂埔" in x for x in t_up) and any("小南門" in x or "新店" in x for x in t_up))
chk(f"Where it fits, a row of the level signs gives its terminals in English too ({[t[2:] for k, t in lv]})",
    any(CJK.search(x) and LATIN.search(x) for k, t in lv for x in t[2:]))
chk(f"The sign up from the lower level names the exits in English ({[t[1] for k, t in lv]})",
    any("上層" in t[0] and "Exit" in t[1] for k, t in lv))
chk("The upper sign stands on platform (not over the stair opening)", walk.is_support(w.get(k_up[0], 49, k_up[2])))
start = (int(round(box.samples[box.lo + 4][0])), ym, int(round(box.samples[box.lo + 4][1])))
chk("The unpaid area of the stacked station's concourse is standable", walk.standable(w.get, *start))
dist, _ = walk.flood(w.get, [start])
lvls = sorted({c[1] for c in yellow_reached(w, dist) if 1400 < c[0] < 1600})
chk(f"With the signs in place, both platform levels are still reachable from the unpaid area ({lvls})",
    lvls == [50 - SK.LEVEL_H, 50])
chk("Every berth is reachable", all(s.stand in dist for bb in berths if bb.station.name == "西門"
                                    for s in bb.slots))
no_exit_first_line(w, "Stacked station")
all_fit(w, "Stacked station")
bilingual(w, berths, "Stacked station")

# ================================================================ Side stacked station
print("\nSide stacked station (like Fuzhong)")
fz = make_seg("D", [(0, 0), (3000, 0)],
              [(500, "D01", "子", "Zi"), (1500, "D02", "丑", "Chou"),
               (2500, "D03", "寅", "Yin")], 48)
bi = next(i for i, v in fz["stn"].items() if v[1] == "丑")
SK.plan_side(fz, bi, +1, "left")
net, berths = NW.plan_berths([fz])
w = build([fz], net, berths)
ride_signs_ok(w, berths, net, "Side stacked station")
box = NW.berth_index(berths)[("D", "丑", 1)].box
dist, _ = walk.flood(w.get, [(int(round(box.samples[box.lo + 4][0])), ym,
                              int(round(box.samples[box.lo + 4][1])))])
lvls = sorted({c[1] for c in yellow_reached(w, dist) if 1400 < c[0] < 1600})
chk(f"Both platform levels are reachable from the unpaid area ({lvls})", lvls == [50 - SK.LEVEL_H, 50])
lv = [(k, t) for k, t, m in signs_with(w, lambda t, m: "層月台" in t[0]) if 1400 < k[0] < 1600]
chk(f"Two signs at the stairs between levels ({[t for k, t in lv]})", len(lv) == 2)
mid = (box.lo + box.hi) // 2
wx, wz = box.cell(mid, -box.side * (AL.BOX_HALF - 1))
px, pz = box.cell(mid, box.side * (AL.BOX_HALF - 1))
blk = SG.band_block("D", COLOURS)
chk(f"The band is on the track-side wall ({blk}), not on the wall behind the platform",
    w.get(wx, 51, wz) == blk and w.get(wx, 51 - SK.LEVEL_H, wz) == blk and w.get(px, 51, pz) != blk)
all_fit(w, "Side stacked station")
bilingual(w, berths, "Side stacked station")

# ================================================================ 45 degrees
print("\nUnderground line at 45 degrees")
k = 1 / math.sqrt(2)
diag = make_seg("T", [(0, 0), (3000 * k, 3000 * k)],
                [((500 * k, 500 * k), "T01", "甲", "Jia"), ((1500 * k, 1500 * k), "T02", "乙", "Yi"),
                 ((2500 * k, 2500 * k), "T03", "丙", "Bing")], 40)
net, berths = NW.plan_berths([diag])
w = build([diag], net, berths)
ride_signs_ok(w, berths, net, "Oblique island station")
box = NW.berth_index(berths)[("T", "乙", 1)].box
inner = {box.cell(i, o) for i in range(box.lo, box.hi + 1) for o in range(-10, 11)}
blk = SG.band_block("T", COLOURS)
leak = [(x, z) for (x, y, z), bb in w.blocks.items() if bb == blk and y in (43, 44) and (x, z) in inner]
chk(f"On the oblique line the bands do not stick into the station either ({len(leak)} cells)", not leak)
ym = 40 + AL.LEVEL_DY["tunnel"]
start = walk.nearest_standable(w.get, *[int(round(v)) for v in box.samples[box.lo + 6][:2]][:1],
                               ym, int(round(box.samples[box.lo + 6][1])), radius=3, dy=1)
dist, _ = walk.flood(w.get, [start])
chk("On the oblique line every berth is reachable from the unpaid area", all(s.stand in dist for bb in berths
                                                                            if bb.station.name == "乙" for s in bb.slots))
gates = [kk for kk, t, m in signs_with(w, lambda t, m: t[0].startswith("往月台"))
         if box.samples[box.lo][0] < kk[0] < box.samples[box.hi][0]]
chk(f"On the oblique line the gate signs also stand on cabinets ({len(gates)})",
    len(gates) == 2 and all(w.get(x, y - 1, z) == BL.GATE for x, y, z in gates))
all_fit(w, "Oblique line")
bilingual(w, berths, "Oblique line")
for ang in (30, 45, 60):
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    dsky = make_seg("S", [(0, 0), (3000 * ca, 3000 * sa)],
                    [((500 * ca, 500 * sa), "S01", "戊", "Wu"), ((1500 * ca, 1500 * sa), "S02", "己", "Ji"),
                     ((2500 * ca, 2500 * sa), "S03", "庚", "Geng")], G + 20)
    net, berths = NW.plan_berths([dsky])
    w0 = DictSink()
    for i, (full, name, en) in dsky["stn"].items():
        BL.build_station(w0, SK.station_samples(dsky, i), dsky["ys"], i, False,
                         label=(full, name, en), grounds=dsky["ground"], access=False)
    w = build([dsky], net, berths)
    y0 = {k for k, v in w0.blocks.items() if v == BL.YELLOW}
    y1 = {k for k, v in w.blocks.items() if v == BL.YELLOW}
    ride_signs_ok(w, berths, net, f"Side-platform station at {ang} degrees")
    chk(f"Side-platform station at {ang} degrees: the signs dig out no warning strip cell ({len(y0)} -> {len(y1)})", y0 == y1)

# ================================================================ Exit signs
print("\nExit signs")
lines = BX.sign_lines(["2"], "乙", "Yi")
styled = SG.exit_sign_lines(lines, "#FFD900")
chk(f"The first line takes the line colour (darkened) and keeps its plain text ({styled[0]})",
    isinstance(styled[0], dict) and styled[0]["text"] == lines[0] == "出口 2"
    and styled[0]["color"] != "#FFD900" and styled[1:] == lines[1:])
well = BX.make_well(dict(x0=100, z0=100, ux=1, uz=0, g0=G, y_to=G - 12), styled, SG.SIGN_STYLE)
w = DictSink()
well.build(w)
(k, t), = list(w.signs.items())
m = w.sign_meta[k]
chk(f"The exit shaft's sign: {t}", t == ["出口 2", "乙", "Yi", "Exit 2"] and m["glow"]
    and m["wood"] == SG.SIGN_WOOD and m["lines"][0]["color"] == styled[0]["color"])
gate = BX.make_gate(dict(x0=0, z0=0, ux=1, uz=0, g0=G, y_to=G + 1), styled, SG.SIGN_STYLE)
w = DictSink()
gate.build(w)
(k, t), = list(w.signs.items())
chk(f"So is the at-grade exit's sign ({t})", t[0] == "出口 2" and w.sign_meta[k]["glow"])
t = SG.transfer_sign_lines(BX.transfer_lines("BL", "中山", "Zhongshan"), "#007EC7")
chk(f"The transfer sign keeps 往 BL 線 on line 2 and gives the line in English under it ({[plain(x) for x in t]})",
    plain(t[0]).startswith("轉乘") and plain(t[1]) == "往 BL 線" and plain(t[2]) == "To Bannan Line"
    and all(SG.line_width(x) <= SG.SIGN_W for x in t))

# ================================================================ Text colours and text
print("\nText colours and text")
cols = NW.line_colours(json.load(open(config.MC_LINES_JSON, encoding="utf-8")))
low = {ref: round(SG.contrast(SG._rgb(SG.ink(c))), 2) for ref, c in cols.items()
       if SG.contrast(SG._rgb(SG.ink(c))) < SG.MIN_CONTRAST}
chk(f"Every line's text colour has a contrast of at least {SG.MIN_CONTRAST} on the pale board", not low)
chk(f"The Circular Line yellow is darkened ({cols['Y']} -> {SG.ink(cols['Y'])})", SG.ink(cols["Y"]) != cols["Y"])
chk(f"The Bannan Line blue is dark enough to keep ({SG.ink(cols['BL'])})", SG.ink(cols["BL"]) == cols["BL"])
bands = {ref: SG.band_block(ref, cols) for ref in cols}
chk(f"No band block is yellow concrete (the warning strip): {bands}", BL.YELLOW not in bands.values())
chk("Tamsui-Xinyi Line red, Zhonghe-Xinlu Line orange", bands["R"] == "minecraft:red_concrete"
    and bands["O"] == "minecraft:orange_concrete")
forms = SG.en_forms("Taipei Nangang Exhibition Center")
chk(f"The English for Taipei Nangang Exhibition Center never shortens to Nangang ({forms})", "Nangang" not in forms)
chk("Every short form is shorter than the original", all(len(f) <= len(forms[0]) for f in forms))
chk("Text that does not fit is truncated with an ellipsis", SG.fit(["X" * 40]).endswith("…")
    and SG.text_width(SG.fit(["X" * 40])) <= SG.SIGN_W)
chk("Eight Chinese characters fit with a prefix", SG.text_width("下一站 南港軟體園區") <= SG.SIGN_W)
far = SG.sight_lines(dict(id="beimen", name_zh="北門（承恩門）", name_en="North Gate (Beimen)",
                          station=("北門", "G13", 895, "Beimen")))[2]
chk(f"The attraction sign gives the distance in both languages at the longest ({far})",
    far == "出站約 900 m away" and SG.text_width(far) <= SG.SIGN_W)

print("\n" + ("All tests passed" if ok else "Some tests failed"))
sys.exit(0 if ok else 1)
