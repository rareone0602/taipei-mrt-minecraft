#!/usr/bin/env python3
"""Fetch the tags of the ways that belong to each route -> data/way_tags.json.

A relation's `out geom` does not include the member ways' own tags, but the
members carry their way ids. This makes a second, tags-only query (the response
is small) and joins it back by id, so each segment can be told apart as tunnel,
bridge or at-grade.
"""
import json, os, time

from mrt import config
from mrt.infrastructure.overpass import BBOX, query

REFS = ["R", "G", "O", "BL", "BR", "Y", "A", "V", "K", "LB"]
OUT = config.WAY_TAGS_JSON

KEEP = ("tunnel", "bridge", "layer", "railway", "usage", "service", "name", "level")


def tag_query(ref):
    return (f'[out:json][timeout:300];\n'
            f'relation["route"~"subway|light_rail"]["ref"="{ref}"]({BBOX});\n'
            f'way(r);\nout tags;')


def fetch(ref):
    return query(tag_query(ref), label=ref)


def main():
    tags = {}
    if os.path.exists(OUT):
        tags = json.load(open(OUT, encoding="utf-8"))
        print(f"{len(tags)} entries already present, filling in the rest")
    for ref in REFS:
        d = fetch(ref)
        if d is None:
            print(f"{ref:<3} failed")
            continue
        n = 0
        for e in d["elements"]:
            if e["type"] != "way":
                continue
            t = {k: v for k, v in (e.get("tags") or {}).items() if k in KEEP}
            tags[str(e["id"])] = t
            n += 1
        json.dump(tags, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"{ref:<3} OK  way={n:<5} total {len(tags)}")
        time.sleep(2)

    # Summary: the share of tunnels and bridges.
    from collections import Counter
    c = Counter()
    for t in tags.values():
        if t.get("tunnel"): c["tunnel"] += 1
        elif t.get("bridge"): c["bridge"] += 1
        else: c["at-grade/untagged"] += 1
    print("\nTag distribution:", dict(c))


if __name__ == "__main__":
    main()
