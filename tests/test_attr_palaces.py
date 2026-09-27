#!/usr/bin/env python3
"""中正紀念堂園區與國父紀念館（application/attractions/cks_memorial.py、sun_yat_sen.py、
palace_kit.py）：蓋進 DictSink（平地 y66），從方塊讀回來驗公開資料的幾個數字。

  · 紀念堂：最高點離地 70 m、八角形的屋頂、方形的堂身、正面半階梯 14 m（28 階）、
    正門高 16 m、大廳裡有銅像（坐姿約 6 m）
  · 自由廣場牌樓：五個門洞、高約 30 m
  · 兩廳院：黃瓦、紅柱、正脊 37 m；音樂廳（歇山）有山花、戲劇院（廡殿）沒有
  · 國父紀念館：高 30 m、四角翼尖比簷口中段高、每邊 14 根柱、門廊最高
  · 傳送點站得住、預設觀景點面向建築、說明牌第一行是景點中文名；禁區照樣擋得住
  · palace_kit：細角度、推山廡殿的正脊沿 u、八角垂脊、屋頂殼會補陡坎

用法: ./.venv/bin/python tests/test_attr_palaces.py
"""
import math
import os
import re
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.application import attractions as AT
from mrt.application.attractions import kit
from mrt.application.attractions import palace_kit as PK
from mrt.application.attractions.cks_memorial import CksMemorial, GATE_PILLARS
from mrt.application.attractions.sun_yat_sen import SunYatSenMemorial
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True
GY = 66


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def base(b):
    return b.split("[")[0]


def build(aid, keep=None):
    items = [i for i in AT.load_items() if i["id"] == aid]
    a = AT.for_world([], items=items)[0]
    a.plan(kit.Site(lambda x, z: GY))
    w = DictSink()
    t = time.time()
    dropped = AT.build(a, w, keep)
    return a, w, time.time() - t, dropped


BLOCK_RE = re.compile(r"^minecraft:([a-z0-9_]+)(\[[a-z_]+=[a-z0-9_]+(,[a-z_]+=[a-z0-9_]+)*\])?$")
JAR = os.path.expanduser("~/Library/Application Support/minecraft/versions/26.2/26.2.jar")


def jar_blocks():
    """裝好的 26.2 jar 裡的方塊 id（blockstates/*.json）；沒裝遊戲回 None（只驗格式）。"""
    if not os.path.exists(JAR):
        return None
    with zipfile.ZipFile(JAR) as z:
        return {n.rsplit("/", 1)[1][:-5] for n in z.namelist()
                if n.startswith("assets/minecraft/blockstates/") and n.endswith(".json")}


KNOWN = jar_blocks()


def check_ids(w, label):
    names = set(w.blocks.values())
    bad = [n for n in names if not BLOCK_RE.match(n)]
    chk("%s：方塊字串格式正確（%d 種%s）" % (label, len(names), "" if not bad else "，錯的：%s" % bad[:3]),
        not bad)
    if KNOWN is not None:
        unknown = sorted({BLOCK_RE.match(n).group(1) for n in names if BLOCK_RE.match(n)} - KNOWN)
        chk("%s：每種方塊都在 26.2 的 jar 裡%s" % (label, "" if not unknown else "（沒有：%s）" % unknown),
            not unknown)


def get_fn(w):
    return lambda x, y, z: w.get(x, y, z)


def column_top(w, x, z, y0=GY, y1=GY + 90):
    top = None
    for y in range(y0, y1):
        if base(w.get(x, y, z)) != "minecraft:air":
            top = y
    return top


# ---------------------------------------------------------------- palace_kit
print("palace_kit")
ring = [(0, 0), (100 * math.cos(math.radians(1.65)), 100 * math.sin(math.radians(1.65))),
        (100 * math.cos(math.radians(1.65)) - 50 * math.sin(math.radians(1.65)),
         100 * math.sin(math.radians(1.65)) + 50 * math.cos(math.radians(1.65))),
        (-50 * math.sin(math.radians(1.65)), 50 * math.cos(math.radians(1.65)))]
chk("fine_angle：偏 1.65° 的矩形量出 %.2f°" % math.degrees(PK.fine_angle(ring)),
    abs(math.degrees(PK.fine_angle(ring)) - 1.65) < 0.01)
