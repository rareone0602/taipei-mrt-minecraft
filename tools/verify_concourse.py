#!/usr/bin/env python3
"""Read the underground malls back from a world save and check that every exit can
really reach the others, instead of trusting the generator's own account.

The generator knows only which blocks it placed, not whether they add up to a walkable
route. A missing step, a passage cut by another line's tunnel lining, a ceiling pressed
down to one block of headroom: in the build log all of these are "done". So the blocks
are read back independently and flood-filled under the rules a player can really walk by
(domain/walk.py), to see how many connected components the exits fall into.

The key is that **walking on the surface is not allowed**. All the exits open onto the
same streets, so with the surface allowed they would always be connected and nothing
would have been checked. Only walkable space underground counts.

Four checks:
  1. Every exit has standable space underground (not a hole into solid ground).
  2. The exits can be reached from each other without surfacing (exactly one connected
     component).
  3. The yellow warning strip at the platform edge is reachable (the underground mall
     really connects into the station instead of forming an area of its own).
  4. Every exit also connects to the surface (no stair is sealed underground).

Usage:
    ./.venv/bin/python tools/verify_concourse.py                     # Default save, Taipei Main Station
    ./.venv/bin/python tools/verify_concourse.py <save> --stations 台北車站 北門
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt import config
from mrt.domain import walk
from mrt.domain.terrain import Terrain
from mrt.infrastructure.savereader import read_volume

PLAT_EDGE = "minecraft:yellow_concrete"     # Platform-edge warning strip: YELLOW in build_line.


def walk_candidates(get, x, y, z, radius=8, dy=20):
    """Standable cells near (x, y, z), nearest first."""
    out = []
    for ddy in range(-dy, dy + 1):
        for ddx in range(-radius, radius + 1):
            for ddz in range(-radius, radius + 1):
                c = (x + ddx, y + ddy, z + ddz)
                if walk.standable(get, *c):
                    out.append((ddx * ddx + ddz * ddz + 4 * ddy * ddy, c))
    out.sort()
    return [c for _, c in out]


def load_entrances(stations, margin):
    """Pick the exits that belong to these stations and compute the area to read back."""
    items = json.load(open(config.ENTRANCES_JSON, encoding="utf-8"))["items"]
    out = []
    for e in items:
        if e.get("station") not in stations:
            continue
        ref = str(e.get("ref") or "")
        if not ref:
            continue
        out.append((ref, e["station"], int(e["mc_x"]), int(e["mc_z"])))
    out.sort()
    if not out:
        return out, None
    xs = [e[2] for e in out]; zs = [e[3] for e in out]
    box = (min(xs) - margin, min(zs) - margin, max(xs) + margin, max(zs) + margin)
    return out, box


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save", nargs="?", default=config.DEFAULT_SAVE)
    ap.add_argument("--stations", nargs="+", default=["台北車站"])
    ap.add_argument("--margin", type=int, default=60,
                    help="Metres to extend the area beyond the exits")
    ap.add_argument("--depth", type=int, default=60,
                    help="Metres to read below the ground. The rail top of a depth band 2 station "
                         "box is 45 m underground, where the Songshan-Xindian Line "
                         "platform at Beimen is, so 40 m misses it")
    a = ap.parse_args()

    if not os.path.isdir(a.save):
        print(f"World save not found: {a.save}")
        return 1

    ents, box = load_entrances(a.stations, a.margin)
    if not ents:
        print(f"entrances.json has no exits for {', '.join(a.stations)}")
        return 1
    x0, z0, x1, z1 = box

    terr = Terrain()
    gs = [int(terr.y_at(x, z)) for _, _, x, z in ents]
    g_hi = max(gs)
    y1 = g_hi + 6                       # Includes the exit kiosks at street level.
    y0 = min(gs) - a.depth

    # "Underground" is judged cell by cell against the local ground: the feet must be 2 or
    # more blocks below the ground surface block. The check once used the lowest ground
    # among all exits as a global ceiling. The ground near Zhongshan and Shuanglian is 3 m
    # lower than at Taipei Main Station, so checking them together judged the whole
    # underground mall to be "surface", and the scattered pockets left over each became a
    # component of their own. The paving of an exit kiosk sits on the ground surface block
    # and the top two steps of a stair are one block below it; neither counts as underground.
    import numpy as np
    GX, GZ = np.meshgrid(np.arange(x0, x1 + 1), np.arange(z0, z1 + 1))
    T = terr.y_at(GX, GZ)

    def underground(x, y, z):
        return y <= int(T[z - z0, x - x0]) - 2

    print(f"World save {a.save}")
    print(f"Stations {', '.join(a.stations)}: {len(ents)} exits")
    print(f"Area x {x0}..{x1}  z {z0}..{z1}  y {y0}..{y1}"
          f" (ground y {min(gs)}-{g_hi}; underground = feet 2 or more blocks below the "
          f"local surface)")

    vol = read_volume(a.save, x0, y0, z0, x1, y1, z1)
    get = vol.get
    ug_bounds = (x0, y0, z0, x1, g_hi, z1)

    # ---- 1. Does every exit have a foothold underground? ----
    foot, nowhere = {}, []
    for (ref, st, x, z), g in zip(ents, gs):
        best = None
        for c in walk_candidates(get, x, g - 6, z):
            if underground(*c):
                best = c
                break
        if best:
            foot[(ref, st)] = best
        else:
            nowhere.append(f"{ref}({st})")

    print(f"\n[1] Foothold underground: {len(foot)}/{len(ents)}")
    if nowhere:
        print(f"    Exits with nothing at all underground ({len(nowhere)}): "
              f"{', '.join(nowhere)}")

    if not foot:
        print("\nNothing underground, so the remaining checks are skipped.")
        return 1

    # ---- 2. Connectivity without surfacing ----
    cells = list(foot.values())
    comps = walk.components(get, cells, bounds=ug_bounds, allow=underground)
    inv = collections.defaultdict(list)
    for (ref, st), c in foot.items():
        # A ref repeats across stations (Taipei Main Station and Beimen both have exits 1, 2
        # and 3), so printing only the ref would not show which station it belongs to.
        inv[c].append(f"{ref}({st})" if len(a.stations) > 1 else ref)
    print(f"\n[2] Connected components without surfacing: {len(comps)}")
    for i, g in enumerate(comps, 1):
        refs = sorted({r for c in g for r in inv[c]})
        head = ", ".join(refs[:14]) + (" …" if len(refs) > 14 else "")
        print(f"    Component {i:>2} ({len(refs):>3} exits): {head}")

    # Steps between the farthest pair: an underground mall should not take a long way round.
    main_comp = comps[0]
    dist, came = walk.flood(get, [main_comp[0]], bounds=ug_bounds, allow=underground)
    far = max(((dist.get(c, -1), c) for c in main_comp), key=lambda t: t[0])
    if far[0] > 0:
        refs = ", ".join(inv[far[1]])
        print(f"    In the largest component, {', '.join(inv[main_comp[0]])} to {refs} "
              f"takes {far[0]:,} steps")

    # ---- 3. Can the platforms be reached? ----
    print("\n[3] Platform edges reachable from the largest component:")
    edges = []
    for yy in range(y0, g_hi + 1):
        for zz in range(z0, z1 + 1, 4):
            for xx in range(x0, x1 + 1, 4):
                if get(xx, yy, zz) == PLAT_EDGE and underground(xx, yy + 1, zz):
                    edges.append((xx, yy + 1, zz))
    if not edges:
        print("    No platform warning strip in the area (this save may have no stations)")
    else:
        # Group the warning strips. The area holds more than one station, and counting them
        # together would hide which platform cannot be reached. Strips at the same y within
        # 60 m of each other count as one platform.
        groups = []
        for c in sorted(edges):
            for g in groups:
                if g[0][1] == c[1] and any(abs(d[0] - c[0]) <= 60
                                           and abs(d[2] - c[2]) <= 60 for d in g):
                    g.append(c)
                    break
            else:
                groups.append([c])
        for g in sorted(groups, key=lambda g: (-len(g), g[0][1])):
            n = sum(1 for c in g if c in dist)
            gx = sum(c[0] for c in g) // len(g)
            gz = sum(c[2] for c in g) // len(g)
            print(f"    Platform y={g[0][1]:>3} near ({gx:>5},{gz:>5}): "
                  f"{len(g):>3} cells sampled, {n:>3} reachable"
                  + ("" if n else "   <- unreachable"))
        reach_edges = [c for c in edges if c in dist]

    # ---- 4. Does every exit reach the surface? ----
    # Each exit must be flooded separately. Starting from all footholds at once, a single
    # stair reaching the street would make every exit "pass", since the streets are
    # connected anyway, and nothing would have been checked. The bounds must also stay near
    # the exit, or the flood spreads along the streets.
    no_surface = []
    for (ref, st), c in sorted(foot.items()):
        g = int(terr.y_at(c[0], c[2]))
        b = (c[0] - 50, y0, c[2] - 50, c[0] + 50, y1, c[2] + 50)
        d, _ = walk.flood(get, [c], bounds=b)
        if not any(p[1] >= g for p in d):
            no_surface.append(f"{ref}({st})")
    print(f"\n[4] Surface reachable from underground: {len(foot) - len(no_surface)}/{len(foot)}")
    if no_surface:
        print(f"    Cannot reach the surface: {', '.join(no_surface)}")

    bad = bool(nowhere) or len(comps) > 1 or bool(no_surface) \
        or (edges and not reach_edges)
    print("\n" + ("Problems found: see the checks above" if bad else
                  "All passed: every exit reaches every other without surfacing, and each "
                  "reaches the platforms and the surface"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
