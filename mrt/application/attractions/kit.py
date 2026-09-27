#!/usr/bin/env python3
"""景點建築的共用工具：局部座標框、禁區守門、基地整地、平面遮罩、屋頂高度場。

每座景點是一個 Attraction（見 __init__.py 的說明）。這裡放的是大家都會用到的
零件，讓台北101、中正紀念堂、城門各自的模組只寫「長相」：

  Frame     建築自己的座標系。OSM 的輪廓多半不是正南北向（總統府偏 1.6°、
            國父紀念館偏 2°），直接在世界格子上畫矩形會歪；在局部座標 (u, v)
            裡畫、再對每個**世界格子**反算回局部座標測試（反向光柵化），
            轉任何角度都不會漏格。u 軸沿 angle，v 軸是 u 往 +z 那側轉 90°
            （angle=0 時 u = 東、v = 南，跟世界的 x、z 一樣）。
  遮罩      Frame 範圍上的二維布林陣列 [z][x]。rect / chamfer / ellipse / ngon /
            polygon 產生，ring / erode / dilate 做描邊與內縮。
  Painter   把遮罩寫成方塊：fill（每格一段 y）、walls（外圈加窗）、
            heightfield（屋頂、斗拱這種曲面）。所有寫入都經過 Guard。
  屋頂      回傳高度場（浮點數陣列）：hip（廡殿）、hip_gable（歇山）、
            pyramid（攢尖：四角、八角、圓）、gable（硬山/懸山）。
            中式屋頂的凹曲面用 profile 次方、起翹用 lift。
  Site      基地：查地面高度（cli 給的「蓋出來的地形」）、決定樓板高度、
            整地（低的填、高的削）。
  Guard     禁區守門：捷運出入口亭、樓梯井、地下街、高架橋所在的格子一律不寫
            （cli 依地標與路段算出來的 keep 函式）。景點比那些東西晚蓋，
            沒有這一關，新光摩天大樓的基座會把站前的出入口封死。

座標慣例與存檔一致：x = 東、z = 南、y = 上；方塊 (x, z) 的中心在 (x+.5, z+.5)。
這一層只呼叫 BlockSink 的 set() 與 SignSink 的 sign()，不碰檔案。
"""
import math
from collections import namedtuple

import numpy as np

from mrt.domain import geometry as shapes

AIR = "minecraft:air"

# 資料包的傳送點：腳所在的方塊 (x, y, z)、朝向（yaw 0 = 南、90 = 西、±180 = 北、-90 = 東；
# pitch 正值往下看），zh / en 是對話框按鈕上的字。key 是函式路徑的一部分
# （"" = 預設的觀景點 sight/<id>，"top" -> sight/<id>_top）。
Spot = namedtuple("Spot", "key x y z yaw pitch zh en")


def sight_fn(aid, key=""):
    """景點傳送函式的路徑（不含命名空間）："sight/taipei101"、"sight/taipei101_top"。
    景點裡的告示牌（例如 101 大廳的「89 樓觀景台」）與資料包（ride_plan）都從這裡拿，
    跟 network.ride_fn 是同一種約定：牌子上的指令與資料包的檔名是同一份的兩端。"""
    return "sight/%s%s" % (aid, ("_" + key) if key else "")


def yaw_of(fx, fz):
    """朝向 (dx, dz) -> Minecraft 的 yaw（度）：0 = 南 (+z)、90 = 西、±180 = 北、-90 = 東。"""
    return math.degrees(math.atan2(-fx, fz))


def look(x, y, z, tx, ty, tz, eye=1.62):
    """站在 (x, y, z)（腳的方塊）看向 (tx, ty, tz) 的 (yaw, pitch)。"""
    dx, dz = tx - (x + 0.5), tz - (z + 0.5)
    dy = ty - (y + eye)
    yaw = yaw_of(dx, dz)
    pitch = -math.degrees(math.atan2(dy, math.hypot(dx, dz)))
    return round(yaw, 1), round(max(-60.0, min(60.0, pitch)), 1)


CARDINAL = {(0, -1): "north", (0, 1): "south", (1, 0): "east", (-1, 0): "west"}


def cardinal(dx, dz):
    """任意方向 -> 最接近的正方位名稱（樓梯、門、壁掛告示牌的 facing）。"""
    if abs(dx) >= abs(dz):
        return "east" if dx > 0 else "west"
    return "south" if dz > 0 else "north"


