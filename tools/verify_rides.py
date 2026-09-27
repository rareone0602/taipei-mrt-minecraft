#!/usr/bin/env python3
"""從存檔讀回每一面搭車告示牌，檢查點了之後真的會到一個站得住的月台 —— 不相信生成器的自述。

搭車告示牌怎麼找：讀回告示牌的點擊動作。`function mrt:ride/<甲>_<乙>` 是從甲坐到乙，
`function mrt:turn/<甲>_<p|m>` 是終點站換到對面月台。牌子是生成器立的沒錯，但下面
每一件事都是從磁碟上的方塊、告示牌與資料包檔案獨立重建出來驗的：

  1. 牌子在月台門那一排：牌子那一格是立牌、上面是月台門的玻璃、底下踩得住
  2. 牌子正前方兩格站得住（domain/walk 的規則），而且那裡是月台（附近有黃色警示帶）
  3. 牌上寫的跟指令對得上：中文牌「下一站 X」的 X 就是 ride 目的地的站名、
     英文牌的 Next 是那一站的英文名（容許縮寫與截短）；牌子離它說的那一站不遠；
     終點側的牌寫「本站終點／Terminus」
  4. 存檔裡有資料包（<存檔>/datapacks/<DATAPACK_NAME>/）的話：每個指令的函式檔都在、
     裡面剛好一行 `tp @s x y z yaw pitch`、傳送目的地站得住、在月台上、
     面前 2～3 格有一面搭車（或終點）告示牌而且人正對著它 —— 坐到乙就要站在乙的牌子前面
     （斜的線形上站位取整後可能只離牌子一個斜格 1.41 m，也算；目的地在 --bbox 沒產生的
     區塊裡的另外列出來，不算失敗）
  5. 每一站數一數：一座站體每條線兩側各三面，少了會列出來；範圍內的車站一面都沒有就算失敗

另外順便點名：路線圖售票機（點了開對話框的牌子）的對話框 id、資料包裡有沒有那個對話框。

用法:
    ./.venv/bin/python tools/verify_rides.py <存檔>
    ./.venv/bin/python tools/verify_rides.py <存檔> --stations 台北車站 西門
    ./.venv/bin/python tools/verify_rides.py <存檔> --bbox X0 Z0 X1 Z1
"""
import argparse
import collections
import csv
import glob
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt import config
from mrt.domain import walk
from mrt.infrastructure.savereader import read_sign_entities, read_volume

PLAT_EDGE = "minecraft:yellow_concrete"
CMD_RE = re.compile(r"^function ([a-z0-9_.-]+):(ride|turn)/([a-z0-9_]+)$")
TP_RE = re.compile(r"(?:^|\s)tp @s (\S+) (\S+) (\S+) (\S+) (\S+)")
MAX_FROM_STATION = 600      # 牌子離它自稱的那一站（mc_stations.csv 的站點）最遠幾公尺
PER_STATION = 6             # 一座站體一條線：兩側各三面


def fn_code(code):
    """站號 -> 函式路徑用的小寫代號（跟資料包的命名同一套：只留 a-z0-9_）。"""
    return "".join(ch for ch in code.lower() if ch.isalnum() or ch == "_")


