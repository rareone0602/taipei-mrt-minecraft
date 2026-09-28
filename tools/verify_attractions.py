#!/usr/bin/env python3
"""Read back every attraction and compare its built height, outline, teleport points
and plaques with independent data.

The generator saying that Taipei 101 is 508 m tall does not count. This tool looks only
at the disk:

  · Height: the highest block within the outline, minus the median ground level in a
    ring outside the outline, compared with the public figure in the FACTS table below
    (tolerance max(2 m, 3%)). FACTS belongs to this tool and is not taken from the
    generator, so that a mistake in the generator is caught here.
  · Outline: the share of the main OSM outline (data/attractions.json) that has
    something 3 blocks above the ground on top (where it was built, and whether it was
    turned the wrong way; a hollow hall does not matter), and the share of columns
    beyond the distance FACTS allows outside the outline that still hold building 6 or
    more blocks above the ground (built askew or out of bounds).
  · Teleport points: the single tp line in the datapack's sight/<id>*.mcfunction (the
    convention is in ride_plan) lands on a standable cell (the rules in domain/walk).
    The default viewpoint must face the outline, within 60°.
  · Plaque: a sign within 4 blocks of the default viewpoint whose first line is the
    attraction's Chinese name and does not start with `出口` ("Exit").
  · Every sign with a click action within the attraction's area points to a function
    that really exists in the datapack.

Usage:
    ./.venv/bin/python tools/verify_attractions.py <save> [--only taipei101 cks_memorial ...]
"""
import argparse
import glob
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt import config
from mrt.domain import geometry as shapes
from mrt.domain import walk
from mrt.infrastructure import savereader as SR

# Published heights (meters, from the ground to the highest point) and tolerances for the
# outline checks. height=None: the height is not checked (no reliable public figure).
# cover: the minimum share of the outline that must be built on at ground level (lower for
# attractions with courtyards or plazas). spill: the distance in meters beyond the outline
# past which there should be no building (larger where steps, plazas or eaves count).
FACTS = {
    "taipei101":              dict(height=508.0, cover=0.6, spill=30),   # Top of the spire 508 m (2004)
    "shin_kong_tower":        dict(height=244.15, cover=0.6, spill=15),  # 244.15 m (1993)
    "cks_memorial":           dict(height=70.0, cover=0.25, spill=60),   # Main hall 70 m
    "presidential_office":    dict(height=60.0, cover=0.4, spill=20),    # Central tower 60 m
    # The element named for The Grand Hotel is the whole hotel site. The main body is the
    # main building plus the rear wing that climbs the hillside.
    "grand_hotel":            dict(height=87.0, cover=0.4, spill=40,     # 87 m (1973)
                                   outline=["way/25202548", "relation/10098399"]),
    "sun_yat_sen_memorial":   dict(height=30.4, cover=0.5, spill=40),    # 30.4 m
    "miramar_wheel":          dict(height=100.0, cover=0.2, spill=40),   # Wheel top 100 m above the ground
    "national_taiwan_museum": dict(height=30.0, cover=0.5, spill=20),   # Top of the dome nearly 30 m (1915)
    "red_house":              dict(height=None, cover=0.5, spill=15),
    # The named way is only the main hall. The front hall is 28 m in front of it and the
    # gate arch 48 m (that is how OSM maps it).
    "longshan_temple":        dict(height=None, cover=0.4, spill=50),
    "beimen":                 dict(height=None, cover=0.5, spill=15),
    "dongmen":                dict(height=None, cover=0.5, spill=25),
    "nanmen":                 dict(height=None, cover=0.5, spill=25),
    "xiaonanmen":             dict(height=None, cover=0.5, spill=25),
    # The campus has two named buildings, the Main Library and the gate's guardhouse 700 m
    # away; the checks are made on the library. Further out than the ring checked here
    # (10–30 m) stand the plaza's palms and the rest of the campus, built on purpose.
    "national_taiwan_university": dict(height=None, cover=0.5, spill=10,
                                       outline=["relation/14045849"]),
}
DEFAULT = dict(height=None, cover=0.4, spill=25)

AIRS = ("minecraft:air", "minecraft:cave_air", "minecraft:void_air")
# Blocks used by the terrain generator (application/build_world.terrain_chunk) and the
# superflat background.
NATURAL = {"minecraft:" + n for n in ("grass_block", "dirt", "stone", "sand", "water", "bedrock",
                                      "gravel", "coarse_dirt")}
