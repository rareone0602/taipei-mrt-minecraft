#!/usr/bin/env python3
"""從存檔讀回所有鐵軌，檢查真的能一路跑完 —— 不相信生成器的自述。

生成器自己的單元測試只證明「算出來的路徑」合法，證明不了寫進世界之後
還是那樣：region 過濾、車站挖空、樓梯都可能把某幾格蓋掉。所以獨立掃一遍。

檢查三件事：
  1. 每根鐵軌宣告的兩個連接方向，對面真的有一根鐵軌接回來
  2. 斜軌上方那一格真的高一格、另一端同高
  3. 鐵軌底下是實心方塊（懸空的軌道礦車會掉下去）

用法: ./.venv/bin/python tools/verify_rails.py [存檔路徑]
"""
import io, os, re, sys, glob, zlib, collections
import numpy as np, nbtlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mrt import config

SAVE = config.INSTALLED_SAVE

DIRV = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
STRAIGHT = {"north_south": ("north", "south"), "east_west": ("east", "west")}
CURVE = {"north_east": ("north", "east"), "north_west": ("north", "west"),
         "south_east": ("south", "east"), "south_west": ("south", "west")}


def conns(shape):
    """(兩個連接方向, 上坡方向或 None)"""
    if shape.startswith("ascending_"):
        d = shape[len("ascending_"):]
        opp = {"north": "south", "south": "north", "east": "west", "west": "east"}[d]
        return (d, opp), d
    if shape in STRAIGHT:
        return STRAIGHT[shape], None
    return CURVE[shape], None


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


def scan(rdir):
    """回傳 {(x,y,z): (shape, powered)} 與 {(x,y,z): 底下是否實心}

    鍵一定要含 y：同一條線可能上下疊（例如支線從主線底下鑽過），
    只用 (x,z) 當鍵會把其中一根蓋掉，然後憑空生出一堆假斷點。
    """
    rails, solid = {}, {}
    files = sorted(glob.glob(os.path.join(rdir, "r.*.mca")))
    for fi, p in enumerate(files, 1):
        raw = open(p, "rb").read()
        if len(raw) < 8192:
            continue
        for i in range(1024):
            off = int.from_bytes(raw[i*4:i*4+3], "big")
            if off == 0:
                continue
            q = off * 4096
            ln = int.from_bytes(raw[q:q+4], "big")
            blob = raw[q+5:q+4+ln]
            root = nbtlib.File.parse(io.BytesIO(
                zlib.decompress(blob) if raw[q+4] == 2 else blob))
            root = root[''] if '' in root else root
            bx, bz = int(root["xPos"]) * 16, int(root["zPos"]) * 16
            # 先把整個 chunk 的 section 解開：鐵軌落在 section 最底一排
            # （y % 16 == 0）時，底下那格在下一個 section 裡，要跨 section 查。
            # 原本只在同一個 section 內往下看，每 16 排就有一排的懸空漏檢。
            decoded = {}
            for sec in root["sections"]:
                bs = sec["block_states"]
                pal = [str(e["Name"]) + (
                    "[" + ",".join(f"{k}={v}" for k, v in e["Properties"].items()) + "]"
                    if "Properties" in e else "") for e in bs["palette"]]
                idx = (unpack(bs["data"], max(4, (len(pal) - 1).bit_length()))
                       if "data" in bs else np.zeros(4096, dtype=np.int64))
                decoded[int(sec["Y"])] = (pal, idx)
            for sy, (pal, idx) in decoded.items():
                names = [s.split("[")[0] for s in pal]
                if not any("rail" in n for n in names):
                    continue
                base = sy * 16
                for k in np.nonzero(np.isin(idx, [j for j, n in enumerate(names)
                                                  if n.endswith("rail")]))[0]:
                    j = int(idx[k])
                    y = base + int(k) // 256
                    z = bz + (int(k) % 256) // 16
                    x = bx + int(k) % 16
                    m = re.search(r"shape=([a-z_]+)", pal[j])
                    rails[(x, y, z)] = (m.group(1) if m else "?",
                                        "powered=true" in pal[j])
                # 記下軌道底下那一格是不是空氣
                air = [j for j, n in enumerate(names) if n == "minecraft:air"]
                below = decoded.get(sy - 1)
                for k in np.nonzero(np.isin(idx, [j for j, n in enumerate(names)
                                                  if n.endswith("rail")]))[0]:
                    y = base + int(k) // 256
                    z = bz + (int(k) % 256) // 16
                    x = bx + int(k) % 16
                    kb = int(k) - 256
                    if kb >= 0:
                        solid[(x, y, z)] = int(idx[kb]) not in air
                    elif below is not None:
                        bpal, bidx = below
                        solid[(x, y, z)] = bpal[int(bidx[kb + 4096])].split("[")[0] \
                            != "minecraft:air"
                    else:
                        solid[(x, y, z)] = False
        if fi % 50 == 0 or fi == len(files):
            print(f"  [{fi}/{len(files)}] {len(rails):,} 根鐵軌", flush=True)
    return rails, solid


