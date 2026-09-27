#!/usr/bin/env python3
"""國立臺灣博物館本館（原兒玉總督及後藤民政長官紀念館，1915）。

位置與輪廓：OSM way/1050624691（一字形、中央量體前後凸出、兩端各一座端樓），
中央的 4 層量體 way/1050624690 就是圓頂底下的大廳。長相照公開資料：
  · 野村一郎、荒木榮一設計，1915 年落成；新古典主義，正面是希臘神廟式的六柱式
    門廊 —— 六根多立克柱撐起三角山牆，山牆上有花葉浮雕；中央是羅馬式圓頂；
    平面一字形左右對稱，正門朝北對著館前路（臺博館網站〈認識臺博〉〈沿革、建築〉、
    交通部觀光署景點介紹、中文維基百科）
  · 中央圓頂塔高近 30 m；大廳四周 32 根複合式柱，每根高 32 尺（約 9.7 m）、
    直徑 2 尺 7 寸；大廳正中的彩繪（鑲嵌）玻璃天窗離地約 54 尺（約 16 m）；
    外牆洗石子、屋頂銅瓦（臺博館網站〈臺博館沿革、建築、典藏與整建說明〉）
OSM 輪廓的主軸只偏 0.5°（各邊 0.3°～0.6° 不等，是描圖誤差），這裡取 0°：
六根柱子、窗與壁柱才會剛好落在格線上、左右對稱。局部座標 u 朝東、v 朝南，
原點是輪廓外接矩形的中心（取整數格，u = 0 是中軸、兩側格子成對）。
"""
import math

import numpy as np

from mrt.application.attractions import colonial_kit as CK
from mrt.application.attractions import kit
from mrt.application.attractions.kit import AIR, Attraction, Frame, Spot, erode, dilate

# ---- 材質 ----
WALL = "minecraft:smooth_quartz"          # 洗石子的白牆
RUST = "minecraft:calcite"                # 一樓粗面砌的灰縫那一皮
BASE = "minecraft:polished_diorite"       # 基座與台階
COLUMN = "minecraft:quartz_pillar[axis=y]"
CAPITAL = "minecraft:chiseled_quartz_block"
TRIM = "minecraft:quartz_bricks"
GLASS = "minecraft:gray_stained_glass"
ROOF = "minecraft:waxed_weathered_cut_copper"     # 銅瓦（上蠟才不會繼續氧化）
ROOF_SLAB = "waxed_weathered_cut_copper_slab"
ROOF_STAIR = "waxed_weathered_cut_copper_stairs"
DOME_RIB = "minecraft:waxed_oxidized_cut_copper"
FLOOR_A = "minecraft:polished_blackstone"  # 大廳地坪：黑白大理石（赤坂黑大理石、水戶白石）
FLOOR_B = "minecraft:smooth_quartz"
LIGHT = "minecraft:sea_lantern"

# ---- 高度（離地面幾格）----
H_FLOOR = 2             # 基座頂 = 一樓地坪（門廊前兩級台階）
H_COL0, H_COL1 = 3, 12  # 門廊柱：柱礎 +3、柱頭 +12（10 m，跟大廳 32 尺的柱子相當）
H_ENT = 13              # 簷部（楣梁、簷口）+13～+14
H_WING = 13             # 兩翼簷口
H_PED = 5.0             # 山牆高
H_ATTIC = (15, 16)      # 圓頂底座（方形女兒牆）
H_DRUM = (17, 20)       # 圓頂鼓座（開窗）
H_DOME0, H_DOME_RISE = 21, 6.0   # 圓頂殼（頂點 +27，上面頂塔兩格、銅頂、避雷針到 +30）
H_TOP = 30              # 頂塔頂端（近 30 m）
H_SKY = 18              # 大廳天窗（一樓地面 +3 往上 15 m；公開資料約 16 m）

