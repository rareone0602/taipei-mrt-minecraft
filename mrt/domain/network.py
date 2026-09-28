#!/usr/bin/env python3
"""Network: the next station, the terminus a train heads for, and where on the
platform to board. These are the pure rules of the ride system.

The world holds 253 km of network, more than a player can cover on foot. The
ride system lets a player right-click a sign on a platform to "ride to the next
station": the datapack teleports the player to the platform for the same
direction of travel at the next station, standing right in front of the sign
for the onward journey. A few clicks in a row ride several stations.

All three of the following must match what the generator builds to the block,
so they are computed here, once:

  · **Direction of travel**: Taipei Metro runs on the right. A train heading
    +u along the sampling order uses the +off track (the same rule as
    ``stacked.upper_side``). On an island platform, the platform screen doors
    on the + side face trains heading +u. At a stacked station, upper_toward
    decides the level and the line decides the side.
  · **Position on the platform**: the sign stands in the row of platform screen
    doors (replacing that pane of glass, where the station-name sign used to
    be). The player stands two blocks in from it, facing the doors.
  · **Next station and terminus**: the stations are listed along the sampling
    order of each selected variant, and each adjacent pair is one ride. A
    branch of the same line naturally adds a third direction at the junction
    station (at Daqiaotou, trains toward Luzhou and toward Huilong use the
    same side platform, and each direction gets its own sign).

This layer knows nothing about Minecraft command syntax: a function id is only
a path ("ride/bl12_bl13"). The namespace lives in config, the command strings
are assembled by application, and the files are written by infrastructure.
"""
import math

from mrt.domain import stacked as SK
from mrt.domain.alignment import (
    PLATFORM_LEN, PLAT_HALF, STEP, structure_for_ground,
)

# Line names are factual data (the official line names of Taipei Metro, New
# Taipei Metro and Taoyuan Metro). Colors are not stored here: they come from
# the OSM `colour` tag in data/mc_lines.json (the same data as the network map
# in the README), which cli reads and passes to line_colours().
LINE_NAMES = {
    "BR": ("文湖線", "Wenhu Line"),
    "R":  ("淡水信義線", "Tamsui-Xinyi Line"),
    "G":  ("松山新店線", "Songshan-Xindian Line"),
    "O":  ("中和新蘆線", "Zhonghe-Xinlu Line"),
    "BL": ("板南線", "Bannan Line"),
    "Y":  ("環狀線", "Circular Line"),
    "A":  ("桃園機場捷運", "Taoyuan Airport MRT"),
    "K":  ("安坑輕軌", "Ankeng LRT"),
    "V":  ("淡海輕軌", "Danhai LRT"),
    "LB": ("三鶯線", "Sanying Line"),
}

# The OSM `colour` tag is sometimes a CSS color name (the Zhonghe-Xinlu Line
# uses "orange").
_CSS = {"orange": "#FFA500", "red": "#FF0000", "green": "#008000", "blue": "#0000FF",
        "yellow": "#FFFF00", "brown": "#A52A2A", "purple": "#800080"}

# Sign positions on the platform (meters from the lo end of the station box).
# The first is the primary position: a player who rides in from the previous
# station stands in front of the sign there. The positions avoid the two stairs
# of an island platform (24..34 and 48..58 m along the line, offsets −3..3) and
# the stairs at the hi end of a side platform (from 53 m at the earliest). They
# also must not fall on a door opening in the platform screen doors (a 2 m
# opening every 7 m along the line: the cells where along % 7 < 2 are air). The
# three underground positions are where the station-name signs used to be.
SLOTS_UNDER = (40, 20, 60)
SLOTS_SIDE = (37, 16, 51)
# When other structures take the first three positions (a tunnel of the
# Xiaobitan branch passes through the south end of Qizhang, and the viaduct of
# the Xinbeitou branch passes over one side platform at Beitou), these fill in
# order, up to three signs per side. They also avoid the stairs and the door
# openings. At a stacked station, the first 22 m hold the stairs between the
# two levels and their railings, so no position there is filled.
SLOTS_UNDER_MORE = (37, 45, 65, 13, 16, 10)
SLOTS_SIDE_MORE = (30, 23, 44, 9)
SLOTS_PER_SIDE = 3
DOOR_EVERY, DOOR_OPEN = 7.0, 2.0     # Same rhythm as the platform screen doors in build_line.
STAND_IN = 2          # Blocks in from the platform screen doors to where the player stands.
# How far ahead along the line (meters) to look when deciding whether a
# neighbor lies at +u or −u of the station box.
SEQ_AHEAD_M = 40.0


