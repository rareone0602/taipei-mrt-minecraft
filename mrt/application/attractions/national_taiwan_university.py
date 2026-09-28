#!/usr/bin/env python3
"""National Taiwan University, main campus: the main gate, Royal Palm Boulevard and its
palms, Fu Bell, the buildings along the boulevard and the Main Library at its end.

Position and outlines (OSM, data/attractions.json, fetched within 110 m of the boulevard):
  relation/14045849  The Main Library. Its 54 building:parts carry story counts from one
                     to six, which give the stepped massing: a one-story podium across the
                     front (building:part=roof), the entrance hall standing out of it, narrow
                     pavilions either side, the six-story main block and spine behind, the
                     four-story corner pavilions and north wing, and the bell tower.
  relation/2589022   The main gate's guardhouse, between the way in and the way out.
  node/472493077     Fu Bell.
  natural=tree       172 royal palms (Roystonea regia) and 32 dragon junipers, mapped one
                     by one with their species; natural=tree_row where a row is mapped as
                     a line (a row mapped by its two ends only is planted every 5 m).
  highway 椰林大道    The boulevard, 15.5–16 m wide, and the loop through the gate.
  building           The other buildings within reach of the boulevard, with
                     building:levels where OSM has them.

Appearance (public sources; photographs on Wikimedia Commons were used only for
proportions and are marked "photo"):
  · Main Library (沈祖海建築師事務所, 1990–98): five stories above ground and one below,
    about 35,000 m². The main block is as wide as the boulevard, the entrance hall stands
    forward of the entrance platform and is double height, the forecourt is red sandstone;
    thirteen-groove tiles, gables, arched windows and bands, from the old campus. The
    colonnade in the design, meant to run out along both sides, was never built. The bell
    tower (鐘塔) stands in the sunken courtyard on the north side, above the roofline, and
    cannot be climbed (the architects' talk, NTU Secretariat e-paper no. 530). The front
    (photo): an entrance arcade of five round arches, the middle one tallest, the outer two
    in pale stone bays, under a parapet of pierced panels; a four-story arched window
    framed by a pale stone pediment; a larger low brick gable with a round window above;
    the wings stepping down to corner pavilions, flat roofs behind parapets and small
    dark gray pitched roofs on the outermost; the tower square, tiled, with pale corners,
    tall round-headed openings and an open belvedere with a flat top, about twice the
    height of the four-story north wing.
  · Old Main Library (1929–31, now the Gallery of NTU History): two stories, a porch of
    three round arches on sandstone columns with a balustrade above, a central gable over
    the great arched window, a hipped roof in dark gray Japanese tile (NTU building
    history site; photo).
  · College of Liberal Arts (1929, 1933–34): two stories, the entrance standing forward
    with two tiers of three arches, a central gable, a dark hipped roof (the same site).
  · Administration Building (1926, extended 1970–71): red brick rather than tile, black
    tiles, a porch of four Corinthian columns rising the full two stories under a
    pediment, a square fountain pool in front (the same site, zh.wikipedia).
  · Main gate (1931): a guardhouse with a gate either side, each a carriageway between
    footways; Beitou tile (#bc8c60) on reinforced concrete, a base and four lamp stands of
    Qilian stone (#c6b190); turned 45° to the campus axis; about 3 m high (NTU history
    site; National Cultural Memory Bank; zh.wikipedia). The guardhouse (photo): a bowed
    front with louvred windows under a stone band bearing the university's name, a flat
    top with a stepped stone cap and a flagpole.
  · Fu Bell (1951, recast 1964): a Western bronze bell on a maroon iron frame of four
    posts that curve in at the top, with two hoops round them; over 5 m high; a round
    raised platform with a compass mark and eight short posts of washed granite; four
    dragon junipers round it (NTU alumni bimonthly no. 9155; photo). It rings 21 times
    (zh.wikipedia).
  · Royal Palm Boulevard: about 100 royal palms a side (NTU visitor center); the species
    grows 15–20 m (NTU history site); a 16 m asphalt carriageway, footpaths beside the
    palms, azaleas, and lamps (NTU alumni bimonthly no. 2100).
"""
import math

import numpy as np

from mrt import config
from mrt.application.attractions import colonial_kit as CK
from mrt.application.attractions import kit
from mrt.application.attractions.kit import AIR, Attraction, Frame, Spot
from mrt.domain import geometry as shapes

LIBRARY = "relation/14045849"
GATE = "relation/2589022"
BELL = "node/472493077"
# Library parts with a look of their own; the rest are tiled walls with windows.
PODIUM = "way/1303202996"           # building:part=roof across the front: the entrance platform
ENTRANCE = "way/1303202995"         # The entrance hall, standing out of the podium
MAIN_BLOCK = "way/1303202984"       # The six-story main block, with the great gable
PAVILIONS = ("way/1303202986", "way/1303202976", "way/1303202988", "way/1303202977")
CORNERS = ("way/1303202991", "way/1303202980")      # Corner pavilions, with pitched roofs
SPINE = "way/1303202970"            # The six-story spine over the atrium
TOWER = "way/1303202957"            # The bell tower in the northern courtyard
# Buildings along the boulevard whose fronts are published (see the docstring).
OLD_LIBRARY = "relation/2586500"
LIBERAL_ARTS = "relation/2586501"
ADMINISTRATION = "relation/2589021"
HERITAGE = {OLD_LIBRARY: "porch", LIBERAL_ARTS: "loggia", ADMINISTRATION: "portico"}
# Left out: Fu Sinian's tomb (斯年堂) in Fu Garden is a small Greek temple, which a tiled
# box would misrepresent.
SKIP = {"way/192060474"}

B = "minecraft:"
TILE = B + "mud_bricks"                      # Thirteen-groove face tiles
TILE_STAIRS = "mud_brick_stairs"
BRICK = B + "bricks"                         # The Administration Building's red brick
BRICK_STAIRS = "brick_stairs"
TRIM = B + "smooth_sandstone"                # Pale stone: bands, cornices, arches, copings
TRIM_STAIRS = "smooth_sandstone_stairs"
TRIM_SLAB = "smooth_sandstone_slab"
PANEL = B + "chiseled_sandstone"             # Pierced parapet panels
STONE = B + "cut_sandstone"                  # Qilian stone: the gate's base and piers
STONE2 = B + "sandstone"
PIER = B + "polished_andesite"               # Granite piers and arch stones
PIER_STAIRS = "polished_andesite_stairs"
PLINTH = B + "stone_bricks"
GLASS = B + "gray_stained_glass"
FRAME = B + "polished_deepslate"             # The great window's dark glazing bars
ROOF = B + "smooth_stone"
TILE_ROOF = B + "deepslate_tiles"            # Dark gray Japanese roof tiles
TILE_ROOF_STAIRS = "deepslate_tile_stairs"
FLOOR = B + "polished_andesite"
FILL = B + "stone"
GRASS = B + "grass_block[snowy=false]"
ROAD = B + "gray_concrete"                   # Asphalt
CURB = B + "smooth_stone"
WALK = B + "bricks"
PLAZA = B + "polished_granite"               # Red sandstone
PLAZA_LINE = B + "granite"
MARBLE = B + "polished_diorite"
WATER = B + "water"
PIT = B + "coarse_dirt"
PALM_TRUNK = B + "mushroom_stem"             # Royal palms: smooth gray trunks
PALM_SHAFT = B + "lime_terracotta"           # The green crownshaft
PALM_LEAF = B + "jungle_leaves[distance=7,persistent=true,waterlogged=false]"
JUNIPER = B + "spruce_leaves[distance=7,persistent=true,waterlogged=false]"
AZALEAS = (B + "azalea", B + "flowering_azalea")
POST = B + "stone_brick_wall"
LANTERN = B + "lantern[hanging=false,waterlogged=false]"
RAIL = B + "sandstone_wall"
IRON = B + "mangrove_fence"                  # Fu Bell's maroon iron frame
BELL_BLOCK = B + "bell[attachment=ceiling,facing=north]"

