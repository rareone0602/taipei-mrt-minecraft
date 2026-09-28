#!/usr/bin/env python3
"""Presidential Office Building (former Office of the Governor-General of Taiwan, 1919).

Position, orientation and outline: OSM relation/206817 (a rectangular outer ring
enclosing a north and a south courtyard) and its building:parts (the tower
way/368582924 with height=60, the six-story pavilions at the four corners and the rear,
the porte-cochère at the front, the semicircular porches at the corners).
The appearance follows public sources:
  · The front faces east; the front is about 140 m long, the sides about 85 m deep, and
    the central tower about 60 m tall (equivalent to 11 stories). The main block has five
    stories; the plan is a rectangle in which an east-west central wing divides the court
    into a north and a south courtyard (the Presidential Office website's "Architectural
    Beauty" and "The Birth of the Presidential Office", Chinese Wikipedia "Presidential
    Office Building (Taiwan)").
  · Late Renaissance "Tatsuno style": red facing brick and off-white granolithic plaster
    laid in alternating red and white horizontal bands, round-arched windows, corner
    towers at the four corners, guard towers on either side of the central tower, a
    porte-cochère at the main entrance (flat-roofed since the war), and a tower that
    turns from square to octagonal (same sources).
  · Originally designed by Nagano Uheiji and revised by Moriyama Matsunosuke;
    construction began in 1912 and was completed in 1919 (English Wikipedia).
The principal axis of the OSM outline is off by 5.7° (after projection), and the whole
building is built in local coordinates at that angle: u points east (the front) and
v points south; the origin is the east-west midpoint of the outer ring on the tower's
north-south center line. All numbers below are meters in this coordinate system,
measured from the OSM building:parts (see each constant's comment); the outer walls
themselves use the OSM outer ring directly.
"""
import math

import numpy as np

from mrt.application.attractions import colonial_kit as CK
from mrt.application.attractions import kit
from mrt.application.attractions.kit import AIR, Attraction, Frame, Spot, erode, dilate

# ---- Materials ----
BRICK = "minecraft:bricks"                    # Red facing brick (OSM building:colour #a25344)
BAND = "minecraft:calcite"                    # Off-white granolithic plaster band
# White stone: cornices, columns, tower top (OSM roof:colour #ffffff)
STONE = "minecraft:smooth_quartz"
PLINTH = "minecraft:polished_andesite"        # Rusticated plinth
GLASS = "minecraft:gray_stained_glass"
# Copper roof (the gray-green of OSM roof:colour #bed0bd); waxed so it stops oxidizing
ROOF = "minecraft:waxed_weathered_cut_copper"
ROOF_SLAB = "waxed_weathered_cut_copper_slab"
ROOF_STAIR = "waxed_weathered_cut_copper_stairs"
FLOOR = "minecraft:smooth_stone"
# Roof of the porte-cochère and the semicircular porches (OSM roof:colour #a25344)
PORCH_ROOF = "minecraft:granite"

# ---- Heights (blocks above the ground; the ground is block g0) ----
H_PLINTH = 1            # Top of the plinth = ground floor
H_FLOORS = (1, 6, 11, 16)   # Floors of stories one to four
# Main cornice (above the four stories of wall; the fifth story is inside the copper mansard roof)
H_CORNICE = 21
# How far the main roof rises above the cornice (ridge at +26;
# the corner towers' pyramidal roofs start at +26)
H_ROOF = 4.0
# Cornice of the corner towers and the rear central pavilion (six stories in OSM)
H_PAVILION = 25
H_GUARD = 26            # Cornice of the guard towers on either side of the main entrance
# Top of the central tower (OSM height=60; the Presidential Office website says "about 60 m")
H_TOWER = 60

