#!/usr/bin/env python3
"""Real exits and transfer passages: connect the OSM exit coordinates to each
station's concourse, and connect the two station boxes of a transfer station.

Apart from Taipei Main Station, every station used to have a single template
stair, opened at a fixed position on the side of the station box. Yet
`data/entrances.json` has long held the coordinates and numbers of all 786 real
exits on the network: Exit 6 of Chiang Kai-shek Memorial Hall is 264 m from the
station box, and Gongguan has 27 exits. This module connects them.

Each exit gets three things:
  1. A switchback stair shaft (build_concourse.ShaftStair) from the street to
     the concourse level. Underground stations dig down; elevated stations
     climb up to the concourse under the viaduct (alignment.station_kind
     decides the type and LEVEL_DY the height; the project has only this one
     definition).
  2. A connecting passage from the shaft door along the outside of the station
     box to its side wall (a skybridge at elevated stations).
  3. An opening in the side wall into the unpaid area of the concourse (the
     stretch in front of the fare gates).

A transfer station also gets a paid-area-to-paid-area transfer passage
(plan_transfer): one passage if the two levels are at the same height;
otherwise a shaft between the two station boxes, with a passage from each
level to the shaft door.

All three are pure geometry. This layer only computes where things go and
places no blocks; block placement is in application/build_exits.py.

Three findings from the real data shaped the approach below:

- **Exits are not beside the station box.** The median distance along the
  line is 73 m and 90% are within 240 m, so more than half the exits fall
  outside the 70 m platform. A passage therefore cannot run straight into the
  box at right angles; it must first run along the outside of the box to the
  opening. Every passage runs at lateral offset PASS_OFF (the box half-width
  of 12 plus 3 more): it follows the alignment sample by sample, so it never
  cuts into the box however much the box curves.
- **Exits are often right above the tunnel.** One in ten exits is less than
  10 m from the centerline. A shaft digs from the ground all the way to the
  concourse, so placed as is it would break through the roof of the running
  tunnel. Shafts are therefore always placed outside the box, and pushed
  outward when too close to the centerline, until they collide with no
  underground structure of any line.
- **Exits at transfer stations are shared.** All 14 exits of Zhongxiao
  Xinsheng are listed under both the Bannan Line and the Zhonghe-Xinlu Line.
  Each exit connects only to the nearest station box (assign_to_boxes).

Self-test: ./.venv/bin/python tests/test_exits.py
"""
import math

from mrt.domain.alignment import (
    BOX_HALF, MEZZ_DY, BOX_TOP_DY, PLATFORM_LEN, STEP, LEVEL_DY,
    structure_for_ground, station_kind,
)
from mrt.domain.stacked import BOX_BOTTOM_DY

PASS_OFF   = BOX_HALF + 3      # Lateral offset of the passage centerline (3 m outside the station box).
PASS_HALF  = 2                 # Passage half-width -> 5 m wide.
CLEAR_OFF  = PASS_OFF + PASS_HALF + 1   # Minimum distance from the centerline to the shaft body (with a
                                        # one-cell margin): the passage band is 13-17 and its outer wall 18,
                                        # so the shaft wall lands beyond 18 and other exits' passages can
                                        # run past its door without hitting the shaft.
SAME_REF_M = 40.0              # Two nodes of one station with the same number within this distance are one exit.
HOLE_ALONG = 7                 # Side-wall opening: meters from the lo end of the station box (the fare gates are at 14).
HOLE_HALF  = 2                 # Half-width of the opening (along the line).
MIN_DROP   = 3                 # Minimum drop from the ground to the concourse that justifies a shaft (underground stations).
MIN_RISE   = 3                 # Elevated stations: minimum rise from the street to the concourse to build a climbing
                               # shaft. The shaft's two doors are on the same wall; with a difference of 2 the bottom
                               # door opening is only one block high, and the apron in front of it happens to clear
                               # away the skybridge floor. Differences of 0-2 use an at-grade exit (see GATE_RUN).
GATE_RUN   = 3                 # At-grade exit: length in blocks of the ramp plus apron outside the door.
MAX_ALONG  = 350               # Exits farther than this along the line from the station center are not connected.
MAX_OFF    = 300               # Exits farther than this from the centerline are not connected.
MERGE_M    = 12.0              # Two exits closer than this share one shaft.
SLIDE_MAX  = 60                # Maximum distance in meters that a shaft is pushed outward.

# Switchback shaft dimensions, matching build_concourse.ShaftStair. In shaft
# coordinates, a runs along u over -1..FLIGHT+2 and b along the normal over
# -HALF_W-1..HALF_W+1.
SHAFT_FLIGHT = 14
SHAFT_HALF_W = 4
SHAFT_A = (-1, SHAFT_FLIGHT + 2)
SHAFT_B = (-SHAFT_HALF_W - 1, SHAFT_HALF_W + 1)


# ---------- Occupancy index ----------

