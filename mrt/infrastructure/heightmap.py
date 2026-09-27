#!/usr/bin/env python3
"""區塊高度圖（Heightmaps）：Status=full 的區塊存檔時一定要帶的四張表。

遊戲找出生點、重生點（PlayerSpawnFinder.getLevelRespawnPos）是直接查區塊的
MOTION_BLOCKING 高度圖取「這一柱最高的一格」，WORLD_SURFACE／OCEAN_FLOOR 用來
排除水面，再從柱頂往下找第一個頂面完整的方塊。區塊原本寫出去的是空的
Heightmaps（遊戲自己存的 full 區塊從來不會這樣），而玩家曾經生在
(0.5, -63, 0.5) —— 世界最底下、岩床上一格的石頭裡。

26.2 的 full 區塊存四種（ChunkStatus.FINAL_HEIGHTMAPS；遊戲自己存的 full 區塊
一律是這四個鍵，逐一解過 GameTest 伺服器存出來的區塊確認）：

    WORLD_SURFACE              不是空氣（air / cave_air / void_air 以外都算）
    OCEAN_FLOOR                BlockState.blocksMotion()
    MOTION_BLOCKING            blocksMotion() 或含流體（水、熔岩、含水方塊）
    MOTION_BLOCKING_NO_LEAVES  同上，但樹葉不算

每張表 256 筆，索引 = x + z*16（區塊內座標），值 = 那一柱最高一格「擋住」的
方塊的 y + 1 - Y_MIN（整柱都不擋就是 0）。每筆 ceil(log2(世界高度+1)) bit、不跨 long
—— 與 block_states 同一套打包法。原版 384 格高是 9 bit、一個 long 7 筆、37 個 long；
這個世界為了台北101 加高到 704 格（config.WORLD_HEIGHT），是 10 bit、6 筆、43 個 long。

**分類只有這一份**（classify / flags）。blocksMotion() 不是「有沒有碰撞箱」：
告示牌（含壁掛、懸掛）、旗幟、壓力板雖然穿得過去，遊戲在方塊屬性上標了
forceSolidOn，高度圖一律算它們擋；反過來雪片（全部 8 層）、鷹架、梯子、
蜘蛛網、竹筍算不擋。這份表是拿 26.2 的 Heightmap.Types.*.isOpaque() 對全部
32,366 個方塊狀態逐一比對過的，不是照直覺寫的 —— 改它之前先重跑一次比對。
"""
import functools

import numpy as np

from mrt.config import Y_MIN, Y_MAX, SEC_MIN, SEC_MAX

# 存檔裡的鍵名與位元順序（flags() 的第 k 個 bit 對應 TYPES[k]）
TYPES = ("WORLD_SURFACE", "OCEAN_FLOOR", "MOTION_BLOCKING", "MOTION_BLOCKING_NO_LEAVES")

