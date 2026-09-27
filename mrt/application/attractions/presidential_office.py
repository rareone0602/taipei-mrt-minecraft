#!/usr/bin/env python3
"""總統府（原臺灣總督府，1919）。

位置、方位、輪廓：OSM relation/206817（日字形外環 + 南北兩個中庭）與它的 building:part
（塔樓 way/368582924 height=60、四角與後側 6 層的角樓、正面的車寄、角落的半圓門廊）。
長相照公開資料：
  · 正面朝東、正面長約 140 m、側面寬約 85 m、中央塔高約 60 m（相當 11 層樓），
    主體 5 層；日字形平面、東西向中軸把中庭分成南北兩個
    （總統府網站〈建築之美〉〈總統府的誕生〉、中文維基百科「總統府 (臺灣)」）
  · 後期文藝復興的「辰野式」：紅色面磚與灰白洗石子排成紅白相間的橫向飾帶、
    圓拱窗、四角的角塔、中央塔兩側的衛塔、正門的車寄（戰後改成平頂）、
    塔樓由方形轉為八角形（同上）
  · 長野宇平治原設計、森山松之助修改，1912 年動工、1919 年落成（英文維基百科）
OSM 輪廓的主軸偏 5.7°（投影後），整座在這個角度的局部座標裡蓋：u 朝東（正面）、
v 朝南，原點是外環的東西中點與塔樓的南北中線。下面的數字都是這個座標系的公尺，
由 OSM 的 building:part 量來（見各常數的註解），外牆本身直接用 OSM 外環。
"""
import math

import numpy as np

from mrt.application.attractions import colonial_kit as CK
from mrt.application.attractions import kit
from mrt.application.attractions.kit import AIR, Attraction, Frame, Spot, erode, dilate

# ---- 材質 ----
BRICK = "minecraft:bricks"                    # 紅色面磚（OSM building:colour #a25344）
BAND = "minecraft:calcite"                    # 灰白洗石子的飾帶
STONE = "minecraft:smooth_quartz"             # 白色石材：簷口、柱子、塔頂（OSM roof:colour #ffffff）
PLINTH = "minecraft:polished_andesite"        # 粗面砌築的基座
GLASS = "minecraft:gray_stained_glass"
ROOF = "minecraft:waxed_weathered_cut_copper"  # 銅板屋頂（OSM roof:colour #bed0bd 的灰綠）；上蠟才不會繼續氧化
ROOF_SLAB = "waxed_weathered_cut_copper_slab"
ROOF_STAIR = "waxed_weathered_cut_copper_stairs"
FLOOR = "minecraft:smooth_stone"
PORCH_ROOF = "minecraft:granite"              # 車寄與半圓門廊的屋頂（OSM roof:colour #a25344）

# ---- 高度（離地面幾格；地面 = g0 那一格）----
H_PLINTH = 1            # 基座頂 = 一樓樓板
H_FLOORS = (1, 6, 11, 16)   # 一～四樓樓板
H_CORNICE = 21          # 主體簷口（四層外牆之上，五樓在銅板的馬薩式屋頂裡）
H_ROOF = 4.0            # 主體屋頂比簷口高多少（屋脊 +26，角塔的攢尖頂從 +26 起）
H_PAVILION = 25         # 角塔與後側中央樓（OSM 6 層）的簷口
H_GUARD = 26            # 正門兩側衛塔的簷口
H_TOWER = 60            # 中央塔頂（OSM height=60、總統府網站「約 60 公尺」）

