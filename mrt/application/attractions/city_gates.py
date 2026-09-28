#!/usr/bin/env python3
"""The four surviving gates of the Taipei Prefecture city wall: the North Gate (Cheng'en
Gate), East Gate (Jingfu Gate), South Gate (Lizheng Gate) and Little South Gate (Chongxi
Gate).

Location, orientation and gate platform outline follow OSM (the historic=city_gate ways);
the appearance follows public sources and photographs:

  North Gate
         Completed in the 10th year of the Guangxu reign (1884), and the only one of the
         four gates that keeps its original Qing appearance. A closed, fortress-style gate
         tower: a gate platform of andesite ashlar laid in alternating courses, with a
         central round-arched passage (the outer arch is smaller than the inner one, with a
         rectangular door chamber between them). The upper storey has red brick walls; the
         outer north wall has three openings, two square and one round, and above the arch
         a horizontal name board reads Cheng'en Gate. Single-eaved xieshan roof, red tiles,
         and a ridge that curls up at both ends. Inside the upper floor a second, inner wall forms
         a square-within-a-square plan (zh.wikipedia, "North Gate of Taipei Prefecture
         City"; Ministry of Culture, National Cultural Memory Bank, "Taipei Prefecture City:
         North Gate").
  East Gate, South Gate, Little South Gate
         In 1966 the Taipei City Government, citing the need to tidy the cityscape, rebuilt
         the gate towers as reinforced-concrete buildings in the northern Chinese palace
         style; only the stone gate platforms and passages remain original Qing work
         (zh.wikipedia, the article on each gate; Bureau of Cultural Heritage, panoramic
         tour of national monuments, "Taipei Prefecture City: East Gate, South Gate, Little
         South Gate, North Gate"). In photographs all three have a gray ashlar gate
         platform, a ring of white crenellations on top of it, red columns on the gate
         tower, blue-green painted decoration and dougong brackets under the eaves, a
         single-eaved xieshan roof, green glazed tiles, and yellow ridges and chiwen.
         The Little South Gate's tower is an open hall with a colonnade all round
         (colonnaded style); on the back (the city side) its balustrade is patterned in red
         brick.
         The East, South and Little South Gates all stand on roundabouts or traffic islands,
         with lawns, clipped shrubs and stone planters around the gate platform.

Dimensions: the platform's length and width follow the OSM outline. The South Gate's OSM
outline, 33.8 × 19.5 m, is nearly twice the platform measured from photographs (in
photographs the arch is about 0.27 of the platform width, as at the East Gate), so the
outline was presumably drawn to include the stone planters and lawn at the four corners.
The platform is taken as 18.5 × 13.5 m, centered, and the rest of the outline becomes
planters and lawn. Heights (platform about 5 m, ridge 12–15 m) are measured from
photographs in proportion to the platform width; there are no official figures.

Data: all four gates in data/attractions.json name their OSM way (historic=city_gate):
North Gate way/238316480, East Gate way/209580573, South Gate way/245993047, Little South
Gate way/246651384. (The original catalog center points of the East, South and Little
South Gates were 146–348 m off, and the fetch returned other buildings nearby. This came to
light only when the world was read back after building the gates; the catalog now names
these three ways.)
"""
import math

import numpy as np

from mrt.application.attractions import kit
from mrt.application.attractions import trad_parts as TP
from mrt.application.attractions.kit import Attraction, Frame, Painter, Spot

AIR = kit.AIR

# ---- Materials ----
RED_WALL = "minecraft:red_terracotta"          # North Gate upper-storey brick wall (vermilion in photographs)
BRICK = "minecraft:bricks"
RED_COL = "minecraft:red_concrete"             # Red columns of the palace-style gate towers
TAN_WALL = "minecraft:smooth_sandstone"        # Wall between the columns (pale yellow in photographs)
BEAM = "minecraft:warped_planks"               # Blue-green ground of the painted architrave
BEAM_PANEL = "minecraft:prismarine_bricks"     # Central panel of the painted decoration (a pale frame)
SOFFIT = "minecraft:dark_prismarine"           # Dougong brackets and rafters under the eaves
GOLD = "minecraft:honeycomb_block"             # Yellow ridges, chiwen, bargeboards
WHITE = "minecraft:white_concrete"             # Crenellations on top of the gate platform
WHITE_TRIM = "minecraft:smooth_quartz"
DARK_RIDGE = "minecraft:polished_deepslate"    # The North Gate's dark gray ridge
PAVE = "minecraft:polished_andesite"
PAVE2 = "minecraft:smooth_stone"
GRASS = "minecraft:grass_block"
HEDGE = "minecraft:azalea_leaves[distance=1,persistent=true,waterlogged=false]"
HEDGE2 = "minecraft:flowering_azalea_leaves[distance=1,persistent=true,waterlogged=false]"
CONIFER = "minecraft:spruce_leaves[distance=1,persistent=true,waterlogged=false]"