def load_stations():
    """{小寫站號: dict(code, zh, en, x, z)}（轉乘站每條線的站號各一筆）。"""
    out = {}
    with open(config.MC_STATIONS_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            zh = r["name_zh"] or r["name_en"]
            en = r["name_en"]
            if "(" in en:
                en = en[:en.index("(")].rstrip()
            for code in r["ref"].split(";"):
                code = code.strip()
                if code:
                    out[fn_code(code)] = dict(code=code, zh=zh, en=en,
                                              x=int(r["mc_x"]), z=int(r["mc_z"]))
    return out


def save_extent(save):
    rdir = config.region_dir(save)
    xs, zs = [], []
    for p in glob.glob(os.path.join(rdir, "r.*.mca")):
        m = re.match(r"r\.(-?\d+)\.(-?\d+)\.mca$", os.path.basename(p))
        if m:
            xs.append(int(m.group(1))); zs.append(int(m.group(2)))
    if not xs:
        return None
    return (min(xs) * 512, min(zs) * 512, max(xs) * 512 + 511, max(zs) * 512 + 511)


def region_exists(save, x, z):
    return os.path.exists(os.path.join(config.region_dir(save), f"r.{x >> 9}.{z >> 9}.mca"))


def chunk_exists(save, x, z):
    """(x, z) 所在的區塊有沒有寫進存檔（region 檔開頭的位移表不是 0）。

    --bbox 只產生一部分 region：坐到範圍外的鄰站，目的地根本沒蓋，讀回來是空氣 ——
    那不是資料包錯了，是那一站不在這個存檔裡，要分開講。"""
    p = os.path.join(config.region_dir(save), f"r.{x >> 9}.{z >> 9}.mca")
    if not os.path.exists(p):
        return False
    i = ((x >> 4) & 31) + ((z >> 4) & 31) * 32
    with open(p, "rb") as f:
        f.seek(i * 4)
        head = f.read(4)
    return len(head) == 4 and int.from_bytes(head[:3], "big") != 0


# ---------- 文字 ----------

def _words(s):
    return [w for w in re.split(r"[\s/\-]+", s) if w]


def en_match(text, name):
    """牌上的英文（可能縮寫、截短）是不是這個站名。

    每個字依序對到站名裡的某個字（可以跳過站名的字，縮寫常常拿掉 Taipei 之類）：
    全大寫的是字首縮寫（WTC、CKS）或原字；其餘可以是縮寫（Exh. -> Exhibition、
    Bldg -> Building：字母依序出現在原字裡、第一個字母相同）；最後一個字後面有
    「…」可以只是字首。
    """
    t = text.strip()
    cut = t.endswith("…")
    t = t.rstrip("…").strip()
    if not t:
        return False
    if t.lower() == name.lower():
        return True
    words = [w.lower().rstrip(".") for w in _words(name)]   # 站名自己也有縮寫（Minquan W. Rd.）
    words = [w for w in words if w]
    toks = _words(t)
    wi = 0
    matched = 0
    for k, tok in enumerate(toks):
        last = k == len(toks) - 1
        if tok == "&":
            tok = "and"
        low = tok.lower().rstrip(".")
        found = False
        while wi < len(words):
            w = words[wi]
            if low == w or (last and cut and w.startswith(low)):
                found = True; wi += 1; break
            if tok.isupper() and len(tok) >= 2 and "".join(x[0] for x in words[wi:wi + len(tok)]) == low:
                found = True; wi += len(tok); break
            # 縮寫（Exh.、Ctr.、Bldg、Pk）：字母依序出現在原字裡、第一個字母相同
            if len(low) >= 2 and low[0] == w[0] and _subseq(low, w) or (low and low == w[:len(low)] and tok.endswith(".")):
                found = True; wi += 1; break
            wi += 1
        if not found:
            return False
        matched += 1
    return matched > 0


def _subseq(a, b):
    it = iter(b)
    return all(ch in it for ch in a)


def sign_next(front):
    """牌上寫的下一站：("zh", 站名) / ("en", 英文) / (None, None)。"""
    for i, ln in enumerate(front):
        s = ln.strip()
        if s.startswith("下一站"):
            return "zh", s[len("下一站"):].strip()
        if s.startswith("下站"):
            return "zh", s[len("下站"):].strip()
        if s.startswith("Next:"):
            return "en", s[len("Next:"):].strip()
        if s == "Next station" and i + 1 < len(front):
            return "en", front[i + 1].strip()
    return None, None


def zh_match(text, name):
    t = text.strip()
    if t.endswith("…"):
        return name.startswith(t.rstrip("…"))
    return t == name


# ---------- 方塊 ----------

class Blocks:
    """幾塊讀回來的立體範圍，依序查。範圍外一律當空氣（呼叫端先保證讀過）。"""

    def __init__(self):
        self.vols = []

    def add(self, vol):
        self.vols.append(vol)

    def covers(self, x, y, z):
        return any(v.x0 <= x <= v.x1 and v.y0 <= y <= v.y1 and v.z0 <= z <= v.z1
                   for v in self.vols)

    def get(self, x, y, z):
        for v in self.vols:
            if v.x0 <= x <= v.x1 and v.y0 <= y <= v.y1 and v.z0 <= z <= v.z1:
                return v.get(x, y, z)
        return "minecraft:air"


def read_clusters(save, pts, blocks, grid=160, pad=8, below=4, above=6):
    """把要查的點依 grid 公尺分團，每團讀一塊立體範圍。"""
    groups = collections.defaultdict(list)
    for x, y, z in pts:
        if not blocks.covers(x, y, z):
            groups[(x // grid, z // grid)].append((x, y, z))
    for g in groups.values():
        xs = [p[0] for p in g]; ys = [p[1] for p in g]; zs = [p[2] for p in g]
        blocks.add(read_volume(save, min(xs) - pad, min(ys) - below, min(zs) - pad,
                               max(xs) + pad, max(ys) + above, max(zs) + pad, verbose=False))


def rotation_of(block):
    m = re.search(r"rotation=(\d+)", block)
    return int(m.group(1)) if m else None


def facing_vec(rot):
    """立牌 rotation（0 = 朝南、4 = 朝西…）-> 牌面朝向的單位向量 (dx, dz)。"""
    yaw = math.radians(rot * 22.5)
    return -math.sin(yaw), math.cos(yaw)


def yaw_vec(yaw_deg):
    yaw = math.radians(yaw_deg)
    return -math.sin(yaw), math.cos(yaw)


def near_yellow(get, x, y, z, r=2):
    """站位附近（腳下那一層）有沒有月台邊的黃色警示帶。"""
    return any(get(x + dx, y - 1, z + dz) == PLAT_EDGE
               for dx in range(-r, r + 1) for dz in range(-r, r + 1))


def stand_in_front(get, sx, sy, sz, f):
    """牌子正前方兩格左右站得住的格子（最接近 2 格的那一個）；沒有就 None。"""
    best = None
    for dx in range(-3, 4):
        for dz in range(-3, 4):
            d = math.hypot(dx, dz)
            if not (1.3 <= d <= 2.95):
                continue
            if (dx * f[0] + dz * f[1]) / d < 0.7:
                continue
            c = (sx + dx, sy, sz + dz)
            if walk.standable(get, *c):
                score = abs(d - 2.0) + 0.5 * (1 - (dx * f[0] + dz * f[1]) / d)
                if best is None or score < best[0]:
                    best = (score, c)
    return best[1] if best else None


# ---------- 資料包 ----------

def function_dir(save):
    root = os.path.join(save, "datapacks", config.DATAPACK_NAME, "data", config.DATAPACK_NS)
    for sub in ("function", "functions"):
        d = os.path.join(root, sub)
        if os.path.isdir(d):
            return d
    return None


def read_tp(path):
    """函式檔裡的 tp：[(x, y, z, yaw, pitch)]（約定是剛好一行）。"""
    out = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.split("#", 1)[0] if ln.lstrip().startswith("#") else ln
            for m in TP_RE.finditer(ln):
                try:
                    out.append(tuple(float(v) for v in m.groups()))
                except ValueError:
                    out.append(None)
    return out


# ---------- 主程式 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save", nargs="?", default=config.DEFAULT_SAVE)
    ap.add_argument("--stations", nargs="*")
    ap.add_argument("--bbox", nargs=4, type=int, metavar=("X0", "Z0", "X1", "Z1"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    if not os.path.isdir(a.save):
        print(f"找不到存檔 {a.save}")
        return 1
    stn = load_stations()
    by_name = collections.defaultdict(list)
    for c, s in stn.items():
        by_name[s["zh"]].append(c)

    if a.bbox:
        box = tuple(a.bbox)
    elif a.stations:
        pts = [(stn[c]["x"], stn[c]["z"]) for n in a.stations for c in by_name.get(n, ())]
        if not pts:
            print("mc_stations.csv 裡沒有這些車站"); return 1
        box = (min(p[0] for p in pts) - 500, min(p[1] for p in pts) - 500,
               max(p[0] for p in pts) + 500, max(p[1] for p in pts) + 500)
    else:
        box = save_extent(a.save)
        if box is None:
            print("存檔裡沒有 region 檔"); return 1

    print(f"存檔 {a.save}\n讀取範圍 x {box[0]}..{box[2]}  z {box[1]}..{box[3]} 的告示牌 …")
    signs = read_sign_entities(a.save, *box)
    rides, maps, bad_exit = [], [], []
    for s in signs:
        click = s["click"] or {}
        cmd = click.get("command", "")
        m = CMD_RE.match(cmd) if click.get("action") == "run_command" else None
        if m and m.group(1) == config.DATAPACK_NS:
            kind, ident = m.group(2), m.group(3)
            parts = ident.split("_")
            if kind == "ride" and len(parts) == 2:
                s.update(kind="ride", ident=f"ride/{ident}", frm=parts[0], to=parts[1])
            elif kind == "turn" and len(parts) == 2 and parts[1] in ("p", "m"):
                s.update(kind="turn", ident=f"turn/{ident}", frm=parts[0], to=None)
            else:
                s.update(kind="bad", ident=ident, frm=None, to=None)
            rides.append(s)
        elif click.get("action") == "show_dialog":
            maps.append(s)
        if s["front"] and s["front"][0].startswith("出口") and click:
            bad_exit.append(s)
    if a.stations:
        want = {c for n in a.stations for c in by_name.get(n, ())}
        rides = [s for s in rides if s.get("frm") in want]
    print(f"告示牌 {len(signs):,} 面，其中搭車告示牌 {sum(1 for s in rides if s['kind'] == 'ride')} 面、"
          f"終點換月台 {sum(1 for s in rides if s['kind'] == 'turn')} 面、路線圖售票機 {len(maps)} 台")

    # ---- 資料包：先把目的地讀出來，一起讀方塊 ----
    fdir = function_dir(a.save)
    targets = {}                            # 函式 id -> (x, y, z, yaw, pitch) 或錯誤訊息
    if fdir is None:
        print(f"（存檔裡沒有資料包 datapacks/{config.DATAPACK_NAME}/，只驗牌子與站位，不驗傳送目的地）")
    else:
        for ident in sorted({s["ident"] for s in rides if s["kind"] in ("ride", "turn")}):
            p = os.path.join(fdir, ident + ".mcfunction")
            if not os.path.exists(p):
                targets[ident] = "函式檔不存在"
                continue
            tps = read_tp(p)
            if len(tps) != 1 or tps[0] is None:
                targets[ident] = f"應該剛好一行 tp @s x y z yaw pitch，實際 {len(tps)} 行"
                continue
            targets[ident] = tps[0]
        print(f"資料包 {fdir}：{len(targets)} 個函式")

    blocks = Blocks()
    pts = [(s["x"], s["y"], s["z"]) for s in rides]
    tcells = {k: (math.floor(v[0]), math.floor(v[1]), math.floor(v[2]))
              for k, v in targets.items() if isinstance(v, tuple)}
    read_clusters(a.save, pts + list(tcells.values()), blocks)
    get = blocks.get

    # 目的地附近的牌子：範圍外的另外讀
    sign_at = {(s["x"], s["y"], s["z"]): s for s in rides}
    extra = [c for c in tcells.values()
             if not (box[0] <= c[0] <= box[2] and box[1] <= c[2] <= box[3])]
    for c in extra:
        for s in read_sign_entities(a.save, c[0] - 4, c[2] - 4, c[0] + 4, c[2] + 4):
            m = CMD_RE.match((s["click"] or {}).get("command", ""))
            if m:
                parts = m.group(3).split("_")
                s.update(kind=m.group(2), ident=f"{m.group(2)}/{m.group(3)}", frm=parts[0])
                sign_at.setdefault((s["x"], s["y"], s["z"]), s)

    # ---- 逐面驗 ----
    problems = collections.defaultdict(list)       # 站號 -> [訊息]
    count = collections.Counter()
    outside = set()                                # 目的地不在這個存檔產生的範圍裡
    for s in rides:
        x, y, z = s["x"], s["y"], s["z"]
        code = s.get("frm")
        tag = f"{' / '.join(t for t in s['front'][:2] if t)}（{x},{y},{z}）"
        if s["kind"] == "bad":
            problems[code or "?"].append(f"{tag}: 看不懂的指令 {s['ident']}")
            continue
        count[(code, s["kind"])] += 1
        me = stn.get(code)
        if me is None:
            problems[code].append(f"{tag}: 站號 {code} 不在 mc_stations.csv 裡")
        elif math.hypot(me["x"] - x, me["z"] - z) > MAX_FROM_STATION:
            problems[code].append(f"{tag}: 離 {me['zh']} 的站點 {math.hypot(me['x'] - x, me['z'] - z):.0f} m，"
                                  f"不像是那一站的牌子")
        blk = get(x, y, z)
        rot = rotation_of(blk)
        if "_sign" not in blk or rot is None:
            problems[code].append(f"{tag}: 那一格不是立牌（{blk}）")
            continue
        above, below = get(x, y + 1, z), get(x, y - 1, z)
        if "glass_pane" not in above:
            problems[code].append(f"{tag}: 不在月台門那一排（上面是 {above}，不是月台門玻璃）")
        if not walk.is_support(below):
            problems[code].append(f"{tag}: 底下踩不住（{below}）")
        f = facing_vec(rot)
        st = stand_in_front(get, x, y, z, f)
        if st is None:
            problems[code].append(f"{tag}: 牌子正前方兩格站不住")
        elif not near_yellow(get, *st):
            problems[code].append(f"{tag}: 站位 {st} 附近沒有月台警示帶，不像在月台上")
        # 文字對不對得上指令
        if s["kind"] == "ride":
            to = stn.get(s["to"])
            lang, nxt = sign_next(s["front"])
            if to is None:
                problems[code].append(f"{tag}: 目的地站號 {s['to']} 不在 mc_stations.csv 裡")
            elif lang is None:
                problems[code].append(f"{tag}: 牌上沒寫下一站")
            elif lang == "zh" and not zh_match(nxt, to["zh"]):
                problems[code].append(f"{tag}: 牌上寫下一站「{nxt}」，指令卻坐到 {to['zh']}（{s['ident']}）")
            elif lang == "en" and not en_match(nxt, to["en"]):
                problems[code].append(f"{tag}: 牌上寫 Next「{nxt}」，指令卻坐到 {to['en']}（{s['ident']}）")
            elif lang == "zh" and me is not None and not any(me["zh"] in t for t in s["front"]):
                problems[code].append(f"{tag}: 中文牌上沒寫本站 {me['zh']}")
        else:
            if not ("本站終點" in s["front"][0] or "Terminus" in s["front"][0]):
                problems[code].append(f"{tag}: 終點換月台的牌子沒寫「本站終點／Terminus」")
        # 資料包：目的地
        if fdir is not None:
            t = targets.get(s["ident"])
            if not isinstance(t, tuple):
                problems[code].append(f"{tag}: {s['ident']}：{t}")
                continue
            tx, ty, tz, yaw, _ = t
            c = tcells[s["ident"]]
            where = f"{s['ident']} -> ({tx:g},{ty:g},{tz:g})"
            if not chunk_exists(a.save, c[0], c[2]):
                outside.add(s["ident"])
                continue
            if abs(tx - c[0] - 0.5) > 1e-6 or abs(tz - c[2] - 0.5) > 1e-6:
                problems[code].append(f"{tag}: {where} 不在方塊正中央（x/z 應該是 .5）")
            if not walk.standable(get, *c):
                problems[code].append(f"{tag}: {where} 站不住（腳 {get(*c)}，腳下 {get(c[0], c[1] - 1, c[2])}）")
                continue
            if not near_yellow(get, *c):
                problems[code].append(f"{tag}: {where} 附近沒有月台警示帶")
            fv = yaw_vec(yaw)
            faced = None
            for (qx, qy, qz), q in sign_at.items():
                if qy != c[1]:
                    continue
                dx, dz = qx - c[0], qz - c[2]
                d = math.hypot(dx, dz)
                # 斜的線形上站位取整之後可能只離牌子一個斜格（1.41 m），也算面前
                if 1.3 <= d <= 3.5 and (dx * fv[0] + dz * fv[1]) / d >= 0.75:
                    faced = q
                    break
            if faced is None:
                problems[code].append(f"{tag}: {where} 面前 2～3 格沒有搭車告示牌（或沒有正對著）")
                continue
            arrive = s["to"] if s["kind"] == "ride" else code
            if faced.get("frm") != arrive:
                problems[code].append(f"{tag}: {where} 面對的是 {faced.get('ident')} 的牌子，"
                                      f"應該是 {arrive} 這一站的")
            elif s["kind"] == "turn" and faced.get("kind") != "ride":
                problems[code].append(f"{tag}: 換月台之後面對的還是終點側的牌子（{faced.get('ident')}）")

    # ---- 路線圖售票機 ----
    want_dialog = f"{config.DATAPACK_NS}:network"
    wrong = [s for s in maps if (s["click"] or {}).get("dialog") != want_dialog]
    for s in wrong:
        problems["路線圖"].append(f"（{s['x']},{s['y']},{s['z']}）對話框是 {(s['click'] or {}).get('dialog')}，"
                                f"不是 {want_dialog}")
    if fdir is not None and maps:
        dlg = os.path.join(os.path.dirname(fdir), "dialog", "network.json")
        if not os.path.exists(dlg):
            problems["路線圖"].append(f"資料包裡沒有 {want_dialog} 對話框（{dlg}）")
    for s in bad_exit:
        problems["出口牌"].append(f"（{s['x']},{s['y']},{s['z']}）第一行是「{s['front'][0]}」卻帶點擊動作")

    # ---- 每一站 ----
    codes = sorted({s["frm"] for s in rides if s.get("frm")} | set(problems) - {"路線圖", "出口牌"},
                   key=lambda c: (re.sub(r"\d.*", "", c), int(re.sub(r"\D", "", c) or 0), c))
    in_box = [c for c, s in stn.items()
              if box[0] <= s["x"] <= box[2] and box[1] <= s["z"] <= box[3]
              and region_exists(a.save, s["x"], s["z"])
              and (not a.stations or s["zh"] in a.stations)]
    missing = sorted(c for c in in_box if c not in codes)
    print()
    few = []
    for c in codes:
        me = stn.get(c, dict(zh="?", code=c))
        nr, nt = count[(c, "ride")], count[(c, "turn")]
        flag = "   <- 有問題" if problems.get(c) else ""
        note = ""
        if nr + nt < PER_STATION:
            note = f"  （少於 {PER_STATION} 面）"
            few.append(c)
        print(f"  {me['code']:<6} {me['zh']:<8} 搭車 {nr:>2}  終點 {nt:>2}{note}{flag}")
        for p in problems.get(c, ())[:8 if not a.verbose else None]:
            print(f"      {p}")
        if not a.verbose and len(problems.get(c, ())) > 8:
            print(f"      …另外 {len(problems[c]) - 8} 則（-v 看全部）")
    for k in ("路線圖", "出口牌"):
        for p in problems.get(k, ()):
            print(f"  {k}: {p}")
    for c in missing:
        print(f"  {stn[c]['code']:<6} {stn[c]['zh']:<8} 一面搭車告示牌都沒有   <- 有問題")

    if outside:
        print(f"  （{len(outside)} 個函式的目的地在這個存檔沒產生的區塊裡，沒驗：{', '.join(sorted(outside)[:8])}"
              f"{' …' if len(outside) > 8 else ''}）")
    n_bad = sum(len(v) for v in problems.values())
    print(f"\n合計 {len(codes)} 個站號、{len(rides)} 面搭車／終點告示牌；"
          f"問題 {n_bad} 則；範圍內沒有牌子的車站 {len(missing)} 座；少於 {PER_STATION} 面的 {len(few)} 個站號")
    if n_bad or missing:
        return 1
    print("全部通過：每一面搭車告示牌都在月台門那一排、前面站得住、寫的跟點了會去的地方一致"
          + ("，資料包的傳送目的地也都站在下一站的牌子前面" if fdir else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
