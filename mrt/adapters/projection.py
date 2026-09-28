#!/usr/bin/env python3
"""Project WGS84 -> TWD97/TM2 (EPSG:3826) -> Minecraft block coordinates (1 block = 1 meter).

Origin: Taipei Main Station (OSM ref="R10"). Writes data/mc_stations.csv and data/mc_lines.json.
Axes: MC X = east, Z = south (north is -Z).

Usage: ./.venv/bin/python -m mrt.adapters.projection
"""
import json, csv, glob, os, math
# Importing pyproj reads certifi's cacert.pem, which the sandbox's **/*.pem
# rule blocks. Only local projection happens here and no network is needed, so
# point the CA bundle elsewhere and turn off PROJ networking first.
os.environ.setdefault("CURL_CA_BUNDLE", "/dev/null")
os.environ.setdefault("PROJ_NETWORK", "OFF")
from pyproj import Transformer

from mrt import config

TF = Transformer.from_crs("EPSG:4326", "EPSG:3826", always_xy=True)
ORIGIN_REF = "R10"        # Taipei Main Station (OSM: ref="R10;BL12", name:en="Taipei main station")

def load_way_tags():
    """Return the way tags (tunnel / elevated).

    Returns an empty dict if fetch_way_tags has not run yet, so every segment
    is treated as at-grade.

    This table used to be a module-level constant, so importing projection read
    the file: anyone who only wanted proj() to convert one coordinate paid that
    cost, and when the file was read depended on who imported it first.
    """
    if not os.path.exists(config.WAY_TAGS_JSON):
        return {}
    with open(config.WAY_TAGS_JSON, encoding="utf-8") as f:
        return json.load(f)


def proj(lon, lat):
    """Return TWD97 (E, N) in meters."""
    return TF.transform(lon, lat)

def load_stations():
    with open(config.STATIONS_JSON, encoding="utf-8") as f:
        d = json.load(f)
    out = []
    for e in d["elements"]:
        t = e.get("tags", {})
        E, N = proj(e["lon"], e["lat"])
        out.append(dict(id=e["id"], lat=e["lat"], lon=e["lon"], E=E, N=N,
                        name_en=t.get("name:en", t.get("name", "")),
                        name_zh=t.get("name:zh", t.get("name", "")),
                        ref=t.get("ref", ""), layer=t.get("layer", "")))
    return out

def stitch(ways, tol=3):
    """Join the ways of an OSM relation by their endpoints.

    The member order of an OSM route relation is not guaranteed and a way may
    run in the opposite direction, so concatenating them directly produces false
    straight lines across the map. This greedily finds ways whose endpoints meet
    (reversing them when needed); a way that does not connect starts a new
    chain. A gap is better than a forced straight line.
    """
    d2 = lambda a, b: (a[0]-b[0])**2 + (a[1]-b[1])**2
    t2 = tol * tol
    remaining = [list(w) for w in ways if len(w) >= 2]
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
                    remaining.pop(i); joined = True; break
                if joined: break
        chains.append(chain)
    return sorted(chains, key=len, reverse=True)


def main():
    stns = load_stations()
    org = next((s for s in stns if ORIGIN_REF in s["ref"].split(";")), None)
    if org is None:
        raise SystemExit(f"Origin station ref={ORIGIN_REF} not found. It must not fall back "
                         f"silently to the centroid: every absolute coordinate would shift. "
                         f"Check data/stations.json.")
    oE, oN = org["E"], org["N"]
    # Minecraft: X = east, Z = south (north is -Z).
    to_mc = lambda E, N: (round(E - oE), round(-(N - oN)))

    with open(config.MC_STATIONS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ref","name_zh","name_en","mc_x","mc_z","layer","lat","lon"])
        for s in sorted(stns, key=lambda s: (s["ref"] or "zz")):
            x, z = to_mc(s["E"], s["N"])
            w.writerow([s["ref"], s["name_zh"], s["name_en"], x, z, s["layer"], s["lat"], s["lon"]])

    way_tags = load_way_tags()
    lines = {}
    empty = []
    for path in sorted(glob.glob(os.path.join(config.LINES_DIR, "*.json"))):
        ref = os.path.basename(path)[:-5]
        # Stop outright if the file cannot be read. This used to be
        # `except: continue`: one truncated G.json made the whole Songshan-Xindian
        # Line vanish from the world, and the output was merely one line shorter,
        # so nobody noticed.
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            raise SystemExit(f"Could not read the route file {path}: {e}\n"
                             f"It must not be skipped silently: line {ref} would vanish "
                             f"from the output entirely. Rerun fetch_network to fetch this file.")
        variants = []
        for rel in d["elements"]:
            t = rel.get("tags", {})
            ways = []
            for m in rel.get("members", []):
                # Keep only track ways; exclude platform and stop members.
                if m.get("type") != "way":
                    continue
                role = m.get("role", "")
                if "platform" in role or "stop" in role:
                    continue
                wt = way_tags.get(str(m.get("ref")), {})
                kind = ("tunnel" if wt.get("tunnel") else
                        "bridge" if wt.get("bridge") else "ground")
                w = []
                for pt in m.get("geometry") or []:
                    x, z = to_mc(*proj(pt["lon"], pt["lat"]))
                    if not w or (x, z) != (w[-1][0], w[-1][1]):
                        w.append((x, z, kind))
                if len(w) >= 2:
                    ways.append(w)
            chains = stitch(ways)
            if chains:
                best = max(chains, key=len)
                variants.append(dict(
                    name=t.get("name",""), name_zh=t.get("name:zh",""),
                    colour=t.get("colour",""),
                    points=[[p[0], p[1]] for p in best],
                    kinds=[p[2] for p in best],           # Per-point underground/elevated/at-grade class.
                    chains=[[[p[0], p[1]] for p in c] for c in chains]))
        if variants:
            lines[ref] = variants
        else:
            empty.append(ref)

    with open(config.MC_LINES_JSON, "w", encoding="utf-8") as f:
        json.dump(lines, f, ensure_ascii=False)

    if empty:
        # The file exists, but no route can be assembled from it. The Sanying
        # Line (LB) was like this: its relation only gained route=subway on
        # 2026-06-30, and before that a query filtered by route returned nothing.
        # fetch_network also skipped any file that existed, so an empty file was
        # never fetched again. When an empty file turns up, delete it, rerun
        # fetch_network, and check that the mirror's data date is recent enough.
        # This is printed so that a missing line shows up in the run's output,
        # rather than only in docs/building.md.
        print(f"warning: the route files for {', '.join(empty)} have no usable route relation; "
              f"these lines will not appear in the world\n")

    print(f"{len(stns)} stations -> data/mc_stations.csv")
    print(f"Origin: {org['name_zh']} ({org['ref']})  TWD97 E={oE:.1f} N={oN:.1f}  -> MC (0,0)\n")
    tot = 0
    for ref, vs in lines.items():
        v = max(vs, key=lambda v: len(v["points"]))
        length = sum(math.dist(v["points"][i], v["points"][i+1]) for i in range(len(v["points"])-1))
        tot += length
        k = v.get("kinds", [])
        pct = lambda w: 100.0 * sum(1 for x in k if x == w) / max(1, len(k))
        print(f"{ref:<3} {v['colour']:<9} main line {len(v['points']):>5} points  {length/1000:>6.1f} km  "
              f"underground {pct('tunnel'):>4.0f}%  elevated {pct('bridge'):>4.0f}%  at-grade {pct('ground'):>4.0f}%")
    print(f"\nWhole network, one direction: about {tot/1000:.1f} km ({tot:,.0f} blocks)")

if __name__ == "__main__":
    main()
