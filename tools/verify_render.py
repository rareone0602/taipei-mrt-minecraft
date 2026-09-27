#!/usr/bin/env python3
"""從已寫好的存檔獨立讀回區域檔，算出俯視圖 — 驗證幾何而不是相信生成器。

全向量化：滿地形的世界有上億個方塊，逐格 Python 迴圈跑不完。
每根柱子只取最高的非空氣方塊，用 (高度, 顏色) 打包成單一鍵值做 maximum 掃描。

用法: ./.venv/bin/python tools/verify_render.py <save_dir> <out.png> [--scale M]
"""
import os, io, glob, sys, zlib, argparse, re
import numpy as np, nbtlib
from PIL import Image

PALETTE = [
    ("minecraft:air",                          (  0,   0,   0)),
    ("minecraft:smooth_stone",                 (196, 200, 205)),   # 走行面
    ("minecraft:gray_concrete",                ( 88,  93, 100)),   # 導引牆
    ("minecraft:light_gray_concrete",          (150, 155, 160)),   # 橋面/屋頂
    ("minecraft:polished_andesite",            (120, 110,  98)),   # 橋墩
    ("minecraft:polished_diorite",             (235, 235, 230)),   # 月台
    ("minecraft:yellow_concrete",              (230, 190,  40)),
    ("minecraft:light_gray_stained_glass_pane",(170, 205, 215)),
    ("minecraft:glass_pane",                   (200, 225, 235)),
    ("minecraft:grass_block",                  ( 74, 110,  62)),
    ("minecraft:dirt",                         (110,  84,  60)),
    ("minecraft:stone",                        (126, 126, 126)),
    ("minecraft:sand",                         (214, 200, 152)),
    ("minecraft:water",                        ( 48,  84, 140)),
    ("minecraft:bedrock",                      ( 40,  40,  44)),
    ("minecraft:gravel",                       (136, 130, 126)),
    ("minecraft:deepslate_bricks",             ( 70,  70,  78)),
    ("minecraft:iron_bars",                    (160, 160, 165)),
    ("minecraft:smooth_stone_slab",            (190, 190, 190)),
    ("minecraft:oak_sign",                     (150, 120,  70)),
    ("minecraft:sea_lantern",                  (200, 235, 230)),
    ("minecraft:rail",                         ( 96,  92,  86)),
    ("minecraft:powered_rail",                 (172, 128,  70)),
    ("minecraft:redstone_block",               (170,  30,  30)),
    ("minecraft:lime_concrete",                ( 94, 168,  64)),
    ("minecraft:smooth_sandstone",             (222, 206, 158)),   # 站體大樓外牆
    ("minecraft:bricks",                       (170,  92,  74)),   # 紅磚色陶瓦屋頂
    ("minecraft:white_concrete",               (232, 232, 232)),   # 屋頂白邊／地坪
    ("minecraft:black_concrete",               ( 30,  30,  34)),   # 大廳黑白棋盤
    ("minecraft:deepslate_tiles",              ( 62,  62,  68)),   # 宮殿式屋頂
    ("minecraft:polished_deepslate",           ( 78,  78,  84)),   # 屋脊
    # 告示牌（application/signage.py）：搭車告示牌、穿堂指引、出口牌都是淡色木頭
    ("minecraft:pale_oak_sign",                (226, 216, 212)),
    # 路線色帶（月台門門楣、軌道外側牆）：signage.band_block 挑的混凝土與陶瓦
    ("minecraft:red_concrete",                 (142,  33,  33)),   # 淡水信義線
    ("minecraft:orange_concrete",              (224,  97,   1)),   # 中和新蘆線
    ("minecraft:light_blue_concrete",          ( 36, 137, 199)),   # 板南線
    ("minecraft:green_concrete",               ( 73,  91,  36)),   # 松山新店線
    ("minecraft:purple_concrete",              (100,  32, 156)),   # 機場捷運
    ("minecraft:cyan_concrete",                ( 21, 119, 136)),   # 三鶯線
    ("minecraft:orange_terracotta",            (162,  84,  38)),   # 文湖線
    ("minecraft:yellow_terracotta",            (186, 133,  35)),   # 環狀線
    ("minecraft:white_terracotta",             (210, 178, 161)),   # 安坑、淡海輕軌
]
NAME2C = {n: i for i, (n, _) in enumerate(PALETTE)}
NC = 4096                        # 顏色索引的容量（鍵值 = (y+YOFF)*NC + 索引）
UNKNOWN = NC - 1                 # 洋紅：手填配色沒有、遊戲材質也算不出來的方塊
COLOR_LIST = [c for _, c in PALETTE]
BG = (18, 20, 26)
YOFF = 100                       # 讓 y 恆為正，才能打包進鍵值

