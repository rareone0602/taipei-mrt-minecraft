#!/usr/bin/env python3
"""圓山大飯店（The Grand Hotel）：劍潭山腰、面向基隆河的十四層宮殿式大樓。

公開的事實（只取數字與形制，文字與圖片都沒有抄進來）：
  · 主樓 1973 年 10 月 10 日落成，建築師楊卓成；高 87 m、14 層，曾是全台最高的建築
    （1973–1981）—— 維基百科「圓山大飯店」、英文維基 Grand Hotel (Taipei)
  · 「紅柱金瓦」：丹朱大圓柱、金黃色琉璃瓦；飛簷斗拱承托出簷 —— 圓山大飯店官網
    （about.aspx）、臺北市政府英文網站 The Grand Hotel 條目
  · 屋頂是歇山式 —— 維基百科。照片上看得出是重簷：大樓頂上一圈腰簷（下簷），
    退進一層白石欄杆的迴廊之後才是歇山頂；兩端的山花是紅底金邊，正脊兩端有吻獸
  · 正面：通貫十二層的紅柱，每層一道白色的陽台板邊與紅色欄杆，內退的客房外牆；
    正中是兩重簷的門廊（車子開得到門口），前面兩座大台階夾著花園，往下接前庭廣場
    （Wikimedia Commons 的正面照：Grand Hotel Taipei front view 20141015 等）

位置、方位、平面：OSM way/25202548「主樓」（building:levels=14）。輪廓的主軸 21°（東偏南），
長 110 m、深 56 m，南面正中凸出 41 m × 17 m 的門廊 —— 這裡從輪廓自動量出來，
不寫死。立面的高度分配（照片比例，下簷約在 49 m、上簷約在 63 m）：

   y = g0 + 0     一樓（大廳、門廊車道）
          4..40  二～十一樓，每層 4 m：白色陽台板、紅欄杆、內退的客房牆；紅柱通到 43
          44..47 十二樓：柱頭的額枋，斗拱三跳、一跳比一跳外挑
          48..53 腰簷（下簷）起翹，簷口外挑 6.5 m
          53..62 十三、十四樓：白石欄杆迴廊、退縮的上層牆、斗拱
          63..84 歇山頂（上簷外挑 5 m），正脊 85，吻獸頂到 87

基地（劍潭山的南坡，DEM 在輪廓內高低差 7 m）：一樓樓板取輪廓內地面的中位數；
上層平台（g0）＝主樓外擴 6 m 加門廊前的車道；兩座大台階與兩側坡道往下 5 m 到
前庭廣場；廣場前緣接一條順著地形往下的車道。比地面高的填石、邊緣砌灰色擋土牆
（照片上的灰色花崗石牆），比地面低的削平、削出來的坡面也砌擋土牆；落差 2 m 以上
的邊緣立白石欄杆。

後棟（OSM relation/10098399）：主樓後面沿著坡往上的長樓。照片上是紅柱、青綠額枋、
紅瓦的四層樓；這裡每 24 m 切一段、各段樓板取自己那一段地面的中位數，一階一階往上。
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions.kit import (AIR, Attraction, Frame, Painter, Spot,
                                            dilate, erode, principal_angle, ring)

# ---- 材質 ----
TILE = "minecraft:raw_gold_block"           # 金黃琉璃瓦
RIDGE = "minecraft:gold_block"              # 屋脊、垂脊
GOLD = "minecraft:gold_block"               # 吻獸、博風、匾額
RED = "minecraft:red_concrete"              # 丹朱圓柱、山花
RAIL = "minecraft:polished_cinnabar_wall"   # 陽台的紅欄杆（一根根的柱頭，看得穿）
BEAM = "minecraft:warped_planks"            # 額枋（青綠彩畫）
BRACKET = ("minecraft:dark_prismarine", "minecraft:prismarine_bricks")   # 斗拱（青、綠相間）
SOFFIT = "minecraft:dark_prismarine"        # 簷下
BAND = "minecraft:smooth_quartz"            # 陽台板邊（白）
WALL = "minecraft:white_terracotta"         # 內退的客房外牆
GLASS = "minecraft:gray_stained_glass"      # 客房落地窗
LOBBY_GLASS = "minecraft:light_gray_stained_glass"
FLOOR = "minecraft:smooth_stone"            # 各層樓板
LOBBY_FLOOR = "minecraft:polished_diorite"  # 大廳石材地坪
CARPET = "minecraft:red_carpet"
LIGHT = "minecraft:ochre_froglight"         # 陽台與門廊的暖色燈
MARBLE = "minecraft:smooth_quartz"          # 白石欄杆（迴廊）
BALUSTER = "minecraft:diorite_wall"         # 白石欄杆（平台、台階兩側）
STONE = "minecraft:stone"
RETAIN = "minecraft:stone_bricks"           # 擋土牆（灰色花崗石）
PAVE = "minecraft:smooth_stone"             # 平台與廣場鋪面
PAVE_SLAB = "minecraft:smooth_stone_slab[type=bottom]"
ROAD = "minecraft:gray_concrete"            # 前庭車道
STAIR = "minecraft:polished_diorite_stairs[facing=%s,half=bottom]"
GRASS = "minecraft:grass_block"
FLOWERS = ("minecraft:poppy", "minecraft:red_tulip", "minecraft:oxeye_daisy", "minecraft:poppy")
LION = "minecraft:polished_blackstone"      # 門前石獅（照片上是深色石獅）
LION_BASE = "minecraft:polished_andesite"
WATER = "minecraft:water"
LAMP_POST = "minecraft:polished_blackstone_wall"
LANTERN = "minecraft:lantern"
PINE_LOG = "minecraft:spruce_log"
PINE_LEAVES = "minecraft:spruce_leaves[persistent=true]"
REAR_ROOF = "minecraft:red_terracotta"      # 後棟（麒麟廳一帶）的紅瓦
REAR_GLASS = "minecraft:light_gray_stained_glass"

# ---- 立面尺寸（公尺 = 格，從一樓樓板 g0 起算）----
STOREY = 4                  # 每層 4 m
BAL_FLOORS = range(1, 11)   # 二～十一樓有陽台（樓板在 4..40）；十二樓是柱頭、額枋與斗拱
COL_TOP = 43                # 紅柱頂
BEAM_Y = 44                 # 額枋
EAVE1 = 48                  # 腰簷簷口
EAVE1_OUT = 6.5             # 腰簷外挑
GALLERY = 53                # 十三樓迴廊樓板（= 腰簷的上緣）
EAVE2 = 63                  # 上簷（歇山頂）簷口
EAVE2_OUT = 5.0
ROOF_RISE = 21.0            # 簷口到正脊
TOP = 87                    # 吻獸頂 = 公開資料的 87 m
N_LONG, N_SHORT = 20, 11    # 長邊、短邊各幾根大柱（正面照數得到二十根，轉角成對）

# ---- 基地（局部 v 從主樓前緣 B 往前量）----
TERRACE_M = 6               # 主樓四周的平台寬
FRONT_UP = 26               # 門廊前的上層平台伸到前緣外 26 m
STAIR_RUN = 5               # 台階 5 階、每階 1 m，往下 5 m
DROP = 5                    # 上層平台到前庭廣場的落差
RAMP_RUN = 20               # 兩側坡道 1:4
PLAZA_END = 84              # 前庭廣場到前緣外 84 m
DRIVE_END = 150             # 車道順著地形伸到前緣外 150 m

# ---- 後棟（relation/10098399）：主樓後面沿著山坡往上的長樓 ----
REAR = "relation/10098399"
REAR_SEG = 24               # 每 24 m 一段、各自一個樓板高度，順著坡一階一階往上
REAR_H = 16                 # 四層、每層 4 m
REAR_ROOF_MAX = 5.0


def _local(poly, cx, cz, ang):
    c, s = math.cos(ang), math.sin(ang)
    return [((x - cx) * c + (z - cz) * s, -(x - cx) * s + (z - cz) * c) for x, z in poly]


def _spans(loc, v):
    """局部多邊形被 v = 常數的掃描線切出來的區間 [(u0, u1)]。"""
    xs = []
    n = len(loc)
    for i in range(n):
        (u1, v1), (u2, v2) = loc[i], loc[(i + 1) % n]
        if (v1 <= v < v2) or (v2 <= v < v1):
            xs.append(u1 + (v - v1) * (u2 - u1) / (v2 - v1))
    xs.sort()
    return [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]


def body_geometry(poly):
    """從 OSM 主樓輪廓量出：主體矩形（中心、方位、半長 A、半深 B）與正面凸出的門廊。

    方位取輪廓主軸；u 沿長邊，v 朝南（飯店面向基隆河）。主體前後緣是「掃描線覆蓋
    全長七成以上」最外側的那兩條（前緣上凸出的門廊、轉角的小凸角都不算主體）；
    門廊是前緣外 3 m 那條掃描線上、落在主體中段的區間。"""
    cx = sum(p[0] for p in poly) / len(poly)
    cz = sum(p[1] for p in poly) / len(poly)
    ang = principal_angle(poly)
    best = None
    for a in (ang, ang + math.pi / 2):
        loc = _local(poly, cx, cz, a)
        us = [p[0] for p in loc]
        if best is None or max(us) - min(us) > best[1]:
            best = (a, max(us) - min(us))
    ang = best[0]
    if math.cos(ang) < 0:                       # +v 朝南（世界 +z）
        ang += math.pi
    loc = _local(poly, cx, cz, ang)
    us, vs = [p[0] for p in loc], [p[1] for p in loc]
    u0, u1 = min(us), max(us)
    L = u1 - u0

    def cover(v):
        return sum(b - a for a, b in _spans(loc, v))

    step = 0.25
    vb = min(vs)
    while vb < max(vs) and cover(vb + 1e-3) < 0.7 * L:
        vb += step
    vf = max(vs)
    while vf > vb and cover(vf - 1e-3) < 0.7 * L:
        vf -= step
    A, B = L / 2, (vf - vb) / 2
    uc, vc = (u0 + u1) / 2, (vb + vf) / 2
    mid = [(a, b) for a, b in _spans(loc, vf + 3) if a > u0 + 0.2 * L and b < u1 - 0.2 * L]
    if mid:
        pa, pb = min(a for a, b in mid), max(b for a, b in mid)
        pd = max(vs) - vf
    else:                                       # 輪廓上沒有門廊：照片的比例
        pa, pb, pd = uc - 0.19 * L, uc + 0.19 * L, 16.0
    c, s = math.cos(ang), math.sin(ang)
    wx, wz = cx + uc * c - vc * s, cz + uc * s + vc * c
    return dict(cx=wx, cz=wz, ang=ang, A=A, B=B,
                upc=(pa + pb) / 2 - uc, ap=(pb - pa) / 2, pd=max(8.0, min(24.0, pd)))


def _lift(fr, a, b, lift, corner=None, du=0.0, dv=0.0):
    """翼角起翹的高度場：kit.hip 給 rise=0 就只剩起翹那一項。"""
    return kit.hip(fr, a, b, 0.0, lift=lift, corner=corner, du=du, dv=dv)


def _skirt(fr, a, b, width, rise, profile=1.6, lift=0.0, corner=None, du=0.0, dv=0.0):
    """一圈腰簷的高度場：簷口（|u|=a 或 |v|=b）為 0，往內 width 處到 rise。"""
    d = np.minimum(a - np.abs(fr.U - du), b - np.abs(fr.V - dv)).clip(0, None)
    return rise * (d / width).clip(0, 1) ** profile + _lift(fr, a, b, lift, corner, du, dv)


def _pattern(fr, period=3.0):
    """沿立面的位置編號：斗拱一朵一朵青綠相間。長邊用 u、短邊用 v。"""
    return (np.floor(fr.U / period) + np.floor(fr.V / period)).astype(int) % 2


class GrandHotel(Attraction):
    height_m = 87.0
    margin = 12
    # 劍潭山在主樓北邊還有三、四百公尺才下到平地：真實地形給到 bbox 外 240 m，
    # 否則背後的山在後棟後面就被削成一道往 y64 的斜坡
    terrain_margin = 240
    MAIN = "way/25202548"

    # ---------------------------------------------------------------- 規劃
    def _main_poly(self):
        f = self.feature(self.MAIN)
        if f and f.get("outer"):
            return max(f["outer"], key=len)
        return None

    def plan(self, site):
        poly = self._main_poly()
        if poly is None:                        # 沒有主樓輪廓：以景點中心、照片比例蓋
            cx, cz = self.center()
            geo = dict(cx=cx, cz=cz, ang=math.radians(21), A=55.0, B=28.0, upc=0.0, ap=20.5, pd=16.5)
        else:
            geo = body_geometry(poly)
        self.geo = geo
        A, B = geo["A"], geo["B"]
        self.A, self.B = A, B
        self.fr = fr = Frame(geo["cx"], geo["cz"], geo["ang"], B + DRIVE_END + 4)
        self.body = fr.box(A, B)
        self.g0 = site.level(fr, self.body)
        self._plan_rear(site)
        self._plan_site(site)
        self.site = site

        # 觀景點：前庭廣場的中軸上，離正面 72 m，看大樓腰部
        g0 = self.g0
        vx, vz = fr.cell(0.0, B + 72.0)
        vy = g0 - DROP + 1
        tx, tz = fr.world(0.0, 0.0)
        yaw, pitch = kit.look(vx, vy, vz, tx, g0 + 40, tz)
        # 迴廊：十三樓正面中央的白石欄杆後面，往南看基隆河與市區
        gx, gz = fr.cell(0.0, B - 2.6)
        self._spots = [
            Spot("", vx, vy, vz, yaw, pitch, self.name_zh, self.name_en),
            Spot("terrace", gx, g0 + GALLERY + 1, gz, round(fr.yaw(0, 1), 1), 12.0,
                 "十三樓迴廊", "13F gallery"),
        ]

    def _plan_rear(self, site):
        """後棟：OSM relation/10098399 的每個外環。沿長軸每 REAR_SEG 公尺切一段，
        每段的樓板取那一段地面的中位數 —— 樓順著劍潭山的坡一階一階往上。
        照片（Kirin Hall Front、從東南遠看的那幾張）：紅柱、青綠額枋、玻璃窗、紅瓦。"""
        self.rear = []
        self.rear_cells = self.fr.empty()
        f = self.feature(REAR)
        if not f:
            return
        for r in f.get("outer", []):
            if len(r) < 4:
                continue
            xs, zs = [p[0] for p in r], [p[1] for p in r]
            cx, cz = sum(xs) / len(xs), sum(zs) / len(zs)
            ang = principal_angle(r)
            loc = _local(r, cx, cz, ang)
            if max(p[1] for p in loc) - min(p[1] for p in loc) > max(p[0] for p in loc) - min(p[0] for p in loc):
                ang += math.pi / 2
            ext = max(max(xs) - min(xs), max(zs) - min(zs)) / 2 + 4
            fr = Frame(cx, cz, ang, ext)
            m = fr.polygon(r)
            # 跟主樓重疊的格子讓給主樓
            for x, z in fr.cells(m):
                u, v = self.fr.local(x, z)
                if abs(u) <= self.A + 1 and abs(v) <= self.B + 1:
                    m[z - fr.z0, x - fr.x0] = False
            if m.sum() < 100:
                continue
            u0 = float(fr.U[m].min())
            k = np.floor((fr.U - u0) / REAR_SEG).astype(int)
            G = site.grid(fr, dilate(m, 2))
            for kk in sorted(set(k[m].tolist())):
                seg = m & (k == kk)
                if seg.sum() < 30:
                    continue
                L = int(np.round(np.median(G[seg])))
                self.rear.append((fr, seg, L, G))
                for x, z in fr.cells(seg):
                    i, j = z - self.fr.z0, x - self.fr.x0
                    if 0 <= i < self.fr.shape[0] and 0 <= j < self.fr.shape[1]:
                        self.rear_cells[i, j] = True

    def _plan_site(self, site):
        """平台、台階、坡道、前庭廣場、車道：每格的鋪面高度（浮點數）與種類。"""
        fr, A, B, g0 = self.fr, self.A, self.B, self.g0
        U, V = fr.U, fr.V
        F = B                                                   # 主樓前緣
        up = fr.box(A + TERRACE_M, B + TERRACE_M) | fr.rect(-35, 35, F - 1, F + FRONT_UP)
        sv = V - (F + FRONT_UP)                                 # 從上層平台前緣往前量
        in_st = (sv >= 0) & (sv < STAIR_RUN)
        stairs = in_st & (np.abs(U) >= 8) & (np.abs(U) <= 23)
        garden = in_st & (np.abs(U) < 8)
        ramps = (sv >= 0) & (sv < RAMP_RUN) & (np.abs(U) > 23) & (np.abs(U) <= 35)
        plaza = fr.rect(-42, 42, F + FRONT_UP, F + PLAZA_END) & ~(stairs | garden | ramps)
        drive = fr.rect(-5, 5, F + PLAZA_END, F + DRIVE_END) & ~plaza
        up &= ~(stairs | garden | ramps | plaza | drive) & ~(self.rear_cells & ~self.body)

        Lv = np.full(fr.shape, np.nan)
        kind = np.zeros(fr.shape, dtype=np.int8)
        Lv[up], kind[up] = g0, 1
        step = np.floor(sv).clip(0, STAIR_RUN - 1)
        Lv[stairs], kind[stairs] = (g0 - step)[stairs], 3
        Lv[garden], kind[garden] = (g0 - step)[garden], 2
        Lv[ramps], kind[ramps] = (g0 - DROP * (sv / RAMP_RUN))[ramps], 4
        Lv[plaza], kind[plaza] = g0 - DROP, 1
        # 車道：廣場前緣（g0-5）線性接到車道盡頭的地面
        ex, ez = fr.cell(0.0, F + DRIVE_END)
        g_end = site.g(ex, ez)
        t = ((V - (F + PLAZA_END)) / (DRIVE_END - PLAZA_END)).clip(0, 1)
        Lv[drive], kind[drive] = ((g0 - DROP) * (1 - t) + g_end * t)[drive], 5
        # 前庭花園（橢圓，中央噴水池）與環繞的車道
        cx_, cv_ = 0.0, F + 50.0
        e = ((U - cx_) / 13.0) ** 2 + ((V - cv_) / 8.0) ** 2
        self.garden_oval = plaza & (e <= 1.0)
        self.loop_road = plaza & (e > 1.0) & (((U - cx_) / 19.0) ** 2 + ((V - cv_) / 13.0) ** 2 <= 1.0)
        self.fountain = (0.0, cv_)
        self.stairs, self.garden = stairs, garden
        self.Lv, self.kind = Lv, kind
        zone = ~np.isnan(Lv)
        self.G = site.grid(fr, dilate(zone, 2))

    # ---------------------------------------------------------------- 蓋
    def build(self, w):
        p = Painter(w, self.fr)
        self._site(w)
        self._rear(w)
        self._body(p)
        self._lower_eave(p)
        self._upper(p)
        self._roof(p)
        self._portico(p, w)
        self._front(p, w)

    # ---- 整地：平台、擋土牆、欄杆 ----
    def _site(self, w):
        fr, G, Lv, kind = self.fr, self.G, self.Lv, self.kind
        zone = ~np.isnan(Lv)
        Li = np.where(zone, np.floor(Lv + 1e-6), -9999).astype(int)
        half = zone & (kind == 4) & ((Lv - np.floor(Lv + 1e-6)) >= 0.5)
        # 每格的地表（平台上是鋪面、平台外是地面），四鄰裡最低的那一個決定這格是不是露出來的邊
        S = np.where(zone, Li, G).astype(float)
        S[~zone & (G == -999)] = np.inf
        P = np.pad(S, 1, constant_values=np.inf)
        nmin = np.minimum.reduce([P[:-2, 1:-1], P[2:, 1:-1], P[1:-1, :-2], P[1:-1, 2:]])
        facing = kit.cardinal(*fr.dir(0, -1))
        st = STAIR % facing
        s = w.set
        X, Z = fr.X, fr.Z
        for i, j in zip(*np.nonzero(zone)):
            x, z = int(X[i, j]), int(Z[i, j])
            L, gy, k = int(Li[i, j]), int(G[i, j]), int(kind[i, j])
            edge = nmin[i, j] < L
            for y in range(gy + 1, L):
                s(x, y, z, RETAIN if edge else STONE)
            s(x, L, z, {1: PAVE, 2: GRASS, 3: st, 4: PAVE, 5: ROAD}.get(k, PAVE))
            top = L
            if half[i, j]:
                s(x, L + 1, z, PAVE_SLAB)
                top = L + 1
            for y in range(top + 1, max(gy, top) + 2):
                s(x, y, z, AIR)
            # 白石欄杆：落差 2 m 以上的邊（台階本身與樓梯口不立）
            if k in (1, 4, 5) and L - nmin[i, j] >= 2:
                s(x, top + 1, z, BALUSTER)
        # 削坡的那一側：平台外、地面比相鄰平台高的格子砌擋土牆
        Lz = np.where(zone, Li, 99999).astype(float)
        P = np.pad(Lz, 1, constant_values=99999)
        lnb = np.minimum.reduce([P[:-2, 1:-1], P[2:, 1:-1], P[1:-1, :-2], P[1:-1, 2:]])
        cut = ~zone & (lnb < 99999) & (G != -999) & (G > lnb)
        for i, j in zip(*np.nonzero(cut)):
            x, z = int(X[i, j]), int(Z[i, j])
            for y in range(int(lnb[i, j]) + 1, int(G[i, j]) + 1):
                s(x, y, z, RETAIN)

    # ---- 後棟：一段一段順著坡往上的四層樓 ----
    def _rear(self, w):
        s = w.set
        for fr, seg, L, G in self.rear:
            p = Painter(w, fr)
            edge = ring(seg)
            X, Z = fr.X, fr.Z
            # 地基：低於樓板的填到地面、邊上砌擋土牆；高於樓板的（上坡那頭）挖掉
            for i, j in zip(*np.nonzero(seg)):
                x, z, gy = int(X[i, j]), int(Z[i, j]), int(G[i, j])
                for y in range(gy + 1, L):
                    s(x, y, z, RETAIN if edge[i, j] else STONE)
                for y in range(L + 1, gy + 1):
                    s(x, y, z, AIR)
            p.layer(seg, L, FLOOR)
            inner = erode(seg, 1)
            for k in range(1, REAR_H // STOREY):
                p.layer(inner, L + STOREY * k, FLOOR)
            # 外牆：每層頂上一道青綠額枋，紅柱每 4 格一根，其餘是窗
            for i, j in zip(*np.nonzero(edge)):
                x, z = int(X[i, j]), int(Z[i, j])
                col = (x + z) % 4 == 0
                for y in range(1, REAR_H + 1):
                    r = y % STOREY
                    blk = BEAM if r == 0 else (RED if col else (REAR_GLASS if r in (1, 2) else WALL))
                    s(x, L + y, z, blk)
            # 屋頂：外挑 1 m 的四坡（依離外緣的深度起坡），紅瓦、簷下青綠
            rm = dilate(seg, 1)
            d = kit.depth(rm).astype(float)
            h = np.minimum((d - 1) * 0.6, REAR_ROOF_MAX)
            p.heightfield(rm, L + REAR_H + 1, h, REAR_ROOF, under=SOFFIT, shell=2)

    # ---- 主樓：陽台、紅柱、內退的客房牆、樓板 ----
    def _columns(self, a, b, inset):
        pts = []
        for i in range(N_LONG):
            u = -(a - inset) + i * 2 * (a - inset) / (N_LONG - 1)
            pts += [(u, b - inset), (u, -(b - inset))]
        for j in range(1, N_SHORT - 1):
            v = -(b - inset) + j * 2 * (b - inset) / (N_SHORT - 1)
            pts += [(a - inset, v), (-(a - inset), v)]
        return pts

    def _body(self, p):
        fr, A, B, g0 = self.fr, self.A, self.B, self.g0
        body = self.body
        bal = body & ~erode(body, 2)
        outer = ring(body)
        inner = erode(body, 3)
        # 一樓：大廳（石材地坪）、柱廊後面的玻璃牆，正面中央開門
        p.layer(body, g0, LOBBY_FLOOR)
        p.walls(erode(body, 2), g0 + 1, g0 + 3, RED, window=LOBBY_GLASS, every=4, sill=0, head=0)
        door = fr.rect(-3.2, 3.2, B - 4, B + 1)
        p.clear(door & bal | door & ring(erode(body, 2)), g0 + 1, g0 + 3)
        p.layer(fr.rect(-1.2, 1.2, -B + 4, B - 1) & inner, g0 + 1, CARPET)
        # 二～十一樓：白色陽台板、紅欄杆（一根根的柱頭）、內退的客房牆
        lamp = ring(erode(body, 1)) & (np.abs(np.mod(fr.U + fr.V, 5.7) - 2.85) < 0.5)
        for k in BAL_FLOORS:
            yf = g0 + STOREY * k
            p.layer(bal, yf, BAND)
            p.layer(outer, yf + 1, RAIL)
            p.walls(erode(body, 2), yf + 1, yf + 3, WALL, window=GLASS, every=4, sill=0, head=0)
            p.layer(inner, yf, FLOOR)
            p.layer(lamp, yf + STOREY, LIGHT)        # 陽台天花的暖色燈（埋在上一層樓板裡）
        # 十二樓：柱頭上的額枋，斗拱三跳、一跳比一跳外挑；後面是內退的牆
        y12 = g0 + STOREY * BAL_FLOORS[-1] + STOREY
        p.layer(bal, y12, BAND)
        p.walls(erode(body, 2), y12 + 1, g0 + GALLERY - 1, WALL, window=GLASS, every=4, sill=1, head=1, storey=4)
        p.layer(inner, y12, FLOOR)
        p.layer(inner, g0 + EAVE1, FLOOR)
        p.layer(outer, g0 + BEAM_Y, BEAM)
        pat = _pattern(fr)
        for k, y in enumerate(range(g0 + BEAM_Y + 1, g0 + EAVE1)):
            m = fr.box(A + 0.4 + 1.1 * k, B + 0.4 + 1.1 * k) & ~erode(body, 1)
            p.layer(m & (pat == 0), y, BRACKET[0])
            p.layer(m & (pat == 1), y, BRACKET[1])
        # 大柱：一樓地坪通到額枋底下，柱頭一圈金
        cols = self._columns(A, B, 1.0)
        p.columns(cols, 0.75, g0 + 1, g0 + COL_TOP, RED)
        p.columns(cols, 0.75, g0 + COL_TOP, g0 + COL_TOP, GOLD)

    # ---- 腰簷（下簷）----
    def _lower_eave(self, p):
        fr, A, B, g0 = self.fr, self.A, self.B, self.g0
        a1, b1 = A + EAVE1_OUT, B + EAVE1_OUT
        width = EAVE1_OUT + 1.5
        mask = fr.box(a1, b1) & ~fr.box(A - 1.5, B - 1.5)
        h = _skirt(fr, a1, b1, width, GALLERY - EAVE1, profile=1.6, lift=2.0, corner=10.0)
        p.heightfield(mask, g0 + EAVE1, h, TILE, under=SOFFIT, shell=2)
        # 垂脊：四個角的對角線
        diag = mask & (np.abs((a1 - np.abs(fr.U)) - (b1 - np.abs(fr.V))) < 0.7)
        top = np.floor(g0 + EAVE1 + h).astype(int)
        p.fill(diag, top + 1, top + 1, RIDGE)

    # ---- 十三、十四樓：白石欄杆迴廊、退縮的上層牆、斗拱 ----
    def _upper(self, p):
        fr, A, B, g0 = self.fr, self.A, self.B, self.g0
        inside = fr.box(A - 1.5, B - 1.5)
        p.layer(inside, g0 + GALLERY, FLOOR)
        p.layer(ring(inside), g0 + GALLERY + 1, MARBLE)
        core = fr.box(A - 4, B - 4)
        p.walls(core, g0 + 54, g0 + 57, WALL, window=GLASS, every=3, sill=0, head=0)
        p.columns(self._columns(A - 3, B - 3, 1.0), 0.7, g0 + 54, g0 + 57, RED)
        p.layer(ring(core), g0 + 58, BEAM)
        pat = _pattern(fr)
        for k, y in enumerate(range(g0 + 59, g0 + EAVE2)):
            out = -3.0 + 1.6 * (k + 1)                  # 一層比一層外挑
            m = fr.box(A + out, B + out) & ~fr.box(A - 5, B - 5)
            p.layer(m & (pat == 0), y, BRACKET[0])
            p.layer(m & (pat == 1), y, BRACKET[1])

    # ---- 上簷：重簷歇山頂 ----
    def _roof(self, p):
        fr, A, B, g0 = self.fr, self.A, self.B, self.g0
        a2, b2 = A + EAVE2_OUT, B + EAVE2_OUT
        gin = 0.45 * b2                                   # 山花離端點多遠
        base = g0 + EAVE2
        h = kit.hip_gable(fr, a2, b2, ROOF_RISE, gin, profile=1.5, lift=2.6, corner=0.3 * b2)
        mask = fr.box(a2, b2)
        p.heightfield(mask, base, h, TILE, under=SOFFIT, shell=2)
        U, V = np.abs(fr.U), np.abs(fr.V)
        top = np.floor(base + h).astype(int)
        # 山花：歇山兩端豎起來的三角形牆面，紅底、斜邊金色博風
        gplane = a2 - gin
        he = ROOF_RISE * ((a2 - U) / b2).clip(0, 1) ** 1.5
        band = mask & (U <= gplane) & (U > gplane - 1.3)
        p.fill(band, np.floor(base + he).astype(int), top - 1, RED)
        p.fill(band, top, top, GOLD)
        # 懸魚：山花正中一塊金
        p.fill(band & (V < 1.0), top - 4, top - 2, GOLD)
        # 垂脊：歇山兩端小坡的對角線
        diag = mask & (U > gplane) & (np.abs((a2 - U) - (b2 - V)) < 0.7)
        p.fill(diag, top + 1, top + 1, RIDGE)
        # 正脊與吻獸
        ridge = mask & (V < 0.9) & (U <= gplane)
        p.fill(ridge, top + 1, base + int(ROOF_RISE) + 1, RIDGE)
        for sgn in (1, -1):
            end = mask & (V < 0.9) & (np.abs(fr.U - sgn * (gplane - 0.5)) < 0.9)
            p.fill(end, base + int(ROOF_RISE) + 1, g0 + TOP, GOLD)
            curl = mask & (V < 0.9) & (np.abs(fr.U - sgn * (gplane - 2.0)) < 0.7)
            p.fill(curl, g0 + TOP - 1, g0 + TOP - 1, GOLD)

    # ---- 門廊：兩重簷、紅柱、金色匾額 ----
    def _portico(self, p, w):
        fr, A, B, g0 = self.fr, self.A, self.B, self.g0
        geo = self.geo
        upc, ap, pd = geo["upc"], geo["ap"], geo["pd"]
        vc, dh = B + pd / 2, pd / 2
        box = fr.box(ap, dh, du=upc, dv=vc)
        keep = fr.V >= B - 1.8                            # 屋頂不伸進主樓的陽台以內
        front_v = B + pd - 1.2
        pts = [(upc + ap * t, front_v) for t in (-0.93, -0.56, -0.19, 0.19, 0.56, 0.93)]
        pts += [(upc + sg * ap * 0.93, B + pd * 0.45) for sg in (1, -1)]
        p.columns(pts, 1.0, g0 + 1, g0 + 7, RED)
        p.layer(ring(box) & keep, g0 + 8, BEAM)
        ceil = erode(box, 1)
        p.layer(ceil, g0 + 8, BEAM)
        p.layer(ceil & (_pattern(fr, 4.0) == 0) & (np.abs(np.mod(fr.U, 4.0) - 2.0) < 0.6)
                & (np.abs(np.mod(fr.V, 4.0) - 2.0) < 0.6), g0 + 8, LIGHT)
        # 下簷
        a1, b1 = ap + 2.5, dh + 2.5
        m1 = fr.box(a1, b1, du=upc, dv=vc) & ~fr.box(ap - 1, dh - 1, du=upc, dv=vc) & keep
        h1 = _skirt(fr, a1, b1, 3.5, 1.6, profile=1.3, lift=0.9, corner=4.0, du=upc, dv=vc)
        p.heightfield(m1, g0 + 9, h1, TILE, under=SOFFIT, shell=2)
        # 額：紅底，正面中央金匾
        fz = ring(fr.box(ap - 1, dh - 1, du=upc, dv=vc)) & keep
        p.fill(fz, g0 + 10, g0 + 12, RED)
        plaque = fz & (fr.V > vc + dh - 2.5) & (np.abs(fr.U - upc) <= 5.5)
        p.layer(plaque, g0 + 11, GOLD)
        # 上簷歇山
        a2, b2 = ap + 1.5, dh + 1.5
        base = g0 + 13
        h2 = kit.hip_gable(fr, a2, b2, 4.0, 0.5 * b2, profile=1.3, lift=1.1, du=upc, dv=vc)
        m2 = fr.box(a2, b2, du=upc, dv=vc) & keep
        p.heightfield(m2, base, h2, TILE, under=SOFFIT, shell=2)
        U, V = np.abs(fr.U - upc), np.abs(fr.V - vc)
        top = np.floor(base + h2).astype(int)
        gplane = a2 - 0.5 * b2
        he = 4.0 * ((a2 - U) / b2).clip(0, 1) ** 1.3
        band = m2 & (U <= gplane) & (U > gplane - 1.3)
        p.fill(band, np.floor(base + he).astype(int), top - 1, RED)
        p.fill(band, top, top, GOLD)
        ridge = m2 & (V < 0.9) & (U <= gplane)
        p.fill(ridge, top + 1, top + 1, RIDGE)
        for sg in (1, -1):
            end = m2 & (V < 0.9) & (np.abs(fr.U - upc - sg * (gplane - 0.5)) < 0.9)
            p.fill(end, top + 1, top + 2, GOLD)
        # 匾額上的字：壁掛告示牌貼在金匾正前方那一格，面向前庭
        fx, fz_ = _vec(fr.facing(0, 1))
        sx, sz = fr.cell(upc, vc + dh - 1.2)
        w.sign(sx + fx, g0 + 11, sz + fz_, ["圓山大飯店", "The Grand Hotel", "", ""],
               facing=(fx, fz_), wood="dark_oak", kind="wall", glow=True, color="yellow")

    # ---- 前庭：花園、噴水池、石獅 ----
    def _front(self, p, w):
        fr, B, g0 = self.fr, self.B, self.g0
        y = g0 - DROP
        # 環繞花園的車道
        p.layer(self.loop_road, y, ROAD)
        # 花園：草地上一圈一圈的花
        p.layer(self.garden_oval, y, GRASS)
        U, V = fr.U, fr.V
        cu, cv = self.fountain
        e = np.sqrt(((U - cu) / 13.0) ** 2 + ((V - cv) / 8.0) ** 2)
        for k, blk in enumerate(FLOWERS):
            m = self.garden_oval & (np.abs(e - (0.38 + 0.17 * k)) < 0.05 + 0.02 * k) & (e > 0.3)
            p.layer(m, y + 1, blk)
        basin = self.garden_oval & (e <= 0.28)
        p.layer(basin, y, LION_BASE)
        p.layer(basin & (e <= 0.2), y, WATER)
        p.layer(ring(basin), y + 1, BALUSTER)
        # 台階中間的花坡：每一階種一排花
        for i, j in zip(*np.nonzero(self.garden)):
            L = int(np.floor(self.Lv[i, j] + 1e-6))
            if (int(fr.X[i, j]) + int(fr.Z[i, j])) % 2 == 0:
                w.set(int(fr.X[i, j]), L + 1, int(fr.Z[i, j]), FLOWERS[(i + j) % len(FLOWERS)])
        # 石獅：前庭前緣、中軸兩側，面向來車
        for sg in (1, -1):
            lu, lv = sg * 9.0, B + 66.0
            base = fr.box(1.6, 1.6, du=lu, dv=lv)
            p.fill(base, y + 1, y + 1, LION_BASE)
            body = fr.box(1.0, 1.4, du=lu, dv=lv)
            p.fill(body, y + 2, y + 3, LION)
            head = fr.box(0.9, 0.7, du=lu, dv=lv + 0.8)
            p.fill(head, y + 4, y + 4, LION)
        # 廣場兩側的花圃（草地鑲一圈紅花）
        U, V = fr.U, fr.V
        for sg in (1, -1):
            bed = fr.rect(24, 38, B + 38, B + 74) if sg > 0 else fr.rect(-38, -24, B + 38, B + 74)
            p.layer(bed, y, GRASS)
            p.layer(ring(bed), y + 1, FLOWERS[0])
            p.layer(erode(bed, 3) & (np.abs(np.mod(V, 6.0) - 3.0) < 0.5), y + 1, FLOWERS[2])
        # 路燈：環繞花園的車道外緣、台階兩側
        lamps = [(sg * 21.0, B + 50.0 + dv) for sg in (1, -1) for dv in (-10.0, 0.0, 10.0)]
        lamps += [(sg * 23.5, B + FRONT_UP + 7.0) for sg in (1, -1)]
        for lu, lv in lamps:
            x, z = fr.cell(lu, lv)
            for yy in range(y + 1, y + 5):
                w.set(x, yy, z, LAMP_POST)
            w.set(x, y + 5, z, LANTERN)
        # 主樓兩側的南洋杉（照片上立面兩側那幾棵高瘦的針葉樹）
        for sg in (1, -1):
            for dv in (-12.0, 8.0, B + 3.0 - 8.0):
                self._pine(w, fr.cell(sg * (self.A + 3.5), dv), g0 + 1, 14 + int(abs(dv)) % 4)

    @staticmethod
    def _pine(w, xz, y0, h):
        """一棵高瘦的針葉樹：雲杉幹，葉子一層一層往上收（persistent 才不會掉光）。"""
        x, z = xz
        for y in range(y0, y0 + h):
            w.set(x, y, z, PINE_LOG)
        for k, y in enumerate(range(y0 + 3, y0 + h + 1)):
            r = 2 if (h - k) > 4 and k % 2 == 0 else 1
            for dx in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    if (dx or dz) and abs(dx) + abs(dz) <= r + (1 if r == 2 else 0):
                        w.set(x + dx, y, z + dz, PINE_LEAVES)
        w.set(x, y0 + h, z, PINE_LEAVES)
        w.set(x, y0 + h + 1, z, PINE_LEAVES)

    # ---------------------------------------------------------------- 說明牌
    def plaque(self):
        return [self.name_zh, self.name_en, "1973 年落成 高 87 m 14 層", "重簷歇山 紅柱金瓦"]


def _vec(name):
    return {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}[name]


BUILDS = {"grand_hotel": GrandHotel}