# ---- 平面（局部座標，公尺；OSM 量來）----
TOWER_U, TOWER_A, TOWER_N = 29.65, 4.15, 1.2   # 塔樓 way/368582924：u 25.5～33.8、v ±4.2，四角各缺 1.2 m（亞字形）
EAST = 37.5             # 東立面（外環 u 36.8～38.4）
WEST = -37.7            # 西立面
CORNER_U = (24.4, -26.7)    # 四角角塔：北、南立面凸出的那一段從這裡開始（外環 u 24.4／-26.7）
CORNER_V = 48.6         # 東、西立面的角塔從 |v| >= 48.6 開始（外環 v ±48.6～±49.5）
GUARD_V = (7.2, 13.1)   # 正門兩側衛塔（外環 u 41.1～41.5、v ±7～±13.1）
GUARD_U = 33.8          # 衛塔往後接到塔樓東緣
PORCH = (39.8, 52.7, 6.0)   # 車寄 way/548610153 + 548610154：u 39.8～52.7、v ±6
WEST_PAV = (-40.4, -24.2, 7.5)   # 後側中央樓 way/1416563941（u -37.9～-24.2、v ±7）＋外環凸出（u -40.4、v ±13）
WEST_PAV_V = 13.3
CENTER_BAR = (-20.7, 20.8, 12.3)  # 中軸（way/1416563951，3 層、白牆）：u -20.7～20.8、v ±12.3
DOME_HALL = (0.6, 18.0, -8.2, 9.3)     # 中軸上的圓頂大廳 way/1416563952（4 層、roof:shape=dome）
GABLE_HALL = (-17.8, -0.4, -8.3, 9.2)  # 中軸上的山牆大廳 way/1416563942（4 層、gabled）

BAY = 4.0               # 開間：一扇 2 m 寬的窗 + 2 m 的窗間牆


def _poly(f):
    return max(f["outer"], key=len) if f and f.get("outer") else None


