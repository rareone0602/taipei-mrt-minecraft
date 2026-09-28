#!/usr/bin/env python3
"""Unit tests for at-grade exits: when an elevated station's street is within
2 m of the concourse, no shaft is built; the passage opens straight onto the
street, with a ramp outside the door.

An elevated line (rail top y80, flat ground y67 -> concourse under the viaduct
at y74) has three exits beside it, each on its own plateau: street y76 (2 m
above the concourse), y73 (1 m below) and y71 (3 m below, just enough for a
shaft). The first two must become at-grade exits and the third stays a
switchback shaft. Once built, walk from beside each of the three exit signs,
without stepping on soil, to both platforms, and check that every doorway
reaches the street.

Usage: ./.venv/bin/python tests/test_ground_gate.py
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
YE = 80
pts = [(-400.0, 0.0), (400.0, 0.0)]
samples = AL.resample(pts, ["bridge"] * len(pts), AL.STEP)
n = len(samples)
ys, gnd = [YE] * n, [G] * n
ie = min(range(n), key=lambda i: samples[i][0] ** 2 + samples[i][1] ** 2)
stn = {ie: ("E1", "測試站", "Test")}
toff = AL.track_offsets(samples, ys, gnd, [ie])
E = dict(ref="E", samples=samples, ys=ys, ground=gnd, stn=stn, toff=toff,
         hw=[AL.half_width(t) for t in toff])
kind, L = AL.station_levels(YE, G)
chk(f"Elevated station concourse is under the viaduct: {kind} y{L}", kind == "under" and L == YE - 6)

# Three plateaus: street = ground + 1.
PLATEAU = {(80, 45): L + 1, (-120, -60): L - 2, (-60, 70): L - 4}


def ground_at(x, z):
    for (px, pz), g in PLATEAU.items():
        if abs(x - px) <= 12 and abs(z - pz) <= 12:
            return g
    return G


ents = [("1", 80, 45), ("2", -120, -60), ("3", -60, 70)]

print("Planning")
occ = EX.index_segments([E])
plan = EX.plan_station(E["samples"], E["ys"], E["ground"], ie, ents, ground_at,
                       occ, EX.Occupancy(), own_tag=0)
chk(f"Two at-grade exits and one shaft (skipped: {[s[3] for s in plan['skipped']]})",
    len(plan["gates"]) == 2 and len(plan["shafts"]) == 1)
chk("MIN_RISE is 3: a shaft from a difference of 3, an at-grade exit at 2 or less",
    EX.MIN_RISE == 3 and not EX.drop_ok("under", L + 1, L) and EX.drop_ok("under", L - 4, L))
for s in plan["gates"]:
    chk(f"At-grade exit {s['refs']}: door at the exit position, apron ground y{s['g0']}",
        (s["x0"], s["z0"]) in {(e[1], e[2]) for e in ents} and abs(s["g0"] + 1 - L) <= 2)
    chk(f"At-grade exit {s['refs']}: ramp faces away from the station box (u=({s['ux']},{s['uz']}))",
        (s["ux"], s["uz"]) == (0, 1 if s["z0"] > 0 else -1))
chk("No walls on the ramp and apron outside the door", plan["open"] and plan["open"] <= plan["no_wall"])

print("Build and walk through")
w = DictSink()
half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
for i, (x, z, ux, uz, _) in enumerate(samples):
    if ie - half <= i <= ie + half:
        continue
    BL.sec_bridge(w, x, z, -uz, ux, ys[i], G, hw=E["hw"][i],
                  pier=(abs((i * AL.STEP) % AL.PIER_EVERY) < AL.STEP / 2))
BL.build_station(w, samples, ys, ie, False, label=stn[ie], grounds=gnd, access=False)
for x in range(-250, 250):
    for z in range(-250, 250):
        g = ground_at(x, z)
        if (x, g, z) not in w.blocks:
            w.set(x, g, z, TERRAIN)
objs, exits, rep = BX.station_exits([E], {"測試站": ents}, ground_at, verbose=False)
chk(f"Report shows all three built {[s['refs'] for s in rep['測試站']['built']]}",
    len(rep["測試站"]["built"]) == 3 and exits == {(0, ie): 3})
gates = [o for o in objs if isinstance(o, BX.GroundGate)]
wells = [o for o in objs if isinstance(o, BX.BCC.ShaftStair)]
chk(f"Objects: {len(gates)} at-grade exits, {len(wells)} shafts", len(gates) == 2 and len(wells) == 1)
for o in objs:
    o.build(w)
get = w.get
bounds = (-450, G - 5, -450, 450, YE + 12, 450)
man_made = lambda b: b != TERRAIN
yel = [(x, y + 1, z) for (x, y, z), b in w.blocks.items()
       if b == BL.YELLOW and y == YE + 1 and walk.standable(get, x, y + 1, z)]
chk(f"Warning strips on the two side platforms: {len(yel)} cells", len(yel) > 100)

for o in gates + wells:
    ref = o.label[1]
    street = ground_at(*[e[1:] for e in ents if e[0] == ref[0]][0]) + 1
    signs = [(x, y, z) for (x, y, z), t in w.signs.items()
             if t[0].startswith("出口") and abs(x - o.x0) < 20 and abs(z - o.z0) < 20]
    chk(f"Exit {ref} sign stands on the street (y{signs[0][1] if signs else None} = street y{street})",
        len(signs) == 1 and signs[0][1] == street)
    sx, sy, sz = signs[0]
    best = None
    for dx in range(-3, 4):
        for dz in range(-3, 4):
            for dy in (-1, 0, 1):
                c = (sx + dx, sy + dy, sz + dz)
                if "sign" in get(*c) or not walk.standable(get, *c, floor_ok=man_made):
                    continue
                d = dx * dx + dz * dz + 4 * dy * dy
                if best is None or d < best[0]:
                    best = (d, c)
    chk(f"Exit {ref} has a threshold beside its sign", best is not None)
    c = best[1]
    on_street = any(walk.standable(get, c[0] + dx, c[1] + dy, c[2] + dz,
                                   floor_ok=lambda b: b == TERRAIN)
                    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2))
                    for dy in (-1, 0, 1))
    chk(f"Exit {ref} doorway reaches the street", on_street)
    dist, _ = walk.flood(get, [c], bounds=bounds, floor_ok=man_made)
    chk(f"Exit {ref} reaches both platforms without stepping on soil ({sum(1 for q in yel if q in dist)}/{len(yel)})",
        all(q in dist for q in yel))
    if isinstance(o, BX.GroundGate):
        # The ramp rises or falls at most one block per cell; the door cell is the passage floor.
        floors = [o.floor_at(a) for a in range(0, o.run + 1)]
        chk(f"Exit {ref} ramp {floors} changes one block per cell and ends at street y{street}",
            floors[0] == L - 1 and floors[-1] == street - 1
            and all(abs(p - q) <= 1 for p, q in zip(floors, floors[1:])))

print("\nAll passed" if ok else "\nSome tests failed")
raise SystemExit(0 if ok else 1)
