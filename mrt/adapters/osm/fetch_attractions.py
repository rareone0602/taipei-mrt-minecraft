#!/usr/bin/env python3
"""Fetch the building footprints of the attractions -> data/attractions.json.

The position, orientation and footprint of each attraction building
(application/attractions/) always follow OSM: Taipei 101's way is tagged
height=508, the National Theater is tagged roof:shape=hipped, and the
Presidential Office Building is a relation with an inner ring. The appearance
(eight flared sections, double eaves, a central tower) is written as
parametric code from public architectural facts (height, floors, bays); the
footprints and orientations are not estimated.

One Overpass query per attraction: every building, building:part, historic,
man_made and attraction within a radius of the center point, plus the OSM
elements the catalog names (the main structure of some attractions has no
building tag, for example the Liberty Square gate). Neighboring buildings
within the radius are kept as well; they are needed to build plazas and walls
and to avoid the real neighbors. Coordinates use the fetch_details origin
(Taipei Main Station R10 -> MC (0,0), X = east, Z = south), but are kept to
0.1 m: a city gate is only a dozen or so meters wide, and rounding to whole
meters would skew it.

The raw Overpass responses are cached in OVERPASS_CACHE (the system temporary
directory by default); --refresh fetches again.

Usage: ./.venv/bin/python -m mrt.adapters.osm.fetch_attractions [--only taipei101 ...] [--refresh]
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

# Attraction catalog: (id, Chinese name, English name, center latitude,
# center longitude, radius m, named OSM elements).
# The id is ASCII (the datapack's function paths and the application's
# building modules both use it).
# The center point is the attraction's node or building centroid in OSM; the
# named elements are the main structure (the rest are neighbors).
CATALOG = [
    # ---- Around Taipei Main Station (within walking distance of the spawn point) ----
    ("shin_kong_tower", "新光摩天大樓", "Shin Kong Life Tower", 25.04605, 121.51510, 90,
     ("way/204711206",)),
    ("beimen", "北門（承恩門）", "North Gate (Beimen)", 25.04775, 121.51123, 45,
     ("way/238316480",)),
    ("national_taiwan_museum", "國立臺灣博物館", "National Taiwan Museum", 25.04275, 121.51500, 90,
     ("way/1050624691",)),
    ("presidential_office", "總統府", "Presidential Office Building", 25.04000, 121.51198, 160,
     ("relation/206817",)),
    ("red_house", "西門紅樓", "Red House", 25.04213, 121.50650, 70, ("way/222080307",)),
    # The three gates' center points were originally estimated from memory and
    # were off by 146 to 348 m, so the fetch returned only other buildings nearby
    # (the agent working on the gates and the temple found this by reading the
    # world back). They now use the positions of the gate ways in OSM, named
    # explicitly.
    ("dongmen", "東門（景福門）", "East Gate (Jingfu Gate)", 25.03902, 121.51767, 45,
     ("way/209580573",)),
    ("nanmen", "南門（麗正門）", "South Gate (Lizheng Gate)", 25.03511, 121.51499, 45,
     ("way/245993047",)),
    ("xiaonanmen", "小南門（重熙門）", "Little South Gate (Chongxi Gate)", 25.03691, 121.50807, 45,
     ("way/246651384",)),
    ("cks_memorial", "中正紀念堂", "Chiang Kai-shek Memorial Hall", 25.03550, 121.51980, 420,
     ("way/1052759757", "way/1052759775", "way/1052759776", "way/1053359244")),
    # ---- Other landmark attractions along the metro ----
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
    raise SystemExit("Origin station ref=R10 not found. Run fetch_stations first.")


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
    """Join a relation's member ways into rings by their endpoints.

    A way that does not connect stays a separate chain.
    """
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
    """Return (area in m2, centroid) of a closed ring."""
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
    # Drop the repeated end point of a closed ring.
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
        print(f"{aid:<24} {zh:<12} centre ({cx:>7.0f},{cz:>6.0f})  buildings {nb:>3}  building:part {npart:>3}  "
              f"named {sum(1 for f in feats if f['main'])}/{len(named)}")

    order = {c[0]: i for i, c in enumerate(CATALOG)}
    items.sort(key=lambda it: order.get(it["id"], 999))
    json.dump(dict(kind="tourist attraction footprints", crs="WGS84 -> EPSG:3826 (TWD97/TM2) -> MC，"
                   "X=東 Z=南，1 方塊 = 1 公尺（保留到 0.1 m）",
                   origin="台北車站 ref=R10 -> MC (0,0)", count=len(items), items=items),
              open(ATTRACTIONS_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nWrote {ATTRACTIONS_JSON}: {len(items)} attractions" + (f"; failed to fetch {failed}" if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