# Ashlar of the gate platform: two sets of gray tones, alternating by course and by block
# (andesite ashlar laid in a staggered bond).
STONE_DARK = ("minecraft:tuff_bricks", "minecraft:polished_tuff", "minecraft:stone_bricks")
STONE_LIGHT = ("minecraft:stone_bricks", "minecraft:andesite", "minecraft:polished_andesite")


def _hash(x, y, z):
    return ((x * 73856093) ^ (y * 19349663) ^ (z * 83492791)) & 0xFFFF


def ashlar(x, y, z, mix):
    """Material of the ashlar: blocks 2–3 cells long in each course, with joints staggered
    between courses; three gray tones in turn."""
    course = y % 2
    blk = (x + z + course) // 3
    return mix[_hash(blk, y, course) % len(mix)]


def rect_frame(ring, outer):
    """OSM outline -> (center x, z, angle, half-length a, half-width b): u runs along the
    city wall (the long side) and v along the passage, with the outside of the city (the
    outer side, world direction (dx, dz)) toward -v."""
    ang = kit.principal_angle(ring)
    for _ in range(4):
        c, s = math.cos(ang), math.sin(ang)
        vx, vz = -s, c                                   # World direction of the v axis
        ux, uz = c, s
        if abs(outer[0] * ux + outer[1] * uz) > abs(outer[0] * vx + outer[1] * vz):
            ang += math.pi / 2                           # The passage must run along v
            continue
        if outer[0] * vx + outer[1] * vz > 0:
            ang += math.pi                               # The outside of the city must be toward -v
            continue
        break
    c, s = math.cos(ang), math.sin(ang)
    cx0 = sum(p[0] for p in ring) / len(ring)
    cz0 = sum(p[1] for p in ring) / len(ring)
    us = [(x - cx0) * c + (z - cz0) * s for x, z in ring]
    vs = [-(x - cx0) * s + (z - cz0) * c for x, z in ring]
    um, vm = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
    cx, cz = cx0 + um * c - vm * s, cz0 + um * s + vm * c
    return cx, cz, ang, (max(us) - min(us)) / 2, (max(vs) - min(vs)) / 2


