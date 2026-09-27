#!/usr/bin/env python3
"""新光摩天大樓（新光人壽保險摩天大樓）：244.15 m、地上 51 層，1993 年落成。

平面與量體照 OSM：主輪廓 way/204711206（62 個節點）之外，OSM 還把整棟樓拆成
三十幾個 building:part —— 16 層、78.56 m 的百貨裙樓（新光三越站前店）繞著塔樓一圈，
北面正中升到 18 層；塔身 50 層到 211.04 m，南北兩端 48 層，四個轉角一層一層退
（48 層 203.36 m、46 層 195.68 m、44 層 187.36 m）；頂上再疊兩段
（211.04→214.88 m、214.88→237.67 m）。這裡照每個 part 的 min_height / height 逐層
算遮罩，量體就是 OSM 的量體。

長相照公開資料：
  · 高度：天線 244.15 m、屋頂 238.15 m（中文維基「新光人壽保險摩天大樓」）
  · 外牆：耐候的鋁板，玫瑰色 —— 取材自台灣與日本的國花（Wikipedia「Shin Kong Life
    Tower」）；頂上是一座角錐（同上）
  · 百貨：地下 2 層到地上 13 層是新光三越（中文維基），裙樓外牆是深褐色的石材
  · 塔身：一層一條水平帶狀窗；轉角是鋸齒狀的退縮
立面的比例（帶狀窗、裙樓石材、頂部較粉的顏色）是看公開照片抓的，沒有抄任何圖。

一樓大廳從北面（台北車站那一側）的門廳進去；站前廣場的出入口與地下街在禁區裡，
寫到那些格子會被 Guard 擋掉。
"""
import math

import numpy as np

from mrt.application.attractions import highrise as HR
from mrt.application.attractions import kit
from mrt.application.attractions.kit import Attraction, Frame, Spot
from mrt.domain import geometry as shapes

MAIN = "way/204711206"
TOWER_BODY = "way/644774181"        # 塔身（50 層、211.04 m），拿來定塔樓的中心與方位

PODIUM_TOP = 78.56                  # 16 層裙樓的頂
TIP = 244                           # 天線頂（244.15 m）
ROOF = 237                          # 頂上那一段（到 237.67 m）的最後一列：角錐從這裡起，238 m 上下是屋頂
OBS_FLOOR = 46                      # 46 樓觀景台（1994～2006 年開放，中文維基）：整圈玻璃
CROWN_FROM = 183.0                  # 44 層以上（第一道轉角退縮）顏色轉成較深的粉紅

# 材質
PODIUM_A = "minecraft:polished_granite"       # 裙樓：深褐帶粉的石材
PODIUM_B = "minecraft:granite"
PODIUM_WIN = "minecraft:gray_stained_glass"
SHOP = "minecraft:light_gray_stained_glass"   # 一樓的店面櫥窗
SHAFT = "minecraft:white_terracotta"          # 塔身：淡玫瑰色的鋁板
BAND = "minecraft:cherry_planks"              # 帶狀窗上緣的粉紅線
WIN = "minecraft:cyan_stained_glass"          # 灰藍色的帶狀窗
CROWN = "minecraft:cherry_planks"             # 頂部：較粉的玫瑰色
CROWN_LINE = "minecraft:pink_terracotta"
LEDGE = "minecraft:smooth_quartz_slab[type=bottom,waterlogged=false]"   # 每道退縮的細挑簷
ROOF_FLAT = "minecraft:smooth_stone"
PYRAMID = "minecraft:brown_terracotta"        # 深色的角錐頂
FINIAL = "minecraft:gold_block"
SLAB = "minecraft:smooth_stone"
FLOOR1 = "minecraft:polished_diorite"
LAMP = "minecraft:sea_lantern"
CORE = "minecraft:polished_andesite"
CANOPY = "minecraft:smooth_quartz"
POST = "minecraft:polished_granite"
PLAZA = "minecraft:polished_andesite"


def _num(t, k):
    try:
        return float(str(t[k]).split()[0])
    except (KeyError, ValueError):
        return None


def _inside(poly, x, z):
    """點在多邊形內（射線法）。"""
    n, c = len(poly), False
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        if (z1 > z) != (z2 > z) and x < (x2 - x1) * (z - z1) / (z2 - z1) + x1:
            c = not c
    return c


def floor_rows():
    """樓板列（離一樓樓板幾格）：1～16 樓是百貨，每層 78.56/16 = 4.91 m；
    17 樓起每層 (211.04 − 78.56)/34 = 3.9 m，51 樓的頂 = 211.04 m（OSM）。"""
    rows = [int(math.floor(PODIUM_TOP / 16 * k)) for k in range(16)]
    rows += [int(math.floor(PODIUM_TOP + 3.896 * (k - 16))) for k in range(16, 51)]
    return rows


