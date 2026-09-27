#!/usr/bin/env python3
"""從存檔讀回出生點與區塊高度圖，驗證新玩家會站在該站的地方。

玩家曾經生在 (0.5, -63, 0.5)，世界最底下的石頭裡。遊戲找出生點
（26.2 的 PlayerSpawnFinder）不看方塊本身，而是查區塊存的 MOTION_BLOCKING
高度圖取柱頂、用 WORLD_SURFACE 與 OCEAN_FLOOR 排除水面，再從柱頂往下找第一個
頂面完整的方塊，站在它上面。所以光是「出生點那格站得住」不夠，高度圖也得對。

這支工具只讀磁碟，不信生成器的自述：

  (a) 讀 level.dat 的 spawn（pos、yaw、pitch、dimension）
  (b) 出生點那一格站得住（walk.standable），而且頭上一路到世界頂都是空氣
  (c) 解出生點所在區塊、周圍 3x3、再抽一批別的區塊，把存的四張高度圖
      和從 section 方塊重算的結果逐柱比對（--all 則比對全部區塊）
  (d) 照遊戲的 getLevelRespawnPos 用存的高度圖走一遍：玩家要剛好落在出生點那一格
  (e) 面向的方向上是出入口亭的門洞，門裡看得到出口牌
  另外印出 respawn_radius（預設 10）範圍內的候選柱各會落在哪裡 —— 只供參考，
  不算失敗：半徑內有屋頂的話，玩家有機會被放到屋頂上。

重算高度圖用的分類表是 mrt/infrastructure/heightmap.py（與生成器同一份；
那份表本身是拿 26.2 的 Heightmap.Types.*.isOpaque() 對全部方塊狀態比對過的）。

用法:
    ./.venv/bin/python tools/verify_spawn.py <存檔> [--sample 300] [--all] [--radius 10]
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

# 碰撞箱頂面不完整的方塊（半格高、細柱、門、梯、罐子……）。遊戲找出生點時
# 要找「頂面完整」（Block.isFaceFull(collision, UP)）的方塊才站得上去。
# 這裡只求對本專案用到的材質與常見方塊判得對：walk.is_support 過了、名稱不落在
# 下面這些形狀裡，就當成完整方塊。用字尾與全名比對，不用子字串 —— 子字串會把
# bedrock 當成床（bed）、把 sea_lantern 當成燈籠。
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
    """這個方塊的碰撞箱頂面是不是完整一整面（站得上去、出生點會落在它上面）。"""
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
    """一個讀回來的區塊：section 方塊與存的高度圖。"""

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
        """區塊內座標 (0..15) 的方塊。"""
        s = self.secs.get(y >> 4)
        if s is None:
            return "minecraft:air"
        pal, idx = s
        return pal[int(idx[(y & 15) * 256 + z * 16 + x])]


def check_chunk(ch):
    """比對一個區塊存的高度圖與重算的結果。回傳問題描述清單（空的就是全對）。"""
    probs = []
    if ch.keys != sorted(HM.TYPES):
        probs.append(f"高度圖的鍵是 {ch.keys}，應該剛好是 {sorted(HM.TYPES)}")
    bad_len = {k: n for k, n in ch.lens.items() if n != HM.N_LONGS}
    if bad_len:
        probs.append(f"長度不是 {HM.N_LONGS} 個 long：{bad_len}")
    mine = ch.recomputed()
    for k, t in enumerate(HM.TYPES):
        if t not in ch.stored:
            continue
        diff = np.nonzero(ch.stored[t] != mine[k])[0]
        if len(diff):
            i = int(diff[0])
            x, z = i % 16, i // 16
            probs.append(f"{t} 有 {len(diff)} 柱不符，例如 ({ch.cx * 16 + x},{ch.cz * 16 + z})："
                         f"存的柱頂 y{HM.top_y(ch.stored[t][i])}，方塊重算 y{HM.top_y(mine[k][i])}")
    return probs


class Nearby:
    """出生點附近讀回來的區塊（只從磁碟）。"""

    def __init__(self, save, coords):
        self.chunks = {(cx, cz): ChunkData(cx, cz, root)
                       for cx, cz, root in SR.read_chunks(save, coords)}

    def get(self, x, y, z):
        ch = self.chunks.get((x >> 4, z >> 4))
        if ch is None or not (Y_MIN <= y <= Y_MAX):
            return "minecraft:air"
        return ch.block(x & 15, y, z & 15)

    def top(self, t, x, z):
        """存的高度圖在 (x, z) 的柱頂 y（遊戲的 getHeight）。"""
        ch = self.chunks.get((x >> 4, z >> 4))
        if ch is None or t not in ch.stored:
            return None
        return HM.top_y(ch.stored[t][(x & 15) + (z & 15) * 16])

    def respawn_pos(self, x, z):
        """照 26.2 的 PlayerSpawnFinder.getLevelRespawnPos 走一遍（有天空的維度）。

        i = MOTION_BLOCKING 柱頂；比世界底還低就放棄。WORLD_SURFACE 柱頂 j 若
        不高於 i 又高於 OCEAN_FLOOR 柱頂，這一柱是水面，放棄。否則從 i+1 往下找：
        碰到流體就放棄，第一個頂面完整的方塊上面那一格就是答案。回傳 y 或 None。
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
        """noCollisionNoLiquid：玩家（0.6 x 1.8）放在這一格底面中央，碰不到方塊、不在水裡。"""
        return all(walk.is_passable(self.get(x, yy, z)) and not HM.has_fluid(self.get(x, yy, z))
                   for yy in (y, y + 1))


