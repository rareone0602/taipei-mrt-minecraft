#!/usr/bin/env python3
"""Parts for traditional Chinese buildings: tiled roofs, ridges (chiwen, swallowtail),
gable pediments, arched gateways, crenellations and stone balustrades.

Shared by the city gates (city_gates.py) and Bangka Longshan Temple (longshan_temple.py).
kit.py supplies the shapes (masks, roof heightfields); this module turns them into blocks
that read as Chinese architecture:

  tile_roof    Roof heightfield -> tiled roof. The top layer of each slope uses stair
               blocks (facing upslope) and slabs; barrel tiles run down the slope row by
               row, alternating two materials. The shell thickens with the slope, so the
               steep part (the upper section of the juzhe curve) lets no light through.
               A further layer under the eaves takes the dougong/rafter color.
  corner_lift  Adds upturned corners to a slope computed by the caller (pent roofs,
               lower eaves).
  ridge_line   Stacks blocks along a polyline in local coordinates (dragon bodies,
               short ridges).
  seg_mask     Cells within half a block of a line segment, so a diagonal ridge stays one
               block wide instead of becoming a two-block-wide sawtooth.
  swallowtail  Minnan-style swallowtail ridge: the main ridge rises at both ends,
               projects past the gable walls and forks at the tip.
  chiwen       The chiwen ornaments at both ends of a northern palace-style main ridge.
  gable_face   The gable pediment of a xieshan (hip-and-gable) roof.
  cut_arch     A semicircular arched passage; the two upper corners of the arch are
               rounded with upside-down stairs.
  plaque_sign  The text on a name board (a wall sign placed on the cardinal neighbor of
               the board).
  walls_conn / panes_conn
               Connection states for stone balustrades (wall blocks) and iron bars: blocks
               written to the save do not update their own connections.

The module has no BUILDS, so the registry scan adds no attraction for it. It only calls
set() on a Painter or BlockSink.
"""
import math

import numpy as np

from mrt.application.attractions import kit

AIR = kit.AIR

# Tiles: for each roof, two alternating rows of (full block, stair prefix, slab prefix).
# Green glazed tiles (the northern palace-style roofs of the East Gate, South Gate and
# Little South Gate, rebuilt in 1966; blue-green in photographs).
GREEN_TILES = (("minecraft:prismarine_bricks", "prismarine_brick", "prismarine_brick"),
               ("minecraft:waxed_oxidized_cut_copper", "waxed_oxidized_cut_copper",
                "waxed_oxidized_cut_copper"))
# Orange-red Minnan tiles (North Gate, Longshan Temple): waxed cut copper (which does not
# oxidize green) alternating with resin bricks.
ORANGE_TILES = (("minecraft:waxed_cut_copper", "waxed_cut_copper", "waxed_cut_copper"),
                ("minecraft:resin_bricks", "resin_brick", "resin_brick"))


def stairs(prefix, facing, half="bottom"):
    """Stair block string. facing is the direction of ascent (on a roof: upslope, toward
    the ridge)."""
    return "minecraft:%s_stairs[facing=%s,half=%s,shape=straight,waterlogged=false]" % (
        prefix, facing, half)


def slab(prefix, kind="bottom"):
    """Slab block string (kind: bottom for the lower half, top for the upper half)."""
    return "minecraft:%s_slab[type=%s,waterlogged=false]" % (prefix, kind)


# ---------------------------------------------------------------- Tiled roofs

def _grad(S, mask, axis):
    """Central difference within the mask; a one-sided difference where only one neighbor
    is in the mask, and 0 where neither is."""
    fwd, fm = np.roll(S, -1, axis), np.roll(mask, -1, axis)
    bwd, bm = np.roll(S, 1, axis), np.roll(mask, 1, axis)
    return np.where(fm & bm, (fwd - bwd) / 2.0,
                    np.where(fm, fwd - S, np.where(bm, S - bwd, 0.0)))


