#!/usr/bin/env python3
"""Shared tools for attraction buildings: local frames, the keep-out guard, site grading,
plan masks and roof heightfields.

Each attraction is an Attraction (see the notes in __init__.py). This module holds the
parts they all use, so the modules for Taipei 101, the Chiang Kai-shek Memorial Hall and
the city gates describe only what the building looks like:

  Frame     The building's own coordinate system. Most OSM outlines are not aligned
            north-south (the Presidential Office Building is 1.6° off, the Sun Yat-sen
            Memorial Hall 2°), so a rectangle drawn directly on the world grid comes out
            skewed. Shapes are drawn in local coordinates (u, v), and each **world cell**
            is mapped back into local coordinates and tested (inverse rasterization), so
            no cell is missed at any angle. The u axis follows angle; the v axis is u
            turned 90° toward +z (at angle=0, u = east and v = south, matching world x
            and z).
  Masks     2D boolean arrays [z][x] over a Frame. rect / chamfer / ellipse / ngon /
            polygon create them; ring / erode / dilate outline and shrink them.
  Painter   Writes masks as blocks: fill (a y range per cell), walls (the outer ring,
            with windows) and heightfield (curved surfaces such as roofs and dougong
            brackets). Every write goes through the Guard.
  Roofs     Return heightfields (float arrays): hip (wudian), hip_gable (xieshan),
            pyramid (cuanjian: square, octagonal, round) and gable (flush or overhanging
            gable). The concave curve of a Chinese roof comes from the profile exponent,
            the upturned corners from lift.
  Site      The site: looks up ground height (the built terrain supplied by cli), sets
            the floor level and grades the ground (fills low cells, cuts high ones).
  Guard     The keep-out guard: cells occupied by MRT exit kiosks, stair shafts,
            underground malls and viaducts are never written (the keep function cli
            computes from landmarks and segments). Attractions are built after all of
            those; without this check, the podium of the Shin Kong Life Tower would seal
            the exits in front of the station.

Coordinates follow the save: x = east, z = south, y = up; block (x, z) is centered at
(x+.5, z+.5). This layer only calls BlockSink.set() and SignSink.sign() and touches no
files.
"""
import math
from collections import namedtuple

import numpy as np

from mrt.domain import geometry as shapes

AIR = "minecraft:air"

# A datapack teleport point: the block the feet are in (x, y, z) and the view direction
# (yaw 0 = south, 90 = west, ±180 = north, -90 = east; a positive pitch looks down). zh and
# en are the labels on the dialog button. key is part of the function path ("" = the
# default viewpoint sight/<id>, "top" -> sight/<id>_top).
Spot = namedtuple("Spot", "key x y z yaw pitch zh en")


def sight_fn(aid, key=""):
    """Path of an attraction's teleport function (without the namespace): "sight/taipei101",
    "sight/taipei101_top". Signs inside attractions (such as the 89th-floor observatory
    sign in the Taipei 101 lobby) and the datapack (ride_plan) both take it from here. It
    follows the same convention as network.ride_fn: the command on the sign and the file
    name in the datapack are two ends of one agreement."""
    return "sight/%s%s" % (aid, ("_" + key) if key else "")


def yaw_of(fx, fz):
    """Direction (dx, dz) -> Minecraft yaw (degrees): 0 = south (+z), 90 = west,
    ±180 = north, -90 = east."""
    return math.degrees(math.atan2(-fx, fz))


def look(x, y, z, tx, ty, tz, eye=1.62):
    """(yaw, pitch) for standing at (x, y, z) (the block the feet are in) and looking at
    (tx, ty, tz)."""
    dx, dz = tx - (x + 0.5), tz - (z + 0.5)
    dy = ty - (y + eye)
    yaw = yaw_of(dx, dz)
    pitch = -math.degrees(math.atan2(dy, math.hypot(dx, dz)))
    return round(yaw, 1), round(max(-60.0, min(60.0, pitch)), 1)


CARDINAL = {(0, -1): "north", (0, 1): "south", (1, 0): "east", (-1, 0): "west"}


def cardinal(dx, dz):
    """Any direction -> the name of the nearest cardinal direction (the facing of stairs,
    doors and wall signs)."""
    if abs(dx) >= abs(dz):
        return "east" if dx > 0 else "west"
    return "south" if dz > 0 else "north"


# ---------------------------------------------------------------- Guard

