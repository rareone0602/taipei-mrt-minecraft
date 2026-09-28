#!/usr/bin/env python3
"""Alignment: sampling, vertical profile, track offsets and route variant selection.

Everything here is a pure function: polylines and tags go in, coordinates and heights
come out, and no world save is touched and no block written. This code used to share
build_line.py with the code that puts blocks into the world, but the two change for
entirely different reasons: what a cross-section looks like is an artistic decision,
while whether the alignment is computed correctly is an engineering one. Separated,
the alignment can be tested on its own (see tests/test_alignment.py) without
generating a world.

Scale: 1 block = 1 meter. Coordinates: X = east, Z = south.
"""
import math

GROUND     = 64        # Top block of the superflat ground
STEP       = 0.5       # Sampling interval along the line (meters)
MAX_GRADE  = 0.04      # Maximum grade: 4%
PIER_EVERY = 25        # Pier spacing

# Track bed height above the ground for each structure type
PROFILE = {"bridge": 13, "ground": 1, "tunnel": -20}

PLATFORM_LEN = 70

# ---- Station box dimensions (every dy is relative to the track bed y) ----
# An underground station is a two-level box structure, an island platform with a concourse above:
#   dy -2 base slab / y track bed / y+1 platform / dy 6 concourse floor slab / dy 10 roof slab
# That is 13 blocks tall, so tunnel layers must be spaced 15 m apart.
BOX_HALF      = 12     # Station box half-width (including 2 blocks of lining)
PLAT_HALF     = 6      # Island platform half-width -> 13 m wide
STN_TRACK_OFF = 8      # Track center offset inside a station
TUN_TRACK_OFF = 3      # Track center offset in a running tunnel
MEZZ_DY       = 6      # Concourse floor slab
BOX_TOP_DY    = 10     # Station box roof slab
FLARE_M       = 40     # Transition length over which the tracks spread from ±3 to ±8


# ---------- Sampling and smoothing ----------

def resample(pts, kinds, step):
    """Resample at equal intervals; return (x, z, ux, uz, kind)."""
    out, acc = [], 0.0
    for i in range(len(pts) - 1):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        seg = math.hypot(x1 - x0, z1 - z0)
        if seg < 1e-9:
            continue
        ux, uz = (x1 - x0) / seg, (z1 - z0) / seg
        k = kinds[i] if i < len(kinds) else "ground"
        t = -acc
        while t < seg:
            if t >= 0:
                out.append((x0 + ux * t, z0 + uz * t, ux, uz, k))
            t += step
        acc = (acc + seg) % step
    return _smooth_tangents(out, step)


def drop_reversal(pts, kinds, thresh=140.0):
    """Cut off the part of a polyline that doubles back on itself, keeping the longer half.

    Geometry chained from an OSM relation occasionally runs to the end and comes back
    the same way (the Ankeng LRT terminus has a full 180-degree reversal). Left in, the
    two offset tracks fight over the same cells and break each other's rails; measured,
    those 220 meters cost 551 cells.
    """
    for i in range(1, len(pts) - 1):
        a = (pts[i][0] - pts[i-1][0], pts[i][1] - pts[i-1][1])
        b = (pts[i+1][0] - pts[i][0], pts[i+1][1] - pts[i][1])
        la, lb = math.hypot(*a), math.hypot(*b)
        if la < 1e-6 or lb < 1e-6:
            continue
        c = max(-1.0, min(1.0, (a[0]*b[0] + a[1]*b[1]) / (la * lb)))
        if math.degrees(math.acos(c)) < thresh:
            continue
        head, tail = pts[:i+1], pts[i:]
        if _length(head) >= _length(tail):
            return drop_reversal(head, kinds[:i], thresh)
        return drop_reversal(tail, kinds[i:], thresh)
    return pts, kinds


def _smooth_tangents(out, step, win_m=4.0):
    """Recompute each direction vector from the positions win_m meters before and after.

    The vertices of an OSM polyline are often sharp corners. Taking the direction per
    segment flips the normal instantly at a vertex, so the offset rails jump sideways
    over a long stretch, and the two tracks can even land on the same cell. Measured on
    the Ankeng LRT, 553 cells were claimed by both tracks, which breaks each of them once.
    """
    k = max(1, int(win_m / step))
    n = len(out)
    res = []
    for i in range(n):
        a, b = out[max(0, i - k)], out[min(n - 1, i + k)]
        dx, dz = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dz)
        if L < 1e-9:
            dx, dz, L = out[i][2], out[i][3], 1.0
        res.append((out[i][0], out[i][1], dx / L, dz / L, out[i][4]))
    return res


