#!/usr/bin/env python3
"""轉乘通道的單元測試：兩條地下線十字交叉，穿堂層差 15 m，中間要立一座
折返梯井、兩層各接一段通道到付費區。蓋出來以後從一條線的月台走到另一條線
的月台，再從街上的出入口走到兩座月台。

用法: ./.venv/bin/python tests/test_transfer.py
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


G = 66                         # 平的地面


def seg(pts, y, ref):
    samples = AL.resample(pts, ["tunnel"] * len(pts), AL.STEP)
    n = len(samples)
    ys, gnd = [y] * n, [G] * n
    idx = min(range(n), key=lambda i: samples[i][0] ** 2 + samples[i][1] ** 2)
    stn = {idx: (ref + "1", "測試站", "Test")}
    toff = AL.track_offsets(samples, ys, gnd, [idx])
    return dict(ref=ref, samples=samples, ys=ys, ground=gnd, stn=stn, toff=toff,
                hw=[AL.half_width(t) for t in toff]), idx


def build(w, sg, idx):
    samples, ys, gnd, hw = sg["samples"], sg["ys"], sg["ground"], sg["hw"]
    half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
    for i, (x, z, ux, uz, _) in enumerate(samples):
        if idx - half <= i <= idx + half:
            continue
        BL.sec_tunnel(w, x, z, -uz, ux, ys[i], hw=hw[i])
    BL.build_station(w, samples, ys, idx, True, label=sg["stn"][idx],
                     grounds=gnd, access=False)


YA, YB = 40, 25                # A 線軌面 y40（穿堂 47）、B 線 y25（穿堂 32）
A, ia = seg([(-400.0, 0.0), (400.0, 0.0)], YA, "A")
B, ib = seg([(0.0, -400.0), (0.0, 400.0)], YB, "B")

print("規劃")
occ = EX.index_segments([A, B])
used = EX.Occupancy()
res = EX.plan_transfer(dict(samples=A["samples"], ys=A["ys"], grounds=A["ground"], idx=ia, tag=0),
                       dict(samples=B["samples"], ys=B["ys"], grounds=B["ground"], idx=ib, tag=1),
                       occ, used)
chk(f"十字交叉的兩座站體接得上（{res.get('reason')}）", res["ok"])
if res["ok"]:
    x0, z0, dx, dz, top, bottom = res["well"]
    chk(f"井在兩層之間：頂 {top} = 47、底 {bottom} = 32", (top, bottom) == (47, 32))
    cells = EX.shaft_cells(x0, z0, dx, dz, margin=1)
    chk(f"井身離兩條線的中心線都 >= {EX.CLEAR_OFF}（{min(abs(z) for _, z in cells)}, {min(abs(x) for x, _ in cells)}）",
        min(abs(z) for _, z in cells) >= EX.CLEAR_OFF and min(abs(x) for x, _ in cells) >= EX.CLEAR_OFF)
    chk("井身沒壓到任何隧道或站體", not occ.any_blocked(EX.shaft_cells(x0, z0, dx, dz), 31, 52))
    levels = sorted(l for _, l, _ in res["legs"])
    chk(f"兩段通道各在自己那一層 {levels}", levels == [32, 47])
    body = {c for c in EX.shaft_cells(x0, z0, dx, dz) if (c[0] - x0) * dx + (c[1] - z0) * dz >= 2}
    chk("兩段通道都沒有穿過井身", all(not (lc & body) for _, _, lc in res["legs"]))
    for tag, level, lc in res["legs"]:
        sg = A if tag == 0 else B
        lo, hi, _ = EX.station_frame(sg["samples"], sg["ys"], sg["stn"] and (ia if tag == 0 else ib))
        # 洞在付費區：閘門在 lo+14..16，洞要在 lo+18 之後
        holes = [c for c in lc if abs((c[1] if tag == 0 else c[0])) in (11, 12, 13)
                 and abs(c[0] if tag == 0 else c[1]) <= 36]
        along = [(c[0] if tag == 0 else c[1]) for c in holes]
        chk(f"{sg['ref']} 線的洞開在付費區（沿線 {min(along)}..{max(along)}，閘門在 -21..-19）",
            min(along) >= -35 + EX.PAID_FROM_M - EX.HOLE_HALF)

print("蓋出來並走一遍")
w = DictSink()
build(w, A, ia)
build(w, B, ib)
ents = [("1", 60, 40), ("2", -40, 90)]
objs, exits, rep = BX.station_exits([A, B], {"測試站": ents}, lambda x, z: G, verbose=False)
tr = rep["測試站"]["transfer"]
chk("station_exits 也接上了轉乘通道", tr and all(t[2]["ok"] for t in tr))
chk(f"兩座站體都有出入口 {exits}", set(exits) == {(0, ia), (1, ib)})
for o in objs:
    o.build(w)
get = w.get
bounds = (-450, YB - 5, -450, 450, G + 8, 450)
yel_a = [(x, y + 1, z) for (x, y, z), b in w.blocks.items() if b == BL.YELLOW and y == YA + 1]
yel_b = [(x, y + 1, z) for (x, y, z), b in w.blocks.items() if b == BL.YELLOW and y == YB + 1]
chk(f"兩座月台的警戒帶各 {len(yel_a)} / {len(yel_b)} 格", len(yel_a) > 100 and len(yel_b) > 100)
dist, _ = walk.flood(get, [yel_a[0]], bounds=bounds)
chk(f"從 A 線月台走得到 B 線月台（到達 {sum(1 for c in yel_b if c in dist)}/{len(yel_b)} 格）",
    all(c in dist for c in yel_b))
wells = [o for o in objs if isinstance(o, BX.BCC.ShaftStair)]
tw = [o for o in wells if o.label[1] == "轉乘"]
chk(f"轉乘井 {len(tw)} 座、出入口井 {len(wells) - len(tw)} 座", len(tw) == 1 and len(wells) - len(tw) == 2)
signs = [t for (x, y, z), t in w.signs.items() if t and t[0].startswith("轉乘")]
chk(f"轉乘井兩扇門邊都有牌子（{len(signs)} 面：{[s[1] for s in signs]}）",
    len(signs) == 2 and {s[1] for s in signs} == {"往 A 線", "往 B 線"})
for well in wells:
    if well.label[1] == "轉乘":
        continue
    x, z = well._w(0, 0)
    c = (x, well.g0 + 1, z)
    dist, _ = walk.flood(get, [c], bounds=bounds)
    chk(f"出入口 {well.label[1]} 走得到兩座月台（A {sum(1 for q in yel_a if q in dist)}、B {sum(1 for q in yel_b if q in dist)}）",
        all(q in dist for q in yel_a) and all(q in dist for q in yel_b))



# ---- 同一層直接接：兩條平行的地下線，穿堂一樣高，不立井、一條通道接過去 ----
print("同一層直接接")
ok2 = ok
C, ic = seg([(-400.0, 0.0), (400.0, 0.0)], YA, "C")
D, id_ = seg([(-400.0, 60.0), (400.0, 60.0)], YA, "D")
w2 = DictSink()
build(w2, C, ic)
build(w2, D, id_)
objs2, exits2, rep2 = BX.station_exits([C, D], {"測試站": [("1", 80, -40), ("2", -80, 100)]},
                                       lambda x, z: G, verbose=False)
tr2 = rep2["測試站"]["transfer"]
chk("同層的兩座站體直接接上、沒有井", tr2 and tr2[0][2]["ok"] and tr2[0][2]["well"] is None)
for o in objs2:
    o.build(w2)
get2 = w2.get
b2 = (-450, YA - 5, -50, 450, G + 8, 110)
yc = [(x, y + 1, z) for (x, y, z), b in w2.blocks.items() if b == BL.YELLOW and abs(z) <= 6]
yd = [(x, y + 1, z) for (x, y, z), b in w2.blocks.items() if b == BL.YELLOW and abs(z - 60) <= 6]
dist2, _ = walk.flood(get2, [yc[0]], bounds=b2)
chk(f"從 C 線月台走得到 D 線月台（{sum(1 for c in yd if c in dist2)}/{len(yd)}）", all(c in dist2 for c in yd))
dist3, _ = walk.flood(get2, [yd[0]], bounds=b2)
chk(f"從 D 線月台走得到 C 線月台（{sum(1 for c in yc if c in dist3)}/{len(yc)}）", all(c in dist3 for c in yc))

print("\n全部通過" if ok else "\n有測試失敗")
raise SystemExit(0 if ok else 1)
