#!/usr/bin/env python3
"""Shin Kong Life Tower: 244.15 m, 51 floors above ground, completed in 1993.

The plan and massing follow OSM. Besides the main outline way/204711206 (62 nodes), OSM
splits the building into thirty-odd building:part elements: a 16-story, 78.56 m
department-store podium (Shin Kong Mitsukoshi, Station Front store) wraps around the
tower and rises to 18 stories at the middle of the north face; the tower body reaches
211.04 m at 50 stories, its north and south ends 48 stories, and its four corners set
back story by story (48 stories at 203.36 m, 46 at 195.68 m, 44 at 187.36 m); two more
sections sit on top (211.04→214.88 m and 214.88→237.67 m). The mask is computed row by
row from each part's min_height / height, so the massing is OSM's massing.

The appearance follows public sources:
  · Heights: antenna 244.15 m, roof 238.15 m (Chinese Wikipedia "Shin Kong Life Tower")
  · Facade: weather-resistant aluminum panels in rose, drawn from the national flowers of
    Taiwan and Japan (Wikipedia "Shin Kong Life Tower"); a pyramid on top (same source)
  · Department store: Shin Kong Mitsukoshi occupies B2 to 13F (Chinese Wikipedia); the
    podium facade is dark brown stone
  · Tower body: one horizontal ribbon window per story; the corners step back in a
    sawtooth
The facade proportions (ribbon windows, podium stone, the pinker color at the top) were
taken from public photographs; no drawing was copied.

The ground-floor lobby is entered through the vestibule on the north face (the side
facing Taipei Main Station). The exits and the underground mall under the station-front
plaza are in keep-out zones, and Guard blocks any write to those cells.
"""
import math

import numpy as np

from mrt.application.attractions import highrise as HR
from mrt.application.attractions import kit
from mrt.application.attractions.kit import Attraction, Frame, Spot
from mrt.domain import geometry as shapes

MAIN = "way/204711206"
# Tower body (50 stories, 211.04 m): fixes the tower's center and orientation.
TOWER_BODY = "way/644774181"

PODIUM_TOP = 78.56                  # Top of the 16-story podium.
TIP = 244                           # Top of the antenna (244.15 m).
# Last row of the top section (up to 237.67 m): the pyramid starts here;
ROOF = 237
                                    # the roof is at about 238 m.
# 46F observatory (open 1994–2006, Chinese Wikipedia): glass all around.
OBS_FLOOR = 46
# From 44 stories up (the first corner setback) the color is a deeper pink.
CROWN_FROM = 183.0

# Materials
PODIUM_A = "minecraft:polished_granite"       # Podium: dark brown stone with a pink cast.
PODIUM_B = "minecraft:granite"
PODIUM_WIN = "minecraft:gray_stained_glass"
SHOP = "minecraft:light_gray_stained_glass"   # Ground-floor shop windows.
SHAFT = "minecraft:white_terracotta"          # Tower body: pale rose aluminum panels.
BAND = "minecraft:cherry_planks"              # Pink line above each ribbon window.
WIN = "minecraft:cyan_stained_glass"          # Gray-blue ribbon windows.
CROWN = "minecraft:cherry_planks"             # Top: a pinker rose.
CROWN_LINE = "minecraft:pink_terracotta"
# Thin overhang at each setback.
LEDGE = "minecraft:smooth_quartz_slab[type=bottom,waterlogged=false]"
ROOF_FLAT = "minecraft:smooth_stone"
PYRAMID = "minecraft:brown_terracotta"        # Dark pyramid roof.
FINIAL = "minecraft:gold_block"
SLAB = "minecraft:smooth_stone"
FLOOR1 = "minecraft:polished_diorite"
LAMP = "minecraft:sea_lantern"
CORE = "minecraft:polished_andesite"
CANOPY = "minecraft:smooth_quartz"
POST = "minecraft:polished_granite"
PLAZA = "minecraft:polished_andesite"


def _num(t, k):
    try:
        return float(str(t[k]).split()[0])
    except (KeyError, ValueError):
        return None


def _inside(poly, x, z):
    """Return whether a point lies inside a polygon (ray casting)."""
    n, c = len(poly), False
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        if (z1 > z) != (z2 > z) and x < (x2 - x1) * (z - z1) / (z2 - z1) + x1:
            c = not c
    return c


def floor_rows():
    """Return the slab rows (blocks above the ground-floor slab).

    Floors 1–16 are the department store at 78.56/16 = 4.91 m per story; from 17F up,
    each story is (211.04 − 78.56)/34 = 3.9 m, and the top of 51F = 211.04 m (OSM)."""
    rows = [int(math.floor(PODIUM_TOP / 16 * k)) for k in range(16)]
    rows += [int(math.floor(PODIUM_TOP + 3.896 * (k - 16))) for k in range(16, 51)]
    return rows


