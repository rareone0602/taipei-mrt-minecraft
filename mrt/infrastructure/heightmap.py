#!/usr/bin/env python3
"""Chunk heightmaps (Heightmaps): the four tables a chunk with Status=full must carry when saved.

The game finds the spawn and respawn points (PlayerSpawnFinder.getLevelRespawnPos)
by reading the chunk's MOTION_BLOCKING heightmap directly for the highest block
in the column, uses WORLD_SURFACE / OCEAN_FLOOR to rule out water surfaces, and
then searches down from the top of the column for the first block with a full
top face. Chunks used to be written with empty Heightmaps (full chunks saved
by the game itself never are), and the player once spawned at (0.5, -63, 0.5):
at the very bottom of the world, inside the stone one block above the bedrock.

A full chunk in 26.2 stores four types (ChunkStatus.FINAL_HEIGHTMAPS; every
full chunk the game saves has exactly these four keys, confirmed by decoding
chunks saved by the GameTest server one by one):

    WORLD_SURFACE              not air (anything other than air / cave_air / void_air)
    OCEAN_FLOOR                BlockState.blocksMotion()
    MOTION_BLOCKING            blocksMotion() or contains a fluid (water, lava, waterlogged blocks)
    MOTION_BLOCKING_NO_LEAVES  as above, but leaves do not count

Each table has 256 entries, index = x + z*16 (coordinates within the chunk),
value = y + 1 - Y_MIN of the highest blocking block in that column (0 if
nothing in the column blocks). Each entry takes ceil(log2(world height + 1))
bits and does not span longs: the same packing as block_states. The vanilla
384-block height is 9 bits, 7 entries per long, 37 longs; this world is raised
to 704 blocks for Taipei 101 (config.WORLD_HEIGHT), which is 10 bits,
6 entries per long, 43 longs.

**This is the only classification** (classify / flags). blocksMotion() does not
mean "has a collision box": signs (including wall and hanging signs), banners
and pressure plates can be walked through, but the game marks them
forceSolidOn in their block properties, so the heightmaps always count them as
blocking. Conversely, snow layers (all 8), scaffolding, ladders, cobwebs and
bamboo shoots count as not blocking. This table was checked state by state
against 26.2's Heightmap.Types.*.isOpaque() for all 32,366 block states, not
written from intuition; rerun that comparison before changing it.
"""
import functools

import numpy as np

from mrt.config import Y_MIN, Y_MAX, SEC_MIN, SEC_MAX

# Key names in the save and their bit order (bit k of flags() is TYPES[k]).
TYPES = ("WORLD_SURFACE", "OCEAN_FLOOR", "MOTION_BLOCKING", "MOTION_BLOCKING_NO_LEAVES")

