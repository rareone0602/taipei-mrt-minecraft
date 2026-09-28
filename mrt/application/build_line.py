#!/usr/bin/env python3
"""Line cross-section generator: sweeps a computed alignment into blocks for
three structure types: underground, elevated and at-grade.

The alignment itself (sampling, vertical profile, track offsets, variant
selection) lives in domain/alignment.py. This module only places the blocks.
The first parameter w of every build_* / sec_* function is a
ports.block_sink.BlockSink, not a specific world-save implementation, so tests
can pass in a DictSink.

Scale: 1 block = 1 meter. See cli/build_line.py for usage.
"""
import math

from mrt.domain import stacked as SK
from mrt.domain.alignment import (
    GROUND, STEP, PIER_EVERY, PLATFORM_LEN, BOX_HALF, PLAT_HALF,
    TUN_TRACK_OFF, MEZZ_DY, BOX_TOP_DY, LEVEL_DY, structure_for_ground,
    station_kind,
)

# ---- Block palette ----
# These decide how things look, so they belong in this layer; the alignment
# does not need to know what the platform is made of.
CONC   = "minecraft:light_gray_concrete"
DECK   = "minecraft:smooth_stone"
WALL   = "minecraft:gray_concrete"
PIER   = "minecraft:polished_andesite"
PLAT   = "minecraft:polished_diorite"
BALLAST= "minecraft:gravel"
LINING = "minecraft:deepslate_bricks"        # Tunnel lining.
PSD    = "minecraft:glass_pane"              # Platform screen doors.
GLASS  = "minecraft:light_gray_stained_glass_pane"
STAIR  = "minecraft:smooth_stone"
SLAB   = "minecraft:smooth_stone_slab[type=bottom]"
BARS   = "minecraft:iron_bars"
GATE   = "minecraft:polished_andesite"       # Fare gate cabinet.
LANE   = "minecraft:lime_concrete"           # Paving of a fare gate lane.
YELLOW = "minecraft:yellow_concrete"
AIR    = "minecraft:air"
# Lighting: an unlit underground section is pitch dark and spawns mobs.
LAMP   = "minecraft:sea_lantern"



# ---------- The three cross-sections ----------

def sec_bridge(w, x, z, nx, nz, y, ground=GROUND, pier=False, hw=5):
    for off in range(-hw, hw + 1):
        bx, bz = round(x + nx * off), round(z + nz * off)
        w.set(bx, y - 1, bz, CONC)
        if abs(off) == hw:
            w.set(bx, y, bz, CONC); w.set(bx, y + 1, bz, WALL); w.set(bx, y + 2, bz, WALL)
        elif off == 0:
            w.set(bx, y, bz, CONC); w.set(bx, y + 1, bz, WALL)
        else:
            w.set(bx, y, bz, DECK)
        for dy in range(1, 5):                  # Clearance above the deck.
            w.set(bx, y + 3 + dy, bz, AIR)
    if pier and y - 2 > ground:
        cx, cz = round(x), round(z)
        for ddx in (-1, 0, 1):
            for ddz in (-1, 0, 1):
                for yy in range(ground - 4, y - 1):
                    w.set(cx + ddx, yy, cz + ddz, PIER)
        for off in range(-hw + 1, hw):
            w.set(round(x + nx * off), y - 2, round(z + nz * off), CONC)


def sec_ground(w, x, z, nx, nz, y, ground=GROUND, hw=5):
    """At-grade section: fills an embankment where the track is above the
    ground and cuts a trench where it is below; the space above is always
    cleared."""
    for off in range(-(hw + 1), hw + 2):
        bx, bz = round(x + nx * off), round(z + nz * off)
        for yy in range(min(y - 1, ground - 1), y):
            w.set(bx, yy, bz, BALLAST)
        for dy in range(1, 8):
            w.set(bx, y + dy, bz, AIR)
        if abs(off) == hw + 1:
            w.set(bx, y, bz, WALL); w.set(bx, y + 1, bz, WALL)
        elif abs(off) == hw:
            w.set(bx, y, bz, CONC)
        elif off == 0:
            w.set(bx, y, bz, CONC); w.set(bx, y + 1, bz, WALL)
        else:
            w.set(bx, y, bz, DECK)


def sec_tunnel(w, x, z, nx, nz, y, light=False, hw=5, toff=TUN_TRACK_OFF):
    # Dig the lined box structure first, then lay the track bed. hw widens
    # before a station so that the tracks can move out to ±8.
    for off in range(-(hw + 2), hw + 3):
        bx, bz = round(x + nx * off), round(z + nz * off)
        for dy in range(-2, 8):
            edge = abs(off) >= hw + 1 or dy in (-2, 7)
            w.set(bx, y + dy, bz, LINING if edge else AIR)
    for off in range(-hw, hw + 1):
        bx, bz = round(x + nx * off), round(z + nz * off)
        w.set(bx, y - 1, bz, CONC)
        if abs(off) == hw or off == 0:
            w.set(bx, y, bz, CONC); w.set(bx, y + 1, bz, WALL)
        else:
            w.set(bx, y, bz, DECK)
    if light:
        for off in (-toff, toff):                     # One lamp above each track.
            w.set(round(x + nx * off), y + 6, round(z + nz * off), LAMP)


