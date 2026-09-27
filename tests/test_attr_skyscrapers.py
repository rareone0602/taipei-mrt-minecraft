#!/usr/bin/env python3
"""台北101 與新光摩天大樓（application/attractions/taipei101.py、shin_kong.py）。

用平地（y66）與 DictSink 蓋一次，不必產生存檔：
  · 101：塔尖 = 一樓 + 508、八斗（每斗頂都有一道挑簷，斗與斗之間半邊長縮回 4 m）、
    地面的平面約 54 m 見方、腰身約 44 m、89 樓觀景台的樓板在 +382 且站得住、
    阻尼器是金色的球、大廳與觀景台的告示牌互相傳送（函式路徑同 kit.sight_fn）
  · 新光：天線頂 = 一樓 + 244、轉角照 OSM 一層一層退（44 層那一角在 187 m 以上沒有東西）、
    主輪廓幾乎整個蓋滿、北面門廳有門、大廳站得住
  · 共通：禁區不寫、說明牌第一行是景點中文名且放得下、告示牌第一行不以「出口」開頭、
    不用黃色混凝土（月台警示帶專用）、方塊 id 都在 26.2 的 jar 裡（找得到 jar 才驗）

用法: ./.venv/bin/python tests/test_attr_skyscrapers.py
"""
import math
import os
import re
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt import config
from mrt.application import attractions as AT
from mrt.application import signage as SG
from mrt.application.attractions import kit
from mrt.application.attractions import shin_kong as SK
from mrt.application.attractions import taipei101 as T1
from mrt.domain import geometry as shapes
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def solid(b):
    return b is not None and b.split("[")[0] not in ("minecraft:air", "minecraft:cave_air")


def build(aid, keep=None):
    items = [it for it in AT.load_items() if it["id"] == aid]
    a = AT.for_world([], items=items)[0]
    AT.plan_all([a], lambda x, z: 66, keep, say=lambda *_: None)
    w = DictSink()
    t0 = time.time()
    dropped = AT.build(a, w, keep)
    return a, w, time.time() - t0, dropped


def jar_blocks():
    jar = os.path.expanduser("~/Library/Application Support/minecraft/versions/26.2/26.2.jar")
    if not os.path.exists(jar):
        return None
    out = set()
    for n in zipfile.ZipFile(jar).namelist():
        m = re.match(r"assets/minecraft/blockstates/([a-z0-9_]+)\.json$", n)
        if m:
            out.add("minecraft:" + m.group(1))
    return out


JAR = jar_blocks()


def common(a, w):
    names = {b.split("[")[0] for b in w.blocks.values()}
    chk("沒有黃色混凝土（月台警示帶專用）", "minecraft:yellow_concrete" not in names)
    if JAR is not None:
        bad = sorted(n for n in names if n not in JAR)
        chk("方塊 id 都在 26.2 的 jar 裡（%d 種）%s" % (len(names), (" 缺：%s" % bad) if bad else ""), not bad)
    firsts = [v[0] for v in w.signs.values()]
    chk("告示牌第一行都不以「出口」開頭（%d 面）" % len(firsts), not any(f.startswith("出口") for f in firsts))
    front, back = AT.plaque_lines(a)
    mine = front[:3] + back[:3]                  # 背面第四行「資料 © OpenStreetMap」是框架的
    chk("說明牌：第一行是「%s」、景點給的字都放得下（%s）" % (a.name_zh, [SG.line_width(t) for t in mine]),
        front[0]["text"] == a.name_zh and all(SG.line_width(t) <= SG.SIGN_W for t in mine)
        and "…" not in "".join(str(t if isinstance(t, str) else t["text"]) for t in mine))
    sp = a.spots()
    chk("第一個傳送點是預設觀景點（key 空字串）", sp and sp[0].key == "")
    for s in sp[1:]:
        st = walk.standable(w.get, s.x, s.y, s.z)
        chk("傳送點 %s (%d,%d,%d) 站得住（腳 %s、腳下 %s）" % (
            s.key, s.x, s.y, s.z, w.get(s.x, s.y, s.z), w.get(s.x, s.y - 1, s.z)), st)


