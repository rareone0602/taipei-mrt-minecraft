#!/usr/bin/env python3
"""National Taiwan Museum, main building (former Kodama and Gotō Memorial Museum, 1915).

Position and outline: OSM way/1050624691 (a straight bar with a central block projecting
front and back and an end pavilion at each end). The four-story central block
way/1050624690 is the hall under the dome. The appearance follows public sources:
  · Designed by Nomura Ichirō and Araki Eiichi, completed in 1915. Neoclassical; the front
    is a Greek-temple hexastyle portico: six Doric columns carry a triangular pediment
    with foliage reliefs. The center is a Roman dome. The plan is a symmetrical straight
    bar, and the main entrance faces north onto Guanqian Road (the museum website's
    "About NTM" and "History, Architecture", the Tourism Administration's attraction
    page, Chinese Wikipedia).
  · The central dome tower is nearly 30 m tall. The hall is ringed by 32 composite
    columns, each 32 shaku (about 9.7 m) tall and 2 shaku 7 sun in diameter. The stained
    glass (mosaic) skylight in the middle of the hall is about 54 shaku (about 16 m) above
    the floor. The walls are granolithic (washed pebble) plaster and the roof is copper
    (the museum website's "History, Architecture, Collections and Renovation").
The principal axis of the OSM outline is off by only 0.5° (0.3° to 0.6° per edge, which
is tracing error), so 0° is used here: the six columns, windows and pilasters then land
exactly on the grid and stay symmetrical. Local u points east and v points south; the
origin is the center of the outline's bounding rectangle (rounded to whole blocks, so
u = 0 is the central axis and the blocks on either side come in pairs).
"""
import math

import numpy as np

from mrt.application.attractions import colonial_kit as CK
from mrt.application.attractions import kit
from mrt.application.attractions.kit import AIR, Attraction, Frame, Spot, erode, dilate

# ---- Materials ----
WALL = "minecraft:smooth_quartz"          # White granolithic plaster wall
RUST = "minecraft:calcite"                # The joint course of the rusticated ground floor
BASE = "minecraft:polished_diorite"       # Plinth and steps
COLUMN = "minecraft:quartz_pillar[axis=y]"
CAPITAL = "minecraft:chiseled_quartz_block"
TRIM = "minecraft:quartz_bricks"
GLASS = "minecraft:gray_stained_glass"
ROOF = "minecraft:waxed_weathered_cut_copper"     # Copper roof (waxed so it stops oxidizing)
ROOF_SLAB = "waxed_weathered_cut_copper_slab"
ROOF_STAIR = "waxed_weathered_cut_copper_stairs"
DOME_RIB = "minecraft:waxed_oxidized_cut_copper"
# Hall floor: black and white marble (Akasaka black marble, Mito white stone)
FLOOR_A = "minecraft:polished_blackstone"
FLOOR_B = "minecraft:smooth_quartz"
LIGHT = "minecraft:sea_lantern"

# ---- Heights (blocks above the ground) ----
H_FLOOR = 2             # Top of the plinth = ground floor (two steps in front of the portico)
# Portico columns: base at +3, capital at +12 (10 m, close to the hall's 32-shaku columns)
H_COL0, H_COL1 = 3, 12
H_ENT = 13              # Entablature (architrave, cornice) at +13 to +14
H_WING = 13             # Cornice of the two wings
H_PED = 5.0             # Pediment height
H_ATTIC = (15, 16)      # Dome base (square parapet)
H_DRUM = (17, 20)       # Dome drum (with windows)
# Dome shell (apex at +27; above it a two-block lantern, copper cap, lightning rod up to +30)
H_DOME0, H_DOME_RISE = 21, 6.0
H_TOP = 30              # Top of the lantern (nearly 30 m)
# Hall skylight (15 m above the ground-floor level at +3; public sources give about 16 m)
H_SKY = 18

