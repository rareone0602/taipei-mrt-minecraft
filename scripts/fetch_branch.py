#!/usr/bin/env python3
"""補抓 ref 不是標準代號的支線關聯，合併進既有的 data/lines/*.json。

例如新北投支線在 OSM 的 ref 是「捷運紅線 (新北投支線)」而非 "R"，
用代號查會整條漏掉。
"""
import json, os, subprocess, time, sys

MIRRORS = ["https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter"]

# 關聯 id -> 併入哪一條線
BRANCHES = {"R": [2665129, 9437206]}      # 新北投支線 (上下行)


def run(q, tries=6):
    for i in range(tries):
        url = MIRRORS[i % len(MIRRORS)]
        p = subprocess.run(["curl", "-sS", "--max-time", "180", "-X", "POST",
                            "--data-urlencode", f"data={q}", url],
                           capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip().startswith("{"):
            try:
                return json.loads(p.stdout)
            except json.JSONDecodeError:
                pass
        print(f"    重試 {i+1} @ {url.split('/')[2]}")
        time.sleep(3 + 3 * i)
    return None


def main():
    tags = json.load(open("data/way_tags.json"))
    KEEP = ("tunnel", "bridge", "layer", "railway", "usage", "service", "name", "level")
    for ref, ids in BRANCHES.items():
        path = f"data/lines/{ref}.json"
        d = json.load(open(path))
        have = {e["id"] for e in d["elements"]}
        ids_str = ",".join(str(i) for i in ids)

        geom = run(f"[out:json][timeout:180];rel(id:{ids_str});out geom;")
        if geom is None:
            print(f"{ref}: 幾何抓取失敗"); continue
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

        json.dump(d, open(path, "w"), ensure_ascii=False)
        json.dump(tags, open("data/way_tags.json", "w"), ensure_ascii=False)
        print(f"{ref}: 併入 {added} 個關聯, {nw} 條 way 標籤 -> {path}")


if __name__ == "__main__":
    main()