# ---------------------------------------------------------------- Guard

class Guard:
    """包住 BlockSink / SignSink：keep(x, y, z) 為真的格子不寫。記下擋掉幾格。"""

    def __init__(self, w, keep=None):
        self.w = w
        self.keep = keep
        self.dropped = 0

    def set(self, x, y, z, block):
        if self.keep is not None and self.keep(x, y, z):
            self.dropped += 1
            return
        self.w.set(x, y, z, block)

    def sign(self, x, y, z, lines, **kw):
        if self.keep is not None and self.keep(x, y, z):
            self.dropped += 1
            return
        self.w.sign(x, y, z, lines, **kw)


# ---------------------------------------------------------------- Frame 與遮罩

class Frame:
    """局部座標框：原點 (cx, cz)、u 軸方向 angle（弧度，從 +x 往 +z 量）。

    grid 涵蓋局部座標 |u|, |v| <= extent 那個正方形轉到世界後的外接矩形，
    U、V 是每個世界格子中心的局部座標（二維陣列 [z][x]）。
    """

    def __init__(self, cx, cz, angle, extent):
        self.cx, self.cz, self.angle = float(cx), float(cz), float(angle)
        self.c, self.s = math.cos(self.angle), math.sin(self.angle)
        r = float(extent) * (abs(self.c) + abs(self.s)) + 2
        self.x0, self.z0 = int(math.floor(self.cx - r)), int(math.floor(self.cz - r))
        self.x1, self.z1 = int(math.ceil(self.cx + r)), int(math.ceil(self.cz + r))
        xs = np.arange(self.x0, self.x1 + 1)
        zs = np.arange(self.z0, self.z1 + 1)
        self.X, self.Z = np.meshgrid(xs, zs)                 # [z][x]
        dx, dz = self.X + 0.5 - self.cx, self.Z + 0.5 - self.cz
        self.U = dx * self.c + dz * self.s
        self.V = -dx * self.s + dz * self.c
        self.shape = self.X.shape

    # ---- 座標換算 ----
    def world(self, u, v):
        """局部 (u, v) -> 世界 (x, z)（浮點數）。"""
        return (self.cx + u * self.c - v * self.s, self.cz + u * self.s + v * self.c)

    def cell(self, u, v):
        """局部 (u, v) -> 那一點所在的世界格子 (x, z)。"""
        x, z = self.world(u, v)
        return int(math.floor(x)), int(math.floor(z))

    def local(self, x, z):
        """世界**格子** (x, z) 的中心 -> 局部 (u, v)（會先加 0.5）。
        OSM 輪廓的頂點是點、不是格子，換算點要用 local_pt()。"""
        dx, dz = x + 0.5 - self.cx, z + 0.5 - self.cz
        return dx * self.c + dz * self.s, -dx * self.s + dz * self.c

    def local_pt(self, x, z):
        """世界座標的**點** (x, z)（例如 OSM 頂點）-> 局部 (u, v)，不加 0.5。"""
        dx, dz = x - self.cx, z - self.cz
        return dx * self.c + dz * self.s, -dx * self.s + dz * self.c

    def dir(self, du, dv):
        """局部方向 -> 世界方向 (dx, dz)（單位向量）。"""
        return du * self.c - dv * self.s, du * self.s + dv * self.c

    def facing(self, du, dv):
        """局部方向 -> 最接近的正方位（樓梯、門、告示牌）。"""
        return cardinal(*self.dir(du, dv))

    def yaw(self, du, dv):
        return yaw_of(*self.dir(du, dv))

    # ---- 遮罩 ----
    def empty(self):
        return np.zeros(self.shape, dtype=bool)

    def rect(self, u0, u1, v0, v1):
        return (self.U >= u0) & (self.U <= u1) & (self.V >= v0) & (self.V <= v1)

    def box(self, a, b, du=0.0, dv=0.0):
        """中心 (du, dv)、半長 a（沿 u）、半寬 b（沿 v）的矩形。"""
        return self.rect(du - a, du + a, dv - b, dv + b)

    def chamfer(self, a, b, c, du=0.0, dv=0.0):
        """四角各切掉一個腰長 c 的等腰直角三角形的矩形（新光摩天大樓、101 的角）。"""
        u, v = np.abs(self.U - du), np.abs(self.V - dv)
        return (u <= a) & (v <= b) & (u + v <= a + b - c)

    def ellipse(self, a, b, du=0.0, dv=0.0):
        return ((self.U - du) / a) ** 2 + ((self.V - dv) / b) ** 2 <= 1.0

    def ngon_radius(self, n, rot=0.0, du=0.0, dv=0.0):
        """正 n 邊形的「多邊形半徑」：max_k (u cos φk + v sin φk)。<= r 就在邊心距 r 的多邊形內。
        rot=0 時第一條邊的法線沿 +u（八角形的一條邊正對 u 軸）。"""
        u, v = self.U - du, self.V - dv
        out = None
        for k in range(n):
            ph = rot + 2 * math.pi * k / n
            d = u * math.cos(ph) + v * math.sin(ph)
            out = d if out is None else np.maximum(out, d)
        return out

    def ngon(self, n, r, rot=0.0, du=0.0, dv=0.0):
        return self.ngon_radius(n, rot, du, dv) <= r

    def polygon(self, poly):
        """世界座標的多邊形（OSM 輪廓）-> 遮罩。格心在多邊形內才算（同 geometry.poly_cells）。"""
        m = self.empty()
        for x, z in shapes.poly_cells(poly):
            i, j = z - self.z0, x - self.x0
            if 0 <= i < self.shape[0] and 0 <= j < self.shape[1]:
                m[i, j] = True
        return m

    def cells(self, mask):
        """遮罩 -> [(x, z)]。"""
        return list(zip(self.X[mask].tolist(), self.Z[mask].tolist()))


