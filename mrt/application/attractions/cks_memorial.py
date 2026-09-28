#!/usr/bin/env python3
"""The Chiang Kai-shek Memorial Hall grounds: the memorial hall, the Liberty Square paifang,
the National Theater, the National Concert Hall, Liberty Square and Democracy Boulevard,
the Gate of Great Loyalty and the Gate of Great Piety, and the perimeter corridor.

Location, orientation and outlines (OSM, data/attractions.json):
  way/1052759757  Memorial hall platform (height 14.5, including the grand staircase at
                  the front)
  way/1052759756  Outermost platform tier (building:levels 1; the middle of the west side
                  is the gap for the stairs)
  way/1052759759  Hall body (min_height 14.5, height 38.5)
  way/1052759768  Octagonal roof (38.5–70 m, pyramidal, roof:colour blue)
  way/1052759782  Liberty Square gate (the paifang; the six bumps in the outline are the
                  six pillar feet)
  way/1052759776  National Theater, way/1052759775  National Concert Hall (height 37,
                  roof:height 12)
  way/1053359244  Liberty Square (the plaza between the theater and the concert hall),
                  way/1053396976  Democracy Boulevard (formerly Memorial Boulevard)
  way/1053359203  Gate of Great Loyalty (north), way/1053359198  Gate of Great Piety
                  (south)
  way/1053359285  Perimeter wall at the southwest corner (OSM lacks the northern stretch,
                  so it is mirrored across the axis)
  Axis: paifang center -> memorial hall center, running from west-northwest to
  east-southeast at about 28°; the memorial hall sits in the east and faces west.

Appearance (public sources: the Wikipedia articles "Chiang Kai-shek Memorial Hall",
"National Theater", "National Concert Hall" and "Liberty Square", and the website of the
National Chiang Kai-shek Memorial Hall; photographs are used only to measure proportions):
  · The memorial hall is 70 m high; the three-tier platform is 14.5 m; the hall walls
    24 m; from the dougong brackets to the finial 31.5 m; the bronze doors 16 m high.
  · Double-eaved octagonal pyramidal roof in blue glazed tiles (the eight sides stand for
    the Eight Virtues), with a gold finial; white marble outer walls (blue and white
    evoke the Blue Sky with a White Sun).
  · 84 granite steps at the front plus 5 into the hall make 89 (Chiang Kai-shek lived to
    89), with an imperial way carved with the national emblem up the middle.
  · Main hall: the seated bronze statue is 6.3 m high; the ceiling is a caisson ceiling
    bearing the twelve-rayed Blue Sky with a White Sun national emblem.
  · Liberty Square paifang: 30 m high and 80 m wide, five bays, six pillars and eleven
    roofs, with white walls and blue tiles.
  · National Theater: double-eaved hip roof; National Concert Hall: double-eaved xieshan
    roof (a lower rank than the hip roof). Yellow glazed tiles, red columns, dougong
    brackets, a white platform and balustrade (designed by Yang Cho-cheng, 1987).
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions import palace_kit as PK
from mrt.application.attractions.kit import Attraction, Frame, Painter, Spot

HALL_BASE = "way/1052759757"
HALL_ROOF = "way/1052759768"
GATE = "way/1052759782"
THEATER = "way/1052759776"
CONCERT = "way/1052759775"
PLAZA = "way/1053359244"
BLVD = "way/1053396976"
LOYALTY = "way/1053359203"      # Gate of Great Loyalty
PIETY = "way/1053359198"        # Gate of Great Piety
SW_WALL = "way/1053359285"

B = "minecraft:"
WHITE = B + "smooth_quartz"
WHITE2 = B + "quartz_bricks"
TRIM = B + "chiseled_quartz_block"
PILLAR = B + "quartz_pillar"
WSLAB = B + "smooth_quartz_slab[type=bottom]"
BLUE = B + "blue_concrete"
BLUE_G = B + "blue_glazed_terracotta"
TEAL = B + "prismarine_bricks"
GOLD = B + "gold_block"
FLOOR = B + "polished_diorite"
GRANITE = B + "polished_andesite"
GRANITE_S = B + "polished_andesite_slab[type=bottom]"
PAVE = B + "smooth_stone"
PAVE2 = B + "polished_andesite"
PAVE3 = B + "polished_diorite"
GRASS = B + "grass_block[snowy=false]"
FILL = B + "stone"
HEDGE = B + "spruce_leaves[distance=7,persistent=true,waterlogged=false]"
BRONZE = B + "waxed_copper_block"
BRONZE2 = B + "waxed_exposed_copper"
LAMP = B + "sea_lantern"
POST = B + "diorite_wall"                      # The default state is a thin post (not connected to neighbors)
LANTERN = B + "lantern[hanging=false,waterlogged=false]"

# Paifang (local u along its width): centers of the six pillars (where the pillar feet bump
# out of the OSM outline, symmetric about the center)
GATE_PILLARS = (8.45, 22.4, 33.65)

# National Theater and Concert Hall: dimensions in local coordinates (front facing -v),
# measured from the OSM outlines (drip lines)
THEATER_SPEC = PK.HallSpec(ca=35.5, cb=43.8, wa=51.8, wb=29.5, sw=10.0, sd=13.5,
                           roof="hip", ridge=24.0)
CONCERT_SPEC = PK.HallSpec(ca=33.0, cb=43.9, wa=51.2, wb=29.6, sw=10.5, sd=13.5,
                           roof="hip_gable", ridge=21.0)

# Perimeter corridor: the north and south sides at v = ±167 (the Gates of Great Loyalty
# and Great Piety and the corridor pavilions all lie on this line), the east side at
# u = +160 (beyond the grounds' buildings behind the memorial hall)
PARK_V = 167.0
PARK_E = 160.0


def _ring(f):
    return max(f["outer"], key=len)


class CksMemorial(Attraction):
    height_m = 70.0
    margin = 10

    def __init__(self, item):
        super().__init__(item)
        self.hall_c = PK.ring_centroid(_ring(self.feature(HALL_ROOF)))
        self.gate_c = PK.ring_centroid(_ring(self.feature(GATE)))
        self.theta = math.atan2(self.hall_c[1] - self.gate_c[1], self.hall_c[0] - self.gate_c[0])
        self.axis = Frame(self.hall_c[0], self.hall_c[1], self.theta, 1)   # Used only for coordinate conversion
        self.gate_u = self.axis.local(self.gate_c[0] - 0.5, self.gate_c[1] - 0.5)[0]

    # ---- Extent ----
    def _corners(self):
        """The four corners of the grounds' outer frame (local coordinates), converted to
        world coordinates."""
        return [self.axis.world(u, v) for u in (self.gate_u - 30, PARK_E + 4)
                for v in (-PARK_V - 16, PARK_V + 16)]

    def bbox(self):
        pts = list(self._corners())
        for osm in (HALL_BASE, THEATER, CONCERT, GATE, PLAZA, BLVD, LOYALTY, PIETY, SW_WALL):
            f = self.feature(osm)
            if f and f.get("outer"):
                pts += _ring(f)
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        m = self.margin
        return (int(math.floor(min(xs))) - m, int(math.floor(min(zs))) - m,
                int(math.ceil(max(xs))) + m, int(math.ceil(max(zs))) + m)

    # ---- Planning ----
    def plan(self, site):
        ax = self.axis
        # Main frame: the whole grounds (local u from outside the paifang to the east
        # corridor)
        ua = (self.gate_u - 40 + PARK_E + 10) / 2.0
        self.ua = ua
        self.fa = PK.sub_frame(ax, ua, 0.0, (PARK_E + 10 - (self.gate_u - 40)) / 2.0 + 2)
        self.fh = PK.sub_frame(ax, 0.0, 0.0, 92)
        self.fg = PK.sub_frame(ax, self.gate_u, 0.0, 46, turn=math.pi / 2)
        self.ft = self._hall_frame(THEATER, THEATER_SPEC, 0.0)
        self.fc = self._hall_frame(CONCERT, CONCERT_SPEC, math.pi)
        fa = self.fa
        Uc, Vc = fa.U + ua, fa.V
        aV = np.abs(Vc)
        self.park = (Uc >= self.gate_u - 1) & (Uc <= PARK_E + 1) & (aV <= PARK_V + 1)
        # Grading area: the grounds plus the drum stones outside the paifang and the two
        # western wall sections
        walls = fa.empty()
        for poly in self._wall_rings():
            walls |= fa.polygon(poly)
        self.level = self.park | ((Uc >= self.gate_u - 12) & (aV <= 45)) | kit.dilate(walls, 2)
        # Site ground: the median of one sample every 5 m within the grounds (the plaza,
        # boulevard and memorial hall are all at one height)
        sample = self.park & (fa.X % 5 == 0) & (fa.Z % 5 == 0)
        gs = [site.g(x, z) for x, z in zip(fa.X[sample].tolist(), fa.Z[sample].tolist())]
        self.G = int(np.round(np.median(gs))) if gs else 64
        self.g0 = self.G
        # Grading needs the ground height of every cell; cli's ground function is
        # available only during plan, so compute and store it here
        self.gnd = site.grid(fa, self.level)
        G = self.G
        # Viewpoint: at the east edge of Liberty Square on the axis, facing the memorial
        # hall (with the paifang behind)
        spots = []
        for key, u, v, y, tu, ty, zh, en in (
                ("", -300.0, 0.0, G + 1, 0.0, G + 35, self.name_zh, self.name_en),
                ("hall", -13.5, 3.0, G + 15, 15.5, G + 21, "紀念堂大廳", "Main Hall"),
                ("arch", self.gate_u + 34, 0.0, G + 1, self.gate_u, G + 17, "自由廣場牌樓",
                 "Liberty Square Gate")):
            x, z = ax.cell(u, v)
            tx, tz = ax.world(tu, 0.0)
            yaw, pitch = kit.look(x, y, z, tx, ty, tz)
            spots.append(Spot(key, x, y, z, yaw, pitch, zh, en))
        self._spots = spots

    def _hall_frame(self, osm, spec, turn):
        """Local frame for the National Theater or Concert Hall: oriented like the axis (the
        Concert Hall turned 180°, so both fronts face -v), centered on the OSM outline's
        bounding box in that orientation (less the grand staircase at the front and the
        wing corners at the back)."""
        ring = _ring(self.feature(osm))
        c = PK.ring_centroid(ring)
        f0 = Frame(c[0], c[1], self.theta + turn, 1)
        u0, u1, v0, v1 = PK.local_bbox(f0, ring)
        uc = (u0 + u1) / 2.0
        vc = ((v0 + spec.sd) + (v1 - 2.0)) / 2.0
        x, z = f0.world(uc, vc)
        return Frame(x, z, self.theta + turn, max(spec.wa, spec.cb + spec.sd) + 8)

    def plaque(self):
        return [self.name_zh, self.name_en, "高 70 m，1980 年落成",
                "正面 84 階＋大廳 5 階＝89 階"]

    def plaque_en(self):
        return ["70 m high, completed in 1980", "70 m high, 1980"]

    # ---- Building ----
    def build(self, w):
        self._grounds(w)
        self._walls(w)
        PK.palace_hall(w, self.ft, THEATER_SPEC, self.G)
        PK.palace_hall(w, self.fc, CONCERT_SPEC, self.G)
        self._gate(w)
        self._side_gates(w)
        self._hall(w)

    # ---------------------------------------------------------------- Ground
    def _grounds(self, w):
        """Grading (the whole grounds leveled to G), paving, lawns, hedges and trees clipped
        into cones."""
        fa, G, ua = self.fa, self.G, self.ua
        p = Painter(w, fa)
        Uc, Vc = fa.U + ua, fa.V
        aV = np.abs(Vc)
        plaza = fa.polygon(_ring(self.feature(PLAZA)))
        blvd = fa.polygon(_ring(self.feature(BLVD)))
        west = (Uc >= self.gate_u - 1) & (Uc <= -410) & (aV <= 62)
        fore = (Uc >= -96) & (Uc <= -84) & (aV <= 53)
        hallring = (np.maximum(np.abs(Uc), aV) <= 70)
        apron_t = (Uc >= -418) & (Uc <= -292) & (aV >= 48) & (aV <= 164)
        side = (np.abs(Uc) <= 4) & (aV <= PARK_V)
        corridor = aV >= PARK_V - 4
        paved = plaza | blvd | west | fore | hallring | apron_t | side | corridor
        gate_apron = (Uc >= self.gate_u - 12) & (Uc < self.gate_u - 1) & (aV <= 45)
        paved = (paved & self.park) | gate_apron
        # Paving pattern: a dark dividing line every 8 m across the plaza and a pale band
        # along the axis
        grid = ((np.floor(Uc) % 8) == 0) | ((np.floor(Vc) % 8) == 0)
        axis = aV <= 2.0
        lv = self.level
        X, Z = fa.X[lv].tolist(), fa.Z[lv].tolist()
        GN = self.gnd[lv].tolist()
        PV, GR, AX, PL = (paved[lv].tolist(), grid[lv].tolist(),
                          axis[lv].tolist(), (plaza | west)[lv].tolist())
        s = p.set
        for x, z, gy, pv, gr, ax_, pl in zip(X, Z, GN, PV, GR, AX, PL):
            if gy < G:
                for y in range(max(gy + 1, G - 8), G):
                    s(x, y, z, FILL)
            elif gy > G:
                for y in range(G + 1, min(gy, G + 12) + 1):
                    s(x, y, z, kit.AIR)
            if not pv:
                s(x, G, z, GRASS)
            elif ax_:
                s(x, G, z, PAVE3)
            elif pl and gr:
                s(x, G, z, PAVE2)
            else:
                s(x, G, z, PAVE if pl else PAVE2)
        # Lawns on both sides of Democracy Boulevard: hedges along the paving edge and a row
        # of cone-clipped trees down the middle of each lawn
        zone = (Uc >= -249) & (Uc <= -92) & self.park
        lawn = zone & ~paved
        edge = lawn & kit.dilate(paved, 1) & ~kit.erode(lawn, 1)
        p.layer(edge & zone, G + 1, HEDGE)
        for vv in (-32.5, 32.5):
            for uu in np.arange(-240.0, -95.0, 12.0):
                self._cone(p, uu - ua, vv, G + 1)
        # Street lamps: on both sides of the boulevard's central paving and along the north
        # and south edges of the plaza, one every 16 m (3 m post with a lantern on top)
        posts = [(uu, vv) for uu in np.arange(-244.0, -95.0, 16.0) for vv in (-19.5, 19.5)]
        posts += [(uu, vv) for uu in np.arange(-408.0, -296.0, 16.0) for vv in (-57.0, 57.0)]
        for uu, vv in posts:
            x, z = fa.cell(uu - ua, vv)
            for y in range(G + 1, G + 4):
                p.set(x, y, z, POST)
            p.set(x, G + 4, z, LANTERN)

    def _cone(self, p, u, v, y0):
        """A tree clipped into a cone (the kind lining Democracy Boulevard), 5 m high, made
        only of leaves (which neither grow nor decay)."""
        fa = p.fr
        d = np.hypot(fa.U - u, fa.V - v)
        for k, r in enumerate((1.9, 1.6, 1.2, 0.8, 0.3)):
            p.layer(d <= r + 0.2, y0 + k, HEDGE)

    # ---------------------------------------------------------------- Corridor
    def _walls(self, w):
        """The white-walled, blue-tiled corridor around the grounds: outer wall 4 m high with
        a lattice window every 8 m, a row of white columns on the inside, and a single-pitch
        blue-tiled roof (at most 5 m above the ground, so it does not block the view). The
        southwest corner follows the OSM wall, mirrored to the northwest corner."""
        fa, G, ua = self.fa, self.G, self.ua
        p = Painter(w, fa)
        Uc, Vc = fa.U + ua, fa.V
        aV = np.abs(Vc)
        # North and south sides (leaving gaps for the Gates of Great Loyalty and Great
        # Piety) and the east side
        ns = (Uc >= self.gate_u + 2) & (Uc <= PARK_E + 1) & ~((Uc > -12.5) & (Uc < 13.5))
        ea = aV <= PARK_V + 1
        outer_ns = ns & (aV > PARK_V) & (aV <= PARK_V + 1)
        outer_e = ea & (Uc > PARK_E) & (Uc <= PARK_E + 1)
        band_ns = ns & (aV > PARK_V - 3.5) & (aV <= PARK_V + 1)
        band_e = ea & (Uc > PARK_E - 3.5) & (Uc <= PARK_E + 1)
        cor = band_ns | band_e
        p.fill(outer_ns | outer_e, G + 1, G + 4, WHITE)
        # Lattice windows: one 2×2 every 8 m
        win = (outer_ns & ((np.floor(Uc) % 8) < 2)) | (outer_e & ((np.floor(Vc) % 8) < 2))
        p.fill(win, G + 2, G + 3, kit.AIR)
        # Inner columns: one every 4 m
        cols = ((ns & (aV > PARK_V - 3.5) & (aV <= PARK_V - 2.5) & ((np.floor(Uc) % 4) == 0)) |
                (ea & (Uc > PARK_E - 3.5) & (Uc <= PARK_E - 2.5) & (aV <= PARK_V - 2.5)
                 & ((np.floor(Vc) % 4) == 0)))
        p.fill(cols, G + 1, G + 3, WHITE)
        # Single-pitch roof: the 2 m next to the outer wall at G+5 (with a beam at G+4
        # below), the inner edge at G+4
        dist = np.minimum(np.where(band_ns, PARK_V + 1 - aV, 99.0),
                          np.where(band_e, PARK_E + 1 - Uc, 99.0))
        hi = cor & (dist <= 2.0)
        p.layer(hi, G + 4, WHITE)
        p.layer(hi, G + 5, BLUE)
        p.layer(cor & ~hi, G + 4, BLUE)
        # The southwest wall (OSM) and its mirror image in the north
        for poly in self._wall_rings():
            m = fa.polygon(poly)
            p.fill(m, G + 1, G + 4, WHITE)
            p.layer(m, G + 5, BLUE)

    def _wall_rings(self):
        """The OSM outline of the southwest perimeter wall, and its mirror image across the
        axis at the northwest corner."""
        ring = _ring(self.feature(SW_WALL))
        ax = self.axis
        mirror = []
        for x, z in ring:
            u, v = ax.local(x - 0.5, z - 0.5)          # local() measures cell centers; shift points by half
            mirror.append(ax.world(u, -v))
        return [ring, mirror]

    # ---------------------------------------------------------------- Paifang
    def _gate(self, w):
        """Liberty Square paifang: five bays, six pillars and eleven roofs, 30 m high and
        80 m wide (including the eaves)."""
        G = self.G
        # Proportions measured from photographs (scaled by the 30 m total height): the
        # Sumeru pedestals at the pillar feet are about 5 m; the archways fill only the
        # lower half, with a tall carved wall above; each bay's roof sits on dougong
        # brackets at the top of the wall, and the small roofs on the pillar tops (jialou
        # and bianlou) are lower than the roofs beside them and project from the wall
        c, s2, o = GATE_PILLARS
        pillars = [(-o, 17), (-s2, 18), (-c, 18), (c, 18), (s2, 18), (o, 17)]
        bays = []
        edges = [-o, -s2, -c, c, s2, o]
        tops = {0: (10.5, 23), 1: (9, 21), 2: (8, 19.5)}          # (springing height, wall top height)
        for i in range(5):
            a, b = edges[i], edges[i + 1]
            cen = (a + b) / 2.0
            half = (b - a) / 2.0 - 1.75
            spring, top = tops[abs(i - 2)]
            bays.append((cen, half, spring, top))
        R = PK.Roof
        roofs = [R(0.0, 7.9, 5.4, 25, 3.6),                                 # Central roof (minglou)
                 R(-15.425, 6.3, 5.0, 23, 3.3), R(15.425, 6.3, 5.0, 23, 3.3),       # Secondary roofs (cilou)
                 R(-28.025, 4.9, 4.7, 21.5, 3.0), R(28.025, 4.9, 4.7, 21.5, 3.0),   # Outer roofs (shaolou)
                 R(-c, 2.4, 3.6, 19.5, 2.6), R(c, 2.4, 3.6, 19.5, 2.6),           # Pillar-top roofs (jialou)
                 R(-s2, 2.4, 3.6, 19.5, 2.6), R(s2, 2.4, 3.6, 19.5, 2.6),
                 R(-o - 0.6, 3.0, 3.6, 18.5, 2.6), R(o + 0.6, 3.0, 3.6, 18.5, 2.6)]  # End roofs (bianlou)
        PK.paifang(w, self.fg, G, pillars, bays, roofs, pedestal=(2.6, 3.6, 5))
        # Name board reading Liberty Square, one on the street side and one on the plaza
        # side (above the central archway)
        for sgn in (1, -1):
            x, z = self.fg.cell(0.0, sgn * 2.6)
            fx, fz = self.fg.dir(0.0, sgn)
            w.sign(x, G + 19, z, ["", "自由廣場", "", ""], facing=(fx, fz), kind="wall",
                   wood="birch", color="black")

    def _side_gates(self, w):
        """Gate of Great Loyalty (north) and Gate of Great Piety (south): three-bay gatehouses
        with white walls and blue tiles, placed by their OSM outlines."""
        G = self.G
        R = PK.Roof
        for osm in (LOYALTY, PIETY):
            ring = _ring(self.feature(osm))
            c = PK.ring_centroid(ring)
            fr = Frame(c[0], c[1], self.theta, 16)       # u along the corridor, v through the archways
            pillars = [(-9.2, 8), (-3.4, 10), (3.4, 10), (9.2, 8)]
            bays = [(-6.3, 1.15, 4, 8), (0.0, 1.65, 6, 10), (6.3, 1.15, 4, 8)]
            roofs = [R(-7.2, 3.6, 3.2, 10, 2.5), R(7.2, 3.6, 3.2, 10, 2.5),
                     R(0.0, 5.0, 3.6, 12, 3.0)]
            PK.paifang(w, fr, G, pillars, bays, roofs, pillar_w=1.8, pillar_d=3.0, wall_d=2.4,
                       pedestal=(1.3, 1.9, 2), scrolls=False)

    # ---------------------------------------------------------------- Memorial hall
    def _hall(self, w):
        G, fr = self.G, self.fh
        p = Painter(w, fr)
        U, V = fr.U, fr.V
        aU, aV = np.abs(U), np.abs(V)
        A = np.maximum(aU, aV)
        mn = np.minimum(aU, aV)

        # ---- Three-tier platform (14.5 m): outer tier ±61.8 (OSM), middle tier ±50 (the
        # inner edge of OSM's outermost platform tier), upper tier ±38
        t1, t2, t3 = A <= 61.8, A <= 50.0, A <= 38.0
        tongue = (U >= -85.4) & (U <= -37.5) & (aV <= 19.9)
        top = np.where(t3, G + 14, np.where(t2, G + 9, G + 4))
        base = t1 & ~tongue
        p.fill(base, G + 1, top - 1, WHITE)
        p.fill(base, top, top, FLOOR)
        skip = kit.dilate(tongue, 1)
        PK.balustrade(p, t1 & ~tongue, G + 5, WHITE, PILLAR, WSLAB, skip=skip)
        PK.balustrade(p, t2 & ~tongue, G + 10, WHITE, PILLAR, WSLAB, skip=skip)
        PK.balustrade(p, t3 & ~tongue, G + 15, WHITE, PILLAR, WSLAB, skip=skip | (A <= 36))

        # ---- Grand staircase at the front: two flights of 14 half steps each (0.5 m per
        # step, 14 m in all) with a landing between; a white imperial way up the middle
        s1 = PK.half_flight(U + 85.4, 0.0, 14)
        s2 = PK.half_flight(U + 67.4, 7.0, 14)
        s = np.where(U < -71.4, s1, np.where(U < -67.4, 7.0, np.where(U < -53.4, s2, 14.0)))
        body = tongue & (aV <= 18.9)
        yulu = body & (aV <= 5.5)
        PK.steps(p, body & ~yulu, G, s, GRANITE, GRANITE_S)
        PK.steps(p, yulu, G, s, WHITE, WSLAB)
        # National emblem on the imperial way: a blue ring on the landing, white in the
        # center
        d0 = np.hypot(U + 69.4, V)
        p.layer(yulu & (d0 <= 2.2), G + 7, BLUE_G)
        p.layer(yulu & (d0 <= 1.0), G + 7, WHITE)
        # Low parapets on both sides of the imperial way, and white cheek walls on both
        # outer sides
        sep = tongue & (aV > 5.5) & (aV <= 6.4)
        p.fill(sep, G + 1, G + np.floor(s).astype(int) + 1, WHITE)
        cheek = tongue & (aV > 18.9)
        ci = G + np.ceil(s).astype(int)
        p.fill(cheek, G + 1, ci, WHITE)
        PK.balustrade(p, cheek, ci + 1, WHITE, PILLAR, WSLAB, every=2)

        # ---- Hall body (24 m): the four corners are piers that taper upward (outer edge
        # from 27 m in to 24.5 m), with the middle wall faces at ±24.4
        room = A <= 21.0
        yc = G + 25                       # Springing height of the doorway: doorway G+15..G+30, 16 m high
        for k in range(24):
            y = G + 15 + k
            R = 27.0 - 2.5 * k / 23.0
            bd = (A <= 23.4) | ((mn >= 12.2) & (A <= R))       # Middle recessed one block from the corner piers
            if k >= 22:
                bd = A <= 25.4            # Molding under the eaves
            if y <= G + 33:
                shell = bd & ~room
            else:
                shell = bd
            # Main door: a doorway square below and round above, through the whole wall
            if y <= yc:
                door = aV <= 5.0
            else:
                door = V ** 2 + (y - yc) ** 2 <= 25.5
            door = door & (U < -19.0)
            p.layer(shell & ~door, y, WHITE)
            # Blind arches on the other three sides (recessed one block)
            for along, depth in ((V, U), (U, V), (U, -V)):
                if y <= yc:
                    arch = np.abs(along) <= 5.0
                else:
                    arch = along ** 2 + (y - yc) ** 2 <= 25.5
                p.layer(arch & (depth > 22.4) & (depth <= 23.4) & (mn < 12.2), y, kit.AIR)
                p.layer(arch & (depth > 21.4) & (depth <= 22.4) & (mn < 12.2), y, WHITE2)
            # Door frame (arch face): projects one block from the wall face
            if y <= yc:
                fr_m = (aV > 5.0) & (aV <= 6.5)
            else:
                r2 = V ** 2 + (y - yc) ** 2
                fr_m = (r2 > 25.5) & (r2 <= 42.5)
            p.layer(fr_m & (U >= -24.4) & (U < -23.4), y, TRIM)
            # The open bronze door leaves: against the inner walls on both sides of the
            # doorway
            if y <= G + 29:
                p.layer((U >= -21.9) & (U < -21.0) & (aV > 5.0) & (aV <= 10.0), y, BRONZE)
        # Name board (above the doorway, under the eaves): blue frame, red ground
        pl = (U >= -24.4) & (U < -23.4) & (aV <= 2.6)
        for y in range(G + 32, G + 38):
            edge = (y in (G + 32, G + 37)) | (aV > 1.6)
            p.layer(pl & edge, y, BLUE_G)
            p.layer(pl & ~edge, y, B + "red_terracotta")

        # ---- Main hall: floor, red carpet, caisson ceiling, lamps, statue
        p.layer(room & (aV <= 1.5) & (U >= -21.0) & (U <= 10.5), G + 15, B + "red_carpet")
        rr8 = fr.ngon_radius(8)
        ceil_lamp = room & (A <= 20.0) & (rr8 > 10.0) & ((np.floor(U) % 5) == 0) & ((np.floor(V) % 5) == 0)
        p.layer(ceil_lamp, G + 34, LAMP)
        # Caisson ceiling: three stepped octagonal tiers, topped by the twelve-rayed Blue
        # Sky with a White Sun
        p.layer(rr8 <= 9.0, G + 34, kit.AIR)
        p.layer((rr8 <= 9.0) & (rr8 > 8.0), G + 35, GOLD)
        p.layer(rr8 <= 8.0, G + 35, kit.AIR)
        p.layer((rr8 <= 8.0) & (rr8 > 7.0), G + 36, LAMP)
        p.layer(rr8 <= 7.0, G + 36, kit.AIR)
        r = np.hypot(U, V)
        ang = np.degrees(np.arctan2(V, U)) / 30.0
        frac = np.abs(ang - np.round(ang))
        ray = (r > 2.6) & (r <= 5.6) & (frac <= 0.28 * (1 - (r - 2.6) / 3.0))
        sun = (r <= 2.6) | ray
        p.layer(rr8 <= 7.0, G + 37, BLUE)
        p.layer((rr8 <= 7.0) & sun, G + 37, B + "white_concrete")
        # Back wall: three gold boards behind the statue (Ethics, Democracy, Science)
        # On the inner face of the back wall, projecting one block into the hall
        back = (U > 20.0) & (U <= 21.0)
        for c in (-8.5, 0.0, 8.5):
            m = back & (np.abs(V - c) <= 1.6)
            p.fill(m, G + 27, G + 29, GOLD)
        # Statue: Sumeru pedestal 3 m, seated figure 6 m (6.3 m in public sources)
        plinth = (U >= 11.5) & (U <= 18.5) & (aV <= 4.5)
        p.fill(plinth, G + 15, G + 17, WHITE2)
        p.layer(plinth & ~kit.erode(plinth, 1), G + 17, TRIM)
        PK.seated_statue(p, 15.0, 0.0, G + 18, (-1.0, 0.0), BRONZE, BRONZE2)

        # ---- Roof: the tops of the corner piers are terraces, with the double-eaved
        # octagon in the middle
        p.layer(A <= 25.4, G + 38, WHITE)
        sb = (rr8 > 23.5) & (rr8 <= 24.6)
        PK.band(p, sb, G + 39, G + 40, TEAL, WHITE)
        hl, hips = PK.octagon(fr, 25.6, 30.0, profile=1.5, lift=1.3)
        lr = (rr8 <= 25.6) & (rr8 >= 18.0)
        PK.roof(p, lr, G + 41, hl, BLUE, shell=2, under=WHITE, rim=WHITE, rim_under=WHITE,
                ridge=BLUE_G, ridge_mask=hips & ~kit.ring(lr))
        drum = (rr8 > 16.5) & (rr8 <= 18.0)
        p.fill(drum, G + 41, G + 46, WHITE)
        PK.band(p, drum, G + 47, G + 48, TEAL, WHITE)
        p.layer(drum, G + 49, WHITE)
        p.layer(rr8 <= 16.5, G + 49, WHITE)
        hu, hips2 = PK.octagon(fr, 22.4, 14.6, profile=1.8, lift=1.8)
        ur = rr8 <= 22.4
        PK.roof(p, ur, G + 50, hu, BLUE, shell=2, under=WHITE, rim=WHITE, rim_under=WHITE,
                ridge=BLUE_G, ridge_mask=hips2 & ~kit.ring(ur) & (rr8 > 1.5))
        # Finial: gold, its tip 70 m above the ground
        near = np.hypot(U, V)
        p.fill(near <= 1.3, G + 63, G + 65, GOLD)
        PK.sphere(p, 0.0, 0.0, G + 67.5, 2.5, GOLD, y_min=G + 65)
        p.layer(near <= 0.8, G + 70, GOLD)


BUILDS = {"cks_memorial": CksMemorial}
