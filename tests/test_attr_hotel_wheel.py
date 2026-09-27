#!/usr/bin/env python3
"""圓山大飯店與美麗華摩天輪（application/attractions/grand_hotel.py、miramar_wheel.py）。

只看 DictSink 裡寫出來的方塊，不信模組自己算的數字：
  圓山大飯店
    · 平地上：最高點（吻獸頂）離一樓樓板 87 m；主體蓋滿 OSM 主樓輪廓、門廊在南面
    · 正脊沿著輪廓的長軸（21°），金瓦、紅柱都在
    · 斜坡上：上層平台底下從地面一路填到樓板、沒有懸空的格子；削坡的地方平台上面是空的
    · 觀景點站得住（前庭廣場、十三樓迴廊），預設觀景點在大樓南邊、面向大樓
  美麗華摩天輪
    · 車廂頂離地 100 m、輪軸在 OSM 的點上
    · 前後兩道輪圈各自連成一圈（26 連通、一度一度掃過去都有）
    · 車廂數：中間挖空、上下是羊毛的車廂內部恰好 48 個
    · 輪面東西向（跟商場長邊一致）；頂端車廂的傳送點站得住、上下都是車廂
    · 商場蓋滿 OSM 輪廓

用法: ./.venv/bin/python tests/test_attr_hotel_wheel.py
"""
import math
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.application import attractions as AT
from mrt.application.attractions import kit
from mrt.domain import geometry as shapes
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def make(aid, ground):
    items = [it for it in AT.load_items() if it["id"] == aid]
    a = AT.for_world([], items=items)[0]
    AT.plan_all([a], ground, None, say=lambda *_: None)
    w = DictSink()
    AT.build(a, w)
    return a, w, items[0]


def base(b):
    return b.split("[")[0]


def solid(b):
    return base(b) != "minecraft:air"


# ================================================================ 圓山大飯店
print("圓山大飯店：平地")
a, w, item = make("grand_hotel", lambda x, z: 66)
chk("有專屬類別（不是 OsmMassing）", type(a).__name__ == "GrandHotel")
g0 = a.g0
ys = [k[1] for k, v in w.blocks.items() if solid(v)]
chk("最高點離一樓樓板 %d m（公開資料 87 m）" % (max(ys) - g0), max(ys) - g0 == 87)
main = next(f for f in item["features"] if f["osm"] == "way/25202548")
ring_ = max(main["outer"], key=len)
cells = shapes.poly_cells(ring_)
cover = sum(1 for x, z in cells if any(solid(w.get(x, y, z)) for y in range(g0 + 1, g0 + 30))) / len(cells)
chk("主體蓋滿 OSM 主樓輪廓（%.0f%% 的格子上有牆、柱或樓板）" % (cover * 100), cover >= 0.9)
# 門廊的金匾：應該在主樓重心的南邊（飯店面向基隆河）
cx = sum(x for x, z in cells) / len(cells)
cz = sum(z for x, z in cells) / len(cells)
plaque = [k for k, v in w.blocks.items() if v == "minecraft:gold_block" and g0 + 9 <= k[1] <= g0 + 13]
pz = sum(k[2] for k in plaque) / max(1, len(plaque))
chk("門廊的金匾在主樓南面（重心南邊 %.0f m）" % (pz - cz), plaque and pz - cz > 20)
# 正脊：最高那一層金色屋脊的走向
top_ridge = max(k[1] for k, v in w.blocks.items() if v == "minecraft:gold_block" and k[1] < g0 + 86)
rid = [(k[0], k[2]) for k, v in w.blocks.items() if v == "minecraft:gold_block" and k[1] == top_ridge]
xs, zs = np.array([p[0] for p in rid], float), np.array([p[1] for p in rid], float)
ev = np.linalg.eigh(np.cov(np.vstack([xs, zs])))[1][:, -1]
ang = math.degrees(math.atan2(ev[1], ev[0])) % 180
chk("正脊沿長軸：%.0f°（輪廓主軸約 21°）、長 %.0f m" % (ang, xs.max() - xs.min()),
    abs(ang - 21) < 6 and xs.max() - xs.min() > 40)
names = {base(v) for v in w.blocks.values()}
chk("金瓦、紅柱、青綠斗拱都在", {"minecraft:raw_gold_block", "minecraft:red_concrete",
                            "minecraft:dark_prismarine", "minecraft:prismarine_bricks"} <= names)
