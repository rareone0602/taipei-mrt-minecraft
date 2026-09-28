#!/usr/bin/env python3
"""Unit tests for the rail generator: shapes, ascending rails, powered rails, degenerate input.

Usage: ./.venv/bin/python tests/test_rails.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.domain.rails import *  # noqa: F403

# ---------- Self-test ----------

def _sample(f, length, step=0.5):
    """Take a point every step along the parameter s ∈ [0, length]; f(s) -> (x, y, z)."""
    n = int(round(length / step))
    return [f(i * step) for i in range(n + 1)]


_FAILS = []


def _fail(name, msg):
    _FAILS.append("%s: %s" % (name, msg))


def _expect(name, cond, msg):
    if not cond:
        _fail(name, msg)


def _case(name, pts, booster_every=12):
    """Run one case: generate, pass it through the general checker, print a one-line summary."""
    try:
        blocks = rail_path(pts, booster_every)
    except Exception as e:                      # noqa: BLE001
        _fail(name, "rail_path raised: %r" % (e,))
        print("[FAIL] %-14s %r" % (name, e))
        return []
    for e in check_rails(blocks):
        _fail(name, e)
    if blocks:
        ys = [b[1] for b in blocks]
        kinds = {"straight": 0, "curve": 0, "ascend": 0}
        for _, _, _, s, _p in blocks:
            kinds["curve" if s in CURVE_SHAPES else
                  "ascend" if s in ASCEND_SHAPES else "straight"] += 1
        pw = sum(1 for b in blocks if b[4])
        print("[%s] %-14s %5d cells  y %d..%d  straight %d  curve %d  slope %d  powered %d"
              % ("ok" if not any(f.startswith(name + ":") for f in _FAILS) else "!!",
                 name, len(blocks), min(ys), max(ys),
                 kinds["straight"], kinds["curve"], kinds["ascend"], pw))
    else:
        print("[ok] %-14s     0 cells" % name)
    return blocks


def _selftest():
    # 1. Due east-west
    b = _case("east_west", _sample(lambda s: (s, 64.0, 0.0), 200))
    _expect("east_west", len(b) == 201, "expected 201 cells, got %d" % len(b))
    _expect("east_west", all(x[3] == "east_west" for x in b), "not every shape is east_west")
    _expect("east_west", all(x[1] == 64 for x in b), "the height should not change")

    # 2. Due north-south
    b = _case("north_south", _sample(lambda s: (0.0, 64.0, s), 200))
    _expect("north_south", all(x[3] == "north_south" for x in b),
            "not every shape is north_south")
    _expect("north_south", [x[2] for x in b] == list(range(201)), "z should increase continuously")

    # 3. A 45° diagonal: every diagonal step must be split into two orthogonal steps
    k = 1.0 / math.sqrt(2.0)
    b = _case("diagonal", _sample(lambda s: (s * k, 64.0, s * k), 200))
    _expect("diagonal", all(x[3] in CURVE_SHAPES for x in b[1:-1]),
            "the inner cells of a 45° staircase should all be curves")
    dev = max(abs((x[0] - x[2])) for x in b)
    _expect("diagonal", dev <= 1, "too far off the centreline (%d cells)" % dev)

    # 4. A quarter circle of radius 200 m
    R = 200.0
    b = _case("arc", _sample(lambda s: (R * math.sin(s / R), 64.0,
                                        R - R * math.cos(s / R)), R * math.pi / 2))
    for x, _y, z, _s, _p in b:
        _expect("arc", abs(math.hypot(x, R - z) - R) <= 1.0,
                "cell (%d,%d) is more than 1 m off the arc" % (x, z))
    _expect("arc", any(x[3] in CURVE_SHAPES for x in b), "there are no curves on the arc")

    # 5. A 4% climb, rising 10 m in total
    b = _case("ramp4pct", _sample(lambda s: (s, 64.0 + 0.04 * s, 0.0), 250))
    _expect("ramp4pct", b[0][1] == 64 and b[-1][1] == 74,
            "start and end heights should be 64→74, got %d→%d" % (b[0][1], b[-1][1]))
    asc = [i for i, x in enumerate(b) if x[3] in ASCEND_SHAPES]
    _expect("ramp4pct", len(asc) == 10, "expected 10 ascending rails, got %d" % len(asc))
    _expect("ramp4pct", all(asc[i + 1] - asc[i] >= 2 for i in range(len(asc) - 1)),
            "ascending rails should not be adjacent")

    # 6. An S curve
    b = _case("s_curve", _sample(lambda s: (s, 64.0, 60.0 * math.sin(s / 60.0)), 300))
    _expect("s_curve", any(x[3] == "north_east" or x[3] == "south_west"
                           for x in b), "an S curve should turn both ways")

    # 7. A height change that falls naturally on a curve: 30 m straight, then a 90° turn, with y
    #    crossing the half block exactly at the corner
    def _corner(s):
        y = 64.49 + 0.02 * (s - 30.0)
        return (s, y, 0.0) if s <= 30.0 else (30.0, y, s - 30.0)
    b = _case("ramp_corner", _sample(_corner, 60))
    corner = [i for i, x in enumerate(b) if x[3] in CURVE_SHAPES]
    _expect("ramp_corner", corner == [30], "only cell 30 should be a curve, got %s" % corner)
    _expect("ramp_corner", b[29][3] == "ascending_east",
            "the height change should move back to cell 29, got %s" % b[29][3])
    _expect("ramp_corner", b[30][1] == b[29][1] + 1 == 65,
            "the corner should sit at the top of the slope, y=65")
    _expect("ramp_corner", b[-1][1] == 65, "the end height should be 65")

    # 8. Very short paths
    b = _case("two_pts", [(0.0, 64.0, 0.0), (1.0, 64.0, 0.0)])
    _expect("two_pts", [x[:3] for x in b] == [(0, 64, 0), (1, 64, 0)], "wrong cells")
    _expect("two_pts", all(x[3] == "east_west" for x in b), "wrong shape")

    b = _case("three_pts", [(0.0, 64.0, 0.0), (1.0, 64.0, 0.0), (1.0, 64.0, 1.0)])
    _expect("three_pts", [x[3] for x in b] == ["east_west", "south_west",
                                               "north_south"], "wrong corner shape")

    b = _case("one_pt", [(3.2, 64.0, -7.8)])
    _expect("one_pt", b == [(3, 64, -8, "north_south", True)], "wrong single-cell output: %r" % b)
    _expect("empty", rail_path([]) == [], "empty input should return an empty list")

    # 9. Defensive: an input grade that is too steep must still be clamped to 1 block per step
    b = _case("steep", _sample(lambda s: (s, 64.0 + 0.5 * s, 0.0), 40))
    _expect("steep", all(abs(b[i + 1][1] - b[i][1]) <= 1 for i in range(len(b) - 1)),
            "the height change per step must be <= 1")

    # 10. Powered rail spacing and block_string
    b = _case("booster", _sample(lambda s: (s, 64.0, 0.0), 300), booster_every=8)
    idx = [i for i, x in enumerate(b) if x[4]]
    _expect("booster", idx[0] == 0, "there should be a powered rail at the start")
    _expect("booster", all(idx[i + 1] - idx[i] == 8 for i in range(len(idx) - 1)),
            "powered rails on a straight should be exactly 8 apart")
    b = _case("no_booster", _sample(lambda s: (s, 64.0, 0.0), 20), booster_every=0)
    _expect("no_booster", not any(x[4] for x in b), "booster_every=0 should give no powered rails")

    _expect("block_string",
            block_string("north_south", False) == "minecraft:rail[shape=north_south]",
            "wrong string for a plain rail")
    _expect("block_string",
            block_string("east_west", True)
            == "minecraft:powered_rail[shape=east_west,powered=true]",
            "wrong string for a powered rail")
    _expect("block_string",
            block_string("ascending_north", True)
            == "minecraft:powered_rail[shape=ascending_north,powered=true]",
            "wrong string for an ascending powered rail")
    for bad in ("south_east", "north_west"):
        try:
            block_string(bad, True)
            _fail("block_string", "curve %s was accepted as a powered rail" % bad)
        except ValueError:
            pass

    # 11. The checker itself must catch broken tracks; otherwise passing everything above
    #     means nothing
    bad_cases = {
        "disconnected":  [(0, 64, 0, "east_west", False), (2, 64, 0, "east_west", False)],
        "mismatched":    [(0, 64, 0, "north_south", False), (1, 64, 0, "east_west", False)],
        "unramped step": [(0, 64, 0, "east_west", False), (1, 65, 0, "east_west", False)],
        "powered curve": [(0, 64, 0, "south_east", True), (1, 64, 0, "east_west", False)],
        "peak":          [(0, 64, 0, "ascending_east", False), (1, 65, 0, "east_west", False),
                          (2, 64, 0, "ascending_west", False)],
        "valley":        [(0, 65, 0, "east_west", False), (1, 64, 0, "ascending_east", False),
                          (2, 65, 0, "east_west", False)],
        "double slope":  [(0, 64, 0, "ascending_east", False), (1, 65, 0, "ascending_east", False),
                          (2, 66, 0, "east_west", False)],
    }
    for label, blocks in bad_cases.items():
        _expect("checker", check_rails(blocks), "the checker missed \"%s\"" % label)


if __name__ == "__main__":
    _selftest()
    print()
    if _FAILS:
        print("FAILED (%d)" % len(_FAILS))
        for f in _FAILS:
            print("  -", f)
        sys.exit(1)
    print("all tests passed")
