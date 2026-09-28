"""Cut a section through a generated world save and check the station or tunnel
structure in ASCII.

Usage:
  python tools/slice_world.py 台北車站            # Cross-section (perpendicular to the line)
  python tools/slice_world.py 台北車站 --long     # Longitudinal section (along the line)
  python tools/slice_world.py --xz 0 0 --dir 1 0
"""
import io, os, sys, json, csv, math, zlib, argparse
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
    ("bricks",              "T"),   # Must come after deepslate_bricks.
    ("white_concrete",      "w"),
    ("black_concrete",      "k"),
    ("terracotta",          "t"),   # Line color bands (signage.band_block); kept last.
    ("concrete",            "c"),
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
    with open(config.MC_STATIONS_CSV, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)]
    # Look for an exact station name first, and fall back to substring matching only
    # when there is none. Zhongshan is a substring of Zhongshan Junior High School and
    # Songshan of Songshan Airport, and the CSV is sorted by station code, so substring
    # matching would hit another station first and cut a section through the wrong one.
    hit = [r for r in rows if (r.get("name_zh") or r.get("name") or "") == name]
    if not hit:
        hit = [r for r in rows if name in (r.get("name_zh") or r.get("name") or "")]
    if not hit:
        keys = list(rows[0].keys())
        raise SystemExit(f"Station {name} not found. Columns: {keys}")
    r = hit[0]
    return int(r["mc_x"]), int(r["mc_z"]), r

def line_dir(x, z):
    """Return the direction of the nearest line segment in mc_lines.json."""
    lines = json.load(open(config.MC_LINES_JSON, encoding="utf-8"))
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
    ap.add_argument("--save", help="Read a different world save (for testing)")
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
        print(f"# Line direction ({ux:+.2f},{uz:+.2f})  station is {dist:.1f} m from the line")

    if a.long:
        dx, dz = ux, uz               # Along the line
    else:
        dx, dz = -uz, ux              # Perpendicular to the line

    rd = Reader(config.region_dir(a.save) if a.save else RDIR)
    # First find the y range in which this section holds anything.
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

    # Automatic crop: keep only the y band with structure other than stone, dirt or air,
    # from 4 below it to 6 above. w (white concrete) and B (smooth sandstone) are the paving
    # and shopfront partitions of the underground malls. Without them the crop would cut away
    # the whole underground mall level, and seeing it would need a manual --ylo/--yhi every time.
    interesting = [y for (off, y), g in grid.items() if g in set("*|#=DPYCW_SAr!wB")]
    if interesting and a.ylo is None:
        ylo = max(config.Y_MIN, min(interesting) - 4)
        yhi = min(config.Y_MAX, max(interesting) + 6)

    print(f"# {'Longitudinal section' if a.long else 'Cross-section'}  y {ylo}..{yhi}  width {2*a.half+1} m")
    print("      " + "".join(str(abs(o) % 10) if o % 5 == 0 else " " for o, _, _ in cols))
    for y in range(yhi, ylo - 1, -1):
        print(f"{y:>5} " + "".join(grid[(o, y)] for o, _, _ in cols))
    print("Key: . air  = ballast  D tunnel lining  C/W concrete  P platform  Y warning strip"
          "  | screen doors/glass  * lamp  _ slab  S smooth stone  A pier  # railing  ! sign"
          "  g/d/s/b ground")

main()
