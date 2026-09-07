#!/usr/bin/env python3
"""真實出入口的單元測試：蓋一座直線地下站，接上幾個刁鑽位置的出入口，
再用玩家真的走得動的規則從每個出入口亭走到月台。

刻意挑的出入口位置，每一個都對應資料裡真的會出現的情況：
  · 站體旁邊（最單純）
  · 隧道正上方、月台範圍之外 —— 井得往外推，通道得沿站體外側繞回來
  · 8 m 內的兩個門 —— 要併成一座井
  · 500 m 外 —— 要拒絕
  · 對面那一側 —— 第二個洞

用法: ./.venv/bin/python tests/test_exits.py
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


Y, G = 40, 60           # 軌面、地面（平的）


def straight_seg(x0=-400, x1=400, idx_x=0):
    pts = [(float(x0), 0.0), (float(x1), 0.0)]
    samples = AL.resample(pts, ["tunnel", "tunnel"], AL.STEP)
    n = len(samples)
    ys = [Y] * n
    gnd = [G] * n
    idx = min(range(n), key=lambda i: abs(samples[i][0] - idx_x))
    stn = {idx: ("T1", "測試站", "Test")}
    toff = AL.track_offsets(samples, ys, gnd, [idx])
    hw = [AL.half_width(t) for t in toff]
    return dict(ref="T", samples=samples, ys=ys, ground=gnd, stn=stn,
                toff=toff, hw=hw), idx


def build_line_and_station(w, seg, idx, access):
    samples, ys, gnd, hw = seg["samples"], seg["ys"], seg["ground"], seg["hw"]
    half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
    lo, hi = idx - half, idx + half
    for i, (x, z, ux, uz, _) in enumerate(samples):
        if lo <= i <= hi:
            continue
        BL.sec_tunnel(w, x, z, -uz, ux, ys[i], hw=hw[i])
    BL.build_station(w, samples, ys, idx, True, label=seg["stn"][idx],
                     grounds=gnd, access=access)
    return lo, hi


seg, idx = straight_seg()
samples = seg["samples"]
print("占用索引")
occ = EX.index_segments([seg])
chk("隧道中心線在軌面高度是被占用的", occ.blocked(200, 0, Y, Y + 2))
chk("隧道側牆外一格沒被占用", not occ.blocked(200, 9, Y, Y + 2))
chk("站體範圍占到半寬 13", occ.blocked(0, 13, Y + 8, Y + 9))
chk("地面以上沒被占用", not occ.blocked(200, 0, G + 1, G + 3))

print("轉乘站分派")
seg2, idx2 = straight_seg(idx_x=0)
# 第二條線：同一條幾何但站體移到 x=+300（假裝是另一條線的站體）
seg2b, idx2b = straight_seg(idx_x=300)
boxes = {"A": (seg2["samples"], seg2["ys"], idx2),
         "B": (seg2b["samples"], seg2b["ys"], idx2b)}
asg = EX.assign_to_boxes([("1", 20, 40), ("2", 280, -40), ("3", 150, 30)], boxes)
chk(f"離 A 近的給 A：{[e[0] for e in asg['A']]}", [e[0] for e in asg["A"]] == ["1", "3"])
chk(f"離 B 近的給 B：{[e[0] for e in asg['B']]}", [e[0] for e in asg["B"]] == ["2"])

print("規劃")
ents = [("1", 10, 40),        # 站體旁邊
        ("2", 120, -5),       # 隧道正上方、月台之外
        ("3", 16, 44),        # 離 1 號 8 m -> 併掉
        ("4", 600, 0),        # 太遠
        ("5", -60, -30)]      # 對面、lo 端之外
ground_at = lambda x, z: G
plan = EX.plan_station(samples, seg["ys"], seg["ground"], idx, ents, ground_at,
                       occ, EX.Occupancy())
chk(f"穿堂層站立面 y{plan['ym']} = 軌面 + 7", plan["ym"] == Y + AL.MEZZ_DY + 1)
chk(f"蓋 {len(plan['shafts'])} 座井（1+3 併、2、5）", len(plan["shafts"]) == 3)
chk(f"拒絕 {len(plan['skipped'])} 個（4 號太遠）",
    len(plan["skipped"]) == 1 and plan["skipped"][0][0] == ["4"])
merged = [s for s in plan["shafts"] if "3" in s["refs"] and "1" in s["refs"]]
chk("1 號與 3 號共用一座井", len(merged) == 1)
s2 = next(s for s in plan["shafts"] if s["refs"] == ["2"])
cells2 = EX.shaft_cells(s2["x0"], s2["z0"], s2["ux"], s2["uz"])
chk(f"隧道正上方的井往外推了 {s2['slide']} m，井身離中心線 >= 13",
    s2["slide"] > 0 and min(abs(z) for _, z in cells2) >= 13)
chk("井身沒有壓到任何地下結構",
    not occ.any_blocked(cells2, plan["ym"] - 1, G + 5))
per_m = int(round(1 / AL.STEP))
hole_x = samples[plan["hole"]][0]
chk(f"開洞位置在 lo + 7 m（x={hole_x:.0f}，閘門在 lo + 14）",
    abs(hole_x - (samples[plan["lo"]][0] + 7)) < 1)
chk("兩側都開了洞",
    (int(round(hole_x)), 11) in plan["cells"] and (int(round(hole_x)), -11) in plan["cells"])
chk("通道格不包含站體內部", not (plan["cells"] & plan["no_wall"]))

print("蓋出來並走一遍")
w = DictSink()
lo, hi = build_line_and_station(w, seg, idx, access=False)
n_before = len(w.blocks)
objs, exits, rep = BX.station_exits([seg], {"測試站": ents}, ground_at,
                                    verbose=False)
chk(f"station_exits 回報這一站有 {list(exits.values())} 座井", exits == {(0, idx): 3})
for o in objs:
    o.build(w)
chk(f"多寫了 {len(w.blocks) - n_before:,} 個方塊", len(w.blocks) - n_before > 5000)

get = w.get
ym = plan["ym"]
bounds = (-450, Y - 5, -120, 450, G + 6, 120)
wells = [o for o in objs if isinstance(o, BX.BCC.ShaftStair)]
chk(f"{len(wells)} 座 ShaftStair", len(wells) == 3)
yellow = [(x, y + 1, z) for (x, y, z), b in w.blocks.items() if b == BL.YELLOW]
chk(f"月台警戒帶 {len(yellow)} 格", len(yellow) > 100)
starts = {}
for well in wells:
    x, z = well._w(0, 0)                      # 井口平台，門內第一格
    c = (x, well.g0 + 1, z)
    chk(f"出入口 {well.label[1]} 的井口站得住 {c}", walk.standable(get, *c))
    starts[well.label[1][0]] = c
comps = walk.components(get, list(starts.values()), bounds=bounds)
chk(f"三座井互相走得到（{len(comps)} 個連通分量）", len(comps) == 1)
for ref, c in sorted(starts.items()):
    dist, _ = walk.flood(get, [c], bounds=bounds)
    reach = sum(1 for y in yellow if y in dist)
    chk(f"從出入口 {ref} 走得到月台警戒帶（{reach}/{len(yellow)} 格）", reach == len(yellow))
    chk(f"出入口 {ref} 走得到穿堂層閘門前（非付費區）",
        any(y == ym and x < samples[lo][0] + 14 for (x, y, z) in dist))

print("井與通道沒有動到隧道")
ref_w = DictSink()
build_line_and_station(ref_w, seg, idx, access=False)
bad = 0
for (x, y, z), b in ref_w.blocks.items():
    if abs(z) <= 7 and not (samples[lo][0] - 1 <= x <= samples[hi][0] + 1):
        if w.blocks.get((x, y, z)) != b:
            bad += 1
chk(f"站體以外的隧道斷面一格都沒被改（改了 {bad} 格）", bad == 0)
hole_cells = [(int(round(hole_x)), ym + dy, 11) for dy in range(0, 3)]
chk("側牆的洞真的是空的", all(get(*c) == "minecraft:air" for c in hole_cells))
chk("洞旁邊的襯砌還在",
    get(int(round(hole_x)) + 6, ym, 11) != "minecraft:air")

print("沒有真實出入口時樣板樓梯照舊")
w0 = DictSink()
build_line_and_station(w0, seg, idx, access=True)
w1 = DictSink()
build_line_and_station(w1, seg, idx, access=False)
chk(f"access=True 多了 {len(w0) - len(w1):,} 個方塊（樣板樓梯與站屋）", len(w0) > len(w1) + 500)

print("\n全部通過" if ok else "\n有測試失敗")
raise SystemExit(0 if ok else 1)
