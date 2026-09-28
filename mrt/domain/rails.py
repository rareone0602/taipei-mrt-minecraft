#!/usr/bin/env python3
"""Single-track generator: turns a floating-point centerline into rail blocks and shape states.

The world save is written directly as NBT with no block updates, so the game does not
connect the rails; the shape of every cell has to be computed correctly here. A wrong
cell raises no error; a minecart simply stops there without a word.

Usage (runs the self-test):
    ./.venv/bin/python -m mrt.domain.rails
"""
import math

RAIL    = "minecraft:rail"
POWERED = "minecraft:powered_rail"

# North = −Z, south = +Z, east = +X, west = −X
DIRS     = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
_DIR_OF  = {v: k for k, v in DIRS.items()}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
AXIS     = {"north": "north_south", "south": "north_south",
            "east":  "east_west",   "west":  "east_west"}

STRAIGHT_SHAPES = {"north_south", "east_west"}
CURVE_SHAPES    = {"north_east", "north_west", "south_east", "south_west"}
ASCEND_SHAPES   = {"ascending_" + d for d in DIRS}
ALL_SHAPES      = STRAIGHT_SHAPES | CURVE_SHAPES | ASCEND_SHAPES
# The shape enumeration of powered_rail has no curves; forcing one gives an invalid block state
POWERED_SHAPES  = STRAIGHT_SHAPES | ASCEND_SHAPES


# ---------- Public API ----------

def rail_path(pts, booster_every=12):
    """pts: iterable of (x, y, z) floats, ordered along the track.
    Returns list of (x:int, y:int, z:int, shape:str, powered:bool)."""
    pts = [(float(x), float(y), float(z)) for x, y, z in pts]
    if not pts:
        return []
    cells = _quantize(pts)          # Round, and merge consecutive samples in the same cell
    cells = _orthogonalize(cells)   # Split diagonal steps into two orthogonal steps
    cells = _despike(cells)         # Remove a-b-a reversal spikes
    ys     = _plan_profile(cells)   # Vertical profile: clamp grades, keep height changes off curves
    shapes = _shapes(cells, ys)
    power  = _boosters(shapes, booster_every)
    return [(c[0], ys[i], c[1], shapes[i], power[i]) for i, c in enumerate(cells)]


def block_string(shape, powered):
    """-> 'minecraft:rail[shape=north_south]' or
          'minecraft:powered_rail[shape=east_west,powered=true]'"""
    if shape not in ALL_SHAPES:
        raise ValueError("unknown rail shape: %r" % (shape,))
    if powered:
        if shape not in POWERED_SHAPES:
            raise ValueError("powered_rail cannot be a curve: %r" % (shape,))
        return "%s[shape=%s,powered=true]" % (POWERED, shape)
    return "%s[shape=%s]" % (RAIL, shape)


def shape_connections(shape):
    """Return (the two directions this shape connects to, the uphill direction or None)."""
    if shape in STRAIGHT_SHAPES:
        return (("north", "south") if shape == "north_south"
                else ("east", "west")), None
    if shape in ASCEND_SHAPES:
        d = shape[len("ascending_"):]
        return (d, OPPOSITE[d]), d
    if shape in CURVE_SHAPES:
        ns, ew = shape.split("_")
        return (ns, ew), None
    raise ValueError("unknown rail shape: %r" % (shape,))


# ---------- Horizontal alignment ----------

def _r(v):
    """Round half up. The built-in round() uses banker's rounding: round(0.5)=0 but
    round(1.5)=2, which on 0.5 m samples makes block runs alternately long and short."""
    return int(math.floor(v + 0.5))


def _quantize(pts):
    """Round to block cells, merging consecutive samples in the same cell into one point.

    At 0.5 m sampling a cell often gets two or three points. The height is the group
    mean rather than the first sample, so that the vertical profile of a gentle slope
    is not shifted half a cell toward the leading edge of each cell.
    """
    out = []
    for x, y, z in pts:
        xi, zi = _r(x), _r(z)
        if out and out[-1][0] == xi and out[-1][1] == zi:
            c = out[-1]
            c[3] += 1
            c[2] += (y - c[2]) / c[3]
        else:
            out.append([xi, zi, y, 1])
    return [(c[0], c[1], c[2]) for c in out]


