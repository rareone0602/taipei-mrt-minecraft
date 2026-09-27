#!/usr/bin/env python3
"""摩天大樓的共用零件（台北101、新光摩天大樓）：逐層遮罩的量體、外殼、樓板燈、門、球、樹。

kit.Painter 的 walls/fill 適合「一段輪廓擠出一段高度」；摩天大樓不是：101 的八節
每一節都往外斜 7°、基座往內收，新光的轉角一層一層退縮。這裡的做法是**逐層**
算遮罩 —— 每個 y 問一次「這一層的樓板長什麼樣」（Frame 上的布林陣列），
外殼就是那一層遮罩的外圈，挑簷的上緣就是「這一層有、上一層沒有」的格子。
斜面每升幾格外圈就挪一格，相鄰兩層的外圈只在斜角相接；shell() 在挪動的地方
把上下兩層的外圈都算進來，外牆才不會漏光。

這個模組只放零件，沒有 BUILDS（景點登錄在 taipei101.py、shin_kong.py）。
"""
import math

import numpy as np

from mrt.application.attractions import kit

AIR = kit.AIR


# ---------------------------------------------------------------- 輪廓與座標

def outline_axes(poly):
    """OSM 輪廓 -> (中心 x, 中心 z, 角度（弧度）, 半長 u, 半寬 v)。

    角度：每條邊的方向乘 4（把互相垂直的邊折到同一個方向）、依邊長加權平均再除 4。
    kit.principal_angle 取整數度，101 的 1.0° 與新光的 −0.6° 都會被捨入；
    這裡要的是小數。中心是轉正之後外接矩形的中心（不是頂點平均：
    有缺角的那幾角頂點比較多，平均會偏）。"""
    sx = sy = 0.0
    n = len(poly)
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        L = math.hypot(x2 - x1, z2 - z1)
        a = 4.0 * math.atan2(z2 - z1, x2 - x1)
        sx += L * math.cos(a)
        sy += L * math.sin(a)
    ang = math.atan2(sy, sx) / 4.0
    c, s = math.cos(ang), math.sin(ang)
    x0 = sum(p[0] for p in poly) / n
    z0 = sum(p[1] for p in poly) / n
    us = [(x - x0) * c + (z - z0) * s for x, z in poly]
    vs = [-(x - x0) * s + (z - z0) * c for x, z in poly]
    mu, mv = (min(us) + max(us)) / 2, (min(vs) + max(vs)) / 2
    return (x0 + mu * c - mv * s, z0 + mu * s + mv * c, ang,
            (max(us) - min(us)) / 2, (max(vs) - min(vs)) / 2)


SNAP_DEG = 1.5          # 偏不到 1.5° 的塔樓轉正（見 snap_angle）


def snap_angle(ang, deg=SNAP_DEG):
    """偏角小於 deg 度就回 0（把塔樓轉正對齊方塊格線），否則原樣回傳。

    101 偏 1.0°、新光偏 −0.6°：半邊長 27 m、23 m 的立面兩端只差 0.5 m、0.3 m，
    跟一格 1 m 的取整誤差同一個量級。不轉正的話，斜面每收一格、直櫺每隔幾格
    都會在立面上畫出一條斜斜的鋸齒線（101 的基座與八斗整面都是）；
    轉正之後收分變成一圈水平的線，跟真的樓層線一樣。位置（中心）照 OSM 不動。"""
    return 0.0 if abs(math.degrees(ang)) <= deg else ang


def rotate_poly(poly, cx, cz, ang):
    """多邊形繞 (cx, cz) 轉 ang 弧度（從 +x 往 +z）。"""
    c, s = math.cos(ang), math.sin(ang)
    return [(cx + (x - cx) * c - (z - cz) * s, cz + (x - cx) * s + (z - cz) * c) for x, z in poly]


def notched_radius(fr, n, du=0.0, dv=0.0):
    """方形平面、四角各有兩階缺角（每階 n 公尺）的「半徑場」R：R <= a 就在半邊長 a 的平面裡。

    101 的轉角不是直角，是兩道內凹的鋸齒（Structure 雜誌：2.5 m 的缺角）。
    令 m = max(|u|, |v|)、s = min(|u|, |v|)：離兩個面各 p = a - |u|、q = a - |v|，
    兩個都小於 2n、其中一個小於 n 的格子被切掉，推回來就是
    R = max(m, min(m + n, s + 2n))。半邊長 a 隨高度變的時候，缺角的大小不變。"""
    u, v = np.abs(fr.U - du), np.abs(fr.V - dv)
    m, s = np.maximum(u, v), np.minimum(u, v)
    return np.maximum(m, np.minimum(m + n, s + 2 * n))


