#!/usr/bin/env python3
"""Taipei 101: 508 m and 101 floors above ground, built 1:1 from public architectural facts.

Position, orientation, and the plans of the mall and the podium come from OSM
(data/attractions.json: tower way/198637969, skewed 1.0°, half-width 27 m; mall
way/64566862, 30 m tall; podium way/1159328963 and way/1159328964, 25 m tall; the dome
way/615183624 and its two round lobes way/1339487731 and way/1339487732 form a
ruyi-shaped roof). The tower's appearance follows these public sources:

  · Heights: spire 508 m, roof 449.2 m, top floor 438 m, 89F indoor observatory 382 m,
    91F outdoor observatory about 390 m (the English and Chinese Wikipedia articles
    "Taipei 101")
  · Story height: office floors 4.2 m (structures-explained.com "Taipei 101 structural
    engineering")
  · Form: a truncated-pyramid base 25–26 stories tall, topped by eight inverted
    trapezoidal modules (dou), each eight stories tall and flaring outward by about 7°;
    above them a top section with a much smaller plan (above 91F) and a 60 m spire
    (the same two sources). The first module starts at 27F (the base's moment frame
    ends at 26F: Shieh's NCREE seminar paper on the design of Taipei 101's mega-columns)
  · Plan: the waist is about 45.9 m square (Structure magazine "Dynamic Loading
    Solutions in Taipei 101"), with 2.5 m notches at the corners (same source)
  · Facade ornaments: one disc on each face where the base meets the tower, representing
    an ancient coin (Wikipedia); each ruyi on the facade is at least 8 m tall
    (Wikipedia), placed here at the center of the top of each module
  · Damper: a steel sphere 5.5 m in diameter weighing 660 metric tons, hung between 92F and
    88F (Wikipedia)
  · Curtain wall: blue-green double glazing (Wikipedia)

For the construction method see highrise.py: the mask is computed story by story, the
shell is its outer ring, and overhangs are the cells "present on this story but not on
the one above".
The ground-floor lobby (doors on the south and east faces), the 89F observatory (double
height, glass walls, the damper at the center) and the 91F outdoor observatory are all
walkable. The lobby sign teleports to 89F, and the observatory sign teleports back to
the lobby.
"""
import math

import numpy as np

from mrt import config
from mrt.application.attractions import highrise as HR
from mrt.application.attractions import kit
from mrt.application.attractions.kit import Attraction, Frame, Spot

# ---------------------------------------------------------------- OSM elements
TOWER = "way/198637969"             # The tower (the 89-story part; its plan has notched corners).
MALL = "way/64566862"               # Taipei 101 Mall, 6 stories, 30 m.
# The podium at the tower's foot, 5 stories, 25 m.
SKIRTS = ("way/1159328963", "way/1159328964")
VESTIBULE = "way/1339487722"        # The vestibule of the south entrance.
DOME = ("way/615183624", "way/1339487731", "way/1339487732")   # The ruyi-shaped dome (30 -> 42 m).
CANOPIES = ("way/1339487735", "way/1339487734", "way/1339487736",
            "way/1339487737", "way/1339487738")   # One-story entrance canopies.
# Xinyi skywalks, second-floor level.
SKYWALKS = ("way/1339487709", "way/1339487716", "way/1339401632")
PLAZA = "way/248210267"             # The attraction's grounds (including the plaza).

# ---------------------------------------------------------------- Dimensions (meters)
BASE_A0 = 27.0          # Half-width of the base at ground level (the OSM tower outline is 54 m).
BASE_A1 = 23.5          # Half-width at the top of the base (26F): it tapers inward.
MOD_B0 = 22.0           # Half-width at the bottom of each module (the waist is about 45.9 m).
# Half-width at the top of each module: 4 m of flare over 33.6 m, about 6.8°.
MOD_B1 = 26.0
NOTCH = 2.5             # Two notched steps at each corner, 2.5 m each.
BAY = 7.25              # Projecting bay at the middle of each face of the base (four slender
                        # 14.5 m wide parts in OSM).
TOP91 = 14.8            # Half-width of the 91F–92F section (OSM way/1339487717, 30 m square).
# Half-width of 93F–101F (OSM top floor 21.3 m square); also flares slightly.
SHAFT0, SHAFT1 = 10.3, 10.9
CROWN_R = 7.3           # The round crown from 439 to 448 m (OSM way/615184269).

H_BASE = 121.8          # 27F floor = top of the base.
H_MOD = 33.6            # One module = eight stories × 4.2 m.
H_91 = 390.6            # 91F floor (the top of the eighth module).
H_93 = 399.0            # 93F floor: the top of the 91F–92F section.
H_SHAFT = 439.0         # Top of the top-floor section (OSM).
H_ROOF = 449            # Roof at 449.2 m: the last row of the crown.
H_TIP = 508             # Spire.

