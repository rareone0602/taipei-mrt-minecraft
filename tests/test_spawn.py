#!/usr/bin/env python3
"""出生點的單元測試：出入口亭的門口在哪、怎麼挑、朝哪邊。

door_front() 是照 Stair._head 的尺寸算的，兩邊各寫一次數字很容易對不上，
所以直接把亭子蓋進 DictSink，看門口那一格外面真的是門洞、裡面真的是亭。

用法: ./.venv/bin/python tests/test_spawn.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application import spawn as SP
from mrt.application.build_concourse import Stair
from mrt.domain import walk
from mrt.infrastructure.mcworld import yaw_of
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and bool(cond)


class Signs(DictSink):
    def sign(self, x, y, z, lines, facing=(0, 1), wood="oak"):
        self.set(x, y, z, f"minecraft:{wood}_sign")
        self.signs[(x, y, z)] = list(lines)


def kiosk(x0, z0, dx, dz, g=66, label=("M4",)):
    """地下街站立面 y62、街面 g 的出入口樓梯 + 亭。"""
    return Stair(x0, z0, dx, dz, 62, g + 1, half_w=2, label=list(label), headhouse=True)


print("門口那一格（四個方向）")
for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
    st = kiosk(0, 0, dx, dz)
    w = Signs()
    st.build(w)
    g = w.blocks.get
    x, z, y, (fx, fz) = st.door_front()
    tag = f"u=({dx},{dz})"
    chk(f"{tag} 朝向是 -u", (fx, fz) == (-dx, -dz))
    chk(f"{tag} 站立面是亭的地坪 y_hi={st.y_hi}", y == st.y_hi)
    chk(f"{tag} 門口那一格亭子沒蓋到", all((x, yy, z) not in w.blocks for yy in range(y - 1, y + 6)))
    door = [g((x + fx, yy, z + fz)) for yy in (y, y + 1, y + 2)]
    chk(f"{tag} 正前方是三格高的門洞", all(b is not None and walk.is_passable(b) for b in door))
    chk(f"{tag} 門洞兩側是牆",
        all(not walk.is_passable(g((x + fx - fz * s * 2, y, z + fz + fx * s * 2)) or "minecraft:air")
            for s in (-1, 1)))
    chk(f"{tag} 門洞上面是牆（亭高三格）", not walk.is_passable(g((x + fx, y + 3, z + fz)) or "minecraft:air"))
    inside = (x + 2 * fx, y, z + 2 * fz)
    chk(f"{tag} 進門一格就是出口牌", inside in w.signs and "出口 Exit" in w.signs[inside])
    chk(f"{tag} 亭的地坪在 y{y - 1}", g((x + fx, y - 1, z + fz)) is not None)

print("朝向換成 yaw（0 = 南、90 = 西、±180 = 北、-90 = 東）")
chk("朝西 (-1,0) -> 90", abs(yaw_of(-1, 0) - 90) < 1e-9)
chk("朝東 (1,0) -> -90", abs(yaw_of(1, 0) + 90) < 1e-9)
chk("朝南 (0,1) -> 0", abs(yaw_of(0, 1)) < 1e-9)
chk("朝北 (0,-1) -> ±180", abs(abs(yaw_of(0, -1)) - 180) < 1e-9)

print("怎麼挑")
stations = [(["A1"], "台北車站", -317, -271, "", "A1"),
            (["R10", "BL12"], "台北車站", 0, 0, "", "R10;BL12")]
chk("站點取線別最多的那一個（R10;BL12，不是機場線）", SP.station_node(stations) == (0, 0))
near = kiosk(-9, -25, 1, 0, label=("M4",))            # 門口 (8,-25)
far = kiosk(32, -6, 0, 1, label=("M3",))              # 門口 (32,11)
mall = kiosk(0, 5, 1, 0, label=("K2",))               # 地下街的出口，不算
flat = lambda x, z: 66                                # 地形一律 y66：門檻與街面齊平
r = SP.plan_spawn([far, near, mall], stations, flat)
chk(f"挑離站點最近的 M 出口：{r and r['refs']}", r is not None and r["refs"] == ["M4"])
chk(f"出生點 = 門口那一格 ({r['x']},{r['y']},{r['z']})",
    (r["x"], r["y"], r["z"]) == (8, 67, -25) and r["facing"] == (-1, 0))
bump = lambda x, z: 67 if (x, z) == (8, -25) else 66
r2 = SP.plan_spawn([far, near, mall], stations, bump)
chk("門口地面比亭的地坪高一格就不挑（要齊平）", r2 is not None and r2["refs"] == ["M3"])


class Roof:
    """一塊蓋在地面上的東西（別座亭、站體大樓……），只需要 bbox。"""
    underground = False

    def bbox(self):
        return 6, -27, 10, -23


r3 = SP.plan_spawn([far, near, mall, Roof()], stations, flat)
chk("門口落在別的地面建物範圍裡就不挑", r3 is not None and r3["refs"] == ["M3"])
r4 = SP.plan_spawn([mall], stations, flat)
chk("一座 M 出口都沒有就回 None（cli 會退回站點上方的地面）", r4 is None)
chk("門口在海平面以下（腳下是水）不挑",
    SP.plan_spawn([near], stations, lambda x, z: 60) is None)

print("\n全部通過" if ok else "\n有失敗")
sys.exit(0 if ok else 1)
