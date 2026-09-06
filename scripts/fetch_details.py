#!/usr/bin/env python3
"""抓取捷運車站細部資料 -> data/entrances.json、data/station_buildings.json、data/platform_levels.json

沿用 fetch_stations.py 的 BBOX、鏡像與重試流程。Overpass 原始回應會快取到
OVERPASS_CACHE 指定的暫存目錄，重跑時直接讀快取，加 --refresh 才重抓。
座標一律轉成 Minecraft 方塊座標，原點與 to_minecraft.py 相同
(台北車站 ref=R10 -> MC (0,0)，X = 東、Z = 南，1 方塊 = 1 公尺)。

出入口分兩段查:
  A. railway=subway_entrance / train_station_entrance (節點與 way)，
     以及 public_transport=stop_area 關聯底下掛的 entrance=* 節點；
     順便把 railway/public_transport=station 節點一起撈回來當「車站種子」。
  B. 全 BBOX 的 entrance=yes / entrance=main 節點 (約 2400 個，多半是一般
     建物大門)，再用種子在本地做半徑過濾。
原本想用 Overpass 的 node(around.stn:150) 一次做完，但整個大台北 BBOX 的
around 在三個鏡像上都跑不完 (>5 分鐘沒回應)，改成本地過濾既快又好檢查。
"""
import csv, json, math, os, re, subprocess, sys, tempfile, time

# pyproj 匯入時會讀 certifi 的 cacert.pem，被 sandbox 的 **/*.pem 規則擋下；
# 這裡只做本地投影不需連網，先把 CA bundle 指走並關閉 PROJ 網路。
os.environ.setdefault("CURL_CA_BUNDLE", "/dev/null")
os.environ.setdefault("PROJ_NETWORK", "OFF")
from pyproj import Transformer

MIRRORS = ["https://overpass.kumi.systems/api/interpreter",
           "https://overpass-api.de/api/interpreter",
           "https://overpass.private.coffee/api/interpreter"]
BBOX = "24.85,121.15,25.32,121.75"
ORIGIN_REF = "R10"                 # 台北車站 (OSM ref="R10;BL12")
CACHE = os.environ.get("OVERPASS_CACHE") or os.path.join(
    tempfile.gettempdir(), "mrt_overpass_cache")
# 上面為了 pyproj 把 CURL_CA_BUNDLE 指到 /dev/null，curl 繼承後會 TLS 失敗
# (curl: (77) error setting certificate verify locations)，所以呼叫 curl 前拿掉。
CURL_ENV = {k: v for k, v in os.environ.items() if k != "CURL_CA_BUNDLE"}
TF = Transformer.from_crs("EPSG:4326", "EPSG:3826", always_xy=True)
NEAR_M = 400          # 統計時判定「屬於某站」的半徑 (公尺 = 方塊)
GEN_NEAR_M = 150      # 一般 entrance=yes/main 要離車站多近才收
CHECK_STATIONS = ["台北車站", "忠孝復興", "民權西路", "東門", "中山", "西門", "南港展覽館"]

# ---------------------------------------------------------------- Overpass 查詢

Q_ENTRANCE_A = f"""[out:json][timeout:300];
(
  node["railway"="subway_entrance"]({BBOX});
  way["railway"="subway_entrance"]({BBOX});
  node["railway"="train_station_entrance"]({BBOX});
  way["railway"="train_station_entrance"]({BBOX});
)->.direct;
rel["public_transport"="stop_area"]({BBOX})->.sa;
node(r.sa)["entrance"]->.saent;
(
  node["railway"="station"]({BBOX});
  node["public_transport"="station"]({BBOX});
)->.stn;
(.direct; .saent; .stn;);
out geom;"""

Q_ENTRANCE_GEN = f"""[out:json][timeout:300];
(
  node["entrance"="yes"]({BBOX});
  node["entrance"="main"]({BBOX});
);
out body;"""

Q_BUILDING = f"""[out:json][timeout:600];
(
  way["building"="train_station"]({BBOX});
  rel["building"="train_station"]({BBOX});
  way["building"="transportation"]({BBOX});
  rel["building"="transportation"]({BBOX});
  way["building"]["public_transport"]({BBOX});
  rel["building"]["public_transport"]({BBOX});
  way["building"]["railway"="station"]({BBOX});
  rel["building"]["railway"="station"]({BBOX});
);
out geom;"""

