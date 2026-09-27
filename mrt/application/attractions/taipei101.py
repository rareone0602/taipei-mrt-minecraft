#!/usr/bin/env python3
"""台北101：508 m、地上 101 層，照公開的建築事實 1:1 蓋。

位置、方位、購物中心與裙樓的平面是 OSM 的（data/attractions.json：塔樓 way/198637969
偏 1.0°、半邊長 27 m；購物中心 way/64566862 高 30 m；裙樓 way/1159328963、
way/1159328964 高 25 m；圓頂 way/615183624 與兩個圓瓣 way/1339487731、way/1339487732
是如意形的屋頂）。塔樓的長相照下面這些公開資料：

  · 高度：塔尖 508 m、屋頂 449.2 m、頂樓 438 m、89 樓室內觀景台 382 m、
    91 樓戶外觀景台約 390 m（Wikipedia「Taipei 101」、中文維基「台北101」）
  · 層高：辦公層 4.2 m（structures-explained.com「Taipei 101 structural engineering」）
  · 造型：25～26 層高的截頭角錐基座，上面疊八個倒梯形的「斗」，每斗八層、往外斜約 7°，
    再上去是平面小很多的頂部（91 樓以上）與 60 m 的塔尖（同上兩處）。第一斗從 27 樓
    開始（基座的抗彎構架到 26 樓為止：NCREE 研討會 Shieh 談 101 巨柱設計的論文）
  · 平面：腰身約 45.9 m 見方（Structure 雜誌「Dynamic Loading Solutions in Taipei 101」），
    轉角是 2.5 m 的缺角（同上）
  · 立面裝飾：基座與塔身交接處每面一個圓盤，代表古錢（Wikipedia）；外牆的如意每個
    至少 8 m 高（Wikipedia），這裡排在每一斗頂端的正中
  · 阻尼器：直徑 5.5 m、660 公噸的鋼球，吊在 92 樓到 88 樓之間（Wikipedia）
  · 帷幕牆：藍綠色的雙層玻璃（Wikipedia）

蓋法見 highrise.py：逐層算遮罩，外殼是外圈、挑簷是「這層有上層沒有」的格子。
一樓大廳（南、東兩面有門）、89 樓觀景台（兩層挑高、玻璃外牆、阻尼器在正中央）、
91 樓戶外觀景台都走得進去；大廳的告示牌傳送到 89 樓，觀景台的告示牌傳送回大廳。
"""
import math

import numpy as np

from mrt import config
from mrt.application.attractions import highrise as HR
from mrt.application.attractions import kit
from mrt.application.attractions.kit import Attraction, Frame, Spot

# ---------------------------------------------------------------- OSM 元素
TOWER = "way/198637969"             # 塔樓（89 層那一段，平面有缺角）
MALL = "way/64566862"               # 台北101購物中心，6 層、30 m
SKIRTS = ("way/1159328963", "way/1159328964")      # 塔樓腳下的裙樓，5 層、25 m
VESTIBULE = "way/1339487722"        # 南門的門廳
DOME = ("way/615183624", "way/1339487731", "way/1339487732")   # 如意形的圓頂（30 -> 42 m）
CANOPIES = ("way/1339487735", "way/1339487734", "way/1339487736",
            "way/1339487737", "way/1339487738")   # 一層高的門口雨庇
SKYWALKS = ("way/1339487709", "way/1339487716", "way/1339401632")  # 信義區空橋，二樓高
PLAZA = "way/248210267"             # 景點範圍（含廣場）

# ---------------------------------------------------------------- 尺寸（公尺）
BASE_A0 = 27.0          # 基座在地面的半邊長（OSM 塔樓輪廓 54 m）
BASE_A1 = 23.5          # 基座頂（26 樓）的半邊長：往內收
MOD_B0 = 22.0           # 每一斗底部的半邊長（腰身約 45.9 m）
MOD_B1 = 26.0           # 每一斗頂部的半邊長：33.6 m 往外斜 4 m，約 6.8°
NOTCH = 2.5             # 轉角兩階缺角，每階 2.5 m
BAY = 7.25              # 基座每面正中的凸出開間（OSM 四條 14.5 m 寬的細長 part）
TOP91 = 14.8            # 91～92 樓那一段的半邊長（OSM way/1339487717，30 m 見方）
SHAFT0, SHAFT1 = 10.3, 10.9     # 93～101 樓的半邊長（OSM 頂樓 21.3 m 見方），也微微外斜
CROWN_R = 7.3           # 439～448 m 的圓形頂冠（OSM way/615184269）

