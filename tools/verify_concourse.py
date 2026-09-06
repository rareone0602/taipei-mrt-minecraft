#!/usr/bin/env python3
"""從存檔讀回地下街，檢查每個出入口真的走得到彼此 —— 不相信生成器的自述。

生成器只知道自己放了哪些方塊，不知道那些方塊拼起來走不走得通。少鋪一階、
通道被別條線的隧道襯砌切斷、頂板壓到只剩一格淨空，在生成紀錄裡通通是
「已完成」。所以獨立把方塊讀回來，用玩家真的走得動的規則（domain/walk.py）
洪水填滿，看出入口落在幾個連通分量裡。

關鍵是**不准走到地面**：所有出入口本來就都開在同一條街上，容許走地面的話
一定全部相連，等於什麼都沒驗到。地下的可走空間才算數。

檢查四件事：
  1. 每個出入口在地下都有站得住的空間（不是一個通到實心土裡的洞）
  2. 不出地面就能在出入口之間往返（連通分量只有一個）
  3. 走得到月台邊緣的黃色警戒帶（地下街真的接進車站，不是自成一區）
  4. 每個出入口也連得上地面（樓梯沒有被封死在地下）

用法:
    ./.venv/bin/python tools/verify_concourse.py                     # 預設存檔、台北車站
    ./.venv/bin/python tools/verify_concourse.py out/測試 --stations 台北車站 北門
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

PLAT_EDGE = "minecraft:yellow_concrete"     # 月台邊緣警戒帶，build_line 的 YELLOW


def load_entrances(stations, margin):
    """挑出屬於這幾座車站的出入口，並算出要讀回來的範圍。"""
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
                    help="出入口範圍再往外擴幾公尺")
    ap.add_argument("--depth", type=int, default=40,
                    help="從地面往下讀幾公尺")
    a = ap.parse_args()

    if not os.path.isdir(a.save):
        print(f"找不到存檔 {a.save}")
        return 1

    ents, box = load_entrances(a.stations, a.margin)
    if not ents:
        print(f"entrances.json 裡沒有 {', '.join(a.stations)} 的出入口")
        return 1
    x0, z0, x1, z1 = box

    terr = Terrain()
    gs = [int(terr.y_at(x, z)) for _, _, x, z in ents]
    g_hi = max(gs)
    y1 = g_hi + 6                       # 含地面出入口亭
    y0 = min(gs) - a.depth
    # 地下的定義取最低的地面再減 3：出入口亭的地坪也算地面，不能放行
    ug_top = min(gs) - 3

    print(f"存檔 {a.save}")
    print(f"車站 {', '.join(a.stations)}：出入口 {len(ents)} 個")
    print(f"範圍 x {x0}..{x1}  z {z0}..{z1}  y {y0}..{y1}"
          f"（地面 y {min(gs)}~{g_hi}，地下的上限取 y<={ug_top}）")

    vol = read_volume(a.save, x0, y0, z0, x1, y1, z1)
    get = vol.get
    ug_bounds = (x0, y0, z0, x1, ug_top, z1)

    # ---- 1. 每個出入口在地下有沒有立足點 ----
    foot, nowhere = {}, []
    for ref, st, x, z in ents:
        c = walk.nearest_standable(get, x, ug_top - 4, z, radius=8, dy=20)
        if c and c[1] <= ug_top:
            foot[(ref, st)] = c
        else:
            nowhere.append(f"{ref}({st})")

    print(f"\n[1] 地下有立足點：{len(foot)}/{len(ents)}")
    if nowhere:
        print(f"    地下完全沒有東西的出入口 {len(nowhere)} 個："
              f"{', '.join(nowhere)}")

    if not foot:
        print("\n地下什麼都沒有，不必再往下驗。")
        return 1

    # ---- 2. 不出地面的連通性 ----
    cells = list(foot.values())
    comps = walk.components(get, cells, bounds=ug_bounds)
    inv = collections.defaultdict(list)
    for (ref, st), c in foot.items():
        # ref 在不同車站會重複（台北車站與北門都有 1、2、3 號出入口），
        # 只印 ref 會看不出是哪一站的。
        inv[c].append(f"{ref}({st})" if len(a.stations) > 1 else ref)
    print(f"\n[2] 不出地面的連通分量：{len(comps)} 個")
    for i, g in enumerate(comps, 1):
        refs = sorted({r for c in g for r in inv[c]})
        head = ", ".join(refs[:14]) + (" …" if len(refs) > 14 else "")
        print(f"    分量{i:>2}（{len(refs):>3} 個出入口）: {head}")

    # 最遠的一對走幾步：地下街不該繞遠路
    main_comp = comps[0]
    dist, came = walk.flood(get, [main_comp[0]], bounds=ug_bounds)
    far = max(((dist.get(c, -1), c) for c in main_comp), key=lambda t: t[0])
    if far[0] > 0:
        refs = ", ".join(inv[far[1]])
        print(f"    最大分量內，從 {', '.join(inv[main_comp[0]])} 走到 {refs} "
              f"要 {far[0]:,} 步")

    # ---- 3. 走不走得到月台 ----
    print("\n[3] 從最大分量走得到的月台邊緣：")
    edges = []
    for yy in range(y0, ug_top + 1):
        for zz in range(z0, z1 + 1, 4):
            for xx in range(x0, x1 + 1, 4):
                if get(xx, yy, zz) == PLAT_EDGE:
                    edges.append((xx, yy + 1, zz))
    if not edges:
        print("    範圍內沒有月台警戒帶（這個存檔可能沒蓋車站）")
    else:
        # 把警戒帶分群 —— 範圍裡不只一座車站，混在一起數會看不出
        # 「哪一座月台走不到」。同 y 且相距 60 m 內算同一座月台。
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
            print(f"    月台面 y={g[0][1]:>3} 約 ({gx:>5},{gz:>5})："
                  f"抽樣 {len(g):>3} 格，走得到 {n:>3} 格"
                  + ("" if n else "   <- 走不到"))
        reach_edges = [c for c in edges if c in dist]

    # ---- 4. 每個出入口通不通地面 ----
    # 一定要逐個出入口各洪水一次。把所有立足點一起當起點的話，只要有一座
    # 樓梯通到街上，全部出入口就都「通過」了 —— 街道本來就是連通的，
    # 那樣等於什麼都沒驗到。範圍也要圈在出入口附近，否則會沿著街道漫出去。
    no_surface = []
    for (ref, st), c in sorted(foot.items()):
        g = int(terr.y_at(c[0], c[2]))
        b = (c[0] - 50, y0, c[2] - 50, c[0] + 50, y1, c[2] + 50)
        d, _ = walk.flood(get, [c], bounds=b)
        if not any(p[1] >= g for p in d):
            no_surface.append(f"{ref}({st})")
    print(f"\n[4] 從地下走得上地面：{len(foot) - len(no_surface)}/{len(foot)}")
    if no_surface:
        print(f"    出不去地面的：{', '.join(no_surface)}")

    bad = bool(nowhere) or len(comps) > 1 or bool(no_surface) \
        or (edges and not reach_edges)
    print("\n" + ("有問題，見上面各項" if bad else
                  "全部通過：所有出入口不出地面就能互相往返，並且都通得到月台與地面"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