STORY = 4                  # Meters per story of the campus buildings
OLD_STORY = 4.5            # The Japanese-era buildings and the library have taller stories
BAY = 5.0                   # Window bays: a three-block window and two blocks of wall
NEAR_M = 105                # Buildings whose walls come this close to the boulevard are built
PALM_TRUNK_M = (11, 14)     # Trunk heights; with the crownshaft and crown, 17–20 m in all
ROAD_W = 15.5               # The boulevard where OSM gives no width
LINK_W = {"1": 4.5, "2": 7.0}
SUNK = 4                    # The northern courtyard lies one story down
TOWER_FLOORS = [0, 4, 9, 13, 18, 22, 27, 31, 35, 40]   # From the courtyard floor
POND_HALF = 7               # The Administration Building's square pool, 15 m a side


def stories(n, height):
    """Floor levels (meters above the ground slab) of n stories, rounded to whole blocks:
    4.5 m stories give 0, 5, 9, 14, 18, 23, 27."""
    return [int(k * height + 0.5) for k in range(n + 1)]


def _levels(tags):
    for key, per in (("building:levels", 1.0), ("height", 3.5)):
        try:
            v = float(str(tags[key]).split()[0])
        except (KeyError, ValueError):
            continue
        return max(1, int(round(v / per)))
    return None


def _outer(f):
    return max(f["outer"], key=len)


def _seg_dist(X, Z, a, b):
    """Distance from every point (X, Z) to the segment a-b."""
    ax, az = a
    dx, dz = b[0] - ax, b[1] - az
    L = dx * dx + dz * dz
    t = np.clip(((X - ax) * dx + (Z - az) * dz) / L, 0.0, 1.0) if L else 0.0
    return np.hypot(X - ax - t * dx, Z - az - t * dz)


def line_dist(X, Z, line):
    d = None
    for a, b in zip(line, line[1:]):
        s = _seg_dist(X, Z, a, b)
        d = s if d is None else np.minimum(d, s)
    return d


def _hash(x, z):
    return (int(x) * 73856093 ^ int(z) * 19349663) & 0xFFFF


def fence(**sides):
    """A mangrove fence with the given sides joined (east=True, ...); the rest default to
    unjoined."""
    on = ["%s=true" % d for d in ("east", "north", "south", "west") if sides.get(d)]
    return IRON + ("[%s]" % ",".join(on) if on else "")


class Mass:
    """One building (or library part) on its own frame: the mask, the floor levels and the
    convex corners (in local coordinates, for keeping windows off the corners)."""

    def __init__(self, fr, mask, floors, corners, osm="", wall=TILE, hip=False, front=None):
        self.fr, self.mask, self.floors, self.corners, self.osm = fr, mask, floors, corners, osm
        self.wall, self.hip, self.front = wall, hip, front


def mass_on(fr, f, floors, **kw):
    ring = _outer(f)
    m = fr.polygon(ring)
    for inner in f.get("inner", []):
        if len(inner) >= 3:
            m &= ~fr.polygon(inner)
    corners = CK.convex_corners([CK.to_local(fr, x, z) for x, z in ring])
    return Mass(fr, m, floors, corners, f["osm"], **kw)


def own_frame(ring, margin=4):
    """A frame square to a building's own walls, with its origin on a cell center so that
    the windows (centered on t = 0) come out three blocks wide."""
    ang = CK.fit_angle(ring)
    if abs(math.degrees(ang)) < 1.2:
        ang = 0.0
    xs = [p[0] for p in ring]
    zs = [p[1] for p in ring]
    cx, cz = math.floor((min(xs) + max(xs)) / 2) + 0.5, math.floor((min(zs) + max(zs)) / 2) + 0.5
    ext = max(max(xs) - min(xs), max(zs) - min(zs)) / 2 + margin
    return Frame(cx, cz, ang, ext)


# ---------------------------------------------------------------- Facades

def tiled(m, floors, bay=BAY, arch=True, wall=TILE):
    """The campus facade: a stone plinth, tiled walls, a stone band at every floor and one
    window per bay (three blocks wide, hollow in the outer layer with glass behind; with
    arch, its head is rounded by two upside-down stairs), none within two blocks of a
    corner. The band at the top is the cornice; one course above it is the parapet."""
    top = floors[-1]
    bands = set(floors[1:])
    stairs = TILE_STAIRS if wall == TILE else BRICK_STAIRS

    def pattern(face, t, h, layer, u, v, q):
        if h > top:
            return wall if layer == 0 else None
        if h in bands:
            return TRIM
        if h == 1:
            return PLINTH if layer == 0 else wall
        k = 0
        while floors[k + 1] < h:
            k += 1
        lo, hi = floors[k] + (2 if k == 0 else 1), floors[k + 1] - 1
        p = (t + bay / 2.0) % bay - bay / 2.0
        if not (abs(p) < 1.5 and lo <= h <= hi and (q is None or q >= 2.0)):
            return wall
        if layer:
            return GLASS
        if arch and h == hi and hi > lo and abs(p) >= 0.5:
            du, dv = m.along(face)
            s = 1 if p > 0 else -1
            return CK.stair(stairs, m.facing(du * s, dv * s), "top")
        return AIR
    return pattern


def build_mass(w, ms, g0, pattern=None, roof=ROOF):
    """Walls and cornice, a flat roof and a ground floor. A flat-roofed mass gets a parapet
    with a stone coping; a mass of under 40 cells (the library's stair towers and fins)
    stops at its cornice, since a parapet round each would clutter the roofs with little
    boxes; a hipped mass gets its roof instead (hip_roof)."""
    m = CK.Mason(w, ms.fr)
    top = ms.floors[-1]
    bare = ms.hip or int(ms.mask.sum()) < 40
    m.fill(ms.mask, g0, g0, FLOOR)
    m.facade(ms.mask, g0 + 1, g0 + top + (0 if bare else 1),
             pattern or tiled(m, ms.floors, wall=ms.wall), base=g0, corners=ms.corners)
    m.fill(kit.erode(ms.mask, 2), g0 + top, g0 + top, roof)
    if not bare:
        m.fill(kit.ring(ms.mask), g0 + top + 2, g0 + top + 2, CK.slab(TRIM_SLAB))
    if ms.hip:
        hip_roof(m, ms, g0)
    return m


def hip_roof(m, ms, g0, pitch=0.6, cap=5.0):
    """A hipped roof in dark gray tile over any plan (courtyards included), its eaves one
    block beyond the walls; the height is the distance in from the eaves."""
    eave = kit.dilate(ms.mask, 1)
    d = kit.depth(eave).astype(float)
    h = np.minimum((d - 1.0) * pitch, cap)
    m.roof(eave, g0 + ms.floors[-1] + 1, h, TILE_ROOF, stair_name=TILE_ROOF_STAIRS, shell=1)


