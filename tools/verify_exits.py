#!/usr/bin/env python3
"""Read the real exits back from a world save and check that each one leads from the
street to the platform, instead of trusting the generator's own account.

Exit kiosks are found by reading back the signs. Each exit shaft has a sign by its door
reading `出口 N` over the station name. The generator placed the sign, of course, but
whether the stair beside it reaches the platform is checked by rebuilding it from the
blocks; the generator's word does not count.

The key rule is **no stepping on soil**: during the flood fill the block underfoot must be
man-made (concrete, smooth stone, slabs, lining...). Grass, dirt, stone, sand and water
are all forbidden. If terrain were allowed, any broken stair could be bypassed by walking
along the street to the next exit and going down there, and nothing would have been
checked. This is stricter than the "no surfacing" rule of verify_concourse: the exit kiosk
itself stands on the surface.

Checks for each station:
  1. There is standable space beside every exit sign (the exit kiosk really is there).
  2. Starting from the sign, without stepping on soil, the yellow warning strip at the
     platform edge is reachable.
  3. There is a foothold on terrain beside the sign (the door really opens onto the
     street instead of being sealed in a wall).
  4. The exits of one station can reach each other. A transfer station (one with more
     than one line in mc_stations.csv) has a transfer passage between its two station
     boxes, so its exits must also form one group; two groups mean the transfer passage
     is not connected.

Usage:
    ./.venv/bin/python tools/verify_exits.py <save>                    # Every exit sign in the save
    ./.venv/bin/python tools/verify_exits.py <save> --stations 公館 西門
    ./.venv/bin/python tools/verify_exits.py <save> --bbox X0 Z0 X1 Z1
"""
import argparse
import collections
import csv
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt import config
from mrt.domain import walk
from mrt.infrastructure.savereader import read_signs, read_volume

PLAT_EDGE = "minecraft:yellow_concrete"
TERRAIN = {"minecraft:grass_block", "minecraft:dirt", "minecraft:stone",
           "minecraft:sand", "minecraft:bedrock", "minecraft:water",
           "minecraft:gravel"}
MARGIN = 60          # Area read back: meters beyond the exit signs and station points.
DEPTH = 60           # Meters read below the highest sign (the deepest concourse is a
                     # little over 45 m underground).
RISE = 32            # Meters read above the lowest sign. Elevated platforms are 14 m
                     # above the street, and footbridge concourses 8 m higher still. This
                     # once reached only 6 m above the sign, so elevated platforms lay
                     # outside the area read back and every elevated station was judged
                     # "platform unreachable": another case of a verifier misleading.


def man_made(name):
    return name not in TERRAIN


def save_extent(save):
    """Block extent covered by all region files in the save."""
    rdir = config.region_dir(save)
    xs, zs = [], []
    for p in glob.glob(os.path.join(rdir, "r.*.mca")):
        m = re.match(r"r\.(-?\d+)\.(-?\d+)\.mca$", os.path.basename(p))
        if m:
            xs.append(int(m.group(1))); zs.append(int(m.group(2)))
    if not xs:
        return None
    return (min(xs) * 512, min(zs) * 512, max(xs) * 512 + 511, max(zs) * 512 + 511)


def station_xy():
    out = collections.defaultdict(list)
    with open(config.MC_STATIONS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["name_zh"] or r["name_en"]].append((int(r["mc_x"]), int(r["mc_z"])))
    return out