class Occupancy:
    """Which cells the structures of all lines occupy in plan, and over which
    height range.

    It answers a single question: is there anything in cell (x, z) between y0
    and y1? Shafts and passages use it to avoid the tunnels of other lines. The
    exit shaft of a transfer station digs from the ground to the concourse of
    the deeper line and must pass through the depth of the shallower line on
    the way; without this check it would break through that line's tunnel.

    Each sample sweeps 2r+1 cells along the normal and records, for each cell,
    the height range occupied and the segment it belongs to (tag). One cell may
    be occupied by two lines at different depths, so each cell holds a list of
    ranges.

    The tag exists for passages. A passage already runs along the outside of
    its own line, and its lateral offset, measured along each sample's normal,
    is always far enough; only where a diagonal is rasterized can its edge
    graze the same cell as the outermost cell of the lining. That is not a real
    collision, so the passage check skips its own segment. Shafts do not skip
    it: a shaft digs down from the ground and really can land right above its
    own running tunnel.
    """

    def __init__(self):
        self.cells = {}

    def copy(self):
        """Return a copy for trial planning: discard it if the plan fails, and
        swap its cells back in if the plan succeeds."""
        o = Occupancy()
        o.cells = {c: list(v) for c, v in self.cells.items()}
        return o

    def add(self, x, z, y0, y1, tag=None):
        c = (int(round(x)), int(round(z)))
        self.cells.setdefault(c, []).append((int(y0), int(y1), tag))

    def add_span(self, x, z, nx, nz, r, y0, y1, tag=None):
        """Occupy y0..y1 over r cells on each side of (x, z) along the normal
        (nx, nz)."""
        for o in range(-r, r + 1):
            self.add(x + nx * o, z + nz * o, y0, y1, tag)

    def blocked(self, x, z, y0, y1, skip_tag=None, ignore=None):
        """Occupancies for which ignore(tag) returns True do not count. A
        transfer passage overlapping an exit passage of the same station box on
        the same level is normal (the two passages merge into one floor);
        overlapping anything else is a collision. skip_tag may be one tag or a
        collection of tags (both lines of a shared station box count as
        allies)."""
        skip = _tags(skip_tag)
        for a, b, t in self.cells.get((int(x), int(z)), ()):
            if a <= y1 and b >= y0 and t not in skip \
                    and not (ignore is not None and ignore(t)):
                return True
        return False

    def any_blocked(self, cells, y0, y1, skip_tag=None, ignore=None):
        for x, z in cells:
            if self.blocked(x, z, y0, y1, skip_tag, ignore):
                return True
        return False

    def who(self, cells, y0, y1, skip_tag=None, ignore=None):
        """Return the tags that block these cells (for reports)."""
        out = set()
        skip = _tags(skip_tag)
        for x, z in cells:
            for a, b, t in self.cells.get((int(x), int(z)), ()):
                if a <= y1 and b >= y0 and t not in skip \
                        and not (ignore is not None and ignore(t)):
                    out.add(t)
        return out


def _tags(skip_tag):
    """skip_tag -> the set of tags to skip (None is the empty set; sets and
    tuples are accepted as they are)."""
    if skip_tag is None:
        return frozenset()
    if isinstance(skip_tag, (set, frozenset, tuple, list)):
        return frozenset(skip_tag)
    return frozenset((skip_tag,))


def index_segments(segs, box_half=BOX_HALF):
    """Record every segment planned by build_world in an Occupancy, tagged with
    the segment index.

    Each element of segs must have samples / ys / ground / stn / hw (the format
    the cli planner produces). Underground segments occupy y-2..y+7 (the tunnel
    cross-section); station ranges occupy y-2..y+10, with the half-width
    widened to the station box. Elevated and at-grade segments are recorded
    too, because shafts dig all the way to the ground and must not land on a
    pier or an embankment.
    Piers reach only 4 blocks below the ground (ground-4 in sec_bridge), and
    the concourse roof of depth band 0 is 5 blocks below the ground, so it just
    passes under the piers; counting one more block would seal off everything
    under the elevated lines.
    """
    occ = Occupancy()
    half = int(PLATFORM_LEN / 2 / STEP)
    for li, sg in enumerate(segs):
        samples, ys, gnd = sg["samples"], sg["ys"], sg["ground"]
        hws = sg.get("hw")
        frames, stacked, y_side = sg.get("frames", {}), sg.get("stacked", {}), sg.get("y_side")
        nob = sg.get("nobuild", set())              # The partner's stretch in a shared station box:
                                                    # the primary records the box structure.
        stn_rng = []
        for bi in sg.get("stn", ()):
            stn_rng.append((max(0, bi - half), min(len(samples) - 1, bi + half), bi))
        n = len(samples)
        for i in range(0, n, 2):                    # One point per meter is enough.
            if i in nob:
                continue
            x, z, ux, uz, _ = samples[i]
            nx, nz = -uz, ux
            y, g = int(ys[i]), int(gnd[i])
            hw = int(hws[i]) if hws is not None else 5
            st = structure_for_ground(y, g)
            in_stn = next((bi for lo, hi, bi in stn_rng if lo <= i <= hi), None)
            if st == "tunnel":
                if in_stn is not None:
                    # A stacked station's box structure reaches down to the lower level's floor slab;
                    # a shared station box follows the frame on the midline of the two lines.
                    fx, fz, fux, fuz, _ = frames.get(in_stn, samples)[i]
                    y0 = y + (BOX_BOTTOM_DY if in_stn in stacked else -2)
                    occ.add_span(fx, fz, -fuz, fux, box_half + 1, y0, y + BOX_TOP_DY, li)
                else:
                    ylo = y if y_side is None else min(y, int(y_side[1][i]), int(y_side[-1][i]))
                    occ.add_span(x, z, nx, nz, hw + 2, ylo - 2, y + 7, li)
            elif st == "viaduct":
                occ.add_span(x, z, nx, nz, hw + 1, y - 2, y + 8, li)
                occ.add_span(x, z, nx, nz, 2, g - 4, y, li)          # Pier.
                if in_stn:                        # The station box, with its concourse under the viaduct
                                                  # or above the platforms.
                    occ.add_span(x, z, nx, nz, 11, g - 3, y + 12, li)
            else:
                occ.add_span(x, z, nx, nz, hw + 2, y - 2, y + 8, li)
                if in_stn:                        # An at-grade station's concourse spans above the platforms.
                    occ.add_span(x, z, nx, nz, 11, g - 3, y + 12, li)
    return occ


# ---------- Station box coordinates ----------

def station_frame(samples, ys, idx):
    """Return the station's sample range (lo, hi) and the sample index of the
    opening."""
    n = len(samples)
    half = int(PLATFORM_LEN / 2 / STEP)
    lo, hi = max(0, idx - half), min(n - 1, idx + half)
    per_m = max(1, int(round(1.0 / STEP)))
    hole = min(hi, lo + HOLE_ALONG * per_m)
    return lo, hi, hole


