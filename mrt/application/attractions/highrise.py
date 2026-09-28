#!/usr/bin/env python3
"""Shared parts for skyscrapers (Taipei 101, Shin Kong Life Tower).

Per-story mass masks, shells, floor lamps, doors, spheres and trees.

kit.Painter's walls/fill suit "extrude one outline to one height"; skyscrapers do not
work that way. Each of Taipei 101's eight modules flares outward by 7° and its base
tapers inward, while Shin Kong's corners set back story by story. The approach here
is to compute the mask **per story**: for each y, ask once "what does this story's
floor plate look like" (a boolean array on the Frame). The shell is the outer ring of
that story's mask, and the top of an overhang is the set of cells "present on this
story but not on the one above".
On a slope the outer ring moves by one cell every few rows, so the rings of adjacent
stories touch only at diagonal corners. Where the ring moves, shell() includes the
outer rings of both the story above and the story below, so no light leaks through
the facade.

This module holds only parts and has no BUILDS (the attractions are registered in
taipei101.py and shin_kong.py).
"""
import math

import numpy as np

from mrt.application.attractions import kit

AIR = kit.AIR


# ---------------------------------------------------------------- Outlines and coordinates

def outline_axes(poly):
    """Return (center x, center z, angle in radians, half-length u, half-width v) of an outline.

    Angle: multiply each edge's direction by 4 (folding perpendicular edges onto one
    direction), take the length-weighted mean, then divide by 4.
    kit.principal_angle rounds to whole degrees, which would round away Taipei 101's
    1.0° and Shin Kong's −0.6°; this function needs the fraction. The center is the
    center of the bounding rectangle after squaring up, not the vertex mean: the
    notched corners have more vertices and would bias the mean."""
    sx = sy = 0.0
    n = len(poly)
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        L = math.hypot(x2 - x1, z2 - z1)
        a = 4.0 * math.atan2(z2 - z1, x2 - x1)
        sx += L * math.cos(a)
        sy += L * math.sin(a)
    ang = math.atan2(sy, sx) / 4.0
    c, s = math.cos(ang), math.sin(ang)
    x0 = sum(p[0] for p in poly) / n
    z0 = sum(p[1] for p in poly) / n
    us = [(x - x0) * c + (z - z0) * s for x, z in poly]
    vs = [-(x - x0) * s + (z - z0) * c for x, z in poly]
    mu, mv = (min(us) + max(us)) / 2, (min(vs) + max(vs)) / 2
    return (x0 + mu * c - mv * s, z0 + mu * s + mv * c, ang,
            (max(us) - min(us)) / 2, (max(vs) - min(vs)) / 2)


SNAP_DEG = 1.5          # Towers skewed by less than 1.5° are squared up (see snap_angle).


def snap_angle(ang, deg=SNAP_DEG):
    """Return 0 if the skew is under deg degrees, otherwise return the angle unchanged.

    Returning 0 squares the tower to the block grid. Taipei 101 is skewed 1.0° and
    Shin Kong −0.6°: across facades with half-lengths of 27 m and 23 m, the two ends
    differ by only 0.5 m and 0.3 m, the same order as the 1 m rounding error of a
    block. Without squaring up, every one-cell setback of a slope and every mullion a
    few cells apart draws a slanted zigzag across the facade (the whole of Taipei 101's
    base and eight modules did). Once squared up, each setback becomes a level ring,
    like real floor lines. The position (center) stays as in OSM."""
    return 0.0 if abs(math.degrees(ang)) <= deg else ang


def rotate_poly(poly, cx, cz, ang):
    """Rotate a polygon about (cx, cz) by ang radians (from +x toward +z)."""
    c, s = math.cos(ang), math.sin(ang)
    return [(cx + (x - cx) * c - (z - cz) * s, cz + (x - cx) * s + (z - cz) * c) for x, z in poly]


def notched_radius(fr, n, du=0.0, dv=0.0):
    """Return the "radius field" R of a square plan with two notched steps at each corner.

    Each step is n meters; R <= a lies inside the plan of half-width a.
    Taipei 101's corners are not right angles but two inward sawtooth steps (Structure
    magazine: a 2.5 m notch). Let m = max(|u|, |v|) and s = min(|u|, |v|). A cell whose
    distances to the two faces, p = a - |u| and q = a - |v|, are both below 2n, with one
    of them below n, is cut away; working backward gives
    R = max(m, min(m + n, s + 2n)). When the half-width a varies with height, the notch
    size stays the same."""
    u, v = np.abs(fr.U - du), np.abs(fr.V - dv)
    m, s = np.maximum(u, v), np.minimum(u, v)
    return np.maximum(m, np.minimum(m + n, s + 2 * n))


