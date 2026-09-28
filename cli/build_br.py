#!/usr/bin/env python3
"""Builds only the Wenhu Line (BR): fully elevated with no tunnels, it is the
cleanest vertical slice.

This script is kept because its output can be compared with that of the
general generator (cli/build_line.py), so a broken elevated cross-section
shows up at once.

Usage: ./.venv/bin/python -m cli.build_br [--out DIR] [--limit N]
"""
import argparse
import csv
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt import config
from mrt.application.build_br import STEP, build_station, build_viaduct, resample
from mrt.infrastructure.mcworld import World


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=config.DEFAULT_SAVE)
    ap.add_argument("--limit", type=int, default=0,
                    help="Build only the first N metres, for testing")
    a = ap.parse_args()

    lines = json.load(open(config.MC_LINES_JSON, encoding="utf-8"))
    v = max(lines["BR"], key=lambda v: len(v["points"]))
    pts = [tuple(p) for p in v["points"]]
    samples = resample(pts, STEP)
    if a.limit:
        samples = samples[:int(a.limit / STEP)]
    length_m = len(samples) * STEP
    print(f"Wenhu Line (BR): {len(pts)} polyline points -> {len(samples)} samples, "
          f"{length_m/1000:.2f} km long")

    # Find the BR stations and match each one to its nearest sample.
    stns = []
    with open(config.MC_STATIONS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if any(t.startswith("BR") for t in r["ref"].split(";")):
                stns.append((r["name_zh"] or r["name_en"], int(r["mc_x"]), int(r["mc_z"])))

    shutil.rmtree(a.out, ignore_errors=True)
    # The spawn point is at the foot of the exit stair at Daan station; the
    # stair leads straight up to the platform.
    w = World(a.out, name="Taipei MRT — 文湖線 Wenhu Line", spawn=(2633, 66, 1387))

    print("Laying the viaduct…")
    build_viaduct(w, samples, set())

    print(f"Placing {len(stns)} stations…")
    built = 0
    for name, sx, sz in stns:
        best, bd = None, 1e18
        for i, (x, z, _, _) in enumerate(samples):
            d = (x - sx) ** 2 + (z - sz) ** 2
            if d < bd:
                bd, best = d, i
        # Too far from the line: a variant that is not on this line, so skip it.
        if bd ** 0.5 > 150:
            print(f"  Skipped {name}: {bd**0.5:.0f} m from the line")
            continue
        build_station(w, samples, best, name)
        built += 1
    print(f"  Built {built} stations")

    print("Writing the world save…")
    w.save()
    print(f"\nLine length {length_m/1000:.2f} km, {len(w.chunks)} chunks")


if __name__ == "__main__":
    main()