class Guard:
    """Wraps a BlockSink / SignSink: cells where keep(x, y, z) is true are not written. Counts
    how many writes it blocked."""

    def __init__(self, w, keep=None):
        self.w = w
        self.keep = keep
        self.dropped = 0

    def set(self, x, y, z, block):
        if self.keep is not None and self.keep(x, y, z):
            self.dropped += 1
            return
        self.w.set(x, y, z, block)

    def sign(self, x, y, z, lines, **kw):
        if self.keep is not None and self.keep(x, y, z):
            self.dropped += 1
            return
        self.w.sign(x, y, z, lines, **kw)


# ---------------------------------------------------------------- Frame and masks

class Frame:
    """Local coordinate frame: origin (cx, cz), u axis along angle (radians, measured from +x
    toward +z).

    The grid covers the bounding rectangle of the square |u|, |v| <= extent once rotated
    into the world. U and V are the local coordinates of each world cell center (2D arrays
    [z][x]).
    """

    def __init__(self, cx, cz, angle, extent):
        self.cx, self.cz, self.angle = float(cx), float(cz), float(angle)
        self.c, self.s = math.cos(self.angle), math.sin(self.angle)
        r = float(extent) * (abs(self.c) + abs(self.s)) + 2
        self.x0, self.z0 = int(math.floor(self.cx - r)), int(math.floor(self.cz - r))
        self.x1, self.z1 = int(math.ceil(self.cx + r)), int(math.ceil(self.cz + r))
        xs = np.arange(self.x0, self.x1 + 1)
        zs = np.arange(self.z0, self.z1 + 1)
        self.X, self.Z = np.meshgrid(xs, zs)                 # [z][x]
        dx, dz = self.X + 0.5 - self.cx, self.Z + 0.5 - self.cz
        self.U = dx * self.c + dz * self.s
        self.V = -dx * self.s + dz * self.c
        self.shape = self.X.shape

    # ---- Coordinate conversion ----
    def world(self, u, v):
        """Local (u, v) -> world (x, z) (floats)."""
        return (self.cx + u * self.c - v * self.s, self.cz + u * self.s + v * self.c)

    def cell(self, u, v):
        """Local (u, v) -> the world cell (x, z) containing that point."""
        x, z = self.world(u, v)
        return int(math.floor(x)), int(math.floor(z))

    def local(self, x, z):
        """Center of the world **cell** (x, z) -> local (u, v) (0.5 is added first).
        OSM outline vertices are points, not cells; convert points with local_pt()."""
        dx, dz = x + 0.5 - self.cx, z + 0.5 - self.cz
        return dx * self.c + dz * self.s, -dx * self.s + dz * self.c

    def local_pt(self, x, z):
        """World **point** (x, z) (such as an OSM vertex) -> local (u, v), without adding
        0.5."""
        dx, dz = x - self.cx, z - self.cz
        return dx * self.c + dz * self.s, -dx * self.s + dz * self.c

    def dir(self, du, dv):
        """Local direction -> world direction (dx, dz) (a unit vector)."""
        return du * self.c - dv * self.s, du * self.s + dv * self.c

    def facing(self, du, dv):
        """Local direction -> the nearest cardinal direction (stairs, doors, signs)."""
        return cardinal(*self.dir(du, dv))

    def yaw(self, du, dv):
        return yaw_of(*self.dir(du, dv))

    # ---- Masks ----
    def empty(self):
        return np.zeros(self.shape, dtype=bool)

    def rect(self, u0, u1, v0, v1):
        return (self.U >= u0) & (self.U <= u1) & (self.V >= v0) & (self.V <= v1)

    def box(self, a, b, du=0.0, dv=0.0):
        """Rectangle centered at (du, dv) with half-length a (along u) and half-width b
        (along v)."""
        return self.rect(du - a, du + a, dv - b, dv + b)

    def chamfer(self, a, b, c, du=0.0, dv=0.0):
        """Rectangle with an isosceles right triangle of leg c cut from each corner (the
        corners of the Shin Kong Life Tower and Taipei 101)."""
        u, v = np.abs(self.U - du), np.abs(self.V - dv)
        return (u <= a) & (v <= b) & (u + v <= a + b - c)

    def ellipse(self, a, b, du=0.0, dv=0.0):
        return ((self.U - du) / a) ** 2 + ((self.V - dv) / b) ** 2 <= 1.0

    def ngon_radius(self, n, rot=0.0, du=0.0, dv=0.0):
        """"Polygon radius" of a regular n-gon: max_k (u cos φk + v sin φk). A value <= r lies
        inside the polygon with apothem r. At rot=0 the normal of the first side points
        along +u (one side of an octagon faces the u axis squarely)."""
        u, v = self.U - du, self.V - dv
        out = None
        for k in range(n):
            ph = rot + 2 * math.pi * k / n
            d = u * math.cos(ph) + v * math.sin(ph)
            out = d if out is None else np.maximum(out, d)
        return out

    def ngon(self, n, r, rot=0.0, du=0.0, dv=0.0):
        return self.ngon_radius(n, rot, du, dv) <= r

    def polygon(self, poly):
        """Polygon in world coordinates (an OSM outline) -> mask. A cell counts only if its
        center is inside the polygon (as in geometry.poly_cells)."""
        m = self.empty()
        for x, z in shapes.poly_cells(poly):
            i, j = z - self.z0, x - self.x0
            if 0 <= i < self.shape[0] and 0 <= j < self.shape[1]:
                m[i, j] = True
        return m

    def cells(self, mask):
        """Mask -> [(x, z)]."""
        return list(zip(self.X[mask].tolist(), self.Z[mask].tolist()))


