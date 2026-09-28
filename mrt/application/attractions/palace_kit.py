#!/usr/bin/env python3
"""Shared parts for Chinese palace-style buildings: platforms, balustrades, half-step stairs,
roofs (hip with tuishan, xieshan, octagonal pyramidal, the lower eave of a double-eaved
roof), ridge and eave trim, dougong bands, finials, and the complete construction of a
double-eaved palace-style hall.

Shared by the Chiang Kai-shek Memorial Hall grounds (the memorial hall, the National
Theater, the National Concert Hall and the Liberty Square paifang) and the Sun Yat-sen
Memorial Hall. This module is not an attraction and has no BUILDS. Coordinates follow
kit.py (local u, v of a Frame; block (x, z) is centered at (x+.5, z+.5)), and every write
goes through the Painter the caller supplies (already wrapped in a Guard).

Heights: G is the y of the site's ground block (a person stands at G+1). "A standing
surface s meters high" means the feet are at G+1+s; when s is a multiple of 0.5, the
half block is a bottom slab.
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions.kit import Frame

AIR = kit.AIR


# ---------------------------------------------------------------- Frames and outlines

def local_bbox(fr, ring):
    """Polygon in world coordinates -> (u0, u1, v0, v1) in fr's local coordinates."""
    pts = [fr.local(x - 0.5, z - 0.5) for x, z in ring]   # local() measures cell centers; these are points
    us = [p[0] for p in pts]
    vs = [p[1] for p in pts]
    return min(us), max(us), min(vs), max(vs)


def ring_centroid(ring):
    """Area centroid of a polygon (world coordinates)."""
    a = cx = cz = 0.0
    n = len(ring)
    for i in range(n):
        x1, z1 = ring[i]
        x2, z2 = ring[(i + 1) % n]
        c = x1 * z2 - x2 * z1
        a += c
        cx += (x1 + x2) * c
        cz += (z1 + z2) * c
    if abs(a) < 1e-9:
        return sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n
    return cx / (3 * a), cz / (3 * a)


def sub_frame(fr, u, v, extent, turn=0.0):
    """A new frame with fr's orientation (turned a further turn radians) and its origin at
    fr's local (u, v)."""
    x, z = fr.world(u, v)
    return Frame(x, z, fr.angle + turn, extent)


# ---------------------------------------------------------------- Small write helpers

def steps(p, mask, g, s, block, slab):
    """Half-step stairs (or any standing surface): fill each cell of the mask up to the
    standing surface s (meters, a multiple of 0.5), solid from g+1 upward, with a bottom
    slab for the half block. Cells with s <= 0 are not written.
    slab may be given with or without [type=...] (Painter.heightfield adds [type=bottom]
    itself)."""
    m = mask & (np.asarray(s) > 0)
    slab_id = slab.split("[")[0] if slab else None
    p.heightfield(m, g + 1, np.asarray(s, dtype=float) - 1.0, block, slab=slab_id)


def half_flight(t, s0, n):
    """Standing surface of a flight of half steps: t is the distance upslope from the start
    of the flight (meters). The standing surface of cell k (k = floor(t)) is
    s0 + 0.5 (k+1), up to n steps. Returns s0 where t < 0."""
    k = np.floor(t)
    return np.where(t < 0, s0, s0 + 0.5 * (np.clip(k, -1, n - 1) + 1))


def balustrade(p, mask, y, rail, post, cap=None, every=3, skip=None):
    """Balustrade along the edge of a platform: the outer ring of the mask, one block wide
    and one block high, with a baluster post (post) every `every` cells topped by cap
    (such as a quartz slab), half a block higher than the panels. Cells in the skip mask
    are left open (stair openings). y may be an integer or an array (a handrail rising
    along a stair)."""
    rg = kit.ring(mask)
    if skip is not None:
        rg &= ~skip
    Y = np.broadcast_to(np.asarray(y), p.fr.shape)
    X, Z, YY = p.fr.X[rg].tolist(), p.fr.Z[rg].tolist(), np.rint(Y[rg]).astype(int).tolist()
    for x, z, yy in zip(X, Z, YY):
        if (x + 2 * z) % every == 0:
            p.set(x, yy, z, post)
            if cap:
                p.set(x, yy + 1, z, cap)
        else:
            p.set(x, yy, z, rail)