def erode(mask, n=1):
    """往內縮 n 格（四鄰）。"""
    m = mask.copy()
    for _ in range(n):
        e = m.copy()
        e[1:, :] &= m[:-1, :]
        e[:-1, :] &= m[1:, :]
        e[:, 1:] &= m[:, :-1]
        e[:, :-1] &= m[:, 1:]
        e[0, :] = e[-1, :] = False
        e[:, 0] = e[:, -1] = False
        m = e
    return m


def dilate(mask, n=1):
    """往外長 n 格（四鄰）。"""
    m = mask.copy()
    for _ in range(n):
        d = m.copy()
        d[1:, :] |= m[:-1, :]
        d[:-1, :] |= m[1:, :]
        d[:, 1:] |= m[:, :-1]
        d[:, :-1] |= m[:, 1:]
        m = d
    return m


def ring(mask, width=1):
    """外圈（寬 width 格）：遮罩裡、往內縮 width 格之後不在的那些。"""
    return mask & ~erode(mask, width)


def depth(mask, limit=200):
    """每格到遮罩邊界的格數（外圈 = 1，四鄰距離）。任意平面的四坡屋頂用它當高度。"""
    d = np.zeros(mask.shape, dtype=np.int32)
    cur = mask.copy()
    k = 0
    while cur.any() and k < limit:
        k += 1
        d[cur] = k
        cur = erode(cur)
    return d


# ---------------------------------------------------------------- 屋頂高度場
#
# 全部回傳「比簷口高多少」的浮點數陣列（簷口 = 0），呼叫端加上簷口的 y。
# 中式屋頂的凹曲面：profile > 1 時靠近屋脊陡、靠近簷口緩（舉折）；
# lift 是四個翼角的起翹量（公尺），corner 是起翹從角落往回延伸多長。

def hip(fr, a, b, rise, profile=1.0, lift=0.0, corner=None, du=0.0, dv=0.0):
    """廡殿頂（四坡）：矩形 |u|<=a、|v|<=b，屋脊沿長邊。"""
    u, v = np.abs(fr.U - du), np.abs(fr.V - dv)
    short = min(a, b)
    d = np.minimum(a - u, b - v).clip(0, None)            # 到最近簷口的距離
    h = rise * (d / short).clip(0, 1) ** profile
    return h + _lift(u, v, a, b, lift, corner, d)


def hip_gable(fr, a, b, rise, gable_in, profile=1.0, lift=0.0, corner=None, du=0.0, dv=0.0):
    """歇山頂：長坡（沿 v 方向的兩坡）一路到屋脊；兩端先是一段廡殿式的小坡，
    再在 |u| = a - gable_in 的地方豎起三角形的山花（高度場在那裡陡升到長坡的高度）。"""
    u, v = np.abs(fr.U - du), np.abs(fr.V - dv)
    long_ = rise * ((b - v) / b).clip(0, 1) ** profile     # 兩個長坡
    end = rise * ((a - u) / b).clip(0, 1) ** profile        # 兩端的小坡（跟長坡同斜率）
    h = np.where(u > a - gable_in, np.minimum(long_, end), long_)
    d = np.minimum(a - u, b - v).clip(0, None)
    return h + _lift(u, v, a, b, lift, corner, d)


