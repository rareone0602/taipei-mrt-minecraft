#!/usr/bin/env python3
"""Unit tests of the spawn point: where an exit kiosk's door is, how the kiosk is chosen, which way the player faces.

door_front() is computed from the dimensions in Stair._head. Numbers written in
two places easily drift apart, so the kiosk is built into a DictSink and the
test checks that the cell outside is really a door opening and the inside really
a kiosk.

Usage: ./.venv/bin/python tests/test_spawn.py
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
    """An exit stair and kiosk from an underground mall standing surface at y62 to a street at g."""
    return Stair(x0, z0, dx, dz, 62, g + 1, half_w=2, label=list(label), headhouse=True)


print("The cell outside the door (four directions)")
for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
    st = kiosk(0, 0, dx, dz)
    w = Signs()
    st.build(w)
    g = w.blocks.get
    x, z, y, (fx, fz) = st.door_front()
    tag = f"u=({dx},{dz})"
    chk(f"{tag} faces -u", (fx, fz) == (-dx, -dz))
    chk(f"{tag} standing surface is the kiosk floor, y_hi={st.y_hi}", y == st.y_hi)
    chk(f"{tag} the kiosk leaves the cell outside the door untouched", all((x, yy, z) not in w.blocks for yy in range(y - 1, y + 6)))
    door = [g((x + fx, yy, z + fz)) for yy in (y, y + 1, y + 2)]
    chk(f"{tag} straight ahead is a three-block-high door opening", all(b is not None and walk.is_passable(b) for b in door))
    chk(f"{tag} walls on both sides of the door opening",
        all(not walk.is_passable(g((x + fx - fz * s * 2, y, z + fz + fx * s * 2)) or "minecraft:air")
            for s in (-1, 1)))
    chk(f"{tag} wall above the door opening (the kiosk is three blocks high)", not walk.is_passable(g((x + fx, y + 3, z + fz)) or "minecraft:air"))
    inside = (x + 2 * fx, y, z + 2 * fz)
    chk(f"{tag} the exit sign is one cell inside the door", inside in w.signs and "出口 Exit" in w.signs[inside])
    chk(f"{tag} the kiosk floor is at y{y - 1}", g((x + fx, y - 1, z + fz)) is not None)

print("Facing as yaw (0 = south, 90 = west, ±180 = north, -90 = east)")
chk("West (-1,0) -> 90", abs(yaw_of(-1, 0) - 90) < 1e-9)
chk("East (1,0) -> -90", abs(yaw_of(1, 0) + 90) < 1e-9)
chk("South (0,1) -> 0", abs(yaw_of(0, 1)) < 1e-9)
chk("North (0,-1) -> ±180", abs(abs(yaw_of(0, -1)) - 180) < 1e-9)

print("How the kiosk is chosen")
stations = [(["A1"], "台北車站", -317, -271, "", "A1"),
            (["R10", "BL12"], "台北車站", 0, 0, "", "R10;BL12")]
chk("The station node is the one with the most lines (R10;BL12, not the Airport MRT)", SP.station_node(stations) == (0, 0))
near = kiosk(-9, -25, 1, 0, label=("M4",))            # Door at (8,-25).
far = kiosk(32, -6, 0, 1, label=("M3",))              # Door at (32,11).
mall = kiosk(0, 5, 1, 0, label=("K2",))               # An underground mall exit, which does not count.
flat = lambda x, z: 66                                # Terrain at y66 everywhere: the threshold is flush with the street.
r = SP.plan_spawn([far, near, mall], stations, flat)
chk(f"The M exit nearest the station node is chosen: {r and r['refs']}", r is not None and r["refs"] == ["M4"])
chk(f"Spawn point = the cell outside the door ({r['x']},{r['y']},{r['z']})",
    (r["x"], r["y"], r["z"]) == (8, 67, -25) and r["facing"] == (-1, 0))
bump = lambda x, z: 67 if (x, z) == (8, -25) else 66
r2 = SP.plan_spawn([far, near, mall], stations, bump)
chk("A door whose ground is one block above the kiosk floor is skipped (it must be flush)", r2 is not None and r2["refs"] == ["M3"])


class Roof:
    """Something built above ground (another kiosk, a station building...); only its bbox matters."""
    underground = False

    def bbox(self):
        return 6, -27, 10, -23


r3 = SP.plan_spawn([far, near, mall, Roof()], stations, flat)
chk("A door inside another above-ground structure is skipped", r3 is not None and r3["refs"] == ["M3"])
r4 = SP.plan_spawn([mall], stations, flat)
chk("No M exit at all returns None (the CLI falls back to the ground above the station node)", r4 is None)
chk("A door below sea level (standing in water) is skipped",
    SP.plan_spawn([near], stations, lambda x, z: 60) is None)

print("\nAll tests passed" if ok else "\nSome tests failed")
sys.exit(0 if ok else 1)
