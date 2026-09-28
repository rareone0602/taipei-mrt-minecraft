#!/usr/bin/env python3
"""Read the track layout back from a world save: how many tracks the cross-section at a
point holds, and the height and offset of each.

Stacked stations (Fuzhong, Ximen) and pocket tracks (Zhongxiao Fuxing to Zhongxiao
Dunhua, Far Eastern Hospital to Haishan) both put "tracks out of their usual place": two
tracks split onto an upper and a lower level, or a third track in the middle. The
generator saying it laid them does not count. This tool cuts a section every meter along
a given direction, counts the rails in each cut and prints
"distance -> [(offset, y), ...]". At a glance it shows where the third track begins, where
the descending track reaches -8, and whether the four tracks of two lines in a shared
station box each keep to their own level.

Usage:
    ./.venv/bin/python tools/verify_tracks.py <save> --xz X Z --dir UX UZ [--span 200] [--half 14]
    ./.venv/bin/python tools/verify_tracks.py <save> --station 府中 [--span 150]
    ./.venv/bin/python tools/verify_tracks.py <save> --station 西門 --expect 4 --levels 2
    ./.venv/bin/python tools/verify_tracks.py <save> --pocket 大安 信義安和 --expect 3
"""
import argparse
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt import config
from mrt.domain import alignment as AL
from mrt.infrastructure.savereader import read_volume


def variants_of(ref):
    """The geometry variants that the generator actually builds.

    One OSM line often has two relations, one per direction, whose geometry differs by
    ten to twenty meters (the Tamsui-Xinyi Line differs by 19 m around Daan). A tool that
    picks "the nearest variant" on its own can easily pick one the generator did not
    build, and its cut then shows only one track: the verifier misleading itself.
    """
    lines = json.load(open(config.MC_LINES_JSON, encoding="utf-8"))
    return AL.select_variants(lines.get(ref, []))


def station_frame(name):
    """Station coordinates and alignment direction, from the segment in mc_lines nearest
    the station."""
    rows = list(csv.DictReader(open(config.MC_STATIONS_CSV, encoding="utf-8")))
    st = next((r for r in rows if r["name_zh"] == name), None)
    if st is None:
        raise SystemExit(f"{name} is not in mc_stations.csv")
    sx, sz = int(st["mc_x"]), int(st["mc_z"])
    best = None
    for ref in st["ref"].split(";"):
        code = "".join(c for c in ref if c.isalpha())
        for v in variants_of(code):
            p = v["points"]
            for i in range(len(p) - 1):
                (ax, az), (bx, bz) = p[i], p[i + 1]
                vx, vz = bx - ax, bz - az
                L = math.hypot(vx, vz)
                if L < 1e-9:
                    continue
                t = max(0.0, min(1.0, ((sx - ax) * vx + (sz - az) * vz) / (L * L)))
                d = math.hypot(sx - (ax + t * vx), sz - (az + t * vz))
                if best is None or d < best[0]:
                    best = (d, vx / L, vz / L)
    return sx, sz, best[1], best[2]


def pocket_frame(a, b):
    """Midpoint and heading of a pocket track, from the OSM way geometry registered in
    domain/stacked.POCKETS."""
    from mrt.domain import stacked as SK
    pk = next((k for k in SK.POCKETS if {k["a"], k["b"]} == {a, b}), None)
    if pk is None:
        raise SystemExit(f"No pocket track {a}–{b} in stacked.POCKETS")
    items = json.load(open(config.SIDINGS_JSON, encoding="utf-8"))["items"]
    way = next((w for w in items if w["id"] == pk["osm"]), None)
    if way is None:
        raise SystemExit(f"No way {pk['osm']} in data/sidings.json")
    # The storage track is drawn about 6 m beside the main line, so the cuts must be
    # centered on the alignment to be symmetric. Cutting at the way's own midpoint puts the
    # third track at the edge of the window or even outside it (as at both Daan and Taipei
    # Main Station).
    pts = way["mc"]
    seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
    want, acc = sum(seg) / 2, 0.0
    mid = pts[0]
    for (a, b), L in zip(zip(pts, pts[1:]), seg):
        if acc + L >= want:
            t = (want - acc) / L if L else 0.0
            mid = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            break
        acc += L
    # The direction is the storage track's own chord, which is always straight and parallel
    # to the main line. The per-segment heading of mc_lines jitters, and as a cutting
    # direction it drifts out of the tunnel within a few dozen meters.
    (ax, az), (bx, bz) = pts[0], pts[-1]
    L = math.hypot(bx - ax, bz - az)
    px, pz, _, _ = project(pk["ref"], mid[0], mid[1])
    return px, pz, (bx - ax) / L, (bz - az) / L


