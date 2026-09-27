#!/usr/bin/env python3
"""抓取觀光景點的建物輪廓 -> data/attractions.json

景點建築（application/attractions/）的位置、方位與平面輪廓一律照 OSM：
台北101 的 way 標了 height=508、國家戲劇院標了 roof:shape=hipped、總統府是
一個帶內環的 relation。長相（八節斗狀、重簷、中央塔）是照公開的建築事實
（高度、樓層、開間）寫成參數化的程式；輪廓與方位不是估的。

每個景點打一次 Overpass：中心點半徑內的所有 building、building:part、
historic、man_made 與 attraction，外加目錄裡指名的 OSM 元素（有些景點的主體
沒掛 building，例如自由廣場的牌樓）。半徑內的鄰棟也留著 —— 蓋廣場、圍牆、
避開真實的鄰棟都用得到。座標照 fetch_details 的原點（台北車站 R10 -> MC (0,0)，
X = 東、Z = 南），但保留到 0.1 m：城門只有十幾公尺寬，四捨五入到整數公尺會歪。

Overpass 原始回應快取在 OVERPASS_CACHE（預設系統暫存目錄），加 --refresh 重抓。

用法: ./.venv/bin/python -m mrt.adapters.osm.fetch_attractions [--only taipei101 ...] [--refresh]
"""
import argparse
import json
import math
import os
import sys
import tempfile

os.environ.setdefault("CURL_CA_BUNDLE", "/dev/null")
os.environ.setdefault("PROJ_NETWORK", "OFF")
from pyproj import Transformer

from mrt import config
from mrt.infrastructure.overpass import query_cached

TF = Transformer.from_crs("EPSG:4326", "EPSG:3826", always_xy=True)
ORIGIN_REF = "R10"
CACHE = os.environ.get("OVERPASS_CACHE") or os.path.join(tempfile.gettempdir(), "mrt_overpass_cache")
ATTRACTIONS_JSON = os.path.join(config.DATA, "attractions.json")

# 景點目錄：(id, 中文名, 英文名, 中心緯度, 中心經度, 半徑 m, 指名的 OSM 元素)
# id 是 ASCII（資料包的函式路徑、application 的建築模組都用它）。
# 中心點取自 OSM 上該景點的節點或建物質心；指名的元素是主體（其餘是鄰棟）。
CATALOG = [
    # ---- 台北車站一帶（出生點走得到）----
    ("shin_kong_tower", "新光摩天大樓", "Shin Kong Life Tower", 25.04605, 121.51510, 90,
     ("way/204711206",)),
    ("beimen", "北門（承恩門）", "North Gate (Beimen)", 25.04775, 121.51123, 45,
     ("way/238316480",)),
    ("national_taiwan_museum", "國立臺灣博物館", "National Taiwan Museum", 25.04275, 121.51500, 90,
     ("way/1050624691",)),
    ("presidential_office", "總統府", "Presidential Office Building", 25.04000, 121.51198, 160,
     ("relation/206817",)),
    ("red_house", "西門紅樓", "Red House", 25.04213, 121.50650, 70, ("way/222080307",)),
    # 三座城門原本的中心點是憑印象估的，差了 146～348 m，抓回來的只是附近別的房子
    # （城門與廟那一組代理人讀回世界才發現）；改成 OSM 上城門 way 的位置並指名
    ("dongmen", "東門（景福門）", "East Gate (Jingfu Gate)", 25.03902, 121.51767, 45,
     ("way/209580573",)),
    ("nanmen", "南門（麗正門）", "South Gate (Lizheng Gate)", 25.03511, 121.51499, 45,
     ("way/245993047",)),
    ("xiaonanmen", "小南門（重熙門）", "Little South Gate (Chongxi Gate)", 25.03691, 121.50807, 45,
     ("way/246651384",)),
    ("cks_memorial", "中正紀念堂", "Chiang Kai-shek Memorial Hall", 25.03550, 121.51980, 420,
     ("way/1052759757", "way/1052759775", "way/1052759776", "way/1053359244")),
    # ---- 捷運沿線的其他代表性景點 ----
    ("taipei101", "台北101", "Taipei 101", 25.03395, 121.56450, 220,
     ("way/1159328965", "relation/11551064", "way/248210267")),
    ("sun_yat_sen_memorial", "國父紀念館", "Sun Yat-sen Memorial Hall", 25.04001, 121.56029, 170,
     ("way/189788192",)),
    ("longshan_temple", "艋舺龍山寺", "Longshan Temple", 25.03728, 121.49988, 90,
     ("way/198401479",)),
    ("grand_hotel", "圓山大飯店", "The Grand Hotel", 25.07873, 121.52639, 170,
     ("way/557039975", "relation/7659663")),
    ("miramar_wheel", "美麗華摩天輪", "Miramar Ferris Wheel", 25.08281, 121.55772, 90,
     ("node/5121602758",)),
]

