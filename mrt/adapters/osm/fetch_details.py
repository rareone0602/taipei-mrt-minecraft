#!/usr/bin/env python3
"""Fetch detailed metro station data.

Writes data/entrances.json, data/station_buildings.json and data/platform_levels.json.

Uses the same BBOX, mirrors and retry flow as fetch_stations.py. The raw
Overpass responses are cached in the temporary directory named by
OVERPASS_CACHE; a rerun reads the cache, and --refresh fetches again.
All coordinates are converted to Minecraft block coordinates with the same
origin as adapters/projection.py (Taipei Main Station ref=R10 -> MC (0,0),
X = east, Z = south, 1 block = 1 meter).

Exits are queried in two parts:
  A. railway=subway_entrance / train_station_entrance (nodes and ways), plus
     the entrance=* nodes attached to public_transport=stop_area relations;
     the railway/public_transport=station nodes come back in the same query
     as "station seeds".
  B. Every entrance=yes / entrance=main node in the BBOX (about 2400, mostly
     ordinary building doors), filtered locally by radius around the seeds.
The original plan was a single Overpass node(around.stn:150) query, but an
around over the whole Greater Taipei BBOX never finished on any of the three
mirrors (no response after more than 5 minutes). Local filtering is faster and
easier to check.
"""
import csv, json, math, os, re, sys, tempfile

# Importing pyproj reads certifi's cacert.pem, which the sandbox's **/*.pem
# rule blocks. Only local projection happens here and no network is needed, so
# point the CA bundle elsewhere and turn off PROJ networking first.
# (overpass.py removes CURL_CA_BUNDLE before calling curl; otherwise curl
# fails TLS.)
os.environ.setdefault("CURL_CA_BUNDLE", "/dev/null")
os.environ.setdefault("PROJ_NETWORK", "OFF")
from pyproj import Transformer

from mrt import config
from mrt.infrastructure.overpass import BBOX, query_cached

ORIGIN_REF = "R10"                 # Taipei Main Station (OSM ref="R10;BL12")
CACHE = os.environ.get("OVERPASS_CACHE") or os.path.join(
    tempfile.gettempdir(), "mrt_overpass_cache")
TF = Transformer.from_crs("EPSG:4326", "EPSG:3826", always_xy=True)
NEAR_M = 400          # Radius for assigning an item to a station in the summary (meters = blocks).
GEN_NEAR_M = 150      # How close to a station a generic entrance=yes/main must be to be kept.
CHECK_STATIONS = ["台北車站", "忠孝復興", "民權西路", "東門", "中山", "西門", "南港展覽館"]

# ---------------------------------------------------------------- Overpass queries

Q_ENTRANCE_A = f"""[out:json][timeout:300];
(
  node["railway"="subway_entrance"]({BBOX});
  way["railway"="subway_entrance"]({BBOX});
  node["railway"="train_station_entrance"]({BBOX});
  way["railway"="train_station_entrance"]({BBOX});
)->.direct;
rel["public_transport"="stop_area"]({BBOX})->.sa;
node(r.sa)["entrance"]->.saent;
(
  node["railway"="station"]({BBOX});
  node["public_transport"="station"]({BBOX});
)->.stn;
(.direct; .saent; .stn;);
out geom;"""

Q_ENTRANCE_GEN = f"""[out:json][timeout:300];
(
  node["entrance"="yes"]({BBOX});
  node["entrance"="main"]({BBOX});
);
out body;"""

Q_BUILDING = f"""[out:json][timeout:600];
(
  way["building"="train_station"]({BBOX});
  rel["building"="train_station"]({BBOX});
  way["building"="transportation"]({BBOX});
  rel["building"="transportation"]({BBOX});
  way["building"]["public_transport"]({BBOX});
  rel["building"]["public_transport"]({BBOX});
  way["building"]["railway"="station"]({BBOX});
  rel["building"]["railway"="station"]({BBOX});
);
out geom;"""

Q_PLATFORM = f"""[out:json][timeout:600];
(
  way["railway"="platform"]({BBOX});
  rel["railway"="platform"]({BBOX});
  way["public_transport"="platform"]({BBOX});
  rel["public_transport"="platform"]({BBOX});
)->.pf;
(
  way.pf["level"];
  rel.pf["level"];
  way.pf["layer"];
  rel.pf["layer"];
);
out geom;"""


