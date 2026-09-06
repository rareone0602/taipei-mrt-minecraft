#!/usr/bin/env python3
"""抓每條路線所屬 way 的標籤 -> data/way_tags.json

relation 的 out geom 不含成員 way 自己的標籤，但成員有 way id。
這裡另外查一次「只要標籤」（回應很小），之後用 id join 回去，
就能知道每一段是 tunnel / bridge / 平面。
"""
import json, os, time

from mrt import config
from mrt.infrastructure.overpass import BBOX, query

REFS = ["R", "G", "O", "BL", "BR", "Y", "A", "V", "K"]
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
        print(f"已有 {len(tags)} 筆，繼續補齊")
    for ref in REFS:
        d = fetch(ref)
        if d is None:
            print(f"{ref:<3} 失敗")
            continue
        n = 0
        for e in d["elements"]:
            if e["type"] != "way":
                continue
            t = {k: v for k, v in (e.get("tags") or {}).items() if k in KEEP}
            tags[str(e["id"])] = t
            n += 1
        json.dump(tags, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"{ref:<3} OK  way={n:<5} 累計 {len(tags)}")
        time.sleep(2)

    # 摘要：看看隧道/橋樑的比例
    from collections import Counter
    c = Counter()
    for t in tags.values():
        if t.get("tunnel"): c["tunnel"] += 1
        elif t.get("bridge"): c["bridge"] += 1
        else: c["平面/未標"] += 1
    print("\n標籤分布:", dict(c))


if __name__ == "__main__":
    main()
