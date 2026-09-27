#!/usr/bin/env python3
"""西門紅樓（原新起街市場，1908）：八角樓與十字樓。

位置與輪廓：OSM way/222080307 —— 東端一座八角形，西邊接一條長廊，長廊在靠西的地方
與一條南北向的橫翼交叉成十字。長相照公開資料：
  · 近藤十郎設計，1908 年落成；紅磚造、二層樓的八角形洋式建築，屋頂是八角攢尖頂，
    牆面以紅磚與白色粉刷相間做成帶狀飾（中文維基百科「西門紅樓」、交通部觀光署景點介紹）
  · 八角樓每一正立面 8 m、占地 412 m²；前門、後門之外還有一門直通十字樓；屋頂的鋼骨
    桁架像雨傘骨一樣放射，中央有圓形光源照亮一樓（中文維基百科）
  · 十字樓：十字交叉處不在對稱的中點、較靠西；南北兩側緊鄰廣場；磚牆厚 49 cm，
    15 m 的大跨距完全靠加強磚造的承重牆與扶壁（中文維基百科）
八角形的邊心距用 11.2 m（412 m² 的正八角形；OSM 描的輪廓約 11.5 m，含出簷），
八角樓屋頂中央的採光塔、正面入口上的山頭與圓窗是照片上看得到的造型，尺寸是估的。
局部座標：原點是八角樓的中心，u 沿十字樓的長軸指向八角樓的正面（東南東，偏 15.1°），
v 是 u 往南轉 90°。十字樓各段的位置由 OSM 頂點量來（見常數）。
"""
import math

import numpy as np

from mrt.application.attractions import colonial_kit as CK
from mrt.application.attractions import kit
from mrt.application.attractions.kit import AIR, Attraction, Frame, Spot, erode, dilate

# ---- 材質 ----
BRICK = "minecraft:bricks"
WHITE = "minecraft:smooth_quartz"          # 白色粉刷的帶狀飾、窗框、簷口
BAND = "minecraft:calcite"
PLINTH = "minecraft:polished_andesite"
GLASS = "minecraft:gray_stained_glass"
ROOF = "minecraft:deepslate_tiles"          # 深灰的屋瓦
ROOF_SLAB = "deepslate_tile_slab"
ROOF_STAIR = "deepslate_tile_stairs"
PAVE = "minecraft:polished_andesite"
PAVE2 = "minecraft:stone_bricks"

# ---- 八角樓（離地面幾格）----
A_WALL = 11.2           # 外牆邊心距（每邊約 9.3 m）
A_EAVE = 12.0           # 出簷
H_BAND1 = 7             # 一、二樓之間的白色腰帶
H_CORNICE = 13          # 簷口
H_ROOF0 = 14            # 屋頂起點
ROOF_SLOPE = 0.55
A_LANTERN = 3.4         # 採光塔邊心距
H_LANTERN = (18, 21)    # 採光塔的牆（開窗）
H_TOP = 27              # 尖頂（避雷針）
HALF_FACE = A_WALL * math.tan(math.radians(22.5))    # 每一面半寬 4.64 m

# ---- 十字樓（局部座標；OSM 頂點量來，以八角樓中心為原點）----
ARM_V = (0.45, 4.2)     # 長廊中線與半寬（OSM v -3.3～5.1，跟八角樓的中線差 0.9 m，取一半）
ARM_U = (-79.9, -A_WALL + 0.5)      # 長廊從西端到八角樓的西牆
CROSS_U = (-62.7, -52.2)            # 橫翼（OSM u -62.7～-52.2）
CROSS_V = (-23.45, 24.35)           # 橫翼南北端（OSM v -22.6～25.2，長度不變、對齊長廊中線）
H_HALL = 8              # 十字樓外牆頂（單層大跨距）
H_HALL_ROOF = 10        # 十字樓屋頂起點
BAY = 4.0               # 扶壁間距