# ---- Plan (local coordinates, measured from OSM) ----
CENTER = 11.6           # Half-width of the central block (u ±11.6)
FRONT = -16.0           # Front edge of the portico (v -16)
PORCH_BACK = -10.0      # Rear wall of the portico (where the main entrance is)
WING_N, WING_S = -8.6, 7.7        # North and south walls of the wings
END_U = 31.6            # End pavilions run from |u| 31.6 to 45.5
END_N, END_S = -11.4, 10.1
# Dome center (way/1050624690 spans v -5.9 to 9.3, midpoint
# 1.7, rounded so the colonnade lands on the grid)
DOME_V = 2.0
DOME_R = 7.4            # Dome radius (the block is 15.7 m square, with a parapet ring around it)
# Hexastyle: 2 m square columns at 4 m spacing (portico 22 m wide)
COLS_U = (-10.0, -6.0, -2.0, 2.0, 6.0, 10.0)
# Hall: columns on a 17 m square, 8 per side at 2 m spacing, 32
# in all (the central axis is left as an aisle)
HALL = 8.0
BAY = 5.0               # Wing bays: pilaster, wall, window, window, wall


class NationalTaiwanMuseum(Attraction):
    height_m = float(H_TOP)
    margin = 14

    def __init__(self, item):
        super().__init__(item)
        main = self.feature("way/1050624691") or (self.mains() or [None])[0]
        self.outer = max(main["outer"], key=len) if main and main.get("outer") else self.outline()
        ang = CK.fit_angle(self.outer)
        self.angle = 0.0 if abs(math.degrees(ang)) < 1.0 else ang
        f0 = Frame(0.0, 0.0, self.angle, 1)
        u0, u1, v0, v1 = CK.local_extent(f0, self.outer)
        ox, oz = f0.world((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        self.origin = (float(round(ox)), float(round(oz)))

    def spot_uv(self):
        """Default viewpoint: the south end of Guanqian Road, 40 m north of the portico,
        where the whole facade and the dome are in view.
        (tools/verify_attractions reads only 44 m beyond the outline, so the viewpoint
        cannot be farther away.)"""
        return (0.0, FRONT - 40.0)

    def bbox(self):
        x0, z0, x1, z1 = super().bbox()
        fr = Frame(self.origin[0], self.origin[1], self.angle, 1)
        sx, sz = fr.world(*self.spot_uv())
        return (min(x0, int(sx) - 6), min(z0, int(sz) - 6), max(x1, int(sx) + 6), max(z1, int(sz) + 6))

    def plan(self, site):
        self.fr = fr = Frame(self.origin[0], self.origin[1], self.angle, 58)
        U, V = fr.U, fr.V
        au = np.abs(U)
        center = (au <= CENTER) & (V >= PORCH_BACK) & (V <= 16.0)
        wings = (au <= END_U) & (V >= WING_N) & (V <= WING_S)
        ends = (au >= END_U) & (au <= 45.5) & (V >= END_N) & (V <= END_S)
        self.body = center | wings | ends
        self.porch = (au <= CENTER) & (V >= FRONT) & (V < PORCH_BACK)
        self.foot = fr.polygon(self.outer)
        self.g0 = site.level(fr, self.foot)
        self.site = site
        # Grading and forecourt: paving 3 blocks beyond the outline, and in front of the
        # portico out to v -26. Ground heights must be looked up in plan() (cli clears the
        # terrain cache after plan_all).
        self.yard = dilate(self.body | self.porch, 3) | ((au <= 16) & (V >= FRONT - 10) & (V < FRONT))
        site.grid(fr, self.yard)
        su, sv = self.spot_uv()
        sx, sz = fr.cell(su, sv)
        sy = site.g(sx, sz) + 1
        tx, tz = fr.world(0.0, -4.0)
        yaw, pitch = kit.look(sx, sy, sz, tx, self.g0 + 14, tz)
        self._spots = [Spot("", sx, sy, sz, yaw, pitch, self.name_zh, self.name_en)]

    def plaque(self):
        return [self.name_zh, self.name_en, "1915 年落成", "臺灣最早的博物館"]

    def plaque_en(self):
        return ["Completed in 1915", "Built in 1915"]

    # ---- Build ----
    def build(self, w):
        fr, g0 = self.fr, self.g0
        m = CK.Mason(w, fr)
        U, V = fr.U, fr.V
        au = np.abs(U)
        body, porch = self.body, self.porch

        self.site.prepare(w, fr, self.yard, g0, top="minecraft:polished_andesite", clear=40)
        m.fill((au <= 13) & (V >= FRONT - 10) & (V < FRONT - 2), g0, g0, "minecraft:stone_bricks")

        # Plinth (+1 to +2) and floor
        m.fill(body | porch, g0 + 1, g0 + H_FLOOR, BASE)
        # Two steps in front of the portico (v -18 to -16): the outer row at +1, the inner row at +2
        for dv, dy in ((-2.0, 1), (-1.0, 2)):
            steps = (au <= CENTER + 0.4) & (V >= FRONT + dv) & (V < FRONT + dv + 1.0)
            if dy > 1:
                m.fill(steps, g0 + 1, g0 + dy - 1, BASE)
            for x, z in fr.cells(steps):
                m.set(x, g0 + dy, z, CK.stair("polished_diorite_stairs", m.facing(0, 1)))

        # Outer walls: the wings and end pavilions have two
        # stories; the central block is the same height
        corners = CK.convex_corners([CK.to_local(fr, x, z) for x, z in self._body_poly()])
        m.facade(body, g0 + H_FLOOR + 1, g0 + H_WING - 1, self._wall_pattern, base=g0, corners=corners)
        m.fill(erode(body, 2), g0 + 8, g0 + 8, "minecraft:smooth_stone")
        # Entablature: architrave + projecting cornice + parapet
        m.fill(body, g0 + H_WING, g0 + H_WING, WALL)
        self._cornice(m, body, g0 + H_WING)
        rim = body & ~erode(body, 1)
        m.fill(rim, g0 + H_WING + 1, g0 + H_WING + 1, WALL)
        m.fill(rim, g0 + H_WING + 2, g0 + H_WING + 2, CK.slab("smooth_quartz_slab"))
        # The end pavilions get one more parapet course (slightly higher than the wings)
        ends = body & (au >= END_U)
        m.fill(ends & ~erode(ends, 1), g0 + H_WING + 2, g0 + H_WING + 2, WALL)
        # Copper roofs of the wings: low-pitched hip roofs inside the parapet
        inner = erode(body, 1) & ~(au <= CENTER)
        d = kit.depth(inner).astype(float)
        m.roof(inner, g0 + H_WING + 1, np.minimum(d * 0.35, 2.5), ROOF, slab_name=ROOF_SLAB, shell=1)

        self._portico(m)
        self._hall(m)
        self._dome(m)

    def _body_poly(self):
        """Simplified outline of the outer walls (local -> world), used only to find the
        convex corners for the quoins."""
        pts = [(-45.5, END_N), (-END_U, END_N), (-END_U, WING_N), (-CENTER, WING_N), (-CENTER, PORCH_BACK),
               (CENTER, PORCH_BACK), (CENTER, WING_N), (END_U, WING_N), (END_U, END_N), (45.5, END_N),
               (45.5, END_S), (END_U, END_S), (END_U, WING_S), (CENTER, WING_S), (CENTER, 16.0),
               (-CENTER, 16.0), (-CENTER, WING_S), (-END_U, WING_S), (-END_U, END_S), (-45.5, END_S)]
        return [self.fr.world(u, v) for u, v in pts]

    # ---- Facade ----
    def _wall_pattern(self, face, t, h, layer, u, v, q=None):
        """Rusticated ground floor (a joint every two courses) with square windows; on the
        upper floor, Doric pilasters flank tall windows capped by stone lintels.
        A window is a hollow in the outer layer with glass in the inner layer."""
        if q is not None and q < 1.2 and layer == 0:      # Wall corner: pilaster
            return COLUMN if h < H_WING - 1 else CAPITAL
        # Bays on the north and south walls start at |u| 11.6
        off = 1.6 if face[1] else 0.0
        bay = BAY
        if abs(u) >= END_U - 0.5 and face[1]:
            # End pavilions: three bays (pilasters at |u| 31.6, 36.2, 40.8, 45.4)
            off, bay = END_U % 4.6, 4.6
        # East and west end walls are centered on v -0.65
        p = (abs(t) - off) % bay if face[1] else (t - 1.85) % bay
        pil = p < 0.5 or p >= bay - 0.5
        win = bay / 2 - 1.0 <= p < bay / 2 + 1.0
        opening = win and (3 <= h <= 5 or 8 <= h <= 11)
        if layer:
            return GLASS if opening else WALL
        if opening:
            return AIR
        if h <= 6:                                        # Ground floor
            if h == 6:
                return TRIM
            return RUST if h % 2 == 0 else WALL
        if pil:
            return CAPITAL if h == H_WING - 1 else COLUMN
        if win and h == 7:
            return TRIM                                   # Windowsill
        if win and h == 12:
            return CK.stair("smooth_quartz_stairs", self.fr.facing(*face), "top")   # Window lintel
        return WALL

    def _cornice(self, m, mask, y):
        out = dilate(mask, 1) & ~mask
        fr = self.fr
        for x, z, u, v, face, t in m.ring_cells(dilate(mask, 1)):
            if out[z - fr.z0, x - fr.x0]:
                m.set(x, y, z, CK.stair("smooth_quartz_stairs", m.facing(-face[0], -face[1]), "top"))

    # ---- Portico ----
    def _portico(self, m):
        """Hexastyle portico: six 2 m square Doric columns (base, shaft, capital) carrying
        an architrave and cornice, and above them a triangular pediment (5 m high at the
        center, with stone stairs along the raking edges) with a cartouche in the middle
        of the tympanum."""
        fr, g0 = self.fr, self.g0
        U, V = fr.U, fr.V
        au = np.abs(U)
        porch = self.porch
        # Portico floor and main entrance
        m.fill(porch, g0 + H_FLOOR, g0 + H_FLOOR, BASE)
        m.fill(porch, g0 + H_FLOOR + 1, g0 + H_ENT - 1, AIR)
        for cu in COLS_U:
            # Six columns in the front row, plus one set back at each end so the sides of the
            # portico are not open
            for cv in (FRONT + 1.0, PORCH_BACK - 1.0) if abs(cu) > 9 else (FRONT + 1.0,):
                m.column(cu, cv, g0 + H_COL0, g0 + H_COL1, COLUMN, base=WALL, capital=CAPITAL, size=2.0)
        # Architrave, frieze (triglyphs: a dark block every 2 m) and cornice
        ent = (au <= CENTER) & (V >= FRONT) & (V <= PORCH_BACK)
        m.fill(ent, g0 + H_ENT, g0 + H_ENT, WALL)
        frieze = ent & ~erode(ent, 1)
        m.fill(frieze, g0 + H_ENT + 1, g0 + H_ENT + 1, TRIM)
        m.fill(frieze & (np.floor(U / 2.0) % 2 == 0), g0 + H_ENT + 1, g0 + H_ENT + 1, RUST)
        m.fill(erode(ent, 1), g0 + H_ENT + 1, g0 + H_ENT + 1, WALL)
        self._cornice(m, ent, g0 + H_ENT + 1)
        # Lights in the portico ceiling
        for cu in (-6.0, 0.0, 6.0):
            m.at(cu, (FRONT + PORCH_BACK) / 2.0, g0 + H_ENT, LIGHT)
        # Pediment: a one-block-thick triangular face at the front (stone stairs along the
        # raking edges), and behind it a copper gable roof running back to the central block
        y = g0 + H_ENT + 2
        m.gable(-CENTER - 0.5, CENTER + 0.5, FRONT - 0.5, FRONT + 0.5, y, H_PED, WALL, edge="smooth_quartz_stairs")
        back = (au <= CENTER + 0.5) & (V > FRONT + 0.5) & (V <= PORCH_BACK + 2.0)
        m.roof(back, y, (H_PED - 0.5) * (1.0 - au / (CENTER + 0.5)), ROOF, slab_name=ROOF_SLAB, shell=1)
        # Tympanum: the central cartouche and the foliage on either side (low relief in whites of
        # different texture)
        for du, dy in ((-0.5, 1), (0.5, 1), (-0.5, 2), (0.5, 2), (-0.5, 3), (0.5, 3), (-1.5, 2), (1.5, 2)):
            m.at(du, FRONT - 0.3, y + dy, TRIM)
        for du in (-6.5, -4.5, 4.5, 6.5):
            m.at(du, FRONT - 0.3, y + 1, CAPITAL)
        # Main entrance: the large door behind the central intercolumniation (4 blocks wide, 5 high)
        door = (au <= 2.0) & (V >= PORCH_BACK - 0.5) & (V <= PORCH_BACK + 2.5)
        m.fill(door, g0 + H_FLOOR + 1, g0 + H_FLOOR + 5, AIR)
        m.fill(door & (V > PORCH_BACK + 1.5), g0 + H_FLOOR + 6, g0 + H_FLOOR + 6, TRIM)

    # ---- Dome ----
    def _dome(self, m):
        """Square base (parapet) -> round drum (eight windows) -> copper dome (eight ribs)
        -> lantern, with the top at nearly 30 m. Built after the hall, so the shell covers
        whatever the hall's hollowing cut away."""
        fr, g0 = self.fr, self.g0
        U, V = fr.U, fr.V
        R = np.hypot(U, V - DOME_V)
        base = (np.abs(U) <= 7.8) & (np.abs(V - DOME_V) <= 7.6)
        drum = R <= 6.8
        # Roof of the central block (inside the parapet, outside the dome base)
        center = (np.abs(U) <= CENTER) & (V >= PORCH_BACK) & (V <= 16.0)
        m.fill(erode(center, 1) & ~base, g0 + H_WING + 1, g0 + H_WING + 1, ROOF)

        def attic(face, t, h, layer, u, v, q=None):
            if h == H_ATTIC[1]:
                return TRIM
            if abs(t - (DOME_V if face[0] else 0.0)) < 1.0 and h == 15:
                return GLASS
            return WALL

        m.facade(base, g0 + H_ATTIC[0] - 1, g0 + H_ATTIC[1], attic, base=g0, layers=1)
        m.fill(base & ~drum, g0 + H_ATTIC[1] + 1, g0 + H_ATTIC[1] + 1, ROOF)

        def drum_pat(face, t, h, layer, u, v, q=None):
            a = math.degrees(math.atan2(v - DOME_V, u)) % 45.0
            if min(a, 45 - a) < 8.0 and H_DRUM[0] + 1 <= h <= H_DRUM[1] - 1:     # Eight windows
                return GLASS
            if h == H_DRUM[1]:
                return TRIM
            return WALL

        m.facade(drum, g0 + H_DRUM[0], g0 + H_DRUM[1], drum_pat, base=g0, layers=1)
        ring = (R <= 7.8) & (R > 6.8)
        m.fill(ring, g0 + H_DRUM[1], g0 + H_DRUM[1], CK.slab("smooth_quartz_slab", "top"))
        # Dome shell (above the drum)
        m.dome(0.0, DOME_V, DOME_R, g0 + H_DOME0, H_DOME_RISE, ROOF, shell=2, slab_name=ROOF_SLAB,
               rib=DOME_RIB, ribs=8)
        # Lantern: four small columns (+27 to +28), a copper cap (+29) and a lightning rod at +30
        top = g0 + H_TOP - 3
        for k in range(4):
            ph = math.radians(45 + 90 * k)
            m.column(1.2 * math.cos(ph), DOME_V + 1.2 * math.sin(ph), top, top + 1, COLUMN)
        m.fill(R <= 1.8, top + 2, top + 2, ROOF)
        m.at(0.0, DOME_V, g0 + H_TOP, "minecraft:waxed_weathered_lightning_rod[facing=up,powered=false]")

    # ---- Hall ----
    def _hall(self, m):
        """The hall under the dome (reachable from the portico): a black and white marble
        floor, 32 composite columns (on a 17 m square, 8 per side at 2 m spacing, 10 m tall),
        an entablature ring above the columns with a coffered ceiling stepping inward, a
        stained glass skylight 15 m above the floor (public sources give about 16 m), and a
        ring of sea lanterns on the entablature and above the skylight."""
        fr, g0 = self.fr, self.g0
        U, V = fr.U, fr.V
        au = np.abs(U)
        hall = (au <= CENTER - 1.0) & (V >= PORCH_BACK + 1.0) & (V <= 15.0)
        y0 = g0 + H_FLOOR
        m.fill(hall, y0 + 1, g0 + H_SKY, AIR)
        checker = ((np.floor(U) + np.floor(V)) % 2 == 0)
        m.fill(hall & checker, y0, y0, FLOOR_A)
        m.fill(hall & ~checker, y0, y0, FLOOR_B)
        # 32 columns on a 17 m square (u and v 8.5 from the center), 8 per side at 2 m
        # spacing; none at the corners or on the central axis
        n = 0
        ring = HALL + 0.5
        for k in (-7.5, -5.5, -3.5, -1.5, 1.5, 3.5, 5.5, 7.5):
            for cu, cv in ((k, DOME_V - ring), (k, DOME_V + ring), (-ring, DOME_V + k), (ring, DOME_V + k)):
                m.column(cu, cv, y0 + 1, y0 + 10, COLUMN, base=WALL, capital=CAPITAL)
                n += 1
        self.hall_columns = n
        # Entablature above the columns and the open coffered ceiling: it steps inward one
        # block at a time up to the drum; the skylight sits at the bottom of the drum (+18)
        sq = lambda r: (au <= r) & (np.abs(V - DOME_V) <= r)
        R = np.hypot(U, V - DOME_V)
        top = g0 + H_SKY - 1
        m.fill(sq(HALL + 0.5) & ~sq(HALL - 0.5), y0 + 11, y0 + 11, WALL)
        m.fill(hall & ~sq(HALL + 0.5), y0 + 11, top, WALL)
        for k, r in enumerate((HALL - 0.5, HALL - 1.5, HALL - 2.5)):
            m.fill(sq(r + 1) & ~sq(r), y0 + 12 + k, top, WALL)
        m.fill(sq(HALL + 0.5) & ~(R <= 6.0), top, top, WALL)
        # Lights: a ring of sea lanterns on top of the entablature
        lamps = sq(HALL + 0.5) & ~sq(HALL - 0.5) & ((np.floor(U) + np.floor(V)) % 4 == 0)
        m.fill(lamps, y0 + 11, y0 + 11, LIGHT)
        # Stained glass skylight (a circle of radius 5.6): concentric rings and eight radial lines
        sky = R <= 5.6
        ang = (np.degrees(np.arctan2(V - DOME_V, U)) + 360.0) % 45.0
        spoke = (np.minimum(ang, 45.0 - ang) < 5.0) & (R >= 1.3)
        y = g0 + H_SKY
        m.fill((R <= 6.8) & ~sky, y, y, WALL)
        for cond, blk in ((spoke, "minecraft:lime_stained_glass"),
                          (R < 1.3, "minecraft:orange_stained_glass"),
                          ((R >= 2.6) & (R < 3.6), "minecraft:light_blue_stained_glass"),
                          (np.ones(fr.shape, dtype=bool), "minecraft:white_stained_glass")):
            sel = sky & cond
            m.fill(sel, y, y, blk)
            sky = sky & ~cond
        # Above the skylight: the drum and dome are hollow so light comes in through the
        # drum windows; a ring of lights on top of the skylight keeps it lit at night
        m.fill(R <= 6.2, y + 1, g0 + H_DOME0 + 4, AIR)
        m.fill((R <= 5.6) & (R > 4.4) & ((np.floor(U) + np.floor(V)) % 3 == 0), y + 1, y + 1, LIGHT)
        # Vestibule from the portico into the hall
        m.fill((au <= 2.0) & (V >= PORCH_BACK - 0.5) & (V <= DOME_V - HALL - 0.5), y0 + 1, y0 + 5, AIR)
        m.fill((au <= 2.0) & (V >= PORCH_BACK) & (V <= DOME_V - HALL - 0.5), y0, y0, FLOOR_B)


BUILDS = {"national_taiwan_museum": NationalTaiwanMuseum}
