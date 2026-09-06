#!/usr/bin/env python3
"""只蓋文湖線（BR）—— 全線高架、無隧道，是最乾淨的垂直切片。

保留這支是因為它蓋出來的東西可以和通用生成器 (cli/build_line.py) 對照，
高架斷面改壞了會立刻看出來。

用法: ./.venv/bin/python -m cli.build_br [--out DIR] [--limit N]
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
    ap.add_argument("--limit", type=int, default=0, help="只蓋前 N 公尺（測試用）")
    a = ap.parse_args()

    lines = json.load(open(config.MC_LINES_JSON, encoding="utf-8"))
    v = max(lines["BR"], key=lambda v: len(v["points"]))
    pts = [tuple(p) for p in v["points"]]
    samples = resample(pts, STEP)
    if a.limit:
        samples = samples[:int(a.limit / STEP)]
    length_m = len(samples) * STEP
    print(f"文湖線 BR: 折線 {len(pts)} 點 -> 取樣 {len(samples)} 點, 長度 {length_m/1000:.2f} km")

    # 找出 BR 車站，對應到最近的取樣點
    stns = []
    with open(config.MC_STATIONS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if any(t.startswith("BR") for t in r["ref"].split(";")):
                stns.append((r["name_zh"] or r["name_en"], int(r["mc_x"]), int(r["mc_z"])))

    shutil.rmtree(a.out, ignore_errors=True)
    # 出生點放在大安站出入口樓梯底，走上去就是月台
    w = World(a.out, name="Taipei MRT — 文湖線", spawn=(2633, 66, 1387))

    print("鋪設高架橋…")
    build_viaduct(w, samples, set())

    print(f"設置車站 ({len(stns)} 座)…")
    built = 0
    for name, sx, sz in stns:
        best, bd = None, 1e18
        for i, (x, z, _, _) in enumerate(samples):
            d = (x - sx) ** 2 + (z - sz) ** 2
            if d < bd:
                bd, best = d, i
        if bd ** 0.5 > 150:      # 離線太遠 = 不屬於這條線的變體，跳過
            print(f"  略過 {name}（離線 {bd**0.5:.0f} m）")
            continue
        build_station(w, samples, best, name)
        built += 1
    print(f"  完成 {built} 座車站")

    print("寫入存檔…")
    w.save()
    print(f"\n路線長度 {length_m/1000:.2f} km，{len(w.chunks)} 個區塊")


if __name__ == "__main__":
    main()
