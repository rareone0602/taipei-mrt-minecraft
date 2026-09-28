#!/usr/bin/env python3
"""Red House, Ximending (former Shinkigai Market, 1908): the Octagon and the Cruciform Building.

Position and outline: OSM way/222080307. At the east end is an octagon; a long hall runs
west from it and, toward its west end, crosses a north-south transept to form a cross.
The appearance follows public sources:
  · Designed by Kondō Jūrō and completed in 1908: a two-story, red brick, octagonal
    Western-style building with an octagonal pyramidal roof, its walls banded in
    alternating red brick and white render (Chinese Wikipedia "Red House (Taipei)", the
    Tourism Administration's attraction page)
  · Each face of the Octagon is 8 m and it covers 412 m². Besides the front and rear
    doors, a third door leads straight into the Cruciform Building. The steel roof
    trusses radiate like the ribs of an umbrella, and a round light source in the middle
    lights the ground floor (Chinese Wikipedia)
  · Cruciform Building: the crossing is not at the symmetrical midpoint but closer to
    the west; the north and south sides border plazas. The brick walls are 49 cm thick,
    and the 15 m clear span rests entirely on reinforced-brick bearing walls and
    buttresses (Chinese Wikipedia)
The octagon's apothem is 11.2 m (a regular octagon of 412 m²; the OSM outline traces
about 11.5 m, including the eaves). The lantern in the middle of the Octagon's roof, and
the pediment and oculus over the front entrance, are shapes visible in photographs; their
sizes are estimates.
Local coordinates: the origin is the center of the Octagon; u runs along the long axis
of the Cruciform Building toward the Octagon's front (east-southeast, 15.1° off), and v
is u turned 90° toward the south. The positions of the Cruciform Building's parts are
measured from the OSM vertices (see the constants).
"""
import math

import numpy as np

from mrt.application.attractions import colonial_kit as CK
from mrt.application.attractions import kit
from mrt.application.attractions.kit import AIR, Attraction, Frame, Spot, erode, dilate

# ---- Materials ----
BRICK = "minecraft:bricks"
WHITE = "minecraft:smooth_quartz"          # White render: bands, window surrounds, cornice
BAND = "minecraft:calcite"
PLINTH = "minecraft:polished_andesite"
GLASS = "minecraft:gray_stained_glass"
ROOF = "minecraft:deepslate_tiles"          # Dark gray roof tiles
ROOF_SLAB = "deepslate_tile_slab"
ROOF_STAIR = "deepslate_tile_stairs"
PAVE = "minecraft:polished_andesite"
PAVE2 = "minecraft:stone_bricks"

# ---- Octagon (blocks above the ground) ----
A_WALL = 11.2           # Apothem of the outer wall (each face about 9.3 m)
A_EAVE = 12.0           # Eaves overhang
H_BAND1 = 7             # White belt course between the ground and upper floors
H_CORNICE = 13          # Cornice
H_ROOF0 = 14            # Base of the roof
ROOF_SLOPE = 0.55
A_LANTERN = 3.4         # Apothem of the lantern
H_LANTERN = (18, 21)    # Lantern walls (with windows)
H_TOP = 27              # Spire (lightning rod)
HALF_FACE = A_WALL * math.tan(math.radians(22.5))    # Half-width of each face, 4.64 m

# ---- Cruciform Building (local coordinates from OSM vertices, origin at the Octagon's center) ----
# Center line and half-width of the long hall (OSM v -3.3 to
# 5.1; 0.9 m off the Octagon's center line, halved)
ARM_V = (0.45, 4.2)
# The long hall runs from its west end to the Octagon's west wall
ARM_U = (-79.9, -A_WALL + 0.5)
CROSS_U = (-62.7, -52.2)            # Transept (OSM u -62.7 to -52.2)
# North and south ends of the transept (OSM v -22.6 to 25.2;
# same length, aligned to the long hall's center line)
CROSS_V = (-23.45, 24.35)
# Top of the Cruciform Building's outer walls (a single story with a clear span)
H_HALL = 8
H_HALL_ROOF = 10        # Base of the Cruciform Building's roof
BAY = 4.0               # Buttress spacing


