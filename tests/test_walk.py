#!/usr/bin/env python3
"""行走可達性規則的單元測試。

這支測試的重點是**半磚**。專案的樓梯是「整塊、下半磚」交替鋪的，每公尺
升降 0.5 m；如果可達性判斷不認得半磚，整段樓梯會被當成一半實心一半懸空，
驗證工具就會回報一堆根本不存在的斷點 —— 或者更糟，把真的斷掉的樓梯
判成通過。所以直接拿生成器蓋出來的樓梯來驗，不用手刻的假資料。

用法: ./.venv/bin/python tests/test_walk.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application.landmarks import ShaftStair
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def floor_world(x0, x1, z0, z1, y, block="minecraft:smooth_stone"):
    """鋪一片地板，上方留 4 格淨空。"""
    d = DictSink()
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            d.set(x, y, z, block)
            for dy in range(1, 5):
                d.set(x, y + dy, z, "minecraft:air")
    return d


print("方塊分類")
chk("空氣可穿越", walk.is_passable("minecraft:air"))
chk("鐵軌可穿越（站在底下那格）", walk.is_passable("minecraft:rail"))
chk("告示牌可穿越", walk.is_passable("minecraft:oak_sign[rotation=4]"))
chk("鐵欄杆擋路", not walk.is_passable("minecraft:iron_bars"))
chk("無狀態的半磚預設是下半磚", walk.is_bottom_slab("minecraft:smooth_stone_slab"))
chk("上半磚不算下半磚", not walk.is_bottom_slab("minecraft:smooth_stone_slab[type=top]"))
chk("雙層半磚不算下半磚", not walk.is_bottom_slab("minecraft:smooth_stone_slab[type=double]"))

print("平地")
d = floor_world(0, 9, 0, 9, 60)
g = d.get
chk("地板上一格站得住", walk.standable(g, 3, 61, 3))
chk("地板那一格站不住（腳陷在方塊裡）", not walk.standable(g, 3, 60, 3))
chk("懸空站不住", not walk.standable(g, 3, 63, 3))
dist, _ = walk.flood(g, [(0, 61, 0)], bounds=(0, 55, 0, 9, 70, 9))
chk(f"10x10 地板全部走得到（{len(dist)} 格）", len(dist) == 100)
chk("步數等於曼哈頓距離", dist[(9, 61, 9)] == 18)

print("淨空不足")
d2 = floor_world(0, 9, 0, 9, 60)
for x in range(0, 10):
    d2.set(x, 62, 5, "minecraft:stone")        # 只剩 1 格淨空的橫樑
dist, _ = walk.flood(d2.get, [(0, 61, 0)], bounds=(0, 55, 0, 9, 70, 9))
chk(f"1 格淨空的橫樑擋得住（走到 {len(dist)} 格）", len(dist) == 50)
chk("樑另一側走不到", (0, 61, 9) not in dist)

print("牆")
d3 = floor_world(0, 9, 0, 9, 60)
for x in range(0, 10):
    for dy in (1, 2, 3):
        d3.set(x, 60 + dy, 5, "minecraft:stone")
comps = walk.components(d3.get, [(0, 61, 0), (0, 61, 9)],
                        bounds=(0, 55, 0, 9, 70, 9))
chk(f"整面牆把地板切成兩塊（{len(comps)} 個分量）", len(comps) == 2)

print("落差")
d4 = floor_world(0, 4, 0, 9, 60)
for x in range(5, 10):                          # 右半邊低 1 格
    for z in range(0, 10):
        d4.set(x, 59, z, "minecraft:smooth_stone")
        for dy in range(1, 5):
            d4.set(x, 59 + dy, z, "minecraft:air")
dist, _ = walk.flood(d4.get, [(0, 61, 0)], bounds=(0, 50, 0, 9, 70, 9))
chk("差 1 格跨得過去", (9, 60, 9) in dist)

d5 = floor_world(0, 4, 0, 9, 60)
for x in range(5, 10):                          # 右半邊低 3 格
    for z in range(0, 10):
        d5.set(x, 57, z, "minecraft:smooth_stone")
        for dy in range(1, 5):
            d5.set(x, 57 + dy, z, "minecraft:air")
dist, _ = walk.flood(d5.get, [(0, 61, 0)], bounds=(0, 50, 0, 9, 70, 9))
chk("差 3 格過不去（跳得下去、爬不上來的不算連通）", (9, 58, 9) not in dist)

print("折返式樓梯井（landmarks.ShaftStair 蓋出來的真樓梯）")
G0, YTO = 66, 44                                # 22 m 深，跟淡水信義線穿堂差不多
d6 = DictSink()
st = ShaftStair(0, 0, 1, 0, G0, YTO)
st.build(d6)
g6 = d6.get
x0, z0, x1, z1 = st.bbox()
b = (x0, YTO - 4, z0, x1, G0 + 6, z1)
top = walk.nearest_standable(g6, 0, G0 + 1, 0, radius=3, dy=2)
chk(f"井口地面站得住 {top}", top is not None)
dist, came = walk.flood(g6, [top], bounds=b)
bottom = [c for c in dist if c[1] <= YTO]
chk(f"從地面 y={G0} 一路走到井底 y={YTO}（{len(bottom)} 格在底層）",
    len(bottom) > 0)
if bottom:
    deep = min(dist, key=lambda c: c[1])
    chk(f"最深走到 y={deep[1]}（目標 {YTO}）", deep[1] <= YTO)
    chk(f"路徑長 {dist[deep]} 步，多於直線距離",
        dist[deep] > (G0 - YTO))
    # 反向也要走得通 —— 對稱的規則本來就保證，這裡是防呆
    back, _ = walk.flood(g6, [deep], bounds=b)
    chk("從井底走得回地面", top in back)

print("\n全部通過" if ok else "\n有測試失敗")
raise SystemExit(0 if ok else 1)
