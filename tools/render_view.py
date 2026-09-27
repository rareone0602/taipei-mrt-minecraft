#!/usr/bin/env python3
"""從存檔讀回一塊範圍，畫立面圖、俯視圖、等角圖 —— 看蓋出來的建築長得像不像。

verify_render 只有俯視圖，看得出平面對不對，看不出台北101 的八節斗狀、
中正紀念堂的八角攢尖頂、總統府的中央塔有沒有蓋歪。這裡照磁碟上的方塊畫：

  south / north / east / west   正投影立面圖（從那一側看過去），深度越遠越暗，
                                輪廓線加深；左邊有 y 刻度（每 10 格一格、50 格一個標）
  top                           俯視圖（每柱最高的方塊，依高度加陰影）
  iso                           等角圖（從東南方上空看），三個面三種亮度

顏色從裝好的遊戲材質算（tools/blockcolors.py）；算不出來的方塊畫成洋紅，
最後列出是哪些。

用法:
    ./.venv/bin/python tools/render_view.py <存檔> --bbox X0 Z0 X1 Z1 [--y0 60 --y1 639] \\
        --out <前綴> [--views south,east,iso,top] [--scale 2]
輸出 <前綴>_<視角>.png。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image, ImageDraw

from mrt import config
from mrt.infrastructure import savereader as SR
from blockcolors import BlockColors

BG = (24, 26, 32)
MAGENTA = (255, 0, 255)
SEE_THROUGH = 0.12          # 覆蓋率低於這個（鐵欄杆以下）的方塊當作看得穿


def palette(vol, bc):
    """Volume 的 palette -> (頂面色 [n,3], 側面色 [n,3], 擋視線 [n] bool, 缺色名單)。"""
    n = len(vol.names)
    top = np.zeros((n, 3), dtype=np.float32)
    side = np.zeros((n, 3), dtype=np.float32)
    solid = np.zeros(n, dtype=bool)
    missing = set()
    for i, name in enumerate(vol.names):
        if name.split("[")[0] in ("minecraft:air", "minecraft:cave_air", "minecraft:void_air"):
            continue
        t, s = bc.rgb(name, "top"), bc.rgb(name, "side")
        if t is None:
            missing.add(name.split("[")[0])
            t = s = MAGENTA
        top[i], side[i] = t, s
        solid[i] = bc.alpha(name) >= SEE_THROUGH
    return top, side, solid, missing


def first_hit(solid_vox, axis, reverse):
    """沿 axis 找第一個擋視線的格子：回傳 (索引, 有沒有打到)。reverse=True 從大的那端看。"""
    m = solid_vox if not reverse else np.flip(solid_vox, axis=axis)
    hit = m.any(axis=axis)
    idx = m.argmax(axis=axis)
    if reverse:
        idx = m.shape[axis] - 1 - idx
    return idx, hit


def ruler(img, y0, y1, scale, margin):
    """左邊畫 y 刻度：每 10 格一條短線，每 50 格一條長線加數字。"""
    d = ImageDraw.Draw(img)
    h = img.size[1]
    for y in range((y0 // 10) * 10, y1 + 1, 10):
        if y < y0:
            continue
        py = h - 1 - (y - y0) * scale
        long_ = y % 50 == 0
        d.line([(margin - (10 if long_ else 4), py), (margin - 1, py)], fill=(200, 200, 200))
        if long_:
            d.text((1, max(0, py - 10)), "y%d" % y, fill=(220, 220, 220))
    return img


def elevation(vol, pal, view, scale):
    top, side, solid, _ = pal
    data = vol.data                                     # [y][z][x]
    sol = solid[data]
    if view in ("south", "north"):
        idx, hit = first_hit(sol, axis=1, reverse=(view == "south"))   # [y][x]
        depth = (vol.nz - 1 - idx) if view == "south" else idx
        ys, xs = np.indices(idx.shape)
        blk = data[ys, idx, xs]
        if view == "north":
            blk, depth, hit = blk[:, ::-1], depth[:, ::-1], hit[:, ::-1]
        dmax = vol.nz
    else:
        idx, hit = first_hit(sol, axis=2, reverse=(view == "east"))    # [y][z]
        depth = (vol.nx - 1 - idx) if view == "east" else idx
        ys, zs = np.indices(idx.shape)
        blk = data[ys, zs, idx]
        if view == "east":                                # 往西看，右手邊是北（-z）
            blk, depth, hit = blk[:, ::-1], depth[:, ::-1], hit[:, ::-1]
        dmax = vol.nx
    col = side[blk]
    shade = 1.0 - 0.55 * (depth / max(1, dmax - 1))
    col = col * shade[..., None]
    # 輪廓：與鄰格深度差 3 格以上就加深
    dd = np.zeros(depth.shape, dtype=bool)
    dd[:, 1:] |= np.abs(np.diff(depth, axis=1)) >= 3
    dd[1:, :] |= np.abs(np.diff(depth, axis=0)) >= 3
    col[dd & hit] *= 0.6
    col[~hit] = BG
    img = np.flipud(col).clip(0, 255).astype(np.uint8)      # y 大的在上面
    im = Image.fromarray(img).resize((img.shape[1] * scale, img.shape[0] * scale), Image.NEAREST)
    margin = 40
    out = Image.new("RGB", (im.size[0] + margin, im.size[1]), BG)
    out.paste(im, (margin, 0))
    return ruler(out, vol.y0, vol.y1, scale, margin)


def topdown(vol, pal, scale):
    top, _, solid, _ = pal
    data = vol.data
    sol = solid[data]
    idx, hit = first_hit(sol, axis=0, reverse=True)          # [z][x]
    zs, xs = np.indices(idx.shape)
    blk = data[idx, zs, xs]
    col = top[blk]
    h = idx.astype(np.float32)
    lo, hi = (h[hit].min(), h[hit].max()) if hit.any() else (0, 1)
    col *= (0.55 + 0.45 * (h - lo) / max(1.0, hi - lo))[..., None]
    col[~hit] = BG
    img = col.clip(0, 255).astype(np.uint8)
    return Image.fromarray(img).resize((img.shape[1] * scale, img.shape[0] * scale), Image.NEAREST)


def iso(vol, pal, scale):
    """等角圖：從東南上空（+x、+z、+y）看。每格畫成 2s 寬的小方塊：上半頂面、
    左下 +z 面、右下 +x 面。深度鍵 x+z+y 越大越近，用 maximum.at 做 z-buffer。"""
    top, side, solid, _ = pal
    data = vol.data
    sol = solid[data]
    # 只畫看得到的格子：+x、+y、+z 三個方向至少有一面露出來
    exp = np.zeros_like(sol)
    exp[:-1] |= ~sol[1:]
    exp[-1] = True
    exp[:, :-1] |= ~sol[:, 1:]
    exp[:, -1] = True
    exp[:, :, :-1] |= ~sol[:, :, 1:]
    exp[:, :, -1] = True
    y, z, x = np.nonzero(sol & exp)
    if len(x) == 0:
        return Image.new("RGB", (64, 64), BG)
    s = scale
    W = (vol.nx + vol.nz) * s + 2 * s
    H = (vol.nx + vol.nz) * s // 2 + vol.ny * s + 2 * s
    px = (x - z + vol.nz) * s
    py = ((x + z) * s) // 2 + (vol.ny - 1 - y) * s
    key = (x + z + y).astype(np.int64)
    b = data[y, z, x]
    faces = [(top[b], 1.0, [(du, dv) for dv in range(s) for du in range(2 * s)]),
             (side[b], 0.62, [(du, dv) for dv in range(s, 2 * s) for du in range(s)]),
             (side[b], 0.80, [(du, dv) for dv in range(s, 2 * s) for du in range(s, 2 * s)])]
    buf = np.full(W * H, -1, dtype=np.int64)
    for col, shade, offs in faces:
        c = (col * shade).clip(0, 255).astype(np.int64)
        rgb = (c[:, 0] << 16) | (c[:, 1] << 8) | c[:, 2]
        packed = (key << 24) | rgb
        for du, dv in offs:
            np.maximum.at(buf, (py + dv) * W + (px + du), packed)
    rgb = buf & 0xFFFFFF
    img = np.stack([(rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255], axis=-1).astype(np.uint8)
    img[buf < 0] = BG
    return Image.fromarray(img.reshape(H, W, 3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save")
    ap.add_argument("--bbox", nargs=4, type=int, required=True, metavar=("X0", "Z0", "X1", "Z1"))
    ap.add_argument("--y0", type=int, default=56)
    ap.add_argument("--y1", type=int, default=None, help="預設到範圍裡最高的方塊上方 4 格")
    ap.add_argument("--out", required=True, help="輸出檔名前綴")
    ap.add_argument("--views", default="south,east,iso,top")
    ap.add_argument("--scale", type=int, default=2)
    a = ap.parse_args()
    x0, z0, x1, z1 = a.bbox
    y1 = a.y1 if a.y1 is not None else config.Y_MAX
    vol = SR.read_volume(a.save, x0, a.y0, z0, x1, y1, z1, verbose=False)
    if a.y1 is None:                                   # 切掉上面整片空氣
        nz_y = np.nonzero((vol.data != 0).any(axis=(1, 2)))[0]
        top_y = vol.y0 + (int(nz_y.max()) if len(nz_y) else 0)
        keep = min(vol.ny, top_y - vol.y0 + 5)
        vol.data = vol.data[:keep]
        vol.y1 = vol.y0 + keep - 1
        vol.ny = keep
    bc = BlockColors()
    pal = palette(vol, bc)
    bc.save()
    for v in a.views.split(","):
        v = v.strip()
        if v in ("south", "north", "east", "west"):
            im = elevation(vol, pal, v, a.scale)
        elif v == "top":
            im = topdown(vol, pal, a.scale)
        elif v == "iso":
            im = iso(vol, pal, a.scale)
        else:
            print("不認得的視角：" + v)
            continue
        path = "%s_%s.png" % (a.out, v)
        im.save(path)
        print("%-6s %4dx%-4d -> %s" % (v, im.size[0], im.size[1], path))
    print("範圍 x%d..%d z%d..%d y%d..%d，%d 種方塊" % (x0, x1, z0, z1, vol.y0, vol.y1, len(vol.names)))
    if pal[3]:
        print("⚠ 算不出顏色（畫成洋紅）：" + "、".join(sorted(pal[3])))


if __name__ == "__main__":
    main()