fr = kit.Frame(0, 0, 0.0, 50)
h, rm = PK.hip_ridge(fr, 30, 40, 10, 20)
ridge_line = fr.box(19, 0.6)
chk("推山廡殿：進深比面寬大，正脊仍沿 u（|u|<=19 的中線都是最高）",
    float(h[ridge_line].min()) >= float(h[fr.box(30, 40)].max()) - 1e-6)
chk("推山廡殿：屋脊遮罩含正脊與四條垂脊", bool(rm[ridge_line].all()) and bool(rm[fr.box(0.6, 0.6, du=25, dv=20)].any()))
ho, hips = PK.octagon(fr, 20, 12)
hm = hips & fr.ngon(8, 18) & (np.hypot(fr.U, fr.V) > 4)
angs = np.degrees(np.arctan2(fr.V[hm], fr.U[hm])) % 45
chk("八角攢尖：垂脊在 22.5° + k·45°（八個頂點方向）", bool(np.all(np.abs(angs - 22.5) < 8)))
w = DictSink()
p = kit.Painter(w, kit.Frame(0.5, 0.5, 0.0, 6))
hstep = np.where(p.fr.U > 0, 8.0, 2.0)
PK.roof(p, p.fr.box(4, 4), 70, hstep, "minecraft:stone", shell=1)
x, z = p.fr.cell(0.7, 0.0)
col = [y for y in range(70, 80) if w.get(x, y, z) != "minecraft:air"]
chk("屋頂殼：陡坎那一排往下補到跟低的一側接起來（%s）" % col, col == list(range(73, 79)))

# ---------------------------------------------------------------- 中正紀念堂
print("\n中正紀念堂")
a, w, dt, _ = build("cks_memorial")
chk("登錄表：cks_memorial -> CksMemorial", AT.registry().get("cks_memorial") is CksMemorial)
chk("蓋一次 %.1f s（每個 region 呼叫一次，要遠低於一分鐘）" % dt, dt < 20)
G = a.G
ys = [k[1] for k in w.blocks]
chk("最高點離地 %d m（公開資料 70 m）" % (max(ys) - G), max(ys) - G == 70)
fh = a.fh


def local_cells(frame, pred, y):
    """某一層符合條件的方塊 -> 局部座標 (u, v) 陣列。"""
    pts = [(x, z) for (x, yy, z), b in w.blocks.items() if yy == y and pred(b)]
    return np.array([frame.local(x, z) for x, z in pts]) if pts else np.zeros((0, 2))


blue = local_cells(fh, lambda b: base(b) in ("minecraft:blue_concrete", "minecraft:blue_glazed_terracotta"), G + 55)
near = blue[np.hypot(blue[:, 0], blue[:, 1]) < 40] if len(blue) else blue
ext = [float((near[:, 0] * math.cos(k * math.pi / 4) + near[:, 1] * math.sin(k * math.pi / 4)).max())
       for k in range(8)] if len(near) else [0]
chk("上層屋頂是八角形：八個邊的法線方向最遠距離 %.1f～%.1f m（差 1.5 m 以內）" % (min(ext), max(ext)),
    len(near) > 50 and max(ext) - min(ext) <= 1.5)
wall = local_cells(fh, lambda b: base(b) == "minecraft:smooth_quartz", G + 30)
wall = wall[np.maximum(np.abs(wall[:, 0]), np.abs(wall[:, 1])) < 30]
chk("堂身是方形：y+30 那層的半寬 u %.1f、v %.1f（OSM 24.5，四角的墩下寬上窄）"
    % (np.abs(wall[:, 0]).max(), np.abs(wall[:, 1]).max()),
    abs(np.abs(wall[:, 0]).max() - np.abs(wall[:, 1]).max()) <= 1.0 and 24 <= np.abs(wall[:, 0]).max() <= 27)
# 正面大階梯：沿 v=12 那條線從廣場走上去，站立面每一階升 0.5 m
heights = []
for uu in np.arange(-88.0, -36.0, 0.5):
    x, z = fh.cell(uu, 12.0)
    t = column_top(w, x, z)
    b = w.get(x, t, z)
    heights.append((t - G) + (0.5 if base(b).endswith("_slab") else 1.0) - 1.0)
steps_ = sorted(set(heights))
chk("正面大階梯：站立面 0 -> 14 m，每階 0.5 m（%d 種高度）" % len(steps_),
    steps_[0] == 0 and steps_[-1] == 14 and all(abs(b_ - a_ - 0.5) < 1e-6 for a_, b_ in zip(steps_, steps_[1:])))
