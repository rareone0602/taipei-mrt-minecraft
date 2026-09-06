"""從已產生的存檔切剖面，用 ASCII 檢查車站／隧道結構是否正確。

用法:
  python tools/slice_world.py 台北車站            # 垂直橫剖面（垂直於路線）
  python tools/slice_world.py 台北車站 --long     # 縱剖面（沿路線）
  python tools/slice_world.py --xz 0 0 --dir 1 0
"""
import io, os, re, sys, glob, json, csv, math, zlib, argparse
import numpy as np, nbtlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mrt import config

SAVE = config.INSTALLED_SAVE
RDIR = config.region_dir(SAVE)

GLYPH = [
    ("air",                 "."),
    ("sea_lantern",         "*"),
    ("glass_pane",          "|"),
    ("light_gray_stained",  "|"),
    ("iron_bars",           "#"),
    ("redstone_block",      "R"),
    ("smooth_sandstone",    "B"),
    ("deepslate_tiles",     "T"),
    ("polished_deepslate",  "T"),
    ("lime_concrete",       "L"),
    ("gravel",              "="),
    ("deepslate_bricks",    "D"),
    ("polished_diorite",    "P"),
    ("yellow_concrete",     "Y"),
    ("light_gray_concrete", "C"),
    ("gray_concrete",       "W"),
    ("smooth_stone_slab",   "_"),
    ("smooth_stone",        "S"),
    ("polished_andesite",   "A"),
    ("grass_block",         "g"),
    ("dirt",                "d"),
    ("stone",               "s"),
    ("bedrock",             "b"),
    ("sign",                "!"),
    ("rail",                "r"),
    ("bricks",              "T"),   # 必須排在 deepslate_bricks 之後
    ("white_concrete",      "w"),
    ("black_concrete",      "k"),
]

def glyph(name):
    if name is None:
        return " "
    n = name.split("[")[0].replace("minecraft:", "")
    for key, g in GLYPH:
        if key in n:
            return g
    return "?"

def unpack(data, bits, n=4096):
    per = 64 // bits
    out = np.zeros(n, dtype=np.int64)
    arr = np.asarray(data, dtype=np.int64).view(np.uint64)
    mask = np.uint64((1 << bits) - 1)
    for slot in range(per):
        vals = (arr >> np.uint64(slot * bits)) & mask
        tgt = np.arange(slot, n, per)
        out[tgt] = vals[:len(tgt)]
    return out

class Reader:
    def __init__(self, rdir=RDIR):
        self.rdir = rdir
        self.regions = {}
        self.chunks = {}

    def _region(self, rx, rz):
        if (rx, rz) not in self.regions:
            p = os.path.join(self.rdir, f"r.{rx}.{rz}.mca")
            self.regions[(rx, rz)] = open(p, "rb").read() if os.path.exists(p) else None
        return self.regions[(rx, rz)]

    def _chunk(self, cx, cz):
        if (cx, cz) in self.chunks:
            return self.chunks[(cx, cz)]
        raw = self._region(cx >> 5, cz >> 5)
        sec = None
        if raw and len(raw) >= 8192:
            i = (cz & 31) * 32 + (cx & 31)
            off = int.from_bytes(raw[i*4:i*4+3], "big")
            if off:
                q = off * 4096
                ln = int.from_bytes(raw[q:q+4], "big")
                comp = raw[q+4]
                blob = raw[q+5:q+4+ln]
                data = zlib.decompress(blob) if comp == 2 else blob
                root = nbtlib.File.parse(io.BytesIO(data))
                root = root[''] if '' in root else root
                sec = {}
                for s in root["sections"]:
                    bs = s.get("block_states")
                    if bs is None:
                        continue
                    pal = [str(b["Name"]) for b in bs["palette"]]
                    if len(pal) == 1:
                        idx = np.zeros(4096, dtype=np.int64)
                    else:
                        bits = max(4, (len(pal) - 1).bit_length())
                        idx = unpack([int(v) for v in bs["data"]], bits)
                    sec[int(s["Y"])] = (pal, idx)
        self.chunks[(cx, cz)] = sec
        return sec

    def block(self, x, y, z):
        sec = self._chunk(x >> 4, z >> 4)
        if sec is None:
            return None
        s = sec.get(y >> 4)
        if s is None:
            return "minecraft:air"
        pal, idx = s
        return pal[idx[(y & 15) * 256 + (z & 15) * 16 + (x & 15)]]

