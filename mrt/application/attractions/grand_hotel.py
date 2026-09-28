#!/usr/bin/env python3
"""The Grand Hotel: a 14-story palace-style block on the slope of Jiantan
Mountain, facing the Keelung River.

Public facts (only numbers and forms are taken; no text or images are copied):
  · The main block was completed on October 10, 1973, to a design by the architect
    Yang Cho-cheng; it is 87 m tall with 14 stories and was once the tallest building
    in Taiwan (1973–1981). Sources: the Chinese and English Wikipedia articles
    "Grand Hotel (Taipei)".
  · "Red columns and golden tiles": vermilion round columns and golden-yellow glazed
    tiles, with deep eaves carried on dougong brackets. Sources: the Grand Hotel's
    official site (about.aspx) and the Taipei City Government English site's entry
    "The Grand Hotel".
  · The roof is a xieshan (hip-and-gable) roof (Wikipedia). Photos show it is
    double-eaved: a skirt eave (the lower eave) runs around the top of the block,
    and the xieshan roof rises only after a gallery with a white stone balustrade
    set back one story. The gable pediments at both ends are red with gold edges,
    and both ends of the main ridge carry ridge-end ornaments (chiwen).
  · Front: red columns running through twelve stories; on every story a white
    balcony slab edge and a red railing, with the guest-room wall set back behind.
    At the center is a double-eaved portico that cars can drive up to, with two
    grand stairs in front flanking a garden, leading down to the forecourt plaza
    (front photos on Wikimedia Commons: "Grand Hotel Taipei front view 20141015"
    and others).

Position, orientation and plan: OSM way/25202548 "main block" (building:levels=14).
The outline's principal axis is 21° (east by south), 110 m long and 56 m deep, with a
41 m × 17 m portico projecting from the middle of the south face. These are measured
from the outline automatically, not hard-coded. Height allocation of the facade
(photo proportions; the lower eave at about 49 m, the upper eave at about 63 m):

   y = g0 + 0     ground floor (lobby, portico driveway)
          4..40  floors 2 to 11, 4 m each: white balcony slabs, red railings,
                 set-back guest-room walls; the red columns reach 43
          44..47 floor 12: the architrave on the column heads; dougong brackets
                 in three tiers, each projecting further than the one below
          48..53 skirt eave (lower eave) with upturned corners, projecting 6.5 m
          53..62 floors 13 and 14: gallery with a white stone balustrade,
                 set-back upper wall, dougong brackets
          63..84 xieshan roof (upper eave projecting 5 m), main ridge at 85,
                 ridge-end ornaments up to 87

Site (the south slope of Jiantan Mountain; the DEM varies by 7 m within the outline):
the ground floor slab takes the median ground height inside the outline. The upper
terrace (g0) is the main block grown by 6 m plus the driveway in front of the portico.
Two grand stairs and ramps on both sides descend 5 m to the forecourt plaza, and a
driveway follows the terrain down from the plaza's front edge. Where the site is
above the ground it is filled with stone and the edges get gray retaining walls (the
gray granite walls in the photos); where it is below the ground it is cut level and
the cut faces also get retaining walls. Edges with a drop of 2 m or more get a white
stone balustrade.

Rear wing (OSM relation/10098399): the long building behind the main block that
climbs the slope. Photos show four stories with red columns, blue-green architraves
and red tiles. It is cut into 24 m sections here, each floored at the median ground
height of its own section, so it steps up the hill.
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions.kit import (AIR, Attraction, Frame, Painter, Spot,
                                            dilate, erode, principal_angle, ring)

# ---- Materials ----
TILE = "minecraft:raw_gold_block"           # Golden-yellow glazed tiles
RIDGE = "minecraft:gold_block"              # Main ridge and hip ridges
GOLD = "minecraft:gold_block"               # Ridge-end ornaments, bargeboards, name board
RED = "minecraft:red_concrete"              # Vermilion round columns, gable pediments
# Red balcony railing (a row of posts you can see through)
RAIL = "minecraft:polished_cinnabar_wall"
BEAM = "minecraft:warped_planks"            # Architrave (blue-green painted decoration)
# Dougong brackets (alternating blue and green)
BRACKET = ("minecraft:dark_prismarine", "minecraft:prismarine_bricks")
SOFFIT = "minecraft:dark_prismarine"        # Eave soffit
BAND = "minecraft:smooth_quartz"            # Balcony slab edge (white)
WALL = "minecraft:white_terracotta"         # Set-back guest-room wall
GLASS = "minecraft:gray_stained_glass"      # Guest-room floor-to-ceiling windows
LOBBY_GLASS = "minecraft:light_gray_stained_glass"
FLOOR = "minecraft:smooth_stone"            # Floor slabs
LOBBY_FLOOR = "minecraft:polished_diorite"  # Stone paving of the lobby
CARPET = "minecraft:red_carpet"
LIGHT = "minecraft:ochre_froglight"         # Warm lights on the balconies and the portico
MARBLE = "minecraft:smooth_quartz"          # White stone balustrade (gallery)
# White stone balustrade (terrace, both sides of the stairs)
BALUSTER = "minecraft:diorite_wall"
STONE = "minecraft:stone"
RETAIN = "minecraft:stone_bricks"           # Retaining wall (gray granite)
PAVE = "minecraft:smooth_stone"             # Paving of the terrace and plaza
PAVE_SLAB = "minecraft:smooth_stone_slab[type=bottom]"
ROAD = "minecraft:gray_concrete"            # Forecourt driveway
STAIR = "minecraft:polished_diorite_stairs[facing=%s,half=bottom]"
GRASS = "minecraft:grass_block"
FLOWERS = ("minecraft:poppy", "minecraft:red_tulip", "minecraft:oxeye_daisy", "minecraft:poppy")
LION = "minecraft:polished_blackstone"      # Stone lions at the gate (dark stone in the photos)
LION_BASE = "minecraft:polished_andesite"
WATER = "minecraft:water"
LAMP_POST = "minecraft:polished_blackstone_wall"
LANTERN = "minecraft:lantern"
PINE_LOG = "minecraft:spruce_log"
PINE_LEAVES = "minecraft:spruce_leaves[persistent=true]"
REAR_ROOF = "minecraft:red_terracotta"      # Red tiles of the rear wing (around the Kirin Hall)
REAR_GLASS = "minecraft:light_gray_stained_glass"

# ---- Facade dimensions (meters = blocks, measured from the ground floor slab g0) ----
STOREY = 4                  # 4 m per story
# Floors 2 to 11 have balconies (slabs at 4..40); floor 12 holds the column heads, architrave and
# dougong brackets
BAL_FLOORS = range(1, 11)
COL_TOP = 43                # Top of the red columns
BEAM_Y = 44                 # Architrave
EAVE1 = 48                  # Eave line of the skirt eave
EAVE1_OUT = 6.5             # Projection of the skirt eave
# Floor slab of the 13th-floor gallery (= the top edge of the skirt eave)
GALLERY = 53
EAVE2 = 63                  # Eave line of the upper eave (xieshan roof)
EAVE2_OUT = 5.0
ROOF_RISE = 21.0            # From the eave line to the main ridge
TOP = 87                    # Top of the ridge-end ornaments = the public figure of 87 m
# Large columns on each long and short side (twenty counted on
# the front photo, paired at the corners)
N_LONG, N_SHORT = 20, 11

# ---- Site (local v measured forward from the main block's front edge B) ----
TERRACE_M = 6               # Width of the terrace around the main block
# The upper terrace in front of the portico reaches 26 m beyond the front edge
FRONT_UP = 26
STAIR_RUN = 5               # 5 steps of 1 m each, descending 5 m
DROP = 5                    # Drop from the upper terrace to the forecourt plaza
RAMP_RUN = 20               # Ramps on both sides at 1:4
PLAZA_END = 84              # The forecourt plaza reaches 84 m beyond the front edge
DRIVE_END = 150             # The driveway follows the terrain to 150 m beyond the front edge

# ---- Rear wing (relation/10098399): the long building behind the main block, up the slope ----
REAR = "relation/10098399"
REAR_SEG = 24               # One 24 m section per floor height, stepping up the slope
REAR_H = 16                 # Four stories of 4 m
REAR_ROOF_MAX = 5.0


def _local(poly, cx, cz, ang):
    c, s = math.cos(ang), math.sin(ang)
    return [((x - cx) * c + (z - cz) * s, -(x - cx) * s + (z - cz) * c) for x, z in poly]


def _spans(loc, v):
    """Return the intervals [(u0, u1)] that the scan line v = constant cuts from a local polygon."""
    xs = []
    n = len(loc)
    for i in range(n):
        (u1, v1), (u2, v2) = loc[i], loc[(i + 1) % n]
        if (v1 <= v < v2) or (v2 <= v < v1):
            xs.append(u1 + (v - v1) * (u2 - u1) / (v2 - v1))
    xs.sort()
    return [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]


def body_geometry(poly):
    """Measure from the OSM main-block outline the main rectangle (center, orientation,
    half-length A, half-depth B) and the portico projecting from the front.

    The orientation is the outline's principal axis; u runs along the long side and v
    points south (the hotel faces the Keelung River). The front and rear edges of the
    main body are the outermost scan lines that cover at least 70% of the full length
    (the portico projecting from the front edge and the small corner projections do
    not count as the main body). The portico is the interval, on the scan line 3 m
    beyond the front edge, that falls in the middle of the main body."""
    cx = sum(p[0] for p in poly) / len(poly)
    cz = sum(p[1] for p in poly) / len(poly)
    ang = principal_angle(poly)
    best = None
    for a in (ang, ang + math.pi / 2):
        loc = _local(poly, cx, cz, a)
        us = [p[0] for p in loc]
        if best is None or max(us) - min(us) > best[1]:
            best = (a, max(us) - min(us))
    ang = best[0]
    if math.cos(ang) < 0:                       # +v points south (world +z)
        ang += math.pi
    loc = _local(poly, cx, cz, ang)
    us, vs = [p[0] for p in loc], [p[1] for p in loc]
    u0, u1 = min(us), max(us)
    L = u1 - u0

    def cover(v):
        return sum(b - a for a, b in _spans(loc, v))

    step = 0.25
    vb = min(vs)
    while vb < max(vs) and cover(vb + 1e-3) < 0.7 * L:
        vb += step
    vf = max(vs)
    while vf > vb and cover(vf - 1e-3) < 0.7 * L:
        vf -= step
    A, B = L / 2, (vf - vb) / 2
    uc, vc = (u0 + u1) / 2, (vb + vf) / 2
    mid = [(a, b) for a, b in _spans(loc, vf + 3) if a > u0 + 0.2 * L and b < u1 - 0.2 * L]
    if mid:
        pa, pb = min(a for a, b in mid), max(b for a, b in mid)
        pd = max(vs) - vf
    # No portico in the outline: use the photo proportions
    else:
        pa, pb, pd = uc - 0.19 * L, uc + 0.19 * L, 16.0
    c, s = math.cos(ang), math.sin(ang)
    wx, wz = cx + uc * c - vc * s, cz + uc * s + vc * c
    return dict(cx=wx, cz=wz, ang=ang, A=A, B=B,
                upc=(pa + pb) / 2 - uc, ap=(pb - pa) / 2, pd=max(8.0, min(24.0, pd)))


def _lift(fr, a, b, lift, corner=None, du=0.0, dv=0.0):
    """Return the heightfield of the upturned eave corners.

    kit.hip with rise=0 leaves only the upturn term."""
    return kit.hip(fr, a, b, 0.0, lift=lift, corner=corner, du=du, dv=dv)


def _skirt(fr, a, b, width, rise, profile=1.6, lift=0.0, corner=None, du=0.0, dv=0.0):
    """Return the heightfield of a skirt eave.

    It is 0 at the eave line (|u|=a or |v|=b) and reaches rise at width inward."""
    d = np.minimum(a - np.abs(fr.U - du), b - np.abs(fr.V - dv)).clip(0, None)
    return rise * (d / width).clip(0, 1) ** profile + _lift(fr, a, b, lift, corner, du, dv)


def _pattern(fr, period=3.0):
    """Return a position index along the facade, so the dougong bracket sets alternate colors.

    The sets alternate blue and green. Long sides use u, short sides use v."""
    return (np.floor(fr.U / period) + np.floor(fr.V / period)).astype(int) % 2


class GrandHotel(Attraction):
    height_m = 87.0
    margin = 12
    # Jiantan Mountain runs three to four hundred meters north of the main block before
    # it reaches the plain. Real terrain extends 240 m beyond the bbox; otherwise the
    # mountain behind is cut into a slope down to y64 just behind the rear wing.
    terrain_margin = 240
    MAIN = "way/25202548"

    # ---------------------------------------------------------------- Planning
    def _main_poly(self):
        f = self.feature(self.MAIN)
        if f and f.get("outer"):
            return max(f["outer"], key=len)
        return None

    def plan(self, site):
        poly = self._main_poly()
        # No main-block outline: use the attraction center and photo proportions
        if poly is None:
            cx, cz = self.center()
            geo = dict(cx=cx, cz=cz, ang=math.radians(21), A=55.0, B=28.0, upc=0.0, ap=20.5, pd=16.5)
        else:
            geo = body_geometry(poly)
        self.geo = geo
        A, B = geo["A"], geo["B"]
        self.A, self.B = A, B
        self.fr = fr = Frame(geo["cx"], geo["cz"], geo["ang"], B + DRIVE_END + 4)
        self.body = fr.box(A, B)
        self.g0 = site.level(fr, self.body)
        self._plan_rear(site)
        self._plan_site(site)
        self.site = site

        # Viewpoint: on the axis of the forecourt plaza, 72 m
        # from the front, looking at the middle of the block
        g0 = self.g0
        vx, vz = fr.cell(0.0, B + 72.0)
        vy = g0 - DROP + 1
        tx, tz = fr.world(0.0, 0.0)
        yaw, pitch = kit.look(vx, vy, vz, tx, g0 + 40, tz)
        # Gallery: behind the white stone balustrade at the center of the 13th-floor front,
        # looking south over the Keelung River and the city
        gx, gz = fr.cell(0.0, B - 2.6)
        self._spots = [
            Spot("", vx, vy, vz, yaw, pitch, self.name_zh, self.name_en),
            Spot("terrace", gx, g0 + GALLERY + 1, gz, round(fr.yaw(0, 1), 1), 12.0,
                 "十三樓迴廊", "13F gallery"),
        ]

    def _plan_rear(self, site):
        """Rear wing: every outer ring of OSM relation/10098399. Each ring is cut into
        REAR_SEG-meter sections along its long axis, and each section is floored at the
        median ground height of that section, so the building steps up the slope of
        Jiantan Mountain. Photos ("Kirin Hall Front" and the distant views from the
        southeast): red columns, blue-green architraves, glass windows, red tiles."""
        self.rear = []
        self.rear_cells = self.fr.empty()
        f = self.feature(REAR)
        if not f:
            return
        for r in f.get("outer", []):
            if len(r) < 4:
                continue
            xs, zs = [p[0] for p in r], [p[1] for p in r]
            cx, cz = sum(xs) / len(xs), sum(zs) / len(zs)
            ang = principal_angle(r)
            loc = _local(r, cx, cz, ang)
            if max(p[1] for p in loc) - min(p[1] for p in loc) > max(p[0] for p in loc) - min(p[0] for p in loc):
                ang += math.pi / 2
            ext = max(max(xs) - min(xs), max(zs) - min(zs)) / 2 + 4
            fr = Frame(cx, cz, ang, ext)
            m = fr.polygon(r)
            # Cells that overlap the main block are left to the main block
            for x, z in fr.cells(m):
                u, v = self.fr.local(x, z)
                if abs(u) <= self.A + 1 and abs(v) <= self.B + 1:
                    m[z - fr.z0, x - fr.x0] = False
            if m.sum() < 100:
                continue
            u0 = float(fr.U[m].min())
            k = np.floor((fr.U - u0) / REAR_SEG).astype(int)
            G = site.grid(fr, dilate(m, 2))
            for kk in sorted(set(k[m].tolist())):
                seg = m & (k == kk)
                if seg.sum() < 30:
                    continue
                L = int(np.round(np.median(G[seg])))
                self.rear.append((fr, seg, L, G))
                for x, z in fr.cells(seg):
                    i, j = z - self.fr.z0, x - self.fr.x0
                    if 0 <= i < self.fr.shape[0] and 0 <= j < self.fr.shape[1]:
                        self.rear_cells[i, j] = True

    def _plan_site(self, site):
        """Plan the terrace, stairs, ramps, forecourt plaza and driveway.

        Records the paving height (a float) and kind of every cell."""
        fr, A, B, g0 = self.fr, self.A, self.B, self.g0
        U, V = fr.U, fr.V
        F = B                                                   # Front edge of the main block
        up = fr.box(A + TERRACE_M, B + TERRACE_M) | fr.rect(-35, 35, F - 1, F + FRONT_UP)
        # Measured forward from the upper terrace's front edge
        sv = V - (F + FRONT_UP)
        in_st = (sv >= 0) & (sv < STAIR_RUN)
        stairs = in_st & (np.abs(U) >= 8) & (np.abs(U) <= 23)
        garden = in_st & (np.abs(U) < 8)
        ramps = (sv >= 0) & (sv < RAMP_RUN) & (np.abs(U) > 23) & (np.abs(U) <= 35)
        plaza = fr.rect(-42, 42, F + FRONT_UP, F + PLAZA_END) & ~(stairs | garden | ramps)
        drive = fr.rect(-5, 5, F + PLAZA_END, F + DRIVE_END) & ~plaza
        up &= ~(stairs | garden | ramps | plaza | drive) & ~(self.rear_cells & ~self.body)

        Lv = np.full(fr.shape, np.nan)
        kind = np.zeros(fr.shape, dtype=np.int8)
        Lv[up], kind[up] = g0, 1
        step = np.floor(sv).clip(0, STAIR_RUN - 1)
        Lv[stairs], kind[stairs] = (g0 - step)[stairs], 3
        Lv[garden], kind[garden] = (g0 - step)[garden], 2
        Lv[ramps], kind[ramps] = (g0 - DROP * (sv / RAMP_RUN))[ramps], 4
        Lv[plaza], kind[plaza] = g0 - DROP, 1
        # Driveway: runs linearly from the plaza's front edge
        # (g0-5) to the ground at the end of the driveway
        ex, ez = fr.cell(0.0, F + DRIVE_END)
        g_end = site.g(ex, ez)
        t = ((V - (F + PLAZA_END)) / (DRIVE_END - PLAZA_END)).clip(0, 1)
        Lv[drive], kind[drive] = ((g0 - DROP) * (1 - t) + g_end * t)[drive], 5
        # Forecourt garden (an ellipse with a fountain at its center) and the loop road around it
        cx_, cv_ = 0.0, F + 50.0
        e = ((U - cx_) / 13.0) ** 2 + ((V - cv_) / 8.0) ** 2
        self.garden_oval = plaza & (e <= 1.0)
        self.loop_road = plaza & (e > 1.0) & (((U - cx_) / 19.0) ** 2 + ((V - cv_) / 13.0) ** 2 <= 1.0)
        self.fountain = (0.0, cv_)
        self.stairs, self.garden = stairs, garden
        self.Lv, self.kind = Lv, kind
        zone = ~np.isnan(Lv)
        self.G = site.grid(fr, dilate(zone, 2))

    # ---------------------------------------------------------------- Build
    def build(self, w):
        p = Painter(w, self.fr)
        self._site(w)
        self._rear(w)
        self._body(p)
        self._lower_eave(p)
        self._upper(p)
        self._roof(p)
        self._portico(p, w)
        self._front(p, w)

    # ---- Grading: terraces, retaining walls, balustrades ----
    def _site(self, w):
        fr, G, Lv, kind = self.fr, self.G, self.Lv, self.kind
        zone = ~np.isnan(Lv)
        Li = np.where(zone, np.floor(Lv + 1e-6), -9999).astype(int)
        half = zone & (kind == 4) & ((Lv - np.floor(Lv + 1e-6)) >= 0.5)
        # The surface of every cell (paving on the terrace, ground outside it). The lowest of the
        # four neighbors decides whether the cell is an exposed edge.
        S = np.where(zone, Li, G).astype(float)
        S[~zone & (G == -999)] = np.inf
        P = np.pad(S, 1, constant_values=np.inf)
        nmin = np.minimum.reduce([P[:-2, 1:-1], P[2:, 1:-1], P[1:-1, :-2], P[1:-1, 2:]])
        facing = kit.cardinal(*fr.dir(0, -1))
        st = STAIR % facing
        s = w.set
        X, Z = fr.X, fr.Z
        for i, j in zip(*np.nonzero(zone)):
            x, z = int(X[i, j]), int(Z[i, j])
            L, gy, k = int(Li[i, j]), int(G[i, j]), int(kind[i, j])
            edge = nmin[i, j] < L
            for y in range(gy + 1, L):
                s(x, y, z, RETAIN if edge else STONE)
            s(x, L, z, {1: PAVE, 2: GRASS, 3: st, 4: PAVE, 5: ROAD}.get(k, PAVE))
            top = L
            if half[i, j]:
                s(x, L + 1, z, PAVE_SLAB)
                top = L + 1
            for y in range(top + 1, max(gy, top) + 2):
                s(x, y, z, AIR)
            # White stone balustrade on edges with a drop of 2
            # m or more (not on the stairs or at stair heads)
            if k in (1, 4, 5) and L - nmin[i, j] >= 2:
                s(x, top + 1, z, BALUSTER)
        # The cut side: cells outside the terrace whose ground is higher than the adjacent terrace
        # get a retaining wall
        Lz = np.where(zone, Li, 99999).astype(float)
        P = np.pad(Lz, 1, constant_values=99999)
        lnb = np.minimum.reduce([P[:-2, 1:-1], P[2:, 1:-1], P[1:-1, :-2], P[1:-1, 2:]])
        cut = ~zone & (lnb < 99999) & (G != -999) & (G > lnb)
        for i, j in zip(*np.nonzero(cut)):
            x, z = int(X[i, j]), int(Z[i, j])
            for y in range(int(lnb[i, j]) + 1, int(G[i, j]) + 1):
                s(x, y, z, RETAIN)

    # ---- Rear wing: four stories stepping up the slope section by section ----
    def _rear(self, w):
        s = w.set
        for fr, seg, L, G in self.rear:
            p = Painter(w, fr)
            edge = ring(seg)
            X, Z = fr.X, fr.Z
            # Foundation: fill up to the floor where the ground is lower, with retaining walls on the
            # edges; dig out where the ground is higher (the uphill end)
            for i, j in zip(*np.nonzero(seg)):
                x, z, gy = int(X[i, j]), int(Z[i, j]), int(G[i, j])
                for y in range(gy + 1, L):
                    s(x, y, z, RETAIN if edge[i, j] else STONE)
                for y in range(L + 1, gy + 1):
                    s(x, y, z, AIR)
            p.layer(seg, L, FLOOR)
            inner = erode(seg, 1)
            for k in range(1, REAR_H // STOREY):
                p.layer(inner, L + STOREY * k, FLOOR)
            # Outer wall: a blue-green architrave atop every story, a red column every 4 blocks,
            # windows elsewhere
            for i, j in zip(*np.nonzero(edge)):
                x, z = int(X[i, j]), int(Z[i, j])
                col = (x + z) % 4 == 0
                for y in range(1, REAR_H + 1):
                    r = y % STOREY
                    blk = BEAM if r == 0 else (RED if col else (REAR_GLASS if r in (1, 2) else WALL))
                    s(x, L + y, z, blk)
            # Roof: a hipped roof projecting 1 m (the slope follows the depth from the outer edge),
            # red tiles with a blue-green soffit
            rm = dilate(seg, 1)
            d = kit.depth(rm).astype(float)
            h = np.minimum((d - 1) * 0.6, REAR_ROOF_MAX)
            p.heightfield(rm, L + REAR_H + 1, h, REAR_ROOF, under=SOFFIT, shell=2)

    # ---- Main block: balconies, red columns, set-back guest-room walls, floor slabs ----
    def _columns(self, a, b, inset):
        pts = []
        for i in range(N_LONG):
            u = -(a - inset) + i * 2 * (a - inset) / (N_LONG - 1)
            pts += [(u, b - inset), (u, -(b - inset))]
        for j in range(1, N_SHORT - 1):
            v = -(b - inset) + j * 2 * (b - inset) / (N_SHORT - 1)
            pts += [(a - inset, v), (-(a - inset), v)]
        return pts

    def _body(self, p):
        fr, A, B, g0 = self.fr, self.A, self.B, self.g0
        body = self.body
        bal = body & ~erode(body, 2)
        outer = ring(body)
        inner = erode(body, 3)
        # Ground floor: lobby (stone paving), a glass wall behind the colonnade, a door at the
        # center of the front
        p.layer(body, g0, LOBBY_FLOOR)
        p.walls(erode(body, 2), g0 + 1, g0 + 3, RED, window=LOBBY_GLASS, every=4, sill=0, head=0)
        door = fr.rect(-3.2, 3.2, B - 4, B + 1)
        p.clear(door & bal | door & ring(erode(body, 2)), g0 + 1, g0 + 3)
        p.layer(fr.rect(-1.2, 1.2, -B + 4, B - 1) & inner, g0 + 1, CARPET)
        # Floors 2 to 11: white balcony slabs, red railings (a
        # row of posts), set-back guest-room walls
        lamp = ring(erode(body, 1)) & (np.abs(np.mod(fr.U + fr.V, 5.7) - 2.85) < 0.5)
        for k in BAL_FLOORS:
            yf = g0 + STOREY * k
            p.layer(bal, yf, BAND)
            p.layer(outer, yf + 1, RAIL)
            p.walls(erode(body, 2), yf + 1, yf + 3, WALL, window=GLASS, every=4, sill=0, head=0)
            p.layer(inner, yf, FLOOR)
            # Warm lights in the balcony ceiling (set into the slab above)
            p.layer(lamp, yf + STOREY, LIGHT)
        # Floor 12: the architrave on the column heads, dougong brackets in three tiers, each
        # projecting further out; the set-back wall behind
        y12 = g0 + STOREY * BAL_FLOORS[-1] + STOREY
        p.layer(bal, y12, BAND)
        p.walls(erode(body, 2), y12 + 1, g0 + GALLERY - 1, WALL, window=GLASS, every=4, sill=1, head=1, storey=4)
        p.layer(inner, y12, FLOOR)
        p.layer(inner, g0 + EAVE1, FLOOR)
        p.layer(outer, g0 + BEAM_Y, BEAM)
        pat = _pattern(fr)
        for k, y in enumerate(range(g0 + BEAM_Y + 1, g0 + EAVE1)):
            m = fr.box(A + 0.4 + 1.1 * k, B + 0.4 + 1.1 * k) & ~erode(body, 1)
            p.layer(m & (pat == 0), y, BRACKET[0])
            p.layer(m & (pat == 1), y, BRACKET[1])
        # Large columns: from the ground floor paving to just
        # below the architrave, with a gold ring at the head
        cols = self._columns(A, B, 1.0)
        p.columns(cols, 0.75, g0 + 1, g0 + COL_TOP, RED)
        p.columns(cols, 0.75, g0 + COL_TOP, g0 + COL_TOP, GOLD)

    # ---- Skirt eave (lower eave) ----
    def _lower_eave(self, p):
        fr, A, B, g0 = self.fr, self.A, self.B, self.g0
        a1, b1 = A + EAVE1_OUT, B + EAVE1_OUT
        width = EAVE1_OUT + 1.5
        mask = fr.box(a1, b1) & ~fr.box(A - 1.5, B - 1.5)
        h = _skirt(fr, a1, b1, width, GALLERY - EAVE1, profile=1.6, lift=2.0, corner=10.0)
        p.heightfield(mask, g0 + EAVE1, h, TILE, under=SOFFIT, shell=2)
        # Hip ridges: the diagonals at the four corners
        diag = mask & (np.abs((a1 - np.abs(fr.U)) - (b1 - np.abs(fr.V))) < 0.7)
        top = np.floor(g0 + EAVE1 + h).astype(int)
        p.fill(diag, top + 1, top + 1, RIDGE)

    # ---- Floors 13 and 14: balustraded gallery, set-back upper wall, dougong brackets ----
    def _upper(self, p):
        fr, A, B, g0 = self.fr, self.A, self.B, self.g0
        inside = fr.box(A - 1.5, B - 1.5)
        p.layer(inside, g0 + GALLERY, FLOOR)
        p.layer(ring(inside), g0 + GALLERY + 1, MARBLE)
        core = fr.box(A - 4, B - 4)
        p.walls(core, g0 + 54, g0 + 57, WALL, window=GLASS, every=3, sill=0, head=0)
        p.columns(self._columns(A - 3, B - 3, 1.0), 0.7, g0 + 54, g0 + 57, RED)
        p.layer(ring(core), g0 + 58, BEAM)
        pat = _pattern(fr)
        for k, y in enumerate(range(g0 + 59, g0 + EAVE2)):
            # Each tier projects further than the one below
            out = -3.0 + 1.6 * (k + 1)
            m = fr.box(A + out, B + out) & ~fr.box(A - 5, B - 5)
            p.layer(m & (pat == 0), y, BRACKET[0])
            p.layer(m & (pat == 1), y, BRACKET[1])

    # ---- Upper eave: double-eaved xieshan roof ----
    def _roof(self, p):
        fr, A, B, g0 = self.fr, self.A, self.B, self.g0
        a2, b2 = A + EAVE2_OUT, B + EAVE2_OUT
        # How far the gable pediment sits from the ends
        gin = 0.45 * b2
        base = g0 + EAVE2
        h = kit.hip_gable(fr, a2, b2, ROOF_RISE, gin, profile=1.5, lift=2.6, corner=0.3 * b2)
        mask = fr.box(a2, b2)
        p.heightfield(mask, base, h, TILE, under=SOFFIT, shell=2)
        U, V = np.abs(fr.U), np.abs(fr.V)
        top = np.floor(base + h).astype(int)
        # Gable pediments: the triangular walls rising at both ends of the xieshan roof, red with
        # gold bargeboards on the raking edges
        gplane = a2 - gin
        he = ROOF_RISE * ((a2 - U) / b2).clip(0, 1) ** 1.5
        band = mask & (U <= gplane) & (U > gplane - 1.3)
        p.fill(band, np.floor(base + he).astype(int), top - 1, RED)
        p.fill(band, top, top, GOLD)
        # Hanging fish (xuanyu): a gold panel at the center of the gable pediment
        p.fill(band & (V < 1.0), top - 4, top - 2, GOLD)
        # Hip ridges: the diagonals of the small hipped slopes at both ends of the xieshan roof
        diag = mask & (U > gplane) & (np.abs((a2 - U) - (b2 - V)) < 0.7)
        p.fill(diag, top + 1, top + 1, RIDGE)
        # Main ridge and ridge-end ornaments
        ridge = mask & (V < 0.9) & (U <= gplane)
        p.fill(ridge, top + 1, base + int(ROOF_RISE) + 1, RIDGE)
        for sgn in (1, -1):
            end = mask & (V < 0.9) & (np.abs(fr.U - sgn * (gplane - 0.5)) < 0.9)
            p.fill(end, base + int(ROOF_RISE) + 1, g0 + TOP, GOLD)
            curl = mask & (V < 0.9) & (np.abs(fr.U - sgn * (gplane - 2.0)) < 0.7)
            p.fill(curl, g0 + TOP - 1, g0 + TOP - 1, GOLD)

    # ---- Portico: double eaves, red columns, gold name board ----
    def _portico(self, p, w):
        fr, A, B, g0 = self.fr, self.A, self.B, self.g0
        geo = self.geo
        upc, ap, pd = geo["upc"], geo["ap"], geo["pd"]
        vc, dh = B + pd / 2, pd / 2
        box = fr.box(ap, dh, du=upc, dv=vc)
        # The roof does not reach inside the main block's balconies
        keep = fr.V >= B - 1.8
        front_v = B + pd - 1.2
        pts = [(upc + ap * t, front_v) for t in (-0.93, -0.56, -0.19, 0.19, 0.56, 0.93)]
        pts += [(upc + sg * ap * 0.93, B + pd * 0.45) for sg in (1, -1)]
        p.columns(pts, 1.0, g0 + 1, g0 + 7, RED)
        p.layer(ring(box) & keep, g0 + 8, BEAM)
        ceil = erode(box, 1)
        p.layer(ceil, g0 + 8, BEAM)
        p.layer(ceil & (_pattern(fr, 4.0) == 0) & (np.abs(np.mod(fr.U, 4.0) - 2.0) < 0.6)
                & (np.abs(np.mod(fr.V, 4.0) - 2.0) < 0.6), g0 + 8, LIGHT)
        # Lower eave
        a1, b1 = ap + 2.5, dh + 2.5
        m1 = fr.box(a1, b1, du=upc, dv=vc) & ~fr.box(ap - 1, dh - 1, du=upc, dv=vc) & keep
        h1 = _skirt(fr, a1, b1, 3.5, 1.6, profile=1.3, lift=0.9, corner=4.0, du=upc, dv=vc)
        p.heightfield(m1, g0 + 9, h1, TILE, under=SOFFIT, shell=2)
        # Frieze: red, with a gold name board at the center of the front
        fz = ring(fr.box(ap - 1, dh - 1, du=upc, dv=vc)) & keep
        p.fill(fz, g0 + 10, g0 + 12, RED)
        plaque = fz & (fr.V > vc + dh - 2.5) & (np.abs(fr.U - upc) <= 5.5)
        p.layer(plaque, g0 + 11, GOLD)
        # Upper eave: xieshan roof
        a2, b2 = ap + 1.5, dh + 1.5
        base = g0 + 13
        h2 = kit.hip_gable(fr, a2, b2, 4.0, 0.5 * b2, profile=1.3, lift=1.1, du=upc, dv=vc)
        m2 = fr.box(a2, b2, du=upc, dv=vc) & keep
        p.heightfield(m2, base, h2, TILE, under=SOFFIT, shell=2)
        U, V = np.abs(fr.U - upc), np.abs(fr.V - vc)
        top = np.floor(base + h2).astype(int)
        gplane = a2 - 0.5 * b2
        he = 4.0 * ((a2 - U) / b2).clip(0, 1) ** 1.3
        band = m2 & (U <= gplane) & (U > gplane - 1.3)
        p.fill(band, np.floor(base + he).astype(int), top - 1, RED)
        p.fill(band, top, top, GOLD)
        ridge = m2 & (V < 0.9) & (U <= gplane)
        p.fill(ridge, top + 1, top + 1, RIDGE)
        for sg in (1, -1):
            end = m2 & (V < 0.9) & (np.abs(fr.U - upc - sg * (gplane - 0.5)) < 0.9)
            p.fill(end, top + 1, top + 2, GOLD)
        # The characters on the name board: a wall sign on the cell just in front of the gold board,
        # facing the forecourt
        fx, fz_ = _vec(fr.facing(0, 1))
        sx, sz = fr.cell(upc, vc + dh - 1.2)
        w.sign(sx + fx, g0 + 11, sz + fz_, ["圓山大飯店", "The Grand Hotel", "", ""],
               facing=(fx, fz_), wood="dark_oak", kind="wall", glow=True, color="yellow")

    # ---- Forecourt: garden, fountain, stone lions ----
    def _front(self, p, w):
        fr, B, g0 = self.fr, self.B, self.g0
        y = g0 - DROP
        # Loop road around the garden
        p.layer(self.loop_road, y, ROAD)
        # Garden: rings of flowers on the lawn
        p.layer(self.garden_oval, y, GRASS)
        U, V = fr.U, fr.V
        cu, cv = self.fountain
        e = np.sqrt(((U - cu) / 13.0) ** 2 + ((V - cv) / 8.0) ** 2)
        for k, blk in enumerate(FLOWERS):
            m = self.garden_oval & (np.abs(e - (0.38 + 0.17 * k)) < 0.05 + 0.02 * k) & (e > 0.3)
            p.layer(m, y + 1, blk)
        basin = self.garden_oval & (e <= 0.28)
        p.layer(basin, y, LION_BASE)
        p.layer(basin & (e <= 0.2), y, WATER)
        p.layer(ring(basin), y + 1, BALUSTER)
        # Flower slope between the stairs: a row of flowers on every step
        for i, j in zip(*np.nonzero(self.garden)):
            L = int(np.floor(self.Lv[i, j] + 1e-6))
            if (int(fr.X[i, j]) + int(fr.Z[i, j])) % 2 == 0:
                w.set(int(fr.X[i, j]), L + 1, int(fr.Z[i, j]), FLOWERS[(i + j) % len(FLOWERS)])
        # Stone lions: at the front edge of the forecourt,
        # either side of the axis, facing arriving cars
        for sg in (1, -1):
            lu, lv = sg * 9.0, B + 66.0
            base = fr.box(1.6, 1.6, du=lu, dv=lv)
            p.fill(base, y + 1, y + 1, LION_BASE)
            body = fr.box(1.0, 1.4, du=lu, dv=lv)
            p.fill(body, y + 2, y + 3, LION)
            head = fr.box(0.9, 0.7, du=lu, dv=lv + 0.8)
            p.fill(head, y + 4, y + 4, LION)
        # Flower beds on both sides of the plaza (lawn edged with red flowers)
        U, V = fr.U, fr.V
        for sg in (1, -1):
            bed = fr.rect(24, 38, B + 38, B + 74) if sg > 0 else fr.rect(-38, -24, B + 38, B + 74)
            p.layer(bed, y, GRASS)
            p.layer(ring(bed), y + 1, FLOWERS[0])
            p.layer(erode(bed, 3) & (np.abs(np.mod(V, 6.0) - 3.0) < 0.5), y + 1, FLOWERS[2])
        # Street lamps: on the outer edge of the loop road
        # around the garden and on both sides of the stairs
        lamps = [(sg * 21.0, B + 50.0 + dv) for sg in (1, -1) for dv in (-10.0, 0.0, 10.0)]
        lamps += [(sg * 23.5, B + FRONT_UP + 7.0) for sg in (1, -1)]
        for lu, lv in lamps:
            x, z = fr.cell(lu, lv)
            for yy in range(y + 1, y + 5):
                w.set(x, yy, z, LAMP_POST)
            w.set(x, y + 5, z, LANTERN)
        # Araucarias on both sides of the main block (the tall,
        # slender conifers flanking the facade in the photos)
        for sg in (1, -1):
            for dv in (-12.0, 8.0, B + 3.0 - 8.0):
                self._pine(w, fr.cell(sg * (self.A + 3.5), dv), g0 + 1, 14 + int(abs(dv)) % 4)

    @staticmethod
    def _pine(w, xz, y0, h):
        """Place a tall, slender conifer: a spruce trunk with leaves tapering tier by tier
        (persistent, so they do not decay)."""
        x, z = xz
        for y in range(y0, y0 + h):
            w.set(x, y, z, PINE_LOG)
        for k, y in enumerate(range(y0 + 3, y0 + h + 1)):
            r = 2 if (h - k) > 4 and k % 2 == 0 else 1
            for dx in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    if (dx or dz) and abs(dx) + abs(dz) <= r + (1 if r == 2 else 0):
                        w.set(x + dx, y, z + dz, PINE_LEAVES)
        w.set(x, y0 + h, z, PINE_LEAVES)
        w.set(x, y0 + h + 1, z, PINE_LEAVES)

    # ---------------------------------------------------------------- Plaque
    def plaque(self):
        return [self.name_zh, self.name_en, "1973 年落成 高 87 m 14 層", "重簷歇山 紅柱金瓦"]

    def plaque_en(self):
        return ["Completed in 1973, 87 m high, 14 storeys", "1973, 87 m high"]


def _vec(name):
    return {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}[name]


BUILDS = {"grand_hotel": GrandHotel}