def tile_roof(p, mask, y_eave, h, tiles, shell=2, under=None, under_mask=None, steep=0.3,
              ridge_full=0.12):
    """Lay a roof heightfield as a tiled roof.

    y_eave   Block y of the ring of tiles at the eaves (where h = 0 the roof top is at
             y_eave + 1).
    h        Heightfield returned by kit.hip / hip_gable / gable / pyramid (meters,
             eaves = 0).
    tiles    Sequence of (full block, stair prefix, slab prefix), used in alternate rows.
    shell    Minimum shell thickness. It grows automatically where the upslope neighbor
             is much higher, so the sides let no light through.
    under    Material for one more block under the shell (dougong brackets and rafters
             under the eaves); under_mask limits which cells get it.
    Returns the block y of the roof top in each cell (an array, -999 outside the mask),
    used to align ridges and gable pediments.
    """
    fr = p.fr
    S = y_eave + 1 + np.asarray(h, dtype=float)
    S = np.broadcast_to(S, fr.shape)
    H = np.where(mask, S, np.nan)
    # Upslope direction: differences use only neighbors inside the mask, so the air
    # beyond a flush-gable wall does not skew the edge.
    gz, gx = _grad(S, mask, 0), _grad(S, mask, 1)
    # Largest drop to a neighbor: sets the shell thickness.
    dmax = np.zeros(fr.shape)
    for dz, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nb = np.roll(np.roll(H, dz, axis=0), dx, axis=1)
        d = np.abs(np.nan_to_num(nb - H, nan=0.0))
        dmax = np.maximum(dmax, d)
    tops = np.full(fr.shape, -999, dtype=np.int32)
    idx = np.argwhere(mask)
    s = p.w.set
    for i, j in idx:
        x, z = int(fr.X[i, j]), int(fr.Z[i, j])
        sv = float(S[i, j])
        n = int(math.floor(sv))
        f = sv - n
        ax, az = float(gx[i, j]), float(gz[i, j])
        slope = math.hypot(ax, az)
        # Barrel tiles run down the slope: rows alternate by z on an east- or west-facing
        # slope, and by x on a north- or south-facing one.
        k = (z if abs(ax) > abs(az) else x) % len(tiles)
        full, st, sl = tiles[k]
        cap = None
        if f < 0.25:
            top = n - 1
        elif f < 0.75:
            top = n - 1
            if slope >= steep:
                cap = stairs(st, kit.cardinal(ax, az))
            else:
                cap = slab(sl)
        else:
            top = n
        if slope < ridge_full and f >= 0.25:
            top, cap = n, None                                # Full blocks along the ridge, no row of slabs
        top = max(top, y_eave)
        thick = max(shell, int(math.ceil(dmax[i, j])) + 1)
        lo = max(y_eave, top - thick + 1)
        for y in range(lo, top + 1):
            s(x, y, z, full)
        if cap is not None:
            s(x, n, z, cap)
            tops[i, j] = n
        else:
            tops[i, j] = top
        if under is not None and (under_mask is None or under_mask[i, j]):
            s(x, lo - 1, z, under)
    return tops


def corner_lift(fr, a, b, lift, du=0.0, dv=0.0):
    """Heightfield of the upturned corners of the rectangle |u-du|<=a, |v-dv|<=b (the same
    formula as the lift in kit.hip), for roofs whose slopes the caller computes itself
    (pent roofs, lower eaves)."""
    u, v = np.abs(fr.U - du), np.abs(fr.V - dv)
    d = np.minimum(a - u, b - v).clip(0, None)
    return kit._lift(u, v, a, b, lift, None, d)


# ---------------------------------------------------------------- Ridges

def ridge_line(p, pts, block, step=0.25, thick=1, cells=None):
    """Stack blocks along the local polyline [(u, v, y), ...]. y is a float and is floored.
    thick: how many blocks to stack downward at each point (a ridge has thickness). Given
    a set as cells, the function only records the cells and writes nothing (the caller
    merges them)."""
    out = set()
    for (u0, v0, y0), (u1, v1, y1) in zip(pts[:-1], pts[1:]):
        L = math.hypot(u1 - u0, v1 - v0) + abs(y1 - y0)
        n = max(1, int(math.ceil(L / step)))
        for t in range(n + 1):
            a = t / float(n)
            u, v, y = u0 + (u1 - u0) * a, v0 + (v1 - v0) * a, y0 + (y1 - y0) * a
            x, z = p.fr.cell(u, v)
            yi = int(math.floor(y))
            for k in range(thick):
                out.add((x, yi - k, z))
    if cells is not None:
        cells |= out
        return out
    for x, y, z in out:
        p.set(x, y, z, block)
    return out


def top_at(tops, fr, u, v):
    """Top y of the roof in the cell at local (u, v) (from tile_roof's return value); None
    outside the mask."""
    x, z = fr.cell(u, v)
    i, j = z - fr.z0, x - fr.x0
    if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] and tops[i, j] > -999:
        return int(tops[i, j])
    return None


