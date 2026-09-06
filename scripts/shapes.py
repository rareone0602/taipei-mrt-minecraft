#!/usr/bin/env python3
"""建築幾何工具：多邊形填充、外牆描邊、四坡屋頂。

車站站體是沿著路線的斷面掃出來的，但地面上的站屋不是 —— 它是一個
從 OSM 拿到的任意多邊形，得自己光柵化。這裡只做純幾何，不碰世界寫入，
所以可以單獨跑自我測試。

自我測試: ./.venv/bin/python scripts/shapes.py
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


def _test():
    ok = True
    def chk(name, cond):
        nonlocal ok
        print(("  ok   " if cond else "  FAIL ") + name)
        ok = ok and cond

    print("多邊形填充")
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    c = poly_cells(sq)
    chk(f"10x10 方形面積 100 -> {len(c)} 格", len(c) == 100)
    chk("左下角在內、右上角外側不在內", (0, 0) in c and (9, 9) in c and (10, 10) not in c)
    chk("外側不在內", (10, 5) not in c and (-1, 5) not in c)

    tri = [(0, 0), (10, 0), (0, 10)]
    t = poly_cells(tri)
    chk(f"直角三角形面積 50 -> {len(t)} 格", 44 <= len(t) <= 56)
    chk("斜邊外不在內", (9, 9) not in t)

    print("外圈與內縮")
    r = ring_cells(c)
    chk(f"10x10 外圈 36 格 -> {len(r)}", len(r) == 36)
    chk(f"內縮 1 -> 8x8 = 64 格 -> {len(inset(c,1))}", len(inset(c, 1)) == 64)
    chk(f"內縮 4 剩中央 2x2 -> {len(inset(c,4))}", len(inset(c, 4)) == 4)
    chk("內縮 5 全空", inset(c, 5) == set())
    chk("內縮到空集合不炸", inset(c, 99) == set())

    print("四坡屋頂")
    d = depth_map(c)
    chk(f"中心距離最大 = 5 -> {d[(5,5)]}", d[(5, 5)] == 5)
    chk("角落距離 = 1", d[(0, 0)] == 1)
    rf = hip_roof(c, 100, slope=0.5)
    chk(f"簷口 100，中心頂 {rf[(5,5)][1]}", rf[(5, 5)][1] == 102)
    chk("簷口那圈不抬高", rf[(0, 0)][1] == 100)
    rf2 = hip_roof(c, 100, slope=0.5, max_rise=1)
    chk("max_rise 有效", rf2[(5, 5)][1] == 101)

    print("重心與矩形")
    cx, cz = centroid(sq)
    chk(f"方形重心 ({cx:.1f},{cz:.1f})", abs(cx - 5) < 1e-6 and abs(cz - 5) < 1e-6)
    rr = rect(0, 0, 10, 4)
    chk(f"未旋轉矩形 bbox {bbox(rr)}", bbox(rr) == (-5.0, -2.0, 5.0, 2.0))
    rr90 = rect(0, 0, 10, 4, math.pi / 2)
    bb = bbox(rr90)
    chk("轉 90 度後長寬互換",
        abs(bb[2] - bb[0] - 4) < 1e-6 and abs(bb[3] - bb[1] - 10) < 1e-6)
    chk(f"未旋轉 20x10 面積 200 -> {len(poly_cells(rect(0,0,20,10)))} 格",
        len(poly_cells(rect(0, 0, 20, 10))) == 200)
    n = len(poly_cells(rect(0, 0, 20, 10, math.pi / 6)))
    chk(f"轉 30 度後面積仍約 200 -> {n} 格", 180 <= n <= 220)

    print("退化輸入")
    chk("兩點回空集合", poly_cells([(0, 0), (1, 1)]) == set())
    chk("零面積重心不炸", centroid([(0, 0), (1, 1), (2, 2)]) is not None)

    print("\n全部通過" if ok else "\n有失敗")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_test())
