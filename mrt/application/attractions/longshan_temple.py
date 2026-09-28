#!/usr/bin/env python3
"""Bangka Longshan Temple: founded in the 3rd year of the Qianlong reign (1738), a
courtyard complex three halls deep, sitting north and facing south.

Public sources (zh.wikipedia, "Bangka Longshan Temple"; Ministry of the Interior,
"Religious Culture Map of Taiwan"; National Cultural Memory Bank, "Architectural layout of
Bangka Longshan Temple"):

  · Along the central axis, from the outside in: a four-pillar, three-bay paifang, the
    temple forecourt, the front hall, the central courtyard, the main hall, the
    connecting passage and the rear hall, with side wings (hulong) left and right, a bell
    tower to the east and a drum tower to the west.
  · A waterfall pool on each side of the forecourt (in place of the lotus ponds of older
    temples); the forecourt is paved with granite strips.
  · The front hall is eleven bays wide: the Sanchuan Hall in the center, flanked by the
    Dragon Gate Hall (east, the entrance) and the Tiger Gate Hall (west, the exit). A
    pair of bronze dragon columns stands before the Sanchuan doors (the only ones in
    Taiwan); the walls contrast bluestone and white stone.
  · Main hall: double-eaved xieshan roof, an open hall with no doors, a caisson ceiling;
    destroyed in an air raid in 1945 and rebuilt in 1959.
  · Bell and drum towers: double-eaved sedan-chair roofs (the first in Taiwan).
  · The ridges and flying eaves are covered in jiannian mosaic and koji pottery dragons,
    phoenixes and qilin in rich colors; the ridges end in upturned, forked swallowtails.

Location and plan: OSM. way/198401479 (main hall, 21 × 18 m), way/198401478 (the U shape
formed by the rear hall and the side wings), way/198401472 (front hall, 40 × 12 m; OSM has
a dividing node on each side of the Sanchuan Hall), way/198401476 (the connecting passage
between the main and rear halls), way/1462833608 (the paifang in front of the forecourt,
named Dragon Gate in OSM).
There are no official heights. From photographs, scaled by the main hall's width of about
26 m including its eaves: lower eaves about 9 m, upper eaves about 12 m, main ridge about
14 m, and the jiannian figures and pagoda on the ridge reach 16–17 m; the ridges of the
front and rear halls are about 10–11.5 m.

Local coordinates: u points east (5° north of east), v points south (the temple front),
with the origin at the center of the main hall.
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions import trad_parts as TP
from mrt.application.attractions.kit import Attraction, Frame, Painter, Spot

AIR = kit.AIR

# ---- Materials ----
PAVE = "minecraft:polished_andesite"            # Granite strips of the forecourt
PAVE2 = "minecraft:smooth_stone"
PLINTH = "minecraft:stone_bricks"               # Platform
WHITE_STONE = "minecraft:polished_diorite"      # Quanzhou white stone
BLUE_STONE = "minecraft:polished_deepslate"     # Qingdou bluestone
CARVED = "minecraft:chiseled_tuff"              # Carved stone windows and columns
BRICK = "minecraft:bricks"                      # Red brick walls of the side wings and rear hall
RED_WOOD = "minecraft:mangrove_planks"          # Woodwork (the vermilion of architraves and doors)
GOLD = "minecraft:raw_gold_block"               # Gilded carving
BRONZE = "minecraft:waxed_exposed_chiseled_copper"   # Bronze dragon columns
DRAGON_COL = "minecraft:chiseled_deepslate"     # Carved stone dragon columns of the main hall
PLAIN_COL = "minecraft:polished_andesite"
RIDGE = "minecraft:red_terracotta"              # Body of the ridges
RIDGE_TOP = "minecraft:resin_bricks"
SOFFIT = "minecraft:stripped_mangrove_wood"     # Dougong brackets and rafters under the eaves
RAIL = "minecraft:stone_brick_wall"             # Stone balustrade
ROCK = ("minecraft:mossy_cobblestone", "minecraft:tuff", "minecraft:stone", "minecraft:mossy_stone_bricks")

# Jiannian colors: blue-green dragon bodies, golden bellies and heads, blue and red
# accents
JIAN_NIAN = ("minecraft:waxed_oxidized_copper", "minecraft:honeycomb_block",
             "minecraft:light_blue_concrete", "minecraft:lime_concrete")
DRAGON_BODY = "minecraft:waxed_oxidized_copper"
DRAGON_HEAD = "minecraft:honeycomb_block"
DRAGON_FIN = "minecraft:light_blue_concrete"

WATER = "minecraft:water[level=0]"
WATER_FLOW = "minecraft:water[level=1]"
WATER_FALL = "minecraft:water[level=8]"


class LongshanTemple(Attraction):
    """The whole of Bangka Longshan Temple: the forecourt (paifang, waterfall pools), front
    hall, side wings with the bell and drum towers, main hall, connecting passage and rear
    hall."""

    height_m = 17.0
    margin = 14

    # OSM elements
    MAIN = "way/198401479"
    U_RING = "way/198401478"
    FRONT = "way/198401472"
    LINK = "way/198401476"
    PAILOU = "way/1462833608"

    def __init__(self, item):
        super().__init__(item)
        main = self.feature(self.MAIN)
        ring = max(main["outer"], key=len) if main and main.get("outer") else self.outline()
        self.main_ring = [tuple(p) for p in ring]
        # u runs along the main hall's long side (east-west) and v points south; if
        # principal_angle picks the north-south sides, turn by -90°
        ang = kit.principal_angle(self.main_ring)
        if math.cos(ang) < 0.7:
            ang -= math.pi / 2
        self.ang = ang
        c, s = math.cos(ang), math.sin(ang)
        cx0 = sum(p[0] for p in self.main_ring) / len(self.main_ring)
        cz0 = sum(p[1] for p in self.main_ring) / len(self.main_ring)
        us = [(x - cx0) * c + (z - cz0) * s for x, z in self.main_ring]
        vs = [-(x - cx0) * s + (z - cz0) * c for x, z in self.main_ring]
        um, vm = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
        self.cx, self.cz = cx0 + um * c - vm * s, cz0 + um * s + vm * c
        self.ha, self.hb_ = (max(us) - min(us)) / 2, (max(vs) - min(vs)) / 2   # Main hall half-length, half-width
        # Extent of the whole temple (local coordinates): from the back of the rear hall to
        # the front of the paifang
        self.site_uv = (-23.0, 21.0, -31.0, 59.0)

    def _local_extent(self, osm, default):
        """Bounding rectangle of an OSM element in local coordinates (u0, u1, v0, v1); default
        if the data lacks it."""
        f = self.feature(osm)
        if not f or not f.get("outer"):
            return default
        c, s = math.cos(self.ang), math.sin(self.ang)
        us, vs = [], []
        for r in f["outer"]:
            for x, z in r:
                dx, dz = x - self.cx, z - self.cz
                us.append(dx * c + dz * s)
                vs.append(-dx * s + dz * c)
        return (min(us), max(us), min(vs), max(vs))

    def bbox(self):
        u0, u1, v0, v1 = self.site_uv
        c, s = math.cos(self.ang), math.sin(self.ang)
        pts = [(self.cx + u * c - v * s, self.cz + u * s + v * c) for u in (u0, u1) for v in (v0, v1)]
        m = self.margin
        return (int(math.floor(min(p[0] for p in pts))) - m, int(math.floor(min(p[1] for p in pts))) - m,
                int(math.ceil(max(p[0] for p in pts))) + m, int(math.ceil(max(p[1] for p in pts))) + m)

    def plaque(self):
        return [self.name_zh, self.name_en, "1738 年創建 · 三進", "全臺唯一銅鑄龍柱"]

    def plaque_en(self):
        return ["Founded in 1738, three halls deep", "1738, three halls"]

    # ---- Planning ----
    def plan(self, site):
        u0, u1, v0, v1 = self.site_uv
        ext = max(abs(u0), abs(u1), abs(v0), abs(v1)) + 6
        self.fr = fr = Frame(self.cx, self.cz, self.ang, ext)
        self.site_mask = fr.rect(u0, u1, v0, v1)
        self.g0 = site.level(fr, fr.rect(u0 + 2, u1 - 2, v0 + 2, v1 - 20))
        self.site = site
        # Grading needs the ground in every cell. cli discards the terrain distance field
        # after plan, so look it up once now and keep it in Site's cache.
        site.grid(fr, self.site_mask)
        # Extent of each building (local coordinates): from OSM where it has one
        self.main_box = (-self.ha, self.ha, -self.hb_, self.hb_)
        self.front_box = self._local_extent(self.FRONT, (-20.6, 19.2, 25.0, 37.3))
        self.link_box = self._local_extent(self.LINK, (-10.0, 8.8, -15.5, -10.8))
        self.pailou_box = self._local_extent(self.PAILOU, (-8.0, 4.7, 52.4, 56.9))
        ring = self._local_extent(self.U_RING, (-21.6, 19.5, -29.2, 23.1))
        self.rear_box = (ring[0], ring[1], ring[2], -16.0)
        self.wing_w = (ring[0] + 0.4, -13.5, -16.0, self.front_box[2])
        self.wing_e = (10.9, ring[1] - 0.2, -16.0, self.front_box[2])
        g = self.g0
        # Viewpoints: the middle of the forecourt looking at the front hall; the courtyard
        # looking at the main hall
        self._spots = []
        for key, (u, v), (tu, tv, th) in (("", (0.0, 48.0), (0.0, 0.0, 7.0)),
                                           ("courtyard", (0.0, 20.5), (0.0, 0.0, 9.0))):
            x, z = fr.cell(u, v)
            tx, tz = fr.world(tu, tv)
            yaw, pitch = kit.look(x, g + 1, z, tx, g + 1 + th, tz)
            zh = self.name_zh if key == "" else "龍山寺中庭"
            en = self.name_en if key == "" else "Longshan Temple Courtyard"
            self._spots.append(Spot(key, x, g + 1, z, yaw, pitch, zh, en))

    # ---- Building ----
    def build(self, w):
        fr = self.fr
        p = Painter(w, fr)
        g = self.g0
        self.site.prepare(w, fr, self.site_mask, g, top=PAVE)
        # Stone strips in the forecourt and courtyard: a pale one every 3 m
        strip = (np.floor(fr.V) % 3 == 0) & self.site_mask
        p.layer(strip, g, PAVE2)
        self._plaza(p)
        self._front_hall(p)
        self._wings(p)
        self._main_hall(p)
        self._link(p)
        self._rear_hall(p)
        self._towers(p)
        self._pailou(p)
        self._courtyard(p)
        for s in self._spots:
            x, z = s.x, s.z
            for y in (s.y, s.y + 1, s.y + 2):
                p.set(x, y, z, AIR)
            p.set(x, s.y - 1, z, PAVE)

    # ================================================================ Shared: flush-gable hall section
    def _box(self, u0, u1, v0, v1):
        return self.fr.rect(u0, u1, v0, v1)

    def gable_roof(self, p, box, y_eave, rise, axis="u", over=1.2, tail=True, tail_rise=2.0,
                   ext=1.4, profile=1.35, ridge_deco=None, end_wall=BRICK, wall_top=None):
        """One flush-gable (yingshan) roof section: box = (u0, u1, v0, v1), ridge along axis
        ("u" east-west, "v" north-south). The two sloped sides overhang by over meters; the
        ends are gable walls (end_wall, built from wall_top up to the underside of the
        roof). tail=True gives the ridge swallowtails at both ends. Returns tile_roof's
        array of roof tops."""
        fr = self.fr
        u0, u1, v0, v1 = box
        du, dv = (u0 + u1) / 2, (v0 + v1) / 2
        if axis == "u":
            L, B = (u1 - u0) / 2, (v1 - v0) / 2 + over
            across = np.abs(fr.V - dv)
            along = np.abs(fr.U - du)
        else:
            L, B = (v1 - v0) / 2, (u1 - u0) / 2 + over
            across = np.abs(fr.U - du)
            along = np.abs(fr.V - dv)
        mask = (along <= L) & (across <= B)
        h = rise * ((B - across) / B).clip(0, 1) ** profile
        tops = TP.tile_roof(p, mask, y_eave, h, TP.ORANGE_TILES, shell=2, under=SOFFIT,
                            under_mask=mask & (across > B - over))
        # Gable walls: one cell at each end, from the wall top up to the underside of the
        # roof
        if end_wall and wall_top is not None:
            ends = mask & (along > L - 1.0) & (across <= B - over)
            for i, j in np.argwhere(ends):
                x, z = int(fr.X[i, j]), int(fr.Z[i, j])
                for y in range(wall_top, int(tops[i, j])):
                    p.set(x, y, z, end_wall)
        # Ridge
        if axis == "u":
            pt = lambda a, off=0.0: (du + a, dv + off)
        else:
            pt = lambda a, off=0.0: (du + off, dv + a)
        ts = [TP.top_at(tops, fr, *pt(a)) for a in np.arange(-L + 0.5, L - 0.4, 1.0)]
        ts = [t for t in ts if t is not None]
        if not ts:
            return tops
        ry = max(ts) + 1
        if tail:
            self._swallowtail(p, pt, L, ry, ext=ext, rise=tail_rise)
        else:
            for a in np.arange(-L, L + 0.01, 0.4):
                x, z = fr.cell(*pt(a))
                p.set(x, ry, z, RIDGE)
        if ridge_deco:
            ridge_deco(p, pt, L, ry)
        elif tail and L >= 3.0:
            self._figures(p, pt, L, ry)
        return tops

    def _figures(self, p, pt, L, ry):
        """A ridge without twin dragons: a small jiannian figure (flowers, people) every 2.5 m
        along the ridge, in alternating colors."""
        fr = self.fr
        k = 0
        for a in np.arange(-L + 1.5, L - 1.4, 2.5):
            x, z = fr.cell(*pt(a))
            p.set(x, ry + 1, z, JIAN_NIAN[k % len(JIAN_NIAN)])
            k += 1

    def _swallowtail(self, p, pt, L, ry, ext=1.4, rise=2.0):
        """Swallowtail ridge along the direction of pt(a). The body is two blocks (red
        terracotta with an orange top edge); both ends rise, project and fork, finishing
        with one block of blue-green jiannian at the tip."""
        fr = self.fr
        c = max(1.5, 0.3 * L)
        a = -(L + ext)
        cells = {}
        while a <= L + ext + 1e-9:
            aa = abs(a)
            k = max(0.0, (aa - (L - c)) / (c + ext))
            yy = ry + rise * k ** 2
            x, z = fr.cell(*pt(a))
            yi = int(math.floor(yy))
            tipz = aa > L + ext - 0.3
            cells[(x, yi, z)] = DRAGON_BODY if tipz else RIDGE_TOP
            if aa <= L + 0.3:
                cells[(x, yi - 1, z)] = RIDGE
            if aa > L + ext - 0.7:
                for sgn in (-1, 1):
                    x2, z2 = fr.cell(*pt(a, sgn * 0.8))
                    cells[(x2, yi + 1, z2)] = DRAGON_BODY if tipz else RIDGE_TOP
            a += 0.25
        for (x, y, z), b in cells.items():
            p.set(x, y, z, b)

    def _dragons(self, p, pt, L, ry, center="pagoda", span=None):
        """Twin dragons: two jiannian dragons on the ridge, swimming from the ends toward the
        middle with their heads toward the central pagoda (or pearl)."""
        fr = self.fr
        span = span or min(L * 0.8, 7.0)
        for sgn in (-1, 1):
            pts = []
            n = 24
            for k in range(n + 1):
                q = k / float(n)
                a = sgn * (span - q * (span - 1.6))
                y = ry + 1 + 1.2 * (0.5 + 0.5 * math.sin(q * math.pi * 2.2))
                pts.append((a, y))
            for a, y in pts:
                x, z = fr.cell(*pt(a))
                p.set(x, int(math.floor(y)), z, DRAGON_BODY)
            # Dragon head (gold) and dorsal fin (blue)
            a_h, y_h = pts[-1]
            x, z = fr.cell(*pt(a_h))
            p.set(x, int(math.floor(y_h)), z, DRAGON_HEAD)
            p.set(x, int(math.floor(y_h)) + 1, z, DRAGON_HEAD)
            a_t, y_t = pts[0]
            x, z = fr.cell(*pt(a_t))
            p.set(x, int(math.floor(y_t)) + 1, z, DRAGON_FIN)
        x, z = fr.cell(*pt(0.0))
        if center == "pagoda":
            # Seven-tier pagoda: alternating copper and gold, with a lightning rod on top as
            # the finial
            stack = ["minecraft:waxed_cut_copper", GOLD,
                     "minecraft:waxed_lightning_rod[facing=up,powered=false]"]
            for k, b in enumerate(stack):
                p.set(x, ry + 1 + k, z, b)
            for sgn in (-1, 1):
                x2, z2 = fr.cell(*pt(sgn * 1.0))
                p.set(x2, ry + 1, z2, "minecraft:waxed_cut_copper")
        else:
            p.set(x, ry + 1, z, GOLD)
            p.set(x, ry + 2, z, "minecraft:red_glazed_terracotta")

    def walls_ring(self, p, box, y0, y1, block, open_side=None):
        """Outer walls of a hall (a ring one block thick); the side named by open_side (such
        as "v+") is left open (a colonnade or front gallery)."""
        fr = self.fr
        u0, u1, v0, v1 = box
        m = self._box(u0, u1, v0, v1)
        ring = kit.ring(m)
        if open_side == "v+":
            ring &= ~(fr.V > v1 - 1.0)
        elif open_side == "v-":
            ring &= ~(fr.V < v0 + 1.0)
        elif open_side == "u+":
            ring &= ~(fr.U > u1 - 1.0)
        elif open_side == "u-":
            ring &= ~(fr.U < u0 + 1.0)
        p.fill(ring, y0, y1, block)
        return ring

    def floor(self, p, box, y, block=PLINTH, top="minecraft:polished_granite"):
        """Platform: build the box from the ground up to y-1, and pave layer y with top."""
        m = self._box(*box)
        p.fill(m, self.g0, y - 1, block)
        p.layer(m, y, top)
        return m

    def col_row(self, p, pts, y0, y1, block):
        for u, v in pts:
            for y in range(y0, y1 + 1):
                p.at(u, v, y, block)

    # ================================================================ Forecourt
    def _plaza(self, p):
        """Forecourt: from the front of the front hall to the paifang, with a waterfall pool
        on each side."""
        fr = self.fr
        g = self.g0
        fu0, fu1, _, fv1 = self.front_box
        for sgn in (-1, 1):
            # Pools: on both sides of the forecourt, with a rock-face waterfall on the outer
            # side
            uo = (fu1 - 0.5) if sgn > 0 else (fu0 + 0.5)       # The rock face is on the outermost side
            ui = uo - sgn * 6.5
            ua, ub = min(uo, ui), max(uo, ui)
            v0, v1 = fv1 + 3.0, fv1 + 12.0
            pool = self._box(ua + 0.5, ub - 0.5, v0 + 1, v1 - 1) & (np.abs(fr.U - uo) > 1.5)
            rim = kit.dilate(pool, 1) & ~pool & ~(np.abs(fr.U - uo) <= 1.0)
            p.fill(pool, g - 2, g - 2, "minecraft:stone")
            p.fill(pool, g - 1, g, WATER)
            p.layer(rim, g, "minecraft:stone_bricks")
            p.layer(rim, g + 1, TP.slab("smooth_stone"))
            # Rock face: two blocks thick on the outer side, 4–6 blocks high, with a ragged
            # top
            wall = self._box(ua, ub, v0, v1) & (np.abs(fr.U - uo) <= 1.0)
            for i, j in np.argwhere(wall):
                x, z = int(fr.X[i, j]), int(fr.Z[i, j])
                top = g + 4 + (x * 7 + z * 3) % 3
                for y in range(g + 1, top + 1):
                    p.set(x, y, z, ROCK[(x + 2 * y + z) % len(ROCK)])
                if (x + z) % 4 == 0:
                    p.set(x, top + 1, z, "minecraft:moss_block")
            # Waterfall: three blocks wide in the middle of the rock face's inner side; a
            # water source at the top spills one block toward the pool and falls
            for k in (-1, 0, 1):
                vv = (v0 + v1) / 2 + k
                x, z = fr.cell(uo - sgn * 1.0, vv)       # Inner side of the rock face, recessed as the spout
                xf, zf = fr.cell(uo - sgn * 2.0, vv)     # In front of the spout (above the pool)
                p.set(x, g + 4, z, WATER)
                p.set(xf, g + 4, zf, WATER_FLOW)
                for y in range(g + 1, g + 4):
                    p.set(xf, y, zf, WATER_FALL)
                    p.set(x, y, z, ROCK[(x + y) % len(ROCK)])
            # Shrubs along the pool
            p.layer(self._box(ua, ub, v1 + 0.5, v1 + 1.5) & ~(np.abs(fr.U - uo) <= 1.0), g + 1,
                    "minecraft:azalea_leaves[distance=1,persistent=true,waterlogged=false]")

    # ================================================================ Front hall
    def _front_hall(self, p):
        """Front hall: eleven bays. The Sanchuan Hall in the center (its ridge in three
        sections with the middle highest: the sanchuan ridge), the Dragon Gate Hall to the
        east and the Tiger Gate Hall to the west. A row of stone columns along the front
        gallery, with a pair of bronze dragon columns before the Sanchuan doors; the walls
        are white stone below and bluestone above."""
        fr = self.fr
        g = self.g0
        u0, u1, v0, v1 = self.front_box
        yf = g + 1                                         # Platform (one step high)
        self.floor(p, (u0, u1, v0, v1), yf)
        wall_v = v1 - 2.2                                  # The front wall is set back to form the front gallery
        body = (u0, u1, v0, wall_v)
        s_mid = 0.5 * (u0 + u1)
        sc0, sc1 = -8.2, 9.2                               # OSM's dividing nodes: the ends of the Sanchuan Hall
        mid0, mid1 = s_mid - 4.0, s_mid + 4.0
        # Walls: stone at the front; red brick at the back (facing the courtyard) and the
        # ends
        ring = self.walls_ring(p, body, yf + 1, g + 6, BRICK)
        front = ring & (fr.V > wall_v - 1.0)
        for i, j in np.argwhere(front):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            for y in range(yf + 1, g + 7):
                k = y - yf
                b = WHITE_STONE if k <= 1 else (BLUE_STONE if k <= 4 else WHITE_STONE)
                if k in (2, 3) and int(math.floor(fr.U[i, j])) % 4 in (1, 2):
                    b = CARVED                             # Carved stone window
                p.set(x, y, z, b)
        # Doors: the Sanchuan doors (three in the center) plus the Dragon Gate (east) and
        # Tiger Gate (west), with matching openings at the back (courtyard side)
        doors = [s_mid - 5.5, s_mid, s_mid + 5.5, (sc1 + u1) / 2, (u0 + sc0) / 2]
        for du in doors:
            sel = ring & (np.abs(fr.U - du) <= 1.0)
            for i, j in np.argwhere(sel):
                x, z = int(fr.X[i, j]), int(fr.Z[i, j])
                for y in range(yf + 1, yf + 4):
                    p.set(x, y, z, AIR)
            # Steps: a row along the front of the front gallery and a row on the courtyard
            # side
            for vv, sv in ((v1 + 0.5, -1), (v0 - 0.5, 1)):
                st = self._box(du - 1.2, du + 1.2, vv - 0.5, vv + 0.5)
                for x, z in fr.cells(st):
                    p.set(x, yf, z, TP.stairs("stone_brick", fr.facing(0, sv)))
        # The name board above the Sanchuan doors, reading Longshan Temple
        vv = wall_v - 0.5
        for d in (-1.0, 0.0, 1.0):
            p.at(s_mid + d, vv, yf + 4, "minecraft:polished_blackstone")
        TP.plaque_sign(p, s_mid, vv, yf + 4, (0, 1), ["", dict(text="龍山寺", color="#E8C15A", bold=True), "", ""])
        # Interior
        inner = kit.erode(self._box(*body), 1)
        p.clear(inner, yf + 1, g + 6)
        p.layer(inner, g + 7, RED_WOOD)                    # Ceiling
        # Front gallery: a row of stone columns (tops at g+5), with two bronze dragon
        # columns before the Sanchuan doors
        vcol = v1 - 0.6
        for uu in np.linspace(u0 + 0.6, u1 - 0.6, 12):
            blk = BRONZE if abs(uu - s_mid) < 3.2 else (CARVED if sc0 < uu < sc1 else PLAIN_COL)
            self.col_row(p, [(uu, vcol)], yf + 1, g + 5, blk)
        # The eaves of the Sanchuan Hall's middle section are one block higher than the
        # sides; the block above the front gallery is a vermilion and gilt architrave
        beam = self._box(mid0, mid1, wall_v, v1) & (fr.V > v1 - 1.0)
        for i, j in np.argwhere(beam):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            p.set(x, g + 6, z, GOLD if (x + z) % 3 == 0 else RED_WOOD)
        # Roof: five sections (Tiger Gate Hall, Sanchuan left, Sanchuan middle, Sanchuan
        # right, Dragon Gate Hall), the middle highest
        segs = [((mid0, mid1), g + 7, 3.0, 2.4, True),
                ((sc0, mid0), g + 6, 2.9, 1.8, False),
                ((mid1, sc1), g + 6, 2.9, 1.8, False),
                ((u0, sc0), g + 6, 2.6, 1.8, False),
                ((sc1, u1), g + 6, 2.6, 1.8, False)]
        for (a0, a1), ye, rise, trise, deco in segs:
            deco_fn = (lambda p_, pt, L, ry: self._dragons(p_, pt, L, ry, center="pearl", span=3.4)) if deco else None
            self.gable_roof(p, (a0, a1, v0, v1), ye, rise, axis="u", over=1.0, tail=True,
                            tail_rise=trise, ext=1.2, ridge_deco=deco_fn, wall_top=g + 6)

    # ================================================================ Side wings
    def _wings(self, p):
        fr = self.fr
        g = self.g0
        for box, inner_side in ((self.wing_w, "u+"), (self.wing_e, "u-")):
            u0, u1, v0, v1 = box
            self.floor(p, box, g + 1, top="minecraft:polished_andesite")
            # Outer walls in red brick; the side facing the courtyard is a colonnade
            self.walls_ring(p, box, g + 2, g + 5, BRICK, open_side=inner_side)
            inner = kit.erode(self._box(*box), 1)
            p.clear(inner, g + 2, g + 5)
            uc = (u1 - 0.6) if inner_side == "u+" else (u0 + 0.6)
            for vv in np.arange(v0 + 1.0, v1 - 0.5, 3.2):
                self.col_row(p, [(uc, vv)], g + 2, g + 5, PLAIN_COL)
            # Inner wall (behind the colonnade): red brick with a doorway at intervals
            uw = uc + (-2.0 if inner_side == "u+" else 2.0)
            wl = (np.abs(fr.U - uw) <= 0.5) & (fr.V > v0 + 1) & (fr.V < v1 - 1)
            gap = (np.floor(fr.V) % 8) < 2
            p.fill(wl & ~gap, g + 2, g + 5, BRICK)
            p.layer(self._box(*box), g + 6, RED_WOOD)
            self.gable_roof(p, box, g + 6, 2.4, axis="v", over=1.0, tail=True, tail_rise=1.4,
                            ext=0.8, wall_top=g + 6)

    # ================================================================ Main hall
    def _main_hall(self, p):
        """Main hall: stone platform, a ring of stone columns (dragon columns in the front
        row), an open hall; double-eaved xieshan roof."""
        fr = self.fr
        g = self.g0
        a, b = self.ha, self.hb_
        yf = g + 1
        # The platform extends 0.8 m beyond the hall, with three flights of steps at the
        # front
        plat = self._box(-a - 0.8, a + 0.8, -b - 0.8, b + 0.8)
        p.fill(plat, g, yf - 1, PLINTH)
        p.layer(plat, yf, "minecraft:polished_granite")
        for du in (-5.0, 0.0, 5.0):
            steps = self._box(du - 1.6, du + 1.6, b + 0.8, b + 1.8)
            fac = fr.facing(0, -1)
            for x, z in fr.cells(steps):
                p.set(x, yf, z, TP.stairs("stone_brick", fac))
        # Stone balustrade: around the edge of the platform, open at the steps
        edge = kit.ring(plat)
        for du in (-5.0, 0.0, 5.0):
            edge &= ~((np.abs(fr.U - du) <= 1.7) & (fr.V > 0))
        rail = {(int(fr.X[i, j]), yf + 1, int(fr.Z[i, j])) for i, j in np.argwhere(edge)}
        for k, blk in TP.walls_conn(rail, "stone_brick_wall").items():
            p.set(k[0], k[1], k[2], blk)
        # Columns: all round the outer ring, with carved stone dragon columns in the front
        # row
        yc = g + 7
        nu, nv = 7, 5
        for i in range(nu + 1):
            for j in range(nv + 1):
                if i not in (0, nu) and j not in (0, nv):
                    continue
                uu = -a + 0.6 + (2 * a - 1.2) * i / nu
                vv = -b + 0.6 + (2 * b - 1.2) * j / nv
                blk = DRAGON_COL if j == nv else PLAIN_COL
                self.col_row(p, [(uu, vv)], yf + 1, yc, blk)
        # Inner sanctum: back and side walls (an open hall with no doors at the front), and
        # a gold shrine
        core = (-a + 2.4, a - 2.4, -b + 2.2, b - 2.6)
        self.walls_ring(p, core, yf + 1, yc, RED_WOOD, open_side="v+")
        cv0 = core[2]
        shrine = self._box(-3.0, 3.0, cv0 + 1.0, cv0 + 2.4)
        p.fill(shrine, yf + 1, yf + 2, "minecraft:polished_blackstone")
        p.layer(shrine, yf + 3, GOLD)
        p.layer(self._box(-1.0, 1.0, cv0 + 1.0, cv0 + 1.8), yf + 4, GOLD)
        # Architrave, dougong brackets
        band = kit.ring(self._box(-a + 0.2, a - 0.2, -b + 0.2, b - 0.2))
        for i, j in np.argwhere(band):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            p.set(x, yc + 1, z, GOLD if (x + z) % 3 == 0 else RED_WOOD)
        p.layer(kit.erode(self._box(-a + 0.2, a - 0.2, -b + 0.2, b - 0.2), 1), yc + 1, RED_WOOD)
        # Lower eave: a pent roof on all four sides, rising from a 1.3 m overhang to the
        # upper walls (on the east side it is only a few tens of centimeters from the side
        # wing, so it cannot be wider)
        la, lb = a + 1.3, b + 1.3
        ua_, ub_ = 7.2, 5.4                                # Half-length and half-width of the upper walls
        low = self._box(-la, la, -lb, lb) & ~self._box(-ua_, ua_, -ub_, ub_)
        d_out = np.minimum(la - np.abs(fr.U), lb - np.abs(fr.V)).clip(0, None)
        d_in = np.minimum(la - ua_, lb - ub_)
        h_low = 1.3 * (d_out / d_in).clip(0, 1) ** 1.2
        h_low = h_low + TP.corner_lift(fr, la, lb, 0.9)
        y_low = yc + 2                                     # g+9
        TP.tile_roof(p, low, y_low, h_low, TP.ORANGE_TILES, shell=2, under=SOFFIT,
                     under_mask=low & ~self._box(-a, a, -b, b))
        # Upper storey: walls (with a gilded architrave band)
        up = self._box(-ua_, ua_, -ub_, ub_)
        ring = kit.ring(up)
        p.fill(ring, y_low, y_low + 2, RED_WOOD)
        for i, j in np.argwhere(ring):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            if (x + z) % 2 == 0:
                p.set(x, y_low + 2, z, GOLD)
        p.clear(kit.erode(up, 1), y_low, y_low + 2)
        # Upper eave: xieshan
        ra, rb = ua_ + 1.8, ub_ + 1.8
        gin = 2.2
        y_up = y_low + 3                                   # g+12
        mask = self._box(-ra, ra, -rb, rb)
        h = kit.hip_gable(fr, ra, rb, 2.1, gin, profile=1.5, lift=1.0)
        tops = TP.tile_roof(p, mask, y_up, h, TP.ORANGE_TILES, shell=2, under=SOFFIT,
                            under_mask=mask & ~up)
        # Gable pediments (red brick, gold bargeboards)
        for su in (-1, 1):
            cells = (su * fr.U > ra - gin) & (su * fr.U <= ra - gin + 1.0) & (np.abs(fr.V) < rb - gin + 0.3)

            def ytop(i, j, su=su):
                t = TP.top_at(tops, fr, su * (ra - gin - 0.6), float(fr.V[i, j]))
                return t if t is not None else tops[i, j]
            TP.gable_face(p, cells, tops, ytop, BRICK, border=GOLD)
        # Main ridge: swallowtails, twin dragons guarding a pagoda
        L = ra - gin
        ts = [TP.top_at(tops, fr, u, 0.0) for u in np.arange(-L, L + 0.01, 0.5)]
        ry = max(t for t in ts if t is not None) + 1
        pt = lambda aa, off=0.0: (aa, off)
        self._swallowtail(p, pt, L, ry, ext=1.6, rise=2.4)
        self._dragons(p, pt, L, ry, center="pagoda", span=min(L - 0.5, 6.0))
        # Vertical and diagonal ridges: red, with one blue-green block at each eave-corner
        # tip
        for su in (-1, 1):
            for sv in (-1, 1):
                pts = []
                for k in np.arange(0.0, rb - gin + 0.01, 0.4):
                    t = TP.top_at(tops, fr, su * (ra - gin - 0.6), sv * k)
                    if t is not None:
                        pts.append((su * (ra - gin + 0.3), sv * k, t + 1))
                for k in range(11):
                    q = k / 10.0
                    uu = su * (ra - gin + 0.3 + (gin - 0.6) * q)
                    vv = sv * (rb - gin + (gin - 0.6) * q)
                    t = TP.top_at(tops, fr, uu, vv)
                    if t is not None:
                        pts.append((uu, vv, t + 1))
                if len(pts) >= 2:
                    TP.ridge_line(p, pts, RIDGE)
                    uu, vv, yy = pts[-1]
                    TP.ridge_line(p, [(uu + su * 0.4, vv + sv * 0.4, yy + 1)] * 2, DRAGON_BODY)
        # Diagonal ridges at the four corners of the lower eave
        for su in (-1, 1):
            for sv in (-1, 1):
                pts = []
                for k in range(9):
                    q = k / 8.0
                    uu = su * (ua_ + (la - ua_) * q)
                    vv = sv * (ub_ + (lb - ub_) * q)
                    x, z = fr.cell(uu, vv)
                    i, j = z - fr.z0, x - fr.x0
                    hv = float(h_low[i, j]) if low[i, j] else 0.0
                    pts.append((uu, vv, y_low + 1 + hv + 0.6))
                TP.ridge_line(p, pts, RIDGE)
                uu, vv, yy = pts[-1]
                TP.ridge_line(p, [(uu + su * 0.4, vv + sv * 0.4, yy + 1)] * 2, DRAGON_BODY)

    # ================================================================ Connecting passage
    def _link(self, p):
        """The connecting passage between the main and rear halls: a colonnade under a gable
        roof."""
        g = self.g0
        u0, u1, v0, v1 = self.link_box
        self.floor(p, self.link_box, g + 1)
        for uu in np.linspace(u0 + 0.6, u1 - 0.6, 6):
            for vv in (v0 + 0.6, v1 - 0.6):
                self.col_row(p, [(uu, vv)], g + 2, g + 5, PLAIN_COL)
        p.layer(self._box(*self.link_box), g + 6, RED_WOOD)
        self.gable_roof(p, self.link_box, g + 6, 1.8, axis="u", over=0.6, tail=True, tail_rise=1.0,
                        ext=0.8, wall_top=None)

    # ================================================================ Rear hall
    def _rear_hall(self, p):
        """Rear hall: dedicated to Mazu, Wenchang Dijun, Guansheng Dijun and others. The front
        (facing the courtyard) is a gallery, and the ridge is in three sections with the
        middle highest."""
        fr = self.fr
        g = self.g0
        u0, u1, v0, v1 = self.rear_box
        yf = g + 1
        self.floor(p, self.rear_box, yf)
        wall_v = v1 - 2.0
        body = (u0, u1, v0, wall_v)
        ring = self.walls_ring(p, body, yf + 1, g + 6, BRICK)
        inner = kit.erode(self._box(*body), 1)
        p.clear(inner, yf + 1, g + 6)
        p.layer(inner, g + 7, RED_WOOD)
        # Front (facing south): vermilion wooden lattice panels, with a door in each bay
        front = ring & (fr.V > wall_v - 1.0)
        for i, j in np.argwhere(front):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            for y in range(yf + 1, g + 7):
                p.set(x, y, z, RED_WOOD if (y - yf) <= 3 else GOLD if (x + z) % 2 else RED_WOOD)
        for du in np.arange(u0 + 3.0, u1 - 2.0, 4.0):
            sel = front & (np.abs(fr.U - du) <= 0.6)
            for i, j in np.argwhere(sel):
                x, z = int(fr.X[i, j]), int(fr.Z[i, j])
                for y in range(yf + 1, yf + 4):
                    p.set(x, y, z, AIR)
        for uu in np.linspace(u0 + 0.6, u1 - 0.6, 12):
            self.col_row(p, [(uu, v1 - 0.6)], yf + 1, g + 6, CARVED)
        s_mid = 0.5 * (u0 + u1)
        mid0, mid1 = s_mid - 5.0, s_mid + 5.0
        segs = [((mid0, mid1), g + 8, 3.3, 2.2, True),
                ((u0, mid0), g + 7, 3.0, 1.8, False),
                ((mid1, u1), g + 7, 3.0, 1.8, False)]
        for (a0, a1), ye, rise, trise, deco in segs:
            deco_fn = (lambda p_, pt, L, ry: self._dragons(p_, pt, L, ry, center="pearl", span=3.8)) if deco else None
            self.gable_roof(p, (a0, a1, v0, v1), ye, rise, axis="u", over=1.0, tail=True,
                            tail_rise=trise, ext=1.2, ridge_deco=deco_fn, wall_top=g + 7)

    # ================================================================ Bell tower, drum tower
    def _towers(self, p):
        """Bell tower (east) and drum tower (west): square towers straddling the side wings,
        with double-eaved sedan-chair roofs (the upper roof resembles the top of a sedan
        chair: a hip roof with a short ridge)."""
        fr = self.fr
        g = self.g0
        for box in (self.wing_w, self.wing_e):
            u0, u1 = box[0], box[1]
            uc = (u0 + u1) / 2
            vc = 15.5
            half = min(3.4, (u1 - u0) / 2)
            tb = self._box(uc - half + 0.6, uc + half - 0.6, vc - half + 0.6, vc + half - 0.6)
            # Tower body: two more storeys above the side wing's roof
            ring = kit.ring(tb)
            p.fill(ring, g + 6, g + 11, RED_WOOD)
            p.clear(kit.erode(tb, 1), g + 7, g + 11)
            for i, j in np.argwhere(ring):
                x, z = int(fr.X[i, j]), int(fr.Z[i, j])
                du, dv = float(fr.U[i, j]) - uc, float(fr.V[i, j]) - vc
                fac = fr.facing(1 if du > 0 else -1, 0) if abs(du) > abs(dv) else fr.facing(0, 1 if dv > 0 else -1)
                if (x + z) % 2 == 0:
                    # Lattice windows: open dark trapdoors against the outside of the wall
                    p.set(x, g + 8, z, "minecraft:dark_oak_trapdoor[facing=%s,half=bottom,open=true,"
                                       "powered=false,waterlogged=false]" % fac)
                p.set(x, g + 11, z, GOLD if (x + z) % 2 else RED_WOOD)
            # Lower pent roof
            sk = self._box(uc - half - 0.8, uc + half + 0.8, vc - half - 0.8, vc + half + 0.8) & ~tb
            d = np.minimum(half + 0.8 - np.abs(fr.U - uc), half + 0.8 - np.abs(fr.V - vc)).clip(0, None)
            hs = 1.4 * (d / 1.8).clip(0, 1) + TP.corner_lift(fr, half + 0.8, half + 0.8, 0.8, du=uc, dv=vc)
            TP.tile_roof(p, sk, g + 9, hs, TP.ORANGE_TILES, shell=1, under=SOFFIT)
            # Upper sedan-chair roof: four slopes, a short ridge, sharply upturned corners
            rt = self._box(uc - half - 0.6, uc + half + 0.6, vc - half - 0.6, vc + half + 0.6)
            hr = kit.hip(fr, half + 0.6, half * 0.9 + 0.6, 3.0, profile=1.6, lift=1.2, du=uc, dv=vc)
            tops = TP.tile_roof(p, rt, g + 12, hr, TP.ORANGE_TILES, shell=2, under=SOFFIT)
            ts = [TP.top_at(tops, fr, uc + dd, vc) for dd in (-0.5, 0.0, 0.5)]
            top = max(t for t in ts if t is not None)
            pt = lambda aa, off=0.0, uc=uc, vc=vc: (uc + off, vc + aa)
            self._swallowtail(p, pt, 0.9, top + 1, ext=0.9, rise=1.2)
            x, z = fr.cell(uc, vc)
            p.set(x, top + 2, z, GOLD)
            p.set(x, top + 3, z, "minecraft:waxed_lightning_rod[facing=up,powered=false]")

    # ================================================================ Paifang
    def _pailou(self, p):
        """The four-pillar, three-bay paifang in front of the forecourt: stone pillars, the
        central bay's roof highest and the two side bays lower, with swallowtail ridges."""
        fr = self.fr
        g = self.g0
        u0, u1, v0, v1 = self.pailou_box
        vc = (v0 + v1) / 2
        span = u1 - u0
        cols = [u0 + 0.6, u0 + span * 0.3, u0 + span * 0.7, u1 - 0.6]
        for uu in cols:
            self.col_row(p, [(uu, vc)], g + 1, g + 6, "minecraft:polished_diorite")
            p.at(uu, vc - 1.0, g + 1, "minecraft:stone_brick_stairs[facing=%s,half=bottom,shape=straight,waterlogged=false]" % fr.facing(0, 1))
            p.at(uu, vc + 1.0, g + 1, "minecraft:stone_brick_stairs[facing=%s,half=bottom,shape=straight,waterlogged=false]" % fr.facing(0, -1))
        # Architrave and name board
        for uu in np.arange(cols[0], cols[-1] + 0.01, 0.5):
            p.at(uu, vc, g + 7, RED_WOOD)
        for uu in np.arange(cols[1], cols[2] + 0.01, 0.5):
            p.at(uu, vc, g + 6, GOLD)
        p.at((cols[1] + cols[2]) / 2, vc, g + 5, "minecraft:polished_blackstone")
        TP.plaque_sign(p, (cols[1] + cols[2]) / 2, vc, g + 5, (0, 1),
                       ["", dict(text="龍山寺", color="#E8C15A", bold=True), "", ""])
        vb = (vc - 1.8, vc + 1.8)
        self.gable_roof(p, (cols[1] - 0.6, cols[2] + 0.6, vb[0] + 0.6, vb[1] - 0.6), g + 8, 1.6, axis="u",
                        over=1.2, tail=True, tail_rise=1.4, ext=0.9, wall_top=None,
                        ridge_deco=lambda p_, pt, L, ry: self._dragons(p_, pt, L, ry, center="pearl", span=2.6))
        for a0, a1 in ((cols[0] - 0.8, cols[1] - 0.6), (cols[2] + 0.6, cols[3] + 0.8)):
            self.gable_roof(p, (a0, a1, vb[0] + 0.6, vb[1] - 0.6), g + 7, 1.2, axis="u", over=1.0,
                            tail=True, tail_rise=1.0, ext=0.6, wall_top=None)

    # ================================================================ Courtyard
    def _courtyard(self, p):
        """Courtyard: the Tiangong censer (bronze) in front of the main hall, with low trees
        on both sides."""
        fr = self.fr
        g = self.g0
        b = self.hb_
        x, z = fr.cell(0.0, b + 4.0)
        p.set(x, g + 1, z, "minecraft:polished_blackstone")
        p.set(x, g + 2, z, "minecraft:cauldron")
        for sgn in (-1, 1):
            xx, zz = fr.cell(sgn * 1.0, b + 4.0)
            p.set(xx, g + 1, zz, "minecraft:waxed_exposed_cut_copper")
        for sgn in (-1, 1):
            tree = fr.ellipse(1.3, 1.3, sgn * 8.0, b + 9.0)
            p.layer(tree, g + 1, "minecraft:stone_bricks")
            p.fill(fr.ellipse(1.0, 1.0, sgn * 8.0, b + 9.0), g + 2, g + 3,
                   "minecraft:azalea_leaves[distance=1,persistent=true,waterlogged=false]")


BUILDS = {"longshan_temple": LongshanTemple}