# ================================================================ 台北101
print("台北101")
a, w, dt, _ = build("taipei101")
g0 = a.g0
ys = [k[1] for k in w.blocks]
chk("蓋一次 %.1f s（每個 region 呼叫一次，要遠低於一分鐘）" % dt, dt < 30)
chk("一樓樓板 y%d（平地 y66）" % g0, g0 == 66)
chk("最高點 y%d = 一樓 + %d（塔尖 508 m）" % (max(ys), max(ys) - g0), max(ys) == g0 + 508)
chk("top_y() 跟實際最高點一樣", a.top_y() == max(ys))
cx, cz = a.fr.world(0, 0)
ymax = max(ys)
tip = [k for k in w.blocks if k[1] == ymax]
chk("塔尖在塔樓中心（%s，中心 %.1f,%.1f）" % (tip, cx, cz),
    all(abs(x + .5 - cx) <= 1 and abs(z + .5 - cz) <= 1 for x, _, z in tip))
chk("塔尖在 OSM 的塔尖位置附近（way/615183623 約 4782,1374）",
    abs(cx - 4782.2) < 1.5 and abs(cz - 1373.8) < 1.5)


def south_extent(yy, du=10.0):
    """塔樓往南（局部 +v）最遠有方塊的距離。量在中心線東邊 10 m：正中有如意、古錢凸出來。"""
    best = None
    for k in range(0, 120):
        d = k * 0.5
        x, z = a.fr.cell(du, d)
        if solid(w.blocks.get((x, g0 + yy, z))):
            best = d
    return best


prof = {yy: south_extent(yy) for yy in range(120, 400)}
# 每斗的頂：輪廓的局部最大值，而且往上四列之內縮回 3 m 以上（斗與斗之間是三格的玻璃斜頂）
drops = [yy for yy in range(122, 393) if None not in (prof[yy - 1], prof[yy], prof[yy + 1], prof[yy + 4])
         and prof[yy] > prof[yy + 1] and prof[yy] >= prof[yy - 1] and prof[yy] - prof[yy + 4] >= 3]
chk("八斗：27 樓以上每斗頂往內收一次、91 樓再收一次，共 8 次（在 %s）" % drops, len(drops) == 8)
flare = [prof[d] - prof[d - 25] for d in drops[:7]]
chk("每一斗往外斜：斗頂比 25 列之下寬 2～4 m（%s）" % flare, all(2 <= f <= 4.5 for f in flare))
base0 = T1.tower_mass(a.F, 0)
e0 = float(a.F.S[base0].max())
e40 = south_extent(40)
waist = south_extent(123)
chk("地面的平面半邊長 %.1f m（OSM 塔樓輪廓 54 m 見方；正中開間多凸 1 m）" % e0, 27 <= e0 <= 28.6)
chk("基座往內收：40 m 高處半邊長 %.1f m" % e40, 25 <= e40 <= e0)
chk("腰身（第一斗底）半邊長 %.1f m（約 45.9 m 見方）" % waist, 21 <= waist <= 23.5)
top_floor = [k for k in w.blocks if k[1] == g0 + T1.OBS_ROW]
chk("89 樓樓板在一樓 +%d（382 m）" % T1.OBS_ROW, T1.OBS_ROW == 382 and len(top_floor) > 1500)
sp = {s.key: s for s in a.spots()}
chk("傳送點：預設、lobby、top", sorted(sp) == ["", "lobby", "top"])
chk("top 在 89 樓（腳在 +383）", sp["top"].y == g0 + 383)
gold = [k for k, v in w.blocks.items() if v == "minecraft:gold_block" and 378 <= k[1] - g0 <= 388]
chk("阻尼器：89 樓的金色鋼球（%d 格，直徑 5.5 m 約 87 格）" % len(gold), 60 <= len(gold) <= 120)
cmds = {tuple(v): w.sign_meta[k]["command"] for k, v in w.signs.items()}
ns = config.DATAPACK_NS
lob = [c for l, c in cmds.items() if l[0].startswith("89 樓觀景台")]
back = [c for l, c in cmds.items() if l[0].startswith("回 1 樓")]
chk("大廳的告示牌傳送到 89 樓：%s" % lob, lob == ["function %s:%s" % (ns, kit.sight_fn("taipei101", "top"))])
chk("觀景台的告示牌傳送回大廳：%s" % back, back == ["function %s:%s" % (ns, kit.sight_fn("taipei101", "lobby"))])
lsign = [k for k, v in w.signs.items() if v[0].startswith("89 樓觀景台")][0]
tsign = [k for k, v in w.signs.items() if v[0].startswith("回 1 樓")][0]
chk("大廳告示牌在一樓（y%d）、觀景台告示牌在 89 樓（y%d）" % (lsign[1], tsign[1]),
    lsign[1] == g0 + 1 and tsign[1] == g0 + 383)
chk("告示牌是發光的淡橡木牌", all(w.sign_meta[k]["wood"] == "pale_oak" and w.sign_meta[k]["glow"]
                            for k in (lsign, tsign)))
