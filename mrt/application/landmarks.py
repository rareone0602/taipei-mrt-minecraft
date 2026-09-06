#!/usr/bin/env python3
"""地標建築：從 OSM 平面圖擠出一棟真的房子，而不是沿線掃出來的制式站屋。

路線上的東西（隧道、高架、月台）都是沿著中心線掃斷面產生的，但地面上的
站體大樓不是 —— 它是一個任意多邊形，要自己光柵化、砌牆、蓋屋頂。

BlockSink 的實作（infrastructure 的 World）會自動丟掉不屬於目前 region
的方塊，所以這裡只要對每個 bbox 涵蓋到的 region 各呼叫一次 build()，
裁切交給它處理。

自我測試: ./.venv/bin/python -m tests.test_landmarks
"""
import os, re, sys, math, json

from mrt import config
from mrt.domain import geometry as shapes

AIR = "minecraft:air"


class Building:
    """依平面多邊形擠出的多層建築，可選四坡屋頂。

    poly      : [(mc_x, mc_z), ...] 平面圖
    g0        : 地面 y（1 樓樓板）
    storeys   : 地上樓層數
    storey_h  : 層高（公尺）
    """

    def __init__(self, poly, g0, storeys=1, storey_h=5,
                 wall="minecraft:smooth_sandstone",
                 floor="minecraft:polished_andesite",
                 roof="minecraft:deepslate_tiles",
                 ridge=None, glass="minecraft:glass_pane",
                 lamp="minecraft:sea_lantern",
                 roof_slope=0.55, roof_max=None, eaves=1,
                 hollow=True, name=None, doors=(), open_core=0, found=3,
                 core_inset=8, wall_inset=0, columns=(), col_half=1,
                 body_poly=None, core_poly=None,
                 checker=None, trim=None):
        self.poly = [(float(x), float(z)) for x, z in poly]
        self.g0, self.storeys, self.storey_h = int(g0), int(storeys), int(storey_h)
        self.wall, self.floor, self.roof = wall, floor, roof
        self.ridge = ridge or roof
        self.glass, self.lamp = glass, lamp
        self.roof_slope, self.roof_max, self.eaves = roof_slope, roof_max, int(eaves)
        self.hollow, self.name = hollow, name
        self.doors = [(int(x), int(z)) for x, z in doors]
        self.open_core = int(open_core)      # 前幾層不鋪樓板 = 挑高大廳
        self.found = int(found)              # 基礎往下墊幾格
        self.core_inset = int(core_inset)    # 挑空從外牆內縮幾格開始
        self.body_poly = body_poly           # 主體結構範圍（與屋簷輪廓取交集）
        self.core_poly = core_poly           # 挑高大廳範圍
        self.wall_inset = int(wall_inset)    # 外牆比屋簷內縮幾格（出簷）
        self.columns = [(int(x), int(z)) for x, z in columns]
        self.col_half = int(col_half)
        self.checker = checker               # (色A, 色B) -> 1 樓棋盤地坪
        self.trim = trim or roof
        self._cells = None

    # ---- 幾何 ----
    @property
    def cells(self):
        if self._cells is None:
            self._cells = shapes.poly_cells(self.poly)
        return self._cells

    def bbox(self):
        x0, z0, x1, z1 = shapes.bbox(self.poly)
        m = self.eaves + 2
        return (int(x0) - m, int(z0) - m, int(x1) + m, int(z1) + m)

    def top_y(self):
        return self.g0 + self.storeys * self.storey_h

    # ---- 寫入 ----
    def build(self, w):
        cells = self.cells
        if not cells:
            return
        # 屋簷比主體外擴：OSM 的平面圖量到的是屋簷與雨庇外緣（158x127 m），
        # 主體結構只有 149x110 m，差的就是每側約 4 m 的出挑。
        if self.body_poly is not None:
            body = cells & shapes.poly_cells(self.body_poly)
        elif self.wall_inset:
            body = shapes.inset(cells, self.wall_inset)
        else:
            body = cells
        if not body:
            body = cells
        ring = shapes.ring_cells(body)
        inner = body - ring
        core = (body & shapes.poly_cells(self.core_poly)) if self.core_poly is not None \
            else shapes.inset(body, self.core_inset)
        g0, sh, n = self.g0, self.storey_h, self.storeys

        for x, z in body:
            for y in range(g0 - self.found, g0):
                w.set(x, y, z, self.floor)

        for k in range(n):
            fy = g0 + k * sh
            if k == 0 or k >= self.open_core:
                for x, z in body:
                    w.set(x, fy, z, self.floor)
            else:
                for x, z in body:          # 中央挑空，只留靠外牆的迴廊
                    w.set(x, fy, z, AIR if (x, z) in core else self.floor)
            for x, z in ring:
                for dy in range(1, sh):
                    y = fy + dy
                    win = 2 <= dy <= sh - 2 and ((x + z) % 4) != 0
                    w.set(x, y, z, self.glass if win else self.wall)
            if self.hollow:
                for x, z in inner:
                    for dy in range(1, sh):
                        w.set(x, fy + dy, z, AIR)
                for x, z in inner:
                    if x % 8 == 0 and z % 8 == 0 and (x, z) not in core:
                        w.set(x, fy + sh - 1, z, self.lamp)

        # 1 樓黑白斜棋盤地坪。實際是 2011 年鋪的，與建築軸線呈 45 度、
        # 單格約 3 m —— (x+z)//4 與 (x-z)//4 正好給出轉 45 度、對角約 2.8 m 的格子。
        if self.checker:
            ca, cb = self.checker
            for x, z in body:
                w.set(x, g0, z, ca if (((x + z) // 4 + (x - z) // 4) % 2) else cb)

        # 大廳獨立柱：2 排 x 4 根，斷面約 1.35 m
        top = g0 + min(self.open_core, n) * sh
        for cxx, czz in self.columns:
            for dx in range(-self.col_half, self.col_half + 1):
                for dz in range(-self.col_half, self.col_half + 1):
                    if (cxx + dx, czz + dz) not in body:
                        continue
                    for y in range(g0 + 1, top):
                        w.set(cxx + dx, y, czz + dz, self.floor)

        ty = self.top_y()
        for x, z in body:
            w.set(x, ty, z, self.floor)
        for x, z in cells - body:          # 出簷
            w.set(x, ty, z, self.trim)
        if self.eaves:
            eave = set()
            for x, z in shapes.ring_cells(cells):
                for dx in range(-self.eaves, self.eaves + 1):
                    for dz in range(-self.eaves, self.eaves + 1):
                        if (x + dx, z + dz) not in cells:
                            eave.add((x + dx, z + dz))
            for x, z in eave:
                w.set(x, ty, z, self.trim)

        for dx, dz in self.doors:
            for x in range(dx - 2, dx + 3):
                for z in range(dz - 2, dz + 3):
                    if (x, z) in ring:
                        for y in range(g0 + 1, g0 + 5):
                            w.set(x, y, z, AIR)

        # 盝頂：四坡水收到一個平頂平台，不是收尖的角錐。
        # hip_roof 的 max_rise 一夾住就自然形成平台。
        rf = shapes.hip_roof(cells, ty + 1, self.roof_slope, self.roof_max)
        peak = max(v[1] for v in rf.values())
        for (x, z), (y0, y1) in rf.items():
            for y in range(y0, y1 + 1):
                w.set(x, y, z, self.trim if (y == y0 and y1 > y0) else self.roof)
        for (x, z), (y0, y1) in rf.items():
            if y1 == peak:
                w.set(x, peak, z, self.roof)
        if self.hollow:
            for (x, z), (y0, y1) in rf.items():
                if (x, z) in inner:
                    for y in range(ty + 1, y1):
                        w.set(x, y, z, AIR)


class Slab:
    """一片水平樓板／地下大廳。用來把幾條線的穿堂層連在一起。"""

    def __init__(self, poly, y, thick=1, mat="minecraft:polished_andesite",
                 clear=0, wall=None, lamp="minecraft:sea_lantern", lamp_every=8):
        self.poly = [(float(x), float(z)) for x, z in poly]
        self.y, self.thick, self.mat = int(y), int(thick), mat
        self.clear, self.wall = int(clear), wall
        self.lamp, self.lamp_every = lamp, int(lamp_every)
        self._cells = None

    @property
    def cells(self):
        if self._cells is None:
            self._cells = shapes.poly_cells(self.poly)
        return self._cells

    def bbox(self):
        x0, z0, x1, z1 = shapes.bbox(self.poly)
        return (int(x0) - 2, int(z0) - 2, int(x1) + 2, int(z1) + 2)

    def build(self, w):
        cells = self.cells
        ring = shapes.ring_cells(cells)
        for x, z in cells:
            for y in range(self.y - self.thick + 1, self.y + 1):
                w.set(x, y, z, self.mat)
        if self.clear:
            for x, z in cells:
                for y in range(self.y + 1, self.y + 1 + self.clear):
                    w.set(x, y, z, AIR)
            if self.wall:
                for x, z in ring:
                    for y in range(self.y + 1, self.y + 1 + self.clear):
                        w.set(x, y, z, self.wall)
            for x, z in cells:
                if x % self.lamp_every == 0 and z % self.lamp_every == 0 \
                        and (x, z) not in ring:
                    w.set(x, self.y + self.clear, z, self.lamp)
            # 頂板
            for x, z in cells:
                w.set(x, self.y + self.clear + 1, z, self.mat)


class ShaftStair:
    """折返式樓梯井：從地面下到任意深度的穿堂層。

    沿線的出入口長梯要 2 m 水平換 1 m 垂直，深 39 m 的站就得拉 78 m 直線 ——
    真實出入口離站體往往不到 40 m，硬拉會穿到別人家。折返梯把行程摺進一個
    固定大小的井裡，深度多少都塞得下，也比較接近真實深站的做法。

    座標系：(x0, z0) 是井的中心，u = (ux, uz) 是梯段延伸方向（單位向量，
    只支援四個正交方向），v 是其法向。
    """

    FLIGHT = 14          # 單一梯段的水平長度（公尺）-> 一段降 7 m
    HALF_W = 4           # 井的半寬（法向）

    def __init__(self, x0, z0, ux, uz, g0, y_to,
                 wall="minecraft:gray_concrete",
                 step="minecraft:smooth_stone",
                 slab="minecraft:smooth_stone_slab",
                 rail="minecraft:iron_bars",
                 lamp="minecraft:sea_lantern"):
        self.x0, self.z0 = int(x0), int(z0)
        self.ux, self.uz = int(round(ux)), int(round(uz))
        self.g0, self.y_to = int(g0), int(y_to)
        self.wall, self.step, self.slab = wall, step, slab
        self.rail, self.lamp = rail, lamp

    # 井內座標 (a 沿 u, b 沿 v) -> 世界座標
    def _w(self, a, b):
        vx, vz = -self.uz, self.ux
        return self.x0 + self.ux * a + vx * b, self.z0 + self.uz * a + vz * b

    def bbox(self):
        pts = [self._w(a, b) for a in (0, self.FLIGHT + 2)
               for b in (-self.HALF_W - 1, self.HALF_W + 1)]
        xs = [p[0] for p in pts]; zs = [p[1] for p in pts]
        return min(xs) - 2, min(zs) - 2, max(xs) + 2, max(zs) + 2

    def flights(self):
        """回傳 [(方向, y_起, y_終)]，方向 +1 沿 u、-1 逆 u。"""
        drop = self.g0 - self.y_to
        if drop <= 0:
            return []
        per = self.FLIGHT / 2.0                  # 一段降幾公尺
        out = []
        y = float(self.g0)
        d = 1
        while y - self.y_to > 1e-6:
            dy = min(per, y - self.y_to)
            out.append((d, y, y - dy))
            y -= dy
            d = -d
        return out

    def build(self, w):
        fl = self.flights()
        if not fl:
            return
        H = self.HALF_W
        lo = min(self.y_to - 1, self.g0)
        # 井壁 + 掏空
        for a in range(-1, self.FLIGHT + 3):
            for b in range(-H - 1, H + 2):
                x, z = self._w(a, b)
                edge = (a in (-1, self.FLIGHT + 2) or abs(b) == H + 1)
                for y in range(lo, self.g0 + 5):
                    w.set(x, y, z, self.wall if edge else AIR)
        # 梯段：+1 走 a 增加，-1 走 a 減少；兩段分別佔法向的兩半
        for k, (d, ya, yb) in enumerate(fl):
            b0, b1 = (1, H) if d > 0 else (-H, -1)
            n = int(round((ya - yb) * 2))
            for t in range(n + 1):
                a = (1 + t) if d > 0 else (self.FLIGHT + 1 - t)
                surf = ya - 0.5 * t
                half = abs(surf - math.floor(surf)) > 0.25
                yb_ = int(math.floor(surf)) if half else int(round(surf)) - 1
                blk = self.slab if half else self.step
                for b in range(b0, b1 + 1):
                    x, z = self._w(a, b)
                    w.set(x, yb_, z, blk)
                    for y in range(yb_ + 1, yb_ + 4):
                        w.set(x, y, z, AIR)
                # 中央扶手，免得從上面直接摔下去
                bm = 0
                x, z = self._w(a, bm)
                w.set(x, yb_, z, self.step)
                w.set(x, yb_ + 1, z, self.rail)
            # 平台
            xa, za = self._w(self.FLIGHT + 1 if d > 0 else 1, 0)
            for b in range(-H, H + 1):
                a = self.FLIGHT + 1 if d > 0 else 1
                x, z = self._w(a, b)
                w.set(x, int(round(yb)) - 1, z, self.step)
                for y in range(int(round(yb)), int(round(yb)) + 4):
                    w.set(x, y, z, AIR)
            if k % 2 == 0:
                x, z = self._w(self.FLIGHT // 2, 0)
                w.set(x, int(round(ya)) + 3, z, self.lamp)
        # 底部樓板
        for a in range(0, self.FLIGHT + 2):
            for b in range(-H, H + 1):
                x, z = self._w(a, b)
                w.set(x, self.y_to - 1, z, self.step)
        # 地面出入口亭：加頂蓋，並在近端牆上開門，否則是個沒有蓋子的陷阱
        for a in range(-1, self.FLIGHT + 3):
            for b in range(-H - 1, H + 2):
                x, z = self._w(a, b)
                w.set(x, self.g0 + 5, z, self.wall)
        for b in range(-1, 2):
            x, z = self._w(-1, b)
            for y in range(self.g0 + 1, self.g0 + 4):
                w.set(x, y, z, AIR)
        x, z = self._w(1, 0)
        w.set(x, self.g0 + 4, z, self.lamp)


class Passage:
    """兩點之間的水平通道：挖空、砌壁、鋪地、裝燈。"""

    def __init__(self, x0, z0, x1, z1, y, half_w=2, head=3,
                 floor="minecraft:polished_andesite",
                 wall="minecraft:gray_concrete",
                 lamp="minecraft:sea_lantern"):
        self.a = (int(x0), int(z0)); self.b = (int(x1), int(z1))
        self.y, self.half_w, self.head = int(y), int(half_w), int(head)
        self.floor, self.wall, self.lamp = floor, wall, lamp

    def bbox(self):
        m = self.half_w + 2
        return (min(self.a[0], self.b[0]) - m, min(self.a[1], self.b[1]) - m,
                max(self.a[0], self.b[0]) + m, max(self.a[1], self.b[1]) + m)

    def build(self, w):
        (x0, z0), (x1, z1) = self.a, self.b
        n = int(max(abs(x1 - x0), abs(z1 - z0)))
        if n == 0:
            return
        ux, uz = (x1 - x0) / n, (z1 - z0) / n
        px, pz = -uz, ux                       # 法向
        H = self.half_w
        for t in range(n + 1):
            cx, cz = x0 + ux * t, z0 + uz * t
            for b in range(-H - 1, H + 2):
                x, z = int(round(cx + px * b)), int(round(cz + pz * b))
                side = abs(b) == H + 1
                w.set(x, self.y - 1, z, self.floor)
                for dy in range(0, self.head + 1):
                    y = self.y + dy
                    if side or dy == self.head:
                        w.set(x, y, z, self.wall)
                    else:
                        w.set(x, y, z, AIR)
            if t % 10 == 0:
                x, z = int(round(cx)), int(round(cz))
                w.set(x, self.y + self.head - 1, z, self.lamp)


class RailHall:
    """多月台的地下車站大廳（台鐵／高鐵那種），依真實月台中心線鋪設。"""

    def __init__(self, plats, y, poly, half_w=5, clear=8,
                 plat="minecraft:polished_diorite",
                 edge="minecraft:yellow_concrete",
                 deck="minecraft:smooth_stone",
                 wall="minecraft:deepslate_bricks",
                 lamp="minecraft:sea_lantern"):
        self.plats = [[(float(x), float(z)) for x, z in g] for g in plats]
        self.y, self.poly = int(y), [(float(x), float(z)) for x, z in poly]
        self.half_w, self.clear = int(half_w), int(clear)
        self.plat, self.edge, self.deck = plat, edge, deck
        self.wall, self.lamp = wall, lamp
        self._cells = None

    @property
    def cells(self):
        if self._cells is None:
            self._cells = shapes.poly_cells(self.poly)
        return self._cells

    def bbox(self):
        x0, z0, x1, z1 = shapes.bbox(self.poly)
        return (int(x0) - 3, int(z0) - 3, int(x1) + 3, int(z1) + 3)

    def build(self, w):
        cells = self.cells
        if not cells:
            return
        ring = shapes.ring_cells(cells)
        y = self.y
        # 箱體：底板、掏空、頂板、周壁
        for x, z in cells:
            w.set(x, y - 1, z, self.wall)
            for dy in range(0, self.clear + 1):
                w.set(x, y + dy, z, self.wall if dy == self.clear else AIR)
            w.set(x, y, z, self.deck)          # 走行面
        for x, z in ring:
            for dy in range(0, self.clear):
                w.set(x, y + dy, z, self.wall)
        # 月台。OSM 的月台 way 多半是**封閉的外框**而不是中心線 ——
        # 沿線刷半徑會把 8.5 m 寬的月台刷成 18 m 寬，四座還會黏在一起。
        # 封閉的直接填多邊形，得到真實形狀；開放的才退回沿線刷。
        for g in self.plats:
            if len(g) > 3 and abs(g[0][0]-g[-1][0]) < 1e-6 and abs(g[0][1]-g[-1][1]) < 1e-6:
                band = shapes.poly_cells(g)
            else:
                band = set()
                for i in range(len(g) - 1):
                    ax, az = g[i]; bx, bz = g[i + 1]
                    n = int(max(abs(bx - ax), abs(bz - az))) or 1
                    for t in range(n + 1):
                        cx, cz = ax + (bx-ax)*t/n, az + (bz-az)*t/n
                        for dx in range(-self.half_w, self.half_w + 1):
                            for dz in range(-self.half_w, self.half_w + 1):
                                if dx*dx + dz*dz <= self.half_w**2:
                                    band.add((int(round(cx))+dx, int(round(cz))+dz))
            band &= cells
            rim = shapes.ring_cells(band)
            for x, z in band:
                w.set(x, y + 1, z, self.edge if (x, z) in rim else self.plat)
                for dy in range(2, self.clear):
                    w.set(x, y + dy, z, AIR)
            for x, z in band:
                if x % 12 == 0 and z % 12 == 0:
                    w.set(x, y + self.clear - 1, z, self.lamp)
# ---------- 世界層級的地標清單 ----------

def for_world(segs, stations, terr):
    """回傳這個世界要蓋的地標。build_world 會依 bbox() 分桶，
    再對每個涵蓋到的 region 呼叫 build(w)。

    segs     : build_world 規劃出來的路段（含 samples / ys / ground / stn）
    stations : (refs, 中文名, mc_x, mc_z, 英文名, ref字串) 串列
    terr     : Terrain，用來查地面高程
    """
    out = []
    out += taipei_main(segs, stations, terr)
    return out


def _load(name):
    f = os.path.join(config.DATA, name)
    if not os.path.exists(f):
        return []
    return json.load(open(f, encoding="utf-8"))["items"]


def _station_on_lines(segs, zh):
    """找出某座車站在各條線上的位置：{ref: (x, z, ux, uz, 軌面y)}"""
    out = {}
    for sg in segs:
        for bi, (full, nm, en) in sg["stn"].items():
            if nm == zh and sg["ref"] not in out:
                x, z, ux, uz, _ = sg["samples"][bi]
                out[sg["ref"]] = (x, z, ux, uz, int(sg["ys"][bi]))
    return out


def _axes(poly):
    """多邊形的主軸與次軸（單位向量）。用來把柱網擺在建築自己的方格上。"""
    import numpy as np
    g = np.array(poly, dtype=float)
    d = g - g.mean(0)
    vt = np.linalg.svd(d, full_matrices=False)[2]
    return [(float(vt[0][0]), float(vt[0][1])), (float(vt[1][0]), float(vt[1][1]))]


def taipei_main(segs, stations, terr):
    """台北車站複合車站。

    幾何全部取自實際資料，不是估的：
      · 站體大樓平面圖來自 OSM way 23641610（25 個頂點、約 2 萬 m2），
        標籤帶 building:levels=7、height=30、roof:shape=pyramidal、roof:height=18
      · 大門開在 OSM 標的南1~3門／北1~3門／東1,3門／西1,3門 節點上
      · 臺鐵／高鐵月台用 OSM 的四條月台中心線（level=-2，各約 327 m）
      · 出入口用 OSM 的 subway_entrance 實際座標（M1~M8 等）
      · 捷運月台的上下關係由 tunnel_layers 的釘樁還原（板南線 B3、淡水信義線 B4）
    """
    blds = _load("station_buildings.json")
    tp = [b for b in blds if (b.get("name_zh") or b.get("name")) == "臺北車站"]
    if not tp:
        return []
    b = tp[0]
    poly = [(p[0], p[1]) for p in b["polygon"]]
    cx, cz = shapes.centroid(poly)
    g0 = int(terr.y_at(cx, cz))

    ents = _load("entrances.json")
    doors = [(e["mc_x"], e["mc_z"]) for e in ents
             if str(e.get("ref") or "").endswith("門")
             and abs(e["mc_x"] - cx) < 160 and abs(e["mc_z"] - cz) < 160]

    out = []

    # ---- 1. 地面站體大樓 ----
    # height=30 撐不下 7 層又留 18 m 屋頂，所以把 30 當簷高、18 m 屋頂疊在上面
    # （簷高 30 + 屋頂 18 = 48 m，與台鐵圖面的柱網推算一致）。
    #
    # 屋頂是**紅磚色陶瓦加白邊的盝頂**（四坡水收到一個平頂平台），
    # 不是深灰、也不是收尖的角錐 —— roof_max 夾住上升量就會自然形成平台。
    #
    # OSM 量到的 158x127 m 是屋簷與雨庇外緣；主體結構是 149x110 m
    # （台鐵圖面柱網 8.75 m：東西 17 跨、南北 12 跨 + 中央窄跨 5.3 m），
    # 所以外牆往內縮 4 格，差額就是出挑的屋簷。
    ax = _axes(poly)
    rot = math.atan2(ax[0][1], ax[0][0])
    # 台鐵圖面：柱網 8.75 m，東西 17 跨 = 148.75 m，南北 12 跨 + 中央窄跨 5.3 = 110.3 m。
    # OSM 沿主軸量到 169x141 m，多出來的是屋簷與地面雨庇 —— 取交集把主體切回官方尺寸。
    body_poly = shapes.rect(cx, cz, 148.75, 110.3, rot)
    core_poly = shapes.rect(cx, cz, 61.25, 40.30, rot)   # 售票大廳柱列圍成的範圍
    cols = []
    for r in (-20.15, 20.15):                       # 兩排相距 40.3 m
        for c in (-26.25, -8.75, 8.75, 26.25):      # 同排柱距 17.5 m
            cols.append((round(cx + ax[0][0]*c + ax[1][0]*r),
                         round(cz + ax[0][1]*c + ax[1][1]*r)))
    out.append(Building(
        poly, g0, storeys=7, storey_h=4,
        wall="minecraft:smooth_sandstone",
        floor="minecraft:polished_andesite",
        roof="minecraft:bricks",
        trim="minecraft:white_concrete",
        glass="minecraft:light_gray_stained_glass_pane",
        roof_slope=0.5, roof_max=18, eaves=2,
        doors=doors, open_core=7, body_poly=body_poly, core_poly=core_poly,
        columns=cols, col_half=1,
        checker=("minecraft:black_concrete", "minecraft:white_concrete"),
        found=8, name="臺北車站"))

    # ---- 2. B1 大廳 ----
    b1 = g0 - 7
    out.append(Slab(shapes.rect(cx, cz, 150, 120), b1, clear=4,
                    wall="minecraft:deepslate_bricks"))

    # ---- 3. 臺鐵／高鐵月台層 ----
    plats = [p["geometry"] for p in _load("platform_levels.json")
             if p.get("station") == "台北車站" and str(p.get("level")) == "-2"
             and p.get("ref") in ("1", "2", "3", "4")]
    if plats:
        xs = [q[0] for g in plats for q in g]; zs = [q[1] for g in plats for q in g]
        hall = [(min(xs) - 10, min(zs) - 12), (max(xs) + 10, min(zs) - 12),
                (max(xs) + 10, max(zs) + 12), (min(xs) - 10, max(zs) + 12)]
        out.append(RailHall(plats, g0 - 17, hall, half_w=4, clear=7))

    # ---- 4. 出入口：真實座標的樓梯井 + 通道 ----
    onl = _station_on_lines(segs, "台北車站")
    targets = []
    for ref, (sx, sz, ux, uz, ty) in onl.items():
        targets.append((sx, sz, ty + 7, ref))      # 穿堂層可站立高度
    targets.append((cx, cz, b1 + 1, "B1"))

    picked = []
    for e in ents:
        r = str(e.get("ref") or "")
        if not re.match(r"^[MKZ]\d+$", r):
            continue
        ex, ez = e["mc_x"], e["mc_z"]
        if math.hypot(ex, ez) > 260:
            continue
        picked.append((r, ex, ez))
    picked.sort()
    for r, ex, ez in picked[:14]:
        tx, tz, ty, ref = min(targets, key=lambda t: math.hypot(t[0]-ex, t[1]-ez))
        d = math.hypot(tx - ex, tz - ez)
        eg = int(terr.y_at(ex, ez))          # 出入口當地的地面，不是大樓的
        if d < 12 or ty >= eg - 4:
            continue
        ux, uz = (tx - ex) / d, (tz - ez) / d
        # 樓梯井朝著目標，四個正交方向取最接近的
        if abs(ux) >= abs(uz):
            dx, dz = (1 if ux > 0 else -1), 0
        else:
            dx, dz = 0, (1 if uz > 0 else -1)
        out.append(ShaftStair(ex, ez, dx, dz, eg, ty))
        bx = ex + dx * (ShaftStair.FLIGHT + 2)
        bz = ez + dz * (ShaftStair.FLIGHT + 2)
        out.append(Passage(bx, bz, tx, tz, ty))
    return out