def face_coords(fr, du=0.0, dv=0.0):
    """(t, side)：t 是沿著最近那個立面量的座標（東西面用 v、南北面用 u），
    side 是離中心的距離（max(|u|, |v|)）。立面上的直櫺、壁飾都用它排。"""
    u, v = fr.U - du, fr.V - dv
    ew = np.abs(u) >= np.abs(v)
    return np.where(ew, v, u), np.maximum(np.abs(u), np.abs(v))


# ---------------------------------------------------------------- 寫入

def paint(w, fr, mask, y, block):
    """遮罩裡每一格的 (x, y, z) 設成 block。"""
    s = w.set
    for x, z in zip(fr.X[mask].tolist(), fr.Z[mask].tolist()):
        s(x, y, z, block)


def paint_layers(w, fr, layers, y):
    """[(遮罩, 方塊)] 依序寫：後面的蓋前面的。"""
    for m, b in layers:
        if m is not None and m.any():
            paint(w, fr, m, y, b)


def shell(M, Mp=None, Mn=None):
    """這一層的外殼格：M 的外圈，加上「上下兩層的外圈裡、貼著這一層外圈」的格子。

    斜面上相鄰兩層的外圈會錯開一格，只在斜角相接 —— 從外面看不出來，但光會漏進去、
    人也鑽得過去。把上下層外圈裡跟這層外圈相鄰的格子也算成牆，錯開的地方就是
    兩格厚。退縮很多的地方（裙樓屋頂接塔樓）不相鄰，不會多砌一圈。"""
    rg = kit.ring(M)
    near = kit.dilate(rg, 1)
    out = rg.copy()
    for other in (Mp, Mn):
        if other is not None:
            out |= M & kit.ring(other) & near
    return out


def grid_mask(fr, step, off=0, du=0.0, dv=0.0):
    """局部座標每 step 公尺一格的點陣（樓板燈、樹、柱子）。"""
    return ((np.floor(fr.U - du).astype(int) % step) == off) & \
           ((np.floor(fr.V - dv).astype(int) % step) == off)


def sphere(w, cx, cy, cz, r, block):
    """實心球：中心 (cx, cy, cz) 是浮點數，格心在半徑內就放。"""
    for x in range(int(math.floor(cx - r)), int(math.ceil(cx + r)) + 1):
        for y in range(int(math.floor(cy - r)), int(math.ceil(cy + r)) + 1):
            for z in range(int(math.floor(cz - r)), int(math.ceil(cz + r)) + 1):
                if (x + .5 - cx) ** 2 + (y + .5 - cy) ** 2 + (z + .5 - cz) ** 2 <= r * r:
                    w.set(x, y, z, block)


def door(w, x, y, z, facing, block="minecraft:waxed_copper_door", hinge="left"):
    """一扇門（上下兩格）。facing 是 kit.cardinal 的方位名：人從門外往門裡走時面對的反方向。"""
    st = "[facing=%s,half=%%s,hinge=%s,open=false,powered=false]" % (facing, hinge)
    w.set(x, y, z, block + st % "lower")
    w.set(x, y + 1, z, block + st % "upper")


LEAVES = "minecraft:oak_leaves[distance=1,persistent=true,waterlogged=false]"
LOG = "minecraft:oak_log[axis=y]"


def tree(w, x, gy, z, trunk=4, r=2.6, leaves=LEAVES, log=LOG):
    """行道樹：樹幹 trunk 格、樹冠是半徑 r 的扁球（葉子設成 persistent，不會自己掉光）。"""
    for y in range(gy + 1, gy + trunk + 1):
        w.set(x, y, z, log)
    cy = gy + trunk + 1.0
    ri = int(math.ceil(r))
    for dx in range(-ri, ri + 1):
        for dz in range(-ri, ri + 1):
            for dy in range(-2, 3):
                if (dx * dx + dz * dz) / (r * r) + (dy * dy) / 4.0 <= 1.0 and not (dx == 0 and dz == 0 and dy < 0):
                    w.set(x + dx, int(cy) + dy, z + dz, leaves)


def dome(mask, rise):
    """任意平面上的圓頂高度場：離邊界越遠越高，剖面是四分之一圓（邊上 0、最深處 rise）。"""
    d = kit.depth(mask).astype(float)
    top = d.max() if d.any() else 1.0
    return rise * np.sqrt(np.clip(1.0 - (1.0 - d / top) ** 2, 0.0, 1.0))


def glyph(rows):
    """點陣字串 -> [(列, 行)]（X 是實心；第 0 列在上）。壁飾（如意、古錢）用它畫。"""
    out = []
    for i, row in enumerate(rows):
        for j, ch in enumerate(row):
            if ch == "X":
                out.append((i, j))
    return out
