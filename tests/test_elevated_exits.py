#!/usr/bin/env python3
"""Unit tests for real exits at elevated stations and for an underground to
elevated transfer.

An elevated line (rail top y80, ground y67 -> concourse under the viaduct at
y74) crosses an underground line (rail top y40 -> concourse y47) at right
angles. The elevated station's exit shafts climb up from the street and its
passages are skybridges; the transfer shaft runs from the concourse under the
viaduct all the way down to the underground concourse, passing the street
level. Once built, walk from beside the exit signs on the street, without
stepping on soil, to the four platforms of the two lines.

Usage: ./.venv/bin/python tests/test_elevated_exits.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.application import build_exits as BX
from mrt.application import build_line as BL
from mrt.domain import alignment as AL
from mrt.domain import exits as EX
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


G = 67
TERRAIN = "minecraft:grass_block"


def seg(pts, y, ref, kind):
    samples = AL.resample(pts, [kind] * len(pts), AL.STEP)
    n = len(samples)
    ys, gnd = [y] * n, [G] * n
    idx = min(range(n), key=lambda i: samples[i][0] ** 2 + samples[i][1] ** 2)
    stn = {idx: (ref + "1", "測試站", "Test")}
    toff = AL.track_offsets(samples, ys, gnd, [idx])
    return dict(ref=ref, samples=samples, ys=ys, ground=gnd, stn=stn, toff=toff,
                hw=[AL.half_width(t) for t in toff]), idx


def build(w, sg, idx, under):
    samples, ys, gnd, hw = sg["samples"], sg["ys"], sg["ground"], sg["hw"]
    half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
    for i, (x, z, ux, uz, _) in enumerate(samples):
        if idx - half <= i <= idx + half:
            continue
        if under:
            BL.sec_tunnel(w, x, z, -uz, ux, ys[i], hw=hw[i])
        else:
            BL.sec_bridge(w, x, z, -uz, ux, ys[i], G, hw=hw[i],
                          pier=(abs((i * AL.STEP) % AL.PIER_EVERY) < AL.STEP / 2))
    BL.build_station(w, samples, ys, idx, under, label=sg["stn"][idx],
                     grounds=gnd, access=False)


YE, YU = 80, 40
E, ie = seg([(-400.0, 0.0), (400.0, 0.0)], YE, "E", "bridge")
U, iu = seg([(0.0, -400.0), (0.0, 400.0)], YU, "U", "tunnel")
kind, L = AL.station_levels(YE, G)
chk(f"Elevated station concourse is under the viaduct: {kind} y{L}", kind == "under" and L == YE - 6)

print("Planning")
ents = [("1", 80, 45), ("2", -120, -60)]            # Two street exits, both near the elevated station.
occ = EX.index_segments([E, U])
plan = EX.plan_station(E["samples"], E["ys"], E["ground"], ie, ents, lambda x, z: G,
                       occ, EX.Occupancy(), own_tag=0)
chk(f"Both shafts fit (skipped: {[s[3] for s in plan['skipped']]})", len(plan["shafts"]) == 2)
chk(f"Passage at concourse height y{plan['ym']}", plan["ym"] == L)
for s in plan["shafts"]:
    chk(f"Exit {s['refs']}: street y{s['g0'] + 1} is below concourse y{s['y_to']}, so the shaft climbs",
        s["g0"] + 1 < s["y_to"])

print("Build and walk through")
w = DictSink()
build(w, E, ie, False)
build(w, U, iu, True)
# Street: lay a layer of grass as terrain, so that the "no stepping on soil" check means something.
for x in range(-250, 250):
    for z in range(-250, 250):
        if (x, G, z) not in w.blocks:
            w.set(x, G, z, TERRAIN)
objs, exits, rep = BX.station_exits([E, U], {"測試站": ents}, lambda x, z: G,
                                    verbose=False)
tr = rep["測試站"]["transfer"]
chk(f"Transfer passage connected ({tr[0][2].get('reason') if tr else None})", bool(tr) and tr[0][2]["ok"])
chk(f"Both station boxes have exits {exits} (the underground station uses default exits)", set(exits) == {(0, ie), (1, iu)})
for o in objs:
    o.build(w)
get = w.get
bounds = (-450, YU - 5, -450, 450, YE + 12, 450)
man_made = lambda b: b != TERRAIN
tiles = [o for o in objs if isinstance(o, BX.BCC.Tile)]
chk(f"Elevated station passage is a skybridge, underground one a tunnel: {sorted((t.y, t.bridge) for t in tiles)}",
    any(t.bridge and t.y == L for t in tiles) and any(not t.bridge and t.y == YU + 7 for t in tiles))
piers = sum(len(t.pier_to) for t in tiles if t.bridge)
chk(f"{piers} piers under the skybridge", piers > 3)

# The end walls of the side platforms sit on the outermost warning-strip cell at each end;
# nobody can stand on those two cells anyway, so they do not count.
yel_e = [(x, y + 1, z) for (x, y, z), b in w.blocks.items()
         if b == BL.YELLOW and y == YE + 1 and walk.standable(get, x, y + 1, z)]
yel_u = [(x, y + 1, z) for (x, y, z), b in w.blocks.items() if b == BL.YELLOW and y == YU + 1]
chk(f"Warning strips: {len(yel_e)} cells on the elevated side platforms, {len(yel_u)} underground",
    len(yel_e) > 100 and len(yel_u) > 100)
wells = [o for o in objs if isinstance(o, BX.BCC.ShaftStair)]
for well in wells:
    if well.label[1] == "轉乘":
        chk(f"Transfer shaft descends from y{well.g0 + 1} to y{well.y_to}, passing street level y{G + 1}",
            well.g0 + 1 == L and well.y_to == YU + 7)
        continue
    # The street door: beside the exit sign.
    signs = [(x, y, z) for (x, y, z), t in w.signs.items()
             if t[0].startswith("出口") and abs(x - well.x0) < 20 and abs(z - well.z0) < 20]
    chk(f"Exit {well.label[1]} sign stands on the street (y{signs[0][1] if signs else None} = street y{G + 1})",
        len(signs) == 1 and signs[0][1] == G + 1)
    sx, sy, sz = signs[0]
    # Threshold: the cell beside the sign whose floor is a man-made block.
    best = None
    for dx in range(-3, 4):
        for dz in range(-3, 4):
            c = (sx + dx, sy, sz + dz)
            if "sign" in get(*c):
                continue
            if walk.standable(get, *c, floor_ok=man_made):
                d = dx * dx + dz * dz
                if best is None or d < best[0]:
                    best = (d, c)
    chk(f"Exit {well.label[1]} has a threshold beside its sign", best is not None)
    dist, _ = walk.flood(get, [best[1]], bounds=bounds, floor_ok=man_made)
    chk(f"Exit {well.label[1]} reaches both elevated platforms without stepping on soil ({sum(1 for q in yel_e if q in dist)}/{len(yel_e)})",
        all(q in dist for q in yel_e))
    chk(f"Exit {well.label[1]} reaches the underground platform without stepping on soil ({sum(1 for q in yel_u if q in dist)}/{len(yel_u)})",
        all(q in dist for q in yel_u))
    top = max(c[1] for c in dist)
    chk(f"Highest point reached, y{top}, is no higher than the elevated platform railing (y{YE + 3})", top <= YE + 3)

print("\nAll passed" if ok else "\nSome tests failed")
raise SystemExit(0 if ok else 1)
