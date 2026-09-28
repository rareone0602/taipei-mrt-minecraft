#!/usr/bin/env python3
"""Terrain and vertical-profile generation services.

The full terrain does not fit in memory, so it is processed in batches by region
(512x512 blocks): sample points are bucketed by region, and each region in turn
gets its terrain generated, its structures built, its file written and its memory
released.

Terrain is generated only inside the line corridors. At the outer edge a distance
field blends it back to a flat sea level, so the corridor boundary does not become
a vertical cliff.

The streaming batch logic and the composition root live in cli/build_world.py.
This module keeps only the reusable parts: vertical-profile planning (profile), the
corridor blend field (blend_field) and terrain chunk assembly (terrain_chunk).

The first parameter of terrain_chunk, ch, is a ports.block_sink.ChunkSink.
"""

import numpy as np

from mrt import config
from mrt.domain import tunnel_layers as TL
from mrt.domain.alignment import MAX_GRADE, STEP
from mrt.domain.terrain import SEA_Y

OFFSET   = {"bridge": 13, "ground": 1, "tunnel": -20}   # Track bed relative to the ground.

# Each line gets its own depth. If every line were at the same level, the tunnels
# and station boxes of two lines at an interchange such as Taipei Main Station or
# Zhongxiao Fuxing would break into each other and form one cavity over a hundred
# meters wide.
#
# The depths are not arbitrary. The underground segments of each line are first
# rasterized onto a 60 m grid to find which lines actually cross:
#   G-O, O-R, BL-G, G-R, BL-R, G-Y
# That graph is then three-colored, so every pair of lines that really crosses
# lands on a different level.
# An exit stair needs 2 m of horizontal run for every 1 m of drop, so the deepest
# line has a 76 m stair. The stairs run outside the station box at off 13 to 17
# and are not limited by the platform length.
# The station box is now a two-level box structure (platform level plus concourse
# level), 13 blocks tall at dy -2 to 10, so the levels need to be 15 m apart to
# avoid overlapping. The old 10 m spacing only fit a single platform level.
# Tunnel depth is no longer one constant per line; see tunnel_layers.py.
# Each line normally runs in the shallowest band and dives only where it has to
# cross another line, so 65% of the network's tunnels stay 15 m underground
# instead of the whole line being dug as deep as its deepest crossing.
# This constant is only a fallback for when assign_bands() gives no result.
TUNNEL_FALLBACK = -20
SMOOTH_M = 400        # The profile first smooths out terrain noise over a few hundred meters.
FLAT_Y   = SEA_Y + 2  # Default ground outside the corridors, matching the superflat level.dat.
                      # It must be above sea level, or the whole blend ring is classed as beach
                      # and paved with sand.
BLEND_CELL = 8        # Distance field resolution, in meters.

BEDROCK, STONE, DIRT = "minecraft:bedrock", "minecraft:stone", "minecraft:dirt"
GRASS, SAND, WATER, AIR = ("minecraft:grass_block", "minecraft:sand",
                           "minecraft:water", "minecraft:air")


def moving_avg(a, win):
    if win < 2 or len(a) < win:
        return np.asarray(a, dtype=np.float64)
    pad = win // 2
    ext = np.concatenate([np.full(pad, a[0]), a, np.full(pad, a[-1])])
    return np.convolve(ext, np.ones(win) / win, mode="same")[pad:pad + len(a)]


def profile(samples, terr, ref=None, band=None):
    """Return a vertical profile that follows the real ground, limited by the maximum grade.

    band is the per-point depth band from tunnel_layers.assign_bands() (-1 means the
    point is not underground). The grade envelope below automatically turns each band
    change into a 4% slope, so it needs no separate handling: the 15 m band spacing
    becomes a 375 m descent, about as long as a real grade-separated crossing.
    """
    xs = np.array([s[0] for s in samples]); zs = np.array([s[1] for s in samples])
    ground = terr.y_at(xs, zs)
    g = moving_avg(ground.astype(np.float64), int(SMOOTH_M / STEP))
    kinds = [s[4] for s in samples]
    base = np.array([OFFSET.get(k, 1) for k in kinds], dtype=np.float64)
    if band is not None:
        base = np.where(np.asarray(band) >= 0, TL.band_depth(band), base)
    else:
        base = np.where(np.array([k == "tunnel" for k in kinds]),
                        TUNNEL_FALLBACK, base)
    tgt = g + base
    y = tgt.copy()
    d = MAX_GRADE * STEP
    for i in range(1, len(y)):                       # Lower envelope, two linear passes.
        if y[i] > y[i - 1] + d: y[i] = y[i - 1] + d
    for i in range(len(y) - 2, -1, -1):
        if y[i] > y[i + 1] + d: y[i] = y[i + 1] + d
    return np.round(y).astype(int), ground