class Front:
    """A face of a mass and the local geometry to build on it: the outward normal n, the
    direction along the face a (t grows along it), and the wall line."""

    def __init__(self, ms, n):
        self.ms, self.n = ms, n
        self.a = (0, 1) if n[0] else (1, 0)
        fr = ms.fr
        U, V = fr.U[ms.mask], fr.V[ms.mask]
        if n[0]:
            near = np.abs(V) <= 1.0
            vals = U[near] if near.any() else U
        else:
            near = np.abs(U) <= 1.0
            vals = V[near] if near.any() else V
        self.wall = float(vals.max()) if (n[0] > 0 or n[1] > 0) else float(vals.min())

    def uv(self, t, d):
        """Local point t along the face and d out from the wall's outer layer."""
        wall = self.wall + d * (self.n[0] or self.n[1])
        return (wall, t) if self.n[0] else (t, wall)

    def put(self, m, t, d, y, block):
        m.at(*self.uv(t, d), y, block)

    def facing(self, m, du, dv):
        return m.facing(du, dv)


def _toward(ms, x, z):
    """The axis-aligned outward normal of the face of ms that looks toward (x, z)."""
    fr = ms.fr
    U, V = fr.U[ms.mask], fr.V[ms.mask]
    cu, cv = (float(U.min()) + float(U.max())) / 2, (float(V.min()) + float(V.max())) / 2
    u, v = fr.local_pt(x, z)
    du, dv = u - cu, v - cv
    if abs(du) >= abs(dv):
        return (1 if du > 0 else -1, 0)
    return (0, 1 if dv > 0 else -1)


def arches(m, fo, t0, t1, d, y0, h, block, stairs, open_d=()):
    """A row of round arches three blocks wide on piers one block wide, from t0 to t1, in the
    plane d out from the wall, from y0 up h blocks (the arch head in the last row but one,
    a lintel course in the last)."""
    t = t0
    while t + 4 <= t1 + 1e-6:
        for k in range(5):
            tt = t + k
            pier = k in (0, 4)
            for dy in range(h):
                y = y0 + dy
                if pier or dy == h - 1:
                    fo.put(m, tt, d, y, block)
                elif dy == h - 2 and k in (1, 3):
                    du, dv = fo.a
                    s = -1 if k == 1 else 1
                    fo.put(m, tt, d, y, CK.stair(stairs, m.facing(du * s, dv * s), "top"))
                else:
                    fo.put(m, tt, d, y, AIR)
                    for dd in open_d:
                        fo.put(m, tt, dd, y, AIR)
        t += 4


def gable(m, fo, t0, t1, d, y, rise, fill, edge):
    """A triangular gable in the plane of the face, d out from the wall."""
    u, v = fo.uv(0.0, d)
    if fo.n[0]:
        m.gable(t0, t1, u - 0.5, u + 0.5, y, rise, fill, edge=edge, axis="v")
    else:
        m.gable(t0, t1, v - 0.5, v + 0.5, y, rise, fill, edge=edge, axis="u")