class RedHouse(Attraction):
    height_m = None         # 沒有公開的高度數字（verify_attractions 也不驗）
    margin = 14

    def __init__(self, item):
        super().__init__(item)
        main = self.feature("way/222080307") or (self.mains() or [None])[0]
        self.outer = max(main["outer"], key=len) if main and main.get("outer") else self.outline()
        self.angle = CK.fit_angle(self.outer)
        f0 = Frame(0.0, 0.0, self.angle, 1)
        L = [CK.to_local(f0, x, z) for x, z in self.outer]
        umax = max(p[0] for p in L)
        octv = [p for p in L if p[0] > umax - 25.0]          # 東端 25 m 內的頂點 = 八角形
        cu = (min(p[0] for p in octv) + max(p[0] for p in octv)) / 2.0
        cv = (min(p[1] for p in octv) + max(p[1] for p in octv)) / 2.0
        self.origin = f0.world(cu, cv)

    def spot_uv(self):
        """預設觀景點：八角樓正面的紅樓廣場上，離正門約 19 m。"""
        return (30.0, 0.0)

    def bbox(self):
        x0, z0, x1, z1 = super().bbox()
        fr = Frame(self.origin[0], self.origin[1], self.angle, 1)
        sx, sz = fr.world(*self.spot_uv())
        return (min(x0, int(sx) - 6), min(z0, int(sz) - 6), max(x1, int(sx) + 6), max(z1, int(sz) + 6))

    def plan(self, site):
        self.fr = fr = Frame(self.origin[0], self.origin[1], self.angle, 84)
        U, V = fr.U, fr.V
        self.oct = fr.ngon(8, A_WALL)
        vc, hw = ARM_V
        self.arm = (U >= ARM_U[0]) & (U <= ARM_U[1]) & (np.abs(V - vc) <= hw)
        self.cross = (U >= CROSS_U[0]) & (U <= CROSS_U[1]) & (V >= CROSS_V[0]) & (V <= CROSS_V[1])
        self.hall = (self.arm | self.cross) & ~self.oct
        self.foot = self.oct | self.hall
        self.g0 = site.level(fr, self.foot)
        self.site = site
        # 廣場：八角樓正面往東 22 m（紅樓廣場），十字樓南北兩側（南、北廣場）。
        # 地面高度要在 plan 裡查好（cli 在 plan_all 之後就清掉地形的快取）
        self.front = (U >= 0) & (U <= 34.0) & (np.abs(V) <= 24.0)
        self.yard = dilate(self.foot, 5) | self.front
        site.grid(fr, self.yard)
        su, sv = self.spot_uv()
        sx, sz = fr.cell(su, sv)
        sy = site.g(sx, sz) + 1
        tx, tz = fr.world(0.0, 0.0)
        yaw, pitch = kit.look(sx, sy, sz, tx, self.g0 + 11, tz)
        self._spots = [Spot("", sx, sy, sz, yaw, pitch, self.name_zh, self.name_en)]

    def plaque(self):
        return [self.name_zh, self.name_en, "1908 年落成", "近藤十郎設計八角樓"]

    def top_y(self):
        return None if self.g0 is None else self.g0 + H_TOP

    # ---- 蓋 ----
    def build(self, w):
        fr, g0 = self.fr, self.g0
        m = CK.Mason(w, fr)
        U, V = fr.U, fr.V
        front = self.front
        self.site.prepare(w, fr, self.yard, g0, top=PAVE, clear=40)
        R = np.hypot(U, V)
        rays = (np.abs(((np.degrees(np.arctan2(V, U)) + 11.25) % 22.5) - 11.25) < 1.2) & (R > A_EAVE + 1)
        m.fill(front & (rays | ((R > 17.5) & (R < 18.6))), g0, g0, PAVE2)
        self._octagon(m)
        self._hall(m)

    # ---- 八角樓 ----
    def _oct_pattern(self, face, t, h, layer, u, v, q=None):
        """八角樓的一面（face = 0 是正面、朝 +u；1～7 逆著 u→v 轉）：
        一樓兩扇拱窗（正面是 3 格寬的拱門）、白色腰帶、二樓兩扇拱窗（正面三扇窄窗），
        轉角是紅磚夾白帶的隅柱，窗間牆在拱腳的高度多一道細白帶。"""
        at = abs(t)
        if h == 1:
            return PLINTH if layer == 0 else BRICK
        if h == H_BAND1:
            return WHITE if layer == 0 else BRICK
        if h == H_CORNICE - 1:                               # 簷下的齒飾：白、紅相間
            return WHITE if (layer == 0 and math.floor(t) % 2 == 0) else BRICK
        corner = at > HALF_FACE - 0.7
        if corner:
            if layer:
                return BRICK
            return BAND if h % 3 == 0 else BRICK
        if face == 0:
            door = at <= 1.5 and 2 <= h <= 5
            win2 = (at <= 0.5 or 1.5 <= at <= 2.5) and 9 <= h <= 11
            if door:
                return AIR if layer == 0 or h <= 5 else BRICK
            if at <= 1.5 and h == 6:
                return WHITE                                 # 門楣
            if win2:
                return GLASS if layer else AIR
            if (at <= 0.5 or 1.5 <= at <= 2.5) and h == 12:
                return WHITE
        else:
            win = 0.5 <= at <= 2.5
            if win and (3 <= h <= 5 or 9 <= h <= 11):
                if layer:
                    return GLASS
                return AIR
            if win and h in (6, 12):
                return WHITE if layer == 0 else BRICK        # 拱窗頂的白色楔石
        if layer:
            return BRICK
        if h in (4, 10):
            return BAND                                       # 拱腳高度的細白帶
        return BRICK

    def _octagon(self, m):
        fr, g0 = self.fr, self.g0
        octm = self.oct
        m.fill(octm, g0 + 1, g0 + 1, PLINTH)
        m.facade(octm, g0 + 1, g0 + H_CORNICE - 1, self._oct_pattern, base=g0, ngon=(8, 0.0, 0.0, 0.0))
        m.fill(erode(octm, 2), g0 + H_BAND1, g0 + H_BAND1, "minecraft:spruce_planks")   # 二樓（劇場）樓板
        # 簷口：白色、出挑到 A_EAVE
        eave = fr.ngon(8, A_EAVE)
        m.fill(eave, g0 + H_CORNICE, g0 + H_CORNICE, WHITE)
        m.fill(eave & ~octm, g0 + H_CORNICE - 1, g0 + H_CORNICE - 1, CK.slab("smooth_quartz_slab", "top"))
        # 八角攢尖頂（雨傘骨般放射的鋼桁架屋頂），中央留給採光塔
        rr = fr.ngon_radius(8)
        h = ((A_EAVE - rr) * ROOF_SLOPE).clip(0, None)
        roofm = eave & ~fr.ngon(8, A_LANTERN - 0.5)
        m.roof(roofm, g0 + H_ROOF0, h, ROOF, slab_name=ROOF_SLAB, shell=2)
        # 八條屋脊：淺灰的壓脊（沿八個頂點方向），八角形的屋頂才看得出來
        for k in range(8):
            ph = math.radians(22.5 + 45 * k)
            R = A_EAVE / math.cos(math.radians(22.5))
            for i in range(0, int(R - A_LANTERN)):
                r = R - i
                rr_ = r * math.cos(math.radians(22.5))
                y = g0 + H_ROOF0 + int(math.floor((A_EAVE - rr_) * ROOF_SLOPE))
                m.at(r * math.cos(ph), r * math.sin(ph), y + 1, CK.slab("polished_andesite_slab"))
        # 採光塔：白色八角筒、四面開窗，深灰八角尖頂、避雷針
        lan = fr.ngon(8, A_LANTERN)

        def lantern(face, t, h, layer, u, v, q=None):
            if abs(t) < 0.8 and H_LANTERN[0] + 1 <= h <= H_LANTERN[1] - 1:
                return GLASS
            return WHITE

        m.facade(lan, g0 + H_LANTERN[0] - 1, g0 + H_LANTERN[1], lantern, base=g0, layers=1, ngon=(8, 0.0, 0.0, 0.0))
        m.fill(erode(lan, 1), g0 + H_LANTERN[0] - 1, g0 + H_LANTERN[1], AIR)
        cap = fr.ngon(8, A_LANTERN + 0.7)
        m.fill(cap, g0 + H_LANTERN[1] + 1, g0 + H_LANTERN[1] + 1, WHITE)
        hc = ((A_LANTERN + 0.4 - rr) * 1.0).clip(0, None)
        m.roof(fr.ngon(8, A_LANTERN + 0.4), g0 + H_LANTERN[1] + 2, hc, ROOF, slab_name=ROOF_SLAB, shell=1)
        top = g0 + H_LANTERN[1] + 2 + int(A_LANTERN + 0.4)
        for y in range(top, g0 + H_TOP):
            m.at(0.0, 0.0, y, ROOF if y < g0 + H_TOP - 1 else "minecraft:polished_deepslate_wall")
        m.at(0.0, 0.0, g0 + H_TOP, "minecraft:waxed_lightning_rod[facing=up,powered=false]")
        # 一樓中央的圓形光源（屋頂採光照到一樓）：天花中央一圈燈
        m.fill(fr.ngon(8, 1.5), g0 + H_BAND1, g0 + H_BAND1, "minecraft:glass")
        m.fill(fr.ngon(8, 2.5) & ~fr.ngon(8, 1.5), g0 + H_CORNICE, g0 + H_CORNICE, "minecraft:sea_lantern")
        # 正面入口：三角山頭（紅磚、白色斜邊）與圓窗，招牌
        self._front_gable(m)

    @staticmethod
    def _front_block(v, h, outer):
        """正面凸出的入口間（每一格離中線 |v|、離地 h；outer = 最外那一層）。"""
        at = abs(v)
        if h == 1:
            return PLINTH
        if h in (H_BAND1, H_CORNICE):
            return WHITE
        if h == H_CORNICE - 1:
            return WHITE if math.floor(v) % 2 == 0 else BRICK
        if at > HALF_FACE - 1.2 and outer:                   # 入口間兩側的隅柱
            return BAND if h % 3 == 0 else BRICK
        if at <= 1.5 and 2 <= h <= 5:
            return AIR                                       # 3 格寬的正門
        if at <= 1.5 and h == 6:
            return WHITE                                     # 門楣
        if (at <= 0.5 or 1.5 <= at <= 2.5) and 9 <= h <= 11:
            return AIR if outer else GLASS                   # 二樓三扇窄窗
        if (at <= 0.5 or 1.5 <= at <= 2.5) and h == 8:
            return WHITE                                     # 窗台
        if h in (4, 10) and outer:
            return BAND
        return BRICK

    def _front_gable(self, m):
        """正面（朝紅樓廣場）的入口間：往前凸出 1 m，上面一座紅磚三角山頭（白色斜邊、
        中央圓窗）高出屋簷。"""
        fr, g0 = self.fr, self.g0
        U, V = fr.U, fr.V
        hw = HALF_FACE - 0.4
        bay = (U >= A_WALL - 0.6) & (U <= A_WALL + 1.2) & (np.abs(V) <= hw)
        for x, z in fr.cells(bay):
            u, v = fr.local(x, z)
            outer = u > A_WALL + 0.2
            for h in range(1, H_CORNICE + 1):
                m.set(x, g0 + h, z, self._front_block(v, h, outer))
        u0 = A_WALL + 0.7
        y = g0 + H_CORNICE + 1
        m.gable(-hw, hw, A_WALL + 0.2, A_WALL + 1.2, y, 5.5, BRICK, edge="smooth_quartz_stairs", axis="v")
        m.gable(-hw + 0.5, hw - 0.5, A_WALL - 3.0, A_WALL + 0.2, y, 5.0, ROOF, axis="v")
        # 山頭中央的圓窗（白框）
        for dv in (-1.0, 0.0, 1.0):
            for dy in (1, 2, 3):
                m.at(u0, dv, y + dy, GLASS if (dv == 0.0 and dy == 2) else WHITE)
        # 門前一級台階
        for dv in np.arange(-2.0, 2.5, 1.0):
            m.at(A_WALL + 1.7, dv, g0 + 1, CK.stair("polished_andesite_stairs", m.facing(-1, 0)))
        # 招牌（門楣上方、二樓窗下）：壁掛告示牌，第一行是名字（不以「出口」開頭）
        x, z = fr.cell(A_WALL + 1.7, 0.0)
        m.w.sign(x, g0 + 7, z, ["西門紅樓", "The Red House", "1908", ""], facing=fr.dir(1.0, 0.0),
                 wood="dark_oak", kind="wall", glow=True, color="white")

    # ---- 十字樓 ----
    def _hall_pattern(self, face, t, h, layer, u, v, q=None):
        """十字樓：單層紅磚牆，扶壁之間一扇 2 m 寬的拱窗，窗頂白色楔石，牆頂白色簷帶。"""
        if h == 1:
            return PLINTH if layer == 0 else BRICK
        if h == H_HALL:
            return WHITE if layer == 0 else BRICK
        p = t % BAY
        win = 1.0 <= p < 3.0 and 3 <= h <= 6
        if win:
            return GLASS if layer else AIR
        if layer:
            return BRICK
        if 1.0 <= p < 3.0 and h == 7:
            return WHITE
        if h == 4 and not (1.0 <= p < 3.0):
            return BAND
        if q is not None and q < 1.6 and h % 2 == 0:
            return BAND
        return BRICK

    def _hall(self, m):
        """十字樓：單層紅磚大跨距（扶壁撐著），長廊與橫翼各一道兩坡屋頂、交叉處相貫，
        三個山牆端各開一扇小圓窗。"""
        fr, g0 = self.fr, self.g0
        U, V = fr.U, fr.V
        hall = self.hall
        corners = [(ARM_U[0], ARM_V[0] - ARM_V[1]), (ARM_U[0], ARM_V[0] + ARM_V[1]),
                   (CROSS_U[0], CROSS_V[0]), (CROSS_U[1], CROSS_V[0]),
                   (CROSS_U[0], CROSS_V[1]), (CROSS_U[1], CROSS_V[1])]
        m.fill(hall, g0 + 1, g0 + 1, PLINTH)
        m.facade(hall, g0 + 1, g0 + H_HALL, self._hall_pattern, base=g0, corners=corners)
        # 扶壁：長牆外側每 4 m 一根，頂上白色斜帽
        out = dilate(hall, 1) & ~hall & ~dilate(self.oct, 2)
        for x, z, u, v, face, t in m.ring_cells(dilate(hall, 1)):
            if not out[z - fr.z0, x - fr.x0]:
                continue
            if (t % BAY) < 0.5 or (t % BAY) >= BAY - 0.5:
                for y in range(g0 + 1, g0 + 7):
                    m.set(x, y, z, BRICK)
                m.set(x, g0 + 7, z, CK.stair("smooth_quartz_stairs", m.facing(-face[0], -face[1])))
        # 兩坡屋頂：長廊的屋脊沿 u、橫翼的屋脊沿 v，交叉處取高的
        vc, hw = ARM_V
        cu0, cu1 = CROSS_U
        chw = (cu1 - cu0) / 2.0
        h_arm = np.where(self.arm, 4.5 * (1 - np.abs(V - vc) / (hw + 0.6)), -1.0)
        h_cross = np.where(self.cross, 5.0 * (1 - np.abs(U - (cu0 + cu1) / 2.0) / (chw + 0.6)), -1.0)
        h = np.maximum(h_arm, h_cross).clip(0, None)
        roofm = dilate(hall, 1) & ~dilate(self.oct, 0)
        hh = np.where(hall, h, 0.0)
        # 牆頂白色簷帶，外面出簷一格（倒吊的半磚）
        m.fill(hall, g0 + H_HALL + 1, g0 + H_HALL + 1, WHITE)
        eave = roofm & ~hall
        m.fill(eave, g0 + H_HALL + 1, g0 + H_HALL + 1, CK.slab(ROOF_SLAB, "top"))
        # 山牆：屋頂底下整個填磚（兩端的三角形山牆就出來了），再鋪屋瓦
        top = g0 + H_HALL_ROOF + np.floor(hh).astype(int) - 1
        m.fill(hall, g0 + H_HALL_ROOF, top, BRICK)
        m.roof(hall, g0 + H_HALL_ROOF, hh, ROOF, slab_name=ROOF_SLAB, stair_name=ROOF_STAIR, shell=1)
        # 山牆頂的白色壓頂與圓窗：長廊西端、橫翼南北兩端
        for cu, cv in ((ARM_U[0] + 0.5, vc), ((cu0 + cu1) / 2.0, CROSS_V[0] + 0.5),
                       ((cu0 + cu1) / 2.0, CROSS_V[1] - 0.5)):
            m.at(cu, cv, g0 + H_HALL_ROOF + 2, WHITE)
            m.at(cu, cv, g0 + H_HALL_ROOF + 1, GLASS)
            m.at(cu, cv, g0 + H_HALL_ROOF, WHITE)


BUILDS = {"red_house": RedHouse}
