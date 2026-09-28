#!/usr/bin/env python3
"""Read the spawn point and the chunk heightmaps back from a world save, and check that a
new player stands where they should.

Players once spawned at (0.5, -63, 0.5), inside the stone at the bottom of the world. The
game's spawn search (PlayerSpawnFinder in 26.2) does not look at the blocks themselves. It
reads the column top from the MOTION_BLOCKING heightmap stored in the chunk, uses
WORLD_SURFACE and OCEAN_FLOOR to rule out water surfaces, then searches down from the
column top for the first block with a full top face and stands on it. So a standable spawn
cell is not enough; the heightmaps must be right too.

This tool reads only the disk and does not trust the generator's own account:

  (a) Read the spawn from level.dat (pos, yaw, pitch, dimension).
  (b) The spawn cell is standable (walk.standable), with air all the way from the head to
      the top of the world.
  (c) Decode the spawn chunk, the 3x3 around it and a sample of other chunks, and compare
      the four stored heightmaps column by column with the ones recomputed from the
      section blocks (--all compares every chunk).
  (d) Follow the game's getLevelRespawnPos with the stored heightmaps: the player must land
      exactly on the spawn cell.
  (e) The facing direction looks into the doorway of an exit kiosk, with the exit sign
      visible inside.
  It also prints where each candidate column within respawn_radius (default 10) would
  land. This is for reference only and does not count as a failure: with a roof within
  the radius, a player may be placed on the roof.

The classification table for recomputing the heightmaps is mrt/infrastructure/heightmap.py
(the same one the generator uses; that table was itself checked against 26.2's
Heightmap.Types.*.isOpaque() for every block state).

Usage:
    ./.venv/bin/python tools/verify_spawn.py <save> [--sample 300] [--all] [--radius 10]
"""
import argparse
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nbtlib
import numpy as np

from mrt.config import Y_MIN, Y_MAX
from mrt.domain import walk
from mrt.infrastructure import heightmap as HM
from mrt.infrastructure import savereader as SR

AIRS = HM.AIR_BLOCKS

# Blocks whose collision box has an incomplete top face (half height, thin posts, doors,
# ladders, pots...). The game's spawn search stands only on a block with a full top face
# (Block.isFaceFull(collision, UP)). This only needs to be right for the materials this
# project uses and for common blocks: a block that passes walk.is_support and whose name
# does not fall among the shapes below counts as full. The match is on suffixes and full
# names, not substrings: a substring match would take bedrock for a bed and sea_lantern for
# a lantern.
_PARTIAL_SUFFIX = ("_fence", "_fence_gate", "_wall", "_pane", "_door", "_trapdoor",
                   "_pressure_plate", "_carpet", "_bed", "candle", "cake", "_sign",
                   "_banner", "_head", "_skull", "_button", "rail", "torch",
                   "copper_lantern", "_chain", "copper_bars", "amethyst_bud",
                   "amethyst_cluster")
_PARTIAL_NAMES = frozenset("minecraft:" + n for n in """
    iron_bars lantern soul_lantern chain iron_chain end_rod lightning_rod ladder
    scaffolding dirt_path farmland chest trapped_chest ender_chest campfire soul_campfire
    anvil chipped_anvil damaged_anvil bell lectern stonecutter enchanting_table cauldron
    water_cauldron lava_cauldron powder_snow_cauldron hopper composter brewing_stand
    daylight_detector sculk_sensor calibrated_sculk_sensor sculk_shrieker conduit
    dragon_egg bamboo cactus honey_block soul_sand mud snow turtle_egg sea_pickle
    pointed_dripstone grindstone end_portal_frame piston_head lily_pad repeater
    comparator flower_pot decorated_pot heavy_core
""".split())


def full_top(block):
    """Whether this block's collision box has a full top face (it can be stood on, and a
    spawn lands on it)."""
    if not walk.is_support(block):
        return False
    name = walk.base_name(block)
    st = block[len(name):]
    if name.endswith("_slab"):
        return "type=top" in st or "type=double" in st
    if name.endswith("_stairs"):
        return "half=top" in st
    if name in _PARTIAL_NAMES or name.startswith("minecraft:potted_"):
        return False
    return not name.endswith(_PARTIAL_SUFFIX)


def read_level(save):
    f = nbtlib.load(os.path.join(save, "level.dat"))
    d = f["Data"] if "Data" in f else f[""]["Data"]
    sp = d["spawn"]
    pos = [int(v) for v in sp["pos"]]
    return dict(pos=pos, yaw=float(sp.get("yaw", 0.0)), pitch=float(sp.get("pitch", 0.0)),
                dim=str(sp.get("dimension", "minecraft:overworld")))