def nearest_index(samples, x, z, lo=None, hi=None):
    """Return the index of the sample nearest to (x, z) (optionally limited to
    lo..hi)."""
    lo = 0 if lo is None else lo
    hi = len(samples) - 1 if hi is None else hi
    best, bd = lo, None
    for i in range(lo, hi + 1):
        d = (samples[i][0] - x) ** 2 + (samples[i][1] - z) ** 2
        if bd is None or d < bd:
            best, bd = i, d
    return best, math.sqrt(bd) if bd is not None else 0.0


def local_coords(samples, i, x, z):
    """Return (along, lateral offset) of (x, z) relative to sample i. A positive
    offset is on the normal side."""
    sx, sz, ux, uz, _ = samples[i]
    dx, dz = x - sx, z - sz
    return dx * ux + dz * uz, -dx * uz + dz * ux


def offset_point(samples, i, off):
    sx, sz, ux, uz, _ = samples[i]
    return sx - uz * off, sz + ux * off


def box_cells(samples, lo, hi, half):
    """Return the cells of the station box between lo and hi with
    |lateral offset| <= half."""
    out = set()
    for i in range(lo, hi + 1):
        sx, sz, ux, uz, _ = samples[i]
        for o in range(-half, half + 1):
            out.add((int(round(sx - uz * o)), int(round(sz + ux * o))))
    return out


def box_distance(samples, ys, idx, x, z):
    """Return the distance from an exit to the station box rectangle (0 inside
    it); used to assign exits at transfer stations."""
    lo, hi, _ = station_frame(samples, ys, idx)
    i, _ = nearest_index(samples, x, z, lo, hi)
    along, off = local_coords(samples, i, x, z)
    da = max(0.0, abs(along) - 1.0) if i not in (lo, hi) else abs(along)
    do = max(0.0, abs(off) - BOX_HALF)
    return math.hypot(da, do)


def assign_to_boxes(entrances, boxes):
    """Transfer stations: connect each exit only to the nearest station box.

    entrances [(ref, x, z)]; boxes {key: (samples, ys, idx)}.
    Returns {key: [(ref, x, z)]}.
    """
    out = {k: [] for k in boxes}
    for ref, x, z in entrances:
        best = min(boxes, key=lambda k: box_distance(boxes[k][0], boxes[k][1],
                                                     boxes[k][2], x, z))
        out[best].append((ref, x, z))
    return out


# ---------- Rasterization (the same as build_concourse.stroke; this layer may not import application) ----------

def stroke(p0, p1, half_w):
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


def polyline_cells(pts, half_w):
    out = set()
    for a, b in zip(pts, pts[1:]):
        out |= stroke(a, b, half_w)
    return out


# ---------- Shaft placement ----------

def shaft_cells(x0, z0, ux, uz, margin=0):
    """Return the plan cells of a switchback shaft (walls included), optionally
    grown outward by margin."""
    vx, vz = -uz, ux
    out = set()
    for a in range(SHAFT_A[0] - margin, SHAFT_A[1] + margin + 1):
        for b in range(SHAFT_B[0] - margin, SHAFT_B[1] + margin + 1):
            out.add((x0 + ux * a + vx * b, z0 + uz * a + vz * b))
    return out


def gate_cells(x0, z0, ux, uz, margin=0):
    """Return the ramp and apron outside an at-grade exit: from the door cell
    (x0, z0), 1..GATE_RUN cells toward the street and PASS_HALF cells to each
    side (as wide as the passage), grown outward by margin."""
    vx, vz = -uz, ux
    out = set()
    for a in range(1, GATE_RUN + margin + 1):
        for b in range(-PASS_HALF - margin, PASS_HALF + margin + 1):
            out.add((x0 + ux * a + vx * b, z0 + uz * a + vz * b))
    return out


def _quantize(vx, vz):
    if abs(vx) >= abs(vz):
        return (1 if vx >= 0 else -1), 0
    return 0, (1 if vz >= 0 else -1)


def well_span(level, street):
    """Return the height range (y_lo, y_hi) a shaft occupies: the standing
    surfaces at both ends, plus a floor slab below and a roof above.

    An underground station's shaft digs down from the street to the concourse;
    an elevated station's shaft climbs from the street to the concourse under
    the viaduct. It is the same shaft with the same geometry; only which end is
    on top differs.
    """
    top, bot = max(level, street), min(level, street)
    return bot - 1, top + 5