def seg_mask(fr, u0, v0, u1, v1, half=0.5):
    """Cells whose centers lie within `half` of the local segment (u0, v0)-(u1, v1) ->
    (mask, parameter t along the segment, 0..1). Diagonal ridges pick their cells this way
    and stay one block wide per row; sampling point by point turns into a two-block-wide
    sawtooth once the frame is rotated."""
    du, dv = u1 - u0, v1 - v0
    L2 = du * du + dv * dv or 1e-9
    t = (((fr.U - u0) * du + (fr.V - v0) * dv) / L2).clip(0, 1)
    d = np.hypot(fr.U - (u0 + t * du), fr.V - (v0 + t * dv))
    return d <= half, t


def swallowtail(p, L, y, block, ext=1.6, rise=2.2, tip=None, dv=0.0, body=2, fork=0.7, half=0.5):
    """Minnan-style swallowtail ridge: a main ridge along u from -L to L (top at y, body
    blocks thick). Over the last quarter at each end it rises gradually, then projects
    ext meters further and turns up rise meters, and the tip forks in two (the swallow's
    tail).
    tip: material for the last section of the tail (jiannian mosaic often finishes in a
    dark or colored piece); None means the same as block.
    Cells are picked as those within half a block of the ridge line, so the ridge is one
    block wide at any angle."""
    fr = p.fr
    c = max(1.5, 0.3 * L)
    au = np.abs(fr.U)
    off = np.abs(fr.V - dv)
    line = (off < half) & (au <= L + ext)
    forks = (off >= half) & (off < half + 0.8) & (au > L + ext - fork) & (au <= L + ext)
    cells = {}
    for sel, extra in ((line, 0), (forks, 1)):
        for i, j in np.argwhere(sel):
            a = float(au[i, j])
            k = max(0.0, (a - (L - c)) / (c + ext))
            yi = int(math.floor(y + rise * k ** 2)) + extra
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            blk = tip if (tip and a > L + ext * 0.4) else block
            for q in range(body if (extra == 0 and a <= L) else 1):
                cells[(x, yi - q, z)] = blk
    for (x, yy, z), blk in cells.items():
        p.set(x, yy, z, blk)
    return cells


def chiwen(p, u, v, y, block, inward, h=2, accent=None):
    """The chiwen at each end of a northern palace-style main ridge: h blocks stacked on
    the ridge end, with the top curling one block toward the inside of the ridge.
    inward = +1 / -1: whether the inside of the ridge lies toward +u or -u."""
    x, z = p.fr.cell(u, v)
    for k in range(h):
        p.set(x, y + k, z, block)
    xi, zi = p.fr.cell(u + inward * 0.9, v)
    p.set(xi, y + h - 1, zi, accent or block)
    xo, zo = p.fr.cell(u - inward * 0.9, v)
    p.set(xo, y, zo, block)


def gable_face(p, cells_mask, tops, y_top_fn, fill, border=None, center=None):
    """Gable pediment of a xieshan roof: fill the row of cells in cells_mask from the roof
    top (tops) up to y_top_fn(i, j).
    border: the top block of each column (the bargeboard); center: ornament on the upper
    half of the center line (a hanging-fish ornament or floral motif)."""
    fr = p.fr
    for i, j in np.argwhere(cells_mask):
        t0 = int(tops[i, j]) if tops[i, j] > -999 else None
        t1 = int(y_top_fn(i, j))
        if t0 is None or t1 <= t0:
            continue
        x, z = int(fr.X[i, j]), int(fr.Z[i, j])
        for y in range(t0 + 1, t1 + 1):
            blk = fill
            if border is not None and y == t1:
                blk = border
            p.set(x, y, z, blk)
    if center is not None:
        center()


# ---------------------------------------------------------------- Arched gateways

def arch_halfwidth(hc, w, spring):
    """Half-width of a semicircular arch hc meters above the floor (below the springing
    height the sides are straight walls)."""
    r = w / 2.0
    if hc <= spring:
        return r
    d = hc - spring
    return math.sqrt(r * r - d * d) if d < r else -1.0


def arch_rows(w, spring):
    """Per-layer (layer number k (0 for the first block above the floor), half-width at
    the block center, half-width at the block bottom) of an arched passage."""
    out = []
    k = 0
    while True:
        hc = arch_halfwidth(k + 0.5, w, spring)
        hb = arch_halfwidth(k + 0.02, w, spring)
        if hb < 0:
            break
        out.append((k, hc, hb))
        k += 1
    return out