def gable(fr, a, b, rise, profile=1.0, du=0.0, dv=0.0):
    """兩坡頂（硬山）：屋脊沿 u，兩端是垂直的山牆。"""
    v = np.abs(fr.V - dv)
    return rise * ((b - v) / b).clip(0, 1) ** profile


def pyramid(fr, r, rise, sides=4, rot=0.0, profile=1.0, lift=0.0, du=0.0, dv=0.0):
    """攢尖頂：sides=4 四角、8 八角（中正紀念堂）、0 圓錐。r 是簷口的邊心距（圓就是半徑）。"""
    if sides:
        rr = fr.ngon_radius(sides, rot, du, dv)
    else:
        rr = np.hypot(fr.U - du, fr.V - dv)
    d = (r - rr).clip(0, None)
    h = rise * (d / r).clip(0, 1) ** profile
    if lift and sides:
        # 翼角：越靠近多邊形的頂點（兩條邊的法線之間）越翹
        ang = np.arctan2(fr.V - dv, fr.U - du) - rot
        k = (ang / (2 * math.pi / sides)) % 1.0              # 0 與 1 是邊的法線、0.5 是頂點
        near_vertex = (1 - np.abs(k - 0.5) * 2) ** 4
        near_eave = (1 - d / (0.35 * r)).clip(0, 1) ** 2
        h = h + lift * near_vertex * near_eave
    return h


def _lift(u, v, a, b, lift, corner, d):
    """四個翼角的起翹：沿簷口越靠近角落越高，只影響靠近簷口的那一圈。"""
    if not lift:
        return 0.0
    c = corner or 0.35 * min(a, b)
    # 沿著「最近的那條簷口」量離角落多近：靠長簷（v 那側）就看 u、靠短簷就看 v。
    # 兩個方向取 max 的話，長簷正中間（v≈b）也會被算成「靠近角落」而整條翹起來
    near_long = (b - v) <= (a - u)
    along = np.where(near_long, ((u - (a - c)) / c).clip(0, 1), ((v - (b - c)) / c).clip(0, 1))
    near = (1 - d / c).clip(0, 1)
    return lift * along ** 2 * near


# ---------------------------------------------------------------- Painter

