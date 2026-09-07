#!/usr/bin/env python3
"""從存檔讀回真實出入口，檢查每一座都能從街上走到月台 —— 不相信生成器的自述。

出入口亭怎麼找：讀回告示牌。每座出入口井的門邊都立了一面「出口 N／站名」，
牌子當然是生成器立的，但「牌子旁邊那座樓梯走不走得到月台」是從方塊
重建出來驗的，生成器說了不算。

關鍵規則是**不踩土**：洪水填滿時腳下只准是人造方塊（混凝土、平滑石、半磚、
襯砌……），草皮、泥土、石頭、沙、水都不准踩。容許踩地形的話，任何一座
樓梯壞了都可以沿街走到隔壁出入口再下去，等於什麼都沒驗到。這比
verify_concourse 的「不出地面」更嚴：出入口亭本身就在地面上。

每座車站檢查：
  1. 每面出口牌旁邊站得住（出入口亭真的在那裡）
  2. 從牌子出發、不踩土，走得到月台邊緣的黃色警戒帶
  3. 牌子旁邊有一格踩在地形上的立足點（門真的通到街上，不是封在牆裡）
  4. 同一座車站的出入口互相走得到（轉乘站兩座站體沒有轉乘通道時會是兩團，照實列出）

用法:
    ./.venv/bin/python tools/verify_exits.py <存檔>                    # 存檔裡所有出口牌
    ./.venv/bin/python tools/verify_exits.py <存檔> --stations 公館 西門
    ./.venv/bin/python tools/verify_exits.py <存檔> --bbox X0 Z0 X1 Z1
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
MARGIN = 60          # 讀回的範圍：出口牌與站點外擴幾公尺
DEPTH = 60           # 從最高的牌子往下讀幾公尺（最深的穿堂在地下 45 m 多一點）


def man_made(name):
    return name not in TERRAIN


def save_extent(save):
    """存檔所有 region 檔涵蓋的方塊範圍。"""
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


def door_cell(get, sx, sy, sz, radius=3):
    """牌子旁邊的門檻：離牌子最近、腳下是人造方塊、而且不是牌子本身的那一格。

    牌子立在門外的街上，它自己那一格底下墊了一塊石頭所以站得住，但四周
    全是街面 —— 從牌子出發「不踩土」一步也走不了。門檻那一格底下是井壁，
    從那裡進去才是在驗樓梯。
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
    """回傳 dict(n, ok_plat, ok_street, comps, bad)。"""
    xs = [s[0] for s in signs] + [p[0] for p in stn_pts]
    zs = [s[2] for s in signs] + [p[1] for p in stn_pts]
    ys = [s[1] for s in signs]
    x0, z0 = min(xs) - MARGIN, min(zs) - MARGIN
    x1, z1 = max(xs) + MARGIN, max(zs) + MARGIN
    y0, y1 = min(ys) - DEPTH, max(ys) + 6
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
        # 同一站同編號的牌子可能不只一面（西門捷運站 1 號出口與西門地下街
        # 1 號出入口都叫 1），鍵要帶座標才不會互相蓋掉
        tag = f"{msgs[0]}({sx},{sz})"
        c = door_cell(get, sx, sy, sz)
        if c is None:
            bad.append(f"{tag}: 牌子旁邊沒有門檻")
            continue
        feet[tag] = c
    ok_plat = ok_street = 0
    for tag, c in feet.items():
        dist, _ = walk.flood(get, [c], bounds=bounds, floor_ok=man_made)
        hit = sum(1 for y in yellow if y in dist)
        if hit:
            ok_plat += 1
        else:
            low = min((p[1] for p in dist), default=c[1])
            bad.append(f"{tag}: 不踩土走不到月台（走到 {len(dist)} 格，最低 y{low}）")
        # 門口有沒有踩在地形上的立足點（牌子在門外，沿四鄰找一格）
        street = False
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2)):
            for dy in (-1, 0, 1):
                n = (c[0] + dx, c[1] + dy, c[2] + dz)
                if walk.standable(get, *n, floor_ok=lambda b: b in TERRAIN):
                    street = True
        if street:
            ok_street += 1
        else:
            bad.append(f"{tag}: 門口沒有接到街面")
    comps = walk.components(get, list(feet.values()), bounds=bounds, floor_ok=man_made) \
        if feet else []
    return dict(n=len(signs), ok_plat=ok_plat, ok_street=ok_street,
                comps=len(comps), bad=bad, yellow=len(yellow))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save", nargs="?", default=config.DEFAULT_SAVE)
    ap.add_argument("--stations", nargs="*")
    ap.add_argument("--bbox", nargs=4, type=int, metavar=("X0", "Z0", "X1", "Z1"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    if not os.path.isdir(a.save):
        print(f"找不到存檔 {a.save}")
        return 1

    stn = station_xy()
    if a.bbox:
        box = tuple(a.bbox)
    elif a.stations:
        pts = [p for s in a.stations for p in stn.get(s, ())]
        if not pts:
            print("mc_stations.csv 裡沒有這些車站"); return 1
        box = (min(p[0] for p in pts) - 500, min(p[1] for p in pts) - 500,
               max(p[0] for p in pts) + 500, max(p[1] for p in pts) + 500)
    else:
        box = save_extent(a.save)
        if box is None:
            print("存檔裡沒有 region 檔"); return 1

    print(f"存檔 {a.save}\n讀取範圍 x {box[0]}..{box[2]}  z {box[1]}..{box[3]} 的告示牌 …")
    signs = read_signs(a.save, *box)
    by_station = collections.defaultdict(list)
    for x, y, z, msgs in signs:
        if len(msgs) >= 2 and msgs[0].startswith("出口") and msgs[1]:
            by_station[msgs[1]].append((x, y, z, msgs))
    if a.stations:
        by_station = {k: v for k, v in by_station.items() if k in a.stations}
    print(f"告示牌 {len(signs):,} 面，其中出口牌 {sum(len(v) for v in by_station.values())} 面，"
          f"{len(by_station)} 座車站\n")

    tot = collections.Counter()
    failed = []
    for name in sorted(by_station):
        sg = by_station[name]
        r = check_station(a.save, name, sg, stn.get(name, []), a.verbose)
        tot["n"] += r["n"]; tot["plat"] += r["ok_plat"]; tot["street"] += r["ok_street"]
        flag = "" if (r["ok_plat"] == r["n"] and r["ok_street"] == r["n"]) else "   <- 有問題"
        print(f"  {name:<8} 出口 {r['n']:>2} 座  通到月台 {r['ok_plat']:>2}  "
              f"通到街上 {r['ok_street']:>2}  分量 {r['comps']}{flag}")
        for b in r["bad"]:
            print(f"      {b}")
        if flag:
            failed.append(name)

    print(f"\n合計 {len(by_station)} 座車站 {tot['n']} 座出入口："
          f"通到月台 {tot['plat']}，通到街上 {tot['street']}")
    if failed:
        print(f"有問題的車站 {len(failed)} 座：{', '.join(failed)}")
        return 1
    print("全部通過：每一座出入口不踩土就走得到月台，門也都開在街上")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