TP_RE = re.compile(r"^tp @s (-?[\d.]+) (-?\d+) (-?[\d.]+) (-?[\d.]+) (-?[\d.]+)$")


def is_air(b):
    return b.split("[")[0] in AIRS


def load_sight_fns(save):
    """The datapack's sight functions: {path: (x, y, z, yaw, pitch)}."""
    root = os.path.join(save, "datapacks", config.DATAPACK_NAME, "data", config.DATAPACK_NS, "function")
    out = {}
    for f in glob.glob(os.path.join(root, "sight", "*.mcfunction")):
        path = "sight/" + os.path.basename(f)[:-len(".mcfunction")]
        tps = [TP_RE.match(ln.strip()) for ln in open(f, encoding="utf-8")]
        tps = [m for m in tps if m]
        if len(tps) != 1:
            out[path] = None
            continue
        x, y, z, yaw, pitch = tps[0].groups()
        out[path] = (float(x), int(y), float(z), float(yaw), float(pitch))
    return out


def all_functions(save):
    root = os.path.join(save, "datapacks", config.DATAPACK_NAME, "data", config.DATAPACK_NS, "function")
    return {os.path.relpath(f, root)[:-len(".mcfunction")].replace(os.sep, "/")
            for f in glob.glob(os.path.join(root, "**", "*.mcfunction"), recursive=True)}


def main_outlines(item, osm_ids=None):
    """Outer rings of the main body: the named elements with a building or building:part
    tag.

    A named element is not always a building. The element named for The Grand Hotel is the
    whole hotel site (tourism=hotel, 40,000 m2). Used as the outline, its surrounding ring
    would be the flat riverbank below the hill, and both the height and the spill would come
    out wrong. When no named element is a building, take the building nearest the center
    with a large area."""
    rings = []
    if osm_ids:                        # FACTS names the buildings that make up the main body.
        for f in item["features"]:
            if f["osm"] in osm_ids and f.get("outer"):
                rings += [r for r in f["outer"] if len(r) >= 3]
        if rings:
            return rings
    for f in item["features"]:
        t = f.get("tags", {})
        if (f.get("main") and f.get("outer") and f.get("area", 0) > 0
                and ("building" in t or "building:part" in t)):
            rings += [r for r in f["outer"] if len(r) >= 3]
    if not rings:
        blds = [f for f in item["features"] if f.get("outer") and "building" in f["tags"]]
        if blds:
            f = min(blds, key=lambda f: f["dist"] - 0.001 * f["area"])
            rings = [max(f["outer"], key=len)]
    return rings


