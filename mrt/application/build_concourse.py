#!/usr/bin/env python3
"""地下街生成器：把 OSM 的地下通道中心線砌成走得通的地下商場。

線形整理（併點、連通分量、出入口接駁）在 domain/concourse.py，這裡只負責
把方塊放進去。每個 build() 的第一個參數 w 是 ports.block_sink.BlockSink。

**為什麼全部蓋在同一層。** OSM 的 level 是各測繪聚落自己的基準，不是絕對
樓層：台北地下街標 -2、站前地下街標 -2 但 layer=-1、中山地下街標 -1，
三者實際上都是 B1。而且這個世界的垂直預算就只有一層 —— 地表 y66、
板南線站體頂板 y61，中間剛好放得下一層淨空。所以通道一律蓋在 B1，
垂直落差交給出入口樓梯與往穿堂層的連絡梯處理。這是取捨，不是疏漏。

**牆為什麼要先把地板算完才砌。** 通道在路口會交叉，各段自己砌牆的話，
先蓋的那段會把路口封死 —— 走廊看起來都在，卻走不過去。所以先把所有通道
與商場的地板格算成一個集合，牆只砌在「集合外緣」。

自我測試: ./.venv/bin/python tests/test_concourse.py
"""
import math

from mrt.domain import concourse as CC

AIR    = "minecraft:air"
FLOOR  = "minecraft:white_concrete"          # 商場地坪，與隧道的灰色系分開
CEIL   = "minecraft:light_gray_concrete"     # 頂板
WALL   = "minecraft:smooth_sandstone"        # 店面隔牆
STRUCT = "minecraft:deepslate_bricks"        # 結構襯砌，與站體箱涵同材質
SHOP   = "minecraft:glass_pane"              # 店面櫥窗
STAIR  = "minecraft:smooth_stone"
SLAB   = "minecraft:smooth_stone_slab[type=bottom]"
BARS   = "minecraft:iron_bars"
LAMP   = "minecraft:sea_lantern"

HEAD = 3            # 淨空格數（站立面往上算），頂板在 y+HEAD
TILE = 128          # 分塊邊長，讓每個物件的 bbox 夠小、分桶才有意義


# ---------- 光柵化 ----------

def stroke(p0, p1, half_w):
    """把一段中心線刷成地板格。半寬 half_w -> 寬 2*half_w+1 公尺。"""
    (x0, z0), (x1, z1) = p0, p1
    n = int(max(abs(x1 - x0), abs(z1 - z0)))
    out = set()
    if n == 0:
        cx, cz = int(round(x0)), int(round(z0))
        for dx in range(-half_w, half_w + 1):
            for dz in range(-half_w, half_w + 1):
                out.add((cx + dx, cz + dz))
        return out
    ux, uz = (x1 - x0) / n, (z1 - z0) / n
    for t in range(n + 1):
        cx, cz = x0 + ux * t, z0 + uz * t
        for dx in range(-half_w, half_w + 1):
            for dz in range(-half_w, half_w + 1):
                if dx * dx + dz * dz <= half_w * half_w + half_w:
                    out.add((int(round(cx)) + dx, int(round(cz)) + dz))
    return out


def outer_ring(cells):
    """地板格集合的外緣（八鄰域），也就是要砌牆的地方。

    用八鄰域而不是四鄰域：只擋四邊的話，兩格斜角相接的位置會留下一條
    對角縫，從剖面看不出來，走進去卻能直接穿出通道外的實心土。
    """
    ring = set()
    for x, z in cells:
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                c = (x + dx, z + dz)
                if c not in cells:
                    ring.add(c)
    return ring


# ---------- 水平層 ----------