Q_PLATFORM = f"""[out:json][timeout:600];
(
  way["railway"="platform"]({BBOX});
  rel["railway"="platform"]({BBOX});
  way["public_transport"="platform"]({BBOX});
  rel["public_transport"="platform"]({BBOX});
)->.pf;
(
  way.pf["level"];
  rel.pf["level"];
  way.pf["layer"];
  rel.pf["layer"];
);
out geom;"""


def fetch(name, q, tries=9):
    """打 Overpass 並快取；快取存在就直接讀，避免重跑時再打 API。"""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{name}.json")
    if os.path.exists(path) and "--refresh" not in sys.argv:
        try:
            d = json.load(open(path))
        except json.JSONDecodeError:
            print(f"{name:<14} 快取毀損，重抓")
        else:
            print(f"{name:<14} 使用快取 {len(d['elements']):>6} 個元素  {path}")
            return d
    for i in range(tries):
        url = MIRRORS[i % len(MIRRORS)]
        p = subprocess.run(["curl", "-sS", "--max-time", "500", "-X", "POST",
                            "--data-urlencode", f"data={q}", url],
                           capture_output=True, text=True, env=CURL_ENV)
        if p.returncode == 0 and p.stdout.strip().startswith("{"):
            try:
                d = json.loads(p.stdout)
            except json.JSONDecodeError:
                print(f"    {name}: 回應截斷/非 JSON ({len(p.stdout)}B) @ {url.split('/')[2]}")
            else:
                json.dump(d, open(path, "w"), ensure_ascii=False)
                print(f"{name:<14} 取得    {len(d['elements']):>6} 個元素  via {url.split('/')[2]}")
                return d
        else:
            print(f"    {name}: curl rc={p.returncode} @ {url.split('/')[2]} "
                  f"{(p.stderr or '').strip()[:80]}")
        time.sleep(4 + 4 * i)
    print(f"{name:<14} 失敗，這份資料會是空的")
    return None

# ---------------------------------------------------------------- 座標轉換

def origin():
    """與 to_minecraft.py 一致：ref=R10 的台北車站當 MC (0,0)。"""
    d = json.load(open("data/stations.json"))
    for e in d["elements"]:
        if ORIGIN_REF in (e.get("tags", {}).get("ref", "")).split(";"):
            return TF.transform(e["lon"], e["lat"])
    raise SystemExit("找不到原點站 ref=R10；請先執行 scripts/fetch_stations.py。"
                     "不可靜默改用別的原點，否則所有絕對座標都會偏移。")


def ring(geom, to_mc):
    """OSM out geom 的節點串 -> MC [[x,z],...]，順手去掉連續重複點。"""
    out = []
    for pt in geom or []:
        if not pt:
            continue
        x, z = to_mc(*TF.transform(pt["lon"], pt["lat"]))
        if not out or [x, z] != out[-1]:
            out.append([x, z])
    return out


