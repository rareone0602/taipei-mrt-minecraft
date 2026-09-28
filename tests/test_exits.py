#!/usr/bin/env python3
"""Unit tests for real exits: build a straight underground station, connect a
few awkwardly placed exits, then walk from every exit kiosk to the platform by
the rules a player can actually walk.

Each exit position is chosen deliberately and matches a case that really
occurs in the data:
  · beside the station box (the simplest)
  · right above the tunnel, outside the platform range: the shaft must be
    pushed outward, and the passage must come back along the outside of the
    station box
  · two doors within 8 m: they must merge into one shaft
  · more than 500 m away: must be rejected
  · on the opposite side: a second opening

Usage: ./.venv/bin/python tests/test_exits.py
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


Y, G = 40, 60           # Rail top and ground (flat).


def straight_seg(x0=-400, x1=400, idx_x=0):
    pts = [(float(x0), 0.0), (float(x1), 0.0)]
    samples = AL.resample(pts, ["tunnel", "tunnel"], AL.STEP)
    n = len(samples)
    ys = [Y] * n
    gnd = [G] * n
    idx = min(range(n), key=lambda i: abs(samples[i][0] - idx_x))
    stn = {idx: ("T1", "測試站", "Test")}
    toff = AL.track_offsets(samples, ys, gnd, [idx])
    hw = [AL.half_width(t) for t in toff]
    return dict(ref="T", samples=samples, ys=ys, ground=gnd, stn=stn,
                toff=toff, hw=hw), idx


def build_line_and_station(w, seg, idx, access):
    samples, ys, gnd, hw = seg["samples"], seg["ys"], seg["ground"], seg["hw"]
    half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
    lo, hi = idx - half, idx + half
    for i, (x, z, ux, uz, _) in enumerate(samples):
        if lo <= i <= hi:
            continue
        BL.sec_tunnel(w, x, z, -uz, ux, ys[i], hw=hw[i])
    BL.build_station(w, samples, ys, idx, True, label=seg["stn"][idx],
                     grounds=gnd, access=access)
    return lo, hi


seg, idx = straight_seg()
samples = seg["samples"]
print("Occupancy index")
occ = EX.index_segments([seg])
chk("Tunnel centreline is occupied at rail-top height", occ.blocked(200, 0, Y, Y + 2))
chk("Cell just outside the tunnel side wall is free", not occ.blocked(200, 9, Y, Y + 2))
chk("Station box occupies half-width 13", occ.blocked(0, 13, Y + 8, Y + 9))
chk("Nothing above the ground is occupied", not occ.blocked(200, 0, G + 1, G + 3))

print("Transfer station assignment")
seg2, idx2 = straight_seg(idx_x=0)
# A second line: the same geometry with the station box moved to x=+300 (standing in for
# another line's station box).
seg2b, idx2b = straight_seg(idx_x=300)
boxes = {"A": (seg2["samples"], seg2["ys"], idx2),
         "B": (seg2b["samples"], seg2b["ys"], idx2b)}
asg = EX.assign_to_boxes([("1", 20, 40), ("2", 280, -40), ("3", 150, 30)], boxes)
chk(f"Exits nearer A go to A: {[e[0] for e in asg['A']]}", [e[0] for e in asg["A"]] == ["1", "3"])
chk(f"Exits nearer B go to B: {[e[0] for e in asg['B']]}", [e[0] for e in asg["B"]] == ["2"])

print("Planning")
ents = [("1", 10, 40),        # Beside the station box.
        ("2", 120, -5),       # Right above the tunnel, beyond the platform.
        ("3", 16, 44),        # 8 m from No. 1 -> merged.
        ("4", 600, 0),        # Too far.
        ("5", -60, -30)]      # Opposite side, beyond the lo end.
ground_at = lambda x, z: G
plan = EX.plan_station(samples, seg["ys"], seg["ground"], idx, ents, ground_at,
                       occ, EX.Occupancy())
chk(f"Concourse standing surface y{plan['ym']} = rail top + 7", plan["ym"] == Y + AL.MEZZ_DY + 1)
chk(f"Builds {len(plan['shafts'])} shafts (1+3 merged, 2, 5)", len(plan["shafts"]) == 3)
chk(f"Rejects {len(plan['skipped'])} (No. 4 is too far)",
    len(plan["skipped"]) == 1 and plan["skipped"][0][0] == ["4"])
merged = [s for s in plan["shafts"] if "3" in s["refs"] and "1" in s["refs"]]
chk("Nos. 1 and 3 share one shaft", len(merged) == 1)
s2 = next(s for s in plan["shafts"] if s["refs"] == ["2"])
cells2 = EX.shaft_cells(s2["x0"], s2["z0"], s2["ux"], s2["uz"])
chk(f"Shaft above the tunnel pushed out {s2['slide']} m, shaft body >= 13 from the centreline",
    s2["slide"] > 0 and min(abs(z) for _, z in cells2) >= 13)
chk("Shaft body overlaps no underground structure",
    not occ.any_blocked(cells2, plan["ym"] - 1, G + 5))
per_m = int(round(1 / AL.STEP))
hole_x = samples[plan["hole"]][0]
chk(f"Opening at lo + 7 m (x={hole_x:.0f}; fare gates at lo + 14)",
    abs(hole_x - (samples[plan["lo"]][0] + 7)) < 1)
chk("Openings on both sides",
    (int(round(hole_x)), 11) in plan["cells"] and (int(round(hole_x)), -11) in plan["cells"])
chk("Passage cells exclude the station box interior", not (plan["cells"] & plan["no_wall"]))

print("Build and walk through")
w = DictSink()
lo, hi = build_line_and_station(w, seg, idx, access=False)
n_before = len(w.blocks)
objs, exits, rep = BX.station_exits([seg], {"測試站": ents}, ground_at,
                                    verbose=False)
chk(f"station_exits reports {list(exits.values())} shafts for this station", exits == {(0, idx): 3})
for o in objs:
    o.build(w)
chk(f"Wrote {len(w.blocks) - n_before:,} more blocks", len(w.blocks) - n_before > 5000)

get = w.get
ym = plan["ym"]
bounds = (-450, Y - 5, -120, 450, G + 6, 120)
wells = [o for o in objs if isinstance(o, BX.BCC.ShaftStair)]
chk(f"{len(wells)} ShaftStairs", len(wells) == 3)
yellow = [(x, y + 1, z) for (x, y, z), b in w.blocks.items() if b == BL.YELLOW]
chk(f"Platform warning strip: {len(yellow)} cells", len(yellow) > 100)
starts = {}
for well in wells:
    x, z = well._w(0, 0)                      # The entrance landing, the first cell inside the door.
    c = (x, well.g0 + 1, z)
    chk(f"Exit {well.label[1]}: shaft entrance {c} is standable", walk.standable(get, *c))
    starts[well.label[1][0]] = c
comps = walk.components(get, list(starts.values()), bounds=bounds)
chk(f"The three shafts reach each other ({len(comps)} connected components)", len(comps) == 1)
for ref, c in sorted(starts.items()):
    dist, _ = walk.flood(get, [c], bounds=bounds)
    reach = sum(1 for y in yellow if y in dist)
    chk(f"Exit {ref} reaches the platform warning strip ({reach}/{len(yellow)} cells)", reach == len(yellow))
    chk(f"Exit {ref} reaches the concourse in front of the fare gates (unpaid area)",
        any(y == ym and x < samples[lo][0] + 14 for (x, y, z) in dist))

print("Shafts and passages leave the tunnel alone")
ref_w = DictSink()
build_line_and_station(ref_w, seg, idx, access=False)
bad = 0
for (x, y, z), b in ref_w.blocks.items():
    if abs(z) <= 7 and not (samples[lo][0] - 1 <= x <= samples[hi][0] + 1):
        if w.blocks.get((x, y, z)) != b:
            bad += 1
chk(f"No tunnel cross-section cell outside the station box changed ({bad} changed)", bad == 0)
hole_cells = [(int(round(hole_x)), ym + dy, 11) for dy in range(0, 3)]
chk("Side-wall opening is really empty", all(get(*c) == "minecraft:air" for c in hole_cells))
chk("Lining beside the opening is intact",
    get(int(round(hole_x)) + 6, ym, 11) != "minecraft:air")

print("Template stair unchanged without real exits")
w0 = DictSink()
build_line_and_station(w0, seg, idx, access=True)
w1 = DictSink()
build_line_and_station(w1, seg, idx, access=False)
chk(f"access=True adds {len(w0) - len(w1):,} blocks (template stair and station building)", len(w0) > len(w1) + 500)

print("\nAll passed" if ok else "\nSome tests failed")
raise SystemExit(0 if ok else 1)
