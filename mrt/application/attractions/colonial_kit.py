#!/usr/bin/env python3
"""日治時期洋風建築的共用零件：總統府、國立臺灣博物館、西門紅樓都用得上。

kit.py 給的是遮罩與高度場；這三座建築要的是「立面」—— 紅磚牆上一條條白色飾帶、
一個開間一扇拱窗、轉角的隅石、門廊的柱子與山牆。這裡把它們寫成：

  fit_angle   OSM 外環 -> 讓局部外接矩形面積最小的角度。kit.principal_angle 取整數度，
              總統府 130 m 長的立面差 0.4° 就歪將近 1 m，這裡取到 0.1°
  to_local    世界座標的點 -> 局部 (u, v)（不加半格，給 OSM 的頂點用）
  Mason       在 Frame 上砌東西（寫入一律經過呼叫端給的 w，也就是 Guard）：
                facade()  遮罩外圈砌 layers 層牆，每格交給 pattern(面, 沿牆座標, 高度, 層)
                          決定材質 —— 窗是外層挖空、內層玻璃，1:1 的牆才看得出深度
                roof()    高度場屋頂：整數格放全方塊、半格放半磚、陡坡的邊放樓梯
                column()  方柱：柱礎、柱身、柱頭
                gable()   三角形山牆（門廊的山花、紅樓入口）
                dome()    圓頂殼（臺博館、總統府的衛塔）
  stair()     樓梯的方塊狀態字串（facing 是「高的那一側」朝哪個方位）

這裡不含任何一座建築的尺寸；尺寸與出處寫在各自的模組裡。
"""
import math

import numpy as np

from mrt.application.attractions.kit import AIR, Painter, erode

OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}


def fit_angle(poly, step=0.1):
    """外環（世界座標）-> u 軸的角度（弧度，落在 -45°～45°）：局部外接矩形面積最小。"""
    pts = np.asarray(poly, dtype=float)
    pts = pts - pts.mean(axis=0)
    best, best_a = None, 0.0
    n = int(round(45.0 / step))
    for k in range(-n, n):
        a = math.radians(k * step)
        c, s = math.cos(a), math.sin(a)
        u = pts[:, 0] * c + pts[:, 1] * s
        v = -pts[:, 0] * s + pts[:, 1] * c
        area = (u.max() - u.min()) * (v.max() - v.min())
        if best is None or area < best - 1e-9:
            best, best_a = area, a
    return best_a


def to_local(fr, x, z):
    """世界座標的「點」-> 局部 (u, v)。Frame.local 是給格子用的（加半格），OSM 頂點用這個。"""
    dx, dz = x - fr.cx, z - fr.cz
    return dx * fr.c + dz * fr.s, -dx * fr.s + dz * fr.c


def local_extent(fr, poly):
    """多邊形在局部座標的範圍 (u0, u1, v0, v1)。"""
    L = [to_local(fr, x, z) for x, z in poly]
    us = [p[0] for p in L]
    vs = [p[1] for p in L]
    return min(us), max(us), min(vs), max(vs)


def convex_corners(pts, min_turn=60.0):
    """多邊形（局部座標）的凸角：轉角大於 min_turn 度、往外凸的頂點。
    弧線（半圓門廊、八角形以外的圓）上的頂點每個只轉十幾度，不算角。"""
    n = len(pts)
    if n < 3:
        return []
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    sgn = 1.0 if area > 0 else -1.0
    out = []
    for i in range(n):
        ax, az = pts[i - 1]
        bx, bz = pts[i]
        cx, cz = pts[(i + 1) % n]
        d1 = (bx - ax, bz - az)
        d2 = (cx - bx, cz - bz)
        if math.hypot(*d1) < 1e-6 or math.hypot(*d2) < 1e-6:
            continue
        cross = d1[0] * d2[1] - d1[1] * d2[0]
        dot = d1[0] * d2[0] + d1[1] * d2[1]
        turn = math.degrees(math.atan2(abs(cross), dot))
        if turn >= min_turn and cross * sgn > 0:
            out.append((bx, bz))
    return out


def centroid(poly):
    xs = [p[0] for p in poly]
    zs = [p[1] for p in poly]
    return sum(xs) / len(xs), sum(zs) / len(zs)


