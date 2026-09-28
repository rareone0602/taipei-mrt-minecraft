#!/usr/bin/env python3
"""Network rules of the ride system (domain/network.py).

Builds the station boxes of a synthetic straight network for real (DictSink),
then checks the berths:
  · Direction of travel: trains run on the right, so a train heading +u stops
    at the + side platform screen doors; next station and terminus
  · Berths: the player can stand there (the rules in domain/walk), faces the
    platform screen doors, and the sign is in the row of doors
  · Rides: riding from 甲 to 乙, the player alights in front of the sign for
    the onward journey to 丙; the arrival side of a terminus has no next
    station
  · Branches: a junction station gains two directions on the same side, and
    its signs alternate between them
  · Elevated side platform station: the platform is outside the doors
  · Shared stacked island station (like Ximen): the level and door side of
    each line follow upper_toward

Usage: ./.venv/bin/python tests/test_network.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.application import build_line as BL
from mrt.domain import alignment as AL
from mrt.domain import network as NW
from mrt.domain import stacked as SK
from mrt.domain import walk
from mrt.ports.block_sink import DictSink

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


G = 66


def make_seg(ref, pts, stations, y):
    """stations = [(x or (x, z), code, name, English name)]; each station falls
    on the nearest sample point."""
    samples = AL.resample(pts, ["tunnel"] * len(pts), AL.STEP)
    n = len(samples)
    stn = {}
    for pos, code, name, en in stations:
        px, pz = pos if isinstance(pos, tuple) else (pos, samples[0][1])
        i = min(range(n), key=lambda k: (samples[k][0] - px) ** 2 + (samples[k][1] - pz) ** 2)
        stn[i] = (code, name, en)
    return dict(ref=ref, samples=samples, ys=np.full(n, y), ground=np.full(n, G),
                stn=stn, stn_seq=dict(stn))


def build(sg):
    """Builds every station on this segment the way cli does and returns the
    DictSink."""
    w = DictSink()
    for i, (full, name, en) in sg["stn"].items():
        under = AL.structure_for_ground(int(sg["ys"][i]), int(sg["ground"][i])) == "tunnel"
        BL.build_station(w, SK.station_samples(sg, i), sg["ys"], i, under,
                         label=(full, name, en), grounds=sg["ground"], access=False,
                         stacked=sg.get("stacked", {}).get(i))
    return w


def check_slots(w, berths, tag):
    """Every berth is standable, its sign is in the row of platform screen doors
    (where glass or a station-name sign was), and the player faces the sign."""
    n = bad = 0
    for b in berths:
        for s in b.slots:
            n += 1
            sx, sy, sz = s.sign
            tx, ty, tz = s.stand
            here = walk.standable(w.get, tx, ty, tz)
            psd = w.get(sx, sy, sz)
            fx, fz = sx - tx, sz - tz
            facing = abs(NW.yaw_of(fx, fz) - s.yaw) < 1.0 or abs(abs(NW.yaw_of(fx, fz) - s.yaw) - 360) < 1.0
            if not (here and ("pane" in psd or "sign" in psd) and facing):
                bad += 1
                print(f"      {b} {s}: standable={here} door row={psd} facing={facing}")
    chk(f"{tag}: all {n} berths are standable and face the sign in the platform screen doors",
        n > 0 and bad == 0)


# ---------------------------------------------------------------- Straight underground line
print("Straight underground line: 甲–乙–丙, island platforms")
line = make_seg("T", [(0, 0), (3000, 0)],
                [(500, "T01", "甲", "Jia"), (1500, "T02", "乙", "Yi"), (2500, "T03", "丙", "Bing")], 40)
segs = [line]
net, berths = NW.plan_berths(segs)
yi = net[("T", "乙")]
chk("乙 has two directions: towards 甲 at −u, towards 丙 at +u",
    set(yi.dirs) == {"甲", "丙"} and yi.dirs["甲"].d == -1 and yi.dirs["丙"].d == 1)
chk("The terminus towards 丙 is 丙, and towards 甲 is 甲",
    yi.dirs["丙"].terminals == ["丙"] and yi.dirs["甲"].terminals == ["甲"])
bidx = NW.berth_index(berths)
b = bidx[("T", "乙", 1)]
chk("Trains run on the right: a train heading +u stops at the + side doors (offset +6); "
    "the player stands at +4",
    b.psd == 6 and all(s.stand[2] == 4 and s.sign[2] == 6 for s in b.slots))
chk("The player faces the platform screen doors (facing +z = south, yaw 0)",
    all(abs(s.yaw) < 0.01 for s in b.slots))
chk("Three signs per side, all towards 丙, alternating Chinese and English",
    [s.dest.next for s in b.slots] == ["丙"] * 3 and [s.lang for s in b.slots] == ["zh", "en", "zh"])
check_slots(build(line), berths, "Island platform station")
slot = NW.arrival(net, bidx, "T", "甲", "乙")
chk("Riding from 甲 to 乙: the player alights in front of the sign onward to 丙",
    slot is not None and slot.dest.next == "丙")
end = bidx[("T", "丙", 1)]
chk("丙 has no next station on its + side: the arrival-side signs are terminus signs",
    end.dests == [] and all(s.dest is None for s in end.slots))
slot = NW.arrival(net, bidx, "T", "乙", "丙")
chk("Riding from 乙 to 丙: the player alights on the arrival side of the terminus",
    slot is not None and slot.dest is None and slot in end.slots)
chk("4 rides in all (甲乙, 乙甲, 乙丙, 丙乙)", len(NW.rides(net, berths)) == 4)
chk("Going to 丙: the player lands on the side with a next station (towards 乙)",
    NW.home_slot(bidx, net[("T", "丙")]).dest.next == "乙")
chk("Function paths use lowercase station codes",
    NW.ride_fn("T02", "T03") == "ride/t02_t03" and NW.go_fn("G03A") == "go/g03a")

# ---------------------------------------------------------------- Skewed alignments
print("\nSkewed alignments: island platform stations at 15°, 30°, 45° and 60°")
for deg in (15, 30, 45, 60):
    ux, uz = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    diag = make_seg("D", [(0, 0), (3000 * ux, 3000 * uz)],
                    [((500 * ux, 500 * uz), "D01", "子", "Zi"), ((1500 * ux, 1500 * uz), "D02", "丑", "Chou"),
                     ((2500 * ux, 2500 * uz), "D03", "寅", "Yin")], 40)
    net, berths = NW.plan_berths([diag])
    far = [max(abs(s.sign[0] - s.stand[0]), abs(s.sign[2] - s.stand[2])) for b in berths for s in b.slots]
    # Offsets 6 and 4 used to be rounded separately. On a skewed alignment they
    # could round to adjacent blocks, and the player stood against the sign
    # (Zhongxiao Xinsheng, Ankang and Danfeng read back that way from the
    # full-network save).
    chk(f"{deg}°: every sign is at Chebyshev distance {NW.STAND_IN} from its berth "
        f"({sorted(set(far))})",
        set(far) == {NW.STAND_IN})
    check_slots(build(diag), berths, f"{deg}° island platform station")

# ---------------------------------------------------------------- Branch
print("\nBranch: a line branches north-east from 乙 to 丁")
k = 1 / math.sqrt(2)
branch = make_seg("T", [(1500, 0), (1500 + 700 * k, -700 * k)],
                  [((1500, 0), "T02", "乙", "Yi"), ((1500 + 600 * k, -600 * k), "T02A", "丁", "Ding")], 40)
del branch["stn"][min(branch["stn"])]        # 乙 is on the trunk; deduplication drops it here.
net, berths = NW.plan_berths([line, branch])
bidx = NW.berth_index(berths)
yi = net[("T", "乙")]
chk("乙 gains a direction towards 丁, on the same side as towards 丙",
    "丁" in yi.dirs and yi.dirs["丁"].d == yi.dirs["丙"].d == 1)
b = bidx[("T", "乙", 1)]
chk("The three signs on that side alternate between 丙 and 丁",
    [s.dest.next for s in b.slots] == ["丙", "丁", "丙"])
chk("丁's station box is on the branch (station code T02A)",
    net[("T", "丁")].box is not None and net[("T", "丁")].code == "T02A")
slot = NW.arrival(net, bidx, "T", "丁", "乙")
chk("Riding from 丁 back to 乙: the player alights in front of the sign towards 甲",
    slot is not None and slot.dest.next == "甲")

# ---------------------------------------------------------------- Elevated side platforms
print("\nElevated side platform station: rail top 20 m above the ground")
sky = make_seg("S", [(0, 0), (2000, 0)],
               [(500, "S01", "戊", "Wu"), (1500, "S02", "己", "Ji")], G + 20)
net, berths = NW.plan_berths([sky])
b = NW.berth_index(berths)[("S", "戊", 1)]
chk("Side platforms: doors at ±5, the platform outside them, the player at ±7",
    b.psd == 5 and b.inward == 1 and all(s.stand[2] == 7 for s in b.slots))
check_slots(build(sky), berths, "Side platform station")

# ---------------------------------------------------------------- Shared stacked station
print("\nShared stacked island station (like Ximen): Bannan Line at z=0, "
      "Songshan-Xindian Line at z=17")
bl = make_seg("BL", [(0, 0), (3000, 0)],
              [(500, "BL10", "龍山寺", "Longshan Temple"), (1500, "BL11", "西門", "Ximen"),
               (2500, "BL12", "台北車站", "Taipei Main Station")], 48)
gl = make_seg("G", [(0, 17), (3000, 17)],
              [((500, 17), "G11", "小南門", "Xiaonanmen"), ((1500, 17), "G12", "西門", "Ximen"),
               ((2500, 17), "G13", "北門", "Beimen")], 48)
bi = next(i for i, v in bl["stn"].items() if v[1] == "西門")
pbi = next(i for i, v in gl["stn"].items() if v[1] == "西門")
j_to = next(i for i, v in bl["stn"].items() if v[1] == "台北車站")
pj_to = next(i for i, v in gl["stn"].items() if v[1] == "北門")
r = SK.plan_shared(bl, bi, SK.direction_sign(bi, j_to), gl, pbi, SK.direction_sign(pbi, pj_to))
chk("plan_shared succeeds", r is not None)
net, berths = NW.plan_berths([bl, gl])
bidx = NW.berth_index(berths)
up_bl, dn_bl = bidx[("BL", "西門", 1)], bidx[("BL", "西門", -1)]
up_g, dn_g = bidx[("G", "西門", 1)], bidx[("G", "西門", -1)]
chk("Bannan Line: towards Taipei Main Station on the upper level, towards Longshan Temple "
    "on the lower (upper_toward=台北車站)",
    up_bl.dy0 == 0 and dn_bl.dy0 == -SK.LEVEL_H)
chk("Songshan-Xindian Line: towards Beimen on the upper level, towards Xiaonanmen "
    "on the lower (upper_toward=北門)",
    up_g.dy0 == 0 and dn_g.dy0 == -SK.LEVEL_H)
chk("The two lines flank the island: Bannan Line at −6, Songshan-Xindian Line at +6 "
    "(partner at +z)",
    up_bl.psd == dn_bl.psd == -6 and up_g.psd == dn_g.psd == 6)
chk("The Songshan-Xindian Line stops in the station box the Bannan Line builds",
    net[("G", "西門")].box is net[("BL", "西門")].box)
w = DictSink()
for sg in (bl, gl):
    for i, (full, name, en) in sg["stn"].items():
        BL.build_station(w, SK.station_samples(sg, i), sg["ys"], i, True, label=(full, name, en),
                         grounds=sg["ground"], access=False, stacked=sg.get("stacked", {}).get(i))
check_slots(w, [up_bl, dn_bl, up_g, dn_g], "Both levels of the stacked station")

print("\n" + ("All tests passed" if ok else "Some tests failed"))
sys.exit(0 if ok else 1)
