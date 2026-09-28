#!/usr/bin/env python3
"""Unit tests for chunk heightmaps.

They cover the packing format, block classification, the column scan, and what
is written to NBT.

The packing format is compared directly against arrays the game saved: the
26.2 GameTest server placed a set of blocks on a superflat plot (signs, rails,
a pool of water, a hole dug through the bedrock, and so on) and saved it. The
GAME_* values below are that chunk's saved heightmaps copied verbatim; for the
same heights, the longs packed here must match bit for bit.

Usage: ./.venv/bin/python tests/test_heightmap.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.config import Y_MIN, Y_MAX
from mrt.infrastructure import heightmap as HM
from mrt.infrastructure.mcworld import Chunk

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and bool(cond)


# ---- Heightmaps saved by the game (a full chunk produced by the GameTest server) ----
# Height value = top y + 1 - Y_MIN; the superflat grass is at y-61, so the default value is 4.
# Column 191 has had even its bedrock dug out (all air -> 0).
GAME_WS = {84: 15, 85: 5, 86: 10, 87: 7, 88: 5, 89: 6, 90: 5, 91: 5, 92: 5, 93: 5,
           94: 5, 95: 5, 132: 5, 133: 5, 134: 5, 135: 5, 136: 5, 138: 5, 140: 5, 142: 5,
           185: 5, 186: 5, 187: 5, 188: 5, 189: 5, 191: 0, 222: 5, 229: 7, 230: 7, 231: 7,
           232: 5, 234: 5, 238: 5}
GAME_WS_LONGS = [
    72198606942111748, 72198606942111748, 72198606942111748, 72198606942111748,
    72198606942111748, 72198606942111748, 72198606942111748, 72198606942111748,
    72198606942111748, 72198606942111748, 72198606942111748, 72198606942111748,
    90283443319474703, 72198675796068869, 72198606942111748, 72198606942111748,
    72198606942111748, 72198606942111748, 90213005451593732, 72233791448680965,
    72198606942373893, 72198606942111748, 72198606942111748, 72198606942111748,
    72198606942111748, 72198606942111748, 90248258677377028, 72198606941063173,
    72198606942111748, 72198606942111748, 72198606942111748, 72233791314200580,
    126347355586824196, 72198607076329991, 72198606942111749, 72198606942111748,
    537921540]
GAME_MB = {84: 15, 85: 5, 89: 5, 92: 5, 132: 5, 133: 5, 134: 5, 135: 5, 136: 5, 138: 5,
           140: 5, 142: 5, 185: 5, 186: 5, 187: 5, 188: 5, 189: 5, 191: 0, 222: 5, 229: 7,
           230: 7, 231: 7, 232: 5, 234: 5}
GAME_MB_LONGS = [
    72198606942111748, 72198606942111748, 72198606942111748, 72198606942111748,
    72198606942111748, 72198606942111748, 72198606942111748, 72198606942111748,
    72198606942111748, 72198606942111748, 72198606942111748, 72198606942111748,
    72233791314201103, 72198606942112260, 72198606942111748, 72198606942111748,
    72198606942111748, 72198606942111748, 90213005451593732, 72233791448680965,
    72198606942373893, 72198606942111748, 72198606942111748, 72198606942111748,
    72198606942111748, 72198606942111748, 90248258677377028, 72198606941063173,
    72198606942111748, 72198606942111748, 72198606942111748, 72233791314200580,
    126347355586824196, 72198607076329991, 72198606942111748, 72198606942111748,
    537921540]


def dense(sparse, default=4):
    v = [default] * 256
    for i, h in sparse.items():
        v[i] = h
    return v


print("Packing format")
H = Y_MAX - Y_MIN + 1
chk("Vanilla 384-block height: 9 bits per entry, 7 entries per long, 37 longs", HM.layout(384) == (9, 7, 37))
chk(f"This world is {H} blocks high (Taipei 101): {HM.BITS} bits per entry, {HM.PER_LONG} entries per long, "
    f"{HM.N_LONGS} longs in all", (HM.BITS, HM.PER_LONG, HM.N_LONGS) == HM.layout(H)
    and (H != 704 or HM.layout(H) == (10, 6, 43)))
# The reference chunk saved by the game is at vanilla height (the GameTest server's
# world is not raised); the packing is the same and only the bit width differs.
for name, sp, longs in (("WORLD_SURFACE", GAME_WS, GAME_WS_LONGS),
                        ("MOTION_BLOCKING", GAME_MB, GAME_MB_LONGS)):
    chk(f"{name}: the same heights packed at vanilla 9 bits match the game's save bit for bit",
        [int(v) for v in HM.pack(dense(sp), height=384)] == longs)
    chk(f"{name}: the game's save unpacks to those heights", HM.unpack(longs, height=384).tolist() == dense(sp))
rnd = np.random.RandomState(0)
vals = rnd.randint(0, H + 1, size=256)
vals[0], vals[255] = H, H                      # The cell at the top of the world.
chk(f"Random heights in 0..{H} survive packing and unpacking", (HM.unpack(HM.pack(vals)) == vals).all())
chk("Packing produces signed longs (NBT has no unsigned long)", HM.pack(vals).dtype == np.int64)

print("Block classification (matches the game's Heightmap.Types.isOpaque)")
C = HM.classify
chk("The three kinds of air count for nothing", all(C(b) == (False,) * 4 for b in
                              ("minecraft:air", "minecraft:cave_air", "minecraft:void_air")))
chk("Stone counts in all four", C("minecraft:stone") == (True,) * 4)
for b in ("minecraft:rail[shape=north_south]", "minecraft:powered_rail[shape=east_west,powered=true]",
          "minecraft:torch", "minecraft:wall_torch[facing=north]", "minecraft:light[level=15]",
          "minecraft:stone_button[face=floor,facing=north]", "minecraft:white_carpet",
          "minecraft:poppy", "minecraft:short_grass", "minecraft:snow[layers=3]",
          "minecraft:ladder[facing=south]", "minecraft:cobweb", "minecraft:structure_void",
          "minecraft:redstone_wire"):
    chk(f"{b.split('[')[0][10:]}: does not block motion, but is not air", C(b) == (True, False, False, False))
# The game marks signs, banners and pressure plates forceSolidOn: they can be
# walked through, yet the heightmaps count them as blocking.
for b in ("minecraft:oak_sign[rotation=4,waterlogged=false]",
          "minecraft:oak_wall_sign[facing=south]", "minecraft:oak_hanging_sign[rotation=0]",
          "minecraft:oak_wall_hanging_sign[facing=north]", "minecraft:white_banner",
          "minecraft:stone_pressure_plate"):
    chk(f"{b.split('[')[0][10:]}: blocks in the heightmaps (forceSolidOn)", C(b) == (True,) * 4)
for b in ("minecraft:iron_bars", "minecraft:glass_pane", "minecraft:oak_fence",
          "minecraft:smooth_stone_slab[type=bottom]", "minecraft:light_gray_stained_glass_pane"):
    chk(f"{b.split('[')[0][10:]}: blocks", C(b) == (True,) * 4)
chk("Water: counts for MOTION_BLOCKING, not for OCEAN_FLOOR", C("minecraft:water") == (True, False, True, True))
chk("Flowing water is the same", C("minecraft:water[level=3]") == (True, False, True, True))
chk("Waterlogged rail: counts for MOTION_BLOCKING (fluid)",
    C("minecraft:rail[shape=north_south,waterlogged=true]") == (True, False, True, True))
chk("Leaves: count for MOTION_BLOCKING, not for NO_LEAVES",
    C("minecraft:oak_leaves[persistent=true]") == (True, True, True, False))
chk("Recognised without a namespace", C("stone") == (True,) * 4 and C("air") == (False,) * 4)


def top(chunk, t, x, z):
    """Return the top y from Chunk.heightmaps() at (x, z) within the chunk."""
    return HM.top_y(chunk.heightmaps()[HM.TYPES.index(t)][x + z * 16])


print("Column scan (Chunk.heightmaps)")
c = Chunk(0, 0)
chk("A column of background strata only: the top is the superflat grass at y64",
    all(top(c, t, 7, 7) == 64 for t in HM.TYPES))
for x in range(16):
    for z in range(16):
        c.set(x, 70, z, "minecraft:smooth_stone")
c.set(1, 71, 1, "minecraft:oak_sign[rotation=4,waterlogged=false]")
c.set(2, 71, 1, "minecraft:rail[shape=north_south]")
c.set(3, 71, 1, "minecraft:light[level=15]")
c.set(4, 71, 1, "minecraft:torch")
chk("The sign column: all four stop at the sign, y71",
    all(top(c, t, 1, 1) == 71 for t in HM.TYPES))
chk("The rail column: WORLD_SURFACE at the rail, y71; MOTION_BLOCKING at the floor slab below, y70",
    top(c, "WORLD_SURFACE", 2, 1) == 71 and top(c, "MOTION_BLOCKING", 2, 1) == 70)
chk("A light block is not air but does not block", top(c, "WORLD_SURFACE", 3, 1) == 71
    and top(c, "MOTION_BLOCKING", 3, 1) == 70)
chk("A torch behaves like a rail", top(c, "WORLD_SURFACE", 4, 1) == 71 and top(c, "OCEAN_FLOOR", 4, 1) == 70)
# Water column: dig out from the floor slab to the grass (y64..70), fill 66..69
# with water, leave 64 and 65 empty; below them, 63 is the background dirt.
for y in range(64, 71):
    c.set(5, y, 5, "minecraft:air")
for y in range(66, 70):
    c.set(5, y, 5, "minecraft:water")
chk("Water column: WORLD_SURFACE / MOTION_BLOCKING stop at the water surface, y69",
    top(c, "WORLD_SURFACE", 5, 5) == 69 and top(c, "MOTION_BLOCKING", 5, 5) == 69
    and top(c, "MOTION_BLOCKING_NO_LEAVES", 5, 5) == 69)
chk("Water column: OCEAN_FLOOR passes through the water and the dug-out cells "
    "and stops at the background dirt, y63",
    top(c, "OCEAN_FLOOR", 5, 5) == 63)
c.set(6, 75, 6, "minecraft:oak_leaves[persistent=true]")
chk("Leaves: MOTION_BLOCKING at y75, NO_LEAVES down to the floor slab at y70",
    top(c, "MOTION_BLOCKING", 6, 6) == 75 and top(c, "MOTION_BLOCKING_NO_LEAVES", 6, 6) == 70)
for y in range(-63, 71):
    c.set(8, y, 9, "minecraft:air")
chk("Dug down to the bedrock: top at y-64 (value 1)", top(c, "MOTION_BLOCKING", 8, 9) == -64
    and c.heightmaps()[2][8 + 9 * 16] == 1)
c.set(8, -64, 9, "minecraft:air")
chk("Bedrock dug out too: all four are 0 (top = one below the bottom of the world)",
    all(v[8 + 9 * 16] == 0 for v in c.heightmaps()) and top(c, "WORLD_SURFACE", 8, 9) == Y_MIN - 1)
c.set(3, Y_MAX, 5, "minecraft:stone")
chk(f"Top of the world, y{Y_MAX}: value {H}", c.heightmaps()[0][3 + 5 * 16] == H)
chk("The index is x + z*16 ((3,5) is entry 83, not entry 53 for (5,3))",
    c.heightmaps()[0][83] == H and c.heightmaps()[0][53] != H)

print("Writing to NBT")
root = c.to_nbt()
hm = root["Heightmaps"]
chk("Exactly four keys: " + ", ".join(sorted(hm.keys())), sorted(hm.keys()) == sorted(HM.TYPES))
chk(f"{HM.N_LONGS} longs in each", all(len(hm[t]) == HM.N_LONGS for t in HM.TYPES))
chk("Unpacks to the same values as heightmaps()",
    all((HM.unpack(hm[t]) == c.heightmaps()[k]).all() for k, t in enumerate(HM.TYPES)))
empty = Chunk(3, 4).to_nbt()["Heightmaps"]
chk("A chunk with no blocks written still carries heightmaps (y64 throughout)",
    all((HM.unpack(empty[t]) == 64 + 1 - Y_MIN).all() for t in HM.TYPES))

print("\nAll passed" if ok else "\nSome tests failed")
sys.exit(0 if ok else 1)
