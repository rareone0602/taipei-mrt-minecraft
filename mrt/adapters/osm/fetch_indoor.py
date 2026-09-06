#!/usr/bin/env python3
"""抓地下人行動線（穿堂、地下街連通道、樓梯、電梯）-> data/indoor.json

台北車站一帶的地下街在 OSM 上是完整測繪過的：8.8 km 的通道中心線、
120 條樓梯、16 座電梯，還有台北地下街／站前地下街／中山地下街的商場輪廓面。
與其自己編一套地下街，不如照著這份資料蓋 —— 這和整個專案「1:1 重建」的
做法一致。

**兩種畫法都要收**。OSM 台北的地下穿堂有兩套並存的標法：
  A 式  highway=corridor + indoor=yes + level     台北車站、中山、松山、忠孝復興…
  B 式  highway=footway  + indoor=yes + level     松山新店線南段（景美到中正紀念堂六站）
只認 A 式會漏掉 3.8 km，那是台北車站以外最大的一塊。

**用 level<0 過濾，不要用 indoor=yes 過濾**。忠孝新生站旁有一所大學把校舍
室內圖畫得很完整 —— 92 條 corridor、1.2 km，level 全是 0~14。照 indoor 收
會在捷運站上面長出一棟十四層的學校。判斷寫在 domain/concourse.underground()。

用法:
    ./.venv/bin/python -m mrt.adapters.osm.fetch_indoor
    ./.venv/bin/python -m mrt.adapters.osm.fetch_indoor --refresh   # 不讀快取
"""
import csv
import math
import os
import sys

from mrt import config
from mrt.domain import concourse
from mrt.infrastructure.overpass import BBOX, query_cached
from mrt.adapters.osm.fetch_details import CACHE, ORIGIN_REF, TF, dump, origin

OUT = os.path.join(config.DATA, "indoor.json")
NEAR_M = 400            # 判定「屬於某站」的半徑

Q_WAYS = f"""[out:json][timeout:600];
(
  way["highway"="corridor"]({BBOX});
  way["highway"="footway"]["level"]({BBOX});
  way["highway"="footway"]["tunnel"]({BBOX});
  way["highway"="steps"]["level"]({BBOX});
  way["highway"="steps"]["tunnel"]({BBOX});
  way["highway"="elevator"]({BBOX});
);
out geom;"""

Q_AREAS = f"""[out:json][timeout:600];
(
  way["shop"="mall"]["level"]({BBOX});
  way["indoor"="area"]["level"]({BBOX});
  way["indoor"="room"]["level"]({BBOX});
);
out geom;"""

Q_LIFTS = f"""[out:json][timeout:300];
node["highway"="elevator"]({BBOX});
out;"""

KEEP = ("highway", "indoor", "level", "layer", "tunnel", "name", "name:zh",
        "name:en", "ref", "conveying", "incline", "shop", "building", "room")


def pick(tags):
    return {k: v for k, v in (tags or {}).items() if k in KEEP}


