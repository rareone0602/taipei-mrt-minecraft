#!/usr/bin/env python3
"""線形的單元測試。

這些原本測不了 —— 線形算式和「把方塊放進世界」綁在同一支 build_line.py 裡，
要驗證縱斷面就得先產生一個存檔。拆到 domain 之後純函式進純函式出，
不必碰 Minecraft。

用法: ./.venv/bin/python tests/test_alignment.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.domain import alignment as AL

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def line(n, step=1.0):
    return [(i * step, 0.0) for i in range(n)]


print("取樣")
pts = line(11, 10.0)                       # 100 m 直線
s = AL.resample(pts, ["ground"] * 11, AL.STEP)
chk(f"100 m / step {AL.STEP} -> {len(s)} 點", abs(len(s) - 200) <= 2)
d = [math.dist(s[i][:2], s[i + 1][:2]) for i in range(len(s) - 1)]
chk(f"間距一致 (max {max(d):.3f}, min {min(d):.3f})",
    max(d) - min(d) < 1e-6 and abs(max(d) - AL.STEP) < 1e-6)
chk("方向向量為單位向量",
    all(abs(math.hypot(p[2], p[3]) - 1) < 1e-9 for p in s))
chk("沿 +X 前進 -> ux=1", abs(s[len(s) // 2][2] - 1.0) < 1e-6)

print("縱斷面")
ys = AL.vertical_profile(["ground"] * 400)
chk("全平面 -> 地面 +1", set(ys) == {AL.GROUND + AL.PROFILE["ground"]})

# 高架段要夠長：從 y77 降到 y44 是 33 m，4% 坡度需要 825 m 引道，
# 短於這個長度整段都會被下包絡線拉下去（這正是設計行為）。
SEG = int(1500 / AL.STEP)        # 每段 1500 m
kinds = ["bridge"] * SEG + ["tunnel"] * SEG + ["bridge"] * SEG
ys = AL.vertical_profile(kinds)
# 坡度要在一段距離上量。ys 已四捨五入成整數，逐點相鄰差最小就是 1 格 /
# 0.5 m = 200%，那是取整的假象，不是真的坡度。
W = int(100 / AL.STEP)           # 100 m 視窗
grades = [abs(ys[i + W] - ys[i]) / 100.0 for i in range(len(ys) - W)]
chk(f"100 m 視窗最大坡度 {max(grades):.4f} <= {AL.MAX_GRADE}",
    max(grades) <= AL.MAX_GRADE + 0.001)
chk("隧道段真的降到地面以下", min(ys) < AL.GROUND)
chk(f"高架段抬到 y={max(ys)} = 地面{AL.PROFILE['bridge']:+d}",
    max(ys) == AL.GROUND + AL.PROFILE["bridge"])
mid = len(ys) // 2
chk(f"隧道中央 y={ys[mid]} = 地面{AL.PROFILE['tunnel']:+d}",
    ys[mid] == AL.GROUND + AL.PROFILE["tunnel"])
# 洞口前後應該是連續下降的引道，不是垂直斷崖
step_down = max(abs(ys[i + 1] - ys[i]) for i in range(len(ys) - 1))
chk(f"相鄰取樣點最大高差 {step_down} 格（不是斷崖）", step_down <= 1)

print("結構型態依高程而非標籤")
chk("軌面高於地面 6 -> 高架", AL.structure_for_ground(AL.GROUND + 6, AL.GROUND) == "viaduct")
chk("軌面貼近地面 -> 平面", AL.structure_for_ground(AL.GROUND + 1, AL.GROUND) == "surface")
chk("軌面低於地面 2 -> 隧道", AL.structure_for_ground(AL.GROUND - 2, AL.GROUND) == "tunnel")
chk("掛 bridge 標籤但已降到地下 -> 仍算隧道",
    AL.structure_for_ground(AL.GROUND - 10, AL.GROUND) == "tunnel")

print("軌道離線位")
n = 600
samples = [(i * AL.STEP, 0.0, 1.0, 0.0, "tunnel") for i in range(n)]
ys = [AL.GROUND - 20] * n
toff = AL.track_offsets(samples, ys, [AL.GROUND] * n, [n // 2])
chk(f"站中心張開到 ±{AL.STN_TRACK_OFF}", toff[n // 2] == AL.STN_TRACK_OFF)
chk(f"區間維持 ±{AL.TUN_TRACK_OFF}", toff[0] == AL.TUN_TRACK_OFF)
chk("過渡是單調的（沒有跳階）",
    all(toff[i] >= toff[i - 1] - 1e-9 for i in range(1, n // 2)))
jump = max(abs(toff[i + 1] - toff[i]) for i in range(n - 1))
chk(f"相鄰點離線位最大變化 {jump:.3f} m（軌道不會斷）", jump < 0.2)

chk("半寬 = 離線位 + 2", AL.half_width(8) == 10)
chk("半寬有下限 5", AL.half_width(1) == 5)

print("原地折返")
pts = [(0, 0), (100, 0), (200, 0), (150, 0)]     # 走到底再折回 50 m
out, _ = AL.drop_reversal(pts, ["ground"] * 4)
chk(f"折返段被砍掉 ({len(pts)} -> {len(out)} 點)", len(out) < len(pts))
chk("留下的是較長的那一半", out[-1][0] == 200)
straight = line(5, 50.0)
out, _ = AL.drop_reversal(straight, ["ground"] * 5)
chk("直線不會被誤砍", len(out) == len(straight))

print("路線變體")
up = {"points": [[i * 10.0, 0.0] for i in range(60)]}
down = {"points": [[i * 10.0, 3.0] for i in reversed(range(60))]}   # 反向的同一條
# 支線要從幹線中段垂直岔出去，長度也不同 —— 若沿著幹線方向直直延伸且長度相同，
# _same_corridor 的端點配對（容差 600 m）會把它誤判成上下行。
branch = {"points": [[300.0, i * 10.0] for i in range(100)]}
sel = AL.select_variants([up, down])
chk(f"上下行收斂成一條（2 -> {len(sel)}）", len(sel) == 1)
sel = AL.select_variants([up, down, branch])
chk(f"支線保留（3 -> {len(sel)}）", len(sel) == 2)

print("退化輸入")
chk("單點取樣不炸", AL.resample([(0.0, 0.0)], ["ground"], AL.STEP) == [])
chk("空縱斷面不炸", AL.vertical_profile([]) == [])
chk("沒有變體回空清單", AL.select_variants([]) == [])

print("\n全部通過" if ok else "\n有測試失敗")
raise SystemExit(0 if ok else 1)
