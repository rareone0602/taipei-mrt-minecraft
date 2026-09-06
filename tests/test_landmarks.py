#!/usr/bin/env python3
"""地標建築的單元測試：擠出、樓板、屋頂、退化輸入。

用法: ./.venv/bin/python tests/test_landmarks.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application.landmarks import *  # noqa: F403
from mrt.domain import geometry as shapes
from mrt.ports.block_sink import DictSink

# ---------- 自我測試 ----------

# 原本這裡自己帶一個 _FakeWorld；現在用 ports 的 DictSink，
# 生成器收的就是同一個介面。
def _test():
    ok = True
    def chk(name, cond):
        nonlocal ok
        print(("  ok   " if cond else "  FAIL ") + name)
        ok = ok and cond

    print("Building")
    poly = shapes.rect(0, 0, 40, 30)
    b = Building(poly, g0=70, storeys=3, storey_h=5, name="測試")
    w = DictSink()
    b.build(w)
    ys = [y for _, y, _ in w.blocks]
    chk(f"寫出 {len(w.blocks):,} 個方塊", len(w.blocks) > 1000)
    chk(f"最低 y={min(ys)} = 地面-3", min(ys) == 67)
    chk(f"頂層樓板 y={b.top_y()}", b.top_y() == 85)
    chk(f"屋脊 y={max(ys)} 高於頂層樓板", max(ys) > b.top_y())
    peak_rise = max(ys) - b.top_y()
    chk(f"屋脊起伏 {peak_rise} m，約為 min(40,30)/2*slope",
        3 <= peak_rise <= 12)

    # 內部應該是空的（可以走人）
    mid = w.blocks.get((0, 72, 0))
    chk(f"1 樓室內 (0,72,0) = {mid}", mid == AIR)
    corner = w.blocks.get((-20, 72, -15))
    chk(f"外牆角 (-20,72,-15) = {corner}", corner not in (None, AIR))

    # 樓板是實的
    chk("2 樓樓板實心", w.blocks.get((0, 75, 0)) not in (None, AIR))

    bb = b.bbox()
    chk(f"bbox {bb} 涵蓋多邊形", bb[0] <= -20 and bb[2] >= 20)

    print("Slab")
    s = Slab(shapes.rect(0, 0, 20, 20), y=50, clear=4,
             wall="minecraft:gray_concrete")
    w2 = DictSink()
    s.build(w2)
    chk(f"寫出 {len(w2.blocks):,} 個方塊", len(w2.blocks) > 500)
    chk("樓板實心", w2.blocks.get((0, 50, 0)) not in (None, AIR))
    chk("淨空是空氣", w2.blocks.get((0, 52, 0)) == AIR)
    chk("頂板實心", w2.blocks.get((0, 55, 0)) not in (None, AIR))
    chk("周牆封閉", w2.blocks.get((-10, 52, 0)) == "minecraft:gray_concrete")

    print("退化輸入")
    w3 = DictSink()
    Building([(0, 0), (1, 1)], g0=70).build(w3)
    chk("兩點多邊形不炸且不寫東西", len(w3.blocks) == 0)

    print("\n全部通過" if ok else "\n有失敗")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_test())