def cut_arch(p, sel, U0, y_floor, w, spring, wall_facing=None, stair_block=None, ring=None,
             ring_block=None, ceil_y=None):
    """Cut a semicircular arch within the mask sel (the passage). U0 is each cell's distance
    from the arch center line (|U - uc|).
    y_floor is the floor surface (the block a person stands in). The two upper corners of
    the arch are rounded with upside-down stairs (stair_block is the stair prefix;
    wall_facing(i, j) -> the stair's facing). ring: the arch ring (the band one block
    further out) is written with ring_block.
    ceil_y: this block (usually the floor slab on top of the gate platform) and those
    above it are not hollowed out; only upside-down stairs may go in it (their upper half
    is still solid)."""
    fr = p.fr
    rows = arch_rows(w, spring)
    for i, j in np.argwhere(sel):
        x, z = int(fr.X[i, j]), int(fr.Z[i, j])
        du = float(U0[i, j])
        for k, hc, hb in rows:
            y = y_floor + k
            if ceil_y is not None and y > ceil_y:
                break
            if du <= hc + 0.05 and (ceil_y is None or y < ceil_y):
                p.set(x, y, z, AIR)
            elif k + 0.5 > spring and du <= hb + 0.45 and stair_block and wall_facing:
                p.set(x, y, z, stairs(stair_block, wall_facing(i, j), "top"))
    if ring is not None and ring_block:
        rows2 = arch_rows(w + 2.0, spring)
        top = {k: hc for k, hc, hb in rows}
        for i, j in np.argwhere(ring):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            du = float(U0[i, j])
            for k, hc, hb in rows2:
                inner = top.get(k, -1.0)
                if du <= hc + 0.05 and du > inner + 0.45:
                    p.set(x, y_floor + k, z, ring_block)


# ---------------------------------------------------------------- Wall block connections

def walls_conn(cells, name, tall=False):
    """A set of (x, y, z) wall blocks -> {(x, y, z): block string}, with each of the four
    connections set by whether the neighbor is a wall. Wall blocks written to the save do
    not update their own connections; without this, every one would stand as an isolated
    post."""
    cs = set(cells)
    out = {}
    lvl = "tall" if tall else "low"
    for x, y, z in cs:
        side = {}
        for d, (dx, dz) in (("east", (1, 0)), ("west", (-1, 0)), ("south", (0, 1)), ("north", (0, -1))):
            side[d] = lvl if (x + dx, y, z + dz) in cs else "none"
        straight = (side["east"] != "none" and side["west"] != "none" and side["north"] == "none"
                    and side["south"] == "none") or (side["north"] != "none" and side["south"] != "none"
                                                     and side["east"] == "none" and side["west"] == "none")
        up = "false" if straight else "true"
        out[(x, y, z)] = "minecraft:%s[east=%s,north=%s,south=%s,up=%s,waterlogged=false,west=%s]" % (
            name, side["east"], side["north"], side["south"], up, side["west"])
    return out


STEP = {"east": (1, 0), "west": (-1, 0), "south": (0, 1), "north": (0, -1)}


def plaque_sign(p, u, v, y, face, lines, wood="dark_oak", glow=True, color="black"):
    """Text on a name board: the cell at local (u, v) is the board (the wall face), and the
    sign hangs on its cardinal neighbor on the face side (a local direction). A wall sign
    attaches only to the block directly behind it."""
    x, z = p.fr.cell(u, v)
    card = kit.cardinal(*p.fr.dir(*face))
    dx, dz = STEP[card]
    p.w.sign(x + dx, y, z + dz, lines, facing=(dx, dz), wood=wood, kind="wall", glow=glow, color=color)
    return (x + dx, y, z + dz)


def panes_conn(cells, name):
    """A set of (x, y, z) iron bars (or glass panes) -> {(x, y, z): block string}, with the
    four connections set from the neighbors."""
    cs = set(cells)
    out = {}
    for x, y, z in cs:
        side = {d: ("true" if (x + dx, y, z + dz) in cs else "false")
                for d, (dx, dz) in (("east", (1, 0)), ("west", (-1, 0)), ("south", (0, 1)), ("north", (0, -1)))}
        out[(x, y, z)] = "minecraft:%s[east=%s,north=%s,south=%s,waterlogged=false,west=%s]" % (
            name, side["east"], side["north"], side["south"], side["west"])
    return out


def edge_coord(fr, i, j, a, b):
    """The coordinate of a ring cell along its own edge: U near a long edge (|V| close to
    b), V near a short edge. Crenellation and balustrade patterns follow it, so each of
    the four edges is continuous."""
    u, v = float(fr.U[i, j]), float(fr.V[i, j])
    return u if (b - abs(v)) <= (a - abs(u)) else v
