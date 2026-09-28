#!/usr/bin/env python3
"""Fetch the branch-line relations whose ref is not a standard line code.

They are merged into the existing data/lines/*.json. For example, the
Xinbeitou Branch has the ref "捷運紅線 (新北投支線)" in OSM rather than "R", so a
query by line code misses the whole branch.
"""
import json, os

from mrt import config
from mrt.infrastructure.overpass import query

# Relation id -> the line it is merged into.
BRANCHES = {"R": [2665129, 9437206]}      # Xinbeitou Branch (both directions)


def run(q, label="branch"):
    return query(q, label=label, tries=6, timeout=180, backoff=3)


def main():
    tags = json.load(open(config.WAY_TAGS_JSON, encoding="utf-8"))
    KEEP = ("tunnel", "bridge", "layer", "railway", "usage", "service", "name", "level")
    for ref, ids in BRANCHES.items():
        path = os.path.join(config.LINES_DIR, f"{ref}.json")
        d = json.load(open(path, encoding="utf-8"))
        have = {e["id"] for e in d["elements"]}
        ids_str = ",".join(str(i) for i in ids)

        geom = run(f"[out:json][timeout:180];rel(id:{ids_str});out geom;")
        if geom is None:
            print(f"{ref}: geometry fetch failed"); continue
        added = 0
        for e in geom["elements"]:
            if e["id"] in have:
                continue
            d["elements"].append(e); added += 1

        wt = run(f"[out:json][timeout:180];rel(id:{ids_str});way(r);out tags;")
        nw = 0
        if wt:
            for e in wt["elements"]:
                if e["type"] == "way":
                    tags[str(e["id"])] = {k: v for k, v in (e.get("tags") or {}).items() if k in KEEP}
                    nw += 1

        json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(tags, open(config.WAY_TAGS_JSON, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"{ref}: merged {added} relations, {nw} way tags -> {path}")


if __name__ == "__main__":
    main()