def vertical_profile(kinds, step=STEP, grade=MAX_GRADE):
    """Smooth the target heights into a vertical profile that respects the grade limit.

    It takes the lower envelope: y[i] = min_j (target[j] + grade * distance).
    Two linear sweeps suffice. As a result, a tunnel pulls the viaduct on either side
    down into an approach ramp, which is exactly how a real line must descend before
    entering a tunnel.
    """
    tgt = [GROUND + PROFILE.get(k, 1) for k in kinds]
    y = tgt[:]
    d = grade * step
    for i in range(1, len(y)):
        y[i] = min(y[i], y[i - 1] + d)
    for i in range(len(y) - 2, -1, -1):
        y[i] = min(y[i], y[i + 1] + d)
    return [int(round(v)) for v in y]


def track_offsets(samples, ys, grounds, stn_idx):
    """Return the track center offset at each sample.

    Between stations it is ±3 (a double-track tunnel). An underground station must
    spread to ±8 to fit the island platform in the middle, with a linear transition of
    FLARE_M meters in between; jumping straight across would break the rails in two.
    """
    n = len(samples)
    toff = [float(TUN_TRACK_OFF)] * n
    half = int(PLATFORM_LEN / 2 / STEP)
    fl = max(1, int(FLARE_M / STEP))
    for i in stn_idx:
        g = int(grounds[i]) if grounds is not None else GROUND
        if structure_for_ground(int(ys[i]), g) != "tunnel":
            continue                                   # Elevated stations keep side platforms
        lo, hi = max(0, i - half), min(n - 1, i + half)
        for k in range(lo, hi + 1):
            toff[k] = max(toff[k], float(STN_TRACK_OFF))
        for j in range(1, fl + 1):
            v = STN_TRACK_OFF + (TUN_TRACK_OFF - STN_TRACK_OFF) * j / fl
            if lo - j >= 0:
                toff[lo - j] = max(toff[lo - j], v)
            if hi + j < n:
                toff[hi + j] = max(toff[hi + j], v)
    return toff


def half_width(toff):
    """Return the track bed half-width: the side wall stands 2 blocks beyond the track center."""
    return max(5, int(round(toff)) + 2)

# ---------- Structure types ----------

# Where the concourse of a station that is not underground goes. When the rail top of an
# elevated station is high enough above the ground, the concourse goes under the viaduct (as
# at the real elevated stations of the Wenhu Line and the Tamsui Line); otherwise it spans
# above the platforms (the footbridge concourse of the Tamsui Line's at-grade stations).
CONC_UNDER_MIN = 9     # The rail top must be at least this far above the ground to fit a concourse
                       # under the viaduct (floor slab 2 blocks above the ground)
ELEV_UNDER_DY  = 6     # Concourse under the viaduct: standing surface = rail top - 6
                       # (floor slab at -7; the roof slab is the deck at -1)
ELEV_OVER_DY   = 8     # Concourse above the platforms: standing surface = rail top + 8
                       # (floor slab at +7, on top of the station building roof at +6)


# Height of the concourse standing surface above the rail top, per type. If the rail top slopes
# inside a station, the concourse floor slab follows it, so the concourse standing surface at a
# given sample = int(ys[i]) + LEVEL_DY[type].
LEVEL_DY = {"tunnel": MEZZ_DY + 1, "under": -ELEV_UNDER_DY, "over": ELEV_OVER_DY}


def station_kind(y, ground):
    """Return the concourse type of a station:
    "tunnel"  Underground island-platform station; concourse at rail top +7 (MEZZ_DY + 1)
    "under"   Elevated station; concourse under the viaduct, directly below the platforms
              (rail top -6)
    "over"    At-grade and low elevated stations; the concourse is a footbridge spanning the
              two side platforms (rail top +8)
    The whole station is classified once, from its center sample; heights elsewhere come
    from LEVEL_DY.
    """
    if structure_for_ground(y, ground) == "tunnel":
        return "tunnel"
    if y - ground >= CONC_UNDER_MIN:
        return "under"
    return "over"


def station_levels(y, ground):
    """Return (type, concourse standing surface y). Exit shafts, transfer passages and platform
    stairs all go by this, so it must be the only definition."""
    k = station_kind(y, ground)
    return k, y + LEVEL_DY[k]


def structure_for_ground(y, ground):
    """Choose the structure from the rail top's height above the local ground, not the OSM tags.

    The tags set the target height, but after grade smoothing an approach ramp can pull
    a viaduct all the way below the ground. Built as a viaduct there, the deck would be
    buried in the soil.
    """
    if y >= ground + 6:
        return "viaduct"
    if y >= ground - 1:
        return "surface"
    return "tunnel"