def project(ref, x, z):
    """Project a point onto a line's centerline and return (projected point, heading there)."""
    best = None
    for v in variants_of(ref):
        p = v["points"]
        for i in range(len(p) - 1):
            (ax, az), (bx, bz) = p[i], p[i + 1]
            vx, vz = bx - ax, bz - az
            L = math.hypot(vx, vz)
            if L < 1e-9:
                continue
            t = max(0.0, min(1.0, ((x - ax) * vx + (z - az) * vz) / (L * L)))
            qx, qz = ax + t * vx, az + t * vz
            d = math.hypot(x - qx, z - qz)
            if best is None or d < best[0]:
                best = (d, qx, qz, vx / L, vz / L)
    return best[1], best[2], best[3], best[4]


def census(save, x, z, ux, uz, span, half, depth=40, rise=20):
    """Cut every meter along (ux, uz) from -span to +span and return
    [(distance along the line, [(offset, y)])]."""
    nx, nz = -uz, ux
    xs = [x + ux * t + nx * o for t in (-span, span) for o in (-half, half)]
    zs = [z + uz * t + nz * o for t in (-span, span) for o in (-half, half)]
    x0, x1 = int(min(xs)) - 2, int(max(xs)) + 2
    z0, z1 = int(min(zs)) - 2, int(max(zs)) + 2
    # Heights read back: depth below the ground surface, with the ground estimated from the
    # highest non-air block in the save.
    vol = read_volume(save, x0, 20, z0, x1, 90, z1, verbose=False)
    import numpy as np
    rails = {}                                      # (x, z) -> {y}
    for name, ident in vol._ids.items():
        if "rail" in name:
            for iy, iz, ix in zip(*np.nonzero(vol.data == ident)):
                rails.setdefault((x0 + int(ix), z0 + int(iz)), set()).add(20 + int(iy))
    out = []
    for t in range(-span, span + 1):
        cx, cz = x + ux * t, z + uz * t
        hits = set()
        for o in range(-half, half + 1):
            bx, bz = int(round(cx + nx * o)), int(round(cz + nz * o))
            for ry in rails.get((bx, bz), ()):
                hits.add((o, ry))
        out.append((t, merge_strands(hits)))
    return out


def merge_strands(hits):
    """Count adjacent offsets at the same height as one track.

    When the alignment runs diagonally, a track is a staircase: one cell forward, then one
    cell sideways, so a single cut hits both -8 and -9. The alignment at Guting and Chiang
    Kai-shek Memorial Hall runs at 56 degrees, and its four tracks were counted as six or
    eight. The rails were fine; this tool was counting wrong.
    """
    out = []
    for y in sorted({ry for _, ry in hits}):
        offs = sorted(o for o, ry in hits if ry == y)
        run = []
        for o in offs:
            if run and o - run[-1] > 1:
                out.append((run[len(run) // 2], y))
                run = []
            run.append(o)
        if run:
            out.append((run[len(run) // 2], y))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save", nargs="?", default=config.DEFAULT_SAVE)
    ap.add_argument("--xz", nargs=2, type=float)
    ap.add_argument("--dir", nargs=2, type=float)
    ap.add_argument("--station")
    ap.add_argument("--pocket", nargs=2, metavar=("STATION_A", "STATION_B"),
                    help="Cut along the pocket track between these stations, using the OSM "
                         "way in stacked.POCKETS")
    ap.add_argument("--span", type=int, default=200)
    ap.add_argument("--half", type=int, default=14)
    ap.add_argument("--every", type=int, default=5, help="Print one line every this many metres")
    ap.add_argument("--expect", type=int,
                    help="Number of tracks expected in the cut at the centre of the station box")
    ap.add_argument("--levels", type=int,
                    help="Number of heights expected for the tracks in the cut at the centre of "
                         "the station box")
    a = ap.parse_args()
    if a.pocket:
        x, z, ux, uz = pocket_frame(*a.pocket)
        print(f"Pocket track {a.pocket[0]}–{a.pocket[1]} midpoint ({x:.0f},{z:.0f})  "
              f"direction ({ux:.2f},{uz:.2f})")
    elif a.station:
        x, z, ux, uz = station_frame(a.station)
        print(f"{a.station} ({x},{z})  direction ({ux:.2f},{uz:.2f})")
    else:
        x, z = a.xz
        ux, uz = a.dir
        L = math.hypot(ux, uz)
        ux, uz = ux / L, uz / L
    rows = census(a.save, x, z, ux, uz, a.span, a.half)
    for t, hits in rows:
        if t % a.every == 0 or not hits:
            print(f"  {t:>+5d} m  tracks {len(hits)}  {hits}")
    mid = next(h for t, h in rows if t == 0)
    n = len(mid)
    lv = sorted({y for _, y in mid})
    print(f"\nCentre cut: tracks {n}, heights {lv}")
    bad = False
    if a.expect is not None and n != a.expect:
        print(f"  Expected tracks: {a.expect}  <- problem"); bad = True
    if a.levels is not None and len(lv) != a.levels:
        print(f"  Expected heights: {a.levels}  <- problem"); bad = True
    gaps = [t for t, h in rows if not h]
    if gaps:
        print(f"  Cuts with no rails: {len(gaps)} ({gaps[:8]}…)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