FLOOR_ROWS = floor_rows()
FLOOR_OF = {r: k + 1 for k, r in enumerate(FLOOR_ROWS)}


def floor_of_row(yy):
    k = 0
    for i, r in enumerate(FLOOR_ROWS):
        if r <= yy:
            k = i
        else:
            break
    return k + 1, yy - FLOOR_ROWS[k]


class ShinKongTower(Attraction):
    height_m = 244.15
    margin = 12

    # ---------------------------------------------------------------- 資料
    def _ring(self, osm):
        f = self.feature(osm)
        return max(f["outer"], key=len) if f and f.get("outer") else None

    def parts(self):
        """主輪廓裡的 building:part：[(osm, 外環, 底 m, 頂 m, 是雨庇)]。
        沒有 height 的（門口的兩三層小量體）用層數 × 4.5 m；兩層以下的當雨庇蓋。"""
        main = self._ring(MAIN)
        out = []
        for f in self.features:
            t = f["tags"]
            if "building:part" not in t or not f.get("outer"):
                continue
            r = max(f["outer"], key=len)
            cx, cz = shapes.centroid(r)
            if not _inside(main, cx, cz):
                continue
            hi = _num(t, "height")
            lv = _num(t, "building:levels") or 1
            canopy = hi is None and lv <= 2
            if hi is None:
                hi = lv * 4.5
            lo = _num(t, "min_height") or 0.0
            out.append((f["osm"], r, lo, hi, canopy))
        return out

    # ---------------------------------------------------------------- 定案
    def plan(self, site):
        self.site = site
        main = self._ring(MAIN)
        mcx, mcz, _, hu, hv = HR.outline_axes(main)
        tcx, tcz, ang_osm, _, _ = HR.outline_axes(self._ring(TOWER_BODY))
        # 塔身偏 −0.6°：整棟連同每個 part 繞塔身中心轉正（highrise.snap_angle），
        # 主輪廓兩端最多挪 0.45 m；帶狀窗與窗櫺才會是水平、垂直的直線
        ang = HR.snap_angle(ang_osm)
        turn = ang - ang_osm

        def fix(r):
            return HR.rotate_poly(r, tcx, tcz, turn) if turn else r

        self._fix = fix
        main = fix(main)
        self.ang = ang
        self.fr = Frame(mcx, mcz, ang, max(hu, hv) + 10)
        fr = self.fr
        self.foot = fr.polygon(main)
        self.p = []
        self.canopies = []
        for osm, r, lo, hi, canopy in self.parts():
            m = fr.polygon(fix(r))
            if not m.any():
                continue
            (self.canopies if canopy else self.p).append((m, lo, hi))
        self.g0 = site.level(fr, self.foot)
        # 整地要用的地面高度現在就查好（Site 會快取）：cli 在 plan 之後就把
        # 「蓋出來的地面」的距離場丟掉了，build() 的時候再查會失敗
        self.near = kit.dilate(self.foot, 10) & ~self.foot
        site.grid(fr, self.foot | self.near)
        c, s = math.cos(ang), math.sin(ang)
        self.tuv = ((tcx - mcx) * c + (tcz - mcz) * s, -(tcx - mcx) * s + (tcz - mcz) * c)
        tu, tv = self.tuv
        self.T, self.S = HR.face_coords(fr, tu, tv)
        uu, vv = fr.U - tu, fr.V - tv
        self.core = (np.abs(uu) <= 7) & (np.abs(vv) <= 10)
        self.lamps = HR.grid_mask(fr, 6, 3, tu, tv)
        # 大廳：北門廳到電梯核前面，挑高兩層
        self.lobby = (np.abs(uu) <= 8) & (vv < -10)
        # 頂上那一段（214.88 -> 237.67 m）：角錐的底
        top = [m for m, lo, hi in self.p if hi > 230]
        self.top_mask = top[0] if top else fr.empty()

        # 觀景點：站前廣場（北面、靠台北車站那一側）的西北角，整座樓框得進畫面
        x0 = min(p[0] for p in main)
        z0 = min(p[1] for p in main)
        vx, vz = int(math.floor(x0)) - 36, int(math.floor(z0)) - 36
        vy = site.g(vx, vz) + 1
        d = math.hypot(tcx - (vx + .5), tcz - (vz + .5))
        up = math.degrees(math.atan2(self.g0 + TIP - (vy + 1.62), d))
        down = math.degrees(math.atan2(vy + 1.62 - self.g0, d))
        yaw, _ = kit.look(vx, vy, vz, tcx, self.g0 + 100, tcz)
        lx, lz = fr.cell(tu, tv - 14.0)
        self.logo_row = 40                                       # 北面裙樓 8、9 樓之間的金色標誌
        self._spots = [
            Spot("", vx, vy, vz, yaw, round(-(up - down) / 2.0, 1), self.name_zh, self.name_en),
            Spot("lobby", lx, self.g0 + 1, lz, round(fr.yaw(0, -1), 1), 0.0,
                 "新光摩天大樓 大廳", "Shin Kong Life Tower Lobby"),
        ]

    def part_ring(self, osm):
        """某個 OSM 元素轉正之後的外環（plan 之後才有；測試拿來比對蓋出來的量體）。"""
        return self._fix(self._ring(osm))

    def plaque(self):
        return [self.name_zh, self.name_en, "244 m，1993年落成", "地上51層·地下7層"]

    # ---------------------------------------------------------------- 蓋
    def mass(self, yy):
        """第 yy 列的量體：所有涵蓋這個高度的 part 取聯集；owner 是這一格最高那個 part 的頂（m）。"""
        t = yy + 0.5
        m = self.fr.empty()
        owner = np.zeros(self.fr.shape)
        for pm, lo, hi in self.p:
            if lo <= t < hi:
                m |= pm
                owner = np.where(pm, np.maximum(owner, hi), owner)
        return m, owner

    def build(self, w):
        fr, g0 = self.fr, self.g0
        self.site.prepare(w, fr, self.foot, g0, top=FLOOR1)
        self._plaza(w)
        cache = {}

        def M(yy):
            if yy not in cache:
                cache[yy] = self.mass(yy) if yy >= 0 else (fr.empty(), np.zeros(fr.shape))
            return cache[yy]

        T = self.T
        col3 = (np.floor(T).astype(int) % 3) == 0
        col4 = (np.floor(T).astype(int) % 4) == 0
        col6 = (np.floor(T).astype(int) % 6) == 0
        panel = ((np.floor(T).astype(int) // 2) % 2) == 0
        for yy in range(0, ROOF):
            m, owner = M(yy)
            if not m.any():
                continue
            mp, _ = M(yy - 1)
            mn, _ = M(yy + 1)
            sh = HR.shell(m, mp, mn)
            y = g0 + yy
            k, kr = floor_of_row(yy)
            podium = sh & (owner <= 90)
            tower = sh & (owner > 90)
            layers = []
            # 裙樓（百貨）：深褐石材，一層一排小窗；一樓是店面櫥窗
            if yy <= 4:
                layers += [(podium, SHOP), (podium & col4, PODIUM_A)]
            elif kr == 0:
                layers.append((podium, PODIUM_A))
            elif kr == 2:
                layers += [(podium, PODIUM_B), (podium & col3, PODIUM_WIN)]
            else:
                layers += [(podium & panel, PODIUM_A), (podium & ~panel, PODIUM_B)]
            # 塔身：淡玫瑰色鋁板 + 一層一條帶狀窗；44 層以上顏色轉成較深的粉紅
            crown = yy + 0.5 >= CROWN_FROM
            if yy < PODIUM_TOP:
                # 裙樓高度以內露出來的塔身（西面 4 層小量體上方）
                layers.append((tower, SHAFT if kr in (0, 3) else WIN))
            elif k == OBS_FLOOR and kr > 0:
                layers.append((tower, WIN))
            elif not crown:
                # 一層一條連續的帶狀窗，每 6 m 一根窄窗櫺
                if kr == 0:
                    layers.append((tower, SHAFT))
                elif kr in (1, 2):
                    layers += [(tower, WIN), (tower & col6, SHAFT)]
                else:
                    layers.append((tower, BAND))
            else:
                if kr in (0, 3):
                    layers.append((tower, CROWN))
                elif kr == 1:
                    layers.append((tower, CROWN_LINE))
                else:
                    layers += [(tower, CROWN), (tower & col3, WIN)]
            HR.paint_layers(w, fr, layers, y)
            # 屋頂與退縮的平台
            cap = m & ~mn & ~sh
            HR.paint(w, fr, cap, y, ROOF_FLAT)
            HR.paint(w, fr, sh & ~mn, y, SHAFT if yy >= PODIUM_TOP else PODIUM_A)
            # 每道退縮的上緣外面一圈細挑簷（44、46、48、50 層的鋸齒轉角看得出來）
            if yy >= 150 and (m & ~mn).any():
                eave = kit.dilate(m & ~mn, 1) & ~m
                HR.paint(w, fr, eave, y + 1, LEDGE)
            # 樓板、燈、電梯核
            inner = m & ~sh & ~cap
            if yy in FLOOR_OF and yy > 0:
                sl = inner
                if FLOOR_OF[yy] == 2:
                    sl = sl & ~self.lobby
                HR.paint(w, fr, sl, y, SLAB)
                HR.paint(w, fr, sl & self.lamps, y, LAMP)
            elif yy > 0:
                HR.paint(w, fr, kit.ring(self.core) & inner, y, CORE)
        self._crown(w)
        self._logo(w)
        self._lobby(w)
        self._canopies(w)

    # ---- 頂：角錐（238 -> 243 m）與金色的尖頂（244 m）----
    def _crown(self, w):
        fr, g0 = self.fr, self.g0
        tm = self.top_mask
        if not tm.any():
            return
        tu, tv = self.tuv
        cu = float(fr.U[tm].mean())
        cv = float(fr.V[tm].mean())
        half = max(float(np.abs(fr.U[tm] - cu).max()), float(np.abs(fr.V[tm] - cv).max()))
        cheb = np.maximum(np.abs(fr.U - cu), np.abs(fr.V - cv))
        rise = TIP - 1 - ROOF                      # 角錐 237 -> 242 m，243 m 是金色的頂
        for i in range(rise):
            r = half + 0.5 - (half / (rise - 0.5)) * i
            HR.paint(w, fr, (cheb <= r) & kit.dilate(tm, 1), g0 + ROOF + i, PYRAMID)
        x, z = fr.cell(cu, cv)
        w.set(x, g0 + TIP - 1, z, FINIAL)
        w.set(x, g0 + TIP, z, "minecraft:lightning_rod[facing=up,powered=false]")

    # ---- 北面裙樓的金色標誌（橢圓形的「光」字章）----
    def _logo(self, w):
        fr, g0 = self.fr, self.g0
        tu, _ = self.tuv
        m, _ = self.mass(self.logo_row)
        cells = set(zip(fr.X[m].tolist(), fr.Z[m].tolist()))
        face = None
        for k in range(200, 0, -1):
            d = -k * 0.5
            if fr.cell(tu, d) in cells:
                face = d
                break
        if face is None:
            return
        for du in np.arange(-4.0, 4.5, 1.0):
            for dy in (-1, 0, 1):
                e = (du / 4.2) ** 2 + (dy / 1.6) ** 2
                if e <= 1.0:
                    x, z = fr.cell(tu + du, face - 1.0)
                    w.set(x, g0 + self.logo_row + dy, z, FINIAL if e > 0.35 or dy else "minecraft:white_concrete")

    # ---- 一樓大廳：北面門廳開門，挑高兩層、有燈 ----
    def _lobby(self, w):
        fr, g0 = self.fr, self.g0
        m1, _ = self.mass(1)
        tu, tv = self.tuv
        cells = set(zip(fr.X[m1].tolist(), fr.Z[m1].tolist()))
        hit = None
        for k in range(160, 0, -1):
            d = -k * 0.5
            x, z = fr.cell(tu, d)
            if (x, z) in cells:
                hit = d
                break
        if hit is not None:
            face = kit.cardinal(*fr.dir(0, 1))
            for s, hinge in ((-0.5, "left"), (0.5, "right")):
                x, z = fr.cell(tu + s, hit)
                HR.door(w, x, g0 + 1, z, face, hinge=hinge, block="minecraft:dark_oak_door")
                for dd in (-1.0, 1.0):
                    xx, zz = fr.cell(tu + s, hit + dd)
                    w.set(xx, g0 + 1, zz, kit.AIR)
                    w.set(xx, g0 + 2, zz, kit.AIR)
        # 大廳的燈：二樓樓板挖掉之後，天花在三樓樓板；地坪嵌一圈燈
        HR.paint(w, fr, self.lobby & m1 & self.lamps, g0, LAMP)
        HR.paint(w, fr, self.lobby & m1 & self.lamps, g0 + FLOOR_ROWS[2], LAMP)

    # ---- 門口雨庇：頂板與柱子，底下走得過去 ----
    def _canopies(self, w):
        fr, g0 = self.fr, self.g0
        tu, _ = self.tuv
        # 柱子每 5 m 一根，大門前面那條走道（正中 5 m 寬）不立柱
        post = HR.grid_mask(fr, 5, 0) & ~(np.abs(fr.U - tu) <= 2.5)
        for m, lo, hi in self.canopies:
            m = m & ~self.mass(1)[0]
            if not m.any():
                continue
            HR.paint(w, fr, m, g0 + 5, CANOPY)
            for yy in range(1, 5):
                HR.paint(w, fr, kit.ring(m) & post, g0 + yy, POST)

    # ---- 站前廣場：樓前面（北側）鋪石板到觀景點那一帶 ----
    def _plaza(self, w):
        self.site.prepare(w, self.fr, self.near, self.g0, top=PLAZA, clear=0)


BUILDS = {"shin_kong_tower": ShinKongTower}