H_BASE = 121.8          # 27 樓樓板 = 基座頂
H_MOD = 33.6            # 一斗 = 八層 × 4.2 m
H_91 = 390.6            # 91 樓樓板（第八斗的頂）
H_93 = 399.0            # 93 樓樓板：91～92 樓那一段的頂
H_SHAFT = 439.0         # 頂樓那一段的頂（OSM）
H_ROOF = 449            # 屋頂 449.2 m：頂冠的最後一格
H_TIP = 508             # 塔尖

# ---------------------------------------------------------------- 材質
GLASS = "minecraft:cyan_stained_glass"            # 藍綠色帷幕玻璃
SPANDREL = "minecraft:prismarine_bricks"          # 每層樓板那一列的層間帶
MULLION = "minecraft:light_gray_stained_glass"    # 直櫺（銀灰色鋁框）
MECH = "minecraft:dark_prismarine"                # 每斗頂的機電層
LEDGE = "minecraft:smooth_quartz"                 # 每斗頂的挑簷（反光的斜頂，遠看是白的）
BAND = "minecraft:light_gray_concrete"            # 基座頂那一圈（古錢後面的帶子）
CORE = "minecraft:polished_andesite"              # 電梯核
SLAB = "minecraft:smooth_stone"                   # 樓板
FLOOR1 = "minecraft:polished_diorite"             # 一樓大廳與觀景台的地坪
LAMP = "minecraft:sea_lantern"
COIN_RIM = "minecraft:iron_block"
COIN_FACE = "minecraft:prismarine_bricks"
COIN_HOLE = "minecraft:gold_block"
RUYI = "minecraft:smooth_quartz"
SPIRE = "minecraft:iron_block"
MALL_WALL = "minecraft:polished_diorite"
MALL_ROOF = "minecraft:smooth_stone"
DOME_GLASS = "minecraft:light_blue_stained_glass"
DOME_RIB = "minecraft:smooth_quartz"
PAVING = "minecraft:polished_andesite"
TMD = "minecraft:gold_block"
CHAIN = "minecraft:iron_chain[axis=y,waterlogged=false]"
RAIL = "minecraft:glass"

# 如意：每斗頂端、每一面正中各一個，至少 8 m 高（Wikipedia）
# 點陣是如意頭（雲形、心形的三瓣）接一段柄，8 列 = 8 m；不留洞，遠看才不會像一張臉
RUYI_GLYPH = HR.glyph([
    ".XX.XX.",
    "XXXXXXX",
    "XXXXXXX",
    ".XXXXX.",
    "..XXX..",
    "...X...",
    "...X...",
    "..XXX..",
])


def floor_h(k):
    """k 樓樓板離一樓樓板幾公尺：1～5 樓是挑高的大廳層，6 樓（33.6 m）起每層 4.2 m。
    這樣 27 樓 = 121.8 m、89 樓 = 382.2 m（觀景台 382 m）、91 樓 = 390.6 m（OSM）。"""
    if k <= 1:
        return 0.0
    if k <= 6:
        return {2: 8.4, 3: 14.7, 4: 21.0, 5: 27.3, 6: 33.6}[k]
    return 33.6 + 4.2 * (k - 6)


FLOOR_ROWS = [int(math.floor(floor_h(k))) for k in range(1, 102)]      # 1..101 樓的樓板列
ROW_FLOOR = {}
for _k, _r in enumerate(FLOOR_ROWS, 1):
    ROW_FLOOR[_r] = _k
OBS_FLOOR = 89
OBS_ROW = FLOOR_ROWS[OBS_FLOOR - 1]           # 382
DECK_ROW = FLOOR_ROWS[91 - 1]                  # 390：第八斗的頂 = 91 樓戶外觀景台
SKIP_SLAB = {FLOOR_ROWS[90 - 1]}               # 90 樓不鋪：89 樓觀景台兩層挑高
CORE_TOP = FLOOR_ROWS[86 - 1]                  # 電梯核蓋到 86 樓（上面是阻尼器那幾層）
COIN_Y = 113            # 古錢中心（25 樓上下）
COIN_R = 6.5


def floor_of_row(yy):
    """-> (樓層, 這一列是那層的第幾列)。"""
    k = 1
    for i, r in enumerate(FLOOR_ROWS):
        if r <= yy:
            k = i + 1
        else:
            break
    return k, yy - FLOOR_ROWS[k - 1]


