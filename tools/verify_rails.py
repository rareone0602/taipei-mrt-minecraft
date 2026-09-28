#!/usr/bin/env python3
"""Read every rail back from a world save and check that a train can really run the
whole way, instead of trusting the generator's own account.

The generator's unit tests prove only that the computed path is valid, not that it is
still valid once written into the world: region filtering, station excavation and stairs
can all overwrite a few cells. So the rails are scanned independently.

Three checks:
  1. In both connection directions a rail declares, the rail on the other side really
     connects back.
  2. On an ascending rail, the cell on the uphill side really is one block higher and the
     other end is level.
  3. There is a solid block under every rail (a minecart falls through a rail over air).

Usage: ./.venv/bin/python tools/verify_rails.py [save path] [--show=20]
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
    """Return (the two connection directions, the uphill direction or None)."""
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
    """Return {(x,y,z): (shape, powered)} and {(x,y,z): whether the block below is solid}.

    The key must include y: track can run above other track (a branch line passing under
    the main line, for example), and keying on (x,z) alone would overwrite one of the two
    rails and produce a crop of false breaks.
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
            # Decode every section of the chunk first. When a rail sits on the bottom layer
            # of a section (y % 16 == 0), the cell below it is in the section beneath, so
            # the lookup must cross sections. The check once looked down only within the
            # same section and missed unsupported rails on one layer in every 16.
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
                # Record whether the cell below each rail is air.
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
            print(f"  [{fi}/{len(files)}] {len(rails):,} rails", flush=True)
    return rails, solid


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show = next((int(a.split("=")[1]) for a in sys.argv[1:]
                 if a.startswith("--show=")), 4)
    save = args[0] if args else SAVE
    rdir = os.path.join(save, "dimensions/minecraft/overworld/region")
    rails, solid = scan(rdir)
    bad = collections.Counter()
    sample = collections.defaultdict(list)
    npow = sum(1 for v in rails.values() if v[1])
    for (x, y, z), (shape, powered) in rails.items():
        try:
            (d1, d2), asc = conns(shape)
        except KeyError:
            bad["Unknown shape"] += 1
            continue
        if powered and shape in CURVE:
            bad["Powered on curve"] += 1
        if solid.get((x, y, z)) is False:
            bad["Rail over air"] += 1
            sample["Rail over air"].append(f"({x},{y},{z}) {shape}")
        for d in (d1, d2):
            dx, dz = DIRV[d]
            back = {"north": "south", "south": "north",
                    "east": "west", "west": "east"}[d]
            want = y + 1 if asc == d else y
            nb = rails.get((x + dx, want, z + dz))
            if nb is None and asc is None:
                # The cell at the top of a slope is flat: its neighbor is one block lower
                # and ascends toward it. This is vanilla RailState behavior, not a break.
                low = rails.get((x + dx, y - 1, z + dz))
                if low and low[0] == "ascending_" + back:
                    nb = low
            if nb is None:
                near = [yy for yy in range(y - 2, y + 3)
                        if (x + dx, yy, z + dz) in rails]
                if near:
                    bad["Height mismatch"] += 1
                    sample["Height mismatch"].append(f"({x},{y},{z}) {shape} towards {d} -> y{near}")
                else:
                    bad["No next rail"] += 1
                    sample["No next rail"].append(f"({x},{y},{z}) {shape} towards {d}")
                continue
            nshape = nb[0]
            del back
            back = {"north": "south", "south": "north",
                    "east": "west", "west": "east"}[d]
            if back not in conns(nshape)[0]:
                bad["Not linked back"] += 1
                sample["Not linked back"].append(f"({x},{y},{z}) {shape} towards {d} -> {nshape}")

    ends = bad["No next rail"]
    print(f"\n{len(rails):,} rails ({npow:,} powered, "
          f"{100*npow/max(1,len(rails)):.1f}%)")
    for k, v in bad.items():
        print(f"  {k:<16} {v:>7,}")
    if not bad:
        print("  All passed")
    for k in bad:
        for t in sample[k][:show]:
            print(f"    · {k} {t}")
        if len(sample[k]) > show:
            print(f"    … {len(sample[k]) - show} more '{k}' (--show prints more)")
    print(f"\nNote: 'No next rail' includes the normal ends of every line (each end counts "
          f"as 1). There are {ends} now; the ends of lines and branches alone come to a few "
          f"dozen.")
    return 1 if (bad - collections.Counter({"No next rail": ends})) else 0


if __name__ == "__main__":
    sys.exit(main())