FLOOR_ROWS = floor_rows()
FLOOR_OF = {r: k + 1 for k, r in enumerate(FLOOR_ROWS)}


def floor_of_row(yy):
    k = 0
    for i, r in enumerate(FLOOR_ROWS):
        if r <= yy:
            k = i
        else:
            break
    return k + 1, yy - FLOOR_ROWS[k]


class ShinKongTower(Attraction):
    height_m = 244.15
    margin = 12

    # ---------------------------------------------------------------- Data
    def _ring(self, osm):
        f = self.feature(osm)
        return max(f["outer"], key=len) if f and f.get("outer") else None

    def parts(self):
        """Return the building:part elements inside the main outline.

        Each entry is (osm, outer ring, bottom m, top m, is canopy). Parts without a height
        (the two- or three-story volumes at the entrances) use levels × 4.5 m; those of two
        stories or fewer are built as canopies."""
        main = self._ring(MAIN)
        out = []
        for f in self.features:
            t = f["tags"]
            if "building:part" not in t or not f.get("outer"):
                continue
            r = max(f["outer"], key=len)
            cx, cz = shapes.centroid(r)
            if not _inside(main, cx, cz):
                continue
            hi = _num(t, "height")
            lv = _num(t, "building:levels") or 1
            canopy = hi is None and lv <= 2
            if hi is None:
                hi = lv * 4.5
            lo = _num(t, "min_height") or 0.0
            out.append((f["osm"], r, lo, hi, canopy))
        return out

    # ---------------------------------------------------------------- Planning
    def plan(self, site):
        self.site = site
        main = self._ring(MAIN)
        mcx, mcz, _, hu, hv = HR.outline_axes(main)
        tcx, tcz, ang_osm, _, _ = HR.outline_axes(self._ring(TOWER_BODY))
        # The tower body is skewed −0.6°: square up the whole building, every
        # part included, about the tower body's center (highrise.snap_angle).
        # The ends of the main outline move by at most 0.45 m, and the ribbon
        # windows and mullions become straight horizontal and vertical lines.
        ang = HR.snap_angle(ang_osm)
        turn = ang - ang_osm

        def fix(r):
            return HR.rotate_poly(r, tcx, tcz, turn) if turn else r

        self._fix = fix
        main = fix(main)
        self.ang = ang
        self.fr = Frame(mcx, mcz, ang, max(hu, hv) + 10)
        fr = self.fr
        self.foot = fr.polygon(main)
        self.p = []
        self.canopies = []
        for osm, r, lo, hi, canopy in self.parts():
            m = fr.polygon(fix(r))
            if not m.any():
                continue
            (self.canopies if canopy else self.p).append((m, lo, hi))
        self.g0 = site.level(fr, self.foot)
        # Look up the ground heights needed for grading now (Site caches them): cli discards the
        # distance field of the "built terrain" after plan, so looking them up in build() fails.
        self.near = kit.dilate(self.foot, 10) & ~self.foot
        site.grid(fr, self.foot | self.near)
        c, s = math.cos(ang), math.sin(ang)
        self.tuv = ((tcx - mcx) * c + (tcz - mcz) * s, -(tcx - mcx) * s + (tcz - mcz) * c)
        tu, tv = self.tuv
        self.T, self.S = HR.face_coords(fr, tu, tv)
        uu, vv = fr.U - tu, fr.V - tv
        self.core = (np.abs(uu) <= 7) & (np.abs(vv) <= 10)
        self.lamps = HR.grid_mask(fr, 6, 3, tu, tv)
        # Lobby: from the north vestibule to the front of the elevator core, double height.
        self.lobby = (np.abs(uu) <= 8) & (vv < -10)
        # The top section (214.88 -> 237.67 m): the base of the pyramid.
        top = [m for m, lo, hi in self.p if hi > 230]
        self.top_mask = top[0] if top else fr.empty()

        # Viewpoint: the northwest corner of the station-front plaza (the north side, facing
        # Taipei Main Station), with the whole building in frame.
        x0 = min(p[0] for p in main)
        z0 = min(p[1] for p in main)
        vx, vz = int(math.floor(x0)) - 36, int(math.floor(z0)) - 36
        vy = site.g(vx, vz) + 1
        d = math.hypot(tcx - (vx + .5), tcz - (vz + .5))
        up = math.degrees(math.atan2(self.g0 + TIP - (vy + 1.62), d))
        down = math.degrees(math.atan2(vy + 1.62 - self.g0, d))
        yaw, _ = kit.look(vx, vy, vz, tcx, self.g0 + 100, tcz)
        lx, lz = fr.cell(tu, tv - 14.0)
        # Gold emblem on the north podium, 8F–9F.
        self.logo_row = 40
        self._spots = [
            Spot("", vx, vy, vz, yaw, round(-(up - down) / 2.0, 1), self.name_zh, self.name_en),
            Spot("lobby", lx, self.g0 + 1, lz, round(fr.yaw(0, -1), 1), 0.0,
                 "新光摩天大樓 大廳", "Shin Kong Life Tower Lobby"),
        ]

    def part_ring(self, osm):
        """Return an OSM element's outer ring after squaring up.

        Available after plan; tests compare it with the built massing."""
        return self._fix(self._ring(osm))

    def plaque(self):
        return [self.name_zh, self.name_en, "244 m，1993年落成", "地上51層·地下7層"]

    def plaque_en(self):
        return ["244 m high, completed in 1993", "244 m high, 1993"]

    # ---------------------------------------------------------------- Building
    def mass(self, yy):
        """Return the massing of row yy: the union of all parts spanning that height.

        owner is the top (m) of the tallest part covering each cell."""
        t = yy + 0.5
        m = self.fr.empty()
        owner = np.zeros(self.fr.shape)
        for pm, lo, hi in self.p:
            if lo <= t < hi:
                m |= pm
                owner = np.where(pm, np.maximum(owner, hi), owner)
        return m, owner

    def build(self, w):
        fr, g0 = self.fr, self.g0
        self.site.prepare(w, fr, self.foot, g0, top=FLOOR1)
        self._plaza(w)
        cache = {}

        def M(yy):
            if yy not in cache:
                cache[yy] = self.mass(yy) if yy >= 0 else (fr.empty(), np.zeros(fr.shape))
            return cache[yy]

        T = self.T
        col3 = (np.floor(T).astype(int) % 3) == 0
        col4 = (np.floor(T).astype(int) % 4) == 0
        col6 = (np.floor(T).astype(int) % 6) == 0
        panel = ((np.floor(T).astype(int) // 2) % 2) == 0
        for yy in range(0, ROOF):
            m, owner = M(yy)
            if not m.any():
                continue
            mp, _ = M(yy - 1)
            mn, _ = M(yy + 1)
            sh = HR.shell(m, mp, mn)
            y = g0 + yy
            k, kr = floor_of_row(yy)
            podium = sh & (owner <= 90)
            tower = sh & (owner > 90)
            layers = []
            # Podium (department store): dark brown stone, one row of small windows per story;
            # shop windows on the ground floor.
            if yy <= 4:
                layers += [(podium, SHOP), (podium & col4, PODIUM_A)]
            elif kr == 0:
                layers.append((podium, PODIUM_A))
            elif kr == 2:
                layers += [(podium, PODIUM_B), (podium & col3, PODIUM_WIN)]
            else:
                layers += [(podium & panel, PODIUM_A), (podium & ~panel, PODIUM_B)]
            # Tower body: pale rose aluminum panels plus one ribbon window per story; from 44
            # stories up the color turns a deeper pink.
            crown = yy + 0.5 >= CROWN_FROM
            if yy < PODIUM_TOP:
                # Tower body exposed below the podium height
                # (above the 4-story volume on the west side).
                layers.append((tower, SHAFT if kr in (0, 3) else WIN))
            elif k == OBS_FLOOR and kr > 0:
                layers.append((tower, WIN))
            elif not crown:
                # One continuous ribbon window per story, with a narrow mullion every 6 m.
                if kr == 0:
                    layers.append((tower, SHAFT))
                elif kr in (1, 2):
                    layers += [(tower, WIN), (tower & col6, SHAFT)]
                else:
                    layers.append((tower, BAND))
            else:
                if kr in (0, 3):
                    layers.append((tower, CROWN))
                elif kr == 1:
                    layers.append((tower, CROWN_LINE))
                else:
                    layers += [(tower, CROWN), (tower & col3, WIN)]
            HR.paint_layers(w, fr, layers, y)
            # Roofs and setback terraces.
            cap = m & ~mn & ~sh
            HR.paint(w, fr, cap, y, ROOF_FLAT)
            HR.paint(w, fr, sh & ~mn, y, SHAFT if yy >= PODIUM_TOP else PODIUM_A)
            # A thin overhang around the top edge of each setback (visible on the sawtooth corners at
            # 44, 46, 48 and 50 stories).
            if yy >= 150 and (m & ~mn).any():
                eave = kit.dilate(m & ~mn, 1) & ~m
                HR.paint(w, fr, eave, y + 1, LEDGE)
            # Slabs, lamps and the elevator core.
            inner = m & ~sh & ~cap
            if yy in FLOOR_OF and yy > 0:
                sl = inner
                if FLOOR_OF[yy] == 2:
                    sl = sl & ~self.lobby
                HR.paint(w, fr, sl, y, SLAB)
                HR.paint(w, fr, sl & self.lamps, y, LAMP)
            elif yy > 0:
                HR.paint(w, fr, kit.ring(self.core) & inner, y, CORE)
        self._crown(w)
        self._logo(w)
        self._lobby(w)
        self._canopies(w)

    # ---- Top: the pyramid (238 -> 243 m) and the gold finial (244 m) ----
    def _crown(self, w):
        fr, g0 = self.fr, self.g0
        tm = self.top_mask
        if not tm.any():
            return
        tu, tv = self.tuv
        cu = float(fr.U[tm].mean())
        cv = float(fr.V[tm].mean())
        half = max(float(np.abs(fr.U[tm] - cu).max()), float(np.abs(fr.V[tm] - cv).max()))
        cheb = np.maximum(np.abs(fr.U - cu), np.abs(fr.V - cv))
        rise = TIP - 1 - ROOF                      # Pyramid 237 -> 242 m; 243 m is the gold top.
        for i in range(rise):
            r = half + 0.5 - (half / (rise - 0.5)) * i
            HR.paint(w, fr, (cheb <= r) & kit.dilate(tm, 1), g0 + ROOF + i, PYRAMID)
        x, z = fr.cell(cu, cv)
        w.set(x, g0 + TIP - 1, z, FINIAL)
        w.set(x, g0 + TIP, z, "minecraft:lightning_rod[facing=up,powered=false]")

    # ---- Gold emblem on the north podium (an oval badge with the character guang, "light") ----
    def _logo(self, w):
        fr, g0 = self.fr, self.g0
        tu, _ = self.tuv
        m, _ = self.mass(self.logo_row)
        cells = set(zip(fr.X[m].tolist(), fr.Z[m].tolist()))
        face = None
        for k in range(200, 0, -1):
            d = -k * 0.5
            if fr.cell(tu, d) in cells:
                face = d
                break
        if face is None:
            return
        for du in np.arange(-4.0, 4.5, 1.0):
            for dy in (-1, 0, 1):
                e = (du / 4.2) ** 2 + (dy / 1.6) ** 2
                if e <= 1.0:
                    x, z = fr.cell(tu + du, face - 1.0)
                    w.set(x, g0 + self.logo_row + dy, z, FINIAL if e > 0.35 or dy else "minecraft:white_concrete")

    # ---- Ground-floor lobby: doors in the north vestibule, double height, lit ----
    def _lobby(self, w):
        fr, g0 = self.fr, self.g0
        m1, _ = self.mass(1)
        tu, tv = self.tuv
        cells = set(zip(fr.X[m1].tolist(), fr.Z[m1].tolist()))
        hit = None
        for k in range(160, 0, -1):
            d = -k * 0.5
            x, z = fr.cell(tu, d)
            if (x, z) in cells:
                hit = d
                break
        if hit is not None:
            face = kit.cardinal(*fr.dir(0, 1))
            for s, hinge in ((-0.5, "left"), (0.5, "right")):
                x, z = fr.cell(tu + s, hit)
                HR.door(w, x, g0 + 1, z, face, hinge=hinge, block="minecraft:dark_oak_door")
                for dd in (-1.0, 1.0):
                    xx, zz = fr.cell(tu + s, hit + dd)
                    w.set(xx, g0 + 1, zz, kit.AIR)
                    w.set(xx, g0 + 2, zz, kit.AIR)
        # Lobby lights: with the 2F slab removed, the ceiling is the 3F slab; a ring of lamps is
        # set into the paving.
        HR.paint(w, fr, self.lobby & m1 & self.lamps, g0, LAMP)
        HR.paint(w, fr, self.lobby & m1 & self.lamps, g0 + FLOOR_ROWS[2], LAMP)

    # ---- Entrance canopies: a roof slab on posts, walkable underneath ----
    def _canopies(self, w):
        fr, g0 = self.fr, self.g0
        tu, _ = self.tuv
        # One post every 5 m, none in the walkway in front of
        # the main door (5 m wide at the middle).
        post = HR.grid_mask(fr, 5, 0) & ~(np.abs(fr.U - tu) <= 2.5)
        for m, lo, hi in self.canopies:
            m = m & ~self.mass(1)[0]
            if not m.any():
                continue
            HR.paint(w, fr, m, g0 + 5, CANOPY)
            for yy in range(1, 5):
                HR.paint(w, fr, kit.ring(m) & post, g0 + yy, POST)

    # ---- Station-front plaza: pave from the north front of the building to the viewpoint ----
    def _plaza(self, w):
        self.site.prepare(w, self.fr, self.near, self.g0, top=PLAZA, clear=0)


BUILDS = {"shin_kong_tower": ShinKongTower}