class ChunkData:
    """A chunk read back: its section blocks and stored heightmaps."""

    def __init__(self, cx, cz, root):
        self.cx, self.cz = cx, cz
        self.status = str(root.get("Status", ""))
        self.secs = {}
        for sec in root.get("sections", ()):
            sb = SR.section_blocks(sec)
            if sb is not None:
                self.secs[int(sec["Y"])] = sb
        hm = root.get("Heightmaps", {})
        self.keys = sorted(str(k) for k in hm.keys())
        self.lens = {str(k): len(v) for k, v in hm.items()}
        self.stored = {}
        for t in HM.TYPES:
            if t in hm and len(hm[t]) == HM.N_LONGS:
                self.stored[t] = HM.unpack([int(v) for v in hm[t]])

    def recomputed(self):
        return HM.heights_from_palettes(self.secs)

    def block(self, x, y, z):
        """The block at in-chunk coordinates (0..15)."""
        s = self.secs.get(y >> 4)
        if s is None:
            return "minecraft:air"
        pal, idx = s
        return pal[int(idx[(y & 15) * 256 + z * 16 + x])]


def check_chunk(ch):
    """Compare a chunk's stored heightmaps with the recomputed ones. Return a list of
    problem descriptions (empty when everything matches)."""
    probs = []
    if ch.keys != sorted(HM.TYPES):
        probs.append(f"heightmap keys are {ch.keys}; expected exactly {sorted(HM.TYPES)}")
    bad_len = {k: n for k, n in ch.lens.items() if n != HM.N_LONGS}
    if bad_len:
        probs.append(f"length is not {HM.N_LONGS} longs: {bad_len}")
    mine = ch.recomputed()
    for k, t in enumerate(HM.TYPES):
        if t not in ch.stored:
            continue
        diff = np.nonzero(ch.stored[t] != mine[k])[0]
        if len(diff):
            i = int(diff[0])
            x, z = i % 16, i // 16
            probs.append(f"{t} differs in {len(diff)} columns, for example "
                         f"({ch.cx * 16 + x},{ch.cz * 16 + z}): stored top "
                         f"y{HM.top_y(ch.stored[t][i])}, recomputed from blocks "
                         f"y{HM.top_y(mine[k][i])}")
    return probs


class Nearby:
    """Chunks near the spawn point, read back (from disk only)."""

    def __init__(self, save, coords):
        self.chunks = {(cx, cz): ChunkData(cx, cz, root)
                       for cx, cz, root in SR.read_chunks(save, coords)}

    def get(self, x, y, z):
        ch = self.chunks.get((x >> 4, z >> 4))
        if ch is None or not (Y_MIN <= y <= Y_MAX):
            return "minecraft:air"
        return ch.block(x & 15, y, z & 15)

    def top(self, t, x, z):
        """Column top y at (x, z) in the stored heightmap (the game's getHeight)."""
        ch = self.chunks.get((x >> 4, z >> 4))
        if ch is None or t not in ch.stored:
            return None
        return HM.top_y(ch.stored[t][(x & 15) + (z & 15) * 16])

    def respawn_pos(self, x, z):
        """Follow 26.2's PlayerSpawnFinder.getLevelRespawnPos (for a dimension with a sky).

        i = the MOTION_BLOCKING column top; give up if it is below the bottom of the world.
        If the WORLD_SURFACE column top j is no higher than i but higher than the
        OCEAN_FLOOR column top, the column is a water surface; give up. Otherwise search
        down from i+1: give up on meeting a fluid, and the cell above the first block with
        a full top face is the answer. Return y or None.
        """
        i = self.top("MOTION_BLOCKING", x, z)
        if i is None or i < Y_MIN:
            return None
        j = self.top("WORLD_SURFACE", x, z)
        of = self.top("OCEAN_FLOOR", x, z)
        if j <= i and j > of:
            return None
        for k in range(i + 1, Y_MIN - 1, -1):
            b = self.get(x, k, z)
            if HM.has_fluid(b):
                return None
            if full_top(b):
                return k + 1
        return None

    def fits(self, x, y, z):
        """noCollisionNoLiquid: a player (0.6 x 1.8) placed at the center of this cell's floor
        touches no block and is not in water."""
        return all(walk.is_passable(self.get(x, yy, z)) and not HM.has_fluid(self.get(x, yy, z))
                   for yy in (y, y + 1))


