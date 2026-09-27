#!/usr/bin/env python3
"""美麗華摩天輪：大直美麗華百樂園屋頂上的摩天輪（2004）。

公開的事實（只取數字與形制，文字與圖片都沒有抄進來）：
  · 輪徑 70 m、總高 100 m；基座架在建築物屋頂（5 樓，30 m 高）—— 維基百科「美麗華摩天輪」
  · 48 個車廂（編號 1–52，跳過 4、13、14、44），其中 2 個透明車廂、2 個無障礙車廂；
    每廂 6 人、繞一圈約 17 分鐘；日本泉陽興業製造、總重約 600 公噸 —— 同上
  · 美麗華百樂園：地上 9 層、地下 3 層，2004 年 11 月開幕；IMAX 影廳在 6–9 樓
    —— 維基百科「美麗華百樂園」
  · 長相（Wikimedia Commons 的照片：Miramar Ferris Wheel, Taipei, 2024、
    Miramar Entertainment Park 20090905、West Side of Miramar Entertainment Park）：
    白色鋼構輪圈、密密的鋼索輻條、兩側各一座 A 字形支腳；車廂掛在輪圈外，
    顏色一圈漸層（頂上紅、左邊橙黃、底下綠、右邊藍）；商場是米色石材外牆、
    每層一道褐色橫紋、淡綠色的斜屋頂，西側是一道從北往南升高的楔形山牆

位置：摩天輪中心照 OSM node/5121602758（attraction=big_wheel、height=100），
商場照 way/155816458 的輪廓。輪面的方向：從北邊山上往南拍的照片裡，輪子是正圓、
台北101 正好在輪軸後方 —— 輪軸大致南北向、輪面東西向，跟商場的長邊（東西向）一致，
所以輪面沿商場南緣的方向擺。

垂直分配（從地面 g0 起算）：屋頂甲板 30（5 樓頂，上下車的月台）、輪軸 67；
車廂的樞軸在半徑 33 m 的圓上、車廂高 4 m 往下掛 —— 最低的車廂底 31、
最高的車廂頂 100，上下一共 70 m，跟公開的「輪徑 70 m、總高 100 m」對得起來。
輪圈半徑 28.3 m，車廂在輪圈外（照片上頂端的車廂在輪圈上方）。

商場是簡化的量體（不是逐層重建）：
  · 整個輪廓：外牆米色、每 5 m 一道褐色橫紋，一樓一圈店面玻璃與淡綠雨庇
  · 摩天輪周圍（輪軸東西 34 m、南緣往北 34 m）：5 樓頂 30 m 的甲板；輪子的南側支腳
    落在 OSM 輪廓外 3～4 m，甲板往南多蓋一小塊（上下車月台）把支腳接住
  · 東北：9 層的 IMAX 大樓 48 m，東牆上一圈圓形標誌、西牆一道大拱窗
  · 西翼：楔形屋頂，北端 16 m 往南升到 36 m，南端再斜下來；西牆一道紅色大拱門
  · 其餘：波浪形的淡綠屋頂 19～26 m
觀景點在輪子正南方 90 m 的街上（面向輪面），另一個在最頂上的車廂裡。
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions.kit import AIR, Attraction, Frame, Painter, Spot, dilate, erode, ring

# ---- 材質 ----
STONE_WALL = "minecraft:white_terracotta"           # 米色石材外牆
STRIPE = "minecraft:terracotta"                     # 褐色橫紋
SHOP_GLASS = "minecraft:light_blue_stained_glass"   # 一樓店面
GLASS = "minecraft:light_gray_stained_glass"
GLASS_ARCH = "minecraft:light_blue_stained_glass"   # IMAX 大樓的大拱窗
COPPER = "minecraft:waxed_weathered_cut_copper"     # 淡綠色金屬屋頂（上蠟，不會再繼續氧化）
COPPER_SLAB = "minecraft:waxed_weathered_cut_copper_slab[type=bottom]"
DECK = "minecraft:smooth_stone"
FLOOR = "minecraft:polished_andesite"
ARCH = "minecraft:red_concrete"
ARCH_GLASS = "minecraft:orange_stained_glass"
PAVE = "minecraft:smooth_stone"
EMBLEM = "minecraft:white_concrete"

RIM = "minecraft:white_concrete"                    # 輪圈
RING2 = "minecraft:red_terracotta"                  # 輪圈外那一圈細的暗紅色圈
STEEL = "minecraft:iron_block"                      # 輪軸、支腳、車廂吊臂
AXLE = "minecraft:light_gray_concrete"
SPOKE = "minecraft:iron_bars"                       # 鋼索輻條（沒有連接狀態就是一根細柱）
COLOURS = ("red", "orange", "yellow", "lime", "green", "cyan", "light_blue", "blue")
CLEAR = ("minecraft:white_stained_glass", "minecraft:glass")   # 透明車廂

# ---- 摩天輪（公尺 = 格）----
DECK_Y = 30          # 5 樓頂（上下車月台）
HUB = 67             # 輪軸
RP = 33.0            # 車廂樞軸的半徑
GH = 4               # 車廂高（地板、兩層窗、頂）
RIM_IN, RIM_OUT = 27.6, 29.0
RIM_W = 2.0          # 前後兩道輪圈在輪軸方向 ±2 m
HUB_R, HUB_W, AXLE_W = 3.5, 4.5, 6.5
N_GONDOLA = 48
N_SPOKE = 32         # 每一面的輻條數（前後兩面錯開半格，正面看是 64 根）
RINGS = (10.0, 19.0) # 內圈
LEG_U, LEG_W, LEG_R = 16.0, 5.5, 1.1
TIE_Y = 44           # 支腳之間的橫撐
TRANSPARENT = (8, 32)    # 兩個透明車廂（十點鐘、四點鐘方向）
VIEW_M = 90.0        # 觀景點在輪子南邊多遠：退到這裡，商場一樓到輪頂都框得進畫面


def axis_angle(poly):
    """輪廓主要的方向（弧度，折到 ±45°）：邊長加權的平均方向。
    principal_angle 取整數度，這裡要的是摩天輪輪面的準確方向。"""
    sx = sy = 0.0
    for i in range(len(poly)):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % len(poly)]
        L = math.hypot(x2 - x1, z2 - z1)
        a = math.atan2(z2 - z1, x2 - x1) * 4          # 四倍角：互相垂直的邊落在同一個方向
        sx += L * math.cos(a)
        sy += L * math.sin(a)
    return math.atan2(sy, sx) / 4


def _seg_dist(U, Y, W, p0, p1):
    """每格到三維線段 p0-p1 的距離（U, Y, W 是同形陣列）。"""
    d = np.array(p1, dtype=float) - np.array(p0, dtype=float)
    L2 = float((d * d).sum()) or 1.0
    t = (((U - p0[0]) * d[0] + (Y - p0[1]) * d[1] + (W - p0[2]) * d[2]) / L2).clip(0, 1)
    return np.sqrt((U - p0[0] - t * d[0]) ** 2 + (Y - p0[1] - t * d[1]) ** 2 + (W - p0[2] - t * d[2]) ** 2)


def gondola_colour(k):
    """第 k 個車廂（k=0 在頂上，往左、逆時針數）的顏色：頂紅、左橙黃、底綠、右藍。"""
    if k in TRANSPARENT:
        return CLEAR
    c = COLOURS[int(k * len(COLOURS) / N_GONDOLA) % len(COLOURS)]
    return ("minecraft:%s_wool" % c, "minecraft:%s_stained_glass" % c)


class MiramarWheel(Attraction):
    height_m = 100.0
    margin = 12
    MALL = "way/155816458"

    def __init__(self, item):
        super().__init__(item)
        node = next((f for f in self.features if f.get("main") and f.get("point")), None)
        self.hub_xz = tuple(node["point"]) if node else tuple(self.center())
        f = self.feature(self.MALL)
        self.mall = max(f["outer"], key=len) if f and f.get("outer") else None
        ang = axis_angle(self.mall) if self.mall else 0.0
        self.angle = ang
        c, s = math.cos(ang), math.sin(ang)
        # 觀景點：輪子南邊（+v）VIEW_M 公尺的街上
        self.view_xz = (self.hub_xz[0] - VIEW_M * s, self.hub_xz[1] + VIEW_M * c)

    def outline(self):
        return self.mall or super().outline()

    def bbox(self):
        x0, z0, x1, z1 = super().bbox()
        vx, vz = self.view_xz
        return (min(x0, int(vx) - 8), min(z0, int(vz) - 8), max(x1, int(vx) + 8), max(z1, int(vz) + 8))

    # ---------------------------------------------------------------- 規劃
    def plan(self, site):
        hx, hz = self.hub_xz
        ang = self.angle
        if self.mall:
            xs = [p[0] for p in self.mall]
            zs = [p[1] for p in self.mall]
            mx, mz = sum(xs) / len(xs), sum(zs) / len(zs)
            ext = max(max(xs) - min(xs), max(zs) - min(zs)) / 2 + 20
        else:
            mx, mz, ext = hx, hz - 40, 90
        self.fr = fr = Frame(mx, mz, ang, ext)
        self.mask = fr.polygon(self.mall) if self.mall else fr.box(70, 50, *fr.local(int(hx), int(hz) - 45))
        self.g0 = site.level(fr, self.mask)
        self.wf = Frame(hx, hz, ang, 40)                  # 摩天輪自己的座標：u 沿輪面、v 沿輪軸
        self._zones()
        # build() 裡整地要查地面；cli 在 plan_all 之後就把地形距離場丟掉了，
        # 所以要在這裡先把會用到的格子查一遍（Site 會快取），build 時才查得到
        site.grid(self.fr, self.mask)
        self.site = site
        g0 = self.g0
        # 預設觀景點：南邊街上，看輪子中段
        vx, vz = (int(math.floor(c)) for c in self.view_xz)
        vy = site.g(vx, vz) + 1
        self.view_ground = vy - 1
        yaw, pitch = kit.look(vx, vy, vz, hx, g0 + HUB - 8, hz)
        # 頂上：最高那個車廂裡面
        top = self._gondolas()[0]
        gx, gy, gz = top["cell"][0], top["y_top"] - 2, top["cell"][1]
        self._spots = [
            Spot("", vx, vy, vz, yaw, pitch, self.name_zh, self.name_en),
            Spot("top", gx, gy, gz, round(self.wf.yaw(0, 1), 1), 15.0, "摩天輪頂端車廂", "Top gondola"),
        ]

    def _zones(self):
        """商場量體：每格的屋頂高度（相對 g0）與屋頂材質。"""
        fr, m = self.fr, self.mask
        U, V = fr.U, fr.V
        hu, hv = fr.local(int(math.floor(self.hub_xz[0])), int(math.floor(self.hub_xz[1])))
        um = U[m]
        vm = V[m]
        u0, u1, v0, v1 = float(um.min()), float(um.max()), float(vm.min()), float(vm.max())
        H = np.zeros(fr.shape)
        roof = np.zeros(fr.shape, dtype=np.int8)          # 0 平頂、1 銅皮斜頂
        H[m] = 20
        west = m & (U < hu - 40)                          # 西翼：楔形屋頂
        north = m & (V < v0 + 50)
        tower = north & (U > hu + 12)                     # 東北 IMAX 大樓
        deck = m & ~west & ~tower & (np.abs(U - hu) <= 34) & (V >= v1 - 34)   # 摩天輪底下的 5 樓甲板
        # 上下車月台：輪子的支腳落在輪廓外，甲板往南多蓋一塊
        wu, wv = self.wf.U, self.wf.V
        st = self._on(self.wf, (np.abs(wu) <= LEG_U + 3) & (wv >= -LEG_W - 3) & (wv <= LEG_W + 2))
        deck |= st
        self.mask = m = m | st
        wave = m & ~west & ~tower & ~deck                 # 其餘：波浪形的淡綠屋頂
        vs = v1 - 10                                      # 楔形的屋脊在南端往北 10 m
        t = ((V - v0) / max(1.0, vs - v0)).clip(0, 1)
        wedge = np.where(V <= vs, 16 + 20 * t, 36 - 6 * ((V - vs) / 10.0).clip(0, 1))
        H[west] = wedge[west]
        roof[west] = 1
        H[tower] = 48
        H[deck] = DECK_Y
        H[wave] = (22 + 3 * np.sin(2 * math.pi * (U - u0) / 24.0) + 1.5 * np.cos(2 * math.pi * (V - v0) / 30.0))[wave]
        roof[wave] = 1
        self.H, self.roof = H, roof
        self.parts = dict(west=west, tower=tower, deck=deck, wave=wave)
        self.u_west, self.v_south = u0, v1

    def _on(self, other, mask2):
        """另一個 Frame 上的遮罩 -> 商場 Frame 上的遮罩（同一批世界格子）。"""
        out = self.fr.empty()
        fr = self.fr
        for x, z in other.cells(mask2):
            i, j = z - fr.z0, x - fr.x0
            if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1]:
                out[i, j] = True
        return out

    def _gondolas(self):
        """48 個車廂：樞軸的位置、落在哪一格、車廂頂的 y、顏色。k=0 在正上方，逆時針（往西）數。"""
        wf, hub = self.wf, self.g0 + HUB
        out = []
        for k in range(N_GONDOLA):
            th = math.pi / 2 + 2 * math.pi * k / N_GONDOLA
            pu = RP * math.cos(th)                        # 從南邊看逆時針：k=1 在頂上偏西（-u）
            py = RP * math.sin(th)
            out.append(dict(k=k, th=th, cell=wf.cell(pu, 0.0), y_top=hub + int(round(py)),
                            colour=gondola_colour(k), pu=pu))
        return out

    # ---------------------------------------------------------------- 蓋
    def build(self, w):
        p = Painter(w, self.fr)
        self._mall(p, w)
        self._station(w)
        self._wheel(w)
        self._view(w)

    # ---- 商場 ----
    def _mall(self, p, w):
        fr, g0, m, H = self.fr, self.g0, self.mask, self.H
        Hi = np.rint(H).astype(int)
        self.site.prepare(w, fr, m, g0, top=FLOOR, clear=4)
        inner = erode(m, 1)
        for y in range(6, 48, 6):                         # 樓板（每 6 m 一層，到各自的屋頂下）
            p.layer(inner & (Hi > y + 1), g0 + y, FLOOR)
        # 各區的外牆：自己的外圈從地面疊到自己的屋頂下；褐色橫紋每 5 m 一道
        X, Z = fr.X, fr.Z
        s = w.set
        outer_ring = ring(m)
        for part in self.parts.values():
            rg = ring(part) | (part & outer_ring)
            for i, j in zip(*np.nonzero(rg)):
                x, z, top = int(X[i, j]), int(Z[i, j]), int(Hi[i, j])
                for y in range(1, top):
                    blk = STRIPE if y % 5 == 0 else STONE_WALL
                    s(x, g0 + y, z, blk)
        # 一樓店面：外圈 1～4 m 開玻璃，5 m 一圈淡綠雨庇伸出 2 m
        shop = outer_ring & ((fr.X + fr.Z) % 7 != 0)
        p.fill(shop, g0 + 1, g0 + 4, SHOP_GLASS)
        canopy = dilate(m, 2) & ~m
        p.layer(canopy, g0 + 5, COPPER_SLAB)
        # 屋頂：平頂鋪面加女兒牆，斜頂與波浪頂是淡綠金屬
        flat = m & (self.roof == 0)
        p.fill(flat, g0 + Hi, g0 + Hi, DECK)
        for part in ("tower",):
            pr = self.parts[part]
            p.fill(ring(pr), g0 + Hi + 1, g0 + Hi + 1, STONE_WALL)
        slope = m & (self.roof == 1)
        p.heightfield(slope, g0, H, COPPER, shell=2)
        p.heightfield(slope, g0, H, COPPER, shell=1, slab=COPPER_SLAB)
        # 西牆的紅色大拱門（南端屋脊底下）
        U, V = fr.U, fr.V
        wr = ring(m) & (U < self.u_west + 1.5)
        vc = self.v_south - 22
        for i, j in zip(*np.nonzero(wr & (np.abs(V - vc) <= 9))):
            dv = float(V[i, j] - vc)
            x, z = int(X[i, j]), int(Z[i, j])
            for y in range(1, 17):
                r = math.hypot(dv, max(0.0, y - 8.0))
                if r <= 7.0:
                    s(x, g0 + y, z, ARCH_GLASS)
                elif r <= 8.8:
                    s(x, g0 + y, z, ARCH)
        # IMAX 大樓西牆的大拱窗（照片上從西北邊看得到的那一面）
        tw = self.parts["tower"]
        wr2 = ring(tw) & (U < U[tw].min() + 1.5)
        if wr2.any():
            vc3 = float(V[wr2].mean())
            for i, j in zip(*np.nonzero(wr2 & (np.abs(V - vc3) <= 9))):
                dv = float(V[i, j] - vc3)
                x, z = int(X[i, j]), int(Z[i, j])
                for y in range(24, 46):
                    r = math.hypot(dv, max(0.0, y - 37.0))
                    if r <= 7.0:
                        s(x, g0 + y, z, GLASS_ARCH)
                    elif r <= 8.5:
                        s(x, g0 + y, z, EMBLEM)
        # IMAX 大樓東牆的圓形標誌
        er = ring(tw) & (U > U[tw].max() - 1.5)
        if er.any():
            vc2 = float(V[er].mean())
            for i, j in zip(*np.nonzero(er)):
                x, z = int(X[i, j]), int(Z[i, j])
                for y in range(20, 46):
                    r = math.hypot(float(V[i, j]) - vc2, y - 34.0)
                    if 8.0 <= r <= 9.2:
                        s(x, g0 + y, z, EMBLEM)
        # 招牌
        sx, sz = fr.cell(self.u_west - 1.0, vc - 11)
        fx, fz = _vec(fr.facing(-1, 0))
        w.sign(sx, g0 + 3, sz, ["美麗華百樂園", "Miramar", "Entertainment Park", ""],
               facing=(fx, fz), wood="birch", kind="wall", glow=True, color="red")

    # ---- 上下車月台 ----
    def _station(self, w):
        wf, g0 = self.wf, self.g0
        p = Painter(w, wf)
        y = g0 + DECK_Y
        plat = wf.rect(-LEG_U - 3, LEG_U + 3, -LEG_W - 3, LEG_W + 2)
        p.layer(plat, y, DECK)
        for sg in (1, -1):
            roof = wf.rect(-9, 9, 3 if sg > 0 else -7.5, 7 if sg > 0 else -3)
            p.layer(roof, y + 5, COPPER_SLAB)
            for cu in (-8.5, 8.5):
                for cv in ((3.5, 6.5) if sg > 0 else (-7, -3.5)):
                    x, z = wf.cell(cu, cv)
                    for yy in range(y + 1, y + 5):
                        w.set(x, yy, z, STEEL)

    # ---- 摩天輪 ----
    def _wheel(self, w):
        wf, hub = self.wf, self.g0 + HUB
        U, W = wf.U, wf.V
        X, Z = wf.X, wf.Z
        near = np.abs(W) <= 12
        s = w.set
        step = 2 * math.pi / N_SPOKE
        gstep = 2 * math.pi / N_GONDOLA
        base_y = self.g0 + DECK_Y
        legs = []
        for su in (1, -1):
            for sw in (1, -1):
                legs.append(((0.0, 0.0, sw * LEG_W), (su * LEG_U, base_y - hub, sw * LEG_W)))
        ty = self.g0 + TIE_Y - hub
        tie_u = LEG_U * (ty - 0) / (base_y - hub)
        ties = [((-tie_u, ty, sw * LEG_W), (tie_u, ty, sw * LEG_W)) for sw in (1, -1)]
        for y in range(base_y, hub + int(RIM_OUT) + 3):
            dy = float(y - hub)
            R = np.hypot(U, dy)
            TH = np.arctan2(dy, U)
            aw = np.abs(W)
            blk = np.full(U.shape, "", dtype=object)
            # 支腳與橫撐
            for (p0, p1), rad in [(l, LEG_R) for l in legs] + [(t, 0.7) for t in ties]:
                blk[near & (_seg_dist(U, dy, W, p0, p1) <= rad)] = STEEL
            # 輻條：前後兩面，從輪軸（±4.5）斜到輪圈（±2）
            for f, off in ((1, 0.0), (-1, step / 2)):
                ws = f * (HUB_W - (HUB_W - RIM_W) * ((R - HUB_R) / (RIM_IN - HUB_R)).clip(0, 1))
                dth = (TH - off + step / 2) % step - step / 2
                lat = R * np.abs(np.sin(dth))
                on_face = np.abs(W - ws) <= 0.6
                blk[near & on_face & (R >= HUB_R) & (R <= RIM_IN + 0.2) & (lat <= 0.5)] = SPOKE
                for rr in RINGS:
                    blk[near & on_face & (np.abs(R - rr) <= 0.5)] = RIM
            # 輪圈（前後兩道）、外圈的細紅圈、車廂位置的橫樑與吊臂
            blk[(R >= RIM_IN) & (R <= RIM_OUT) & (np.abs(aw - RIM_W) <= 0.55)] = RIM
            blk[(R > RIM_OUT) & (R <= RIM_OUT + 1.0) & (aw <= 0.55)] = RING2
            gd = (TH - math.pi / 2 + gstep / 2) % gstep - gstep / 2
            glat = R * np.abs(np.sin(gd))
            blk[(glat <= 0.5) & (R >= RIM_IN) & (R <= RIM_OUT) & (aw <= RIM_W + 0.5)] = RIM
            blk[(glat <= 0.5) & (R > RIM_OUT) & (R <= RP + 0.3) & (np.abs(aw - RIM_W) <= 0.55)] = STEEL
            # 輪軸
            blk[(R <= HUB_R) & (aw <= HUB_W)] = STEEL
            blk[(R <= 1.6) & (aw <= AXLE_W)] = AXLE
            for i, j in zip(*np.nonzero(blk != "")):
                s(int(X[i, j]), y, int(Z[i, j]), blk[i, j])
        # 車廂：掛在樞軸下，3 × 3 × 4（地板、兩層窗、頂），中間那一格是空的
        eu = _vec(kit.cardinal(*wf.dir(1, 0)))
        ev = _vec(kit.cardinal(*wf.dir(0, 1)))
        for g in self._gondolas():
            (gx, gz), yt = g["cell"], g["y_top"]
            solid, glass = g["colour"]
            for a in (-1, 0, 1):
                for b in (-1, 0, 1):
                    x, z = gx + a * eu[0] + b * ev[0], gz + a * eu[1] + b * ev[1]
                    s(x, yt, z, solid)
                    s(x, yt - GH + 1, z, solid)
                    for yy in range(yt - GH + 2, yt):
                        s(x, yy, z, AIR if (a, b) == (0, 0) else glass)

    # ---- 觀景點腳下的一小塊人行鋪面 ----
    def _view(self, w):
        vx, vz = (int(math.floor(c)) for c in self.view_xz)
        gy = self.view_ground
        for dx in range(-4, 5):
            for dz in range(-4, 5):
                w.set(vx + dx, gy, vz + dz, PAVE)
                for yy in range(gy + 1, gy + 4):
                    w.set(vx + dx, yy, vz + dz, AIR)

    # ---------------------------------------------------------------- 說明牌
    def plaque(self):
        return [self.name_zh, self.name_en, "2004 年啟用 頂高 100 m", "輪徑 70 m 48 個車廂"]


def _vec(name):
    return {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}[name]


BUILDS = {"miramar_wheel": MiramarWheel}