class Painter:
    """在 Frame 上把遮罩寫成方塊。w 是（已包了 Guard 的）BlockSink。"""

    def __init__(self, w, frame):
        self.w, self.fr = w, frame

    def set(self, x, y, z, block):
        self.w.set(int(x), int(y), int(z), block)

    def at(self, u, v, y, block):
        """局部座標那一點所在的格子。"""
        x, z = self.fr.cell(u, v)
        self.w.set(x, int(y), z, block)

    def fill(self, mask, y0, y1, block):
        """遮罩裡每一格從 y0 疊到 y1（含）。y0、y1 可以是整數或跟 Frame 同形的陣列。"""
        X, Z = self.fr.X[mask], self.fr.Z[mask]
        Y0 = np.broadcast_to(np.asarray(y0), self.fr.shape)[mask]
        Y1 = np.broadcast_to(np.asarray(y1), self.fr.shape)[mask]
        s = self.w.set
        for x, z, a, b in zip(X.tolist(), Z.tolist(), np.rint(Y0).astype(int).tolist(),
                              np.rint(Y1).astype(int).tolist()):
            for y in range(a, b + 1):
                s(x, y, z, block)

    def layer(self, mask, y, block):
        self.fill(mask, y, y, block)

    def clear(self, mask, y0, y1):
        self.fill(mask, y0, y1, AIR)

    def walls(self, mask, y0, y1, wall, window=None, every=3, sill=1, head=1, storey=None):
        """外圈的牆：y0..y1。給 window 就開窗 —— 每層（storey 格一層，預設整段一層）
        離樓板 sill 格以上、離天花 head 格以下，沿外圈每 every 格留一格牆當窗櫺。"""
        rg = ring(mask)
        X, Z = self.fr.X[rg].tolist(), self.fr.Z[rg].tolist()
        for x, z in zip(X, Z):
            for y in range(int(y0), int(y1) + 1):
                blk = wall
                if window is not None:
                    k = (y - y0) % storey if storey else (y - y0)
                    top = (storey or (y1 - y0 + 1)) - 1
                    if sill <= k <= top - head and (x + z) % every != 0:
                        blk = window
                self.w.set(x, y, z, blk)

    def heightfield(self, mask, base, h, block, under=None, shell=None, slab=None):
        """每格從 base 疊到 base + h（h 是浮點數陣列）。

        shell=k：只留最上面 k 格（屋頂是殼，裡面挑空）；under：殼底下那一格的材質
        （例如簷口底下的斗拱色）。slab="minecraft:xxx_slab"：小數部分 >= 0.5 的地方
        在頂上再加半磚，坡面就不會一格一格地跳。"""
        X, Z = self.fr.X[mask].tolist(), self.fr.Z[mask].tolist()
        B = np.broadcast_to(np.asarray(base), self.fr.shape)[mask]
        H = np.asarray(h)[mask] if np.ndim(h) else np.full(len(X), float(h))
        top = B + H
        s = self.w.set
        for x, z, b, t in zip(X, Z, np.rint(B).astype(int).tolist(), top.tolist()):
            ti = int(math.floor(t))
            lo = b if shell is None else max(b, ti - shell + 1)
            for y in range(lo, ti + 1):
                s(x, y, z, block)
            if under is not None and lo - 1 >= b:
                s(x, lo - 1, z, under)
            if slab is not None and t - ti >= 0.5:
                s(x, ti + 1, z, slab + "[type=bottom]")

    def columns(self, pts, radius, y0, y1, block, square=False):
        """柱列：pts 是局部座標 [(u, v)]，每根半徑 radius（圓柱，square=True 方柱）。"""
        for u, v in pts:
            cx, cz = self.fr.world(u, v)
            r = radius
            for x in range(int(math.floor(cx - r - 1)), int(math.ceil(cx + r + 1))):
                for z in range(int(math.floor(cz - r - 1)), int(math.ceil(cz + r + 1))):
                    du, dv = self.fr.local(x, z)
                    du, dv = du - u, dv - v
                    inside = (max(abs(du), abs(dv)) <= r) if square else (du * du + dv * dv <= r * r + 0.25)
                    if inside:
                        for y in range(int(y0), int(y1) + 1):
                            self.w.set(x, y, z, block)


# ---------------------------------------------------------------- Site

class Site:
    """基地：地面高度與整地。

    ground(x, z) 是 cli 給的「這一格蓋出來的地面方塊 y」（跟 terrain_chunk 同一個式子，
    走廊外會漸變回超平坦的 y64）。keep 是禁區（同 Guard）。

    地面最好在 plan() 裡查完（site.grid(fr, mask) 先抓一整片）：build() 會被每個
    region 各呼叫一次，在裡面逐格查地面既慢、又讓 build() 依賴 cli 的地形快取。
    """

    def __init__(self, ground, keep=None):
        self.ground = ground
        self.keep = keep
        self._cache = {}

    def g(self, x, z):
        k = (x, z)
        v = self._cache.get(k)
        if v is None:
            v = self._cache[k] = int(self.ground(x, z))
        return v

    def grid(self, fr, mask=None):
        """Frame 上每一格的地面 y（mask 以外填 -999）。"""
        out = np.full(fr.shape, -999, dtype=np.int32)
        m = mask if mask is not None else np.ones(fr.shape, dtype=bool)
        for i, j in zip(*np.nonzero(m)):
            out[i, j] = self.g(int(fr.X[i, j]), int(fr.Z[i, j]))
        return out

    def level(self, fr, mask, how="median"):
        """一樓樓板該放在哪個 y：遮罩範圍地面高度的中位數（how="max" 取最高，不會埋進坡裡）。"""
        g = self.grid(fr, mask)[mask]
        if len(g) == 0:
            return 64
        return int(np.max(g)) if how == "max" else int(np.round(np.median(g)))

    def prepare(self, w, fr, mask, y, fill="minecraft:stone", top="minecraft:grass_block", clear=24):
        """整地：遮罩範圍的地面整成 y（y 那一格放 top）。低於 y 的往上填 fill，
        高於 y 的削掉、上面清空 clear 格（削坡）。寫入一律走 w（呼叫端給 Guard）。"""
        g = self.grid(fr, mask)
        X, Z, G = fr.X[mask].tolist(), fr.Z[mask].tolist(), g[mask].tolist()
        for x, z, gy in zip(X, Z, G):
            for yy in range(min(gy, y) + 1, y):
                w.set(x, yy, z, fill)
            w.set(x, y, z, top)
            for yy in range(y + 1, max(gy, y) + 1 + (clear if gy > y else 0)):
                w.set(x, yy, z, AIR)