def stitch(rings, tol=2):
    """把 relation 的成員 way 依端點接成環；接不上的自成一段，不硬拉直線。"""
    d2 = lambda a, b: (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
    t2 = tol * tol
    remaining = [list(r) for r in rings if len(r) >= 2]
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
                    remaining.pop(i)
                    joined = True
                    break
                if joined:
                    break
        chains.append(chain)
    return sorted(chains, key=len, reverse=True)


def centroid(pts):
    """封閉環用面積質心，開放線用平均點。"""
    if not pts:
        return None, None
    if len(pts) >= 4 and pts[0] == pts[-1]:
        a = cx = cz = 0.0
        for (x1, z1), (x2, z2) in zip(pts, pts[1:]):
            cr = x1 * z2 - x2 * z1
            a += cr
            cx += (x1 + x2) * cr
            cz += (z1 + z2) * cr
        if abs(a) > 1e-9:
            return round(cx / (3 * a)), round(cz / (3 * a))
    return (round(sum(p[0] for p in pts) / len(pts)),
            round(sum(p[1] for p in pts) / len(pts)))


def geometry_of(e, to_mc):
    """回傳 (外環列表, 內環列表)。way 只有一個外環；relation 先把成員接起來。"""
    if e["type"] == "way":
        r = ring(e.get("geometry"), to_mc)
        return ([r] if r else []), []
    outer, inner = [], []
    for m in e.get("members", []):
        if m.get("type") != "way":
            continue
        r = ring(m.get("geometry"), to_mc)
        if len(r) >= 2:
            (inner if m.get("role") == "inner" else outer).append(r)
    return stitch(outer), stitch(inner)


def names(t):
    return dict(name=t.get("name", ""), name_zh=t.get("name:zh", ""),
                name_en=t.get("name:en", ""))


def pick(t, keys):
    """只留有值的關鍵標籤，免得 JSON 塞一堆空字串。"""
    return {k: t[k] for k in keys if t.get(k)}

# ---------------------------------------------------------------- 出入口

ENT_KEYS = ("railway", "entrance", "level", "layer", "highway", "wheelchair",
            "elevator", "operator", "network", "description", "note", "ref:zh")

# 台北的出入口有不少只把編號寫在 name，沒有 ref (例如 name="Y11"、
# "1號出入口"、"捷運市政府站4號出口"、"出口 3 (聯合醫院忠孝院區)")。
# 這裡照下列樣式補出 ref，並用 ref_from_name 標記是推導出來的，不是原始標籤。
REF_PATTERNS = [
    re.compile(r"^([A-Z]{1,2}\d{1,2})(?![0-9])"),      # M6出口 台北凱薩飯店 / Y11
    re.compile(r"(\d{1,2})\s*號出入?口"),               # 1號出入口 / 4號出口
    re.compile(r"出入?口\s*(\d{1,2})(?![0-9])"),        # 捷運出入口2 / 出口 3
    re.compile(r"^([東西南北]\d門)$"),                    # 北1門
]


def ref_from_name(t):
    for key in ("name", "name:zh", "description"):
        v = (t.get(key) or "").strip()
        if not v:
            continue
        for pat in REF_PATTERNS:
            m = pat.search(v)
            if m:
                return m.group(1)
    return ""


def is_station_seed(t):
    return (t.get("railway") == "station" or t.get("public_transport") == "station") \
        and not t.get("entrance") and "entrance" not in (t.get("railway") or "")


def entrance_record(e, to_mc, source):
    t = e.get("tags", {}) or {}
    poly = None
    if e["type"] == "node":
        x, z = to_mc(*TF.transform(e["lon"], e["lat"]))
        lat, lon = e["lat"], e["lon"]
    else:
        outer, _ = geometry_of(e, to_mc)
        if not outer:
            return None
        poly = outer[0]
        x, z = centroid(poly)                     # way 取幾何中心
        g = [p for p in (e.get("geometry") or []) if p]
        lat = round(sum(p["lat"] for p in g) / len(g), 7) if g else None
        lon = round(sum(p["lon"] for p in g) / len(g), 7) if g else None
    rw = t.get("railway", "")
    kind = (rw if rw.endswith("entrance") else f"entrance={t.get('entrance', '')}")
    ref, derived = t.get("ref", ""), False
    if not ref:
        ref = ref_from_name(t)
        derived = bool(ref)
    rec = dict(id=e["id"], type=e["type"], kind=kind, source=source,
               ref=ref, ref_from_name=derived, **names(t),
               lat=lat, lon=lon, mc_x=x, mc_z=z, tags=pick(t, ENT_KEYS))
    if poly:
        rec["polygon"] = poly
    return rec


def build_entrances(da, dg, to_mc):
    """A 段全收；B 段 (一般大門) 只收離車站種子 GEN_NEAR_M 內的。"""
    seeds, out, seen = [], [], set()
    for e in (da["elements"] if da else []):
        t = e.get("tags", {}) or {}
        if is_station_seed(t):
            if e["type"] == "node":
                seeds.append(to_mc(*TF.transform(e["lon"], e["lat"])))
            continue
        # 有 railway=*_entrance 的是直接命中；只有 entrance=* 的來自 stop_area 關聯
        src = "railway_tag" if t.get("railway", "").endswith("entrance") else "stop_area"
        r = entrance_record(e, to_mc, src)
        if r:
            out.append(r)
            seen.add((r["type"], r["id"]))
    skipped = 0
    for e in (dg["elements"] if dg else []):
        if ("node", e["id"]) in seen:
            continue
        x, z = to_mc(*TF.transform(e["lon"], e["lat"]))
        if not any(math.dist((x, z), s) <= GEN_NEAR_M for s in seeds):
            skipped += 1
            continue
        r = entrance_record(e, to_mc, "near_station")
        if r:
            out.append(r)
            seen.add((r["type"], r["id"]))
    return out, len(seeds), skipped

# ---------------------------------------------------------------- 建物 / 月台

BLD_KEYS = ("building", "building:levels", "height", "min_height",
            "building:levels:underground", "building:min_level", "layer",
            "public_transport", "railway", "operator", "roof:shape", "roof:height")


def build_buildings(d, to_mc):
    out = []
    for e in d["elements"]:
        t = e.get("tags", {}) or {}
        outer, inner = geometry_of(e, to_mc)
        if not outer:
            continue
        poly = outer[0]
        cx, cz = centroid(poly)
        out.append(dict(id=e["id"], type=e["type"], **names(t),
                        mc_x=cx, mc_z=cz, tags=pick(t, BLD_KEYS),
                        polygon=poly, extra_outer=outer[1:], inner=inner))
    return out


PF_KEYS = ("railway", "public_transport", "level", "layer", "subway", "train",
           "light_rail", "network", "operator", "line", "route_ref", "colour",
           "covered", "surface", "width", "bus", "highway")


def build_platforms(d, to_mc):
    out = []
    for e in d["elements"]:
        t = e.get("tags", {}) or {}
        outer, _ = geometry_of(e, to_mc)
        if not outer:
            continue
        geom = outer[0]
        cx, cz = centroid(geom)
        out.append(dict(id=e["id"], type=e["type"], **names(t),
                        ref=t.get("ref", ""), level=t.get("level", ""),
                        layer=t.get("layer", ""),
                        lines=t.get("line") or t.get("route_ref") or "",
                        mc_x=cx, mc_z=cz, geometry=geom,
                        closed=len(geom) >= 4 and geom[0] == geom[-1],
                        tags=pick(t, PF_KEYS)))
    return out

# ---------------------------------------------------------------- 主流程

def load_mc_stations():
    """讀既有的 data/mc_stations.csv，用來做「離哪一站最近」的歸屬判斷。"""
    with open("data/mc_stations.csv") as f:
        return [dict(ref=r["ref"], name=r["name_zh"],
                     x=int(r["mc_x"]), z=int(r["mc_z"]))
                for r in csv.DictReader(f)]


def attach_station(items, stns):
    """標上最近的捷運站 (超過 NEAR_M 就留空，但仍保留距離)。

    月台在 OSM 這一帶完全沒有 line / route_ref 標籤，所以歸屬只能靠距離推，
    station_ref 就是可用來對回路線代號的欄位。"""
    for it in items:
        best, bd = None, None
        for s in stns:
            d = math.dist((it["mc_x"], it["mc_z"]), (s["x"], s["z"]))
            if bd is None or d < bd:
                best, bd = s, d
        it["station"] = best["name"] if best and bd <= NEAR_M else ""
        it["station_ref"] = best["ref"] if best and bd <= NEAR_M else ""
        it["station_dist"] = round(bd) if bd is not None else None


def dump(path, kind, items, extra=None):
    doc = dict(kind=kind, bbox=BBOX,
               origin=f"台北車站 ref={ORIGIN_REF} -> MC (0,0)",
               crs="WGS84 -> EPSG:3826 (TWD97/TM2) -> MC，X=東 Z=南，1 方塊 = 1 公尺",
               count=len(items), items=items)
    if extra:
        doc.update(extra)
    json.dump(doc, open(path, "w"), ensure_ascii=False, indent=1)
    print(f"  寫出 {path}  ({len(items)} 筆)")


def bad_coords(items, limit=35000):
    return [i for i in items
            if i.get("mc_x") is None or i.get("mc_z") is None
            or abs(i["mc_x"]) > limit or abs(i["mc_z"]) > limit]


def main():
    oE, oN = origin()
    to_mc = lambda E, N: (round(E - oE), round(-(N - oN)))
    print(f"原點 台北車站 (ref={ORIGIN_REF})  TWD97 E={oE:.1f} N={oN:.1f} -> MC (0,0)")
    print(f"快取目錄 {CACHE}\n")

    da = fetch("entrances_a", Q_ENTRANCE_A)
    dg = fetch("entrances_gen", Q_ENTRANCE_GEN)
    db = fetch("buildings", Q_BUILDING)
    dp = fetch("platforms", Q_PLATFORM)
    print()

    stns = load_mc_stations()
    ents, n_seed, n_skip = build_entrances(da, dg, to_mc)
    blds = build_buildings(db, to_mc) if db else []
    pfs = build_platforms(dp, to_mc) if dp else []
    attach_station(ents, stns)
    attach_station(blds, stns)
    attach_station(pfs, stns)

    os.makedirs("data", exist_ok=True)
    dump("data/entrances.json", "subway/train station entrances", ents,
         dict(near_radius_m=NEAR_M, generic_entrance_radius_m=GEN_NEAR_M))
    dump("data/station_buildings.json", "station building footprints", blds)
    dump("data/platform_levels.json", "platforms with level/layer", pfs)

    # ---------------------------------------------------------- 中文摘要
    print("\n=== 摘要 ===")
    kinds, srcs = {}, {}
    for e in ents:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        srcs[e["source"]] = srcs.get(e["source"], 0) + 1
    print(f"出入口       {len(ents):>5} 個   " +
          "  ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    print(f"             來源: " + "  ".join(f"{k}={v}" for k, v in sorted(srcs.items()))
          + f"   (車站種子 {n_seed} 個，另有 {n_skip} 個一般大門離站太遠被剔除)")
    print(f"             有 ref: {sum(1 for e in ents if e['ref']):>3} 個 "
          f"(其中 {sum(1 for e in ents if e['ref_from_name'])} 個是從 name 推導)；"
          f"無 ref {sum(1 for e in ents if not e['ref'])} 個")
    print(f"車站建物     {len(blds):>5} 個   "
          f"way={sum(1 for b in blds if b['type'] == 'way')}  "
          f"relation={sum(1 for b in blds if b['type'] == 'relation')}  "
          f"有樓層數={sum(1 for b in blds if b['tags'].get('building:levels'))}  "
          f"有高度={sum(1 for b in blds if b['tags'].get('height'))}  "
          f"有地下樓層={sum(1 for b in blds if b['tags'].get('building:levels:underground'))}")
    print(f"月台(有層資訊){len(pfs):>4} 個   "
          f"有 level={sum(1 for p in pfs if p['level'])}  "
          f"有 layer={sum(1 for p in pfs if p['layer'])}  "
          f"鐵道月台={sum(1 for p in pfs if p['tags'].get('railway') == 'platform')}  "
          f"有 line/route_ref={sum(1 for p in pfs if p['lines'])}  "
          f"能對到 {NEAR_M}m 內車站={sum(1 for p in pfs if p['station'])}")

    print(f"\n各站 {NEAR_M} 公尺內的出入口數:")
    for nm in CHECK_STATIONS:
        pts = [(s["x"], s["z"]) for s in stns if s["name"] == nm]
        if not pts:
            print(f"  {nm:<6} 在 mc_stations.csv 找不到此站名")
            continue
        near = [e for e in ents
                if any(math.dist((e["mc_x"], e["mc_z"]), p) <= NEAR_M for p in pts)]
        rw = sum(1 for e in near if e["kind"].endswith("entrance"))
        print(f"  {nm:<6} {len(near):>3} 個 (其中 railway 出入口 {rw:>2} 個)   "
              f"站點 {len(pts)} 處: " + ", ".join(f"({x},{z})" for x, z in pts))

    # ------------------------------------- 台北車站逐筆列出 (合理性檢查)
    tp = [(s["x"], s["z"]) for s in stns if s["name"] == "台北車站"]
    near = sorted((e for e in ents
                   if any(math.dist((e["mc_x"], e["mc_z"]), p) <= NEAR_M for p in tp)),
                  key=lambda e: (e["ref"] or "~", e["id"]))
    print(f"\n=== 台北車站 (MC 0,0) {NEAR_M} 公尺內出入口逐筆 ({len(near)} 個) ===")
    print(f"  {'ref':<6}{'mc_x':>7}{'mc_z':>7}{'距離':>7}  {'種類':<24}{'名稱'}")
    for e in near:
        d = min(math.dist((e["mc_x"], e["mc_z"]), p) for p in tp)
        nm = e["name"] or e["name_zh"] or e["name_en"] or e["tags"].get("description", "")
        print(f"  {(e['ref'] or '-'):<6}{e['mc_x']:>7}{e['mc_z']:>7}{d:>7.0f}  "
              f"{e['kind']:<24}{nm}")
    rw_near = [e for e in near if e["kind"].endswith("entrance")]
    if len(rw_near) < 20:
        print(f"  ※ 台北車站實際有 20 個以上編號出口 (M1-M8、Z1-Z10、K 區、Y 區等)，"
              f"這裡只找到 {len(rw_near)} 個 railway 出入口 —— OSM 資料不完整，"
              f"不要當成全集使用。")

    # ------------------------------------- 座標範圍檢查
    bad = bad_coords(ents) + bad_coords(blds) + bad_coords(pfs)
    allx = [i["mc_x"] for i in ents + blds + pfs if i.get("mc_x") is not None]
    allz = [i["mc_z"] for i in ents + blds + pfs if i.get("mc_z") is not None]
    if bad:
        print(f"\n※ 有 {len(bad)} 筆座標缺值或超出 ±35000，需檢查: "
              + ", ".join(f"{b['type']}/{b['id']}" for b in bad[:5]))
    else:
        print(f"\n座標範圍檢查通過: X {min(allx)}~{max(allx)}, Z {min(allz)}~{max(allz)}"
              f" (皆在 ±35000 內)")


if __name__ == "__main__":
    main()
