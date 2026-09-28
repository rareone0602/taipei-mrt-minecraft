#!/usr/bin/env python3
"""Read an area back from a world save and draw elevations, top-down and isometric
views, to see whether the finished buildings look like the real ones.

verify_render draws only a top-down map. It shows whether a plan is right, but not
whether Taipei 101's eight flared sections, the octagonal pyramidal roof of the Chiang
Kai-shek Memorial Hall or the central tower of the Presidential Office Building came out
askew. This tool draws the blocks on disk:

  south / north / east / west   Orthographic elevation, viewed from that side. Farther
                                blocks are darker and outlines are darkened. A y scale
                                runs down the left (a tick every 10 blocks, a label
                                every 50).
  top                           Top-down view: the highest block in each column,
                                shaded by height.
  iso                           Isometric view from above the southeast, with the
                                three faces in three brightnesses.

Colors are computed from the installed game textures (tools/blockcolors.py). Blocks
whose color cannot be computed are drawn magenta and listed at the end.

Usage:
    ./.venv/bin/python tools/render_view.py <save> --bbox X0 Z0 X1 Z1 [--y0 60 --y1 639] \\
        --out <prefix> [--views south,east,iso,top] [--scale 2]
Writes <prefix>_<view>.png.
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
SEE_THROUGH = 0.12          # Coverage below this (iron bars and less) counts as see-through.


def palette(vol, bc):
    """Volume palette -> (top colors [n,3], side colors [n,3], blocks sight [n] bool,
    names with no color)."""
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
    """Find the first sight-blocking cell along axis and return (index, hit or not).
    reverse=True looks from the high end."""
    m = solid_vox if not reverse else np.flip(solid_vox, axis=axis)
    hit = m.any(axis=axis)
    idx = m.argmax(axis=axis)
    if reverse:
        idx = m.shape[axis] - 1 - idx
    return idx, hit


def ruler(img, y0, y1, scale, margin):
    """Draw a y scale down the left: a short tick every 10 blocks and a long tick with a
    number every 50."""
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
        if view == "east":                                # Looking west, north (-z) is on the right.
            blk, depth, hit = blk[:, ::-1], depth[:, ::-1], hit[:, ::-1]
        dmax = vol.nx
    col = side[blk]
    shade = 1.0 - 0.55 * (depth / max(1, dmax - 1))
    col = col * shade[..., None]
    # Outline: darken where the depth differs from a neighbor by 3 blocks or more.
    dd = np.zeros(depth.shape, dtype=bool)
    dd[:, 1:] |= np.abs(np.diff(depth, axis=1)) >= 3
    dd[1:, :] |= np.abs(np.diff(depth, axis=0)) >= 3
    col[dd & hit] *= 0.6
    col[~hit] = BG
    img = np.flipud(col).clip(0, 255).astype(np.uint8)      # Higher y at the top.
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
    """Isometric view from above the southeast (+x, +z, +y). Each cell is drawn as a tile
    2s wide: the top face in the upper half, the +z face at lower left and the +x face at
    lower right. A larger depth key x+z+y is nearer, and maximum.at acts as the z-buffer."""
    top, side, solid, _ = pal
    data = vol.data
    sol = solid[data]
    # Draw only visible cells: at least one face exposed toward +x, +y or +z.
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
    ap.add_argument("--y1", type=int, default=None,
                    help="Defaults to 4 blocks above the highest block in the area")
    ap.add_argument("--out", required=True, help="Prefix for the output file names")
    ap.add_argument("--views", default="south,east,iso,top")
    ap.add_argument("--scale", type=int, default=2)
    a = ap.parse_args()
    x0, z0, x1, z1 = a.bbox
    y1 = a.y1 if a.y1 is not None else config.Y_MAX
    vol = SR.read_volume(a.save, x0, a.y0, z0, x1, y1, z1, verbose=False)
    if a.y1 is None:                                   # Trim the empty air above.
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
            print("Unknown view: " + v)
            continue
        path = "%s_%s.png" % (a.out, v)
        im.save(path)
        print("%-6s %4dx%-4d -> %s" % (v, im.size[0], im.size[1], path))
    print("Area x%d..%d z%d..%d y%d..%d, %d block types"
          % (x0, x1, z0, z1, vol.y0, vol.y1, len(vol.names)))
    if pal[3]:
        print("warning: no computable colour (drawn magenta): " + ", ".join(sorted(pal[3])))


if __name__ == "__main__":
    main()
