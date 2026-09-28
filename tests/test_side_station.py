#!/usr/bin/env python3
"""Unit tests for the concourse of side-platform stations (elevated /
at-grade).

Elevated and at-grade stations used to have only two separate, closed side
platforms; the template stair led only to the + side one, and nobody could
reach the - side platform. Now every station that is not underground has a
concourse level (its type decided by domain/alignment.station_kind): fare
gates and one stair to each platform, and the real exits connect to this
level. This test builds two straight synthetic stations and, by the rules a
player can actually walk (domain/walk), starts from the + side platform of
each to prove:

  platform -> end stair -> concourse -> fare gates -> the other stair -> the other platform

One of each type:
  · elevated station (rail top 13 m above the ground) -> "under": the
    concourse is under the viaduct, and the deck is its roof
  · at-grade station (rail top level with the ground) -> "over": the
    concourse is a bridge spanning above the platforms

A one-block error at either end of a stair is the classic mistake here (the
stair top one block above the platform surface, or the stair bottom one block
below the floor slab: you can walk down but not back up), so besides the flood
fill, the treads at both ends are checked cell by cell.

Usage: ./.venv/bin/python tests/test_side_station.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application import build_concourse as BCC
from mrt.application import build_line as BL
from mrt.domain import alignment as AL
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


PER_M = max(1, int(round(1.0 / AL.STEP)))


def straight(y, g, x0=-400, x1=400):
    """A straight line along the X axis with a flat rail top y and flat ground g.
    The station is at x=0."""
    pts = [(float(x0), 0.0), (float(x1), 0.0)]
    samples = AL.resample(pts, ["bridge", "bridge"], AL.STEP)
    n = len(samples)
    idx = min(range(n), key=lambda i: abs(samples[i][0]))
    half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
    return samples, [y] * n, [g] * n, idx, idx - half, idx + half


def build(sec, y, g):
    """Follow the order of cli/build_world.py: first the cross-sections of the
    whole line (the station range included, which is how piers grow into the
    station box), then the station on top."""
    w = DictSink()
    samples, ys, gnd, idx, lo, hi = straight(y, g)
    for i, (x, z, ux, uz, _) in enumerate(samples):
        if sec is BL.sec_bridge:
            sec(w, x, z, -uz, ux, ys[i], gnd[i],
                pier=(abs((i * AL.STEP) % AL.PIER_EVERY) < AL.STEP / 2))
        else:
            sec(w, x, z, -uz, ux, ys[i], gnd[i])
    BL.build_station(w, samples, ys, idx, False, label=("T1", "測試站", "Test"),
                     grounds=gnd, access=False)
    return w, samples, ys, gnd, idx, lo, hi


def col(samples, i, off):
    """Return the (x, z) block coordinates at lateral offset off from sample i,
    rounded the same way as in the generator."""
    x, z, ux, uz, _ = samples[i]
    nx, nz = -uz, ux
    return int(round(x + nx * off)), int(round(z + nz * off))


def walk_station(kind_expect, w, samples, ys, gnd, idx, lo, hi):
    y, g = int(ys[idx]), int(gnd[idx])
    kind = AL.station_kind(y, g)
    chk(f"Type {kind}", kind == kind_expect)
    L = y + AL.LEVEL_DY[kind]                             # Concourse standing surface.
    fl = L - 1
    x_lo, x_hi = col(samples, lo, 0)[0], col(samples, hi, 0)[0]
    get = w.get

    # Platform warning strips: the row at each end lies under the end wall (the station building
    # closes both platform ends anyway), so it does not count.
    yellow = [(x, yy + 1, z) for (x, yy, z), b in w.blocks.items()
              if b == BL.YELLOW and x_lo < x < x_hi]
    chk(f"Platform warning strips: {len(yellow)} cells ({(x_hi - x_lo - 1)} on each platform)",
        len(yellow) == 2 * (x_hi - x_lo - 1))
    plus = [c for c in yellow if c[2] > 0]
    minus = [c for c in yellow if c[2] < 0]
    chk("Present on both sides", len(plus) == len(minus) and len(plus) > 0)

    start = (0, y + 2, 6)                                 # Middle of the + side platform.
    chk(f"Start {start} is standable", walk.standable(get, *start))
    bounds = (x_lo - 30, min(g, y) - 6, -20, x_hi + 30, max(g, y) + 16, 20)
    dist, _ = walk.flood(get, [start], bounds=bounds)
    chk(f"All of the + side warning strip reachable ({sum(1 for c in plus if c in dist)}/{len(plus)})",
        all(c in dist for c in plus))
    chk(f"All of the - side warning strip reachable ({sum(1 for c in minus if c in dist)}/{len(minus)})",
        all(c in dist for c in minus))
    conc = [c for c in dist if c[1] == L and abs(c[2]) <= 10 and x_lo <= c[0] <= x_hi]
    chk(f"Concourse y{L} reachable ({len(conc)} cells)", len(conc) > 200)
    chk("Unpaid area in front of the fare gates reachable (before lo+14 m)",
        any(c[0] < x_lo + 14 for c in conc))
    chk("Rows along both concourse walls (|off| 10) walkable in the unpaid area",
        all((x, L, s * 10) in dist for x in range(x_lo + 3, x_lo + 12) for s in (1, -1)))
    lane = col(samples, lo + 14 * PER_M, 0)
    chk("Fare gate row on the concourse floor (the centre at lo+14 m is a through lane)",
        get(lane[0], fl, lane[1]) == BL.LANE and get(lane[0], fl + 1, lane[1]) == "minecraft:air")
    chk("Fare gate cabinets present", get(lane[0], fl + 1, lane[1] + 1) == BL.GATE)

    # Stair ends: the + side at off 8 and the - side at off -9, both set back run+1 m from the hi end.
    run = 2 * abs(AL.LEVEL_DY[kind] - 2)
    s0 = hi - (run + 1) * PER_M
    for off in (8, -9):
        top = col(samples, s0 + run * PER_M, off)            # Last step (at the hi end).
        first = col(samples, s0 + PER_M, off)                # First step (at the concourse floor).
        if kind == "under":
            chk(f"off {off:>2}: full block at the stair top is level with the platform surface (y{y + 1})",
                get(top[0], y + 1, top[1]) == BL.STAIR)
            chk(f"off {off:>2}: slab at the stair bottom rests on the concourse floor (y{fl + 1})",
                get(first[0], fl + 1, first[1]) == BL.SLAB
                and get(first[0], fl, first[1]) == BL.CONC)
        else:
            chk(f"off {off:>2}: full block at the stair bottom is level with the platform surface (y{y + 1})",
                get(top[0], y + 1, top[1]) == BL.STAIR)
            chk(f"off {off:>2}: slab at the stair top is set into the concourse floor (y{fl})",
                get(first[0], fl, first[1]) == BL.SLAB)
    return dist, L, fl, x_lo, x_hi, s0, run


# ============ Elevated station: concourse under the viaduct ============
print("Elevated station (rail top y80, ground y67)")
Y, G = 80, 67
w, samples, ys, gnd, idx, lo, hi = build(BL.sec_bridge, Y, G)
dist, L, fl, x_lo, x_hi, s0, run = walk_station("under", w, samples, ys, gnd, idx, lo, hi)
chk(f"Concourse floor y{fl} is above the ground (>= g+2 = {G + 2})", fl >= G + 2)
chk("Space below the floor is empty (hanging under the viaduct, not buried)",
    w.get(5, fl, 3) == BL.CONC and w.get(5, fl - 1, 3) == "minecraft:air")
chk("Deck (y-1) is the concourse roof and is not dug out under the platforms",
    all(w.get(x, Y - 1, z) == BL.CONC for x in range(x_lo + 2, x_lo + 40) for z in (0, 7, -7)))
chk("Side wall at |off| 11 is glass up to the deck edge",
    w.get(10, L, 11) == BL.GLASS and w.get(10, Y - 1, 11) == BL.CONC
    and w.get(10, fl, -11) == BL.CONC)
chk("End walls closed", all(w.get(x_lo, yy, z) == BL.CONC for yy in range(L, Y - 1) for z in range(-11, 12)))
# Piers: sec_bridge stands one at x=0, which must be restored after the concourse is hollowed
# out, running from the ground to the deck.
piers = [i for i in range(lo, hi + 1) if abs((i * AL.STEP) % AL.PIER_EVERY) < AL.STEP / 2]
chk(f"{len(piers)} piers in the station", len(piers) >= 2)
cx = int(round(samples[piers[0]][0]))
chk(f"Pier x={cx} is continuous through the hall (floor -> underside of the deck)",
    all(w.get(cx + dx, yy, dz) == BL.PIER for yy in range(fl + 1, Y - 1)
        for dx in (-1, 0, 1) for dz in (-1, 0, 1)))
chk("Pier still present below the floor", w.get(cx, fl - 1, 0) == BL.PIER and w.get(cx, G - 4, 0) == BL.PIER)
chk("Pier does not block the concourse (walkable past it)",
    (cx + 2, L, 0) in dist and (cx - 2, L, 0) in dist)
# Openings and railings on the platform: where the stair cuts through the platform surface, the
# inner row (off 7) is fenced. Anything on the platform surface level that is not platform paving
# is the opening (the treads of the top two steps are themselves at y+1).
opening = [x for x in range(x_lo + 1, x_hi) if w.get(x, Y + 1, 8) != BL.PLAT]
chk(f"+ side platform surface has a {len(opening)} m opening (x {min(opening)}..{max(opening)}, up to hi-1)",
    len(opening) == 10 and max(opening) == x_hi - 1)
fenced = [x for x in opening if w.get(x, Y + 2, 7) == BL.BARS]
chk(f"Railing at off 7 beside the opening ({len(fenced)} cells)", len(fenced) >= 6)
chk("No railing beside the last three steps at the top (the way onto the platform)",
    all(w.get(x, Y + 2, 7) != BL.BARS for x in range(x_hi - 3, x_hi)))
chk("A cross row of railing closes the end of the opening", w.get(min(opening) - 1, Y + 2, 8) == BL.BARS
    and w.get(min(opening) - 1, Y + 2, 9) == BL.BARS)
chk("Warning strip (off 6) not taken up by railing",
    all(w.get(x, Y + 2, 6) == "minecraft:air" for x in opening))
chk("- side is symmetric", all(w.get(x, Y + 2, -7) == BL.BARS for x in fenced)
    and all(w.get(x, Y + 1, -8) != BL.PLAT for x in opening))
chk("Station building roof not cut through by the stair",
    all(w.get(x, Y + 6, z) == BL.CONC for x in range(x_lo, x_hi + 1) for z in range(-10, 11)))

# ============ At-grade station: bridge concourse ============
print("At-grade station (rail top y71, ground y71)")
Y, G = 71, 71
w, samples, ys, gnd, idx, lo, hi = build(BL.sec_ground, Y, G)
dist, L, fl, x_lo, x_hi, s0, run = walk_station("over", w, samples, ys, gnd, idx, lo, hi)
chk(f"Concourse floor y{fl} sits on the station building roof (y{Y + 6})", fl == Y + 7)
foot = set()
for t in range(1, run + 1):
    for off in (8, 9, -9, -8):
        foot.add(col(samples, s0 + t * PER_M, off))
roof_bad = [(x, z) for x in range(x_lo, x_hi + 1) for z in range(-10, 11)
            if (x, z) not in foot and w.get(x, Y + 6, z) != BL.CONC]
chk(f"Station building roof y{Y + 6} is still CONC except at the stair ({len(roof_bad)} bad cells)", not roof_bad)
chk("Concourse roof not cut through by the headroom above the stair top",
    all(w.get(x, Y + 11, z) == BL.CONC for x in range(x_lo, x_hi + 1) for z in range(-11, 12)))
chk("Side wall at |off| 11 is glass", w.get(10, L, 11) == BL.GLASS and w.get(10, L + 2, -11) == BL.GLASS)
hole = [x for x in range(x_lo, x_hi + 1) if w.get(x, fl, 8) == "minecraft:air"]
chk(f"Concourse floor has a {len(hole)} m opening", len(hole) >= 6)
chk("Railings on both sides of the opening (off 7 and off 10)",
    sum(1 for x in hole if w.get(x, L, 7) == BL.BARS) >= 5
    and sum(1 for x in hole if w.get(x, L, 10) == BL.BARS) >= 5)
chk("A cross row of railing closes the end of the opening (at the hi end)",
    w.get(max(hole) + 1, L, 8) == BL.BARS and w.get(max(hole) + 1, L, 9) == BL.BARS)
chk("No extra railing on the platforms",
    all(w.get(x, Y + 2, 7) != BL.BARS for x in range(x_lo, x_hi + 1)))

# ============ Template stair unchanged when there are exits ============
print("Access switch")
w1 = DictSink()
samples, ys, gnd, idx, lo, hi = straight(80, 67)
BL.build_station(w1, samples, ys, idx, False, label=("T1", "測試站", "Test"), grounds=gnd, access=True)
w0 = DictSink()
BL.build_station(w0, samples, ys, idx, False, label=("T1", "測試站", "Test"), grounds=gnd, access=False)
chk(f"access=True adds {len(w1) - len(w0):,} blocks (template stair and station building)", len(w1) > len(w0) + 500)
chk("access=False has no station building exit sign", not any("Exit" in " ".join(v) for v in w0.signs.values()))

# ============ build_concourse: climbing shafts and skybridges ============
print("Exit shafts (climbing) and skybridges")
w = DictSink()
well = BCC.ShaftStair(100, 100, 1, 0, 90, 71, bottom_door=True, sign_bottom=["T1", "測試站", "Test", "出口 1"])
well.build(w)
sx, sz = well._w(-2, 2)
chk("Exit sign beside the bottom door of the shaft", w.signs.get((sx, 71, sz)) == ["T1", "測試站", "Test", "出口 1"])
chk("Block placed under the sign", w.get(sx, 70, sz) == well.step)
chk("No sign at the shaft top", (well._w(-2, 2)[0], 91, well._w(-2, 2)[1]) not in w.signs)
w = DictSink()
cells = {(x, z) for x in range(0, 30) for z in range(-2, 3)}
ring = BCC.outer_ring(cells)
tile = BCC.Tile(cells, ring, 80, {}, shopfront=False, bridge=True, pier_to={(0, 0): 66, (25, 0): 60})
tile.build(w)
chk("Skybridge edge is a glass parapet", w.get(10, 80, 3) == BCC.RAIL and w.get(10, 82, 3) == BCC.RAIL)
chk("Deck and roof at the skybridge edge", w.get(10, 79, 3) == BCC.EDGE and w.get(10, 83, 3) == BCC.CEIL)
chk("Pier runs from 2 blocks below the ground to one block below the deck",
    all(w.get(25, yy, 0) == BCC.PIER for yy in range(58, 79)) and w.get(25, 79, 0) == BCC.FLOOR)
chk("Tile without bridge is unchanged",
    (lambda d: (BCC.Tile(cells, ring, 80, {}).build(d), d.get(10, 80, 3) == BCC.WALL)[1])(DictSink()))

print("\nAll passed" if ok else "\nSome tests failed")
raise SystemExit(0 if ok else 1)