def sec_multi(w, x, z, nx, nz, tracks, light=False, half=2):
    """Tunnel cross-section for several tracks, or for tracks on stacked
    levels. tracks = [(offset, rail-top y), ...].

    Tracks at the same height share one box structure: the interior extends
    half blocks beyond the outermost tracks, with a low dividing wall between
    adjacent tracks (as in sec_tunnel: with two tracks at ±3 the interior is ±5
    and the wall is at 0; with three pocket tracks at −6/0/6 the interior is
    ±8 and the walls are at ±3). Tracks at different heights each get their own
    box structure, the overlap is merged into a union, and the lining is laid
    only around the outside of the union. In a level-transition section the box
    of the descending track slides from beside the other track to directly
    beneath it, so the lining has to be computed point by point, or it would
    seal off the other track's clearance. The upper level is laid first, so
    the lower level's clearance does not dig out the upper level's floor slab.
    """
    groups = {}
    for off, y in tracks:
        groups.setdefault(int(y), []).append(int(round(off)))
    interior = {}                                   # (off, y) -> block
    for y in sorted(groups, reverse=True):
        offs = sorted(groups[y])
        o0, o1 = offs[0] - half, offs[-1] + half
        curbs = {o0, o1} | {(a + b) // 2 for a, b in zip(offs, offs[1:])}
        for o in range(o0, o1 + 1):
            interior.setdefault((o, y - 1), CONC)
            interior.setdefault((o, y), CONC if o in curbs else DECK)
            for dy in range(1, 7):
                interior.setdefault((o, y + dy), WALL if (dy == 1 and o in curbs) else AIR)
    shell = set()
    for o, yy in interior:
        for do in (-2, -1, 0, 1, 2):
            for dyy in (-1, 0, 1):
                c = (o + do, yy + dyy)
                if c not in interior:
                    shell.add(c)
    for o, yy in shell:
        w.set(round(x + nx * o), yy, round(z + nz * o), LINING)
    for (o, yy), blk in interior.items():
        w.set(round(x + nx * o), yy, round(z + nz * o), blk)
    if light:
        for off, y in tracks:
            w.set(round(x + nx * off), int(y) + 6, round(z + nz * off), LAMP)


def build_alignment(w, samples, ys):
    counts = {"viaduct": 0, "surface": 0, "tunnel": 0}
    for i, (x, z, ux, uz, k) in enumerate(samples):
        nx, nz = -uz, ux
        y = ys[i]
        st = structure_for_ground(y, GROUND)
        counts[st] += 1
        if st == "tunnel":
            sec_tunnel(w, x, z, nx, nz, y)
        elif st == "viaduct":
            sec_bridge(w, x, z, nx, nz, y, GROUND,
                       pier=(abs((i * STEP) % PIER_EVERY) < STEP / 2))
        else:
            sec_ground(w, x, z, nx, nz, y)
    return counts


# ---------- Stairs ----------

def _stair_run(w, samples, ys, s0, d, per_m, y_from, y_to, off_lo, off_hi,
               head=4, clear_dy=None, wall_offs=(), wall_ground=None,
               clear_max_dy=None):
    """Lay a straight stair run that rises or falls 0.5 m per meter (full
    blocks alternating with slabs).

    y_from / y_to are standing-surface heights, that is, the top faces of
    blocks. The alternation must match the direction of travel: going down,
    place the full block first and then the slab. The other way round leaves a
    1.5 m drop every two meters, which you can walk down but not climb up.

    By default, headroom is cleared to head blocks above the tread. clear_dy
    clears to rail top + clear_dy instead, and clear_max_dy is an upper limit:
    when the top of the stair sits right under the roof slab, the headroom of
    the last few steps would dig through the slab.
    """
    n = int(round(abs(y_to - y_from) * 2))
    sgn = 1.0 if y_to > y_from else -1.0
    out, treads = [], []
    for t in range(1, n + 1):
        si = s0 + d * t * per_m
        if not (0 <= si < len(samples)):
            break
        surf = y_from + sgn * 0.5 * t
        half = abs(surf - math.floor(surf)) > 0.25
        yb = int(math.floor(surf)) if half else int(round(surf)) - 1
        treads.append((si, yb, SLAB if half else STAIR))
        out.append((si, yb))

    def cells_at(si):
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        return [(round(x + nx * off), round(z + nz * off)) for off in range(off_lo, off_hi + 1)]

    # When the alignment runs at 45 degrees, the cells of two adjacent treads
    # may touch only at a corner: the sample point advances (0.7, 0.7) per
    # meter, and after rounding the two treads' cell sets may share no
    # edge-adjacent pair. (The two-block-wide platform stairs at Liuzhangli and
    # Tamsui were like this: in cross-section every tread is there, but the
    # stair breaks off halfway when you walk it.)
    # Fix: each tread also paves the cells of the half-meter sample point
    # between the previous tread and this one, but only cells that no tread
    # uses; the original treads do not change by a single cell.
    main = set()
    for si, yb, blk in treads:
        main.update(cells_at(si))
    filled = set()
    per_tread = []
    for si, yb, blk in treads:
        cells = cells_at(si)
        sh = si - d * (per_m // 2)
        if per_m >= 2 and 0 <= sh < len(samples):
            for c in cells_at(sh):
                if c not in main and c not in filled:
                    filled.add(c)
                    cells.append(c)
        per_tread.append(cells)
    # The cells of the half-meter sample point may also land exactly on an
    # existing tread (common when the alignment is close to 45 degrees), in
    # which case nothing is added. So check each pair of adjacent treads
    # again: if they still share no edge-adjacent pair, add one cell between
    # the diagonally touching pair (at the height of the first of the two), which
    # guarantees that the whole stair is 4-connected.
    for t in range(len(per_tread) - 1):
        a, b = per_tread[t], set(per_tread[t + 1])
        if any((ax + ddx, az + ddz) in b for ax, az in a
               for ddx, ddz in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            continue
        for ax, az in a:
            hit = next(((bx, bz) for bx, bz in b if abs(bx - ax) == 1 and abs(bz - az) == 1), None)
            if hit is not None:
                bx, bz = hit
                cand = [(ax, bz), (bx, az)]
                c = next((q for q in cand if q not in main and q not in filled), cand[0])
                filled.add(c)
                per_tread[t].append(c)
                break
    for (si, yb, blk), cells in zip(treads, per_tread):
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        top = (int(ys[si]) + clear_dy) if clear_dy is not None else yb + head
        if clear_max_dy is not None:
            top = min(top, int(ys[si]) + clear_max_dy)
        for bx, bz in cells:
            w.set(bx, yb, bz, blk)
            for yy in range(yb + 1, top + 1):
                w.set(bx, yy, bz, AIR)
        for off in wall_offs:
            bx, bz = round(x + nx * off), round(z + nz * off)
            for yy in range(yb, yb + 1 + head):
                w.set(bx, yy, bz,
                      WALL if wall_ground is None or yy < wall_ground else BARS)
    return out


# ---------- Stations ----------

def build_station(w, samples, ys, idx, underground, label=None, grounds=None,
                  access=True, stacked=None, name_signs=False):
    """With access=False the template exit stair is not built: stations with
    real exits (application/build_exits.py) use those, and the template one
    would only add a hole that nobody walks through. This applies to both
    underground stations and side-platform stations.

    stacked is the layout from domain/stacked.layout(), for underground
    stations whose two tracks are split across an upper and a lower level
    (Fuzhong's stacked side platforms, and a stacked island shared by two
    lines, as at Ximen). samples are then in the station-box frame (for a
    shared station box, the frame of the centerline between the two lines; see
    stacked.station_samples).

    Only with name_signs=True are the old text-only station name signs placed
    on the platform (_plat_signs / place_signs). In a full-network build the
    row of platform screen doors carries ride signs instead
    (application/signage.py, following the berths from domain/network.py), and
    the same cell must not get a station name sign as well; only
    cli/build_line, which does not plan the network, still uses them."""
    n = len(samples)
    half = int(PLATFORM_LEN / 2 / STEP)
    lo, hi = max(0, idx - half), min(n - 1, idx + half)
    plat_label = label if name_signs else None
    if stacked is not None:
        _station_stacked(w, samples, ys, grounds, lo, hi, label, stacked, access=access,
                         plat_label=plat_label)
    elif underground:
        _station_island(w, samples, ys, grounds, lo, hi, label, access=access,
                        plat_label=plat_label)
    else:
        _station_side(w, samples, ys, grounds, lo, hi, label, access=access,
                      plat_label=plat_label)


# ===== Underground stations: island platform + concourse =====

def _station_island(w, samples, ys, grounds, lo, hi, label, access=True, plat_label=None):
    """Underground island-platform station.

    Almost every underground Taipei Metro station has an island platform: the
    tracks run on the two sides, the platform sits in the middle, and a
    concourse is stacked on top. With side platforms, the tracks in the middle
    would cut the concourse circulation in two, and each side would need its
    own set of stairs.

    This is done in two passes: first the whole station box is dug out, then
    the fittings are installed. Samples are only STEP meters apart, so digging
    and installing in one pass would let the next sample's excavation erase
    the platform screen doors and lamps just installed.
    """
    per_m = max(1, int(round(1.0 / STEP)))

    # ---- Pass 1: excavate ----
    for i in range(lo, hi + 1):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        end = i in (lo, hi)
        for off in range(-BOX_HALF, BOX_HALF + 1):
            bx, bz = round(x + nx * off), round(z + nz * off)
            for dy in range(-2, BOX_TOP_DY + 1):
                # The end walls are opened only across the tunnel
                # cross-section (±10 after widening). A solid end wall would
                # seal the station box off; a fully open one would let the
                # concourse above open straight into the tunnel.
                portal = abs(off) <= BOX_HALF - 2 and -1 <= dy <= 6
                solid = (abs(off) >= BOX_HALF - 1 or dy in (-2, BOX_TOP_DY)
                         or (end and not portal))
                w.set(bx, y + dy, bz, LINING if solid else AIR)

    # ---- Pass 2: install ----
    for i in range(lo, hi + 1):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        along = (i - lo) * STEP
        door = (along % 7.0) < 2.0

        for off in list(range(-10, -PLAT_HALF)) + list(range(PLAT_HALF + 1, 11)):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, y - 1, bz, CONC)
            w.set(bx, y, bz, DECK)                      # Track bed on both sides.

        for off in range(-PLAT_HALF, PLAT_HALF + 1):    # Island platform.
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, y - 1, bz, CONC)
            w.set(bx, y, bz, CONC)
            w.set(bx, y + 1, bz, YELLOW if abs(off) == PLAT_HALF - 1 else PLAT)

        for off in (-PLAT_HALF, PLAT_HALF):             # Platform screen doors.
            bx, bz = round(x + nx * off), round(z + nz * off)
            for yy in range(y + 2, y + MEZZ_DY):
                w.set(bx, yy, bz, AIR if door else PSD)

        for off in range(-(BOX_HALF - 2), BOX_HALF - 1):
            w.set(round(x + nx * off), y + MEZZ_DY, round(z + nz * off), CONC)

        if (along % 8.0) < STEP:                        # Lighting.
            for off in (-10, -3, 3, 10):
                w.set(round(x + nx * off), y + MEZZ_DY - 1, round(z + nz * off), LAMP)
            for off in (-7, 0, 7):
                w.set(round(x + nx * off), y + BOX_TOP_DY - 1, round(z + nz * off), LAMP)

    _gates(w, samples, ys, lo + 14 * per_m, per_m)
    for a0 in (24, 48):
        _plat_stair(w, samples, ys, lo + a0 * per_m, per_m)
    if access:
        _station_access(w, samples, ys, grounds, lo, hi, label)
    if plat_label:
        _plat_signs(w, samples, ys, lo, hi, plat_label)


def _gates(w, samples, ys, s0, per_m, floor_dy=MEZZ_DY, half=BOX_HALF - 2):
    """Fare gates: a row across the whole concourse that separates the paid
    area from the unpaid area.

    The exit is at the lo+6 end and the platform stairs are at the other end,
    so only a row across the middle blocks the way; a short row would simply
    be walked around.

    floor_dy is the height of the concourse floor slab relative to the rail
    top (MEZZ_DY, as in underground stations, by default), and half is the
    half-width of the gate row. The concourse of a side-platform station uses
    the same gates with a different floor height.
    """
    for t in range(2 * per_m):
        si = s0 + t
        if not (0 <= si < len(samples)):
            continue
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        ym = int(ys[si]) + floor_dy
        for off in range(-half, half + 1):
            bx, bz = round(x + nx * off), round(z + nz * off)
            if off % 3 == 0:                            # Gate lane.
                w.set(bx, ym, bz, LANE)
                for yy in range(ym + 1, ym + 4):
                    w.set(bx, yy, bz, AIR)
            else:
                w.set(bx, ym + 1, bz, GATE)
                for yy in range(ym + 2, ym + 4):
                    w.set(bx, yy, bz, AIR)


def _plat_stair(w, samples, ys, s0, per_m, off_lo=-3, off_hi=3):
    """Stair from the concourse down to the platform, which also opens the
    hole in the floor slab. off_lo..off_hi are the tread offsets (−3..3,
    centered, for an island platform; on the platform for stacked side
    platforms)."""
    y0 = int(ys[min(s0, len(ys) - 1)])
    steps = _stair_run(w, samples, ys, s0, 1, per_m,
                       y0 + MEZZ_DY + 1, y0 + 2, off_lo, off_hi,
                       clear_dy=BOX_TOP_DY - 1)
    for si, yb in steps:                                # Railings on both sides of the opening.
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        ym = int(ys[si]) + MEZZ_DY
        for off in (off_lo - 1, off_hi + 1):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, ym, bz, CONC)
            w.set(bx, ym + 1, bz, BARS)