x, z = fh.cell(-80.0, 0.0)
chk("御路（階梯正中）是白色", base(w.get(x, column_top(w, x, z), z)).startswith("minecraft:smooth_quartz"))
x, z = fh.cell(-22.0, 0.0)
door = []
for y in range(G + 15, G + 40):
    if w.get(x, y, z) != "minecraft:air":
        break
    door.append(y - G)
chk("正門：門洞從台基面 %d 到 %d（高 %d m，公開資料 16 m）" % (door[0], door[-1], len(door)),
    door[0] == 15 and len(door) == 16 and base(w.get(x, G + 14, z)) != "minecraft:air")
bronze = [k for k, b in w.blocks.items() if base(b) in ("minecraft:waxed_copper_block", "minecraft:waxed_exposed_copper")
          and fh.local(k[0], k[2])[0] > 5]
by = [k[1] for k in bronze]
chk("大廳銅像：%d 格銅，坐姿高 %d m（公開資料 6.3 m），坐在 3 m 的座上"
    % (len(bronze), max(by) - min(by) + 1), len(bronze) > 50 and 5 <= max(by) - min(by) + 1 <= 7
    and min(by) == G + 18)
lamps = [k for k, b in w.blocks.items() if base(b) == "minecraft:sea_lantern"
         and max(abs(fh.local(k[0], k[2])[0]), abs(fh.local(k[0], k[2])[1])) < 21]
chk("大廳有燈（%d 盞）" % len(lamps), len(lamps) >= 20)

# 牌樓
fg = a.fg
runs, cur = 0, False
for uu in np.arange(-GATE_PILLARS[2], GATE_PILLARS[2], 0.25):
    x, z = fg.cell(uu, 0.0)
    open_ = w.get(x, G + 5, z) == "minecraft:air"
    if open_ and not cur:
        runs += 1
    cur = open_
chk("自由廣場牌樓：沿面寬在 y+5 數到 %d 個門洞（五間）" % runs, runs == 5)
gate_top = max(k[1] for k in w.blocks if abs(fg.local(k[0], k[2])[0]) < 45 and abs(fg.local(k[0], k[2])[1]) < 12)
chk("牌樓高 %d m（公開資料 30 m）" % (gate_top - G), 29 <= gate_top - G <= 31)
roof_eaves = set()
for sgn in (-1, 1):
    for uu in (0.0, 15.4, 28.0, GATE_PILLARS[0], GATE_PILLARS[1], GATE_PILLARS[2] + 0.6):
        x, z = fg.cell(sgn * uu, 0.0)
        roof_eaves.add((sgn * uu, column_top(w, x, z)))
chk("牌樓十一樓：明樓最高，往兩側遞減（%s）" % sorted(roof_eaves),
    max(roof_eaves, key=lambda t: t[1])[0] == 0.0)

# 兩廳院


def hall_stats(frame):
    tops, blocks = [], set()
    for (x, y, z), b in w.blocks.items():
        u, v = frame.local(x, z)
        if abs(u) <= 52 and abs(v) <= 58:
            blocks.add(base(b))
            if abs(u) < 3 and abs(v) < 2:
                tops.append(y)
    return max(tops) - G, blocks


ht, bt = hall_stats(a.ft)
hc, bc_ = hall_stats(a.fc)
chk("國家戲劇院：正脊 %d m（OSM 37 m）、黃瓦、紅柱" % ht,
    36 <= ht <= 38 and "minecraft:honeycomb_block" in bt and "minecraft:red_concrete" in bt)
chk("國家音樂廳：正脊 %d m、黃瓦、紅柱" % hc,
    36 <= hc <= 38 and "minecraft:honeycomb_block" in bc_ and "minecraft:red_concrete" in bc_)
chk("音樂廳是歇山（有藍色山花），戲劇院是廡殿（沒有）",
    "minecraft:blue_glazed_terracotta" in bc_ and "minecraft:blue_glazed_terracotta" not in bt)

# 傳送點、說明牌
sp = a.spots()
g = get_fn(w)
chk("傳送點 %s，第一個是預設觀景點" % [s.key for s in sp], sp and sp[0].key == "" and len(sp) >= 2)
for s in sp:
    chk("傳送點 %r (%d,%d,%d) 站得住" % (s.key, s.x, s.y, s.z), walk.standable(g, s.x, s.y, s.z))