def band(p, mask, y0, y1, a, b, period=2):
    """Dougong band: each cell of the mask from y0 to y1, alternating blocks a and b along
    the cells (from a distance it reads as rows of dougong brackets)."""
    X, Z = p.fr.X[mask].tolist(), p.fr.Z[mask].tolist()
    for x, z in zip(X, Z):
        blk = a if ((x + z) // period) % 2 == 0 else b
        for y in range(int(y0), int(y1) + 1):
            p.set(x, y, z, blk)


def sphere(p, u, v, y, r, block, y_min=None):
    """Solid sphere of radius r centered at local (u, v) and height y (a float, measured at
    cell centers). Used for finials."""
    fr = p.fr
    near = np.hypot(fr.U - u, fr.V - v) <= r + 0.5
    X, Z, UU, VV = fr.X[near].tolist(), fr.Z[near].tolist(), fr.U[near].tolist(), fr.V[near].tolist()
    for x, z, uu, vv in zip(X, Z, UU, VV):
        d2 = (uu - u) ** 2 + (vv - v) ** 2
        for yy in range(int(math.floor(y - r)), int(math.ceil(y + r)) + 1):
            if y_min is not None and yy < y_min:
                continue
            if d2 + (yy + 0.5 - y) ** 2 <= r * r:
                p.set(x, yy, z, block)


def fine_angle(ring):
    """Principal direction of an outline (radians, 0–90°): the circular mean of the side
    directions, folded into 90° and weighted by side length. kit.principal_angle rounds to
    whole degrees, which turns the Sun Yat-sen Memorial Hall's 1.65° into 2°: a 0.6 m
    difference between the ends of a 100 m side."""
    sx = sy = 0.0
    n = len(ring)
    for i in range(n):
        x1, z1 = ring[i]
        x2, z2 = ring[(i + 1) % n]
        L = math.hypot(x2 - x1, z2 - z1)
        a = math.atan2(z2 - z1, x2 - x1) * 4.0          # Fourfold symmetry: 0°, 90°, 180° and 270° coincide
        sx += L * math.cos(a)
        sy += L * math.sin(a)
    return (math.atan2(sy, sx) / 4.0) % (math.pi / 2)


def seated_statue(p, cu, cv, y0, face, body, chair):
    """Seated bronze statue (about 6 m high): chair, legs, robe, hands and head, assembled
    from a few ellipsoids and boxes.
    (cu, cv) is the center of the statue (local coordinates), face the local direction it
    faces (du, dv), and y0 the block at the base of the seat.
    Shared by the statue of Chiang Kai-shek in the Chiang Kai-shek Memorial Hall (6.3 m
    seated) and the statue of Sun Yat-sen in the Sun Yat-sen Memorial Hall (5.8 m for the
    figure)."""
    fr = p.fr
    fu, fv = face
    n = math.hypot(fu, fv)
    fu, fv = fu / n, fv / n
    du, dv = fr.U - cu, fr.V - cv
    near = np.hypot(du, dv) <= 5.0
    b = -(du * fu + dv * fv)                 # Positive toward the back (the chair back)
    l = -du * fv + dv * fu                   # Left-right
    X, Z = fr.X[near].tolist(), fr.Z[near].tolist()
    for x, z, u, v in zip(X, Z, b[near].tolist(), l[near].tolist()):
        av = abs(v)
        for k in range(0, 7):
            yy = k + 0.5
            blk = None
            if -0.5 <= u <= 2.2 and av <= 2.6 and yy <= 1.0:
                blk = chair                                            # Seat
            if 1.5 <= u <= 2.4 and av <= 2.6 and yy <= 4.6:
                blk = chair                                            # Chair back
            if -0.8 <= u <= 1.8 and 1.8 < av <= 2.6 and 1.0 <= yy <= 2.0:
                blk = chair                                            # Armrests
            if -2.6 <= u <= 0.8 and av <= 1.6 and 1.0 <= yy <= 2.1:
                blk = body                                             # Thighs
            if -2.9 <= u <= -1.7 and av <= 1.6 and yy <= 1.2:
                blk = body                                             # Shins and shoes
            if ((u - 0.6) / 1.2) ** 2 + (v / 1.7) ** 2 + ((yy - 3.1) / 1.5) ** 2 <= 1.0:
                blk = body                                             # Torso (robe)
            if -1.4 <= u <= 0.9 and 1.4 < av <= 2.3 and 2.0 <= yy <= 3.3:
                blk = body                                             # Arms
            if (u - 0.5) ** 2 + v ** 2 + (yy - 5.3) ** 2 <= 0.95:
                blk = body                                             # Head
            if blk:
                p.set(x, y0 + k, z, blk)


# ---------------------------------------------------------------- Roof heightfields
#
# Like the roofs in kit, these return arrays of height above the eaves, plus a ridge mask
# (the main ridge and the hip or diagonal ridges) on which roof() adds a ridge.

def hip_ridge(fr, a, b, rise, ridge, profile=1.0, lift=0.0, corner=None, du=0.0, dv=0.0):
    """Hip roof with the main ridge along u and half-length ridge (tuishan: the end slopes
    are steeper than the front and back slopes, which lengthens the main ridge).
    kit.hip always runs the main ridge along the long side. The National Theater's roof is
    deeper than it is wide, yet its main ridge runs parallel to the front, so it needs
    this function."""
    u, v = np.abs(fr.U - du), np.abs(fr.V - dv)
    t_long = ((b - v) / b).clip(0, 1)                     # Front and back slopes: fraction of the way to the eaves
    t_end = ((a - u) / (a - ridge)).clip(0, 1)            # End slopes
    t = np.minimum(t_long, t_end)
    h = rise * t ** profile
    d = np.minimum(a - u, b - v).clip(0, None)
    h = h + kit._lift(u, v, a, b, lift, corner, d)
    # Hip ridges: where the two slope fractions are equal (within 0.6 m of that line).
    # Main ridge: v≈0, |u|<=ridge.
    k = b / (a - ridge)
    hips = np.abs((b - v) - (a - u) * k) / math.hypot(1.0, k) <= 0.6
    main = (v <= 0.6) & (u <= ridge + 0.5)
    ridge_m = (hips | main) & (u <= a) & (v <= b)
    return h, ridge_m


def hip_gable(fr, a, b, rise, gable_in, profile=1.0, lift=0.0, corner=None, du=0.0, dv=0.0):
    """Xieshan roof (kit.hip_gable) with a ridge mask and a gable pediment mask.

    Returns (h, ridges, pediment). The pediment is the one-block-wide vertical triangular
    wall just inside |u| = a - gable_in (in that row the heightfield jumps straight from
    the height of the short end slopes to that of the long slopes)."""
    h = kit.hip_gable(fr, a, b, rise, gable_in, profile, lift, corner, du, dv)
    u, v = np.abs(fr.U - du), np.abs(fr.V - dv)
    ug = a - gable_in
    main = (v <= 0.6) & (u <= ug + 0.5)
    # Diagonal ridges: where the short end slopes meet the front and back slopes
    # ((b - v) equals (a - u)), only outside the pediment.
    hips = (np.abs((b - v) - (a - u)) / math.sqrt(2.0) <= 0.6) & (u > ug)
    # Vertical ridges: from the edges of the pediment down along the front and back
    # slopes.
    verge = (np.abs(u - ug) <= 0.6) & (v <= b)
    gable = (u <= ug) & (u > ug - 1.0) & (v < b * 0.95)
    inside = (u <= a) & (v <= b)
    return h, (main | hips | verge) & inside, gable & inside


def octagon(fr, r, rise, profile=1.0, lift=0.0, du=0.0, dv=0.0):
    """Octagonal pyramidal roof (kit.pyramid with sides=8, one side facing +u squarely) with
    a mask of its eight hip ridges."""
    h = kit.pyramid(fr, r, rise, sides=8, rot=0.0, profile=profile, lift=lift, du=du, dv=dv)
    u, v = fr.U - du, fr.V - dv
    ds = np.stack([u * math.cos(2 * math.pi * k / 8) + v * math.sin(2 * math.pi * k / 8)
                   for k in range(8)])
    top2 = np.sort(ds, axis=0)[-2:]
    hips = (top2[1] - top2[0]) <= 0.55
    return h, hips


def skirt(fr, a_out, b_out, a_in, b_in, rise, profile=1.0, lift=0.0, corner=None):
    """Lower eave of a double-eaved roof: rises from the eaves of the outer rectangle
    |u|<=a_out, |v|<=b_out inward to the foot of the inner rectangle's walls (the upper
    storey); the inside of the inner rectangle is excluded. Returns (h, mask)."""
    u, v = np.abs(fr.U), np.abs(fr.V)
    w = min(a_out - a_in, b_out - b_in)
    d = np.minimum(a_out - u, b_out - v).clip(0, None)
    h = rise * (d / w).clip(0, 1) ** profile + kit._lift(u, v, a_out, b_out, lift, corner, d)
    m = (u <= a_out) & (v <= b_out) & ~((u < a_in) & (v < b_in))
    return h, m


# ---------------------------------------------------------------- Writing heightfields as roofs

def roof(p, mask, base, h, tile, shell=2, under=None, rim=None, rim_under=None,
         ridge=None, ridge_mask=None, cap_ridge=True, rim_w=2):
    """Roof shell: the top of each cell is floor(base + h), extending shell blocks down.
    Where a neighbor is lower, the shell extends down to meet the lowest of the four
    neighbors (so steep steps such as a gable pediment or the junction of two roof tiers
    leave no gaps).

    under     One block below the shell (the color of the rafters or ceiling under the
              eaves).
    rim       Top block of the outermost ring at the eaves. rim_under is the block below
              the top in the outer rim_w rings (the fascia board). The outer ring of a
              rotated frame is jagged; replacing only one ring would show the second ring
              of tiles between the white edges from the front, so the fascia is two rings
              wide by default.
    ridge     Ridge: cells in ridge_mask get one more block on top (cap_ridge=False only
              changes the material).
    Returns the array of top heights (int; a very small number outside the mask), for
    placing ridge beasts and finials."""
    fr = p.fr
    T = np.full(fr.shape, -10 ** 6, dtype=np.int64)
    B = np.broadcast_to(np.asarray(base, dtype=float), fr.shape)
    H = np.broadcast_to(np.asarray(h, dtype=float), fr.shape)
    T[mask] = np.floor(B[mask] + H[mask]).astype(np.int64)
    big = 10 ** 6
    Tn = np.where(mask, T, big)
    low = Tn.copy()
    low[1:, :] = np.minimum(low[1:, :], Tn[:-1, :])
    low[:-1, :] = np.minimum(low[:-1, :], Tn[1:, :])
    low[:, 1:] = np.minimum(low[:, 1:], Tn[:, :-1])
    low[:, :-1] = np.minimum(low[:, :-1], Tn[:, 1:])
    lo = np.minimum(T - shell + 1, low + 1)
    none = np.zeros(fr.shape, dtype=bool)
    rimm = kit.ring(mask) if rim is not None else none
    rimu = kit.ring(mask, rim_w) if rim_under is not None else none
    rm = ridge_mask if (ridge is not None and ridge_mask is not None) else none
    X, Z = fr.X[mask].tolist(), fr.Z[mask].tolist()
    TT, LL = T[mask].tolist(), lo[mask].tolist()
    RI, RU, RG = rimm[mask].tolist(), rimu[mask].tolist(), rm[mask].tolist()
    s = p.set
    for x, z, t, l, ri, ru, rg in zip(X, Z, TT, LL, RI, RU, RG):
        for y in range(l, t + 1):
            s(x, y, z, tile)
        if under is not None:
            s(x, l - 1, z, under)
        if ru:
            s(x, t - 1, z, rim_under)
        if ri:
            s(x, t, z, rim)
        elif rg:
            if cap_ridge:
                s(x, t + 1, z, ridge)
            else:
                s(x, t, z, ridge)
    return T


def gable_panel(p, mask, T_face, T_low, block, border=None):
    """Gable pediment of a xieshan roof: within the mask (the row of pediment cells), blocks
    from the top of the outer end slope T_low+1 up to this row's top T_face-1 become block
    (the triangular pediment board); the top block is left for border."""
    X, Z = p.fr.X[mask].tolist(), p.fr.Z[mask].tolist()
    A, B = T_face[mask].tolist(), T_low[mask].tolist()
    for x, z, t, lo in zip(X, Z, A, B):
        for y in range(int(lo) + 1, int(t)):
            p.set(x, y, z, block)
        if border is not None and t - lo >= 2:
            p.set(x, int(t), z, border)


# ---------------------------------------------------------------- Double-eaved palace-style hall
#
# The National Theater and the National Concert Hall (designed by Yang Cho-cheng, 1987):
# a cross-shaped plan, with a deep central main hall and shallow wings on either side. The
# main hall is double-eaved (hip or xieshan above, a lower eave below); the wings are
# single-eaved. Red columns, dougong brackets, yellow glazed tiles, a white platform and
# balustrade, and a grand staircase at the front. Proportions measured from public
# photographs (a front view of the Concert Hall, scaled by its frontage of about 104 m):
# platform about 5 m, column tops about 15 m, lower eaves about 18–19 m, upper eaves
# about 25 m, main ridge 37 m (OSM height=37, roof:height=12).

class HallSpec:
    """Dimensions of a double-eaved palace-style hall (local coordinates, front facing -v).

    ca, cb   Half-frontage and half-depth of the central main hall (roof drip line)
    wa, wb   Half-length to the outer end of the wings, and half-depth of the wings
    sw, sd   Half-width and depth of the grand staircase at the front (outward from the
             front of the main hall)
    roof     "hip" (wudian) or "hip_gable" (xieshan)
    ridge    Half-length of the main ridge (hip with tuishan), or of the xieshan main ridge
             (the position of the gable pediments)
    """

    def __init__(self, ca, cb, wa, wb, sw, sd, roof, ridge,
                 plat=5, col_top=14, low_eave=18, wing_eave=17, up_eave=25, top=37):
        self.ca, self.cb, self.wa, self.wb = ca, cb, wa, wb
        self.sw, self.sd = sw, sd
        self.roof, self.ridge = roof, ridge
        self.plat, self.col_top = plat, col_top
        self.low_eave, self.wing_eave, self.up_eave, self.top = low_eave, wing_eave, up_eave, top


PALACE = dict(
    tile="minecraft:honeycomb_block",              # Yellow glazed tiles (orange-gold in photographs)
    ridge="minecraft:yellow_glazed_terracotta",    # Ridges, ridge beasts
    column="minecraft:red_concrete",               # Red columns
    wall="minecraft:white_terracotta",             # Wall behind the columns (pale orange-pink)
    window="minecraft:yellow_glazed_terracotta",   # Gold square windows in the wall
    door="minecraft:brown_stained_glass",          # Main door
    beam="minecraft:cyan_glazed_terracotta",       # Architrave (blue-green painted decoration)
    bracket="minecraft:dark_prismarine",           # Dougong brackets, underside of the eaves
    red="minecraft:red_terracotta",                # Red fascia at the eaves, upper storey
    base="minecraft:polished_diorite",             # Platform
    floor="minecraft:smooth_stone",                # Platform surface
    rail="minecraft:smooth_quartz",                # White balustrade
    post="minecraft:quartz_pillar",
    cap="minecraft:smooth_quartz_slab[type=bottom]",
    stair="minecraft:polished_andesite",           # Granite steps
    stair_slab="minecraft:polished_andesite_slab",
    gable="minecraft:blue_glazed_terracotta",      # Gable pediment board
    plaque="minecraft:lapis_block",                # Name board (porcelain-blue ground)
    gold="minecraft:gold_block",
)


def palace_hall(w, fr, spec, g, mat=None):
    """Build a double-eaved palace-style hall on fr (front facing -v). g is the y of the
    site's ground block."""
    M = dict(PALACE)
    M.update(mat or {})
    p = kit.Painter(w, fr)
    S = spec
    au, av = np.abs(fr.U), np.abs(fr.V)
    V = fr.V

    central = (au <= S.ca) & (av <= S.cb)
    wing = (au <= S.wa) & (av <= S.wb)
    stairs = (au <= S.sw + 1) & (V < -S.cb) & (V >= -S.cb - S.sd)
    plat = central | wing

    # ---- Platform: solid, pale gray stone outside, stone slabs on top
    y_top = g + S.plat
    p.fill(plat, g + 1, y_top - 1, M["base"])
    p.layer(plat, y_top, M["floor"])
    balustrade(p, plat, y_top + 1, M["rail"], M["post"], M["cap"],
               skip=(au <= S.sw + 1.5) & (V < -S.cb + 2))

    # ---- Grand staircase at the front: half steps rising toward +v to the platform
    run = S.sd
    n = 2 * S.plat
    tread = run / n
    t = (V - (-S.cb - S.sd)) / tread
    s = np.where(t >= n, float(S.plat), 0.5 * (np.floor(t) + 1))
    body = stairs & (au <= S.sw)
    steps(p, body, g, s, M["stair"], M["stair_slab"])
    cheek = stairs & (au > S.sw)
    p.fill(cheek, g + 1, g + np.ceil(s).astype(int), M["base"])
    balustrade(p, cheek | ((au > S.sw) & (au <= S.sw + 1) & (V >= -S.cb) & (V < -S.cb + 1)),
               g + np.ceil(s).astype(int) + 1, M["rail"], M["post"], M["cap"], every=2)

    # ---- Colonnade: 3.5 m inside the main hall's drip line and 3 m inside the wings';
    # about one column every 6.5 m, with a wider central bay
    y0, y1 = y_top + 1, g + S.col_top
    pts = []
    vf = S.cb - 3.5
    n_c = max(2, int(round(2 * (S.ca - 2.5) / 6.5)) + 1)
    for k in range(n_c):
        u = -(S.ca - 2.5) + 2 * (S.ca - 2.5) * k / (n_c - 1)
        if abs(u) < 5.0:                    # The main-door bay
            continue
        pts += [(u, -vf), (u, vf)]
    pts += [(-4.5, -vf), (4.5, -vf), (-4.5, vf), (4.5, vf)]
    for sgn in (-1, 1):
        # Sides of the main hall (the stretch beyond the wings)
        for v in np.linspace(S.wb - 3.0 + 3.2, vf, 3):
            pts += [(sgn * (S.ca - 2.5), v), (sgn * (S.ca - 2.5), -v)]
        # Front and back of the wings
        for u in np.linspace(S.ca + 1.5, S.wa - 2.5, 3):
            pts += [(sgn * u, -(S.wb - 3.0)), (sgn * u, S.wb - 3.0)]
        # Outer ends of the wings
        n_e = max(2, int(round(2 * (S.wb - 3.0) / 6.5)) + 1)
        for k in range(n_e):
            v = -(S.wb - 3.0) + 2 * (S.wb - 3.0) * k / (n_e - 1)
            pts.append((sgn * (S.wa - 2.5), v))
    p.columns(pts, 0.8, y0, y1, M["column"])

    # ---- Wall behind the columns (3.5 m front gallery): the outer ring of the union of
    # the main hall and the wings
    wall_c = (au <= S.ca - 5.0) & (av <= S.cb - 7.0)
    wall_w = (au <= S.wa - 5.0) & (av <= S.wb - 5.0)
    wm = wall_c | wall_w
    p.walls(wm, y0, y1 + 3, M["wall"])
    rg = kit.ring(wm)
    win = rg & (((fr.X + fr.Z) % 11) <= 2)
    p.fill(win, y0 + 4, y0 + 6, M["window"])
    door = rg & (au <= 4.5) & (V < 0)
    p.fill(door, y0, y0 + 7, M["door"])
    # Ceiling: the layer at the top of the walls is closed over the empty hall inside
    p.layer(kit.erode(wm, 1), y1 + 3, M["bracket"])

    # ---- Architrave and dougong brackets: a ring above the column tops
    col_line = (((au <= S.ca - 2.5) & (av <= S.cb - 3.5)) |
                ((au <= S.wa - 2.5) & (av <= S.wb - 3.0)))
    cl = kit.ring(col_line)
    p.layer(cl, y1 + 1, M["beam"])
    band(p, cl, y1 + 2, y1 + 3, M["bracket"], M["beam"])

    # ---- Lower roofs: single eaves on the wings (hip, main ridge along v) plus the main
    # hall's lower eave, taking the highest surface of the union
    e_w, e_l = g + S.wing_eave, g + S.low_eave
    a_core, b_core = S.ca - 2.0, S.cb - 7.0
    hs, ms = skirt(fr, S.ca + 4.5, S.cb, a_core, b_core, rise=(S.up_eave - 1 - S.low_eave),
                   profile=1.3, lift=1.2)
    H = np.full(fr.shape, -1e9)
    H[ms] = e_l + hs[ms]
    wing_len = (S.wa - (S.ca - 4.0)) / 2.0
    for sgn in (-1, 1):
        du = sgn * (S.ca - 4.0 + wing_len)
        uu, vv = np.abs(fr.V), np.abs(fr.U - du)            # The wing's long axis (v) serves as the hip roof's u
        a_, b_ = S.wb, wing_len
        d = np.minimum(a_ - uu, b_ - vv).clip(0, None)
        hw = 5.0 * (d / min(a_, b_)).clip(0, 1) ** 1.3 + kit._lift(uu, vv, a_, b_, 1.2, None, d)
        mw = (uu <= a_) & (vv <= b_)
        H = np.where(mw, np.maximum(H, e_w + hw), H)
    low_m = (ms | wing) & ~((au < a_core) & (av < b_core))
    low_m &= H > -1e8
    roof(p, low_m, 0, H, M["tile"], shell=2, under=M["bracket"],
         rim=M["tile"], rim_under=M["red"])

    # ---- Upper storey (between the two eaves): red walls plus dougong brackets
    core = (au <= a_core) & (av <= b_core)
    cr = kit.ring(core)
    p.fill(cr, e_l, g + S.up_eave - 3, M["red"])
    band(p, cr, g + S.up_eave - 2, g + S.up_eave - 1, M["bracket"], M["beam"])
    # Name board: centered between the two eaves, blue with a gold frame, resting on the
    # lower eave's ridge
    plq = (au <= 1.6) & (V >= -b_core - 1.0) & (V < -b_core)
    for y in range(g + S.up_eave - 4, g + S.up_eave):
        edge = (y in (g + S.up_eave - 4, g + S.up_eave - 1)) | (au > 0.6)
        p.layer(plq & edge, y, M["gold"])
        p.layer(plq & ~edge, y, M["plaque"])

    # ---- Upper roof
    a_up, b_up = S.ca + 1.0, S.cb - 4.5
    rise = S.top - S.up_eave
    up_m = (au <= a_up) & (av <= b_up)
    if S.roof == "hip":
        hu, rm = hip_ridge(fr, a_up, b_up, rise, S.ridge, profile=1.35, lift=1.8)
        gm = None
    else:
        hu, rm, gm = hip_gable(fr, a_up, b_up, rise, a_up - S.ridge, profile=1.35, lift=1.8)
    Tu = roof(p, up_m, g + S.up_eave, hu, M["tile"], shell=2, under=M["bracket"],
              rim=M["tile"], rim_under=M["red"], ridge=M["ridge"], ridge_mask=rm & ~kit.ring(up_m))
    if gm is not None:
        # Gable pediment: its lower edge is the outer end slope (the lowest top among the
        # four neighbors outside the pediment row)
        lowg = _neighbor_low(Tu, gm, up_m & ~gm & (au > S.ridge))
        gable_panel(p, gm & up_m, Tu, lowg, M["gable"], border=M["ridge"])
    # Chiwen: one at each end of the main ridge (3 blocks high, gold top)
    for sgn in (-1, 1):
        x, z = fr.cell(sgn * S.ridge, 0.0)
        i, j = z - fr.z0, x - fr.x0
        if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] and Tu[i, j] > -10 ** 5:
            t0 = int(Tu[i, j]) + 1
            p.set(x, t0, z, M["ridge"])
            p.set(x, t0 + 1, z, M["tile"])
            p.set(x, t0 + 2, z, M["gold"])
    return dict(platform_top=y_top, top=int(Tu[up_m].max()) if up_m.any() else None)


