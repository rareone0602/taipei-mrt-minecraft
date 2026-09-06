#!/usr/bin/env python3
"""地下街的單元測試：不必產生存檔，用 DictSink 蓋一座小地下街再走一遍。

重點不是「有沒有放方塊」，而是「放完之後走不走得通」。這一支和
tools/verify_concourse.py 共用 domain/walk.py 的同一套規則，差別只在
方塊來源：這裡是記憶體裡的 dict，那裡是從 Anvil 存檔讀回來的。
所以這支測試抓得到的問題，在真實世界裡也是同一個問題。

用法: ./.venv/bin/python tests/test_concourse.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application import build_concourse as BC
from mrt.domain import concourse as CC
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True
G = 68              # 平坦地面
Y = G - 6           # 地下街站立面


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def ways_T():
    """一個 T 字路口：東西向幹道 + 往南的支線。節點 id 共用才接得起來。"""
    return [
        {"nodes": [1, 2, 3], "points": [[-60, 0], [0, 0], [60, 0]]},
        {"nodes": [2, 4], "points": [[0, 0], [0, 60]]},
    ]


print("level 標籤解析")
chk("-1 -> (-1, -1)", CC.parse_level("-1") == (-1.0, -1.0))
chk("-2--1 是範圍不是減法", CC.parse_level("-2--1") == (-2.0, -1.0))
chk("-2--0 的 -0 收成 0", CC.parse_level("-2--0") == (-2.0, 0.0))
chk("分號清單不必先排序", CC.parse_level("0;-0.5;-1") == (-1.0, 0.0))
chk("冒號當成打錯的分號", CC.parse_level("-1:0;1") == (-1.0, 1.0))
chk("5A 取前面的數字", CC.parse_level("5A") == (5.0, 5.0))
chk("空字串回 None", CC.parse_level("") is None)
chk("地下才收", CC.underground({"level": "-1"}))
chk("地面不收", not CC.underground({"level": "0"}))
chk("通到 1 樓以上的百貨電扶梯不收", not CC.underground({"level": "-1-4"}))
chk("沒 level 但標隧道也算", CC.underground({"tunnel": "yes"}))

print("併點與連通")
pos, adj, edges = CC.build_graph(ways_T(), tol=3.0)
chk(f"T 字路口 4 個節點（實得 {len(pos)}）", len(pos) == 4)
chk("路口節點分歧度 3", max(len(v) for v in adj.values()) == 3)
chk("只有一個連通分量", len(CC.components(pos, adj)) == 1)

# 沒接起來的端點：差 2 m 應該併掉，差 40 m 不該併
near = ways_T() + [{"nodes": [9, 10], "points": [[62, 0], [90, 0]]}]
pos2, adj2, _ = CC.build_graph(near, tol=3.0)
chk("差 2 m 的懸空端點被併起來", len(CC.components(pos2, adj2)) == 1)
far = ways_T() + [{"nodes": [9, 10], "points": [[100, 0], [130, 0]]}]
pos3, adj3, edges3 = CC.build_graph(far, tol=3.0)
chk("差 40 m 的不併", len(CC.components(pos3, adj3)) == 2)
added = CC.bridge_gaps(pos3, adj3, edges3, max_gap=45.0)
chk(f"補洞後接起來（補了 {len(added)} 條）", len(CC.components(pos3, adj3)) == 1)

print("主分量的挑選")
# 台北車站正上方有一條兩節點的孤立通道，選「最近」會選到它
# 孤立的短通道要離主網夠遠（併點容差 3 m 內會被吸進去）
stray = [{"nodes": [77, 78], "points": [[6, 6], [14, 14]]}] + ways_T()
p4, a4, _ = CC.build_graph(stray, tol=3.0)
grp = CC.main_component(p4, a4, near=(0, 0))
chk(f"挑到近處最大的那一團而不是最近的（{len(grp)} 個節點）", len(grp) == 4)

print("出入口樓梯的方向")
d = CC.outward(pos, adj, 3, 60, 0)          # 出入口就是東端點
chk(f"端點出入口背對通道往東爬 {d}", d == (1, 0))
d = CC.outward(pos, adj, 1, -60, 0)
chk(f"西端點往西爬 {d}", d == (-1, 0))

print("蓋一座小地下街並走一遍")
ents = [("E", 60, 0), ("W", -60, 0), ("S", 0, 60)]
objs, rep = BC.plan(ways_T(), ents, lambda x, z: G, Y, near=(0, 0))
w = DictSink()
for o in objs:
    o.build(w)
chk(f"寫出 {len(w.blocks):,} 個方塊", len(w.blocks) > 5000)
chk(f"三個出入口都接得上（{len(rep['connected'])}）", len(rep["connected"]) == 3)
chk(f"沒有接不上的（{rep['orphan']}）", not rep["orphan"])
chk(f"蓋了 {len(rep['exits'])} 座出入口樓梯", len(rep["exits"]) == 3)

get = w.get
bnd = (-90, Y - 10, -30, 90, G + 10, 90)
feet = {}
for ref, x, z in ents:
    feet[ref] = walk.nearest_standable(get, x, Y, z, radius=6, dy=4)
chk("三個出入口在地下都站得住", all(feet.values()))

# 關鍵：不出地面就要能互相往返
ug = (-90, Y - 10, -30, 90, G - 2, 90)
comps = walk.components(get, list(feet.values()), bounds=ug)
chk(f"不出地面連成一團（{len(comps)} 個分量）", len(comps) == 1)
dist, _ = walk.flood(get, [feet["E"]], bounds=ug)
chk(f"東端走到西端 {dist.get(feet['W'])} 步（直線 120 m）",
    dist.get(feet["W"], 0) >= 120)

# 每個出入口都要走得上地面
for ref, x, z in ents:
    d2, _ = walk.flood(get, [feet[ref]], bounds=bnd)
    chk(f"{ref} 走得上地面", any(p[1] >= G for p in d2))

print("驗證器抓得到壞掉的地下街")
# 否則上面全過也不代表什麼：把路口封死，連通分量必須變成 2
w2 = DictSink()
for o in objs:
    o.build(w2)
# 把東翼整個斷面砌死（含地板與淨空），東側出入口應該被孤立起來
for x in (10, 11, 12):
    for z in range(-9, 10):
        for y in range(Y - 1, Y + BC.HEAD + 2):
            w2.set(x, y, z, "minecraft:deepslate_bricks")
comps2 = walk.components(w2.get, list(feet.values()), bounds=ug)
chk(f"把路口砌死之後分成 {len(comps2)} 團", len(comps2) == 2)

print("退化輸入")
o0, r0 = BC.plan([], [], lambda x, z: G, Y)
chk("沒有通道不炸且不產生物件", o0 == [] and r0["cells"] == 0)
o1, r1 = BC.plan(ways_T(), [("X", 900, 900)], lambda x, z: G, Y, near=(0, 0))
chk(f"太遠的出入口列為接不上（{r1['orphan']}）", len(r1["orphan"]) == 1)
o2, r2 = BC.plan(ways_T(), [], lambda x, z: Y, Y, near=(0, 0))
chk("地面比地下街還低時整段放棄，不會蓋出露天壕溝", r2["cells"] == 0)

print("\n全部通過" if ok else "\n有測試失敗")
raise SystemExit(0 if ok else 1)
