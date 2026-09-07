#!/usr/bin/env python3
"""平面出入口的單元測試：高架站的街面就在穿堂前後兩公尺內時不蓋井，
通道直接開到街上、門外接一段坡道。

一條高架線（軌面 y80、平地 y67 -> 穿堂在橋下 y74）旁邊有三個出入口，各在一塊
台地上：街面 y76（比穿堂高 2 m）、y73（低 1 m）、y71（低 3 m，剛好夠蓋井）。
前兩個要變成平面出入口、第三個還是折返梯井；蓋出來以後從三面出口牌旁邊
不踩土走到兩座月台，門口也都踩得到街。

用法: ./.venv/bin/python tests/test_ground_gate.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application import build_exits as BX
from mrt.application import build_line as BL
from mrt.domain import alignment as AL
from mrt.domain import exits as EX
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


G = 67
TERRAIN = "minecraft:grass_block"
YE = 80
pts = [(-400.0, 0.0), (400.0, 0.0)]
samples = AL.resample(pts, ["bridge"] * len(pts), AL.STEP)
n = len(samples)
ys, gnd = [YE] * n, [G] * n
ie = min(range(n), key=lambda i: samples[i][0] ** 2 + samples[i][1] ** 2)
stn = {ie: ("E1", "測試站", "Test")}
toff = AL.track_offsets(samples, ys, gnd, [ie])
E = dict(ref="E", samples=samples, ys=ys, ground=gnd, stn=stn, toff=toff,
         hw=[AL.half_width(t) for t in toff])
kind, L = AL.station_levels(YE, G)
chk(f"高架站的穿堂在橋下：{kind} y{L}", kind == "under" and L == YE - 6)

# 三塊台地：街面 = 地面 + 1
PLATEAU = {(80, 45): L + 1, (-120, -60): L - 2, (-60, 70): L - 4}


def ground_at(x, z):
    for (px, pz), g in PLATEAU.items():
        if abs(x - px) <= 12 and abs(z - pz) <= 12:
            return g
    return G


ents = [("1", 80, 45), ("2", -120, -60), ("3", -60, 70)]

print("規劃")
occ = EX.index_segments([E])
plan = EX.plan_station(E["samples"], E["ys"], E["ground"], ie, ents, ground_at,
                       occ, EX.Occupancy(), own_tag=0)
chk(f"兩座平面出入口、一座井（略過 {[s[3] for s in plan['skipped']]}）",
    len(plan["gates"]) == 2 and len(plan["shafts"]) == 1)
chk("MIN_RISE 是 3：差 3 才蓋井，差 2 以下是平面出入口",
    EX.MIN_RISE == 3 and not EX.drop_ok("under", L + 1, L) and EX.drop_ok("under", L - 4, L))
for s in plan["gates"]:
    chk(f"平面出入口 {s['refs']} 的門在出入口位置上、前庭地面 y{s['g0']}",
        (s["x0"], s["z0"]) in {(e[1], e[2]) for e in ents} and abs(s["g0"] + 1 - L) <= 2)
    chk(f"平面出入口 {s['refs']} 的坡道背對站體（u=({s['ux']},{s['uz']})）",
        (s["ux"], s["uz"]) == (0, 1 if s["z0"] > 0 else -1))
chk("門外的坡道與前庭不砌牆", plan["open"] and plan["open"] <= plan["no_wall"])

print("蓋出來並走一遍")
w = DictSink()
half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
for i, (x, z, ux, uz, _) in enumerate(samples):
    if ie - half <= i <= ie + half:
        continue
    BL.sec_bridge(w, x, z, -uz, ux, ys[i], G, hw=E["hw"][i],
                  pier=(abs((i * AL.STEP) % AL.PIER_EVERY) < AL.STEP / 2))
BL.build_station(w, samples, ys, ie, False, label=stn[ie], grounds=gnd, access=False)
for x in range(-250, 250):
    for z in range(-250, 250):
        g = ground_at(x, z)
        if (x, g, z) not in w.blocks:
            w.set(x, g, z, TERRAIN)
objs, exits, rep = BX.station_exits([E], {"測試站": ents}, ground_at, verbose=False)
chk(f"報表裡三座都蓋了 {[s['refs'] for s in rep['測試站']['built']]}",
    len(rep["測試站"]["built"]) == 3 and exits == {(0, ie): 3})
gates = [o for o in objs if isinstance(o, BX.GroundGate)]
wells = [o for o in objs if isinstance(o, BX.BCC.ShaftStair)]
chk(f"物件：{len(gates)} 座平面出入口、{len(wells)} 座井", len(gates) == 2 and len(wells) == 1)
for o in objs:
    o.build(w)
get = w.get
bounds = (-450, G - 5, -450, 450, YE + 12, 450)
man_made = lambda b: b != TERRAIN
yel = [(x, y + 1, z) for (x, y, z), b in w.blocks.items()
       if b == BL.YELLOW and y == YE + 1 and walk.standable(get, x, y + 1, z)]
chk(f"兩座側式月台的警戒帶 {len(yel)} 格", len(yel) > 100)

for o in gates + wells:
    ref = o.label[1]
    street = ground_at(*[e[1:] for e in ents if e[0] == ref[0]][0]) + 1
    signs = [(x, y, z) for (x, y, z), t in w.signs.items()
             if t[0].startswith("出口") and abs(x - o.x0) < 20 and abs(z - o.z0) < 20]
    chk(f"出入口 {ref} 的出口牌立在街上（y{signs[0][1] if signs else None} = 街面 y{street}）",
        len(signs) == 1 and signs[0][1] == street)
    sx, sy, sz = signs[0]
    best = None
    for dx in range(-3, 4):
        for dz in range(-3, 4):
            for dy in (-1, 0, 1):
                c = (sx + dx, sy + dy, sz + dz)
                if "sign" in get(*c) or not walk.standable(get, *c, floor_ok=man_made):
                    continue
                d = dx * dx + dz * dz + 4 * dy * dy
                if best is None or d < best[0]:
                    best = (d, c)
    chk(f"出入口 {ref} 牌子旁邊有門檻", best is not None)
    c = best[1]
    on_street = any(walk.standable(get, c[0] + dx, c[1] + dy, c[2] + dz,
                                   floor_ok=lambda b: b == TERRAIN)
                    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2))
                    for dy in (-1, 0, 1))
    chk(f"出入口 {ref} 的門口踩得到街面", on_street)
    dist, _ = walk.flood(get, [c], bounds=bounds, floor_ok=man_made)
    chk(f"出入口 {ref} 不踩土走得到兩座月台（{sum(1 for q in yel if q in dist)}/{len(yel)}）",
        all(q in dist for q in yel))
    if isinstance(o, BX.GroundGate):
        # 坡道每格升降不超過一格，門那一格是通道的樓板
        floors = [o.floor_at(a) for a in range(0, o.run + 1)]
        chk(f"出入口 {ref} 的坡道 {floors} 每格升降一格、盡頭在街面 y{street}",
            floors[0] == L - 1 and floors[-1] == street - 1
            and all(abs(p - q) <= 1 for p, q in zip(floors, floors[1:])))

print("\n全部通過" if ok else "\n有測試失敗")
raise SystemExit(0 if ok else 1)
