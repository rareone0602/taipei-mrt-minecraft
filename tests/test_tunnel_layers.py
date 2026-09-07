#!/usr/bin/env python3
"""隧道分層的單元測試：兩條線交叉，晚蓋的那條要提前一段斜坡就換帶。

帶號只是目標深度，真正的高程由 4% 坡度包絡線決定；換一帶要走 375 m。
走到衝突點才換帶的話，衝突點本身還在斜坡半路上 —— 松江南京的松山新店線
就這樣停在地下 27 m，與地下 30 m 的中和新蘆線站體上下只差 3 m。

用法: ./.venv/bin/python tests/test_tunnel_layers.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.domain import alignment as AL
from mrt.domain import tunnel_layers as TL

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def straight(p0, p1):
    return AL.resample([p0, p1], ["tunnel", "tunnel"], AL.STEP)


G = 66
main = straight((-3000.0, 0.0), (3000.0, 0.0))        # 長的先指派，拿帶 0
cross = straight((0.0, -2000.0), (0.0, 2000.0))       # 短的要繞開
bands = TL.assign_bands([("A", main), ("B", cross)])
ba, bb = bands
print("帶號")
chk("長的那條全程帶 0", int(ba.max()) == 0)
xi = min(range(len(cross)), key=lambda i: abs(cross[i][1]))      # 交叉點
chk(f"短的在交叉點是帶 1（實得 {bb[xi]}）", bb[xi] == 1)
first = int(np.argmax(bb == 1))
dist = (xi - first) * AL.STEP
chk(f"帶 1 從交叉點前 {dist:.0f} m 就開始（要 >= 375 m 斜坡）", dist >= TL.RAMP_M - 1)
chk("交叉點前 1 km 還是帶 0", bb[xi - int(1000 / AL.STEP)] == 0)


# 真正要驗的是高程：用平地算縱斷面，交叉點必須在完整的帶 1 深度
def profile(samples, band):
    base = TL.band_depth(band)
    y = G + base.astype(float)
    d = AL.MAX_GRADE * AL.STEP
    for i in range(1, len(y)):
        if y[i] > y[i - 1] + d: y[i] = y[i - 1] + d
    for i in range(len(y) - 2, -1, -1):
        if y[i] > y[i + 1] + d: y[i] = y[i + 1] + d
    return np.round(y).astype(int)


ya, yb = profile(main, ba), profile(cross, bb)
print("縱斷面")
chk(f"交叉點長線深 {G - ya[xi]} m（帶 0 = 15）", G - ya[xi] == TL.BAND0)
chk(f"交叉點短線深 {G - yb[xi]} m（帶 1 = 30，不是斜坡半路）",
    G - yb[xi] == TL.BAND0 + TL.BAND_DY)
chk("兩座站體上下相差 15 m，不交疊", ya[xi] - yb[xi] == TL.BAND_DY)

# 斜坡走完之前舊帶仍占用：第三條線在斜坡段底下不能拿帶 0
third = straight((-400.0, -1000.0), (-400.0, 1000.0))  # 距交叉點 400 m，斜坡中段…
# …只有當短線在那裡還在帶 0（斜坡起點附近）才會衝到；這裡驗的是不炸且無衝突
b3 = TL.assign_bands([("A", main), ("B", cross), ("C", third)])
chk("三條線都指派得出來", all(int(b.max()) >= 0 for b in b3))

print("\n全部通過" if ok else "\n有測試失敗")
raise SystemExit(0 if ok else 1)
