#!/usr/bin/env python3
"""Underground mall generator: builds OSM underground passage centerlines into walkable malls.

Alignment cleanup (merging points, connected components, exit connectors) lives in
domain/concourse.py; this module only places the blocks. The first parameter w of
each build() is a ports.block_sink.BlockSink.

**Why everything is built on one level.** The OSM level tag is relative to each
mapped cluster's own datum, not an absolute floor: Taipei City Mall is tagged -2,
Station Front Metro Mall is tagged -2 but layer=-1, and Zhongshan Metro Mall is
tagged -1, yet all three are actually B1. This world's vertical budget also has
room for only one level: the ground surface is at y66 and the roof slab of the
Bannan Line station box at y61, which leaves exactly enough clearance for one
level. So passages are always built on B1, and the vertical differences are left
to the exit stairs and to the link stairs down to the concourse. This is a
trade-off, not an oversight.

**Why walls are built only after all floors are computed.** Passages cross at
junctions. If each segment built its own walls, the segment built first would seal
the junction: the corridors all look present, but you cannot walk through. So the
floor cells of every passage and mall are first computed as one set, and walls are
built only on the outer ring of that set.

Self-test: ./.venv/bin/python tests/test_concourse.py
"""
import math

from mrt.domain import concourse as CC

AIR    = "minecraft:air"
FLOOR  = "minecraft:white_concrete"          # Mall paving, kept distinct from the tunnel grays.
CEIL   = "minecraft:light_gray_concrete"     # Roof slab.
WALL   = "minecraft:smooth_sandstone"        # Shopfront partition walls.
STRUCT = "minecraft:deepslate_bricks"        # Structural lining, same material as the station box structure.
SHOP   = "minecraft:glass_pane"              # Shop windows.
STAIR  = "minecraft:smooth_stone"
SLAB   = "minecraft:smooth_stone_slab[type=bottom]"
BARS   = "minecraft:iron_bars"
LAMP   = "minecraft:sea_lantern"
RAIL   = "minecraft:light_gray_stained_glass_pane"   # Glass parapet of the skybridge.
EDGE   = "minecraft:light_gray_concrete"             # Outer edge of the skybridge deck.
PIER   = "minecraft:polished_andesite"               # Skybridge piers, same material as the viaduct.

HEAD = 3            # Clearance in blocks, counted up from the standing surface; the roof slab is at y+HEAD.
TILE = 128          # Tile edge length, so each object's bbox is small enough for bucketing to be useful.


# ---------- Rasterization ----------

def stroke(p0, p1, half_w):
    """Rasterize a centerline segment into floor cells. Half-width half_w gives a width of 2*half_w+1 meters."""
    (x0, z0), (x1, z1) = p0, p1
    n = int(max(abs(x1 - x0), abs(z1 - z0)))
    out = set()
    if n == 0:
        cx, cz = int(round(x0)), int(round(z0))
        for dx in range(-half_w, half_w + 1):
            for dz in range(-half_w, half_w + 1):
                out.add((cx + dx, cz + dz))
        return out
    ux, uz = (x1 - x0) / n, (z1 - z0) / n
    for t in range(n + 1):
        cx, cz = x0 + ux * t, z0 + uz * t
        for dx in range(-half_w, half_w + 1):
            for dz in range(-half_w, half_w + 1):
                if dx * dx + dz * dz <= half_w * half_w + half_w:
                    out.add((int(round(cx)) + dx, int(round(cz)) + dz))
    return out


def outer_ring(cells):
    """Return the outer ring (8-neighborhood) of a set of floor cells, which is where walls go.

    It uses the 8-neighborhood rather than the 4-neighborhood. Blocking only the four
    sides leaves a diagonal gap wherever two cells touch at a corner: the gap is
    invisible in a cross-section, but you can walk through it straight into the solid
    ground outside the passage.
    """
    ring = set()
    for x, z in cells:
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                c = (x + dx, z + dz)
                if c not in cells:
                    ring.add(c)
    return ring


# ---------- Horizontal level ----------