def erode(mask, n=1):
    """Shrink by n cells (4-neighborhood)."""
    m = mask.copy()
    for _ in range(n):
        e = m.copy()
        e[1:, :] &= m[:-1, :]
        e[:-1, :] &= m[1:, :]
        e[:, 1:] &= m[:, :-1]
        e[:, :-1] &= m[:, 1:]
        e[0, :] = e[-1, :] = False
        e[:, 0] = e[:, -1] = False
        m = e
    return m


def dilate(mask, n=1):
    """Grow by n cells (4-neighborhood)."""
    m = mask.copy()
    for _ in range(n):
        d = m.copy()
        d[1:, :] |= m[:-1, :]
        d[:-1, :] |= m[1:, :]
        d[:, 1:] |= m[:, :-1]
        d[:, :-1] |= m[:, 1:]
        m = d
    return m


def ring(mask, width=1):
    """Outer ring (width cells wide): cells in the mask that are gone after shrinking it
    by width cells."""
    return mask & ~erode(mask, width)


def depth(mask, limit=200):
    """Number of cells from each cell to the mask boundary (outer ring = 1, 4-neighborhood
    distance). A hip roof over an arbitrary plan uses it as the height."""
    d = np.zeros(mask.shape, dtype=np.int32)
    cur = mask.copy()
    k = 0
    while cur.any() and k < limit:
        k += 1
        d[cur] = k
        cur = erode(cur)
    return d


# ---------------------------------------------------------------- Roof heightfields
#
# All return float arrays of height above the eaves (eaves = 0); the caller adds the y of
# the eaves. The concave curve of a Chinese roof: with profile > 1 the slope is steep near
# the ridge and gentle near the eaves (the juzhe curve). lift is how far the four eave
# corners turn up (meters); corner is how far the upturn extends back from each corner.

def hip(fr, a, b, rise, profile=1.0, lift=0.0, corner=None, du=0.0, dv=0.0):
    """Hip roof (wudian, four slopes): rectangle |u|<=a, |v|<=b, with the ridge along the
    long side."""
    u, v = np.abs(fr.U - du), np.abs(fr.V - dv)
    short = min(a, b)
    d = np.minimum(a - u, b - v).clip(0, None)            # Distance to the nearest eave
    h = rise * (d / short).clip(0, 1) ** profile
    return h + _lift(u, v, a, b, lift, corner, d)


def hip_gable(fr, a, b, rise, gable_in, profile=1.0, lift=0.0, corner=None, du=0.0, dv=0.0):
    """Xieshan (hip-and-gable) roof: the long slopes (the two slopes along v) run all the way
    to the ridge. Each end starts with a short hipped slope, and at |u| = a - gable_in a
    triangular gable pediment rises (the heightfield jumps there to the height of the long
    slopes)."""
    u, v = np.abs(fr.U - du), np.abs(fr.V - dv)
    long_ = rise * ((b - v) / b).clip(0, 1) ** profile     # The two long slopes
    end = rise * ((a - u) / b).clip(0, 1) ** profile        # Short end slopes, same pitch as the long ones
    h = np.where(u > a - gable_in, np.minimum(long_, end), long_)
    d = np.minimum(a - u, b - v).clip(0, None)
    return h + _lift(u, v, a, b, lift, corner, d)