def check(save, item, fns, funcs, say):
    aid = item["id"]
    fact = FACTS.get(aid, DEFAULT)
    probs = []
    rings = main_outlines(item, fact.get("outline"))
    if not rings:
        return ["the data has no main outline"]
    cells = set()
    for r in rings:
        cells |= shapes.poly_cells(r)
    xs = [c[0] for c in cells]
    zs = [c[1] for c in cells]
    m = int(fact["spill"]) + 24
    x0, z0, x1, z1 = min(xs) - m, min(zs) - m, max(xs) + m, max(zs) + m
    vol = SR.read_volume(save, x0, 40, z0, x1, config.Y_MAX, z1, verbose=False)
    data = vol.data                                    # [y][z][x]
    air = np.array([is_air(n) for n in vol.names])
    solid = ~air[data]
    col_any = solid.any(axis=0)
    top = np.where(col_any, vol.y0 + (vol.ny - 1 - np.argmax(solid[::-1], axis=0)), -999)   # [z][x]

    def T(x, z):
        return int(top[z - z0, x - x0])

    # Ground: the median column top in the ring from spill+8 to spill+20 beyond the outline
    # (there should be only terrain there). For a building on a hillside (The Grand Hotel
    # stands halfway up Jiantan Mountain) that ring is the flat riverbank below, so the
    # height has to be measured from the building's own base: if the lowest man-made block
    # within the outline (the ground-floor slab) is 2 or more blocks above the far ring,
    # use it instead.
    fp = np.zeros(top.shape, dtype=bool)
    for x, z in cells:
        fp[z - z0, x - x0] = True
    dist = _chebyshev_from(fp)
    band = (dist > fact["spill"] + 8) & (dist <= fact["spill"] + 20) & col_any
    if not band.any():
        return probs + ["cannot read the ground outside the outline (no chunks beyond the area?)"]
    natural = np.array([n.split("[")[0] in NATURAL for n in vol.names])
    iy = np.clip(top - vol.y0, 0, vol.ny - 1)
    zz, xx = np.indices(top.shape)
    top_natural = natural[data[iy, zz, xx]] & col_any
    far_g = int(np.median(top[band]))
    # The building's own base: in each column within the outline, the first man-made block
    # upward from 3 blocks below the far-ring ground, taking the lower quartile (the main
    # building's ground-floor slab; the rear wing up the hillside has higher floors and must
    # not raise the base).
    lo = max(0, far_g - 3 - vol.y0)
    man = solid[lo:] & ~natural[data[lo:]]
    has_man = man.any(axis=0) & fp
    base_g = (int(np.percentile(vol.y0 + lo + np.argmax(man, axis=0)[has_man], 25))
              if has_man.any() else far_g)
    ground = base_g if base_g > far_g + 2 else far_g

    # Height
    near = dist <= 3
    peak = int(top[near].max()) if near.any() else -999
    h = peak - ground
    if fact["height"] is not None:
        tol = max(2.0, 0.03 * fact["height"])
        ok = abs(h - fact["height"]) <= tol
        say("  %s Height: top y%d − ground y%d = %d m (published %.1f m, tolerance ±%.0f m)%s"
            % ("ok  " if ok else "FAIL", peak, ground, h, fact["height"], tol,
               "" if ground == far_g else
               " (on a hillside: ground taken from the building base y%d, distant terrain y%d)"
               % (base_g, far_g)))
        if not ok:
            probs.append("height %d m, published %.1f m" % (h, fact["height"]))
    else:
        say("  --   Height: top y%d − ground y%d = %d m (no published figure to compare)"
            % (peak, ground, h))
        if h < 4:
            probs.append("almost nothing on the outline (%d m tall)" % h)

    # Outline cover: seen from above, how many cells within the outline have something on
    # top (3 blocks above the ground; a hollow hall does not matter).
    cover = float((top[fp] >= ground + 3).mean())
    ok = cover >= fact["cover"]
    say("  %s Outline cover: of %d cells in the OSM outline, %.0f%% have something 3 blocks "
        "above the ground (minimum %.0f%%)"
        % ("ok  " if ok else "FAIL", len(cells), cover * 100, fact["cover"] * 100))
    if not ok:
        probs.append("outline cover only %.0f%%" % (cover * 100))

    # Spill: columns farther than spill from the outline that still have something 6 or more
    # blocks above the ground. Columns topped by natural terrain (a hillside) do not count.
    tall = (top >= ground + 6) & ~top_natural
    out = tall & (dist > fact["spill"]) & (dist <= fact["spill"] + 20)
    n_out, n_in = int(out.sum()), int((tall & fp).sum())
    spill = n_out / max(1, n_in + n_out)
    ok = spill <= 0.10
    say("  %s Spill: beyond %d m outside the outline, %d columns stand 6 blocks above the "
        "ground (%.0f%%, limit 10%%)"
        % ("ok  " if ok else "FAIL", fact["spill"], n_out, spill * 100))
    if not ok:
        probs.append("beyond %d m outside the outline, %d columns (built askew or out of bounds)"
                     % (fact["spill"], n_out))

    # Teleport points
    mine = {p: v for p, v in fns.items() if p == "sight/" + aid or p.startswith("sight/%s_" % aid)}
    if "sight/" + aid not in mine:
        probs.append("no sight/%s in the datapack" % aid)
        say("  FAIL No sight/%s in the datapack" % aid)
    cx, cz = sum(xs) / len(xs), sum(zs) / len(zs)
    for path, tp in sorted(mine.items()):
        if tp is None:
            probs.append("%s is not exactly one tp line" % path)
            continue
        x, y, z, yaw, pitch = tp
        bx, bz = int(math.floor(x)), int(math.floor(z))
        get = vol.get
        if not (x0 <= bx <= x1 and z0 <= bz <= z1):
            # A tall building must be viewed from farther away to fit in view, so the
            # viewpoint may lie outside the area read back. Read its small patch separately.
            get = SR.read_volume(save, bx - 1, y - 2, bz - 1, bx + 1, y + 3, bz + 1, verbose=False).get
        stand = walk.standable(get, bx, y, bz)
        msg = "standable" if stand else "not standable (feet %s, head %s, below %s)" % (
            get(bx, y, bz), get(bx, y + 1, bz), get(bx, y - 1, bz))
        ok = stand
        if path == "sight/" + aid:
            want = math.degrees(math.atan2(-(cx + 0.5 - x), cz + 0.5 - z))
            dev = abs((yaw - want + 180) % 360 - 180)
            ok = ok and dev <= 60
            msg += ", facing %.0f° off the outline centre" % dev
        say("  %s Teleport point %s (%.1f, %d, %.1f): %s" % ("ok  " if ok else "FAIL", path, x, y, z, msg))
        if not ok:
            probs.append("%s: %s" % (path, msg))

    # Plaques and click commands
    signs = SR.read_sign_entities(save, x0, z0, x1, z1)
    tp = mine.get("sight/" + aid)
    if tp and not (x0 <= tp[0] <= x1 and z0 <= tp[2] <= z1):
        signs += SR.read_sign_entities(save, int(tp[0]) - 6, int(tp[2]) - 6, int(tp[0]) + 6, int(tp[2]) + 6)
    if tp:
        x, y, z = tp[0], tp[1], tp[2]
        pl = [s for s in signs if abs(s["x"] - x) <= 4.5 and abs(s["z"] - z) <= 4.5 and abs(s["y"] - y) <= 2]
        named = [s for s in pl if s["front"] and s["front"][0].strip() == item["name_zh"]]
        ok = bool(named)
        say("  %s Plaque: signs within 4 blocks of the viewpoint %d%s" % (
            "ok  " if ok else "FAIL", len(pl), (", first line '%s'" % named[0]["front"][0]) if named else ""))
        if not ok:
            probs.append("no plaque reading '%s' next to the viewpoint" % item["name_zh"])
    ns = config.DATAPACK_NS + ":"
    for s in signs:
        if s["front"] and s["front"][0].startswith("出口") and (x0 + 20 < s["x"] < x1 - 20):
            pass                                         # Metro exit signs are not this tool's concern.
        c = s.get("click")
        if not c or c.get("action") != "run_command":
            continue
        cmd = c.get("command", "").lstrip("/")
        mm = re.match(r"^function %s(\S+)$" % re.escape(ns), cmd)
        if mm and mm.group(1) not in funcs:
            probs.append("sign (%d,%d,%d) runs a missing function: %s" % (s["x"], s["y"], s["z"], cmd))
    return probs