# 手填配色以外的方塊（景點建築一次用上上百種）：從裝好的遊戲材質算平均色
# （tools/blockcolors.py）。算不出來的才畫洋紅 —— 洋紅仍然代表「這個方塊沒有顏色」，
# 不是「沒列進手填表」
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_BC = None
AUTO = set()                     # 靠遊戲材質上色的方塊


def color_index(name):
    global _BC
    i = NAME2C.get(name)
    if i is not None:
        return i
    if _BC is None:
        from blockcolors import BlockColors
        _BC = BlockColors()
    rgb = _BC.rgb(name, "top") if _BC.available or _BC.table else None
    if rgb is None or len(COLOR_LIST) >= NC - 1:
        NAME2C[name] = UNKNOWN
        return UNKNOWN
    COLOR_LIST.append(tuple(int(v) for v in rgb))
    NAME2C[name] = len(COLOR_LIST) - 1
    AUTO.add(name)
    return NAME2C[name]


def unpack(data, bits, n=4096):
    per = 64 // bits
    out = np.zeros(n, dtype=np.int64)
    arr = np.asarray(data, dtype=np.uint64)
    mask = np.uint64((1 << bits) - 1)
    for slot in range(per):
        vals = (arr >> np.uint64(slot * bits)) & mask
        tgt = np.arange(slot, n, per)
        out[tgt] = vals[:len(tgt)]
    return out


def region_files(rdir):
    for p in sorted(glob.glob(os.path.join(rdir, "r.*.mca"))):
        m = re.match(r"r\.(-?\d+)\.(-?\d+)\.mca$", os.path.basename(p))
        if m:
            yield p, int(m.group(1)), int(m.group(2))