def _ortho_walk(a, b, state):
    """Walk from a to b in orthogonal steps; return the cells on the way (without a, with b).

    Each step takes the axis that stays closer to the straight line a→b. When both are
    equally close (exactly 45°), it takes the axis the previous step did not, so a
    diagonal becomes a regular staircase instead of a long straight run and a sharp turn.
    """
    ax, az = a
    bx, bz = b
    dx, dz = bx - ax, bz - az
    span = math.hypot(dx, dz)
    x, z, out = ax, az, []
    while (x, z) != (bx, bz):
        cands = []
        if x != bx:
            cands.append(("x", (x + (1 if bx > x else -1), z)))
        if z != bz:
            cands.append(("z", (x, z + (1 if bz > z else -1))))
        if len(cands) == 1:
            axis, nxt = cands[0]
        else:
            dev = [abs(dz * (c[1][0] - ax) - dx * (c[1][1] - az)) / span
                   for c in cands]
            if abs(dev[0] - dev[1]) < 1e-9:
                axis, nxt = cands[1] if state[0] == "x" else cands[0]
            else:
                axis, nxt = cands[0] if dev[0] < dev[1] else cands[1]
        state[0] = axis
        out.append(nxt)
        x, z = nxt
    return out


def _orthogonalize(cells):
    """Fill in cells so that neighbors are 4-connected. Rails have no diagonal connections, so a
    diagonal step must be split in two."""
    out = [cells[0]]
    state = [None]
    for bx, bz, by in cells[1:]:
        ax, az, ay = out[-1]
        steps = _ortho_walk((ax, az), (bx, bz), state)
        for k, (x, z) in enumerate(steps, 1):
            # Inserted cells have no original height; interpolate along the Manhattan progress
            out.append((x, z, ay + (by - ay) * k / len(steps)))
    return out


def _despike(cells):
    """Remove a-b-a reversals: a cell with both neighbors on the same side has no valid shape."""
    out = []
    for c in cells:
        if out and (out[-1][0], out[-1][1]) == (c[0], c[1]):
            continue
        if len(out) >= 2 and (out[-2][0], out[-2][1]) == (c[0], c[1]):
            out.pop()
            continue
        out.append(c)
    return out


def _straight_flags(cells):
    """Return whether each cell is on a straight run (its two neighbors exactly opposite).
    End cells count as straight: with only one neighbor, a straight or ascending shape can
    always be chosen."""
    n = len(cells)
    flags = [True] * n
    for i in range(1, n - 1):
        px, pz = cells[i - 1][0] - cells[i][0], cells[i - 1][1] - cells[i][1]
        nx, nz = cells[i + 1][0] - cells[i][0], cells[i + 1][1] - cells[i][1]
        flags[i] = (px == -nx and pz == -nz)
    return flags


# ---------- Vertical profile ----------

def _limit_grade(ys):
    """Clamp the height change per step to ±1: an ascending rail rises only one block at a time,
    however steep the input."""
    out = list(ys)
    for i in range(1, len(out)):
        out[i] = max(out[i - 1] - 1, min(out[i - 1] + 1, out[i]))
    return out


def _nearest_ok(ok, idx, lo):
    """Find the valid edge nearest to idx and >= lo; on a tie, prefer moving back (less lag)."""
    n = len(ok)
    for r in range(n):
        for j in ((idx,) if r == 0 else (idx - r, idx + r)):
            if lo <= j < n and ok[j]:
                return j
        if idx - r < lo and idx + r >= n:
            break
    return None


def _plan_profile(cells):
    """Plan the y of every cell.

    A height change may only fall on an edge whose lower cell is on a straight run: an
    ascending rail cannot also be a curve, and the ascending rail is always the lower
    cell. In addition, two adjacent edges may not both change height. This guarantees
    that the other end of every ascending rail is level, and it also removes valleys and
    peaks. At a real grade of 4%, two height changes are at least 25 cells apart, so this
    constraint never gets in the way.
    """
    n = len(cells)
    tgt = _limit_grade([_r(c[2]) for c in cells])
    if n < 2:
        return tgt
    straight = _straight_flags(cells)
    up_ok   = [straight[i]     for i in range(n - 1)]   # Up: the ascending rail is cell i
    down_ok = [straight[i + 1] for i in range(n - 1)]   # Down: the ascending rail is cell i+1

    placed, last = [], -2
    for i in range(n - 1):
        d = tgt[i + 1] - tgt[i]
        if d == 0:
            continue
        j = _nearest_ok(up_ok if d > 0 else down_ok, i, last + 2)
        if j is None:
            continue        # The whole stretch is on curves, so this height change is dropped
                            # (the track remains passable)
        placed.append((j, d))
        last = j

    ys, cur, k = [0] * n, tgt[0], 0
    for i in range(n):
        if k < len(placed) and placed[k][0] == i - 1:
            cur += placed[k][1]
            k += 1
        ys[i] = cur
    return ys


# ---------- Shapes and powered rails ----------