def load_station(name):
    with open(config.MC_STATIONS_CSV) as f:
        rows = [r for r in csv.DictReader(f)]
    hit = [r for r in rows if name in (r.get("name_zh") or r.get("name") or "")]
    if not hit:
        keys = list(rows[0].keys())
        raise SystemExit(f"找不到車站 {name}；欄位={keys}")
    r = hit[0]
    return int(r["mc_x"]), int(r["mc_z"]), r

def line_dir(x, z):
    """從 mc_lines.json 找最近的線段方向"""
    lines = json.load(open(config.MC_LINES_JSON))
    best, bd = (1.0, 0.0), 1e18
    for ref, variants in lines.items():
        for v in variants:
            pts = v["points"]
            for i in range(len(pts) - 1):
                (ax, az), (bx, bz) = pts[i], pts[i+1]
                d = (ax - x) ** 2 + (az - z) ** 2
                if d < bd:
                    bd = d
                    L = math.hypot(bx - ax, bz - az) or 1.0
                    best = ((bx - ax) / L, (bz - az) / L)
    return best, math.sqrt(bd)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("station", nargs="?")
    ap.add_argument("--xz", nargs=2, type=int)
    ap.add_argument("--dir", nargs=2, type=float)
    ap.add_argument("--long", action="store_true")
    ap.add_argument("--half", type=int, default=22)
    ap.add_argument("--ylo", type=int)
    ap.add_argument("--yhi", type=int)
    ap.add_argument("--save", help="改讀其他存檔（測試用）")
    a = ap.parse_args()

    if a.station:
        x, z, row = load_station(a.station)
        print(f"# {a.station}  MC({x},{z})  {row}")
    else:
        x, z = a.xz
    if a.dir:
        ux, uz = a.dir
        L = math.hypot(ux, uz); ux, uz = ux/L, uz/L
        dist = 0
    else:
        (ux, uz), dist = line_dir(x, z)
        print(f"# 路線方向 ({ux:+.2f},{uz:+.2f})  站點離線 {dist:.1f} m")

    if a.long:
        dx, dz = ux, uz               # 沿線
    else:
        dx, dz = -uz, ux              # 垂直於線

    rd = Reader(config.region_dir(a.save) if a.save else RDIR)
    # 先掃出這條剖面上有東西的 y 範圍
    cols = []
    for off in range(-a.half, a.half + 1):
        bx, bz = round(x + dx * off), round(z + dz * off)
        cols.append((off, bx, bz))

    ylo = a.ylo if a.ylo is not None else -64
    yhi = a.yhi if a.yhi is not None else 200
    grid = {}
    for off, bx, bz in cols:
        for y in range(ylo, yhi + 1):
            grid[(off, y)] = glyph(rd.block(bx, y, bz))

    # 自動裁切：只留有非 stone/dirt/air 結構的 y 帶 ± 6
    interesting = [y for (off, y), g in grid.items() if g in set("*|#=DPYCW_SAr!")]
    if interesting and a.ylo is None:
        ylo = max(-64, min(interesting) - 4)
        yhi = min(320, max(interesting) + 6)

    print(f"# {'縱' if a.long else '橫'}剖面  y {ylo}..{yhi}  寬 {2*a.half+1} m")
    print("      " + "".join(str(abs(o) % 10) if o % 5 == 0 else " " for o, _, _ in cols))
    for y in range(yhi, ylo - 1, -1):
        print(f"{y:>5} " + "".join(grid[(o, y)] for o, _, _ in cols))
    print("圖例 . 空氣  = 道碴  D 隧道襯砌  C/W 混凝土  P 月台  Y 警示帶  | 月台門/玻璃"
          "  * 燈  _ 半磚  S 平滑石  A 橋墩  # 欄杆  ! 告示牌  g/d/s/b 地表")

main()