class Tile:
    """地下街的一塊地板（含頂板、外牆、照明）。

    整座地下街先算成一個格子集合再切塊，切塊只是為了讓 bbox 小到可以
    分桶到 region；相鄰塊的邊界不會有牆，因為外緣是對整體算的。
    """

    def __init__(self, cells, ring, y, ceil_of, shopfront=True):
        self.cells = cells                  # {(x, z)} 地板
        self.ring = ring                    # {(x, z)} 外牆
        self.y = int(y)                     # 站立面
        self.ceil_of = ceil_of              # {(x, z): 頂板 y}
        self.shopfront = shopfront

    def bbox(self):
        xs = [c[0] for c in self.cells] + [c[0] for c in self.ring]
        zs = [c[1] for c in self.cells] + [c[1] for c in self.ring]
        return min(xs) - 1, min(zs) - 1, max(xs) + 1, max(zs) + 1

    def build(self, w):
        y = self.y
        for x, z in self.cells:
            cy = self.ceil_of.get((x, z), y + HEAD)
            w.set(x, y - 1, z, FLOOR)
            for yy in range(y, cy):
                w.set(x, yy, z, AIR)
            w.set(x, cy, z, CEIL)
            if x % 9 == 0 and z % 9 == 0:
                w.set(x, cy - 1, z, LAMP)
        for x, z in self.ring:
            cy = self.ceil_of.get((x, z))
            if cy is None:                  # 外緣沒有頂板高度，取鄰居的
                cy = max((self.ceil_of.get((x + dx, z + dz), y + HEAD)
                          for dx in (-1, 0, 1) for dz in (-1, 0, 1)),
                         default=y + HEAD)
            w.set(x, y - 1, z, STRUCT)
            for yy in range(y, cy + 1):
                # 店面：每 7 m 開一段 2 m 的櫥窗，讓它看起來像地下街而不是坑道
                win = (self.shopfront and yy in (y + 1, y + 2)
                       and ((x + z) % 7) < 2)
                w.set(x, yy, z, SHOP if win else WALL)


# ---------- 垂直連接 ----------

class Stair:
    """一段直梯：每 2 m 水平升降 1 m，整塊與半磚交替（與 build_line 同一套）。

    (x0, z0) 是低端的起點，(dx, dz) 是往高端走的方向（四個正交方向之一）。
    自己砌牆與頂板，所以可以從地下街直接鑽進土裡，不必事先挖好。

    交替順序一定要跟行進方向對上：上坡先放整塊再放半磚。反過來的話每兩公尺
    會出現 1.5 m 落差 —— 走得下去卻爬不上來，而且從剖面圖完全看不出來。
    """

    def __init__(self, x0, z0, dx, dz, y_lo, y_hi, half_w=2, head=HEAD,
                 label=None, headhouse=False, open_cells=()):
        self.x0, self.z0 = int(x0), int(z0)
        self.dx, self.dz = int(dx), int(dz)
        self.y_lo, self.y_hi = int(y_lo), int(y_hi)
        self.half_w, self.head = int(half_w), int(head)
        self.label, self.headhouse = label, headhouse
        # 已經是通道地板的格子不准砌牆。出入口常常兩兩相鄰（北3門與
        # 台北地下街 Y8 只差 8 m），一座梯的側牆會把另一座的接駁段封死；
        # 這種事從剖面圖完全看不出來，只有走一遍才會發現。
        self.open_cells = open_cells

    def run(self):
        """水平長度（公尺）"""
        return 2 * max(0, self.y_hi - self.y_lo)

    def _w(self, a, b):
        vx, vz = -self.dz, self.dx
        return self.x0 + self.dx * a + vx * b, self.z0 + self.dz * a + vz * b

    def bbox(self):
        H = self.half_w + 1
        ends = [self._w(a, b) for a in (-2, self.run() + 4) for b in (-H, H)]
        xs = [p[0] for p in ends]; zs = [p[1] for p in ends]
        return min(xs) - 2, min(zs) - 2, max(xs) + 2, max(zs) + 2

    def treads(self):
        """[(a, 支承方塊 y, 方塊種類, 站立面 y)]，a 是沿梯段的水平距離。"""
        out = []
        n = self.run()
        for t in range(n + 1):
            surf = self.y_lo + 0.5 * t
            half = abs(surf - math.floor(surf)) > 0.25
            yb = int(math.floor(surf)) if half else int(round(surf)) - 1
            out.append((t, yb, SLAB if half else STAIR, surf))
        return out

    def build(self, w):
        if self.y_hi <= self.y_lo:
            return
        H = self.half_w
        tr = self.treads()
        # 先挖：整段梯井連同前後各兩公尺一起清乾淨，再鋪踏面
        for a, yb, blk, surf in tr:
            for b in range(-H - 1, H + 2):
                x, z = self._w(a, b)
                edge = abs(b) == H + 1 and (x, z) not in self.open_cells
                for yy in range(yb, yb + self.head + 2):
                    w.set(x, yy, z, WALL if edge else AIR)
                if (x, z) not in self.open_cells:
                    w.set(x, yb + self.head + 1, z, STRUCT)  # 頂板隨梯段上升
        for a, yb, blk, surf in tr:
            for b in range(-H, H + 1):
                x, z = self._w(a, b)
                w.set(x, yb, z, blk)
            if a % 8 == 0:
                x, z = self._w(a, 0)
                w.set(x, yb + self.head, z, LAMP)
        # 上下兩端各補一段平台，接回通道的地板高度
        for a, ylev in ((-2, self.y_lo), (self.run() + 2, self.y_hi)):
            for t in (0, 1, 2):
                aa = a + (t if a < 0 else -t)
                for b in range(-H, H + 1):
                    x, z = self._w(aa, b)
                    w.set(x, ylev - 1, z, STAIR)
                    for yy in range(ylev, ylev + self.head + 1):
                        w.set(x, yy, z, AIR)
                    if abs(b) == H and (x, z) not in self.open_cells:
                        for yy in range(ylev, ylev + self.head + 1):
                            w.set(x, yy, z, WALL)
                    if (x, z) not in self.open_cells:
                        w.set(x, ylev + self.head + 1, z, STRUCT)
        if self.headhouse:
            self._head(w)

    def _head(self, w):
        """地面出入口亭：頂蓋 + 一面開門，否則梯頂是街上一個沒有蓋子的洞。"""
        H = self.half_w
        g = self.y_hi
        for a in range(self.run(), self.run() + 7):
            for b in range(-H - 1, H + 2):
                x, z = self._w(a, b)
                far = a == self.run() + 6
                side = abs(b) == H + 1 or far
                for yy in range(g, g + 4):
                    door = far and abs(b) <= 1 and yy <= g + 2
                    if side and not door:
                        w.set(x, yy, z, WALL)
                    else:
                        w.set(x, yy, z, AIR)
                w.set(x, g - 1, z, FLOOR)
                w.set(x, g + 4, z, CEIL)
        x, z = self._w(self.run() + 3, 0)
        w.set(x, g + 3, z, LAMP)
        if self.label:
            names = self.label if isinstance(self.label, (list, tuple)) else [self.label]
            sx, sz = self._w(self.run() + 5, 0)
            w.set(sx, g - 1, sz, FLOOR)
            if hasattr(w, "sign"):
                w.sign(sx, g, sz, ["／".join(str(t) for t in names[:2]),
                                   "台北地下街", "Taipei City Mall", "出口 Exit"],
                       facing=(self.dx, self.dz))


