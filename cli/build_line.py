#!/usr/bin/env python3
"""單獨蓋幾條路線（不含地形）—— 快速檢查斷面與車站樣板用。

要真實地形與全網請用 cli/build_world.py。

用法:
    ./.venv/bin/python -m cli.build_line --lines BR R Y
    ./.venv/bin/python -m cli.build_line --all
"""
import argparse
import csv
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt import config
from mrt.application import build_line as BL
from mrt.domain.alignment import (
    GROUND, STEP, drop_reversal, resample, select_variants,
    structure_for_ground, vertical_profile,
)
from mrt.infrastructure.mcworld import World


def load_stations():
    rows = []
    with open(config.MC_STATIONS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append((r["ref"].split(";"), r["name_zh"] or r["name_en"],
                         int(r["mc_x"]), int(r["mc_z"]), r["name_en"], r["ref"]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", nargs="*", default=["BR"])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default=config.DEFAULT_SAVE)
    a = ap.parse_args()

    lines = json.load(open(config.MC_LINES_JSON, encoding="utf-8"))
    refs = sorted(lines) if a.all else a.lines
    stations = load_stations()

    shutil.rmtree(a.out, ignore_errors=True)
    w = World(a.out, name=config.WORLD_NAME, spawn=(2633, 66, 1387))

    total_km = 0.0
    for ref in refs:
        if ref not in lines:
            print(f"{ref}: 沒有幾何資料，略過"); continue
        chosen = select_variants(lines[ref])
        all_samples, all_ys, cnt = [], [], {"viaduct": 0, "surface": 0, "tunnel": 0}
        km = 0.0
        for v in chosen:
            pts = [tuple(p) for p in v["points"]]
            kinds = v.get("kinds") or ["ground"] * len(pts)
            pts, kinds = drop_reversal(pts, kinds)
            samples = resample(pts, kinds, STEP)
            if len(samples) < 10:
                continue
            ys = vertical_profile([s[4] for s in samples])
            c = BL.build_alignment(w, samples, ys)
            for k in cnt:
                cnt[k] += c[k]
            all_samples += samples
            all_ys += ys
            km += len(samples) * STEP / 1000
        if not all_samples:
            print(f"{ref}: 取樣點太少，略過"); continue
        total_km += km
        samples, ys = all_samples, all_ys
        branch = f" (+{len(chosen)-1} 支線/分歧)" if len(chosen) > 1 else ""
        mine = [s for s in stations if any(t.startswith(ref) and
                (len(t) > len(ref) and t[len(ref)].isdigit()) for t in s[0])]
        built = 0
        for _, name, sx, sz, en, full_ref in mine:
            best, bd = None, 1e18
            for i, (x, z, _, _, _) in enumerate(samples):
                dd = (x - sx) ** 2 + (z - sz) ** 2
                if dd < bd:
                    bd, best = dd, i
            if bd ** 0.5 > 200:
                continue
            BL.build_station(w, samples, ys, best,
                             structure_for_ground(ys[best], GROUND) == "tunnel",
                             label=(full_ref, name, en))
            built += 1
        tot = max(1, sum(cnt.values()))
        print(f"{ref:<3} {km:>6.2f} km  y{min(ys):>3}~{max(ys):<3}  "
              f"高架{100*cnt['viaduct']//tot:>3}% 平面{100*cnt['surface']//tot:>3}% "
              f"地下{100*cnt['tunnel']//tot:>3}%  車站 {built}/{len(mine)}{branch}")

    print(f"\n合計 {total_km:.1f} km，寫入存檔…")
    w.save()


if __name__ == "__main__":
    main()