def gable(fr, a, b, rise, profile=1.0, du=0.0, dv=0.0):
    """Gable roof (yingshan, flush gable): ridge along u, with vertical gable walls at both
    ends."""
    v = np.abs(fr.V - dv)
    return rise * ((b - v) / b).clip(0, 1) ** profile


def pyramid(fr, r, rise, sides=4, rot=0.0, profile=1.0, lift=0.0, du=0.0, dv=0.0):
    """Pyramidal roof (cuanjian): sides=4 square, 8 octagonal (Chiang Kai-shek Memorial Hall),
    0 conical. r is the apothem at the eaves (the radius for a circle)."""
    if sides:
        rr = fr.ngon_radius(sides, rot, du, dv)
    else:
        rr = np.hypot(fr.U - du, fr.V - dv)
    d = (r - rr).clip(0, None)
    h = rise * (d / r).clip(0, 1) ** profile
    if lift and sides:
        # Eave corners: the closer to a polygon vertex (between the normals of two sides),
        # the higher the upturn.
        ang = np.arctan2(fr.V - dv, fr.U - du) - rot
        k = (ang / (2 * math.pi / sides)) % 1.0              # 0 and 1 are side normals, 0.5 a vertex
        near_vertex = (1 - np.abs(k - 0.5) * 2) ** 4
        near_eave = (1 - d / (0.35 * r)).clip(0, 1) ** 2
        h = h + lift * near_vertex * near_eave
    return h


def _lift(u, v, a, b, lift, corner, d):
    """Upturn of the four eave corners: higher the closer to a corner along the eaves,
    affecting only the band near the eaves."""
    if not lift:
        return 0.0
    c = corner or 0.35 * min(a, b)
    # Measure closeness to a corner along the nearest eave: u near a long eave (the v
    # side), v near a short eave. Taking the max of both directions would count the middle
    # of a long eave (v≈b) as near a corner too, and the whole eave would turn up.
    near_long = (b - v) <= (a - u)
    along = np.where(near_long, ((u - (a - c)) / c).clip(0, 1), ((v - (b - c)) / c).clip(0, 1))
    near = (1 - d / c).clip(0, 1)
    return lift * along ** 2 * near


# ---------------------------------------------------------------- Painter

class Painter:
    """Writes masks as blocks on a Frame. w is a BlockSink (already wrapped in a Guard)."""

    def __init__(self, w, frame):
        self.w, self.fr = w, frame

    def set(self, x, y, z, block):
        self.w.set(int(x), int(y), int(z), block)

    def at(self, u, v, y, block):
        """The cell containing the point at local coordinates (u, v)."""
        x, z = self.fr.cell(u, v)
        self.w.set(x, int(y), z, block)

    def fill(self, mask, y0, y1, block):
        """Stack every cell in the mask from y0 to y1 (inclusive). y0 and y1 may be integers
        or arrays with the Frame's shape."""
        X, Z = self.fr.X[mask], self.fr.Z[mask]
        Y0 = np.broadcast_to(np.asarray(y0), self.fr.shape)[mask]
        Y1 = np.broadcast_to(np.asarray(y1), self.fr.shape)[mask]
        s = self.w.set
        for x, z, a, b in zip(X.tolist(), Z.tolist(), np.rint(Y0).astype(int).tolist(),
                              np.rint(Y1).astype(int).tolist()):
            for y in range(a, b + 1):
                s(x, y, z, block)

    def layer(self, mask, y, block):
        self.fill(mask, y, y, block)

    def clear(self, mask, y0, y1):
        self.fill(mask, y0, y1, AIR)

    def walls(self, mask, y0, y1, wall, window=None, every=3, sill=1, head=1, storey=None):
        """Walls on the outer ring: y0..y1. Given window, windows are cut: on each storey
        (storey blocks per storey; by default the whole range is one storey), from sill
        blocks above the floor to head blocks below the ceiling, leaving one block of wall
        every `every` cells along the ring as a mullion."""
        rg = ring(mask)
        X, Z = self.fr.X[rg].tolist(), self.fr.Z[rg].tolist()
        for x, z in zip(X, Z):
            for y in range(int(y0), int(y1) + 1):
                blk = wall
                if window is not None:
                    k = (y - y0) % storey if storey else (y - y0)
                    top = (storey or (y1 - y0 + 1)) - 1
                    if sill <= k <= top - head and (x + z) % every != 0:
                        blk = window
                self.w.set(x, y, z, blk)

    def heightfield(self, mask, base, h, block, under=None, shell=None, slab=None):
        """Stack each cell from base to base + h (h is a float array).

        shell=k: keep only the top k blocks (the roof is a shell, hollow inside). under:
        the material of the block below the shell (such as the dougong color under the
        eaves). slab="minecraft:xxx_slab": where the fractional part is >= 0.5, add a slab
        on top, so the slope does not step one whole block at a time."""
        X, Z = self.fr.X[mask].tolist(), self.fr.Z[mask].tolist()
        B = np.broadcast_to(np.asarray(base), self.fr.shape)[mask]
        H = np.asarray(h)[mask] if np.ndim(h) else np.full(len(X), float(h))
        top = B + H
        s = self.w.set
        for x, z, b, t in zip(X, Z, np.rint(B).astype(int).tolist(), top.tolist()):
            ti = int(math.floor(t))
            lo = b if shell is None else max(b, ti - shell + 1)
            for y in range(lo, ti + 1):
                s(x, y, z, block)
            if under is not None and lo - 1 >= b:
                s(x, lo - 1, z, under)
            if slab is not None and t - ti >= 0.5:
                s(x, ti + 1, z, slab + "[type=bottom]")

    def columns(self, pts, radius, y0, y1, block, square=False):
        """A row of columns: pts are local coordinates [(u, v)], each column of radius
        radius (round; square=True for square columns)."""
        for u, v in pts:
            cx, cz = self.fr.world(u, v)
            r = radius
            for x in range(int(math.floor(cx - r - 1)), int(math.ceil(cx + r + 1))):
                for z in range(int(math.floor(cz - r - 1)), int(math.ceil(cz + r + 1))):
                    du, dv = self.fr.local(x, z)
                    du, dv = du - u, dv - v
                    inside = (max(abs(du), abs(dv)) <= r) if square else (du * du + dv * dv <= r * r + 0.25)
                    if inside:
                        for y in range(int(y0), int(y1) + 1):
                            self.w.set(x, y, z, block)