# ---------- Helpers ----------

def line_code(full_ref, ref):
    """The station code on line ref: "R10;BL12" on BL -> "BL12" (None if absent)."""
    for t in str(full_ref).split(";"):
        t = t.strip()
        if t.startswith(ref) and len(t) > len(ref) and t[len(ref)].isdigit():
            return t
    return None


def fn_code(code):
    """Station code -> lowercase code for function paths (datapack resource paths
    allow only a-z0-9_.-/)."""
    return "".join(ch for ch in code.lower() if ch.isalnum() or ch == "_")


# The route map dialog (the ticket machine signs, the hotkey and the pause menu
# all open this one) and each line's station list.
MENU_DIALOG = "network"


def line_dialog(ref):
    return "line/%s" % fn_code(ref)


def ride_fn(code_from, code_to):
    return "ride/%s_%s" % (fn_code(code_from), fn_code(code_to))


def go_fn(code):
    return "go/%s" % fn_code(code)


def turn_fn(code, d):
    """At a terminus, a click moves the player to the opposite platform (d is this
    side's direction in the station box's frame)."""
    return "turn/%s_%s" % (fn_code(code), "p" if d > 0 else "m")


def yaw_of(fx, fz):
    """Minecraft yaw for facing (fx, fz): 0 = south, 90 = west, 180 = north, -90 = east."""
    return round(math.degrees(math.atan2(-fx, fz)), 1)


def code_sort_key(code):
    """Natural sort key for station codes: G03 < G03A < G04, O21 < O50."""
    i = 0
    while i < len(code) and not code[i].isdigit():
        i += 1
    j = i
    while j < len(code) and code[j].isdigit():
        j += 1
    return (code[:i], int(code[i:j]) if j > i else 0, code[j:])


def line_colours(lines_json):
    """{line: "#rrggbb"}: each line takes the OSM `colour` of its longest variant.
    Branches often have their own color (the Xiaobitan and Xinbeitou branches,
    for example), and it must not replace the trunk's."""
    out = {}
    for ref, variants in lines_json.items():
        best = max(variants, key=lambda v: len(v.get("points", ())), default=None)
        c = str((best or {}).get("colour") or "#808080").strip()
        c = _CSS.get(c.lower(), c)
        if not c.startswith("#"):
            c = "#808080"
        out[ref] = c.upper()
    return out


# ---------- Station sequence and direction ----------

def _seq_of(sg):
    """The stations of a segment in sampling order: [(sample index, name,
    English name, station code string)].

    Uses stn_seq (the snapshot taken before deduplication). A station the branch
    shares with the trunk has already been removed from the branch segment by
    deduplication, but the fact that the branch starts at Qizhang must still be
    read from the branch's own sequence.
    """
    stn = sg.get("stn_seq", sg["stn"])
    return [(bi, v[1], v[2], v[0]) for bi, v in sorted(stn.items())]


class Station:
    """One station on one line (a transfer station has one on each line)."""

    def __init__(self, ref, name, en, code):
        self.ref, self.name, self.en, self.code = ref, name, en, code
        self.dirs = {}               # Neighbor name -> Direction.
        self.box = None              # Box: the built station box (None if not built).

    def __repr__(self):
        return "Station(%s %s)" % (self.code, self.name)