# ---------------------------------------------------------------- Paifang
#
# Local coordinates: u runs along the paifang's width, v through the archways. Pillars,
# archways and roofs are all positioned by u.

BLUE_WHITE = dict(
    wall="minecraft:smooth_quartz",                # White marble
    trim="minecraft:chiseled_quartz_block",        # Arch faces and carving around the archways
    panel="minecraft:quartz_bricks",
    tile="minecraft:blue_concrete",                # Sapphire-blue glazed tiles
    bracket="minecraft:blue_glazed_terracotta",    # Dougong brackets (blue and white paint)
    ridge="minecraft:blue_glazed_terracotta",
    rim="minecraft:smooth_quartz",
)


class Roof:
    """One roof of a paifang (xieshan): center du, half-length a, half-depth b, eave height
    eave and rise rise (all in meters)."""

    def __init__(self, du, a, b, eave, rise):
        self.du, self.a, self.b, self.eave, self.rise = du, a, b, eave, rise


def paifang(w, fr, g, pillars, bays, roofs, pillar_w=3.5, pillar_d=5.0, wall_d=4.0,
            pedestal=None, scrolls=True, mat=None):
    """Paifang: pillars are pillar centers [(u, pillar top height)]; bays are archways
    [(center u, clear half-width, springing height, wall top height)]; roofs is [Roof]
    (built from lowest to highest, so higher roofs overlap lower ones).
    pedestal=(half-width, half-depth, height) is the Sumeru pedestal at the foot of each
    pillar, and scrolls adds drum stones in front of and behind each pillar foot. All
    heights are meters above the ground (block y = g + height)."""
    M = dict(BLUE_WHITE)
    M.update(mat or {})
    p = kit.Painter(w, fr)
    U, V = fr.U, fr.V
    av = np.abs(V)

    # Wall above the archways (architrave, name board): between the pillars, up to each
    # bay's wall top height
    for c, half, spring, top in bays:
        m = (np.abs(U - c) <= half + 0.01) & (av <= wall_d / 2)
        p.fill(m, g + 1, g + top, M["wall"])
    # Pillars
    for u, top in pillars:
        m = (np.abs(U - u) <= pillar_w / 2) & (av <= pillar_d / 2)
        p.fill(m, g + 1, g + top, M["wall"])
        if pedestal:
            ha, hb, hh = pedestal
            pm = (np.abs(U - u) <= ha) & (av <= hb)
            p.fill(pm, g + 1, g + hh, M["wall"])
            p.layer(pm & ~kit.erode(pm, 1), g + hh, M["trim"])
            if scrolls:
                # Drum stones: one in front of and one behind each pillar foot, a quarter
                # ellipse in side view
                dv = av - hb
                sm = (np.abs(U - u) <= 1.0) & (dv > 0) & (dv <= 4.7)
                hs = 1.5 + 3.3 * np.sqrt((1 - (dv / 4.7) ** 2).clip(0, 1))
                p.fill(sm, g + 1, g + np.rint(hs).astype(int), M["wall"])
                drum = sm & (dv <= 1.6)
                p.layer(drum, g + int(round(hh)) - 1, M["trim"])
    # Archways: square below, semicircular arch above, cut all the way through
    for c, half, spring, top in bays:
        du = U - c
        inside = np.abs(du) <= half
        for k in range(1, int(math.ceil(spring + half)) + 1):
            y = g + k
            if k <= spring:
                m = inside
                ring_m = (np.abs(du) > half) & (np.abs(du) <= half + 1.0)
            else:
                dy = k - spring
                r2 = du ** 2 + dy ** 2
                m = inside & (r2 <= half * half + 0.3)
                ring_m = (r2 > half * half + 0.3) & (r2 <= (half + 1.0) ** 2 + 0.3)
            p.layer(m & (av <= pillar_d / 2 + 0.5), y, AIR)
            # Arch faces: a ring of carved stone around each archway (on both faces of the
            # wall)
            face = ring_m & (av <= wall_d / 2) & (av > wall_d / 2 - 1.0)
            p.layer(face, y, M["trim"])
    # Dougong brackets and roofs
    for rf in sorted(roofs, key=lambda r: r.eave):
        bm = (np.abs(U - rf.du) <= rf.a - 0.8) & (av <= rf.b - 1.2)
        band(p, bm, g + rf.eave - 2, g + rf.eave - 1, M["bracket"], M["wall"])
        h, rm, gm = hip_gable(fr, rf.a, rf.b, rf.rise, rf.a * 0.3, profile=1.4, lift=0.9, du=rf.du)
        mask = (np.abs(U - rf.du) <= rf.a) & (av <= rf.b)
        T = roof(p, mask, g + rf.eave, h, M["tile"], shell=2, under=M["bracket"],
                 rim=M["rim"], rim_under=M["bracket"], ridge=M["ridge"],
                 ridge_mask=rm & ~kit.ring(mask))
        lowg = _neighbor_low(T, gm & mask, mask & ~gm & (np.abs(U - rf.du) > rf.a * 0.7))
        gable_panel(p, gm & mask, T, lowg, M["bracket"], border=M["rim"])
        # Ridge-end beasts at both ends of the main ridge
        for sgn in (-1, 1):
            x, z = fr.cell(rf.du + sgn * rf.a * 0.7, 0.0)
            i, j = z - fr.z0, x - fr.x0
            if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] and T[i, j] > -10 ** 5:
                p.set(x, int(T[i, j]) + 2, z, M["ridge"])


def _neighbor_low(T, target, source):
    """For each cell of the target mask: the lowest top among its four neighbors in source
    (its own top - 1 where there is none)."""
    big = 10 ** 6
    S = np.where(source, T, big)
    low = np.full(T.shape, big, dtype=np.int64)
    low[1:, :] = np.minimum(low[1:, :], S[:-1, :])
    low[:-1, :] = np.minimum(low[:-1, :], S[1:, :])
    low[:, 1:] = np.minimum(low[:, 1:], S[:, :-1])
    low[:, :-1] = np.minimum(low[:, :-1], S[:, 1:])
    return np.where(target & (low < big), low, T - 1)