class CityGate(Attraction):
    """The common frame of a city gate: gate platform, passage, surrounding ground and
    viewpoint. Subclasses build the upper part."""

    osm = None                 # id of the gate's way
    outer = (0, -1)            # World direction of the outside of the city (the side with the name board)
    base_half = None           # Overrides the platform's half-length and half-width (a, b); None follows OSM
    base_h = 5                 # Platform height (blocks)
    stone = STONE_DARK
    passage = (4.0, 2.4)       # Passage width and springing height (meters)
    view_dist = 22             # Distance from the viewpoint to the platform's outer wall (meters)
    plaque_text = ""
    fact_lines = ("", "")      # The two fact lines on the plaque (each must fit the 90 px sign width)
    fact_en = ()               # The first fact in English, fullest first (see Attraction.plaque_en)
    margin = 16

    def __init__(self, item):
        super().__init__(item)
        f = self.feature(self.osm) if self.osm else None
        if f and f.get("outer"):
            self.ring = [tuple(p) for p in max(f["outer"], key=len)]
        else:
            # The data has no way for this gate (an old attractions.json): build a
            # standard-size platform at the catalog center point, so at least the whole
            # world build does not stop.
            cx, cz = self.item["center"]
            self.ring = [(cx - 9, cz - 7), (cx + 9, cz - 7), (cx + 9, cz + 7), (cx - 9, cz + 7)]
        self.cx, self.cz, self.ang, self.ra, self.rb = rect_frame(self.ring, self.outer)
        self.a, self.b = self.base_half or (self.ra, self.rb)

    # ---- Location: always from the gate's OSM outline (the catalog center point may be off) ----
    def outline(self):
        return list(self.ring)

    def center(self):
        return (sum(p[0] for p in self.ring) / len(self.ring),
                sum(p[1] for p in self.ring) / len(self.ring))

    def plaque(self):
        return [self.name_zh, self.name_en, self.fact_lines[0], self.fact_lines[1]]

    def plaque_en(self):
        return list(self.fact_en)

    # ---- Planning ----
    def plan(self, site):
        ext = max(self.ra, self.rb, self.a, self.b) + self.margin + 2
        self.fr = fr = Frame(self.cx, self.cz, self.ang, ext)
        self.base = fr.box(self.a, self.b)
        self.g0 = site.level(fr, self.base)
        self.hb = self.g0 + self.base_h                 # The block at the top of the platform
        self.site = site
        self.ground = self._ground_mask()
        # Grading needs the ground height of every cell. cli discards the terrain distance
        # field after plan (looking it up during build fails), so look it up here once;
        # Site keeps it in its cache.
        site.grid(fr, self.ground)
        self._spots = [self._pick_spot(site)]

    def _ground_mask(self):
        """Grading area: a rectangle with cut corners a few meters beyond the platform (the
        traffic island or plaza)."""
        return self.fr.chamfer(self.a + 7, self.b + 7, 4)

    def _pick_spot(self, site):
        """View the gate from the pavement straight in front of it on the outside of the city,
        view_dist meters from the platform. A candidate in the keep-out zone (MRT exits) or
        in the grading area is skipped for the next; if none works, try the city side."""
        fr = self.fr
        cands = []
        for side in (-1, 1):
            for d in (self.view_dist, self.view_dist + 5, self.view_dist - 5, self.view_dist + 10):
                for lat in (0.0, -4.0, 4.0, -8.0, 8.0):
                    cands.append((lat, side * (self.b + d)))
        keep = site.keep
        for u, v in cands:
            x, z = fr.cell(u, v)
            i, j = z - fr.z0, x - fr.x0
            if 0 <= i < fr.shape[0] and 0 <= j < fr.shape[1] and self.ground[i, j]:
                continue
            gy = site.g(x, z)
            pad = self._pad_cells(x, z, u, v)
            if keep is not None and any(keep(px, gy + dy, pz) for px, pz in pad for dy in (0, 1, 2)):
                continue
            ty = self.g0 + 1 + (self.height_m or 12) * 0.45
            yaw, pitch = kit.look(x, gy + 1, z, self.cx, ty, self.cz)
            self._pad = (pad, gy)
            return Spot("", x, gy + 1, z, yaw, pitch, self.name_zh, self.name_en)
        x, z = fr.cell(0, -(self.b + self.view_dist))
        gy = site.g(x, z)
        self._pad = (self._pad_cells(x, z, 0, -(self.b + self.view_dist)), gy)
        yaw, pitch = kit.look(x, gy + 1, z, self.cx, self.g0 + 5, self.cz)
        return Spot("", x, gy + 1, z, yaw, pitch, self.name_zh, self.name_en)

    def _pad_cells(self, x, z, u, v):
        """A small pad under the viewpoint: the cell the player stands in, the plaque 2 blocks
        to their right, and one cell around them."""
        out = set()
        for dx in range(-2, 3):
            for dz in range(-2, 3):
                out.add((x + dx, z + dz))
        return out

    # ---- Building ----
    def build(self, w):
        p = Painter(w, self.fr)
        self._build_ground(w, p)
        self._build_base(p)
        self._build_passage(p)
        self._build_upper(p)
        self._build_pad(p)

    def _build_ground(self, w, p):
        fr = self.fr
        self.site.prepare(w, fr, self.ground, self.g0, top=GRASS)
        # A ring of paving stones around the foot of the platform
        walk = kit.dilate(self.base, 1) & ~self.base
        p.layer(walk, self.g0, PAVE)

    def _build_base(self, p):
        """Gate platform: solid ashlar up to hb, paved on top."""
        fr = self.fr
        s = p.w.set
        for x, z in fr.cells(self.base):
            for y in range(self.g0, self.hb + 1):
                s(x, y, z, ashlar(x, y, z, self.stone))

    def _passage_segments(self):
        """The passage in segments along v: [(v0, v1, width, springing height, arched)]. By
        default one segment runs right through."""
        w, sp = self.passage
        return [(-self.b - 1, self.b + 1, w, sp, True)]

    def _build_passage(self, p):
        fr = self.fr
        Ua = np.abs(fr.U)
        # Paving: the passage plus a stone path extending 4 m in front and behind
        road = (Ua <= self.passage[0] / 2 + 0.6) & (np.abs(fr.V) <= self.b + 4)
        p.layer(road & ~self.base, self.g0, PAVE2)
        for v0, v1, w, sp, arched in self._passage_segments():
            sel = (fr.V >= v0) & (fr.V < v1) & (Ua <= w / 2 + 1.0) & self.base
            face = sel & (np.abs(fr.V) >= self.b - 1.0)
            if arched:
                TP.cut_arch(p, sel, Ua, self.g0 + 1, w, sp,
                            wall_facing=lambda i, j: fr.facing(1 if fr.U[i, j] > 0 else -1, 0),
                            stair_block="stone_brick", ring=face, ring_block="minecraft:chiseled_stone_bricks",
                            ceil_y=self.hb)
            else:
                h = min(int(round(sp)), self.hb - self.g0 - 1)
                for x, z in fr.cells(sel & (Ua <= w / 2 + 0.05)):
                    for y in range(self.g0 + 1, self.g0 + 1 + h):
                        p.set(x, y, z, AIR)
            p.layer(sel & (Ua <= w / 2 + 0.05), self.g0, "minecraft:stone_bricks")

    def _build_upper(self, p):
        raise NotImplementedError

    def _build_pad(self, p):
        pad, gy = self._pad
        for x, z in pad:
            p.set(x, gy, z, PAVE2 if (x + z) % 2 else PAVE)
            p.set(x, gy + 1, z, AIR)
            p.set(x, gy + 2, z, AIR)

    # ---- Shared small parts ----
    def wall_plaque(self, p, u, v, y, text, board="minecraft:polished_blackstone", width=3,
                    wood="dark_oak", color="#E8C15A", facing_v=-1):
        """Name board: a dark board width blocks wide on the wall, with a sign hung in the
        middle for the inscription (gold characters)."""
        for k in range(width):
            du = k - (width - 1) / 2.0
            p.at(u + du, v, y, board)
        TP.plaque_sign(p, u, v, y, (0, facing_v), ["", dict(text=text, color=color, bold=True), "", ""],
                       wood=wood, glow=True)

    def _gables(self, p, tops, a, b, gin, fill, border):
        """Gable pediments at both ends of a xieshan roof: built up from the end slope to the
        height of the long slopes, with a bargeboard as the top block."""
        fr = self.fr
        for su in (-1, 1):
            cells = (su * fr.U > a - gin) & (su * fr.U <= a - gin + 1.0) & (np.abs(fr.V) < b - gin + 0.3)

            def ytop(i, j, su=su):
                t = TP.top_at(tops, fr, su * (a - gin - 0.6), float(fr.V[i, j]))
                return (t if t is not None else tops[i, j])
            TP.gable_face(p, cells, tops, ytop, fill, border=border)

    def _hip_ridges(self, p, tops, a, b, gin, block, curl=1):
        """Vertical ridges (along the sloping edges of the pediments) and diagonal ridges
        (toward the four eave corners) of a xieshan roof, with the tips turning up and out
        by curl blocks. Cells are picked by distance from the ridge line (one block wide),
        and the height follows the roof below."""
        fr = self.fr
        for su in (-1, 1):
            for sv in (-1, 1):
                ug = su * (a - gin + 0.3)
                # Vertical ridge: rides on the pediment's sloping edge (the bargeboard),
                # following the height of the long slope
                m, _ = TP.seg_mask(fr, ug, 0.0, ug, sv * (b - gin))
                for i, j in np.argwhere(m):
                    t = TP.top_at(tops, fr, su * (a - gin - 0.6), float(fr.V[i, j]))
                    if t is not None:
                        p.set(int(fr.X[i, j]), t + 1, int(fr.Z[i, j]), block)
                # Diagonal ridge: from the foot of the pediment toward the eave corner, one
                # block above the roof in each cell
                u1, v1 = su * (a - 0.4), sv * (b - 0.4)
                m, tt = TP.seg_mask(fr, ug, sv * (b - gin), u1, v1)
                end = None
                for i, j in np.argwhere(m & (tops > -999)):
                    y = int(tops[i, j]) + 1
                    p.set(int(fr.X[i, j]), y, int(fr.Z[i, j]), block)
                    if end is None or tt[i, j] > end[0]:
                        end = (float(tt[i, j]), i, j, y)
                if end is not None:
                    _, i, j, y = end
                    x, z = int(fr.X[i, j]), int(fr.Z[i, j])
                    for c in range(1, curl + 1):                 # The tip at the eave corner turns up
                        p.set(x, y + c, z, block)