KEEP_TAGS = ("name", "name:zh", "name:en", "building", "building:part", "building:levels",
             "building:levels:underground", "building:min_level", "min_height", "height",
             "roof:shape", "roof:height", "roof:levels", "roof:colour", "roof:material",
             "roof:orientation", "roof:direction", "building:colour", "building:material",
             "colour", "material", "historic", "man_made", "tourism", "attraction", "amenity",
             "leisure", "layer", "location", "start_date", "architect", "wikidata", "diameter")


def origin():
    d = json.load(open(config.STATIONS_JSON, encoding="utf-8"))
    for e in d["elements"]:
        if ORIGIN_REF in (e.get("tags", {}).get("ref", "")).split(";"):
            return TF.transform(e["lon"], e["lat"])
    raise SystemExit("找不到原點站 ref=R10；請先執行 fetch_stations。")


def query_for(lat, lon, r, named):
    ids = {"way": [], "relation": [], "node": []}
    for key in named:
        t, _, i = key.partition("/")
        ids[t].append(i)
    body = [f'wr["{k}"](around:{r},{lat},{lon});' for k in ("building", "building:part", "historic", "man_made")]
    body.append(f'nwr["attraction"](around:{r},{lat},{lon});')
    for t, lst in ids.items():
        if lst:
            body.append(f"{t}(id:{','.join(lst)});")
    return "[out:json][timeout:180];(\n  " + "\n  ".join(body) + "\n);\nout geom;"


def ring(geom, to_mc):
    out = []
    for pt in geom or []:
        if not pt:
            continue
        x, z = to_mc(*TF.transform(pt["lon"], pt["lat"]))
        p = [round(x, 1), round(z, 1)]
        if not out or p != out[-1]:
            out.append(p)
    return out