def iter_chunks(rdir):
    """保留舊介面：逐一產出 chunk 的 NBT root。"""
    for p, _, _ in region_files(rdir):
        raw = open(p, "rb").read()
        if len(raw) < 8192:
            continue
        for i in range(1024):
            off = int.from_bytes(raw[i*4:i*4+3], "big")
            if off == 0:
                continue
            q = off * 4096
            ln = int.from_bytes(raw[q:q+4], "big")
            comp = raw[q+4]
            blob = raw[q+5:q+4+ln]
            data = zlib.decompress(blob) if comp == 2 else blob
            root = nbtlib.File.parse(io.BytesIO(data))
            yield root[''] if '' in root else root


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save"); ap.add_argument("out")
    ap.add_argument("--scale", type=int, default=4, help="每像素幾公尺")
    ap.add_argument("--bbox", nargs=4, type=int, metavar=("X0", "Z0", "X1", "Z1"),
                    help="只畫這個範圍（Minecraft 座標），用來出局部特寫")
    a = ap.parse_args()
    rdir = os.path.join(a.save, "dimensions/minecraft/overworld/region")

    files = list(region_files(rdir))
    if not files:
        raise SystemExit(f"{rdir} 下沒有區域檔")
    rxs = [r[1] for r in files]; rzs = [r[2] for r in files]
    x0, x1 = min(rxs) * 512, (max(rxs) + 1) * 512 - 1
    z0, z1 = min(rzs) * 512, (max(rzs) + 1) * 512 - 1
    if a.bbox:
        bx0, bz0, bx1, bz1 = a.bbox
        x0, z0, x1, z1 = min(bx0, bx1), min(bz0, bz1), max(bx0, bx1), max(bz0, bz1)
        files = [f for f in files
                 if f[1] * 512 <= x1 and (f[1] + 1) * 512 > x0
                 and f[2] * 512 <= z1 and (f[2] + 1) * 512 > z0]
        print(f"局部特寫：只處理 {len(files)} 個區域檔")
    s = a.scale
    W = (x1 - x0) // s + 1; H = (z1 - z0) // s + 1
    key = np.zeros(H * W, dtype=np.int64)        # (y+YOFF)*NC + 顏色索引
    print(f"{len(files)} 個區域檔  X[{x0},{x1}] Z[{z0},{z1}] -> {W}x{H} px @ {s} m/px")

    seen = {}
    nch = 0
    for fi, (p, rx, rz) in enumerate(files, 1):
        raw = open(p, "rb").read()
        if len(raw) < 8192:
            continue
        for i in range(1024):
            off = int.from_bytes(raw[i*4:i*4+3], "big")
            if off == 0:
                continue
            q = off * 4096
            ln = int.from_bytes(raw[q:q+4], "big")
            comp = raw[q+4]
            blob = raw[q+5:q+4+ln]
            root = nbtlib.File.parse(io.BytesIO(
                zlib.decompress(blob) if comp == 2 else blob))
            root = root[''] if '' in root else root
            nch += 1
            bx, bz = int(root["xPos"]) * 16, int(root["zPos"]) * 16

            best_y = np.full((16, 16), -9999, dtype=np.int64)     # [z, x]
            best_c = np.zeros((16, 16), dtype=np.int64)
            for sec in root["sections"]:
                bs = sec["block_states"]
                pal = [str(e["Name"]) for e in bs["palette"]]
                if len(pal) == 1 and pal[0] == "minecraft:air":
                    continue
                base = int(sec["Y"]) * 16
                idx = (unpack(bs["data"], max(4, (len(pal) - 1).bit_length()))
                       if "data" in bs else np.zeros(4096, dtype=np.int64))
                cmap = np.array([color_index(n) for n in pal], dtype=np.int64)
                for n in pal:
                    if n != "minecraft:air":
                        seen[n] = seen.get(n, 0) + 1
                codes = cmap[idx].reshape(16, 16, 16)             # [y, z, x]
                solid = codes != 0
                if not solid.any():
                    continue
                top = 15 - np.argmax(solid[::-1], axis=0)         # [z, x]
                has = solid.any(axis=0)
                yabs = base + top
                upd = has & (yabs > best_y)
                if upd.any():
                    pick = np.take_along_axis(codes, top[None], axis=0)[0]
                    best_y = np.where(upd, yabs, best_y)
                    best_c = np.where(upd, pick, best_c)

            ok = best_y > -9999
            if not ok.any():
                continue
            zz, xx = np.nonzero(ok)
            wx = bx + xx; wz = bz + zz
            keep = (wx >= x0) & (wx <= x1) & (wz >= z0) & (wz <= z1)
            if not keep.any():
                continue
            zz, xx, wx, wz = zz[keep], xx[keep], wx[keep], wz[keep]
            px = (wx - x0) // s
            pz = (wz - z0) // s
            flat = pz * W + px
            k = (best_y[zz, xx] + YOFF) * NC + best_c[zz, xx]
            np.maximum.at(key, flat, k)
        if fi % 50 == 0 or fi == len(files):
            print(f"  [{fi}/{len(files)}] {nch:,} 區塊")

    img = np.zeros((H * W, 3), dtype=np.uint8); img[:] = BG
    hit = key > 0
    ys = key[hit] // NC - YOFF
    cs = key[hit] % NC
    shade = (0.55 + 0.45 * np.clip((ys - 55) / 120.0, 0, 1))[:, None]
    colors = np.zeros((NC, 3), dtype=np.uint8)
    colors[:len(COLOR_LIST)] = COLOR_LIST
    colors[UNKNOWN] = (255, 0, 255)
    img[hit] = (colors[cs] * shade).astype(np.uint8)
    Image.fromarray(img.reshape(H, W, 3)).save(a.out)

    print(f"\n讀入 {nch:,} 區塊，出現的方塊種類：")
    for n, c in sorted(seen.items(), key=lambda kv: -kv[1])[:20]:
        mark = ("   <-- 沒有顏色（洋紅）" if NAME2C.get(n) == UNKNOWN
                else "   （遊戲材質配色）" if n in AUTO else "")
        print(f"  {n:<45} {c:>8} 個 section{mark}")
    none = sorted(n for n in seen if NAME2C.get(n) == UNKNOWN)
    if AUTO:
        print(f"另有 {len(AUTO)} 種方塊不在手填配色裡，照遊戲材質上色")
    if none:
        print(f"⚠ {len(none)} 種方塊算不出顏色、畫成洋紅：" + "、".join(none))
    if _BC is not None:
        _BC.save()
    print(f"已輸出 {a.out}")


if __name__ == "__main__":
    main()
