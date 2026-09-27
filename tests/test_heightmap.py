#!/usr/bin/env python3
"""區塊高度圖的單元測試：打包格式、方塊分類、逐柱掃描，以及寫進 NBT 的樣子。

打包格式直接拿遊戲存出來的陣列比：26.2 的 GameTest 伺服器在一塊超平坦地上
擺了一批方塊（告示牌、鐵軌、水坑、挖穿岩床的洞……）再存檔，下面的 GAME_* 是
那個區塊存的高度圖原封不動抄下來的 —— 同樣的高度，我們打包出來的 long 要
逐位元相同。

用法: ./.venv/bin/python tests/test_heightmap.py
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


# ---- 遊戲存的高度圖（GameTest 伺服器產生的 full 區塊）----
# 高度值 = 柱頂 y + 1 - Y_MIN；超平坦的草皮在 y-61，所以預設值是 4。
# 191 那一柱連岩床都挖掉了（整柱空氣 -> 0）。
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


print("打包格式")
H = Y_MAX - Y_MIN + 1
chk("原版 384 格高：每筆 9 bit、一個 long 7 筆、37 個 long", HM.layout(384) == (9, 7, 37))
chk(f"這個世界 {H} 格高（台北101）：每筆 {HM.BITS} bit、一個 long 塞 {HM.PER_LONG} 筆、"
    f"共 {HM.N_LONGS} 個 long", (HM.BITS, HM.PER_LONG, HM.N_LONGS) == HM.layout(H)
    and (H != 704 or HM.layout(H) == (10, 6, 43)))
# 遊戲存的參考區塊是原版高度（GameTest 伺服器的世界沒有加高），打包法同一套、只差位元數
for name, sp, longs in (("WORLD_SURFACE", GAME_WS, GAME_WS_LONGS),
                        ("MOTION_BLOCKING", GAME_MB, GAME_MB_LONGS)):
    chk(f"{name}：同樣的高度照原版 9 bit 打包出來跟遊戲存的逐位元相同",
        [int(v) for v in HM.pack(dense(sp), height=384)] == longs)
    chk(f"{name}：遊戲存的解開來就是那些高度", HM.unpack(longs, height=384).tolist() == dense(sp))
rnd = np.random.RandomState(0)
vals = rnd.randint(0, H + 1, size=256)
vals[0], vals[255] = H, H                      # 世界頂那一格
chk(f"0..{H} 的隨機高度打包再解開不變", (HM.unpack(HM.pack(vals)) == vals).all())
chk("打包出來是有號 long（NBT 的 long 沒有無號）", HM.pack(vals).dtype == np.int64)

print("方塊分類（與遊戲的 Heightmap.Types.isOpaque 一致）")
C = HM.classify
chk("空氣三兄弟什麼都不算", all(C(b) == (False,) * 4 for b in
                              ("minecraft:air", "minecraft:cave_air", "minecraft:void_air")))
chk("石頭四張都算", C("minecraft:stone") == (True,) * 4)
for b in ("minecraft:rail[shape=north_south]", "minecraft:powered_rail[shape=east_west,powered=true]",
          "minecraft:torch", "minecraft:wall_torch[facing=north]", "minecraft:light[level=15]",
          "minecraft:stone_button[face=floor,facing=north]", "minecraft:white_carpet",
          "minecraft:poppy", "minecraft:short_grass", "minecraft:snow[layers=3]",
          "minecraft:ladder[facing=south]", "minecraft:cobweb", "minecraft:structure_void",
          "minecraft:redstone_wire"):
    chk(f"{b.split('[')[0][10:]}：不擋動作，但不是空氣", C(b) == (True, False, False, False))
# 遊戲把告示牌、旗幟、壓力板標成 forceSolidOn：穿得過去，高度圖卻算它們擋
for b in ("minecraft:oak_sign[rotation=4,waterlogged=false]",
          "minecraft:oak_wall_sign[facing=south]", "minecraft:oak_hanging_sign[rotation=0]",
          "minecraft:oak_wall_hanging_sign[facing=north]", "minecraft:white_banner",
          "minecraft:stone_pressure_plate"):
    chk(f"{b.split('[')[0][10:]}：高度圖算擋（forceSolidOn）", C(b) == (True,) * 4)
for b in ("minecraft:iron_bars", "minecraft:glass_pane", "minecraft:oak_fence",
          "minecraft:smooth_stone_slab[type=bottom]", "minecraft:light_gray_stained_glass_pane"):
    chk(f"{b.split('[')[0][10:]}：擋", C(b) == (True,) * 4)
chk("水：MOTION_BLOCKING 算、OCEAN_FLOOR 不算", C("minecraft:water") == (True, False, True, True))
chk("流動的水也一樣", C("minecraft:water[level=3]") == (True, False, True, True))
chk("含水的鐵軌：MOTION_BLOCKING 算（流體）",
    C("minecraft:rail[shape=north_south,waterlogged=true]") == (True, False, True, True))
chk("樹葉：MOTION_BLOCKING 算、NO_LEAVES 不算",
    C("minecraft:oak_leaves[persistent=true]") == (True, True, True, False))
chk("沒寫命名空間也認得", C("stone") == (True,) * 4 and C("air") == (False,) * 4)


def top(chunk, t, x, z):
    """Chunk.heightmaps() 在區塊內 (x, z) 的柱頂 y。"""
    return HM.top_y(chunk.heightmaps()[HM.TYPES.index(t)][x + z * 16])


print("逐柱掃描（Chunk.heightmaps）")
c = Chunk(0, 0)
chk("整柱都是背景地層：柱頂是超平坦的草皮 y64",
    all(top(c, t, 7, 7) == 64 for t in HM.TYPES))
for x in range(16):
    for z in range(16):
        c.set(x, 70, z, "minecraft:smooth_stone")
c.set(1, 71, 1, "minecraft:oak_sign[rotation=4,waterlogged=false]")
c.set(2, 71, 1, "minecraft:rail[shape=north_south]")
c.set(3, 71, 1, "minecraft:light[level=15]")
c.set(4, 71, 1, "minecraft:torch")
chk("告示牌那一柱：四張都停在告示牌 y71",
    all(top(c, t, 1, 1) == 71 for t in HM.TYPES))
chk("鐵軌那一柱：WORLD_SURFACE 在鐵軌 y71、MOTION_BLOCKING 在底下的樓板 y70",
    top(c, "WORLD_SURFACE", 2, 1) == 71 and top(c, "MOTION_BLOCKING", 2, 1) == 70)
chk("light 方塊不是空氣但不擋", top(c, "WORLD_SURFACE", 3, 1) == 71
    and top(c, "MOTION_BLOCKING", 3, 1) == 70)
chk("火把同鐵軌", top(c, "WORLD_SURFACE", 4, 1) == 71 and top(c, "OCEAN_FLOOR", 4, 1) == 70)
# 水柱：樓板到草皮（y64..70）挖空，66..69 灌水，64、65 留空，底下 63 是背景的泥土
for y in range(64, 71):
    c.set(5, y, 5, "minecraft:air")
for y in range(66, 70):
    c.set(5, y, 5, "minecraft:water")
chk("水柱：WORLD_SURFACE / MOTION_BLOCKING 停在水面 y69",
    top(c, "WORLD_SURFACE", 5, 5) == 69 and top(c, "MOTION_BLOCKING", 5, 5) == 69
    and top(c, "MOTION_BLOCKING_NO_LEAVES", 5, 5) == 69)
chk("水柱：OCEAN_FLOOR 穿過水與挖空的格子，停在背景的泥土 y63",
    top(c, "OCEAN_FLOOR", 5, 5) == 63)
c.set(6, 75, 6, "minecraft:oak_leaves[persistent=true]")
chk("樹葉：MOTION_BLOCKING 在 y75，NO_LEAVES 往下到樓板 y70",
    top(c, "MOTION_BLOCKING", 6, 6) == 75 and top(c, "MOTION_BLOCKING_NO_LEAVES", 6, 6) == 70)
for y in range(-63, 71):
    c.set(8, y, 9, "minecraft:air")
chk("挖到岩床：柱頂 y-64（值 1）", top(c, "MOTION_BLOCKING", 8, 9) == -64
    and c.heightmaps()[2][8 + 9 * 16] == 1)
c.set(8, -64, 9, "minecraft:air")
chk("連岩床都挖掉：四張都是 0（柱頂 = 世界底下一格）",
    all(v[8 + 9 * 16] == 0 for v in c.heightmaps()) and top(c, "WORLD_SURFACE", 8, 9) == Y_MIN - 1)
c.set(3, Y_MAX, 5, "minecraft:stone")
chk(f"世界頂 y{Y_MAX}：值 {H}", c.heightmaps()[0][3 + 5 * 16] == H)
chk("索引是 x + z*16（(3,5) 是 83 號，不是 (5,3) 的 53 號）",
    c.heightmaps()[0][83] == H and c.heightmaps()[0][53] != H)

print("寫進 NBT")
root = c.to_nbt()
hm = root["Heightmaps"]
chk("剛好四個鍵：" + ", ".join(sorted(hm.keys())), sorted(hm.keys()) == sorted(HM.TYPES))
chk(f"每張 {HM.N_LONGS} 個 long", all(len(hm[t]) == HM.N_LONGS for t in HM.TYPES))
chk("解開來跟 heightmaps() 一樣",
    all((HM.unpack(hm[t]) == c.heightmaps()[k]).all() for k, t in enumerate(HM.TYPES)))
empty = Chunk(3, 4).to_nbt()["Heightmaps"]
chk("沒寫過任何方塊的區塊也帶高度圖（整片 y64）",
    all((HM.unpack(empty[t]) == 64 + 1 - Y_MIN).all() for t in HM.TYPES))

print("\n全部通過" if ok else "\n有失敗")
sys.exit(0 if ok else 1)