def fetch(name, q):
    """Query Overpass with caching; read the cache when it exists so a rerun does not call the API again."""
    return query_cached(name, q, cache_dir=CACHE,
                        refresh="--refresh" in sys.argv, timeout=500)


# ---------------------------------------------------------------- Coordinate conversion

def origin():
    """Return the origin, as in adapters/projection.py: Taipei Main Station, ref=R10, is MC (0,0)."""
    d = json.load(open(config.STATIONS_JSON, encoding="utf-8"))
    for e in d["elements"]:
        if ORIGIN_REF in (e.get("tags", {}).get("ref", "")).split(";"):
            return TF.transform(e["lon"], e["lat"])
    raise SystemExit("Origin station ref=R10 not found. Run mrt.adapters.osm.fetch_stations first. "
                     "Another origin must not be substituted silently: every absolute "
                     "coordinate would shift.")


def ring(geom, to_mc):
    """Convert an OSM out-geom node list to MC [[x,z],...], dropping consecutive duplicate points."""
    out = []
    for pt in geom or []:
        if not pt:
            continue
        x, z = to_mc(*TF.transform(pt["lon"], pt["lat"]))
        if not out or [x, z] != out[-1]:
            out.append([x, z])
    return out


def stitch(rings, tol=2):
    """Join a relation's member ways into rings by their endpoints.

    A way that does not connect stays a separate chain; no straight line is forced between them.
    """
    d2 = lambda a, b: (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
    t2 = tol * tol
    remaining = [list(r) for r in rings if len(r) >= 2]
    chains = []
    while remaining:
        chain = remaining.pop(0)
        joined = True
        while joined:
            joined = False
            for i, w in enumerate(remaining):
                for cand in (w, w[::-1]):
                    if d2(chain[-1], cand[0]) <= t2:
                        chain += cand[1:]
                    elif d2(chain[0], cand[-1]) <= t2:
                        chain = cand[:-1] + chain
                    else:
                        continue
                    remaining.pop(i)
                    joined = True
                    break
                if joined:
                    break
        chains.append(chain)
    return sorted(chains, key=len, reverse=True)


def centroid(pts):
    """Return the area centroid of a closed ring, or the mean point of an open line."""
    if not pts:
        return None, None
    if len(pts) >= 4 and pts[0] == pts[-1]:
        a = cx = cz = 0.0
        for (x1, z1), (x2, z2) in zip(pts, pts[1:]):
            cr = x1 * z2 - x2 * z1
            a += cr
            cx += (x1 + x2) * cr
            cz += (z1 + z2) * cr
        if abs(a) > 1e-9:
            return round(cx / (3 * a)), round(cz / (3 * a))
    return (round(sum(p[0] for p in pts) / len(pts)),
            round(sum(p[1] for p in pts) / len(pts)))


def geometry_of(e, to_mc):
    """Return (outer rings, inner rings).

    A way has a single outer ring; a relation's members are joined first.
    """
    if e["type"] == "way":
        r = ring(e.get("geometry"), to_mc)
        return ([r] if r else []), []
    outer, inner = [], []
    for m in e.get("members", []):
        if m.get("type") != "way":
            continue
        r = ring(m.get("geometry"), to_mc)
        if len(r) >= 2:
            (inner if m.get("role") == "inner" else outer).append(r)
    return stitch(outer), stitch(inner)


def names(t):
    return dict(name=t.get("name", ""), name_zh=t.get("name:zh", ""),
                name_en=t.get("name:en", ""))


def pick(t, keys):
    """Keep only the key tags that have values, so the JSON is not filled with empty strings."""
    return {k: t[k] for k in keys if t.get(k)}

# ---------------------------------------------------------------- Exits

ENT_KEYS = ("railway", "entrance", "level", "layer", "highway", "wheelchair",
            "elevator", "operator", "network", "description", "note", "ref:zh")

# Many Taipei exits carry their number only in name, with no ref (for example
# name="Y11", "1號出入口", "捷運市政府站4號出口", "出口 3 (聯合醫院忠孝院區)").
# The patterns below fill in ref, and ref_from_name marks it as derived rather
# than an original tag.
REF_PATTERNS = [
    re.compile(r"^([A-Z]{1,2}\d{1,2})(?![0-9])"),      # M6出口 台北凱薩飯店 / Y11
    re.compile(r"(\d{1,2})\s*號出入?口"),               # 1號出入口 / 4號出口
    re.compile(r"出入?口\s*(\d{1,2})(?![0-9])"),        # 捷運出入口2 / 出口 3
    re.compile(r"^([東西南北]\d門)$"),                    # 北1門
]


def ref_from_name(t):
    for key in ("name", "name:zh", "description"):
        v = (t.get(key) or "").strip()
        if not v:
            continue
        for pat in REF_PATTERNS:
            m = pat.search(v)
            if m:
                return m.group(1)
    return ""


def is_station_seed(t):
    return (t.get("railway") == "station" or t.get("public_transport") == "station") \
        and not t.get("entrance") and "entrance" not in (t.get("railway") or "")


def entrance_record(e, to_mc, source):
    t = e.get("tags", {}) or {}
    poly = None
    if e["type"] == "node":
        x, z = to_mc(*TF.transform(e["lon"], e["lat"]))
        lat, lon = e["lat"], e["lon"]
    else:
        outer, _ = geometry_of(e, to_mc)
        if not outer:
            return None
        poly = outer[0]
        x, z = centroid(poly)                     # A way takes its geometric center.
        g = [p for p in (e.get("geometry") or []) if p]
        lat = round(sum(p["lat"] for p in g) / len(g), 7) if g else None
        lon = round(sum(p["lon"] for p in g) / len(g), 7) if g else None
    rw = t.get("railway", "")
    kind = (rw if rw.endswith("entrance") else f"entrance={t.get('entrance', '')}")
    ref, derived = t.get("ref", ""), False
    if not ref:
        ref = ref_from_name(t)
        derived = bool(ref)
    rec = dict(id=e["id"], type=e["type"], kind=kind, source=source,
               ref=ref, ref_from_name=derived, **names(t),
               lat=lat, lon=lon, mc_x=x, mc_z=z, tags=pick(t, ENT_KEYS))
    if poly:
        rec["polygon"] = poly
    return rec


def build_entrances(da, dg, to_mc):
    """Keep all of part A; keep part B (ordinary doors) only within GEN_NEAR_M of a station seed."""
    seeds, out, seen = [], [], set()
    for e in (da["elements"] if da else []):
        t = e.get("tags", {}) or {}
        if is_station_seed(t):
            if e["type"] == "node":
                seeds.append(to_mc(*TF.transform(e["lon"], e["lat"])))
            continue
        # One with railway=*_entrance is a direct hit; one with only entrance=*
        # comes from a stop_area relation.
        src = "railway_tag" if t.get("railway", "").endswith("entrance") else "stop_area"
        r = entrance_record(e, to_mc, src)
        if r:
            out.append(r)
            seen.add((r["type"], r["id"]))
    skipped = 0
    for e in (dg["elements"] if dg else []):
        if ("node", e["id"]) in seen:
            continue
        x, z = to_mc(*TF.transform(e["lon"], e["lat"]))
        if not any(math.dist((x, z), s) <= GEN_NEAR_M for s in seeds):
            skipped += 1
            continue
        r = entrance_record(e, to_mc, "near_station")
        if r:
            out.append(r)
            seen.add((r["type"], r["id"]))
    return out, len(seeds), skipped

# ---------------------------------------------------------------- Buildings / platforms

BLD_KEYS = ("building", "building:levels", "height", "min_height",
            "building:levels:underground", "building:min_level", "layer",
            "public_transport", "railway", "operator", "roof:shape", "roof:height")


def build_buildings(d, to_mc):
    out = []
    for e in d["elements"]:
        t = e.get("tags", {}) or {}
        outer, inner = geometry_of(e, to_mc)
        if not outer:
            continue
        poly = outer[0]
        cx, cz = centroid(poly)
        out.append(dict(id=e["id"], type=e["type"], **names(t),
                        mc_x=cx, mc_z=cz, tags=pick(t, BLD_KEYS),
                        polygon=poly, extra_outer=outer[1:], inner=inner))
    return out


PF_KEYS = ("railway", "public_transport", "level", "layer", "subway", "train",
           "light_rail", "network", "operator", "line", "route_ref", "colour",
           "covered", "surface", "width", "bus", "highway")


def build_platforms(d, to_mc):
    out = []
    for e in d["elements"]:
        t = e.get("tags", {}) or {}
        outer, _ = geometry_of(e, to_mc)
        if not outer:
            continue
        geom = outer[0]
        cx, cz = centroid(geom)
        out.append(dict(id=e["id"], type=e["type"], **names(t),
                        ref=t.get("ref", ""), level=t.get("level", ""),
                        layer=t.get("layer", ""),
                        lines=t.get("line") or t.get("route_ref") or "",
                        mc_x=cx, mc_z=cz, geometry=geom,
                        closed=len(geom) >= 4 and geom[0] == geom[-1],
                        tags=pick(t, PF_KEYS)))
    return out

# ---------------------------------------------------------------- Main flow

def load_mc_stations():
    """Read the existing data/mc_stations.csv, used to assign each item to its nearest station."""
    with open(config.MC_STATIONS_CSV, encoding="utf-8") as f:
        return [dict(ref=r["ref"], name=r["name_zh"],
                     x=int(r["mc_x"]), z=int(r["mc_z"]))
                for r in csv.DictReader(f)]


def attach_station(items, stns):
    """Label each item with its nearest metro station (left empty beyond NEAR_M, but the distance is kept).

    Platforms in this area have no line / route_ref tags at all in OSM, so the
    assignment can only be inferred from distance; station_ref is the field
    that maps back to a line code."""
    for it in items:
        best, bd = None, None
        for s in stns:
            d = math.dist((it["mc_x"], it["mc_z"]), (s["x"], s["z"]))
            if bd is None or d < bd:
                best, bd = s, d
        it["station"] = best["name"] if best and bd <= NEAR_M else ""
        it["station_ref"] = best["ref"] if best and bd <= NEAR_M else ""
        it["station_dist"] = round(bd) if bd is not None else None


def dump(path, kind, items, extra=None):
    doc = dict(kind=kind, bbox=BBOX,
               origin=f"台北車站 ref={ORIGIN_REF} -> MC (0,0)",
               crs="WGS84 -> EPSG:3826 (TWD97/TM2) -> MC，X=東 Z=南，1 方塊 = 1 公尺",
               count=len(items), items=items)
    if extra:
        doc.update(extra)
    json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  Wrote {path}  ({len(items)} items)")


def bad_coords(items, limit=35000):
    return [i for i in items
            if i.get("mc_x") is None or i.get("mc_z") is None
            or abs(i["mc_x"]) > limit or abs(i["mc_z"]) > limit]


def main():
    oE, oN = origin()
    to_mc = lambda E, N: (round(E - oE), round(-(N - oN)))
    print(f"Origin: Taipei Main Station (ref={ORIGIN_REF})  TWD97 E={oE:.1f} N={oN:.1f} -> MC (0,0)")
    print(f"Cache directory {CACHE}\n")

    da = fetch("entrances_a", Q_ENTRANCE_A)
    dg = fetch("entrances_gen", Q_ENTRANCE_GEN)
    db = fetch("buildings", Q_BUILDING)
    dp = fetch("platforms", Q_PLATFORM)
    print()

    stns = load_mc_stations()
    ents, n_seed, n_skip = build_entrances(da, dg, to_mc)
    blds = build_buildings(db, to_mc) if db else []
    pfs = build_platforms(dp, to_mc) if dp else []
    attach_station(ents, stns)
    attach_station(blds, stns)
    attach_station(pfs, stns)

    os.makedirs("data", exist_ok=True)
    dump(config.ENTRANCES_JSON, "subway/train station entrances", ents,
         dict(near_radius_m=NEAR_M, generic_entrance_radius_m=GEN_NEAR_M))
    dump(config.STATION_BUILDINGS_JSON, "station building footprints", blds)
    dump(config.PLATFORM_LEVELS_JSON, "platforms with level/layer", pfs)

    # ---------------------------------------------------------- Summary
    print("\n=== Summary ===")
    kinds, srcs = {}, {}
    for e in ents:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        srcs[e["source"]] = srcs.get(e["source"], 0) + 1
    print(f"Exits              {len(ents):>5}   " +
          "  ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    print("                   sources: " + "  ".join(f"{k}={v}" for k, v in sorted(srcs.items()))
          + f"   ({n_seed} station seeds; {n_skip} ordinary doors dropped as too far from a station)")
    print(f"                   with ref: {sum(1 for e in ents if e['ref']):>3} "
          f"({sum(1 for e in ents if e['ref_from_name'])} derived from name); "
          f"without ref: {sum(1 for e in ents if not e['ref'])}")
    print(f"Station buildings  {len(blds):>5}   "
          f"way={sum(1 for b in blds if b['type'] == 'way')}  "
          f"relation={sum(1 for b in blds if b['type'] == 'relation')}  "
          f"with levels={sum(1 for b in blds if b['tags'].get('building:levels'))}  "
          f"with height={sum(1 for b in blds if b['tags'].get('height'))}  "
          f"with underground levels={sum(1 for b in blds if b['tags'].get('building:levels:underground'))}")
    print(f"Platforms (levels) {len(pfs):>5}   "
          f"with level={sum(1 for p in pfs if p['level'])}  "
          f"with layer={sum(1 for p in pfs if p['layer'])}  "
          f"railway platforms={sum(1 for p in pfs if p['tags'].get('railway') == 'platform')}  "
          f"with line/route_ref={sum(1 for p in pfs if p['lines'])}  "
          f"matched to a station within {NEAR_M} m={sum(1 for p in pfs if p['station'])}")

    print(f"\nExits within {NEAR_M} metres of each station:")
    for nm in CHECK_STATIONS:
        pts = [(s["x"], s["z"]) for s in stns if s["name"] == nm]
        if not pts:
            print(f"  {nm:<6} station name not found in mc_stations.csv")
            continue
        near = [e for e in ents
                if any(math.dist((e["mc_x"], e["mc_z"]), p) <= NEAR_M for p in pts)]
        rw = sum(1 for e in near if e["kind"].endswith("entrance"))
        print(f"  {nm:<6} {len(near):>3} ({rw:>2} of them railway exits)   "
              f"{len(pts)} station points: " + ", ".join(f"({x},{z})" for x, z in pts))

    # ------------------------------------- List Taipei Main Station one by one (sanity check)
    tp = [(s["x"], s["z"]) for s in stns if s["name"] == "台北車站"]
    near = sorted((e for e in ents
                   if any(math.dist((e["mc_x"], e["mc_z"]), p) <= NEAR_M for p in tp)),
                  key=lambda e: (e["ref"] or "~", e["id"]))
    print(f"\n=== Exits within {NEAR_M} metres of Taipei Main Station (MC 0,0), one by one ({len(near)}) ===")
    print(f"  {'ref':<6}{'mc_x':>7}{'mc_z':>7}{'dist':>7}  {'kind':<24}{'name'}")
    for e in near:
        d = min(math.dist((e["mc_x"], e["mc_z"]), p) for p in tp)
        nm = e["name"] or e["name_zh"] or e["name_en"] or e["tags"].get("description", "")
        print(f"  {(e['ref'] or '-'):<6}{e['mc_x']:>7}{e['mc_z']:>7}{d:>7.0f}  "
              f"{e['kind']:<24}{nm}")
    rw_near = [e for e in near if e["kind"].endswith("entrance")]
    if len(rw_near) < 20:
        print(f"  warning: Taipei Main Station has more than 20 numbered exits in reality "
              f"(M1-M8, Z1-Z10, the K area, the Y area and others), but only {len(rw_near)} "
              f"railway exits were found here. The OSM data is incomplete; "
              f"do not treat it as the full set.")

    # ------------------------------------- Coordinate range check
    bad = bad_coords(ents) + bad_coords(blds) + bad_coords(pfs)
    allx = [i["mc_x"] for i in ents + blds + pfs if i.get("mc_x") is not None]
    allz = [i["mc_z"] for i in ents + blds + pfs if i.get("mc_z") is not None]
    if bad:
        print(f"\nwarning: {len(bad)} items have missing coordinates or lie beyond ±35000; check: "
              + ", ".join(f"{b['type']}/{b['id']}" for b in bad[:5]))
    else:
        print(f"\nCoordinate range check passed: X {min(allx)}~{max(allx)}, Z {min(allz)}~{max(allz)}"
              f" (all within ±35000)")


if __name__ == "__main__":
    main()
