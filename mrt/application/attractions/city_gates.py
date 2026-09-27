#!/usr/bin/env python3
"""臺北府城現存的四座城門：北門（承恩門）、東門（景福門）、南門（麗正門）、小南門（重熙門）。

位置、方位、城座輪廓照 OSM（historic=city_gate 的 way）；長相照公開資料與照片：

  北門   光緒十年（1884）完工，四門裡唯一保留清代原貌的一座。封閉的碉堡式城樓：
         安山岩條石交錯砌成的城座、中央圓拱門洞（外拱比內拱小，中間是矩形的門扇間）；
         上層是紅磚牆，北面外壁有「二方一圓」三個窗洞，圓拱上方橫額題「承恩門」；
         單簷歇山頂、紅瓦、兩端上捲的屋脊；二樓內部另有一道內牆，成「回」字形
         （zh.wikipedia〈臺北府城北門〉；文化部國家文化記憶庫〈臺北府城—北門〉）。
  東門、南門、小南門
         1966 年臺北市政府以「整頓市容」為由，把城樓改建成中國北方宮殿式的鋼筋混凝土
         建築，只有石砌的城座與門洞保留清代原物（zh.wikipedia 各門條目；文化資產局
         國定古蹟環景導覽〈臺北府城—東門、南門、小南門、北門〉）。照片上三座都是：
         灰色條石城座、城座頂一圈白色雉堞、城樓紅柱、簷下青綠彩畫與斗拱、
         單簷歇山頂、綠色琉璃瓦、黃色屋脊與鴟吻。
         小南門的城樓是四周迴廊的敞廳（廊柱式），背面（城內側）的欄杆以紅磚砌出花樣。
         東門、南門、小南門都在圓環或安全島上，城座四周是草坪、修剪過的灌木與石砌花台。

尺寸：城座長寬照 OSM 輪廓；南門的 OSM 外框 33.8 × 19.5 m 比照片量得的城座大將近一倍
（照片裡拱門寬約是城座寬的 0.27，跟東門一樣），外框應是連同四角的石砌花台與草坪一起描的
—— 城座取 18.5 × 13.5 m 置中，外框其餘部分做成花台與草坪。高度（城座約 5 m、屋脊 12～15 m）
是照片裡跟城座寬度比例量的，沒有官方數字。

資料：data/attractions.json 的北門有指名的 way/238316480。東門、南門、小南門的目錄中心點
（mrt/adapters/osm/fetch_attractions.py 的 CATALOG）離真正的城門 146～348 m，抓回來的資料裡
沒有城門本身 —— 這裡先用 OSM 的城門 way 當後備輪廓（下面的 OSM_RINGS，同一套投影算的），
資料修正之後（目錄改指名這三個 way）會自動改用資料裡的那一份。
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions import trad_parts as TP
from mrt.application.attractions.kit import Attraction, Frame, Painter, Spot

AIR = kit.AIR

# OSM 的城門輪廓（MC 座標，照 fetch_attractions 同一個原點與投影換算，保留到 0.1 m）。
# 資料 © OpenStreetMap 貢獻者，ODbL 1.0。目錄修正後資料裡就會有，這份只是後備。
OSM_RINGS = {
    "way/209580573": [   # 臺北府城東門（景福門）
        [14.7, 806.4], [16.2, 803.1], [17.6, 798.3], [19.1, 792.8], [19.2, 789.4], [21.7, 790.5],
        [29.4, 792.6], [32.3, 792.7], [30.9, 795.2], [29.3, 801.5], [27.7, 807.4], [27.7, 809.7],
        [25.6, 808.7], [16.9, 806.4]],
    "way/245993047": [   # 臺北府城南門（麗正門）
        [-260.9, 1239.7], [-227.4, 1244.1], [-224.8, 1224.8], [-258.3, 1220.4]],
    "way/246651384": [   # 臺北府城小南門（重熙門）
        [-947.0, 1029.0], [-934.8, 1034.6], [-940.0, 1045.9], [-946.5, 1042.9], [-952.3, 1040.3]],
}

# ---- 材質 ----
RED_WALL = "minecraft:red_terracotta"          # 北門上層的紅磚牆（照片上的朱紅）
BRICK = "minecraft:bricks"
RED_COL = "minecraft:red_concrete"             # 宮殿式城樓的紅柱
TAN_WALL = "minecraft:smooth_sandstone"        # 柱間的牆（照片上淡黃）
BEAM = "minecraft:warped_planks"               # 額枋的青綠彩畫底色
BEAM_PANEL = "minecraft:prismarine_bricks"     # 彩畫的枋心（淺色的框）
SOFFIT = "minecraft:dark_prismarine"           # 簷下斗拱、椽子
GOLD = "minecraft:honeycomb_block"             # 黃色的屋脊、鴟吻、博風板
WHITE = "minecraft:white_concrete"             # 城座頂的雉堞
WHITE_TRIM = "minecraft:smooth_quartz"
DARK_RIDGE = "minecraft:polished_deepslate"    # 北門的灰黑屋脊
PAVE = "minecraft:polished_andesite"
PAVE2 = "minecraft:smooth_stone"
GRASS = "minecraft:grass_block"
HEDGE = "minecraft:azalea_leaves[distance=1,persistent=true,waterlogged=false]"
HEDGE2 = "minecraft:flowering_azalea_leaves[distance=1,persistent=true,waterlogged=false]"
CONIFER = "minecraft:spruce_leaves[distance=1,persistent=true,waterlogged=false]"

# 城座的條石：兩種灰階的組合，照石頭的「層」與「塊」交錯（安山岩條石的交丁砌）
STONE_DARK = ("minecraft:tuff_bricks", "minecraft:polished_tuff", "minecraft:stone_bricks")
STONE_LIGHT = ("minecraft:stone_bricks", "minecraft:andesite", "minecraft:polished_andesite")


def _hash(x, y, z):
    return ((x * 73856093) ^ (y * 19349663) ^ (z * 83492791)) & 0xFFFF


def ashlar(x, y, z, mix):
    """條石的材質：每層的石塊長 2～3 格、上下層錯縫；三種灰階輪流。"""
    course = y % 2
    blk = (x + z + course) // 3
    return mix[_hash(blk, y, course) % len(mix)]


def rect_frame(ring, outer):
    """OSM 輪廓 -> (中心 x, z, 角度, 半長 a, 半寬 b)：u 沿城牆（長邊）、v 沿門洞，
    城外（outer 那一側，世界方向 (dx, dz)）在 -v。"""
    ang = kit.principal_angle(ring)
    for _ in range(4):
        c, s = math.cos(ang), math.sin(ang)
        vx, vz = -s, c                                   # v 軸的世界方向
        ux, uz = c, s
        if abs(outer[0] * ux + outer[1] * uz) > abs(outer[0] * vx + outer[1] * vz):
            ang += math.pi / 2                           # 門洞要沿 v
            continue
        if outer[0] * vx + outer[1] * vz > 0:
            ang += math.pi                               # 城外要在 -v
            continue
        break
    c, s = math.cos(ang), math.sin(ang)
    cx0 = sum(p[0] for p in ring) / len(ring)
    cz0 = sum(p[1] for p in ring) / len(ring)
    us = [(x - cx0) * c + (z - cz0) * s for x, z in ring]
    vs = [-(x - cx0) * s + (z - cz0) * c for x, z in ring]
    um, vm = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
    cx, cz = cx0 + um * c - vm * s, cz0 + um * s + vm * c
    return cx, cz, ang, (max(us) - min(us)) / 2, (max(vs) - min(vs)) / 2


class CityGate(Attraction):
    """城門的共同骨架：城座、門洞、四周的地面、觀景點。上層由子類別蓋。"""

    osm = None                 # 城門 way 的 id
    outer = (0, -1)            # 城外的世界方向（門額所在的那一面）
    base_half = None           # 覆寫城座半長、半寬 (a, b)；None 照 OSM
    base_h = 5                 # 城座高（格）
    stone = STONE_DARK
    passage = (4.0, 2.4)       # 門洞寬、起拱高（公尺）
    view_dist = 22             # 觀景點離城座外牆幾公尺
    plaque_text = ""
    fact_lines = ("", "")      # 說明牌背面兩行（每行要放得下告示牌寬 90 px）
    margin = 16

    def __init__(self, item):
        super().__init__(item)
        f = self.feature(self.osm) if self.osm else None
        if f and f.get("outer"):
            self.ring = [tuple(p) for p in max(f["outer"], key=len)]
        else:
            self.ring = [tuple(p) for p in OSM_RINGS[self.osm]]
        self.cx, self.cz, self.ang, self.ra, self.rb = rect_frame(self.ring, self.outer)
        self.a, self.b = self.base_half or (self.ra, self.rb)

    # ---- 位置：一律照城門的 OSM 輪廓（目錄中心點可能不準）----
    def outline(self):
        return list(self.ring)

    def center(self):
        return (sum(p[0] for p in self.ring) / len(self.ring),
                sum(p[1] for p in self.ring) / len(self.ring))

    def plaque(self):
        return [self.name_zh, self.name_en, self.fact_lines[0], self.fact_lines[1]]

    # ---- 定案 ----
    def plan(self, site):
        ext = max(self.ra, self.rb, self.a, self.b) + self.margin + 2
        self.fr = fr = Frame(self.cx, self.cz, self.ang, ext)
        self.base = fr.box(self.a, self.b)
        self.g0 = site.level(fr, self.base)
        self.hb = self.g0 + self.base_h                 # 城座頂那一格
        self.site = site
        self.ground = self._ground_mask()
        # 整地要查每一格的地面高度：cli 在 plan 之後就把地形距離場丟掉了（build 時
        # 再查會出錯），所以在這裡先查一遍，Site 會記在快取裡
        site.grid(fr, self.ground)
        self._spots = [self._pick_spot(site)]

    def _ground_mask(self):
        """整地範圍：城座外擴幾公尺的圓角矩形（安全島／廣場）。"""
        return self.fr.chamfer(self.a + 7, self.b + 7, 4)

    def _pick_spot(self, site):
        """城外正前方、離城座 view_dist 公尺的人行道上看城門。禁區（捷運出入口）或
        整地範圍裡的格子換下一個候選；都不行就換城內那一側。"""
        fr = self.fr
        cands = []
        for side in (-1, 1):
            for d in (self.view_dist, self.view_dist + 5, self.view_dist - 5, self.view_dist + 10):
                for lat in (0.0, -4.0, 4.0, -8.0, 8.0):
                    cands.append((lat, side * (self.b + d)))
        keep = site.keep
        for u, v in cands:
            x, z = fr.cell(u, v)
            i, j = z - fr.z0, x - fr.x0
            if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] and self.ground[i, j]:
                continue
            gy = site.g(x, z)
            pad = self._pad_cells(x, z, u, v)
            if keep is not None and any(keep(px, gy + dy, pz) for px, pz in pad for dy in (0, 1, 2)):
                continue
            ty = self.g0 + 1 + (self.height_m or 12) * 0.45
            yaw, pitch = kit.look(x, gy + 1, z, self.cx, ty, self.cz)
            self._pad = (pad, gy)
            return Spot("", x, gy + 1, z, yaw, pitch, self.name_zh, self.name_en)
        x, z = fr.cell(0, -(self.b + self.view_dist))
        gy = site.g(x, z)
        self._pad = (self._pad_cells(x, z, 0, -(self.b + self.view_dist)), gy)
        yaw, pitch = kit.look(x, gy + 1, z, self.cx, self.g0 + 5, self.cz)
        return Spot("", x, gy + 1, z, yaw, pitch, self.name_zh, self.name_en)

    def _pad_cells(self, x, z, u, v):
        """觀景點腳下鋪一小塊地：人站的格子、右手邊 2 格的說明牌，前後左右一格。"""
        out = set()
        for dx in range(-2, 3):
            for dz in range(-2, 3):
                out.add((x + dx, z + dz))
        return out

    # ---- 蓋 ----
    def build(self, w):
        p = Painter(w, self.fr)
        self._build_ground(w, p)
        self._build_base(p)
        self._build_passage(p)
        self._build_upper(p)
        self._build_pad(p)

    def _build_ground(self, w, p):
        fr = self.fr
        self.site.prepare(w, fr, self.ground, self.g0, top=GRASS)
        # 城座腳下一圈石板
        walk = kit.dilate(self.base, 1) & ~self.base
        p.layer(walk, self.g0, PAVE)

    def _build_base(self, p):
        """城座：條石實砌到 hb；頂上鋪石板。"""
        fr = self.fr
        s = p.w.set
        for x, z in fr.cells(self.base):
            for y in range(self.g0, self.hb + 1):
                s(x, y, z, ashlar(x, y, z, self.stone))

    def _passage_segments(self):
        """門洞沿 v 分段：[(v0, v1, 寬, 起拱高, 是否拱頂)]。預設一段貫穿。"""
        w, sp = self.passage
        return [(-self.b - 1, self.b + 1, w, sp, True)]

    def _build_passage(self, p):
        fr = self.fr
        Ua = np.abs(fr.U)
        # 地坪：門洞與前後各延伸 4 m 的石板路
        road = (Ua <= self.passage[0] / 2 + 0.6) & (np.abs(fr.V) <= self.b + 4)
        p.layer(road & ~self.base, self.g0, PAVE2)
        for v0, v1, w, sp, arched in self._passage_segments():
            sel = (fr.V >= v0) & (fr.V < v1) & (Ua <= w / 2 + 1.0) & self.base
            face = sel & (np.abs(fr.V) >= self.b - 1.0)
            if arched:
                TP.cut_arch(p, sel, Ua, self.g0 + 1, w, sp,
                            wall_facing=lambda i, j: fr.facing(1 if fr.U[i, j] > 0 else -1, 0),
                            stair_block="stone_brick", ring=face, ring_block="minecraft:chiseled_stone_bricks",
                            ceil_y=self.hb)
            else:
                h = min(int(round(sp)), self.hb - self.g0 - 1)
                for x, z in fr.cells(sel & (Ua <= w / 2 + 0.05)):
                    for y in range(self.g0 + 1, self.g0 + 1 + h):
                        p.set(x, y, z, AIR)
            p.layer(sel & (Ua <= w / 2 + 0.05), self.g0, "minecraft:stone_bricks")

    def _build_upper(self, p):
        raise NotImplementedError

    def _build_pad(self, p):
        pad, gy = self._pad
        for x, z in pad:
            p.set(x, gy, z, PAVE2 if (x + z) % 2 else PAVE)
            p.set(x, gy + 1, z, AIR)
            p.set(x, gy + 2, z, AIR)

    # ---- 共用小零件 ----
    def wall_plaque(self, p, u, v, y, text, board="minecraft:polished_blackstone", width=3,
                    wood="dark_oak", color="#E8C15A", facing_v=-1):
        """門額：牆面上 width 格深色匾、中間掛一面告示牌寫字（金字）。"""
        for k in range(width):
            du = k - (width - 1) / 2.0
            p.at(u + du, v, y, board)
        TP.plaque_sign(p, u, v, y, (0, facing_v), ["", dict(text=text, color=color, bold=True), "", ""],
                       wood=wood, glow=True)

    def _gables(self, p, tops, a, b, gin, fill, border):
        """歇山兩端的山花：從端坡往上砌到長坡的高度，最上一格是博風板。"""
        fr = self.fr
        for su in (-1, 1):
            cells = (su * fr.U > a - gin) & (su * fr.U <= a - gin + 1.0) & (np.abs(fr.V) < b - gin + 0.3)

            def ytop(i, j, su=su):
                t = TP.top_at(tops, fr, su * (a - gin - 0.6), float(fr.V[i, j]))
                return (t if t is not None else tops[i, j])
            TP.gable_face(p, cells, tops, ytop, fill, border=border)

    def _hip_ridges(self, p, tops, a, b, gin, block, curl=1):
        """歇山的垂脊（沿山花斜邊）與戧脊（斜向四個翼角），尾端往外上方翹 curl 格。
        格子照離脊線的距離挑（一格寬），高度跟著底下的屋面走。"""
        fr = self.fr
        for su in (-1, 1):
            for sv in (-1, 1):
                ug = su * (a - gin + 0.3)
                # 垂脊：騎在山花的斜邊（博風板）上，高度跟著長坡走
                m, _ = TP.seg_mask(fr, ug, 0.0, ug, sv * (b - gin))
                for i, j in np.argwhere(m):
                    t = TP.top_at(tops, fr, su * (a - gin - 0.6), float(fr.V[i, j]))
                    if t is not None:
                        p.set(int(fr.X[i, j]), t + 1, int(fr.Z[i, j]), block)
                # 戧脊：從山花腳斜向翼角，高度是那一格屋面 + 1
                u1, v1 = su * (a - 0.4), sv * (b - 0.4)
                m, tt = TP.seg_mask(fr, ug, sv * (b - gin), u1, v1)
                end = None
                for i, j in np.argwhere(m & (tops > -999)):
                    y = int(tops[i, j]) + 1
                    p.set(int(fr.X[i, j]), y, int(fr.Z[i, j]), block)
                    if end is None or tt[i, j] > end[0]:
                        end = (float(tt[i, j]), i, j, y)
                if end is not None:
                    _, i, j, y = end
                    x, z = int(fr.X[i, j]), int(fr.Z[i, j])
                    for c in range(1, curl + 1):                 # 翼角尾端翹起
                        p.set(x, y + c, z, block)


# ================================================================ 北門：清代原貌

class Beimen(CityGate):
    """北門（承恩門）：碉堡式城樓、紅磚牆、紅瓦單簷歇山、灰黑燕尾脊。

    量法（照片，以城座寬 15 m 為尺）：城座高約 5.3 m、上層紅牆約 4.7 m、屋脊約 12.5 m、
    兩端上捲的脊尾到 14 m；北面門洞淨寬約 3.6 m、高約 4.3 m；外壁兩個方窗約
    1.1 × 1.3 m、中間圓窗直徑約 1.3 m、窗台離地約 7 m；「承恩門」匾在拱頂正上方、
    紅牆最下緣。"""

    osm = "way/238316480"
    outer = (0, -1)                     # 門額在北面（外壁）
    base_h = 5
    stone = STONE_DARK
    height_m = 14.0
    view_dist = 20
    fact_lines = ("1884 年 · 清代原貌", "四門裡唯一沒改建")

    def _ground_mask(self):
        # 北門廣場：城門四周是鋪面廣場
        return self.fr.chamfer(self.a + 9, self.b + 9, 5)

    def _build_ground(self, w, p):
        fr = self.fr
        self.site.prepare(w, fr, self.ground, self.g0, top=PAVE)
        # 廣場鋪面：每 4 m 一道淺色分隔
        grid = ((np.floor(fr.U) % 4 == 0) | (np.floor(fr.V) % 4 == 0)) & self.ground
        p.layer(grid, self.g0, PAVE2)
        # 城座四周一圈矮石階（門洞前後留空）
        step = kit.dilate(self.base, 1) & ~self.base & ~(np.abs(fr.U) <= 2.6)
        p.layer(step, self.g0 + 1, TP.slab("smooth_stone"))

    def _passage_segments(self):
        # 外拱（北）比內拱（南）小，中間是放門扇的矩形門洞（文化資產局導覽）
        b = self.b
        return [(-b - 1, -b + 3.0, 3.6, 2.5, True),
                (-b + 3.0, -b + 5.5, 5.0, 4.0, False),
                (-b + 5.5, b + 1, 4.6, 2.4, True)]

    def _build_upper(self, p):
        fr = self.fr
        a, b, g0 = self.a, self.b, self.g0
        y0, y1 = self.hb + 1, self.hb + 5              # 紅牆 g0+6 .. g0+10
        shell = kit.ring(self.base)
        p.fill(shell, y0, y1, RED_WALL)
        inner = kit.erode(self.base, 1)
        p.clear(inner, y0, y1 - 1)
        p.layer(inner, y1, "minecraft:spruce_planks")   # 天花
        # 「回」字形的內牆（二樓內部另有一道內壁）
        in2 = kit.ring(fr.box(a - 2.6, b - 2.4))
        door = np.abs(fr.U) <= 1.0
        p.fill(in2 & ~door, y0, y1 - 1, BRICK)
        # 北面（外壁）：二方一圓；方窗磚框、圓窗石框
        yw = g0 + 8
        for uw in (-3.7, 3.7):
            self._window(p, uw, -b, yw, frame=BRICK)
        self._window(p, 0.0, -b, yw, frame="minecraft:polished_andesite")
        # 南面（城內側）與兩側：方窗、側面各一個拱窗
        for uw in (-3.7, 3.7):
            self._window(p, uw, b, yw, frame=BRICK, inward=-1)
        for su in (-1, 1):
            # 側面正中一個拱形窗（1 格寬、2 格高），磚框
            uu = su * (a - 0.3)
            for dv, dy in ((0, 1), (0, -2), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
                p.at(uu, dv, yw + dy, BRICK)
            p.at(uu, 0, yw, AIR)
            p.at(uu, 0, yw - 1, AIR)
        # 門額「承恩門」：北面拱頂正上方、紅牆最下緣
        self.wall_plaque(p, 0.0, -b + 0.3, y0, "承恩門")
        self._roof(p)

    def _window(self, p, u, v, y, frame, inward=1):
        """牆上一個 1 × 1 的窗洞（穿透一格厚的牆）與一圈窗框。"""
        fr = self.fr
        vv = v + 0.3 * inward
        for du in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if du == 0 and dy == 0:
                    continue
                p.at(u + du, vv, y + dy, frame)
        x, z = fr.cell(u, vv)
        p.set(x, y, z, AIR)

    def _roof(self, p):
        fr = self.fr
        a, b = self.a + 0.5, self.b + 0.5
        gin, rise, prof = 2.0, 1.9, 1.3
        y_eave = self.hb + 5                            # 簷口那一圈與牆頂同高
        mask = fr.box(a, b)
        h = kit.hip_gable(fr, a, b, rise, gin, profile=prof, lift=0.8)
        tops = TP.tile_roof(p, mask, y_eave, h, TP.ORANGE_TILES, shell=2,
                            under="minecraft:spruce_planks", under_mask=mask & ~self.base)
        # 山花：紅牆，博風板用磚
        self._gables(p, tops, a, b, gin, RED_WALL, BRICK)
        # 正脊：灰黑，兩端上捲（照片上兩端翹起、往外伸出山牆）
        ridge_y = max(t for t in (TP.top_at(tops, fr, u, 0) for u in np.arange(-a + gin, a - gin, 1.0)) if t) + 1
        TP.swallowtail(p, a - gin, ridge_y + 0.5, DARK_RIDGE, ext=1.0, rise=1.4, body=1)
        # 垂脊（沿山花斜邊）與戧脊（到四個翼角），尾端各翹一格
        self._hip_ridges(p, tops, a, b, gin, DARK_RIDGE, curl=1)


# ================================================================ 1966 年的北方宮殿式城樓

class PalaceGate(CityGate):
    """東門、南門、小南門：灰色條石城座 + 白雉堞 + 紅柱城樓 + 綠琉璃瓦單簷歇山。"""

    stone = STONE_DARK
    pav = (7.0, 4.5)           # 城樓柱網的半長、半寬（公尺）
    bays = (5, 3)              # 面寬五間、進深三間
    col_h = 3                  # 柱高（格）：柱頂約 8 m、簷口約 10 m（照片）
    overhang = 2.3             # 出簷
    rise = 3.2
    gable_in = 2.4
    lift = 1.2
    open_hall = False          # 小南門：四周迴廊的敞廳
    back_railing = False       # 小南門：城內側欄杆用紅磚花格
    planters = False           # 四角的石砌花台（南門、小南門的安全島上）
    garden = False             # 安全島上的灌木與樹（南門）
    fence = False              # 安全島外緣的鐵欄杆（東門）

    def _grid(self, n, half):
        """柱位：明間（中間那間）寬 1.3 倍，其餘等寬。"""
        wts = [1.0] * n
        wts[n // 2] = 1.3
        tot = sum(wts)
        out, acc = [-half], -half
        for wv in wts:
            acc += 2 * half * wv / tot
            out.append(acc)
        return out

    def _build_ground(self, w, p):
        fr = self.fr
        self.site.prepare(w, fr, self.ground, self.g0, top=GRASS)
        walk = kit.dilate(self.base, 1) & ~self.base
        p.layer(walk, self.g0, PAVE)
        a, b, g0 = self.a, self.b, self.g0
        # 門洞兩側修剪成方塊的灌木（照片上每座城門的拱門兩邊都有）
        for su in (-1, 1):
            for sv in (-1, 1):
                hed = fr.box(1.3, 0.9, du=su * (self.passage[0] / 2 + 2.6), dv=sv * (b + 2.2))
                p.fill(hed, g0 + 1, g0 + 2, HEDGE)
        if self.garden:
            # 安全島的花園：城座兩個長面前一排修剪成柱狀的針葉灌木（拱門兩側留空），
            # 四角各一棵樹（照片上南門四周是高灌木與大樹）
            for sv in (-1, 1):
                row = fr.rect(-a + 1.0, a - 1.0, b + 1.2, b + 2.6) if sv > 0 else fr.rect(-a + 1.0, a - 1.0, -b - 2.6, -b - 1.2)
                row &= np.abs(fr.U) > self.passage[0] / 2 + 4.2
                p.fill(row, g0 + 1, g0 + 3, CONIFER)
            for su in (-1, 1):
                for sv in (-1, 1):
                    tu, tv = su * (a + 5.0), sv * (b + 1.2)
                    for y in range(g0 + 1, g0 + 4):
                        p.at(tu, tv, y, "minecraft:oak_log[axis=y]")
                    crown = fr.ellipse(2.3, 2.3, tu, tv)
                    p.fill(crown, g0 + 4, g0 + 5, HEDGE)
                    p.layer(fr.ellipse(1.3, 1.3, tu, tv), g0 + 6, HEDGE)
        if self.planters:
            for su in (-1, 1):
                for sv in (-1, 1):
                    du, dv = su * (a + 3.2), sv * (b + 3.0)
                    ring = fr.ellipse(2.4, 2.4, du, dv) & ~fr.ellipse(1.5, 1.5, du, dv)
                    core = fr.ellipse(1.5, 1.5, du, dv)
                    p.layer(ring, g0 + 1, "minecraft:stone_bricks")
                    p.layer(ring, g0 + 2, TP.slab("smooth_stone"))
                    p.layer(core, g0 + 1, "minecraft:dirt")
                    p.layer(core, g0 + 2, GRASS)
                    p.layer(fr.ellipse(0.9, 0.9, du, dv), g0 + 3, HEDGE2)
        if self.fence:
            # 安全島外緣一圈低矮的鐵欄杆（OSM 在東門四周畫了 barrier=fence），門洞的延長線上留缺口
            edge = kit.ring(self.ground) & ~(np.abs(fr.U) <= self.passage[0] / 2 + 0.6)
            cells = [(int(fr.X[i, j]), g0 + 1, int(fr.Z[i, j])) for i, j in np.argwhere(edge)]
            for (x, y, z), blk in TP.panes_conn(cells, "iron_bars").items():
                p.set(x, y, z, blk)

    def _build_upper(self, p):
        fr = self.fr
        a, b, hb = self.a, self.b, self.hb
        s = p.w.set
        # 城座頂：最上一層白色（雉堞的基座），外緣挑出一圈白色壓簷
        top_ring = kit.ring(self.base)
        p.layer(top_ring, hb, WHITE_TRIM)
        p.layer(kit.erode(self.base, 1), hb, PAVE)
        lip = kit.dilate(self.base, 1) & ~self.base
        p.layer(lip, hb, TP.slab("smooth_quartz", "top"))
        # 雉堞：城座頂最上一層白（上面那行）是女兒牆的牆身，再上一格是墩：
        # 每 3 格兩格墩、一格垛口（垛口是半磚），照片量得牆頂離城座頂約 1 m
        for i, j in np.argwhere(top_ring):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            back = self.back_railing and fr.V[i, j] > b - 1.2
            if back:
                s(x, hb + 1, z, BRICK)
                if (x + z) % 2 == 0:
                    s(x, hb + 2, z, "minecraft:brick_wall[east=none,north=none,south=none,up=true,waterlogged=false,west=none]")
                continue
            c = TP.edge_coord(fr, i, j, a, b)
            k = math.floor(c) % 3
            s(x, hb + 1, z, WHITE if k == 0 else WHITE_TRIM if k == 1 else TP.slab("smooth_quartz"))
        # 門額：外側雉堞正中
        self._parapet_plaque(p)
        # 城樓
        self._pavilion(p)

    def _parapet_plaque(self, p):
        v = -self.b + 0.3
        y = self.hb + 1
        for du in (-1.5, -0.5, 0.5, 1.5):
            p.at(du, v, y, "minecraft:stripped_dark_oak_wood")
            p.at(du, v, y + 1, "minecraft:stripped_dark_oak_wood")
        # 匾：深色木框、淺色匾心、深金色的字（照片上三座城門的門額都是這樣）
        TP.plaque_sign(p, 0.0, v, y + 1, (0, -1),
                       ["", dict(text=self.plaque_text, color="#5A3A10", bold=True), "", ""],
                       wood="pale_oak", glow=False)

    def _pavilion(self, p):
        fr = self.fr
        hb = self.hb
        pa, pb = self.pav
        y0 = hb + 1
        yc = hb + self.col_h                            # 柱頂
        yb = yc + 1                                     # 額枋
        y_eave = yb + 1                                 # 簷口那一圈瓦
        us = self._grid(self.bays[0], pa)
        vs = self._grid(self.bays[1], pb)
        # 室內地坪
        p.layer(fr.box(pa + 0.4, pb + 0.4), hb, "minecraft:polished_granite")
        # 牆：柱網內縮一格半的一圈（前後正中開門）；小南門只圍中間三間
        if self.open_hall:
            wa, wb = (us[3] - us[2]) / 2 + 0.6, pb - 1.4
        else:
            wa, wb = pa - 1.3, pb - 1.3
        room = fr.box(wa, wb)
        wall = kit.ring(room)
        door = (np.abs(fr.U) <= 1.0)
        p.fill(wall & ~door, y0, yc, TAN_WALL)
        # 門：前後各一樘雙扇朱紅門（照片上明間的紅色格扇門）
        for sv in (-1, 1):
            cells = wall & door & (np.sign(fr.V) == sv)
            fac = fr.facing(0, sv)
            for k, (x, z) in enumerate(sorted(fr.cells(cells))):
                hinge = "left" if k % 2 == 0 else "right"
                p.set(x, y0, z, "minecraft:mangrove_door[facing=%s,half=lower,hinge=%s,open=false,powered=false]" % (fac, hinge))
                p.set(x, y0 + 1, z, "minecraft:mangrove_door[facing=%s,half=upper,hinge=%s,open=false,powered=false]" % (fac, hinge))
                for y in range(y0 + 2, yc + 1):
                    p.set(x, y, z, "minecraft:red_terracotta")
        # 柱：外圈一周（1 × 1，朱紅）
        for i, u in enumerate(us):
            for j, v in enumerate(vs):
                if i in (0, len(us) - 1) or j in (0, len(vs) - 1):
                    for y in range(y0, yc + 1):
                        p.at(u, v, y, RED_COL)
        # 額枋：柱頂那一圈，青綠底、每間正中一段淺色枋心
        band = kit.ring(fr.box(pa + 0.5, pb + 0.5))
        for i, j in np.argwhere(band):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            c = TP.edge_coord(fr, i, j, pa + 0.5, pb + 0.5)
            grid = us if abs(fr.V[i, j]) >= pb - 0.2 else vs
            mid = any(abs(c - (q0 + q1) / 2) <= 0.8 for q0, q1 in zip(grid[:-1], grid[1:]))
            p.set(x, yb, z, BEAM_PANEL if mid else BEAM)
        p.layer(kit.erode(fr.box(pa + 0.5, pb + 0.5), 1), yb, "minecraft:spruce_planks")
        # 斗拱：額枋外一圈，深青綠與青綠相間（一攢一攢）
        br = fr.box(pa + 1.4, pb + 1.4) & ~fr.box(pa + 0.5, pb + 0.5)
        for i, j in np.argwhere(br):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            p.set(x, yb, z, SOFFIT if (x + z) % 2 else BEAM)
        # 屋頂：單簷歇山、綠琉璃瓦、黃脊
        ra, rb = pa + self.overhang, pb + self.overhang
        gin = self.gable_in
        mask = fr.box(ra, rb)
        h = kit.hip_gable(fr, ra, rb, self.rise, gin, profile=1.7, lift=self.lift)
        tops = TP.tile_roof(p, mask, y_eave, h, TP.GREEN_TILES, shell=2, under=SOFFIT,
                            under_mask=mask & ~fr.box(pa + 0.5, pb + 0.5))
        self.tops = tops
        # 山花：紅底、黃色博風板、正中一塊白色花飾
        self._palace_gables(p, tops, ra, rb, gin)
        # 正脊與鴟吻
        L = ra - gin
        band = (np.abs(fr.V) < 0.5) & (np.abs(fr.U) <= L + 0.3) & (tops > -999)
        ry = int(tops[band].max()) + 1
        for i, j in np.argwhere(band):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            for y in range(int(tops[i, j]) + 1, ry + 1):
                p.set(x, y, z, GOLD)
        for su in (-1, 1):
            TP.chiwen(p, su * L, 0.0, ry, GOLD, inward=-su, h=2,
                      accent="minecraft:orange_terracotta")
        # 垂脊、戧脊（黃），翼角翹起一格
        self._hip_ridges(p, tops, ra, rb, gin, GOLD, curl=1)

    def _palace_gables(self, p, tops, a, b, gin):
        fr = self.fr
        for su in (-1, 1):
            cells = (su * fr.U > a - gin) & (su * fr.U <= a - gin + 1.0) & (np.abs(fr.V) < b - gin + 0.3)

            def ytop(i, j, su=su):
                t = TP.top_at(tops, fr, su * (a - gin - 0.6), float(fr.V[i, j]))
                return (t if t is not None else tops[i, j])
            TP.gable_face(p, cells, tops, ytop, RED_WALL, border=GOLD)
            # 白色花飾：山花正中
            top = TP.top_at(tops, fr, su * (a - gin - 0.6), 0.0)
            bot = TP.top_at(tops, fr, su * (a - gin + 0.5), 0.0)
            if top is not None and bot is not None and top - bot >= 3:
                mid = (top + bot) // 2
                for dv, ys in ((0.0, (mid - 1, mid, mid + 1)), (-1.0, (mid,)), (1.0, (mid,))):
                    for y in ys:
                        p.at(su * (a - gin + 0.5), dv, y, WHITE_TRIM)


class Dongmen(PalaceGate):
    """東門（景福門）：城座照 OSM（約 17.7 × 13.4 m），門洞東西向，門額在東面（城外）。
    照片量得城座高約 4.7 m、屋脊約 14 m；城樓面寬五間、進深三間。"""

    osm = "way/209580573"
    outer = (1, 0)
    stone = STONE_LIGHT                 # 照片上東門的城座偏淺灰
    base_h = 5
    pav = (7.0, 4.4)
    col_h = 3
    rise = 2.9
    height_m = 15.0
    passage = (4.2, 1.9)
    fence = True
    plaque_text = "景福門"
    fact_lines = ("1966 年改建宮殿式", "城座門洞是清代原物")


class Nanmen(PalaceGate):
    """南門（麗正門）：臺北府城的正門、規模最大。城座 18.5 × 13.5 m（見模組說明），
    門洞南北向，門額在南面。屋脊約 14.5 m。"""

    osm = "way/245993047"
    outer = (0, 1)
    base_half = (9.25, 6.75)
    stone = STONE_DARK
    base_h = 5
    pav = (7.2, 4.6)
    col_h = 3
    rise = 3.1
    height_m = 15.5
    passage = (4.4, 1.9)
    planters = True
    garden = True
    plaque_text = "麗正門"
    fact_lines = ("1966 年改建宮殿式", "臺北府城的正門")

    def _ground_mask(self):
        # 南門的 OSM 外框（連同花台、草坪的安全島）整片整地
        return self.fr.chamfer(max(self.ra, self.a + 7), max(self.rb, self.b + 7), 4)


class Xiaonanmen(PalaceGate):
    """小南門（重熙門）：面向西南的艋舺（城外在西南西），城座 13.4 × 12.4 m、高約 4.8 m，
    城樓是四周迴廊的敞廳，屋脊約 12.7 m；城內側欄杆是紅磚花格。"""

    osm = "way/246651384"
    outer = (math.cos(math.radians(114.7)), math.sin(math.radians(114.7)))
    stone = STONE_DARK
    base_h = 5
    pav = (5.5, 3.9)
    col_h = 3
    rise = 2.6
    overhang = 2.1
    gable_in = 2.0
    height_m = 13.5
    passage = (3.2, 2.1)
    open_hall = True
    back_railing = True
    planters = True
    view_dist = 20
    plaque_text = "重熙門"
    fact_lines = ("1966 年改建宮殿式", "清代原是廊柱式城樓")


BUILDS = {"beimen": Beimen, "dongmen": Dongmen, "nanmen": Nanmen, "xiaonanmen": Xiaonanmen}
