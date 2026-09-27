#!/usr/bin/env python3
"""艋舺龍山寺：乾隆三年（1738）創建，坐北朝南的三進四合院。

公開資料（zh.wikipedia〈艋舺龍山寺〉；內政部「臺灣宗教文化地圖」；國家文化記憶庫
〈艋舺龍山寺建築佈局〉）：

  · 中軸線由外而內：四柱三間牌樓、廟埕、前殿、中庭、正殿（大殿）、過水、後殿，
    左右護室（護龍），東鐘樓、西鼓樓
  · 廟埕左右各一座飛瀑水池（取代古時寺廟的蓮花池）；鋪花岡石條
  · 前殿正面十一開間：中央三川殿，兩側龍門廳（東，入口）、虎門廳（西，出口）；
    三川門前一對銅鑄龍柱（全臺唯一）；牆以青、白石對比
  · 正殿：歇山重簷、不設門扇的敞堂、藻井；1945 年毀於空襲、1959 年重建
  · 鐘鼓樓：轎頂式重簷屋頂（臺灣首見）
  · 屋脊與飛簷滿是剪黏、交趾陶的龍鳳麒麟，色彩瑰麗；屋脊兩端上揚分叉的燕尾脊

位置與平面：OSM。way/198401479（正殿，21 × 18 m）、way/198401478（後殿與左右護室
連成的ㄇ字形）、way/198401472（前殿，40 × 12 m，OSM 在三川殿兩側各有一個分段點）、
way/198401476（正殿與後殿之間的過水）、way/1462833608（廟埕前的牌樓，OSM 名為「龍門」）。
高度沒有官方數字：照片以正殿連簷寬約 26 m 為尺，下簷約 9 m、上簷約 12 m、正脊約 14 m、
脊上剪黏與寶塔到 16～17 m；前殿與後殿的脊約 10～11.5 m。

局部座標：u 朝東（偏北 5°）、v 朝南（廟的正面），原點在正殿中心。
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions import trad_parts as TP
from mrt.application.attractions.kit import Attraction, Frame, Painter, Spot

AIR = kit.AIR

# ---- 材質 ----
PAVE = "minecraft:polished_andesite"            # 廟埕的花岡石條
PAVE2 = "minecraft:smooth_stone"
PLINTH = "minecraft:stone_bricks"               # 台基
WHITE_STONE = "minecraft:polished_diorite"      # 泉州白石
BLUE_STONE = "minecraft:polished_deepslate"     # 青斗石
CARVED = "minecraft:chiseled_tuff"              # 石雕窗、石雕柱
BRICK = "minecraft:bricks"                      # 護室、後殿的紅磚牆
RED_WOOD = "minecraft:mangrove_planks"          # 木作（額枋、門扇的朱紅）
GOLD = "minecraft:raw_gold_block"               # 貼金的雕刻
BRONZE = "minecraft:waxed_exposed_chiseled_copper"   # 銅鑄龍柱
DRAGON_COL = "minecraft:chiseled_deepslate"     # 正殿的石雕龍柱
PLAIN_COL = "minecraft:polished_andesite"
RIDGE = "minecraft:red_terracotta"              # 屋脊的脊身
RIDGE_TOP = "minecraft:resin_bricks"
SOFFIT = "minecraft:stripped_mangrove_wood"     # 簷下的斗拱與椽子
RAIL = "minecraft:stone_brick_wall"             # 石欄杆
ROCK = ("minecraft:mossy_cobblestone", "minecraft:tuff", "minecraft:stone", "minecraft:mossy_stone_bricks")

# 剪黏的顏色：龍身青綠、腹與頭金黃、點綴藍與紅
JIAN_NIAN = ("minecraft:waxed_oxidized_copper", "minecraft:honeycomb_block",
             "minecraft:light_blue_concrete", "minecraft:lime_concrete")
DRAGON_BODY = "minecraft:waxed_oxidized_copper"
DRAGON_HEAD = "minecraft:honeycomb_block"
DRAGON_FIN = "minecraft:light_blue_concrete"

WATER = "minecraft:water[level=0]"
WATER_FLOW = "minecraft:water[level=1]"
WATER_FALL = "minecraft:water[level=8]"


class LongshanTemple(Attraction):
    """艋舺龍山寺整座寺：廟埕（牌樓、飛瀑水池）、前殿、左右護室與鐘鼓樓、正殿、過水、後殿。"""

    height_m = 17.0
    margin = 14

    # OSM 元素
    MAIN = "way/198401479"
    U_RING = "way/198401478"
    FRONT = "way/198401472"
    LINK = "way/198401476"
    PAILOU = "way/1462833608"

    def __init__(self, item):
        super().__init__(item)
        main = self.feature(self.MAIN)
        ring = max(main["outer"], key=len) if main and main.get("outer") else self.outline()
        self.main_ring = [tuple(p) for p in ring]
        # u 沿正殿的長邊（東西），v 朝南：principal_angle 取到南北那組邊就轉 -90°
        ang = kit.principal_angle(self.main_ring)
        if math.cos(ang) < 0.7:
            ang -= math.pi / 2
        self.ang = ang
        c, s = math.cos(ang), math.sin(ang)
        cx0 = sum(p[0] for p in self.main_ring) / len(self.main_ring)
        cz0 = sum(p[1] for p in self.main_ring) / len(self.main_ring)
        us = [(x - cx0) * c + (z - cz0) * s for x, z in self.main_ring]
        vs = [-(x - cx0) * s + (z - cz0) * c for x, z in self.main_ring]
        um, vm = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
        self.cx, self.cz = cx0 + um * c - vm * s, cz0 + um * s + vm * c
        self.ha, self.hb_ = (max(us) - min(us)) / 2, (max(vs) - min(vs)) / 2   # 正殿半長、半寬
        # 整座寺的範圍（局部座標）：後殿後緣到牌樓前緣
        self.site_uv = (-23.0, 21.0, -31.0, 59.0)

    def _local_extent(self, osm, default):
        """OSM 元素在局部座標的外接矩形 (u0, u1, v0, v1)；資料裡沒有就用 default。"""
        f = self.feature(osm)
        if not f or not f.get("outer"):
            return default
        c, s = math.cos(self.ang), math.sin(self.ang)
        us, vs = [], []
        for r in f["outer"]:
            for x, z in r:
                dx, dz = x - self.cx, z - self.cz
                us.append(dx * c + dz * s)
                vs.append(-dx * s + dz * c)
        return (min(us), max(us), min(vs), max(vs))

    def bbox(self):
        u0, u1, v0, v1 = self.site_uv
        c, s = math.cos(self.ang), math.sin(self.ang)
        pts = [(self.cx + u * c - v * s, self.cz + u * s + v * c) for u in (u0, u1) for v in (v0, v1)]
        m = self.margin
        return (int(math.floor(min(p[0] for p in pts))) - m, int(math.floor(min(p[1] for p in pts))) - m,
                int(math.ceil(max(p[0] for p in pts))) + m, int(math.ceil(max(p[1] for p in pts))) + m)

    def plaque(self):
        return [self.name_zh, self.name_en, "1738 年創建 · 三進", "全臺唯一銅鑄龍柱"]

    # ---- 定案 ----
    def plan(self, site):
        u0, u1, v0, v1 = self.site_uv
        ext = max(abs(u0), abs(u1), abs(v0), abs(v1)) + 6
        self.fr = fr = Frame(self.cx, self.cz, self.ang, ext)
        self.site_mask = fr.rect(u0, u1, v0, v1)
        self.g0 = site.level(fr, fr.rect(u0 + 2, u1 - 2, v0 + 2, v1 - 20))
        self.site = site
        # 整地要查每一格的地面：cli 在 plan 之後就丟掉地形距離場，先查一遍留在 Site 的快取
        site.grid(fr, self.site_mask)
        # 各棟的範圍（局部座標）：OSM 有就照 OSM
        self.main_box = (-self.ha, self.ha, -self.hb_, self.hb_)
        self.front_box = self._local_extent(self.FRONT, (-20.6, 19.2, 25.0, 37.3))
        self.link_box = self._local_extent(self.LINK, (-10.0, 8.8, -15.5, -10.8))
        self.pailou_box = self._local_extent(self.PAILOU, (-8.0, 4.7, 52.4, 56.9))
        ring = self._local_extent(self.U_RING, (-21.6, 19.5, -29.2, 23.1))
        self.rear_box = (ring[0], ring[1], ring[2], -16.0)
        self.wing_w = (ring[0] + 0.4, -13.5, -16.0, self.front_box[2])
        self.wing_e = (10.9, ring[1] - 0.2, -16.0, self.front_box[2])
        g = self.g0
        # 觀景點：廟埕中央看前殿；中庭看正殿
        self._spots = []
        for key, (u, v), (tu, tv, th) in (("", (0.0, 48.0), (0.0, 0.0, 7.0)),
                                           ("courtyard", (0.0, 20.5), (0.0, 0.0, 9.0))):
            x, z = fr.cell(u, v)
            tx, tz = fr.world(tu, tv)
            yaw, pitch = kit.look(x, g + 1, z, tx, g + 1 + th, tz)
            zh = self.name_zh if key == "" else "龍山寺中庭"
            en = self.name_en if key == "" else "Longshan Temple Courtyard"
            self._spots.append(Spot(key, x, g + 1, z, yaw, pitch, zh, en))

    # ---- 蓋 ----
    def build(self, w):
        fr = self.fr
        p = Painter(w, fr)
        g = self.g0
        self.site.prepare(w, fr, self.site_mask, g, top=PAVE)
        # 廟埕與中庭的石條：每 3 m 一道淺色
        strip = (np.floor(fr.V) % 3 == 0) & self.site_mask
        p.layer(strip, g, PAVE2)
        self._plaza(p)
        self._front_hall(p)
        self._wings(p)
        self._main_hall(p)
        self._link(p)
        self._rear_hall(p)
        self._towers(p)
        self._pailou(p)
        self._courtyard(p)
        for s in self._spots:
            x, z = s.x, s.z
            for y in (s.y, s.y + 1, s.y + 2):
                p.set(x, y, z, AIR)
            p.set(x, s.y - 1, z, PAVE)

    # ================================================================ 共用：一段硬山屋頂的殿
    def _box(self, u0, u1, v0, v1):
        return self.fr.rect(u0, u1, v0, v1)

    def gable_roof(self, p, box, y_eave, rise, axis="u", over=1.2, tail=True, tail_rise=2.0,
                   ext=1.4, profile=1.35, ridge_deco=None, end_wall=BRICK, wall_top=None):
        """一段硬山頂：box = (u0, u1, v0, v1)，屋脊沿 axis（"u" 東西向、"v" 南北向）。
        坡的那兩邊出簷 over 公尺；兩端是山牆（end_wall 從 wall_top 砌到屋面底下）；
        tail=True 屋脊兩端做燕尾。回傳 tile_roof 的屋面頂陣列。"""
        fr = self.fr
        u0, u1, v0, v1 = box
        du, dv = (u0 + u1) / 2, (v0 + v1) / 2
        if axis == "u":
            L, B = (u1 - u0) / 2, (v1 - v0) / 2 + over
            across = np.abs(fr.V - dv)
            along = np.abs(fr.U - du)
        else:
            L, B = (v1 - v0) / 2, (u1 - u0) / 2 + over
            across = np.abs(fr.U - du)
            along = np.abs(fr.V - dv)
        mask = (along <= L) & (across <= B)
        h = rise * ((B - across) / B).clip(0, 1) ** profile
        tops = TP.tile_roof(p, mask, y_eave, h, TP.ORANGE_TILES, shell=2, under=SOFFIT,
                            under_mask=mask & (across > B - over))
        # 山牆：兩端一格，從牆頂砌到屋面底下
        if end_wall and wall_top is not None:
            ends = mask & (along > L - 1.0) & (across <= B - over)
            for i, j in np.argwhere(ends):
                x, z = int(fr.X[i, j]), int(fr.Z[i, j])
                for y in range(wall_top, int(tops[i, j])):
                    p.set(x, y, z, end_wall)
        # 屋脊
        if axis == "u":
            pt = lambda a, off=0.0: (du + a, dv + off)
        else:
            pt = lambda a, off=0.0: (du + off, dv + a)
        ts = [TP.top_at(tops, fr, *pt(a)) for a in np.arange(-L + 0.5, L - 0.4, 1.0)]
        ts = [t for t in ts if t is not None]
        if not ts:
            return tops
        ry = max(ts) + 1
        if tail:
            self._swallowtail(p, pt, L, ry, ext=ext, rise=tail_rise)
        else:
            for a in np.arange(-L, L + 0.01, 0.4):
                x, z = fr.cell(*pt(a))
                p.set(x, ry, z, RIDGE)
        if ridge_deco:
            ridge_deco(p, pt, L, ry)
        elif tail and L >= 3.0:
            self._figures(p, pt, L, ry)
        return tops

    def _figures(self, p, pt, L, ry):
        """沒有雙龍的屋脊：脊上每隔 2.5 m 一尊小小的剪黏（花草、人物），顏色輪流。"""
        fr = self.fr
        k = 0
        for a in np.arange(-L + 1.5, L - 1.4, 2.5):
            x, z = fr.cell(*pt(a))
            p.set(x, ry + 1, z, JIAN_NIAN[k % len(JIAN_NIAN)])
            k += 1

    def _swallowtail(self, p, pt, L, ry, ext=1.4, rise=2.0):
        """燕尾脊：沿 pt(a) 的方向。脊身兩格（紅陶＋上緣橙），兩端上揚、伸出、分叉，
        最末端一格青綠剪黏收頭。"""
        fr = self.fr
        c = max(1.5, 0.3 * L)
        a = -(L + ext)
        cells = {}
        while a <= L + ext + 1e-9:
            aa = abs(a)
            k = max(0.0, (aa - (L - c)) / (c + ext))
            yy = ry + rise * k ** 2
            x, z = fr.cell(*pt(a))
            yi = int(math.floor(yy))
            tipz = aa > L + ext - 0.3
            cells[(x, yi, z)] = DRAGON_BODY if tipz else RIDGE_TOP
            if aa <= L + 0.3:
                cells[(x, yi - 1, z)] = RIDGE
            if aa > L + ext - 0.7:
                for sgn in (-1, 1):
                    x2, z2 = fr.cell(*pt(a, sgn * 0.8))
                    cells[(x2, yi + 1, z2)] = DRAGON_BODY if tipz else RIDGE_TOP
            a += 0.25
        for (x, y, z), b in cells.items():
            p.set(x, y, z, b)

    def _dragons(self, p, pt, L, ry, center="pagoda", span=None):
        """雙龍：屋脊上兩條剪黏龍，從兩端往中間游、頭朝中央的寶塔（或寶珠）。"""
        fr = self.fr
        span = span or min(L * 0.8, 7.0)
        for sgn in (-1, 1):
            pts = []
            n = 24
            for k in range(n + 1):
                q = k / float(n)
                a = sgn * (span - q * (span - 1.6))
                y = ry + 1 + 1.2 * (0.5 + 0.5 * math.sin(q * math.pi * 2.2))
                pts.append((a, y))
            for a, y in pts:
                x, z = fr.cell(*pt(a))
                p.set(x, int(math.floor(y)), z, DRAGON_BODY)
            # 龍頭（金）與背鰭（藍）
            a_h, y_h = pts[-1]
            x, z = fr.cell(*pt(a_h))
            p.set(x, int(math.floor(y_h)), z, DRAGON_HEAD)
            p.set(x, int(math.floor(y_h)) + 1, z, DRAGON_HEAD)
            a_t, y_t = pts[0]
            x, z = fr.cell(*pt(a_t))
            p.set(x, int(math.floor(y_t)) + 1, z, DRAGON_FIN)
        x, z = fr.cell(*pt(0.0))
        if center == "pagoda":
            # 七級寶塔：銅、金相間，頂上一支避雷針當塔剎
            stack = ["minecraft:waxed_cut_copper", GOLD,
                     "minecraft:waxed_lightning_rod[facing=up,powered=false]"]
            for k, b in enumerate(stack):
                p.set(x, ry + 1 + k, z, b)
            for sgn in (-1, 1):
                x2, z2 = fr.cell(*pt(sgn * 1.0))
                p.set(x2, ry + 1, z2, "minecraft:waxed_cut_copper")
        else:
            p.set(x, ry + 1, z, GOLD)
            p.set(x, ry + 2, z, "minecraft:red_glazed_terracotta")

    def walls_ring(self, p, box, y0, y1, block, open_side=None):
        """一棟殿的外牆（一格厚的一圈）；open_side="v+" 之類的一邊不砌（迴廊、前廊）。"""
        fr = self.fr
        u0, u1, v0, v1 = box
        m = self._box(u0, u1, v0, v1)
        ring = kit.ring(m)
        if open_side == "v+":
            ring &= ~(fr.V > v1 - 1.0)
        elif open_side == "v-":
            ring &= ~(fr.V < v0 + 1.0)
        elif open_side == "u+":
            ring &= ~(fr.U > u1 - 1.0)
        elif open_side == "u-":
            ring &= ~(fr.U < u0 + 1.0)
        p.fill(ring, y0, y1, block)
        return ring

    def floor(self, p, box, y, block=PLINTH, top="minecraft:polished_granite"):
        """台基：box 範圍從地面砌到 y-1，y 那一層鋪 top。"""
        m = self._box(*box)
        p.fill(m, self.g0, y - 1, block)
        p.layer(m, y, top)
        return m

    def col_row(self, p, pts, y0, y1, block):
        for u, v in pts:
            for y in range(y0, y1 + 1):
                p.at(u, v, y, block)

    # ================================================================ 廟埕
    def _plaza(self, p):
        """廟埕：前殿前緣到牌樓，左右兩座飛瀑水池。"""
        fr = self.fr
        g = self.g0
        fu0, fu1, _, fv1 = self.front_box
        for sgn in (-1, 1):
            # 水池：廟埕兩側、靠外的一邊是岩壁瀑布
            uo = (fu1 - 0.5) if sgn > 0 else (fu0 + 0.5)       # 岩壁在最外側
            ui = uo - sgn * 6.5
            ua, ub = min(uo, ui), max(uo, ui)
            v0, v1 = fv1 + 3.0, fv1 + 12.0
            pool = self._box(ua + 0.5, ub - 0.5, v0 + 1, v1 - 1) & (np.abs(fr.U - uo) > 1.5)
            rim = kit.dilate(pool, 1) & ~pool & ~(np.abs(fr.U - uo) <= 1.0)
            p.fill(pool, g - 2, g - 2, "minecraft:stone")
            p.fill(pool, g - 1, g, WATER)
            p.layer(rim, g, "minecraft:stone_bricks")
            p.layer(rim, g + 1, TP.slab("smooth_stone"))
            # 岩壁：外側兩格厚、高 4～6 格、頂上參差
            wall = self._box(ua, ub, v0, v1) & (np.abs(fr.U - uo) <= 1.0)
            for i, j in np.argwhere(wall):
                x, z = int(fr.X[i, j]), int(fr.Z[i, j])
                top = g + 4 + (x * 7 + z * 3) % 3
                for y in range(g + 1, top + 1):
                    p.set(x, y, z, ROCK[(x + 2 * y + z) % len(ROCK)])
                if (x + z) % 4 == 0:
                    p.set(x, top + 1, z, "minecraft:moss_block")
            # 瀑布：岩壁內側中段三格寬，頂上是水源、往池子那邊溢出一格後落下
            for k in (-1, 0, 1):
                vv = (v0 + v1) / 2 + k
                x, z = fr.cell(uo - sgn * 1.0, vv)       # 岩壁內側那一格（凹進去當水口）
                xf, zf = fr.cell(uo - sgn * 2.0, vv)     # 水口前方（池子上空）
                p.set(x, g + 4, z, WATER)
                p.set(xf, g + 4, zf, WATER_FLOW)
                for y in range(g + 1, g + 4):
                    p.set(xf, y, zf, WATER_FALL)
                    p.set(x, y, z, ROCK[(x + y) % len(ROCK)])
            # 池邊的灌木
            p.layer(self._box(ua, ub, v1 + 0.5, v1 + 1.5) & ~(np.abs(fr.U - uo) <= 1.0), g + 1,
                    "minecraft:azalea_leaves[distance=1,persistent=true,waterlogged=false]")

    # ================================================================ 前殿
    def _front_hall(self, p):
        """前殿：十一開間。中央三川殿（屋脊分三段、中段最高，即三川脊），東龍門廳、西虎門廳；
        前廊一排石柱，三川門前一對銅龍柱；牆身下段白石、上段青石。"""
        fr = self.fr
        g = self.g0
        u0, u1, v0, v1 = self.front_box
        yf = g + 1                                         # 台基（高一階）
        self.floor(p, (u0, u1, v0, v1), yf)
        wall_v = v1 - 2.2                                  # 正面牆退縮成前廊
        body = (u0, u1, v0, wall_v)
        s_mid = 0.5 * (u0 + u1)
        sc0, sc1 = -8.2, 9.2                               # OSM 的分段點：三川殿兩端
        mid0, mid1 = s_mid - 4.0, s_mid + 4.0
        # 牆身：前牆石作、背牆（面中庭）與兩端紅磚
        ring = self.walls_ring(p, body, yf + 1, g + 6, BRICK)
        front = ring & (fr.V > wall_v - 1.0)
        for i, j in np.argwhere(front):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            for y in range(yf + 1, g + 7):
                k = y - yf
                b = WHITE_STONE if k <= 1 else (BLUE_STONE if k <= 4 else WHITE_STONE)
                if k in (2, 3) and int(math.floor(fr.U[i, j])) % 4 in (1, 2):
                    b = CARVED                             # 石雕窗
                p.set(x, y, z, b)
        # 門：三川門（中央三樘）＋龍門（東）、虎門（西）；背面（中庭側）對應開洞
        doors = [s_mid - 5.5, s_mid, s_mid + 5.5, (sc1 + u1) / 2, (u0 + sc0) / 2]
        for du in doors:
            sel = ring & (np.abs(fr.U - du) <= 1.0)
            for i, j in np.argwhere(sel):
                x, z = int(fr.X[i, j]), int(fr.Z[i, j])
                for y in range(yf + 1, yf + 4):
                    p.set(x, y, z, AIR)
            # 台階：前廊前緣一排、中庭側一排
            for vv, sv in ((v1 + 0.5, -1), (v0 - 0.5, 1)):
                st = self._box(du - 1.2, du + 1.2, vv - 0.5, vv + 0.5)
                for x, z in fr.cells(st):
                    p.set(x, yf, z, TP.stairs("stone_brick", fr.facing(0, sv)))
        # 三川門上方的門匾「龍山寺」
        vv = wall_v - 0.5
        for d in (-1.0, 0.0, 1.0):
            p.at(s_mid + d, vv, yf + 4, "minecraft:polished_blackstone")
        TP.plaque_sign(p, s_mid, vv, yf + 4, (0, 1), ["", dict(text="龍山寺", color="#E8C15A", bold=True), "", ""])
        # 室內
        inner = kit.erode(self._box(*body), 1)
        p.clear(inner, yf + 1, g + 6)
        p.layer(inner, g + 7, RED_WOOD)                    # 天花
        # 前廊：石柱一排（柱頭到 g+5），三川門前兩根銅龍柱
        vcol = v1 - 0.6
        for uu in np.linspace(u0 + 0.6, u1 - 0.6, 12):
            blk = BRONZE if abs(uu - s_mid) < 3.2 else (CARVED if sc0 < uu < sc1 else PLAIN_COL)
            self.col_row(p, [(uu, vcol)], yf + 1, g + 5, blk)
        # 三川殿中段的屋簷比兩側高一格：前廊上方那一格是朱紅貼金的額枋
        beam = self._box(mid0, mid1, wall_v, v1) & (fr.V > v1 - 1.0)
        for i, j in np.argwhere(beam):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            p.set(x, g + 6, z, GOLD if (x + z) % 3 == 0 else RED_WOOD)
        # 屋頂：五段（虎門廳、三川殿左、三川殿中、三川殿右、龍門廳），中段最高
        segs = [((mid0, mid1), g + 7, 3.0, 2.4, True),
                ((sc0, mid0), g + 6, 2.9, 1.8, False),
                ((mid1, sc1), g + 6, 2.9, 1.8, False),
                ((u0, sc0), g + 6, 2.6, 1.8, False),
                ((sc1, u1), g + 6, 2.6, 1.8, False)]
        for (a0, a1), ye, rise, trise, deco in segs:
            deco_fn = (lambda p_, pt, L, ry: self._dragons(p_, pt, L, ry, center="pearl", span=3.4)) if deco else None
            self.gable_roof(p, (a0, a1, v0, v1), ye, rise, axis="u", over=1.0, tail=True,
                            tail_rise=trise, ext=1.2, ridge_deco=deco_fn, wall_top=g + 6)

    # ================================================================ 左右護室
    def _wings(self, p):
        fr = self.fr
        g = self.g0
        for box, inner_side in ((self.wing_w, "u+"), (self.wing_e, "u-")):
            u0, u1, v0, v1 = box
            self.floor(p, box, g + 1, top="minecraft:polished_andesite")
            # 外牆紅磚；面中庭那一側是迴廊（柱列）
            self.walls_ring(p, box, g + 2, g + 5, BRICK, open_side=inner_side)
            inner = kit.erode(self._box(*box), 1)
            p.clear(inner, g + 2, g + 5)
            uc = (u1 - 0.6) if inner_side == "u+" else (u0 + 0.6)
            for vv in np.arange(v0 + 1.0, v1 - 0.5, 3.2):
                self.col_row(p, [(uc, vv)], g + 2, g + 5, PLAIN_COL)
            # 內牆（迴廊後方）：紅磚、每隔一段一個門洞
            uw = uc + (-2.0 if inner_side == "u+" else 2.0)
            wl = (np.abs(fr.U - uw) <= 0.5) & (fr.V > v0 + 1) & (fr.V < v1 - 1)
            gap = (np.floor(fr.V) % 8) < 2
            p.fill(wl & ~gap, g + 2, g + 5, BRICK)
            p.layer(self._box(*box), g + 6, RED_WOOD)
            self.gable_roof(p, box, g + 6, 2.4, axis="v", over=1.0, tail=True, tail_rise=1.4,
                            ext=0.8, wall_top=g + 6)

    # ================================================================ 正殿
    def _main_hall(self, p):
        """正殿：石台基、周圍一圈石柱（前排龍柱）、敞堂；重簷歇山。"""
        fr = self.fr
        g = self.g0
        a, b = self.ha, self.hb_
        yf = g + 1
        # 台基外擴 0.8 m，前面三組台階
        plat = self._box(-a - 0.8, a + 0.8, -b - 0.8, b + 0.8)
        p.fill(plat, g, yf - 1, PLINTH)
        p.layer(plat, yf, "minecraft:polished_granite")
        for du in (-5.0, 0.0, 5.0):
            steps = self._box(du - 1.6, du + 1.6, b + 0.8, b + 1.8)
            fac = fr.facing(0, -1)
            for x, z in fr.cells(steps):
                p.set(x, yf, z, TP.stairs("stone_brick", fac))
        # 石欄杆：台基邊緣一圈，台階處留空
        edge = kit.ring(plat)
        for du in (-5.0, 0.0, 5.0):
            edge &= ~((np.abs(fr.U - du) <= 1.7) & (fr.V > 0))
        rail = {(int(fr.X[i, j]), yf + 1, int(fr.Z[i, j])) for i, j in np.argwhere(edge)}
        for k, blk in TP.walls_conn(rail, "stone_brick_wall").items():
            p.set(k[0], k[1], k[2], blk)
        # 柱：外圈一周，前排是石雕龍柱
        yc = g + 7
        nu, nv = 7, 5
        for i in range(nu + 1):
            for j in range(nv + 1):
                if i not in (0, nu) and j not in (0, nv):
                    continue
                uu = -a + 0.6 + (2 * a - 1.2) * i / nu
                vv = -b + 0.6 + (2 * b - 1.2) * j / nv
                blk = DRAGON_COL if j == nv else PLAIN_COL
                self.col_row(p, [(uu, vv)], yf + 1, yc, blk)
        # 內殿：後牆與兩側牆（敞堂：前面不設門扇），神龕金色
        core = (-a + 2.4, a - 2.4, -b + 2.2, b - 2.6)
        self.walls_ring(p, core, yf + 1, yc, RED_WOOD, open_side="v+")
        cv0 = core[2]
        shrine = self._box(-3.0, 3.0, cv0 + 1.0, cv0 + 2.4)
        p.fill(shrine, yf + 1, yf + 2, "minecraft:polished_blackstone")
        p.layer(shrine, yf + 3, GOLD)
        p.layer(self._box(-1.0, 1.0, cv0 + 1.0, cv0 + 1.8), yf + 4, GOLD)
        # 額枋、斗拱
        band = kit.ring(self._box(-a + 0.2, a - 0.2, -b + 0.2, b - 0.2))
        for i, j in np.argwhere(band):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            p.set(x, yc + 1, z, GOLD if (x + z) % 3 == 0 else RED_WOOD)
        p.layer(kit.erode(self._box(-a + 0.2, a - 0.2, -b + 0.2, b - 0.2), 1), yc + 1, RED_WOOD)
        # 下簷：四面披檐，從出簷 1.3 m 處升到上層的牆（東側離護室只有幾十公分，不能再寬）
        la, lb = a + 1.3, b + 1.3
        ua_, ub_ = 7.2, 5.4                                # 上層牆的半長、半寬
        low = self._box(-la, la, -lb, lb) & ~self._box(-ua_, ua_, -ub_, ub_)
        d_out = np.minimum(la - np.abs(fr.U), lb - np.abs(fr.V)).clip(0, None)
        d_in = np.minimum(la - ua_, lb - ub_)
        h_low = 1.3 * (d_out / d_in).clip(0, 1) ** 1.2
        h_low = h_low + TP.corner_lift(fr, la, lb, 0.9)
        y_low = yc + 2                                     # g+9
        TP.tile_roof(p, low, y_low, h_low, TP.ORANGE_TILES, shell=2, under=SOFFIT,
                     under_mask=low & ~self._box(-a, a, -b, b))
        # 上層：牆（貼金的額枋帶）
        up = self._box(-ua_, ua_, -ub_, ub_)
        ring = kit.ring(up)
        p.fill(ring, y_low, y_low + 2, RED_WOOD)
        for i, j in np.argwhere(ring):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            if (x + z) % 2 == 0:
                p.set(x, y_low + 2, z, GOLD)
        p.clear(kit.erode(up, 1), y_low, y_low + 2)
        # 上簷：歇山
        ra, rb = ua_ + 1.8, ub_ + 1.8
        gin = 2.2
        y_up = y_low + 3                                   # g+12
        mask = self._box(-ra, ra, -rb, rb)
        h = kit.hip_gable(fr, ra, rb, 2.1, gin, profile=1.5, lift=1.0)
        tops = TP.tile_roof(p, mask, y_up, h, TP.ORANGE_TILES, shell=2, under=SOFFIT,
                            under_mask=mask & ~up)
        # 山花（紅磚底、金色博風）
        for su in (-1, 1):
            cells = (su * fr.U > ra - gin) & (su * fr.U <= ra - gin + 1.0) & (np.abs(fr.V) < rb - gin + 0.3)

            def ytop(i, j, su=su):
                t = TP.top_at(tops, fr, su * (ra - gin - 0.6), float(fr.V[i, j]))
                return t if t is not None else tops[i, j]
            TP.gable_face(p, cells, tops, ytop, BRICK, border=GOLD)
        # 正脊：燕尾、雙龍護塔
        L = ra - gin
        ts = [TP.top_at(tops, fr, u, 0.0) for u in np.arange(-L, L + 0.01, 0.5)]
        ry = max(t for t in ts if t is not None) + 1
        pt = lambda aa, off=0.0: (aa, off)
        self._swallowtail(p, pt, L, ry, ext=1.6, rise=2.4)
        self._dragons(p, pt, L, ry, center="pagoda", span=min(L - 0.5, 6.0))
        # 垂脊、戧脊：紅脊，翼角尾端一格青綠
        for su in (-1, 1):
            for sv in (-1, 1):
                pts = []
                for k in np.arange(0.0, rb - gin + 0.01, 0.4):
                    t = TP.top_at(tops, fr, su * (ra - gin - 0.6), sv * k)
                    if t is not None:
                        pts.append((su * (ra - gin + 0.3), sv * k, t + 1))
                for k in range(11):
                    q = k / 10.0
                    uu = su * (ra - gin + 0.3 + (gin - 0.6) * q)
                    vv = sv * (rb - gin + (gin - 0.6) * q)
                    t = TP.top_at(tops, fr, uu, vv)
                    if t is not None:
                        pts.append((uu, vv, t + 1))
                if len(pts) >= 2:
                    TP.ridge_line(p, pts, RIDGE)
                    uu, vv, yy = pts[-1]
                    TP.ridge_line(p, [(uu + su * 0.4, vv + sv * 0.4, yy + 1)] * 2, DRAGON_BODY)
        # 下簷四角的戧脊
        for su in (-1, 1):
            for sv in (-1, 1):
                pts = []
                for k in range(9):
                    q = k / 8.0
                    uu = su * (ua_ + (la - ua_) * q)
                    vv = sv * (ub_ + (lb - ub_) * q)
                    x, z = fr.cell(uu, vv)
                    i, j = z - fr.z0, x - fr.x0
                    hv = float(h_low[i, j]) if low[i, j] else 0.0
                    pts.append((uu, vv, y_low + 1 + hv + 0.6))
                TP.ridge_line(p, pts, RIDGE)
                uu, vv, yy = pts[-1]
                TP.ridge_line(p, [(uu + su * 0.4, vv + sv * 0.4, yy + 1)] * 2, DRAGON_BODY)

    # ================================================================ 過水
    def _link(self, p):
        """正殿與後殿之間的過水：柱廊加一段兩坡頂。"""
        g = self.g0
        u0, u1, v0, v1 = self.link_box
        self.floor(p, self.link_box, g + 1)
        for uu in np.linspace(u0 + 0.6, u1 - 0.6, 6):
            for vv in (v0 + 0.6, v1 - 0.6):
                self.col_row(p, [(uu, vv)], g + 2, g + 5, PLAIN_COL)
        p.layer(self._box(*self.link_box), g + 6, RED_WOOD)
        self.gable_roof(p, self.link_box, g + 6, 1.8, axis="u", over=0.6, tail=True, tail_rise=1.0,
                        ext=0.8, wall_top=None)

    # ================================================================ 後殿
    def _rear_hall(self, p):
        """後殿：供奉媽祖、文昌帝君、關聖帝君等；正面（朝中庭）是前廊，屋脊分三段、中段最高。"""
        fr = self.fr
        g = self.g0
        u0, u1, v0, v1 = self.rear_box
        yf = g + 1
        self.floor(p, self.rear_box, yf)
        wall_v = v1 - 2.0
        body = (u0, u1, v0, wall_v)
        ring = self.walls_ring(p, body, yf + 1, g + 6, BRICK)
        inner = kit.erode(self._box(*body), 1)
        p.clear(inner, yf + 1, g + 6)
        p.layer(inner, g + 7, RED_WOOD)
        # 正面（朝南）：木作格扇（朱紅），每間一樘門
        front = ring & (fr.V > wall_v - 1.0)
        for i, j in np.argwhere(front):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            for y in range(yf + 1, g + 7):
                p.set(x, y, z, RED_WOOD if (y - yf) <= 3 else GOLD if (x + z) % 2 else RED_WOOD)
        for du in np.arange(u0 + 3.0, u1 - 2.0, 4.0):
            sel = front & (np.abs(fr.U - du) <= 0.6)
            for i, j in np.argwhere(sel):
                x, z = int(fr.X[i, j]), int(fr.Z[i, j])
                for y in range(yf + 1, yf + 4):
                    p.set(x, y, z, AIR)
        for uu in np.linspace(u0 + 0.6, u1 - 0.6, 12):
            self.col_row(p, [(uu, v1 - 0.6)], yf + 1, g + 6, CARVED)
        s_mid = 0.5 * (u0 + u1)
        mid0, mid1 = s_mid - 5.0, s_mid + 5.0
        segs = [((mid0, mid1), g + 8, 3.3, 2.2, True),
                ((u0, mid0), g + 7, 3.0, 1.8, False),
                ((mid1, u1), g + 7, 3.0, 1.8, False)]
        for (a0, a1), ye, rise, trise, deco in segs:
            deco_fn = (lambda p_, pt, L, ry: self._dragons(p_, pt, L, ry, center="pearl", span=3.8)) if deco else None
            self.gable_roof(p, (a0, a1, v0, v1), ye, rise, axis="u", over=1.0, tail=True,
                            tail_rise=trise, ext=1.2, ridge_deco=deco_fn, wall_top=g + 7)

    # ================================================================ 鐘樓、鼓樓
    def _towers(self, p):
        """東鐘樓、西鼓樓：騎在護室上的方樓，轎頂式重簷（上層屋頂像轎子頂：短脊的四坡頂）。"""
        fr = self.fr
        g = self.g0
        for box in (self.wing_w, self.wing_e):
            u0, u1 = box[0], box[1]
            uc = (u0 + u1) / 2
            vc = 15.5
            half = min(3.4, (u1 - u0) / 2)
            tb = self._box(uc - half + 0.6, uc + half - 0.6, vc - half + 0.6, vc + half - 0.6)
            # 樓身：護室屋頂上再起兩層
            ring = kit.ring(tb)
            p.fill(ring, g + 6, g + 11, RED_WOOD)
            p.clear(kit.erode(tb, 1), g + 7, g + 11)
            for i, j in np.argwhere(ring):
                x, z = int(fr.X[i, j]), int(fr.Z[i, j])
                du, dv = float(fr.U[i, j]) - uc, float(fr.V[i, j]) - vc
                fac = fr.facing(1 if du > 0 else -1, 0) if abs(du) > abs(dv) else fr.facing(0, 1 if dv > 0 else -1)
                if (x + z) % 2 == 0:
                    # 格窗：打開的暗色活板門貼在牆外側
                    p.set(x, g + 8, z, "minecraft:dark_oak_trapdoor[facing=%s,half=bottom,open=true,"
                                       "powered=false,waterlogged=false]" % fac)
                p.set(x, g + 11, z, GOLD if (x + z) % 2 else RED_WOOD)
            # 下層披檐
            sk = self._box(uc - half - 0.8, uc + half + 0.8, vc - half - 0.8, vc + half + 0.8) & ~tb
            d = np.minimum(half + 0.8 - np.abs(fr.U - uc), half + 0.8 - np.abs(fr.V - vc)).clip(0, None)
            hs = 1.4 * (d / 1.8).clip(0, 1) + TP.corner_lift(fr, half + 0.8, half + 0.8, 0.8, du=uc, dv=vc)
            TP.tile_roof(p, sk, g + 9, hs, TP.ORANGE_TILES, shell=1, under=SOFFIT)
            # 上層轎頂：四坡、短脊、翼角高翹
            rt = self._box(uc - half - 0.6, uc + half + 0.6, vc - half - 0.6, vc + half + 0.6)
            hr = kit.hip(fr, half + 0.6, half * 0.9 + 0.6, 3.0, profile=1.6, lift=1.2, du=uc, dv=vc)
            tops = TP.tile_roof(p, rt, g + 12, hr, TP.ORANGE_TILES, shell=2, under=SOFFIT)
            ts = [TP.top_at(tops, fr, uc + dd, vc) for dd in (-0.5, 0.0, 0.5)]
            top = max(t for t in ts if t is not None)
            pt = lambda aa, off=0.0, uc=uc, vc=vc: (uc + off, vc + aa)
            self._swallowtail(p, pt, 0.9, top + 1, ext=0.9, rise=1.2)
            x, z = fr.cell(uc, vc)
            p.set(x, top + 2, z, GOLD)
            p.set(x, top + 3, z, "minecraft:waxed_lightning_rod[facing=up,powered=false]")

    # ================================================================ 牌樓
    def _pailou(self, p):
        """廟埕前的四柱三間牌樓：石柱，明間屋頂最高，兩次間較低，燕尾脊。"""
        fr = self.fr
        g = self.g0
        u0, u1, v0, v1 = self.pailou_box
        vc = (v0 + v1) / 2
        span = u1 - u0
        cols = [u0 + 0.6, u0 + span * 0.3, u0 + span * 0.7, u1 - 0.6]
        for uu in cols:
            self.col_row(p, [(uu, vc)], g + 1, g + 6, "minecraft:polished_diorite")
            p.at(uu, vc - 1.0, g + 1, "minecraft:stone_brick_stairs[facing=%s,half=bottom,shape=straight,waterlogged=false]" % fr.facing(0, 1))
            p.at(uu, vc + 1.0, g + 1, "minecraft:stone_brick_stairs[facing=%s,half=bottom,shape=straight,waterlogged=false]" % fr.facing(0, -1))
        # 額枋與匾
        for uu in np.arange(cols[0], cols[-1] + 0.01, 0.5):
            p.at(uu, vc, g + 7, RED_WOOD)
        for uu in np.arange(cols[1], cols[2] + 0.01, 0.5):
            p.at(uu, vc, g + 6, GOLD)
        p.at((cols[1] + cols[2]) / 2, vc, g + 5, "minecraft:polished_blackstone")
        TP.plaque_sign(p, (cols[1] + cols[2]) / 2, vc, g + 5, (0, 1),
                       ["", dict(text="龍山寺", color="#E8C15A", bold=True), "", ""])
        vb = (vc - 1.8, vc + 1.8)
        self.gable_roof(p, (cols[1] - 0.6, cols[2] + 0.6, vb[0] + 0.6, vb[1] - 0.6), g + 8, 1.6, axis="u",
                        over=1.2, tail=True, tail_rise=1.4, ext=0.9, wall_top=None,
                        ridge_deco=lambda p_, pt, L, ry: self._dragons(p_, pt, L, ry, center="pearl", span=2.6))
        for a0, a1 in ((cols[0] - 0.8, cols[1] - 0.6), (cols[2] + 0.6, cols[3] + 0.8)):
            self.gable_roof(p, (a0, a1, vb[0] + 0.6, vb[1] - 0.6), g + 7, 1.2, axis="u", over=1.0,
                            tail=True, tail_rise=1.0, ext=0.6, wall_top=None)

    # ================================================================ 中庭
    def _courtyard(self, p):
        """中庭：正殿前的天公爐（銅），兩側矮樹。"""
        fr = self.fr
        g = self.g0
        b = self.hb_
        x, z = fr.cell(0.0, b + 4.0)
        p.set(x, g + 1, z, "minecraft:polished_blackstone")
        p.set(x, g + 2, z, "minecraft:cauldron")
        for sgn in (-1, 1):
            xx, zz = fr.cell(sgn * 1.0, b + 4.0)
            p.set(xx, g + 1, zz, "minecraft:waxed_exposed_cut_copper")
        for sgn in (-1, 1):
            tree = fr.ellipse(1.3, 1.3, sgn * 8.0, b + 9.0)
            p.layer(tree, g + 1, "minecraft:stone_bricks")
            p.fill(fr.ellipse(1.0, 1.0, sgn * 8.0, b + 9.0), g + 2, g + 3,
                   "minecraft:azalea_leaves[distance=1,persistent=true,waterlogged=false]")


BUILDS = {"longshan_temple": LongshanTemple}