def stair(name, facing, half="bottom", shape="straight"):
    """minecraft:<name>_stairs 的狀態字串。facing 是樓梯高的那一側（往那個方向走是上樓）。"""
    return "minecraft:%s[facing=%s,half=%s,shape=%s,waterlogged=false]" % (name, facing, half, shape)


def slab(name, kind="bottom"):
    return "minecraft:%s[type=%s,waterlogged=false]" % (name, kind)


def shift(m, dz, dx):
    """遮罩平移：out[i, j] = m[i + dz, j + dx]（出界當 False）。"""
    out = np.zeros_like(m)
    h, w = m.shape
    i0, i1 = max(0, -dz), min(h, h - dz)
    j0, j1 = max(0, -dx), min(w, w - dx)
    if i0 < i1 and j0 < j1:
        out[i0:i1, j0:j1] = m[i0 + dz:i1 + dz, j0 + dx:j1 + dx]
    return out


class Mason:
    """在 Frame 上砌牆、屋頂、柱子。w 是（已包了 Guard 的）BlockSink。"""

    def __init__(self, w, fr):
        self.w, self.fr = w, fr
        self.p = Painter(w, fr)
        self._face_cache = {}

    # ---- 基本 ----
    def set(self, x, y, z, block):
        self.w.set(int(x), int(y), int(z), block)

    def at(self, u, v, y, block):
        x, z = self.fr.cell(u, v)
        self.w.set(x, int(y), z, block)

    def fill(self, mask, y0, y1, block):
        self.p.fill(mask, y0, y1, block)

    def facing(self, du, dv):
        """局部方向 -> 正方位（有快取：一面牆幾千格都問同一個方向）。"""
        k = (du, dv)
        f = self._face_cache.get(k)
        if f is None:
            f = self._face_cache[k] = self.fr.facing(du, dv)
        return f

    @staticmethod
    def along(face):
        """面的法線 (nu, nv) -> 沿牆的「正方向」(du, dv)：法線沿 u 的牆，沿牆座標是 v。"""
        return (0, 1) if face[0] else (1, 0)

    # ---- 立面 ----
    def ring_cells(self, mask):
        """遮罩外圈每格：(x, z, u, v, 面的法線 (nu, nv), 沿牆座標 t)。

        法線看四鄰哪幾側在遮罩外，合成世界方向再轉回局部，取最接近的那一軸。
        Frame 轉了角度時外圈是鋸齒狀的，每一格的法線仍然是那面牆的朝向。"""
        m = mask
        ex = m & ~shift(m, 0, 1)             # 東鄰（x+1）在外面
        wx = m & ~shift(m, 0, -1)
        sz = m & ~shift(m, 1, 0)             # 南鄰（z+1）
        nz = m & ~shift(m, -1, 0)
        edge = ex | wx | sz | nz
        dx = ex.astype(np.int8) - wx.astype(np.int8)
        dz = sz.astype(np.int8) - nz.astype(np.int8)
        ii, jj = np.nonzero(edge)
        fr = self.fr
        out = []
        for i, j in zip(ii.tolist(), jj.tolist()):
            wx_, wz_ = float(dx[i, j]), float(dz[i, j])
            if wx_ == 0 and wz_ == 0:            # 一格寬的牆兩側都在外：隨便挑一側
                wx_ = 1.0 if ex[i, j] else 0.0
                wz_ = 0.0 if ex[i, j] else 1.0
            du = wx_ * fr.c + wz_ * fr.s
            dv = -wx_ * fr.s + wz_ * fr.c
            if abs(du) >= abs(dv):
                face = (1 if du > 0 else -1, 0)
                t = float(fr.V[i, j])
            else:
                face = (0, 1 if dv > 0 else -1)
                t = float(fr.U[i, j])
            out.append((int(fr.X[i, j]), int(fr.Z[i, j]), float(fr.U[i, j]), float(fr.V[i, j]), face, t))
        return out

    @staticmethod
    def _ngon_cell(cell, ngon):
        """外圈的一格改用正 n 邊形的面來分：面 = 法線最接近的那條邊的編號 k，
        沿牆座標 t = 從那條邊的中點量起（逆著 u→v 的方向為負）。"""
        x, z, u, v, _, _ = cell
        n, rot, du, dv = ngon
        uu, vv = u - du, v - dv
        best, bk = None, 0
        for k in range(n):
            ph = rot + 2 * math.pi * k / n
            d = uu * math.cos(ph) + vv * math.sin(ph)
            if best is None or d > best:
                best, bk = d, k
        ph = rot + 2 * math.pi * bk / n
        t = -uu * math.sin(ph) + vv * math.cos(ph)
        return (x, z, u, v, bk, t)

    def facade(self, mask, y0, y1, pattern, base=0, layers=2, corners=None, ngon=None):
        """遮罩外圈砌牆 y0..y1（含）。第 k 層是遮罩往內縮 k 格之後的外圈。

        pattern(face, t, h, layer, u, v, q) -> 方塊字串或 None（None = 不寫，留給別人）；
        h = y - base（通常 base 給一樓地面，pattern 就只管「離地幾公尺」）。
        face 平常是法線 (nu, nv)（±u 或 ±v）；給 ngon=(n, rot, du, dv) 就改成正 n 邊形的
        面編號 k（法線角度 rot + k·360°/n），t 從那一面的中點量起 —— 八角樓的斜面才分得出來。
        corners 給一串局部座標的凸角（convex_corners 算的），q 就是這一格離最近凸角的
        切比雪夫距離（隅石用）；沒給就是 None。"""
        cur = mask
        C = np.asarray(corners, dtype=float) if corners else None
        for k in range(layers):
            if k:
                cur = erode(cur)
            cells = self.ring_cells(cur)
            if ngon is not None:
                cells = [self._ngon_cell(c, ngon) for c in cells]
            if C is not None and len(cells):
                P = np.array([(c[2], c[3]) for c in cells])
                Q = np.min(np.maximum(np.abs(P[:, None, 0] - C[None, :, 0]),
                                      np.abs(P[:, None, 1] - C[None, :, 1])), axis=1).tolist()
            else:
                Q = [None] * len(cells)
            for (x, z, u, v, face, t), q in zip(cells, Q):
                for y in range(int(y0), int(y1) + 1):
                    b = pattern(face, t, y - base, k, u, v, q)
                    if b is not None:
                        self.w.set(x, y, z, b)

    # ---- 屋頂 ----
    def roof(self, mask, base, h, full, slab_name=None, stair_name=None, shell=2, under=None):
        """高度場屋頂：每格從 base + h 往下疊 shell 格。

        小數 >= 0.5 的地方頂上加半磚（slab_name）；給 stair_name 就在「旁邊有矮一格的鄰居」
        的格子頂上放樓梯（高的一側朝上坡），45° 的坡面才不會一格一格地跳。"""
        fr = self.fr
        H = np.asarray(h, dtype=float) * np.ones(fr.shape)
        B = np.broadcast_to(np.asarray(base), fr.shape)
        top = np.where(mask, B + H, -9999.0)
        ti = np.floor(top).astype(int)
        frac = top - ti
        # 四鄰的頂（遮罩外當成無限低）：上坡 = 最高的鄰居那一側，旁邊有矮一格的才放樓梯
        dirs = ((0, 1, "east"), (0, -1, "west"), (1, 0, "south"), (-1, 0, "north"))
        nbs = [np.where(shift(mask, dz, dx), shift(top, dz, dx), -9999.0) for dz, dx, _ in dirs]
        nb_max = np.max(nbs, axis=0)
        up = np.argmax(nbs, axis=0)
        lower = np.zeros(fr.shape, dtype=bool)
        for nb in nbs:
            lower |= np.floor(nb) < ti
        ii, jj = np.nonzero(mask)
        s = self.w.set
        for i, j in zip(ii.tolist(), jj.tolist()):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            b, t = int(round(B[i, j])), int(ti[i, j])
            lo = max(b, t - shell + 1)
            for y in range(lo, t + 1):
                s(x, y, z, full)
            if under is not None and lo - 1 >= b:
                s(x, lo - 1, z, under)
            if slab_name is not None and frac[i, j] >= 0.5:
                s(x, t + 1, z, slab(slab_name))
            elif stair_name is not None and lower[i, j] and nb_max[i, j] > top[i, j] + 0.25:
                s(x, t, z, stair(stair_name, dirs[int(up[i, j])][2]))

    # ---- 柱子、山牆、圓頂 ----
    def column(self, u, v, y0, y1, shaft, base=None, capital=None, size=1.0):
        """方柱：中心 (u, v)、邊長 size（公尺）。柱礎一格、柱頭一格（給了才放）。
        格心落在邊上時只算一側（半開區間），邊長 1 的柱子就是一格、2 就是兩格。"""
        fr = self.fr
        r = size / 2.0
        cx, cz = fr.world(u, v)
        R = int(math.ceil(r + 1.5))
        for x in range(int(math.floor(cx)) - R, int(math.floor(cx)) + R + 1):
            for z in range(int(math.floor(cz)) - R, int(math.floor(cz)) + R + 1):
                du, dv = fr.local(x, z)
                if -r <= du - u < r and -r <= dv - v < r:
                    for y in range(int(y0), int(y1) + 1):
                        b = shaft
                        if base is not None and y == y0:
                            b = base
                        elif capital is not None and y == y1:
                            b = capital
                        self.w.set(x, y, z, b)

    def gable(self, u0, u1, v0, v1, y, rise, fill, edge=None, axis="u"):
        """三角形山牆：沿 axis 從 u0 到 u1、厚度 v0..v1（另一軸）、底邊在 y、中央高 rise。
        axis="v" 時兩組參數對調意義：沿 v 從 u0 到 u1、厚度是 u 的 v0..v1。

        edge 給樓梯名稱就沿兩條斜邊放樓梯（高的一側朝中央），山牆頂才是斜的；
        正中央那一格改放全方塊加半磚當屋脊。"""
        fr = self.fr
        if axis == "u":
            A, D = fr.U, fr.V
        else:
            A, D = fr.V, fr.U
        mid, half = (u0 + u1) / 2.0, (u1 - u0) / 2.0
        m = (A >= u0) & (A <= u1) & (D >= v0) & (D <= v1)
        h = rise * (1.0 - np.abs(A - mid) / half)
        ii, jj = np.nonzero(m)
        for i, j in zip(ii.tolist(), jj.tolist()):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            hh = float(h[i, j])
            top = int(math.floor(hh + 0.25))
            for yy in range(int(y), int(y) + top):
                self.w.set(x, yy, z, fill)
            if edge is not None:
                a = float(A[i, j])
                toward = (1, 0) if a < mid else (-1, 0)
                if axis != "u":
                    toward = (toward[1], toward[0])
                if abs(a - mid) < 0.75:
                    self.w.set(x, int(y) + top, z, fill)
                    self.w.set(x, int(y) + top + 1, z, slab(edge.replace("_stairs", "_slab")))
                else:
                    self.w.set(x, int(y) + top, z, stair(edge, self.facing(*toward)))

    def dome(self, du, dv, r, y, rise, block, shell=2, slab_name=None, rib=None, ribs=0, profile=0.5):
        """圓頂殼：中心 (du, dv)、底圓半徑 r、底在 y、高 rise。profile=0.5 是半球（橢球），
        < 0.5 比較扁、> 0.5 比較尖。ribs > 0 就在那麼多條經線上換成 rib 的材質（圓頂的肋）。"""
        fr = self.fr
        d = np.hypot(fr.U - du, fr.V - dv)
        m = d <= r
        h = rise * np.clip(1.0 - (d / r) ** 2, 0, 1) ** profile
        top = y + h
        ii, jj = np.nonzero(m)
        ang = np.arctan2(fr.V - dv, fr.U - du)
        for i, j in zip(ii.tolist(), jj.tolist()):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            t = float(top[i, j])
            ti = int(math.floor(t))
            b = block
            if ribs and rib is not None:
                k = (float(ang[i, j]) / (2 * math.pi / ribs)) % 1.0
                if min(k, 1 - k) * (2 * math.pi / ribs) * float(d[i, j]) < 0.55 and float(d[i, j]) > 0.8:
                    b = rib
            for yy in range(max(int(y), ti - shell + 1), ti + 1):
                self.w.set(x, yy, z, b)
            if slab_name is not None and t - ti >= 0.5:
                self.w.set(x, ti + 1, z, slab(slab_name))

    def clear_box(self, mask, y0, y1):
        self.p.fill(mask, y0, y1, AIR)
