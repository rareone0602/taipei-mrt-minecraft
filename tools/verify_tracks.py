#!/usr/bin/env python3
"""從存檔讀回軌道配置：某一點的橫斷面裡有幾股鐵軌、各在哪個高度與離線位。

疊式車站（府中、西門）與袋狀軌（忠孝復興—忠孝敦化、亞東醫院—海山）都是
「軌道不在原本的位置」：兩股道分到上下兩層、或中間多一股。生成器說它鋪了，
不算數 —— 這支工具沿指定方向每公尺切一刀，數每一刀裡的鐵軌，印出
「距離 -> [(離線位, y), ...]」，一眼看得出第三股道從哪裡開始、下潛那股在
哪裡降到 -8、共用站體裡兩條線的四股道是不是各在自己的層。

用法:
    ./.venv/bin/python tools/verify_tracks.py <存檔> --xz X Z --dir UX UZ [--span 200] [--half 14]
    ./.venv/bin/python tools/verify_tracks.py <存檔> --station 府中 [--span 150]
    ./.venv/bin/python tools/verify_tracks.py <存檔> --station 西門 --expect 4 --levels 2
    ./.venv/bin/python tools/verify_tracks.py <存檔> --pocket 大安 信義安和 --expect 3
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
    """生成器實際會蓋的那幾份幾何。

    OSM 的同一條線常有上下行兩個 relation，幾何相差十幾二十公尺
    （淡水信義線在大安一帶就差 19 m）。工具若自己挑「最近的一份」，
    很容易挑到生成器沒蓋的那一份，切下去只看得到一股道 —— 驗證器自己騙人。
    """
    lines = json.load(open(config.MC_LINES_JSON, encoding="utf-8"))
    return AL.select_variants(lines.get(ref, []))


def station_frame(name):
    """站點座標與線形方向（取 mc_lines 裡離站點最近的那一段）。"""
    rows = list(csv.DictReader(open(config.MC_STATIONS_CSV, encoding="utf-8")))
    st = next((r for r in rows if r["name_zh"] == name), None)
    if st is None:
        raise SystemExit(f"mc_stations.csv 裡沒有 {name}")
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
    """袋狀軌的中點與走向：照 domain/stacked.POCKETS 登記的 OSM way 幾何。"""
    from mrt.domain import stacked as SK
    pk = next((k for k in SK.POCKETS if {k["a"], k["b"]} == {a, b}), None)
    if pk is None:
        raise SystemExit(f"stacked.POCKETS 裡沒有 {a}—{b}")
    items = json.load(open(config.SIDINGS_JSON, encoding="utf-8"))["items"]
    way = next((w for w in items if w["id"] == pk["osm"]), None)
    if way is None:
        raise SystemExit(f"data/sidings.json 裡沒有 way {pk['osm']}")
    # 儲車軌畫在正線旁邊 6 m 左右，切刀要以線形為中心才對稱 —— 照 way 自己的
    # 中點切，第三股道會落在窗子邊緣甚至外面（大安、台北車站兩處都是這樣）
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
    # 方向用儲車軌自己的弦：它一定是直的、而且與正線平行；mc_lines 逐段的
    # 走向會抖，拿來當切刀方向，走個幾十公尺就滑出隧道了
    (ax, az), (bx, bz) = pts[0], pts[-1]
    L = math.hypot(bx - ax, bz - az)
    px, pz, _, _ = project(pk["ref"], mid[0], mid[1])
    return px, pz, (bx - ax) / L, (bz - az) / L


def project(ref, x, z):
    """把一點投影到某條路線的中心線上，回傳 (投影點, 該處的走向)。"""
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
    """沿 (ux, uz) 從 -span 到 +span 每公尺切一刀，回傳 [(沿線距離, [(離線位, y)])]。"""
    nx, nz = -uz, ux
    xs = [x + ux * t + nx * o for t in (-span, span) for o in (-half, half)]
    zs = [z + uz * t + nz * o for t in (-span, span) for o in (-half, half)]
    x0, x1 = int(min(xs)) - 2, int(max(xs)) + 2
    z0, z1 = int(min(zs)) - 2, int(max(zs)) + 2
    # 讀回的高度：從地表往下 depth，地面用存檔裡最高的非空氣方塊估
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
    """同一個高度上相鄰的離線位算同一股。

    線形斜著走的時候，一股鐵軌是階梯狀的：連續兩格往前一格、往旁一格，
    切下去的那一刀就同時打到 -8 與 -9 兩格。古亭與中正紀念堂的線形是 56 度，
    四股道因此被數成六股、八股 —— 鐵軌沒問題，是這支工具數錯了。
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
    ap.add_argument("--pocket", nargs=2, metavar=("甲站", "乙站"),
                    help="照 stacked.POCKETS 的 OSM way 切袋狀軌那一段")
    ap.add_argument("--span", type=int, default=200)
    ap.add_argument("--half", type=int, default=14)
    ap.add_argument("--every", type=int, default=5, help="每幾公尺印一行")
    ap.add_argument("--expect", type=int, help="站體中心那一刀應該有幾股鐵軌")
    ap.add_argument("--levels", type=int, help="站體中心那一刀鐵軌應該分布在幾個高度")
    a = ap.parse_args()
    if a.pocket:
        x, z, ux, uz = pocket_frame(*a.pocket)
        print(f"袋狀軌 {a.pocket[0]}—{a.pocket[1]} 中點 ({x:.0f},{z:.0f})  "
              f"方向 ({ux:.2f},{uz:.2f})")
    elif a.station:
        x, z, ux, uz = station_frame(a.station)
        print(f"{a.station} ({x},{z})  方向 ({ux:.2f},{uz:.2f})")
    else:
        x, z = a.xz
        ux, uz = a.dir
        L = math.hypot(ux, uz)
        ux, uz = ux / L, uz / L
    rows = census(a.save, x, z, ux, uz, a.span, a.half)
    for t, hits in rows:
        if t % a.every == 0 or not hits:
            print(f"  {t:>+5d} m  {len(hits)} 股  {hits}")
    mid = next(h for t, h in rows if t == 0)
    n = len(mid)
    lv = sorted({y for _, y in mid})
    print(f"\n中心那一刀：{n} 股鐵軌，高度 {lv}")
    bad = False
    if a.expect is not None and n != a.expect:
        print(f"  應該有 {a.expect} 股  <- 有問題"); bad = True
    if a.levels is not None and len(lv) != a.levels:
        print(f"  應該分布在 {a.levels} 個高度  <- 有問題"); bad = True
    gaps = [t for t, h in rows if not h]
    if gaps:
        print(f"  沒有任何鐵軌的刀數 {len(gaps)}（{gaps[:8]}…）")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