def stitch(rings, tol=1.0):
    """relation 的成員 way 依端點接成環；接不上的自成一段。"""
    d2 = lambda a, b: (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
    remaining = [list(r) for r in rings if len(r) >= 2]
    chains = []
    while remaining:
        chain = remaining.pop(0)
        joined = True
        while joined:
            joined = False
            for i, w in enumerate(remaining):
                for cand in (w, w[::-1]):
                    if d2(chain[-1], cand[0]) <= tol * tol:
                        chain += cand[1:]
                    elif d2(chain[0], cand[-1]) <= tol * tol:
                        chain = cand[:-1] + chain
                    else:
                        continue
                    remaining.pop(i)
                    joined = True
                    break
                if joined:
                    break
        chains.append(chain)
    return chains


def area_centroid(pts):
    """封閉環 -> (面積 m2, 質心)。"""
    if len(pts) < 3:
        return 0.0, (pts[0] if pts else [0, 0])
    a = cx = cz = 0.0
    for i in range(len(pts)):
        x1, z1 = pts[i]
        x2, z2 = pts[(i + 1) % len(pts)]
        cr = x1 * z2 - x2 * z1
        a += cr
        cx += (x1 + x2) * cr
        cz += (z1 + z2) * cr
    if abs(a) < 1e-9:
        n = len(pts)
        return 0.0, [sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n]
    return abs(a) / 2, [round(cx / (3 * a), 1), round(cz / (3 * a), 1)]


def feature(e, to_mc):
    t = e.get("tags", {})
    rec = {"osm": "%s/%d" % (e["type"], e["id"]),
           "tags": {k: t[k] for k in KEEP_TAGS if t.get(k)}}
    if e["type"] == "node":
        x, z = to_mc(*TF.transform(e["lon"], e["lat"]))
        rec.update(point=[round(x, 1), round(z, 1)], area=0.0, centroid=[round(x, 1), round(z, 1)])
        return rec
    if e["type"] == "way":
        r = ring(e.get("geometry"), to_mc)
        outer, inner = ([r] if r else []), []
    else:
        outer, inner = [], []
        for m in e.get("members", []):
            if m.get("type") != "way":
                continue
            r = ring(m.get("geometry"), to_mc)
            if len(r) >= 2:
                (inner if m.get("role") == "inner" else outer).append(r)
        outer, inner = stitch(outer), stitch(inner)
    # 封閉環去掉重複的終點
    outer = [r[:-1] if len(r) > 3 and r[0] == r[-1] else r for r in outer]
    inner = [r[:-1] if len(r) > 3 and r[0] == r[-1] else r for r in inner]
    if not outer:
        return None
    a_c = [area_centroid(r) for r in outer]
    area = sum(a for a, _ in a_c) - sum(area_centroid(r)[0] for r in inner)
    big = max(a_c, key=lambda v: v[0])
    rec.update(outer=outer, inner=inner, area=round(area, 1), centroid=big[1])
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    oE, oN = origin()
    to_mc = lambda E, N: (E - oE, -(N - oN))

    old = {}
    if os.path.exists(ATTRACTIONS_JSON):
        for it in json.load(open(ATTRACTIONS_JSON, encoding="utf-8"))["items"]:
            old[it["id"]] = it

    items, failed = [], []
    for aid, zh, en, lat, lon, r, named in CATALOG:
        if a.only and aid not in a.only:
            if aid in old:
                items.append(old[aid])
            continue
        d = query_cached("attr_" + aid, query_for(lat, lon, r, named), cache_dir=CACHE,
                         refresh=a.refresh, timeout=200, tries=8)
        if d is None:
            failed.append(aid)
            if aid in old:
                items.append(old[aid])
            continue
        cx, cz = to_mc(*TF.transform(lon, lat))
        feats, seen = [], set()
        for e in d["elements"]:
            key = "%s/%d" % (e["type"], e["id"])
            if key in seen:
                continue
            seen.add(key)
            f = feature(e, to_mc)
            if f is None:
                continue
            f["main"] = key in named
            f["dist"] = round(math.hypot(f["centroid"][0] - cx, f["centroid"][1] - cz), 1)
            feats.append(f)
        feats.sort(key=lambda f: (not f["main"], f["dist"]))
        items.append(dict(id=aid, name_zh=zh, name_en=en, center=[round(cx, 1), round(cz, 1)],
                          radius=r, main=list(named), features=feats))
        nb = sum(1 for f in feats if "building" in f["tags"])
        npart = sum(1 for f in feats if "building:part" in f["tags"])
        print(f"{aid:<24} {zh:<12} 中心 ({cx:>7.0f},{cz:>6.0f})  建物 {nb:>3}  building:part {npart:>3}  "
              f"指名 {sum(1 for f in feats if f['main'])}/{len(named)}")

    order = {c[0]: i for i, c in enumerate(CATALOG)}
    items.sort(key=lambda it: order.get(it["id"], 999))
    json.dump(dict(kind="tourist attraction footprints", crs="WGS84 -> EPSG:3826 (TWD97/TM2) -> MC，"
                   "X=東 Z=南，1 方塊 = 1 公尺（保留到 0.1 m）",
                   origin="台北車站 ref=R10 -> MC (0,0)", count=len(items), items=items),
              open(ATTRACTIONS_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n寫出 {ATTRACTIONS_JSON}：{len(items)} 個景點" + (f"；抓不到 {failed}" if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