def _level_stair(w, samples, ys, s0, per_m, drop, off_lo, off_hi):
    """Stair in a stacked station from the upper platform down to the lower
    platform (the standing surface falls from rail top +2 to +2 − drop).

    Headroom is cleared to rail top +5 at most: the top of the stair is on the
    upper platform, and four blocks of headroom would dig through the
    concourse floor slab at +6. The treads that cut into the upper platform
    get railings on both sides, and another row runs across the far end of the
    hole: without it, someone walking over from the other end of the platform
    would step straight into a four-block-deep hole.
    """
    y0 = int(ys[min(s0, len(ys) - 1)])
    steps = _stair_run(w, samples, ys, s0, 1, per_m, y0 + 2, y0 + 2 - drop,
                       off_lo, off_hi, head=4, clear_max_dy=5)
    opened = []
    for si, yb in steps:
        # The headroom reaches the upper platform surface (+1).
        opened.append(yb + 4 >= int(ys[si]) + 1)
    for k, (si, yb) in enumerate(steps):
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        stand = int(ys[si]) + 2
        if opened[k] and yb < int(ys[si]):
            for off in (off_lo - 1, off_hi + 1):
                w.set(round(x + nx * off), stand, round(z + nz * off), BARS)
        elif not opened[k] and k > 0 and opened[k - 1]:
            for off in range(off_lo - 1, off_hi + 2):
                w.set(round(x + nx * off), stand, round(z + nz * off), BARS)
    return steps