# ---------------------------------------------------------------- Attraction 基底

class Attraction:
    """一座景點。子類別覆寫 plan() 與 build()，其餘有預設。

    生命週期（cli 照這個順序呼叫）：
      1. __init__(item)          item 是 data/attractions.json 的一筆（OSM 輪廓、標籤）
      2. bbox()                  整座景點（含廣場）占的世界範圍：分桶與地形距離場用
      3. plan(site)              拿到地面與禁區之後定案：一樓樓板高度、門、觀景點
      4. build(w)                寫方塊；w 已包了 Guard。跨幾個 region 就被呼叫幾次
                                 （World 會丟掉不屬於目前 region 的方塊）
      5. spots()                 資料包的傳送點（第一個是預設觀景點，key=""）
      6. plaque()                景點說明牌的四行字
    """

    height_m = None          # 公開資料的高度（公尺，從地面算到最高點）—— verify_attractions 拿來比
    margin = 12              # bbox 比 OSM 輪廓外擴幾格（廣場、台階、屋簷）
    # bbox 外再多遠也生成真實地形（再往外 cli 的 --fade 那一圈才漸變回超平坦 y64）。
    # 山坡上的景點要大一點，否則背後的山在建築後面幾十公尺就被削成一道斜坡
    terrain_margin = 48

    def __init__(self, item):
        self.item = item
        self.id = item["id"]
        self.name_zh = item["name_zh"]
        self.name_en = item["name_en"]
        self.features = item.get("features", [])
        self.g0 = None
        self._spots = []

    # ---- OSM 資料 ----
    def feature(self, osm):
        return next((f for f in self.features if f["osm"] == osm), None)

    def mains(self):
        return [f for f in self.features if f.get("main")]

    def outline(self):
        """主體的外環（世界座標）。預設取第一個有面積的指名元素，沒有就取中心最近、
        面積最大的建物。"""
        for f in self.mains():
            if f.get("outer") and f.get("area", 0) > 0:
                return max(f["outer"], key=lambda r: abs(_area(r)))
        blds = [f for f in self.features if f.get("outer") and "building" in f["tags"]]
        if not blds:
            return None
        f = min(blds, key=lambda f: f["dist"] - 0.001 * f["area"])
        return max(f["outer"], key=lambda r: abs(_area(r)))

    def center(self):
        return tuple(self.item["center"])

    # ---- 框架介面 ----
    def bbox(self):
        pts = self.outline() or [self.center()]
        x0, z0, x1, z1 = shapes.bbox(pts)
        m = self.margin
        return (int(math.floor(x0)) - m, int(math.floor(z0)) - m,
                int(math.ceil(x1)) + m, int(math.ceil(z1)) + m)

    def plan(self, site):
        raise NotImplementedError

    def build(self, w):
        raise NotImplementedError

    def spots(self):
        return list(self._spots)

    def plaque(self):
        """說明牌四行：中文名、英文名、一句事實、（留給框架填最近的捷運站）。
        第一行不准以「出口」開頭（verify_exits 靠那個認出入口亭）。"""
        return [self.name_zh, self.name_en, "", ""]

    def top_y(self):
        """最高點的 y（plan 之後才有）。"""
        if self.g0 is None or self.height_m is None:
            return None
        return self.g0 + int(round(self.height_m))


def _area(r):
    a = 0.0
    for i in range(len(r)):
        x1, z1 = r[i]
        x2, z2 = r[(i + 1) % len(r)]
        a += x1 * z2 - x2 * z1
    return a / 2


def principal_angle(poly):
    """多邊形的主軸方向（弧度）：最長的那組平行邊。OSM 的建物輪廓用它定 Frame 的 u 軸。"""
    best, ang = -1.0, 0.0
    n = len(poly)
    acc = {}
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        L = math.hypot(x2 - x1, z2 - z1)
        if L < 1e-6:
            continue
        a = math.atan2(z2 - z1, x2 - x1) % (math.pi / 2)    # 同一組正交邊折到同一個角度
        k = int(round(math.degrees(a))) % 90
        acc[k] = acc.get(k, 0.0) + L
    for k, L in acc.items():
        if L > best:
            best, ang = L, math.radians(k)
    return ang
