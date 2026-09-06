#!/usr/bin/env python3
"""WGS84 -> TWD97/TM2 (EPSG:3826) -> Minecraft 方塊座標 (1 方塊 = 1 公尺)
原點: 台北車站。輸出 data/mc_stations.csv 與 data/mc_lines.json"""
import json, csv, glob, os, math
# pyproj 匯入時會讀 certifi 的 cacert.pem，被 sandbox 的 **/*.pem 規則擋下；
# 這裡只做本地投影不需連網，先把 CA bundle 指走並關閉 PROJ 網路。
os.environ.setdefault("CURL_CA_BUNDLE", "/dev/null")
os.environ.setdefault("PROJ_NETWORK", "OFF")
from pyproj import Transformer

TF = Transformer.from_crs("EPSG:4326", "EPSG:3826", always_xy=True)
WAY_TAGS = json.load(open("data/way_tags.json")) if os.path.exists("data/way_tags.json") else {}
ORIGIN_REF = "R10"        # 台北車站 (OSM: ref="R10;BL12", name:en="Taipei main station")

def proj(lon, lat):
    """回傳 TWD97 (E, N) 公尺"""
    return TF.transform(lon, lat)

def load_stations():
    d = json.load(open("data/stations.json"))
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
    """把 OSM relation 的 way 依端點接起來。

    OSM route relation 的成員順序不保證、方向也可能相反，直接串接會產生
    橫跨地圖的假直線。這裡貪婪地找端點相接的 way（必要時反轉），接不上
    的就另開一條 chain — 寧可留下缺口，也不要用直線硬連。
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
        raise SystemExit(f"找不到原點站 ref={ORIGIN_REF}；不可靜默退回質心，"
                         f"否則所有絕對座標都會偏移。請檢查 data/stations.json")
    oE, oN = org["E"], org["N"]
    # Minecraft: X = 東, Z = 南 (北方為 -Z)
    to_mc = lambda E, N: (round(E - oE), round(-(N - oN)))

    with open("data/mc_stations.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ref","name_zh","name_en","mc_x","mc_z","layer","lat","lon"])
        for s in sorted(stns, key=lambda s: (s["ref"] or "zz")):
            x, z = to_mc(s["E"], s["N"])
            w.writerow([s["ref"], s["name_zh"], s["name_en"], x, z, s["layer"], s["lat"], s["lon"]])

    lines = {}
    for path in sorted(glob.glob("data/lines/*.json")):
        ref = os.path.basename(path)[:-5]
        try: d = json.load(open(path))
        except Exception: continue
        variants = []
        for rel in d["elements"]:
            t = rel.get("tags", {})
            ways = []
            for m in rel.get("members", []):
                # 只要軌道 way，排除月台/停靠點成員
                if m.get("type") != "way":
                    continue
                role = m.get("role", "")
                if "platform" in role or "stop" in role:
                    continue
                wt = WAY_TAGS.get(str(m.get("ref")), {})
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
                    kinds=[p[2] for p in best],           # 每點的地下/高架/平面分類
                    chains=[[[p[0], p[1]] for p in c] for c in chains]))
        if variants: lines[ref] = variants

    json.dump(lines, open("data/mc_lines.json","w"), ensure_ascii=False)

    print(f"車站 {len(stns)} 座 -> data/mc_stations.csv")
    print(f"原點: {org['name_zh']} ({org['ref']})  TWD97 E={oE:.1f} N={oN:.1f}  -> MC (0,0)\n")
    tot = 0
    for ref, vs in lines.items():
        v = max(vs, key=lambda v: len(v["points"]))
        length = sum(math.dist(v["points"][i], v["points"][i+1]) for i in range(len(v["points"])-1))
        tot += length
        xs=[p[0] for p in v["points"]]; zs=[p[1] for p in v["points"]]
        k = v.get("kinds", [])
        pct = lambda w: 100.0 * sum(1 for x in k if x == w) / max(1, len(k))
        print(f"{ref:<3} {v['colour']:<9} 主線 {len(v['points']):>5} 點  {length/1000:>6.1f} km  "
              f"地下 {pct('tunnel'):>4.0f}%  高架 {pct('bridge'):>4.0f}%  平面 {pct('ground'):>4.0f}%")
    print(f"\n全網單向總長約 {tot/1000:.1f} km ({tot:,.0f} 方塊)")

if __name__ == "__main__":
    main()