class Direction:
    """From a station toward one neighbor: next is the neighbor's name, and
    terminals are the terminus names of the variants in this direction."""

    def __init__(self, nxt):
        self.next = nxt
        self.terminals = []
        self.via = []                # [(segment index, sample index here, neighbor's sample index)]
        self.d = 0                   # +u (1) or -u (-1) in the station box's frame.

    def __repr__(self):
        return "Direction(->%s to %s d=%+d)" % (self.next, "/".join(self.terminals), self.d)


# English station names in mc_stations.csv are occasionally flawed; fix them
# before they appear on signs.
_EN_FIX = {"Taipei main station": "Taipei Main Station"}


def display_en(en):
    """English station name for display, without parenthetical notes (such as
    "(Under construction)" on Guangci/Fengtian Temple)."""
    en = _EN_FIX.get(en, en)
    if "(" in en:
        en = en[:en.index("(")].rstrip()
    return en


def build_network(segs):
    """{(line, name): Station}, with each station's directions and termini toward
    each neighbor."""
    # The English name field is occasionally Chinese (Dapinglin on the Circular
    # Line). If a station of the same name on another line has an English name,
    # borrow it.
    en_of = {}
    for sg in segs:
        for _, name, en, _ in _seq_of(sg):
            if any("a" <= ch.lower() <= "z" for ch in en):
                en_of.setdefault(name, en)
    net = {}
    for li, sg in enumerate(segs):
        ref = sg["ref"]
        seq = _seq_of(sg)
        if not seq:
            continue
        first, last = seq[0][1], seq[-1][1]
        for k, (bi, name, en, full) in enumerate(seq):
            code = line_code(full, ref) or full
            st = net.get((ref, name))
            if st is None:
                st = net[(ref, name)] = Station(ref, name, display_en(en_of.get(name, en)), code)
            for kk, term in ((k - 1, first), (k + 1, last)):
                if not (0 <= kk < len(seq)):
                    continue
                nb = seq[kk][1]
                dr = st.dirs.get(nb)
                if dr is None:
                    dr = st.dirs[nb] = Direction(nb)
                if term not in dr.terminals:
                    dr.terminals.append(term)
                dr.via.append((li, bi, seq[kk][0]))
    return net


# ---------- Station boxes and platforms ----------

class Box:
    """A built station box, in the same coordinates as the generator
    (build_line.build_station):

    samples  sample points in the station box's frame (for a shared stacked
             station, the frame of the centerline between the two lines)
    ys       rail top (a shared station box uses the primary's; the two lines
             are pinned to the same values anyway)
    lo, hi   sample indices of the station box's extent
    kind     "island" underground island platform, "side" elevated or at-grade
             side platforms, "stacked_side" stacked side platforms,
             "stacked_shared" stacked island platform shared by two lines
    """

    def __init__(self, li, bi, samples, ys, kind, lay=None, side=0):
        n = len(samples)
        half = int(PLATFORM_LEN / 2 / STEP)
        self.li, self.bi = li, bi
        self.samples, self.ys = samples, ys
        self.lo, self.hi = max(0, bi - half), min(n - 1, bi + half)
        self.kind, self.lay, self.side = kind, lay, side
        self.lines = []              # Lines that stop at this station box.

    @property
    def key(self):
        return (self.li, self.bi)

    def center(self):
        x, z = self.samples[self.bi][:2]
        return x, z

    def cell(self, i, off):
        """The block (x, z) at sample i and offset off, rounded exactly as
        build_line rounds it."""
        x, z, ux, uz, _ = self.samples[i]
        nx, nz = -uz, ux
        return round(x + nx * off), round(z + nz * off)

    def normal(self, i):
        x, z, ux, uz, _ = self.samples[i]
        return -uz, ux