def _chebyshev_from(mask):
    """Chebyshev distance from each cell to the mask (0 inside the mask)."""
    d = np.where(mask, 0, 10 ** 6).astype(np.int64)
    cur = mask.copy()
    k = 0
    while not cur.all() and k < 400:
        k += 1
        n = cur.copy()
        n[1:, :] |= cur[:-1, :]
        n[:-1, :] |= cur[1:, :]
        n[:, 1:] |= cur[:, :-1]
        n[:, :-1] |= cur[:, 1:]
        n[1:, 1:] |= cur[:-1, :-1]
        n[:-1, :-1] |= cur[1:, 1:]
        n[1:, :-1] |= cur[:-1, 1:]
        n[:-1, 1:] |= cur[1:, :-1]
        d[n & ~cur] = k
        if (n == cur).all():
            break
        cur = n
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save")
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args()
    items = json.load(open(os.path.join(config.DATA, "attractions.json"), encoding="utf-8"))["items"]
    fns = load_sight_fns(a.save)
    funcs = all_functions(a.save)
    bad = {}
    n = 0
    for it in items:
        if a.only and it["id"] not in a.only:
            continue
        print("%s %s %s" % (it["id"], it["name_zh"], it["name_en"]))
        n += 1
        p = check(a.save, it, fns, funcs, print)
        if p:
            bad[it["id"]] = p
    print()
    if bad:
        print("Attractions with problems: %d of %d" % (len(bad), n))
        for k, v in bad.items():
            print("  %s: %s" % (k, "; ".join(v)))
        sys.exit(1)
    print("Attractions passed: %d of %d" % (n, n))


if __name__ == "__main__":
    main()