class Tile:
    """One floor tile of the underground mall, with its roof slab, outer walls and lighting.

    The whole underground mall is first computed as one set of cells and then cut into
    tiles, only so that each bbox is small enough to be bucketed into a region.
    Adjacent tiles have no wall between them, because the outer ring is computed for
    the whole mall.
    """

    def __init__(self, cells, ring, y, ceil_of, shopfront=True, bridge=False,
                 pier_to=None):
        self.cells = cells                  # {(x, z)} floor
        self.ring = ring                    # {(x, z)} outer walls
        self.y = int(y)                     # Standing surface.
        self.ceil_of = ceil_of              # {(x, z): roof slab y}
        self.shopfront = shopfront
        # bridge: this tile is a skybridge (the exit passage of an elevated or at-grade
        # station), so its outer edge is a glass parapet rather than a shopfront wall.
        # pier_to = {(x, z): ground y}: piers are built from those cells down to the ground.
        self.bridge = bool(bridge)
        self.pier_to = dict(pier_to) if pier_to else {}

    def bbox(self):
        xs = [c[0] for c in self.cells] + [c[0] for c in self.ring]
        zs = [c[1] for c in self.cells] + [c[1] for c in self.ring]
        return min(xs) - 1, min(zs) - 1, max(xs) + 1, max(zs) + 1

    def build(self, w):
        y = self.y
        for x, z in self.cells:
            cy = self.ceil_of.get((x, z), y + HEAD)
            w.set(x, y - 1, z, FLOOR)
            for yy in range(y, cy):
                w.set(x, yy, z, AIR)
            w.set(x, cy, z, CEIL)
            if x % 9 == 0 and z % 9 == 0:
                w.set(x, cy - 1, z, LAMP)
        for x, z in self.ring:
            cy = self.ceil_of.get((x, z))
            if cy is None:                  # The ring has no roof height of its own; use the neighbors'.
                cy = max((self.ceil_of.get((x + dx, z + dz), y + HEAD)
                          for dx in (-1, 0, 1) for dz in (-1, 0, 1)),
                         default=y + HEAD)
            if self.bridge:
                w.set(x, y - 1, z, EDGE)
                for yy in range(y, cy):
                    w.set(x, yy, z, RAIL if yy <= y + 2 else EDGE)
                w.set(x, cy, z, CEIL)
                continue
            w.set(x, y - 1, z, STRUCT)
            for yy in range(y, cy + 1):
                # Shopfront: a 2 m shop window every 7 m, so it looks like an
                # underground mall rather than a mine tunnel.
                win = (self.shopfront and yy in (y + 1, y + 2)
                       and ((x + z) % 7) < 2)
                w.set(x, yy, z, SHOP if win else WALL)
        for (x, z), g in self.pier_to.items():
            for yy in range(int(g) - 2, y - 1):         # From 2 blocks below the ground to 1 below the deck.
                w.set(x, yy, z, PIER)


# ---------- Vertical connections ----------

