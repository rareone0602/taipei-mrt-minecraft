#!/usr/bin/env python3
"""The Miramar Ferris Wheel: the Ferris wheel on the roof of Miramar Entertainment Park in
Dazhi (2004).

Public facts (only numbers and forms are taken; no text or images are copied):
  · Wheel diameter 70 m, total height 100 m; the base stands on the building's roof
    (5th floor, 30 m up). Source: Chinese Wikipedia "Miramar Ferris Wheel".
  · 48 gondolas (numbered 1–52, skipping 4, 13, 14 and 44), of which 2 are transparent
    and 2 are wheelchair accessible; 6 people per gondola, about 17 minutes per
    revolution; made by Senyo Kogyo of Japan, total weight about 600 metric tons. Same
    source.
  · Miramar Entertainment Park: 9 floors above ground and 3 below, opened in November
    2004; the IMAX theater is on floors 6 to 9. Source: Chinese Wikipedia "Miramar
    Entertainment Park".
  · Appearance (photos on Wikimedia Commons: "Miramar Ferris Wheel, Taipei, 2024",
    "Miramar Entertainment Park 20090905", "West Side of Miramar Entertainment Park"):
    a white steel rim, dense steel-cable spokes and an A-frame support leg on each
    side; the gondolas hang outside the rim, their colors graded around the wheel (red
    at the top, orange and yellow on the left, green at the bottom, blue on the right).
    The mall has beige stone walls with a brown horizontal band on every floor and a
    pale green pitched roof; on the west side is a wedge-shaped gable wall that rises
    from north to south.

Position: the wheel's center follows OSM node/5121602758 (attraction=big_wheel,
height=100), and the mall follows the outline of way/155816458. Orientation of the
wheel plane: in photos taken southward from the hills to the north, the wheel is a
perfect circle and Taipei 101 sits right behind the axle. The axle therefore runs
roughly north-south and the wheel plane east-west, matching the mall's long (east-west)
side, so the wheel plane is set along the direction of the mall's south edge.

Vertical allocation (measured from the ground g0): roof deck at 30 (top of the 5th
floor, the boarding platform), axle at 67. The gondola pivots lie on a circle of radius
33 m and the gondolas, 4 m tall, hang below them: the lowest gondola floor is at 31 and
the highest gondola roof at 100, 70 m from bottom to top, which agrees with the public
"wheel diameter 70 m, total height 100 m". The rim has a radius of 28.3 m and the
gondolas sit outside it (in photos the top gondola is above the rim).

The mall is a simplified massing (not a floor-by-floor reconstruction):
  · The whole outline: beige outer walls with a brown band every 5 m, shop windows
    around the ground floor and a pale green canopy.
  · Around the wheel (34 m east and west of the axle, 34 m north of the south edge):
    a deck on top of the 5th floor at 30 m. The wheel's south legs land 3 to 4 m
    outside the OSM outline, so the deck extends a little further south (the
    boarding platform) to carry them.
  · Northeast: the 9-story IMAX building, 48 m, with a circular emblem on its east
    wall and a large arched window on its west wall.
  · West wing: a wedge-shaped roof rising from 16 m at the north end to 36 m toward
    the south, then sloping down again at the south end; a large red arched gateway
    in the west wall.
  · Everything else: a wavy pale green roof at 19 to 26 m.
One viewpoint is on the street 90 m due south of the wheel (facing the wheel plane);
the other is inside the top gondola.
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions.kit import AIR, Attraction, Frame, Painter, Spot, dilate, erode, ring

# ---- Materials ----
STONE_WALL = "minecraft:white_terracotta"           # Beige stone outer wall
STRIPE = "minecraft:terracotta"                     # Brown horizontal band
SHOP_GLASS = "minecraft:light_blue_stained_glass"   # Ground-floor shop windows
GLASS = "minecraft:light_gray_stained_glass"
GLASS_ARCH = "minecraft:light_blue_stained_glass"   # Large arched window of the IMAX building
# Pale green metal roof (waxed, so it does not oxidize further)
COPPER = "minecraft:waxed_weathered_cut_copper"
COPPER_SLAB = "minecraft:waxed_weathered_cut_copper_slab[type=bottom]"
DECK = "minecraft:smooth_stone"
FLOOR = "minecraft:polished_andesite"
ARCH = "minecraft:red_concrete"
ARCH_GLASS = "minecraft:orange_stained_glass"
PAVE = "minecraft:smooth_stone"
EMBLEM = "minecraft:white_concrete"

RIM = "minecraft:white_concrete"                    # Rim
RING2 = "minecraft:red_terracotta"                  # The thin dark red ring outside the rim
STEEL = "minecraft:iron_block"                      # Axle, legs, gondola hangers
AXLE = "minecraft:light_gray_concrete"
# Steel-cable spokes (unconnected iron bars are a thin post)
SPOKE = "minecraft:iron_bars"
COLOURS = ("red", "orange", "yellow", "lime", "green", "cyan", "light_blue", "blue")
CLEAR = ("minecraft:white_stained_glass", "minecraft:glass")   # Transparent gondolas

# ---- Ferris wheel (meters = blocks) ----
DECK_Y = 30          # Top of the 5th floor (boarding platform)
HUB = 67             # Axle
RP = 33.0            # Radius of the gondola pivots
GH = 4               # Gondola height (floor, two rows of windows, roof)
RIM_IN, RIM_OUT = 27.6, 29.0
RIM_W = 2.0          # The front and rear rims sit ±2 m along the axle
HUB_R, HUB_W, AXLE_W = 3.5, 4.5, 6.5
N_GONDOLA = 48
# Spokes per face (the front and rear faces are offset by half
# a step, so 64 are seen from the front)
N_SPOKE = 32
RINGS = (10.0, 19.0) # Inner rings
LEG_U, LEG_W, LEG_R = 16.0, 5.5, 1.1
TIE_Y = 44           # Cross-brace between the legs
# The two transparent gondolas (at the ten o'clock and four o'clock positions)
TRANSPARENT = (8, 32)
# How far south of the wheel the viewpoint is: from here the frame holds everything from the
# mall's ground floor to the top of the wheel
VIEW_M = 90.0


def axis_angle(poly):
    """Return the outline's dominant direction (radians, folded into ±45°).

    It is the length-weighted mean direction of the edges. principal_angle rounds to
    whole degrees; the wheel plane needs the exact direction."""
    sx = sy = 0.0
    for i in range(len(poly)):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % len(poly)]
        L = math.hypot(x2 - x1, z2 - z1)
        # Quadruple angle: perpendicular edges fall on the same direction
        a = math.atan2(z2 - z1, x2 - x1) * 4
        sx += L * math.cos(a)
        sy += L * math.sin(a)
    return math.atan2(sy, sx) / 4


def _seg_dist(U, Y, W, p0, p1):
    """Return the distance from every cell to the 3D line segment p0-p1.

    U, Y and W are arrays of the same shape."""
    d = np.array(p1, dtype=float) - np.array(p0, dtype=float)
    L2 = float((d * d).sum()) or 1.0
    t = (((U - p0[0]) * d[0] + (Y - p0[1]) * d[1] + (W - p0[2]) * d[2]) / L2).clip(0, 1)
    return np.sqrt((U - p0[0] - t * d[0]) ** 2 + (Y - p0[1] - t * d[1]) ** 2 + (W - p0[2] - t * d[2]) ** 2)


def gondola_colour(k):
    """Return the color of gondola k (k=0 at the top, counted counterclockwise toward the left):
    red at the top, orange and yellow on the left, green at the bottom, blue on the right."""
    if k in TRANSPARENT:
        return CLEAR
    c = COLOURS[int(k * len(COLOURS) / N_GONDOLA) % len(COLOURS)]
    return ("minecraft:%s_wool" % c, "minecraft:%s_stained_glass" % c)


class MiramarWheel(Attraction):
    height_m = 100.0
    margin = 12
    MALL = "way/155816458"

    def __init__(self, item):
        super().__init__(item)
        node = next((f for f in self.features if f.get("main") and f.get("point")), None)
        self.hub_xz = tuple(node["point"]) if node else tuple(self.center())
        f = self.feature(self.MALL)
        self.mall = max(f["outer"], key=len) if f and f.get("outer") else None
        ang = axis_angle(self.mall) if self.mall else 0.0
        self.angle = ang
        c, s = math.cos(ang), math.sin(ang)
        # Viewpoint: on the street VIEW_M meters south (+v) of the wheel
        self.view_xz = (self.hub_xz[0] - VIEW_M * s, self.hub_xz[1] + VIEW_M * c)

    def outline(self):
        return self.mall or super().outline()

    def bbox(self):
        x0, z0, x1, z1 = super().bbox()
        vx, vz = self.view_xz
        return (min(x0, int(vx) - 8), min(z0, int(vz) - 8), max(x1, int(vx) + 8), max(z1, int(vz) + 8))

    # ---------------------------------------------------------------- Planning
    def plan(self, site):
        hx, hz = self.hub_xz
        ang = self.angle
        if self.mall:
            xs = [p[0] for p in self.mall]
            zs = [p[1] for p in self.mall]
            mx, mz = sum(xs) / len(xs), sum(zs) / len(zs)
            ext = max(max(xs) - min(xs), max(zs) - min(zs)) / 2 + 20
        else:
            mx, mz, ext = hx, hz - 40, 90
        self.fr = fr = Frame(mx, mz, ang, ext)
        self.mask = fr.polygon(self.mall) if self.mall else fr.box(70, 50, *fr.local(int(hx), int(hz) - 45))
        self.g0 = site.level(fr, self.mask)
        # The wheel's own coordinates: u along the wheel plane, v along the axle
        self.wf = Frame(hx, hz, ang, 40)
        self._zones()
        # Grading in build() looks up the ground, and cli discards the terrain distance
        # field after plan_all, so every cell needed is looked up here first (Site caches
        # them) to be available at build time.
        site.grid(self.fr, self.mask)
        self.site = site
        g0 = self.g0
        # Default viewpoint: on the street to the south, looking at the middle of the wheel
        vx, vz = (int(math.floor(c)) for c in self.view_xz)
        vy = site.g(vx, vz) + 1
        self.view_ground = vy - 1
        yaw, pitch = kit.look(vx, vy, vz, hx, g0 + HUB - 8, hz)
        # Top: inside the highest gondola
        top = self._gondolas()[0]
        gx, gy, gz = top["cell"][0], top["y_top"] - 2, top["cell"][1]
        self._spots = [
            Spot("", vx, vy, vz, yaw, pitch, self.name_zh, self.name_en),
            Spot("top", gx, gy, gz, round(self.wf.yaw(0, 1), 1), 15.0, "摩天輪頂端車廂", "Top gondola"),
        ]

    def _zones(self):
        """Mall massing: the roof height of every cell (relative to g0) and its roof material."""
        fr, m = self.fr, self.mask
        U, V = fr.U, fr.V
        hu, hv = fr.local(int(math.floor(self.hub_xz[0])), int(math.floor(self.hub_xz[1])))
        um = U[m]
        vm = V[m]
        u0, u1, v0, v1 = float(um.min()), float(um.max()), float(vm.min()), float(vm.max())
        H = np.zeros(fr.shape)
        roof = np.zeros(fr.shape, dtype=np.int8)          # 0 flat roof, 1 pitched copper roof
        H[m] = 20
        west = m & (U < hu - 40)                          # West wing: wedge-shaped roof
        north = m & (V < v0 + 50)
        tower = north & (U > hu + 12)                     # Northeast IMAX building
        # 5th-floor deck under the wheel
        deck = m & ~west & ~tower & (np.abs(U - hu) <= 34) & (V >= v1 - 34)
        # Boarding platform: the wheel's legs land outside the
        # outline, so the deck extends further south
        wu, wv = self.wf.U, self.wf.V
        st = self._on(self.wf, (np.abs(wu) <= LEG_U + 3) & (wv >= -LEG_W - 3) & (wv <= LEG_W + 2))
        deck |= st
        self.mask = m = m | st
        wave = m & ~west & ~tower & ~deck                 # Everything else: wavy pale green roof
        # The ridge of the wedge is 10 m north of the south end
        vs = v1 - 10
        t = ((V - v0) / max(1.0, vs - v0)).clip(0, 1)
        wedge = np.where(V <= vs, 16 + 20 * t, 36 - 6 * ((V - vs) / 10.0).clip(0, 1))
        H[west] = wedge[west]
        roof[west] = 1
        H[tower] = 48
        H[deck] = DECK_Y
        H[wave] = (22 + 3 * np.sin(2 * math.pi * (U - u0) / 24.0) + 1.5 * np.cos(2 * math.pi * (V - v0) / 30.0))[wave]
        roof[wave] = 1
        self.H, self.roof = H, roof
        self.parts = dict(west=west, tower=tower, deck=deck, wave=wave)
        self.u_west, self.v_south = u0, v1

    def _on(self, other, mask2):
        """Map a mask on another Frame to a mask on the mall Frame (the same world cells)."""
        out = self.fr.empty()
        fr = self.fr
        for x, z in other.cells(mask2):
            i, j = z - fr.z0, x - fr.x0
            if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1]:
                out[i, j] = True
        return out

    def _gondolas(self):
        """Return the 48 gondolas: pivot position, the cell it falls in, the y of the gondola roof,
        and color. k=0 is at the top, counted counterclockwise (toward the west)."""
        wf, hub = self.wf, self.g0 + HUB
        out = []
        for k in range(N_GONDOLA):
            th = math.pi / 2 + 2 * math.pi * k / N_GONDOLA
            # Counterclockwise as seen from the south: k=1 is at the top, slightly west (-u)
            pu = RP * math.cos(th)
            py = RP * math.sin(th)
            out.append(dict(k=k, th=th, cell=wf.cell(pu, 0.0), y_top=hub + int(round(py)),
                            colour=gondola_colour(k), pu=pu))
        return out

    # ---------------------------------------------------------------- Build
    def build(self, w):
        p = Painter(w, self.fr)
        self._mall(p, w)
        self._station(w)
        self._wheel(w)
        self._view(w)

    # ---- Mall ----
    def _mall(self, p, w):
        fr, g0, m, H = self.fr, self.g0, self.mask, self.H
        Hi = np.rint(H).astype(int)
        self.site.prepare(w, fr, m, g0, top=FLOOR, clear=4)
        inner = erode(m, 1)
        # Floor slabs every 6 m, up to just below each roof
        for y in range(6, 48, 6):
            p.layer(inner & (Hi > y + 1), g0 + y, FLOOR)
        # Outer walls of each zone: its own perimeter from the ground up to just below its own roof;
        # a brown band every 5 m
        X, Z = fr.X, fr.Z
        s = w.set
        outer_ring = ring(m)
        for part in self.parts.values():
            rg = ring(part) | (part & outer_ring)
            for i, j in zip(*np.nonzero(rg)):
                x, z, top = int(X[i, j]), int(Z[i, j]), int(Hi[i, j])
                for y in range(1, top):
                    blk = STRIPE if y % 5 == 0 else STONE_WALL
                    s(x, g0 + y, z, blk)
        # Ground-floor shops: glass in the perimeter from 1 to
        # 4 m, and a pale green canopy at 5 m projecting 2 m
        shop = outer_ring & ((fr.X + fr.Z) % 7 != 0)
        p.fill(shop, g0 + 1, g0 + 4, SHOP_GLASS)
        canopy = dilate(m, 2) & ~m
        p.layer(canopy, g0 + 5, COPPER_SLAB)
        # Roofs: flat roofs are paved with a parapet; pitched and wavy roofs are pale green metal
        flat = m & (self.roof == 0)
        p.fill(flat, g0 + Hi, g0 + Hi, DECK)
        for part in ("tower",):
            pr = self.parts[part]
            p.fill(ring(pr), g0 + Hi + 1, g0 + Hi + 1, STONE_WALL)
        slope = m & (self.roof == 1)
        p.heightfield(slope, g0, H, COPPER, shell=2)
        p.heightfield(slope, g0, H, COPPER, shell=1, slab=COPPER_SLAB)
        # Large red arched gateway in the west wall (under the ridge at the south end)
        U, V = fr.U, fr.V
        wr = ring(m) & (U < self.u_west + 1.5)
        vc = self.v_south - 22
        for i, j in zip(*np.nonzero(wr & (np.abs(V - vc) <= 9))):
            dv = float(V[i, j] - vc)
            x, z = int(X[i, j]), int(Z[i, j])
            for y in range(1, 17):
                r = math.hypot(dv, max(0.0, y - 8.0))
                if r <= 7.0:
                    s(x, g0 + y, z, ARCH_GLASS)
                elif r <= 8.8:
                    s(x, g0 + y, z, ARCH)
        # Large arched window in the west wall of the IMAX building (the face seen from the
        # northwest in the photos)
        tw = self.parts["tower"]
        wr2 = ring(tw) & (U < U[tw].min() + 1.5)
        if wr2.any():
            vc3 = float(V[wr2].mean())
            for i, j in zip(*np.nonzero(wr2 & (np.abs(V - vc3) <= 9))):
                dv = float(V[i, j] - vc3)
                x, z = int(X[i, j]), int(Z[i, j])
                for y in range(24, 46):
                    r = math.hypot(dv, max(0.0, y - 37.0))
                    if r <= 7.0:
                        s(x, g0 + y, z, GLASS_ARCH)
                    elif r <= 8.5:
                        s(x, g0 + y, z, EMBLEM)
        # Circular emblem on the east wall of the IMAX building
        er = ring(tw) & (U > U[tw].max() - 1.5)
        if er.any():
            vc2 = float(V[er].mean())
            for i, j in zip(*np.nonzero(er)):
                x, z = int(X[i, j]), int(Z[i, j])
                for y in range(20, 46):
                    r = math.hypot(float(V[i, j]) - vc2, y - 34.0)
                    if 8.0 <= r <= 9.2:
                        s(x, g0 + y, z, EMBLEM)
        # Signboard
        sx, sz = fr.cell(self.u_west - 1.0, vc - 11)
        fx, fz = _vec(fr.facing(-1, 0))
        w.sign(sx, g0 + 3, sz, ["美麗華百樂園", "Miramar", "Entertainment Park", ""],
               facing=(fx, fz), wood="birch", kind="wall", glow=True, color="red")

    # ---- Boarding platform ----
    def _station(self, w):
        wf, g0 = self.wf, self.g0
        p = Painter(w, wf)
        y = g0 + DECK_Y
        plat = wf.rect(-LEG_U - 3, LEG_U + 3, -LEG_W - 3, LEG_W + 2)
        p.layer(plat, y, DECK)
        for sg in (1, -1):
            roof = wf.rect(-9, 9, 3 if sg > 0 else -7.5, 7 if sg > 0 else -3)
            p.layer(roof, y + 5, COPPER_SLAB)
            for cu in (-8.5, 8.5):
                for cv in ((3.5, 6.5) if sg > 0 else (-7, -3.5)):
                    x, z = wf.cell(cu, cv)
                    for yy in range(y + 1, y + 5):
                        w.set(x, yy, z, STEEL)

    # ---- Ferris wheel ----
    def _wheel(self, w):
        wf, hub = self.wf, self.g0 + HUB
        U, W = wf.U, wf.V
        X, Z = wf.X, wf.Z
        near = np.abs(W) <= 12
        s = w.set
        step = 2 * math.pi / N_SPOKE
        gstep = 2 * math.pi / N_GONDOLA
        base_y = self.g0 + DECK_Y
        legs = []
        for su in (1, -1):
            for sw in (1, -1):
                legs.append(((0.0, 0.0, sw * LEG_W), (su * LEG_U, base_y - hub, sw * LEG_W)))
        ty = self.g0 + TIE_Y - hub
        tie_u = LEG_U * (ty - 0) / (base_y - hub)
        ties = [((-tie_u, ty, sw * LEG_W), (tie_u, ty, sw * LEG_W)) for sw in (1, -1)]
        for y in range(base_y, hub + int(RIM_OUT) + 3):
            dy = float(y - hub)
            R = np.hypot(U, dy)
            TH = np.arctan2(dy, U)
            aw = np.abs(W)
            blk = np.full(U.shape, "", dtype=object)
            # Legs and cross-braces
            for (p0, p1), rad in [(l, LEG_R) for l in legs] + [(t, 0.7) for t in ties]:
                blk[near & (_seg_dist(U, dy, W, p0, p1) <= rad)] = STEEL
            # Spokes: front and rear faces, slanting from the axle (±4.5) to the rim (±2)
            for f, off in ((1, 0.0), (-1, step / 2)):
                ws = f * (HUB_W - (HUB_W - RIM_W) * ((R - HUB_R) / (RIM_IN - HUB_R)).clip(0, 1))
                dth = (TH - off + step / 2) % step - step / 2
                lat = R * np.abs(np.sin(dth))
                on_face = np.abs(W - ws) <= 0.6
                blk[near & on_face & (R >= HUB_R) & (R <= RIM_IN + 0.2) & (lat <= 0.5)] = SPOKE
                for rr in RINGS:
                    blk[near & on_face & (np.abs(R - rr) <= 0.5)] = RIM
            # Rims (front and rear), the thin red outer ring, and the cross-beams and hangers at the
            # gondola positions
            blk[(R >= RIM_IN) & (R <= RIM_OUT) & (np.abs(aw - RIM_W) <= 0.55)] = RIM
            blk[(R > RIM_OUT) & (R <= RIM_OUT + 1.0) & (aw <= 0.55)] = RING2
            gd = (TH - math.pi / 2 + gstep / 2) % gstep - gstep / 2
            glat = R * np.abs(np.sin(gd))
            blk[(glat <= 0.5) & (R >= RIM_IN) & (R <= RIM_OUT) & (aw <= RIM_W + 0.5)] = RIM
            blk[(glat <= 0.5) & (R > RIM_OUT) & (R <= RP + 0.3) & (np.abs(aw - RIM_W) <= 0.55)] = STEEL
            # Axle
            blk[(R <= HUB_R) & (aw <= HUB_W)] = STEEL
            blk[(R <= 1.6) & (aw <= AXLE_W)] = AXLE
            for i, j in zip(*np.nonzero(blk != "")):
                s(int(X[i, j]), y, int(Z[i, j]), blk[i, j])
        # Gondolas: hanging below the pivots, 3 × 3 × 4 (floor, two rows of windows, roof), with the
        # center cell empty
        eu = _vec(kit.cardinal(*wf.dir(1, 0)))
        ev = _vec(kit.cardinal(*wf.dir(0, 1)))
        for g in self._gondolas():
            (gx, gz), yt = g["cell"], g["y_top"]
            solid, glass = g["colour"]
            for a in (-1, 0, 1):
                for b in (-1, 0, 1):
                    x, z = gx + a * eu[0] + b * ev[0], gz + a * eu[1] + b * ev[1]
                    s(x, yt, z, solid)
                    s(x, yt - GH + 1, z, solid)
                    for yy in range(yt - GH + 2, yt):
                        s(x, yy, z, AIR if (a, b) == (0, 0) else glass)

    # ---- A small patch of sidewalk paving under the viewpoint ----
    def _view(self, w):
        vx, vz = (int(math.floor(c)) for c in self.view_xz)
        gy = self.view_ground
        for dx in range(-4, 5):
            for dz in range(-4, 5):
                w.set(vx + dx, gy, vz + dz, PAVE)
                for yy in range(gy + 1, gy + 4):
                    w.set(vx + dx, yy, vz + dz, AIR)

    # ---------------------------------------------------------------- Plaque
    def plaque(self):
        return [self.name_zh, self.name_en, "2004 年啟用 頂高 100 m", "輪徑 70 m 48 個車廂"]

    def plaque_en(self):
        return ["Opened in 2004, 100 m high", "2004, 100 m high"]


def _vec(name):
    return {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}[name]


BUILDS = {"miramar_wheel": MiramarWheel}