def _station_access(w, samples, ys, grounds, lo, hi, label):
    """Stair from the concourse to the ground, and the at-grade exit building.

    The stair runs outside the station box at offsets 13 to 17. A deep station
    needs 2 meters of horizontal run per meter of descent, and on the deepest
    line one flight is 76 meters long, so it cannot fit within the platform
    length.
    """
    per_m = max(1, int(round(1.0 / STEP)))
    sd = min(lo + 6 * per_m, len(samples) - 1)
    y0 = int(ys[sd])
    ym = y0 + MEZZ_DY + 1                               # Standing height on the concourse.
    g0 = int(grounds[sd]) if grounds is not None else GROUND
    # g0 is the topmost ground block; a person standing on it has their feet
    # at g0+1. The stair has to climb to g0+1 to meet the station building's
    # paving flush (_hall raises the paving to g0). It used to stop at g0,
    # which left the top of the stair one block below the building: you could
    # walk down, but coming up took a jump.
    n = g0 + 1 - ym
    if n < 2:
        return
    need = (2 * n + 12) * per_m
    d = 1 if sd + need < len(samples) else -1
    if not (0 <= sd + d * need < len(samples)):
        return

    for t in range(-2 * per_m, 2 * per_m + 1):          # Passage through the station box side wall.
        si = sd + t
        if not (0 <= si < len(samples)):
            continue
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        ymm = int(ys[si]) + MEZZ_DY
        for off in range(BOX_HALF - 1, 18):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, ymm, bz, CONC)
            for yy in range(ymm + 1, ymm + 4):
                w.set(bx, yy, bz, AIR)
            w.set(bx, ymm + 4, bz, LINING)

    _stair_run(w, samples, ys, sd + d * 2 * per_m, d, per_m, ym, g0 + 1, 13, 17,
               head=4, wall_offs=(12, 18), wall_ground=g0)
    # The headroom of the last few steps digs through the ground surface, so
    # the station building has to reach back to t=-9; otherwise an uncovered
    # trench is left in front of the exit.
    _hall(w, samples, ys, sd + d * (2 + 2 * n) * per_m, d, per_m, g0, label,
          t0=-9, t1=6, o0=12, o1=18, floor_t0=1, door_t=6)