def load_stations():
    """(名稱, ref, x, z)，用來標註每條通道屬於哪一站。"""
    rows = []
    with open(config.MC_STATIONS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append((r["name_zh"] or r["name_en"], r["ref"],
                         int(r["mc_x"]), int(r["mc_z"])))
    return rows


def tag_station(item, stns, x, z):
    best, bd = None, None
    for name, ref, sx, sz in stns:
        d = math.hypot(x - sx, z - sz)
        if bd is None or d < bd:
            best, bd = (name, ref), d
    item["station"] = best[0] if bd is not None and bd <= NEAR_M else ""
    item["station_ref"] = best[1] if bd is not None and bd <= NEAR_M else ""
    item["station_dist"] = round(bd) if bd is not None else None


def main():
    refresh = "--refresh" in sys.argv
    oE, oN = origin()
    to_mc = lambda E, N: (round(E - oE), round(-(N - oN)))
    print(f"原點 台北車站 (ref={ORIGIN_REF}) -> MC (0,0)")

    stns = load_stations()
    dw = query_cached("indoor_ways", Q_WAYS, cache_dir=CACHE,
                      refresh=refresh, timeout=600)
    da = query_cached("indoor_areas", Q_AREAS, cache_dir=CACHE,
                      refresh=refresh, timeout=600)
    dl = query_cached("indoor_lifts", Q_LIFTS, cache_dir=CACHE,
                      refresh=refresh, timeout=300)
    if dw is None:
        raise SystemExit("通道查詢失敗，data/indoor.json 不動。"
                         "不可寫出空檔 —— 之後的生成會靜默地少蓋一整座地下街。")

    ways, dropped = [], 0
    for e in dw["elements"]:
        if e["type"] != "way" or not e.get("geometry"):
            continue
        t = e.get("tags") or {}
        if not concourse.underground(t):
            dropped += 1
            continue
        pts, nodes = [], []
        for nid, g in zip(e.get("nodes", []), e["geometry"]):
            x, z = to_mc(*TF.transform(g["lon"], g["lat"]))
            if pts and [x, z] == pts[-1]:
                continue                      # 併掉重複點，長度才算得準
            pts.append([x, z])
            nodes.append(nid)
        if len(pts) < 2:
            continue
        lv = concourse.parse_level(t.get("level"))
        it = dict(id=e["id"], type="way", highway=t.get("highway", ""),
                  name=t.get("name", ""), name_zh=t.get("name:zh", ""),
                  ref=t.get("ref", ""), level=t.get("level", ""),
                  level_lo=lv[0] if lv else None, level_hi=lv[1] if lv else None,
                  layer=t.get("layer", ""), conveying=t.get("conveying", ""),
                  nodes=nodes, points=pts,
                  length=round(sum(math.dist(pts[i], pts[i + 1])
                                   for i in range(len(pts) - 1)), 1),
                  tags=pick(t))
        cx = sum(p[0] for p in pts) / len(pts)
        cz = sum(p[1] for p in pts) / len(pts)
        it["mc_x"], it["mc_z"] = round(cx), round(cz)
        tag_station(it, stns, cx, cz)
        ways.append(it)

    areas = []
    for e in (da or {}).get("elements", []):
        if e["type"] != "way" or not e.get("geometry"):
            continue
        t = e.get("tags") or {}
        lv = concourse.parse_level(t.get("level"))
        if not lv or lv[0] >= 0:
            continue
        poly = []
        for g in e["geometry"]:
            x, z = to_mc(*TF.transform(g["lon"], g["lat"]))
            if not poly or [x, z] != poly[-1]:
                poly.append([x, z])
        if len(poly) < 4:
            continue
        it = dict(id=e["id"], type="way", name=t.get("name", ""),
                  name_zh=t.get("name:zh", ""), level=t.get("level", ""),
                  level_lo=lv[0], level_hi=lv[1], polygon=poly, tags=pick(t))
        cx = sum(p[0] for p in poly) / len(poly)
        cz = sum(p[1] for p in poly) / len(poly)
        it["mc_x"], it["mc_z"] = round(cx), round(cz)
        tag_station(it, stns, cx, cz)
        areas.append(it)

    lifts = []
    for e in (dl or {}).get("elements", []):
        if e["type"] != "node":
            continue
        t = e.get("tags") or {}
        lv = concourse.parse_level(t.get("level"))
        if not lv or lv[0] >= 0:
            continue
        x, z = to_mc(*TF.transform(e["lon"], e["lat"]))
        it = dict(id=e["id"], type="node", ref=t.get("ref", ""),
                  level=t.get("level", ""), level_lo=lv[0], level_hi=lv[1],
                  mc_x=x, mc_z=z, tags=pick(t))
        tag_station(it, stns, x, z)
        lifts.append(it)

    dump(OUT, "underground pedestrian corridors, stairs and lifts", ways,
         extra=dict(areas=areas, lifts=lifts,
                    area_count=len(areas), lift_count=len(lifts)))
    print(f"  通道 {len(ways)} 條（篩掉地上的 {dropped} 條）、"
          f"商場輪廓 {len(areas)} 面、電梯 {len(lifts)} 座")

    # 摘要：哪幾站真的有東西可以蓋
    per = {}
    for w in ways:
        st = w["station"] or "（不屬於任何站）"
        e = per.setdefault(st, [0, 0.0])
        e[0] += 1
        e[1] += w["length"]
    print(f"\n{'車站':<12}{'通道數':>6}{'長度 m':>9}")
    for st, (n, L) in sorted(per.items(), key=lambda kv: -kv[1][1])[:20]:
        print(f"  {st:<12}{n:>6}{L:>9.0f}")


if __name__ == "__main__":
    main()