class ShaftStair:
    """折返式樓梯井：從某一層下到任意深度的另一層。

    原本放在 landmarks.py，因為地下街的連絡梯也要用而搬過來。
    給地下街用時 g0 傳 y_stand-1（地下街樓板）：井口平台的方塊剛好落在
    地下街樓板上、門開在地下街的淨空高度、頂蓋剛好是地下街的頂板 ——
    同一套幾何，換個 g0 就從「地面出入口」變成「層間連絡梯」。

    沿線的出入口長梯要 2 m 水平換 1 m 垂直，深 39 m 的站就得拉 78 m 直線 ——
    真實出入口離站體往往不到 40 m，硬拉會穿到別人家。折返梯把行程摺進一個
    固定大小的井裡，深度多少都塞得下，也比較接近真實深站的做法。

    座標系：(x0, z0) 是井的中心，u = (ux, uz) 是梯段延伸方向（單位向量，
    只支援四個正交方向），v 是其法向。
    """

    FLIGHT = 14          # 單一梯段的水平長度（公尺）-> 一段降 7 m
    HALF_W = 4           # 井的半寬（法向）

    def __init__(self, x0, z0, ux, uz, g0, y_to, bottom_door=False,
                 wall="minecraft:gray_concrete",
                 step="minecraft:smooth_stone",
                 slab="minecraft:smooth_stone_slab",
                 rail="minecraft:iron_bars",
                 lamp="minecraft:sea_lantern",
                 sign=None):
        self.x0, self.z0 = int(x0), int(z0)
        self.ux, self.uz = int(round(ux)), int(round(uz))
        self.g0, self.y_to = int(g0), int(y_to)
        self.bottom_door = bool(bottom_door)
        self.wall, self.step, self.slab = wall, step, slab
        self.rail, self.lamp = rail, lamp
        self.sign = list(sign) if sign else None    # 井口門邊的告示牌（最多四行）

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
        # 井口平台：門開在 a=-1，第一段梯從 a=1 起，中間的 a=0 原本沒鋪東西 ——
        # 門一開就是直通井底的洞（台北車站最深的一座落差 22 m）。玩家掉下去
        # 摔死，走路可達性也判定為不連通：樓梯明明蓋好了卻誰也走不進去。
        # 鋪成與門檻同高的門廳，再往下接第一階（梯頂踏面在 g0，剛好差一階）。
        for b in range(-H, H + 1):
            x, z = self._w(0, b)
            w.set(x, self.g0, z, self.step)
            for y in range(self.g0 + 1, self.g0 + 5):
                w.set(x, y, z, AIR)

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
        # 井底也要開門。當連絡梯用時井身四周是實心的，不開門的話整座井
        # 只有頂端那一個入口 —— 樓梯完整地蓋好了，卻誰也走不到穿堂層。
        # （原本這個類別只當地面出入口用，井底是靠外面另接一段 Passage 打通的。）
        if self.bottom_door:
            for b in range(-1, 2):
                x, z = self._w(-1, b)
                # 上限夾在 g0：井很淺時（機場線的穿堂只低 2 m）下方門洞會
                # 一路挖到 g0，把井口平台賴以站立的那一格挖掉 —— 於是從
                # 地下街走過去會直接掉下去，掉得下去爬不上來，等於不連通。
                for y in range(self.y_to, min(self.y_to + 3, self.g0)):
                    w.set(x, y, z, AIR)
        # 出口編號牌立在門外側，牌面朝著走過來的人。底下墊一塊，免得
        # 地形在那格剛好低一點，告示牌浮在半空中。
        if self.sign and hasattr(w, "sign"):
            x, z = self._w(-2, 2)
            w.set(x, self.g0, z, self.step)
            w.sign(x, self.g0 + 1, z, self.sign[:4], facing=(-self.ux, -self.uz))