def station_lines():
    """{station name: set of line codes serving it}. A transfer station is one with more than
    one line."""
    out = collections.defaultdict(set)
    with open(config.MC_STATIONS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for ref in r["ref"].split(";"):
                m = re.match(r"[A-Z]+", ref)
                if m:
                    out[r["name_zh"] or r["name_en"]].add(m.group(0))
    return out


def door_cell(get, sx, sy, sz, radius=3):
    """The threshold beside a sign: the cell nearest the sign that has a man-made block
    underfoot and is not the sign's own cell.

    The sign stands on the street outside the door. Its own cell has a stone block beneath
    it and so is standable, but everything around it is street, so starting from the sign
    without stepping on soil goes nowhere. The threshold cell has the shaft wall beneath
    it, and entering from there is what actually tests the stair.
    """
    best = None
    for dx in range(-radius, radius + 1):
        for dz in range(-radius, radius + 1):
            for dy in (-1, 0, 1):
                c = (sx + dx, sy + dy, sz + dz)
                if "sign" in get(*c):
                    continue
                if not walk.standable(get, *c, floor_ok=man_made):
                    continue
                w = dx * dx + dz * dz + 4 * dy * dy
                if best is None or w < best[0]:
                    best = (w, c)
    return best[1] if best else None


def check_station(save, name, signs, stn_pts, verbose):
    """Return dict(n, ok_plat, ok_street, comps, bad)."""
    xs = [s[0] for s in signs] + [p[0] for p in stn_pts]
    zs = [s[2] for s in signs] + [p[1] for p in stn_pts]
    ys = [s[1] for s in signs]
    x0, z0 = min(xs) - MARGIN, min(zs) - MARGIN
    x1, z1 = max(xs) + MARGIN, max(zs) + MARGIN
    y0, y1 = min(ys) - DEPTH, max(ys) + RISE
    vol = read_volume(save, x0, y0, z0, x1, y1, z1, verbose=False)
    get = vol.get
    bounds = (x0, y0, z0, x1, y1, z1)

    yellow = set()
    ny, nz, nx = vol.data.shape
    import numpy as np
    yid = vol._ids.get(PLAT_EDGE)
    if yid is not None:
        for iy, iz, ix in zip(*np.nonzero(vol.data == yid)):
            yellow.add((x0 + int(ix), y0 + int(iy) + 1, z0 + int(iz)))

    feet, bad = {}, []
    for sx, sy, sz, msgs in signs:
        # One station may have more than one sign with the same number (Exit 1 of Ximen
        # station and exit 1 of the Ximen underground mall are both 1), so the key includes
        # the coordinates to keep them from overwriting each other.
        tag = f"{msgs[0]}({sx},{sz})"
        c = door_cell(get, sx, sy, sz)
        if c is None:
            bad.append(f"{tag}: no threshold beside the sign")
            continue
        feet[tag] = c
    ok_plat = ok_street = 0
    levels = set()                  # Heights of the reachable warning strips (a stacked
                                    # station needs two).
    for tag, c in feet.items():
        dist, _ = walk.flood(get, [c], bounds=bounds, floor_ok=man_made)
        hits = [y for y in yellow if y in dist]
        if hits:
            ok_plat += 1
            levels |= {p[1] for p in hits}
        else:
            low = min((p[1] for p in dist), default=c[1])
            bad.append(f"{tag}: platform unreachable without stepping on soil "
                       f"(reached {len(dist)} cells, lowest y{low})")
        # Is there a foothold on terrain at the door? The sign is outside the door, so search
        # the neighbors for one cell.
        street = False
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2)):
            for dy in (-1, 0, 1):
                n = (c[0] + dx, c[1] + dy, c[2] + dz)
                if walk.standable(get, *n, floor_ok=lambda b: b in TERRAIN):
                    street = True
        if street:
            ok_street += 1
        else:
            bad.append(f"{tag}: the door does not connect to the street")
    comps = walk.components(get, list(feet.values()), bounds=bounds, floor_ok=man_made) \
        if feet else []
    return dict(n=len(signs), ok_plat=ok_plat, ok_street=ok_street,
                comps=len(comps), bad=bad, yellow=len(yellow), levels=sorted(levels))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save", nargs="?", default=config.DEFAULT_SAVE)
    ap.add_argument("--stations", nargs="*")
    ap.add_argument("--bbox", nargs=4, type=int, metavar=("X0", "Z0", "X1", "Z1"))
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--levels", nargs="*", default=[],
                    help="Stacked stations: the exits of these stations must reach the warning strips "
                         "on both platform levels")
    a = ap.parse_args()
    if not os.path.isdir(a.save):
        print(f"World save not found: {a.save}")
        return 1

    stn = station_xy()
    lines_of = station_lines()
    if a.bbox:
        box = tuple(a.bbox)
    elif a.stations:
        pts = [p for s in a.stations for p in stn.get(s, ())]
        if not pts:
            print("None of these stations is in mc_stations.csv"); return 1
        box = (min(p[0] for p in pts) - 500, min(p[1] for p in pts) - 500,
               max(p[0] for p in pts) + 500, max(p[1] for p in pts) + 500)
    else:
        box = save_extent(a.save)
        if box is None:
            print("The world save has no region files"); return 1

    print(f"World save {a.save}\nReading signs in x {box[0]}..{box[2]}  z {box[1]}..{box[3]} …")
    signs = read_signs(a.save, *box)
    by_station = collections.defaultdict(list)
    for x, y, z, msgs in signs:
        if len(msgs) >= 2 and msgs[0].startswith("出口") and msgs[1]:
            by_station[msgs[1]].append((x, y, z, msgs))
    if a.stations:
        by_station = {k: v for k, v in by_station.items() if k in a.stations}
    print(f"Signs: {len(signs):,}. Exit signs: {sum(len(v) for v in by_station.values())}. "
          f"Stations: {len(by_station)}\n")

    tot = collections.Counter()
    failed = []
    for name in sorted(by_station):
        sg = by_station[name]
        r = check_station(a.save, name, sg, stn.get(name, []), a.verbose)
        tot["n"] += r["n"]; tot["plat"] += r["ok_plat"]; tot["street"] += r["ok_street"]
        transfer = len(lines_of.get(name, ())) >= 2
        if transfer and r["comps"] > 1:
            r["bad"].append(f"Transfer station exits form {r['comps']} groups: no walkable "
                           f"transfer passage between the two station boxes")
            tot["split"] += 1
        # Stacked station: the warning strips of the two platform levels are LEVEL_H apart in
        # height, so at least two reachable heights are required.
        two = name in a.levels
        if two and len(r["levels"]) < 2:
            r["bad"].append(f"Stacked station: only one platform level reachable "
                           f"(warning strip heights {r['levels']})")
        flag = "" if (r["ok_plat"] == r["n"] and r["ok_street"] == r["n"]
                      and not (transfer and r["comps"] > 1)
                      and not (two and len(r["levels"]) < 2)) else "   <- problem"
        lv = f"  platform levels y{'/'.join(str(v) for v in r['levels'])}" if (two or len(r["levels"]) > 1) else ""
        print(f"  {name:<8} exits {r['n']:>2}  to platform {r['ok_plat']:>2}  "
              f"to street {r['ok_street']:>2}  components {r['comps']}"
              f"{'  transfer station' if transfer else ''}{lv}{flag}")
        for b in r["bad"]:
            print(f"      {b}")
        if flag:
            failed.append(name)

    n_tr = sum(1 for n in by_station if len(lines_of.get(n, ())) >= 2)
    print(f"\nTotal: stations {len(by_station)}, exits {tot['n']}. "
          f"Reach the platform: {tot['plat']}. Reach the street: {tot['street']}. "
          f"Transfer stations: {n_tr}, with station boxes not connected: {tot['split']}")
    if failed:
        print(f"Stations with problems ({len(failed)}): {', '.join(failed)}")
        return 1
    print("All passed: every exit reaches the platform without stepping on soil, "
          "and every door opens onto the street")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
