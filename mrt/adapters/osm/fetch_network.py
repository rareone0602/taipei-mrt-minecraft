#!/usr/bin/env python3
"""抓取台北捷運/機場捷運/輕軌路線幾何 (OSM Overpass) -> data/lines/*.json"""
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
            try:
                json.load(open(path)); print(f"{ref:<3} 已存在，略過"); continue
            except Exception: pass
        d = fetch(ref)
        if d is None:
            print(f"{ref:<3} 失敗"); continue
        json.dump(d, open(path, "w"), ensure_ascii=False)
        rels = d["elements"]
        pts = sum(len(w.get("geometry", [])) for r in rels for w in r.get("members", []))
        print(f"{ref:<3} OK  relations={len(rels):<3} points={pts:<6}")
        time.sleep(2)

if __name__ == "__main__":
    main()