class RedHouse(Attraction):
    height_m = None         # No public height figure (verify_attractions does not check it either)
    margin = 14

    def __init__(self, item):
        super().__init__(item)
        main = self.feature("way/222080307") or (self.mains() or [None])[0]
        self.outer = max(main["outer"], key=len) if main and main.get("outer") else self.outline()
        self.angle = CK.fit_angle(self.outer)
        f0 = Frame(0.0, 0.0, self.angle, 1)
        L = [CK.to_local(f0, x, z) for x, z in self.outer]
        umax = max(p[0] for p in L)
        # Vertices within 25 m of the east end = the octagon
        octv = [p for p in L if p[0] > umax - 25.0]
        cu = (min(p[0] for p in octv) + max(p[0] for p in octv)) / 2.0
        cv = (min(p[1] for p in octv) + max(p[1] for p in octv)) / 2.0
        self.origin = f0.world(cu, cv)

    def spot_uv(self):
        """Default viewpoint: on the Red House Plaza in front of the Octagon, about 19 m
        from the main entrance."""
        return (30.0, 0.0)

    def bbox(self):
        x0, z0, x1, z1 = super().bbox()
        fr = Frame(self.origin[0], self.origin[1], self.angle, 1)
        sx, sz = fr.world(*self.spot_uv())
        return (min(x0, int(sx) - 6), min(z0, int(sz) - 6), max(x1, int(sx) + 6), max(z1, int(sz) + 6))

    def plan(self, site):
        self.fr = fr = Frame(self.origin[0], self.origin[1], self.angle, 84)
        U, V = fr.U, fr.V
        self.oct = fr.ngon(8, A_WALL)
        vc, hw = ARM_V
        self.arm = (U >= ARM_U[0]) & (U <= ARM_U[1]) & (np.abs(V - vc) <= hw)
        self.cross = (U >= CROSS_U[0]) & (U <= CROSS_U[1]) & (V >= CROSS_V[0]) & (V <= CROSS_V[1])
        self.hall = (self.arm | self.cross) & ~self.oct
        self.foot = self.oct | self.hall
        self.g0 = site.level(fr, self.foot)
        self.site = site
        # Plazas: 22 m east of the Octagon's front (Red House Plaza), and the north and
        # south sides of the Cruciform Building (North and South Plazas).
        # Ground heights must be looked up in plan() (cli clears the terrain cache after plan_all).
        self.front = (U >= 0) & (U <= 34.0) & (np.abs(V) <= 24.0)
        self.yard = dilate(self.foot, 5) | self.front
        site.grid(fr, self.yard)
        su, sv = self.spot_uv()
        sx, sz = fr.cell(su, sv)
        sy = site.g(sx, sz) + 1
        tx, tz = fr.world(0.0, 0.0)
        yaw, pitch = kit.look(sx, sy, sz, tx, self.g0 + 11, tz)
        self._spots = [Spot("", sx, sy, sz, yaw, pitch, self.name_zh, self.name_en)]

    def plaque(self):
        return [self.name_zh, self.name_en, "1908 年落成", "近藤十郎設計八角樓"]

    def plaque_en(self):
        return ["Completed in 1908", "Built in 1908"]

    def top_y(self):
        return None if self.g0 is None else self.g0 + H_TOP

    # ---- Build ----
    def build(self, w):
        fr, g0 = self.fr, self.g0
        m = CK.Mason(w, fr)
        U, V = fr.U, fr.V
        front = self.front
        self.site.prepare(w, fr, self.yard, g0, top=PAVE, clear=40)
        R = np.hypot(U, V)
        rays = (np.abs(((np.degrees(np.arctan2(V, U)) + 11.25) % 22.5) - 11.25) < 1.2) & (R > A_EAVE + 1)
        m.fill(front & (rays | ((R > 17.5) & (R < 18.6))), g0, g0, PAVE2)
        self._octagon(m)
        self._hall(m)

    # ---- Octagon ----
    def _oct_pattern(self, face, t, h, layer, u, v, q=None):
        """One face of the Octagon (face = 0 is the front, facing +u; 1 to 7 turn from u
        toward v): two arched windows on the ground floor (on the front, a 3-block-wide
        arched doorway), a white belt course, two arched windows on the upper floor (three
        narrow windows on the front), corner piers of red brick banded with white, and one
        more thin white band across the piers at springing height."""
        at = abs(t)
        if h == 1:
            return PLINTH if layer == 0 else BRICK
        if h == H_BAND1:
            return WHITE if layer == 0 else BRICK
        # Dentils under the eaves: alternating white and red
        if h == H_CORNICE - 1:
            return WHITE if (layer == 0 and math.floor(t) % 2 == 0) else BRICK
        corner = at > HALF_FACE - 0.7
        if corner:
            if layer:
                return BRICK
            return BAND if h % 3 == 0 else BRICK
        if face == 0:
            door = at <= 1.5 and 2 <= h <= 5
            win2 = (at <= 0.5 or 1.5 <= at <= 2.5) and 9 <= h <= 11
            if door:
                return AIR if layer == 0 or h <= 5 else BRICK
            if at <= 1.5 and h == 6:
                return WHITE                                 # Door lintel
            if win2:
                return GLASS if layer else AIR
            if (at <= 0.5 or 1.5 <= at <= 2.5) and h == 12:
                return WHITE
        else:
            win = 0.5 <= at <= 2.5
            if win and (3 <= h <= 5 or 9 <= h <= 11):
                if layer:
                    return GLASS
                return AIR
            if win and h in (6, 12):
                return WHITE if layer == 0 else BRICK        # White keystone above an arched window
        if layer:
            return BRICK
        if h in (4, 10):
            return BAND                                       # Thin white band at springing height
        return BRICK

    def _octagon(self, m):
        fr, g0 = self.fr, self.g0
        octm = self.oct
        m.fill(octm, g0 + 1, g0 + 1, PLINTH)
        m.facade(octm, g0 + 1, g0 + H_CORNICE - 1, self._oct_pattern, base=g0, ngon=(8, 0.0, 0.0, 0.0))
        # Upper floor (theater)
        m.fill(erode(octm, 2), g0 + H_BAND1, g0 + H_BAND1, "minecraft:spruce_planks")
        # Cornice: white, projecting out to A_EAVE
        eave = fr.ngon(8, A_EAVE)
        m.fill(eave, g0 + H_CORNICE, g0 + H_CORNICE, WHITE)
        m.fill(eave & ~octm, g0 + H_CORNICE - 1, g0 + H_CORNICE - 1, CK.slab("smooth_quartz_slab", "top"))
        # Octagonal pyramidal roof (steel trusses radiating like
        # umbrella ribs), leaving the center for the lantern
        rr = fr.ngon_radius(8)
        h = ((A_EAVE - rr) * ROOF_SLOPE).clip(0, None)
        roofm = eave & ~fr.ngon(8, A_LANTERN - 0.5)
        m.roof(roofm, g0 + H_ROOF0, h, ROOF, slab_name=ROOF_SLAB, shell=2)
        # Eight hips: light gray ridge capping along the eight vertex directions, so the octagonal
        # roof reads as such
        for k in range(8):
            ph = math.radians(22.5 + 45 * k)
            R = A_EAVE / math.cos(math.radians(22.5))
            for i in range(0, int(R - A_LANTERN)):
                r = R - i
                rr_ = r * math.cos(math.radians(22.5))
                y = g0 + H_ROOF0 + int(math.floor((A_EAVE - rr_) * ROOF_SLOPE))
                m.at(r * math.cos(ph), r * math.sin(ph), y + 1, CK.slab("polished_andesite_slab"))
        # Lantern: a white octagonal drum with windows on four faces, a dark gray octagonal spire
        # and a lightning rod
        lan = fr.ngon(8, A_LANTERN)

        def lantern(face, t, h, layer, u, v, q=None):
            if abs(t) < 0.8 and H_LANTERN[0] + 1 <= h <= H_LANTERN[1] - 1:
                return GLASS
            return WHITE

        m.facade(lan, g0 + H_LANTERN[0] - 1, g0 + H_LANTERN[1], lantern, base=g0, layers=1, ngon=(8, 0.0, 0.0, 0.0))
        m.fill(erode(lan, 1), g0 + H_LANTERN[0] - 1, g0 + H_LANTERN[1], AIR)
        cap = fr.ngon(8, A_LANTERN + 0.7)
        m.fill(cap, g0 + H_LANTERN[1] + 1, g0 + H_LANTERN[1] + 1, WHITE)
        hc = ((A_LANTERN + 0.4 - rr) * 1.0).clip(0, None)
        m.roof(fr.ngon(8, A_LANTERN + 0.4), g0 + H_LANTERN[1] + 2, hc, ROOF, slab_name=ROOF_SLAB, shell=1)
        top = g0 + H_LANTERN[1] + 2 + int(A_LANTERN + 0.4)
        for y in range(top, g0 + H_TOP):
            m.at(0.0, 0.0, y, ROOF if y < g0 + H_TOP - 1 else "minecraft:polished_deepslate_wall")
        m.at(0.0, 0.0, g0 + H_TOP, "minecraft:waxed_lightning_rod[facing=up,powered=false]")
        # The round light source in the middle of the ground floor (roof light reaching the ground
        # floor): a ring of lights in the middle of the ceiling
        m.fill(fr.ngon(8, 1.5), g0 + H_BAND1, g0 + H_BAND1, "minecraft:glass")
        m.fill(fr.ngon(8, 2.5) & ~fr.ngon(8, 1.5), g0 + H_CORNICE, g0 + H_CORNICE, "minecraft:sea_lantern")
        # Front entrance: triangular pediment (red brick, white raking edges), oculus and sign
        self._front_gable(m)

    @staticmethod
    def _front_block(v, h, outer):
        """The projecting entrance bay on the front (each block is |v| from the center line
        and h above the ground; outer = the outermost layer)."""
        at = abs(v)
        if h == 1:
            return PLINTH
        if h in (H_BAND1, H_CORNICE):
            return WHITE
        if h == H_CORNICE - 1:
            return WHITE if math.floor(v) % 2 == 0 else BRICK
        # Corner piers on either side of the entrance bay
        if at > HALF_FACE - 1.2 and outer:
            return BAND if h % 3 == 0 else BRICK
        if at <= 1.5 and 2 <= h <= 5:
            return AIR                                       # 3-block-wide main entrance
        if at <= 1.5 and h == 6:
            return WHITE                                     # Door lintel
        if (at <= 0.5 or 1.5 <= at <= 2.5) and 9 <= h <= 11:
            return AIR if outer else GLASS                   # Three narrow upper-floor windows
        if (at <= 0.5 or 1.5 <= at <= 2.5) and h == 8:
            return WHITE                                     # Windowsill
        if h in (4, 10) and outer:
            return BAND
        return BRICK

    def _front_gable(self, m):
        """The entrance bay on the front (facing Red House Plaza): it projects 1 m, topped
        by a red brick triangular pediment (white raking edges, central oculus) that rises
        above the eaves."""
        fr, g0 = self.fr, self.g0
        U, V = fr.U, fr.V
        hw = HALF_FACE - 0.4
        bay = (U >= A_WALL - 0.6) & (U <= A_WALL + 1.2) & (np.abs(V) <= hw)
        for x, z in fr.cells(bay):
            u, v = fr.local(x, z)
            outer = u > A_WALL + 0.2
            for h in range(1, H_CORNICE + 1):
                m.set(x, g0 + h, z, self._front_block(v, h, outer))
        u0 = A_WALL + 0.7
        y = g0 + H_CORNICE + 1
        m.gable(-hw, hw, A_WALL + 0.2, A_WALL + 1.2, y, 5.5, BRICK, edge="smooth_quartz_stairs", axis="v")
        m.gable(-hw + 0.5, hw - 0.5, A_WALL - 3.0, A_WALL + 0.2, y, 5.0, ROOF, axis="v")
        # Oculus in the middle of the pediment (white surround)
        for dv in (-1.0, 0.0, 1.0):
            for dy in (1, 2, 3):
                m.at(u0, dv, y + dy, GLASS if (dv == 0.0 and dy == 2) else WHITE)
        # One step in front of the door
        for dv in np.arange(-2.0, 2.5, 1.0):
            m.at(A_WALL + 1.7, dv, g0 + 1, CK.stair("polished_andesite_stairs", m.facing(-1, 0)))
        # Sign (above the door lintel, below the upper-floor windows): a wall sign whose
        # first line is the name (it does not start with `出口`)
        x, z = fr.cell(A_WALL + 1.7, 0.0)
        m.w.sign(x, g0 + 7, z, ["西門紅樓", "The Red House", "1908", ""], facing=fr.dir(1.0, 0.0),
                 wood="dark_oak", kind="wall", glow=True, color="white")

    # ---- Cruciform Building ----
    def _hall_pattern(self, face, t, h, layer, u, v, q=None):
        """Cruciform Building: a single story of red brick walls with a 2 m wide arched
        window between each pair of buttresses, white keystones above the windows, and a
        white band along the top of the wall."""
        if h == 1:
            return PLINTH if layer == 0 else BRICK
        if h == H_HALL:
            return WHITE if layer == 0 else BRICK
        p = t % BAY
        win = 1.0 <= p < 3.0 and 3 <= h <= 6
        if win:
            return GLASS if layer else AIR
        if layer:
            return BRICK
        if 1.0 <= p < 3.0 and h == 7:
            return WHITE
        if h == 4 and not (1.0 <= p < 3.0):
            return BAND
        if q is not None and q < 1.6 and h % 2 == 0:
            return BAND
        return BRICK

    def _hall(self, m):
        """Cruciform Building: a single-story red brick clear span (held up by buttresses);
        the long hall and the transept each have a gable roof, intersecting at the crossing,
        and each of the three gable ends has a small oculus."""
        fr, g0 = self.fr, self.g0
        U, V = fr.U, fr.V
        hall = self.hall
        corners = [(ARM_U[0], ARM_V[0] - ARM_V[1]), (ARM_U[0], ARM_V[0] + ARM_V[1]),
                   (CROSS_U[0], CROSS_V[0]), (CROSS_U[1], CROSS_V[0]),
                   (CROSS_U[0], CROSS_V[1]), (CROSS_U[1], CROSS_V[1])]
        m.fill(hall, g0 + 1, g0 + 1, PLINTH)
        m.facade(hall, g0 + 1, g0 + H_HALL, self._hall_pattern, base=g0, corners=corners)
        # Buttresses: one every 4 m along the outside of the
        # long walls, each capped with a white sloped top
        out = dilate(hall, 1) & ~hall & ~dilate(self.oct, 2)
        for x, z, u, v, face, t in m.ring_cells(dilate(hall, 1)):
            if not out[z - fr.z0, x - fr.x0]:
                continue
            if (t % BAY) < 0.5 or (t % BAY) >= BAY - 0.5:
                for y in range(g0 + 1, g0 + 7):
                    m.set(x, y, z, BRICK)
                m.set(x, g0 + 7, z, CK.stair("smooth_quartz_stairs", m.facing(-face[0], -face[1])))
        # Gable roofs: the long hall's ridge runs along u, the transept's along v; the higher one
        # wins at the crossing
        vc, hw = ARM_V
        cu0, cu1 = CROSS_U
        chw = (cu1 - cu0) / 2.0
        h_arm = np.where(self.arm, 4.5 * (1 - np.abs(V - vc) / (hw + 0.6)), -1.0)
        h_cross = np.where(self.cross, 5.0 * (1 - np.abs(U - (cu0 + cu1) / 2.0) / (chw + 0.6)), -1.0)
        h = np.maximum(h_arm, h_cross).clip(0, None)
        roofm = dilate(hall, 1) & ~dilate(self.oct, 0)
        hh = np.where(hall, h, 0.0)
        # White band along the top of the wall, with eaves projecting one block beyond it
        # (upside-down slabs)
        m.fill(hall, g0 + H_HALL + 1, g0 + H_HALL + 1, WHITE)
        eave = roofm & ~hall
        m.fill(eave, g0 + H_HALL + 1, g0 + H_HALL + 1, CK.slab(ROOF_SLAB, "top"))
        # Gables: fill everything under the roof with brick (which produces the triangular
        # gable walls at the ends), then lay the roof tiles
        top = g0 + H_HALL_ROOF + np.floor(hh).astype(int) - 1
        m.fill(hall, g0 + H_HALL_ROOF, top, BRICK)
        m.roof(hall, g0 + H_HALL_ROOF, hh, ROOF, slab_name=ROOF_SLAB, stair_name=ROOF_STAIR, shell=1)
        # White coping and an oculus at the top of each gable: the long hall's west end and the
        # transept's north and south ends
        for cu, cv in ((ARM_U[0] + 0.5, vc), ((cu0 + cu1) / 2.0, CROSS_V[0] + 0.5),
                       ((cu0 + cu1) / 2.0, CROSS_V[1] - 0.5)):
            m.at(cu, cv, g0 + H_HALL_ROOF + 2, WHITE)
            m.at(cu, cv, g0 + H_HALL_ROOF + 1, GLASS)
            m.at(cu, cv, g0 + H_HALL_ROOF, WHITE)


BUILDS = {"red_house": RedHouse}