# ---- Plan (local coordinates in meters, measured from OSM) ----
# Tower way/368582924: u 25.5 to 33.8, v ±4.2, with a 1.2 m
# notch at each corner (a cross-shaped plan)
TOWER_U, TOWER_A, TOWER_N = 29.65, 4.15, 1.2
EAST = 37.5             # East facade (outer ring u 36.8 to 38.4)
WEST = -37.7            # West facade
# Corner towers: the projecting part of the north and south facades starts here
# (outer ring u 24.4 / -26.7)
CORNER_U = (24.4, -26.7)
# Corner towers on the east and west facades start at |v| >= 48.6 (outer ring v ±48.6 to ±49.5)
CORNER_V = 48.6
# Guard towers on either side of the main entrance (outer ring u 41.1 to 41.5, v ±7 to ±13.1)
GUARD_V = (7.2, 13.1)
GUARD_U = 33.8          # The guard towers extend back to the east edge of the tower
PORCH = (39.8, 52.7, 6.0)   # Porte-cochère way/548610153 + 548610154: u 39.8 to 52.7, v ±6
# Rear central pavilion way/1416563941 (u -37.9 to -24.2, v ±7) plus the outer ring's
# projection (u -40.4, v ±13)
WEST_PAV = (-40.4, -24.2, 7.5)
WEST_PAV_V = 13.3
# Central wing (way/1416563951, three stories, white walls): u -20.7 to 20.8, v ±12.3
CENTER_BAR = (-20.7, 20.8, 12.3)
# Domed hall on the central wing, way/1416563952 (four stories, roof:shape=dome)
DOME_HALL = (0.6, 18.0, -8.2, 9.3)
# Gabled hall on the central wing, way/1416563942 (four stories, gabled)
GABLE_HALL = (-17.8, -0.4, -8.3, 9.2)

BAY = 4.0               # Bay: a 2 m wide window + 2 m of pier


def _poly(f):
    return max(f["outer"], key=len) if f and f.get("outer") else None