# ---------------------------------------------------------------- Materials
GLASS = "minecraft:cyan_stained_glass"            # Blue-green curtain-wall glass.
SPANDREL = "minecraft:prismarine_bricks"          # Spandrel band on each floor-slab row.
MULLION = "minecraft:light_gray_stained_glass"    # Vertical mullions (silver-gray aluminum frames).
MECH = "minecraft:dark_prismarine"                # Mechanical floor at the top of each module.
LEDGE = "minecraft:smooth_quartz"                 # Overhang at the top of each module (a reflective
                                                  # sloped top that reads as white from afar).
# Ring at the top of the base (the band behind the coins).
BAND = "minecraft:light_gray_concrete"
CORE = "minecraft:polished_andesite"              # Elevator core.
SLAB = "minecraft:smooth_stone"                   # Floor slabs.
# Paving of the ground-floor lobby and the observatory.
FLOOR1 = "minecraft:polished_diorite"
LAMP = "minecraft:sea_lantern"
COIN_RIM = "minecraft:iron_block"
COIN_FACE = "minecraft:prismarine_bricks"
COIN_HOLE = "minecraft:gold_block"
RUYI = "minecraft:smooth_quartz"
SPIRE = "minecraft:iron_block"
MALL_WALL = "minecraft:polished_diorite"
MALL_ROOF = "minecraft:smooth_stone"
DOME_GLASS = "minecraft:light_blue_stained_glass"
DOME_RIB = "minecraft:smooth_quartz"
PAVING = "minecraft:polished_andesite"
TMD = "minecraft:gold_block"
CHAIN = "minecraft:iron_chain[axis=y,waterlogged=false]"
RAIL = "minecraft:glass"

# Ruyi: one at the middle of each face at the top of each module, at least 8 m tall (Wikipedia).
# The dot matrix is a ruyi head (a three-lobed cloud or heart shape) on a short handle; 8 rows =
# 8 m. It has no holes, so from afar it does not look like a face.
RUYI_GLYPH = HR.glyph([
    ".XX.XX.",
    "XXXXXXX",
    "XXXXXXX",
    ".XXXXX.",
    "..XXX..",
    "...X...",
    "...X...",
    "..XXX..",
])


def floor_h(k):
    """Return the height in meters of floor k's slab above the ground-floor slab.

    Floors 1–5 are double-height lobby floors; from 6F (33.6 m) up, each story is
    4.2 m. This gives 27F = 121.8 m, 89F = 382.2 m (observatory 382 m) and
    91F = 390.6 m (OSM)."""
    if k <= 1:
        return 0.0
    if k <= 6:
        return {2: 8.4, 3: 14.7, 4: 21.0, 5: 27.3, 6: 33.6}[k]
    return 33.6 + 4.2 * (k - 6)


FLOOR_ROWS = [int(math.floor(floor_h(k))) for k in range(1, 102)]      # Slab rows of floors 1..101.
ROW_FLOOR = {}
for _k, _r in enumerate(FLOOR_ROWS, 1):
    ROW_FLOOR[_r] = _k
OBS_FLOOR = 89
OBS_ROW = FLOOR_ROWS[OBS_FLOOR - 1]           # 382
# 390: the top of the eighth module = 91F outdoor observatory.
DECK_ROW = FLOOR_ROWS[91 - 1]
SKIP_SLAB = {FLOOR_ROWS[90 - 1]}               # No 90F slab: the 89F observatory is double height.
# The elevator core rises to 86F (the damper floors are above).
CORE_TOP = FLOOR_ROWS[86 - 1]
COIN_Y = 113            # Center of the coins (around 25F).
COIN_R = 6.5


def floor_of_row(yy):
    """Return (floor, row within that floor) for a row."""
    k = 1
    for i, r in enumerate(FLOOR_ROWS):
        if r <= yy:
            k = i + 1
        else:
            break
    return k, yy - FLOOR_ROWS[k - 1]