def extend_ends(samples, step, need_start=0.0, need_end=0.0):
    """Extend the samples a few meters outward along the tangent at each end (keeping its kind).

    A terminus station box extends 35 m either side of the station node, but the OSM line
    geometry ends at the terminus node: at Tamsui, Dingpu, Yingtao Fude and others only
    half the station box got built, leaving no room for platform stairs or transfer
    passages. A real terminus has a tail track anyway, so extending the line fits.
    """
    if not samples:
        return samples
    out = list(samples)
    n0 = int(round(need_start / step))
    if n0 > 0:
        x, z, ux, uz, k = out[0]
        head = [(x - ux * step * t, z - uz * step * t, ux, uz, k) for t in range(n0, 0, -1)]
        out = head + out
    n1 = int(round(need_end / step))
    if n1 > 0:
        x, z, ux, uz, k = out[-1]
        out += [(x + ux * step * t, z + uz * step * t, ux, uz, k) for t in range(1, n1 + 1)]
    return out


def terminus_extension(samples, station_pts, others=(), margin=5.0, junction_m=30.0):
    """Return how far to extend each end to fit the stations near it, in meters: (start, end).

    station_pts are the station node coordinates of this line. When a station node lies
    within 35 m of an end, the line extends half a station box beyond the node, plus
    margin; a node beyond the end (up to 35 m) also counts.

    others are the samples of the line's other variants. If another variant passes within
    junction_m of an end, that end is not a terminus but the point where a branch joins
    the trunk (Qizhang, Beitou), and an extended tail track would run straight into the
    trunk's station box; such ends are not extended.
    """
    half_m = PLATFORM_LEN / 2
    need = [0.0, 0.0]
    for slot, end, sgn in ((0, samples[0], -1), (1, samples[-1], 1)):
        x, z, ux, uz, _ = end
        if any(math.hypot(ox - x, oz - z) <= junction_m for ox, oz in others):
            continue
        for sx, sz in station_pts:
            along = ((sx - x) * ux + (sz - z) * uz) * sgn     # Positive = beyond the end
            off = abs(-(sx - x) * uz + (sz - z) * ux)
            if -half_m <= along <= half_m and off <= 30:
                need[slot] = max(need[slot], half_m + along + margin)
    return need[0], need[1]


# ---------- Route variants ----------

def _length(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _same_corridor(a, b, tol=600, len_ratio=0.2):
    """Tell whether two polylines are the two directions of the same corridor.

    Matching or swapped endpoints are enough, with a tolerance of 600 m: the two
    directions often end separately a few hundred meters around a terminus (476 m apart
    at the Taipei Zoo end of the Wenhu Line). Endpoints alone would mistake a short
    branch for the same corridor, so the lengths must also differ by no more than 20%.
    """
    pa, pb = a["points"], b["points"]
    la, lb = _length(pa), _length(pb)
    if abs(la - lb) > len_ratio * max(la, lb, 1):
        return False
    a0, a1 = tuple(pa[0]), tuple(pa[-1])
    b0, b1 = tuple(pb[0]), tuple(pb[-1])
    fwd = math.dist(a0, b0) < tol and math.dist(a1, b1) < tol
    rev = math.dist(a0, b1) < tol and math.dist(a1, b0) < tol
    return fwd or rev


def select_variants(variants, tol=60, min_new_m=400):
    """Pick a set of routes whose geometry does not overlap.

    One line often has several OSM relations: one per direction (with nearly identical
    geometry), branches, and service patterns such as express and local. Building all of
    them turns the two directions into two parallel structures; building only the longest
    misses the branches.

    It works in two steps, because no coverage threshold alone satisfies both:
      1. Collapse the two directions into one by matching endpoints (matching or swapped
         endpoints mean the same corridor).
      2. For the survivors, compute the absolute uncovered length and keep only those
         that bring genuinely new geometry.
    """
    uniq = []
    for v in sorted(variants, key=lambda v: -len(v["points"])):
        if not any(_same_corridor(v, u) for u in uniq):
            uniq.append(v)

    sel, grid = [], set()

    def mark(pts):
        for x, z in pts:
            grid.add((int(x // tol), int(z // tol)))

    def uncovered_m(pts):
        total = 0.0
        for i in range(len(pts) - 1):
            x, z = pts[i]
            gx, gz = int(x // tol), int(z // tol)
            if not any((gx + dx, gz + dz) in grid
                       for dx in (-1, 0, 1) for dz in (-1, 0, 1)):
                total += math.dist(pts[i], pts[i + 1])
        return total

    for v in uniq:
        if not sel or uncovered_m(v["points"]) > min_new_m:
            sel.append(v)
            mark(v["points"])
    return sel