def place_shaft(samples, ys, lo, hi, ex, ez, ym, g_top, occ, used, ground_at,
                extra=frozenset(), kind="tunnel"):
    """Find a position and orientation for an exit's shaft.

    Returns (x0, z0, ux, uz, g0, meters pushed, orientation) or None. The
    orientation "normal" faces away from the station box; "tangent" follows the
    alignment.

    Facing away from the station box is preferred: the shaft entrance door
    (a=-1) faces the line, and the connecting passage runs from the door
    straight to the box. The two directions along the alignment come next. A
    shaft body pointing toward the box is never considered: the shaft would
    stand between the door and the box, and the passage would have to go
    around its own shaft.

    The position starts at the exit itself and is pushed outward along the
    normal until:
      · every cell of the shaft body (with a one-cell margin) is at least
        CLEAR_OFF from the centerline. Passages run in the band at lateral
        offset PASS_OFF, and other exits' passages pass in front of this door.
        Every cell must be measured, not just the door: a shaft can only take
        the four axis-aligned orientations, so where the alignment runs at 45
        degrees the corner of the shaft is 4 m closer than the door (this is
        how Fuzhong station blocked the passage of Exit 1).
      · the shaft body collides with no underground structure (occ) and no
        shaft or passage already built (used); extra holds the passage cells
        this station has already laid, which the shaft may not cover.
    The shorter the push, the better.

    kind is the station type (alignment.station_kind). An underground
    station's shaft digs down, so it only makes sense when the street is at
    least MIN_DROP above the concourse; an elevated station's shaft climbs up,
    and when the street and the concourse differ by less than MIN_RISE the door
    opening is too low to pass through.
    """
    i, _ = nearest_index(samples, ex, ez, lo, hi)
    along, off = local_coords(samples, i, ex, ez)
    side = 1 if off >= 0 else -1
    sx, sz, ux, uz, _ = samples[i]
    nx, nz = -uz * side, ux * side              # The normal pointing to the exit's side.

    dirs = [(_quantize(nx, nz), "normal")]
    for t in ((ux, uz), (-ux, -uz)):
        q = _quantize(*t)
        if q != dirs[0][0] and q != (-dirs[0][0][0], -dirs[0][0][1]):
            dirs.append((q, "tangent"))
    for slide in range(0, SLIDE_MAX + 1):
        px, pz = ex + nx * slide, ez + nz * slide
        for (dx, dz), kind_ in dirs:
            x0, z0 = int(round(px)), int(round(pz))
            door = (x0 - dx, z0 - dz)
            di, _ = nearest_index(samples, door[0], door[1])
            near = min(abs(local_coords(samples, di, cx, cz)[1])
                       for cx, cz in shaft_cells(x0, z0, dx, dz, margin=1))
            if near < CLEAR_OFF:
                continue
            cells = shaft_cells(x0, z0, dx, dz)
            if any(c in extra for c in cells):
                continue
            g0 = int(ground_at(*door))
            if not drop_ok(kind, g0, ym):
                return None                      # The ground here is at the wrong height; a shaft would serve no purpose.
            y_lo, y_hi = well_span(ym, g0 + 1)
            if occ.any_blocked(cells, y_lo, y_hi) or used.any_blocked(cells, y_lo, y_hi):
                continue
            return x0, z0, dx, dz, g0, slide, kind_
    return None


def drop_ok(kind, g0, level):
    """Return whether the height difference between the street (ground block
    g0) and the concourse standing surface `level` is enough for a shaft."""
    if kind == "tunnel":
        return g0 - level >= MIN_DROP
    return abs(g0 + 1 - level) >= MIN_RISE


def place_gate(samples, ys, lo, hi, ex, ez, ym, occ, used, ground_at,
               extra=frozenset()):
    """Find an at-grade exit position for an exit whose street is less than
    MIN_RISE from the concourse.

    The concourse under the viaduct of an elevated station is only 3-7 m above
    the ground, so on a hillside an exit's street may be within 2 m of the
    concourse height. No shaft can be built there (the shaft's two doors are on
    the same wall, and with a drop of less than three blocks the bottom door
    opening is only one block high), and none is needed: the passage ends at
    the door, and outside it the floor rises or falls one block per cell to the
    street, followed by a small apron.

    Returns (x0, z0, ux, uz, g0, meters pushed) or None. (x0, z0) is the door
    cell (the end of the passage); u faces away from the station box, quantized
    to an axis direction, and the ramp and apron are 1..GATE_RUN cells outside
    the door in direction u. g0 is the ground at the far end of the apron:
    people walk up the ramp from there, so the street there must be within
    MIN_RISE-1 blocks of the concourse, or the gate is pushed farther out.

    Like place_shaft, it pushes outward along the normal: the ramp (with a
    one-cell margin) must be at least CLEAR_OFF from the centerline so that
    other exits' passages can pass in front of the door; it must not hit
    another line's structure or another shaft or passage, nor cover passage
    cells this station has already laid (extra).
    """
    i, _ = nearest_index(samples, ex, ez, lo, hi)
    along, off = local_coords(samples, i, ex, ez)
    side = 1 if off >= 0 else -1
    sx, sz, ux, uz, _ = samples[i]
    nx, nz = -uz * side, ux * side              # The normal pointing to the exit's side.
    dx, dz = _quantize(nx, nz)
    for slide in range(0, SLIDE_MAX + 1):
        x0 = int(round(ex + nx * slide))
        z0 = int(round(ez + nz * slide))
        wide = gate_cells(x0, z0, dx, dz, margin=1) | {(x0, z0)}
        di, _ = nearest_index(samples, x0, z0)
        near = min(abs(local_coords(samples, di, cx, cz)[1]) for cx, cz in wide)
        if near < CLEAR_OFF:
            continue
        if any(c in extra for c in wide):
            continue
        g0 = int(ground_at(x0 + dx * GATE_RUN, z0 + dz * GATE_RUN))
        if abs(g0 + 1 - ym) >= MIN_RISE:
            continue                             # The ground at the apron is too far from the concourse; push farther.
        if occ.any_blocked(wide, ym - 3, ym + 4) or used.any_blocked(wide, ym - 3, ym + 4):
            continue
        return x0, z0, dx, dz, g0, slide
    return None


# ---------- Plan for a whole station ----------

def merge_entrances(entrances, merge_m=MERGE_M, same_ref_m=SAME_REF_M):
    """Merge nodes that are really one exit. Returns [dict(refs, x, z)].

    There are two cases: two doors very close together (two names, one exit),
    and one station mapping the same exit number as two nodes (OSM often tags
    it once per line, or once for the door and once for the stair head; the two
    nodes of Exit 1 at Fuzhong station are 26 m apart). Left unmerged, the
    latter produce two shafts one behind the other on the same normal, and the
    front shaft blocks the rear one's passage.
    """
    groups = []
    for ref, x, z in sorted(entrances, key=lambda e: str(e[0])):
        ref = str(ref)
        for g in groups:
            d = math.hypot(g["x"] - x, g["z"] - z)
            if d <= merge_m or (ref and ref in g["refs"] and d <= same_ref_m):
                n = len(g["refs"])
                g["x"] = (g["x"] * n + x) / (n + 1)
                g["z"] = (g["z"] * n + z) / (n + 1)
                g["refs"].append(ref)
                break
        else:
            groups.append(dict(refs=[ref], x=float(x), z=float(z)))
    for g in groups:                       # Keep each name once, so the sign does not print it twice.
        seen, refs = set(), []
        for r in g["refs"]:
            if r not in seen:
                seen.add(r); refs.append(r)
        g["refs"] = refs
    return groups