# ---------------------------------------------------------------- Site

class Site:
    """The site: ground height and grading.

    ground(x, z), supplied by cli, is the y of the ground block built in that cell (the same
    formula as terrain_chunk; outside the corridor it fades back to the superflat y64). keep
    is the keep-out zone (as in Guard).

    Look the ground up in plan() (site.grid(fr, mask) fetches a whole area at once).
    build() is called once per region, and looking up the ground cell by cell in there is
    slow and makes build() depend on cli's terrain cache.
    """

    def __init__(self, ground, keep=None):
        self.ground = ground
        self.keep = keep
        self._cache = {}

    def g(self, x, z):
        k = (x, z)
        v = self._cache.get(k)
        if v is None:
            v = self._cache[k] = int(self.ground(x, z))
        return v

    def grid(self, fr, mask=None):
        """Ground y of every cell in the Frame (-999 outside mask)."""
        out = np.full(fr.shape, -999, dtype=np.int32)
        m = mask if mask is not None else np.ones(fr.shape, dtype=bool)
        for i, j in zip(*np.nonzero(m)):
            out[i, j] = self.g(int(fr.X[i, j]), int(fr.Z[i, j]))
        return out

    def level(self, fr, mask, how="median"):
        """The y for the ground-floor slab: the median ground height over the mask
        (how="max" takes the highest, so the building is not buried in a slope)."""
        g = self.grid(fr, mask)[mask]
        if len(g) == 0:
            return 64
        return int(np.max(g)) if how == "max" else int(np.round(np.median(g)))

    def prepare(self, w, fr, mask, y, fill="minecraft:stone", top="minecraft:grass_block", clear=24):
        """Grading: level the ground over the mask to y (top goes in the block at y). Ground
        below y is filled up with fill; ground above y is cut away and clear blocks above
        it are emptied (cutting back the slope). All writes go through w (the caller passes
        a Guard)."""
        g = self.grid(fr, mask)
        X, Z, G = fr.X[mask].tolist(), fr.Z[mask].tolist(), g[mask].tolist()
        for x, z, gy in zip(X, Z, G):
            for yy in range(min(gy, y) + 1, y):
                w.set(x, yy, z, fill)
            w.set(x, y, z, top)
            for yy in range(y + 1, max(gy, y) + 1 + (clear if gy > y else 0)):
                w.set(x, yy, z, AIR)


# ---------------------------------------------------------------- Attraction base class

