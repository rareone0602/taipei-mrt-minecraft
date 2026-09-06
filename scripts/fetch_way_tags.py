#!/usr/bin/env python3
"""抓每條路線所屬 way 的標籤 -> data/way_tags.json

relation 的 out geom 不含成員 way 自己的標籤，但成員有 way id。
這裡另外查一次「只要標籤」（回應很小），之後用 id join 回去，
就能知道每一段是 tunnel / bridge / 平面。
"""
import json, os, subprocess, time

MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
BBOX = "24.85,121.15,25.32,121.75"
REFS = ["R", "G", "O", "BL", "BR", "Y", "A", "V", "K"]
OUT = "data/way_tags.json"

KEEP = ("tunnel", "bridge", "layer", "railway", "usage", "service", "name", "level")


def query(ref):
    return (f'[out:json][timeout:300];\n'
            f'relation["route"~"subway|light_rail"]["ref"="{ref}"]({BBOX});\n'
            f'way(r);\nout tags;')


def fetch(ref, tries=9):
    for i in range(tries):
        url = MIRRORS[i % len(MIRRORS)]
        p = subprocess.run(["curl", "-sS", "--max-time", "300", "-X", "POST",
                            "--data-urlencode", f"data={query(ref)}", url],
                           capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            try:
                return json.loads(p.stdout), url
            except json.JSONDecodeError:
                print(f"    {ref}: 回應截斷/非 JSON ({len(p.stdout)}B) @ {url.split('/')[2]}")
        else:
            print(f"    {ref}: curl rc={p.returncode} @ {url.split('/')[2]}")
        time.sleep(4 + 4 * i)
    return None, None


def main():
    tags = {}
    if os.path.exists(OUT):
        tags = json.load(open(OUT))
        print(f"已有 {len(tags)} 筆，繼續補齊")
    for ref in REFS:
        d, url = fetch(ref)
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
        json.dump(tags, open(OUT, "w"), ensure_ascii=False)
        print(f"{ref:<3} OK  way={n:<5} 累計 {len(tags)}  via {url.split('/')[2]}")
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