def hole_cells(samples, lo, hi, k, side):
    """Return the side-wall opening: |off| 11..13 (the two lining cells plus
    one outside), along the line k ± HOLE_HALF.

    It does not dig further in: the concourse at |off| <= 10 is already empty,
    and paving more would only recolor the floor. The side wall of an
    underground station is at 11..12 and the glass wall of an elevated
    concourse at 11; the same set of cells breaks through both.
    """
    out = set()
    for kk in range(k - HOLE_HALF * 2, k + HOLE_HALF * 2 + 1):
        if not (lo <= kk <= hi):
            continue
        for o in range(BOX_HALF - 1, BOX_HALF + 2):
            x, z = offset_point(samples, kk, side * o)
            out.add((int(round(x)), int(round(z))))
    return out


def passage_tag(own_tag, level):
    """Return a passage's tag in used: passages of the same segment on the same
    level may overlap (they merge into one floor)."""
    return ("通道", own_tag, int(level))


def plan_station(samples, ys, grounds, idx, entrances, ground_at, occ, used,
                 own_tag=None, ally_tags=()):
    """Connect all exits of one station (underground stations to the
    concourse; elevated and at-grade stations to the concourse under the
    viaduct or above the platforms; alignment.station_kind / LEVEL_DY decide
    the type and height).

    samples/ys/grounds  segment arrays planned by the cli
    idx                 sample index of the station
    entrances           [(ref, x, z)]; ref is the exit number (may repeat or be blank)
    ground_at           f(x, z) -> ground y
    occ                 Occupancy (all lines)
    used                Occupancy of shafts and passages already built (updated
                        here: once planned, all of this station's shafts and
                        passages are added to it). It is separate from occ
                        because it grows as planning proceeds. It records
                        heights: the concourses of the two station boxes of a
                        transfer station differ by 15 m, so their passages cross
                        in plan but never touch.
    own_tag             this segment's tag in occ, skipped by the passage check
                        (see Occupancy)
    ally_tags           tags skipped as well: the other line of a shared station
                        box (Ximen). Its level-split transition runs right
                        outside the box's side wall, so an exit passage running
                        along the outside of the box always grazes it, just as
                        it grazes the flare of its own line.

    Returns a dict:
      kind     station type
      ym       concourse standing surface y
      shafts   [dict(refs, x0, z0, ux, uz, g0, y_to, slide)]  switchback shafts
      gates    [dict(refs, x0, z0, ux, uz, g0, y_to, slide)]  at-grade exits:
               (x0, z0) is the door cell (the end of the passage), u points
               toward the street, and g0 is the ground at the apron
      cells    floor cells of the connecting passages (side-wall openings included)
      open     cells outside at-grade exit doors where no wall may be built
               (the ramp and apron; the passage's outer wall must not seal them)
      no_wall  cells where no wall may be built (the box interior plus open)
      skipped  [(refs, x, z, reason, what blocked it)]
    """
    lo, hi, hole = station_frame(samples, ys, idx)
    kind = station_kind(int(ys[idx]), int(grounds[idx]))
    ym = int(ys[hole]) + LEVEL_DY[kind]
    interior = box_cells(samples, lo, hi, BOX_HALF - 2)
    own_box = box_cells(samples, lo, hi, BOX_HALF + 2)   # Passages have to enter their own station box anyway.
    cells, shafts, gates, skipped = set(), [], [], []
    open_cells, sides_used = set(), set()

    groups = merge_entrances(entrances)

    for g in groups:
        ex, ez = g["x"], g["z"]
        i, _ = nearest_index(samples, ex, ez)
        along_c, off_c = local_coords(samples, idx, ex, ez)
        if abs(along_c) > MAX_ALONG or abs(off_c) > MAX_OFF:
            skipped.append((g["refs"], ex, ez, "too far from the station box", set()))
            continue
        g_here = int(ground_at(ex, ez))
        if kind == "tunnel" and not drop_ok(kind, g_here, ym):
            skipped.append((g["refs"], ex, ez, "ground too low for a drop", set()))
            continue
        placed = gate = None
        if drop_ok(kind, g_here, ym):
            # A shaft may not cover passages this station has already laid;
            # passages may overlap each other (same level, same height).
            placed = place_shaft(samples, ys, lo, hi, ex, ez, ym, g_here, occ,
                                 used, ground_at, extra=cells, kind=kind)
        if placed is None and kind != "tunnel":
            # The elevated station's street is within 2 m of the concourse
            # height (or became so once the shaft was pushed outward): build no
            # shaft; the passage opens straight onto the street, with a ramp
            # outside the door.
            gate = place_gate(samples, ys, lo, hi, ex, ez, ym, occ, used,
                              ground_at, extra=cells)
        if placed is None and gate is None:
            skipped.append((g["refs"], ex, ez, "no room for a shaft (hits another line or shaft)", set()))
            continue

        if gate is not None:
            x0, z0, dx, dz, g0, slide = gate
            door = (x0, z0)
            pts = [door]
            own = gate_cells(x0, z0, dx, dz, margin=1)
        else:
            x0, z0, dx, dz, g0, slide, kind_ = placed
            # Connecting passage: door -> PASS_OFF outside the station box ->
            # along the line to the opening -> the opening. A shaft oriented
            # along the alignment has its door facing along the alignment, so
            # the passage goes straight for three cells before turning toward
            # the box; turning diagonally at once, the swept width of the
            # passage would cut into the row of shaft wall at the entrance.
            door = (x0 - dx, z0 - dz)
            pts = [door]
            if kind_ == "tangent":
                door = (x0 - 4 * dx, z0 - 4 * dz)
                pts.append(door)
            own = shaft_cells(x0, z0, dx, dz)
        di, _ = nearest_index(samples, door[0], door[1])
        _, doff = local_coords(samples, di, door[0], door[1])
        side = 1 if doff >= 0 else -1
        pts.append(offset_point(samples, di, side * PASS_OFF))
        step = max(1, int(4 / STEP))
        rng = range(di, hole, step if hole > di else -step)
        for k in rng:
            pts.append(offset_point(samples, k, side * PASS_OFF))
        pts.append(offset_point(samples, hole, side * PASS_OFF))
        pts.append(offset_point(samples, hole, side * (BOX_HALF - 1)))
        pcells = polyline_cells(pts, PASS_HALF)
        pcells -= interior                                   # No need to pave inside the station box.
        # Underground passages are level; the terrain is not. At Banqiao
        # station the ground drops 6 m toward the Circular Line end, and a
        # passage running there would push its roof out through the street. At
        # least one block of soil must remain above the roof. An elevated
        # station's passage is a skybridge: where the terrain is higher it cuts
        # into the slope, and where it is lower it stands on piers, so it can
        # always be built.
        if kind == "tunnel" and any(int(ground_at(x, z)) < ym + 4 for x, z in pcells):
            skipped.append((g["refs"], ex, ez, "passage would break the surface", set()))
            continue
        # A passage may not pass through another line's structure or another
        # shaft (its own shaft body and ramp excepted).
        chk = pcells - own - own_box
        skip = {own_tag, *ally_tags}
        if occ.any_blocked(chk, ym - 1, ym + 3, skip_tag=skip):
            skipped.append((g["refs"], ex, ez, "passage hits another line's structure",
                            occ.who(chk, ym - 1, ym + 3, skip_tag=skip)))
            continue
        # Passages of the same segment on the same level (a transfer passage
        # this station connected first) may overlap: they merge into one floor.
        same = passage_tag(own_tag, ym)
        if used.any_blocked(chk, ym - 1, ym + 3, ignore=lambda t: t == same):
            skipped.append((g["refs"], ex, ez, "passage hits another shaft or passage",
                            used.who(chk, ym - 1, ym + 3, ignore=lambda t: t == same)))
            continue

        cells |= pcells
        sides_used.add(side)
        if gate is not None:
            for c in own:
                used.add(c[0], c[1], ym - 3, ym + 4, ("井", tuple(g["refs"])))
            open_cells |= own
            gates.append(dict(refs=g["refs"], x0=x0, z0=z0, ux=dx, uz=dz,
                              g0=g0, y_to=ym, slide=slide, ex=ex, ez=ez, kind=kind))
            continue
        y_lo, y_hi = well_span(ym, g0 + 1)
        for c in shaft_cells(x0, z0, dx, dz, margin=1):
            used.add(c[0], c[1], y_lo, y_hi, ("井", tuple(g["refs"])))
        shafts.append(dict(refs=g["refs"], x0=x0, z0=z0, ux=dx, uz=dz,
                           g0=g0, y_to=ym, slide=slide, ex=ex, ez=ez, kind=kind))

    for side in sides_used:
        cells |= hole_cells(samples, lo, hi, hole, side)
    for c in cells:
        used.add(c[0], c[1], ym - 1, ym + 3, passage_tag(own_tag, ym))

    return dict(kind=kind, ym=ym, lo=lo, hi=hi, hole=hole, shafts=shafts,
                gates=gates, cells=cells, open=open_cells,
                no_wall=interior | open_cells, skipped=skipped)