def facing_of(yaw):
    """Minecraft yaw -> the nearest orthogonal horizontal direction (dx, dz)."""
    fx, fz = -math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    return (int(round(fx)), 0) if abs(fx) >= abs(fz) else (0, int(round(fz)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save")
    ap.add_argument("--sample", type=int, default=300,
                    help="Number of extra chunks to sample for the heightmap comparison")
    ap.add_argument("--all", action="store_true", help="Compare the heightmaps of every chunk in the save")
    ap.add_argument("--radius", type=int, default=10, help="respawn_radius (for reference only)")
    a = ap.parse_args()

    fails = []

    def fail(msg):
        fails.append(msg)
        print("  ✗ " + msg)

    def ok(msg):
        print("  ✓ " + msg)

    # ---- (a) level.dat ----
    lv = read_level(a.save)
    x, y, z = lv["pos"]
    print(f"level.dat spawn point ({x},{y},{z})  yaw {lv['yaw']:.1f}  pitch {lv['pitch']:.1f}  {lv['dim']}")
    if lv["dim"] != "minecraft:overworld":
        fail(f"Spawn point is not in the overworld: {lv['dim']}")

    coords_all = SR.chunk_coords(a.save)
    have = set(coords_all)
    scx, scz = x >> 4, z >> 4
    r = max(1, (a.radius + 15) // 16 + 1)
    near = [(scx + dx, scz + dz) for dx in range(-r, r + 1) for dz in range(-r, r + 1)]
    if (scx, scz) not in have:
        fail(f"The spawn chunk ({scx},{scz}) is not in the save. The game would generate a "
             f"superflat chunk of its own, unrelated to the built world")
        print(f"\nChecks failed: {len(fails)}")
        return 1
    w = Nearby(a.save, [c for c in near if c in have])
    sch = w.chunks[(scx, scz)]
    print(f"  Spawn chunk ({scx},{scz})  Status {sch.status}")

    # ---- (b) Standable, with open sky overhead ----
    print("\n(b) Spawn cell")
    below = w.get(x, y - 1, z)
    print(f"  Below y{y - 1} {below}; feet y{y} {w.get(x, y, z)}; head y{y + 1} {w.get(x, y + 1, z)}")
    if walk.standable(w.get, x, y, z):
        ok("Standable (walk.standable)")
    else:
        fail("Not standable: the feet or head cell is blocked, or the block below is not solid")
    roof = next((yy for yy in range(y, Y_MAX + 1) if w.get(x, yy, z) not in AIRS), None)
    if roof is None:
        ok(f"Air all the way up from y{y} to y{Y_MAX} (open sky)")
    else:
        fail(f"{w.get(x, roof, z)} overhead at y{roof}: not open sky")
    if full_top(below):
        ok(f"The {walk.base_name(below)} underfoot has a full top face")
    else:
        fail(f"The {below} underfoot has no full top face, so the game's spawn search passes "
             f"through it")

    # ---- (c) Column-by-column heightmap comparison ----
    print("\n(c) Stored heightmaps against a recomputation from the blocks")
    col = (x & 15) + (z & 15) * 16
    mine = sch.recomputed()
    for k, t in enumerate(HM.TYPES):
        s = sch.stored.get(t)
        sv = "(none)" if s is None else f"y{HM.top_y(s[col])}"
        print(f"  Spawn column {t:<26} stored top {sv:<8} recomputed y{HM.top_y(mine[k][col])}")
    if a.all:
        pick = sorted(have)
    else:
        rest = sorted(have - set(w.chunks))
        rnd = random.Random(0)
        pick = sorted(set(w.chunks) | set(rnd.sample(rest, min(a.sample, len(rest)))))
    n_bad = n = 0
    first = []
    for cx, cz, root in SR.read_chunks(a.save, pick):
        ch = w.chunks.get((cx, cz)) or ChunkData(cx, cz, root)
        probs = check_chunk(ch)
        n += 1
        if probs:
            n_bad += 1
            if len(first) < 8:
                first.append(f"Chunk ({cx},{cz}): " + "; ".join(probs))
    if n_bad:
        fail(f"{n_bad} of {n} chunks have heightmaps that do not match their blocks")
        for s in first:
            print("      " + s)
    else:
        ok(f"All four heightmaps match column by column in {n:,} chunks"
           + (" (every chunk in the save)" if a.all
              else f" ({len(w.chunks)} around the spawn point plus a sample, of "
                   f"{len(have):,} in the save; --all compares every one)"))

    # ---- (d) Follow the game's logic ----
    print("\n(d) The game's spawn search with the heightmaps (getLevelRespawnPos)")
    got = w.respawn_pos(x, z)
    if w.top("MOTION_BLOCKING", x, z) is None:
        fail("The spawn chunk has no stored MOTION_BLOCKING heightmap")
    elif got is None:
        fail("The game would find no spawn position in this column (heightmap below the world, "
             "a water surface, or a fluid on the way down)")
    elif got != y:
        fail(f"The heightmaps would place the player at y{got}, not at the spawn point's y{y}")
    else:
        ok(f"MOTION_BLOCKING column top y{w.top('MOTION_BLOCKING', x, z)}, "
           f"first full top face below it at y{got - 1}: the player stands exactly at y{y}")
    if w.fits(x, y, z):
        ok("The player's collision box fits and is not in water (noCollisionNoLiquid)")
    else:
        fail("The player's collision box would be stuck in blocks or water")

    # ---- (e) Facing the exit kiosk door ----
    print("\n(e) Facing")
    fx, fz = facing_of(lv["yaw"])
    door = [w.get(x + fx, yy, z + fz) for yy in (y, y + 1, y + 2)]
    signs = SR.read_signs(a.save, x - 6, z - 6, x + 6, z + 6)
    ahead = [(sx, sy, sz, m) for sx, sy, sz, m in signs
             if (sx - x) * fx + (sz - z) * fz >= 1 and abs((sx - x) * fz - (sz - z) * fx) <= 1
             and (sx - x) * fx + (sz - z) * fz <= 4 and abs(sy - y) <= 2]
    print(f"  yaw {lv['yaw']:.1f} -> facing ({fx},{fz}); one block ahead, y{y}..y{y + 2}: " +
          ", ".join(walk.base_name(b).replace("minecraft:", "") for b in door))
    if all(walk.is_passable(b) for b in door):
        ok("Straight ahead is a doorway 3 blocks high")
    else:
        fail("Straight ahead is not a doorway")
    if ahead:
        sx, sy, sz, m = ahead[0]
        ok(f"Sign inside the door at ({sx},{sy},{sz}): {' / '.join(t for t in m if t)}")
    else:
        fail("No exit sign within 4 blocks in the facing direction")

    # ---- respawn_radius, for reference ----
    R = a.radius
    print(f"\nWith respawn_radius = {R} (for reference only): the game takes the first valid "
          f"column, in random order, from {2 * R + 1}x{2 * R + 1} candidates")
    if R > 0:
        cats = {"street": [], "roof": [], "low": [], "none": []}
        for dx in range(-R, R + 1):
            for dz in range(-R, R + 1):
                cx_, cz_ = x + dx, z + dz
                if ((cx_ >> 4, cz_ >> 4)) not in w.chunks:
                    cats["none"].append((cx_, cz_, None))
                    continue
                yy = w.respawn_pos(cx_, cz_)
                if yy is None or not w.fits(cx_, yy, cz_):
                    cats["none"].append((cx_, cz_, yy))
                elif yy > y + 1:
                    cats["roof"].append((cx_, cz_, yy))
                elif yy < y - 1:
                    cats["low"].append((cx_, cz_, yy))
                else:
                    cats["street"].append((cx_, cz_, yy))
        total = (2 * R + 1) ** 2
        valid = total - len(cats["none"])
        print(f"  Street level (spawn ±1 block) {len(cats['street'])}, above the street (roofs) "
              f"{len(cats['roof'])}, below the street {len(cats['low'])}, invalid "
              f"{len(cats['none'])} (of {total} columns)")
        if valid == 0:
            print("  No valid column. The game falls back to searching upward from the spawn point "
                  "for free space, then dropping to the first collision surface")
        elif cats["roof"]:
            ys = sorted({c[2] for c in cats["roof"]})
            what = sorted({walk.base_name(w.get(c[0], c[2] - 1, c[1])).replace("minecraft:", "")
                           for c in cats["roof"]})
            print(f"  Roof columns land at y{ys[0]}-y{ys[-1]} on {', '.join(what)}: "
                  f"about a {len(cats['roof']) / max(1, valid):.0%} chance of a roof. "
                  f"For every new player to stand at the door, respawn_radius must be 0")
        else:
            print("  No roofs within the radius, so the default radius will not place a player on a "
                  "roof either")

    print()
    if fails:
        print(f"Checks failed: {len(fails)}")
        return 1
    print("Spawn point checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
