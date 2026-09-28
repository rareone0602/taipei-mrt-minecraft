#!/usr/bin/env python3
"""Unit tests for the alignment.

These used to be untestable: the alignment formulas were tied to the code that puts
blocks into the world, in the same build_line.py, so checking a vertical profile meant
generating a world save first. Moved into domain, they are pure functions in and out,
with no need to touch Minecraft.

Usage: ./.venv/bin/python tests/test_alignment.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt.domain import alignment as AL

ok = True


def chk(name, cond):
    global ok
    print(("  ok   " if cond else "  FAIL ") + name)
    ok = ok and cond


def line(n, step=1.0):
    return [(i * step, 0.0) for i in range(n)]


print("Sampling")
pts = line(11, 10.0)                       # A 100 m straight line
s = AL.resample(pts, ["ground"] * 11, AL.STEP)
chk(f"100 m / step {AL.STEP} -> {len(s)} points", abs(len(s) - 200) <= 2)
d = [math.dist(s[i][:2], s[i + 1][:2]) for i in range(len(s) - 1)]
chk(f"even spacing (max {max(d):.3f}, min {min(d):.3f})",
    max(d) - min(d) < 1e-6 and abs(max(d) - AL.STEP) < 1e-6)
chk("direction vectors are unit vectors",
    all(abs(math.hypot(p[2], p[3]) - 1) < 1e-9 for p in s))
chk("heading along +X -> ux=1", abs(s[len(s) // 2][2] - 1.0) < 1e-6)

print("Vertical profile")
ys = AL.vertical_profile(["ground"] * 400)
chk("all at grade -> ground +1", set(ys) == {AL.GROUND + AL.PROFILE["ground"]})

# The viaduct segments must be long enough: dropping from y77 to y44 is 33 m, which at a
# 4% grade needs an 825 m approach ramp. Anything shorter is pulled down entirely by the
# lower envelope (which is the intended behavior).
SEG = int(1500 / AL.STEP)        # 1500 m per segment
kinds = ["bridge"] * SEG + ["tunnel"] * SEG + ["bridge"] * SEG
ys = AL.vertical_profile(kinds)
# The grade must be measured over a distance. ys is already rounded to integers, so the
# smallest nonzero difference between adjacent samples is 1 block / 0.5 m = 200%, an
# artifact of rounding rather than a real grade.
W = int(100 / AL.STEP)           # A 100 m window
grades = [abs(ys[i + W] - ys[i]) / 100.0 for i in range(len(ys) - W)]
chk(f"maximum grade over a 100 m window {max(grades):.4f} <= {AL.MAX_GRADE}",
    max(grades) <= AL.MAX_GRADE + 0.001)
chk("the tunnel segment really drops below the ground", min(ys) < AL.GROUND)
chk(f"the viaduct segment rises to y={max(ys)} = ground {AL.PROFILE['bridge']:+d}",
    max(ys) == AL.GROUND + AL.PROFILE["bridge"])
mid = len(ys) // 2
chk(f"mid-tunnel y={ys[mid]} = ground {AL.PROFILE['tunnel']:+d}",
    ys[mid] == AL.GROUND + AL.PROFILE["tunnel"])
# Around a portal there should be a continuously descending approach ramp, not a vertical cliff
step_down = max(abs(ys[i + 1] - ys[i]) for i in range(len(ys) - 1))
chk(f"largest height step between adjacent samples: {step_down} block (not a cliff)",
    step_down <= 1)

print("Structure type follows elevation, not tags")
chk("rail top 6 above the ground -> viaduct",
    AL.structure_for_ground(AL.GROUND + 6, AL.GROUND) == "viaduct")
chk("rail top close to the ground -> at grade",
    AL.structure_for_ground(AL.GROUND + 1, AL.GROUND) == "surface")
chk("rail top 2 below the ground -> tunnel",
    AL.structure_for_ground(AL.GROUND - 2, AL.GROUND) == "tunnel")
chk("tagged bridge but already below ground -> still a tunnel",
    AL.structure_for_ground(AL.GROUND - 10, AL.GROUND) == "tunnel")

print("Track offsets")
n = 600
samples = [(i * AL.STEP, 0.0, 1.0, 0.0, "tunnel") for i in range(n)]
ys = [AL.GROUND - 20] * n
toff = AL.track_offsets(samples, ys, [AL.GROUND] * n, [n // 2])
chk(f"spreads to ±{AL.STN_TRACK_OFF} at the station centre", toff[n // 2] == AL.STN_TRACK_OFF)
chk(f"stays at ±{AL.TUN_TRACK_OFF} between stations", toff[0] == AL.TUN_TRACK_OFF)
chk("the transition is monotonic (no jumps)",
    all(toff[i] >= toff[i - 1] - 1e-9 for i in range(1, n // 2)))
jump = max(abs(toff[i + 1] - toff[i]) for i in range(n - 1))
chk(f"largest offset change between adjacent points: {jump:.3f} m (the track does not break)",
    jump < 0.2)

chk("half-width = offset + 2", AL.half_width(8) == 10)
chk("half-width has a minimum of 5", AL.half_width(1) == 5)

print("Reversals")
pts = [(0, 0), (100, 0), (200, 0), (150, 0)]     # Runs to the end, then doubles back 50 m
out, _ = AL.drop_reversal(pts, ["ground"] * 4)
chk(f"the reversal is cut off ({len(pts)} -> {len(out)} points)", len(out) < len(pts))
chk("the longer half is kept", out[-1][0] == 200)
straight = line(5, 50.0)
out, _ = AL.drop_reversal(straight, ["ground"] * 5)
chk("a straight line is not cut by mistake", len(out) == len(straight))

print("Route variants")
up = {"points": [[i * 10.0, 0.0] for i in range(60)]}
down = {"points": [[i * 10.0, 3.0] for i in reversed(range(60))]}   # The same line, reversed
# The branch must leave the middle of the trunk at a right angle and differ in length. If it
# ran straight on in the trunk's direction with the same length, the endpoint matching in
# _same_corridor (600 m tolerance) would mistake it for the other direction.
branch = {"points": [[300.0, i * 10.0] for i in range(100)]}
sel = AL.select_variants([up, down])
chk(f"the two directions collapse into one (2 -> {len(sel)})", len(sel) == 1)
sel = AL.select_variants([up, down, branch])
chk(f"the branch is kept (3 -> {len(sel)})", len(sel) == 2)

print("Degenerate input")
chk("sampling a single point does not crash",
    AL.resample([(0.0, 0.0)], ["ground"], AL.STEP) == [])
chk("an empty vertical profile does not crash", AL.vertical_profile([]) == [])
chk("no variants returns an empty list", AL.select_variants([]) == [])

print("\nAll passed" if ok else "\nSome tests failed")
raise SystemExit(0 if ok else 1)