def find_boxes(segs):
    """{(line, name): Box}: the station box that each station of each line
    stops at.

    An ordinary station is the one left in sg["stn"]. The partner of a shared
    stacked station no longer has a station on its own segment
    (stacked.plan_shared removes it); it stops in the station box the primary
    builds.
    """
    out = {}
    for li, sg in enumerate(segs):
        ref = sg["ref"]
        for bi, (full, name, en) in sg["stn"].items():
            lay = sg.get("stacked", {}).get(bi)
            samples = SK.station_samples(sg, bi)
            if lay is not None:
                tr = lay["tracks"]
                if len(tr) == 1:
                    box = Box(li, bi, samples, sg["ys"], "stacked_side", lay,
                              side=-1 if tr[0] > 0 else 1)
                    box.lines.append(ref)
                    out[(ref, name)] = box
                else:
                    side = 1 if tr[1] > 0 else -1
                    box = Box(li, bi, samples, sg["ys"], "stacked_shared", lay, side=side)
                    box.lines.append(ref)
                    out[(ref, name)] = box
                    spec = SK.STACKED.get((name, ref), {})
                    pref = spec.get("partner")
                    if pref:
                        box.lines.append(pref)
                        out[(pref, name)] = box
                continue
            y, g = int(sg["ys"][bi]), int(sg["ground"][bi])
            kind = "island" if structure_for_ground(y, g) == "tunnel" else "side"
            box = Box(li, bi, samples, sg["ys"], kind)
            box.lines.append(ref)
            out[(ref, name)] = box
    return out


def _box_direction(box, segs, via):
    """Whether a direction (along segment li from sample i_here toward i_next)
    is +u or −u in the station box's frame.

    Takes the point SEQ_AHEAD_M meters ahead along the segment and checks the
    sign of its projection onto the tangent at the station box's center. It
    does not compare the two stations' coordinates directly, because the
    alignment may turn sharply between them. Nor does it compare tangents
    alone, because a branch's tangent at the junction station can differ
    greatly from the trunk's.
    """
    li, i_here, i_next = via
    sm = segs[li]["samples"]
    sgn = 1 if i_next > i_here else -1
    j = i_here + sgn * int(round(SEQ_AHEAD_M / STEP))
    j = max(0, min(len(sm) - 1, j))
    cx, cz, ux, uz, _ = box.samples[box.bi]
    dot = (sm[j][0] - cx) * ux + (sm[j][1] - cz) * uz
    if abs(dot) < 1e-6:
        dot = (sm[j][2] * ux + sm[j][3] * uz) * sgn
    return 1 if dot > 0 else -1


# ---------- Berths ----------

class Slot:
    """A ride sign on the platform and the berth in front of it.

    sign    the sign's block (x, y, z) (in the row of platform screen doors)
    face    the direction the sign faces (dx, dz): toward the berth
    stand   the block (x, y, z) of the player's feet
    yaw     the yaw that faces the sign's block from the berth (on a skewed
            alignment it differs by a few degrees from the doors' normal)
    dest    Direction (None = no next station on this side: the arrival side
            of a terminus)
    lang    "zh" / "en": signs for the same direction alternate between
            Chinese and English
    """

    def __init__(self, sign, face, stand, yaw, dest, lang):
        self.sign, self.face, self.stand, self.yaw = sign, face, stand, yaw
        self.dest, self.lang = dest, lang

    def __repr__(self):
        return "Slot(%s %s %s)" % (self.sign, self.lang, self.dest)


class Berth:
    """The platform edge for one line and one direction of travel in one station
    box: how many signs it has, and where each one goes."""

    def __init__(self, station, box, d, dy0, psd, inward):
        self.station, self.box, self.d, self.dy0 = station, box, d, dy0
        self.psd, self.inward = psd, inward      # Door offset; the platform's side of the doors (±1).
        self.dests = []
        self.slots = []

    @property
    def line(self):
        return self.station.ref

    def primary(self, dest_next=None):
        """The primary position: the first sign toward dest_next (the first sign
        on this side if dest_next is not given)."""
        for s in self.slots:
            if dest_next is None or (s.dest is not None and s.dest.next == dest_next):
                return s
        return self.slots[0] if self.slots else None

    def __repr__(self):
        return "Berth(%s %s d=%+d dy0=%d psd=%+d)" % (
            self.station.code, self.station.name, self.d, self.dy0, self.psd)