def _hall(w, samples, ys, s0, d, per_m, g0, label, t0, t1, o0, o1,
          floor_t0, door_t, open_end=None, gate_t=None):
    """Ground-level station building: t0..t1 is the range along the line, and
    o0/o1 are the offsets of the two side walls (all relative to s0).

    The open_end end is left open (the stair enters there), and the door_t end
    has a door to the street.
    """
    mid = (o0 + o1) // 2
    for t in range(t0, t1 + 1):
        si = s0 + d * t * per_m
        if not (0 <= si < len(samples)):
            continue
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        cap = t in (t0, t1) and t != open_end
        for off in range(o0 - 1, o1 + 2):
            bx, bz = round(x + nx * off), round(z + nz * off)
            if o0 <= off <= o1:
                if t >= floor_t0:
                    for yy in range(g0 - 3, g0 + 1):
                        w.set(bx, yy, bz, CONC)         # Level the paving.
                side = off in (o0, o1) or cap
                for yy in range(g0 + 1, g0 + 5):
                    door = (t == door_t and mid - 1 <= off <= mid + 1
                            and yy <= g0 + 3)
                    if side and not door:
                        w.set(bx, yy, bz, GLASS if g0 + 2 <= yy <= g0 + 3 else CONC)
                    else:
                        w.set(bx, yy, bz, AIR)
                if t % 4 == 0 and off == mid:
                    w.set(bx, g0 + 4, bz, LAMP)
            w.set(bx, g0 + 5, bz, CONC)                 # Roof, including the eaves.
        if gate_t is not None and t in (gate_t, gate_t + 1):
            for off in range(o0 + 1, o1):
                bx, bz = round(x + nx * off), round(z + nz * off)
                if (off - mid) % 3 == 0:
                    w.set(bx, g0, bz, LANE)
                    for yy in range(g0 + 1, g0 + 4):
                        w.set(bx, yy, bz, AIR)
                else:
                    w.set(bx, g0 + 1, bz, GATE)
                    for yy in range(g0 + 2, g0 + 4):
                        w.set(bx, yy, bz, AIR)
    if label:
        st = door_t + (1 if door_t == t1 else -1)
        si = s0 + d * st * per_m
        if 0 <= si < len(samples):
            x, z, ux, uz, _ = samples[si]
            nx, nz = -uz, ux
            bx, bz = round(x + nx * mid), round(z + nz * mid)
            w.set(bx, g0, bz, CONC)
            w.sign(bx, g0 + 1, bz, [label[0], label[1], label[2], "出口 Exit"],
                   facing=(nx, nz))


def _plat_signs(w, samples, ys, lo, hi, label, offs=(PLAT_HALF, -PLAT_HALF), dy0=0):
    """A station name sign every 20 m on the platform screen doors, facing
    into the platform. offs are the offsets of the platform screen doors, and
    dy0 is this level's rail top relative to the alignment's rail top
    (−LEVEL_H for the lower level of a stacked station)."""
    ref, zh, en = label
    per_m = max(1, int(round(1.0 / STEP)))
    for i in range(lo + 20 * per_m, hi - 8 * per_m, 20 * per_m):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i]) + dy0
        for off in offs:
            face = (-nx, -nz) if off > 0 else (nx, nz)
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.sign(bx, y + 2, bz, [ref, zh, en, ""], facing=face)


# ===== Stacked underground stations: two tracks on an upper and a lower level =====