def default_entrances(samples, ys, idx, offs=(24, -24), along_m=HOLE_ALONG):
    """Default exits for stations without real exit data (the Taoyuan section
    of the Taoyuan Airport MRT, the Ankeng LRT, ...): a point opposite the
    opening, offs meters from the centerline, one candidate on each side; the
    first that succeeds counts.
    """
    lo, hi, hole = station_frame(samples, ys, idx)
    out = []
    for o in offs:
        x, z = offset_point(samples, hole, o)
        out.append(("", int(round(x)), int(round(z))))
    return out


# ---------- Transfer passages ----------

TRANSFER_MAX_M = 400     # Two station boxes whose nearest connection points are farther apart than this
                         # are not connected (Sanchong A/O: 302 m).
PAID_FROM_M    = 20      # The transfer passage opens into the paid area: the fare gates are at lo+14..16,
                         # the opening itself is ±2 m wide, plus 2 m to spare.
PAID_END_M     = 4       # Minimum distance in meters from the end wall of the station box.
STAIR_END_M    = 18      # Both platform stairs of an elevated concourse are at the hi end
                         # (build_line._side_concourse).
LEVEL_DIRECT   = 1       # Levels within this many blocks are connected directly by one passage
                         # (a one-block step can be walked up).
LEVEL_WELL     = 5       # A shaft is built only from this difference up; at 2-4 m the two passages would
                         # cut into each other at the door, so no connection is made.
GRID_M         = 4       # Grid spacing of candidate shaft positions.
MAX_TRIES      = 1500    # Maximum number of candidate positions evaluated in full (those rejected by the
                         # coarse filter do not count).
MAX_PAIRS      = 40      # Maximum number of connection-point pairs tried when connecting on the same level.


def paid_range(samples, ys, idx, kind, side):
    """Return where a transfer passage may open in the side wall, as a list of
    sample indices (one every 3 m).

    Only positions whose rail top is at the same height as at the exit opening
    (lo + HOLE_ALONG) are chosen: if the rails slope inside the station, the
    concourse floor steps up with them, and the transfer passage must be on the
    same level as this station's exit passages for the two to merge into one
    floor; one block off and the two floors cut into each other. Only when no
    position has that height does it fall back to taking them all.
    """
    lo, hi, hole = station_frame(samples, ys, idx)
    per_m = max(1, int(round(1.0 / STEP)))
    a, b = lo + PAID_FROM_M * per_m, hi - PAID_END_M * per_m
    if kind != "tunnel":                         # Both platform stairs are at the hi end.
        b = hi - STAIR_END_M * per_m
    ks = list(range(a, b + 1, 3 * per_m))
    same = [k for k in ks if int(ys[k]) == int(ys[hole])]
    return same or ks


