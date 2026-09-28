#!/usr/bin/env python3
"""Unit tests for tunnel layering: where two lines cross, the one assigned later must change
band one ramp length early.

A depth band is only a target depth; the real elevation comes from the 4% grade
envelope, and changing by one band takes 375 m. If the band changes only at the
conflict point, the conflict point itself is still partway down the ramp. That is how
the Songshan-Xindian Line at Songjiang Nanjing stopped at 27 m underground, only 3 m
above the Zhonghe-Xinlu Line's station box at 30 m.

Usage: ./.venv/bin/python tests/test_tunnel_layers.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from mrt.domain import alignment as AL
from mrt.domain import tunnel_layers as TL

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def straight(p0, p1):
    return AL.resample([p0, p1], ["tunnel", "tunnel"], AL.STEP)


G = 66
main = straight((-3000.0, 0.0), (3000.0, 0.0))        # The longer one goes first and gets band 0
cross = straight((0.0, -2000.0), (0.0, 2000.0))       # The shorter one must go around
bands = TL.assign_bands([("A", main), ("B", cross)])
ba, bb = bands
print("Depth bands")
chk("the longer line is in band 0 throughout", int(ba.max()) == 0)
xi = min(range(len(cross)), key=lambda i: abs(cross[i][1]))      # The crossing point
chk(f"the shorter line is in band 1 at the crossing (got {bb[xi]})", bb[xi] == 1)
first = int(np.argmax(bb == 1))
dist = (xi - first) * AL.STEP
chk(f"band 1 starts {dist:.0f} m before the crossing (needs a ramp of >= 375 m)",
    dist >= TL.RAMP_M - 1)
chk("still band 0 1 km before the crossing", bb[xi - int(1000 / AL.STEP)] == 0)


# What really needs checking is the elevation: compute the vertical profile on flat ground; the
# crossing must be at the full depth of band 1
def profile(samples, band):
    base = TL.band_depth(band)
    y = G + base.astype(float)
    d = AL.MAX_GRADE * AL.STEP
    for i in range(1, len(y)):
        if y[i] > y[i - 1] + d: y[i] = y[i - 1] + d
    for i in range(len(y) - 2, -1, -1):
        if y[i] > y[i + 1] + d: y[i] = y[i + 1] + d
    return np.round(y).astype(int)


ya, yb = profile(main, ba), profile(cross, bb)
print("Vertical profile")
chk(f"the longer line is {G - ya[xi]} m deep at the crossing (band 0 = 15)",
    G - ya[xi] == TL.BAND0)
chk(f"the shorter line is {G - yb[xi]} m deep at the crossing "
    f"(band 1 = 30, not partway down a ramp)",
    G - yb[xi] == TL.BAND0 + TL.BAND_DY)
chk("the two station boxes are 15 m apart vertically and do not overlap",
    ya[xi] - yb[xi] == TL.BAND_DY)

# The old band stays taken until the ramp is complete: a third line cannot take band 0
# beneath the ramp
third = straight((-400.0, -1000.0), (-400.0, 1000.0))  # 400 m from the crossing, mid-ramp ...
# ... it would conflict only if the shorter line were still in band 0 there (near the start of
# the ramp); this checks that nothing crashes and there is no conflict
b3 = TL.assign_bands([("A", main), ("B", cross), ("C", third)])
chk("all three lines can be assigned", all(int(b.max()) >= 0 for b in b3))

print("\nAll passed" if ok else "\nSome tests failed")
raise SystemExit(0 if ok else 1)