def _station_stacked(w, samples, ys, grounds, lo, hi, label, lay, access=True,
                     plat_label=None):
    """Two-level underground station (domain/stacked.py). The upper level has
    the same dimensions as an island station: the concourse stays at rail top
    +7, so exits, transfer passages and verification tools need no changes.
    The lower level is a full copy placed LEVEL_H blocks below, and its roof
    slab is the upper level's floor slab. lay is the layout from
    stacked.layout(): stacked side platforms (Fuzhong) have one track per
    level with the platforms on the same side; a shared island (Ximen) has two
    tracks per level, one for each line.

    As with an island station, this is done in two passes: first the
    21-block-tall box structure is dug out, then both levels are fitted out.
    Each end wall gets one opening at the tunnel cross-section height of each
    level (upper dy −1..6, lower dy −9..−3).
    """
    per_m = max(1, int(round(1.0 / STEP)))
    H, bot = SK.LEVEL_H, SK.BOX_BOTTOM_DY

    for i in range(lo, hi + 1):                         # ---- Pass 1: excavate ----
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        end = i in (lo, hi)
        for off in range(-BOX_HALF, BOX_HALF + 1):
            bx, bz = round(x + nx * off), round(z + nz * off)
            for dy in range(bot, BOX_TOP_DY + 1):
                portal = abs(off) <= BOX_HALF - 2 and (-1 <= dy <= 6 or bot + 1 <= dy <= -3)
                solid = (abs(off) >= BOX_HALF - 1 or dy in (bot, -2, BOX_TOP_DY)
                         or (end and not portal))
                w.set(bx, y + dy, bz, LINING if solid else AIR)

    for dy0 in (0, -H):                                 # ---- Pass 2: both platform levels ----
        _stacked_level(w, samples, ys, lo, hi, dy0, lay)

    for i in range(lo, hi + 1):                         # Concourse floor slab and lighting.
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        for off in range(-(BOX_HALF - 2), BOX_HALF - 1):
            w.set(round(x + nx * off), y + MEZZ_DY, round(z + nz * off), CONC)
        if (((i - lo) * STEP) % 8.0) < STEP:
            for off in (-7, 0, 7):
                w.set(round(x + nx * off), y + BOX_TOP_DY - 1, round(z + nz * off), LAMP)

    _gates(w, samples, ys, lo + 14 * per_m, per_m)
    s0, s1 = lay["stair"]
    for a0 in (24, 48):
        _plat_stair(w, samples, ys, lo + a0 * per_m, per_m, off_lo=s0, off_hi=s1)
    l0, l1 = lay["lstair"]
    _level_stair(w, samples, ys, lo + 4 * per_m, per_m, H, l0, l1)
    if access:
        _station_access(w, samples, ys, grounds, lo, hi, label)
    if plat_label:
        for dy0 in (0, -H):
            _plat_signs(w, samples, ys, lo, hi, plat_label, offs=lay["psd"], dy0=dy0)


def _stacked_level(w, samples, ys, lo, hi, dy0, lay):
    """One level of a stacked station, with its rail top at the alignment's
    rail top + dy0. Lays the platform paving (including the platform screen
    door row), the warning strip and the platform screen doors; everything
    else is track bed. Lamps hang under this level's roof slab."""
    p0, p1 = lay["plat"]
    plat = set(range(p0, p1 + 1)) | set(lay["psd"])
    for i in range(lo, hi + 1):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i]) + dy0
        along = (i - lo) * STEP
        door = (along % 7.0) < 2.0
        for off in range(-(BOX_HALF - 2), BOX_HALF - 1):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, y - 1, bz, CONC)
            if off in plat:
                w.set(bx, y, bz, CONC)
                w.set(bx, y + 1, bz, YELLOW if off in lay["yellow"] else PLAT)
            else:
                w.set(bx, y, bz, DECK)
        for off in lay["psd"]:
            bx, bz = round(x + nx * off), round(z + nz * off)
            for yy in range(y + 2, y + MEZZ_DY):
                w.set(bx, yy, bz, AIR if door else PSD)
        if (along % 8.0) < STEP:
            for off in (-10, -3, 3, 10):
                w.set(round(x + nx * off), y + MEZZ_DY - 1, round(z + nz * off), LAMP)


# ===== Elevated and at-grade stations: side platforms =====

def _station_side(w, samples, ys, grounds, lo, hi, label, access=True, plat_label=None):
    """Side-platform station: the track bed is level with the line between
    stations, and the platform surface is 1 m higher.

    The two platforms are enclosed separately and joined by a concourse
    (_side_concourse): the fare gates are on the concourse, with one stair per
    platform. Real exits also connect to the concourse. With access=False the
    template ground-level stair is not built (it only reaches the + side
    platform, and stations with real exits do not need it).
    """
    roof_h = 6
    for i in range(lo, hi + 1):                         # Pass 1: clear the station box.
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        for off in range(-11, 12):
            bx, bz = round(x + nx * off), round(z + nz * off)
            for dy in range(1, roof_h + 1):
                w.set(bx, y + dy, bz, AIR)

    for i in range(lo, hi + 1):                         # Pass 2: install.
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        end = i in (lo, hi)
        along = (i - lo) * STEP
        door = (along % 7.0) < 2.0

        for off in range(-5, 6):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, y - 1, bz, CONC)
            w.set(bx, y, bz, DECK)

        for off in (-5, 5):                             # Platform screen doors.
            bx, bz = round(x + nx * off), round(z + nz * off)
            for yy in range(y + 1, y + 5):
                w.set(bx, yy, bz, AIR if door else PSD)

        for off in list(range(-10, -5)) + list(range(6, 11)):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, y - 1, bz, CONC)
            w.set(bx, y, bz, CONC)
            w.set(bx, y + 1, bz, YELLOW if abs(off) == 6 else PLAT)
            if abs(off) == 10 or end:
                for yy in range(y + 2, y + roof_h):
                    w.set(bx, yy, bz, GLASS if not end else CONC)
        for off in range(-10, 11):
            w.set(round(x + nx * off), y + roof_h, round(z + nz * off), CONC)

        if (along % 8.0) < STEP:                        # Lighting.
            for off in (-8, 0, 8):
                w.set(round(x + nx * off), y + roof_h - 1, round(z + nz * off), LAMP)

    _side_concourse(w, samples, ys, grounds, lo, hi)
    if plat_label:
        place_signs(w, samples, ys, lo, hi, plat_label)
    if access:
        build_entrance(w, samples, ys, lo, hi, grounds, label)