def facing_of(yaw):
    """Minecraft 的 yaw -> 水平朝向的最近正交方向 (dx, dz)。"""
    fx, fz = -math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    return (int(round(fx)), 0) if abs(fx) >= abs(fz) else (0, int(round(fz)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save")
    ap.add_argument("--sample", type=int, default=300, help="另外抽幾個區塊比對高度圖")
    ap.add_argument("--all", action="store_true", help="比對存檔裡每一個區塊的高度圖")
    ap.add_argument("--radius", type=int, default=10, help="respawn_radius（只供參考）")
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
    print(f"level.dat 出生點 ({x},{y},{z})  yaw {lv['yaw']:.1f}  pitch {lv['pitch']:.1f}  {lv['dim']}")
    if lv["dim"] != "minecraft:overworld":
        fail(f"出生點不在主世界：{lv['dim']}")

    coords_all = SR.chunk_coords(a.save)
    have = set(coords_all)
    scx, scz = x >> 4, z >> 4
    r = max(1, (a.radius + 15) // 16 + 1)
    near = [(scx + dx, scz + dz) for dx in range(-r, r + 1) for dz in range(-r, r + 1)]
    if (scx, scz) not in have:
        fail(f"出生點所在的區塊 ({scx},{scz}) 不在存檔裡 —— 遊戲會自己生成一塊超平坦地，"
             f"跟蓋好的世界無關")
        print(f"\n驗證失敗：{len(fails)} 項")
        return 1
    w = Nearby(a.save, [c for c in near if c in have])
    sch = w.chunks[(scx, scz)]
    print(f"  出生點區塊 ({scx},{scz})  Status {sch.status}")

    # ---- (b) 站得住、頭上是天空 ----
    print("\n(b) 出生點那一格")
    below = w.get(x, y - 1, z)
    print(f"  腳下 y{y - 1} {below}；腳 y{y} {w.get(x, y, z)}；頭 y{y + 1} {w.get(x, y + 1, z)}")
    if walk.standable(w.get, x, y, z):
        ok("站得住（walk.standable）")
    else:
        fail("站不住：腳或頭那一格不通，或腳下不是實心")
    roof = next((yy for yy in range(y, Y_MAX + 1) if w.get(x, yy, z) not in AIRS), None)
    if roof is None:
        ok(f"頭上 y{y}..y{Y_MAX} 全是空氣（開放的天空）")
    else:
        fail(f"頭上 y{roof} 有 {w.get(x, roof, z)}，不是開放的天空")
    if full_top(below):
        ok(f"腳下的 {walk.base_name(below)} 頂面完整")
    else:
        fail(f"腳下的 {below} 頂面不完整，遊戲找出生點時會穿過它往下找")

    # ---- (c) 高度圖逐柱比對 ----
    print("\n(c) 存的高度圖 vs. 從方塊重算")
    col = (x & 15) + (z & 15) * 16
    mine = sch.recomputed()
    for k, t in enumerate(HM.TYPES):
        s = sch.stored.get(t)
        sv = "（沒存）" if s is None else f"y{HM.top_y(s[col])}"
        print(f"  出生點那一柱 {t:<26} 存的柱頂 {sv:<8} 重算 y{HM.top_y(mine[k][col])}")
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
                first.append(f"區塊 ({cx},{cz})：" + "；".join(probs))
    if n_bad:
        fail(f"{n} 個區塊裡 {n_bad} 個的高度圖跟方塊對不上")
        for s in first:
            print("      " + s)
    else:
        ok(f"{n:,} 個區塊四張高度圖逐柱全對"
           + ("（存檔裡的全部區塊）" if a.all
              else f"（出生點周圍 {len(w.chunks)} 個 + 抽樣；存檔共 {len(have):,} 個，--all 全比）"))

    # ---- (d) 照遊戲的邏輯走一遍 ----
    print("\n(d) 遊戲用高度圖找出生點（getLevelRespawnPos）")
    got = w.respawn_pos(x, z)
    if w.top("MOTION_BLOCKING", x, z) is None:
        fail("出生點區塊沒有存 MOTION_BLOCKING 高度圖")
    elif got is None:
        fail("這一柱會被遊戲判成找不到出生點（高度圖在世界底下、是水面，或往下碰到流體）")
    elif got != y:
        fail(f"高度圖會把玩家放在 y{got}，不是出生點的 y{y}")
    else:
        ok(f"MOTION_BLOCKING 柱頂 y{w.top('MOTION_BLOCKING', x, z)}，"
           f"往下第一個完整頂面在 y{got - 1} —— 玩家剛好站在 y{y}")
    if w.fits(x, y, z):
        ok("玩家的碰撞箱放得下、不在水裡（noCollisionNoLiquid）")
    else:
        fail("玩家的碰撞箱會卡在方塊或水裡")

    # ---- (e) 面向出入口亭的門 ----
    print("\n(e) 面向")
    fx, fz = facing_of(lv["yaw"])
    door = [w.get(x + fx, yy, z + fz) for yy in (y, y + 1, y + 2)]
    signs = SR.read_signs(a.save, x - 6, z - 6, x + 6, z + 6)
    ahead = [(sx, sy, sz, m) for sx, sy, sz, m in signs
             if (sx - x) * fx + (sz - z) * fz >= 1 and abs((sx - x) * fz - (sz - z) * fx) <= 1
             and (sx - x) * fx + (sz - z) * fz <= 4 and abs(sy - y) <= 2]
    print(f"  yaw {lv['yaw']:.1f} -> 朝 ({fx},{fz})；前方一格 y{y}..y{y + 2}：" +
          "、".join(walk.base_name(b).replace("minecraft:", "") for b in door))
    if all(walk.is_passable(b) for b in door):
        ok("正前方是三格高的門洞")
    else:
        fail("正前方不是門洞")
    if ahead:
        sx, sy, sz, m = ahead[0]
        ok(f"門裡 ({sx},{sy},{sz}) 的牌子：{' / '.join(t for t in m if t)}")
    else:
        fail("面向的方向上四格內看不到出口牌")

    # ---- respawn_radius 的參考 ----
    R = a.radius
    print(f"\nrespawn_radius = {R} 時（只供參考）：遊戲會在 {2 * R + 1}x{2 * R + 1} 的候選柱裡"
          f"依亂數順序挑第一個合格的")
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
        print(f"  街面（出生點 ±1 格）{len(cats['street'])}、比街面高（屋頂）{len(cats['roof'])}、"
              f"比街面低 {len(cats['low'])}、不合格 {len(cats['none'])}（共 {total} 柱）")
        if valid == 0:
            print("  沒有一柱合格 —— 遊戲會退回「從出生點往上找空位、再往下掉到第一個碰撞面」")
        elif cats["roof"]:
            ys = sorted({c[2] for c in cats["roof"]})
            what = sorted({walk.base_name(w.get(c[0], c[2] - 1, c[1])).replace("minecraft:", "")
                           for c in cats["roof"]})
            print(f"  屋頂柱落在 y{ys[0]}～y{ys[-1]}，踩的是 {', '.join(what)}："
                  f"約 {len(cats['roof']) / max(1, valid):.0%} 的機會被放到屋頂上 —— "
                  f"要讓每個新玩家都站在門口，respawn_radius 得設成 0")
        else:
            print("  半徑內沒有屋頂，預設半徑也不會把玩家放到屋頂上")

    print()
    if fails:
        print(f"驗證失敗：{len(fails)} 項")
        return 1
    print("出生點驗證通過")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
