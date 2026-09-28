#!/usr/bin/env python3
"""Fetch the underground pedestrian routes -> data/indoor.json.

The routes are concourses, underground mall corridors, stairs and elevators.

The underground malls around Taipei Main Station are fully mapped in OSM:
8.8 km of corridor centerlines, 120 stairs, 16 elevators, and the outline
polygons of the Taipei City Mall, the Station Front Metro Mall and the
Zhongshan Metro Mall. Building from this data rather than inventing an
underground mall matches the project's 1:1 approach.

**Take both tagging schemes.** Taipei's underground concourses are tagged in
OSM in two schemes that coexist:
  Scheme A  highway=corridor + indoor=yes + level
            Taipei Main Station, Zhongshan, Songshan, Zhongxiao Fuxing...
  Scheme B  highway=footway  + indoor=yes + level
            southern Songshan-Xindian Line (six stations, Jingmei to
            Chiang Kai-Shek Memorial Hall)
Taking only scheme A misses 3.8 km, the largest area outside Taipei Main Station.

**Filter by level<0, not by indoor=yes.** A university next to Zhongxiao
Xinsheng station has mapped its buildings' interiors in full: 92 corridors,
1.2 km, all on levels 0 to 14. Filtering by indoor would grow a fourteen-story
school on top of the metro station. The test is in domain/concourse.underground().

Usage:
    ./.venv/bin/python -m mrt.adapters.osm.fetch_indoor
    ./.venv/bin/python -m mrt.adapters.osm.fetch_indoor --refresh   # bypass the cache
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
NEAR_M = 400            # Radius within which an item counts as belonging to a station.

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
    """Return (name, ref, x, z) rows, used to label which station each corridor belongs to."""
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
    print(f"Origin: Taipei Main Station (ref={ORIGIN_REF}) -> MC (0,0)")

    stns = load_stations()
    dw = query_cached("indoor_ways", Q_WAYS, cache_dir=CACHE,
                      refresh=refresh, timeout=600)
    da = query_cached("indoor_areas", Q_AREAS, cache_dir=CACHE,
                      refresh=refresh, timeout=600)
    dl = query_cached("indoor_lifts", Q_LIFTS, cache_dir=CACHE,
                      refresh=refresh, timeout=300)
    if dw is None:
        raise SystemExit("Corridor query failed; data/indoor.json left unchanged. "
                         "An empty file must not be written: later builds would silently "
                         "leave out a whole underground mall.")

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
                continue                      # Merge duplicate points so the length is accurate.
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
    print(f"  {len(ways)} corridors ({dropped} above ground filtered out), "
          f"{len(areas)} mall outlines, {len(lifts)} lifts")

    # Summary: which stations actually have something to build.
    per = {}
    for w in ways:
        st = w["station"] or "(no station)"
        e = per.setdefault(st, [0, 0.0])
        e[0] += 1
        e[1] += w["length"]
    print(f"\n{'station':<12}{'corridors':>10}{'length m':>9}")
    for st, (n, L) in sorted(per.items(), key=lambda kv: -kv[1][1])[:20]:
        print(f"  {st:<12}{n:>10}{L:>9.0f}")


if __name__ == "__main__":
    main()