# ================================================================ North Gate: original Qing form

class Beimen(CityGate):
    """North Gate (Cheng'en Gate): fortress-style gate tower, red brick walls, single-eaved
    xieshan roof in red tiles, dark gray swallowtail ridge.

    Measurements (from photographs, scaled by the 15 m platform width): platform about
    5.3 m high, red upper walls about 4.7 m, ridge about 12.5 m, and the upturned ridge
    ends reach 14 m. The north passage is about 3.6 m clear width and about 4.3 m high. The
    two square windows in the outer wall are about 1.1 × 1.3 m, the round window between
    them about 1.3 m across, with sills about 7 m above the ground. The Cheng'en Gate name
    board sits directly above the crown of the arch, at the bottom edge of the red wall."""

    osm = "way/238316480"
    outer = (0, -1)                     # The name board is on the north (outer) face
    base_h = 5
    stone = STONE_DARK
    height_m = 14.0
    view_dist = 20
    fact_lines = ("1884 年 · 清代原貌", "四門裡唯一沒改建")
    fact_en = ("1884, in its original Qing form", "1884, unaltered")

    def _ground_mask(self):
        # North Gate plaza: the gate is surrounded by a paved plaza
        return self.fr.chamfer(self.a + 9, self.b + 9, 5)

    def _build_ground(self, w, p):
        fr = self.fr
        self.site.prepare(w, fr, self.ground, self.g0, top=PAVE)
        # Plaza paving: a pale dividing line every 4 m
        grid = ((np.floor(fr.U) % 4 == 0) | (np.floor(fr.V) % 4 == 0)) & self.ground
        p.layer(grid, self.g0, PAVE2)
        # A low stone step around the platform (open in front of and behind the passage)
        step = kit.dilate(self.base, 1) & ~self.base & ~(np.abs(fr.U) <= 2.6)
        p.layer(step, self.g0 + 1, TP.slab("smooth_stone"))

    def _passage_segments(self):
        # The outer arch (north) is smaller than the inner arch (south), with a rectangular
        # chamber for the doors between them (Bureau of Cultural Heritage tour)
        b = self.b
        return [(-b - 1, -b + 3.0, 3.6, 2.5, True),
                (-b + 3.0, -b + 5.5, 5.0, 4.0, False),
                (-b + 5.5, b + 1, 4.6, 2.4, True)]

    def _build_upper(self, p):
        fr = self.fr
        a, b, g0 = self.a, self.b, self.g0
        y0, y1 = self.hb + 1, self.hb + 5              # Red wall g0+6 .. g0+10
        shell = kit.ring(self.base)
        p.fill(shell, y0, y1, RED_WALL)
        inner = kit.erode(self.base, 1)
        p.clear(inner, y0, y1 - 1)
        p.layer(inner, y1, "minecraft:spruce_planks")   # Ceiling
        # The inner wall of the square-within-a-square plan (a second wall inside the upper
        # floor)
        in2 = kit.ring(fr.box(a - 2.6, b - 2.4))
        door = np.abs(fr.U) <= 1.0
        p.fill(in2 & ~door, y0, y1 - 1, BRICK)
        # North (outer) face: two square windows and one round; brick frames for the square
        # windows, a stone frame for the round one
        yw = g0 + 8
        for uw in (-3.7, 3.7):
            self._window(p, uw, -b, yw, frame=BRICK)
        self._window(p, 0.0, -b, yw, frame="minecraft:polished_andesite")
        # South face (city side) and the sides: square windows, and one arched window on
        # each side
        for uw in (-3.7, 3.7):
            self._window(p, uw, b, yw, frame=BRICK, inward=-1)
        for su in (-1, 1):
            # One arched window in the middle of each side (1 block wide, 2 high), framed in
            # brick
            uu = su * (a - 0.3)
            for dv, dy in ((0, 1), (0, -2), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
                p.at(uu, dv, yw + dy, BRICK)
            p.at(uu, 0, yw, AIR)
            p.at(uu, 0, yw - 1, AIR)
        # The Cheng'en Gate name board: directly above the crown of the north arch, at the
        # bottom edge of the red wall
        self.wall_plaque(p, 0.0, -b + 0.3, y0, "承恩門")
        self._roof(p)

    def _window(self, p, u, v, y, frame, inward=1):
        """A 1 × 1 window opening in the wall (through the one-block wall) with a frame
        around it."""
        fr = self.fr
        vv = v + 0.3 * inward
        for du in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if du == 0 and dy == 0:
                    continue
                p.at(u + du, vv, y + dy, frame)
        x, z = fr.cell(u, vv)
        p.set(x, y, z, AIR)

    def _roof(self, p):
        fr = self.fr
        a, b = self.a + 0.5, self.b + 0.5
        gin, rise, prof = 2.0, 1.9, 1.3
        y_eave = self.hb + 5                            # The ring at the eaves is level with the wall top
        mask = fr.box(a, b)
        h = kit.hip_gable(fr, a, b, rise, gin, profile=prof, lift=0.8)
        tops = TP.tile_roof(p, mask, y_eave, h, TP.ORANGE_TILES, shell=2,
                            under="minecraft:spruce_planks", under_mask=mask & ~self.base)
        # Gable pediments: red wall, with brick bargeboards
        self._gables(p, tops, a, b, gin, RED_WALL, BRICK)
        # Main ridge: dark gray, curling up at both ends (in photographs the ends turn up and
        # project past the gable walls)
        ridge_y = max(t for t in (TP.top_at(tops, fr, u, 0) for u in np.arange(-a + gin, a - gin, 1.0)) if t) + 1
        TP.swallowtail(p, a - gin, ridge_y + 0.5, DARK_RIDGE, ext=1.0, rise=1.4, body=1)
        # Vertical ridges (along the sloping edges of the pediments) and diagonal ridges (to
        # the four eave corners), each tip turned up one block
        self._hip_ridges(p, tops, a, b, gin, DARK_RIDGE, curl=1)


# ================================================================ The 1966 northern palace-style gate towers

class PalaceGate(CityGate):
    """East Gate, South Gate, Little South Gate: gray ashlar platform, white crenellations,
    red-columned gate tower, and a single-eaved xieshan roof in green glazed tiles."""

    stone = STONE_DARK
    pav = (7.0, 4.5)           # Half-length and half-width of the tower's column grid (meters)
    bays = (5, 3)              # Five bays wide, three bays deep
    col_h = 3                  # Column height (blocks): column tops about 8 m, eaves about 10 m (photographs)
    overhang = 2.3             # Eave overhang
    rise = 3.2
    gable_in = 2.4
    lift = 1.2
    open_hall = False          # Little South Gate: an open hall with a colonnade all round
    back_railing = False       # Little South Gate: patterned red brick balustrade on the city side
    planters = False           # Stone planters at the four corners (on the South and Little South Gate islands)
    garden = False             # Shrubs and trees on the traffic island (South Gate)
    fence = False              # Iron railing along the edge of the traffic island (East Gate)

    def _grid(self, n, half):
        """Column positions: the central bay is 1.3 times as wide, the others equal."""
        wts = [1.0] * n
        wts[n // 2] = 1.3
        tot = sum(wts)
        out, acc = [-half], -half
        for wv in wts:
            acc += 2 * half * wv / tot
            out.append(acc)
        return out

    def _build_ground(self, w, p):
        fr = self.fr
        self.site.prepare(w, fr, self.ground, self.g0, top=GRASS)
        walk = kit.dilate(self.base, 1) & ~self.base
        p.layer(walk, self.g0, PAVE)
        a, b, g0 = self.a, self.b, self.g0
        # Shrubs clipped into boxes on both sides of the passage (every gate has them beside
        # the arch in photographs)
        for su in (-1, 1):
            for sv in (-1, 1):
                hed = fr.box(1.3, 0.9, du=su * (self.passage[0] / 2 + 2.6), dv=sv * (b + 2.2))
                p.fill(hed, g0 + 1, g0 + 2, HEDGE)
        if self.garden:
            # Traffic island garden: a row of conifers clipped into columns in front of both
            # long faces of the platform (clear on either side of the arch), and a tree at
            # each corner (in photographs the South Gate is ringed by tall shrubs and large
            # trees)
            for sv in (-1, 1):
                row = fr.rect(-a + 1.0, a - 1.0, b + 1.2, b + 2.6) if sv > 0 else fr.rect(-a + 1.0, a - 1.0, -b - 2.6, -b - 1.2)
                row &= np.abs(fr.U) > self.passage[0] / 2 + 4.2
                p.fill(row, g0 + 1, g0 + 3, CONIFER)
            for su in (-1, 1):
                for sv in (-1, 1):
                    tu, tv = su * (a + 5.0), sv * (b + 1.2)
                    for y in range(g0 + 1, g0 + 4):
                        p.at(tu, tv, y, "minecraft:oak_log[axis=y]")
                    crown = fr.ellipse(2.3, 2.3, tu, tv)
                    p.fill(crown, g0 + 4, g0 + 5, HEDGE)
                    p.layer(fr.ellipse(1.3, 1.3, tu, tv), g0 + 6, HEDGE)
        if self.planters:
            for su in (-1, 1):
                for sv in (-1, 1):
                    du, dv = su * (a + 3.2), sv * (b + 3.0)
                    ring = fr.ellipse(2.4, 2.4, du, dv) & ~fr.ellipse(1.5, 1.5, du, dv)
                    core = fr.ellipse(1.5, 1.5, du, dv)
                    p.layer(ring, g0 + 1, "minecraft:stone_bricks")
                    p.layer(ring, g0 + 2, TP.slab("smooth_stone"))
                    p.layer(core, g0 + 1, "minecraft:dirt")
                    p.layer(core, g0 + 2, GRASS)
                    p.layer(fr.ellipse(0.9, 0.9, du, dv), g0 + 3, HEDGE2)
        if self.fence:
            # A low iron railing around the edge of the traffic island (OSM maps barrier=fence
            # around the East Gate), with gaps in line with the passage
            edge = kit.ring(self.ground) & ~(np.abs(fr.U) <= self.passage[0] / 2 + 0.6)
            cells = [(int(fr.X[i, j]), g0 + 1, int(fr.Z[i, j])) for i, j in np.argwhere(edge)]
            for (x, y, z), blk in TP.panes_conn(cells, "iron_bars").items():
                p.set(x, y, z, blk)

    def _build_upper(self, p):
        fr = self.fr
        a, b, hb = self.a, self.b, self.hb
        s = p.w.set
        # Top of the platform: the top layer is white (the base of the crenellations), with a
        # white coping projecting around the outer edge
        top_ring = kit.ring(self.base)
        p.layer(top_ring, hb, WHITE_TRIM)
        p.layer(kit.erode(self.base, 1), hb, PAVE)
        lip = kit.dilate(self.base, 1) & ~self.base
        p.layer(lip, hb, TP.slab("smooth_quartz", "top"))
        # Crenellations: the white top layer of the platform (the line above) is the body of
        # the parapet, and the block above holds the merlons: two merlons and one crenel in
        # every 3 cells (the crenel is a slab). In photographs the top of the parapet is
        # about 1 m above the top of the platform.
        for i, j in np.argwhere(top_ring):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            back = self.back_railing and fr.V[i, j] > b - 1.2
            if back:
                s(x, hb + 1, z, BRICK)
                if (x + z) % 2 == 0:
                    s(x, hb + 2, z, "minecraft:brick_wall[east=none,north=none,south=none,up=true,waterlogged=false,west=none]")
                continue
            c = TP.edge_coord(fr, i, j, a, b)
            k = math.floor(c) % 3
            s(x, hb + 1, z, WHITE if k == 0 else WHITE_TRIM if k == 1 else TP.slab("smooth_quartz"))
        # Name board: in the middle of the outer parapet
        self._parapet_plaque(p)
        # Gate tower
        self._pavilion(p)

    def _parapet_plaque(self, p):
        v = -self.b + 0.3
        y = self.hb + 1
        for du in (-1.5, -0.5, 0.5, 1.5):
            p.at(du, v, y, "minecraft:stripped_dark_oak_wood")
            p.at(du, v, y + 1, "minecraft:stripped_dark_oak_wood")
        # Name board: dark wooden frame, pale panel, dark gold characters (as on all three
        # gates' name boards in photographs)
        TP.plaque_sign(p, 0.0, v, y + 1, (0, -1),
                       ["", dict(text=self.plaque_text, color="#5A3A10", bold=True), "", ""],
                       wood="pale_oak", glow=False)

    def _pavilion(self, p):
        fr = self.fr
        hb = self.hb
        pa, pb = self.pav
        y0 = hb + 1
        yc = hb + self.col_h                            # Column tops
        yb = yc + 1                                     # Architrave
        y_eave = yb + 1                                 # The ring of tiles at the eaves
        us = self._grid(self.bays[0], pa)
        vs = self._grid(self.bays[1], pb)
        # Interior floor
        p.layer(fr.box(pa + 0.4, pb + 0.4), hb, "minecraft:polished_granite")
        # Walls: a ring set one and a half cells inside the column grid (doors in the middle
        # of the front and back); the Little South Gate encloses only the middle three bays
        if self.open_hall:
            wa, wb = (us[3] - us[2]) / 2 + 0.6, pb - 1.4
        else:
            wa, wb = pa - 1.3, pb - 1.3
        room = fr.box(wa, wb)
        wall = kit.ring(room)
        door = (np.abs(fr.U) <= 1.0)
        p.fill(wall & ~door, y0, yc, TAN_WALL)
        # Doors: a pair of vermilion double doors at front and back (the red lattice doors of
        # the central bay in photographs)
        for sv in (-1, 1):
            cells = wall & door & (np.sign(fr.V) == sv)
            fac = fr.facing(0, sv)
            for k, (x, z) in enumerate(sorted(fr.cells(cells))):
                hinge = "left" if k % 2 == 0 else "right"
                p.set(x, y0, z, "minecraft:mangrove_door[facing=%s,half=lower,hinge=%s,open=false,powered=false]" % (fac, hinge))
                p.set(x, y0 + 1, z, "minecraft:mangrove_door[facing=%s,half=upper,hinge=%s,open=false,powered=false]" % (fac, hinge))
                for y in range(y0 + 2, yc + 1):
                    p.set(x, y, z, "minecraft:red_terracotta")
        # Columns: all round the outer ring (1 × 1, vermilion)
        for i, u in enumerate(us):
            for j, v in enumerate(vs):
                if i in (0, len(us) - 1) or j in (0, len(vs) - 1):
                    for y in range(y0, yc + 1):
                        p.at(u, v, y, RED_COL)
        # Architrave: the ring at the column tops, blue-green, with a pale central panel in
        # the middle of each bay
        band = kit.ring(fr.box(pa + 0.5, pb + 0.5))
        for i, j in np.argwhere(band):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            c = TP.edge_coord(fr, i, j, pa + 0.5, pb + 0.5)
            grid = us if abs(fr.V[i, j]) >= pb - 0.2 else vs
            mid = any(abs(c - (q0 + q1) / 2) <= 0.8 for q0, q1 in zip(grid[:-1], grid[1:]))
            p.set(x, yb, z, BEAM_PANEL if mid else BEAM)
        p.layer(kit.erode(fr.box(pa + 0.5, pb + 0.5), 1), yb, "minecraft:spruce_planks")
        # Dougong brackets: a ring outside the architrave, alternating dark blue-green and
        # blue-green (one bracket set after another)
        br = fr.box(pa + 1.4, pb + 1.4) & ~fr.box(pa + 0.5, pb + 0.5)
        for i, j in np.argwhere(br):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            p.set(x, yb, z, SOFFIT if (x + z) % 2 else BEAM)
        # Roof: single-eaved xieshan, green glazed tiles, yellow ridges
        ra, rb = pa + self.overhang, pb + self.overhang
        gin = self.gable_in
        mask = fr.box(ra, rb)
        h = kit.hip_gable(fr, ra, rb, self.rise, gin, profile=1.7, lift=self.lift)
        tops = TP.tile_roof(p, mask, y_eave, h, TP.GREEN_TILES, shell=2, under=SOFFIT,
                            under_mask=mask & ~fr.box(pa + 0.5, pb + 0.5))
        self.tops = tops
        # Gable pediments: red, with yellow bargeboards and a white floral motif in the
        # center
        self._palace_gables(p, tops, ra, rb, gin)
        # Main ridge and chiwen
        L = ra - gin
        band = (np.abs(fr.V) < 0.5) & (np.abs(fr.U) <= L + 0.3) & (tops > -999)
        ry = int(tops[band].max()) + 1
        for i, j in np.argwhere(band):
            x, z = int(fr.X[i, j]), int(fr.Z[i, j])
            for y in range(int(tops[i, j]) + 1, ry + 1):
                p.set(x, y, z, GOLD)
        for su in (-1, 1):
            TP.chiwen(p, su * L, 0.0, ry, GOLD, inward=-su, h=2,
                      accent="minecraft:orange_terracotta")
        # Vertical and diagonal ridges (yellow), with the eave corners turned up one block
        self._hip_ridges(p, tops, ra, rb, gin, GOLD, curl=1)

    def _palace_gables(self, p, tops, a, b, gin):
        fr = self.fr
        for su in (-1, 1):
            cells = (su * fr.U > a - gin) & (su * fr.U <= a - gin + 1.0) & (np.abs(fr.V) < b - gin + 0.3)

            def ytop(i, j, su=su):
                t = TP.top_at(tops, fr, su * (a - gin - 0.6), float(fr.V[i, j]))
                return (t if t is not None else tops[i, j])
            TP.gable_face(p, cells, tops, ytop, RED_WALL, border=GOLD)
            # White floral motif: in the center of the pediment
            top = TP.top_at(tops, fr, su * (a - gin - 0.6), 0.0)
            bot = TP.top_at(tops, fr, su * (a - gin + 0.5), 0.0)
            if top is not None and bot is not None and top - bot >= 3:
                mid = (top + bot) // 2
                for dv, ys in ((0.0, (mid - 1, mid, mid + 1)), (-1.0, (mid,)), (1.0, (mid,))):
                    for y in ys:
                        p.at(su * (a - gin + 0.5), dv, y, WHITE_TRIM)


class Dongmen(PalaceGate):
    """East Gate (Jingfu Gate): platform from OSM (about 17.7 × 13.4 m), passage running east-
    west, name board on the east face (outside the city). Measured from photographs: platform
    about 4.7 m high, ridge about 14 m; the tower is five bays wide and three deep."""

    osm = "way/209580573"
    outer = (1, 0)
    stone = STONE_LIGHT                 # The East Gate's platform is a lighter gray in photographs
    base_h = 5
    pav = (7.0, 4.4)
    col_h = 3
    rise = 2.9
    height_m = 15.0
    passage = (4.2, 1.9)
    fence = True
    plaque_text = "景福門"
    fact_lines = ("1966 年改建宮殿式", "城座門洞是清代原物")
    fact_en = ("Rebuilt in 1966 in the palace style", "Rebuilt in 1966")


class Nanmen(PalaceGate):
    """South Gate (Lizheng Gate): the main and largest gate of Taipei Prefecture City.
    Platform 18.5 × 13.5 m (see the module notes), passage running north-south, name board
    on the south face. Ridge about 14.5 m."""

    osm = "way/245993047"
    outer = (0, 1)
    base_half = (9.25, 6.75)
    stone = STONE_DARK
    base_h = 5
    pav = (7.2, 4.6)
    col_h = 3
    rise = 3.1
    height_m = 15.5
    passage = (4.4, 1.9)
    planters = True
    garden = True
    plaque_text = "麗正門"
    fact_lines = ("1966 年改建宮殿式", "臺北府城的正門")
    fact_en = ("Rebuilt in 1966 in the palace style", "Rebuilt in 1966")

    def _ground_mask(self):
        # Grade the whole of the South Gate's OSM outline (the traffic island with its
        # planters and lawn)
        return self.fr.chamfer(max(self.ra, self.a + 7), max(self.rb, self.b + 7), 4)


class Xiaonanmen(PalaceGate):
    """Little South Gate (Chongxi Gate): faces Bangka to the southwest (the outside of the
    city lies west-southwest). Platform 13.4 × 12.4 m, about 4.8 m high; the tower is an
    open hall with a colonnade all round, ridge about 12.7 m; the balustrade on the city
    side is patterned red brick."""

    osm = "way/246651384"
    outer = (math.cos(math.radians(114.7)), math.sin(math.radians(114.7)))
    stone = STONE_DARK
    base_h = 5
    pav = (5.5, 3.9)
    col_h = 3
    rise = 2.6
    overhang = 2.1
    gable_in = 2.0
    height_m = 13.5
    passage = (3.2, 2.1)
    open_hall = True
    back_railing = True
    planters = True
    view_dist = 20
    plaque_text = "重熙門"
    fact_lines = ("1966 年改建宮殿式", "清代原是廊柱式城樓")
    fact_en = ("Rebuilt in 1966 in the palace style", "Rebuilt in 1966")


BUILDS = {"beimen": Beimen, "dongmen": Dongmen, "nanmen": Nanmen, "xiaonanmen": Xiaonanmen}