def _shapes(cells, ys):
    n = len(cells)
    out = []
    for i in range(n):
        nbs = []
        for j in (i - 1, i + 1):
            if 0 <= j < n:
                d = _DIR_OF[(cells[j][0] - cells[i][0], cells[j][1] - cells[i][1])]
                nbs.append((d, ys[j]))
        if not nbs:
            out.append("north_south")   # A one-cell track; either axis will do
            continue
        is_straight = len(nbs) == 1 or nbs[0][0] == OPPOSITE[nbs[1][0]]
        up = [d for d, y in nbs if y == ys[i] + 1]
        if up:
            # Either case means _plan_profile failed to prevent it; better to fail loudly than to
            # produce an impassable track
            if not is_straight:
                raise ValueError("#%d ascending rail on a curve" % i)
            if len(up) > 1:
                raise ValueError("#%d both neighbours are higher (a valley)" % i)
            out.append("ascending_" + up[0])
        elif is_straight:
            out.append(AXIS[nbs[0][0]])
        else:
            ns = nbs[0][0] if nbs[0][0] in ("north", "south") else nbs[1][0]
            ew = nbs[0][0] if nbs[0][0] in ("east", "west")   else nbs[1][0]
            out.append(ns + "_" + ew)
    return out


def _boosters(shapes, every):
    """Place a powered rail every `every` cells; one that lands on a curve moves to the next straight.

    The whole network is 240 km, and a minecart that is not boosted stops partway, so
    it is better to place too many.
    """
    out = [False] * len(shapes)
    if not every or every <= 0:
        return out
    since = every       # Start with one on the first cell so the minecart can get moving
    for i, s in enumerate(shapes):
        if since >= every and s in POWERED_SHAPES:
            out[i] = True
            since = 0
        since += 1
    return out


# ---------- General checker ----------

def check_rails(blocks):
    """Check that a minecart can pass. Return a list of error messages; an empty list means the
    track is passable."""
    errs = []
    n = len(blocks)
    if n == 0:
        return errs

    seen = {}
    for i, (x, y, z, shape, pw) in enumerate(blocks):
        if shape not in ALL_SHAPES:
            errs.append("#%d unknown shape %r" % (i, shape))
        if pw and shape in CURVE_SHAPES:
            errs.append("#%d curve %s cannot be powered_rail" % (i, shape))
        if (x, z) in seen:
            errs.append("#%d and #%d occupy the same cell (%d,%d)" % (i, seen[(x, z)], x, z))
        seen[(x, z)] = i

    for i in range(n - 1):
        ax, _, az = blocks[i][:3]
        bx, _, bz = blocks[i + 1][:3]
        if abs(ax - bx) + abs(az - bz) != 1:
            errs.append("#%d (%d,%d) -> #%d (%d,%d) are not orthogonally adjacent"
                        % (i, ax, az, i + 1, bx, bz))
    if errs:
        return errs     # Connectivity is already broken, so the shape checks below mean nothing

    for i, (x, y, z, shape, pw) in enumerate(blocks):
        dirs, asc = shape_connections(shape)
        nbs = []
        for j in (i - 1, i + 1):
            if 0 <= j < n:
                nbs.append((j, _DIR_OF[(blocks[j][0] - x, blocks[j][2] - z)]))

        for j, d in nbs:
            ny = blocks[j][1]
            back = OPPOSITE[d]
            jdirs, jasc = shape_connections(blocks[j][3])
            if d not in dirs:
                errs.append("#%d %s has no connection towards %s (neighbour #%d)"
                            % (i, shape, d, j))
            if back not in jdirs:
                errs.append("#%d %s does not connect back towards %s (neighbour #%d)"
                            % (j, blocks[j][3], back, i))
            if asc == d:
                if ny != y + 1:
                    errs.append("#%d %s: neighbour on the %s side should be 1 block higher, got %+d"
                                % (i, shape, d, ny - y))
            elif jasc == back:
                # Top of a slope: the neighbor is 1 block lower but ascends toward this cell. The
                # specification says both sides of a non-ascending rail are level; taken literally,
                # no height change could ever work, so this cell must be allowed.
                if ny != y - 1:
                    errs.append("#%d: neighbour #%d claims to ascend towards it "
                                "but is not 1 block lower" % (i, j))
            elif ny != y:
                errs.append("#%d and #%d differ in height by %+d, but neither is an ascending rail"
                            % (i, j, ny - y))

        if asc:
            ndirs = [d for _, d in nbs]
            if asc not in ndirs:
                errs.append("#%d %s ascends towards %s, but there is no track in that direction"
                            % (i, shape, asc))
            if len(nbs) == 2 and nbs[0][1] != OPPOSITE[nbs[1][1]]:
                errs.append("#%d an ascending rail cannot also be a curve" % i)
            for j, d in nbs:
                if d != asc and blocks[j][1] != y:
                    errs.append("#%d %s: neighbour #%d at the other end must be level with it"
                                % (i, shape, j))

        if len(nbs) == 2:
            y0, y1 = blocks[nbs[0][0]][1], blocks[nbs[1][0]][1]
            if y < y0 and y < y1:
                errs.append("#%d is lower than both neighbours (a valley)" % i)
            if y > y0 and y > y1:
                errs.append("#%d is higher than both neighbours (a peak)" % i)
    return errs