class NationalTaiwanUniversity(Attraction):
    height_m = None
    margin = 8

    def __init__(self, item):
        super().__init__(item)
        F = self.features
        self.lib = self.feature(LIBRARY)
        self.gate = self.feature(GATE)
        self.bell = self.feature(BELL)
        roads = [f for f in F if f.get("line") and "highway" in f["tags"]]
        self.boulevard = [f["line"] for f in roads if f["tags"]["highway"] == "tertiary"]
        self.links = [(f["line"], LINK_W.get(f["tags"].get("lanes"), 6.0))
                      for f in roads if f["tags"]["highway"] == "tertiary_link"]
        widths = [float(f["tags"].get("width", ROAD_W)) for f in roads if f["tags"]["highway"] == "tertiary"]
        self.hw = (sum(widths) / len(widths) if widths else ROAD_W) / 2.0
        self.palms, self.cross_rows = self._palms()
        self.junipers = [tuple(f["point"]) for f in F if f["tags"].get("natural") == "tree"
                         and "niperus" in f["tags"].get("species", "")]
        self.lib_parts = self._library_parts()
        self.buildings = self._campus_buildings()
        self._lib_frame()

    # ---- Data ----
    def _palms(self):
        """Every royal palm node, plus the nodes of tree rows that no palm node stands on; a
        row mapped only by its two ends is planted every 5 m. Returns the palms and the
        two-node rows (the palm road that leaves the end of the boulevard northwards)."""
        pts = [tuple(f["point"]) for f in self.features if f["tags"].get("natural") == "tree"
               and "Roystonea" in f["tags"].get("species", "")]
        cross = []
        for f in self.features:
            if f["tags"].get("natural") != "tree_row" or not f.get("line"):
                continue
            line = f["line"]
            if len(line) == 2:
                cross.append(line)
                (x0, z0), (x1, z1) = line
                n = max(1, int(round(math.hypot(x1 - x0, z1 - z0) / 5.0)))
                line = [(x0 + (x1 - x0) * k / n, z0 + (z1 - z0) * k / n) for k in range(n + 1)]
            for x, z in line:
                if all(math.hypot(x - a, z - b) > 1.5 for a, b in pts):
                    pts.append((x, z))
        return pts, cross

    def _library_parts(self):
        """The library's building:parts: the parts at least half inside its outline."""
        cells = shapes.poly_cells(_outer(self.lib))
        out = []
        for f in self.features:
            if "building:part" not in f["tags"] or not f.get("outer"):
                continue
            c = shapes.poly_cells(_outer(f))
            if c and len(c & cells) >= 0.5 * len(c):
                out.append(f)
        return out

    def _campus_buildings(self):
        """The buildings along the boulevard: walls within NEAR_M of it, on the campus side
        of Xinsheng South Road (centered east of the gate) and short of the library.
        Canopies, greenhouses, substations and sheds are left out. Returns (feature,
        stories, heritage front or None)."""
        gx = min(p[0] for p in _outer(self.gate))
        lx = min(p[0] for p in _outer(self.lib))
        lines = self.boulevard + [l for l, _ in self.links]
        parts = [f for f in self.features if "building:part" in f["tags"] and f.get("outer")]
        out = []
        for f in self.features:
            t = f["tags"]
            if ("building" not in t or not f.get("outer") or f["osm"] in (LIBRARY, GATE) or f["osm"] in SKIP
                    or t["building"] in ("roof", "service", "greenhouse", "warehouse")
                    or f["area"] < 60):
                continue
            ring = _outer(f)
            xs = np.array([p[0] for p in ring])
            zs = np.array([p[1] for p in ring])
            if f["centroid"][0] < gx - 10 or xs.max() > lx - 2:
                continue
            if min(float(line_dist(xs, zs, l).min()) for l in lines) > NEAR_M:
                continue
            n = _levels(t)
            if f["osm"] in HERITAGE:
                # All three are two stories (the Administration Building's OSM outline takes
                # in its 1970s additions and is tagged with four).
                n = 2
            elif n is None:
                cells = shapes.poly_cells(ring)
                inside = [_levels(p["tags"]) for p in parts
                          if (int(p["centroid"][0]), int(p["centroid"][1])) in cells]
                inside = [k for k in inside if k]
                n = max(inside) if inside else (2 if f["area"] >= 150 else 1)
            out.append((f, min(n, 8), HERITAGE.get(f["osm"])))
        return out

    def _lib_frame(self):
        """The library's frame: u runs east into the building from its front, v south, and
        the origin sits on the axis of symmetry (the entrance hall's middle), on a cell
        center."""
        ring = _outer(self.lib)
        ang = CK.fit_angle(ring)
        self.lib_angle = 0.0 if abs(math.degrees(ang)) < 1.2 else ang
        front = min(p[0] for p in ring)
        ent = self.feature(ENTRANCE)
        zs = [p[1] for p in _outer(ent)] if ent else [self.lib["centroid"][1]]
        self.lib_origin = (math.floor(front) + 0.5, math.floor((min(zs) + max(zs)) / 2) + 0.5)

    # ---- Framework ----
    def bbox(self):
        pts = list(_outer(self.lib)) + list(_outer(self.gate)) + list(self.palms)
        for line in self.boulevard:
            pts += [(x, z - 24) for x, z in line] + [(x, z + 24) for x, z in line]
        for line, _ in self.links:
            pts += line
        for f, _, _ in self.buildings:
            pts += _outer(f)
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        m = self.margin
        return (int(math.floor(min(xs))) - m, int(math.floor(min(zs))) - m,
                int(math.ceil(max(xs))) + m, int(math.ceil(max(zs))) + m)

    def _lib_frame_obj(self, extent):
        return Frame(self.lib_origin[0], self.lib_origin[1], self.lib_angle, extent)

    def plan(self, site):
        x0, z0, x1, z1 = self.bbox()
        self.fa = fa = Frame((x0 + x1) / 2.0, (z0 + z1) / 2.0, 0.0, max(x1 - x0, z1 - z0) / 2.0)
        X, Z = fa.X + 0.5, fa.Z + 0.5
        # The boulevard: the road, a curb, the lawn strip the palms stand in, a footpath.
        d = None
        for line in self.boulevard:
            s = line_dist(X, Z, line)
            d = s if d is None else np.minimum(d, s)
        hw = self.hw
        road = d <= hw
        for line, wd in self.links:
            road |= line_dist(X, Z, line) <= wd / 2.0
        # The palm road north from the end of the boulevard, between its two rows.
        if len(self.cross_rows) == 2:
            (a0, a1), (b0, b1) = self.cross_rows
            mid = [((a0[0] + b0[0]) / 2, (a0[1] + b0[1]) / 2), ((a1[0] + b1[0]) / 2, (a1[1] + b1[1]) / 2)]
            gap = math.hypot(a0[0] - b0[0], a0[1] - b0[1])
            south = max(mid, key=lambda p: p[1])
            north = min(mid, key=lambda p: p[1])
            end = (south[0], self.lib_origin[1] + 26)
            road |= line_dist(X, Z, [north, south, end]) <= gap / 2.0 - 2.5
        curb = ~road & (d <= hw + 0.7)
        lawn = ~road & ~curb & (d <= hw + 3.5)
        walk = ~road & ~curb & ~lawn & (d <= hw + 6.5)
        self.lawn = lawn
        # Before the library: a red sandstone forecourt, the long lawn between the rows of
        # dragon junipers with the palms outside them, and the red plaza at the front.
        lib = self._lib_frame_obj(1)
        u_lib, v_lib = self._local(fa, lib)
        east = max(p[0] for l in self.boulevard for p in l)
        area = (u_lib >= (east - self.lib_origin[0]) - 1) & (u_lib < 0) & (np.abs(v_lib) <= 25) & ~road
        vj = self._plaza_rows(self.junipers)
        long_lawn = fa.empty()
        if len(vj) >= 2:
            long_lawn = area & (u_lib > -106) & (u_lib < -34) & (v_lib >= min(vj) - 1.5) & (v_lib <= max(vj) + 1.5)
        plaza = area & ~long_lawn
        lib_poly = fa.polygon(_outer(self.lib))
        court = self._court(u_lib, v_lib) & ~lib_poly
        self.court = court
        # Buildings and the library's parts
        self.masses = []
        for f, n, front in self.buildings:
            fr = own_frame(_outer(f))
            hip = front is not None or (n <= 2 and f["tags"].get("building") == "university"
                                        and f["area"] >= 300)
            st = OLD_STORY if front else STORY
            self.masses.append(mass_on(fr, f, stories(n, st), hip=hip, front=front,
                                       wall=BRICK if f["osm"] == ADMINISTRATION else TILE))
        self.lib_fr = self._lib_frame_obj(110)
        self.lib_masses = []
        for f in sorted(self.lib_parts, key=lambda f: (_levels(f["tags"]) or 1, -f["area"])):
            n = _levels(f["tags"]) or 1
            self.lib_masses.append(mass_on(self.lib_fr, f, stories(n, OLD_STORY),
                                           hip=f["osm"] in CORNERS))
        foot = fa.empty()
        for ms in self.masses + self.lib_masses:
            foot |= self._on(fa, ms)
        foot |= lib_poly | fa.polygon(_outer(self.gate))
        # Small things on their own: Fu Bell, the trees, round the gate.
        spots = fa.empty()
        pts = [(tuple(self.bell["point"]), 5)] + [(p, 2) for p in self.junipers] + [(p, 1) for p in self.palms]
        for (px, pz), r in pts:
            i, j = int(math.floor(pz)) - fa.z0, int(math.floor(px)) - fa.x0
            spots[max(0, i - r):i + r + 1, max(0, j - r):j + r + 1] = True
        spots |= kit.dilate(fa.polygon(_outer(self.gate)), 8)
        # The forecourt: the way in and the way out meet Roosevelt Road at one node, so
        # together they ring the guardhouse; what they enclose is paved, not lawn.
        ring = self._link_ring()
        fore = (fa.polygon(ring) & ~road) if len(ring) >= 3 else fa.empty()
        pool = self._pool(fa)
        # Grading: every paved, planted or built cell is brought to one level G, the median
        # of the ground along the boulevard (the campus is flat).
        self.yard = road | curb | lawn | walk | area | court | kit.dilate(foot, 2) | spots | fore | pool
        sample = (road | area) & (fa.X % 4 == 0) & (fa.Z % 4 == 0)
        gs = [site.g(x, z) for x, z in zip(fa.X[sample].tolist(), fa.Z[sample].tolist())]
        self.G = self.g0 = int(np.round(np.median(gs))) if gs else 64
        self.gnd = site.grid(fa, self.yard)
        self.cat = np.zeros(fa.shape, dtype=np.int8)       # What goes on top of each yard cell
        for k, msk in ((1, lawn | spots | long_lawn), (2, walk | fore), (3, curb), (4, road),
                       (5, plaza), (7, court), (8, kit.dilate(foot, 2) & ~road & ~area), (9, pool)):
            self.cat[msk & self.yard] = k
        self._spots = self._make_spots()

    def _local(self, fa, fr):
        """Local (u, v) in frame fr of every cell of frame fa."""
        dx = fa.X + 0.5 - fr.cx
        dz = fa.Z + 0.5 - fr.cz
        return dx * fr.c + dz * fr.s, -dx * fr.s + dz * fr.c

    def _plaza_rows(self, pts):
        """The rows of trees before the library, as v in the library frame."""
        fr = self._lib_frame_obj(1)
        vs = []
        for x, z in pts:
            u, v = fr.local_pt(x, z)
            if -110 < u < -30 and abs(v) < 26:
                vs.append(round(v))
        rows = []
        for v in sorted(set(vs)):
            if vs.count(v) >= 4 and all(abs(v - r) > 2 for r in rows):
                rows.append(v)
        return rows

    def _court(self, u, v):
        """The northern courtyard: the notch in the library's outline north of the front
        block, in front of the north wing (the caller takes the outline itself away)."""
        fr = self._lib_frame_obj(1)
        L = [fr.local_pt(x, z) for x, z in _outer(self.lib)]
        vmin = min(p[1] for p in L)
        front_v = min(p[1] for p in L if p[0] < 3.0)           # North end of the front
        return (u >= 0) & (u < 70) & (v >= vmin) & (v < front_v)

    def _link_ring(self):
        """The gate's way in and way out chained end to end into one ring (empty if they do
        not close)."""
        lines = [list(l) for l, _ in self.links]
        if not lines:
            return []
        ring = lines.pop(0)
        close = lambda p, q: math.hypot(p[0] - q[0], p[1] - q[1]) < 1.0
        while lines:
            for i, l in enumerate(lines):
                if close(ring[-1], l[0]):
                    ring += l[1:]
                elif close(ring[-1], l[-1]):
                    ring += l[::-1][1:]
                else:
                    continue
                lines.pop(i)
                break
            else:
                return []
        return ring[:-1] if close(ring[0], ring[-1]) else []

    def _pool(self, fa):
        """The Administration Building's square pool, on its axis halfway between its front
        and Fu Bell (the pool's size and exact place are not published)."""
        self.pool_c = None
        adm = next((ms for ms in self.masses if ms.osm == ADMINISTRATION), None)
        if adm is None:
            return fa.empty()
        bx, bz = self.bell["point"]
        fo = Front(adm, _toward(adm, bx, bz))
        px, pz = adm.fr.world(*fo.uv(0.0, 4.0))
        cx, cz = (px + bx) / 2.0, (pz + bz) / 2.0
        self.pool_c = (cx, cz, adm.fr)
        dx, dz = fa.X + 0.5 - cx, fa.Z + 0.5 - cz
        u = dx * adm.fr.c + dz * adm.fr.s
        v = -dx * adm.fr.s + dz * adm.fr.c
        return (np.abs(u) <= POND_HALF) & (np.abs(v) <= POND_HALF)

    def _on(self, fa, ms):
        """A mass's mask moved onto frame fa."""
        out = fa.empty()
        X, Z = ms.fr.X[ms.mask], ms.fr.Z[ms.mask]
        i, j = Z - fa.z0, X - fa.x0
        ok = (i >= 0) & (i < fa.shape[0]) & (j >= 0) & (j < fa.shape[1])
        out[i[ok], j[ok]] = True
        return out

    def _center_z(self, x):
        """z of the boulevard's center line at x."""
        for line in self.boulevard:
            for (x0, z0), (x1, z1) in zip(line, line[1:]):
                if min(x0, x1) <= x <= max(x0, x1) and x0 != x1:
                    return z0 + (z1 - z0) * (x - x0) / (x1 - x0)
        return sum(p[1] for l in self.boulevard for p in l) / sum(len(l) for l in self.boulevard)

    def _make_spots(self):
        """The default viewpoint stands on the long lawn on the library's axis, 70 m out,
        facing the entrance hall. A second, near the gate end of the boulevard, looks down
        it."""
        G = self.G
        fr = self._lib_frame_obj(1)
        sx, sz = fr.cell(-70.0, 0.0)
        tx, tz = fr.world(12.0, 0.0)
        yaw, pitch = kit.look(sx, G + 1, sz, tx, G + 14, tz)
        spots = [Spot("", sx, G + 1, sz, yaw, pitch, self.name_zh, self.name_en)]
        west = min((p for l in self.boulevard for p in l), key=lambda p: p[0])
        east = max((p for l in self.boulevard for p in l), key=lambda p: p[0])
        gx = int(math.floor(west[0] + 30))
        gz = int(math.floor(self._center_z(gx + 0.5)))
        yaw, pitch = kit.look(gx, G + 1, gz, east[0], G + 8, east[1])
        spots.append(Spot("gate", gx, G + 1, gz, yaw, pitch, "椰林大道", "Royal Palm Boulevard"))
        return spots

    def plaque(self):
        return [self.name_zh, self.name_en, "1928 年創校", "傅鐘每次響 21 聲"]

    def plaque_en(self):
        return ["Founded in 1928", "Founded 1928"]

    # ---- Build ----
    def build(self, w):
        self._grounds(w)
        for ms in self.masses:
            m = build_mass(w, ms, self.G)
            if ms.front:
                self._heritage_front(m, ms)
        self._library(w)
        self._sunken_court(w)
        self._trees(w)
        self._lamps(w)
        self._gate(w)
        self._fu_bell(w)
        self._signs(w)

    def _grounds(self, w):
        fa, G = self.fa, self.G
        top = {1: GRASS, 2: WALK, 3: CURB, 4: ROAD, 5: PLAZA, 7: FLOOR, 8: FLOOR, 9: WATER}
        grid = ((fa.X % 8) == 0) | ((fa.Z % 8) == 0)
        pool = self.cat == 9
        rim = pool & ~kit.erode(pool, 1)
        yd = self.yard
        s = w.set
        for x, z, gy, c, gr, rm in zip(fa.X[yd].tolist(), fa.Z[yd].tolist(), self.gnd[yd].tolist(),
                                       self.cat[yd].tolist(), grid[yd].tolist(), rim[yd].tolist()):
            for y in range(max(gy + 1, G - 8), G):
                s(x, y, z, FILL)
            for y in range(G + 1, max(gy, G) + 13):
                s(x, y, z, AIR)
            blk = top.get(c, GRASS)
            if c == 5 and gr:
                blk = PLAZA_LINE
            if c == 9 and rm:
                s(x, G, z, TRIM)
                s(x, G + 1, z, CK.slab(TRIM_SLAB))
                continue
            s(x, G, z, blk)

    def _trees(self, w):
        """Royal palms, azaleas in the lawn strips, and the dragon junipers."""
        G = self.G
        s = w.set
        fa = self.fa
        az = self.lawn & (self.cat == 1)
        for x, z in zip(fa.X[az].tolist(), fa.Z[az].tolist()):
            hh = _hash(x, z)
            if hh % 5 == 0:
                s(x, G + 1, z, AZALEAS[hh // 5 % 2])
        for x, z in self.palms:
            bx, bz = int(math.floor(x)), int(math.floor(z))
            hh = _hash(bx, bz)
            trunk = PALM_TRUNK_M[0] + hh % (PALM_TRUNK_M[1] - PALM_TRUNK_M[0] + 1)
            s(bx, G, bz, PIT)
            for y in range(G + 1, G + trunk + 1):
                s(bx, y, bz, PALM_TRUNK)
            y0 = G + trunk + 1
            for y in range(y0, y0 + 3):
                s(bx, y, bz, PALM_SHAFT)
            yc = y0 + 3
            # The crown: a spear leaf up the middle and eight fronds that rise, arch over
            # and droop (royal palm fronds are 3–5 m long).
            for y in range(yc, yc + 3):
                s(bx, y, bz, PALM_LEAF)
            rot = hh % 2
            for k in range(8):
                dx, dz = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)][(k + rot) % 8]
                prof = (1, 1, 0, -1, -2) if dx == 0 or dz == 0 else (1, 0, -1, -2)
                for r, dy in enumerate(prof, 1):
                    s(bx + dx * r, yc + dy, bz + dz * r, PALM_LEAF)
                if dx and dz:
                    s(bx + dx, yc + 1, bz, PALM_LEAF)
                    s(bx, yc + 1, bz + dz, PALM_LEAF)
        for x, z in self.junipers:
            bx, bz = int(math.floor(x)), int(math.floor(z))
            s(bx, G, bz, GRASS)
            for k, r in enumerate((1.2, 1.2, 1.0, 0.8, 0.5)):
                for dx in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        if math.hypot(dx, dz) <= r + 0.2:
                            s(bx + dx, G + 1 + k, bz + dz, JUNIPER)

    def _lamps(self, w):
        """Lamp posts along the outer edge of both footpaths, one every 24 m."""
        G, hw = self.G, self.hw
        for line in self.boulevard:
            t = 12.0                                   # Distance to the next lamp
            for a, b in zip(line, line[1:]):
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                if L < 1e-6:
                    continue
                ux, uz = (b[0] - a[0]) / L, (b[1] - a[1]) / L
                while t < L:
                    for side in (-1, 1):
                        x = a[0] + ux * t - uz * side * (hw + 6.0)
                        z = a[1] + uz * t + ux * side * (hw + 6.0)
                        bx, bz = int(math.floor(x)), int(math.floor(z))
                        for y in range(G + 1, G + 4):
                            w.set(bx, y, bz, POST)
                        w.set(bx, G + 4, bz, LANTERN)
                    t += 24.0
                t -= L

    # ---- The buildings along the boulevard ----
    def _heritage_front(self, m, ms):
        """The published fronts, on the face toward the boulevard, centered: the Old Main
        Library's porch of three arches with a balustrade, the College of Liberal Arts' two
        tiers of three arches, and the Administration Building's four columns rising two
        stories under a pediment; each with a gable over the middle of the front."""
        G = self.G
        x, z = self._nearest_on_boulevard(ms)
        fo = Front(ms, _toward(ms, x, z))
        f1, top = ms.floors[1], ms.floors[-1]
        if ms.front in ("porch", "loggia"):
            for t in range(-6, 7):
                for d in (1, 2, 3):
                    fo.put(m, t, d, G, MARBLE)
                    for y in range(G + 1, G + f1):
                        fo.put(m, t, d, y, AIR)
            arches(m, fo, -6, 6, 3, G + 1, f1, TRIM, TRIM_STAIRS)
            for d in (1, 2):
                for side in (-6, 6):
                    for y in range(G + 1, G + f1 + 1):
                        fo.put(m, side, d, y, TRIM)
            for t in range(-6, 7):
                for d in (1, 2, 3):
                    fo.put(m, t, d, G + f1, TRIM)
            for t in range(-1, 2):                      # The door
                for d in (0, -1):
                    for y in range(G + 1, G + 4):
                        fo.put(m, t, d, y, AIR)
            if ms.front == "loggia":
                arches(m, fo, -6, 6, 3, G + f1 + 1, top - f1, TRIM, TRIM_STAIRS)
                for d in (1, 2):
                    for side in (-6, 6):
                        for y in range(G + f1 + 1, G + top + 1):
                            fo.put(m, side, d, y, TRIM)
                for t in range(-6, 7):
                    for d in (1, 2, 3):
                        fo.put(m, t, d, G + top, TRIM)
                        fo.put(m, t, d, G + top + 1, CK.slab(TRIM_SLAB))
            else:
                for t in range(-6, 7):
                    fo.put(m, t, 3, G + f1 + 1, RAIL)
                for d in (1, 2):
                    for side in (-6, 6):
                        fo.put(m, side, d, G + f1 + 1, RAIL)
        else:
            # Four columns in two pairs, two stories, under an entablature and a low pediment.
            for t in range(-6, 7):
                for d in (1, 2, 3):
                    fo.put(m, t, d, G, MARBLE)
                    fo.put(m, t, d, G + top, TRIM)
            for t in (-5, -3, 3, 5):
                for y in range(G + 1, G + top):
                    fo.put(m, t, 3, y, B + "cut_sandstone" if y < G + top - 1 else PANEL)
            gable(m, fo, -6.5, 6.5, 3, G + top + 1, 2.0, TRIM, TRIM_STAIRS)
            for t in range(-1, 2):
                for d in (0, -1):
                    for y in range(G + 1, G + 4):
                        fo.put(m, t, d, y, AIR)
        gable(m, fo, -6.5, 6.5, 0, G + top + 1, 4.0, ms.wall, TRIM_STAIRS)

    def _nearest_on_boulevard(self, ms):
        fr = ms.fr
        U, V = fr.U[ms.mask], fr.V[ms.mask]
        cx, cz = fr.world((float(U.min()) + float(U.max())) / 2, (float(V.min()) + float(V.max())) / 2)
        best = None
        for line in self.boulevard:
            for (x0, z0), (x1, z1) in zip(line, line[1:]):
                L = (x1 - x0) ** 2 + (z1 - z0) ** 2
                t = max(0.0, min(1.0, ((cx - x0) * (x1 - x0) + (cz - z0) * (z1 - z0)) / L)) if L else 0.0
                p = (x0 + t * (x1 - x0), z0 + t * (z1 - z0))
                dd = math.hypot(p[0] - cx, p[1] - cz)
                if best is None or dd < best[0]:
                    best = (dd, p)
        return best[1]

    # ---- The Main Library ----
    def _library(self, w):
        G = self.G
        for ms in self.lib_masses:
            if ms.osm == PODIUM:
                self._podium(w, ms)
            elif ms.osm == TOWER:
                self._tower(w, ms)
            else:
                rect = ms.osm not in PAVILIONS + CORNERS
                m = CK.Mason(w, ms.fr)
                build_mass(w, ms, G, pattern=tiled(m, ms.floors, arch=not rect),
                           roof=GLASS if ms.osm == SPINE else ROOF)
                if ms.osm == ENTRANCE:
                    self._entrance(m, ms)
                elif ms.osm == MAIN_BLOCK:
                    self._great_gable(m, ms)
                elif ms.osm in PAVILIONS:
                    fo = Front(ms, (-1, 0))
                    V = ms.fr.V[ms.mask]
                    gable(m, fo, float(V.min()) - 0.5, float(V.max()) + 0.5, 0,
                          G + ms.floors[-1] + 1, 2.0, TILE, TRIM_STAIRS)

    def _podium(self, w, ms):
        """The entrance platform, one story across the front. In the middle of its front,
        the entrance arcade: three brick arches on granite piers, the middle one tallest,
        and one arch in a pale stone bay either side. Elsewhere tiled wall with windows.
        Above, a parapet of pierced panels."""
        G = self.G
        m = CK.Mason(w, ms.fr)
        top = 5
        wall = tiled(m, [0, top], arch=False)

        def arcade(t, h, layer):
            a = abs(round(t))
            if h == top:
                return TRIM
            if a in (2, 6):
                return PIER
            if a >= 7:
                c = 10 if round(t) > 0 else -10
                k = round(t) - c
                if abs(k) <= 1 and h <= 3:
                    if h == 3 and k:
                        return CK.stair(PIER_STAIRS, m.facing(0, 1 if k > 0 else -1), "top")
                    return AIR
                return TRIM
            c = 0 if a <= 1 else (4 if round(t) > 0 else -4)
            k = round(t) - c
            head = 4 if c == 0 else 3
            if h < head or (h == head and k == 0):
                return AIR
            if h == head:
                return CK.stair(PIER_STAIRS, m.facing(0, 1 if k > 0 else -1), "top")
            return TILE

        def pattern(face, t, h, layer, u, v, q):
            if h > top:
                if layer:
                    return None
                return PANEL if round(t) % 2 == 0 else TRIM
            if face == (-1, 0) and abs(t) <= 12.5:
                return arcade(t, h, layer)
            return wall(face, t, h, layer, u, v, q)

        m.fill(ms.mask, G, G, FLOOR)
        m.fill(kit.erode(ms.mask, 2), G + 1, G + top - 1, AIR)
        m.facade(ms.mask, G + 1, G + top + 1, pattern, base=G, corners=ms.corners)
        m.fill(kit.erode(ms.mask, 2), G + top, G + top, ROOF)
        m.fill(kit.ring(ms.mask), G + top + 2, G + top + 2, CK.slab(TRIM_SLAB))

    def _entrance(self, m, ms):
        """The entrance hall: over the podium, the great arched window, four stories high,
        in dark glazing bars with a semicircular fanlight, framed by pale stone pilasters
        and a pale stone pediment; a slim arched window either side; the doors behind the
        arcade."""
        G = self.G
        fo = Front(ms, (-1, 0))
        top = ms.floors[-1]
        R, spring = 4.5, top - 5
        for t in range(-5, 6):
            head = spring + math.sqrt(max(0.0, R * R - t * t)) if abs(t) <= 4 else spring
            for h in range(6, top):
                if abs(t) == 5 or h > head + 0.5:
                    blk = TRIM
                elif h == 6 or h == spring or t in (-3, 0, 3) or (h - 6) % 4 == 0:
                    blk = FRAME
                else:
                    blk = GLASS
                fo.put(m, t, 0, G + h, blk)
                if abs(t) < 5 and h <= head + 0.5:
                    fo.put(m, t, -1, G + h, AIR)
        for t in (-7, 7):
            for h in range(8, top - 3):
                fo.put(m, t, 0, G + h, AIR if h < top - 4 else CK.stair(TRIM_STAIRS, m.facing(0, 1), "top"))
                fo.put(m, t, -1, G + h, GLASS)
        U, V = ms.fr.U[ms.mask], ms.fr.V[ms.mask]
        gable(m, fo, float(V.min()) - 0.5, float(V.max()) + 0.5, 0, G + top + 1, 4.0, TRIM, TRIM_STAIRS)
        for t in range(-2, 3):
            for d in (0, -1):
                for h in range(1, 5):
                    fo.put(m, t, d, G + h, AIR)

    def _great_gable(self, m, ms):
        """Over the main block's front, the larger low brick gable with a round window."""
        G = self.G
        fo = Front(ms, (-1, 0))
        y = G + ms.floors[-1] + 1
        gable(m, fo, -12.5, 12.5, 0, y, 5.0, TILE, TRIM_STAIRS)
        fo.put(m, 0, 0, y + 2, GLASS)
        for t, dy in ((-1, 2), (1, 2), (0, 1), (0, 3)):
            fo.put(m, t, 0, y + dy, TRIM)

    def _tower(self, w, ms):
        """The bell tower, rising from the sunken courtyard to about twice the height of the
        north wing: tiled, with pale stone corners and bands, a round-arched doorway onto
        the courtyard, a tall round-headed opening in each face, and an open belvedere on
        corner piers under a flat top."""
        g0 = self.G - SUNK
        m = CK.Mason(w, ms.fr)
        F = TOWER_FLOORS
        top = F[-1]
        U, V = ms.fr.U[ms.mask], ms.fr.V[ms.mask]
        cu, cv = (float(U.min()) + float(U.max())) / 2.0, (float(V.min()) + float(V.max())) / 2.0

        def pattern(face, t, h, layer, u, v, q):
            tc = t - (cv if face[0] else cu)
            a = abs(tc)
            du, dv = m.along(face)
            s = 1 if tc > 0 else -1
            if h > top:
                return TILE if layer == 0 else None
            if h == top or h in (F[2], F[5], F[8] - 1):
                return TRIM
            if q is not None and q < 1.2:
                return TRIM
            if h == 1:
                return PLINTH if layer == 0 else TILE
            if a < 1.5:
                if face == (-1, 0) and h <= 4:          # The doorway onto the courtyard
                    if h == 4 and a >= 0.5:
                        return CK.stair(TRIM_STAIRS, m.facing(du * s, dv * s), "top")
                    return AIR
                if F[3] <= h <= F[7]:                   # The tall opening
                    if h == F[7] and a >= 0.5:
                        return CK.stair(TILE_STAIRS, m.facing(du * s, dv * s), "top")
                    return GLASS if layer else AIR
                if F[8] <= h < top:                     # The belvedere
                    if h == top - 1 and a >= 0.5:
                        return CK.stair(TRIM_STAIRS, m.facing(du * s, dv * s), "top")
                    return AIR
            return TILE

        tower = Mass(ms.fr, ms.mask, F, ms.corners, ms.osm)
        build_mass(w, tower, g0, pattern=pattern)

    def _sunken_court(self, w):
        """The courtyard on the north side, one story down: a red sandstone floor, tiled
        retaining walls with a railing where the ground is open, and steps down from the
        plaza at its west end."""
        G, fa = self.G, self.fa
        court = self.court
        if not court.any():
            return
        s = w.set
        for x, z in zip(fa.X[court].tolist(), fa.Z[court].tolist()):
            s(x, G - SUNK, z, PLAZA)
            for y in range(G - SUNK + 1, G + 1):
                s(x, y, z, AIR)
        edge = kit.dilate(court, 1) & ~court
        lib_poly = fa.polygon(_outer(self.lib))
        fr = self._lib_frame_obj(1)
        u, v = self._local(fa, fr)
        vs = v[court]
        vmid = (float(vs.min()) + float(vs.max())) / 2.0
        steps = court & (u < SUNK - 1) & (np.abs(v - vmid) <= 5)
        open_edge = edge & ~lib_poly & ~((u < 0) & (np.abs(v - vmid) <= 5.5))
        for x, z in zip(fa.X[edge].tolist(), fa.Z[edge].tolist()):
            for y in range(G - SUNK, G):
                s(x, y, z, TILE)
        for x, z in zip(fa.X[open_edge].tolist(), fa.Z[open_edge].tolist()):
            s(x, G, z, TRIM)
            s(x, G + 1, z, RAIL)
        up = CK.stair(TRIM_STAIRS, fr.facing(-1, 0))
        for x, z, uu in zip(fa.X[steps].tolist(), fa.Z[steps].tolist(), u[steps].tolist()):
            k = int(math.floor(uu))                     # 0, 1, 2 from the top
            y = G - 1 - k
            for yy in range(G - SUNK, y):
                s(x, yy, z, TILE)
            s(x, y, z, up)

    # ---- The gate and Fu Bell ----
    def _gate(self, w):
        """The main gate: the guardhouse about 4 m high on a stepped stone base, tiled, with
        louvred windows in its bowed front under the stone band with the university's name,
        a flat top with a stepped stone cap and a flagpole; either side, a gate across the
        way in or out (footway, carriageway, footway) closed off by a rusticated stone pier
        with a lamp and a low brick wall, and a stone lamp stand by the guardhouse."""
        G = self.G
        ring = _outer(self.gate)
        fr = own_frame(ring, margin=3)
        ms = mass_on(fr, self.gate, [0, 4])
        m = CK.Mason(w, fr)
        L = [CK.to_local(fr, x, z) for x, z in ring]
        us, vs = [p[0] for p in L], [p[1] for p in L]
        long_u = (max(us) - min(us)) >= (max(vs) - min(vs))
        # The bowed front is the end nearer the forecourt's outer point (Roosevelt Road).
        link = self._link_ring()
        far = min(link, key=lambda p: p[0]) if link else (ring[0][0] - 20, ring[0][1])
        fu, fv = CK.to_local(fr, *far)
        front_sgn = 1 if (fu if long_u else fv) > 0 else -1

        def pattern(face, t, h, layer, u, v, q):
            if h == 1:
                return STONE
            if h == 4:
                return TRIM                              # The name band and cap
            if h == 5:
                return TRIM if layer == 0 else None      # The cap's step
            end = (u if long_u else v) * front_sgn
            ext = (max(us) if front_sgn > 0 else -min(us)) if long_u else (max(vs) if front_sgn > 0 else -min(vs))
            if layer == 0 and h == 2 and end > ext - 2.5 and (q is None or q >= 1.0):
                return B + "iron_bars"                  # The louvred windows of the front
            return TILE

        m.fill(kit.dilate(ms.mask, 1), G, G, STONE2)
        m.fill(ms.mask, G, G, FLOOR)
        m.facade(ms.mask, G + 1, G + 5, pattern, base=G, corners=ms.corners)
        m.fill(kit.erode(ms.mask, 2), G + 4, G + 4, ROOF)
        m.fill(kit.ring(ms.mask), G + 6, G + 6, CK.slab(TRIM_SLAB))
        # Flagpole on a stepped plinth
        cu, cv = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
        m.at(cu, cv, G + 5, TRIM)
        m.at(cu, cv, G + 6, CK.slab(TRIM_SLAB))
        for y in range(G + 7, G + 13):
            m.at(cu, cv, y, B + "iron_bars")
        # The name band on the bowed front
        nu, nv = ((max(us) + 1.0 if front_sgn > 0 else min(us) - 1.0), cv) if long_u else \
            (cu, (max(vs) + 1.0 if front_sgn > 0 else min(vs) - 1.0))
        sx, sz = fr.cell(nu, nv)
        bx, bz = fr.cell(cu, cv)
        w.sign(sx, G + 4, sz, ["國立臺灣大學", "National Taiwan", "University", ""],
               facing=(sx - bx, sz - bz), wood="dark_oak", kind="wall", glow=True, color="white")
        # The gates: where each way crosses the line through the guardhouse's middle,
        # square to its length.
        c = fr.world(cu, cv)
        tdir = fr.dir(0, 1) if long_u else fr.dir(1, 0)
        s = w.set
        for line, wd in self.links:
            p = self._cross(line, c, tdir)
            if p is None:
                continue
            off = (p[0] - c[0]) * tdir[0] + (p[1] - c[1]) * tdir[1]
            sg = 1 if off > 0 else -1
            out = abs(off) + wd / 2.0 + 2.0 + 1.0            # Outer pier, beyond the far footway
            near = abs(off) - wd / 2.0 - 1.5                  # Lamp stand, on the near footway
            for k, (dist, kind) in enumerate(((out, "pier"), (near, "stand"))):
                px, pz = c[0] + tdir[0] * sg * dist, c[1] + tdir[1] * sg * dist
                bx, bz = int(math.floor(px)), int(math.floor(pz))
                if kind == "pier":
                    for dx in (0, 1):
                        for dz in (0, 1):
                            for y in range(G + 1, G + 4):
                                s(bx + dx, y, bz + dz, STONE if y % 2 else STONE2)
                            s(bx + dx, G + 4, bz + dz, CK.slab(TRIM_SLAB))
                    s(bx, G + 5, bz, LANTERN)
                    for r in range(2, 8):                     # The low brick wall beyond
                        wx = int(math.floor(px + tdir[0] * sg * r))
                        wz = int(math.floor(pz + tdir[1] * sg * r))
                        for y in range(G + 1, G + 3):
                            s(wx, y, wz, BRICK)
                        s(wx, G + 3, wz, CK.slab(TRIM_SLAB))
                else:
                    for y in range(G + 1, G + 3):
                        s(bx, y, bz, STONE)
                    s(bx, G + 3, bz, LANTERN)

    @staticmethod
    def _cross(line, c, tdir):
        """Where a polyline crosses the line through c along tdir (the first crossing)."""
        nx, nz = -tdir[1], tdir[0]
        side = [(x - c[0]) * nx + (z - c[1]) * nz for x, z in line]
        for (p, q), a, b in zip(zip(line, line[1:]), side, side[1:]):
            if a == 0:
                return p
            if a * b < 0:
                k = a / (a - b)
                return (p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k)
        return None

    def _fu_bell(self, w):
        """Fu Bell: a round platform of pale stone with a compass mark and eight short posts
        round its edge, a step up on the boulevard side, and on it the maroon iron frame of
        four posts, hooped twice and curving in at the top to the disc the bell hangs
        from."""
        G = self.G
        x, z = self.bell["point"]
        bx, bz = int(math.floor(x)), int(math.floor(z))
        s = w.set
        for dx in range(-4, 5):
            for dz in range(-4, 5):
                if math.hypot(dx, dz) <= 3.6:
                    s(bx + dx, G + 1, bz + dz, MARBLE)
        for dx, dz in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            s(bx + dx, G + 1, bz + dz, B + "smooth_quartz")
        for k in range(8):
            a = math.radians(22.5 + 45 * k)
            s(bx + int(round(3.2 * math.cos(a))), G + 2, bz + int(round(3.2 * math.sin(a))),
              B + "andesite_wall")
        for dx in (-1, 0, 1):                               # The step, on the north side
            s(bx + dx, G + 1, bz - 4, CK.stair("polished_diorite_stairs", "south"))
        ring = {(1, 1): dict(west=True, north=True), (-1, 1): dict(east=True, north=True),
                (1, -1): dict(west=True, south=True), (-1, -1): dict(east=True, south=True),
                (0, 1): dict(east=True, west=True), (0, -1): dict(east=True, west=True),
                (1, 0): dict(north=True, south=True), (-1, 0): dict(north=True, south=True)}
        for y in range(G + 2, G + 7):
            for (dx, dz), joins in ring.items():
                if dx and dz:
                    s(bx + dx, y, bz + dz, fence(**joins) if y in (G + 3, G + 5) else fence())
                elif y in (G + 3, G + 5):
                    s(bx + dx, y, bz + dz, fence(**joins))
        for (dx, dz) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            toward = {(1, 0): "west", (-1, 0): "east", (0, 1): "north", (0, -1): "south"}[(dx, dz)]
            s(bx + dx, G + 7, bz + dz, fence(**{toward: True}))
        s(bx, G + 7, bz, B + "mangrove_planks")
        s(bx, G + 6, bz, BELL_BLOCK)

    def _signs(self, w):
        """A sign at each viewpoint that takes you to the other end of the boulevard."""
        main, gate = self._spots[0], self._spots[1]
        for here, there, lines in ((main, gate, ["椰林大道 校門端 ▶", "To the gate end", "", ""]),
                                   (gate, main, ["總圖書館 ▶", "To the Main Library", "", ""])):
            fx, fz = -math.sin(math.radians(here.yaw)), math.cos(math.radians(here.yaw))
            lx, lz = fz, -fx                                   # To the viewer's left
            sx, sz = here.x + int(round(lx * 2)), here.z + int(round(lz * 2))
            w.sign(sx, here.y, sz, lines, facing=(here.x - sx, here.z - sz), wood="pale_oak",
                   kind="standing", glow=True,
                   command="function %s:%s" % (config.DATAPACK_NS,
                                               kit.sight_fn(self.id, there.key)))


BUILDS = {"national_taiwan_university": NationalTaiwanUniversity}