def _side_concourse(w, samples, ys, grounds, lo, hi):
    """Concourse of a side-platform station: the fare gates and the stairs to
    both platforms are on this level, and real exits
    (application/build_exits.py) connect here too.

    Which level it is on is decided by station_kind in domain/alignment.py:
    the whole station is judged once, from the center sample only, and every
    height is then computed point by point as int(ys[i]) + LEVEL_DY[kind], so
    the floor slab follows any grade in the station's rail top (the same rule
    as the concourse of an underground station):
      "under"  concourse under the viaduct: floor slab at rail top -7, and
               the bridge deck (-1) is its roof slab; 5 blocks of clearance,
               glass side walls, and the piers pass through the hall
      "over"   footbridge concourse: floor slab at rail top +7, stacked on the
               station building roof (+6), roof slab at +11, glass side walls

    The fare gates are at lo+14 m (as in underground stations; the side-wall
    opening for exits is at lo+7). Both platform stairs are at the hi end, in
    the two outermost rows of each platform (|off| 8..9), with the foot of
    each stair in the paid area:
      · At the lo end, the "over" stair would open a hole at lo+1..lo+11 in
        the concourse floor slab, right against the door the exit opens at
        lo+5..lo+9: one step out of the door would be a three-block-deep
        stairwell.
      · The "under" stair is 16 m long; measured from the lo end, its foot
        would land in the gate row at lo+14.
    The two outermost rows of each platform go to the stairs; the warning
    strip (|off| 6) and the inner row remain walkable.
    """
    per_m = max(1, int(round(1.0 / STEP)))
    mid = (lo + hi) // 2
    g_mid = int(grounds[mid]) if grounds is not None else GROUND
    kind = station_kind(int(ys[mid]), g_mid)
    if kind == "tunnel":                                # Underground stations never get here.
        return
    dy = LEVEL_DY[kind]                                 # Standing surface relative to the rail top.
    under = kind == "under"

    def levels(y):
        """(floor slab block, roof slab block)"""
        return y + dy - 1, (y - 1 if under else y + dy + 3)

    # ---- Floor slab, clearance, side walls, end walls, lighting ----
    for i in range(lo, hi + 1):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        fl, ceil = levels(y)
        end = i in (lo, hi)
        for off in range(-11, 12):
            bx, bz = round(x + nx * off), round(z + nz * off)
            side = abs(off) == 11
            w.set(bx, fl, bz, CONC)
            w.set(bx, ceil, bz, CONC)                   # For "under", |off|<=10 is the bridge deck.
            for yy in range(fl + 1, ceil):
                w.set(bx, yy, bz, CONC if end else (GLASS if side else AIR))
        if not end and (((i - lo) * STEP) % 8.0) < STEP:  # No lamps in the end walls.
            for off in (-7, 0, 7):
                w.set(round(x + nx * off), ceil - 1, round(z + nz * off), LAMP)

    _gates(w, samples, ys, lo + 14 * per_m, per_m, floor_dy=dy - 1)

    # ---- Piers ----
    # sec_bridge built the line between stations before the station, and the
    # excavation above cuts away the part of each pier inside the hall. Put the
    # piers back at the sec_bridge positions (the same sampling condition, and
    # the same 3x3 rounded at the center point) so that the bridge deck has
    # support inside the hall. The floor slab cell stays CONC, so the pier
    # appears to pass through the floor slab.
    if under:
        for i in range(lo, hi + 1):
            if abs((i * STEP) % PIER_EVERY) >= STEP / 2:
                continue
            x, z, _, _, _ = samples[i]
            y = int(ys[i])
            g = int(grounds[i]) if grounds is not None else GROUND
            if y - 2 <= g:
                continue
            fl, _ = levels(y)
            cx, cz = round(x), round(z)
            for ddx in (-1, 0, 1):
                for ddz in (-1, 0, 1):
                    for yy in range(fl + 1, y - 1):
                        w.set(cx + ddx, yy, cz + ddz, PIER)

    # ---- Platform stairs ----
    # One per platform, 2 blocks wide, starting run+1 m back from the hi end;
    # "under" climbs from the concourse up to the platform, and "over" goes
    # down from the concourse. y_from / y_to are both standing surfaces: the
    # bottom slab is flush with the floor slab and the top full block is flush
    # with the platform surface (y+1), so neither end is off by a block.
    run = 2 * abs(dy - 2)
    s0 = hi - (run + 1) * per_m
    if s0 <= lo:
        return
    y0 = int(ys[s0])
    for off_lo, off_hi in ((8, 9), (-9, -8)):
        _side_stair(w, samples, ys, s0, per_m, y0 + dy, y0 + 2, off_lo, off_hi,
                    under, levels)