def layout(height):
    """世界高度 -> (每筆幾 bit, 一個 long 幾筆, 幾個 long)。384 -> (9, 7, 37)。"""
    bits = height.bit_length()
    per = 64 // bits
    return bits, per, -(-256 // per)


BITS, PER_LONG, N_LONGS = layout(Y_MAX - Y_MIN + 1)     # 704 -> (10, 6, 43)

AIR_BLOCKS = frozenset({"minecraft:air", "minecraft:cave_air", "minecraft:void_air"})

# 不管什麼狀態都含流體的方塊（其餘的方塊要看 waterlogged=true）
ALWAYS_FLUID = frozenset("minecraft:" + n for n in (
    "water", "lava", "bubble_column", "kelp", "kelp_plant", "seagrass", "tall_seagrass"))

# ---- blocksMotion() 為否的方塊：整族用字尾（逐一確認過沒有誤收）、其餘逐一列出 ----
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

# 樹葉：MOTION_BLOCKING_NO_LEAVES 不算它們
_LEAVES_SUFFIX = "_leaves"


def _split(block):
    """'oak_sign[rotation=4]' -> ('minecraft:oak_sign', 'rotation=4')"""
    base, _, props = block.partition("[")
    if ":" not in base:
        base = "minecraft:" + base
    return base, props.rstrip("]")


def _solid(base, props):
    """BlockState.blocksMotion()。"""
    if base in _NOT_SOLID:
        return False
    name = base[len("minecraft:"):] if base.startswith("minecraft:") else base
    if name.endswith(_NOT_SOLID_SUFFIX) or name.startswith(_NOT_SOLID_PREFIX):
        return False
    # 唯一一個看狀態的：沒有柱子、四面都不接的樹脂磚牆沒有碰撞箱
    # （其他牆有 forceSolidOn，只有它沒有）
    if base == "minecraft:resin_brick_wall" and "up=false" in props and all(
            f"{d}=none" in props for d in ("north", "south", "east", "west")):
        return False
    return True


def has_fluid(block):
    """含流體（BlockState.getFluidState() 不是空的）：水、熔岩、含水的方塊。"""
    base, props = _split(block)
    return base in ALWAYS_FLUID or "waterlogged=true" in props


def classify(block):
    """方塊字串 -> 四種高度圖各自算不算擋住：(WORLD_SURFACE, OCEAN_FLOOR,
    MOTION_BLOCKING, MOTION_BLOCKING_NO_LEAVES)。None 當成空氣。"""
    if block is None:
        return (False, False, False, False)
    base, props = _split(block)
    not_air = base not in AIR_BLOCKS
    solid = _solid(base, props)
    mb = solid or has_fluid(block)
    return (not_air, solid, mb, mb and not base.endswith(_LEAVES_SUFFIX))


@functools.lru_cache(maxsize=None)
def flags(block):
    """classify() 壓成一個位元組：第 k 個 bit 是 TYPES[k]。
    全世界不到一千種方塊字串，快取起來每個區塊只剩查表。"""
    return sum(1 << k for k, v in enumerate(classify(block)) if v)


def flags_lut(names):
    """palette（方塊字串清單）-> uint8 查表陣列。"""
    return np.array([flags(n) for n in names], dtype=np.uint8)


def column_heights(section_flags, sec_min=SEC_MIN, sec_max=SEC_MAX):
    """由上往下掃 section，算出四張高度圖。

    section_flags(sy) 回傳這個 section 每格的 flags（uint8，(16,16,16) 的 [y][z][x]），
    或 None 表示整個 section 都不擋（例如地面以上沒寫過的空氣）。
    回傳 int32 陣列 (4, 16, 16) = [TYPES 的順序][z][x]，值是 y + 1 - Y_MIN，
    整柱都不擋是 0。四張表都找齊就提早停 —— 絕大多數的柱子在地表那個
    section 就結束了，底下的隧道根本不必看。
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
            top = 15 - np.argmax(m[:, ::-1], axis=1)      # 每柱最高那一格的 y（section 內）
            out[hit] = (sy * 16 + top[hit]) + 1 - Y_MIN
            todo &= ~hit
            if not todo.any():
                break
    return out


def heights_from_palettes(sections):
    """{sy: (palette 名稱清單, 長度 4096 的索引)} -> (4, 256) 的高度圖。

    讀回存檔時用：section 已經是完整的方塊（背景地層寫檔時就填進去了），
    缺的 section 當成全空氣 —— 遊戲自己存的區塊也會省略全空的 section。
    """
    def section_flags(sy):
        s = sections.get(sy)
        if s is None:
            return None
        pal, idx = s
        return flags_lut(pal)[np.asarray(idx)]
    return column_heights(section_flags).reshape(4, 256)


def pack(values, height=None):
    """256 筆高度 -> N_LONGS 個有號 long（與遊戲的 SimpleBitStorage 相同：
    第 i 筆放在第 i // PER_LONG 個 long 的第 (i % PER_LONG) * BITS 個 bit 起，不跨 long）。
    height 預設是這個世界的高度；測試拿遊戲存的原版高度（384）區塊來比對時才指定。"""
    bits, per, n_longs = layout(height) if height else (BITS, PER_LONG, N_LONGS)
    v = np.asarray(values, dtype=np.uint64).reshape(-1)
    if v.size != 256:
        raise ValueError(f"高度圖要剛好 256 筆，拿到 {v.size}")
    buf = np.zeros(n_longs * per, dtype=np.uint64)
    buf[:256] = v
    buf = buf.reshape(n_longs, per)
    shifts = (np.arange(per, dtype=np.uint64) * np.uint64(bits))
    out = np.bitwise_or.reduce(buf << shifts, axis=1)
    return out.astype(np.int64)


def unpack(longs, height=None):
    """N_LONGS 個 long -> 256 筆高度（int32，索引 x + z*16）。height 同 pack()。"""
    bits, per, n_longs = layout(height) if height else (BITS, PER_LONG, N_LONGS)
    a = np.asarray(longs, dtype=np.int64).view(np.uint64).reshape(-1)
    if a.size != n_longs:
        raise ValueError(f"高度圖要剛好 {n_longs} 個 long，拿到 {a.size}")
    shifts = (np.arange(per, dtype=np.uint64) * np.uint64(bits))
    vals = (a[:, None] >> shifts) & np.uint64((1 << bits) - 1)
    return vals.reshape(-1)[:256].astype(np.int32)


def top_y(value):
    """高度圖的值 -> 那一柱最高一格擋住的方塊的 y（整柱都不擋回 Y_MIN - 1）。
    就是遊戲 ChunkAccess.getHeight() 回傳的東西。"""
    return int(value) - 1 + Y_MIN