class Attraction:
    """One attraction. Subclasses override plan() and build(); everything else has a default.

    Lifecycle (cli calls these in this order):
      1. __init__(item)          item is one entry of data/attractions.json (OSM outline,
                                 tags)
      2. bbox()                  World extent of the whole attraction (including its
                                 plaza), for bucketing and the terrain distance field
      3. plan(site)              Settle the design once the ground and keep-out zone are
                                 known: ground-floor level, doors, viewpoints
      4. build(w)                Write blocks; w is already wrapped in a Guard. Called once
                                 for each region the attraction spans (World discards
                                 blocks outside the current region)
      5. spots()                 Datapack teleport points (the first is the default
                                 viewpoint, key="")
      6. plaque()                The four lines of the attraction's plaque
      7. plaque_en()             English for the plaque's first fact (optional)
    """

    # Published height (meters, from the ground to the highest point); verify_attractions
    # compares against it.
    height_m = None
    margin = 12              # Blocks the bbox extends beyond the OSM outline (plaza, steps, eaves)
    # How far beyond the bbox real terrain is still generated (beyond that, cli's --fade band
    # fades back to the superflat y64). Hillside attractions need a larger value; otherwise
    # the hill behind the building is shaved into a ramp a few tens of meters behind it.
    terrain_margin = 48

    def __init__(self, item):
        self.item = item
        self.id = item["id"]
        self.name_zh = item["name_zh"]
        self.name_en = item["name_en"]
        self.features = item.get("features", [])
        self.g0 = None
        self._spots = []

    # ---- OSM data ----
    def feature(self, osm):
        return next((f for f in self.features if f["osm"] == osm), None)

    def mains(self):
        return [f for f in self.features if f.get("main")]

    def outline(self):
        """Outer ring of the main building (world coordinates). By default the first named
        element with an area; failing that, the building nearest the center with the
        largest area."""
        for f in self.mains():
            if f.get("outer") and f.get("area", 0) > 0:
                return max(f["outer"], key=lambda r: abs(_area(r)))
        blds = [f for f in self.features if f.get("outer") and "building" in f["tags"]]
        if not blds:
            return None
        f = min(blds, key=lambda f: f["dist"] - 0.001 * f["area"])
        return max(f["outer"], key=lambda r: abs(_area(r)))

    def center(self):
        return tuple(self.item["center"])

    # ---- Framework interface ----
    def bbox(self):
        pts = self.outline() or [self.center()]
        x0, z0, x1, z1 = shapes.bbox(pts)
        m = self.margin
        return (int(math.floor(x0)) - m, int(math.floor(z0)) - m,
                int(math.ceil(x1)) + m, int(math.ceil(z1)) + m)

    def plan(self, site):
        raise NotImplementedError

    def build(self, w):
        raise NotImplementedError

    def spots(self):
        return list(self._spots)

    def plaque(self):
        """The plaque's four lines: Chinese name, English name, and two facts in Chinese.
        The framework adds the nearest MRT station.
        The first line must not start with `出口` (verify_exits recognizes exit kiosks by
        it)."""
        return [self.name_zh, self.name_en, "", ""]

    def plaque_en(self):
        """The plaque's first fact in English, as candidates from fullest to shortest.
        plaque_lines prints the first that fits the sign (signage.fit), and the datapack
        shows the first. An empty list keeps the plaque's facts in Chinese only."""
        return []

    def top_y(self):
        """y of the highest point (available only after plan)."""
        if self.g0 is None or self.height_m is None:
            return None
        return self.g0 + int(round(self.height_m))


def _area(r):
    a = 0.0
    for i in range(len(r)):
        x1, z1 = r[i]
        x2, z2 = r[(i + 1) % len(r)]
        a += x1 * z2 - x2 * z1
    return a / 2


def principal_angle(poly):
    """Principal direction of a polygon (radians): the longest set of parallel sides. OSM
    building outlines use it to set the Frame's u axis."""
    best, ang = -1.0, 0.0
    n = len(poly)
    acc = {}
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        L = math.hypot(x2 - x1, z2 - z1)
        if L < 1e-6:
            continue
        a = math.atan2(z2 - z1, x2 - x1) % (math.pi / 2)    # Fold each set of orthogonal sides onto one angle
        k = int(round(math.degrees(a))) % 90
        acc[k] = acc.get(k, 0.0) + L
    for k, L in acc.items():
        if L > best:
            best, ang = L, math.radians(k)
    return ang