def layout(height):
    """Map a world height to (bits per entry, entries per long, number of longs). 384 -> (9, 7, 37)."""
    bits = height.bit_length()
    per = 64 // bits
    return bits, per, -(-256 // per)


BITS, PER_LONG, N_LONGS = layout(Y_MAX - Y_MIN + 1)     # 704 -> (10, 6, 43)

AIR_BLOCKS = frozenset({"minecraft:air", "minecraft:cave_air", "minecraft:void_air"})

# Blocks that contain a fluid in every state (any other block depends on waterlogged=true).
ALWAYS_FLUID = frozenset("minecraft:" + n for n in (
    "water", "lava", "bubble_column", "kelp", "kelp_plant", "seagrass", "tall_seagrass"))

# ---- Blocks for which blocksMotion() is false ----
# Whole families by suffix (each checked for false matches); the rest one by one.
_NOT_SOLID_SUFFIX = ("_button", "_carpet", "candle", "_sapling", "rail", "torch",
                     "copper_golem_statue", "_skull")
_NOT_SOLID_PREFIX = ("potted_",)
_NOT_SOLID = frozenset("minecraft:" + n for n in """
    air cave_air void_air light structure_void
    water lava bubble_column fire soul_fire nether_portal end_portal end_gateway
    snow powder_snow cobweb scaffolding ladder lever tripwire tripwire_hook
    redstone_wire repeater comparator end_rod flower_pot heavy_core frogspawn
    vine cave_vines cave_vines_plant twisting_vines twisting_vines_plant
    weeping_vines weeping_vines_plant glow_lichen resin_clump hanging_roots
    pale_hanging_moss spore_blossom sugar_cane chorus_plant chorus_flower cocoa
    lily_pad sea_pickle kelp kelp_plant seagrass tall_seagrass
    big_dripleaf big_dripleaf_stem small_dripleaf mangrove_propagule
    wheat carrots potatoes beetroots nether_wart sweet_berry_bush
    melon_stem pumpkin_stem attached_melon_stem attached_pumpkin_stem
    torchflower_crop pitcher_crop pitcher_plant
    short_grass tall_grass fern large_fern dead_bush bush firefly_bush
    short_dry_grass tall_dry_grass nether_sprouts crimson_roots warped_roots
    crimson_fungus warped_fungus brown_mushroom red_mushroom azalea flowering_azalea
    dandelion golden_dandelion poppy blue_orchid allium azure_bluet
    red_tulip orange_tulip white_tulip pink_tulip oxeye_daisy cornflower
    lily_of_the_valley wither_rose torchflower sunflower lilac rose_bush peony
    open_eyeblossom closed_eyeblossom cactus_flower pink_petals wildflowers leaf_litter
    tube_coral brain_coral bubble_coral fire_coral horn_coral
    tube_coral_fan brain_coral_fan bubble_coral_fan fire_coral_fan horn_coral_fan
    tube_coral_wall_fan brain_coral_wall_fan bubble_coral_wall_fan
    fire_coral_wall_fan horn_coral_wall_fan
    creeper_head creeper_wall_head dragon_head dragon_wall_head piglin_head
    piglin_wall_head player_head player_wall_head zombie_head zombie_wall_head
""".split())

# Leaves: MOTION_BLOCKING_NO_LEAVES does not count them.
_LEAVES_SUFFIX = "_leaves"


def _split(block):
    """'oak_sign[rotation=4]' -> ('minecraft:oak_sign', 'rotation=4')"""
    base, _, props = block.partition("[")
    if ":" not in base:
        base = "minecraft:" + base
    return base, props.rstrip("]")


def _solid(base, props):
    """Return BlockState.blocksMotion()."""
    if base in _NOT_SOLID:
        return False
    name = base[len("minecraft:"):] if base.startswith("minecraft:") else base
    if name.endswith(_NOT_SOLID_SUFFIX) or name.startswith(_NOT_SOLID_PREFIX):
        return False
    # The only state-dependent case: a resin brick wall with no post and no
    # connection on any side has no collision box (every other wall has
    # forceSolidOn; this one does not).
    if base == "minecraft:resin_brick_wall" and "up=false" in props and all(
            f"{d}=none" in props for d in ("north", "south", "east", "west")):
        return False
    return True


def has_fluid(block):
    """Return whether the block contains a fluid.

    That is, BlockState.getFluidState() is not empty: water, lava, waterlogged blocks.
    """
    base, props = _split(block)
    return base in ALWAYS_FLUID or "waterlogged=true" in props


def classify(block):
    """Map a block string to whether it blocks in each of the four heightmaps.

    Returns (WORLD_SURFACE, OCEAN_FLOOR, MOTION_BLOCKING, MOTION_BLOCKING_NO_LEAVES).
    None is treated as air."""
    if block is None:
        return (False, False, False, False)
    base, props = _split(block)
    not_air = base not in AIR_BLOCKS
    solid = _solid(base, props)
    mb = solid or has_fluid(block)
    return (not_air, solid, mb, mb and not base.endswith(_LEAVES_SUFFIX))


@functools.lru_cache(maxsize=None)
def flags(block):
    """Pack classify() into one byte: bit k is TYPES[k].

    The whole world has fewer than a thousand distinct block strings, so with
    caching each chunk is only a table lookup."""
    return sum(1 << k for k, v in enumerate(classify(block)) if v)


def flags_lut(names):
    """Map a palette (a list of block strings) to a uint8 lookup array."""
    return np.array([flags(n) for n in names], dtype=np.uint8)


def column_heights(section_flags, sec_min=SEC_MIN, sec_max=SEC_MAX):
    """Scan the sections from the top down and compute the four heightmaps.

    section_flags(sy) returns the flags of every cell in the section (uint8,
    (16,16,16) as [y][z][x]), or None when nothing in the section blocks (for
    example, unwritten air above the ground).
    Returns an int32 array (4, 16, 16) = [TYPES order][z][x] whose values are
    y + 1 - Y_MIN, or 0 where nothing in the column blocks. It stops early once
    all four tables are found: almost every column ends in the section that
    holds the ground surface, so the tunnels below never need to be read.
    """
    out = np.zeros((4, 16, 16), dtype=np.int32)
    todo = np.ones((4, 16, 16), dtype=bool)
    bits = np.arange(4, dtype=np.uint8).reshape(4, 1, 1, 1)
    for sy in range(sec_max, sec_min - 1, -1):
        f = section_flags(sy)
        if f is None:
            continue
        f = np.asarray(f, dtype=np.uint8).reshape(16, 16, 16)
        if not f.any():
            continue
        m = ((f[None] >> bits) & 1).astype(bool)          # (4, y, z, x)
        hit = m.any(axis=1) & todo                        # (4, z, x)
        if hit.any():
            # y of the highest cell in each column, within the section.
            top = 15 - np.argmax(m[:, ::-1], axis=1)
            out[hit] = (sy * 16 + top[hit]) + 1 - Y_MIN
            todo &= ~hit
            if not todo.any():
                break
    return out


def heights_from_palettes(sections):
    """Map {sy: (palette names, 4096 indices)} to (4, 256) heightmaps.

    Used when reading a save back: the sections already hold complete blocks
    (the background strata are filled in when the file is written), and a
    missing section is treated as all air; chunks saved by the game also omit
    sections that are entirely air.
    """
    def section_flags(sy):
        s = sections.get(sy)
        if s is None:
            return None
        pal, idx = s
        return flags_lut(pal)[np.asarray(idx)]
    return column_heights(section_flags).reshape(4, 256)


def pack(values, height=None):
    """Pack 256 heights into N_LONGS signed longs.

    Matches the game's SimpleBitStorage: entry i goes into long i // PER_LONG,
    starting at bit (i % PER_LONG) * BITS, and does not span longs.
    height defaults to this world's height; it is given only when a test
    compares against a chunk the game saved at the vanilla height (384)."""
    bits, per, n_longs = layout(height) if height else (BITS, PER_LONG, N_LONGS)
    v = np.asarray(values, dtype=np.uint64).reshape(-1)
    if v.size != 256:
        raise ValueError(f"A heightmap needs exactly 256 entries, got {v.size}")
    buf = np.zeros(n_longs * per, dtype=np.uint64)
    buf[:256] = v
    buf = buf.reshape(n_longs, per)
    shifts = (np.arange(per, dtype=np.uint64) * np.uint64(bits))
    out = np.bitwise_or.reduce(buf << shifts, axis=1)
    return out.astype(np.int64)


def unpack(longs, height=None):
    """Unpack N_LONGS longs into 256 heights (int32, index x + z*16). height is as in pack()."""
    bits, per, n_longs = layout(height) if height else (BITS, PER_LONG, N_LONGS)
    a = np.asarray(longs, dtype=np.int64).view(np.uint64).reshape(-1)
    if a.size != n_longs:
        raise ValueError(f"A heightmap needs exactly {n_longs} longs, got {a.size}")
    shifts = (np.arange(per, dtype=np.uint64) * np.uint64(bits))
    vals = (a[:, None] >> shifts) & np.uint64((1 << bits) - 1)
    return vals.reshape(-1)[:256].astype(np.int32)


def top_y(value):
    """Map a heightmap value to the y of the highest blocking block in the column.

    Returns Y_MIN - 1 if nothing in the column blocks. This is what the game's
    ChunkAccess.getHeight() returns."""
    return int(value) - 1 + Y_MIN