def _side_stair(w, samples, ys, s0, per_m, y_from, y_to, off_lo, off_hi,
                under, levels):
    """One platform stair, together with the railings around the hole it
    opens in the platform surface or the concourse floor slab.

    The headroom (4 blocks) automatically digs open the bridge deck and the
    platform surface ("under"), or the station building roof and the
    concourse floor slab ("over"); clear_max_dy stops it from digging through
    the station building roof or the concourse roof slab.
    """
    head = 4
    steps = _stair_run(w, samples, ys, s0, 1, per_m, y_from, y_to, off_lo, off_hi,
                       head=head, clear_max_dy=(5 if under else (y_from - y_to) + 2))
    if not steps:
        return
    sgn = 1.0 if y_to > y_from else -1.0
    sd = 1 if off_lo > 0 else -1
    # For each tread: the standing height, and whether it opened the floor
    # slab of the level people walk on.
    info = []
    for k, (si, yb) in enumerate(steps):
        y = int(ys[si])
        fl, _ = levels(y)
        walk_blk = (y + 1) if under else fl               # Platform surface / concourse floor slab.
        foot = int(math.floor(y_from + sgn * 0.5 * (k + 1)))
        info.append((si, yb + head >= walk_blk, walk_blk + 1, foot))
    for k, (si, opened, stand, foot) in enumerate(info):
        x, z, ux, uz, _ = samples[si]
        nx, nz = -uz, ux
        if opened and stand - foot >= 2:
            # Both sides of the opening: on the platform, only the inner row
            # gets railings (the outer side is the station building's glass
            # wall); on the concourse both sides do, because the row along the
            # wall is too narrow and nobody should fall in from there.
            for off in ((7,) if under else (7, 10)):
                w.set(round(x + nx * sd * off), stand, round(z + nz * sd * off), BARS)
        nb = [info[j][1] for j in (k - 1, k + 1) if 0 <= j < len(info)]
        if not opened and any(nb):
            # The end of the hole: this floor cell is still there and the next
            # one is already open, so a row of railings goes across.
            for off in range(off_lo, off_hi + 1):
                w.set(round(x + nx * off), stand, round(z + nz * off), BARS)


def place_signs(w, samples, ys, lo, hi, label):
    """A station name sign every 20 m on both sides of the platform, facing
    into the platform (toward the tracks)."""
    ref, zh, en = label
    per_m = max(1, int(round(1.0 / STEP)))
    for i in range(lo + 8 * per_m, hi - 6 * per_m, 20 * per_m):
        x, z, ux, uz, _ = samples[i]
        nx, nz = -uz, ux
        y = int(ys[i])
        for off, face in ((9, (-nx, -nz)), (-9, (nx, nz))):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.sign(bx, y + 2, bz, [ref, zh, en, ""], facing=face)


def build_entrance(w, samples, ys, lo, hi, grounds=None, label=None):
    """Exit stair of an elevated station: climbs from the real ground to the
    platform surface.

    Step heights must be counted from the local ground, grounds[]. They used
    to be counted from the hard-coded constant GROUND=64, so where the ground
    was at 71 m the stair started 7 m underground, leaving only a vertical
    shaft with no steps above it.
    """
    per_m = max(1, int(round(1.0 / STEP)))
    start = min(lo + 4 * per_m, len(ys) - 1)
    g0 = int(grounds[start]) if grounds is not None else GROUND
    y_plat = int(ys[start]) + 2
    # Standing on the ground block g0 puts the feet at g0+1; the stair has to
    # start there to meet the station hall's paving flush.
    need = (abs(y_plat - g0 - 1) * 2 + 4) * per_m
    d = 1 if start + need < len(samples) else -1
    if not (0 <= start + d * need < len(samples)):
        return
    steps = _stair_run(w, samples, ys, start, d, per_m, g0 + 1, y_plat, 11, 13,
                       head=4, wall_offs=(10, 14), wall_ground=g0)
    if not steps:
        return
    # The ground-level station hall at the foot of the stair, with the fare
    # gates inside. At an at-grade station the platform is at ground level, and
    # a hall at off 9 would cover the two outer platform rows and the glass
    # wall, so the hall has to move out beyond the platform.
    o0 = 11 if y_plat - g0 <= 6 else 9
    _hall(w, samples, ys, start, d, per_m, g0, label, t0=-11, t1=0,
          o0=o0, o1=o0 + 8, floor_t0=-11, door_t=-11, open_end=0, gate_t=-4)
    si, _ = steps[-1]
    for s in range(max(0, si - per_m), min(len(samples), si + 2 * per_m)):
        # Landing at the top of the stair, joined to the platform surface.
        x, z, ux, uz, _ = samples[s]
        nx, nz = -uz, ux
        yb = int(ys[s]) + 1
        for off in range(10, 14):
            bx, bz = round(x + nx * off), round(z + nz * off)
            w.set(bx, yb, bz, STAIR)
            for yy in range(yb + 1, yb + 5):
                w.set(bx, yy, bz, AIR)