def _geometry(box, d):
    """(dy0, offset of the platform screen doors, the side of the doors the
    platform is on) for the platform edge toward d at an island or side
    platform station.

    Island: tracks at ±8, doors at ±6, the island in the middle (the platform
    is inside the doors).
    Side: tracks at ±3, doors at ±5, the platform at 6..10 (the platform is
    outside the doors).
    """
    if box.kind == "island":
        return 0, d * PLAT_HALF, -d
    return 0, d * (PLAT_HALF - 1), d


def _stacked_geometry(box, ref, d, upper_d):
    """Stacked station: the direction toward upper_toward is on the upper level,
    and the other direction is on the lower level."""
    dy0 = 0 if d == upper_d else -SK.LEVEL_H
    if box.kind == "stacked_side":
        psd = box.lay["psd"][0]
        # The platform is on the side of the doors nearer the station box's
        # centerline.
        return dy0, psd, -1 if psd > 0 else 1
    # Shared island: the primary line's track is at −side and the partner's at
    # +side, with the island in the middle.
    primary = ref == box.lines[0]
    psd = (-box.side if primary else box.side) * PLAT_HALF
    return dy0, psd, -1 if psd > 0 else 1


def _stand_cell(sx, sz, wx, wz):
    """The berth STAND_IN blocks from the sign's block toward the platform
    interior (unit vector (wx, wz)).

    Rounding the offsets psd and psd ± 2 separately does not work: on a skewed
    alignment the two offsets can round to adjacent blocks, and the player
    stands right against the sign (this happened at Zhongxiao Xinsheng, Ankang
    and Danfeng). Starting from the sign's block and scaling the step so that
    the major axis moves exactly STAND_IN blocks guarantees that the Chebyshev
    distance between berth and sign is STAND_IN.
    """
    m = max(abs(wx), abs(wz)) or 1.0
    return sx + int(round(wx / m * STAND_IN)), sz + int(round(wz / m * STAND_IN))


