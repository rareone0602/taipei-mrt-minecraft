#!/usr/bin/env python3
"""抓取捷運的袋狀軌、橫渡線與機廠線 -> data/sidings.json

路線幾何（fetch_network）只收 route relation 的成員 way，袋狀軌（儲車軌）與
橫渡線不在 relation 裡，所以另外抓。OSM 對板南線的兩處袋狀軌畫得很完整：
忠孝復興—忠孝敦化的中央那條是 way 877532286，亞東醫院—海山的五條 way 直接
叫「亞東醫院袋狀軌」。生成器（domain/stacked.POCKETS）拿這裡的幾何決定
第三股道從哪裡鋪到哪裡，沒有資料才退回手填的距離。

查兩次：先照 id 抓已知的那幾條（一定要有），再用標籤掃整個 BBOX
（service=siding/crossover/yard、名字含「袋狀軌」）—— 後者失敗也沒關係。
座標轉法與 fetch_details 相同：台北車站 ref=R10 -> MC (0,0)，X=東、Z=南。

用法: ./.venv/bin/python -m mrt.adapters.osm.fetch_sidings [--refresh]
"""
import json
import math
import os
import sys
import tempfile

os.environ.setdefault("CURL_CA_BUNDLE", "/dev/null")
os.environ.setdefault("PROJ_NETWORK", "OFF")
from pyproj import Transformer

from mrt import config
from mrt.infrastructure.overpass import BBOX, query_cached

ORIGIN_REF = "R10"
CACHE = os.environ.get("OVERPASS_CACHE") or os.path.join(
    tempfile.gettempdir(), "mrt_overpass_cache")
TF = Transformer.from_crs("EPSG:4326", "EPSG:3826", always_xy=True)

# 已知的袋狀軌 way（板南線）：中央那條與兩端的道岔腿
KNOWN_IDS = [877532286, 877532243, 877532285, 877532287, 877532288,     # 忠孝復興—忠孝敦化
             818792051, 818792052, 818792053, 818792054, 818792055]     # 亞東醫院—海山

Q_IDS = f"""[out:json][timeout:120];
way(id:{",".join(str(i) for i in KNOWN_IDS)});
out geom;"""

Q_TAGS = f"""[out:json][timeout:180];
(
  way["railway"="subway"]["service"]({BBOX});
  way["railway"="subway"]["name"~"袋狀軌|儲車|避車"]({BBOX});
);
out geom;"""


def origin():
    d = json.load(open(config.STATIONS_JSON, encoding="utf-8"))
    for e in d["elements"]:
        if ORIGIN_REF in (e.get("tags", {}).get("ref", "")).split(";"):
            return TF.transform(e["lon"], e["lat"])
    raise SystemExit("找不到原點站 ref=R10；請先執行 fetch_stations")


def main():
    oE, oN = origin()
    to_mc = lambda E, N: (round(E - oE), round(-(N - oN)))
    refresh = "--refresh" in sys.argv
    print(f"原點 台北車站 (ref={ORIGIN_REF})  TWD97 E={oE:.1f} N={oN:.1f} -> MC (0,0)")

    d_ids = query_cached("sidings_ids", Q_IDS, cache_dir=CACHE, refresh=refresh, timeout=120)
    if d_ids is None:
        raise SystemExit("已知的袋狀軌 way 抓不到，三個鏡像都失敗")
    d_tags = query_cached("sidings_tags", Q_TAGS, cache_dir=CACHE, refresh=refresh,
                          tries=3, timeout=180)
    if d_tags is None:
        print("  標籤掃描失敗，只用已知 id 的那幾條")

    items, seen = [], set()
    for d in (d_ids, d_tags or {"elements": []}):
        for e in d["elements"]:
            if e.get("type") != "way" or e["id"] in seen or not e.get("geometry"):
                continue
            seen.add(e["id"])
            pts = []
            for p in e["geometry"]:
                x, z = to_mc(*TF.transform(p["lon"], p["lat"]))
                if not pts or [x, z] != pts[-1]:
                    pts.append([x, z])
            if len(pts) < 2:
                continue
            length = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
            t = e.get("tags", {})
            items.append(dict(id=e["id"], name=t.get("name", ""), service=t.get("service", ""),
                              tags={k: v for k, v in t.items()
                                    if k in ("name", "service", "railway", "tunnel", "layer",
                                             "usage", "operator", "gauge")},
                              mc=pts, length_m=round(length, 1), known=e["id"] in KNOWN_IDS))
    items.sort(key=lambda it: (not it["known"], it["id"]))
    doc = dict(kind="subway sidings / pocket tracks / crossovers", bbox=BBOX,
               origin=f"台北車站 ref={ORIGIN_REF} -> MC (0,0)",
               crs="WGS84 -> EPSG:3826 (TWD97/TM2) -> MC，X=東 Z=南，1 方塊 = 1 公尺",
               known_ids=KNOWN_IDS, count=len(items), items=items)
    json.dump(doc, open(config.SIDINGS_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  寫出 {config.SIDINGS_JSON}  ({len(items)} 條 way，其中已知的袋狀軌 "
          f"{sum(1 for it in items if it['known'])} 條)")
    for it in items:
        if it["known"] or "袋狀" in it["name"]:
            x0, z0 = it["mc"][0]; x1, z1 = it["mc"][-1]
            print(f"    way {it['id']:<10} {it['length_m']:>6.1f} m  ({x0},{z0}) -> ({x1},{z1})  "
                  f"{it['name']} {it['service']}")


if __name__ == "__main__":
    main()