s0 = sp[0]
want = kit.yaw_of(a.hall_c[0] - s0.x - 0.5, a.hall_c[1] - s0.z - 0.5)
chk("預設觀景點面向紀念堂（偏 %.1f°）" % abs((s0.yaw - want + 180) % 360 - 180),
    abs((s0.yaw - want + 180) % 360 - 180) < 3)
signs = [v for k, v in w.signs.items() if abs(k[0] - s0.x) <= 3 and abs(k[2] - s0.z) <= 3]
chk("觀景點旁的說明牌第一行是「中正紀念堂」", any(v and v[0] == "中正紀念堂" for v in signs))
chk("園區裡沒有一面牌子第一行以「出口」開頭", not any(v and v[0].startswith("出口") for v in w.signs.values()))
chk("沒有用到黃色混凝土（月台警示帶專用）", not any(base(b) == "minecraft:yellow_concrete" for b in w.blocks.values()))
check_ids(w, "中正紀念堂")
# 禁區：一條穿過階梯的禁區，照樣擋得住
kx, kz = fh.cell(-70.0, 0.0)
_, w2, _, dropped = build("cks_memorial", keep=lambda x, y, z: abs(x - kx) <= 2 and abs(z - kz) <= 2)
chk("禁區裡一格都不寫（擋掉 %d 格）" % dropped,
    dropped > 0 and not any(abs(k[0] - kx) <= 2 and abs(k[2] - kz) <= 2 for k in w2.blocks))

# ---------------------------------------------------------------- 國父紀念館
print("\n國父紀念館")
a, w, dt, _ = build("sun_yat_sen_memorial")
chk("登錄表：sun_yat_sen_memorial -> SunYatSenMemorial",
    AT.registry().get("sun_yat_sen_memorial") is SunYatSenMemorial)
G = a.G
fr = a.fr
ys = [k[1] for k in w.blocks]
chk("最高點離地 %d m（公開資料 29.6～30.4 m）" % (max(ys) - G), max(ys) - G == 30)
top = max(w.blocks, key=lambda k: k[1])
tu, tv = fr.local(top[0], top[2])
chk("最高點在正門門廊（u %.1f、v %.1f）" % (tu, tv), abs(tu) <= 18 and tv > 38)
corner = max(column_top(w, *fr.cell(su * 52.0, sv * 52.0)) for su in (-1, 1) for sv in (-1, 1)) - G
mid = column_top(w, *fr.cell(0.0, -51.0)) - G
chk("四角的飛簷翹起：翼尖 %d m、北面簷口中段 %d m" % (corner, mid), corner - mid >= 5 and 12 <= mid <= 15)
cols = 0
cur = False
for uu in np.arange(-52.0, 52.0, 0.25):
    x, z = fr.cell(uu, -47.0)
    c_ = base(w.get(x, G + 6, z)) == "minecraft:smooth_stone"
    if c_ and not cur:
        cols += 1
    cur = c_
chk("北面柱列：%d 根（公開資料每邊 14 根）" % cols, cols == 14)
names = {base(b) for b in w.blocks.values()}
chk("黃色大屋頂、赭紅外牆、中央平屋頂",
    {"minecraft:honeycomb_block", "minecraft:red_terracotta", "minecraft:packed_mud"} <= names)
sp = a.spots()
g = get_fn(w)
for s in sp:
    chk("傳送點 %r (%d,%d,%d) 站得住" % (s.key, s.x, s.y, s.z), walk.standable(g, s.x, s.y, s.z))
s0 = sp[0]
want = kit.yaw_of(a.c[0] - s0.x - 0.5, a.c[1] - s0.z - 0.5)
chk("預設觀景點在正面廣場、面向紀念館（偏 %.1f°）" % abs((s0.yaw - want + 180) % 360 - 180),
    abs((s0.yaw - want + 180) % 360 - 180) < 3 and fr.local(s0.x, s0.z)[1] > 60)
signs = [v for k, v in w.signs.items() if abs(k[0] - s0.x) <= 3 and abs(k[2] - s0.z) <= 3]
chk("觀景點旁的說明牌第一行是「國父紀念館」", any(v and v[0] == "國父紀念館" for v in signs))
chk("沒有用到黃色混凝土", not any(base(b) == "minecraft:yellow_concrete" for b in w.blocks.values()))
check_ids(w, "國父紀念館")

print("\n" + ("全部通過" if ok else "有測試失敗"))
sys.exit(0 if ok else 1)
