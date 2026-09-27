#!/usr/bin/env python3
"""中正紀念堂園區：紀念堂、自由廣場牌樓、國家戲劇院、國家音樂廳、自由廣場與民主大道、
大忠門與大孝門、園區迴廊。

位置、方向、輪廓（OSM，data/attractions.json）：
  way/1052759757  紀念堂台基（height 14.5，連正面大階梯）
  way/1052759756  最外一層台基（building:levels 1，西側中段是階梯的缺口）
  way/1052759759  堂身（min_height 14.5、height 38.5）
  way/1052759768  八角屋頂（38.5～70 m、pyramidal、roof:colour blue）
  way/1052759782  自由廣場門（牌樓；六根柱腳的位置就是輪廓上的六個凸出）
  way/1052759776  國家戲劇院、way/1052759775  國家音樂廳（height 37、roof:height 12）
  way/1053359244  自由廣場（兩廳院之間的廣場）、way/1053396976  民主大道（瞻仰大道）
  way/1053359203  大忠門（北）、way/1053359198  大孝門（南）
  way/1053359285  西南角的圍牆（北邊那段 OSM 沒有，照軸線鏡射）
  軸線：牌樓中心 -> 紀念堂中心，由西北西往東南東約 28°；紀念堂坐東朝西。

長相（公開資料：維基百科「中正紀念堂」「國家戲劇院」「國家音樂廳」「自由廣場」，
國立中正紀念堂管理處網站；照片只拿來量比例）：
  · 紀念堂高 70 m；三層台基高 14.5 m；堂身牆高 24 m；斗拱至寶頂 31.5 m；青銅大門高 16 m
  · 藍色琉璃瓦八角重簷攢尖頂（八角象徵八德）、金色寶頂；外牆白色大理石（藍白＝青天白日）
  · 正面花崗石 84 階＋大廳 5 階＝89 階（蔣中正享壽 89 歲），中間是刻國徽的御路
  · 大廳：銅像坐姿高 6.3 m；天花是青天白日十二道光芒國徽的藻井
  · 自由廣場牌樓：高 30 m、寬 80 m，「五間六柱十一樓」，白牆藍瓦
  · 國家戲劇院：重簷廡殿頂；國家音樂廳：重簷歇山頂（等級低於廡殿）；
    黃色琉璃瓦、紅柱、斗拱、白色台基與欄杆（楊卓成設計，1987）
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions import palace_kit as PK
from mrt.application.attractions.kit import Attraction, Frame, Painter, Spot

HALL_BASE = "way/1052759757"
HALL_ROOF = "way/1052759768"
GATE = "way/1052759782"
THEATER = "way/1052759776"
CONCERT = "way/1052759775"
PLAZA = "way/1053359244"
BLVD = "way/1053396976"
LOYALTY = "way/1053359203"      # 大忠門
PIETY = "way/1053359198"        # 大孝門
SW_WALL = "way/1053359285"

B = "minecraft:"
WHITE = B + "smooth_quartz"
WHITE2 = B + "quartz_bricks"
TRIM = B + "chiseled_quartz_block"
PILLAR = B + "quartz_pillar"
WSLAB = B + "smooth_quartz_slab[type=bottom]"
BLUE = B + "blue_concrete"
BLUE_G = B + "blue_glazed_terracotta"
TEAL = B + "prismarine_bricks"
GOLD = B + "gold_block"
FLOOR = B + "polished_diorite"
GRANITE = B + "polished_andesite"
GRANITE_S = B + "polished_andesite_slab[type=bottom]"
PAVE = B + "smooth_stone"
PAVE2 = B + "polished_andesite"
PAVE3 = B + "polished_diorite"
GRASS = B + "grass_block[snowy=false]"
FILL = B + "stone"
HEDGE = B + "spruce_leaves[distance=7,persistent=true,waterlogged=false]"
BRONZE = B + "waxed_copper_block"
BRONZE2 = B + "waxed_exposed_copper"
LAMP = B + "sea_lantern"
POST = B + "diorite_wall"                      # 預設狀態是一根細柱（不接鄰格）
LANTERN = B + "lantern[hanging=false,waterlogged=false]"

# 牌樓（局部 u 沿面寬）：六根柱的中心（OSM 輪廓上柱腳凸出的位置，對中心左右對稱）
GATE_PILLARS = (8.45, 22.4, 33.65)

# 兩廳院：局部座標（正面朝 -v）的尺寸，量自 OSM 輪廓（滴水線）
THEATER_SPEC = PK.HallSpec(ca=35.5, cb=43.8, wa=51.8, wb=29.5, sw=10.0, sd=13.5,
                           roof="hip", ridge=24.0)
CONCERT_SPEC = PK.HallSpec(ca=33.0, cb=43.9, wa=51.2, wb=29.6, sw=10.5, sd=13.5,
                           roof="hip_gable", ridge=21.0)

# 園區迴廊：南北兩側在 v = ±167（大忠門、大孝門與迴廊上的涼亭都在這條線上），
# 東側在 u = +160（紀念堂後方的園區建物之外）
PARK_V = 167.0
PARK_E = 160.0


def _ring(f):
    return max(f["outer"], key=len)


class CksMemorial(Attraction):
    height_m = 70.0
    margin = 10

    def __init__(self, item):
        super().__init__(item)
        self.hall_c = PK.ring_centroid(_ring(self.feature(HALL_ROOF)))
        self.gate_c = PK.ring_centroid(_ring(self.feature(GATE)))
        self.theta = math.atan2(self.hall_c[1] - self.gate_c[1], self.hall_c[0] - self.gate_c[0])
        self.axis = Frame(self.hall_c[0], self.hall_c[1], self.theta, 1)   # 只拿來換算座標
        self.gate_u = self.axis.local(self.gate_c[0] - 0.5, self.gate_c[1] - 0.5)[0]

    # ---- 範圍 ----
    def _corners(self):
        """園區的外框（局部座標）轉成世界座標的四個角。"""
        return [self.axis.world(u, v) for u in (self.gate_u - 30, PARK_E + 4)
                for v in (-PARK_V - 16, PARK_V + 16)]

    def bbox(self):
        pts = list(self._corners())
        for osm in (HALL_BASE, THEATER, CONCERT, GATE, PLAZA, BLVD, LOYALTY, PIETY, SW_WALL):
            f = self.feature(osm)
            if f and f.get("outer"):
                pts += _ring(f)
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        m = self.margin
        return (int(math.floor(min(xs))) - m, int(math.floor(min(zs))) - m,
                int(math.ceil(max(xs))) + m, int(math.ceil(max(zs))) + m)

    # ---- 規劃 ----
    def plan(self, site):
        ax = self.axis
        # 大框：整個園區（局部 u 從牌樓外到東側迴廊）
        ua = (self.gate_u - 40 + PARK_E + 10) / 2.0
        self.ua = ua
        self.fa = PK.sub_frame(ax, ua, 0.0, (PARK_E + 10 - (self.gate_u - 40)) / 2.0 + 2)
        self.fh = PK.sub_frame(ax, 0.0, 0.0, 92)
        self.fg = PK.sub_frame(ax, self.gate_u, 0.0, 46, turn=math.pi / 2)
        self.ft = self._hall_frame(THEATER, THEATER_SPEC, 0.0)
        self.fc = self._hall_frame(CONCERT, CONCERT_SPEC, math.pi)
        fa = self.fa
        Uc, Vc = fa.U + ua, fa.V
        aV = np.abs(Vc)
        self.park = (Uc >= self.gate_u - 1) & (Uc <= PARK_E + 1) & (aV <= PARK_V + 1)
        # 整地範圍：園區加上牌樓外側的抱鼓石、西側兩段圍牆
        walls = fa.empty()
        for poly in self._wall_rings():
            walls |= fa.polygon(poly)
        self.level = self.park | ((Uc >= self.gate_u - 12) & (aV <= 45)) | kit.dilate(walls, 2)
        # 基地地面：園區裡每 5 m 取一點的中位數（廣場、大道、紀念堂都在同一個高度上）
        sample = self.park & (fa.X % 5 == 0) & (fa.Z % 5 == 0)
        gs = [site.g(x, z) for x, z in zip(fa.X[sample].tolist(), fa.Z[sample].tolist())]
        self.G = int(np.round(np.median(gs))) if gs else 64
        self.g0 = self.G
        # 整地要逐格的地面高度；cli 的地面函式只在 plan 階段可用，這裡先算好存起來
        self.gnd = site.grid(fa, self.level)
        G = self.G
        # 觀景點：自由廣場東緣、軸線上，面向紀念堂（背後是牌樓）
        spots = []
        for key, u, v, y, tu, ty, zh, en in (
                ("", -300.0, 0.0, G + 1, 0.0, G + 35, self.name_zh, self.name_en),
                ("hall", -13.5, 3.0, G + 15, 15.5, G + 21, "紀念堂大廳", "Main Hall"),
                ("arch", self.gate_u + 34, 0.0, G + 1, self.gate_u, G + 17, "自由廣場牌樓",
                 "Liberty Square Gate")):
            x, z = ax.cell(u, v)
            tx, tz = ax.world(tu, 0.0)
            yaw, pitch = kit.look(x, y, z, tx, ty, tz)
            spots.append(Spot(key, x, y, z, yaw, pitch, zh, en))
        self._spots = spots

    def _hall_frame(self, osm, spec, turn):
        """兩廳院的局部框：方向跟軸線一樣（音樂廳轉 180°，讓兩座的正面都朝 -v），
        中心取 OSM 輪廓在這個方向上的外接框（扣掉正面大階梯、背面的翼角）。"""
        ring = _ring(self.feature(osm))
        c = PK.ring_centroid(ring)
        f0 = Frame(c[0], c[1], self.theta + turn, 1)
        u0, u1, v0, v1 = PK.local_bbox(f0, ring)
        uc = (u0 + u1) / 2.0
        vc = ((v0 + spec.sd) + (v1 - 2.0)) / 2.0
        x, z = f0.world(uc, vc)
        return Frame(x, z, self.theta + turn, max(spec.wa, spec.cb + spec.sd) + 8)

    def plaque(self):
        return [self.name_zh, self.name_en, "高 70 m，1980 年落成",
                "正面 84 階＋大廳 5 階＝89 階"]

    # ---- 蓋 ----
    def build(self, w):
        self._grounds(w)
        self._walls(w)
        PK.palace_hall(w, self.ft, THEATER_SPEC, self.G)
        PK.palace_hall(w, self.fc, CONCERT_SPEC, self.G)
        self._gate(w)
        self._side_gates(w)
        self._hall(w)

    # ---------------------------------------------------------------- 地面
    def _grounds(self, w):
        """整地（園區內一律整成 G）、鋪面、草地、樹籬與修剪成圓錐的樹。"""
        fa, G, ua = self.fa, self.G, self.ua
        p = Painter(w, fa)
        Uc, Vc = fa.U + ua, fa.V
        aV = np.abs(Vc)
        plaza = fa.polygon(_ring(self.feature(PLAZA)))
        blvd = fa.polygon(_ring(self.feature(BLVD)))
        west = (Uc >= self.gate_u - 1) & (Uc <= -410) & (aV <= 62)
        fore = (Uc >= -96) & (Uc <= -84) & (aV <= 53)
        hallring = (np.maximum(np.abs(Uc), aV) <= 70)
        apron_t = (Uc >= -418) & (Uc <= -292) & (aV >= 48) & (aV <= 164)
        side = (np.abs(Uc) <= 4) & (aV <= PARK_V)
        corridor = aV >= PARK_V - 4
        paved = plaza | blvd | west | fore | hallring | apron_t | side | corridor
        gate_apron = (Uc >= self.gate_u - 12) & (Uc < self.gate_u - 1) & (aV <= 45)
        paved = (paved & self.park) | gate_apron
        # 鋪面的花紋：廣場每 8 m 一道深色分隔線、軸線上一道淺色帶
        grid = ((np.floor(Uc) % 8) == 0) | ((np.floor(Vc) % 8) == 0)
        axis = aV <= 2.0
        lv = self.level
        X, Z = fa.X[lv].tolist(), fa.Z[lv].tolist()
        GN = self.gnd[lv].tolist()
        PV, GR, AX, PL = (paved[lv].tolist(), grid[lv].tolist(),
                          axis[lv].tolist(), (plaza | west)[lv].tolist())
        s = p.set
        for x, z, gy, pv, gr, ax_, pl in zip(X, Z, GN, PV, GR, AX, PL):
            if gy < G:
                for y in range(max(gy + 1, G - 8), G):
                    s(x, y, z, FILL)
            elif gy > G:
                for y in range(G + 1, min(gy, G + 12) + 1):
                    s(x, y, z, kit.AIR)
            if not pv:
                s(x, G, z, GRASS)
            elif ax_:
                s(x, G, z, PAVE3)
            elif pl and gr:
                s(x, G, z, PAVE2)
            else:
                s(x, G, z, PAVE if pl else PAVE2)
        # 民主大道兩側的草地：樹籬沿著鋪面邊緣，草地中間一排修剪成圓錐的樹
        zone = (Uc >= -249) & (Uc <= -92) & self.park
        lawn = zone & ~paved
        edge = lawn & kit.dilate(paved, 1) & ~kit.erode(lawn, 1)
        p.layer(edge & zone, G + 1, HEDGE)
        for vv in (-32.5, 32.5):
            for uu in np.arange(-240.0, -95.0, 12.0):
                self._cone(p, uu - ua, vv, G + 1)
        # 路燈：大道中央鋪面兩側、廣場南北兩緣，每 16 m 一盞（柱 3 m、燈籠在頂上）
        posts = [(uu, vv) for uu in np.arange(-244.0, -95.0, 16.0) for vv in (-19.5, 19.5)]
        posts += [(uu, vv) for uu in np.arange(-408.0, -296.0, 16.0) for vv in (-57.0, 57.0)]
        for uu, vv in posts:
            x, z = fa.cell(uu - ua, vv)
            for y in range(G + 1, G + 4):
                p.set(x, y, z, POST)
            p.set(x, G + 4, z, LANTERN)

    def _cone(self, p, u, v, y0):
        """修剪成圓錐的樹（民主大道兩旁那種），高 5 m，只用樹葉（不會長、不會掉）。"""
        fa = p.fr
        d = np.hypot(fa.U - u, fa.V - v)
        for k, r in enumerate((1.9, 1.6, 1.2, 0.8, 0.3)):
            p.layer(d <= r + 0.2, y0 + k, HEDGE)

    # ---------------------------------------------------------------- 迴廊
    def _walls(self, w):
        """園區外圍的白牆藍瓦迴廊：外牆高 4 m、每 8 m 一扇漏窗，內側一排白柱、
        單坡藍瓦頂（最高離地 5 m，不擋視線）。西南角照 OSM 的牆，西北角鏡射過去。"""
        fa, G, ua = self.fa, self.G, self.ua
        p = Painter(w, fa)
        Uc, Vc = fa.U + ua, fa.V
        aV = np.abs(Vc)
        # 南北兩側（大忠門、大孝門那一段空出來）與東側
        ns = (Uc >= self.gate_u + 2) & (Uc <= PARK_E + 1) & ~((Uc > -12.5) & (Uc < 13.5))
        ea = aV <= PARK_V + 1
        outer_ns = ns & (aV > PARK_V) & (aV <= PARK_V + 1)
        outer_e = ea & (Uc > PARK_E) & (Uc <= PARK_E + 1)
        band_ns = ns & (aV > PARK_V - 3.5) & (aV <= PARK_V + 1)
        band_e = ea & (Uc > PARK_E - 3.5) & (Uc <= PARK_E + 1)
        cor = band_ns | band_e
        p.fill(outer_ns | outer_e, G + 1, G + 4, WHITE)
        # 漏窗：每 8 m 一扇 2×2
        win = (outer_ns & ((np.floor(Uc) % 8) < 2)) | (outer_e & ((np.floor(Vc) % 8) < 2))
        p.fill(win, G + 2, G + 3, kit.AIR)
        # 內側柱：每 4 m 一根
        cols = ((ns & (aV > PARK_V - 3.5) & (aV <= PARK_V - 2.5) & ((np.floor(Uc) % 4) == 0)) |
                (ea & (Uc > PARK_E - 3.5) & (Uc <= PARK_E - 2.5) & (aV <= PARK_V - 2.5)
                 & ((np.floor(Vc) % 4) == 0)))
        p.fill(cols, G + 1, G + 3, WHITE)
        # 單坡頂：靠外牆的 2 m 在 G+5（底下 G+4 是樑），內緣 G+4
        dist = np.minimum(np.where(band_ns, PARK_V + 1 - aV, 99.0),
                          np.where(band_e, PARK_E + 1 - Uc, 99.0))
        hi = cor & (dist <= 2.0)
        p.layer(hi, G + 4, WHITE)
        p.layer(hi, G + 5, BLUE)
        p.layer(cor & ~hi, G + 4, BLUE)
        # 西南角的牆（OSM）與它在北邊的鏡射
        for poly in self._wall_rings():
            m = fa.polygon(poly)
            p.fill(m, G + 1, G + 4, WHITE)
            p.layer(m, G + 5, BLUE)

    def _wall_rings(self):
        """西南角圍牆的 OSM 輪廓，與它對軸線鏡射到西北角的那一份。"""
        ring = _ring(self.feature(SW_WALL))
        ax = self.axis
        mirror = []
        for x, z in ring:
            u, v = ax.local(x - 0.5, z - 0.5)          # local() 量格心，點要先扣半格
            mirror.append(ax.world(u, -v))
        return [ring, mirror]

    # ---------------------------------------------------------------- 牌樓
    def _gate(self, w):
        """自由廣場牌樓：五間六柱十一樓，高 30 m、寬 80 m（含屋簷）。"""
        G = self.G
        # 照片量的比例（以總高 30 m 換算）：柱腳須彌座約 5 m；門洞只占下半，上面是
        # 很高的雕花牆；每一間的屋頂在牆頂的斗拱上，柱頂上的小屋頂（夾樓、邊樓）比兩側
        # 的屋頂低、從牆面凸出來
        c, s2, o = GATE_PILLARS
        pillars = [(-o, 17), (-s2, 18), (-c, 18), (c, 18), (s2, 18), (o, 17)]
        bays = []
        edges = [-o, -s2, -c, c, s2, o]
        tops = {0: (10.5, 23), 1: (9, 21), 2: (8, 19.5)}          # (起拱高, 牆頂高)
        for i in range(5):
            a, b = edges[i], edges[i + 1]
            cen = (a + b) / 2.0
            half = (b - a) / 2.0 - 1.75
            spring, top = tops[abs(i - 2)]
            bays.append((cen, half, spring, top))
        R = PK.Roof
        roofs = [R(0.0, 7.9, 5.4, 25, 3.6),                                 # 明樓（正中）
                 R(-15.425, 6.3, 5.0, 23, 3.3), R(15.425, 6.3, 5.0, 23, 3.3),       # 次樓
                 R(-28.025, 4.9, 4.7, 21.5, 3.0), R(28.025, 4.9, 4.7, 21.5, 3.0),   # 梢樓
                 R(-c, 2.4, 3.6, 19.5, 2.6), R(c, 2.4, 3.6, 19.5, 2.6),           # 夾樓
                 R(-s2, 2.4, 3.6, 19.5, 2.6), R(s2, 2.4, 3.6, 19.5, 2.6),
                 R(-o - 0.6, 3.0, 3.6, 18.5, 2.6), R(o + 0.6, 3.0, 3.6, 18.5, 2.6)]  # 邊樓
        PK.paifang(w, self.fg, G, pillars, bays, roofs, pedestal=(2.6, 3.6, 5))
        # 匾：「自由廣場」，街道側與廣場側各一面（明間門洞上方）
        for sgn in (1, -1):
            x, z = self.fg.cell(0.0, sgn * 2.6)
            fx, fz = self.fg.dir(0.0, sgn)
            w.sign(x, G + 19, z, ["", "自由廣場", "", ""], facing=(fx, fz), kind="wall",
                   wood="birch", color="black")

    def _side_gates(self, w):
        """大忠門（北）、大孝門（南）：三間的白牆藍瓦門樓，照 OSM 輪廓放。"""
        G = self.G
        R = PK.Roof
        for osm in (LOYALTY, PIETY):
            ring = _ring(self.feature(osm))
            c = PK.ring_centroid(ring)
            fr = Frame(c[0], c[1], self.theta, 16)       # u 沿迴廊、v 穿過門洞
            pillars = [(-9.2, 8), (-3.4, 10), (3.4, 10), (9.2, 8)]
            bays = [(-6.3, 1.15, 4, 8), (0.0, 1.65, 6, 10), (6.3, 1.15, 4, 8)]
            roofs = [R(-7.2, 3.6, 3.2, 10, 2.5), R(7.2, 3.6, 3.2, 10, 2.5),
                     R(0.0, 5.0, 3.6, 12, 3.0)]
            PK.paifang(w, fr, G, pillars, bays, roofs, pillar_w=1.8, pillar_d=3.0, wall_d=2.4,
                       pedestal=(1.3, 1.9, 2), scrolls=False)

    # ---------------------------------------------------------------- 紀念堂
    def _hall(self, w):
        G, fr = self.G, self.fh
        p = Painter(w, fr)
        U, V = fr.U, fr.V
        aU, aV = np.abs(U), np.abs(V)
        A = np.maximum(aU, aV)
        mn = np.minimum(aU, aV)

        # ---- 三層台基（14.5 m）：外層 ±61.8（OSM）、中層 ±50（OSM 最外一層台基的內緣）、上層 ±38
        t1, t2, t3 = A <= 61.8, A <= 50.0, A <= 38.0
        tongue = (U >= -85.4) & (U <= -37.5) & (aV <= 19.9)
        top = np.where(t3, G + 14, np.where(t2, G + 9, G + 4))
        base = t1 & ~tongue
        p.fill(base, G + 1, top - 1, WHITE)
        p.fill(base, top, top, FLOOR)
        skip = kit.dilate(tongue, 1)
        PK.balustrade(p, t1 & ~tongue, G + 5, WHITE, PILLAR, WSLAB, skip=skip)
        PK.balustrade(p, t2 & ~tongue, G + 10, WHITE, PILLAR, WSLAB, skip=skip)
        PK.balustrade(p, t3 & ~tongue, G + 15, WHITE, PILLAR, WSLAB, skip=skip | (A <= 36))

        # ---- 正面大階梯：兩段各 14 個半階（每階 0.5 m，共 14 m），中間平台；正中是白色御路
        s1 = PK.half_flight(U + 85.4, 0.0, 14)
        s2 = PK.half_flight(U + 67.4, 7.0, 14)
        s = np.where(U < -71.4, s1, np.where(U < -67.4, 7.0, np.where(U < -53.4, s2, 14.0)))
        body = tongue & (aV <= 18.9)
        yulu = body & (aV <= 5.5)
        PK.steps(p, body & ~yulu, G, s, GRANITE, GRANITE_S)
        PK.steps(p, yulu, G, s, WHITE, WSLAB)
        # 御路的國徽：中間平台上一圈藍、中心白
        d0 = np.hypot(U + 69.4, V)
        p.layer(yulu & (d0 <= 2.2), G + 7, BLUE_G)
        p.layer(yulu & (d0 <= 1.0), G + 7, WHITE)
        # 御路兩側的矮欄與兩邊的白色擋牆
        sep = tongue & (aV > 5.5) & (aV <= 6.4)
        p.fill(sep, G + 1, G + np.floor(s).astype(int) + 1, WHITE)
        cheek = tongue & (aV > 18.9)
        ci = G + np.ceil(s).astype(int)
        p.fill(cheek, G + 1, ci, WHITE)
        PK.balustrade(p, cheek, ci + 1, WHITE, PILLAR, WSLAB, every=2)

        # ---- 堂身（24 m）：四角是往上收分的墩（外緣從 27 m 收到 24.5 m），中段牆面 ±24.4
        room = A <= 21.0
        yc = G + 25                       # 門洞起拱高度：門洞 G+15..G+30，高 16 m
        for k in range(24):
            y = G + 15 + k
            R = 27.0 - 2.5 * k / 23.0
            bd = (A <= 23.4) | ((mn >= 12.2) & (A <= R))       # 中段比四角的墩凹進一格
            if k >= 22:
                bd = A <= 25.4            # 簷下的線腳
            if y <= G + 33:
                shell = bd & ~room
            else:
                shell = bd
            # 正門：下方上圓的門洞，穿過整道牆
            if y <= yc:
                door = aV <= 5.0
            else:
                door = V ** 2 + (y - yc) ** 2 <= 25.5
            door = door & (U < -19.0)
            p.layer(shell & ~door, y, WHITE)
            # 其他三面的盲拱（凹進一格）
            for along, depth in ((V, U), (U, V), (U, -V)):
                if y <= yc:
                    arch = np.abs(along) <= 5.0
                else:
                    arch = along ** 2 + (y - yc) ** 2 <= 25.5
                p.layer(arch & (depth > 22.4) & (depth <= 23.4) & (mn < 12.2), y, kit.AIR)
                p.layer(arch & (depth > 21.4) & (depth <= 22.4) & (mn < 12.2), y, WHITE2)
            # 門框（券面）：比牆面凸出一格
            if y <= yc:
                fr_m = (aV > 5.0) & (aV <= 6.5)
            else:
                r2 = V ** 2 + (y - yc) ** 2
                fr_m = (r2 > 25.5) & (r2 <= 42.5)
            p.layer(fr_m & (U >= -24.4) & (U < -23.4), y, TRIM)
            # 打開的青銅門扇：貼在門洞兩側的內牆上
            if y <= G + 29:
                p.layer((U >= -21.9) & (U < -21.0) & (aV > 5.0) & (aV <= 10.0), y, BRONZE)
        # 匾（門洞上方、簷下）：藍框紅底
        pl = (U >= -24.4) & (U < -23.4) & (aV <= 2.6)
        for y in range(G + 32, G + 38):
            edge = (y in (G + 32, G + 37)) | (aV > 1.6)
            p.layer(pl & edge, y, BLUE_G)
            p.layer(pl & ~edge, y, B + "red_terracotta")

        # ---- 大廳：地板、紅地毯、藻井、燈、銅像
        p.layer(room & (aV <= 1.5) & (U >= -21.0) & (U <= 10.5), G + 15, B + "red_carpet")
        rr8 = fr.ngon_radius(8)
        ceil_lamp = room & (A <= 20.0) & (rr8 > 10.0) & ((np.floor(U) % 5) == 0) & ((np.floor(V) % 5) == 0)
        p.layer(ceil_lamp, G + 34, LAMP)
        # 藻井：三層內收的八角井，最上面是青天白日十二道光芒
        p.layer(rr8 <= 9.0, G + 34, kit.AIR)
        p.layer((rr8 <= 9.0) & (rr8 > 8.0), G + 35, GOLD)
        p.layer(rr8 <= 8.0, G + 35, kit.AIR)
        p.layer((rr8 <= 8.0) & (rr8 > 7.0), G + 36, LAMP)
        p.layer(rr8 <= 7.0, G + 36, kit.AIR)
        r = np.hypot(U, V)
        ang = np.degrees(np.arctan2(V, U)) / 30.0
        frac = np.abs(ang - np.round(ang))
        ray = (r > 2.6) & (r <= 5.6) & (frac <= 0.28 * (1 - (r - 2.6) / 3.0))
        sun = (r <= 2.6) | ray
        p.layer(rr8 <= 7.0, G + 37, BLUE)
        p.layer((rr8 <= 7.0) & sun, G + 37, B + "white_concrete")
        # 後牆：銅像背後三塊金色匾（倫理、民主、科學）
        back = (U > 20.0) & (U <= 21.0)            # 貼在後牆內面，凸進大廳一格
        for c in (-8.5, 0.0, 8.5):
            m = back & (np.abs(V - c) <= 1.6)
            p.fill(m, G + 27, G + 29, GOLD)
        # 銅像：須彌座 3 m、坐姿 6 m（公開資料 6.3 m）
        plinth = (U >= 11.5) & (U <= 18.5) & (aV <= 4.5)
        p.fill(plinth, G + 15, G + 17, WHITE2)
        p.layer(plinth & ~kit.erode(plinth, 1), G + 17, TRIM)
        PK.seated_statue(p, 15.0, 0.0, G + 18, (-1.0, 0.0), BRONZE, BRONZE2)

        # ---- 屋頂：四角墩頂是平台，中間是八角重簷
        p.layer(A <= 25.4, G + 38, WHITE)
        sb = (rr8 > 23.5) & (rr8 <= 24.6)
        PK.band(p, sb, G + 39, G + 40, TEAL, WHITE)
        hl, hips = PK.octagon(fr, 25.6, 30.0, profile=1.5, lift=1.3)
        lr = (rr8 <= 25.6) & (rr8 >= 18.0)
        PK.roof(p, lr, G + 41, hl, BLUE, shell=2, under=WHITE, rim=WHITE, rim_under=WHITE,
                ridge=BLUE_G, ridge_mask=hips & ~kit.ring(lr))
        drum = (rr8 > 16.5) & (rr8 <= 18.0)
        p.fill(drum, G + 41, G + 46, WHITE)
        PK.band(p, drum, G + 47, G + 48, TEAL, WHITE)
        p.layer(drum, G + 49, WHITE)
        p.layer(rr8 <= 16.5, G + 49, WHITE)
        hu, hips2 = PK.octagon(fr, 22.4, 14.6, profile=1.8, lift=1.8)
        ur = rr8 <= 22.4
        PK.roof(p, ur, G + 50, hu, BLUE, shell=2, under=WHITE, rim=WHITE, rim_under=WHITE,
                ridge=BLUE_G, ridge_mask=hips2 & ~kit.ring(ur) & (rr8 > 1.5))
        # 寶頂：金色，頂端離地 70 m
        near = np.hypot(U, V)
        p.fill(near <= 1.3, G + 63, G + 65, GOLD)
        PK.sphere(p, 0.0, 0.0, G + 67.5, 2.5, GOLD, y_min=G + 65)
        p.layer(near <= 0.8, G + 70, GOLD)


BUILDS = {"cks_memorial": CksMemorial}