# ---- 平面（局部座標；OSM 量來）----
CENTER = 11.6           # 中央量體半寬（u ±11.6）
FRONT = -16.0           # 門廊前緣（v -16）
PORCH_BACK = -10.0      # 門廊後牆（正門所在）
WING_N, WING_S = -8.6, 7.7        # 兩翼北、南牆
END_U = 31.6            # 端樓從 |u| 31.6 起到 45.5
END_N, END_S = -11.4, 10.1
DOME_V = 2.0            # 圓頂中心（way/1050624690：v -5.9～9.3 的中點 1.7，取整讓柱列落在格子上）
DOME_R = 7.4            # 圓頂半徑（量體 15.7 m 見方，四周留一圈女兒牆）
COLS_U = (-10.0, -6.0, -2.0, 2.0, 6.0, 10.0)   # 六柱式：2 m 見方、柱距 4 m（門廊寬 22 m）
HALL = 8.0              # 大廳：柱列在 17 m 見方的一圈上，每邊 8 根、柱距 2 m，共 32 根（中軸留走道）
BAY = 5.0               # 兩翼的開間：壁柱、牆、窗、窗、牆


class NationalTaiwanMuseum(Attraction):
    height_m = float(H_TOP)
    margin = 14

    def __init__(self, item):
        super().__init__(item)
        main = self.feature("way/1050624691") or (self.mains() or [None])[0]
        self.outer = max(main["outer"], key=len) if main and main.get("outer") else self.outline()
        ang = CK.fit_angle(self.outer)
        self.angle = 0.0 if abs(math.degrees(ang)) < 1.0 else ang
        f0 = Frame(0.0, 0.0, self.angle, 1)
        u0, u1, v0, v1 = CK.local_extent(f0, self.outer)
        ox, oz = f0.world((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        self.origin = (float(round(ox)), float(round(oz)))

    def spot_uv(self):
        """預設觀景點：館前路的南端、門廊往北 40 m，看得到整個立面與圓頂。
        （tools/verify_attractions 只讀輪廓外 44 m 以內，觀景點不能更遠。）"""
        return (0.0, FRONT - 40.0)

    def bbox(self):
        x0, z0, x1, z1 = super().bbox()
        fr = Frame(self.origin[0], self.origin[1], self.angle, 1)
        sx, sz = fr.world(*self.spot_uv())
        return (min(x0, int(sx) - 6), min(z0, int(sz) - 6), max(x1, int(sx) + 6), max(z1, int(sz) + 6))

    def plan(self, site):
        self.fr = fr = Frame(self.origin[0], self.origin[1], self.angle, 58)
        U, V = fr.U, fr.V
        au = np.abs(U)
        center = (au <= CENTER) & (V >= PORCH_BACK) & (V <= 16.0)
        wings = (au <= END_U) & (V >= WING_N) & (V <= WING_S)
        ends = (au >= END_U) & (au <= 45.5) & (V >= END_N) & (V <= END_S)
        self.body = center | wings | ends
        self.porch = (au <= CENTER) & (V >= FRONT) & (V < PORCH_BACK)
        self.foot = fr.polygon(self.outer)
        self.g0 = site.level(fr, self.foot)
        self.site = site
        # 整地與前庭：輪廓外擴 3 格鋪石，門廊前鋪到 v -26。地面高度要在 plan 裡查好
        # （cli 在 plan_all 之後就清掉地形的快取）
        self.yard = dilate(self.body | self.porch, 3) | ((au <= 16) & (V >= FRONT - 10) & (V < FRONT))
        site.grid(fr, self.yard)
        su, sv = self.spot_uv()
        sx, sz = fr.cell(su, sv)
        sy = site.g(sx, sz) + 1
        tx, tz = fr.world(0.0, -4.0)
        yaw, pitch = kit.look(sx, sy, sz, tx, self.g0 + 14, tz)
        self._spots = [Spot("", sx, sy, sz, yaw, pitch, self.name_zh, self.name_en)]

    def plaque(self):
        return [self.name_zh, self.name_en, "1915 年落成", "臺灣最早的博物館"]

    # ---- 蓋 ----
    def build(self, w):
        fr, g0 = self.fr, self.g0
        m = CK.Mason(w, fr)
        U, V = fr.U, fr.V
        au = np.abs(U)
        body, porch = self.body, self.porch

        self.site.prepare(w, fr, self.yard, g0, top="minecraft:polished_andesite", clear=40)
        m.fill((au <= 13) & (V >= FRONT - 10) & (V < FRONT - 2), g0, g0, "minecraft:stone_bricks")

        # 基座（+1～+2）與地坪
        m.fill(body | porch, g0 + 1, g0 + H_FLOOR, BASE)
        # 門廊前兩級台階（v -18～-16）：外面一排在 +1、裡面一排在 +2
        for dv, dy in ((-2.0, 1), (-1.0, 2)):
            steps = (au <= CENTER + 0.4) & (V >= FRONT + dv) & (V < FRONT + dv + 1.0)
            if dy > 1:
                m.fill(steps, g0 + 1, g0 + dy - 1, BASE)
            for x, z in fr.cells(steps):
                m.set(x, g0 + dy, z, CK.stair("polished_diorite_stairs", m.facing(0, 1)))

        # 外牆：兩翼與端樓兩層，中央量體同高
        corners = CK.convex_corners([CK.to_local(fr, x, z) for x, z in self._body_poly()])
        m.facade(body, g0 + H_FLOOR + 1, g0 + H_WING - 1, self._wall_pattern, base=g0, corners=corners)
        m.fill(erode(body, 2), g0 + 8, g0 + 8, "minecraft:smooth_stone")
        # 簷部：楣梁 + 出挑的簷口 + 女兒牆
        m.fill(body, g0 + H_WING, g0 + H_WING, WALL)
        self._cornice(m, body, g0 + H_WING)
        rim = body & ~erode(body, 1)
        m.fill(rim, g0 + H_WING + 1, g0 + H_WING + 1, WALL)
        m.fill(rim, g0 + H_WING + 2, g0 + H_WING + 2, CK.slab("smooth_quartz_slab"))
        # 端樓多一層女兒牆（比兩翼高一點）
        ends = body & (au >= END_U)
        m.fill(ends & ~erode(ends, 1), g0 + H_WING + 2, g0 + H_WING + 2, WALL)
        # 兩翼的銅瓦屋頂：女兒牆裡面的低坡四坡頂
        inner = erode(body, 1) & ~(au <= CENTER)
        d = kit.depth(inner).astype(float)
        m.roof(inner, g0 + H_WING + 1, np.minimum(d * 0.35, 2.5), ROOF, slab_name=ROOF_SLAB, shell=1)

        self._portico(m)
        self._hall(m)
        self._dome(m)

    def _body_poly(self):
        """外牆的簡化輪廓（局部 -> 世界），只拿來找凸角放隅石。"""
        pts = [(-45.5, END_N), (-END_U, END_N), (-END_U, WING_N), (-CENTER, WING_N), (-CENTER, PORCH_BACK),
               (CENTER, PORCH_BACK), (CENTER, WING_N), (END_U, WING_N), (END_U, END_N), (45.5, END_N),
               (45.5, END_S), (END_U, END_S), (END_U, WING_S), (CENTER, WING_S), (CENTER, 16.0),
               (-CENTER, 16.0), (-CENTER, WING_S), (-END_U, WING_S), (-END_U, END_S), (-45.5, END_S)]
        return [self.fr.world(u, v) for u, v in pts]

    # ---- 立面 ----
    def _wall_pattern(self, face, t, h, layer, u, v, q=None):
        """一樓粗面砌（每兩皮一道灰縫）＋方窗；二樓多立克壁柱夾高窗、窗頂有石楣。
        窗是外層挖空、內層玻璃。"""
        if q is not None and q < 1.2 and layer == 0:      # 牆角：壁柱
            return COLUMN if h < H_WING - 1 else CAPITAL
        off = 1.6 if face[1] else 0.0                     # 南北牆的開間從 |u| 11.6 起算
        bay = BAY
        if abs(u) >= END_U - 0.5 and face[1]:
            off, bay = END_U % 4.6, 4.6                   # 端樓：三個開間（壁柱在 |u| 31.6、36.2、40.8、45.4）
        p = (abs(t) - off) % bay if face[1] else (t - 1.85) % bay   # 東西端牆以 v -0.65 為中心
        pil = p < 0.5 or p >= bay - 0.5
        win = bay / 2 - 1.0 <= p < bay / 2 + 1.0
        opening = win and (3 <= h <= 5 or 8 <= h <= 11)
        if layer:
            return GLASS if opening else WALL
        if opening:
            return AIR
        if h <= 6:                                        # 一樓
            if h == 6:
                return TRIM
            return RUST if h % 2 == 0 else WALL
        if pil:
            return CAPITAL if h == H_WING - 1 else COLUMN
        if win and h == 7:
            return TRIM                                   # 窗台
        if win and h == 12:
            return CK.stair("smooth_quartz_stairs", self.fr.facing(*face), "top")   # 窗楣
        return WALL

    def _cornice(self, m, mask, y):
        out = dilate(mask, 1) & ~mask
        fr = self.fr
        for x, z, u, v, face, t in m.ring_cells(dilate(mask, 1)):
            if out[z - fr.z0, x - fr.x0]:
                m.set(x, y, z, CK.stair("smooth_quartz_stairs", m.facing(-face[0], -face[1]), "top"))

    # ---- 門廊 ----
    def _portico(self, m):
        """六柱式門廊：2 m 見方的多立克柱六根（柱礎、柱身、柱頭），上面楣梁與簷口，
        再上面是三角山牆（中央高 5 m、斜邊是石材樓梯），山牆面中央一塊盾徽。"""
        fr, g0 = self.fr, self.g0
        U, V = fr.U, fr.V
        au = np.abs(U)
        porch = self.porch
        # 門廊地坪與正門
        m.fill(porch, g0 + H_FLOOR, g0 + H_FLOOR, BASE)
        m.fill(porch, g0 + H_FLOOR + 1, g0 + H_ENT - 1, AIR)
        for cu in COLS_U:
            # 前排六根；兩端各多一根靠後的柱子，門廊側面才不是空的
            for cv in (FRONT + 1.0, PORCH_BACK - 1.0) if abs(cu) > 9 else (FRONT + 1.0,):
                m.column(cu, cv, g0 + H_COL0, g0 + H_COL1, COLUMN, base=WALL, capital=CAPITAL, size=2.0)
        # 楣梁、簷帶（三槽板：每 2 m 一塊深色）、簷口
        ent = (au <= CENTER) & (V >= FRONT) & (V <= PORCH_BACK)
        m.fill(ent, g0 + H_ENT, g0 + H_ENT, WALL)
        frieze = ent & ~erode(ent, 1)
        m.fill(frieze, g0 + H_ENT + 1, g0 + H_ENT + 1, TRIM)
        m.fill(frieze & (np.floor(U / 2.0) % 2 == 0), g0 + H_ENT + 1, g0 + H_ENT + 1, RUST)
        m.fill(erode(ent, 1), g0 + H_ENT + 1, g0 + H_ENT + 1, WALL)
        self._cornice(m, ent, g0 + H_ENT + 1)
        # 門廊天花的燈
        for cu in (-6.0, 0.0, 6.0):
            m.at(cu, (FRONT + PORCH_BACK) / 2.0, g0 + H_ENT, LIGHT)
        # 山牆：前面一道 1 格厚的三角形山牆面（斜邊是石材樓梯），後面兩坡銅瓦屋頂接到中央量體
        y = g0 + H_ENT + 2
        m.gable(-CENTER - 0.5, CENTER + 0.5, FRONT - 0.5, FRONT + 0.5, y, H_PED, WALL, edge="smooth_quartz_stairs")
        back = (au <= CENTER + 0.5) & (V > FRONT + 0.5) & (V <= PORCH_BACK + 2.0)
        m.roof(back, y, (H_PED - 0.5) * (1.0 - au / (CENTER + 0.5)), ROOF, slab_name=ROOF_SLAB, shell=1)
        # 山牆面：中央的盾徽與兩側的花葉（淺浮雕用紋理不同的白）
        for du, dy in ((-0.5, 1), (0.5, 1), (-0.5, 2), (0.5, 2), (-0.5, 3), (0.5, 3), (-1.5, 2), (1.5, 2)):
            m.at(du, FRONT - 0.3, y + dy, TRIM)
        for du in (-6.5, -4.5, 4.5, 6.5):
            m.at(du, FRONT - 0.3, y + 1, CAPITAL)
        # 正門：中央柱間後面的大門（4 格寬、5 格高）
        door = (au <= 2.0) & (V >= PORCH_BACK - 0.5) & (V <= PORCH_BACK + 2.5)
        m.fill(door, g0 + H_FLOOR + 1, g0 + H_FLOOR + 5, AIR)
        m.fill(door & (V > PORCH_BACK + 1.5), g0 + H_FLOOR + 6, g0 + H_FLOOR + 6, TRIM)

    # ---- 圓頂 ----
    def _dome(self, m):
        """方形底座（女兒牆）→ 圓形鼓座（八扇窗）→ 銅瓦圓頂（八條肋）→ 頂塔，頂端近 30 m。
        蓋在大廳之後：外殼覆蓋大廳挖空時削到的地方。"""
        fr, g0 = self.fr, self.g0
        U, V = fr.U, fr.V
        R = np.hypot(U, V - DOME_V)
        base = (np.abs(U) <= 7.8) & (np.abs(V - DOME_V) <= 7.6)
        drum = R <= 6.8
        # 中央量體屋頂（女兒牆內、圓頂底座以外）
        center = (np.abs(U) <= CENTER) & (V >= PORCH_BACK) & (V <= 16.0)
        m.fill(erode(center, 1) & ~base, g0 + H_WING + 1, g0 + H_WING + 1, ROOF)

        def attic(face, t, h, layer, u, v, q=None):
            if h == H_ATTIC[1]:
                return TRIM
            if abs(t - (DOME_V if face[0] else 0.0)) < 1.0 and h == 15:
                return GLASS
            return WALL

        m.facade(base, g0 + H_ATTIC[0] - 1, g0 + H_ATTIC[1], attic, base=g0, layers=1)
        m.fill(base & ~drum, g0 + H_ATTIC[1] + 1, g0 + H_ATTIC[1] + 1, ROOF)

        def drum_pat(face, t, h, layer, u, v, q=None):
            a = math.degrees(math.atan2(v - DOME_V, u)) % 45.0
            if min(a, 45 - a) < 8.0 and H_DRUM[0] + 1 <= h <= H_DRUM[1] - 1:     # 八扇窗
                return GLASS
            if h == H_DRUM[1]:
                return TRIM
            return WALL

        m.facade(drum, g0 + H_DRUM[0], g0 + H_DRUM[1], drum_pat, base=g0, layers=1)
        ring = (R <= 7.8) & (R > 6.8)
        m.fill(ring, g0 + H_DRUM[1], g0 + H_DRUM[1], CK.slab("smooth_quartz_slab", "top"))
        # 圓頂殼（鼓座上方）
        m.dome(0.0, DOME_V, DOME_R, g0 + H_DOME0, H_DOME_RISE, ROOF, shell=2, slab_name=ROOF_SLAB,
               rib=DOME_RIB, ribs=8)
        # 頂塔：四根小柱（+27～+28）＋銅頂（+29）、避雷針 +30
        top = g0 + H_TOP - 3
        for k in range(4):
            ph = math.radians(45 + 90 * k)
            m.column(1.2 * math.cos(ph), DOME_V + 1.2 * math.sin(ph), top, top + 1, COLUMN)
        m.fill(R <= 1.8, top + 2, top + 2, ROOF)
        m.at(0.0, DOME_V, g0 + H_TOP, "minecraft:waxed_weathered_lightning_rod[facing=up,powered=false]")

    # ---- 大廳 ----
    def _hall(self, m):
        """圓頂下的大廳（從門廊走得進來）：黑白大理石地坪、32 根複合式柱（17 m 見方一圈、
        每邊 8 根、柱距 2 m、高 10 m）、柱頂一圈簷部與往內收的藻井、離地 15 m 的彩繪玻璃
        天窗（公開資料約 16 m），簷部與天窗上各一圈海燈。"""
        fr, g0 = self.fr, self.g0
        U, V = fr.U, fr.V
        au = np.abs(U)
        hall = (au <= CENTER - 1.0) & (V >= PORCH_BACK + 1.0) & (V <= 15.0)
        y0 = g0 + H_FLOOR
        m.fill(hall, y0 + 1, g0 + H_SKY, AIR)
        checker = ((np.floor(U) + np.floor(V)) % 2 == 0)
        m.fill(hall & checker, y0, y0, FLOOR_A)
        m.fill(hall & ~checker, y0, y0, FLOOR_B)
        # 32 根柱：17 m 見方的一圈（u、v 離中心 8.5），每邊 8 根、柱距 2 m；四角不放、中軸不放
        n = 0
        ring = HALL + 0.5
        for k in (-7.5, -5.5, -3.5, -1.5, 1.5, 3.5, 5.5, 7.5):
            for cu, cv in ((k, DOME_V - ring), (k, DOME_V + ring), (-ring, DOME_V + k), (ring, DOME_V + k)):
                m.column(cu, cv, y0 + 1, y0 + 10, COLUMN, base=WALL, capital=CAPITAL)
                n += 1
        self.hall_columns = n
        # 柱頂的簷部與挑空的藻井：往內一格一格收到鼓座，天窗在鼓座底（+18）
        sq = lambda r: (au <= r) & (np.abs(V - DOME_V) <= r)
        R = np.hypot(U, V - DOME_V)
        top = g0 + H_SKY - 1
        m.fill(sq(HALL + 0.5) & ~sq(HALL - 0.5), y0 + 11, y0 + 11, WALL)
        m.fill(hall & ~sq(HALL + 0.5), y0 + 11, top, WALL)
        for k, r in enumerate((HALL - 0.5, HALL - 1.5, HALL - 2.5)):
            m.fill(sq(r + 1) & ~sq(r), y0 + 12 + k, top, WALL)
        m.fill(sq(HALL + 0.5) & ~(R <= 6.0), top, top, WALL)
        # 燈：簷部上方一圈海燈
        lamps = sq(HALL + 0.5) & ~sq(HALL - 0.5) & ((np.floor(U) + np.floor(V)) % 4 == 0)
        m.fill(lamps, y0 + 11, y0 + 11, LIGHT)
        # 彩繪玻璃天窗（半徑 5.6 的圓）：同心圓與八道放射線
        sky = R <= 5.6
        ang = (np.degrees(np.arctan2(V - DOME_V, U)) + 360.0) % 45.0
        spoke = (np.minimum(ang, 45.0 - ang) < 5.0) & (R >= 1.3)
        y = g0 + H_SKY
        m.fill((R <= 6.8) & ~sky, y, y, WALL)
        for cond, blk in ((spoke, "minecraft:lime_stained_glass"),
                          (R < 1.3, "minecraft:orange_stained_glass"),
                          ((R >= 2.6) & (R < 3.6), "minecraft:light_blue_stained_glass"),
                          (np.ones(fr.shape, dtype=bool), "minecraft:white_stained_glass")):
            sel = sky & cond
            m.fill(sel, y, y, blk)
            sky = sky & ~cond
        # 天窗上方：鼓座與圓頂裡面挖空，光從鼓座的窗照進來；天窗上再鋪一圈燈（晚上也亮）
        m.fill(R <= 6.2, y + 1, g0 + H_DOME0 + 4, AIR)
        m.fill((R <= 5.6) & (R > 4.4) & ((np.floor(U) + np.floor(V)) % 3 == 0), y + 1, y + 1, LIGHT)
        # 從門廊進大廳的前廳
        m.fill((au <= 2.0) & (V >= PORCH_BACK - 0.5) & (V <= DOME_V - HALL - 0.5), y0 + 1, y0 + 5, AIR)
        m.fill((au <= 2.0) & (V >= PORCH_BACK) & (V <= DOME_V - HALL - 0.5), y0, y0, FLOOR_B)


BUILDS = {"national_taiwan_museum": NationalTaiwanMuseum}