chk("沒有用到月台警示帶的黃色混凝土", "minecraft:yellow_concrete" not in names)
sp = a.spots()
chk("兩個觀景點：預設與十三樓迴廊", [s.key for s in sp] == ["", "terrace"])
for s in sp:
    chk("觀景點 %r (%d,%d,%d) 站得住" % (s.key, s.x, s.y, s.z), walk.standable(w.get, s.x, s.y, s.z))
s0 = sp[0]
chk("預設觀景點在大樓南邊（%d m）" % (s0.z - cz), s0.z - cz > 60)
want = kit.yaw_of(cx - s0.x, cz - s0.z)
chk("預設觀景點面向大樓（偏差 %.0f°）" % abs((s0.yaw - want + 180) % 360 - 180),
    abs((s0.yaw - want + 180) % 360 - 180) < 20)
front, back = AT.plaque_lines(a)
chk("說明牌第一行是「圓山大飯店」", kit.sight_fn(a.id) == "sight/grand_hotel"
    and a.plaque()[0] == "圓山大飯店")

print("\n圓山大飯店：斜坡（往北每公尺升 0.12 m，外加東西向起伏）")


def slope(x, z):
    return int(round(80 - 0.12 * (z + 3590) + 3 * math.sin(x / 23.0)))


a, w, item = make("grand_hotel", slope)
g0 = a.g0
fr = a.fr
up = (a.kind == 1) & (np.abs(a.Lv - g0) < 1e-6)
holes = low = high = 0
for i, j in zip(*np.nonzero(up)):
    x, z = int(fr.X[i, j]), int(fr.Z[i, j])
    gy = slope(x, z)
    if gy < g0:
        low += 1
        if any(not solid(w.get(x, y, z)) for y in range(gy + 1, g0 + 1)):
            holes += 1
    elif gy > g0:
        high += 1
chk("上層平台跨在坡上：%d 格要填、%d 格要削" % (low, high), low > 200 and high > 200)
chk("填方的格子從地面到樓板沒有空隙（%d 格有洞）" % holes, holes == 0)
cut_bad = 0
for i, j in zip(*np.nonzero(up)):
    x, z = int(fr.X[i, j]), int(fr.Z[i, j])
    gy = slope(x, z)
    if gy > g0 + 1 and a.body[i, j] == 0:
        if w.get(x, g0 + 1, z) != "minecraft:air" and base(w.get(x, g0 + 1, z)) != "minecraft:diorite_wall":
            cut_bad += 1
chk("削坡的平台上面清空了（%d 格沒清）" % cut_bad, cut_bad == 0)
floor = sum(1 for i, j in zip(*np.nonzero(a.body)) if solid(w.get(int(fr.X[i, j]), g0, int(fr.Z[i, j]))))
chk("主樓一樓樓板鋪滿（%d / %d）" % (floor, int(a.body.sum())), floor == int(a.body.sum()))
ys = [k[1] for k, v in w.blocks.items() if solid(v)]
chk("斜坡上高度一樣是 87 m（%d）" % (max(ys) - g0), max(ys) - g0 == 87)
for s in a.spots():
    chk("斜坡上觀景點 %r 站得住" % s.key, walk.standable(w.get, s.x, s.y, s.z))

# ================================================================ 美麗華摩天輪
print("\n美麗華摩天輪：平地")
a, w, item = make("miramar_wheel", lambda x, z: 66)
chk("有專屬類別（不是 OsmMassing）", type(a).__name__ == "MiramarWheel")
g0 = a.g0
ys = [k[1] for k, v in w.blocks.items() if solid(v)]
chk("最高點離地 %d m（公開資料 100 m）" % (max(ys) - g0), max(ys) - g0 == 100)
node = next(f for f in item["features"] if f.get("point"))
hx, hz = node["point"]
axle = [k for k, v in w.blocks.items() if v == "minecraft:light_gray_concrete" and k[1] > g0 + 60]
ax = sum(k[0] for k in axle) / len(axle) + 0.5
az = sum(k[2] for k in axle) / len(axle) + 0.5
hub_y = int(round(sum(k[1] for k in axle) / len(axle)))
chk("輪軸在 OSM 的點上（差 %.1f m）、高 %d m" % (math.hypot(ax - hx, az - hz), hub_y - g0),
    math.hypot(ax - hx, az - hz) <= 1.5 and 60 <= hub_y - g0 <= 70)
