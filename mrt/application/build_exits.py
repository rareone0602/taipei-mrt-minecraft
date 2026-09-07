#!/usr/bin/env python3
"""真實出入口生成器：把 domain/exits.py 算好的計畫變成可以 build() 的物件。

每座地下站（台北車站以外）原本只有一座樣板樓梯。這裡照 `data/entrances.json`
的真實座標與編號，替每個出入口蓋一座折返式樓梯井（ShaftStair）下到穿堂層，
再用一段接駁通道（Tile）沿站體外側接進穿堂層的非付費區。三樣東西全部沿用
地下街的那一套零件 —— 台北車站的連絡梯就是這麼接的，只是把 g0 從「地下街
樓板」換成「真實地面」。

回傳的物件都有 bbox() 與 build(w)，跟其他地標一樣由 cli/build_world 依 region
分桶。通道標 underground=True（不必為它生成地形），樓梯井不標 —— 它的出入口
亭露在街上，四周要有真實地形才不會懸空或被埋。

自我測試: ./.venv/bin/python tests/test_exits.py
"""
import collections

from mrt.application import build_concourse as BCC
from mrt.domain import exits as EX
from mrt.domain.alignment import structure_for_ground


def sign_lines(refs, name_zh, name_en):
    """出口牌的四行：編號、站名、英文站名、Exit。"""
    tags = [str(r) for r in refs if str(r)]
    tag = "/".join(tags[:3]) if tags else ""
    return [("出口 " + tag).strip(), name_zh or "", name_en or "",
            ("Exit " + tag).strip()]


def footprint(objs, used=None):
    """把一批地標的占用格加進 Occupancy（Tile 用實際地板與牆，其餘用 bbox，
    高度一律當成整根柱子）。

    出入口井不能壓到台北車站的地下街 —— 中山地下街一路通到雙連，
    中山站與雙連站的出入口井從地面挖下去，正好穿過它。
    """
    used = EX.Occupancy() if used is None else used
    for o in objs:
        cells = getattr(o, "cells", None)
        if cells is not None and getattr(o, "ring", None) is not None:
            for x, z in set(cells) | set(o.ring):
                used.add(x, z, -64, 319)
            continue
        x0, z0, x1, z1 = o.bbox()
        for x in range(int(x0), int(x1) + 1):
            for z in range(int(z0), int(z1) + 1):
                used.add(x, z, -64, 319)
    return used


def station_exits(segs, entrances_by_name, ground_at, skip=(), used=None,
                  verbose=True):
    """替所有地下站蓋真實出入口。

    segs               cli 規劃好的路段（samples / ys / ground / stn / hw）
    entrances_by_name  {站名: [(ref, x, z)]}
    ground_at          f(x, z) -> 地面 y
    skip               不處理的站名（台北車站一帶由地下街負責）
    used               Occupancy，已被其他地標占用的格子（footprint() 的結果）

    回傳 (objects, exits, report)：
      exits   {(路段索引, 取樣索引): 井的數量}，cli 用它關掉樣板樓梯
      report  {站名: dict(built, skipped)}
    """
    used = EX.Occupancy() if used is None else used
    occ = EX.index_segments(segs)

    boxes = collections.defaultdict(dict)          # 站名 -> {(li, bi): ...}
    labels = {}
    for li, sg in enumerate(segs):
        for bi, (full, name, en) in sg["stn"].items():
            y, g = int(sg["ys"][bi]), int(sg["ground"][bi])
            if structure_for_ground(y, g) != "tunnel":
                continue
            boxes[name][(li, bi)] = (sg["samples"], sg["ys"], bi)
            labels[(li, bi)] = (full, name, en)

    objs, exits, report = [], {}, {}
    for name in sorted(boxes):
        if name in skip:
            continue
        ents = entrances_by_name.get(name) or []
        if not ents:
            continue
        # 先併掉重複的節點，再分派到站體：同編號的兩個節點若分到兩座站體，
        # 後規劃的那條通道一定撞上先蓋的那座井
        merged = [("/".join(g["refs"]), g["x"], g["z"])
                  for g in EX.merge_entrances(ents)]
        assigned = EX.assign_to_boxes(merged, boxes[name])
        built, skipped = [], []
        for key, mine in assigned.items():
            if not mine:
                continue
            li, bi = key
            sg = segs[li]
            plan = EX.plan_station(sg["samples"], sg["ys"], sg["ground"], bi,
                                   mine, ground_at, occ, used, own_tag=li)
            skipped += plan["skipped"]
            if not plan["shafts"]:
                continue
            full, zh, en = labels[key]
            ring = BCC.outer_ring(plan["cells"]) - plan["no_wall"]
            tile = BCC.Tile(plan["cells"], ring, plan["ym"], {}, shopfront=False)
            tile.underground = True
            objs.append(tile)
            for s in plan["shafts"]:
                well = BCC.ShaftStair(s["x0"], s["z0"], s["ux"], s["uz"],
                                      s["g0"], s["y_to"], bottom_door=True,
                                      sign=sign_lines(s["refs"], zh, en))
                well.label = (name, s["refs"])
                well.underground = False
                objs.append(well)
                built.append(s)
            exits[key] = len(plan["shafts"])
        report[name] = dict(built=built, skipped=skipped)

    if verbose:
        nb = sum(len(r["built"]) for r in report.values())
        ns = sum(len(r["skipped"]) for r in report.values())
        why = collections.Counter(s[3] for r in report.values() for s in r["skipped"])
        print(f"  真實出入口：{len(exits)} 座車站共 {nb} 座樓梯井"
              + (f"，接不上的 {ns} 個（"
                 + "、".join(f"{k} {v}" for k, v in why.most_common()) + "）"
                 if ns else ""))
    return objs, exits, report
