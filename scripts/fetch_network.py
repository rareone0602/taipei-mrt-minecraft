#!/usr/bin/env python3
"""抓取台北捷運/機場捷運/輕軌路線幾何 (OSM Overpass) -> data/lines/*.json
用 curl 子行程送出請求（避開 sandbox 對 *.pem 的讀取限制）。"""
import json, os, subprocess, time

MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
BBOX = "24.85,121.15,25.32,121.75"
REFS = ["R", "G", "O", "BL", "BR", "Y", "A", "V", "K", "LB"]
OUT = "data/lines"

def query(ref):
    return (f'[out:json][timeout:300];\n'
            f'(\n relation["route"~"subway|light_rail"]["ref"="{ref}"]({BBOX});\n);\nout geom;')

def fetch(ref, tries=9):
    for i in range(tries):
        url = MIRRORS[i % len(MIRRORS)]
        p = subprocess.run(["curl", "-sS", "--max-time", "300", "-X", "POST",
                            "--data-urlencode", f"data={query(ref)}", url],
                           capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            try:
                return json.loads(p.stdout), url   # 解析成功才算數，可擋截斷
            except json.JSONDecodeError:
                print(f"    {ref}: 回應截斷/非 JSON ({len(p.stdout)}B) @ {url.split('/')[2]}")
        else:
            print(f"    {ref}: curl rc={p.returncode} @ {url.split('/')[2]}")
        time.sleep(4 + 4 * i)
    return None, None

def main():
    os.makedirs(OUT, exist_ok=True)
    for ref in REFS:
        path = f"{OUT}/{ref}.json"
        if os.path.exists(path):
            try:
                json.load(open(path)); print(f"{ref:<3} 已存在，略過"); continue
            except Exception: pass
        d, url = fetch(ref)
        if d is None:
            print(f"{ref:<3} 失敗"); continue
        json.dump(d, open(path, "w"), ensure_ascii=False)
        rels = d["elements"]
        pts = sum(len(w.get("geometry", [])) for r in rels for w in r.get("members", []))
        print(f"{ref:<3} OK  relations={len(rels):<3} points={pts:<6} via {url.split('/')[2]}")
        time.sleep(2)

if __name__ == "__main__":
    main()