class PresidentialOffice(Attraction):
    height_m = float(H_TOWER)
    margin = 16

    def __init__(self, item):
        super().__init__(item)
        main = self.feature("relation/206817") or (self.mains() or [None])[0]
        self.outer = _poly(main) or self.outline()
        self.holes = [r for r in (main.get("inner") or []) if len(r) >= 3] if main else []
        self.angle = CK.fit_angle(self.outer)
        cx, cz = CK.centroid(self.outer)
        f0 = Frame(cx, cz, self.angle, 10)
        u0, u1, _, _ = CK.local_extent(f0, self.outer)
        tower = _poly(self.feature("way/368582924"))
        tv = CK.to_local(f0, *CK.centroid(tower))[1] if tower else 0.0
        self.origin = f0.world((u0 + u1) / 2.0, tv)
        # Semicircular porches (at the four corners, building:part=roof, one story) and the rear
        # semicircular porch (two stories)
        self.porch_polys = [p for p in (_poly(self.feature(k)) for k in (
            "way/1416563953", "way/1416563944", "way/1416563945", "way/1416563954")) if p]
        self.west_porch = _poly(self.feature("way/1416563938"))

    # ---- Framework interface ----
    def spot_uv(self):
        """Default viewpoint: on Ketagalan Boulevard, 38 m east of the front, where the
        60 m tower top is in view when looking up.
        (tools/verify_attractions reads only 44 m beyond the outline, so the viewpoint
        cannot be farther away.)"""
        return (EAST + 38.0, 0.0)

    def bbox(self):
        x0, z0, x1, z1 = super().bbox()
        fr = Frame(self.origin[0], self.origin[1], self.angle, 1)
        sx, sz = fr.world(*self.spot_uv())
        return (min(x0, int(sx) - 6), min(z0, int(sz) - 6), max(x1, int(sx) + 6), max(z1, int(sz) + 6))

    def plan(self, site):
        ox, oz = self.origin
        self.fr = fr = Frame(ox, oz, self.angle, 72)
        foot = fr.polygon(self.outer)
        for r in self.holes:
            foot &= ~fr.polygon(r)
        self.foot = foot
        self.courts = [fr.polygon(r) for r in self.holes]
        self.g0 = site.level(fr, foot)
        self.site = site
        self.semis = fr.empty()
        for p in self.porch_polys:
            self.semis |= fr.polygon(p)
        self.west_semi = fr.polygon(self.west_porch) if self.west_porch else fr.empty()
        # The central wing (between the two courtyards) is built separately; the four
        # wings = the outer ring minus the courtyards, the central wing and the semicircular porches
        u0, u1, hv = CENTER_BAR
        self.bar = foot & (fr.U > u0 + 0.5) & (fr.U < u1 - 0.5) & (np.abs(fr.V) <= hv + 0.5)
        self.body = foot & ~self.semis & ~self.west_semi & ~self.bar
        # Grading area: 3 blocks beyond the outer ring, plus the area in front of the
        # porte-cochère. Ground heights must be looked up in plan(): cli clears the terrain
        # cache after plan_all, and calling site.g in build() raises an error.
        self.yard = dilate(foot | self.semis | self.west_semi, 3) | fr.rect(
            EAST, PORCH[1] + 3, -PORCH[2] - 4, PORCH[2] + 4)
        site.grid(fr, self.yard)
        # Convex corners of the outer ring (local coordinates): white quoins at the wall corners
        self.corners = CK.convex_corners([CK.to_local(fr, x, z) for x, z in self.outer])
        su, sv = self.spot_uv()
        sx, sz = fr.cell(su, sv)
        sy = site.g(sx, sz) + 1
        yaw, pitch = kit.look(sx, sy, sz, *self._world3(TOWER_U, 0.0, self.g0 + 28))
        self._spots = [Spot("", sx, sy, sz, yaw, pitch, self.name_zh, self.name_en)]

    def _world3(self, u, v, y):
        x, z = self.fr.world(u, v)
        return x, y, z

    def plaque(self):
        return [self.name_zh, self.name_en, "1919 年落成", "中央塔高 60 公尺"]

    def plaque_en(self):
        return ["Completed in 1919", "Built in 1919"]

    # ---- Build ----
    def build(self, w):
        fr, g0 = self.fr, self.g0
        m = CK.Mason(w, fr)
        U, V = fr.U, fr.V
        foot, body = self.foot, self.body
        west_semi = self.west_semi

        # Grading: 3 blocks beyond the outer ring, paved as a plaza (andesite paving)
        self.site.prepare(w, fr, self.yard, g0, top="minecraft:polished_andesite", clear=40)
        for c in self.courts:
            self._courtyard(m, c)

        # The four wings of the main block: four stories of red brick + cornice + copper roof
        m.fill(erode(body, 1), g0 + 1, g0 + 1, FLOOR)
        m.facade(body, g0 + 1, g0 + H_CORNICE - 1, self._wing_pattern, base=g0, corners=self.corners)
        for h in H_FLOORS[1:]:
            m.fill(erode(body, 2), g0 + h, g0 + h, FLOOR)
        m.fill(body, g0 + H_CORNICE, g0 + H_CORNICE, STONE)
        self._cornice(m, body, g0 + H_CORNICE)
        d = kit.depth(body).astype(float)
        rise = np.minimum(d, 3.0) + np.clip(d - 3.0, 0, None) * 0.3
        m.roof(body, g0 + H_CORNICE + 1, np.minimum(rise - 1.0, H_ROOF).clip(0, None), ROOF,
               slab_name=ROOF_SLAB, stair_name=ROOF_STAIR, shell=2)
        self._dormers(m, body)

        # Corner towers at the four corners (six stories, square pyramidal copper roofs)
        for su in (1, -1):
            for sv in (1, -1):
                u_in = CORNER_U[0] if su > 0 else CORNER_U[1]
                zone = body & ((U - u_in) * su >= 0) & (V * sv >= CORNER_V)
                self._pavilion(m, zone, H_PAVILION, rise=8.0, lantern=True)
        # Rear central pavilion
        wz = body & (U <= WEST_PAV[1]) & (np.abs(V) <= WEST_PAV_V)
        self._pavilion(m, wz, H_PAVILION, rise=6.0, lantern=False)
        # Guard towers on either side of the main entrance (small domes)
        for sv in (1, -1):
            gz = body & (U >= GUARD_U) & (V * sv >= GUARD_V[0]) & (V * sv <= GUARD_V[1])
            self._guard_tower(m, gz, sv)
        # Central wing: three stories of white walls and two halls (one gabled, one domed)
        self._center(m)
        # Central tower
        self._tower(m)
        # Porte-cochère and semicircular porches
        self._porte_cochere(m)
        for p in self.porch_polys:
            self._semi_porch(m, fr.polygon(p), 6)
        if self.west_porch:
            self._semi_porch(m, west_semi, 11)
        # Main entrance: a 3-block-wide doorway in the middle of the ground floor; a ring of
        # steps around the plinth (the porte-cochère floor is also one block higher)
        m.fill(foot & (U >= EAST - 1.0) & (U <= PORCH[0] + 1.0) & (np.abs(V) <= 1.6), g0 + 2, g0 + 5, AIR)
        porch = fr.rect(PORCH[0], PORCH[1], -PORCH[2], PORCH[2])
        for x, z, u, v, face, t in m.ring_cells(dilate(porch, 1) & ~foot):
            if face[0] < 0:
                continue
            m.set(x, g0 + 1, z, CK.stair("polished_andesite_stairs", m.facing(-face[0], -face[1])))

    # ---- Facade patterns ----
    def _window(self, face, t, h, layer, rows, top_arch=True, width=2.0, bay=BAY, off=0.0):
        """A window within a bay: if the along-wall coordinate t falls inside the window
        and the height h is in rows, the outer layer is hollow and the inner layer is glass;
        the top block of the outer layer is an upside-down stair forming the round arch.
        Returns None where there is no window."""
        p = (t - off) % bay
        lo = (bay - width) / 2.0
        if not (lo <= p < lo + width) or h not in rows:
            return None
        if layer:
            return GLASS
        if top_arch and h == rows[-1]:
            a = CK.Mason.along(face)
            left = p < lo + width / 2.0
            d = (-a[0], -a[1]) if left else a
            return CK.stair("smooth_quartz_stairs", self._fc(d), "top")
        return AIR

    def _fc(self, d):
        return self.fr.facing(*d)

    @staticmethod
    def _quoin(q, h):
        """Quoins at the wall corners: alternating long (within 2 blocks of the corner) and
        short (within 1 block) courses of white granolithic plaster."""
        return q is not None and (q < 1.6 if h % 2 == 0 else q < 0.8)

    def _wing_pattern(self, face, t, h, layer, u, v, q=None):
        if h == H_PLINTH:
            return PLINTH if layer == 0 else BRICK
        rows = {2: (2, 3, 4), 3: (2, 3, 4), 4: (2, 3, 4), 7: (7, 8, 9), 8: (7, 8, 9), 9: (7, 8, 9),
                12: (12, 13, 14), 13: (12, 13, 14), 14: (12, 13, 14), 17: (17, 18), 18: (17, 18)}.get(h)
        if layer == 0 and q is not None and q < 2.0:
            return BAND if self._quoin(q, h) else BRICK
        if rows:
            b = self._window(face, t, h, layer, rows, top_arch=(h <= 14))
            if b is not None:
                return b
        if layer:
            return BRICK
        p = t % BAY
        if h in (5, 10, 15) and 1.5 <= p < 2.5:      # Keystone above an arched window
            return BAND
        if h in (6, 11, 16, 20):                      # White band at each floor line
            return BAND
        return BRICK

    def _pavilion_pattern(self, face, t, h, layer, u, v, q=None):
        """Corner towers and guard towers: one story more than the main block; the piers
        between windows have a white band every three courses (suggesting rustication),
        and the wall corners have quoins."""
        if h == H_PLINTH:
            return PLINTH if layer == 0 else BRICK
        rows = {2: (2, 3, 4), 3: (2, 3, 4), 4: (2, 3, 4), 7: (7, 8, 9), 8: (7, 8, 9), 9: (7, 8, 9),
                12: (12, 13, 14), 13: (12, 13, 14), 14: (12, 13, 14), 17: (17, 18), 18: (17, 18),
                21: (21, 22, 23), 22: (21, 22, 23), 23: (21, 22, 23)}.get(h)
        if layer == 0 and q is not None and q < 2.0:
            return BAND if self._quoin(q, h) else BRICK
        if rows:
            b = self._window(face, t, h, layer, rows, top_arch=(h <= 14 or h >= 21))
            if b is not None:
                return b
        if layer:
            return BRICK
        p = t % BAY
        if h in (6, 11, 16, 20, 24):
            return BAND
        if h in (5, 10, 15) and 1.5 <= p < 2.5:
            return BAND
        if h in (3, 13) and not (1.0 <= p < 3.0):
            return BAND
        return BRICK

    # ---- Parts ----
    def _cornice(self, m, mask, y):
        """Cornice: a ring of upside-down stone stairs outside the wall (projecting 1 m)."""
        out = dilate(mask, 1) & ~mask
        for x, z, u, v, face, t in m.ring_cells(dilate(mask, 1)):
            if not out[z - self.fr.z0, x - self.fr.x0]:
                continue
            m.set(x, y, z, CK.stair("smooth_quartz_stairs", m.facing(-face[0], -face[1]), "top"))

    def _dormers(self, m, body):
        """Dormers on the roof (vents in the copper roof): one every two bays along the
        outer facades, set back 1 block from the cornice. None on the courtyard side or on
        the walls that meet the central wing (skip any spot whose point 3 m outward is still
        inside the building or a courtyard)."""
        fr, g0 = self.fr, self.g0
        y = g0 + H_CORNICE + 1
        seen = set()
        inside = self.foot | self.bar
        for c in self.courts:
            inside = inside | c
        for x, z, u, v, face, t in m.ring_cells(body):
            p = t % (2 * BAY)
            if not (1.0 <= p < 3.0):
                continue
            cx, cz = fr.cell(u + face[0] * 3.0, v + face[1] * 3.0)
            i, j = cz - fr.z0, cx - fr.x0
            if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] and inside[i, j]:
                continue
            iu, iv = u - face[0] * 1.0, v - face[1] * 1.0
            key = fr.cell(iu, iv)
            if key in seen:
                continue
            seen.add(key)
            ix, iz = key
            m.set(ix, y, iz, STONE)
            m.set(ix, y + 1, iz, GLASS)
            m.set(ix, y + 2, iz, STONE)
            m.set(ix, y + 3, iz, CK.slab(ROOF_SLAB))
            bx, bz = fr.cell(iu - face[0], iv - face[1])
            for yy in range(y, y + 3):
                m.set(bx, yy, bz, ROOF)

    def _pavilion(self, m, zone, h_top, rise, lantern):
        """A corner tower one story taller than the main block: the outer walls follow the
        pavilion pattern up to h_top, topped by a square pyramidal copper roof."""
        if not zone.any():
            return
        fr, g0 = self.fr, self.g0
        m.clear_box(zone, g0 + H_CORNICE + 1, g0 + h_top + 12)
        m.facade(zone, g0 + 1, g0 + h_top - 1, self._pavilion_pattern, base=g0, corners=self.corners)
        m.fill(erode(zone, 2), g0 + H_CORNICE, g0 + H_CORNICE, FLOOR)
        m.fill(zone, g0 + h_top, g0 + h_top, STONE)
        self._cornice(m, zone, g0 + h_top)
        us, vs = fr.U[zone], fr.V[zone]
        cu, cv = (us.min() + us.max()) / 2.0, (vs.min() + vs.max()) / 2.0
        r = max(us.max() - us.min(), vs.max() - vs.min()) / 2.0 + 0.5
        h = kit.pyramid(fr, r, rise, sides=4, du=cu, dv=cv)
        m.roof(zone, g0 + h_top + 1, h, ROOF, slab_name=ROOF_SLAB, shell=2)
        top = g0 + h_top + 1 + int(rise)
        if lantern:
            m.at(cu, cv, top, STONE)
            m.at(cu, cv, top + 1, "minecraft:waxed_weathered_lightning_rod[facing=up,powered=false]")

    def _guard_tower(self, m, zone, sv):
        if not zone.any():
            return
        fr, g0 = self.fr, self.g0
        m.clear_box(zone, g0 + H_CORNICE + 1, g0 + H_GUARD + 8)
        m.facade(zone, g0 + 1, g0 + H_GUARD - 1, self._pavilion_pattern, base=g0, corners=self.corners)
        m.fill(zone, g0 + H_GUARD, g0 + H_GUARD, STONE)
        self._cornice(m, zone, g0 + H_GUARD)
        us, vs = fr.U[zone], fr.V[zone]
        cu, cv = (us.min() + us.max()) / 2.0, (vs.min() + vs.max()) / 2.0
        r = min(us.max() - us.min(), vs.max() - vs.min()) / 2.0
        m.dome(cu, cv, r, g0 + H_GUARD + 1, 3.5, ROOF, shell=2, slab_name=ROOF_SLAB)
        m.at(cu, cv, g0 + H_GUARD + 5, STONE)
        m.at(cu, cv, g0 + H_GUARD + 6, "minecraft:waxed_weathered_lightning_rod[facing=up,powered=false]")

    def _center(self, m):
        """Central wing: three stories of white walls between the two courtyards (OSM
        building:colour #ffffff), topped by two four-story halls (gabled way/1416563942 and
        domed way/1416563952; hidden behind the tower from the front, visible from the
        courtyards)."""
        fr, g0 = self.fr, self.g0
        bar = self.bar

        def white(face, t, h, layer, u, v, q=None):
            if h in (6, 11, 15, 19):
                return STONE
            rows = (2, 3, 4) if h < 6 else (7, 8, 9) if h < 11 else (12, 13) if h < 15 else (16, 17, 18)
            b = self._window(face, t, h, layer, rows)
            return b if b is not None else BAND

        m.fill(erode(bar, 1), g0 + 1, g0 + 1, FLOOR)
        m.facade(bar, g0 + 1, g0 + 15, white, base=g0)
        for h in (6, 11):
            m.fill(erode(bar, 2), g0 + h, g0 + h, FLOOR)
        m.fill(bar, g0 + 16, g0 + 16, STONE)
        for (a0, a1, b0, b1), kind in ((GABLE_HALL, "gable"), (DOME_HALL, "dome")):
            hall = fr.rect(a0, a1, b0, b1) & bar
            m.facade(hall, g0 + 17, g0 + 19, white, base=g0, layers=1)
            m.fill(hall, g0 + 20, g0 + 20, STONE)
            cu, cv = (a0 + a1) / 2, (b0 + b1) / 2
            if kind == "gable":
                m.roof(hall, g0 + 21, kit.gable(fr, (a1 - a0) / 2, (b1 - b0) / 2, 4.0, du=cu, dv=cv),
                       ROOF, slab_name=ROOF_SLAB, shell=1)
            else:
                r = min(a1 - a0, b1 - b0) / 2 - 1.0
                m.dome(cu, cv, r, g0 + 21, 5.0, ROOF, shell=1, slab_name=ROOF_SLAB)

    def _tower(self, m):
        """Central tower (Presidential Office website: about 60 m, equivalent to 11 stories,
        a cross-shaped section with notched corners, turning from square to octagonal):

          +22 to +42  Cross-shaped red brick shaft with a white band every three courses,
                      white quoins at the re-entrant corners, and two tiers of tall narrow
                      arched windows on each face
          +43 to +44  White cornice (projecting 1 m), small pinnacles at the four corners,
                      a stone balustrade
          +45 to +52  Octagonal white belvedere with a large round arch on each of the four
                      cardinal faces
          +53 to +54  Octagonal cornice
          +55 to +59  White octagonal pyramidal roof (OSM roof:shape=pyramidal, roof:colour #ffffff)
          +60         Lightning rod at the top (OSM height=60)
        """
        fr, g0 = self.fr, self.g0
        U, V = fr.U - TOWER_U, fr.V
        a, n = TOWER_A, TOWER_N
        au, av = np.abs(U), np.abs(V)
        plan = (au <= a) & (av <= a) & ~((au > a - n) & (av > a - n))
        m.clear_box(plan, g0 + H_CORNICE + 1, g0 + 59)

        def rel(face, t):
            """Rebase the along-wall coordinate on the tower's center line (for a wall whose
            normal runs along v, the along-wall coordinate is u)."""
            return t - TOWER_U if face[1] else t

        def arch(face, t):
            al = CK.Mason.along(face)
            return CK.stair("smooth_quartz_stairs", self._fc((-al[0], -al[1]) if t < 0 else al), "top")

        def shaft(face, t, h, layer, u, v, q=None):
            if layer:
                return BRICK
            t = rel(face, t)
            # Quoins at the re-entrant corners of the cross-shaped plan
            if abs(t) > a - n - 0.6:
                return BAND if h % 2 == 0 else STONE
            if abs(t) < 1.0 and (26 <= h <= 31 or 35 <= h <= 40):
                return arch(face, t) if h in (31, 40) else AIR
            if h in (32, 41):
                return STONE if abs(t) < 1.0 else BAND
            if h % 3 == 0:
                return BAND
            return BRICK

        m.facade(plan, g0 + 16, g0 + 42, shaft, base=g0)
        inner = erode(plan, 2)
        m.fill(inner & ((np.abs(V) < 1.0) | (np.abs(U) < 1.0)), g0 + 26, g0 + 40, GLASS)
        for h in (25, 34):
            m.fill(inner, g0 + h, g0 + h, FLOOR)
        # Cornice, corner pinnacles, balustrade
        m.fill(plan, g0 + 43, g0 + 43, STONE)
        self._cornice(m, plan, g0 + 43)
        big = (au <= a + 1) & (av <= a + 1)
        m.fill(big & ~erode(big, 1), g0 + 44, g0 + 44, CK.slab("smooth_quartz_slab"))
        for su in (-1, 1):
            for sv in (-1, 1):
                pu, pv = TOWER_U + su * (a + 0.5), sv * (a + 0.5)
                for y in range(g0 + 44, g0 + 47):
                    m.at(pu, pv, y, "minecraft:quartz_pillar[axis=y]")
                m.at(pu, pv, g0 + 47, CK.slab("smooth_quartz_slab"))
        # Octagonal belvedere (apothem 3.3): white stone, a
        # large round arch on each of the four cardinal faces
        oct2 = fr.ngon(8, 3.3, rot=0.0, du=TOWER_U)
        m.fill(plan & ~erode(plan, 1) | oct2, g0 + 44, g0 + 44, STONE)

        def stage2(face, t, h, layer, u, v, q=None):
            ang = math.degrees(math.atan2(v, u - TOWER_U)) % 90
            cardinal_face = ang < 22.5 or ang > 67.5
            t = rel(face, t)
            if cardinal_face and abs(t) < 1.0 and 46 <= h <= 51:
                return arch(face, t) if h == 51 else AIR
            if h in (45, 48):
                return BAND
            return STONE

        m.facade(oct2, g0 + 45, g0 + 52, stage2, base=g0, layers=1)
        m.fill(erode(oct2, 1), g0 + 45, g0 + 45, FLOOR)
        # Stone core inside the belvedere (the stairwell)
        m.fill(erode(oct2, 2), g0 + 46, g0 + 51, BAND)
        ring = fr.ngon(8, 4.0, du=TOWER_U)
        m.fill(ring, g0 + 53, g0 + 53, STONE)
        m.fill(ring & ~fr.ngon(8, 3.1, du=TOWER_U), g0 + 54, g0 + 54, CK.slab("smooth_quartz_slab"))
        m.fill(fr.ngon(8, 3.1, du=TOWER_U), g0 + 54, g0 + 54, STONE)
        # Octagonal pyramidal roof at +55 to +59, lightning rod at +60
        h = kit.pyramid(fr, 3.0, 4.4, sides=8, du=TOWER_U)
        m.roof(fr.ngon(8, 3.0, du=TOWER_U), g0 + 55, h, STONE, slab_name="smooth_quartz_slab", shell=1)
        m.at(TOWER_U, 0.0, g0 + 59, "minecraft:quartz_pillar[axis=y]")
        m.at(TOWER_U, 0.0, g0 + H_TOWER, "minecraft:waxed_weathered_lightning_rod[facing=up,powered=false]")

    def _porte_cochere(self, m):
        """Porte-cochère: a one-story colonnade (flat-roofed since the war) whose roof is a
        second-floor terrace. The driveway passes through from the north and south sides."""
        fr, g0 = self.fr, self.g0
        u0, u1, hv = PORCH
        top = fr.rect(u0, u1, -hv, hv)
        m.fill(top, g0 + 1, g0 + 1, "minecraft:polished_andesite")
        for u in (u1 - 1.0, u1 - 4.5, u1 - 8.0):
            for v in (-hv + 1.0, hv - 1.0):
                m.column(u, v, g0 + 2, g0 + 7, "minecraft:quartz_pillar[axis=y]",
                         base=STONE, capital="minecraft:chiseled_quartz_block")
        for v in (-2.5, 2.5):
            m.column(u1 - 1.0, v, g0 + 2, g0 + 7, "minecraft:quartz_pillar[axis=y]",
                     base=STONE, capital="minecraft:chiseled_quartz_block")
        m.fill(top, g0 + 8, g0 + 8, STONE)
        m.fill(top & ~erode(top, 1), g0 + 9, g0 + 9, "minecraft:diorite_wall")
        m.fill(erode(top, 1), g0 + 9, g0 + 9, AIR)
        m.fill(erode(top, 1), g0 + 8, g0 + 8, PORCH_ROOF)
        # Driveway: sloped brick paving on both sides running under the porte-cochère
        m.fill(top & (fr.U < u1 - 1.5) & (fr.U > u0 + 1.0), g0 + 1, g0 + 1, "minecraft:stone_bricks")

    def _semi_porch(self, m, mask, height):
        """Semicircular porch: a ring of white columns along the arc, topped by a ring of
        stone lintels and a red roof."""
        if not mask.any():
            return
        g0 = self.g0
        m.fill(mask, g0 + 1, g0 + 1, "minecraft:polished_andesite")
        rim = mask & ~erode(mask, 1)
        for x, z, u, v, face, t in m.ring_cells(mask):
            if (x + z) % 2 == 0:
                for y in range(g0 + 2, g0 + height):
                    m.set(x, y, z, "minecraft:quartz_pillar[axis=y]")
        m.fill(mask, g0 + height, g0 + height, STONE)
        m.fill(erode(mask, 1), g0 + height, g0 + height, PORCH_ROOF)
        m.fill(rim, g0 + height + 1, g0 + height + 1, CK.slab("smooth_quartz_slab"))

    def _courtyard(self, m, court):
        """Courtyard: lawn, cross-shaped paths, a low hedge around the edge, and four trees."""
        fr, g0 = self.fr, self.g0
        m.fill(court, g0, g0, "minecraft:grass_block")
        m.fill(court, g0 + 1, g0 + 30, AIR)
        us, vs = fr.U[court], fr.V[court]
        cu, cv = (us.min() + us.max()) / 2.0, (vs.min() + vs.max()) / 2.0
        path = court & ((np.abs(fr.U - cu) <= 1.0) | (np.abs(fr.V - cv) <= 1.0))
        m.fill(path, g0, g0, "minecraft:polished_andesite")
        hedge = erode(court, 2) & ~erode(court, 3) & ~dilate(path, 1)
        m.fill(hedge, g0 + 1, g0 + 1, "minecraft:oak_leaves[persistent=true]")
        for du in (-0.3, 0.3):
            for dv in (-0.3, 0.3):
                tu = cu + du * (us.max() - us.min())
                tv = cv + dv * (vs.max() - vs.min())
                for y in range(g0 + 1, g0 + 5):
                    m.at(tu, tv, y, "minecraft:oak_log[axis=y]")
                blob = fr.ellipse(2.6, 2.6, du=tu, dv=tv) & court
                m.fill(blob, g0 + 5, g0 + 7, "minecraft:oak_leaves[persistent=true]")
                m.fill(fr.ellipse(1.6, 1.6, du=tu, dv=tv) & court, g0 + 8, g0 + 8,
                       "minecraft:oak_leaves[persistent=true]")


BUILDS = {"presidential_office": PresidentialOffice}