class Stair:
    """A straight stair: 1 m of rise per 2 m of run, alternating full blocks and slabs.

    It uses the same scheme as build_line.

    (x0, z0) is the start of the low end, and (dx, dz) is the direction toward the high
    end (one of the four orthogonal directions). It builds its own walls and roof slab,
    so it can dig straight from the underground mall into the ground without anything
    excavated in advance.

    The alternation must match the direction of travel: going up, a full block comes
    before a slab. Reversed, a 1.5 m step appears every 2 m, which you can walk down but
    not climb, and which is completely invisible in a cross-section.
    """

    def __init__(self, x0, z0, dx, dz, y_lo, y_hi, half_w=2, head=HEAD,
                 label=None, headhouse=False, open_cells=()):
        self.x0, self.z0 = int(x0), int(z0)
        self.dx, self.dz = int(dx), int(dz)
        self.y_lo, self.y_hi = int(y_lo), int(y_hi)
        self.half_w, self.head = int(half_w), int(head)
        self.label, self.headhouse = label, headhouse
        # Cells that are already passage floor must not get walls. Exits often come in
        # adjacent pairs (Taipei Main Station's exit North 3 and Taipei City Mall's Y8
        # are only 8 m apart), and one stair's side wall would seal the other's
        # connector. This is completely invisible in a cross-section and only shows up
        # when you walk through it.
        self.open_cells = open_cells

    def run(self):
        """Return the horizontal length in meters."""
        return 2 * max(0, self.y_hi - self.y_lo)

    def _w(self, a, b):
        vx, vz = -self.dz, self.dx
        return self.x0 + self.dx * a + vx * b, self.z0 + self.dz * a + vz * b

    def bbox(self):
        H = self.half_w + 1
        ends = [self._w(a, b) for a in (-2, self.run() + 4) for b in (-H, H)]
        xs = [p[0] for p in ends]; zs = [p[1] for p in ends]
        return min(xs) - 2, min(zs) - 2, max(xs) + 2, max(zs) + 2

    def treads(self):
        """Return [(a, supporting block y, block type, standing surface y)], where a is the distance along the flight."""
        out = []
        n = self.run()
        for t in range(n + 1):
            surf = self.y_lo + 0.5 * t
            half = abs(surf - math.floor(surf)) > 0.25
            yb = int(math.floor(surf)) if half else int(round(surf)) - 1
            out.append((t, yb, SLAB if half else STAIR, surf))
        return out

    def build(self, w):
        if self.y_hi <= self.y_lo:
            return
        H = self.half_w
        tr = self.treads()
        # Excavate first: clear the whole stair shaft plus 2 m at each end, then lay the treads.
        for a, yb, blk, surf in tr:
            for b in range(-H - 1, H + 2):
                x, z = self._w(a, b)
                edge = abs(b) == H + 1 and (x, z) not in self.open_cells
                for yy in range(yb, yb + self.head + 2):
                    w.set(x, yy, z, WALL if edge else AIR)
                if (x, z) not in self.open_cells:
                    w.set(x, yb + self.head + 1, z, STRUCT)  # The roof slab rises with the flight.
        for a, yb, blk, surf in tr:
            for b in range(-H, H + 1):
                x, z = self._w(a, b)
                w.set(x, yb, z, blk)
            if a % 8 == 0:
                x, z = self._w(a, 0)
                w.set(x, yb + self.head, z, LAMP)
        # Add a landing at each end to meet the passage floor level.
        for a, ylev in ((-2, self.y_lo), (self.run() + 2, self.y_hi)):
            for t in (0, 1, 2):
                aa = a + (t if a < 0 else -t)
                for b in range(-H, H + 1):
                    x, z = self._w(aa, b)
                    w.set(x, ylev - 1, z, STAIR)
                    for yy in range(ylev, ylev + self.head + 1):
                        w.set(x, yy, z, AIR)
                    if abs(b) == H and (x, z) not in self.open_cells:
                        for yy in range(ylev, ylev + self.head + 1):
                            w.set(x, yy, z, WALL)
                    if (x, z) not in self.open_cells:
                        w.set(x, ylev + self.head + 1, z, STRUCT)
        if self.headhouse:
            self._head(w)

    HEAD_LEN = 7        # Exit kiosk length along the flight: a = run .. run+6, door in the farthest wall.

    def door_front(self):
        """Return the cell outside the exit kiosk door, centered on the doorway.

        The result is (x, z, standing surface y, direction toward the door (dx, dz)).

        The door is in the wall at a = run + HEAD_LEN - 1, at b = -1..1, three blocks
        tall. Its paving is at y_hi, the same as inside the kiosk (the kiosk floor slab
        is at y_hi - 1). Standing one cell outside and facing -u faces the door directly.
        """
        x, z = self._w(self.run() + self.HEAD_LEN, 0)
        return x, z, self.y_hi, (-self.dx, -self.dz)

    def _head(self, w):
        """Build the street-level exit kiosk: a roof and one wall with a door.

        Without it, the top of the stair is an uncovered hole in the street.
        """
        H = self.half_w
        g = self.y_hi
        for a in range(self.run(), self.run() + self.HEAD_LEN):
            for b in range(-H - 1, H + 2):
                x, z = self._w(a, b)
                far = a == self.run() + self.HEAD_LEN - 1
                side = abs(b) == H + 1 or far
                for yy in range(g, g + 4):
                    door = far and abs(b) <= 1 and yy <= g + 2
                    if side and not door:
                        w.set(x, yy, z, WALL)
                    else:
                        w.set(x, yy, z, AIR)
                w.set(x, g - 1, z, FLOOR)
                w.set(x, g + 4, z, CEIL)
        x, z = self._w(self.run() + 3, 0)
        w.set(x, g + 3, z, LAMP)
        if self.label:
            names = self.label if isinstance(self.label, (list, tuple)) else [self.label]
            sx, sz = self._w(self.run() + 5, 0)
            w.set(sx, g - 1, sz, FLOOR)
            if hasattr(w, "sign"):
                w.sign(sx, g, sz, ["／".join(str(t) for t in names[:2]),
                                   "台北地下街", "Taipei City Mall", "出口 Exit"],
                       facing=(self.dx, self.dz))