doors = [k for k, v in w.blocks.items() if "door" in v and "half=lower" in v]
chk("一樓有門（南、東各兩扇：%d）" % len(doors), len(doors) == 4 and all(k[1] == g0 + 1 for k in doors))
d0 = sp[""]
dist = math.hypot(d0.x - cx, d0.z - cz)
chk("預設觀景點離塔 %.0f m，塔尖的仰角 %.0f°（要框得進 70° 的畫面）" % (
    dist, math.degrees(math.atan2(508, dist))), math.degrees(math.atan2(508, dist)) < 69)
mall = shapes.poly_cells(a._ring(T1.MALL))
roof = sum(1 for x, z in mall if any(solid(w.blocks.get((x, g0 + yy, z))) for yy in range(26, 44)))
chk("購物中心（OSM 輪廓 %d 格）有 %.0f%% 蓋到 30 m 上下" % (len(mall), 100.0 * roof / len(mall)),
    roof >= 0.9 * len(mall))
common(a, w)

print("\n禁區")
kx, kz = a.fr.cell(0.0, 20.0)
a2, w2, _, dropped = build("taipei101", keep=lambda x, y, z: (x, z) == (kx, kz))
chk("禁區那一根柱子一格都沒寫（擋掉 %d 格）" % dropped,
    dropped > 0 and not any((x, z) == (kx, kz) for x, _, z in w2.blocks))

# ================================================================ 新光摩天大樓
print("\n新光摩天大樓")
s, w, dt, _ = build("shin_kong_tower")
g0 = s.g0
ys = [k[1] for k in w.blocks]
chk("蓋一次 %.1f s" % dt, dt < 30)
chk("最高點 y%d = 一樓 + %d（天線 244.15 m）" % (max(ys), max(ys) - g0), max(ys) == g0 + 244)
colmax = {}
for (x, y, z), b in w.blocks.items():
    if solid(b) and not b.startswith(SK.LEDGE.split("[")[0]):   # 細挑簷會伸出去蓋住低一階的轉角
        if y > colmax.get((x, z), -999):
            colmax[(x, z)] = y
main = shapes.poly_cells(s.part_ring(SK.MAIN))
cov = sum(1 for c in main if colmax.get(c, -999) >= g0 + 3)
chk("主輪廓（%d 格）%.0f%% 頂上有高過地面 3 格的東西" % (len(main), 100.0 * cov / len(main)),
    cov >= 0.95 * len(main))
corner = shapes.poly_cells(s.part_ring("way/644774199"))     # 44 層（187.36 m）那一角
tops = sorted({colmax.get(c, -999) - g0 for c in corner})
chk("鋸齒轉角：44 層那一角的頂在 186～187（%s）" % tops, tops and all(185 <= t <= 187 for t in tops))
corner = shapes.poly_cells(s.part_ring("way/644774198"))     # 46 層（195.68 m）那一角
tops = sorted({colmax.get(c, -999) - g0 for c in corner})
chk("鋸齒轉角：46 層那一角的頂在 194～195（%s）" % tops, tops and all(193 <= t <= 195 for t in tops))
body = shapes.poly_cells(s.part_ring(SK.TOWER_BODY))
tb = [colmax.get(c, -999) - g0 for c in body]
chk("塔身（50 層、211.04 m）：輪廓裡八成以上的柱子頂在 210 m 以上（%d/%d）" % (
    sum(1 for t in tb if t >= 210), len(tb)), sum(1 for t in tb if t >= 210) >= 0.8 * len(tb))
ymax = max(ys)
top = [v for k, v in w.blocks.items() if k[1] == ymax]
chk("頂上是角錐加尖頂（%s）" % top, top == ["minecraft:lightning_rod[facing=up,powered=false]"])
pyr = sum(1 for k, v in w.blocks.items() if v == SK.PYRAMID)
chk("角錐 %d 格" % pyr, pyr > 100)
doors = [k for k, v in w.blocks.items() if "door" in v and "half=lower" in v]
chk("北面門廳有兩扇門（%s）" % doors, len(doors) == 2 and all(k[1] == g0 + 1 for k in doors)
    and all(k[2] < 0 for k in doors))
common(s, w)

print("\n登錄表")
reg = AT.registry()
chk("taipei101 -> Taipei101、shin_kong_tower -> ShinKongTower",
    reg.get("taipei101") is T1.Taipei101 and reg.get("shin_kong_tower") is SK.ShinKongTower)

print("\n" + ("全部通過" if ok else "有測試失敗"))
sys.exit(0 if ok else 1)
