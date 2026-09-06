#!/usr/bin/env python3
"""幾何工具的單元測試：多邊形填充、外圈、內縮、四坡屋頂。

用法: ./.venv/bin/python tests/test_geometry.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.domain import geometry
from mrt.domain.geometry import *  # noqa: F403  測試沿用原本的裸名呼叫

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