class ShaftStair:
    """A switchback stair shaft that goes down from one level to another at any depth.

    It used to live in landmarks.py and moved here because the underground mall's link
    stairs use it too. For the underground mall, g0 is passed as y_stand-1 (the mall
    floor slab): the top landing blocks sit exactly on the mall floor slab, the door
    opens within the mall's clearance, and the roof is exactly the mall's roof slab.
    The same geometry with a different g0 turns a street exit into a link stair
    between levels.

    The long exit stairs along the lines need 2 m of run per 1 m of drop, so a station
    39 m deep needs a 78 m straight run. Real exits are often less than 40 m from the
    station box, so forcing a straight run would cut through neighboring property. A
    switchback stair folds the run into a shaft of fixed size that fits any depth, and
    is closer to how real deep stations do it.

    Coordinates: (x0, z0) is the center of the shaft, u = (ux, uz) is the direction the
    flights run (a unit vector; only the four orthogonal directions are supported), and
    v is its normal.
    """

    FLIGHT = 14          # Horizontal length of one flight in meters, so each flight drops 7 m.
    HALF_W = 4           # Half-width of the shaft, along the normal.

    def __init__(self, x0, z0, ux, uz, g0, y_to, bottom_door=False,
                 wall="minecraft:gray_concrete",
                 step="minecraft:smooth_stone",
                 slab="minecraft:smooth_stone_slab",
                 rail="minecraft:iron_bars",
                 lamp="minecraft:sea_lantern",
                 sign=None, sign_bottom=None, apron=None, sign_style=None):
        self.x0, self.z0 = int(x0), int(z0)
        self.ux, self.uz = int(round(ux)), int(round(uz))
        self.g0, self.y_to = int(g0), int(y_to)
        self.bottom_door = bool(bottom_door)
        self.wall, self.step, self.slab = wall, step, slab
        self.rail, self.lamp = rail, lamp
        self.sign = list(sign) if sign else None    # Sign beside the top door (up to four lines).
        # Sign beside the bottom door. In a shaft that climbs from the street up to an
        # elevated concourse, the street door is at the bottom, so the exit number sign
        # has to stand there.
        self.sign_bottom = list(sign_bottom) if sign_bottom else None
        self.apron = apron          # Apron paving block in front of the street door (None paves nothing).
        # Remaining sign parameters (wood, glowing ink and so on; see ports.block_sink.SignSink).
        self.sign_style = dict(sign_style or {})

    # Shaft coordinates (a along u, b along v) -> world coordinates.
    def _w(self, a, b):
        vx, vz = -self.uz, self.ux
        return self.x0 + self.ux * a + vx * b, self.z0 + self.uz * a + vz * b

    def bbox(self):
        pts = [self._w(a, b) for a in (0, self.FLIGHT + 2)
               for b in (-self.HALF_W - 1, self.HALF_W + 1)]
        xs = [p[0] for p in pts]; zs = [p[1] for p in pts]
        return min(xs) - 2, min(zs) - 2, max(xs) + 2, max(zs) + 2

    def flights(self):
        """Return [(direction, y_start, y_end)], where direction +1 runs along u and -1 against u."""
        drop = self.g0 - self.y_to
        if drop <= 0:
            return []
        per = self.FLIGHT / 2.0                  # Meters dropped per flight.
        out = []
        y = float(self.g0)
        d = 1
        while y - self.y_to > 1e-6:
            dy = min(per, y - self.y_to)
            out.append((d, y, y - dy))
            y -= dy
            d = -d
        return out

    def build(self, w):
        fl = self.flights()
        if not fl:
            return
        H = self.HALF_W
        lo = min(self.y_to - 1, self.g0)
        # Shaft walls and excavation.
        for a in range(-1, self.FLIGHT + 3):
            for b in range(-H - 1, H + 2):
                x, z = self._w(a, b)
                edge = (a in (-1, self.FLIGHT + 2) or abs(b) == H + 1)
                for y in range(lo, self.g0 + 5):
                    w.set(x, y, z, self.wall if edge else AIR)
        # Top landing. The door is at a=-1 and the first flight starts at a=1, and a=0
        # between them used to be left empty: the door opened onto a hole straight to the
        # bottom of the shaft (a 22 m drop in the deepest one at Taipei Main Station).
        # The player fell to their death, and the walkability check found it
        # disconnected: the stair was fully built, but nobody could walk into it. The
        # cell is now paved as a lobby level with the threshold, leading down to the
        # first step (the top tread is at g0, exactly one step lower).
        for b in range(-H, H + 1):
            x, z = self._w(0, b)
            w.set(x, self.g0, z, self.step)
            for y in range(self.g0 + 1, self.g0 + 5):
                w.set(x, y, z, AIR)

        # Flights: +1 runs toward increasing a and -1 toward decreasing a; the two
        # directions occupy the two halves along the normal.
        for k, (d, ya, yb) in enumerate(fl):
            b0, b1 = (1, H) if d > 0 else (-H, -1)
            n = int(round((ya - yb) * 2))
            for t in range(n + 1):
                a = (1 + t) if d > 0 else (self.FLIGHT + 1 - t)
                surf = ya - 0.5 * t
                half = abs(surf - math.floor(surf)) > 0.25
                yb_ = int(math.floor(surf)) if half else int(round(surf)) - 1
                blk = self.slab if half else self.step
                for b in range(b0, b1 + 1):
                    x, z = self._w(a, b)
                    w.set(x, yb_, z, blk)
                    for y in range(yb_ + 1, yb_ + 4):
                        w.set(x, y, z, AIR)
                # Central handrail, so nobody falls straight down from above.
                bm = 0
                x, z = self._w(a, bm)
                w.set(x, yb_, z, self.step)
                w.set(x, yb_ + 1, z, self.rail)
            # Landing.
            xa, za = self._w(self.FLIGHT + 1 if d > 0 else 1, 0)
            for b in range(-H, H + 1):
                a = self.FLIGHT + 1 if d > 0 else 1
                x, z = self._w(a, b)
                w.set(x, int(round(yb)) - 1, z, self.step)
                for y in range(int(round(yb)), int(round(yb)) + 4):
                    w.set(x, y, z, AIR)
            if k % 2 == 0:
                x, z = self._w(self.FLIGHT // 2, 0)
                w.set(x, int(round(ya)) + 3, z, self.lamp)
        # Bottom floor slab.
        for a in range(0, self.FLIGHT + 2):
            for b in range(-H, H + 1):
                x, z = self._w(a, b)
                w.set(x, self.y_to - 1, z, self.step)
        # Street-level exit kiosk: add a roof and open a door in the near wall;
        # otherwise it is an uncovered trap.
        for a in range(-1, self.FLIGHT + 3):
            for b in range(-H - 1, H + 2):
                x, z = self._w(a, b)
                w.set(x, self.g0 + 5, z, self.wall)
        for b in range(-1, 2):
            x, z = self._w(-1, b)
            for y in range(self.g0 + 1, self.g0 + 4):
                w.set(x, y, z, AIR)
        x, z = self._w(1, 0)
        w.set(x, self.g0 + 4, z, self.lamp)
        # The bottom of the shaft needs a door too. As a link stair, the shaft is
        # surrounded by solid ground, and without a door its only entrance is at the top:
        # the stair is fully built, but nobody can reach the concourse. (This class was
        # originally used only for street exits, where the bottom was opened by a
        # separate Passage outside.)
        if self.bottom_door:
            for b in range(-1, 2):
                x, z = self._w(-1, b)
                # The upper limit is clamped to g0. When the shaft is very shallow (the
                # Taoyuan Airport MRT concourse is only 2 m lower), the lower doorway would
                # be dug all the way up to g0 and remove the block the top landing stands
                # on. Walking over from the underground mall then drops you straight down,
                # and a drop you cannot climb back up is the same as no connection.
                for y in range(self.y_to, min(self.y_to + 3, self.g0)):
                    w.set(x, y, z, AIR)
        # Pave a small apron in front of the street door (paving at grass level, two
        # blocks of clearance). When the shaft stands on a hillside, the terrain on
        # either side of the threshold can differ by two or three blocks, so the first
        # step out of the door lands on a dirt slope or a cliff. The exits at Muzha,
        # Tamkang University and Yingge Station failed this way: the doorway did not
        # meet the street. The apron covers only a=-2..-4 directly in front of the door,
        # does not touch the shaft, and stays below the passage level (a skybridge floor
        # slab is at least two blocks above the street, and the clearance is cleared
        # only to one block above the street).
        if self.apron:
            street = self.y_to if self.sign_bottom else self.g0 + 1
            for a in (-2, -3, -4):
                for b in range(-2, 3):
                    x, z = self._w(a, b)
                    w.set(x, street - 1, z, self.apron)
                    for y in range(street, street + 2):
                        w.set(x, y, z, AIR)
        # The exit number sign stands outside the door, facing people as they approach.
        # A block goes underneath, so the sign does not float in midair where the
        # terrain happens to dip.
        if self.sign and hasattr(w, "sign"):
            x, z = self._w(-2, 2)
            w.set(x, self.g0, z, self.step)
            w.sign(x, self.g0 + 1, z, self.sign[:4], facing=(-self.ux, -self.uz),
                   **self.sign_style)
        if self.sign_bottom and hasattr(w, "sign"):
            x, z = self._w(-2, 2)
            w.set(x, self.y_to - 1, z, self.step)
            w.sign(x, self.y_to, z, self.sign_bottom[:4], facing=(-self.ux, -self.uz),
                   **self.sign_style)



# ---------- Plan ----------

def plan(ways, entrances, ground_at, y_stand, links=(), half_w=3,
         snap_tol=3.0, snap_radius=60.0, near=(0.0, 0.0), tile=TILE,
         no_wall=(), bridge=25.0, merge_m=12.0, occ=None, own_tags=None):
    """Turn OSM passages and exits into a list of objects that can build().

    ways        [{"nodes": [...], "points": [[x, z], ...]}], already projected to MC coordinates
    entrances   [(ref, x, z)]
    ground_at   f(x, z) -> ground y
    y_stand     standing surface y of the underground mall
    links       [(x, z, concourse standing surface y, name, ux, uz)], the link stairs
                down to each line's concourse
    no_wall     cells that get no walls (for example the B1 hall, which is already open space)
    occ         exits.Occupancy: which heights every line's tunnels and station boxes
                occupy. A link stair shaft is dug from the underground mall all the way
                to the concourse of the deeper line and passes through the depths of the
                shallower lines on the way.
    own_tags    f(link stair name) -> that line's own segment tags (the bottom of the
                shaft is inside its own station box by design)
    Returns (objects, report).
    """
    pos, adj, edges = CC.build_graph(ways, tol=snap_tol)
    bridged = CC.bridge_gaps(pos, adj, edges, max_gap=bridge)
    group = CC.main_component(pos, adj, near=near)
    lines = CC.corridor_lines(pos, edges, group)
    connected, orphan = CC.snap_entrances(pos, group, entrances,
                                          radius=snap_radius)

    # ---- 1. Floor cells: the passages, the exit connectors and the link stair connectors ----
    cells = set()
    for a, b in lines:
        cells |= stroke(a, b, half_w)

    # Exit connectors. Taipei City Mall is five centerlines in OSM, and its exits Y9 to
    # Y20 and Y22 to Y28 are all 9 to 42 m off those lines: the cross passages are not
    # mapped at all. Without these connectors those exits would not connect.
    for ref, ex, ez, n, d in connected:
        if d > 1.0:
            cells |= stroke((ex, ez), pos[n], max(2, half_w - 1))

    # Link stairs: from each line's concourse up to the underground mall. They use
    # switchback stair shafts, not straight stairs. The Tamsui-Xinyi Line concourse is at
    # y44, so a straight stair would need 36 m of run to climb up, and the station box
    # structure follows the curved alignment: a straight 36 m run leaves the box
    # structure partway, and the foot of the stair no longer meets the concourse (in
    # testing, this is exactly what happened on the R line). A switchback stair folds
    # the run into an 18x11 m shaft that fits any depth.
    #
    # g0 is passed as y_stand-1: the top landing sits exactly on the underground mall
    # floor slab, the door opens within the mall's clearance, and the roof is exactly
    # the mall's roof slab. The shaft extends outward along the station box normal,
    # away from the platform stairs (within ±3 cells of the centerline).
    # ---- Exit stairs are planned first (not built yet): the link stair shafts must avoid them ----
    # Exits very close together share one stair. Taipei Main Station's exit North 3 and
    # Taipei City Mall's Y8 are only 8 m apart and are in reality two names for the same
    # exit. With one stair each, the side wall of the later one would seal the earlier
    # one (in testing, North 3 became a separate connected component this way).
    stair_plan, exits_flat, merged, taken = [], [], [], []
    stair_fp = set()
    for ref, ex, ez, n, d in sorted(connected, key=lambda e: e[4]):
        g = int(ground_at(ex, ez))
        if g - y_stand < 2:
            exits_flat.append((ref, ex, ez))
            continue
        near_t = next((t for t in taken
                       if math.hypot(t[1] - ex, t[2] - ez) <= merge_m), None)
        if near_t is not None:
            near_t[0].append(ref)
            merged.append((ref, ex, ez))
            continue
        refs = [ref]
        taken.append((refs, ex, ez))
        dx, dz = CC.outward(pos, adj, n, ex, ez)
        stair_plan.append((refs, ref, ex, ez, dx, dz, g))
        run = 2 * (g + 1 - y_stand)
        vx, vz = -dz, dx
        for a in range(-3, run + 8):
            for b in range(-4, 5):
                stair_fp.add((int(ex) + dx * a + vx * b, int(ez) + dz * a + vz * b))

    # Where each shaft goes and which way it faces has to be chosen:
    #  · When two link stairs are close together (at Zhongshan the Songshan-Xindian Line
    #    and Tamsui-Xinyi Line concourses are only 14 m apart), the shafts overlap, and
    #    the later one hollows out the earlier one's stair. A cross-section shows both
    #    shafts; only walking through reveals that one of them is empty.
    #  · A shaft on top of a passage cuts it in two. Zhongshan Metro Mall lies directly
    #    above the Tamsui-Xinyi Line, and a shaft at the station box center sits right
    #    across the passage, wider than it, so the north and south halves no longer
    #    connect. The shaft may therefore shift sideways along the station box normal to
    #    the edge of the passage, with a connector leading back to its door; the bottom
    #    door is still inside the concourse (|offset from the line| <= 9).
    # Each candidate position and direction gets a score. Overlapping another shaft,
    # overlapping a passage, and a connector crossing another shaft all add a penalty.
    # The best one wins, and the smaller the shift the better.
    from mrt.domain.exits import shaft_cells
    corridor = set(cells)
    link_objs = []
    taken_fp, taken_st = set(), set()
    for lk in links:
        lx, lz, ly, name = lk[0], lk[1], lk[2], lk[3]
        ux, uz = (lk[4], lk[5]) if len(lk) > 5 else (1.0, 0.0)
        if ly >= y_stand - 1 or not group:
            continue
        px, pz = -uz, ux                        # Station box normal.
        cands = []
        for vx, vz in ((px, pz), (-px, -pz), (ux, uz), (-ux, -uz)):
            q = ((1 if vx > 0 else -1), 0) if abs(vx) >= abs(vz) \
                else (0, (1 if vz > 0 else -1))
            if q not in cands:
                cands.append(q)
        # The door moves 7 m along the station box. The two stairs from the concourse
        # down to the platform open holes in the floor slab at -8..-1 m and +16..+23 m
        # from the station box center, so a door facing the center opens onto a 5 m drop
        # (this is how the Songshan-Xindian Line platform at Zhongshan became unreachable
        # from the underground mall).
        # The shaft must not pass through another line's station box or tunnel. The link
        # stair to the Tamsui-Xinyi Line at Taipei Main Station (concourse y44) is dug
        # down from the underground mall (y61) and passes exactly through the depth of
        # the Bannan Line station box (y49..61). The code used to check only the
        # underground mall's own objects, so the shaft sat on the north edge of the
        # Bannan Line station box and turned 17 m of the north track and platform edge
        # into shaft, lined with shaft walls; it only showed up in a cross-section cut
        # from the world save. Several positions along the station box are tried, and one
        # that passes through no other line is chosen. The door must land where the floor
        # slab has no hole: between the two platform stair holes (0..15 m from the
        # station box center), between the fare gates and the first stair (−19..−12), or
        # past the second stair (24..33).
        mine = own_tags(name) if own_tags is not None else None

        def hits_other(fp):
            if occ is None:
                return 0
            return sum(1 for x, z in fp if occ.blocked(x, z, ly - 1, y_stand - 2, skip_tag=mine))

        best = None
        for along, shift in [(a, s_) for a in (7, 11, 3, 13, -15, -14, 27, 30) for s_ in (0, 8, -8, 9, -9)]:
            cx_ = lx + ux * along + px * shift
            cz_ = lz + uz * along + pz * shift
            for dx, dz in cands:
                x0, z0 = int(round(cx_)) + dx, int(round(cz_)) + dz
                fp = shaft_cells(x0, z0, dx, dz, margin=1)
                door = (x0 - dx, z0 - dz)
                # Out of the door, the connector runs straight for four cells before
                # turning toward the nearest node. The door is only three cells wide,
                # centered in the row of shaft wall. If the connector left the doorway
                # diagonally, its width would sweep over the shaft wall on either side of
                # the door; the shaft is built after the passages, so once the shaft wall
                # is rebuilt, the short stretch in front of the door is sealed. This is how
                # the link stairs at Beimen and Shuanglian failed to reach the underground
                # mall.
                porch = (door[0] - 4 * dx, door[1] - 4 * dz)
                near_n = min(group, key=lambda n: math.hypot(pos[n][0] - porch[0],
                                                             pos[n][1] - porch[1]))
                st = (stroke(door, porch, max(2, half_w - 1))
                      | stroke(porch, pos[near_n], max(2, half_w - 1)))
                bad = (10 * (len(fp & taken_fp) + len(st & taken_fp) + len(fp & taken_st)
                             + len(fp & stair_fp))
                       + 50 * hits_other(fp)
                       + len(fp & corridor) + abs(shift) + abs(along - 7))
                if best is None or bad < best[0]:
                    best = (bad, dx, dz, x0, z0, door, near_n, fp, st)
        _, dx, dz, x0, z0, door, near_n, fp, st = best
        well = ShaftStair(x0, z0, dx, dz, y_stand - 1, ly, bottom_door=True)
        well.label = name
        well.clash = hits_other(fp)             # Cells still passing through other lines (for the report; should be 0).
        link_objs.append(well)
        taken_fp |= fp
        taken_st |= st
        # The door at the top of the shaft is at a=-1, the station box center cell.
        # Connect it back to the passage network.
        cells |= st

    # ---- 2. Roof slab height ----
    # It follows the terrain but is never higher than the ground surface. Where the
    # ground surface is too low (around the north section of Zhongshan Metro Mall the
    # ground is only at y64), the roof slab is allowed to serve directly as the road
    # surface: in reality that section has a linear park on top, and the roof slab is
    # the paving. At least 2 blocks of clearance are kept; a cell is given up only when
    # its standing surface is already above the ground.
    ceil_of, thin, shallow = {}, set(), 0
    for c in cells:
        g = int(ground_at(c[0], c[1]))
        if g <= y_stand + 1:
            thin.add(c)
            continue
        cy = min(y_stand + HEAD, g - 1)
        if cy - y_stand < 2:
            cy = y_stand + 2
            shallow += 1
        ceil_of[c] = cy
    cells -= thin

    # ---- 3. Tiling ----
    # no_wall is space that is already open (the B1 hall). A passage crossing it must
    # not get walls, or it would build a corridor through the hall and cut it in two.
    ring = outer_ring(cells) - set(no_wall)
    objs, buckets = [], {}
    for c in cells:
        buckets.setdefault((c[0] // tile, c[1] // tile), [set(), set()])[0].add(c)
    for c in ring:
        buckets.setdefault((c[0] // tile, c[1] // tile), [set(), set()])[1].add(c)
    for key in sorted(buckets):
        cs, rs = buckets[key]
        objs.append(Tile(cs, rs, y_stand, ceil_of))

    # ---- 4. Exit stairs (they must come after the floors to dig their own holes) ----
    # Positions and directions were decided above; this step only builds them.
    exits_built = []
    for refs, ref, ex, ez, dx, dz, g in stair_plan:
        # g is the ground surface block, and a person standing on it has their feet at
        # g+1. The stair must climb to g+1 for the exit kiosk paving to be level with the
        # street. It used to stop at g, so leaving meant jumping up one block and
        # entering meant dropping one.
        objs.append(Stair(ex, ez, dx, dz, y_stand, g + 1, half_w=2,
                          label=refs, headhouse=True, open_cells=cells))
        exits_built.append((ref, ex, ez))
    objs += link_objs

    report = dict(nodes=len(pos), group=len(group), lines=len(lines),
                  bridged=len(bridged), length=round(CC.total_length(lines)),
                  cells=len(cells), ring=len(ring), tiles=len(buckets),
                  links=[(o.label, o.x0, o.z0, o.y_to, o.g0, getattr(o, "clash", 0))
                         for o in link_objs],
                  # ref repeats across stations (Taipei Main Station and Beimen both
                  # have exits 1, 2 and 3), so the report always carries coordinates;
                  # otherwise another station's exit could be mistaken for connected.
                  connected=[(e[0], e[1], e[2]) for e in connected],
                  orphan=[(r, x, z) for r, x, z in orphan],
                  exits=exits_built, exits_flat=exits_flat,
                  merged=merged,
                  thin=len(thin), shallow=shallow)
    return objs, report