def runs(mask, min_len):
    """Return the runs of True, dropping runs that are too short.

    Gaps shorter than min_len/2 inside a run are absorbed into it.

    Returns [(start, end)] with end exclusive. When the inner loop stops, j points
    just past the last cell examined; subtracting the trailing gap gives the end of
    this run. The next run is scanned from j + gap. An earlier version added 1 more,
    so the first cell after every gap was skipped: a run following a gap of exactly
    min_len/2 lost one cell, and if that one cell put it under the threshold, the
    whole run disappeared.
    """
    out, i, n = [], 0, len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        gap = 0
        while j < n and gap < min_len // 2:
            gap = 0 if mask[j] else gap + 1
            j += 1
        j -= gap
        if j - i >= min_len:
            out.append((i, j))
        i = j + gap
    return out


def blend_field(pts, rx, rz, inner, outer):
    """Map each cell's distance to the line within a region to a terrain weight (1 = full terrain, 0 = flat)."""
    ox, oz = rx * 512, rz * 512
    n = 512 // BLEND_CELL
    g = (np.arange(n) + 0.5) * BLEND_CELL
    GZ, GX = np.meshgrid(oz + g, ox + g, indexing="ij")
    d2 = np.full((n, n), 1e18)
    for sx, sz in pts:
        np.minimum(d2, (GX - sx) ** 2 + (GZ - sz) ** 2, out=d2)
    d = np.sqrt(d2)
    return np.clip((outer - d) / max(1.0, outer - inner), 0.0, 1.0)


def surface_y(terr, blend, rx, rz, XX, ZZ):
    """Return the y of the terrain surface (the grass block).

    Inside the corridors this is the real terrain; farther out it blends back to
    FLAT_Y according to blend.

    terrain_chunk builds terrain with this. The spawn point uses the same formula to
    find the height of the ground at the door, without reading the world save. A
    blend of None gives the real terrain with no blending.
    """
    XX, ZZ = np.asarray(XX), np.asarray(ZZ)
    H = terr.y_at(XX, ZZ).astype(np.float64)
    if blend is not None:
        bi = ((XX - rx * 512) // BLEND_CELL).clip(0, blend.shape[1] - 1)
        bj = ((ZZ - rz * 512) // BLEND_CELL).clip(0, blend.shape[0] - 1)
        f = blend[bj.astype(int), bi.astype(int)]
        H = H * f + FLAT_Y * (1 - f)
    return np.round(H).astype(np.int32)


def terrain_chunk(ch, cx, cz, terr, blend, rx, rz):
    """Assemble the terrain of a whole chunk at once with numpy."""
    xs = np.arange(cx * 16, cx * 16 + 16)
    zs = np.arange(cz * 16, cz * 16 + 16)
    ZZ, XX = np.meshgrid(zs, xs, indexing="ij")
    H = surface_y(terr, blend, rx, rz, XX, ZZ)

    names = [AIR, BEDROCK, STONE, DIRT, GRASS, SAND, WATER]
    A, B, S, D, G, SD, W = range(7)
    for sy in range(config.SEC_MIN, config.SEC_MAX + 1):
        yy = np.arange(16).reshape(16, 1, 1) + sy * 16
        H3 = H[None, :, :]
        beach = H3 <= SEA_Y + 1
        code = np.where(yy > H3, A,
               np.where(yy == H3, np.where(beach, SD, G),
               np.where(yy >= H3 - 3, np.where(beach, SD, D), S)))
        code = np.where((yy > H3) & (yy <= SEA_Y), W, code)      # Fill with water below sea level.
        code = np.where(yy == -64, B, code)
        # An all-air section must also be written if it lies within the height of
        # the superflat background layers. When the world save is written, any
        # section never written is filled back with the background layers (grass at
        # y=64). If all-air sections above the rivers were skipped, a layer of grass
        # at y=64 would float over the Keelung and Tamsui rivers, with air below it
        # and the water below that.
        if (code != A).any() or sy * 16 <= FLAT_Y:
            ch.set_section(sy, code, names)
