#!/usr/bin/env python3
"""地標建築：從 OSM 平面圖擠出一棟真的房子，而不是沿線掃出來的制式站屋。

路線上的東西（隧道、高架、月台）都是沿著中心線掃斷面產生的，但地面上的
站體大樓不是 —— 它是一個任意多邊形，要自己光柵化、砌牆、蓋屋頂。

BlockSink 的實作（infrastructure 的 World）會自動丟掉不屬於目前 region
的方塊，所以這裡只要對每個 bbox 涵蓋到的 region 各呼叫一次 build()，
裁切交給它處理。

自我測試: ./.venv/bin/python -m tests.test_landmarks
"""
import collections
import os, math, json

from mrt import config
from mrt.application import build_concourse as BCC
from mrt.application import build_exits as BX
from mrt.application.build_concourse import ShaftStair
from mrt.domain import geometry as shapes

AIR = "minecraft:air"

# 台北車站複合體：地下街同時服務台北車站與北門（台北地下街西端在北門站），
# 中山地下街則一路通到中山、雙連 —— 這兩站的出入口現實中就是開在地下街上，
# 各自另拉樓梯井的話會把地下街挖穿，所以一併交給地下街處理。
COMPLEX = ("台北車站", "北門", "中山", "雙連")
INDOOR_R = 1500        # 收多遠以內的通道；中山地下街一路通到雙連


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
    """回傳 (地標清單, 真實出入口)。build_world 會依 bbox() 把地標分桶，
    再對每個涵蓋到的 region 呼叫 build(w)。

    真實出入口涵蓋全網每一座車站（地下、高架、平面），轉乘站的兩座站體之間
    另接轉乘通道；台北車站複合體（COMPLEX）例外，它靠地下街進出與轉乘。

    segs     : build_world 規劃出來的路段（含 samples / ys / ground / stn / hw）
    stations : (refs, 中文名, mc_x, mc_z, 英文名, ref字串) 串列
    terr     : Terrain，用來查地面高程

    真實出入口是 {(路段索引, 取樣索引): 井數}：有真實出入口的車站不再蓋
    樣板樓梯，cli 靠這張表把它關掉。
    """
    out = []
    tm, leftover = taipei_main(segs, stations, terr)
    out += tm
    # 台北車站一帶的出入口由地下街負責；其餘地下站照 entrances.json 蓋。
    # 複合站裡地下街接不上的出入口也交給這裡，各自接進所屬站體。
    # 地下街的地板與樓梯先占位，後蓋的井與通道才不會挖穿它。
    by_name = collections.defaultdict(list)
    for e in _load("entrances.json"):
        if e.get("source") == "near_station" or not e.get("station"):
            continue                    # 一般建物大門，不是捷運出入口
        if e["station"] in COMPLEX:
            continue
        ref = str(e.get("ref") or e.get("name_zh") or e.get("name") or "")
        by_name[e["station"]].append((ref, int(e["mc_x"]), int(e["mc_z"])))
    for name, lst in leftover.items():
        by_name[name] = lst
    ex_objs, exits, _ = BX.station_exits(
        segs, by_name, lambda x, z: int(terr.y_at(x, z)),
        used=BX.footprint(tm), no_transfer=COMPLEX, no_default=COMPLEX)
    out += ex_objs
    # 複合站的地下站體由地下街的連絡梯進出，樣板樓梯要關掉：那座樓梯從穿堂層
    # 一路爬到地面，正好穿過地下街那一層，踏面橫在通道裡把路封死 ——
    # 中山站的松山新店線月台就是這樣從地下街走不到的。
    from mrt.domain.alignment import structure_for_ground
    for li, sg in enumerate(segs):
        for bi, (full, name, en) in sg["stn"].items():
            if name in COMPLEX and structure_for_ground(
                    int(sg["ys"][bi]), int(sg["ground"][bi])) == "tunnel":
                exits.setdefault((li, bi), 0)
    return out, exits


def _load(name):
    f = os.path.join(config.DATA, name)
    if not os.path.exists(f):
        return []
    return json.load(open(f, encoding="utf-8"))["items"]


