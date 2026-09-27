#!/usr/bin/env python3
"""國父紀念館（1972，王大閎設計）。

位置、方向、輪廓（OSM，data/attractions.json）：
  way/189788192   主體（height 30、roof:shape mansard、roof:height 10、roof:colour gold）；
                  輪廓就是屋簷的滴水線：每邊約 102.6 m，四角的翼角尖往外斜伸 3 m，
                  南面正中凸出 6.5 m 的是抬高的正門門廊。整棟偏北 1.65°
  way/1305268840  中央平屋頂（±25.8 m）      way/1305268839/37/38  東西北三面的斜屋面
  way/1305268835  正門門廊（|u| <= 17.5）    way/1305268833/34/36  門廊兩側與後方的屋面
  正門朝南（仁愛路那側；地址是仁愛路四段 505 號）。

長相（公開資料：維基百科「國立國父紀念館」、國父紀念館官網「古蹟之美」；
照片只拿來量比例）：
  · 高 29.6～30.4 m；平面正方形、每邊 100 m；鋼骨鋼筋混凝土
  · 仿唐風的黃色大屋頂，四角的飛簷高高翹起（取「人」字的筆意），中央是平屋頂、
    四周四坡洩水；正面屋面整片抬高往上掀起，形成高聳的門廊
  · 每邊 14 根灰色大柱，柱與樑的邊角切 135°；外牆是清水磚外包赭紅色鋼磚；
    四周是有美人靠欄杆的迴廊；門寬與門高 1:4
  · 大廳正中是孫中山坐姿銅像（陳一帆作，本體 5.8 m、連座 8.9 m）
比例（正面照，以總高 30 m 換算）：簷口最低約 13 m、四角翼尖約 19.5 m、
斜屋面與平屋頂交界約 26 m、門廊頂 30 m。
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions import palace_kit as PK
from mrt.application.attractions.kit import Attraction, Frame, Painter, Spot

MAIN = "way/189788192"

B = "minecraft:"
TILE = B + "honeycomb_block"                 # 黃色琉璃瓦（照片上偏橘金）
HIP = B + "light_gray_concrete"              # 灰色的垂脊與簷口封邊
SOFFIT = B + "gray_concrete"                 # 簷下（照片上是深灰）
COLUMN = B + "smooth_stone"                  # 灰色大柱、門廊
BEAM = B + "light_gray_concrete"
WALL = B + "red_terracotta"                  # 赭紅色鋼磚
FLAT = B + "packed_mud"                      # 中央平屋頂（照片上是褐色）
BASE = B + "smooth_stone"
STEP = B + "smooth_stone_slab[type=bottom]"
GLASS = B + "gray_stained_glass"
PAVE = B + "smooth_stone"
PAVE2 = B + "polished_andesite"
GRASS = B + "grass_block[snowy=false]"
FILL = B + "stone"
LAMP = B + "sea_lantern"
BRONZE = B + "waxed_copper_block"
BRONZE2 = B + "waxed_exposed_copper"
PLINTH = B + "polished_granite"

E = 51.4          # 簷口滴水線的半邊長
F = 25.8          # 中央平屋頂的半邊長
C = 47.0          # 柱列
W = 43.0          # 外牆（柱與牆之間是迴廊）
PU = 17.5         # 門廊半寬
PV0, PV1 = 38.4, 57.6    # 門廊的進深（OSM）
E_MIN, E_CORNER, RIDGE, PORCH = 13.0, 19.5, 26.0, 29.5


def eave_height(s, front):
    """簷口高度（離地公尺）：s 是沿簷口離中線的距離。中段平、往四角翹到 19.5 m；
    正面在門廊兩側再往上掀到門廊頂。"""
    k = ((s - 22.0) / (E - 22.0)).clip(0, None)
    e = E_MIN + (E_CORNER - E_MIN) * k ** 2.2
    if front:
        t = (1.0 - (s - PU) / 13.0).clip(0, 1)
        e = np.maximum(e, E_MIN + (PORCH - E_MIN) * t ** 2.2)
    return e


class SunYatSenMemorial(Attraction):
    height_m = 30.0
    margin = 12

    def __init__(self, item):
        super().__init__(item)
        ring = self.outline()
        self.theta = PK.fine_angle(ring)
        c = PK.ring_centroid(ring)
        f0 = Frame(c[0], c[1], self.theta, 1)
        pts = [f0.local(x - 0.5, z - 0.5) for x, z in ring]
        us = [p[0] for p in pts]
        tips = [p[1] for p in pts if abs(p[0]) > 30]          # 四角翼尖（門廊不算）
        uc, vc = (min(us) + max(us)) / 2.0, (min(tips) + max(tips)) / 2.0
        self.c = f0.world(uc, vc)

    def bbox(self):
        fr = Frame(self.c[0], self.c[1], self.theta, 1)
        pts = [fr.world(u, v) for u in (-70, 70) for v in (-66, 130)]
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        return (int(math.floor(min(xs))), int(math.floor(min(zs))),
                int(math.ceil(max(xs))), int(math.ceil(max(zs))))

    def plan(self, site):
        # 框：原點在建築中心；v 往南（正面）。範圍含正面廣場
        self.fr = Frame(self.c[0], self.c[1], self.theta, 132)
        fr = self.fr
        U, V = fr.U, fr.V
        self.level = (np.abs(U) <= 68) & (V >= -64) & (V <= 128)
        sample = self.level & (fr.X % 4 == 0) & (fr.Z % 4 == 0) & (np.abs(U) <= 60) & (V <= 60)
        gs = [site.g(x, z) for x, z in zip(fr.X[sample].tolist(), fr.Z[sample].tolist())]
        self.G = int(np.round(np.median(gs))) if gs else 64
        self.g0 = self.G
        self.gnd = site.grid(fr, self.level)
        G = self.G
        spots = []
        for key, u, v, y, tu, tv, ty, zh, en in (
                ("", 0.0, 112.0, G + 1, 0.0, 0.0, G + 15, self.name_zh, self.name_en),
                ("hall", 6.0, 36.0, G + 2, 0.0, 26.0, G + 7, "國父銅像", "Statue of Dr. Sun Yat-sen")):
            x, z = fr.cell(u, v)
            tx, tz = fr.world(tu, tv)
            yaw, pitch = kit.look(x, y, z, tx, ty, tz)
            spots.append(Spot(key, x, y, z, yaw, pitch, zh, en))
        self._spots = spots

    def plaque(self):
        return [self.name_zh, self.name_en, "1972 年落成，王大閎設計",
                "每邊 14 根灰柱、黃色大屋頂"]

    # ---- 蓋 ----
    def build(self, w):
        fr, G = self.fr, self.G
        p = Painter(w, fr)
        U, V = fr.U, fr.V
        aU, aV = np.abs(U), np.abs(V)
        A = np.maximum(aU, aV)
        porch = (aU <= PU) & (V > PV0 - 0.5) & (V <= PV1)

        # ---- 整地與廣場：正面（南）一大片廣場，建築四周一圈步道
        plaza = (aU <= 62) & (V > E) & (V <= 126)
        walk = (A <= E + 7)
        paved = plaza | walk
        grid = ((np.floor(U) % 6) == 0) | ((np.floor(V) % 6) == 0)
        lv = self.level
        X, Z = fr.X[lv].tolist(), fr.Z[lv].tolist()
        s = p.set
        for x, z, gy, pv, gr in zip(X, Z, self.gnd[lv].tolist(), paved[lv].tolist(), grid[lv].tolist()):
            if gy < G:
                for y in range(max(gy + 1, G - 8), G):
                    s(x, y, z, FILL)
            elif gy > G:
                for y in range(G + 1, min(gy, G + 12) + 1):
                    s(x, y, z, kit.AIR)
            s(x, G, z, (PAVE2 if gr else PAVE) if pv else GRASS)

        # ---- 台基（1 m）與四周的一階
        plat = (A <= E - 1.9) | ((aU <= PU) & (V <= PV1))
        p.layer(plat, G + 1, BASE)
        p.layer(kit.dilate(plat, 1) & ~plat, G + 1, STEP)

        # ---- 外牆（赭紅）與室內
        wall = A <= W
        p.walls(wall, G + 2, G + 12, WALL)
        p.layer(kit.erode(wall, 1), G + 13, BEAM)                 # 室內天花
        lamps = kit.erode(wall, 2) & ((np.floor(U) % 7) == 0) & ((np.floor(V) % 7) == 0)
        p.layer(lamps, G + 13, LAMP)
        # 正門：門廊後方整片玻璃（瘦高的門窗，1:4），三個門洞
        facade = (aU <= PU - 2) & (V > W - 1) & (V <= W)
        p.fill(facade, G + 2, G + 12, GLASS)
        mull = facade & ((np.floor(U) % 4) == 0)
        p.fill(mull, G + 2, G + 12, COLUMN)
        doors = facade & ((aU <= 1.5) | ((aU >= 5.0) & (aU <= 7.0)))
        p.fill(doors, G + 2, G + 5, kit.AIR)
        # 門廊裡面的高牆（玻璃上方到門廊頂）
        p.fill((aU <= PU - 1) & (V > W - 1) & (V <= W), G + 13, G + 26, WALL)
        # 國父銅像：面向正門，座高 3 m
        pl = (aU <= 4.0) & (np.abs(V - 25.0) <= 4.0)
        p.fill(pl, G + 2, G + 4, PLINTH)
        PK.seated_statue(p, 0.0, 25.0, G + 5, (0.0, 1.0), BRONZE, BRONZE2)

        # ---- 柱：每邊 14 根（正面是兩邊各 5 根 + 門廊 4 根），切角方柱
        pts = []
        side = np.linspace(-C, C, 14)
        for t in side:
            pts += [(t, -C), (-C, t), (C, t)]
        for t in (21.8, 28.1, 34.4, 40.7):
            pts += [(t, C), (-t, C)]
        p.columns(pts, 1.0, G + 2, G + 12, COLUMN)
        p.columns([(-6.6, 55.5), (6.6, 55.5)], 1.0, G + 2, G + 26, COLUMN)
        # 門廊兩側的大柱（連到頂上的翼牆）
        post = (np.abs(aU - 15.8) <= 1.2) & (V >= 53.0) & (V <= PV1)
        p.fill(post, G + 2, G + 26, COLUMN)
        # 柱頂的樑：一圈灰色
        beam = (A <= C + 1.0) & ~(A <= C - 1.0) & ~porch
        p.layer(beam, G + 12, BEAM)

        # ---- 大屋頂：四坡的斜屋面（簷口曲線見 eave_height），中央平屋頂
        roofm = fr.polygon(self.outline()) & ~porch & ~(A <= F - 0.5)
        front = (aV >= aU) & (V > 0)
        ns = aV >= aU
        s_ = np.where(ns, aU, aV)
        d = np.where(ns, E - aV, E - aU).clip(0, None)
        e = np.where(front, eave_height(s_, True), eave_height(s_, False))
        t = (d / (E - F)).clip(0, 1) ** 1.4
        h = e + (RIDGE - e) * t
        hips = np.abs(aU - aV) <= 0.7
        T = PK.roof(p, roofm, G, h, TILE, shell=2, under=SOFFIT, rim=HIP, rim_under=HIP,
                    ridge=HIP, ridge_mask=hips & roofm & ~kit.ring(roofm), cap_ridge=False)
        flat = A <= F - 0.5
        p.layer(flat, G + 25, FLAT)
        p.layer(flat & ~kit.erode(flat, 1), G + 26, HIP)
        # 外牆一路砌到屋面底下（四角的屋簷翹得高，牆頂與屋面之間不能留縫）
        wr = kit.ring(wall) & roofm
        p.fill(wr, G + 13, np.where(wr, T - 3, 0), WALL)

        # ---- 門廊：灰色的門框、頂樑、兩側翼牆，頂上一片往後斜下的屋面
        topb = (aU <= PU) & (V >= 53.0) & (V <= PV1)
        p.fill(topb, G + 27, G + 29, BEAM)
        fin = (aU > PU - 1.2) & (aU <= PU) & (V > PV0 - 0.5) & (V <= PV1)
        fin_top = G + 26 + np.rint(3.0 * ((V - PV0) / (PV1 - PV0)).clip(0, 1)).astype(int)
        p.fill(fin, G + 13, fin_top, COLUMN)
        p.layer(fin & (V > PV1 - 1.5), G + 30, COLUMN)             # 翼牆前端往上翹
        slope = (aU <= PU - 1.2) & (V > F - 0.5) & (V < 53.0)
        hs = 26.0 + 3.0 * ((V - F) / (53.0 - F)).clip(0, 1)
        PK.roof(p, slope, G, hs, TILE, shell=1, under=SOFFIT)
        # 門廊的天花（簷下）
        p.layer((aU <= PU - 1.2) & (V > W) & (V < 53.0), G + 26, SOFFIT)
        # 匾：「國父紀念館」（黑底金字）
        x, z = fr.cell(0.0, PV1 + 0.6)
        p.fill((aU <= 3.5) & (V > PV1 - 1) & (V <= PV1), G + 27, G + 28, B + "black_concrete")
        fx, fz = fr.dir(0.0, 1.0)
        w.sign(x, G + 28, z, ["", "國父紀念館", "", ""], facing=(fx, fz), kind="wall",
               wood="dark_oak", glow=True, color="#E8C060")


BUILDS = {"sun_yat_sen_memorial": SunYatSenMemorial}
