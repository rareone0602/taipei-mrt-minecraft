#!/usr/bin/env python3
"""建築幾何工具：多邊形填充、外牆描邊、四坡屋頂。

車站站體是沿著路線的斷面掃出來的，但地面上的站屋不是 —— 它是一個
從 OSM 拿到的任意多邊形，得自己光柵化。這裡只做純幾何，不碰世界寫入，
所以可以單獨跑自我測試。

自我測試: ./.venv/bin/python -m mrt.domain.geometry
"""
import math


def poly_cells(poly):
    """多邊形內部的整數格 (x, z)。掃描線 + 奇偶規則。

    判定的是**格心**（xc+0.5, zc+0.5）在不在多邊形內，不是格角。
    這樣格數才等於面積（(0,0)-(10,10) 的方形剛好 100 格），
    共用邊的相鄰多邊形也不會重複填到同一格。
    """
    if len(poly) < 3:
        return set()
    zs = [p[1] for p in poly]
    out = set()
    for zc in range(int(math.floor(min(zs))), int(math.ceil(max(zs))) + 1):
        zy = zc + 0.5
        xs = []
        for i in range(len(poly)):
            x0, z0 = poly[i]
            x1, z1 = poly[(i + 1) % len(poly)]
            if z0 == z1:
                continue
            lo, hi = (z0, z1) if z0 < z1 else (z1, z0)
            if lo <= zy < hi:
                xs.append(x0 + (zy - z0) * (x1 - x0) / (z1 - z0))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            a, b = xs[i], xs[i + 1]
            for xc in range(int(math.ceil(a - 0.5)), int(math.floor(b - 0.5)) + 1):
                if a <= xc + 0.5 < b:
                    out.add((xc, zc))
    return out


def ring_cells(cells):
    """填充區的最外圈 —— 四鄰有一格不在集合內就算外牆。"""
    return {(x, z) for x, z in cells
            if not all((x + dx, z + dz) in cells
                       for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)))}


def inset(cells, n=1):
    """把填充區往內縮 n 格（連續剝掉 n 層外圈）。"""
    cur = set(cells)
    for _ in range(n):
        cur -= ring_cells(cur)
    return cur


def depth_map(cells):
    """每一格到邊界的曼哈頓距離（外圈 = 1）。多來源 BFS。

    四坡屋頂就是拿這個當高度：離邊越遠越高，脊線自然出現在最裡面，
    對任意形狀的平面圖都成立，不必假設是矩形。
    """
    from collections import deque
    d = {}
    q = deque()
    for c in ring_cells(cells):
        d[c] = 1
        q.append(c)
    while q:
        x, z = q.popleft()
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, z + dz)
            if n in cells and n not in d:
                d[n] = d[(x, z)] + 1
                q.append(n)
    return d


def hip_roof(cells, y0, slope=0.5, max_rise=None):
    """四坡（廡殿）屋頂 -> {(x, z): (y_底, y_頂)}。

    y0 是簷口高度。每格從簷口疊到 y0 + round(dist * slope)，
    夾在 max_rise 以內；封頂那格另外回傳，呼叫端可以換成脊瓦。
    """
    d = depth_map(cells)
    out = {}
    for c, dist in d.items():
        rise = (dist - 1) * slope
        if max_rise is not None:
            rise = min(rise, max_rise)
        out[c] = (y0, y0 + int(round(rise)))
    return out


def centroid(poly):
    a = cx = cz = 0.0
    for i in range(len(poly)):
        x0, z0 = poly[i]
        x1, z1 = poly[(i + 1) % len(poly)]
        cr = x0 * z1 - x1 * z0
        a += cr; cx += (x0 + x1) * cr; cz += (z0 + z1) * cr
    if abs(a) < 1e-9:
        n = len(poly)
        return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
    a *= 0.5
    return (cx / (6 * a), cz / (6 * a))


def bbox(poly):
    xs = [p[0] for p in poly]; zs = [p[1] for p in poly]
    return min(xs), min(zs), max(xs), max(zs)


def rect(cx, cz, w, h, rot=0.0):
    """中心 (cx,cz)、寬 w 深 h、逆時針轉 rot 弧度的矩形頂點。"""
    c, s = math.cos(rot), math.sin(rot)
    out = []
    for dx, dz in ((-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)):
        out.append((cx + dx * c - dz * s, cz + dx * s + dz * c))
    return out