# ---------- 計畫 ----------

def plan(ways, entrances, ground_at, y_stand, links=(), half_w=3,
         snap_tol=3.0, snap_radius=60.0, near=(0.0, 0.0), tile=TILE,
         no_wall=(), bridge=25.0, merge_m=12.0):
    """把 OSM 通道與出入口變成一串可以 build() 的物件。

    ways        [{"nodes": [...], "points": [[x, z], ...]}]，已投影成 MC 座標
    entrances   [(ref, x, z)]
    ground_at   f(x, z) -> 地面 y
    y_stand     地下街站立面 y
    links       [(x, z, 穿堂站立面 y, 名稱, ux, uz)]，往各線穿堂層的連絡梯
    no_wall     這些格子上不砌牆（例如 B1 大廳，本來就是開放空間）
    回傳 (objects, report)
    """
    pos, adj, edges = CC.build_graph(ways, tol=snap_tol)
    bridged = CC.bridge_gaps(pos, adj, edges, max_gap=bridge)
    group = CC.main_component(pos, adj, near=near)
    lines = CC.corridor_lines(pos, edges, group)
    connected, orphan = CC.snap_entrances(pos, group, entrances,
                                          radius=snap_radius)

    # ---- 1. 地板格：通道本身 + 出入口接駁段 + 連絡梯的接駁段 ----
    cells = set()
    for a, b in lines:
        cells |= stroke(a, b, half_w)

    # 出入口接駁段。台北地下街在 OSM 上是五條中心線，沿線的 Y9~Y20、Y22~Y28
    # 全部離線 9~42 m —— 橫向的聯絡通道根本沒畫。不補的話那些出入口接不上。
    for ref, ex, ez, n, d in connected:
        if d > 1.0:
            cells |= stroke((ex, ez), pos[n], max(2, half_w - 1))

    # 連絡梯：從各線穿堂層上到地下街。用折返式樓梯井，不用直梯 ——
    # 淡水信義線穿堂在 y44，直梯要 36 m 才爬得上來，而站體箱涵是照著彎曲的
    # 線形蓋的，直直拉出去 36 m 會在中途鑽出箱涵外，梯底就接不到穿堂層了
    # （實測 R 線正是如此）。折返梯把行程摺進 18x11 m 的井裡，深度多少都塞得下。
    #
    # g0 傳 y_stand-1：井口平台剛好落在地下街樓板上、門開在地下街的淨空裡、
    # 頂蓋剛好是地下街頂板。井身沿站體法向往外，避開月台樓梯（在中線 ±3 格）。
    # ---- 出入口樓梯先規劃（還不蓋）：連絡梯的井要避開它們 ----
    # 靠得很近的出入口共用一座樓梯。台北車站的北3門與台北地下街 Y8 相距
    # 只有 8 m，現實中本來就是同一個出入口的兩個名字；各蓋一座的話，
    # 後蓋的那座側牆會把前一座封死（實測北3門因此變成獨立的連通分量）。
    stair_plan, exits_flat, merged, taken = [], [], [], []
    stair_fp = set()
    for ref, ex, ez, n, d in sorted(connected, key=lambda e: e[4]):
        g = int(ground_at(ex, ez))
        if g - y_stand < 2:
            exits_flat.append((ref, ex, ez))
            continue
        near_t = next((t for t in taken
                       if math.hypot(t[1] - ex, t[2] - ez) <= merge_m), None)
        if near_t is not None:
            near_t[0].append(ref)
            merged.append((ref, ex, ez))
            continue
        refs = [ref]
        taken.append((refs, ex, ez))
        dx, dz = CC.outward(pos, adj, n, ex, ez)
        stair_plan.append((refs, ref, ex, ez, dx, dz, g))
        run = 2 * (g + 1 - y_stand)
        vx, vz = -dz, dx
        for a in range(-3, run + 8):
            for b in range(-4, 5):
                stair_fp.add((int(ex) + dx * a + vx * b, int(ez) + dz * a + vz * b))

    # 井擺在哪、朝哪邊，要挑：
    #  · 兩座連絡梯靠得近時（中山站的松山新店線與淡水信義線穿堂只差 14 m）
    #    井身會疊在一起，後蓋的那座把先蓋的樓梯挖成一個空洞 —— 從剖面看
    #    兩座井都在，走一遍才發現一座是空的
    #  · 井壓在通道上會把通道切成兩截：中山地下街就在淡水信義線正上方，
    #    井擺在站體中心正好橫在通道裡，比通道還寬，北段南段從此不相通。
    #    所以井可以沿站體法向往旁邊挪，挪到通道邊上，門再用接駁段接回來；
    #    井底的門仍在穿堂層裡（|離線位| <= 9）
    # 每個候選位置與方向算一個分數：壓到別座井、壓到通道、接駁段穿過別座井
    # 都扣分，挑最好的；挪得越少越好。
    from mrt.domain.exits import shaft_cells
    corridor = set(cells)
    link_objs = []
    taken_fp, taken_st = set(), set()
    for lk in links:
        lx, lz, ly, name = lk[0], lk[1], lk[2], lk[3]
        ux, uz = (lk[4], lk[5]) if len(lk) > 5 else (1.0, 0.0)
        if ly >= y_stand - 1 or not group:
            continue
        px, pz = -uz, ux                        # 站體法向
        cands = []
        for vx, vz in ((px, pz), (-px, -pz), (ux, uz), (-ux, -uz)):
            q = ((1 if vx > 0 else -1), 0) if abs(vx) >= abs(vz) \
                else (0, (1 if vz > 0 else -1))
            if q not in cands:
                cands.append(q)
        # 門沿站體往前挪 7 m：穿堂層往月台的兩座樓梯在樓板上開了洞，
        # 分別在站體中心的 -8..-1 m 與 +16..+23 m，門正對中心的話一出門
        # 就是往下五公尺的洞（中山站的松山新店線就是這樣從地下街走不到月台）。
        best = None
        for shift in (0, 8, -8, 9, -9):
            cx_ = lx + ux * 7 + px * shift
            cz_ = lz + uz * 7 + pz * shift
            for dx, dz in cands:
                x0, z0 = int(round(cx_)) + dx, int(round(cz_)) + dz
                fp = shaft_cells(x0, z0, dx, dz, margin=1)
                door = (x0 - dx, z0 - dz)
                # 出門先直走四格再轉向最近的節點。門只有三格寬，開在井壁那一排
                # 的正中央；接駁段若從門口斜著出去，刷寬會掃到門兩側的井壁，
                # 而井是在通道之後才蓋的，井壁一補回去，門前那一小段就被封死
                # —— 北門與雙連的連絡梯就是這樣走不進地下街的。
                porch = (door[0] - 4 * dx, door[1] - 4 * dz)
                near_n = min(group, key=lambda n: math.hypot(pos[n][0] - porch[0],
                                                             pos[n][1] - porch[1]))
                st = (stroke(door, porch, max(2, half_w - 1))
                      | stroke(porch, pos[near_n], max(2, half_w - 1)))
                bad = (10 * (len(fp & taken_fp) + len(st & taken_fp) + len(fp & taken_st)
                             + len(fp & stair_fp))
                       + len(fp & corridor) + abs(shift))
                if best is None or bad < best[0]:
                    best = (bad, dx, dz, x0, z0, door, near_n, fp, st)
        _, dx, dz, x0, z0, door, near_n, fp, st = best
        well = ShaftStair(x0, z0, dx, dz, y_stand - 1, ly, bottom_door=True)
        well.label = name
        link_objs.append(well)
        taken_fp |= fp
        taken_st |= st
        # 井口的門開在 a=-1，也就是站體中心那一格。把它接回通道網。
        cells |= st

    # ---- 2. 頂板高度 ----
    # 隨地形，但絕不高過地表。地表太低的地方（中山地下街北段一帶地面只有
    # y64）寧可讓頂板直接當成路面 —— 現實中那一段上面就是線形公園，頂板
    # 本來就是鋪面。淨空最少留 2 格；站立面已經高過地面才真的放棄那一格。
    ceil_of, thin, shallow = {}, set(), 0
    for c in cells:
        g = int(ground_at(c[0], c[1]))
        if g <= y_stand + 1:
            thin.add(c)
            continue
        cy = min(y_stand + HEAD, g - 1)
        if cy - y_stand < 2:
            cy = y_stand + 2
            shallow += 1
        ceil_of[c] = cy
    cells -= thin

    # ---- 3. 切塊 ----
    # no_wall 是本來就開放的空間（B1 大廳）。通道穿過去時不能砌牆，
    # 否則等於在大廳裡蓋一條走廊把大廳切成兩半。
    ring = outer_ring(cells) - set(no_wall)
    objs, buckets = [], {}
    for c in cells:
        buckets.setdefault((c[0] // tile, c[1] // tile), [set(), set()])[0].add(c)
    for c in ring:
        buckets.setdefault((c[0] // tile, c[1] // tile), [set(), set()])[1].add(c)
    for key in sorted(buckets):
        cs, rs = buckets[key]
        objs.append(Tile(cs, rs, y_stand, ceil_of))

    # ---- 4. 出入口樓梯（一定要排在地板之後，才挖得開自己的洞）----
    # 位置與方向在上面決定好了；這裡只是照著蓋。
    exits_built = []
    for refs, ref, ex, ez, dx, dz, g in stair_plan:
        # g 是地表方塊，人站在上面腳在 g+1；梯頂要爬到 g+1，出入口亭的
        # 地坪才與街面齊平。原本停在 g，出門要跳一格、進門掉一格。
        objs.append(Stair(ex, ez, dx, dz, y_stand, g + 1, half_w=2,
                          label=refs, headhouse=True, open_cells=cells))
        exits_built.append((ref, ex, ez))
    objs += link_objs

    report = dict(nodes=len(pos), group=len(group), lines=len(lines),
                  bridged=len(bridged), length=round(CC.total_length(lines)),
                  cells=len(cells), ring=len(ring), tiles=len(buckets),
                  links=[(o.label, o.x0, o.z0, o.y_to, o.g0)
                         for o in link_objs],
                  # ref 在不同車站會重複（台北車站與北門都有 1、2、3 號
                  # 出入口），所以報表一律帶座標，否則會把別站的出入口
                  # 誤判成已接上。
                  connected=[(e[0], e[1], e[2]) for e in connected],
                  orphan=[(r, x, z) for r, x, z in orphan],
                  exits=exits_built, exits_flat=exits_flat,
                  merged=merged,
                  thin=len(thin), shallow=shallow)
    return objs, report
