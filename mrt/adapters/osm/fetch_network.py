#!/usr/bin/env python3
"""Fetch route geometry from OSM Overpass -> data/lines/*.json.

Covers the Taipei Metro, the Taoyuan Airport MRT and the light rail lines.
"""
import json, os, time

from mrt import config
from mrt.infrastructure.overpass import BBOX, query

REFS = ["R", "G", "O", "BL", "BR", "Y", "A", "V", "K", "LB"]
OUT = config.LINES_DIR

def relation_query(ref):
    return (f'[out:json][timeout:300];\n'
            f'(\n relation["route"~"subway|light_rail"]["ref"="{ref}"]({BBOX});\n);\nout geom;')

def fetch(ref):
    return query(relation_query(ref), label=ref)

def main():
    os.makedirs(OUT, exist_ok=True)
    for ref in REFS:
        path = f"{OUT}/{ref}.json"
        if os.path.exists(path):
            # An empty result (an empty elements list) does not count as existing:
            # the Sanying Line once came back as an empty file because a mirror's
            # data was stale, and every rerun after that skipped it here, so it
            # was never filled in.
            try:
                if json.load(open(path, encoding="utf-8")).get("elements"):
                    print(f"{ref:<3} already exists, skipped"); continue
                print(f"{ref:<3} file is empty, fetching again")
            except Exception: pass
        d = fetch(ref)
        if d is None:
            print(f"{ref:<3} failed"); continue
        json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        rels = d["elements"]
        pts = sum(len(w.get("geometry", [])) for r in rels for w in r.get("members", []))
        print(f"{ref:<3} OK  relations={len(rels):<3} points={pts:<6}")
        time.sleep(2)

if __name__ == "__main__":
    main()