def section(yy):
    """Return the section of a row.

    One of base / mod (with module index 0..7) / top91 / shaft / crown / spire."""
    t = yy + 0.5
    if t < H_BASE:
        return "base", None
    if t < H_91:
        return "mod", int((t - H_BASE) // H_MOD)
    if t < H_93:
        return "top91", None
    if t < H_SHAFT:
        return "shaft", None
    if yy <= H_ROOF - 1:
        return "crown", None
    return "spire", None


def half_width(yy):
    """Return the plan half-width of a row (base and the eight modules; None for other sections)."""
    t = yy + 0.5
    sec, m = section(yy)
    if sec == "base":
        return BASE_A0 + (BASE_A1 - BASE_A0) * t / H_BASE
    if sec == "mod":
        f = (t - H_BASE - m * H_MOD) / H_MOD
        return MOD_B0 + (MOD_B1 - MOD_B0) * f
    return None


def section_top(yy):
    """Return whether a row is the last row of its section (overhangs and roofs are white)."""
    return section(yy) != section(yy + 1)


class Fields:
    """Distance fields on a Frame with the tower center as origin (computed once per Frame)."""

    def __init__(self, fr, du, dv):
        u, v = fr.U - du, fr.V - dv
        self.fr = fr
        self.u, self.v = u, v
        self.R = HR.notched_radius(fr, NOTCH, du, dv)
        self.T, self.S = HR.face_coords(fr, du, dv)
        self.D = np.hypot(u, v)
        self.bay = np.abs(self.T) <= BAY
        self.mull = (np.floor(self.T).astype(int) % 4) == 0
        self.lamps = HR.grid_mask(fr, 6, 3, du, dv)
        self.core = (np.maximum(np.abs(u), np.abs(v)) <= 10.0)
        self.core_ring = kit.ring(self.core)
        self.notch91 = (np.minimum(np.abs(u), np.abs(v)) < 1.8) & (self.S > TOP91 - 2.4)


def tower_mass(F, yy):
    """Return the tower's plan mask at row yy (yy blocks above the ground-floor slab)."""
    sec, m = section(yy)
    if sec == "base":
        a = half_width(yy)
        return (F.R <= a) | (F.bay & (F.S <= a + 1.0))
    if sec == "mod":
        return F.R <= half_width(yy)
    if sec == "top91":
        return (F.S <= TOP91) & ~F.notch91
    if sec == "shaft":
        t = yy + 0.5
        return F.S <= SHAFT0 + (SHAFT1 - SHAFT0) * (t - H_93) / (H_SHAFT - H_93)
    if sec == "crown":
        return F.D <= CROWN_R
    return np.zeros(F.R.shape, dtype=bool)


def tower_skin(F, yy, sh):
    """Return the materials of the tower shell at row yy as [(mask, block)]; later entries win."""
    sec, m = section(yy)
    k, kr = floor_of_row(yy)
    out = [(sh, GLASS)]
    if sec in ("base", "mod", "top91", "shaft"):
        out.append((sh & F.mull, MULLION))
        if kr == 0:
            out.append((sh, SPANDREL))
    if sec == "base":
        bay = sh & F.bay
        # The bay at the middle of the base: two dark horizontal bands per story (from afar,
        # a vertical "ladder").
        if kr in (0, 2):
            out.append((bay, MECH))
        else:
            out.append((bay, GLASS))
        if COIN_Y - 2 <= yy <= COIN_Y + 1:
            out.append((sh, BAND))
    elif sec == "mod":
        # The top story of each module is a mechanical floor (where the outrigger trusses are),
        # slightly darker.
        if k == 34 + 8 * m:
            out.append((sh & ~F.mull, MECH))
    elif sec == "crown":
        # Crown: glass with rings of metal.
        if kr == 0 or yy % 3 == 0:
            out.append((sh, SPIRE))
    return out


class Taipei101(Attraction):
    height_m = 508.0
    margin = 12
    # The default viewpoint is 210 m southwest of the tower (so the whole tower fits in view);
    # that area must be real terrain too.
    terrain_margin = 240

    # ---------------------------------------------------------------- Data
    def _ring(self, osm):
        f = self.feature(osm)
        if not f or not f.get("outer"):
            return None
        return max(f["outer"], key=len)

    def _mask(self, fr, osms):
        m = fr.empty()
        for o in (osms if isinstance(osms, (list, tuple)) else [osms]):
            r = self._ring(o)
            if r:
                m |= fr.polygon(r)
        return m

    def bbox(self):
        """Return the grounds (plaza and street trees included): the OSM tourism=attraction area
        (way/248210267) grown by margin."""
        r = self._ring(PLAZA) or self.outline()
        xs = [p[0] for p in r]
        zs = [p[1] for p in r]
        m = self.margin
        return (int(math.floor(min(xs))) - m, int(math.floor(min(zs))) - m,
                int(math.ceil(max(xs))) + m, int(math.ceil(max(zs))) + m)

    # ---------------------------------------------------------------- Planning
    def plan(self, site):
        self.site = site
        cx, cz, ang_osm, _, _ = HR.outline_axes(self._ring(TOWER))
        # The tower is skewed 1.0°: square it up (see highrise.snap_angle), with its center as in
        # OSM. The mall and the podium are still rasterized from their OSM polygons as they are
        # (they are in world coordinates and unaffected by the Frame angle).
        ang = HR.snap_angle(ang_osm)
        self.ang = ang
        # Tower (including the entrance canopies).
        self.fr = Frame(cx, cz, ang, 48)
        x0, z0, x1, z1 = self.bbox()
        scx, scz = (x0 + x1) / 2.0, (z0 + z1) / 2.0
        self.sfr = Frame(scx, scz, ang, max(x1 - x0, z1 - z0) / 2.0 + 2)   # The whole site.
        # The tower center in the site Frame's local coordinates (both Frames share an angle, so
        # their local coordinates differ only by a translation).
        c, s = math.cos(ang), math.sin(ang)
        tu = (cx - scx) * c + (cz - scz) * s
        tv = -(cx - scx) * s + (cz - scz) * c
        self.tuv = (tu, tv)
        self.F = Fields(self.fr, 0.0, 0.0)
        self.SF = Fields(self.sfr, tu, tv)

        sfr = self.sfr
        self.m_mall = self._mask(sfr, MALL)
        self.m_skirt = self._mask(sfr, SKIRTS)
        self.m_vest = self._mask(sfr, VESTIBULE)
        self.m_dome = self._mask(sfr, DOME)
        self.m_canopy = [self._mask(sfr, o) for o in CANOPIES]
        self.m_walk = [self._mask(sfr, o) for o in SKYWALKS]
        self.m_plaza = self._mask(sfr, PLAZA)
        base0 = tower_mass(self.SF, 0)
        self.m_foot = self.m_mall | self.m_skirt | self.m_vest | base0
        self.g0 = site.level(sfr, base0)
        # Look up the ground heights needed for grading now (Site caches them): cli discards the
        # distance field of the "built terrain" after plan, so looking them up in build() fails.
        site.grid(sfr, self.m_plaza | self.m_foot)

        # Viewpoint: on the street outside the plaza's southwest corner (Xinyi Road side), with
        # the whole tower in frame (the spire at an elevation angle of about 67°).
        pr = self._ring(PLAZA)
        vx = int(math.floor(min(p[0] for p in pr))) - 50
        vz = int(math.ceil(max(p[1] for p in pr))) + 49
        vy = site.g(vx, vz) + 1
        d = math.hypot(cx - (vx + .5), cz - (vz + .5))
        up = math.degrees(math.atan2(self.g0 + H_TIP - (vy + 1.62), d))
        down = math.degrees(math.atan2(vy + 1.62 - self.g0, d))
        yaw, _ = kit.look(vx, vy, vz, cx, self.g0 + 200, cz)
        # Half the elevation: base to spire in frame.
        pitch = round(-(up - down) / 2.0, 1)
        # Lobby: 6 m south of the elevator core (a dozen or so meters in from the south entrance),
        # facing the sign on the core.
        lx, lz = self.fr.cell(0.0, 16.0)
        # 89F: by the window on the side facing Taipei Main Station (toward the city).
        a89 = half_width(OBS_ROW + 1)
        wu, wv = self._city_dir()
        tx, tz = self.fr.cell(wu * (a89 - 3.5), wv * (a89 - 3.5))
        self.top_cell = (tx, tz)
        self._spots = [
            Spot("", vx, vy, vz, yaw, pitch, self.name_zh, self.name_en),
            Spot("lobby", lx, self.g0 + 1, lz, round(self.fr.yaw(0, -1), 1), 0.0,
                 "台北101 大廳", "Taipei 101 Lobby"),
            Spot("top", tx, self.g0 + OBS_ROW + 1, tz, round(self.fr.yaw(wu, wv), 1), 12.0,
                 "89 樓觀景台", "89F Observatory"),
        ]

    def _city_dir(self):
        """Return the direction from the tower to Taipei Main Station (the origin).

        The result is a unit vector in local coordinates."""
        dx, dz = -self.fr.cx, -self.fr.cz
        L = math.hypot(dx, dz) or 1.0
        dx, dz = dx / L, dz / L
        c, s = math.cos(self.ang), math.sin(self.ang)
        return dx * c + dz * s, -dx * s + dz * c

    def plaque(self):
        # A sign line is at most 90 px wide (signage.SIGN_W): these two lines are 88 and 85 px.
        return [self.name_zh, self.name_en, "508 m，2004年落成", "101 層，八斗各八層"]

    def plaque_en(self):
        return ["508 m high, completed in 2004", "508 m high, 2004"]

    # ---------------------------------------------------------------- Building
    def build(self, w):
        self._ground(w)
        self._podium(w)
        self._tower(w)
        self._spire(w)
        self._ornaments(w)
        self._observatory(w)
        self._lobby(w)
        self._canopies(w)
        self._skywalks(w)
        self._trees(w)

    # ---- Grading: level the site to the ground-floor slab and pave the plaza ----
    def _ground(self, w):
        sfr = self.sfr
        self.site.prepare(w, sfr, self.m_plaza & ~self.m_foot, self.g0, top=PAVING)
        self.site.prepare(w, sfr, self.m_foot, self.g0, top=FLOOR1)

    # ---- Mall, podium and the tower's first 31 rows (one mask, no inner walls at the seams) ----
    def _podium_mass(self, yy):
        m = np.zeros_like(self.m_foot)
        if yy < 30:
            m = m | self.m_mall
        if yy < 25:
            m = m | self.m_skirt
        if yy < 8:
            m = m | self.m_vest
        return m

    def _podium(self, w):
        sfr, SF, g0 = self.sfr, self.SF, self.g0
        mass = {}

        near_tower = SF.S <= BASE_A0 + 4.0

        def M(yy):
            if yy not in mass:
                if yy < 0:
                    mass[yy] = (sfr.empty(), sfr.empty())
                else:
                    t = tower_mass(SF, yy)
                    m = self._podium_mass(yy) | t
                    if yy < 25:
                        # OSM draws the podium's notch at the tower corners as a 45° chamfer, while
                        # the tower here has two sawtooth steps; the two leave a few unroofed gaps
                        # one or two cells wide, which are filled in here.
                        m |= kit.erode(kit.dilate(m, 2), 2) & near_tower
                    mass[yy] = (t, m)
            return mass[yy]

        pillar = ((sfr.X + sfr.Z) % 6) == 0
        for yy in range(0, 31):
            t_m, m = M(yy)
            _, mp = M(yy - 1)
            _, mn = M(yy + 1)
            sh = HR.shell(m, mp, mn)
            y = g0 + yy
            tsh = sh & t_m
            psh = sh & ~t_m
            layers = tower_skin(SF, yy, tsh)
            # Mall: 6 m per story; the slab row and the top row are stone, glass in between,
            # with a stone pillar every 6 cells.
            kr = yy % 6
            mall = psh & self.m_mall
            layers.append((mall, MALL_WALL if kr in (0, 5) else GLASS))
            if kr not in (0, 5):
                layers.append((mall & pillar, MALL_WALL))
            # Podium: the same glass as the tower, 5 m per story.
            sk = psh & ~self.m_mall
            layers.append((sk, SPANDREL if yy % 5 == 0 else GLASS))
            if yy % 5:
                layers.append((sk & self.SF.mull, MULLION))
            HR.paint_layers(w, sfr, layers, y)
            # Roof: present on this row but not the next (the dome area is left open; the dome
            # builds its own roof).
            cap = m & ~mn & ~sh & ~self.m_dome
            HR.paint(w, sfr, cap & ~t_m, y, MALL_ROOF)
            HR.paint(w, sfr, cap & t_m, y, GLASS)
            inner = m & ~sh
            slab = sfr.empty()
            if yy in ROW_FLOOR and yy not in SKIP_SLAB:
                slab |= inner & t_m
            if yy % 6 == 0:
                slab |= inner & self.m_mall & ~t_m & (~self.m_dome | (yy == 0))
            if yy % 5 == 0:
                slab |= inner & (self.m_skirt | self.m_vest) & ~self.m_mall & ~t_m
            if yy > 0:
                HR.paint(w, sfr, slab & ~cap, y, SLAB)
                HR.paint(w, sfr, slab & ~cap & self.SF.lamps, y, LAMP)
            if yy > 0:
                HR.paint(w, sfr, SF.core_ring & t_m & ~sh & ~slab, y, CORE)
        # The ruyi-shaped dome: a glass vault on the mall roof, 30 -> 42 m.
        dm = self.m_dome
        h = HR.dome(dm, 12.0)
        rib = (np.floor(sfr.U).astype(int) % 5 == 0) | (np.floor(sfr.V).astype(int) % 5 == 0)
        p = kit.Painter(w, sfr)
        p.heightfield(dm & ~rib, g0 + 29, h, DOME_GLASS, shell=1)
        p.heightfield(dm & rib, g0 + 29, h, DOME_RIB, shell=1)
        HR.paint(w, sfr, kit.ring(dm), g0 + 29, MALL_ROOF)

    # ---- Tower: row 31 to the roof ----
    def _tower(self, w):
        fr, F, g0 = self.fr, self.F, self.g0
        cache = {}

        def M(yy):
            if yy not in cache:
                cache[yy] = tower_mass(F, yy)
            return cache[yy]

        hole = F.D <= 5.5                              # The slabs are cut open around the damper.
        for yy in range(31, H_ROOF):
            m = M(yy)
            if not m.any():
                continue
            mn, mp = M(yy + 1), M(yy - 1)
            sh = HR.shell(m, mp, mn)
            y = g0 + yy
            HR.paint_layers(w, fr, tower_skin(F, yy, sh), y)
            cap = m & ~mn & ~sh
            sec, mod = section(yy)
            if section_top(yy):
                # Top of a section: a white overhang around the edge (from afar, the
                # bright rim at the top of each module). The tops of the base and
                # the modules are inward-sloping glass (slope below); the 91F
                # outdoor observatory (top of the eighth module) is paved.
                if sec == "mod" and mod == 7:
                    HR.paint(w, fr, cap, y, FLOOR1)
                elif sec in ("base", "mod"):
                    HR.paint(w, fr, cap, y, GLASS)
                else:
                    HR.paint(w, fr, cap, y, LEDGE)
                HR.paint(w, fr, sh & ~mn, y, LEDGE)
            elif cap.any():
                # The small ledges exposed by each one-cell
                # setback of a slope: glass, like the facade.
                HR.paint(w, fr, cap, y, GLASS)
            if sec == "mod":
                # Sloped glass between modules: from the lower module's overhang, stepping in and up
                # three cells to the bottom of this module.
                yt = int(math.ceil(H_BASE + mod * H_MOD - 0.5)) - 1
                i = yy - yt
                if 1 <= i <= 3:
                    slope = (F.R <= half_width(yt) - 1.2 * i) & ~m
                    HR.paint(w, fr, slope, y, GLASS)
            inner = m & ~sh & ~cap
            if yy in ROW_FLOOR and yy not in SKIP_SLAB:
                sl = inner
                if 86 <= ROW_FLOOR[yy] <= 92:
                    sl = sl & ~hole
                HR.paint(w, fr, sl, y, FLOOR1 if yy == OBS_ROW else SLAB)
                HR.paint(w, fr, sl & F.lamps, y, LAMP)
            elif yy < CORE_TOP:
                HR.paint(w, fr, F.core_ring & inner, y, CORE)

    # ---- Spire: 449 -> 508 m; a cone at the base, thinner higher up, a white rod on top ----
    def _spire(self, w):
        fr, F, g0 = self.fr, self.F, self.g0
        for yy in range(H_ROOF, H_TIP + 1):
            if yy <= 454:
                r = 3.4 - 0.25 * (yy - H_ROOF)
                HR.paint(w, fr, F.D <= r, g0 + yy, SPIRE)
            elif yy <= 478:
                HR.paint(w, fr, F.S <= 1.0, g0 + yy, SPIRE)
                if yy in (462, 470):
                    HR.paint(w, fr, F.D <= 2.2, g0 + yy, BAND)
            elif yy <= 498:
                x, z = fr.cell(0.0, 0.0)
                w.set(x, g0 + yy, z, SPIRE)
                if yy == 488:
                    HR.paint(w, fr, F.D <= 1.3, g0 + yy, BAND)
            else:
                x, z = fr.cell(0.0, 0.0)
                w.set(x, g0 + yy, z, "minecraft:end_rod[facing=up]")

    # ---- Ancient coins (top of the base) and ruyi (top of each module), one per face ----
    def _ornaments(self, w):
        fr, F, g0 = self.fr, self.F, self.g0
        # Coins: 13 m discs projecting 3 m from the facade; the front shows the rim, the face and
        # the square hole.
        for yy in range(int(COIN_Y - COIN_R) - 1, int(COIN_Y + COIN_R) + 2):
            a = half_width(yy)
            dy = yy - COIN_Y
            rr = np.hypot(F.T, dy)
            disc = (rr <= COIN_R) & (F.S > a) & (F.S <= a + 3.0) & ~F.bay | \
                   (rr <= COIN_R) & (F.S > a + 1.0) & (F.S <= a + 4.0) & F.bay
            if not disc.any():
                continue
            front = disc & ((F.S > a + 2.0) & ~F.bay | (F.S > a + 3.0) & F.bay)
            y = g0 + yy
            HR.paint(w, fr, disc & ~front, y, BAND)
            HR.paint(w, fr, front & (rr > COIN_R - 1.3), y, COIN_RIM)
            face = front & (rr <= COIN_R - 1.3)
            sq = np.maximum(np.abs(F.T), abs(dy))
            HR.paint(w, fr, face & (sq > 2.5), y, COIN_FACE)
            HR.paint(w, fr, face & (sq <= 2.5) & (sq > 1.5), y, COIN_HOLE)
            HR.paint(w, fr, face & (sq <= 1.5), y, MECH)
        # Ruyi: set at the top of each module (drawn downward from the row below the overhang),
        # projecting one cell from the facade.
        pts = RUYI_GLYPH
        for m in range(8):
            top = int(math.ceil(H_BASE + (m + 1) * H_MOD - 0.5)) - 2
            for i, j in pts:
                yy = top - i
                a = half_width(yy)
                col = j - 3
                cellm = (np.floor(F.T).astype(int) == col) & (F.S > a) & (F.S <= a + 1.0)
                HR.paint(w, fr, cellm, g0 + yy, RUYI)

    # ---- 89F observatory, damper, 91F outdoor observatory ----
    def _observatory(self, w):
        fr, F, g0 = self.fr, self.F, self.g0
        y_obs = g0 + OBS_ROW
        a = half_width(OBS_ROW + 1)
        inner = F.R <= a - 1.5
        # The double-height observatory space (89F and 90F): clear the interior.
        for yy in range(OBS_ROW + 1, DECK_ROW):
            HR.paint(w, fr, inner & ~(F.D <= 3.0), g0 + yy, kit.AIR)
        # Damper: a gold steel sphere 5.5 m in diameter, centered at the 89F slab level (upper half
        # on 89F, lower half on 88F).
        cx, cz = fr.world(0.0, 0.0)
        HR.sphere(w, cx, y_obs + 0.5, cz, 2.75, TMD)
        # Cables: from the top of the sphere to the 91F slab (92F is above it).
        for du, dv in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
            x, z = fr.cell(du, dv)
            for y in range(y_obs + 3, g0 + DECK_ROW):
                w.set(x, y, z, CHAIN)
        # Glass railing around the opening.
        HR.paint(w, fr, (F.D > 5.5) & (F.D <= 6.5), y_obs + 1, RAIL)
        # 91F outdoor observatory: a ring on top of the eighth module, with a one-block glass
        # parapet at the edge.
        a8 = half_width(DECK_ROW)
        deck = (F.R <= a8) & ~((F.S <= TOP91) & ~F.notch91)
        HR.paint(w, fr, kit.ring(F.R <= a8) & deck, g0 + DECK_ROW + 1, RAIL)
        # Observatory lights: one lamp cell each in the ceiling (the 91F slab) and in the paving.
        HR.paint(w, fr, inner & F.lamps & ~(F.D <= 6.5), y_obs, LAMP)
        HR.paint(w, fr, inner & F.lamps, g0 + DECK_ROW, LAMP)
        # Signs: back to the ground-floor lobby; the damper's information sign, with its English
        # version on the reader's right.
        tx, tz = self.top_cell
        wu, wv = self._city_dir()
        ru, rv = -wv, wu                                  # To the viewpoint's right.
        su, sv = self.fr.local(tx, tz)
        sx, sz = fr.cell(su + ru * 2.0 - wu * 1.0, sv + rv * 2.0 - wv * 1.0)
        w.sign(sx, y_obs + 1, sz, ["回 1 樓 ▼", "To Lobby", "", ""],
               facing=(tx - sx, tz - sz), wood="pale_oak", kind="standing", glow=True,
               command="function %s:%s" % (config.DATAPACK_NS, kit.sight_fn(self.id, "lobby")))
        mx, mz = fr.cell(0.0, 7.5)
        w.sign(mx, y_obs + 1, mz, ["調諧質量阻尼器", "660 公噸", "直徑 5.5 m", "88～92 樓"],
               facing=fr.dir(0, 1), wood="pale_oak", kind="standing", glow=True)
        ex, ez = fr.cell(1.0, 7.5)
        w.sign(ex, y_obs + 1, ez, ["Tuned mass", "damper, 660 t", "5.5 m diameter", "Floors 88–92"],
               facing=fr.dir(0, 1), wood="pale_oak", kind="standing", glow=True)

    # ---- Ground-floor lobby: doors on the south and east faces, a sign to 89F on the core ----
    def _lobby(self, w):
        fr, F, g0 = self.fr, self.F, self.g0
        foot = set()
        m1 = self._podium_mass(1) | tower_mass(self.SF, 1)
        for x, z in zip(self.sfr.X[m1].tolist(), self.sfr.Z[m1].tolist()):
            foot.add((x, z))
        for du, dv in ((0.0, 1.0), (1.0, 0.0)):
            # Search inward from outside for the first wall.
            hit = None
            for k in range(90, 30, -1):
                d = k * 0.5
                x, z = fr.cell(du * d, dv * d)
                if (x, z) in foot:
                    hit = d
                    break
            if hit is None:
                continue
            face = kit.cardinal(*fr.dir(-du, -dv))     # The direction a player entering faces.
            tu, tv = dv, du                             # Along the wall.
            for s, hinge in ((-0.5, "left"), (0.5, "right")):
                x, z = fr.cell(du * hit + tu * s, dv * hit + tv * s)
                HR.door(w, x, g0 + 1, z, face, hinge=hinge)
                for dd in (-1.0, 1.0):
                    xx, zz = fr.cell(du * (hit + dd) + tu * s, dv * (hit + dd) + tv * s)
                    w.set(xx, g0 + 1, zz, kit.AIR)
                    w.set(xx, g0 + 2, zz, kit.AIR)
            for s in (-1.5, 1.5):
                x, z = fr.cell(du * hit + tu * s, dv * hit + tv * s)
                w.set(x, g0 + 1, z, GLASS)
                w.set(x, g0 + 2, z, GLASS)
        # South face of the elevator core: two elevator doors (iron frames) and the sign.
        for su in (-4.0, -3.0, 3.0, 4.0):
            for yy in (1, 2, 3):
                x, z = fr.cell(su, 10.0)
                w.set(x, g0 + yy, z, COIN_RIM)
        sx, sz = fr.cell(0.0, 12.0)
        w.sign(sx, g0 + 1, sz, ["89 樓觀景台 ▲", "89F Observatory", "", ""],
               facing=fr.dir(0, 1), wood="pale_oak", kind="standing", glow=True,
               command="function %s:%s" % (config.DATAPACK_NS, kit.sight_fn(self.id, "top")))

    # ---- Entrance canopies: a one-story (5 m) roof slab on posts, walkable underneath ----
    def _canopies(self, w):
        sfr, g0 = self.sfr, self.g0
        post = HR.grid_mask(sfr, 5, 0)
        for m in self.m_canopy:
            m = m & ~self.m_foot
            if not m.any():
                continue
            HR.paint(w, sfr, m, g0 + 5, LEDGE)
            rg = kit.ring(m) & post
            for yy in range(1, 5):
                HR.paint(w, sfr, rg, g0 + yy, MALL_WALL)

    # ---- Skywalks: glass corridors at second-floor level (only the stretch in the grounds) ----
    def _skywalks(self, w):
        sfr, g0 = self.sfr, self.g0
        post = HR.grid_mask(sfr, 12, 0)
        for m in self.m_walk:
            m = m & ~self.m_foot
            if not m.any():
                continue
            rg = kit.ring(m)
            HR.paint(w, sfr, m, g0 + 6, SLAB)
            for yy in (7, 8, 9):
                HR.paint(w, sfr, rg, g0 + yy, GLASS)
            HR.paint(w, sfr, m, g0 + 10, MALL_ROOF)
            for yy in range(1, 6):
                HR.paint(w, sfr, m & post & kit.erode(m, 1), g0 + yy, MALL_WALL)

    # ---- Plaza trees: one every 8 m, none in front of the entrances or under the skywalks ----
    def _trees(self, w):
        sfr, g0 = self.sfr, self.g0
        free = self.m_plaza & ~kit.dilate(self.m_foot, 4)
        for m in self.m_canopy:
            free &= ~kit.dilate(m, 3)
        for m in self.m_walk:
            free &= ~kit.dilate(m, 3)
        # Keep a 14 m wide passage clear in front of each of the south and east entrances.
        tu, tv = self.tuv
        free &= ~((np.abs(sfr.U - tu) <= 7) & (sfr.V > tv))
        free &= ~((np.abs(sfr.V - tv) <= 7) & (sfr.U > tu))
        spots = free & HR.grid_mask(sfr, 8, 4)
        keep = self.site.keep

        def near_keep(x, z):
            """Return whether a keep-out zone lies within 3 cells of the crown.

            MRT Exit 4 is on the south plaza; no tree goes there, so none blocks the exit door."""
            if keep is None:
                return False
            return any(keep(x + dx, self.g0 + dy, z + dz)
                       for dx in range(-4, 5, 2) for dz in range(-4, 5, 2) for dy in (1, 4, 7))

        for x, z in zip(sfr.X[spots].tolist(), sfr.Z[spots].tolist()):
            if near_keep(x, z):
                continue
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    w.set(x + dx, g0, z + dz, "minecraft:grass_block[snowy=false]")
            HR.tree(w, x, g0, z, trunk=4, r=2.8)


BUILDS = {"taipei101": Taipei101}