def _station_on_lines(segs, zh, underground_only=False):
    """找出某座車站在各條線上的位置：{ref: (x, z, ux, uz, 軌面y)}"""
    from mrt.domain.alignment import structure_for_ground
    out = {}
    for sg in segs:
        for bi, (full, nm, en) in sg["stn"].items():
            if nm == zh and sg["ref"] not in out:
                x, z, ux, uz, _ = sg["samples"][bi]
                y, g = int(sg["ys"][bi]), int(sg["ground"][bi])
                if underground_only and structure_for_ground(y, g) != "tunnel":
                    continue
                out[sg["ref"]] = (x, z, ux, uz, y)
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
        return [], {}
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
    rail_hall_y = None
    plats = [p["geometry"] for p in _load("platform_levels.json")
             if p.get("station") == "台北車站" and str(p.get("level")) == "-2"
             and p.get("ref") in ("1", "2", "3", "4")]
    if plats:
        xs = [q[0] for g in plats for q in g]; zs = [q[1] for g in plats for q in g]
        hall = [(min(xs) - 10, min(zs) - 12), (max(xs) + 10, min(zs) - 12),
                (max(xs) + 10, max(zs) + 12), (min(xs) - 10, max(zs) + 12)]
        out.append(RailHall(plats, g0 - 17, hall, half_w=4, clear=7))
        rail_hall_y = g0 - 16          # 台鐵／高鐵大廳的可站立面

    # ---- 4. 地下街：照 OSM 的地下通道中心線蓋，把所有出入口接起來 ----
    # 原本這裡是「每個出入口各拉一座樓梯井到最近的目標」，目標彼此不相通，
    # 蓋出來是十四座各自獨立的洞。改成照 OSM 實際測繪的地下街網路蓋：
    # 台北車站一帶有 7.7 km 的通道中心線（台北地下街、站前地下街、中山地下街、
    # 凱薩美食街、M/K 區穿堂），照著蓋出來本來就是連通的。
    ways = [w for w in _load("indoor.json")
            if math.hypot(w["mc_x"] - cx, w["mc_z"] - cz) <= INDOOR_R]
    picked = [(str(e.get("ref") or ""), e["mc_x"], e["mc_z"]) for e in ents
              if e.get("station") in COMPLEX and str(e.get("ref") or "")
              and math.hypot(e["mc_x"] - cx, e["mc_z"] - cz) <= INDOOR_R]
    station_of = {(e["mc_x"], e["mc_z"]): e["station"] for e in ents
                  if e.get("station") in COMPLEX}
    # 每座複合站在每條地下線上的穿堂層都要接一座連絡梯。原本只接台北車站
    # 自己的三條線，北門的松山新店線月台從地下街根本走不到。
    links = []
    for name in COMPLEX:
        for ref, (sx, sz, ux, uz, ty) in _station_on_lines(
                segs, name, underground_only=True).items():
            tag = ref if name == "台北車站" else f"{ref}@{name}"
            links.append((sx, sz, ty + 7, tag, ux, uz))
    if rail_hall_y is not None:
        # 台鐵／高鐵大廳也要接上 —— 現實中台北車站的地下街本來就是先通到
        # 台鐵 B1 大廳，再往下到月台。
        links.append((cx, cz, rail_hall_y, "台鐵", 1.0, 0.0))

    hall_cells = shapes.poly_cells(shapes.rect(cx, cz, 150, 120))
    objs, rep = BCC.plan(ways, picked, lambda x, z: int(terr.y_at(x, z)),
                         b1 + 1, links=links, near=(cx, cz),
                         no_wall=hall_cells)
    for o in objs:
        o.underground = True        # 地下街不必觸發地形生成，見 cli/build_world
    out += objs
    print(f"  台北車站地下街：通道 {rep['length']:,} m、"
          f"地板 {rep['cells']:,} 格、出入口 {len(rep['exits'])} 座樓梯"
          + (f"、接不上的 {len(rep['orphan'])} 個" if rep["orphan"] else ""))
    for nm, sx0, sz0, yto, yg0 in rep["links"]:
        print(f"    連絡梯樓梯井 {nm:<8} ({sx0},{sz0})  "
              f"地下街 y{yg0 + 1} -> 穿堂 y{yto}")

    # 接不上地下街的出入口（OSM 沒畫那一帶的通道）退回舊做法：
    # 一座樓梯井下到 B1 大廳。大廳本身有被地下街接到，所以還是連通的。
    # 限 260 m 內：更遠的（北門西側那幾個）OSM 那一帶根本沒有通道，
    # 硬拉一條六百公尺的通道過去只會把沿路的東西全鑿穿 ——
    # 那些交還給一般車站的出入口規劃（build_exits），各自接進所屬站體。
    leftover = collections.defaultdict(list)
    handled = 0
    for r, ex, ez in rep["orphan"]:
        eg = int(terr.y_at(ex, ez))
        d = math.hypot(cx - ex, cz - ez)
        if d <= 260 and handled < 8 and d >= 12 and b1 + 1 < eg - 4:
            ux, uz = (cx - ex) / d, (cz - ez) / d
            if abs(ux) >= abs(uz):
                dx, dz = (1 if ux > 0 else -1), 0
            else:
                dx, dz = 0, (1 if uz > 0 else -1)
            out.append(ShaftStair(ex, ez, dx, dz, eg, b1 + 1))
            bx = ex + dx * (ShaftStair.FLIGHT + 2)
            bz = ez + dz * (ShaftStair.FLIGHT + 2)
            out.append(Passage(bx, bz, cx, cz, b1 + 1))
            handled += 1
            continue
        st = station_of.get((int(ex), int(ez)))
        if st:
            leftover[st].append((r, int(ex), int(ez)))
    return out, leftover