def main():
    save = sys.argv[1] if len(sys.argv) > 1 else SAVE
    rdir = os.path.join(save, "dimensions/minecraft/overworld/region")
    rails, solid = scan(rdir)
    bad = collections.Counter()
    sample = collections.defaultdict(list)
    npow = sum(1 for v in rails.values() if v[1])
    for (x, y, z), (shape, powered) in rails.items():
        try:
            (d1, d2), asc = conns(shape)
        except KeyError:
            bad["形狀無法辨識"] += 1
            continue
        if powered and shape in CURVE:
            bad["動力軌用了彎道形狀"] += 1
        if solid.get((x, y, z)) is False:
            bad["軌道懸空"] += 1
            sample["軌道懸空"].append(f"({x},{y},{z}) {shape}")
        for d in (d1, d2):
            dx, dz = DIRV[d]
            back = {"north": "south", "south": "north",
                    "east": "west", "west": "east"}[d]
            want = y + 1 if asc == d else y
            nb = rails.get((x + dx, want, z + dz))
            if nb is None and asc is None:
                # 斜軌的上端那一格是平的：它的鄰居低一格、而且朝自己爬上來。
                # 這是原版 RailState 的行為，不是斷點。
                low = rails.get((x + dx, y - 1, z + dz))
                if low and low[0] == "ascending_" + back:
                    nb = low
            if nb is None:
                near = [yy for yy in range(y - 2, y + 3)
                        if (x + dx, yy, z + dz) in rails]
                if near:
                    bad["高程對不上"] += 1
                    sample["高程對不上"].append(f"({x},{y},{z}) {shape} 往{d} -> y{near}")
                else:
                    bad["接不到下一根"] += 1
                    sample["接不到下一根"].append(f"({x},{y},{z}) {shape} 往{d}")
                continue
            nshape = nb[0]
            del back
            back = {"north": "south", "south": "north",
                    "east": "west", "west": "east"}[d]
            if back not in conns(nshape)[0]:
                bad["對面沒接回來"] += 1
                sample["對面沒接回來"].append(f"({x},{y},{z}) {shape} 往{d} -> {nshape}")

    ends = bad["接不到下一根"]
    print(f"\n鐵軌 {len(rails):,} 根（動力軌 {npow:,} 根，"
          f"{100*npow/max(1,len(rails)):.1f}%）")
    for k, v in bad.items():
        print(f"  {k:<16} {v:>7,}")
    if not bad:
        print("  全部通過")
    for k in bad:
        for t in sample[k][:4]:
            print(f"    · {k} {t}")
    print(f"\n註：「接不到下一根」含各路線的正常端點（每個端點算 1）。"
          f"目前 {ends} 個，路線／支線端點本來就會有幾十個。")
    return 1 if (bad - collections.Counter({"接不到下一根": ends})) else 0


if __name__ == "__main__":
    sys.exit(main())