# 輪圈：OSM 的點為圓心、半徑 27～29.5 m 的白色格子（內圈、商場的白色標誌不算）
rim = [k for k, v in w.blocks.items() if v == "minecraft:white_concrete" and abs(k[2] + 0.5 - hz) <= 6
       and 27.0 <= math.hypot(k[0] + 0.5 - hx, k[1] - hub_y) <= 29.5]
rx = np.array([k[0] for k in rim], float)
rz = np.array([k[2] for k in rim], float)
chk("輪面東西向：輪圈東西寬 %.0f m、南北厚 %.0f m" % (rx.max() - rx.min(), rz.max() - rz.min()),
    rx.max() - rx.min() > 55 and rz.max() - rz.min() <= 7)


def rim_face(sign):
    """一道輪圈：半徑 27～29.5、在輪軸那一側（南或北）的白色格子。"""
    return {(x, y, z) for (x, y, z) in rim if (z + 0.5 - hz) * sign > 0.4}


for sign, nm in ((1, "南"), (-1, "北")):
    face = rim_face(sign)
    start = next(iter(face))
    seen = {start}
    q = deque([start])
    while q:
        x, y, z = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    n = (x + dx, y + dy, z + dz)
                    if n in face and n not in seen:
                        seen.add(n)
                        q.append(n)
    # 輪圈周長約 178 m：每 3° 一格扇形（約 1.5 m）都要有輪圈
    bins = {int((math.degrees(math.atan2(y - hub_y, x + 0.5 - hx)) % 360) // 3) for x, y, z in face}
    chk("%s側輪圈連成一圈：%d 格一個連通分量、120 個 3° 扇形都有（缺 %d 個）"
        % (nm, len(face), 120 - len(bins)), len(seen) == len(face) and len(bins) == 120)
interiors = 0
for (x, y, z), v in w.blocks.items():
    if v != "minecraft:air" or w.get(x, y + 1, z) != "minecraft:air":
        continue
    below, above = w.get(x, y - 1, z), w.get(x, y + 2, z)
    if base(below).endswith(("_wool", "glass")) and base(above).endswith(("_wool", "glass")) \
            and y > g0 + 25:
        interiors += 1
chk("車廂 %d 個（公開資料 48 個）" % interiors, interiors == 48)
clear = {k for k, v in w.blocks.items() if v in ("minecraft:white_stained_glass", "minecraft:glass")}
chk("有透明車廂（白色玻璃 %d 格）" % len(clear), len(clear) >= 2 * 16)
sp = a.spots()
chk("兩個觀景點：預設與頂端車廂", [s.key for s in sp] == ["", "top"])
for s in sp:
    chk("觀景點 %r (%d,%d,%d) 站得住" % (s.key, s.x, s.y, s.z), walk.standable(w.get, s.x, s.y, s.z))
top = sp[1]
chk("頂端車廂：腳下是車廂地板、頭上是車廂頂（高 %d m）" % (top.y - g0),
    base(w.get(top.x, top.y - 1, top.z)).endswith("_wool")
    and base(w.get(top.x, top.y + 2, top.z)).endswith("_wool") and top.y - g0 >= 95)
s0 = sp[0]
want = kit.yaw_of(hx - s0.x, hz - s0.z)
chk("預設觀景點在輪子南邊 %d m、面向輪子（偏差 %.0f°）" % (s0.z - hz, abs((s0.yaw - want + 180) % 360 - 180)),
    s0.z - hz > 45 and abs((s0.yaw - want + 180) % 360 - 180) < 10)
mall = next(f for f in item["features"] if f["osm"] == "way/155816458")
mc = shapes.poly_cells(max(mall["outer"], key=len))
cover = sum(1 for x, z in mc if solid(w.get(x, g0 + 12, z)) or solid(w.get(x, g0 + 6, z))) / len(mc)
chk("商場蓋滿 OSM 輪廓（%.0f%%）" % (cover * 100), cover >= 0.95)
names = {base(v) for v in w.blocks.values()}
chk("沒有用到月台警示帶的黃色混凝土", "minecraft:yellow_concrete" not in names)
chk("說明牌第一行是「美麗華摩天輪」", a.plaque()[0] == "美麗華摩天輪")

print("\n" + ("全部通過" if ok else "有測試失敗"))
sys.exit(0 if ok else 1)
