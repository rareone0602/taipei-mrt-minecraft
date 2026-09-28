#!/usr/bin/env python3
"""Read the region files of a finished world save back independently and render a
top-down map, to check the geometry instead of trusting the generator.

Fully vectorized: a world with full terrain has hundreds of millions of blocks, and a
per-block Python loop would never finish. Each column keeps only its highest non-air
block, packing (height, color) into a single key and scanning with maximum.

Usage: ./.venv/bin/python tools/verify_render.py <save_dir> <out.png> [--scale M]
"""
import os, io, glob, sys, zlib, argparse, re
import numpy as np, nbtlib
from PIL import Image

PALETTE = [
    ("minecraft:air",                          (  0,   0,   0)),
    ("minecraft:smooth_stone",                 (196, 200, 205)),   # Track bed
    ("minecraft:gray_concrete",                ( 88,  93, 100)),   # Guide wall
    ("minecraft:light_gray_concrete",          (150, 155, 160)),   # Deck / roof
    ("minecraft:polished_andesite",            (120, 110,  98)),   # Pier
    ("minecraft:polished_diorite",             (235, 235, 230)),   # Platform
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
    ("minecraft:smooth_sandstone",             (222, 206, 158)),   # Station building facade
    ("minecraft:bricks",                       (170,  92,  74)),   # Red-brick clay tile roof
    ("minecraft:white_concrete",               (232, 232, 232)),   # White roof trim / paving
    ("minecraft:black_concrete",               ( 30,  30,  34)),   # Checkerboard hall floor
    ("minecraft:deepslate_tiles",              ( 62,  62,  68)),   # Palace-style roof
    ("minecraft:polished_deepslate",           ( 78,  78,  84)),   # Roof ridge
    # Signs (application/signage.py): ride signs, concourse directions and exit signs
    # are all pale wood.
    ("minecraft:pale_oak_sign",                (226, 216, 212)),
    # Line color bands (PSD headers, outer track walls): the concrete and terracotta
    # that signage.band_block picks.
    ("minecraft:red_concrete",                 (142,  33,  33)),   # Tamsui-Xinyi Line
    ("minecraft:orange_concrete",              (224,  97,   1)),   # Zhonghe-Xinlu Line
    ("minecraft:light_blue_concrete",          ( 36, 137, 199)),   # Bannan Line
    ("minecraft:green_concrete",               ( 73,  91,  36)),   # Songshan-Xindian Line
    ("minecraft:purple_concrete",              (100,  32, 156)),   # Taoyuan Airport MRT
    ("minecraft:cyan_concrete",                ( 21, 119, 136)),   # Sanying Line
    ("minecraft:orange_terracotta",            (162,  84,  38)),   # Wenhu Line
    ("minecraft:yellow_terracotta",            (186, 133,  35)),   # Circular Line
    ("minecraft:white_terracotta",             (210, 178, 161)),   # Ankeng and Danhai LRT
]
NAME2C = {n: i for i, (n, _) in enumerate(PALETTE)}
NC = 4096                        # Capacity of the color index (key = (y+YOFF)*NC + index)
UNKNOWN = NC - 1                 # Magenta: a block that neither the hand-picked palette nor the
                                 # game textures can color.
COLOR_LIST = [c for _, c in PALETTE]
BG = (18, 20, 26)
YOFF = 100                       # Keeps y positive so that it can be packed into the key.

# Blocks outside the hand-picked palette (an attraction building uses a hundred or more
# at once) get the average color of the installed game's textures (tools/blockcolors.py).
# Only a block whose color cannot be computed is drawn magenta, so magenta still means
# "this block has no color", not "this block is missing from the hand-picked table".
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_BC = None
AUTO = set()                     # Blocks colored from the game textures.


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
    """Yield the NBT root of each chunk in turn (kept for the old interface)."""
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
    ap.add_argument("--scale", type=int, default=4, help="Metres per pixel")
    ap.add_argument("--bbox", nargs=4, type=int, metavar=("X0", "Z0", "X1", "Z1"),
                    help="Draw only this area (Minecraft coordinates), for a close-up")
    a = ap.parse_args()
    rdir = os.path.join(a.save, "dimensions/minecraft/overworld/region")

    files = list(region_files(rdir))
    if not files:
        raise SystemExit(f"No region files in {rdir}")
    rxs = [r[1] for r in files]; rzs = [r[2] for r in files]
    x0, x1 = min(rxs) * 512, (max(rxs) + 1) * 512 - 1
    z0, z1 = min(rzs) * 512, (max(rzs) + 1) * 512 - 1
    if a.bbox:
        bx0, bz0, bx1, bz1 = a.bbox
        x0, z0, x1, z1 = min(bx0, bx1), min(bz0, bz1), max(bx0, bx1), max(bz0, bz1)
        files = [f for f in files
                 if f[1] * 512 <= x1 and (f[1] + 1) * 512 > x0
                 and f[2] * 512 <= z1 and (f[2] + 1) * 512 > z0]
        print(f"Close-up: reading {len(files)} region files")
    s = a.scale
    W = (x1 - x0) // s + 1; H = (z1 - z0) // s + 1
    key = np.zeros(H * W, dtype=np.int64)        # (y+YOFF)*NC + color index
    print(f"{len(files)} region files  X[{x0},{x1}] Z[{z0},{z1}] -> {W}x{H} px @ {s} m/px")

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
            print(f"  [{fi}/{len(files)}] {nch:,} chunks")

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

    print(f"\nRead {nch:,} chunks. Block types found (top 20):")
    for n, c in sorted(seen.items(), key=lambda kv: -kv[1])[:20]:
        mark = ("   <-- no colour (magenta)" if NAME2C.get(n) == UNKNOWN
                else "   (coloured from game textures)" if n in AUTO else "")
        print(f"  {n:<45} {c:>8} sections{mark}")
    none = sorted(n for n in seen if NAME2C.get(n) == UNKNOWN)
    if AUTO:
        print(f"{len(AUTO)} other block types are not in the hand-picked palette "
              "and are coloured from the game textures")
    if none:
        print(f"warning: {len(none)} block types have no computable colour "
              "and are drawn magenta: " + ", ".join(none))
    if _BC is not None:
        _BC.save()
    print(f"Wrote {a.out}")


if __name__ == "__main__":
    main()