class PresidentialOffice(Attraction):
    height_m = float(H_TOWER)
    margin = 16

    def __init__(self, item):
        super().__init__(item)
        main = self.feature("relation/206817") or (self.mains() or [None])[0]
        self.outer = _poly(main) or self.outline()
        self.holes = [r for r in (main.get("inner") or []) if len(r) >= 3] if main else []
        self.angle = CK.fit_angle(self.outer)
        cx, cz = CK.centroid(self.outer)
        f0 = Frame(cx, cz, self.angle, 10)
        u0, u1, _, _ = CK.local_extent(f0, self.outer)
        tower = _poly(self.feature("way/368582924"))
        tv = CK.to_local(f0, *CK.centroid(tower))[1] if tower else 0.0
        self.origin = f0.world((u0 + u1) / 2.0, tv)
        # 半圓門廊（四角、building:part=roof、1 層）與後側的半圓門廊（2 層）
        self.porch_polys = [p for p in (_poly(self.feature(k)) for k in (
            "way/1416563953", "way/1416563944", "way/1416563945", "way/1416563954")) if p]
        self.west_porch = _poly(self.feature("way/1416563938"))

    # ---- 框架介面 ----
    def spot_uv(self):
        """預設觀景點：凱達格蘭大道上、正面往東 38 m，抬頭看得到 60 m 的塔頂。
        （tools/verify_attractions 只讀輪廓外 44 m 以內，觀景點不能更遠。）"""
        return (EAST + 38.0, 0.0)

    def bbox(self):
        x0, z0, x1, z1 = super().bbox()
        fr = Frame(self.origin[0], self.origin[1], self.angle, 1)
        sx, sz = fr.world(*self.spot_uv())
        return (min(x0, int(sx) - 6), min(z0, int(sz) - 6), max(x1, int(sx) + 6), max(z1, int(sz) + 6))

    def plan(self, site):
        ox, oz = self.origin
        self.fr = fr = Frame(ox, oz, self.angle, 72)
        foot = fr.polygon(self.outer)
        for r in self.holes:
            foot &= ~fr.polygon(r)
        self.foot = foot
        self.courts = [fr.polygon(r) for r in self.holes]
        self.g0 = site.level(fr, foot)
        self.site = site
        self.semis = fr.empty()
        for p in self.porch_polys:
            self.semis |= fr.polygon(p)
        self.west_semi = fr.polygon(self.west_porch) if self.west_porch else fr.empty()
        # 中軸（兩個中庭之間）另外蓋；四翼 = 外環扣掉中庭、中軸、半圓門廊
        u0, u1, hv = CENTER_BAR
        self.bar = foot & (fr.U > u0 + 0.5) & (fr.U < u1 - 0.5) & (np.abs(fr.V) <= hv + 0.5)
        self.body = foot & ~self.semis & ~self.west_semi & ~self.bar
        # 整地範圍：外環外擴 3 格、車寄前面。地面高度要在 plan 裡查好 —— cli 在 plan_all
        # 之後就清掉地形的快取，build() 裡再問 site.g 會出錯
        self.yard = dilate(foot | self.semis | self.west_semi, 3) | fr.rect(
            EAST, PORCH[1] + 3, -PORCH[2] - 4, PORCH[2] + 4)
        site.grid(fr, self.yard)
        # 外環的凸角（局部座標）：牆角的白色隅石
        self.corners = CK.convex_corners([CK.to_local(fr, x, z) for x, z in self.outer])
        su, sv = self.spot_uv()
        sx, sz = fr.cell(su, sv)
        sy = site.g(sx, sz) + 1
        yaw, pitch = kit.look(sx, sy, sz, *self._world3(TOWER_U, 0.0, self.g0 + 28))
        self._spots = [Spot("", sx, sy, sz, yaw, pitch, self.name_zh, self.name_en)]

    def _world3(self, u, v, y):
        x, z = self.fr.world(u, v)
        return x, y, z

    def plaque(self):
        return [self.name_zh, self.name_en, "1919 年落成", "中央塔高 60 公尺"]

    # ---- 蓋 ----
    def build(self, w):
        fr, g0 = self.fr, self.g0
        m = CK.Mason(w, fr)
        U, V = fr.U, fr.V
        foot, body = self.foot, self.body
        west_semi = self.west_semi

        # 整地：外環外擴 3 格鋪成廣場（安山岩地坪）
        self.site.prepare(w, fr, self.yard, g0, top="minecraft:polished_andesite", clear=40)
        for c in self.courts:
            self._courtyard(m, c)

        # 主體四翼：四層紅磚牆 + 簷口 + 銅板屋頂
        m.fill(erode(body, 1), g0 + 1, g0 + 1, FLOOR)
        m.facade(body, g0 + 1, g0 + H_CORNICE - 1, self._wing_pattern, base=g0, corners=self.corners)
        for h in H_FLOORS[1:]:
            m.fill(erode(body, 2), g0 + h, g0 + h, FLOOR)
        m.fill(body, g0 + H_CORNICE, g0 + H_CORNICE, STONE)
        self._cornice(m, body, g0 + H_CORNICE)
        d = kit.depth(body).astype(float)
        rise = np.minimum(d, 3.0) + np.clip(d - 3.0, 0, None) * 0.3
        m.roof(body, g0 + H_CORNICE + 1, np.minimum(rise - 1.0, H_ROOF).clip(0, None), ROOF,
               slab_name=ROOF_SLAB, stair_name=ROOF_STAIR, shell=2)
        self._dormers(m, body)

        # 四角角塔（6 層、四角攢尖銅頂）
        for su in (1, -1):
            for sv in (1, -1):
                u_in = CORNER_U[0] if su > 0 else CORNER_U[1]
                zone = body & ((U - u_in) * su >= 0) & (V * sv >= CORNER_V)
                self._pavilion(m, zone, H_PAVILION, rise=8.0, lantern=True)
        # 後側中央樓
        wz = body & (U <= WEST_PAV[1]) & (np.abs(V) <= WEST_PAV_V)
        self._pavilion(m, wz, H_PAVILION, rise=6.0, lantern=False)
        # 正門兩側的衛塔（小圓頂）
        for sv in (1, -1):
            gz = body & (U >= GUARD_U) & (V * sv >= GUARD_V[0]) & (V * sv <= GUARD_V[1])
            self._guard_tower(m, gz, sv)
        # 中軸：三層白牆、兩座大廳（山牆頂與圓頂）
        self._center(m)
        # 中央塔
        self._tower(m)
        # 車寄、半圓門廊
        self._porte_cochere(m)
        for p in self.porch_polys:
            self._semi_porch(m, fr.polygon(p), 6)
        if self.west_porch:
            self._semi_porch(m, west_semi, 11)
        # 正門：一樓中央開 3 格寬的門洞；基座外緣一圈台階（車寄的地坪也高一格）
        m.fill(foot & (U >= EAST - 1.0) & (U <= PORCH[0] + 1.0) & (np.abs(V) <= 1.6), g0 + 2, g0 + 5, AIR)
        porch = fr.rect(PORCH[0], PORCH[1], -PORCH[2], PORCH[2])
        for x, z, u, v, face, t in m.ring_cells(dilate(porch, 1) & ~foot):
            if face[0] < 0:
                continue
            m.set(x, g0 + 1, z, CK.stair("polished_andesite_stairs", m.facing(-face[0], -face[1])))

    # ---- 立面花樣 ----
    def _window(self, face, t, h, layer, rows, top_arch=True, width=2.0, bay=BAY, off=0.0):
        """開間裡的窗：沿牆座標 t 落在窗的範圍、高度 h 在 rows 裡 -> 外層挖空、內層玻璃，
        最上一格外層放倒吊的樓梯做成圓拱。不是窗回 None。"""
        p = (t - off) % bay
        lo = (bay - width) / 2.0
        if not (lo <= p < lo + width) or h not in rows:
            return None
        if layer:
            return GLASS
        if top_arch and h == rows[-1]:
            a = CK.Mason.along(face)
            left = p < lo + width / 2.0
            d = (-a[0], -a[1]) if left else a
            return CK.stair("smooth_quartz_stairs", self._fc(d), "top")
        return AIR

    def _fc(self, d):
        return self.fr.facing(*d)

    @staticmethod
    def _quoin(q, h):
        """牆角的隅石：一皮長（離角 2 格內）一皮短（1 格內），白色洗石子。"""
        return q is not None and (q < 1.6 if h % 2 == 0 else q < 0.8)

    def _wing_pattern(self, face, t, h, layer, u, v, q=None):
        if h == H_PLINTH:
            return PLINTH if layer == 0 else BRICK
        rows = {2: (2, 3, 4), 3: (2, 3, 4), 4: (2, 3, 4), 7: (7, 8, 9), 8: (7, 8, 9), 9: (7, 8, 9),
                12: (12, 13, 14), 13: (12, 13, 14), 14: (12, 13, 14), 17: (17, 18), 18: (17, 18)}.get(h)
        if layer == 0 and q is not None and q < 2.0:
            return BAND if self._quoin(q, h) else BRICK
        if rows:
            b = self._window(face, t, h, layer, rows, top_arch=(h <= 14))
            if b is not None:
                return b
        if layer:
            return BRICK
        p = t % BAY
        if h in (5, 10, 15) and 1.5 <= p < 2.5:      # 拱窗頂上的楔石
            return BAND
        if h in (6, 11, 16, 20):                      # 樓板線的白色飾帶
            return BAND
        return BRICK

    def _pavilion_pattern(self, face, t, h, layer, u, v, q=None):
        """角塔與衛塔：比主體多一層；窗間牆每三皮一道白帶（粗面砌的意思），牆角有隅石。"""
        if h == H_PLINTH:
            return PLINTH if layer == 0 else BRICK
        rows = {2: (2, 3, 4), 3: (2, 3, 4), 4: (2, 3, 4), 7: (7, 8, 9), 8: (7, 8, 9), 9: (7, 8, 9),
                12: (12, 13, 14), 13: (12, 13, 14), 14: (12, 13, 14), 17: (17, 18), 18: (17, 18),
                21: (21, 22, 23), 22: (21, 22, 23), 23: (21, 22, 23)}.get(h)
        if layer == 0 and q is not None and q < 2.0:
            return BAND if self._quoin(q, h) else BRICK
        if rows:
            b = self._window(face, t, h, layer, rows, top_arch=(h <= 14 or h >= 21))
            if b is not None:
                return b
        if layer:
            return BRICK
        p = t % BAY
        if h in (6, 11, 16, 20, 24):
            return BAND
        if h in (5, 10, 15) and 1.5 <= p < 2.5:
            return BAND
        if h in (3, 13) and not (1.0 <= p < 3.0):
            return BAND
        return BRICK

    # ---- 零件 ----
    def _cornice(self, m, mask, y):
        """簷口：牆外一圈倒吊的石材樓梯（出挑 1 m）。"""
        out = dilate(mask, 1) & ~mask
        for x, z, u, v, face, t in m.ring_cells(dilate(mask, 1)):
            if not out[z - self.fr.z0, x - self.fr.x0]:
                continue
            m.set(x, y, z, CK.stair("smooth_quartz_stairs", m.facing(-face[0], -face[1]), "top"))

    def _dormers(self, m, body):
        """屋頂上的老虎窗（銅頂的氣窗）：外立面每兩個開間一座，縮進簷口 1 格。
        中庭那一側、接中軸的那幾面牆不放（往外 3 m 還在建築或中庭裡的就跳過）。"""
        fr, g0 = self.fr, self.g0
        y = g0 + H_CORNICE + 1
        seen = set()
        inside = self.foot | self.bar
        for c in self.courts:
            inside = inside | c
        for x, z, u, v, face, t in m.ring_cells(body):
            p = t % (2 * BAY)
            if not (1.0 <= p < 3.0):
                continue
            cx, cz = fr.cell(u + face[0] * 3.0, v + face[1] * 3.0)
            i, j = cz - fr.z0, cx - fr.x0
            if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] and inside[i, j]:
                continue
            iu, iv = u - face[0] * 1.0, v - face[1] * 1.0
            key = fr.cell(iu, iv)
            if key in seen:
                continue
            seen.add(key)
            ix, iz = key
            m.set(ix, y, iz, STONE)
            m.set(ix, y + 1, iz, GLASS)
            m.set(ix, y + 2, iz, STONE)
            m.set(ix, y + 3, iz, CK.slab(ROOF_SLAB))
            bx, bz = fr.cell(iu - face[0], iv - face[1])
            for yy in range(y, y + 3):
                m.set(bx, yy, bz, ROOF)

    def _pavilion(self, m, zone, h_top, rise, lantern):
        """比主體高一層的角塔：外牆照角塔花樣砌到 h_top，上面四角攢尖銅頂。"""
        if not zone.any():
            return
        fr, g0 = self.fr, self.g0
        m.clear_box(zone, g0 + H_CORNICE + 1, g0 + h_top + 12)
        m.facade(zone, g0 + 1, g0 + h_top - 1, self._pavilion_pattern, base=g0, corners=self.corners)
        m.fill(erode(zone, 2), g0 + H_CORNICE, g0 + H_CORNICE, FLOOR)
        m.fill(zone, g0 + h_top, g0 + h_top, STONE)
        self._cornice(m, zone, g0 + h_top)
        us, vs = fr.U[zone], fr.V[zone]
        cu, cv = (us.min() + us.max()) / 2.0, (vs.min() + vs.max()) / 2.0
        r = max(us.max() - us.min(), vs.max() - vs.min()) / 2.0 + 0.5
        h = kit.pyramid(fr, r, rise, sides=4, du=cu, dv=cv)
        m.roof(zone, g0 + h_top + 1, h, ROOF, slab_name=ROOF_SLAB, shell=2)
        top = g0 + h_top + 1 + int(rise)
        if lantern:
            m.at(cu, cv, top, STONE)
            m.at(cu, cv, top + 1, "minecraft:waxed_weathered_lightning_rod[facing=up,powered=false]")

    def _guard_tower(self, m, zone, sv):
        if not zone.any():
            return
        fr, g0 = self.fr, self.g0
        m.clear_box(zone, g0 + H_CORNICE + 1, g0 + H_GUARD + 8)
        m.facade(zone, g0 + 1, g0 + H_GUARD - 1, self._pavilion_pattern, base=g0, corners=self.corners)
        m.fill(zone, g0 + H_GUARD, g0 + H_GUARD, STONE)
        self._cornice(m, zone, g0 + H_GUARD)
        us, vs = fr.U[zone], fr.V[zone]
        cu, cv = (us.min() + us.max()) / 2.0, (vs.min() + vs.max()) / 2.0
        r = min(us.max() - us.min(), vs.max() - vs.min()) / 2.0
        m.dome(cu, cv, r, g0 + H_GUARD + 1, 3.5, ROOF, shell=2, slab_name=ROOF_SLAB)
        m.at(cu, cv, g0 + H_GUARD + 5, STONE)
        m.at(cu, cv, g0 + H_GUARD + 6, "minecraft:waxed_weathered_lightning_rod[facing=up,powered=false]")

    def _center(self, m):
        """中軸：兩個中庭之間的三層白牆（OSM building:colour #ffffff），上面兩座四層的大廳
        （山牆頂 way/1416563942、圓頂 way/1416563952 —— 被正面的塔樓擋住，從中庭看得到）。"""
        fr, g0 = self.fr, self.g0
        bar = self.bar

        def white(face, t, h, layer, u, v, q=None):
            if h in (6, 11, 15, 19):
                return STONE
            rows = (2, 3, 4) if h < 6 else (7, 8, 9) if h < 11 else (12, 13) if h < 15 else (16, 17, 18)
            b = self._window(face, t, h, layer, rows)
            return b if b is not None else BAND

        m.fill(erode(bar, 1), g0 + 1, g0 + 1, FLOOR)
        m.facade(bar, g0 + 1, g0 + 15, white, base=g0)
        for h in (6, 11):
            m.fill(erode(bar, 2), g0 + h, g0 + h, FLOOR)
        m.fill(bar, g0 + 16, g0 + 16, STONE)
        for (a0, a1, b0, b1), kind in ((GABLE_HALL, "gable"), (DOME_HALL, "dome")):
            hall = fr.rect(a0, a1, b0, b1) & bar
            m.facade(hall, g0 + 17, g0 + 19, white, base=g0, layers=1)
            m.fill(hall, g0 + 20, g0 + 20, STONE)
            cu, cv = (a0 + a1) / 2, (b0 + b1) / 2
            if kind == "gable":
                m.roof(hall, g0 + 21, kit.gable(fr, (a1 - a0) / 2, (b1 - b0) / 2, 4.0, du=cu, dv=cv),
                       ROOF, slab_name=ROOF_SLAB, shell=1)
            else:
                r = min(a1 - a0, b1 - b0) / 2 - 1.0
                m.dome(cu, cv, r, g0 + 21, 5.0, ROOF, shell=1, slab_name=ROOF_SLAB)

    def _tower(self, m):
        """中央塔（總統府網站：約 60 m、相當 11 層樓、亞字形斷面、由方形轉為八角形）：

          +22～+42  亞字形的紅磚塔身，每三皮一道白帶、凹角是白色隅石、每面兩層細長拱窗
          +43～+44  白色簷口（出挑 1 m）、四角小尖塔、一圈石欄
          +45～+52  八角形的白色塔亭，四個正面開大圓拱（望樓）
          +53～+54  八角簷口
          +55～+59  白色八角攢尖頂（OSM roof:shape=pyramidal、roof:colour #ffffff）
          +60       頂端的避雷針（OSM height=60）
        """
        fr, g0 = self.fr, self.g0
        U, V = fr.U - TOWER_U, fr.V
        a, n = TOWER_A, TOWER_N
        au, av = np.abs(U), np.abs(V)
        plan = (au <= a) & (av <= a) & ~((au > a - n) & (av > a - n))
        m.clear_box(plan, g0 + H_CORNICE + 1, g0 + 59)

        def rel(face, t):
            """沿牆座標改成以塔的中線為 0（法線沿 v 的牆，沿牆座標是 u）。"""
            return t - TOWER_U if face[1] else t

        def arch(face, t):
            al = CK.Mason.along(face)
            return CK.stair("smooth_quartz_stairs", self._fc((-al[0], -al[1]) if t < 0 else al), "top")

        def shaft(face, t, h, layer, u, v, q=None):
            if layer:
                return BRICK
            t = rel(face, t)
            if abs(t) > a - n - 0.6:                      # 亞字形凹角的隅石
                return BAND if h % 2 == 0 else STONE
            if abs(t) < 1.0 and (26 <= h <= 31 or 35 <= h <= 40):
                return arch(face, t) if h in (31, 40) else AIR
            if h in (32, 41):
                return STONE if abs(t) < 1.0 else BAND
            if h % 3 == 0:
                return BAND
            return BRICK

        m.facade(plan, g0 + 16, g0 + 42, shaft, base=g0)
        inner = erode(plan, 2)
        m.fill(inner & ((np.abs(V) < 1.0) | (np.abs(U) < 1.0)), g0 + 26, g0 + 40, GLASS)
        for h in (25, 34):
            m.fill(inner, g0 + h, g0 + h, FLOOR)
        # 簷口、四角小尖塔、石欄
        m.fill(plan, g0 + 43, g0 + 43, STONE)
        self._cornice(m, plan, g0 + 43)
        big = (au <= a + 1) & (av <= a + 1)
        m.fill(big & ~erode(big, 1), g0 + 44, g0 + 44, CK.slab("smooth_quartz_slab"))
        for su in (-1, 1):
            for sv in (-1, 1):
                pu, pv = TOWER_U + su * (a + 0.5), sv * (a + 0.5)
                for y in range(g0 + 44, g0 + 47):
                    m.at(pu, pv, y, "minecraft:quartz_pillar[axis=y]")
                m.at(pu, pv, g0 + 47, CK.slab("smooth_quartz_slab"))
        # 八角塔亭（邊心距 3.3）：白石、四個正面開大圓拱
        oct2 = fr.ngon(8, 3.3, rot=0.0, du=TOWER_U)
        m.fill(plan & ~erode(plan, 1) | oct2, g0 + 44, g0 + 44, STONE)

        def stage2(face, t, h, layer, u, v, q=None):
            ang = math.degrees(math.atan2(v, u - TOWER_U)) % 90
            cardinal_face = ang < 22.5 or ang > 67.5
            t = rel(face, t)
            if cardinal_face and abs(t) < 1.0 and 46 <= h <= 51:
                return arch(face, t) if h == 51 else AIR
            if h in (45, 48):
                return BAND
            return STONE

        m.facade(oct2, g0 + 45, g0 + 52, stage2, base=g0, layers=1)
        m.fill(erode(oct2, 1), g0 + 45, g0 + 45, FLOOR)
        m.fill(erode(oct2, 2), g0 + 46, g0 + 51, BAND)       # 塔亭裡的石芯（樓梯間）
        ring = fr.ngon(8, 4.0, du=TOWER_U)
        m.fill(ring, g0 + 53, g0 + 53, STONE)
        m.fill(ring & ~fr.ngon(8, 3.1, du=TOWER_U), g0 + 54, g0 + 54, CK.slab("smooth_quartz_slab"))
        m.fill(fr.ngon(8, 3.1, du=TOWER_U), g0 + 54, g0 + 54, STONE)
        # 八角攢尖頂 +55～+59、避雷針 +60
        h = kit.pyramid(fr, 3.0, 4.4, sides=8, du=TOWER_U)
        m.roof(fr.ngon(8, 3.0, du=TOWER_U), g0 + 55, h, STONE, slab_name="smooth_quartz_slab", shell=1)
        m.at(TOWER_U, 0.0, g0 + 59, "minecraft:quartz_pillar[axis=y]")
        m.at(TOWER_U, 0.0, g0 + H_TOWER, "minecraft:waxed_weathered_lightning_rod[facing=up,powered=false]")

    def _porte_cochere(self, m):
        """車寄：一層樓高的柱廊（戰後改成平頂），屋頂是二樓的露台。車道從南北兩側穿過。"""
        fr, g0 = self.fr, self.g0
        u0, u1, hv = PORCH
        top = fr.rect(u0, u1, -hv, hv)
        m.fill(top, g0 + 1, g0 + 1, "minecraft:polished_andesite")
        for u in (u1 - 1.0, u1 - 4.5, u1 - 8.0):
            for v in (-hv + 1.0, hv - 1.0):
                m.column(u, v, g0 + 2, g0 + 7, "minecraft:quartz_pillar[axis=y]",
                         base=STONE, capital="minecraft:chiseled_quartz_block")
        for v in (-2.5, 2.5):
            m.column(u1 - 1.0, v, g0 + 2, g0 + 7, "minecraft:quartz_pillar[axis=y]",
                     base=STONE, capital="minecraft:chiseled_quartz_block")
        m.fill(top, g0 + 8, g0 + 8, STONE)
        m.fill(top & ~erode(top, 1), g0 + 9, g0 + 9, "minecraft:diorite_wall")
        m.fill(erode(top, 1), g0 + 9, g0 + 9, AIR)
        m.fill(erode(top, 1), g0 + 8, g0 + 8, PORCH_ROOF)
        # 車道：兩側的斜坡磚鋪到車寄底下
        m.fill(top & (fr.U < u1 - 1.5) & (fr.U > u0 + 1.0), g0 + 1, g0 + 1, "minecraft:stone_bricks")

    def _semi_porch(self, m, mask, height):
        """半圓門廊：沿弧一圈白柱，上面一圈石材過梁與紅色屋頂。"""
        if not mask.any():
            return
        g0 = self.g0
        m.fill(mask, g0 + 1, g0 + 1, "minecraft:polished_andesite")
        rim = mask & ~erode(mask, 1)
        for x, z, u, v, face, t in m.ring_cells(mask):
            if (x + z) % 2 == 0:
                for y in range(g0 + 2, g0 + height):
                    m.set(x, y, z, "minecraft:quartz_pillar[axis=y]")
        m.fill(mask, g0 + height, g0 + height, STONE)
        m.fill(erode(mask, 1), g0 + height, g0 + height, PORCH_ROOF)
        m.fill(rim, g0 + height + 1, g0 + height + 1, CK.slab("smooth_quartz_slab"))

    def _courtyard(self, m, court):
        """中庭：草地、十字步道、四周一圈矮籬、四棵樹。"""
        fr, g0 = self.fr, self.g0
        m.fill(court, g0, g0, "minecraft:grass_block")
        m.fill(court, g0 + 1, g0 + 30, AIR)
        us, vs = fr.U[court], fr.V[court]
        cu, cv = (us.min() + us.max()) / 2.0, (vs.min() + vs.max()) / 2.0
        path = court & ((np.abs(fr.U - cu) <= 1.0) | (np.abs(fr.V - cv) <= 1.0))
        m.fill(path, g0, g0, "minecraft:polished_andesite")
        hedge = erode(court, 2) & ~erode(court, 3) & ~dilate(path, 1)
        m.fill(hedge, g0 + 1, g0 + 1, "minecraft:oak_leaves[persistent=true]")
        for du in (-0.3, 0.3):
            for dv in (-0.3, 0.3):
                tu = cu + du * (us.max() - us.min())
                tv = cv + dv * (vs.max() - vs.min())
                for y in range(g0 + 1, g0 + 5):
                    m.at(tu, tv, y, "minecraft:oak_log[axis=y]")
                blob = fr.ellipse(2.6, 2.6, du=tu, dv=tv) & court
                m.fill(blob, g0 + 5, g0 + 7, "minecraft:oak_leaves[persistent=true]")
                m.fill(fr.ellipse(1.6, 1.6, du=tu, dv=tv) & court, g0 + 8, g0 + 8,
                       "minecraft:oak_leaves[persistent=true]")


BUILDS = {"presidential_office": PresidentialOffice}