def section(yy):
    """這一列屬於哪一段：base / mod（附第幾斗 0..7）/ top91 / shaft / crown / spire。"""
    t = yy + 0.5
    if t < H_BASE:
        return "base", None
    if t < H_91:
        return "mod", int((t - H_BASE) // H_MOD)
    if t < H_93:
        return "top91", None
    if t < H_SHAFT:
        return "shaft", None
    if yy <= H_ROOF - 1:
        return "crown", None
    return "spire", None


def half_width(yy):
    """這一列的平面半邊長（基座與八斗；其他段回 None）。"""
    t = yy + 0.5
    sec, m = section(yy)
    if sec == "base":
        return BASE_A0 + (BASE_A1 - BASE_A0) * t / H_BASE
    if sec == "mod":
        f = (t - H_BASE - m * H_MOD) / H_MOD
        return MOD_B0 + (MOD_B1 - MOD_B0) * f
    return None


def section_top(yy):
    """這一列是不是一段的最後一列（挑簷、屋頂用白色）。"""
    return section(yy) != section(yy + 1)


class Fields:
    """某個 Frame 上以塔樓中心為原點的各種距離場（每個 Frame 算一次）。"""

    def __init__(self, fr, du, dv):
        u, v = fr.U - du, fr.V - dv
        self.fr = fr
        self.u, self.v = u, v
        self.R = HR.notched_radius(fr, NOTCH, du, dv)
        self.T, self.S = HR.face_coords(fr, du, dv)
        self.D = np.hypot(u, v)
        self.bay = np.abs(self.T) <= BAY
        self.mull = (np.floor(self.T).astype(int) % 4) == 0
        self.lamps = HR.grid_mask(fr, 6, 3, du, dv)
        self.core = (np.maximum(np.abs(u), np.abs(v)) <= 10.0)
        self.core_ring = kit.ring(self.core)
        self.notch91 = (np.minimum(np.abs(u), np.abs(v)) < 1.8) & (self.S > TOP91 - 2.4)


def tower_mass(F, yy):
    """塔樓在第 yy 列（離一樓樓板 yy 格）的平面遮罩。"""
    sec, m = section(yy)
    if sec == "base":
        a = half_width(yy)
        return (F.R <= a) | (F.bay & (F.S <= a + 1.0))
    if sec == "mod":
        return F.R <= half_width(yy)
    if sec == "top91":
        return (F.S <= TOP91) & ~F.notch91
    if sec == "shaft":
        t = yy + 0.5
        return F.S <= SHAFT0 + (SHAFT1 - SHAFT0) * (t - H_93) / (H_SHAFT - H_93)
    if sec == "crown":
        return F.D <= CROWN_R
    return np.zeros(F.R.shape, dtype=bool)


def tower_skin(F, yy, sh):
    """塔樓外殼第 yy 列的材質：[(遮罩, 方塊)]，後面蓋前面。"""
    sec, m = section(yy)
    k, kr = floor_of_row(yy)
    out = [(sh, GLASS)]
    if sec in ("base", "mod", "top91", "shaft"):
        out.append((sh & F.mull, MULLION))
        if kr == 0:
            out.append((sh, SPANDREL))
    if sec == "base":
        bay = sh & F.bay
        # 基座正中的開間：一層兩道深色橫帶（遠看是一條直的「梯子」）
        if kr in (0, 2):
            out.append((bay, MECH))
        else:
            out.append((bay, GLASS))
        if COIN_Y - 2 <= yy <= COIN_Y + 1:
            out.append((sh, BAND))
    elif sec == "mod":
        # 每斗最上面一層是機電層（外伸桁架所在），顏色深一點
        if k == 34 + 8 * m:
            out.append((sh & ~F.mull, MECH))
    elif sec == "crown":
        # 頂冠：玻璃加一圈圈的金屬環
        if kr == 0 or yy % 3 == 0:
            out.append((sh, SPIRE))
    return out


class Taipei101(Attraction):
    height_m = 508.0
    margin = 12
    # 預設觀景點在塔西南 210 m（整座塔才塞得進視野）：那一帶也要是真實地形
    terrain_margin = 240

    # ---------------------------------------------------------------- 資料
    def _ring(self, osm):
        f = self.feature(osm)
        if not f or not f.get("outer"):
            return None
        return max(f["outer"], key=len)

    def _mask(self, fr, osms):
        m = fr.empty()
        for o in (osms if isinstance(osms, (list, tuple)) else [osms]):
            r = self._ring(o)
            if r:
                m |= fr.polygon(r)
        return m

    def bbox(self):
        """景點範圍（含廣場、行道樹）：OSM 的 tourism=attraction 範圍（way/248210267）外擴 margin。"""
        r = self._ring(PLAZA) or self.outline()
        xs = [p[0] for p in r]
        zs = [p[1] for p in r]
        m = self.margin
        return (int(math.floor(min(xs))) - m, int(math.floor(min(zs))) - m,
                int(math.ceil(max(xs))) + m, int(math.ceil(max(zs))) + m)

    # ---------------------------------------------------------------- 定案
    def plan(self, site):
        self.site = site
        cx, cz, ang_osm, _, _ = HR.outline_axes(self._ring(TOWER))
        # 塔樓偏 1.0°：轉正（highrise.snap_angle 的說明），中心照 OSM。購物中心與裙樓
        # 仍照 OSM 的多邊形原樣光柵化（它們在世界座標裡，不受 Frame 角度影響）
        ang = HR.snap_angle(ang_osm)
        self.ang = ang
        self.fr = Frame(cx, cz, ang, 48)                        # 塔樓（含門口雨庇）
        x0, z0, x1, z1 = self.bbox()
        scx, scz = (x0 + x1) / 2.0, (z0 + z1) / 2.0
        self.sfr = Frame(scx, scz, ang, max(x1 - x0, z1 - z0) / 2.0 + 2)   # 整個基地
        # 塔樓中心在基地 Frame 的局部座標（兩個 Frame 同角度，局部座標只差一個平移）
        c, s = math.cos(ang), math.sin(ang)
        tu = (cx - scx) * c + (cz - scz) * s
        tv = -(cx - scx) * s + (cz - scz) * c
        self.tuv = (tu, tv)
        self.F = Fields(self.fr, 0.0, 0.0)
        self.SF = Fields(self.sfr, tu, tv)

        sfr = self.sfr
        self.m_mall = self._mask(sfr, MALL)
        self.m_skirt = self._mask(sfr, SKIRTS)
        self.m_vest = self._mask(sfr, VESTIBULE)
        self.m_dome = self._mask(sfr, DOME)
        self.m_canopy = [self._mask(sfr, o) for o in CANOPIES]
        self.m_walk = [self._mask(sfr, o) for o in SKYWALKS]
        self.m_plaza = self._mask(sfr, PLAZA)
        base0 = tower_mass(self.SF, 0)
        self.m_foot = self.m_mall | self.m_skirt | self.m_vest | base0
        self.g0 = site.level(sfr, base0)
        # 整地要用的地面高度現在就查好（Site 會快取）：cli 在 plan 之後就把
        # 「蓋出來的地面」的距離場丟掉了，build() 的時候再查會失敗
        site.grid(sfr, self.m_plaza | self.m_foot)

        # 觀景點：廣場西南角外的街上（信義路側），整座塔框得進畫面（塔尖仰角約 67°）
        pr = self._ring(PLAZA)
        vx = int(math.floor(min(p[0] for p in pr))) - 50
        vz = int(math.ceil(max(p[1] for p in pr))) + 49
        vy = site.g(vx, vz) + 1
        d = math.hypot(cx - (vx + .5), cz - (vz + .5))
        up = math.degrees(math.atan2(self.g0 + H_TIP - (vy + 1.62), d))
        down = math.degrees(math.atan2(vy + 1.62 - self.g0, d))
        yaw, _ = kit.look(vx, vy, vz, cx, self.g0 + 200, cz)
        pitch = round(-(up - down) / 2.0, 1)                    # 仰角的一半：塔腳到塔尖都在畫面裡
        # 大廳：電梯核南面 6 m（南門進來十幾公尺），面向核上的告示牌
        lx, lz = self.fr.cell(0.0, 16.0)
        # 89 樓：面向台北車站那一側（城市的方向）的窗邊
        a89 = half_width(OBS_ROW + 1)
        wu, wv = self._city_dir()
        tx, tz = self.fr.cell(wu * (a89 - 3.5), wv * (a89 - 3.5))
        self.top_cell = (tx, tz)
        self._spots = [
            Spot("", vx, vy, vz, yaw, pitch, self.name_zh, self.name_en),
            Spot("lobby", lx, self.g0 + 1, lz, round(self.fr.yaw(0, -1), 1), 0.0,
                 "台北101 大廳", "Taipei 101 Lobby"),
            Spot("top", tx, self.g0 + OBS_ROW + 1, tz, round(self.fr.yaw(wu, wv), 1), 12.0,
                 "89 樓觀景台", "89F Observatory"),
        ]

    def _city_dir(self):
        """塔樓往台北車站（原點）的方向，換成局部座標的單位向量。"""
        dx, dz = -self.fr.cx, -self.fr.cz
        L = math.hypot(dx, dz) or 1.0
        dx, dz = dx / L, dz / L
        c, s = math.cos(self.ang), math.sin(self.ang)
        return dx * c + dz * s, -dx * s + dz * c

    def plaque(self):
        # 告示牌一行最寬 90 px（signage.SIGN_W）：這兩行各 88、85 px
        return [self.name_zh, self.name_en, "508 m，2004年落成", "101 層，八斗各八層"]

    # ---------------------------------------------------------------- 蓋
    def build(self, w):
        self._ground(w)
        self._podium(w)
        self._tower(w)
        self._spire(w)
        self._ornaments(w)
        self._observatory(w)
        self._lobby(w)
        self._canopies(w)
        self._skywalks(w)
        self._trees(w)

    # ---- 整地：基地整成一樓樓板的高度，廣場鋪石板 ----
    def _ground(self, w):
        sfr = self.sfr
        self.site.prepare(w, sfr, self.m_plaza & ~self.m_foot, self.g0, top=PAVING)
        self.site.prepare(w, sfr, self.m_foot, self.g0, top=FLOOR1)

    # ---- 購物中心、裙樓、塔樓的前 31 列（同一個遮罩，交界不砌內牆）----
    def _podium_mass(self, yy):
        m = np.zeros_like(self.m_foot)
        if yy < 30:
            m = m | self.m_mall
        if yy < 25:
            m = m | self.m_skirt
        if yy < 8:
            m = m | self.m_vest
        return m

    def _podium(self, w):
        sfr, SF, g0 = self.sfr, self.SF, self.g0
        mass = {}

        near_tower = SF.S <= BASE_A0 + 4.0

        def M(yy):
            if yy not in mass:
                if yy < 0:
                    mass[yy] = (sfr.empty(), sfr.empty())
                else:
                    t = tower_mass(SF, yy)
                    m = self._podium_mass(yy) | t
                    if yy < 25:
                        # OSM 的裙樓在塔樓轉角照 45° 斜切的缺口畫，這裡的塔樓是兩階鋸齒：
                        # 兩者之間留下幾個一兩格寬、沒有屋頂的小縫，補起來
                        m |= kit.erode(kit.dilate(m, 2), 2) & near_tower
                    mass[yy] = (t, m)
            return mass[yy]

        pillar = ((sfr.X + sfr.Z) % 6) == 0
        for yy in range(0, 31):
            t_m, m = M(yy)
            _, mp = M(yy - 1)
            _, mn = M(yy + 1)
            sh = HR.shell(m, mp, mn)
            y = g0 + yy
            tsh = sh & t_m
            psh = sh & ~t_m
            layers = tower_skin(SF, yy, tsh)
            # 購物中心：每層 6 m，樓板那列與最上一列是石材、中間是玻璃，每 6 格一根石柱
            kr = yy % 6
            mall = psh & self.m_mall
            layers.append((mall, MALL_WALL if kr in (0, 5) else GLASS))
            if kr not in (0, 5):
                layers.append((mall & pillar, MALL_WALL))
            # 裙樓：跟塔樓同一種玻璃，每層 5 m
            sk = psh & ~self.m_mall
            layers.append((sk, SPANDREL if yy % 5 == 0 else GLASS))
            if yy % 5:
                layers.append((sk & self.SF.mull, MULLION))
            HR.paint_layers(w, sfr, layers, y)
            # 屋頂：這一列有、上一列沒有（圓頂那一塊挑空，屋頂由圓頂自己蓋）
            cap = m & ~mn & ~sh & ~self.m_dome
            HR.paint(w, sfr, cap & ~t_m, y, MALL_ROOF)
            HR.paint(w, sfr, cap & t_m, y, GLASS)
            inner = m & ~sh
            slab = sfr.empty()
            if yy in ROW_FLOOR and yy not in SKIP_SLAB:
                slab |= inner & t_m
            if yy % 6 == 0:
                slab |= inner & self.m_mall & ~t_m & (~self.m_dome | (yy == 0))
            if yy % 5 == 0:
                slab |= inner & (self.m_skirt | self.m_vest) & ~self.m_mall & ~t_m
            if yy > 0:
                HR.paint(w, sfr, slab & ~cap, y, SLAB)
                HR.paint(w, sfr, slab & ~cap & self.SF.lamps, y, LAMP)
            if yy > 0:
                HR.paint(w, sfr, SF.core_ring & t_m & ~sh & ~slab, y, CORE)
        # 如意形圓頂：購物中心屋頂上的玻璃拱，30 -> 42 m
        dm = self.m_dome
        h = HR.dome(dm, 12.0)
        rib = (np.floor(sfr.U).astype(int) % 5 == 0) | (np.floor(sfr.V).astype(int) % 5 == 0)
        p = kit.Painter(w, sfr)
        p.heightfield(dm & ~rib, g0 + 29, h, DOME_GLASS, shell=1)
        p.heightfield(dm & rib, g0 + 29, h, DOME_RIB, shell=1)
        HR.paint(w, sfr, kit.ring(dm), g0 + 29, MALL_ROOF)

    # ---- 塔樓：第 31 列到屋頂 ----
    def _tower(self, w):
        fr, F, g0 = self.fr, self.F, self.g0
        cache = {}

        def M(yy):
            if yy not in cache:
                cache[yy] = tower_mass(F, yy)
            return cache[yy]

        hole = F.D <= 5.5                              # 阻尼器那一圈樓板挖空
        for yy in range(31, H_ROOF):
            m = M(yy)
            if not m.any():
                continue
            mn, mp = M(yy + 1), M(yy - 1)
            sh = HR.shell(m, mp, mn)
            y = g0 + yy
            HR.paint_layers(w, fr, tower_skin(F, yy, sh), y)
            cap = m & ~mn & ~sh
            sec, mod = section(yy)
            if section_top(yy):
                # 一段的頂：外緣一圈白色挑簷（遠看是每斗頂的那一圈亮邊）。基座與各斗的頂
                # 是往內收的玻璃斜頂（下面 slope），91 樓戶外觀景台（第八斗的頂）鋪地坪
                if sec == "mod" and mod == 7:
                    HR.paint(w, fr, cap, y, FLOOR1)
                elif sec in ("base", "mod"):
                    HR.paint(w, fr, cap, y, GLASS)
                else:
                    HR.paint(w, fr, cap, y, LEDGE)
                HR.paint(w, fr, sh & ~mn, y, LEDGE)
            elif cap.any():
                # 斜面每收一格露出來的小平台：跟立面一樣是玻璃
                HR.paint(w, fr, cap, y, GLASS)
            if sec == "mod":
                # 斗與斗之間的玻璃斜頂：從下面那一斗的挑簷往內、往上收三格，接到這一斗的底
                yt = int(math.ceil(H_BASE + mod * H_MOD - 0.5)) - 1
                i = yy - yt
                if 1 <= i <= 3:
                    slope = (F.R <= half_width(yt) - 1.2 * i) & ~m
                    HR.paint(w, fr, slope, y, GLASS)
            inner = m & ~sh & ~cap
            if yy in ROW_FLOOR and yy not in SKIP_SLAB:
                sl = inner
                if 86 <= ROW_FLOOR[yy] <= 92:
                    sl = sl & ~hole
                HR.paint(w, fr, sl, y, FLOOR1 if yy == OBS_ROW else SLAB)
                HR.paint(w, fr, sl & F.lamps, y, LAMP)
            elif yy < CORE_TOP:
                HR.paint(w, fr, F.core_ring & inner, y, CORE)

    # ---- 塔尖：449 -> 508 m，底座是錐、上面越來越細，頂端是白色的避雷針 ----
    def _spire(self, w):
        fr, F, g0 = self.fr, self.F, self.g0
        for yy in range(H_ROOF, H_TIP + 1):
            if yy <= 454:
                r = 3.4 - 0.25 * (yy - H_ROOF)
                HR.paint(w, fr, F.D <= r, g0 + yy, SPIRE)
            elif yy <= 478:
                HR.paint(w, fr, F.S <= 1.0, g0 + yy, SPIRE)
                if yy in (462, 470):
                    HR.paint(w, fr, F.D <= 2.2, g0 + yy, BAND)
            elif yy <= 498:
                x, z = fr.cell(0.0, 0.0)
                w.set(x, g0 + yy, z, SPIRE)
                if yy == 488:
                    HR.paint(w, fr, F.D <= 1.3, g0 + yy, BAND)
            else:
                x, z = fr.cell(0.0, 0.0)
                w.set(x, g0 + yy, z, "minecraft:end_rod[facing=up]")

    # ---- 古錢（基座頂、每面一枚）與如意（每斗頂、每面一個）----
    def _ornaments(self, w):
        fr, F, g0 = self.fr, self.F, self.g0
        # 古錢：直徑 13 m 的圓盤、凸出立面 3 m；正面是外圈、錢面、方孔
        for yy in range(int(COIN_Y - COIN_R) - 1, int(COIN_Y + COIN_R) + 2):
            a = half_width(yy)
            dy = yy - COIN_Y
            rr = np.hypot(F.T, dy)
            disc = (rr <= COIN_R) & (F.S > a) & (F.S <= a + 3.0) & ~F.bay | \
                   (rr <= COIN_R) & (F.S > a + 1.0) & (F.S <= a + 4.0) & F.bay
            if not disc.any():
                continue
            front = disc & ((F.S > a + 2.0) & ~F.bay | (F.S > a + 3.0) & F.bay)
            y = g0 + yy
            HR.paint(w, fr, disc & ~front, y, BAND)
            HR.paint(w, fr, front & (rr > COIN_R - 1.3), y, COIN_RIM)
            face = front & (rr <= COIN_R - 1.3)
            sq = np.maximum(np.abs(F.T), abs(dy))
            HR.paint(w, fr, face & (sq > 2.5), y, COIN_FACE)
            HR.paint(w, fr, face & (sq <= 2.5) & (sq > 1.5), y, COIN_HOLE)
            HR.paint(w, fr, face & (sq <= 1.5), y, MECH)
        # 如意：貼在每一斗頂端（挑簷下一列開始往下畫），凸出立面一格
        pts = RUYI_GLYPH
        for m in range(8):
            top = int(math.ceil(H_BASE + (m + 1) * H_MOD - 0.5)) - 2
            for i, j in pts:
                yy = top - i
                a = half_width(yy)
                col = j - 3
                cellm = (np.floor(F.T).astype(int) == col) & (F.S > a) & (F.S <= a + 1.0)
                HR.paint(w, fr, cellm, g0 + yy, RUYI)

    # ---- 89 樓觀景台、阻尼器、91 樓戶外觀景台 ----
    def _observatory(self, w):
        fr, F, g0 = self.fr, self.F, self.g0
        y_obs = g0 + OBS_ROW
        a = half_width(OBS_ROW + 1)
        inner = F.R <= a - 1.5
        # 兩層挑高的觀景空間（89、90 樓），把中間清空
        for yy in range(OBS_ROW + 1, DECK_ROW):
            HR.paint(w, fr, inner & ~(F.D <= 3.0), g0 + yy, kit.AIR)
        # 阻尼器：直徑 5.5 m 的金色鋼球，球心在 89 樓樓板高度（上半在 89 樓、下半在 88 樓）
        cx, cz = fr.world(0.0, 0.0)
        HR.sphere(w, cx, y_obs + 0.5, cz, 2.75, TMD)
        # 吊索：從球頂拉到 91 樓樓板（92 樓在它上面）
        for du, dv in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
            x, z = fr.cell(du, dv)
            for y in range(y_obs + 3, g0 + DECK_ROW):
                w.set(x, y, z, CHAIN)
        # 洞口的玻璃欄杆
        HR.paint(w, fr, (F.D > 5.5) & (F.D <= 6.5), y_obs + 1, RAIL)
        # 91 樓戶外觀景台：第八斗的頂上一圈，外緣一格高的玻璃欄板
        a8 = half_width(DECK_ROW)
        deck = (F.R <= a8) & ~((F.S <= TOP91) & ~F.notch91)
        HR.paint(w, fr, kit.ring(F.R <= a8) & deck, g0 + DECK_ROW + 1, RAIL)
        # 觀景台的燈：天花（91 樓樓板）與地坪各一格燈
        HR.paint(w, fr, inner & F.lamps & ~(F.D <= 6.5), y_obs, LAMP)
        HR.paint(w, fr, inner & F.lamps, g0 + DECK_ROW, LAMP)
        # 告示牌：回一樓大廳；阻尼器的說明牌
        tx, tz = self.top_cell
        wu, wv = self._city_dir()
        ru, rv = -wv, wu                                  # 觀景點右手邊
        su, sv = self.fr.local(tx, tz)
        sx, sz = fr.cell(su + ru * 2.0 - wu * 1.0, sv + rv * 2.0 - wv * 1.0)
        w.sign(sx, y_obs + 1, sz, ["回 1 樓 ▼", "To Lobby", "", ""],
               facing=(tx - sx, tz - sz), wood="pale_oak", kind="standing", glow=True,
               command="function %s:%s" % (config.DATAPACK_NS, kit.sight_fn(self.id, "lobby")))
        mx, mz = fr.cell(0.0, 7.5)
        w.sign(mx, y_obs + 1, mz, ["調諧質量阻尼器", "660 公噸", "直徑 5.5 m", "88～92 樓"],
               facing=fr.dir(0, 1), wood="pale_oak", kind="standing", glow=True)

    # ---- 一樓大廳：南、東兩面開門，電梯核上立往 89 樓的告示牌 ----
    def _lobby(self, w):
        fr, F, g0 = self.fr, self.F, self.g0
        foot = set()
        m1 = self._podium_mass(1) | tower_mass(self.SF, 1)
        for x, z in zip(self.sfr.X[m1].tolist(), self.sfr.Z[m1].tolist()):
            foot.add((x, z))
        for du, dv in ((0.0, 1.0), (1.0, 0.0)):
            # 從外往內找第一道牆
            hit = None
            for k in range(90, 30, -1):
                d = k * 0.5
                x, z = fr.cell(du * d, dv * d)
                if (x, z) in foot:
                    hit = d
                    break
            if hit is None:
                continue
            face = kit.cardinal(*fr.dir(-du, -dv))     # 進門的人面向的方位
            tu, tv = dv, du                             # 沿牆方向
            for s, hinge in ((-0.5, "left"), (0.5, "right")):
                x, z = fr.cell(du * hit + tu * s, dv * hit + tv * s)
                HR.door(w, x, g0 + 1, z, face, hinge=hinge)
                for dd in (-1.0, 1.0):
                    xx, zz = fr.cell(du * (hit + dd) + tu * s, dv * (hit + dd) + tv * s)
                    w.set(xx, g0 + 1, zz, kit.AIR)
                    w.set(xx, g0 + 2, zz, kit.AIR)
            for s in (-1.5, 1.5):
                x, z = fr.cell(du * hit + tu * s, dv * hit + tv * s)
                w.set(x, g0 + 1, z, GLASS)
                w.set(x, g0 + 2, z, GLASS)
        # 電梯核南面：兩座電梯門（鐵框）與告示牌
        for su in (-4.0, -3.0, 3.0, 4.0):
            for yy in (1, 2, 3):
                x, z = fr.cell(su, 10.0)
                w.set(x, g0 + yy, z, COIN_RIM)
        sx, sz = fr.cell(0.0, 12.0)
        w.sign(sx, g0 + 1, sz, ["89 樓觀景台 ▲", "89F Observatory", "", ""],
               facing=fr.dir(0, 1), wood="pale_oak", kind="standing", glow=True,
               command="function %s:%s" % (config.DATAPACK_NS, kit.sight_fn(self.id, "top")))

    # ---- 門口雨庇：一層高（5 m）的頂板與柱子，底下走得過去 ----
    def _canopies(self, w):
        sfr, g0 = self.sfr, self.g0
        post = HR.grid_mask(sfr, 5, 0)
        for m in self.m_canopy:
            m = m & ~self.m_foot
            if not m.any():
                continue
            HR.paint(w, sfr, m, g0 + 5, LEDGE)
            rg = kit.ring(m) & post
            for yy in range(1, 5):
                HR.paint(w, sfr, rg, g0 + yy, MALL_WALL)

    # ---- 空橋：二樓高的玻璃廊道（只蓋景點範圍裡那一段）----
    def _skywalks(self, w):
        sfr, g0 = self.sfr, self.g0
        post = HR.grid_mask(sfr, 12, 0)
        for m in self.m_walk:
            m = m & ~self.m_foot
            if not m.any():
                continue
            rg = kit.ring(m)
            HR.paint(w, sfr, m, g0 + 6, SLAB)
            for yy in (7, 8, 9):
                HR.paint(w, sfr, rg, g0 + yy, GLASS)
            HR.paint(w, sfr, m, g0 + 10, MALL_ROOF)
            for yy in range(1, 6):
                HR.paint(w, sfr, m & post & kit.erode(m, 1), g0 + yy, MALL_WALL)

    # ---- 廣場的行道樹：每 8 m 一棵，門口前面與空橋底下留空 ----
    def _trees(self, w):
        sfr, g0 = self.sfr, self.g0
        free = self.m_plaza & ~kit.dilate(self.m_foot, 4)
        for m in self.m_canopy:
            free &= ~kit.dilate(m, 3)
        for m in self.m_walk:
            free &= ~kit.dilate(m, 3)
        # 南門、東門前面各留一條 14 m 寬的通道
        tu, tv = self.tuv
        free &= ~((np.abs(sfr.U - tu) <= 7) & (sfr.V > tv))
        free &= ~((np.abs(sfr.V - tv) <= 7) & (sfr.U > tu))
        spots = free & HR.grid_mask(sfr, 8, 4)
        keep = self.site.keep

        def near_keep(x, z):
            """樹冠 3 格內有禁區（捷運 4 號出口就在南廣場）：不種，免得擋住出口的門。"""
            if keep is None:
                return False
            return any(keep(x + dx, self.g0 + dy, z + dz)
                       for dx in range(-4, 5, 2) for dz in range(-4, 5, 2) for dy in (1, 4, 7))

        for x, z in zip(sfr.X[spots].tolist(), sfr.Z[spots].tolist()):
            if near_keep(x, z):
                continue
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    w.set(x + dx, g0, z + dz, "minecraft:grass_block[snowy=false]")
            HR.tree(w, x, g0, z, trunk=4, r=2.8)


BUILDS = {"taipei101": Taipei101}