def _box(box):
    """Compute what plan_transfer needs from a station box dict."""
    samples, ys, grounds, idx = box["samples"], box["ys"], box["grounds"], box["idx"]
    lo, hi, hole = station_frame(samples, ys, idx)
    kind = station_kind(int(ys[idx]), int(grounds[idx]))
    return dict(box, lo=lo, hi=hi, hole=hole, kind=kind,
                interior=box_cells(samples, lo, hi, BOX_HALF - 2),
                own=box_cells(samples, lo, hi, BOX_HALF + 2))


def _leg(bx, px, pz):
    """Connect (px, pz) into station box bx: choose the opening position in the
    paid area nearest to it.

    Returns (k, side, level, passage vertices [...], opening cells).
    """
    samples, ys = bx["samples"], bx["ys"]
    best = None
    for side in (1, -1):
        ks = paid_range(samples, ys, bx["idx"], bx["kind"], side)
        if not ks:
            continue
        k = min(ks, key=lambda k: (samples[k][0] - px) ** 2 + (samples[k][1] - pz) ** 2)
        _, off = local_coords(samples, k, px, pz)
        if (off >= 0) != (side > 0):
            continue
        band = offset_point(samples, k, side * PASS_OFF)
        d = math.hypot(band[0] - px, band[1] - pz)
        if best is None or d < best[0]:
            best = (d, k, side, band)
    if best is None:
        return None
    d, k, side, band = best
    level = int(ys[k]) + LEVEL_DY[bx["kind"]]
    pts = [(px, pz), band, offset_point(samples, k, side * (BOX_HALF - 1))]
    holes = hole_cells(samples, bx["lo"], bx["hi"], k, side)
    return k, side, level, pts, holes


def _leg_blocked(bx, cells, level, occ, used, exempt):
    """Check whether passage cells can be laid on this level: they must not hit
    another line, another shaft, or a passage on a different level (passages of
    the same segment on the same level may merge)."""
    chk = (cells | outer_ring(cells)) - exempt - bx["own"]
    if occ.any_blocked(chk, level - 1, level + 3, skip_tag=bx["tag"]):
        return "hits another line's structure", occ.who(chk, level - 1, level + 3, skip_tag=bx["tag"])
    same = passage_tag(bx["tag"], level)
    if used.any_blocked(chk, level - 1, level + 3, ignore=lambda t: t == same):
        return "hits another shaft or passage", used.who(chk, level - 1, level + 3,
                                                         ignore=lambda t: t == same)
    return None


def outer_ring(cells):
    ring = set()
    for x, z in cells:
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                c = (x + dx, z + dz)
                if c not in cells:
                    ring.add(c)
    return ring


def _near_off(bx, x0, z0, dx=None, dz=None):
    """Return how close the shaft body (every cell, margin included) comes to
    this line's centerline. Only the 200 m before and after the station box are
    scanned. Without a direction, only the shaft's center cell is measured (for
    the coarse filter)."""
    samples = bx["samples"]
    a, b = max(0, bx["lo"] - 400), min(len(samples) - 1, bx["hi"] + 400)
    di, _ = nearest_index(samples, x0, z0, a, b)
    if dx is None:
        return abs(local_coords(samples, di, x0, z0)[1])
    return min(abs(local_coords(samples, di, cx, cz)[1])
               for cx, cz in shaft_cells(x0, z0, dx, dz, margin=1))


def _pairs(A, B):
    """Return the connection-point pairs on the paid-area side-wall bands of
    the two station boxes, nearest first: [(d, ka, sa, pa, kb, sb, pb)]."""
    out = []
    for sa in (1, -1):
        for ka in paid_range(A["samples"], A["ys"], A["idx"], A["kind"], sa):
            pa = offset_point(A["samples"], ka, sa * PASS_OFF)
            for sb in (1, -1):
                for kb in paid_range(B["samples"], B["ys"], B["idx"], B["kind"], sb):
                    pb = offset_point(B["samples"], kb, sb * PASS_OFF)
                    d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
                    out.append((d, ka, sa, pa, kb, sb, pb))
    out.sort(key=lambda t: t[0])
    return out


