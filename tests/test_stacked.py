#!/usr/bin/env python3
"""Unit tests for stacked stations and pocket tracks (domain/stacked.py,
build_line.sec_multi / _station_stacked).

Three synthetic straight underground stations, each actually built (DictSink)
and then checked:
  · stacked side platforms (like Fuzhong): one line whose two tracks split onto
    two levels before the station, with the platforms on the same side
  · shared stacked island platforms (like Ximen): two parallel lines 17 m
    apart sharing one two-level station box
  · a pocket track: the main tracks flare out between stations, with an extra
    storage track between them

The checks use the rules a player can actually walk (domain/walk): starting
from the concourse, the warning strips on both platform levels must be
reachable. A missing stair step, an opening left closed, or a lower-level roof
that leaves too little headroom cannot be seen in a cross-section; only walking
through reveals them. Rails are laid from strands() the way the cli lays them,
must pass the general checker, and must each sit on the track bed (the box
structure in the split section is built as a per-sample union, and any cell
missed leaves a rail hanging).

Usage: ./.venv/bin/python tests/test_stacked.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.application import build_line as BL
from mrt.domain import alignment as AL
from mrt.domain import exits as EX
from mrt.domain import rails
from mrt.domain import stacked as SK
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


Y, G = 48, 66                       # Rail top and ground (flat).


def make_seg(ref, pts, stn_x, y=Y):
    """A straight underground line with a station at the sample nearest x=stn_x."""
    samples = AL.resample(pts, ["tunnel"] * len(pts), AL.STEP)
    n = len(samples)
    idxs = [min(range(n), key=lambda i: abs(samples[i][0] - sx)) for sx in stn_x]
    stn = {i: (f"{ref}{k + 1}", f"{ref}站{k + 1}", f"{ref} station {k + 1}")
           for k, i in enumerate(idxs)}
    return dict(ref=ref, samples=samples, ys=np.full(n, y), ground=np.full(n, G),
                stn=stn), idxs


def finish(sg):
    """What cli.plan_segments does after level splits and pocket tracks: lateral
    offsets and half-widths."""
    stk = sg.get("stacked", {})
    if "toff" not in sg:
        sg["toff"] = AL.track_offsets(sg["samples"], sg["ys"], sg["ground"],
                                      [i for i in sorted(sg["stn"]) if i not in stk])
    sg["hw"] = [AL.half_width(t) for t in sg["toff"]]


def build_sections(w, sg, skip_stn=True):
    """Build cross-sections in the order of cli.main: none within station ranges
    (the station builds its own) and none in nobuild."""
    samples, ys = sg["samples"], sg["ys"]
    n = len(samples)
    half = int(AL.PLATFORM_LEN / 2 / AL.STEP)
    in_stn = set()
    for bi in sg["stn"]:
        in_stn.update(range(max(0, bi - half), min(n - 1, bi + half) + 1))
    nob = sg.get("nobuild", set())
    multi = sg.get("multi")
    for i, (x, z, ux, uz, _) in enumerate(samples):
        if (skip_stn and i in in_stn) or i in nob:
            continue
        if multi is not None and multi[i]:
            BL.sec_multi(w, x, z, -uz, ux, SK.tracks_at(sg, i))
        else:
            BL.sec_tunnel(w, x, z, -uz, ux, int(ys[i]), hw=sg["hw"][i])


def build_stations(w, sg):
    for bi, label in sg["stn"].items():
        BL.build_station(w, SK.station_samples(sg, bi), sg["ys"], bi, True, label=label,
                         grounds=sg["ground"], access=False,
                         stacked=sg.get("stacked", {}).get(bi))


def lay_rails(w, sg):
    """Lay rails as cli.main does; returns [(track number, blocks)]."""
    out = []
    for k, (i0, i1, off_at, y_at) in enumerate(SK.strands(sg)):
        pts = []
        for i in range(i0, i1 + 1):
            x, z, ux, uz, _ = sg["samples"][i]
            o = off_at(i)
            pts.append((x - uz * o, y_at(i) + 1, z + ux * o))
        blocks = rails.rail_path(pts)
        for bx, by, bz, shape, pw in blocks:
            w.set(bx, by, bz, rails.block_string(shape, pw))
        out.append((k, blocks))
    return out


def rails_supported(w, blocks, cells):
    """Return the number of hanging rails. To land diagonal rails on straight
    runs, rails.py shifts height changes a few cells forward or back, and those
    shifted cells sit one block above the track bed. The cli adds a support
    under every rail, so the descent allows one hanging rail per block of
    drop; more means the box structure was not fully dug out or paved."""
    bad = 0
    for bx, by, bz, _, _ in blocks:
        below = w.get(bx, by - 1, bz)
        if below == BL.AIR or (bx, by - 1, bz) in cells:
            bad += 1
    return bad


def reach(w, start, floor_ok=None):
    bounds = None
    dist, _ = walk.flood(w.get, [start], bounds=bounds, floor_ok=floor_ok)
    return dist


def yellow_levels(w, dist):
    """Return the heights (standing surface) of the reachable warning strips."""
    lv = set()
    for (x, y, z), blk in w.blocks.items():
        if blk == BL.YELLOW and (x, y + 1, z) in dist:
            lv.add(y + 1)
    return sorted(lv)


def col(samples, i, off):
    x, z, ux, uz, _ = samples[i]
    return int(round(x - uz * off)), int(round(z + ux * off))


# ======================================================================
print("Stacked side-platform station (Fuzhong)")
A, (ia,) = make_seg("A", [(-700.0, 0.0), (700.0, 0.0)], [0])
lay = SK.plan_side(A, ia, +1, "left")            # The upper level runs toward +x; the platform is on the left (-z).
finish(A)
n = len(A["samples"])
chk("Platform on the -off side (left of +x), track against the +off side wall",
    lay["plat"][0] == -(AL.BOX_HALF - 2) and lay["tracks"][0] == AL.STN_TRACK_OFF)
chk("Upper level is the +off track (right-hand running)",
    int(A["y_side"][1][ia]) == Y and int(A["y_side"][-1][ia]) == Y - SK.LEVEL_H)
chk("Both tracks converge to one lateral offset in the station",
    A["off_side"][1][ia] == A["off_side"][-1][ia] == lay["tracks"][0])
lo, hi = SK.station_range(n, ia)
ext = int(round(SK.SPLIT_M / AL.STEP))
chk("Between stations the tracks stay at ±3 with one rail top",
    A["off_side"][1][lo - ext - 10] == 3 and A["off_side"][-1][lo - ext - 10] == -3
    and int(A["y_side"][-1][lo - ext - 10]) == Y)
ramp = A["y_side"][-1][lo - ext:lo]
chk("Descent drops at most one block per step, LEVEL_H in total",
    int(ramp[0]) == Y and int(ramp[-1]) == Y - SK.LEVEL_H
    and max(abs(int(ramp[k + 1]) - int(ramp[k])) for k in range(len(ramp) - 1)) <= 1)

w = DictSink()
build_sections(w, A)
build_stations(w, A)
ym = Y + AL.LEVEL_DY["tunnel"]                    # Concourse standing surface.
start = (*col(A["samples"], ia, 0), )
start = (start[0], ym, start[1])
chk("Concourse is standable", walk.standable(w.get, *start))
dist = reach(w, start)
lv = yellow_levels(w, dist)
chk(f"Warning strips on both platform levels reachable from the concourse ({lv})", lv == [Y + 2 - SK.LEVEL_H, Y + 2])
# The lower platform surface itself: standing surface Y-6, with the warning strip by the
# platform screen doors.
yl = Y - SK.LEVEL_H
cx, cz = col(A["samples"], ia, lay["yellow"][0])
chk("Lower warning strip block at platform surface height", w.get(cx, yl + 1, cz) == BL.YELLOW)
cx, cz = col(A["samples"], ia, lay["tracks"][0])
chk("Lower track bed at rail top -8", w.get(cx, yl, cz) == BL.DECK and w.get(cx, Y, cz) == BL.DECK)
chk("Floor slab between the two levels", w.get(cx, Y - 2, cz) == BL.LINING)
strands = lay_rails(w, A)
chk("Two main tracks", len(strands) == 2)
for k, blocks in strands:
    errs = rails.check_rails(blocks)
    chk(f"Track {k} rails pass the general checker ({len(blocks)} cells)", not errs)
    if errs:
        print("     ", errs[:3])
    nbad = rails_supported(w, blocks, set())
    allow = 0 if k == 0 else 2 * SK.LEVEL_H          # The descending track: 8 blocks down at each end.
    chk(f"Track {k} has no more hanging rails than blocks of height change ({nbad} hanging, limit {allow})", nbad <= allow)
ys_low = [b[1] for k, blocks in strands for b in blocks if k == 1]
chk("Rails of the descending track really are 8 blocks lower", min(ys_low) == Y + 1 - SK.LEVEL_H)
occ = EX.index_segments([A])
cx, cz = col(A["samples"], ia, 0)
chk("Occupancy covers the lower level", occ.blocked(cx, cz, Y - 9, Y - 8))
fl = int(round(SK.FLARE_M / AL.STEP))
cx, cz = col(A["samples"], lo - fl - 4, -3)         # End of the descent, nearly 8 blocks down.
chk("Occupancy covers the descent", occ.blocked(cx, cz, Y - 8, Y - 7))

# ======================================================================
print("Shared stacked island station (Ximen)")
P, (ip,) = make_seg("P", [(-700.0, 0.0), (700.0, 0.0)], [0])
Q, (iq,) = make_seg("Q", [(-700.0, 17.0), (700.0, 17.0)], [0])
lay, m, side, prng = SK.plan_shared(P, ip, +1, Q, iq, +1)
finish(P); finish(Q)
chk("Partner on the +off side, midline offset 8", side == 1 and m == 8)
chk("Partner's station removed, no cross-sections within the station box",
    iq not in Q["stn"] and prng[0] < iq < prng[1] and iq in Q["nobuild"])
fr = SK.station_samples(P, ip)
chk("Frame lies on the midline of the two lines", abs(fr[ip][1] - 8.0) < 1e-9)
chk("Primary's two tracks converge to its own centreline (frame -8)", P["off_side"][1][ip] == 0.0)
chk("Partner's two tracks converge to frame +8 (-1 in its own coordinates)",
    abs(Q["off_side"][1][iq] - (-1.0)) < 1e-6)
chk("Both lines pinned to the same rail top", int(Q["ys"][iq]) == int(P["ys"][ip]) == Y)

w = DictSink()
build_sections(w, P)
build_sections(w, Q)
build_stations(w, P)
start = (int(round(fr[ip][0])), ym, int(round(fr[ip][1])))
chk("Concourse (frame midline) is standable", walk.standable(w.get, *start))
dist = reach(w, start)
lv = yellow_levels(w, dist)
chk(f"Island platforms on both levels reachable from the concourse ({lv})", lv == [Y + 2 - SK.LEVEL_H, Y + 2])
n_y = {}
for (x, y, z), blk in w.blocks.items():
    if blk == BL.YELLOW and (x, y + 1, z) in dist:
        n_y[(y + 1, z)] = n_y.get((y + 1, z), 0) + 1
chk("Warning strips on both sides of each level reachable (four)", len(n_y) == 4)
all_blocks = []
for sg in (P, Q):
    for k, blocks in lay_rails(w, sg):
        errs = rails.check_rails(blocks)
        chk(f"{sg['ref']} track {k} rails pass the general checker", not errs)
        if errs:
            print("     ", errs[:3])
        all_blocks.append((sg["ref"], k, blocks))
for ref, k, blocks in all_blocks:
    nbad = rails_supported(w, blocks, set())
    allow = 0 if k == 0 else 2 * SK.LEVEL_H
    chk(f"{ref} track {k} has no more hanging rails than blocks of height change ({nbad} hanging, limit {allow})", nbad <= allow)
# In the station, P's rails are at z=0 (frame -8) and Q's at z=16 (frame +8), two levels each.
def rails_at(blocks, x):
    return sorted({(b[1], b[2]) for b in blocks if b[0] == x})
px = int(round(fr[ip][0]))
zs = {ref: set() for ref, _, _ in all_blocks}
for ref, k, blocks in all_blocks:
    for y, z in rails_at(blocks, px):
        zs[ref].add((y, z))
chk(f"P's two tracks stacked at z=0 in the station ({sorted(zs['P'])})",
    zs["P"] == {(Y + 1, 0), (Y + 1 - SK.LEVEL_H, 0)})
chk(f"Q's two tracks stacked at z=16 in the station ({sorted(zs['Q'])})",
    zs["Q"] == {(Y + 1, 16), (Y + 1 - SK.LEVEL_H, 16)})
occ = EX.index_segments([P, Q])
chk("Occupancy follows the frame: lower level at midline z=8 is occupied", occ.blocked(px, 8, Y - 9, Y - 8))
chk("Occupancy: cell just outside the frame side wall is free", not occ.blocked(px, 8 + 14, Y, Y + 2))

# ======================================================================
print("Pocket track")
R, (ir0, ir1) = make_seg("R", [(-900.0, 0.0), (900.0, 0.0)], [-400, 400])
finish(R)
res = SK.plan_pocket(R, ir0, ir1, None, 150)
chk("Fits between the two stations", res is not None)
i0, i1 = res
R["hw"] = [AL.half_width(t) for t in R["toff"]]
mid = (i0 + i1) // 2
chk("Main tracks flare out to ±6 along the storage track", R["toff"][mid] == 6.0)
chk("Third track is >= 150 m long", (i1 - i0) * AL.STEP >= 150)
trs = SK.tracks_at(R, mid)
chk(f"Three tracks along the storage track ({sorted(o for o, _ in trs)})", sorted(o for o, _ in trs) == [-6.0, 0.0, 6.0])
chk("Station flare untouched by the pocket track", R["toff"][ir0] == 8.0 and R["toff"][ir0 + int(80 / AL.STEP)] == 3.0)
w = DictSink()
build_sections(w, R)
build_stations(w, R)
cx, cz = col(R["samples"], mid, 0)
chk("Storage track centreline is track bed, not a dividing wall", w.get(cx, Y, cz) == BL.DECK and w.get(cx, Y + 1, cz) == BL.AIR)
cx, cz = col(R["samples"], mid, 3)
chk("Low dividing wall between the main and storage tracks", w.get(cx, Y + 1, cz) == BL.WALL)
cx, cz = col(R["samples"], mid, 9)
chk("Side walls at ±9", w.get(cx, Y + 2, cz) == BL.LINING)
strands = lay_rails(w, R)
chk("Three tracks", len(strands) == 3)
for k, blocks in strands:
    errs = rails.check_rails(blocks)
    chk(f"Track {k} rails pass the general checker ({len(blocks)} cells)", not errs)
    if errs:
        print("     ", errs[:3])
    nbad = rails_supported(w, blocks, set())
    chk(f"Every rail of track {k} is supported ({nbad} hanging)", nbad == 0)
# The three tracks never share a cell.
cells = {}
for k, blocks in strands:
    for b in blocks:
        cells.setdefault((b[0], b[2]), set()).add(k)
chk("No two tracks claim the same cell", all(len(v) == 1 for v in cells.values()))

print()
print("Centreline distance guard for shared station boxes")
for sep, why in ((40.0, "too far"), (6.0, "too close")):
    A, (ia,) = make_seg("A", [(-700.0, 0.0), (700.0, 0.0)], [0])
    B, (ib,) = make_seg("B", [(-700.0, sep), (700.0, sep)], [0])
    before = (int(A["ys"][ia]), dict(B["stn"]))
    chk(f"Lines {sep:.0f} m apart ({why}): no shared station box",
        SK.plan_shared(A, ia, +1, B, ib, +1) is None)
    chk(f"At {sep:.0f} m apart plan_shared changes nothing",
        (int(A["ys"][ia]), dict(B["stn"])) == before
        and "frames" not in A and "nobuild" not in B)

print()
print("Real data tables (STACKED / POCKETS)")
import json
import math
from mrt import config

for (name, ref), spec in SK.STACKED.items():
    if spec["kind"] != "shared":
        continue
    if "partner" in spec:
        chk(f"{name} {ref}: partner {spec['partner']} is registered too",
            (name, spec["partner"]) in SK.STACKED)
    else:
        chk(f"{name} {ref} is the partner of some entry",
            any(k[0] == name and v.get("partner") == ref
                for k, v in SK.STACKED.items()))
chk("Each shared station box has exactly one primary line",
    all(sum(1 for k, v in SK.STACKED.items()
            if k[0] == n and "partner" in v) == 1
        for n in {k[0] for k, v in SK.STACKED.items() if v["kind"] == "shared"}))

if os.path.exists(config.SIDINGS_JSON) and os.path.exists(config.MC_LINES_JSON):
    ways = {w["id"]: w for w in
            json.load(open(config.SIDINGS_JSON, encoding="utf-8"))["items"]}
    lines = json.load(open(config.MC_LINES_JSON, encoding="utf-8"))

    def d_seg(pt, a, b):
        dx, dz = b[0] - a[0], b[1] - a[1]
        L = dx * dx + dz * dz
        t = 0.0 if L == 0 else max(0.0, min(1.0,
            ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dz) / L))
        return math.hypot(pt[0] - (a[0] + t * dx), pt[1] - (a[1] + t * dz))

    for pk in SK.POCKETS:
        way = ways.get(pk["osm"])
        chk(f"{pk['a']}–{pk['b']}: way {pk['osm']} is in data/sidings.json",
            way is not None)
        if way is None:
            continue
        tags = way["tags"]
        chk(f"{pk['a']}–{pk['b']} is underground (sec_multi only digs tunnel cross-sections)",
            tags.get("tunnel") == "yes" or str(tags.get("layer", "0")).startswith("-"))
        # The storage track must run close to its own line (between the main
        # tracks, less than one track from the centerline). Compare against every
        # OSM variant, not only those the generator chose: the two directions are
        # two relations up to 19 m apart, and the storage track is drawn along one
        # of them (at Daan, along the other one).
        segs = [(p[i], p[i + 1]) for v in lines[pk["ref"]]
                for p in [v["points"]] for i in range(len(p) - 1)]
        ds = [min(d_seg(q, a, b) for a, b in segs) for q in way["mc"]]
        chk(f"{pk['a']}–{pk['b']}: way runs along line {pk['ref']}"
            f" (perpendicular distance {min(ds):.0f}–{max(ds):.0f} m)", max(ds) <= 12.0)

print("\n" + ("All passed" if ok else "Some tests failed"))
sys.exit(0 if ok else 1)
