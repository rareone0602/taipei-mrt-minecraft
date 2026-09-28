#!/usr/bin/env python3
"""Sun Yat-sen Memorial Hall (1972, designed by Wang Da-hong).

Position, orientation and outline (OSM, data/attractions.json):
  way/189788192         Main building (height 30, roof:shape mansard, roof:height 10,
                        roof:colour gold). The outline is the eave drip line: each side is
                        about 102.6 m, the tips of the upturned corners project 3 m
                        diagonally, and the 6.5 m projection at the middle of the south face
                        is the raised main porch. The whole building is skewed 1.65° from
                        north.
  way/1305268840        Central flat roof (±25.8 m)
  way/1305268839/37/38  Sloped roofs on the east, west and north sides
  way/1305268835        Main porch (|u| <= 17.5)
  way/1305268833/34/36  Roofs beside and behind the porch
  The main entrance faces south (the Ren'ai Road side; the address is No. 505, Sec. 4,
  Ren'ai Road).

Appearance (public sources: Chinese Wikipedia "National Dr. Sun Yat-sen Memorial Hall"
and the "Beauty of the Monument" page of the hall's official website; photographs were
used only to measure proportions):
  · 29.6–30.4 m tall; square plan, 100 m per side; steel-reinforced concrete
  · A large yellow roof in Tang style whose corners sweep high (evoking the brushstrokes of
    the character ren, "person"), with a flat roof at the center drained by slopes on four
    sides; on the front the roof lifts as a whole to form a tall porch
  · 14 large gray columns per side, with the edges of columns and beams chamfered at 135°;
    the walls are fair-faced brick clad in ochre-red porcelain tiles; a gallery with a
    curved-back (meirenkao) railing runs all around; doors are 1:4 in width to height
  · At the center of the main hall stands a seated bronze statue of Sun Yat-sen (by Chen
    Yi-fan; 5.8 m for the figure, 8.9 m with the pedestal)
Proportions (from a frontal photograph, scaled to a total height of 30 m): lowest eave
about 13 m, corner tips about 19.5 m, the junction of the sloped roofs and the flat roof
about 26 m, top of the porch 30 m.
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions import palace_kit as PK
from mrt.application.attractions.kit import Attraction, Frame, Painter, Spot

MAIN = "way/189788192"

B = "minecraft:"
TILE = B + "honeycomb_block"                 # Yellow glazed tiles (orange-gold in photographs).
HIP = B + "light_gray_concrete"              # Gray hip ridges and eave trim.
SOFFIT = B + "gray_concrete"                 # Eave soffit (dark gray in photographs).
COLUMN = B + "smooth_stone"                  # Gray columns and the porch.
BEAM = B + "light_gray_concrete"
WALL = B + "red_terracotta"                  # Ochre-red porcelain tiles.
FLAT = B + "packed_mud"                      # Central flat roof (brown in photographs).
BASE = B + "smooth_stone"
STEP = B + "smooth_stone_slab[type=bottom]"
GLASS = B + "gray_stained_glass"
PAVE = B + "smooth_stone"
PAVE2 = B + "polished_andesite"
GRASS = B + "grass_block[snowy=false]"
FILL = B + "stone"
LAMP = B + "sea_lantern"
BRONZE = B + "waxed_copper_block"
BRONZE2 = B + "waxed_exposed_copper"
PLINTH = B + "polished_granite"

E = 51.4          # Half-width of the eave drip line.
F = 25.8          # Half-width of the central flat roof.
C = 47.0          # Colonnade.
W = 43.0          # Outer wall (the gallery runs between the columns and the wall).
PU = 17.5         # Half-width of the porch.
PV0, PV1 = 38.4, 57.6    # Depth range of the porch (OSM).
E_MIN, E_CORNER, RIDGE, PORCH = 13.0, 19.5, 26.0, 29.5


def eave_height(s, front):
    """Return the eave height in meters above ground.

    s is the distance along the eave from the centerline. The eave is level along the
    middle and curves up to 19.5 m toward the four corners; on the front, beside the porch,
    it sweeps further up to the top of the porch."""
    k = ((s - 22.0) / (E - 22.0)).clip(0, None)
    e = E_MIN + (E_CORNER - E_MIN) * k ** 2.2
    if front:
        t = (1.0 - (s - PU) / 13.0).clip(0, 1)
        e = np.maximum(e, E_MIN + (PORCH - E_MIN) * t ** 2.2)
    return e


class SunYatSenMemorial(Attraction):
    height_m = 30.0
    margin = 12

    def __init__(self, item):
        super().__init__(item)
        ring = self.outline()
        self.theta = PK.fine_angle(ring)
        c = PK.ring_centroid(ring)
        f0 = Frame(c[0], c[1], self.theta, 1)
        pts = [f0.local(x - 0.5, z - 0.5) for x, z in ring]
        us = [p[0] for p in pts]
        # The four corner tips (the porch excluded).
        tips = [p[1] for p in pts if abs(p[0]) > 30]
        uc, vc = (min(us) + max(us)) / 2.0, (min(tips) + max(tips)) / 2.0
        self.c = f0.world(uc, vc)

    def bbox(self):
        fr = Frame(self.c[0], self.c[1], self.theta, 1)
        pts = [fr.world(u, v) for u in (-70, 70) for v in (-66, 130)]
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        return (int(math.floor(min(xs))), int(math.floor(min(zs))),
                int(math.ceil(max(xs))), int(math.ceil(max(zs))))

    def plan(self, site):
        # Frame: origin at the building center; v points south
        # (the front). The extent includes the front plaza.
        self.fr = Frame(self.c[0], self.c[1], self.theta, 132)
        fr = self.fr
        U, V = fr.U, fr.V
        self.level = (np.abs(U) <= 68) & (V >= -64) & (V <= 128)
        sample = self.level & (fr.X % 4 == 0) & (fr.Z % 4 == 0) & (np.abs(U) <= 60) & (V <= 60)
        gs = [site.g(x, z) for x, z in zip(fr.X[sample].tolist(), fr.Z[sample].tolist())]
        self.G = int(np.round(np.median(gs))) if gs else 64
        self.g0 = self.G
        self.gnd = site.grid(fr, self.level)
        G = self.G
        spots = []
        for key, u, v, y, tu, tv, ty, zh, en in (
                ("", 0.0, 112.0, G + 1, 0.0, 0.0, G + 15, self.name_zh, self.name_en),
                ("hall", 6.0, 36.0, G + 2, 0.0, 26.0, G + 7, "國父銅像", "Statue of Dr. Sun Yat-sen")):
            x, z = fr.cell(u, v)
            tx, tz = fr.world(tu, tv)
            yaw, pitch = kit.look(x, y, z, tx, ty, tz)
            spots.append(Spot(key, x, y, z, yaw, pitch, zh, en))
        self._spots = spots

    def plaque(self):
        return [self.name_zh, self.name_en, "1972 年落成，王大閎設計",
                "每邊 14 根灰柱、黃色大屋頂"]

    def plaque_en(self):
        return ["Completed in 1972, designed by Wang Da-hong", "Completed in 1972"]

    # ---- Building ----
    def build(self, w):
        fr, G = self.fr, self.G
        p = Painter(w, fr)
        U, V = fr.U, fr.V
        aU, aV = np.abs(U), np.abs(V)
        A = np.maximum(aU, aV)
        porch = (aU <= PU) & (V > PV0 - 0.5) & (V <= PV1)

        # ---- Grading: a large plaza at the front (south), a walkway all around the building
        plaza = (aU <= 62) & (V > E) & (V <= 126)
        walk = (A <= E + 7)
        paved = plaza | walk
        grid = ((np.floor(U) % 6) == 0) | ((np.floor(V) % 6) == 0)
        lv = self.level
        X, Z = fr.X[lv].tolist(), fr.Z[lv].tolist()
        s = p.set
        for x, z, gy, pv, gr in zip(X, Z, self.gnd[lv].tolist(), paved[lv].tolist(), grid[lv].tolist()):
            if gy < G:
                for y in range(max(gy + 1, G - 8), G):
                    s(x, y, z, FILL)
            elif gy > G:
                for y in range(G + 1, min(gy, G + 12) + 1):
                    s(x, y, z, kit.AIR)
            s(x, G, z, (PAVE2 if gr else PAVE) if pv else GRASS)

        # ---- Platform (1 m) and one step around it
        plat = (A <= E - 1.9) | ((aU <= PU) & (V <= PV1))
        p.layer(plat, G + 1, BASE)
        p.layer(kit.dilate(plat, 1) & ~plat, G + 1, STEP)

        # ---- Outer wall (ochre red) and interior
        wall = A <= W
        p.walls(wall, G + 2, G + 12, WALL)
        p.layer(kit.erode(wall, 1), G + 13, BEAM)                 # Interior ceiling.
        lamps = kit.erode(wall, 2) & ((np.floor(U) % 7) == 0) & ((np.floor(V) % 7) == 0)
        p.layer(lamps, G + 13, LAMP)
        # Main entrance: a full glass wall behind the porch (tall, narrow doors and windows, 1:4)
        # with three doorways.
        facade = (aU <= PU - 2) & (V > W - 1) & (V <= W)
        p.fill(facade, G + 2, G + 12, GLASS)
        mull = facade & ((np.floor(U) % 4) == 0)
        p.fill(mull, G + 2, G + 12, COLUMN)
        doors = facade & ((aU <= 1.5) | ((aU >= 5.0) & (aU <= 7.0)))
        p.fill(doors, G + 2, G + 5, kit.AIR)
        # The tall wall inside the porch (from above the glass to the top of the porch).
        p.fill((aU <= PU - 1) & (V > W - 1) & (V <= W), G + 13, G + 26, WALL)
        # Statue of Sun Yat-sen: facing the main entrance, on a 3 m pedestal.
        pl = (aU <= 4.0) & (np.abs(V - 25.0) <= 4.0)
        p.fill(pl, G + 2, G + 4, PLINTH)
        PK.seated_statue(p, 0.0, 25.0, G + 5, (0.0, 1.0), BRONZE, BRONZE2)

        # ---- Columns: 14 per side (the front: 5 each side plus 4 at the porch), chamfered squares
        pts = []
        side = np.linspace(-C, C, 14)
        for t in side:
            pts += [(t, -C), (-C, t), (C, t)]
        for t in (21.8, 28.1, 34.4, 40.7):
            pts += [(t, C), (-t, C)]
        p.columns(pts, 1.0, G + 2, G + 12, COLUMN)
        p.columns([(-6.6, 55.5), (6.6, 55.5)], 1.0, G + 2, G + 26, COLUMN)
        # The large piers on both sides of the porch (joined to the wing walls above).
        post = (np.abs(aU - 15.8) <= 1.2) & (V >= 53.0) & (V <= PV1)
        p.fill(post, G + 2, G + 26, COLUMN)
        # Beam over the columns: a gray ring.
        beam = (A <= C + 1.0) & ~(A <= C - 1.0) & ~porch
        p.layer(beam, G + 12, BEAM)

        # ---- Main roof: slopes on four sides (eave curve in eave_height) around a flat center
        roofm = fr.polygon(self.outline()) & ~porch & ~(A <= F - 0.5)
        front = (aV >= aU) & (V > 0)
        ns = aV >= aU
        s_ = np.where(ns, aU, aV)
        d = np.where(ns, E - aV, E - aU).clip(0, None)
        e = np.where(front, eave_height(s_, True), eave_height(s_, False))
        t = (d / (E - F)).clip(0, 1) ** 1.4
        h = e + (RIDGE - e) * t
        hips = np.abs(aU - aV) <= 0.7
        T = PK.roof(p, roofm, G, h, TILE, shell=2, under=SOFFIT, rim=HIP, rim_under=HIP,
                    ridge=HIP, ridge_mask=hips & roofm & ~kit.ring(roofm), cap_ridge=False)
        flat = A <= F - 0.5
        p.layer(flat, G + 25, FLAT)
        p.layer(flat & ~kit.erode(flat, 1), G + 26, HIP)
        # Build the outer wall right up to the underside of the roof (the corner eaves sweep high,
        # so no gap may be left between the top of the wall and the roof).
        wr = kit.ring(wall) & roofm
        p.fill(wr, G + 13, np.where(wr, T - 3, 0), WALL)

        # ---- Porch: gray frame, top beam and wing walls, under a roof sloping down to the back
        topb = (aU <= PU) & (V >= 53.0) & (V <= PV1)
        p.fill(topb, G + 27, G + 29, BEAM)
        fin = (aU > PU - 1.2) & (aU <= PU) & (V > PV0 - 0.5) & (V <= PV1)
        fin_top = G + 26 + np.rint(3.0 * ((V - PV0) / (PV1 - PV0)).clip(0, 1)).astype(int)
        p.fill(fin, G + 13, fin_top, COLUMN)
        # The front ends of the wing walls turn up.
        p.layer(fin & (V > PV1 - 1.5), G + 30, COLUMN)
        slope = (aU <= PU - 1.2) & (V > F - 0.5) & (V < 53.0)
        hs = 26.0 + 3.0 * ((V - F) / (53.0 - F)).clip(0, 1)
        PK.roof(p, slope, G, hs, TILE, shell=1, under=SOFFIT)
        # Porch ceiling (the soffit).
        p.layer((aU <= PU - 1.2) & (V > W) & (V < 53.0), G + 26, SOFFIT)
        # Inscription board with the hall's name in gold characters on black.
        x, z = fr.cell(0.0, PV1 + 0.6)
        p.fill((aU <= 3.5) & (V > PV1 - 1) & (V <= PV1), G + 27, G + 28, B + "black_concrete")
        fx, fz = fr.dir(0.0, 1.0)
        w.sign(x, G + 28, z, ["", "國父紀念館", "", ""], facing=(fx, fz), kind="wall",
               wood="dark_oak", glow=True, color="#E8C060")


BUILDS = {"sun_yat_sen_memorial": SunYatSenMemorial}
