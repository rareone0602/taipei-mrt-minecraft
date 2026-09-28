#!/usr/bin/env python3
"""Fetch the metro's pocket tracks, crossovers and depot tracks -> data/sidings.json.

The route geometry (fetch_network) only takes the member ways of the route
relations. Pocket tracks (storage sidings) and crossovers are not in the
relations, so they are fetched separately. OSM maps the Bannan Line's two
pocket tracks in full: the center one between Zhongxiao Fuxing and Zhongxiao
Dunhua is way 877532286, and the five ways between Far Eastern Hospital and
Haishan are named "亞東醫院袋狀軌" outright. The generator
(domain/stacked.POCKETS) uses this geometry to decide where the third track
starts and ends, and falls back to hand-entered distances only when there is no
data.

Two queries: first the known ways by id (these must be present), then a tag
scan of the whole BBOX (service=siding/crossover/yard, or a name containing
"袋狀軌"); the second one may fail. The coordinate conversion matches
fetch_details: Taipei Main Station ref=R10 -> MC (0,0), X=east, Z=south.

Usage: ./.venv/bin/python -m mrt.adapters.osm.fetch_sidings [--refresh]
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

# Known pocket-track ways (Bannan Line): the center track and the turnout legs at both ends.
KNOWN_IDS = [877532286, 877532243, 877532285, 877532287, 877532288,     # Zhongxiao Fuxing - Zhongxiao Dunhua
             818792051, 818792052, 818792053, 818792054, 818792055]     # Far Eastern Hospital - Haishan

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
    raise SystemExit("Origin station ref=R10 not found. Run fetch_stations first.")


def main():
    oE, oN = origin()
    to_mc = lambda E, N: (round(E - oE), round(-(N - oN)))
    refresh = "--refresh" in sys.argv
    print(f"Origin: Taipei Main Station (ref={ORIGIN_REF})  TWD97 E={oE:.1f} N={oN:.1f} -> MC (0,0)")

    d_ids = query_cached("sidings_ids", Q_IDS, cache_dir=CACHE, refresh=refresh, timeout=120)
    if d_ids is None:
        raise SystemExit("Could not fetch the known pocket-track ways: all three mirrors failed.")
    d_tags = query_cached("sidings_tags", Q_TAGS, cache_dir=CACHE, refresh=refresh,
                          tries=3, timeout=180)
    if d_tags is None:
        print("  Tag scan failed; using only the ways with known ids")

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
    print(f"  Wrote {config.SIDINGS_JSON}  ({len(items)} ways, of which known pocket tracks: "
          f"{sum(1 for it in items if it['known'])})")
    for it in items:
        if it["known"] or "袋狀" in it["name"]:
            x0, z0 = it["mc"][0]; x1, z1 = it["mc"][-1]
            print(f"    way {it['id']:<10} {it['length_m']:>6.1f} m  ({x0},{z0}) -> ({x1},{z1})  "
                  f"{it['name']} {it['service']}")


if __name__ == "__main__":
    main()
