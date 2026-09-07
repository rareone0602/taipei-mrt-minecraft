#!/usr/bin/env python3
"""高架站的真實出入口與地下—高架轉乘的單元測試。

一條高架線（軌面 y80、地面 y67 -> 穿堂在橋下 y74）與一條地下線（軌面 y40 ->
穿堂 y47）十字交叉。高架站的出入口井從街上往上爬、通道是空橋；轉乘井從橋下
穿堂一路下到地下穿堂，穿過街面。蓋出來以後從街上的出口牌旁邊、不踩土，
走到兩條線的四座月台。

用法: ./.venv/bin/python tests/test_elevated_exits.py
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


def seg(pts, y, ref, kind):
    samples = AL.resample(pts, [kind] * len(pts), AL.STEP)
    n = len(samples)
    ys, gnd = [y] * n, [G] * n
    idx = min(range(n), key=lambda i: samples[i][0] ** 2 + samples[i][1] ** 2)
    stn = {idx: (ref + "1", "測試站", "Test")}
    toff = AL.track_offsets(samples, ys, gnd, [idx])
    return dict(ref=ref, samples=samples, ys=ys, ground=gnd, stn=stn, toff=toff,
                hw=[AL.half_width(t) for t in toff]), idx


def build(w, sg, idx, under):
    samples, ys, gnd, hw = sg["samples"], sg["ys"], sg["ground"], sg["hw"]
    half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
    for i, (x, z, ux, uz, _) in enumerate(samples):
        if idx - half <= i <= idx + half:
            continue
        if under:
            BL.sec_tunnel(w, x, z, -uz, ux, ys[i], hw=hw[i])
        else:
            BL.sec_bridge(w, x, z, -uz, ux, ys[i], G, hw=hw[i],
                          pier=(abs((i * AL.STEP) % AL.PIER_EVERY) < AL.STEP / 2))
    BL.build_station(w, samples, ys, idx, under, label=sg["stn"][idx],
                     grounds=gnd, access=False)


YE, YU = 80, 40
E, ie = seg([(-400.0, 0.0), (400.0, 0.0)], YE, "E", "bridge")
U, iu = seg([(0.0, -400.0), (0.0, 400.0)], YU, "U", "tunnel")
kind, L = AL.station_levels(YE, G)
chk(f"高架站的穿堂在橋下：{kind} y{L}", kind == "under" and L == YE - 6)

print("規劃")
ents = [("1", 80, 45), ("2", -120, -60)]            # 兩個街上的出入口，都靠高架站
occ = EX.index_segments([E, U])
plan = EX.plan_station(E["samples"], E["ys"], E["ground"], ie, ents, lambda x, z: G,
                       occ, EX.Occupancy(), own_tag=0)
chk(f"兩座井都擺得下（略過 {[s[3] for s in plan['skipped']]}）", len(plan["shafts"]) == 2)
chk(f"通道在穿堂高度 y{plan['ym']}", plan["ym"] == L)
for s in plan["shafts"]:
    chk(f"出入口 {s['refs']} 的街面 y{s['g0'] + 1} 比穿堂 y{s['y_to']} 低，井往上爬",
        s["g0"] + 1 < s["y_to"])

print("蓋出來並走一遍")
w = DictSink()
build(w, E, ie, False)
build(w, U, iu, True)
# 街面：鋪一層草皮當地形，驗證「不踩土」才有意義
for x in range(-250, 250):
    for z in range(-250, 250):
        if (x, G, z) not in w.blocks:
            w.set(x, G, z, TERRAIN)
objs, exits, rep = BX.station_exits([E, U], {"測試站": ents}, lambda x, z: G,
                                    verbose=False)
tr = rep["測試站"]["transfer"]
chk(f"轉乘通道接上（{tr[0][2].get('reason') if tr else None}）", bool(tr) and tr[0][2]["ok"])
chk(f"兩座站體都有出入口 {exits}（地下站用預設出入口）", set(exits) == {(0, ie), (1, iu)})
for o in objs:
    o.build(w)
get = w.get
bounds = (-450, YU - 5, -450, 450, YE + 12, 450)
man_made = lambda b: b != TERRAIN
tiles = [o for o in objs if isinstance(o, BX.BCC.Tile)]
chk(f"高架站的通道是空橋、地下站的是隧道：{sorted((t.y, t.bridge) for t in tiles)}",
    any(t.bridge and t.y == L for t in tiles) and any(not t.bridge and t.y == YU + 7 for t in tiles))
piers = sum(len(t.pier_to) for t in tiles if t.bridge)
chk(f"空橋底下有 {piers} 根柱子", piers > 3)

# 側式月台兩端的端牆壓在警戒帶最外一格上，那兩格本來就站不了人，不算
yel_e = [(x, y + 1, z) for (x, y, z), b in w.blocks.items()
         if b == BL.YELLOW and y == YE + 1 and walk.standable(get, x, y + 1, z)]
yel_u = [(x, y + 1, z) for (x, y, z), b in w.blocks.items() if b == BL.YELLOW and y == YU + 1]
chk(f"高架站兩座側式月台的警戒帶 {len(yel_e)} 格、地下站 {len(yel_u)} 格",
    len(yel_e) > 100 and len(yel_u) > 100)
wells = [o for o in objs if isinstance(o, BX.BCC.ShaftStair)]
for well in wells:
    if well.label[1] == "轉乘":
        chk(f"轉乘井從 y{well.g0 + 1} 下到 y{well.y_to}，穿過街面 y{G + 1}",
            well.g0 + 1 == L and well.y_to == YU + 7)
        continue
    # 街上的門：出口牌旁邊
    signs = [(x, y, z) for (x, y, z), t in w.signs.items()
             if t[0].startswith("出口") and abs(x - well.x0) < 20 and abs(z - well.z0) < 20]
    chk(f"出入口 {well.label[1]} 的出口牌立在街上（y{signs[0][1] if signs else None} = 街面 y{G + 1}）",
        len(signs) == 1 and signs[0][1] == G + 1)
    sx, sy, sz = signs[0]
    # 門檻：牌子旁邊腳下是人造方塊的那一格
    best = None
    for dx in range(-3, 4):
        for dz in range(-3, 4):
            c = (sx + dx, sy, sz + dz)
            if "sign" in get(*c):
                continue
            if walk.standable(get, *c, floor_ok=man_made):
                d = dx * dx + dz * dz
                if best is None or d < best[0]:
                    best = (d, c)
    chk(f"出入口 {well.label[1]} 牌子旁邊有門檻", best is not None)
    dist, _ = walk.flood(get, [best[1]], bounds=bounds, floor_ok=man_made)
    chk(f"出入口 {well.label[1]} 不踩土走得到高架站兩座月台（{sum(1 for q in yel_e if q in dist)}/{len(yel_e)}）",
        all(q in dist for q in yel_e))
    chk(f"出入口 {well.label[1]} 不踩土走得到地下站月台（{sum(1 for q in yel_u if q in dist)}/{len(yel_u)}）",
        all(q in dist for q in yel_u))
    top = max(c[1] for c in dist)
    chk(f"走到的最高點 y{top} 不高過高架月台的欄杆（y{YE + 3}）", top <= YE + 3)

print("\n全部通過" if ok else "\n有測試失敗")
raise SystemExit(0 if ok else 1)