def plan_berths(segs, blocked=None):
    """Berths for the whole network. Returns (net, berths):

    net      the result of build_network, with each Station's box and each
             direction's d filled in
    berths   [Berth], one per station box, line and direction (including a
             direction without a station: the arrival side of a terminus gets
             a terminus sign that moves the player to the opposite platform)
    blocked  (x, y, z, box) -> bool: whether this block will be overwritten by
             something else after this station box is built (the composition
             root builds it from the landmark extents and the cross-sections
             of other segments built later). At Taipei Main Station, the
             TRA/HSR platform level is at the same depth as the Bannan Line
             station box and swallows the whole stretch of platform screen
             doors on the north side of the west end. A sign there would hang
             in mid-air in the hall, and the player could not stand there.
    """
    net = build_network(segs)
    boxes = find_boxes(segs)
    for key, st in net.items():
        st.box = boxes.get(key)
    # A direction whose neighbor has no built station box cannot be ridden.
    # This does not happen for stations in stn_seq, but no sign may point to a
    # ride that does not exist.
    for (ref, name), st in net.items():
        for nb in [nb for nb in st.dirs if net.get((ref, nb)) is None
                   or net[(ref, nb)].box is None]:
            del st.dirs[nb]
    berths = []
    for (ref, name), st in sorted(net.items(), key=lambda kv: code_sort_key(kv[1].code)):
        box = st.box
        if box is None:
            continue
        for dr in st.dirs.values():
            dr.d = _box_direction(box, segs, dr.via[0])
        upper_d = None
        if box.kind.startswith("stacked"):
            spec = SK.STACKED.get((name, ref), {})
            up = st.dirs.get(spec.get("upper_toward"))
            upper_d = up.d if up is not None else 1
        per = max(1, int(round(1.0 / STEP)))
        if box.kind == "side":
            slots_m = SLOTS_SIDE + SLOTS_SIDE_MORE
        else:
            slots_m = SLOTS_UNDER + tuple(a for a in SLOTS_UNDER_MORE
                                          if not (box.kind.startswith("stacked") and a < 22))
        for d in (1, -1):
            if upper_d is None:
                dy0, psd, inward = _geometry(box, d)
            else:
                dy0, psd, inward = _stacked_geometry(box, ref, d, upper_d)
            b = Berth(st, box, d, dy0, psd, inward)
            # When a junction station has two directions on the same side, the
            # trunk (the longest variant) takes the primary position.
            b.dests = sorted((dr for dr in st.dirs.values() if dr.d == d),
                             key=lambda dr: (-max(len(segs[li]["samples"]) for li, _, _ in dr.via),
                                             dr.next))
            k = max(1, len(b.dests))
            j = 0
            for along in slots_m:
                if j >= SLOTS_PER_SIDE:
                    break
                i = box.lo + along * per
                if not (box.lo < i < box.hi):
                    continue
                nx, nz = box.normal(i)
                y = int(box.ys[i]) + dy0 + 2
                sx, sz = box.cell(i, psd)
                tx, tz = _stand_cell(sx, sz, nx * inward, nz * inward)
                if blocked is not None and (blocked(sx, y, sz, box) or blocked(tx, y, tz, box)):
                    continue
                face = (nx * inward, nz * inward)            # The sign faces the berth.
                yaw = yaw_of(sx - tx, sz - tz)               # The player faces the sign's block.
                dest = b.dests[j % k] if b.dests else None
                lang = "zh" if (j // k) % 2 == 0 else "en"
                b.slots.append(Slot((sx, y, sz), face, (tx, y, tz), yaw, dest, lang))
                j += 1
            berths.append(b)
    return net, berths


def berth_index(berths):
    """{(line, name, d): Berth}"""
    return {(b.line, b.station.name, b.d): b for b in berths}


def arrival(net, bidx, ref, frm, to):
    """The Slot for alighting after a ride from frm to to (in front of the sign
    for the onward journey).

    The arriving train travels through the station box of to away from frm, so
    the platform edge to alight at is d = −(direction from to toward frm). If
    that side has several directions (a junction station), prefer the one on
    the same variant as this ride: riding from Taipei Bridge to Daqiaotou, the
    onward direction is toward Minquan West Road, not toward Sanchong
    Elementary School.
    """
    st = net.get((ref, to))
    if st is None or st.box is None or frm not in st.dirs:
        return None
    back = st.dirs[frm]
    b = bidx.get((ref, to, -back.d))
    if b is None or not b.slots:
        return None
    same = {li for li, _, _ in back.via}
    for s in b.slots:
        if s.dest is not None and any(li in same for li, _, _ in s.dest.via):
            return s
    return b.primary()


def rides(net, berths):
    """All rides: [(line, origin Station, destination Station, alighting Slot,
    Direction)]."""
    bidx = berth_index(berths)
    out = []
    for (ref, name), st in sorted(net.items(), key=lambda kv: code_sort_key(kv[1].code)):
        if st.box is None:
            continue
        for nb, dr in sorted(st.dirs.items()):
            to = net.get((ref, nb))
            if to is None or to.box is None:
                continue
            slot = arrival(net, bidx, ref, name, nb)
            if slot is not None:
                out.append((ref, st, to, slot, dr))
    return out


def home_slot(bidx, st):
    """The destination for "go to a station": the primary position on the side
    with a next station (at a terminus, the departure side)."""
    for d in (1, -1):
        b = bidx.get((st.ref, st.name, d))
        if b is not None and b.dests and b.slots:
            return b.primary()
    for d in (1, -1):
        b = bidx.get((st.ref, st.name, d))
        if b is not None and b.slots:
            return b.slots[0]
    return None