def plan_transfer(box_a, box_b, occ, used):
    """Plan a transfer passage between the two station boxes of a transfer
    station (paid area to paid area).

    box_* is dict(samples, ys, grounds, idx, tag); tag is the segment's tag in
    occ.

    If the two levels are at the same height (difference <= LEVEL_DIRECT), one
    passage connects them directly. Otherwise a switchback shaft is placed
    between the two station boxes, with a passage from each level to the shaft
    door. The shaft's doors are on the same face (the top and bottom doors of
    ShaftStair both open at a=-1), so both passages leave from that door, go
    straight for four cells (the porch) and then turn toward their own station
    box.

    Shaft position: a grid is laid around the nearest pair of connection points
    of the two station boxes, and positions close to both connection points are
    tried first. At transfer stations where the lines cross (Guting, Dongmen,
    Ximen, ...), the connection points of both boxes are right beside the
    crossing, and every position near the center of the grid is too close to
    both lines; the shaft has to retreat into one of the quadrants of the
    crossing. So a coarse filter on the shaft center comes first (>= CLEAR_OFF
    + 5 from both lines), and only candidates that pass are checked cell by
    cell. Each candidate must (1) keep every cell of the shaft body far enough
    from the centerlines of both lines (so it blocks no one's passage band),
    (2) keep the shaft body clear of every structure and of shafts and passages
    already built, and (3) keep each of the two passages clear on its own
    level. The first candidate that passes is used.

    Returns dict(ok, well, legs, reason):
      well   (x0, z0, ux, uz, top, bottom), or None when connected directly
      legs   [(box_tag, level, cells)], the floor cells to lay on each level
             (openings included)
    """
    A, B = _box(box_a), _box(box_b)
    pairs = _pairs(A, B)
    if not pairs:
        return dict(ok=False, reason="no paid-area side wall to open in the station boxes")
    d = pairs[0][0]
    if d > TRANSFER_MAX_M:
        return dict(ok=False, reason=f"station boxes {d:.0f} m apart: too far")
    _, ka, sa, pa, kb, sb, pb = pairs[0]
    la = int(A["ys"][ka]) + LEVEL_DY[A["kind"]]
    lb = int(B["ys"][kb]) + LEVEL_DY[B["kind"]]

    # ---- Same level: connect directly with one passage; if the nearest pair is blocked, try the next ----
    if abs(la - lb) <= LEVEL_DIRECT:
        reasons = {}
        for _, ka, sa, pa, kb, sb, pb in pairs[:MAX_PAIRS]:
            la = int(A["ys"][ka]) + LEVEL_DY[A["kind"]]
            pts = [offset_point(A["samples"], ka, sa * (BOX_HALF - 1)), pa, pb,
                   offset_point(B["samples"], kb, sb * (BOX_HALF - 1))]
            cells = polyline_cells(pts, PASS_HALF) - A["interior"] - B["interior"]
            cells |= hole_cells(A["samples"], A["lo"], A["hi"], ka, sa)
            cells |= hole_cells(B["samples"], B["lo"], B["hi"], kb, sb)
            # When checking the A end, exempt the cells around station box B
            # (and vice versa): the passage has to enter both boxes anyway, and
            # its outer ring is bound to touch the other box structure.
            why = _leg_blocked(A, cells, la, occ, used, B["own"])
            if why is None:
                why = _leg_blocked(B, cells, la, occ, used, A["own"])
            if why is not None:
                reasons["passage " + why[0]] = reasons.get("passage " + why[0], 0) + 1
                continue
            for c in cells:
                used.add(c[0], c[1], la - 1, la + 3, passage_tag(A["tag"], la))
            return dict(ok=True, well=None, legs=[(A["tag"], la, cells)], reason=None,
                        length=len(cells))
        why = "; ".join(f"{k}: {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]))
        return dict(ok=False, reason=f"none of {min(len(pairs), MAX_PAIRS)} connection-point pairs worked ({why})")
    if abs(la - lb) < LEVEL_WELL:
        return dict(ok=False, reason=f"levels only {abs(la - lb)} m apart: the shaft's two doors would cut into each other")

    # ---- Different levels: find a shaft position ----
    mx, mz = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
    r = int(d / 2) + 60
    cands = []
    for gx in range(int(mx) - r, int(mx) + r + 1, GRID_M):
        for gz in range(int(mz) - r, int(mz) + r + 1, GRID_M):
            est = math.hypot(gx - pa[0], gz - pa[1]) + math.hypot(gx - pb[0], gz - pb[1])
            cands.append((est, gx, gz))
    cands.sort()
    y_lo, y_hi = well_span(la, lb)
    tries = 0
    reasons = {}
    for est, gx, gz in cands:
        if tries >= MAX_TRIES:
            break
        if _near_off(A, gx, gz) < CLEAR_OFF + 5 or _near_off(B, gx, gz) < CLEAR_OFF + 5:
            continue                                   # Coarse filter: the shaft center alone is too close.
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            tries += 1
            if _near_off(A, gx, gz, dx, dz) < CLEAR_OFF or _near_off(B, gx, gz, dx, dz) < CLEAR_OFF:
                reasons["shaft too close to a station box"] = reasons.get("shaft too close to a station box", 0) + 1
                continue
            cells = shaft_cells(gx, gz, dx, dz)
            if occ.any_blocked(cells, y_lo, y_hi) or used.any_blocked(cells, y_lo, y_hi):
                reasons["shaft hits something"] = reasons.get("shaft hits something", 0) + 1
                continue
            door = (gx - dx, gz - dz)
            porch = (gx - 5 * dx, gz - 5 * dz)
            # The shaft body (the door row and the entrance landing excepted):
            # when a passage turns from the porch toward a station box that lies
            # beside and behind the shaft, the straight line cuts diagonally
            # across the shaft body. The shaft is built after the passages, so
            # once its walls are restored the passage is cut (the transfers at
            # Banqiao, Touqianzhuang and Taipei Nangang Exhibition Center all
            # led to a dead end at the top of the shaft this way).
            body = {c for c in cells
                    if (c[0] - gx) * dx + (c[1] - gz) * dz >= 2}
            legs, bad = [], None
            for bx in (A, B):
                leg = _leg(bx, porch[0], porch[1])
                if leg is None:
                    bad = "no opening position found"; break
                k, side, level, pts, holes = leg
                lcells = polyline_cells([door] + pts, PASS_HALF) - bx["interior"] | holes
                if lcells & body:
                    bad = "passage crosses the shaft body"; break
                why = _leg_blocked(bx, lcells, level, occ, used, cells)
                if why is not None:
                    bad = "passage " + why[0]; break
                legs.append((bx["tag"], level, lcells))
            if bad is not None:
                reasons[bad] = reasons.get(bad, 0) + 1
                continue
            # The two passages overlap in the few cells at the door, but one is
            # above the other (by >= LEVEL_WELL), so they never touch.
            for c in shaft_cells(gx, gz, dx, dz, margin=1):
                used.add(c[0], c[1], y_lo, y_hi, ("井", "轉乘"))
            for tag, level, lcells in legs:
                for c in lcells:
                    used.add(c[0], c[1], level - 1, level + 3, passage_tag(tag, level))
            top, bottom = max(legs[0][1], legs[1][1]), min(legs[0][1], legs[1][1])
            return dict(ok=True, well=(gx, gz, dx, dz, top, bottom), legs=legs,
                        reason=None, tries=tries,
                        length=sum(len(l[2]) for l in legs))
    why = "; ".join(f"{k}: {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]))
    return dict(ok=False, reason=f"no room for a shaft at any of {tries} positions ({why})")