def face_coords(fr, du=0.0, dv=0.0):
    """Return (t, side) for laying out mullions and ornaments on the facades.

    t is the coordinate measured along the nearest facade (v on the east and west
    faces, u on the north and south faces), and side is the distance from the center
    (max(|u|, |v|))."""
    u, v = fr.U - du, fr.V - dv
    ew = np.abs(u) >= np.abs(v)
    return np.where(ew, v, u), np.maximum(np.abs(u), np.abs(v))


# ---------------------------------------------------------------- Writing

def paint(w, fr, mask, y, block):
    """Set (x, y, z) to block for every cell in the mask."""
    s = w.set
    for x, z in zip(fr.X[mask].tolist(), fr.Z[mask].tolist()):
        s(x, y, z, block)


def paint_layers(w, fr, layers, y):
    """Write [(mask, block)] in order: later entries overwrite earlier ones."""
    for m, b in layers:
        if m is not None and m.any():
            paint(w, fr, m, y, b)


def shell(M, Mp=None, Mn=None):
    """Return this story's shell cells.

    The shell is the outer ring of M plus the cells "in the outer ring of the story
    above or below, adjacent to this story's ring".
    On a slope, the outer rings of adjacent stories are offset by one cell and touch
    only at diagonal corners. This is invisible from outside, but light leaks in and a
    player can squeeze through. Counting the cells of the rings above and below that
    are adjacent to this ring as wall makes the offset spots two cells thick. Where the
    setback is large (a podium roof meeting the tower), the rings are not adjacent, so
    no extra ring is built."""
    rg = kit.ring(M)
    near = kit.dilate(rg, 1)
    out = rg.copy()
    for other in (Mp, Mn):
        if other is not None:
            out |= M & kit.ring(other) & near
    return out


def grid_mask(fr, step, off=0, du=0.0, dv=0.0):
    """Return a dot grid, one cell every step meters in local coordinates (lamps, trees, posts)."""
    return ((np.floor(fr.U - du).astype(int) % step) == off) & \
           ((np.floor(fr.V - dv).astype(int) % step) == off)


def sphere(w, cx, cy, cz, r, block):
    """Place a solid sphere around the float center (cx, cy, cz).

    A cell is filled if its center lies within the radius."""
    for x in range(int(math.floor(cx - r)), int(math.ceil(cx + r)) + 1):
        for y in range(int(math.floor(cy - r)), int(math.ceil(cy + r)) + 1):
            for z in range(int(math.floor(cz - r)), int(math.ceil(cz + r)) + 1):
                if (x + .5 - cx) ** 2 + (y + .5 - cy) ** 2 + (z + .5 - cz) ** 2 <= r * r:
                    w.set(x, y, z, block)


def door(w, x, y, z, facing, block="minecraft:waxed_copper_door", hinge="left"):
    """Place a door (two blocks tall).

    facing is a kit.cardinal direction name: the opposite of the direction a player
    faces when walking in from outside."""
    st = "[facing=%s,half=%%s,hinge=%s,open=false,powered=false]" % (facing, hinge)
    w.set(x, y, z, block + st % "lower")
    w.set(x, y + 1, z, block + st % "upper")


LEAVES = "minecraft:oak_leaves[distance=1,persistent=true,waterlogged=false]"
LOG = "minecraft:oak_log[axis=y]"


def tree(w, x, gy, z, trunk=4, r=2.6, leaves=LEAVES, log=LOG):
    """Place a street tree: a trunk of trunk blocks and a flattened-sphere crown of radius r.

    The leaves are persistent, so they do not decay."""
    for y in range(gy + 1, gy + trunk + 1):
        w.set(x, y, z, log)
    cy = gy + trunk + 1.0
    ri = int(math.ceil(r))
    for dx in range(-ri, ri + 1):
        for dz in range(-ri, ri + 1):
            for dy in range(-2, 3):
                if (dx * dx + dz * dz) / (r * r) + (dy * dy) / 4.0 <= 1.0 and not (dx == 0 and dz == 0 and dy < 0):
                    w.set(x + dx, int(cy) + dy, z + dz, leaves)


def dome(mask, rise):
    """Return a dome heightfield over an arbitrary plan.

    It rises with distance from the edge along a quarter-circle profile: 0 at the edge,
    rise at the deepest point."""
    d = kit.depth(mask).astype(float)
    top = d.max() if d.any() else 1.0
    return rise * np.sqrt(np.clip(1.0 - (1.0 - d / top) ** 2, 0.0, 1.0))


def glyph(rows):
    """Convert a dot-matrix string to [(row, column)] (X is solid; row 0 is at the top).

    Facade ornaments (the ruyi and the ancient coins) are drawn with it."""
    out = []
    for i, row in enumerate(rows):
        for j, ch in enumerate(row):
            if ch == "X":
                out.append((i, j))
    return out
